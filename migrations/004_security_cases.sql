-- B-06 additive tenant-scoped security holds, cases and immutable audit events.
-- Resource aliases are resolved and locked by the trusted owner adapter; no
-- foreign keys point into Dev C's simulator schema.
CREATE TABLE security_holds (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    hold_id text NOT NULL,
    tenant_id text NOT NULL,
    resource_id text NOT NULL,
    reason_code text NOT NULL CHECK (reason_code IN (
        'UNKNOWN_BENEFICIARY','BENEFICIARY_MISMATCH','BENEFICIARY_CHANGE_REQUESTED',
        'PROMPT_INJECTION','SCAM_INDICATOR','POLICY_REVIEW'
    )),
    state text NOT NULL CHECK (state IN ('ACTIVE','CLEARED')),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    cleared_by text,
    cleared_at timestamptz,
    audit_event_id text NOT NULL UNIQUE,
    UNIQUE (tenant_id, hold_id),
    CHECK ((state = 'ACTIVE') = (cleared_by IS NULL AND cleared_at IS NULL)),
    CHECK ((cleared_by IS NULL) = (cleared_at IS NULL))
);
CREATE UNIQUE INDEX security_holds_one_active_resource
    ON security_holds (tenant_id, resource_id) WHERE state = 'ACTIVE';
CREATE INDEX security_holds_resource
    ON security_holds (tenant_id, resource_id, created_at DESC);

CREATE TABLE security_cases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id text NOT NULL,
    tenant_id text NOT NULL,
    resource_id text NOT NULL,
    reason_code text NOT NULL CHECK (reason_code IN (
        'UNKNOWN_BENEFICIARY','BENEFICIARY_MISMATCH','BENEFICIARY_CHANGE_REQUESTED',
        'PROMPT_INJECTION','SCAM_INDICATOR','POLICY_REVIEW'
    )),
    state text NOT NULL CHECK (state IN ('OPEN','UNDER_REVIEW','RESOLVED','ESCALATED')),
    evidence_ids text[] NOT NULL DEFAULT '{}',
    opened_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    audit_event_id text NOT NULL UNIQUE,
    UNIQUE (tenant_id, case_id),
    CHECK (cardinality(evidence_ids) <= 20),
    CHECK (array_position(evidence_ids, NULL) IS NULL)
);
CREATE INDEX security_cases_resource
    ON security_cases (tenant_id, resource_id, updated_at DESC);
CREATE INDEX security_cases_opener
    ON security_cases (tenant_id, opened_by, updated_at DESC);

CREATE TABLE security_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_event_id text NOT NULL UNIQUE,
    tenant_id text NOT NULL,
    actor_id text NOT NULL,
    action text NOT NULL CHECK (action IN (
        'HOLD_PLACED','HOLD_CLEARED','CASE_CREATED','CASE_REVIEWED'
    )),
    decision text NOT NULL CHECK (decision IN (
        'PLACE_HOLD','CLEAR_HOLD','OPEN_CASE','UNDER_REVIEW','RESOLVE_CASE','ESCALATE_CASE'
    )),
    resource_id text NOT NULL,
    reason_code text NOT NULL CHECK (reason_code IN (
        'UNKNOWN_BENEFICIARY','BENEFICIARY_MISMATCH','BENEFICIARY_CHANGE_REQUESTED',
        'PROMPT_INJECTION','SCAM_INDICATOR','POLICY_REVIEW'
    )),
    state text NOT NULL CHECK (state IN ('ACTIVE','CLEARED','OPEN','UNDER_REVIEW','RESOLVED','ESCALATED')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (
        (action = 'HOLD_PLACED' AND decision = 'PLACE_HOLD' AND state = 'ACTIVE') OR
        (action = 'HOLD_CLEARED' AND decision = 'CLEAR_HOLD' AND state = 'CLEARED') OR
        (action = 'CASE_CREATED' AND decision = 'OPEN_CASE' AND state = 'OPEN') OR
        (action = 'CASE_REVIEWED' AND decision = 'UNDER_REVIEW' AND state = 'UNDER_REVIEW') OR
        (action = 'CASE_REVIEWED' AND decision = 'RESOLVE_CASE' AND state = 'RESOLVED') OR
        (action = 'CASE_REVIEWED' AND decision = 'ESCALATE_CASE' AND state = 'ESCALATED')
    )
);
CREATE INDEX security_events_resource
    ON security_events (tenant_id, resource_id, created_at DESC);

CREATE FUNCTION protect_security_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'security_events' THEN
        RAISE EXCEPTION 'Security events are append only';
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Security history cannot be deleted';
    ELSIF TG_TABLE_NAME = 'security_holds' THEN
        IF OLD.state = 'CLEARED' AND NEW.state IS DISTINCT FROM OLD.state THEN
            RAISE EXCEPTION 'Cleared hold cannot be reopened';
        END IF;
        IF OLD.state = 'ACTIVE' AND NEW.state NOT IN ('ACTIVE','CLEARED') THEN
            RAISE EXCEPTION 'Invalid hold transition';
        END IF;
        IF (to_jsonb(NEW) - ARRAY['state','cleared_by','cleared_at','audit_event_id'])
            IS DISTINCT FROM
            (to_jsonb(OLD) - ARRAY['state','cleared_by','cleared_at','audit_event_id']) THEN
            RAISE EXCEPTION 'Hold terms are immutable';
        END IF;
        IF NEW.state = 'CLEARED' AND (NEW.cleared_by IS NULL OR NEW.cleared_at IS NULL) THEN
            RAISE EXCEPTION 'Hold clear requires reviewer and time';
        END IF;
    ELSE
        IF OLD.state = 'RESOLVED' AND NEW.state IS DISTINCT FROM OLD.state THEN
            RAISE EXCEPTION 'Resolved case cannot be reopened';
        END IF;
        IF NOT (
            (OLD.state = 'OPEN' AND NEW.state IN ('OPEN','UNDER_REVIEW','RESOLVED','ESCALATED')) OR
            (OLD.state = 'UNDER_REVIEW' AND NEW.state IN ('UNDER_REVIEW','RESOLVED','ESCALATED')) OR
            (OLD.state = 'ESCALATED' AND NEW.state IN ('ESCALATED','UNDER_REVIEW','RESOLVED')) OR
            (OLD.state = 'RESOLVED' AND NEW.state = 'RESOLVED')
        ) THEN
            RAISE EXCEPTION 'Invalid case transition';
        END IF;
        IF (to_jsonb(NEW) - ARRAY['state','updated_at','audit_event_id'])
            IS DISTINCT FROM
            (to_jsonb(OLD) - ARRAY['state','updated_at','audit_event_id']) THEN
            RAISE EXCEPTION 'Case facts are immutable';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER security_holds_history BEFORE UPDATE OR DELETE ON security_holds
    FOR EACH ROW EXECUTE FUNCTION protect_security_history();
CREATE TRIGGER security_cases_history BEFORE UPDATE OR DELETE ON security_cases
    FOR EACH ROW EXECUTE FUNCTION protect_security_history();
CREATE TRIGGER security_events_history BEFORE UPDATE OR DELETE ON security_events
    FOR EACH ROW EXECUTE FUNCTION protect_security_history();
