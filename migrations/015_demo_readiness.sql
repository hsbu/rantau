-- C: payer name for reference matching, allowance recipients, intent revisions and the
-- untrusted-document surface used by the attack scenarios.
ALTER TABLE tuition_obligations ADD COLUMN student_name text NOT NULL DEFAULT 'Demo Student';

ALTER TABLE beneficiaries
    ADD COLUMN purpose_type text NOT NULL DEFAULT 'TUITION'
        CHECK (purpose_type IN ('TUITION', 'ALLOWANCE')),
    ADD COLUMN student_id text;

-- A revision is a new immutable intent; the superseded one is cancelled, never edited.
ALTER TABLE payment_intents ADD COLUMN supersedes_alias text;

CREATE TABLE untrusted_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    alias text NOT NULL,
    student_id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('INVOICE', 'EMAIL', 'NOTICE')),
    title text NOT NULL CHECK (length(title) <= 200),
    body text NOT NULL CHECK (length(body) <= 4000),
    claimed_sender text NOT NULL CHECK (length(claimed_sender) <= 200),
    received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id, alias)
);
