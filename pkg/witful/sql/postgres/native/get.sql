SELECT
    id,
    payload
FROM witful_native_objects
WHERE tenant = %s AND identity_id = %s AND id = ANY(%s::uuid[]);
