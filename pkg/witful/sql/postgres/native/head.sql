SELECT
    generation,
    root,
    digest
FROM witful_native_heads
WHERE tenant = %s AND identity_id = %s;
