PRAGMA foreign_keys = ON;

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    csrf_hash TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX sessions_user_id_idx ON sessions(user_id);
CREATE INDEX sessions_expires_at_idx ON sessions(expires_at);

CREATE TABLE user_settings (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    default_aspect_ratio TEXT NOT NULL,
    default_duration_seconds INTEGER NOT NULL,
    default_bgm_volume REAL NOT NULL,
    preferred_voice TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE video_tasks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    target_duration_seconds INTEGER NOT NULL,
    aspect_ratio TEXT NOT NULL,
    status TEXT NOT NULL,
    current_stage TEXT NOT NULL,
    completed_steps INTEGER NOT NULL DEFAULT 0,
    script_version INTEGER NOT NULL DEFAULT 0,
    storyboard_version INTEGER NOT NULL DEFAULT 0,
    preview_version INTEGER NOT NULL DEFAULT 0,
    script_json TEXT,
    storyboard_json TEXT,
    timeline_json TEXT,
    preview_relative_path TEXT,
    final_relative_path TEXT,
    final_duration_ms INTEGER,
    bgm_added INTEGER,
    bgm_suggested_query TEXT,
    bgm_default_volume REAL NOT NULL DEFAULT 0.2,
    pending_command_json TEXT,
    error_code TEXT,
    error_message TEXT,
    error_retryable INTEGER,
    failed_stage TEXT,
    idempotency_key TEXT,
    request_fingerprint TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX video_tasks_owner_created_idx
    ON video_tasks(user_id, created_at DESC, id DESC);
CREATE UNIQUE INDEX video_tasks_owner_idempotency_idx
    ON video_tasks(user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE reviews (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES video_tasks(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    version INTEGER NOT NULL,
    action TEXT NOT NULL,
    feedback TEXT,
    volume REAL,
    created_at TEXT NOT NULL,
    UNIQUE(task_id, kind, version)
);
CREATE INDEX reviews_task_idx ON reviews(task_id, created_at);

