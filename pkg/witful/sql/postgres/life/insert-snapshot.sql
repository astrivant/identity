INSERT INTO witful_life_snapshots (namespace, id, payload)
VALUES (%(namespace)s, %(id)s, %(payload)s)
ON CONFLICT (namespace, id) DO NOTHING;
