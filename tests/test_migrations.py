from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.db.repository import Repository


def test_voice_and_provider_migration_preserves_existing_tasks(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.sqlite3"
    migration_dir = Path(__file__).parents[1] / "backend" / "db" / "migrations"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.executescript((migration_dir / "0001_initial.sql").read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            ("0001_initial.sql", "2026-08-03T00:00:00Z"),
        )
        connection.execute(
            "INSERT INTO users(id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            ("user-1", "legacy@example.com", "unused", "2026-08-03T00:00:00Z"),
        )
        connection.execute(
            """
            INSERT INTO user_settings(
                user_id, default_aspect_ratio, default_duration_seconds,
                default_bgm_volume, preferred_voice, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("user-1", "16:9", 60, 0.2, "warm", "2026-08-03T00:00:00Z"),
        )
        connection.execute(
            """
            INSERT INTO video_tasks(
                id, user_id, thread_id, topic, target_duration_seconds, aspect_ratio,
                status, current_stage, completed_steps, bgm_default_volume,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-1",
                "user-1",
                "thread-1",
                "旧任务",
                60,
                "16:9",
                "completed",
                "completed",
                12,
                0.2,
                "2026-08-03T00:00:00Z",
                "2026-08-03T00:00:00Z",
            ),
        )
        connection.commit()

    Repository(database_path).initialize()

    with sqlite3.connect(database_path) as connection:
        settings = connection.execute(
            "SELECT preferred_voice FROM user_settings WHERE user_id = ?", ("user-1",)
        ).fetchone()
        task = connection.execute(
            "SELECT voice_id, provider_mode FROM video_tasks WHERE id = ?", ("task-1",)
        ).fetchone()
    assert settings == ("mimo_default",)
    assert task == ("mimo_default", "fake")
