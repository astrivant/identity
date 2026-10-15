SELECT
    rolsuper,
    rolbypassrls
FROM pg_roles
WHERE rolname = current_user;
