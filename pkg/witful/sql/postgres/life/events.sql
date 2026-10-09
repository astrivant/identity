SELECT
    ordinal,
    id,
    payload
FROM witful_life_events
WHERE namespace = %(namespace)s
ORDER BY ordinal;
