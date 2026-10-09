-- Corrections remain searchable with --history but stop guiding ordinary searches.
SELECT
    lessons.id,
    lessons.topic,
    lessons.lesson,
    lessons.source,
    lessons.observed_at,
    lessons.supersedes,
    EXISTS(
        SELECT 1 FROM lessons AS newer
        WHERE newer.supersedes = lessons.id
    ) AS superseded
FROM LESSON_SEARCH(:query) AS matches
INNER JOIN lessons ON matches.rowid = lessons.rowid
WHERE
    :history OR NOT EXISTS (
        SELECT 1 FROM lessons AS newer
        WHERE newer.supersedes = lessons.id
    )
ORDER BY matches.rank, lessons.observed_at, lessons.id
LIMIT :limit;
