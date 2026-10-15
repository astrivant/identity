SELECT prepared_batch FROM witful_native_operations
WHERE tenant = %s AND identity_id = %s
ORDER BY generation LIMIT %s;
