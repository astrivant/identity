-- Immutable decision events and their exact replay inputs are separate from the lesson search index.
CREATE TABLE IF NOT EXISTS sapience_life_snapshots (
    namespace TEXT NOT NULL,
    id TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (namespace, id)
);

CREATE TABLE IF NOT EXISTS sapience_life_events (
    namespace TEXT NOT NULL,
    id TEXT NOT NULL,
    ordinal BIGINT NOT NULL CHECK (ordinal > 0),
    snapshot_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (namespace, id),
    UNIQUE (namespace, ordinal),
    FOREIGN KEY (namespace, snapshot_id) REFERENCES sapience_life_snapshots (namespace, id)
);
