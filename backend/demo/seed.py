"""Seed one scenario through the same service code the application uses."""

from datetime import datetime, timedelta

from psycopg.types.json import Jsonb

from backend.authz.policy_repository import PolicyConnection
from backend.contracts.enums import FaultMode
from backend.demo.scenarios import (
    OBLIGATION_ALIAS,
    OBLIGATION_DUE_AT,
    OBLIGATION_DUE_MINOR,
    QUOTE_ALIASES,
    ROUTINE_THRESHOLD_MINOR,
    STUDENT_ID,
    TUITION_UNIVERSITY_ID,
    ScenarioSpec,
)
from backend.finance.clock import db_now
from backend.finance.provider import set_fault
from backend.finance.quotes import QuoteService
from backend.kb.catalog import load_bundle

# Validity is rebased onto the run's clock: the KB record uses a fictional November
# scenario clock, which the real database clock used by the policy gate would reject.
FIXTURE_VALIDITY_BEFORE = timedelta(days=1)
FIXTURE_VALIDITY_AFTER = timedelta(days=60)


def seed_scenario(connection: PolicyConnection, tenant_id: str, spec: ScenarioSpec) -> None:
    now = db_now(connection)
    _seed_accounts(connection, tenant_id, spec)
    _seed_beneficiaries(connection, tenant_id, spec)
    _seed_policy(connection, tenant_id, now, spec)
    _seed_obligation(connection, tenant_id, spec)
    _seed_faults(connection, tenant_id, spec)
    QuoteService(ttl_seconds=spec.quote_ttl_seconds).issue(
        connection, tenant_id, OBLIGATION_DUE_MINOR, QUOTE_ALIASES
    )


def _seed_accounts(connection: PolicyConnection, tenant_id: str, spec: ScenarioSpec) -> None:
    for account in spec.accounts:
        connection.execute(
            "INSERT INTO funding_accounts (tenant_id, alias, owner_id, currency, balance_minor, "
            "masked_number, timezone, per_transfer_limit_minor, daily_limit_minor, "
            "monthly_limit_minor, permitted_requesters) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                tenant_id,
                account.alias,
                account.owner_id,
                account.currency.value,
                account.balance_minor,
                f"•••• {account.alias[-4:]}",
                account.timezone,
                account.per_transfer_limit_minor,
                account.daily_limit_minor,
                account.monthly_limit_minor,
                list(account.permitted_requesters),
            ),
        )


def _seed_beneficiaries(connection: PolicyConnection, tenant_id: str, spec: ScenarioSpec) -> None:
    for beneficiary in spec.beneficiaries:
        connection.execute(
            "INSERT INTO beneficiaries (tenant_id, alias, owner_id, fingerprint, masked_display, "
            "verified) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                tenant_id,
                beneficiary.alias,
                TUITION_UNIVERSITY_ID,
                beneficiary.fingerprint,
                beneficiary.masked_display,
                beneficiary.verified,
            ),
        )


def _seed_policy(
    connection: PolicyConnection, tenant_id: str, now: datetime, spec: ScenarioSpec
) -> None:
    policy = load_bundle().simulation.policy.model_copy(
        update={
            "verified_at": now,
            "effective_from": now - FIXTURE_VALIDITY_BEFORE,
            "effective_to": now + FIXTURE_VALIDITY_AFTER,
            "id": spec.policy_id,
            "version": spec.policy_id,
            "topup_allowed": spec.topup_allowed,
        }
    )
    connection.execute(
        "INSERT INTO university_policies (tenant_id, alias, university_id, policy, synthetic) "
        "VALUES (%s, %s, %s, %s, true)",
        (tenant_id, policy.id, policy.university_id, Jsonb(policy.model_dump(mode="json"))),
    )
    connection.execute(
        "INSERT INTO payment_rules (tenant_id, version, effective_from, effective_to, "
        "routine_threshold_minor, purposes, currency_pairs) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            tenant_id,
            spec.policy_id,
            policy.effective_from,
            policy.effective_to,
            ROUTINE_THRESHOLD_MINOR,
            ["TUITION", "ALLOWANCE"],
            Jsonb([["IDR", "CNY"]]),
        ),
    )


def _seed_obligation(connection: PolicyConnection, tenant_id: str, spec: ScenarioSpec) -> None:
    connection.execute(
        "INSERT INTO tuition_obligations (tenant_id, alias, student_id, university_id, currency, "
        "amount_due_minor, due_at, policy_alias) VALUES (%s, %s, %s, %s, 'CNY', %s, %s, %s)",
        (
            tenant_id,
            OBLIGATION_ALIAS,
            STUDENT_ID,
            TUITION_UNIVERSITY_ID,
            OBLIGATION_DUE_MINOR,
            OBLIGATION_DUE_AT,
            spec.policy_id,
        ),
    )


def _seed_faults(connection: PolicyConnection, tenant_id: str, spec: ScenarioSpec) -> None:
    for provider, mode in spec.faults:
        set_fault(connection, tenant_id, provider, FaultMode(mode))
