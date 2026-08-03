ALTER TABLE video_tasks
    ADD COLUMN voice_id TEXT NOT NULL DEFAULT 'mimo_default';

ALTER TABLE video_tasks
    ADD COLUMN provider_mode TEXT NOT NULL DEFAULT 'fake';

UPDATE user_settings
SET preferred_voice = 'mimo_default'
WHERE preferred_voice NOT IN (
    'mimo_default', '冰糖', '茉莉', '苏打', '白桦', 'Mia', 'Chloe', 'Milo', 'Dean'
);
