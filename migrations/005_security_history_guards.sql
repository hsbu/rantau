-- Preserve completed hold decisions, including reviewer identity, time and audit
-- reference. Additive guard keeps the already-versioned 004 checksum unchanged.
CREATE FUNCTION protect_cleared_security_hold() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.state = 'CLEARED' AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'Cleared hold facts are immutable';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER security_holds_cleared_history BEFORE UPDATE ON security_holds
    FOR EACH ROW EXECUTE FUNCTION protect_cleared_security_hold();
