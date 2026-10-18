-- A-03-F1: team-approved scoped drafts and immutable, text-free run diagnostics.
CREATE TABLE agent_conversations (
    tenant_id text NOT NULL,
    actor_id text NOT NULL,
    session_id text NOT NULL REFERENCES auth_sessions(session_id) ON DELETE CASCADE,
    conversation_id text NOT NULL,
    schema_version integer NOT NULL DEFAULT 1 CHECK (schema_version > 0),
    revision bigint NOT NULL CHECK (revision > 0),
    scenario_run_no integer NOT NULL CHECK (scenario_run_no >= 0),
    state jsonb NOT NULL CHECK (jsonb_typeof(state) = 'object'
                              AND octet_length(state::text) <= 65536),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, actor_id, session_id, conversation_id),
    FOREIGN KEY (tenant_id, actor_id) REFERENCES actors(tenant_id, actor_id) ON DELETE CASCADE
);
CREATE INDEX agent_conversations_expiry ON agent_conversations(tenant_id, expires_at);

-- No cascading identity/session FK: revocation denies reads without erasing history.
CREATE TABLE agent_runs (
    run_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    actor_id text NOT NULL,
    session_id text NOT NULL,
    conversation_id text,
    scenario_run_no integer NOT NULL CHECK (scenario_run_no >= 0),
    metadata jsonb NOT NULL CHECK (jsonb_typeof(metadata) = 'object'
                                 AND octet_length(metadata::text) <= 32768),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX agent_runs_scope ON agent_runs(tenant_id, actor_id, session_id, created_at);
CREATE FUNCTION agent_runs_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'agent_runs is append-only';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER agent_runs_no_change BEFORE UPDATE OR DELETE ON agent_runs
    FOR EACH ROW EXECUTE FUNCTION agent_runs_immutable();
