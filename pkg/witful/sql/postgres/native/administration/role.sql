-- Abort before schema changes unless the runtime is an existing independent unprivileged login.
-- A zero denominator is a failed role precondition, never a request to weaken this gate.
SELECT 1 / CASE WHEN EXISTS (
    SELECT 1 FROM pg_roles AS runtime_role
    WHERE
        runtime_role.rolname = %(name)s AND runtime_role.rolcanlogin
        AND NOT runtime_role.rolsuper AND NOT runtime_role.rolbypassrls
        AND NOT runtime_role.rolcreatedb AND NOT runtime_role.rolcreaterole AND NOT runtime_role.rolreplication
        AND runtime_role.rolname != current_user
        AND NOT EXISTS (
            SELECT 1 FROM pg_auth_members AS memberships
            WHERE memberships.member = runtime_role.oid
        )
        AND NOT EXISTS (
            SELECT 1 FROM pg_database AS database_entries
            WHERE database_entries.datname = current_database() AND database_entries.datdba = runtime_role.oid
        )
        AND NOT EXISTS (
            SELECT 1 FROM pg_class AS relations
            WHERE relations.relowner = runtime_role.oid
        )
) THEN 1 ELSE 0 END AS runtime_role_precondition;
