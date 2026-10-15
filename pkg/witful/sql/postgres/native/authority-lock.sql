SELECT
    backend,
    epoch,
    policy_revision,
    generation,
    root,
    digest,
    pending
FROM witful_native_registry
WHERE tenant = %s AND identity_id = %s FOR UPDATE;
