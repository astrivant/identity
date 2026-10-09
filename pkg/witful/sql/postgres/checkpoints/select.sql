SELECT
    ordinal,
    id,
    project,
    revision,
    payload
FROM witful_checkpoints
WHERE namespace = %(namespace)s
ORDER BY ordinal;
