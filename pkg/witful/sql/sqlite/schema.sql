-- The database is a local search index rebuilt from the reviewed JSONL journal.
PRAGMA foreign_keys = ON;
PRAGMA user_version = 2;

CREATE TABLE lessons (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    lesson TEXT NOT NULL,
    source TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    supersedes TEXT REFERENCES lessons (id) DEFERRABLE INITIALLY DEFERRED
);

-- Use the source rowid as the FTS identity; content IDs remain outside searchable text.
CREATE VIRTUAL TABLE lesson_search USING fts5 (topic, lesson, source);
