from __future__ import annotations

import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import ValidationError

from backend.config import Settings
from backend.db.repository import Repository, TaskNotFoundError
from backend.domain.models import TaskStatus
from backend.infrastructure.adapters import ProviderError, build_adapters
from backend.infrastructure.storage import ArtifactStore
from backend.workflow.graph import WorkflowNodes, WorkflowValidationError, build_workflow

LOGGER = logging.getLogger(__name__)
REVIEW_NODES = {"review_script", "review_storyboard", "review_bgm"}


class WorkflowService:
    def __init__(self, settings: Settings, repository: Repository) -> None:
        self.settings = settings
        self.repository = repository
        self.store = ArtifactStore(settings.media_root)
        self.checkpoint_connection = sqlite3.connect(
            settings.checkpoint_path, check_same_thread=False
        )
        self.checkpointer = SqliteSaver(self.checkpoint_connection)
        self.checkpointer.setup()
        llm, tts, materials, renderer = build_adapters(settings, self.store)
        nodes = WorkflowNodes(
            llm=llm,
            tts=tts,
            materials=materials,
            renderer=renderer,
            store=self.store,
            progress=self.repository.set_task_status_internal,
        )
        self.graph = build_workflow(nodes, self.checkpointer)
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="clip-workflow")
        self.running: set[str] = set()
        self.running_lock = threading.Lock()
        self.task_locks: dict[str, threading.Lock] = {}

    def submit(self, task_id: str) -> bool:
        with self.running_lock:
            if task_id in self.running:
                return False
            self.running.add(task_id)
        self.executor.submit(self._run_and_release, task_id)
        return True

    def _run_and_release(self, task_id: str) -> None:
        try:
            self.run_now(task_id)
        finally:
            with self.running_lock:
                self.running.discard(task_id)

    def _current_stage(self, task_id: str, fallback: str) -> str:
        try:
            return str(self.repository.get_task_internal(task_id).get("current_stage") or fallback)
        except TaskNotFoundError:
            return fallback

    def run_now(self, task_id: str) -> dict[str, Any] | None:
        task_lock = self.task_locks.setdefault(task_id, threading.Lock())
        with task_lock:
            try:
                task = self.repository.get_task_internal(task_id)
            except TaskNotFoundError:
                return None
            if task["provider_mode"] != self.settings.provider_mode:
                self.repository.mark_failed(
                    task_id,
                    code="PROVIDER_MODE_CHANGED",
                    message="任务创建时的供应商模式与当前服务配置不一致，请新建任务",
                    retryable=False,
                    failed_stage=task.get("current_stage") or "queued",
                )
                LOGGER.warning(
                    "provider mode mismatch task_id=%s task_mode=%s runtime_mode=%s",
                    task_id,
                    task["provider_mode"],
                    self.settings.provider_mode,
                )
                return None
            config = {"configurable": {"thread_id": task["thread_id"]}}
            snapshot = self.graph.get_state(config)
            try:
                if not snapshot.values:
                    graph_input: dict[str, Any] | Command | None = {
                        "task_id": task["id"],
                        "user_id": task["user_id"],
                        "thread_id": task["thread_id"],
                        "topic": task["topic"],
                        "target_duration_seconds": task["target_duration_seconds"],
                        "aspect_ratio": task["aspect_ratio"],
                        "voice_id": task["voice_id"],
                        "provider_mode": task["provider_mode"],
                        "status": TaskStatus.QUEUED.value,
                        "current_stage": TaskStatus.QUEUED.value,
                        "script_version": 0,
                        "storyboard_version": 0,
                        "preview_version": 0,
                        "review_history": [],
                    }
                elif task.get("pending_command") and set(snapshot.next) & REVIEW_NODES:
                    graph_input = Command(resume=task["pending_command"])
                else:
                    graph_input = None
                result = self.graph.invoke(graph_input, config=config)
                self.repository.sync_task_from_state(task_id, result)
                LOGGER.info(
                    "workflow invocation complete task_id=%s stage=%s",
                    task_id,
                    result.get("current_stage"),
                )
                return result
            except ProviderError as error:
                failed_stage = self._current_stage(task_id, task.get("current_stage") or "unknown")
                self.repository.mark_failed(
                    task_id,
                    code="PROVIDER_UNAVAILABLE" if error.retryable else "PROVIDER_ERROR",
                    message=str(error),
                    retryable=error.retryable,
                    failed_stage=failed_stage,
                )
                LOGGER.warning(
                    "provider failure task_id=%s stage=%s retryable=%s",
                    task_id,
                    failed_stage,
                    error.retryable,
                )
            except (WorkflowValidationError, ValidationError, ValueError) as error:
                failed_stage = self._current_stage(task_id, task.get("current_stage") or "unknown")
                self.repository.mark_failed(
                    task_id,
                    code="WORKFLOW_VALIDATION_FAILED",
                    message="生成产物未通过结构或时间轴校验",
                    retryable=False,
                    failed_stage=failed_stage,
                )
                LOGGER.warning(
                    "workflow validation failure task_id=%s error_type=%s",
                    task_id,
                    type(error).__name__,
                )
            except Exception:
                failed_stage = self._current_stage(task_id, task.get("current_stage") or "unknown")
                self.repository.mark_failed(
                    task_id,
                    code="INTERNAL_ERROR",
                    message="任务处理遇到内部错误，可安全重试",
                    retryable=True,
                    failed_stage=failed_stage,
                )
                LOGGER.exception("workflow internal failure task_id=%s", task_id)
            return None

    def resume_incomplete(self) -> None:
        for task_id in self.repository.list_resumable_task_ids():
            self.submit(task_id)

    def delete_checkpoints(self, thread_id: str) -> None:
        self.checkpointer.delete_thread(thread_id)

    def close(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.checkpoint_connection.close()
