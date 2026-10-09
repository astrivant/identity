SELECT
    id,
    payload
FROM witful_life_snapshots
WHERE namespace = %(namespace)s
ORDER BY id;
