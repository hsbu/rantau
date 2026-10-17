-- B-01: additive authentication tables approved by the requester on 2026-10-17.
-- Tenant + stable actor alias is the identity key consumed by existing ActorContext.
CREATE TABLE actors (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    actor_id text NOT NULL,
    role text NOT NULL CHECK (role IN ('STUDENT', 'SPONSOR', 'UNIVERSITY_SERVICE', 'DEMO_ADMIN')),
    scopes text[] NOT NULL DEFAULT '{}',
    active boolean NOT NULL DEFAULT true,
    UNIQUE (tenant_id, actor_id)
);
CREATE TABLE auth_credentials (
    tenant_id text NOT NULL,
    actor_id text NOT NULL,
    username text NOT NULL,
    password_hash text NOT NULL,
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    PRIMARY KEY (tenant_id, actor_id),
    UNIQUE (tenant_id, username),
    FOREIGN KEY (tenant_id, actor_id) REFERENCES actors (tenant_id, actor_id) ON DELETE CASCADE
);
CREATE TABLE auth_sessions (
    session_id text PRIMARY KEY,
    token_digest text NOT NULL UNIQUE CHECK (length(token_digest) = 64),
    tenant_id text NOT NULL,
    actor_id text NOT NULL,
    credential_version bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT now() + interval '1 hour',
    revoked_at timestamptz,
    FOREIGN KEY (tenant_id, actor_id) REFERENCES auth_credentials ON DELETE CASCADE
);
CREATE INDEX auth_sessions_actor ON auth_sessions (tenant_id, actor_id);
CREATE TABLE student_sponsor_consents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    student_id text NOT NULL,
    sponsor_id text NOT NULL,
    allowed_shared_fields text[] NOT NULL CHECK (
        cardinality(allowed_shared_fields) > 0 AND
        allowed_shared_fields <@ ARRAY['tuition_summary','payment_summary','case_summary']::text[]
    ),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    UNIQUE (tenant_id, student_id, sponsor_id),
    FOREIGN KEY (tenant_id, student_id) REFERENCES actors (tenant_id, actor_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, sponsor_id) REFERENCES actors (tenant_id, actor_id) ON DELETE CASCADE
);
CREATE TABLE auth_login_attempts (
    bucket text PRIMARY KEY,
    window_started timestamptz NOT NULL DEFAULT now(),
    attempts integer NOT NULL CHECK (attempts > 0)
);
CREATE INDEX auth_login_attempts_window ON auth_login_attempts (window_started);
