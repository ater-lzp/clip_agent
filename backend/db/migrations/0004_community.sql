CREATE TABLE community_posts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES video_tasks(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    prompt_public INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE INDEX community_posts_visible_idx ON community_posts(is_deleted, created_at DESC, id DESC);
CREATE INDEX community_posts_owner_idx ON community_posts(user_id, created_at DESC);

CREATE TABLE post_tags (
    post_id TEXT NOT NULL REFERENCES community_posts(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY(post_id, tag)
);
CREATE INDEX post_tags_tag_idx ON post_tags(tag, post_id);

CREATE TABLE post_comments (
    id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL REFERENCES community_posts(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    parent_id TEXT REFERENCES post_comments(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX post_comments_post_idx ON post_comments(post_id, created_at DESC);

CREATE TABLE comment_likes (
    comment_id TEXT NOT NULL REFERENCES post_comments(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY(comment_id, user_id)
);

CREATE TABLE post_shares (
    id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL REFERENCES community_posts(id) ON DELETE CASCADE,
    sender_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    UNIQUE(post_id, sender_id, recipient_id)
);
CREATE INDEX post_shares_recipient_idx ON post_shares(recipient_id, created_at DESC);

CREATE TABLE post_favorites (
    post_id TEXT NOT NULL REFERENCES community_posts(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY(post_id, user_id)
);
CREATE INDEX post_favorites_user_idx ON post_favorites(user_id, created_at DESC);
