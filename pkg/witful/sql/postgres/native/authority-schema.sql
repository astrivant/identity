-- Install in an independently administered database using a migration role.
-- The runtime role receives SELECT/UPDATE on registry and SELECT on grants only.
CREATE TABLE IF NOT EXISTS witful_native_registry (
    tenant UUID NOT NULL,
    identity_id UUID NOT NULL,
    backend UUID NOT NULL,
    epoch BIGINT NOT NULL CHECK (epoch > 0),
    policy_revision UUID NOT NULL,
    generation BIGINT NOT NULL DEFAULT 0 CHECK (generation >= 0),
    root UUID,
    digest BYTEA NOT NULL DEFAULT ''::BYTEA,
    pending BYTEA,
    transition BYTEA,
    PRIMARY KEY (tenant, identity_id),
    CHECK (
        (generation = 0 AND root IS NULL AND octet_length(digest) = 0)
        OR (generation > 0 AND root IS NOT NULL AND octet_length(digest) = 32)
    )
);
-- Existing native deployments add the independent migration fence without changing retained history.
ALTER TABLE witful_native_registry ADD COLUMN IF NOT EXISTS transition BYTEA;

CREATE TABLE IF NOT EXISTS witful_native_grants (
    tenant UUID NOT NULL,
    identity_id UUID NOT NULL,
    policy_revision UUID NOT NULL,
    id UUID NOT NULL,
    subject TEXT NOT NULL CHECK (subject ~ '^[a-f0-9]{64}$'),
    task_id UUID NOT NULL,
    actions TEXT[] NOT NULL,
    records TEXT[] NOT NULL,
    starts_at BIGINT NOT NULL,
    expires BIGINT NOT NULL CHECK (expires > starts_at),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (tenant, identity_id, policy_revision, id),
    FOREIGN KEY (tenant, identity_id) REFERENCES witful_native_registry (tenant, identity_id)
);

-- Runtime admission can lock a grant against revocation without receiving permission to modify grants.
CREATE OR REPLACE FUNCTION witful_native_admit_grant(
    requested_tenant UUID,
    requested_identity UUID,
    requested_policy UUID,
    requested_grant UUID
) RETURNS SETOF WITFUL_NATIVE_GRANTS
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT * FROM public.witful_native_grants
    WHERE tenant = requested_tenant AND identity_id = requested_identity
        AND policy_revision = requested_policy AND id = requested_grant AND enabled
    FOR SHARE;
$$;
REVOKE ALL ON FUNCTION witful_native_admit_grant(UUID, UUID, UUID, UUID) FROM public;
