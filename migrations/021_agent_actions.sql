-- A-04: requester-approved retry correlation; no financial authority is cached.
CREATE TABLE agent_actions (
    action_key text PRIMARY KEY CHECK (length(action_key) = 64),
    tenant_id text NOT NULL,
    actor_id text NOT NULL,
    session_id text NOT NULL,
    conversation_id text NOT NULL,
    scenario_run_no integer NOT NULL CHECK (scenario_run_no >= 0),
    proposal jsonb NOT NULL CHECK (jsonb_typeof(proposal) = 'object'
                                 AND octet_length(proposal::text) <= 4096),
    intent_id text NOT NULL,
    terms_hash text NOT NULL,
    execution_key text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX agent_actions_scope
    ON agent_actions(tenant_id, actor_id, session_id, conversation_id);
CREATE TRIGGER agent_actions_no_change BEFORE UPDATE OR DELETE ON agent_actions
    FOR EACH ROW EXECUTE FUNCTION agent_runs_immutable();
