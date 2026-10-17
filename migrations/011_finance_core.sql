-- C: simulated funding accounts, quotes, intents, transfers and ledger.
-- Every table is tenant-scoped with a stable alias; money is integer minor units.
CREATE TABLE demo_state (
    tenant_id text PRIMARY KEY,
    run_no integer NOT NULL DEFAULT 0,
    scenario_id text NOT NULL,
    sim_offset_seconds bigint NOT NULL DEFAULT 0,
    reset_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE funding_accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    alias text NOT NULL,
    owner_id text NOT NULL,
    currency text NOT NULL CHECK (currency IN ('IDR', 'CNY')),
    balance_minor bigint NOT NULL CHECK (balance_minor >= 0),
    version bigint NOT NULL DEFAULT 1,
    masked_number text NOT NULL,
    timezone text NOT NULL,
    per_transfer_limit_minor bigint NOT NULL CHECK (per_transfer_limit_minor >= 0),
    daily_limit_minor bigint NOT NULL CHECK (daily_limit_minor >= 0),
    monthly_limit_minor bigint NOT NULL CHECK (monthly_limit_minor >= 0),
    active boolean NOT NULL DEFAULT true,
    UNIQUE (tenant_id, alias),
    FOREIGN KEY (tenant_id, owner_id) REFERENCES actors (tenant_id, actor_id)
);

CREATE TABLE beneficiaries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    alias text NOT NULL,
    owner_id text NOT NULL,
    fingerprint text NOT NULL,
    masked_display text NOT NULL,
    verified boolean NOT NULL,
    UNIQUE (tenant_id, alias)
);

CREATE TABLE university_policies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    alias text NOT NULL,
    university_id text NOT NULL,
    policy jsonb NOT NULL,
    synthetic boolean NOT NULL CHECK (synthetic),
    UNIQUE (tenant_id, alias)
);

CREATE TABLE payment_rules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    version text NOT NULL,
    effective_from timestamptz NOT NULL,
    effective_to timestamptz NOT NULL,
    routine_threshold_minor bigint NOT NULL CHECK (routine_threshold_minor >= 0),
    purposes text[] NOT NULL,
    currency_pairs jsonb NOT NULL,
    UNIQUE (tenant_id, version),
    CHECK (effective_from < effective_to)
);

CREATE TABLE tuition_obligations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    alias text NOT NULL,
    student_id text NOT NULL,
    university_id text NOT NULL,
    currency text NOT NULL CHECK (currency = 'CNY'),
    amount_due_minor bigint NOT NULL CHECK (amount_due_minor > 0),
    due_at timestamptz NOT NULL,
    policy_alias text NOT NULL,
    UNIQUE (tenant_id, alias),
    FOREIGN KEY (tenant_id, student_id) REFERENCES actors (tenant_id, actor_id)
);

CREATE TABLE fx_quotes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    alias text NOT NULL,
    provider text NOT NULL,
    source_currency text NOT NULL,
    destination_currency text NOT NULL,
    source_principal_minor bigint NOT NULL CHECK (source_principal_minor > 0),
    fee_minor bigint NOT NULL CHECK (fee_minor >= 0),
    source_total_minor bigint NOT NULL CHECK (source_total_minor > 0),
    destination_amount_minor bigint NOT NULL CHECK (destination_amount_minor > 0),
    rate text NOT NULL,
    expires_at timestamptz NOT NULL,
    estimated_delivery_at timestamptz NOT NULL,
    request_digest text NOT NULL,
    UNIQUE (tenant_id, alias),
    UNIQUE (tenant_id, provider, request_digest),
    CHECK (source_total_minor = source_principal_minor + fee_minor)
);

CREATE TABLE payment_intents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    alias text NOT NULL,
    requested_by text NOT NULL,
    funding_owner_id text NOT NULL,
    source_account_alias text NOT NULL,
    beneficiary_alias text NOT NULL,
    beneficiary_fingerprint text NOT NULL,
    obligation_alias text,
    purpose text NOT NULL CHECK (purpose IN ('TUITION', 'ALLOWANCE')),
    source_currency text NOT NULL,
    destination_currency text NOT NULL,
    source_total_minor bigint NOT NULL CHECK (source_total_minor > 0),
    destination_amount_minor bigint NOT NULL CHECK (destination_amount_minor > 0),
    quote_alias text NOT NULL,
    quote_expiry timestamptz NOT NULL,
    policy_version text NOT NULL,
    intent_revision integer NOT NULL DEFAULT 1 CHECK (intent_revision > 0),
    terms_hash text NOT NULL,
    tier text NOT NULL CHECK (tier IN ('T0', 'T1', 'T2', 'T3')),
    state text NOT NULL CHECK (state IN (
        'DRAFT', 'AWAITING_APPROVAL', 'AUTHORIZED', 'ON_HOLD', 'PROCESSING', 'DELIVERED',
        'FAILED', 'OUTCOME_UNKNOWN', 'REJECTED', 'EXPIRED', 'CANCELLED'
    )),
    version bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id, alias),
    CHECK (purpose <> 'TUITION' OR obligation_alias IS NOT NULL)
);

