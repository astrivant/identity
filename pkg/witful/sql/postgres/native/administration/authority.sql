-- Authority mutations are limited to fenced runtime registry transitions; grant administration stays separate.
REVOKE CREATE ON SCHEMA public FROM public;
REVOKE ALL ON witful_native_registry, witful_native_grants FROM %(role)s;
GRANT USAGE ON SCHEMA public TO %(role)s;
GRANT SELECT, UPDATE ON witful_native_registry TO %(role)s;
GRANT SELECT ON witful_native_grants TO %(role)s;
GRANT EXECUTE ON FUNCTION witful_native_admit_grant(UUID, UUID, UUID, UUID) TO %(role)s;
