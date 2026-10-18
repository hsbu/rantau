-- C: the simulated payment provider's own records (the "outside world"), kept apart from
-- Dev C's transfer rows so polling a reference returns evidence that survives restarts.
CREATE TABLE sim_provider_transfers (
    provider_reference text PRIMARY KEY,
    tenant_id text NOT NULL,
    provider text NOT NULL,
    amount_minor bigint NOT NULL CHECK (amount_minor > 0),
    destination_amount_minor bigint NOT NULL CHECK (destination_amount_minor > 0),
    status text NOT NULL CHECK (status IN ('ACCEPTED', 'DELIVERED', 'REJECTED_NO_DEBIT')),
    debited boolean NOT NULL,
    deliver_after timestamptz NOT NULL,
    payer_reference text,
    delivered_destination_minor bigint,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((status = 'REJECTED_NO_DEBIT') = (NOT debited))
);
CREATE TABLE sim_provider_faults (
    tenant_id text NOT NULL,
    provider text NOT NULL,
    mode text NOT NULL CHECK (mode IN (
        'DELAYED_DELIVERY', 'TIMEOUT_AFTER_ACCEPT', 'TIMEOUT_BEFORE_ACCEPT', 'UNAVAILABLE',
        'SHORT_PAYMENT', 'REFERENCE_MISSING'
    )),
    remaining integer NOT NULL CHECK (remaining >= 0),
    PRIMARY KEY (tenant_id, provider)
);
-- Which actors besides the owner may propose a payment from an account.
ALTER TABLE funding_accounts ADD COLUMN permitted_requesters text[] NOT NULL DEFAULT '{}';
