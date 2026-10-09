SELECT
    lessons.id,
    lessons.topic,
    lessons.lesson,
    lessons.provenance,
    lessons.observed_at,
    lessons.supersedes,
    EXISTS(
        SELECT 1 FROM witful_lessons AS newer
        WHERE newer.namespace = lessons.namespace AND newer.supersedes = lessons.id
    ) AS superseded
FROM witful_lessons AS lessons
WHERE
    lessons.namespace = %(namespace)s
    AND lessons.search_document @@ PLAINTO_TSQUERY('simple', %(query)s)
    AND (%(history)s OR NOT EXISTS (
        SELECT 1 FROM witful_lessons AS newer
        WHERE newer.namespace = lessons.namespace AND newer.supersedes = lessons.id
    ))
ORDER BY
    TS_RANK(lessons.search_document, PLAINTO_TSQUERY('simple', %(query)s)) DESC,
    lessons.observed_at, lessons.id ASC
LIMIT %(limit)s;
