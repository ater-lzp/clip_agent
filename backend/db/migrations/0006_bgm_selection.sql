ALTER TABLE video_tasks ADD COLUMN uploaded_bgm_relative_path TEXT;
ALTER TABLE video_tasks ADD COLUMN uploaded_bgm_name TEXT;
ALTER TABLE video_tasks ADD COLUMN uploaded_bgm_duration_ms INTEGER;
ALTER TABLE video_tasks ADD COLUMN uploaded_bgm_checksum TEXT;
ALTER TABLE video_tasks ADD COLUMN selected_bgm_track_id TEXT;
ALTER TABLE video_tasks ADD COLUMN selected_bgm_name TEXT;
ALTER TABLE video_tasks ADD COLUMN selected_bgm_source TEXT;

ALTER TABLE reviews ADD COLUMN bgm_track_id TEXT;
ALTER TABLE reviews ADD COLUMN bgm_track_name TEXT;
ALTER TABLE reviews ADD COLUMN bgm_track_source TEXT;
