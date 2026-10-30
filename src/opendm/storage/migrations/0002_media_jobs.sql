-- OpenDM schema v2: media (yt-dlp) jobs.

ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'http';  -- 'http' or 'media'
ALTER TABLE jobs ADD COLUMN media_options TEXT;                 -- JSON, media jobs only
