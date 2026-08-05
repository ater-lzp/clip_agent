CREATE TABLE ads (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 80),
    link_url TEXT NOT NULL CHECK(length(link_url) BETWEEN 1 AND 2048),
    placement TEXT NOT NULL DEFAULT 'auto'
        CHECK(placement IN ('auto', 'history', 'community', 'new_task', 'task_detail')),
    image_relative_path TEXT NOT NULL,
    image_media_type TEXT NOT NULL
        CHECK(image_media_type IN ('image/jpeg', 'image/png', 'image/gif')),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    impressions INTEGER NOT NULL DEFAULT 0 CHECK(impressions >= 0),
    clicks INTEGER NOT NULL DEFAULT 0 CHECK(clicks >= 0),
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX ads_active_placement_created_idx
    ON ads(is_active, placement, created_at DESC, id DESC);
