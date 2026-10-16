-- Synthetic fault injection only: fail a selected child's final authority acknowledgment.
CREATE OR REPLACE FUNCTION witful_native_fail_derivation() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.identity_id::TEXT = TG_ARGV[0] AND NEW.generation > OLD.generation THEN
        RAISE EXCEPTION 'synthetic publication failure';
    END IF;
    RETURN NEW;
END;
$$;
