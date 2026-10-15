SELECT
    request_binding,
    receipt,
    generation,
    root,
    digest
FROM witful_native_operations
WHERE tenant = %s AND identity_id = %s AND operation_id = %s;
