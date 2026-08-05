from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.domain.models import PROGRESS, TaskStatus, UserPreferences


class RepositoryError(Exception):
    """Base repository exception."""


class DuplicateEmailError(RepositoryError):
    pass


class DuplicateNicknameError(RepositoryError):
    pass


class TaskNotFoundError(RepositoryError):
    pass


class StateConflictError(RepositoryError):
    pass


class VersionConflictError(RepositoryError):
    pass


class IdempotencyConflictError(RepositoryError):
    pass


class CommunityNotFoundError(RepositoryError):
    pass


class CommunityConflictError(RepositoryError):
    pass


class QuotaExceededError(RepositoryError):
    pass


class AccountDisabledError(RepositoryError):
    pass


class CdkNotFoundError(RepositoryError):
    pass


class CdkUsedError(RepositoryError):
    pass


class InsufficientBalanceError(RepositoryError):
    pass


class UserNotFoundError(RepositoryError):
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
        return {
            "id": user_id,
            "email": email,
            "nickname": None,
            "avatar_relative_path": None,
            "role": "user",
            "is_active": True,
            "created_at": created_at,
        }

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT id, email, password_hash, nickname, avatar_relative_path, role,
                          is_active, created_at
                   FROM users WHERE email = ?""",
                (email,),
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT id, email, nickname, avatar_relative_path, role, is_active, created_at
                   FROM users WHERE id = ?""",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_user_credentials(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, password_hash FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_profile(self, user_id: str, nickname: str) -> dict[str, Any]:
        try:
            with self.transaction(immediate=True) as connection:
                connection.execute(
                    "UPDATE users SET nickname = ? WHERE id = ?", (nickname, user_id)
                )
        except sqlite3.IntegrityError as error:
            raise DuplicateNicknameError from error
        user = self.get_user_by_id(user_id)
        if not user:
            raise RepositoryError("user missing")
        return user

    def update_avatar(self, user_id: str, relative_path: str) -> dict[str, Any]:
        with self.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE users SET avatar_relative_path = ? WHERE id = ?",
                (relative_path, user_id),
            )
        user = self.get_user_by_id(user_id)
        if not user:
            raise RepositoryError("user missing")
        return user

    def change_password(self, user_id: str, password_hash: str) -> None:
        with self.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id)
            )
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def record_audit(
        self,
        user_id: str | None,
        action: str,
        ip_address: str,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> None:
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO audit_logs(id, user_id, action, target_type, target_id, ip_address, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (str(uuid4()), user_id, action, target_type, target_id, ip_address[:64], utc_now()),
            )

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
                       u.email, u.nickname, u.avatar_relative_path, u.role, u.is_active,
                       u.created_at AS user_created_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_active = 1
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

            account = connection.execute(
                "SELECT is_active, generation_quota, generations_used FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if not account or not account["is_active"]:
                raise AccountDisabledError
            if int(account["generations_used"]) >= int(account["generation_quota"]):
                raise QuotaExceededError

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
            connection.execute(
                "UPDATE users SET generations_used = generations_used + 1 WHERE id = ?",
                (user_id,),
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
        self,
        user_id: str,
        page: int,
        page_size: int,
        status: str | None,
        status_group: str | None = None,
        query: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        where = "user_id = ?"
        params: list[Any] = [user_id]
        if status:
            where += " AND status = ?"
            params.append(status)
        elif status_group == "in_progress":
            active_statuses = (
                TaskStatus.QUEUED.value,
                TaskStatus.GENERATING_SCRIPT.value,
                TaskStatus.GENERATING_STORYBOARD.value,
                TaskStatus.SYNTHESIZING_AUDIO.value,
                TaskStatus.BUILDING_TIMELINE.value,
                TaskStatus.FETCHING_ASSETS.value,
                TaskStatus.ALIGNING_TIMELINE.value,
                TaskStatus.RENDERING_PREVIEW.value,
                TaskStatus.PROCESSING_BGM.value,
            )
            where += f" AND status IN ({','.join('?' for _ in active_statuses)})"
            params.extend(active_statuses)
        if query:
            escaped_query = (
                query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            pattern = f"%{escaped_query}%"
            where += " AND topic LIKE ? ESCAPE '\\'"
            params.append(pattern)
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

    def get_task_stats(self, user_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                    SUM(CASE WHEN status IN ('queued','generating_script','generating_storyboard',
                        'synthesizing_audio','building_timeline','fetching_assets',
                        'aligning_timeline','rendering_preview','processing_bgm') THEN 1 ELSE 0 END)
                        AS in_progress,
                    SUM(CASE WHEN status IN ('awaiting_script_review','awaiting_storyboard_review',
                        'awaiting_bgm_decision') THEN 1 ELSE 0 END) AS awaiting_review,
                    COALESCE(SUM(CASE WHEN status = 'completed' THEN final_duration_ms ELSE 0 END), 0)
                        AS total_duration_ms
                FROM video_tasks WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "completed": int(row["completed"] or 0),
            "failed": int(row["failed"] or 0),
            "in_progress": int(row["in_progress"] or 0),
            "awaiting_review": int(row["awaiting_review"] or 0),
            "total_duration_seconds": round(int(row["total_duration_ms"] or 0) / 1000, 3),
        }

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
        bgm_selection: dict[str, Any] | None = None,
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
        if bgm_selection is not None:
            command["selection"] = bgm_selection
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
                        id, task_id, user_id, kind, version, action, feedback, volume,
                        bgm_track_id, bgm_track_name, bgm_track_source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        bgm_selection.get("track_id") if bgm_selection else None,
                        bgm_selection.get("name") if bgm_selection else None,
                        bgm_selection.get("source") if bgm_selection else None,
                        utc_now(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise VersionConflictError from error
            connection.execute(
                """
                UPDATE video_tasks
                SET status = ?, current_stage = ?, pending_command_json = ?,
                    selected_bgm_track_id = ?, selected_bgm_name = ?, selected_bgm_source = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    next_status[kind],
                    next_status[kind],
                    json.dumps(command),
                    bgm_selection.get("track_id") if bgm_selection else None,
                    bgm_selection.get("name") if bgm_selection else None,
                    bgm_selection.get("source") if bgm_selection else None,
                    utc_now(),
                    task_id,
                ),
            )
        return self.get_task(user_id, task_id)

    def register_uploaded_bgm(
        self,
        *,
        user_id: str,
        task_id: str,
        preview_version: int,
        relative_path: str,
        name: str,
        duration_ms: int,
        checksum: str,
    ) -> dict[str, Any]:
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM video_tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
            ).fetchone()
            if not row:
                raise TaskNotFoundError
            if row["status"] != TaskStatus.AWAITING_BGM_DECISION.value:
                raise StateConflictError
            if int(row["preview_version"]) != preview_version:
                raise VersionConflictError
            connection.execute(
                """
                UPDATE video_tasks SET uploaded_bgm_relative_path = ?, uploaded_bgm_name = ?,
                    uploaded_bgm_duration_ms = ?, uploaded_bgm_checksum = ?, updated_at = ?
                WHERE id = ?
                """,
                (relative_path, name, duration_ms, checksum, utc_now(), task_id),
            )
        return self.get_task(user_id, task_id)

    def tasks_for_bulk_delete(
        self, user_id: str, task_ids: list[str] | None
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if task_ids is None:
                rows = connection.execute(
                    "SELECT * FROM video_tasks WHERE user_id = ? ORDER BY created_at, id",
                    (user_id,),
                ).fetchall()
            else:
                placeholders = ",".join("?" for _ in task_ids)
                rows = connection.execute(
                    f"SELECT * FROM video_tasks WHERE user_id = ? AND id IN ({placeholders})",
                    [user_id, *task_ids],
                ).fetchall()
                if len(rows) != len(task_ids):
                    raise TaskNotFoundError
        return [self._decode_task(row) for row in rows]

    def delete_task_rows(self, user_id: str, task_ids: list[str]) -> int:
        if not task_ids:
            return 0
        deletable = {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.AWAITING_SCRIPT_REVIEW.value,
            TaskStatus.AWAITING_STORYBOARD_REVIEW.value,
            TaskStatus.AWAITING_BGM_DECISION.value,
        }
        with self.transaction(immediate=True) as connection:
            placeholders = ",".join("?" for _ in task_ids)
            rows = connection.execute(
                f"SELECT id, status FROM video_tasks WHERE user_id = ? AND id IN ({placeholders})",
                [user_id, *task_ids],
            ).fetchall()
            if len(rows) != len(task_ids):
                raise TaskNotFoundError
            if any(row["status"] not in deletable for row in rows):
                raise StateConflictError
            connection.execute(
                f"DELETE FROM video_tasks WHERE user_id = ? AND id IN ({placeholders})",
                [user_id, *task_ids],
            )
        return len(task_ids)

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

    def create_post(
        self,
        user_id: str,
        task_id: str,
        title: str,
        description: str,
        prompt_public: bool,
        tags: list[str],
    ) -> dict[str, Any]:
        post_id = str(uuid4())
        created_at = utc_now()
        with self.transaction(immediate=True) as connection:
            task = connection.execute(
                """SELECT id FROM video_tasks
                   WHERE id = ? AND user_id = ? AND status = 'completed'
                         AND final_relative_path IS NOT NULL""",
                (task_id, user_id),
            ).fetchone()
            if not task:
                raise StateConflictError
            connection.execute(
                """INSERT INTO community_posts(
                       id, user_id, task_id, title, description, prompt_public, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (post_id, user_id, task_id, title, description, int(prompt_public), created_at),
            )
            connection.executemany(
                "INSERT INTO post_tags(post_id, tag) VALUES (?, ?)",
                [(post_id, tag) for tag in tags],
            )
        return self.get_post(user_id, post_id)

    def get_post(self, viewer_id: str, post_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT p.*, u.email AS author_email, u.nickname AS author_nickname,
                       u.avatar_relative_path AS author_avatar,
                       t.topic AS generation_prompt, t.aspect_ratio,
                       t.final_duration_ms, t.final_relative_path, t.preview_relative_path,
                       (SELECT COUNT(*) FROM post_comments c WHERE c.post_id = p.id) comment_count,
                       (SELECT COUNT(*) FROM post_shares s WHERE s.post_id = p.id) share_count,
                       (SELECT COUNT(*) FROM post_favorites f WHERE f.post_id = p.id) favorite_count,
                       (SELECT COUNT(*) FROM post_likes l WHERE l.post_id = p.id) like_count,
                       EXISTS(SELECT 1 FROM post_favorites f WHERE f.post_id = p.id AND f.user_id = ?) favorited,
                       EXISTS(SELECT 1 FROM post_likes l WHERE l.post_id = p.id AND l.user_id = ?) liked
                FROM community_posts p
                JOIN users u ON u.id = p.user_id
                JOIN video_tasks t ON t.id = p.task_id
                WHERE p.id = ? AND p.is_deleted = 0
                """,
                (viewer_id, viewer_id, post_id),
            ).fetchone()
            if not row:
                raise CommunityNotFoundError
            tags = [
                item["tag"]
                for item in connection.execute(
                    "SELECT tag FROM post_tags WHERE post_id = ? ORDER BY tag", (post_id,)
                )
            ]
        post = dict(row)
        post["tags"] = tags
        post["prompt_public"] = bool(post["prompt_public"])
        post["favorited"] = bool(post["favorited"])
        post["liked"] = bool(post["liked"])
        return post

    def list_posts(
        self,
        viewer_id: str,
        page: int,
        page_size: int,
        *,
        owner_id: str | None = None,
        favorite_only: bool = False,
        following_only: bool = False,
        tag: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        filters = ["p.is_deleted = 0"]
        parameters: list[Any] = []
        if owner_id:
            filters.append("p.user_id = ?")
            parameters.append(owner_id)
        if following_only:
            filters.append(
                "EXISTS(SELECT 1 FROM user_follows uf "
                "WHERE uf.follower_id=? AND uf.followee_id=p.user_id)"
            )
            parameters.append(viewer_id)
        if favorite_only:
            filters.append(
                "EXISTS(SELECT 1 FROM post_favorites pf WHERE pf.post_id=p.id AND pf.user_id=?)"
            )
            parameters.append(viewer_id)
        if tag:
            filters.append("EXISTS(SELECT 1 FROM post_tags pt WHERE pt.post_id=p.id AND pt.tag=?)")
            parameters.append(tag)
        where = " AND ".join(filters)
        with self._connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM community_posts p WHERE {where}", parameters
            ).fetchone()[0]
            ids = [
                row["id"]
                for row in connection.execute(
                    f"""SELECT p.id FROM community_posts p WHERE {where}
                        ORDER BY p.created_at DESC, p.id DESC LIMIT ? OFFSET ?""",
                    [*parameters, page_size, (page - 1) * page_size],
                )
            ]
        return [self.get_post(viewer_id, post_id) for post_id in ids], int(total)

    def soft_delete_post(self, user_id: str, post_id: str) -> None:
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT user_id FROM community_posts WHERE id=? AND is_deleted=0", (post_id,)
            ).fetchone()
            if not row:
                raise CommunityNotFoundError
            if row["user_id"] != user_id:
                raise CommunityNotFoundError
            connection.execute(
                """UPDATE community_posts
                   SET is_deleted=1, deleted_at=?, prompt_public=0 WHERE id=?""",
                (utc_now(), post_id),
            )
            connection.execute("DELETE FROM post_tags WHERE post_id=?", (post_id,))
            connection.execute("DELETE FROM post_comments WHERE post_id=?", (post_id,))
            connection.execute("DELETE FROM post_shares WHERE post_id=?", (post_id,))
            connection.execute("DELETE FROM post_favorites WHERE post_id=?", (post_id,))
            connection.execute("DELETE FROM post_likes WHERE post_id=?", (post_id,))

    def add_comment(
        self, user_id: str, post_id: str, content: str, parent_id: str | None
    ) -> dict[str, Any]:
        comment_id = str(uuid4())
        with self.transaction(immediate=True) as connection:
            post = connection.execute(
                "SELECT id FROM community_posts WHERE id=? AND is_deleted=0", (post_id,)
            ).fetchone()
            if not post:
                raise CommunityNotFoundError
            if parent_id:
                parent = connection.execute(
                    "SELECT parent_id FROM post_comments WHERE id=? AND post_id=?",
                    (parent_id, post_id),
                ).fetchone()
                if not parent or parent["parent_id"] is not None:
                    raise CommunityConflictError
            connection.execute(
                """INSERT INTO post_comments(id, post_id, user_id, parent_id, content, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (comment_id, post_id, user_id, parent_id, content, utc_now()),
            )
        return {"id": comment_id}

    def list_comments(self, viewer_id: str, post_id: str, sort: str) -> list[dict[str, Any]]:
        order = "like_count DESC, c.created_at DESC" if sort == "hot" else "c.created_at DESC"
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT c.*, u.email author_email, u.nickname author_nickname,
                       u.avatar_relative_path author_avatar,
                       (SELECT COUNT(*) FROM comment_likes l WHERE l.comment_id=c.id) like_count,
                       EXISTS(SELECT 1 FROM comment_likes l WHERE l.comment_id=c.id AND l.user_id=?) liked
                FROM post_comments c JOIN users u ON u.id=c.user_id
                WHERE c.post_id=? ORDER BY c.parent_id IS NOT NULL, {order}
                """,
                (viewer_id, post_id),
            ).fetchall()
        comments = [dict(row) for row in rows]
        for comment in comments:
            comment["liked"] = bool(comment["liked"])
        return comments

    def toggle_comment_like(self, user_id: str, comment_id: str) -> bool:
        with self.transaction(immediate=True) as connection:
            if not connection.execute(
                "SELECT 1 FROM post_comments WHERE id=?", (comment_id,)
            ).fetchone():
                raise CommunityNotFoundError
            existing = connection.execute(
                "SELECT 1 FROM comment_likes WHERE comment_id=? AND user_id=?",
                (comment_id, user_id),
            ).fetchone()
            if existing:
                connection.execute(
                    "DELETE FROM comment_likes WHERE comment_id=? AND user_id=?",
                    (comment_id, user_id),
                )
                return False
            connection.execute(
                "INSERT INTO comment_likes(comment_id,user_id,created_at) VALUES (?,?,?)",
                (comment_id, user_id, utc_now()),
            )
            return True

    def delete_comment(self, user_id: str, comment_id: str) -> None:
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                """SELECT c.user_id, p.user_id post_owner FROM post_comments c
                   JOIN community_posts p ON p.id=c.post_id WHERE c.id=?""",
                (comment_id,),
            ).fetchone()
            if not row or user_id not in {row["user_id"], row["post_owner"]}:
                raise CommunityNotFoundError
            connection.execute("DELETE FROM post_comments WHERE id=?", (comment_id,))

    def toggle_favorite(self, user_id: str, post_id: str) -> bool:
        with self.transaction(immediate=True) as connection:
            if not connection.execute(
                "SELECT 1 FROM community_posts WHERE id=? AND is_deleted=0", (post_id,)
            ).fetchone():
                raise CommunityNotFoundError
            existing = connection.execute(
                "SELECT 1 FROM post_favorites WHERE post_id=? AND user_id=?", (post_id, user_id)
            ).fetchone()
            if existing:
                connection.execute(
                    "DELETE FROM post_favorites WHERE post_id=? AND user_id=?", (post_id, user_id)
                )
                return False
            connection.execute(
                "INSERT INTO post_favorites(post_id,user_id,created_at) VALUES (?,?,?)",
                (post_id, user_id, utc_now()),
            )
            return True

    def toggle_post_like(self, user_id: str, post_id: str) -> bool:
        with self.transaction(immediate=True) as connection:
            if not connection.execute(
                "SELECT 1 FROM community_posts WHERE id=? AND is_deleted=0", (post_id,)
            ).fetchone():
                raise CommunityNotFoundError
            existing = connection.execute(
                "SELECT 1 FROM post_likes WHERE post_id=? AND user_id=?", (post_id, user_id)
            ).fetchone()
            if existing:
                connection.execute(
                    "DELETE FROM post_likes WHERE post_id=? AND user_id=?", (post_id, user_id)
                )
                return False
            connection.execute(
                "INSERT INTO post_likes(post_id,user_id,created_at) VALUES (?,?,?)",
                (post_id, user_id, utc_now()),
            )
            return True

    def follow_user(self, follower_id: str, followee_id: str) -> bool:
        if follower_id == followee_id:
            raise CommunityConflictError
        with self.transaction(immediate=True) as connection:
            target = connection.execute("SELECT 1 FROM users WHERE id=?", (followee_id,)).fetchone()
            if not target:
                raise CommunityNotFoundError
            existing = connection.execute(
                "SELECT 1 FROM user_follows WHERE follower_id=? AND followee_id=?",
                (follower_id, followee_id),
            ).fetchone()
            if existing:
                connection.execute(
                    "DELETE FROM user_follows WHERE follower_id=? AND followee_id=?",
                    (follower_id, followee_id),
                )
                return False
            connection.execute(
                "INSERT INTO user_follows(follower_id,followee_id,created_at) VALUES (?,?,?)",
                (follower_id, followee_id, utc_now()),
            )
            return True

    def get_public_profile(self, viewer_id: str, user_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            user = connection.execute(
                "SELECT id,email,nickname,avatar_relative_path,created_at FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
            if not user:
                raise CommunityNotFoundError
            follower_count = connection.execute(
                "SELECT COUNT(*) FROM user_follows WHERE followee_id=?", (user_id,)
            ).fetchone()[0]
            following_count = connection.execute(
                "SELECT COUNT(*) FROM user_follows WHERE follower_id=?", (user_id,)
            ).fetchone()[0]
            post_count = connection.execute(
                "SELECT COUNT(*) FROM community_posts WHERE user_id=? AND is_deleted=0", (user_id,)
            ).fetchone()[0]
            is_following = bool(
                connection.execute(
                    "SELECT 1 FROM user_follows WHERE follower_id=? AND followee_id=?",
                    (viewer_id, user_id),
                ).fetchone()
            )
        profile = dict(user)
        profile["follower_count"] = int(follower_count)
        profile["following_count"] = int(following_count)
        profile["post_count"] = int(post_count)
        profile["is_following"] = is_following
        profile["is_self"] = viewer_id == user_id
        return profile

    def search_users(self, query: str, exclude_id: str) -> list[dict[str, Any]]:
        pattern = f"%{query.replace('%', '').replace('_', '')}%"
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT id,email,nickname,avatar_relative_path FROM users
                   WHERE id<>? AND (nickname LIKE ? OR email LIKE ?)
                   ORDER BY nickname IS NULL, nickname, email LIMIT 20""",
                (exclude_id, pattern, pattern),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_received_posts(
        self, viewer_id: str, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        with self._connect() as connection:
            total = connection.execute(
                """SELECT COUNT(*) FROM post_shares s JOIN community_posts p ON p.id=s.post_id
                   WHERE s.recipient_id=? AND p.is_deleted=0""",
                (viewer_id,),
            ).fetchone()[0]
            ids = [
                row["post_id"]
                for row in connection.execute(
                    """SELECT s.post_id FROM post_shares s
                       JOIN community_posts p ON p.id=s.post_id
                       WHERE s.recipient_id=? AND p.is_deleted=0
                       ORDER BY s.created_at DESC LIMIT ? OFFSET ?""",
                    (viewer_id, page_size, (page - 1) * page_size),
                )
            ]
        return [self.get_post(viewer_id, post_id) for post_id in ids], int(total)

    def share_post(self, sender_id: str, post_id: str, recipient_id: str) -> None:
        if sender_id == recipient_id:
            raise CommunityConflictError
        try:
            with self.transaction(immediate=True) as connection:
                if (
                    not connection.execute(
                        "SELECT 1 FROM community_posts WHERE id=? AND is_deleted=0", (post_id,)
                    ).fetchone()
                    or not connection.execute(
                        "SELECT 1 FROM users WHERE id=?", (recipient_id,)
                    ).fetchone()
                ):
                    raise CommunityNotFoundError
                connection.execute(
                    """INSERT INTO post_shares(id,post_id,sender_id,recipient_id,created_at)
                       VALUES (?,?,?,?,?)""",
                    (str(uuid4()), post_id, sender_id, recipient_id, utc_now()),
                )
        except sqlite3.IntegrityError as error:
            raise CommunityConflictError from error

    def duplicate_task(
        self,
        user_id: str,
        source_task_id: str,
        *,
        provider_mode: str,
        default_bgm_volume: float,
        idempotency_key: str | None,
    ) -> tuple[dict[str, Any], bool]:
        with self.transaction(immediate=True) as connection:
            source = connection.execute(
                "SELECT * FROM video_tasks WHERE id=? AND user_id=?", (source_task_id, user_id)
            ).fetchone()
            if not source:
                raise TaskNotFoundError
            if source["status"] != TaskStatus.COMPLETED.value:
                raise StateConflictError
            topic = source["topic"]
            target_duration_seconds = int(source["target_duration_seconds"])
            aspect_ratio = source["aspect_ratio"]
            voice_id = source["voice_id"]
            raw_fingerprint = json.dumps(
                {
                    "operation": "duplicate_task",
                    "source_task_id": source_task_id,
                    "topic": topic,
                    "target_duration_seconds": target_duration_seconds,
                    "aspect_ratio": aspect_ratio,
                    "voice_id": voice_id,
                    "provider_mode": provider_mode,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            fingerprint = hashlib.sha256(raw_fingerprint.encode("utf-8")).hexdigest()
            if idempotency_key:
                existing = connection.execute(
                    "SELECT * FROM video_tasks WHERE user_id = ? AND idempotency_key = ?",
                    (user_id, idempotency_key),
                ).fetchone()
                if existing:
                    if existing["request_fingerprint"] != fingerprint:
                        raise IdempotencyConflictError
                    return self._decode_task(existing), False

            account = connection.execute(
                "SELECT is_active, generation_quota, generations_used FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if not account or not account["is_active"]:
                raise AccountDisabledError
            if int(account["generations_used"]) >= int(account["generation_quota"]):
                raise QuotaExceededError

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
            connection.execute(
                "UPDATE users SET generations_used = generations_used + 1 WHERE id = ?",
                (user_id,),
            )
            row = connection.execute(
                "SELECT * FROM video_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            assert row is not None
            return self._decode_task(row), True

    @staticmethod
    def _account_from_row(row: sqlite3.Row) -> dict[str, Any]:
        quota = int(row["generation_quota"])
        used = int(row["generations_used"])
        return {
            "membership_tier": row["membership_tier"],
            "membership_expires_at": row["membership_expires_at"],
            "balance_cents": int(row["balance_cents"]),
            "generation_quota": quota,
            "generations_used": used,
            "generations_remaining": max(0, quota - used),
            "has_payment_password": bool(row["payment_password_hash"]),
        }

    def get_account(self, user_id: str) -> dict[str, Any]:
        with self.transaction(immediate=True) as connection:
            now = utc_now()
            connection.execute(
                """UPDATE users SET membership_tier='free', membership_expires_at=NULL
                   WHERE id=? AND membership_tier!='free' AND membership_expires_at<=?""",
                (user_id, now),
            )
            row = connection.execute(
                """SELECT membership_tier, membership_expires_at, balance_cents,
                          generation_quota, generations_used, payment_password_hash
                   FROM users WHERE id=?""",
                (user_id,),
            ).fetchone()
            if not row:
                raise UserNotFoundError
            return self._account_from_row(row)

    def get_payment_password_hash(self, user_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payment_password_hash FROM users WHERE id=?", (user_id,)
            ).fetchone()
        if not row:
            raise UserNotFoundError
        return row["payment_password_hash"]

    def set_payment_password_hash(self, user_id: str, password_hash: str) -> None:
        with self.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE users SET payment_password_hash=? WHERE id=?", (password_hash, user_id)
            )

    def redeem_cdk(self, user_id: str, code_hash: str) -> dict[str, Any]:
        with self.transaction(immediate=True) as connection:
            cdk = connection.execute(
                "SELECT * FROM cdks WHERE code_hash=?", (code_hash,)
            ).fetchone()
            if not cdk:
                raise CdkNotFoundError
            if cdk["status"] != "unused":
                raise CdkUsedError
            now = utc_now()
            connection.execute(
                "UPDATE cdks SET status='used', used_by=?, used_at=? WHERE id=? AND status='unused'",
                (user_id, now, cdk["id"]),
            )
            connection.execute(
                "UPDATE users SET balance_cents=balance_cents+? WHERE id=?",
                (cdk["amount_cents"], user_id),
            )
            balance = int(
                connection.execute(
                    "SELECT balance_cents FROM users WHERE id=?", (user_id,)
                ).fetchone()[0]
            )
            connection.execute(
                """INSERT INTO account_ledger(
                       id,user_id,kind,amount_cents,balance_after_cents,reference_type,
                       reference_id,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    str(uuid4()),
                    user_id,
                    "cdk_recharge",
                    int(cdk["amount_cents"]),
                    balance,
                    "cdk",
                    cdk["id"],
                    now,
                ),
            )
        return self.get_account(user_id)

    def purchase_membership(
        self,
        *,
        user_id: str,
        tier: str,
        price_cents: int,
        generation_credits: int,
        duration_days: int,
        idempotency_key: str | None,
    ) -> tuple[dict[str, Any], bool]:
        fingerprint = hashlib.sha256(f"membership:{tier}:{price_cents}".encode()).hexdigest()
        with self.transaction(immediate=True) as connection:
            if idempotency_key:
                existing = connection.execute(
                    "SELECT * FROM membership_orders WHERE user_id=? AND idempotency_key=?",
                    (user_id, idempotency_key),
                ).fetchone()
                if existing:
                    if existing["request_fingerprint"] != fingerprint:
                        raise IdempotencyConflictError
                    return dict(existing), False
            user = connection.execute(
                "SELECT * FROM users WHERE id=? AND is_active=1", (user_id,)
            ).fetchone()
            if not user:
                raise AccountDisabledError
            if int(user["balance_cents"]) < price_cents:
                raise InsufficientBalanceError
            now_dt = datetime.now(timezone.utc)
            current_expiry = user["membership_expires_at"]
            base = now_dt
            if user["membership_tier"] == tier and current_expiry:
                parsed = datetime.fromisoformat(current_expiry.replace("Z", "+00:00"))
                if parsed > now_dt:
                    base = parsed
            expires = (base + timedelta(days=duration_days)).isoformat().replace("+00:00", "Z")
            order_id = str(uuid4())
            now = utc_now()
            balance = int(user["balance_cents"]) - price_cents
            connection.execute(
                """UPDATE users SET balance_cents=?, membership_tier=?,
                       membership_expires_at=?, generation_quota=generation_quota+?
                   WHERE id=?""",
                (balance, tier, expires, generation_credits, user_id),
            )
            connection.execute(
                """INSERT INTO membership_orders(
                       id,user_id,tier,price_cents,generation_credits,status,idempotency_key,
                       request_fingerprint,created_at) VALUES (?,?,?,?,?,'paid',?,?,?)""",
                (
                    order_id,
                    user_id,
                    tier,
                    price_cents,
                    generation_credits,
                    idempotency_key,
                    fingerprint,
                    now,
                ),
            )
            connection.execute(
                """INSERT INTO account_ledger(
                       id,user_id,kind,amount_cents,balance_after_cents,reference_type,
                       reference_id,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    str(uuid4()),
                    user_id,
                    "membership_payment",
                    -price_cents,
                    balance,
                    "membership_order",
                    order_id,
                    now,
                ),
            )
            order = connection.execute(
                "SELECT * FROM membership_orders WHERE id=?", (order_id,)
            ).fetchone()
            assert order is not None
            return dict(order), True

    def list_ledger(self, user_id: str, page: int, page_size: int) -> tuple[list[dict], int]:
        with self._connect() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM account_ledger WHERE user_id=?", (user_id,)
                ).fetchone()[0]
            )
            rows = connection.execute(
                """SELECT id,kind,amount_cents,balance_after_cents,reference_type,created_at
                   FROM account_ledger WHERE user_id=? ORDER BY created_at DESC,id DESC
                   LIMIT ? OFFSET ?""",
                (user_id, page_size, (page - 1) * page_size),
            ).fetchall()
        return [dict(row) for row in rows], total

    def create_cdks(self, admin_id: str, items: list[tuple[str, str, int]]) -> list[dict]:
        now = utc_now()
        created: list[dict] = []
        with self.transaction(immediate=True) as connection:
            for code_hash, hint, amount_cents in items:
                cdk_id = str(uuid4())
                connection.execute(
                    """INSERT INTO cdks(id,code_hash,code_hint,amount_cents,created_by,created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (cdk_id, code_hash, hint, amount_cents, admin_id, now),
                )
                created.append({"id": cdk_id, "amount_cents": amount_cents, "created_at": now})
        return created

    def list_cdks(self, page: int, page_size: int, status: str | None) -> tuple[list[dict], int]:
        where = "WHERE c.status=?" if status else ""
        params: list[Any] = [status] if status else []
        with self._connect() as connection:
            total = int(
                connection.execute(f"SELECT COUNT(*) FROM cdks c {where}", params).fetchone()[0]
            )
            rows = connection.execute(
                f"""SELECT c.id,c.code_hint,c.amount_cents,c.status,c.created_at,c.used_at,
                           c.used_by,u.email AS used_by_email,u.nickname AS used_by_nickname
                    FROM cdks c LEFT JOIN users u ON u.id=c.used_by {where}
                    ORDER BY c.created_at DESC,c.id DESC LIMIT ? OFFSET ?""",
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        return [dict(row) for row in rows], total

    def admin_dashboard(self) -> dict[str, int]:
        with self._connect() as connection:
            user_total = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            active_users = int(
                connection.execute("SELECT COUNT(*) FROM users WHERE is_active=1").fetchone()[0]
            )
            vip_users = int(
                connection.execute(
                    "SELECT COUNT(*) FROM users WHERE membership_tier='vip'"
                ).fetchone()[0]
            )
            svip_users = int(
                connection.execute(
                    "SELECT COUNT(*) FROM users WHERE membership_tier='svip'"
                ).fetchone()[0]
            )
            task_total = int(connection.execute("SELECT COUNT(*) FROM video_tasks").fetchone()[0])
            task_counts = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                    SUM(CASE WHEN status IN (
                        'queued','generating_script','generating_storyboard','synthesizing_audio',
                        'building_timeline','fetching_assets','aligning_timeline',
                        'rendering_preview','processing_bgm'
                    ) THEN 1 ELSE 0 END) AS in_progress,
                    SUM(CASE WHEN status IN (
                        'awaiting_script_review','awaiting_storyboard_review','awaiting_bgm_decision'
                    ) THEN 1 ELSE 0 END) AS awaiting
                FROM video_tasks
                """
            ).fetchone()
            today_users = int(
                connection.execute(
                    "SELECT COUNT(*) FROM users WHERE substr(created_at,1,10)=substr(?,1,10)",
                    (utc_now(),),
                ).fetchone()[0]
            )
            revenue = int(
                connection.execute(
                    "SELECT COALESCE(SUM(price_cents),0) FROM membership_orders WHERE status='paid'"
                ).fetchone()[0]
            )
            cdk_total = int(connection.execute("SELECT COUNT(*) FROM cdks").fetchone()[0])
            cdk_used = int(
                connection.execute("SELECT COUNT(*) FROM cdks WHERE status='used'").fetchone()[0]
            )
        return {
            "user_total": user_total,
            "active_users": active_users,
            "vip_users": vip_users,
            "svip_users": svip_users,
            "task_total": task_total,
            "completed_tasks": int(task_counts["completed"] or 0),
            "failed_tasks": int(task_counts["failed"] or 0),
            "in_progress_tasks": int(task_counts["in_progress"] or 0),
            "awaiting_tasks": int(task_counts["awaiting"] or 0),
            "today_users": today_users,
            "membership_revenue_cents": revenue,
            "cdk_total": cdk_total,
            "cdk_used": cdk_used,
        }

    def list_admin_users(
        self,
        page: int,
        page_size: int,
        query: str | None,
        active: bool | None,
        role: str | None,
        membership: str | None,
    ) -> tuple[list[dict], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("(email LIKE ? ESCAPE '\\' OR nickname LIKE ? ESCAPE '\\')")
            params.extend([f"%{escaped}%", f"%{escaped}%"])
        if active is not None:
            clauses.append("is_active=?")
            params.append(int(active))
        if role:
            clauses.append("role=?")
            params.append(role)
        if membership:
            clauses.append("membership_tier=?")
            params.append(membership)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            total = int(
                connection.execute(f"SELECT COUNT(*) FROM users {where}", params).fetchone()[0]
            )
            rows = connection.execute(
                f"""SELECT id,email,nickname,role,is_active,membership_tier,
                           membership_expires_at,balance_cents,generation_quota,
                           generations_used,created_at,
                           (SELECT COUNT(*) FROM video_tasks t WHERE t.user_id=users.id) AS task_count
                    FROM users {where}
                    ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?""",
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        return [dict(row) for row in rows], total

    def get_admin_user(self, user_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT id,email,nickname,role,is_active,membership_tier,
                          membership_expires_at,balance_cents,generation_quota,
                          generations_used,created_at FROM users WHERE id=?""",
                (user_id,),
            ).fetchone()
            if not row:
                raise UserNotFoundError
            result = dict(row)
            result["task_count"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM video_tasks WHERE user_id=?", (user_id,)
                ).fetchone()[0]
            )
            result["completed_task_count"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM video_tasks WHERE user_id=? AND status='completed'",
                    (user_id,),
                ).fetchone()[0]
            )
            result["failed_task_count"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM video_tasks WHERE user_id=? AND status='failed'",
                    (user_id,),
                ).fetchone()[0]
            )
            result["recent_ledger"] = [
                dict(item)
                for item in connection.execute(
                    """SELECT id,kind,amount_cents,balance_after_cents,reference_type,created_at
                       FROM account_ledger WHERE user_id=?
                       ORDER BY created_at DESC,id DESC LIMIT 10""",
                    (user_id,),
                ).fetchall()
            ]
        return result

    def list_admin_tasks(
        self,
        page: int,
        page_size: int,
        query: str | None,
        status: str | None,
        provider_mode: str | None,
        user_id: str | None,
    ) -> tuple[list[dict], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            clauses.append(
                "(t.topic LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\' "
                "OR u.nickname LIKE ? ESCAPE '\\')"
            )
            params.extend([pattern, pattern, pattern])
        if status:
            clauses.append("t.status=?")
            params.append(status)
        if provider_mode:
            clauses.append("t.provider_mode=?")
            params.append(provider_mode)
        if user_id:
            clauses.append("t.user_id=?")
            params.append(user_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            total = int(
                connection.execute(
                    f"""SELECT COUNT(*) FROM video_tasks t
                        JOIN users u ON u.id=t.user_id {where}""",
                    params,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""SELECT t.id,t.user_id,u.email AS user_email,
                           u.nickname AS user_nickname,t.topic,t.status,t.current_stage,
                           t.provider_mode,t.target_duration_seconds,
                           CASE WHEN t.final_duration_ms IS NULL THEN NULL
                                ELSE t.final_duration_ms / 1000.0 END AS final_duration_seconds,
                           t.aspect_ratio,t.error_code,t.error_message,t.created_at,t.updated_at
                    FROM video_tasks t JOIN users u ON u.id=t.user_id {where}
                    ORDER BY t.created_at DESC,t.id DESC LIMIT ? OFFSET ?""",
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        return [dict(row) for row in rows], total

    def list_admin_audit_logs(
        self, page: int, page_size: int, query: str | None, action: str | None
    ) -> tuple[list[dict], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            clauses.append(
                "(u.email LIKE ? ESCAPE '\\' OR u.nickname LIKE ? ESCAPE '\\' "
                "OR a.action LIKE ? ESCAPE '\\' OR a.target_id LIKE ? ESCAPE '\\')"
            )
            params.extend([pattern, pattern, pattern, pattern])
        if action:
            clauses.append("a.action=?")
            params.append(action)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            total = int(
                connection.execute(
                    f"""SELECT COUNT(*) FROM audit_logs a
                        LEFT JOIN users u ON u.id=a.user_id {where}""",
                    params,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""SELECT a.id,a.user_id AS actor_id,u.email AS actor_email,
                           u.nickname AS actor_nickname,a.action,a.target_type,a.target_id,
                           a.ip_address,a.created_at
                    FROM audit_logs a LEFT JOIN users u ON u.id=a.user_id {where}
                    ORDER BY a.created_at DESC,a.id DESC LIMIT ? OFFSET ?""",
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        return [dict(row) for row in rows], total

    def update_admin_user(
        self,
        user_id: str,
        *,
        is_active: bool | None,
        role: str | None,
        generation_quota: int | None,
    ) -> dict:
        assignments: list[str] = []
        params: list[Any] = []
        if is_active is not None:
            assignments.append("is_active=?")
            params.append(int(is_active))
        if role is not None:
            assignments.append("role=?")
            params.append(role)
        if generation_quota is not None:
            assignments.append("generation_quota=?")
            params.append(generation_quota)
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT generations_used FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if not row:
                raise UserNotFoundError
            if generation_quota is not None and generation_quota < int(row["generations_used"]):
                raise StateConflictError
            connection.execute(
                f"UPDATE users SET {','.join(assignments)} WHERE id=?", [*params, user_id]
            )
            if is_active is False:
                connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        return self.get_admin_user(user_id)

    def create_ad(
        self,
        ad_id: str,
        title: str,
        link_url: str,
        placement: str,
        image_relative_path: str,
        image_media_type: str,
        is_active: bool,
        created_by: str,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO ads(
                       id,title,link_url,placement,image_relative_path,image_media_type,
                       is_active,impressions,clicks,created_by,created_at,updated_at
                   ) VALUES (?,?,?,?,?,?,?,0,0,?,?,?)""",
                (
                    ad_id,
                    title,
                    link_url,
                    placement,
                    image_relative_path,
                    image_media_type,
                    int(is_active),
                    created_by,
                    now,
                    now,
                ),
            )
        ad = self.get_ad(ad_id)
        assert ad is not None
        return ad

    def get_ad(self, ad_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM ads WHERE id=?", (ad_id,)).fetchone()
        if row is None:
            return None
        ad = dict(row)
        ad["is_active"] = bool(ad["is_active"])
        return ad

    def select_active_ad(self, slot: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM ads
                   WHERE is_active=1 AND placement IN ('auto', ?)
                   ORDER BY RANDOM() LIMIT 1""",
                (slot,),
            ).fetchone()
        if row is None:
            return None
        ad = dict(row)
        ad["is_active"] = True
        return ad

    def list_admin_ads(
        self,
        page: int,
        page_size: int,
        active: bool | None,
        placement: str | None,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if active is not None:
            clauses.append("is_active=?")
            params.append(int(active))
        if placement is not None:
            clauses.append("placement=?")
            params.append(placement)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            total = int(
                connection.execute(f"SELECT COUNT(*) FROM ads {where}", params).fetchone()[0]
            )
            rows = connection.execute(
                f"""SELECT * FROM ads {where}
                    ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?""",
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["is_active"] = bool(item["is_active"])
        return items, total

    def update_ad(
        self,
        ad_id: str,
        *,
        title: str | None,
        link_url: str | None,
        placement: str | None,
        is_active: bool | None,
    ) -> dict[str, Any] | None:
        assignments: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("title", title),
            ("link_url", link_url),
            ("placement", placement),
        ):
            if value is not None:
                assignments.append(f"{column}=?")
                params.append(value)
        if is_active is not None:
            assignments.append("is_active=?")
            params.append(int(is_active))
        assignments.append("updated_at=?")
        params.append(utc_now())
        with self.transaction(immediate=True) as connection:
            cursor = connection.execute(
                f"UPDATE ads SET {','.join(assignments)} WHERE id=?", [*params, ad_id]
            )
            if cursor.rowcount == 0:
                return None
        return self.get_ad(ad_id)

    def delete_ad(self, ad_id: str) -> dict[str, Any] | None:
        with self.transaction(immediate=True) as connection:
            row = connection.execute("SELECT * FROM ads WHERE id=?", (ad_id,)).fetchone()
            if row is None:
                return None
            connection.execute("DELETE FROM ads WHERE id=?", (ad_id,))
        ad = dict(row)
        ad["is_active"] = bool(ad["is_active"])
        return ad

    def record_ad_event(self, ad_id: str, event: str) -> bool:
        column = {"impression": "impressions", "click": "clicks"}[event]
        with self.transaction(immediate=True) as connection:
            cursor = connection.execute(
                f"UPDATE ads SET {column}={column}+1 WHERE id=? AND is_active=1",
                (ad_id,),
            )
        return cursor.rowcount > 0

    def promote_admin(self, user_id: str) -> None:
        with self.transaction(immediate=True) as connection:
            connection.execute("UPDATE users SET role='admin',is_active=1 WHERE id=?", (user_id,))

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
