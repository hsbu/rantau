-- C: what the university received, and reconciliation cases for payments it could not match.
CREATE TABLE university_receipts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    alias text NOT NULL,
    provider_reference text NOT NULL,
    transfer_alias text NOT NULL,
    obligation_alias text NOT NULL,
    received_minor bigint NOT NULL CHECK (received_minor > 0),
    payer_reference_text text,
    match_status text NOT NULL CHECK (match_status IN ('MATCHED', 'UNMATCHED', 'POSTED', 'RECONCILED')),
    matched_student_id text,
    post_after timestamptz NOT NULL,
    window_deadline timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id, alias),
    UNIQUE (tenant_id, provider_reference),
    UNIQUE (tenant_id, transfer_alias)
);
CREATE VIEW unmatched_payments AS
    SELECT * FROM university_receipts WHERE match_status = 'UNMATCHED';

CREATE TABLE reconciliation_cases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    alias text NOT NULL,
    transfer_alias text NOT NULL,
    obligation_alias text NOT NULL,
    state text NOT NULL CHECK (state IN (
        'OPEN', 'EVIDENCE_REQUIRED', 'READY', 'SUBMITTED', 'UNDER_REVIEW', 'RESOLVED',
        'REJECTED', 'NEEDS_INFO', 'ESCALATED'
    )),
    version bigint NOT NULL DEFAULT 1,
    evidence_missing text[] NOT NULL DEFAULT '{}',
    submitted_by text NOT NULL,
    reviewer_decision text,
    reviewer_reason text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id, alias)
);
CREATE UNIQUE INDEX reconciliation_one_active_case
    ON reconciliation_cases (tenant_id, transfer_alias)
    WHERE state NOT IN ('RESOLVED', 'REJECTED', 'ESCALATED');

CREATE TABLE reconciliation_evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    alias text NOT NULL,
    case_alias text NOT NULL,
    kind text NOT NULL CHECK (kind IN (
        'RECEIPT', 'PROVIDER_REFERENCE', 'AMOUNT', 'STUDENT_REFERENCE_CLAIM'
    )),
    source text NOT NULL CHECK (source IN ('SYSTEM_VERIFIED', 'USER_SUPPLIED')),
    data_digest text NOT NULL,
    UNIQUE (tenant_id, alias),
    UNIQUE (tenant_id, case_alias, kind)
);
