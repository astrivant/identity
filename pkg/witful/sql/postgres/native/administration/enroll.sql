INSERT INTO witful_native_registry (tenant, identity_id, backend, epoch, policy_revision)
VALUES (%(tenant)s, %(identity)s, %(backend)s, 1, %(policy)s);
INSERT INTO witful_native_grants (
    tenant, identity_id, policy_revision, id, subject, task_id, actions, records, starts_at, expires
) VALUES (
    %(tenant)s, %(identity)s, %(policy)s, %(grant)s, %(subject)s, %(task)s,
    %(actions)s, %(records)s, %(starts)s, %(expires)s
);
