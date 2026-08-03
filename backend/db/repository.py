from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.domain.models import PROGRESS, TaskStatus, UserPreferences


class RepositoryError(Exception):
    """Base repository exception."""


class DuplicateEmailError(RepositoryError):
    pass


class TaskNotFoundError(RepositoryError):
    pass


class StateConflictError(RepositoryError):
    pass


class VersionConflictError(RepositoryError):
    pass


class IdempotencyConflictError(RepositoryError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Repository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.migrations_path = Path(__file__).with_name("migrations")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {
                row["version"]
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for migration in sorted(self.migrations_path.glob("*.sql")):
                if migration.name in applied:
                    continue
                connection.executescript(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (migration.name, utc_now()),
                )
            connection.commit()

    def create_user(self, email: str, password_hash: str) -> dict[str, Any]:
        user_id = str(uuid4())
        created_at = utc_now()
        preferences = UserPreferences()
        try:
            with self.transaction(immediate=True) as connection:
                connection.execute(
                    "INSERT INTO users(id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, email, password_hash, created_at),
                )
                connection.execute(
                    """
                    INSERT INTO user_settings(
                        user_id, default_aspect_ratio, default_duration_seconds,
                        default_bgm_volume, preferred_voice, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        preferences.default_aspect_ratio.value,
                        preferences.default_duration_seconds,
                        preferences.default_bgm_volume,
                        preferences.preferred_voice.value,
                        created_at,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise DuplicateEmailError from error
        return {"id": user_id, "email": email, "created_at": created_at}

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, email, password_hash, created_at FROM users WHERE email = ?", (email,)
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return dict(row) if row else None

    def create_session(
        self, token_hash: str, csrf_hash: str, user_id: str, expires_at: str
    ) -> None:
        with self.transaction(immediate=True) as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (utc_now(),))
            connection.execute(
                """
                INSERT INTO sessions(token_hash, csrf_hash, user_id, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (token_hash, csrf_hash, user_id, expires_at, utc_now()),
            )

    def get_session(self, token_hash: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.token_hash, s.csrf_hash, s.user_id, s.expires_at,
                       u.email, u.created_at AS user_created_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ? AND s.expires_at > ?
                """,
                (token_hash, utc_now()),
            ).fetchone()
        return dict(row) if row else None

    def delete_session(self, token_hash: str) -> None:
        with self.transaction(immediate=True) as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def get_settings(self, user_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT default_aspect_ratio, default_duration_seconds,
                       default_bgm_volume, preferred_voice
                FROM user_settings WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if not row:
            raise RepositoryError("user settings missing")
        return dict(row)

    def update_settings(self, user_id: str, preferences: UserPreferences) -> dict[str, Any]:
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE user_settings
                SET default_aspect_ratio = ?, default_duration_seconds = ?,
                    default_bgm_volume = ?, preferred_voice = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (
                    preferences.default_aspect_ratio.value,
                    preferences.default_duration_seconds,
                    preferences.default_bgm_volume,
                    preferences.preferred_voice.value,
                    utc_now(),
                    user_id,
                ),
            )
        return self.get_settings(user_id)

    @staticmethod
    def fingerprint_request(
        topic: str, duration: int, aspect_ratio: str, voice_id: str, provider_mode: str
    ) -> str:
        raw = json.dumps(
            {
                "topic": topic,
                "target_duration_seconds": duration,
                "aspect_ratio": aspect_ratio,
                "voice_id": voice_id,
                "provider_mode": provider_mode,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def create_task(
        self,
        *,
        user_id: str,
        topic: str,
        target_duration_seconds: int,
        aspect_ratio: str,
        voice_id: str,
        provider_mode: str,
        idempotency_key: str | None,
        default_bgm_volume: float,
    ) -> tuple[dict[str, Any], bool]:
        fingerprint = self.fingerprint_request(
            topic, target_duration_seconds, aspect_ratio, voice_id, provider_mode
        )
        with self.transaction(immediate=True) as connection:
            if idempotency_key:
                existing = connection.execute(
                    "SELECT * FROM video_tasks WHERE user_id = ? AND idempotency_key = ?",
                    (user_id, idempotency_key),
                ).fetchone()
                if existing:
                    if existing["request_fingerprint"] != fingerprint:
                        raise IdempotencyConflictError
                    return self._decode_task(existing), False

            task_id = str(uuid4())
            thread_id = str(uuid4())
            now = utc_now()
            connection.execute(
                """
                INSERT INTO video_tasks(
                    id, user_id, thread_id, topic, target_duration_seconds, aspect_ratio,
                    voice_id, provider_mode, status, current_stage, completed_steps,
                    bgm_default_volume,
                    idempotency_key, request_fingerprint, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    user_id,
                    thread_id,
                    topic,
                    target_duration_seconds,
                    aspect_ratio,
                    voice_id,
                    provider_mode,
                    TaskStatus.QUEUED.value,
                    TaskStatus.QUEUED.value,
                    0,
                    default_bgm_volume,
                    idempotency_key,
                    fingerprint,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM video_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            assert row is not None
            return self._decode_task(row), True

    def get_task(self, user_id: str, task_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM video_tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
            ).fetchone()
        if not row:
            raise TaskNotFoundError
        return self._decode_task(row)

    def get_task_internal(self, task_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM video_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        if not row:
            raise TaskNotFoundError
        return self._decode_task(row)

    def list_tasks(
        self, user_id: str, page: int, page_size: int, status: str | None
    ) -> tuple[list[dict[str, Any]], int]:
        where = "user_id = ?"
        params: list[Any] = [user_id]
        if status:
            where += " AND status = ?"
            params.append(status)
        with self._connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) AS total FROM video_tasks WHERE {where}", params
            ).fetchone()["total"]
            rows = connection.execute(
                f"""
                SELECT * FROM video_tasks WHERE {where}
                ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?
                """,
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        return [self._decode_task(row) for row in rows], int(total)

    def list_resumable_task_ids(self) -> list[str]:
        waiting = (
            TaskStatus.AWAITING_SCRIPT_REVIEW.value,
            TaskStatus.AWAITING_STORYBOARD_REVIEW.value,
            TaskStatus.AWAITING_BGM_DECISION.value,
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
        )
        placeholders = ",".join("?" for _ in waiting)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT id FROM video_tasks WHERE status NOT IN ({placeholders})", waiting
            ).fetchall()
        return [row["id"] for row in rows]

    def sync_task_from_state(self, task_id: str, state: dict[str, Any]) -> None:
        status = TaskStatus(state["status"])
        completed_steps = PROGRESS[status][0]
        script = state.get("script")
        storyboard = state.get("storyboard")
        timeline = state.get("timeline")
        preview = state.get("preview_video")
        final_video = state.get("final_video")
        error = state.get("error")
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE video_tasks SET
                    status = ?, current_stage = ?, completed_steps = ?,
                    script_version = ?, storyboard_version = ?, preview_version = ?,
                    script_json = ?, storyboard_json = ?, timeline_json = ?,
                    preview_relative_path = ?, final_relative_path = ?, final_duration_ms = ?,
                    bgm_added = ?, bgm_suggested_query = ?, pending_command_json = NULL,
                    error_code = ?, error_message = ?, error_retryable = ?, failed_stage = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    state.get("current_stage", status.value),
                    completed_steps,
                    int(state.get("script_version", 0)),
                    int(state.get("storyboard_version", 0)),
                    int(state.get("preview_version", 0)),
                    self._json_dump(script),
                    self._json_dump(storyboard),
                    self._json_dump(timeline),
                    preview.get("relative_path") if preview else None,
                    final_video.get("relative_path") if final_video else None,
                    (final_video or preview or {}).get("duration_ms"),
                    self._bool_to_int(state.get("bgm_added")),
                    state.get("bgm_query"),
                    error.get("code") if error else None,
                    error.get("message") if error else None,
                    self._bool_to_int(error.get("retryable")) if error else None,
                    error.get("failed_stage") if error else None,
                    utc_now(),
                    task_id,
                ),
            )

    def set_task_status_internal(self, task_id: str, status: TaskStatus) -> None:
        completed_steps, _ = PROGRESS[status]
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE video_tasks
                SET status = ?, current_stage = ?, completed_steps = ?, updated_at = ?
                WHERE id = ?
                """,
                (status.value, status.value, completed_steps, utc_now(), task_id),
            )

    def claim_review(
        self,
        *,
        user_id: str,
        task_id: str,
        kind: str,
        version: int,
        action: str,
        feedback: str | None = None,
        volume: float | None = None,
    ) -> dict[str, Any]:
        expected = {
            "script": (TaskStatus.AWAITING_SCRIPT_REVIEW.value, "script_version"),
            "storyboard": (TaskStatus.AWAITING_STORYBOARD_REVIEW.value, "storyboard_version"),
            "bgm": (TaskStatus.AWAITING_BGM_DECISION.value, "preview_version"),
        }
        next_status = {
            "script": TaskStatus.GENERATING_SCRIPT.value
            if action == "reject"
            else TaskStatus.GENERATING_STORYBOARD.value,
            "storyboard": TaskStatus.GENERATING_STORYBOARD.value
            if action == "reject"
            else TaskStatus.SYNTHESIZING_AUDIO.value,
            "bgm": TaskStatus.PROCESSING_BGM.value
            if action in {"add", "no_add"}
            else TaskStatus.AWAITING_BGM_DECISION.value,
        }
        command = {"kind": kind, "action": action, "version": version}
        if feedback is not None:
            command["feedback"] = feedback
        if volume is not None:
            command["volume"] = volume
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM video_tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
            ).fetchone()
            if not row:
                raise TaskNotFoundError
            expected_status, version_column = expected[kind]
            if row["status"] != expected_status:
                raise StateConflictError
            if int(row[version_column]) != version:
                raise VersionConflictError
            try:
                connection.execute(
                    """
                    INSERT INTO reviews(
                        id, task_id, user_id, kind, version, action, feedback, volume, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        task_id,
                        user_id,
                        kind,
                        version,
                        action,
                        feedback,
                        volume,
                        utc_now(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise VersionConflictError from error
            connection.execute(
                """
                UPDATE video_tasks
                SET status = ?, current_stage = ?, pending_command_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_status[kind], next_status[kind], json.dumps(command), utc_now(), task_id),
            )
        return self.get_task(user_id, task_id)

    def mark_failed(
        self,
        task_id: str,
        *,
        code: str,
        message: str,
        retryable: bool,
        failed_stage: str,
    ) -> None:
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE video_tasks
                SET status = ?, current_stage = ?, error_code = ?, error_message = ?,
                    error_retryable = ?, failed_stage = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.FAILED.value,
                    TaskStatus.FAILED.value,
                    code,
                    message,
                    int(retryable),
                    failed_stage,
                    utc_now(),
                    task_id,
                ),
            )

    def claim_retry(self, user_id: str, task_id: str) -> dict[str, Any]:
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM video_tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
            ).fetchone()
            if not row:
                raise TaskNotFoundError
            if row["status"] != TaskStatus.FAILED.value or not row["error_retryable"]:
                raise StateConflictError
            connection.execute(
                """
                UPDATE video_tasks SET status = ?, current_stage = ?, error_code = NULL,
                    error_message = NULL, error_retryable = NULL, failed_stage = NULL,
                    updated_at = ? WHERE id = ?
                """,
                (TaskStatus.QUEUED.value, TaskStatus.QUEUED.value, utc_now(), task_id),
            )
        return self.get_task(user_id, task_id)

    def delete_task_row(self, user_id: str, task_id: str) -> dict[str, Any]:
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM video_tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
            ).fetchone()
            if not row:
                raise TaskNotFoundError
            deletable = {
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.AWAITING_SCRIPT_REVIEW.value,
                TaskStatus.AWAITING_STORYBOARD_REVIEW.value,
                TaskStatus.AWAITING_BGM_DECISION.value,
            }
            if row["status"] not in deletable:
                raise StateConflictError
            connection.execute("DELETE FROM video_tasks WHERE id = ?", (task_id,))
        return self._decode_task(row)

    def list_reviews(self, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reviews WHERE task_id = ? ORDER BY created_at, id", (task_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _json_dump(value: Any) -> str | None:
        return json.dumps(value, ensure_ascii=False) if value is not None else None

    @staticmethod
    def _bool_to_int(value: Any) -> int | None:
        return None if value is None else int(bool(value))

    @staticmethod
    def _decode_task(row: sqlite3.Row) -> dict[str, Any]:
        task = dict(row)
        for key in ("script_json", "storyboard_json", "timeline_json", "pending_command_json"):
            task[key.removesuffix("_json")] = json.loads(task[key]) if task[key] else None
        task["bgm_added"] = None if task["bgm_added"] is None else bool(task["bgm_added"])
        if task["error_retryable"] is not None:
            task["error_retryable"] = bool(task["error_retryable"])
        return task
