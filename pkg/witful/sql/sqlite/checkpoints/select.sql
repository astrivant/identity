SELECT
    ordinal,
    id,
    project,
    revision,
    payload
FROM witful_checkpoints
WHERE namespace = :namespace
ORDER BY ordinal;
