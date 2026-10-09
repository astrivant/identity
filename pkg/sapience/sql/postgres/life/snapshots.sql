SELECT
    id,
    payload
FROM sapience_life_snapshots
WHERE namespace = %(namespace)s
ORDER BY id;
