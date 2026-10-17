-- C: append-only audit trail for financial actions (MVP spec section 7).
-- Only allowlisted, redacted fields are written by backend.finance.audit.AuditWriter.
CREATE TABLE audit_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_event_id text NOT NULL UNIQUE,
    tenant_id text NOT NULL,
    run_no integer NOT NULL DEFAULT 0,
    actor_id text,
    action text NOT NULL,
    resource_type text NOT NULL,
    resource_id text,
    decision text,
    reason_code text,
    before_state jsonb,
    after_state jsonb,
    request_id text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX audit_events_resource ON audit_events (tenant_id, resource_id, created_at);
CREATE INDEX audit_events_run ON audit_events (tenant_id, run_no, created_at);

CREATE FUNCTION audit_events_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER audit_events_no_change BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_immutable();
