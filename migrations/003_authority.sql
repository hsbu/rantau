-- B-03 authority storage approved 2026-10-17. No invented C ledger tables.
CREATE TABLE approvals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_id text NOT NULL,
    tenant_id text NOT NULL,
    owner_id text NOT NULL,
    intent_id text NOT NULL,
    intent_revision bigint NOT NULL CHECK (intent_revision > 0),
    terms_hash text NOT NULL CHECK (terms_hash ~ '^[0-9a-f]{64}$'),
    terms jsonb NOT NULL,
    review jsonb NOT NULL,
    state text NOT NULL CHECK (state IN ('REQUESTED','PENDING','APPROVED','REJECTED',
        'EXPIRED','REVOKED','INVALIDATED_BY_CHANGE','CONSUMED')),
    expires_at timestamptz NOT NULL,
    decision_actor_id text,
    recorded_at timestamptz,
    consumed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id, approval_id),
    CHECK ((state = 'CONSUMED') = (consumed_at IS NOT NULL)),
    CHECK (state NOT IN ('APPROVED','REJECTED','CONSUMED') OR
        (decision_actor_id = owner_id AND recorded_at IS NOT NULL AND decision_actor_id IS NOT NULL))
);
CREATE UNIQUE INDEX approvals_one_active_revision ON approvals (tenant_id, intent_id, intent_revision)
    WHERE state IN ('REQUESTED','PENDING','APPROVED');
CREATE INDEX approvals_owner ON approvals (tenant_id, owner_id, created_at DESC);
CREATE TABLE mandates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    mandate_id text NOT NULL,
    tenant_id text NOT NULL,
    owner_id text NOT NULL,
    account_id text NOT NULL,
    delegate_id text NOT NULL,
    beneficiary_id text NOT NULL,
    revision bigint NOT NULL CHECK (revision > 0),
    payload jsonb NOT NULL,
    source_label text NOT NULL,
    beneficiary_label text NOT NULL,
    account_timezone text NOT NULL,
    current boolean NOT NULL DEFAULT true,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id, mandate_id, revision)
);
CREATE UNIQUE INDEX mandates_one_current ON mandates (tenant_id, mandate_id) WHERE current;
CREATE UNIQUE INDEX mandates_one_active_recipient
    ON mandates (tenant_id, account_id, delegate_id, beneficiary_id)
    WHERE current AND revoked_at IS NULL;
CREATE TABLE authority_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_event_id text NOT NULL UNIQUE,
    tenant_id text NOT NULL,
    actor_id text NOT NULL,
    action text NOT NULL,
    resource_id text NOT NULL,
    state text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX authority_events_resource ON authority_events (tenant_id, resource_id, created_at);
CREATE FUNCTION protect_authority_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'authority_events' THEN
        RAISE EXCEPTION 'Authority events are append only';
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Authority history cannot be deleted';
    ELSIF TG_TABLE_NAME = 'approvals' THEN
        IF OLD.state IN ('REJECTED','EXPIRED','REVOKED','INVALIDATED_BY_CHANGE','CONSUMED')
            AND NEW.state IS DISTINCT FROM OLD.state THEN
            RAISE EXCEPTION 'Terminal approval cannot be reopened';
        END IF;
        IF OLD.state = 'APPROVED' AND NEW.state NOT IN
            ('APPROVED','CONSUMED','EXPIRED','REVOKED','INVALIDATED_BY_CHANGE') THEN
            RAISE EXCEPTION 'Owner decision cannot be replaced';
        END IF;
        IF OLD.state = 'PENDING' AND NEW.state = 'REQUESTED' THEN
            RAISE EXCEPTION 'Approval cannot move backwards';
        END IF;
        IF OLD.decision_actor_id IS NOT NULL AND
            (NEW.decision_actor_id,NEW.recorded_at) IS DISTINCT FROM
            (OLD.decision_actor_id,OLD.recorded_at) THEN
            RAISE EXCEPTION 'Owner decision is immutable';
        END IF;
        IF OLD.consumed_at IS NOT NULL AND NEW.consumed_at IS DISTINCT FROM OLD.consumed_at THEN
            RAISE EXCEPTION 'Consumption timestamp is immutable';
        END IF;
        IF (to_jsonb(NEW) - ARRAY['state','decision_actor_id','recorded_at','consumed_at'])
            IS DISTINCT FROM
            (to_jsonb(OLD) - ARRAY['state','decision_actor_id','recorded_at','consumed_at']) THEN
            RAISE EXCEPTION 'Approval terms are immutable';
        END IF;
    ELSE
        IF (NOT OLD.current AND NEW.current) OR (OLD.revoked_at IS NOT NULL AND
            NEW.revoked_at IS DISTINCT FROM OLD.revoked_at) THEN
            RAISE EXCEPTION 'Old mandate revision cannot be reopened';
        END IF;
        IF (to_jsonb(NEW) - ARRAY['current','revoked_at']) IS DISTINCT FROM
            (to_jsonb(OLD) - ARRAY['current','revoked_at']) THEN
            RAISE EXCEPTION 'Mandate revision is immutable';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER approvals_history BEFORE UPDATE OR DELETE ON approvals
    FOR EACH ROW EXECUTE FUNCTION protect_authority_history();
CREATE TRIGGER mandates_history BEFORE UPDATE OR DELETE ON mandates
    FOR EACH ROW EXECUTE FUNCTION protect_authority_history();
CREATE TRIGGER authority_events_history BEFORE UPDATE OR DELETE ON authority_events
    FOR EACH ROW EXECUTE FUNCTION protect_authority_history();
