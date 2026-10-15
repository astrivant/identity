-- This database is dedicated to native ciphertext; the runtime cannot create schema objects or delete history.
REVOKE CREATE ON SCHEMA public FROM public;
REVOKE ALL ON witful_native_objects, witful_native_heads, witful_native_operations, witful_native_outbox FROM %(role)s;
GRANT USAGE ON SCHEMA public TO %(role)s;
GRANT SELECT, INSERT ON witful_native_objects, witful_native_operations, witful_native_outbox TO %(role)s;
GRANT SELECT, INSERT, UPDATE ON witful_native_heads TO %(role)s;
