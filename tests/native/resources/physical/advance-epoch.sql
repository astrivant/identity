UPDATE witful_native_registry SET epoch = epoch + 1
WHERE tenant = %s AND identity_id = %s;
