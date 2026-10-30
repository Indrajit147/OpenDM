-- OpenDM schema v1: queues, categories, jobs, settings.

CREATE TABLE queues (
    id             INTEGER PRIMARY KEY,
    name           TEXT    NOT NULL UNIQUE,
    max_concurrent INTEGER NOT NULL DEFAULT 3 CHECK (max_concurrent BETWEEN 1 AND 32),
    enabled        INTEGER NOT NULL DEFAULT 1,
    start_time     TEXT,                       -- "HH:MM", local time
    stop_time      TEXT,
    days           INTEGER NOT NULL DEFAULT 127,  -- bit 0 = Monday ... bit 6 = Sunday
    after_action   TEXT    NOT NULL DEFAULT 'none',
    position       INTEGER NOT NULL DEFAULT 0
);

INSERT INTO queues (id, name, position) VALUES (1, 'Main', 0);

CREATE TABLE categories (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL UNIQUE,
    extensions TEXT    NOT NULL DEFAULT '',    -- space-separated, lowercase, no dots
    folder     TEXT    NOT NULL DEFAULT '',    -- '' = base folder, relative = inside it
    fallback   INTEGER NOT NULL DEFAULT 0,
    position   INTEGER NOT NULL DEFAULT 0
);

INSERT INTO categories (name, extensions, folder, fallback, position) VALUES
    ('Video', 'mp4 mkv webm avi mov wmv flv m4v ts 3gp mpg mpeg', 'Video', 0, 0),
    ('Audio', 'mp3 m4a aac flac wav ogg opus wma', 'Audio', 0, 1),
    ('Documents', 'pdf doc docx xls xlsx ppt pptx odt ods odp txt rtf epub csv', 'Documents', 0, 2),
    ('Compressed', 'zip rar 7z tar gz bz2 xz zst tgz tar.gz tar.bz2 tar.xz iso', 'Compressed', 0, 3),
    ('Programs', 'exe msi msix appx apk', 'Programs', 0, 4),
    ('Other', '', '', 1, 5);

CREATE TABLE jobs (
    id            TEXT    PRIMARY KEY,
    url           TEXT    NOT NULL,
    dest_dir      TEXT    NOT NULL,
    filename      TEXT,
    final_path    TEXT,
    category_id   INTEGER REFERENCES categories (id) ON DELETE SET NULL,
    queue_id      INTEGER NOT NULL DEFAULT 1 REFERENCES queues (id) ON DELETE SET DEFAULT,
    position      INTEGER NOT NULL DEFAULT 0,
    state         TEXT    NOT NULL,
    message       TEXT    NOT NULL DEFAULT '',
    size          INTEGER,
    downloaded    INTEGER NOT NULL DEFAULT 0,
    connections   INTEGER,
    speed_limit   INTEGER,
    checksum      TEXT,
    verify_tls    INTEGER NOT NULL DEFAULT 1,
    referrer      TEXT,
    user_agent    TEXT,
    headers       TEXT    NOT NULL DEFAULT '{}',  -- JSON, non-secret headers only
    secrets       BLOB,                           -- DPAPI-encrypted cookies/auth headers
    relinked      INTEGER NOT NULL DEFAULT 0,
    error_kind    TEXT,
    error_message TEXT,
    sha256        TEXT,
    created_at    TEXT    NOT NULL,
    started_at    TEXT,
    completed_at  TEXT
);

CREATE INDEX jobs_by_queue ON jobs (queue_id, state, position);
CREATE INDEX jobs_by_state ON jobs (state, completed_at);

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL  -- JSON
);
