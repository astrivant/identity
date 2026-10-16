SELECT
    set_config('witful.tenant', %s, true) AS tenant_scope,
    set_config('witful.identity_id', %s, true) AS identity_scope;
