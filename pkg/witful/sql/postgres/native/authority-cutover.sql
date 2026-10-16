UPDATE witful_native_registry
SET backend = %s, epoch = epoch + 1, generation = %s, root = %s, digest = %s, transition = NULL
WHERE tenant = %s AND identity_id = %s;
