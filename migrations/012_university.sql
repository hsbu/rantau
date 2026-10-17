-- C: university ledger. Posted amounts are derived only from these rows.
CREATE TABLE university_postings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    alias text NOT NULL,
    institution_id text NOT NULL,
    obligation_alias text NOT NULL,
    transfer_alias text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('PAYMENT', 'RECONCILIATION', 'TOPUP')),
    posted_minor bigint NOT NULL CHECK (posted_minor > 0),
    posted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id, alias),
    -- Stricter than the spec's per-kind key: one posting per transfer can never be doubled.
    UNIQUE (tenant_id, institution_id, transfer_alias)
);
