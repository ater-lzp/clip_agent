CREATE TABLE post_likes (
    post_id TEXT NOT NULL REFERENCES community_posts(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY(post_id, user_id)
);
CREATE INDEX post_likes_user_idx ON post_likes(user_id, created_at DESC);

CREATE TABLE user_follows (
    follower_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    followee_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY(follower_id, followee_id),
    CHECK(follower_id <> followee_id)
);
CREATE INDEX user_follows_followee_idx ON user_follows(followee_id, created_at DESC);
