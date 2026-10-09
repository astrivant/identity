-- Populate only after all source rows exist; this index is replaced atomically, never edited in place.
INSERT INTO lesson_search (rowid, topic, lesson, source)
SELECT
    rowid,
    topic,
    lesson,
    source
FROM lessons;
