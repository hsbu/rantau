-- B-02: additive minimal decision audit approved by the requester on 2026-10-17.
-- No financial balances, account IDs, approval payloads, tokens or chat content.
-- Actor aliases intentionally have no deletion cascade: identity/reset changes
-- must not silently erase audit history. B-06 owns the broader audit workflow.
CREATE TABLE policy_decisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_event_id text NOT NULL UNIQUE,
    tenant_id text NOT NULL,
    actor_id text NOT NULL,
    action text NOT NULL CHECK (action IN (
        'CREATE_INTENT', 'EXECUTE_PAYMENT', 'SUBMIT_RECONCILIATION'
    )),
    resource_id text,
    decision text NOT NULL CHECK (decision IN ('ALLOW','REQUIRE_APPROVAL','HOLD','DENY')),
    tier text NOT NULL CHECK (tier IN ('T0','T1','T2','T3')),
    reason_code text CHECK (reason_code IN (
        'INVALID_SCOPE','UNKNOWN_BENEFICIARY','BENEFICIARY_MISMATCH',
        'FUNDING_OWNER_APPROVAL_REQUIRED','APPROVAL_EXPIRED','APPROVAL_TERMS_MISMATCH',
        'QUOTE_EXPIRED','INSUFFICIENT_FUNDS','LIMIT_EXCEEDED','SECURITY_HOLD',
        'UNIVERSITY_POLICY_UNKNOWN','PROVIDER_OUTCOME_UNKNOWN','PAYMENT_ALREADY_SUBMITTED',
        'RECONCILIATION_NEEDS_INFO','POSTING_WINDOW_ACTIVE','TOPUP_NOT_PERMITTED'
    )),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((decision = 'ALLOW') = (reason_code IS NULL))
);
CREATE INDEX policy_decisions_resource ON policy_decisions (tenant_id, resource_id, created_at);
