from __future__ import annotations

import logging
import socket
from pathlib import Path

import pytest

from backend.application.workflow_service import WorkflowService
from backend.db.repository import Repository
from backend.domain.models import TaskStatus
from backend.infrastructure.security import RedactingFilter, hash_password, validate_https_url
from backend.infrastructure.storage import ArtifactStore, UnsafePathError
from tests.fakes import FastRenderer


def test_checkpoint_recovery_after_process_restart(test_settings, monkeypatch) -> None:
    import backend.application.workflow_service as workflow_service_module

    original_builder = workflow_service_module.build_adapters

    def build_test_adapters(settings, store):
        llm, tts, materials, _ = original_builder(settings, store)
        return llm, tts, materials, FastRenderer()

    monkeypatch.setattr(workflow_service_module, "build_adapters", build_test_adapters)
    test_settings.ensure_directories()
    repository = Repository(test_settings.database_path)
    repository.initialize()
    user = repository.create_user("resume@example.com", hash_password("a-secure-password"))
    task, _ = repository.create_task(
        user_id=user["id"],
        topic="检查点恢复",
        target_duration_seconds=10,
        aspect_ratio="16:9",
        voice_id="mimo_default",
        provider_mode="fake",
        idempotency_key=None,
        default_bgm_volume=0.2,
    )

    first_service = WorkflowService(test_settings, repository)
    first_service.run_now(task["id"])
    first = repository.get_task(user["id"], task["id"])
    assert first["status"] == TaskStatus.AWAITING_SCRIPT_REVIEW.value
    first_service.close()

    repository.claim_review(
        user_id=user["id"],
        task_id=task["id"],
        kind="script",
        version=1,
        action="approve",
    )
    second_service = WorkflowService(test_settings, repository)
    second_service.run_now(task["id"])
    restored = repository.get_task(user["id"], task["id"])
    assert restored["status"] == TaskStatus.AWAITING_STORYBOARD_REVIEW.value
    assert restored["script_version"] == 1
    second_service.close()


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "media")
    user_id = "48da6f89-4533-43fb-8a78-950cec8213cd"
    task_id = "307ba0f2-5fb1-48b2-a81d-ad50ec4083b4"
    store.task_directory(user_id, task_id)
    with pytest.raises(UnsafePathError):
        store.resolve_registered_path(user_id, task_id, "../outside.mp4")
    with pytest.raises(UnsafePathError):
        store.artifact_path(user_id, task_id, "video", "../../escape.mp4")


def test_ssrf_validation_rejects_protocol_host_and_private_resolution(monkeypatch) -> None:
    with pytest.raises(ValueError):
        validate_https_url("http://videos.pexels.com/test.mp4", {"videos.pexels.com"})
    with pytest.raises(ValueError):
        validate_https_url("https://evil.example/test.mp4", {"videos.pexels.com"})

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(ValueError):
        validate_https_url("https://videos.pexels.com/test.mp4", {"videos.pexels.com"})


def test_log_filter_redacts_credentials() -> None:
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "Authorization=Bearer-secret api_key=provider-secret password=bad",
        (),
        None,
    )
    assert RedactingFilter().filter(record)
    message = record.getMessage()
    assert "Bearer-secret" not in message
    assert "provider-secret" not in message
    assert "password=[REDACTED]" in message
