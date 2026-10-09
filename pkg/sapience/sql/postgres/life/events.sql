SELECT
    ordinal,
    id,
    payload
FROM sapience_life_events
WHERE namespace = %(namespace)s
ORDER BY ordinal;
