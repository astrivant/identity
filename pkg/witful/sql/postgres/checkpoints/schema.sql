-- Additive schema: checkpoint history is independent of the rebuildable lesson index.
CREATE TABLE IF NOT EXISTS witful_checkpoints (
    namespace TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    id TEXT NOT NULL,
    project TEXT NOT NULL,
    revision TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (namespace, id),
    UNIQUE (namespace, ordinal)
);
CREATE INDEX IF NOT EXISTS witful_checkpoints_project ON witful_checkpoints (namespace, project, ordinal);
