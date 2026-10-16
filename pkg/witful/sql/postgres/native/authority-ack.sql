UPDATE witful_native_registry SET generation = %s, root = %s, digest = %s, pending = NULL
WHERE tenant = %s AND identity_id = %s;
