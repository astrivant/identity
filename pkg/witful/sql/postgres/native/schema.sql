CREATE TABLE IF NOT EXISTS witful_native_objects (
    tenant UUID NOT NULL,
    identity_id UUID NOT NULL,
    id UUID NOT NULL,
    payload BYTEA NOT NULL,
    PRIMARY KEY (tenant, identity_id, id)
);
CREATE TABLE IF NOT EXISTS witful_native_heads (
    tenant UUID NOT NULL,
    identity_id UUID NOT NULL,
    generation BIGINT NOT NULL DEFAULT 0 CHECK (generation >= 0),
    root UUID,
    digest BYTEA NOT NULL DEFAULT ''::BYTEA,
    PRIMARY KEY (tenant, identity_id),
    CHECK (
        (generation = 0 AND root IS NULL AND octet_length(digest) = 0)
        OR (generation > 0 AND root IS NOT NULL AND octet_length(digest) = 32)
    )
);
CREATE TABLE IF NOT EXISTS witful_native_operations (
    tenant UUID NOT NULL,
    identity_id UUID NOT NULL,
    operation_id UUID NOT NULL,
    request_binding BYTEA NOT NULL CHECK (octet_length(request_binding) = 32),
    receipt UUID NOT NULL,
    prepared_batch BYTEA NOT NULL,
    generation BIGINT NOT NULL,
    root UUID NOT NULL,
    digest BYTEA NOT NULL,
    PRIMARY KEY (tenant, identity_id, operation_id),
    UNIQUE (tenant, identity_id, generation),
    FOREIGN KEY (tenant, identity_id, receipt) REFERENCES witful_native_objects (tenant, identity_id, id)
);
CREATE TABLE IF NOT EXISTS witful_native_outbox (
    tenant UUID NOT NULL,
    identity_id UUID NOT NULL,
    id UUID NOT NULL,
    generation BIGINT NOT NULL,
    PRIMARY KEY (tenant, identity_id, id),
    FOREIGN KEY (tenant, identity_id, id) REFERENCES witful_native_objects (tenant, identity_id, id)
);
ALTER TABLE witful_native_objects ENABLE ROW LEVEL SECURITY;
ALTER TABLE witful_native_objects FORCE ROW LEVEL SECURITY;
ALTER TABLE witful_native_heads ENABLE ROW LEVEL SECURITY;
ALTER TABLE witful_native_heads FORCE ROW LEVEL SECURITY;
ALTER TABLE witful_native_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE witful_native_operations FORCE ROW LEVEL SECURITY;
ALTER TABLE witful_native_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE witful_native_outbox FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS witful_native_scope ON witful_native_objects;
CREATE POLICY witful_native_scope ON witful_native_objects
USING (
    tenant = current_setting('witful.tenant')::UUID
    AND identity_id = current_setting('witful.identity_id')::UUID
)
WITH CHECK (
    tenant = current_setting('witful.tenant')::UUID
    AND identity_id = current_setting('witful.identity_id')::UUID
);
DROP POLICY IF EXISTS witful_native_scope ON witful_native_heads;
CREATE POLICY witful_native_scope ON witful_native_heads
USING (
    tenant = current_setting('witful.tenant')::UUID
    AND identity_id = current_setting('witful.identity_id')::UUID
)
WITH CHECK (
    tenant = current_setting('witful.tenant')::UUID
    AND identity_id = current_setting('witful.identity_id')::UUID
);
DROP POLICY IF EXISTS witful_native_scope ON witful_native_operations;
CREATE POLICY witful_native_scope ON witful_native_operations
USING (
    tenant = current_setting('witful.tenant')::UUID
    AND identity_id = current_setting('witful.identity_id')::UUID
)
WITH CHECK (
    tenant = current_setting('witful.tenant')::UUID
    AND identity_id = current_setting('witful.identity_id')::UUID
);
DROP POLICY IF EXISTS witful_native_scope ON witful_native_outbox;
CREATE POLICY witful_native_scope ON witful_native_outbox
USING (
    tenant = current_setting('witful.tenant')::UUID
    AND identity_id = current_setting('witful.identity_id')::UUID
)
WITH CHECK (
    tenant = current_setting('witful.tenant')::UUID
    AND identity_id = current_setting('witful.identity_id')::UUID
);
