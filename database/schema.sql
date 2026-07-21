-- ============================================================
-- YouTube English Video Auto Generator - Database Schema
-- ============================================================

CREATE TABLE IF NOT EXISTS phrases (
    id          SERIAL PRIMARY KEY,
    phrase      TEXT NOT NULL,
    example     TEXT NOT NULL,
    scene       TEXT NOT NULL,               -- 画像検索キーワード (例: "airport")
    topic       TEXT,                        -- グルーピング用 (例: "Travel English")
    uploaded    BOOLEAN NOT NULL DEFAULT FALSE,  -- Shorts等で使用済みか
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    used_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_phrases_uploaded ON phrases (uploaded);
CREATE INDEX IF NOT EXISTS idx_phrases_topic ON phrases (topic);

CREATE TABLE IF NOT EXISTS videos (
    id           SERIAL PRIMARY KEY,
    video_type   TEXT NOT NULL CHECK (video_type IN ('short', 'long')),
    title        TEXT NOT NULL,
    description  TEXT,
    tags         TEXT[],
    file_path    TEXT,
    thumbnail_path TEXT,
    youtube_video_id TEXT,
    uploaded     BOOLEAN NOT NULL DEFAULT FALSE,
    scheduled_at TIMESTAMPTZ,
    visibility   TEXT NOT NULL DEFAULT 'private',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_videos_uploaded ON videos (uploaded);

-- 動画とフレーズの紐付け（Long動画は複数フレーズを含むため多対多）
CREATE TABLE IF NOT EXISTS video_phrases (
    video_id   INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    phrase_id  INTEGER NOT NULL REFERENCES phrases(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (video_id, phrase_id)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          SERIAL PRIMARY KEY,
    run_date    DATE NOT NULL,
    video_type  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'started',
    video_id    INTEGER REFERENCES videos(id),
    error       TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);
