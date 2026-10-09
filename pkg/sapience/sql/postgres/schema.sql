-- Version one is additive and immutable. Future incompatible schemas need explicit migrations.
CREATE TABLE IF NOT EXISTS sapience_lessons (
    namespace TEXT NOT NULL,
    id TEXT NOT NULL,
    topic TEXT NOT NULL,
    lesson TEXT NOT NULL,
    provenance TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    supersedes TEXT,
    search_document TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('simple', topic || ' ' || lesson || ' ' || provenance)
    ) STORED,
    PRIMARY KEY (namespace, id),
    FOREIGN KEY (namespace, supersedes) REFERENCES sapience_lessons (namespace, id)
    DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS sapience_lessons_search ON sapience_lessons USING gin (search_document);
CREATE INDEX IF NOT EXISTS sapience_lessons_supersedes ON sapience_lessons (namespace, supersedes);