-- Approved terms must never be edited in place; a changed payment is a new intent.
CREATE FUNCTION payment_intents_terms_immutable() RETURNS trigger AS $$
BEGIN
    IF (NEW.requested_by, NEW.funding_owner_id, NEW.source_account_alias, NEW.beneficiary_alias,
        NEW.beneficiary_fingerprint, NEW.obligation_alias, NEW.purpose, NEW.source_currency,
        NEW.destination_currency, NEW.source_total_minor, NEW.destination_amount_minor,
        NEW.quote_alias, NEW.quote_expiry, NEW.policy_version, NEW.intent_revision, NEW.terms_hash)
       IS DISTINCT FROM
       (OLD.requested_by, OLD.funding_owner_id, OLD.source_account_alias, OLD.beneficiary_alias,
        OLD.beneficiary_fingerprint, OLD.obligation_alias, OLD.purpose, OLD.source_currency,
        OLD.destination_currency, OLD.source_total_minor, OLD.destination_amount_minor,
        OLD.quote_alias, OLD.quote_expiry, OLD.policy_version, OLD.intent_revision, OLD.terms_hash)
    THEN
        RAISE EXCEPTION 'payment intent terms are immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER payment_intents_terms_locked BEFORE UPDATE ON payment_intents
    FOR EACH ROW EXECUTE FUNCTION payment_intents_terms_immutable();

CREATE TABLE transfers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    alias text NOT NULL,
    intent_alias text NOT NULL,
    account_alias text NOT NULL,
    obligation_alias text,
    beneficiary_alias text NOT NULL,
    provider text NOT NULL,
    provider_reference text NOT NULL UNIQUE,
    state text NOT NULL CHECK (state IN ('PROCESSING', 'DELIVERED', 'FAILED', 'OUTCOME_UNKNOWN')),
    version bigint NOT NULL DEFAULT 1,
    source_total_minor bigint NOT NULL CHECK (source_total_minor > 0),
    destination_amount_minor bigint NOT NULL CHECK (destination_amount_minor > 0),
    delivered_destination_minor bigint CHECK (delivered_destination_minor >= 0),
    payer_reference text,
    receipt_reference text,
    provider_submitted_at timestamptz,
    blocks_obligation boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id, alias),
    UNIQUE (tenant_id, intent_alias)
);
-- At most one unresolved transfer per obligation, even for two concurrent intents.
CREATE UNIQUE INDEX transfers_one_unresolved_per_obligation
    ON transfers (tenant_id, obligation_alias) WHERE blocks_obligation;

CREATE TABLE ledger_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    transfer_alias text NOT NULL,
    leg text NOT NULL CHECK (leg IN (
        'DEBIT_FUNDING', 'CREDIT_CLEARING', 'CREDIT_FEE',
        'REV_DEBIT_CLEARING', 'REV_DEBIT_FEE', 'REV_CREDIT_FUNDING'
    )),
    account_ref text NOT NULL,
    direction text NOT NULL CHECK (direction IN ('DEBIT', 'CREDIT')),
    amount_minor bigint NOT NULL CHECK (amount_minor > 0),
    currency text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id, transfer_alias, leg)
);

CREATE TABLE spend_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id text NOT NULL,
    intent_alias text NOT NULL,
    account_alias text NOT NULL,
    amount_minor bigint NOT NULL CHECK (amount_minor > 0),
    currency text NOT NULL,
    state text NOT NULL CHECK (state IN ('COMPLETED', 'RELEASED')),
    at timestamptz NOT NULL DEFAULT clock_timestamp(),
    authority_ref text,
    UNIQUE (tenant_id, intent_alias)
);
CREATE INDEX spend_entries_account ON spend_entries (tenant_id, account_alias, at);

CREATE TABLE idempotency_keys (
    tenant_id text NOT NULL,
    actor_id text NOT NULL,
    key text NOT NULL,
    fingerprint text NOT NULL,
    intent_alias text NOT NULL,
    transfer_alias text NOT NULL,
    audit_event_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, actor_id, key)
);
