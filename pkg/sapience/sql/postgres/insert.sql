-- Identical guidance retains its first observation time; a correction has its own content-derived ID.
INSERT INTO sapience_lessons (namespace, id, topic, lesson, provenance, observed_at, supersedes)
VALUES (%(namespace)s, %(id)s, %(topic)s, %(lesson)s, %(source)s, %(observed_at)s, %(supersedes)s)
ON CONFLICT (namespace, id) DO NOTHING;
