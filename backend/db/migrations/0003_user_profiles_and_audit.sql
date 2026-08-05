ALTER TABLE users ADD COLUMN nickname TEXT;
ALTER TABLE users ADD COLUMN avatar_relative_path TEXT;

CREATE UNIQUE INDEX users_nickname_unique_idx
    ON users(nickname COLLATE NOCASE)
    WHERE nickname IS NOT NULL;

CREATE TABLE audit_logs (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    ip_address TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX audit_logs_user_created_idx ON audit_logs(user_id, created_at DESC);
