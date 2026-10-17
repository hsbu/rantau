from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.authz.policy import evaluate_payment, evaluate_reconciliation
from backend.authz.policy_models import ReconciliationSnapshot, SpendingEntry
from backend.contracts.enums import (
    ApprovalState,
    Currency,
    Decision,
    PaymentState,
    Role,
    Tier,
    TuitionState,
)
from backend.contracts.models import ServiceUnavailable
from tests.authz.policy_data import ACTION, ACTOR_EXECUTOR, allowance, approve, tuition
from tests.fixtures.data import NOW


def result(snapshot, actor=ACTOR_EXECUTOR, action=ACTION, now=NOW):
    return evaluate_payment(actor, action, snapshot, now)


def spent(amount, *, intent_id="previous_intent", state="RESERVED", at=NOW):
    return SpendingEntry(
        intent_id=intent_id,
        account_id="acct_idr_01",
        currency=Currency.IDR,
        amount_minor=amount,
        state=state,
        at=at,
    )


def test_tuition_requires_owner_approval_then_allows_exact_approved_terms():
    assert result(tuition()).decision == Decision.REQUIRE_APPROVAL
    allowed = result(approve(tuition()))
    assert (allowed.decision, allowed.tier, allowed.reason_code) == (Decision.ALLOW, Tier.T2, None)


def test_verified_allowance_under_current_mandate_is_t1():
    allowed = result(allowance())
    assert (allowed.decision, allowed.tier) == (Decision.ALLOW, Tier.T1)


@pytest.mark.parametrize(
    "change",
    [
        {"tenant_id": "other"},
        {"role": Role.DEMO_ADMIN},
        {"scopes": frozenset()},
        {"actor_id": "unrelated"},
    ],
)
def test_scope_and_identity_are_hard_denials(change):
    denied = result(approve(tuition()), actor=ACTOR_EXECUTOR.model_copy(update=change))
    assert (denied.decision, denied.reason_code) == (Decision.DENY, "INVALID_SCOPE")


@pytest.mark.parametrize(
    "part,updates",
    [
        ("account", {"owner_id": "another_owner"}),
        ("account", {"tenant_id": "other"}),
        ("account", {"id": "another_account"}),
        ("account", {"active": False}),
        ("account", {"owner_active": False}),
        ("account", {"currency": Currency.CNY}),
        ("intent", {"requested_by": "unrelated"}),
    ],
)
def test_funding_and_requester_bindings_cannot_be_forged(part, updates):
    snapshot = approve(tuition())
    snapshot = snapshot.model_copy(
        update={part: getattr(snapshot, part).model_copy(update=updates)}
    )
    assert result(snapshot).decision == Decision.DENY


@pytest.mark.parametrize(
    "state,reason",
    [
        (PaymentState.PROCESSING, "PAYMENT_ALREADY_SUBMITTED"),
        (PaymentState.DELIVERED, "PAYMENT_ALREADY_SUBMITTED"),
        (PaymentState.OUTCOME_UNKNOWN, "PROVIDER_OUTCOME_UNKNOWN"),
        (PaymentState.FAILED, "INVALID_SCOPE"),
        (PaymentState.CANCELLED, "INVALID_SCOPE"),
        (PaymentState.REJECTED, "INVALID_SCOPE"),
        (PaymentState.EXPIRED, "INVALID_SCOPE"),
    ],
)
def test_non_executable_states_never_allow_even_with_approval(state, reason):
    snapshot = approve(tuition())
    outcome = result(
        snapshot.model_copy(update={"intent": snapshot.intent.model_copy(update={"state": state})})
    )
    assert outcome.decision == Decision.DENY and outcome.reason_code == reason


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"verified": False}, "UNKNOWN_BENEFICIARY"),
        ({"fingerprint": "changed"}, "BENEFICIARY_MISMATCH"),
        ({"id": "other_beneficiary"}, "BENEFICIARY_MISMATCH"),
        ({"owner_id": "other_owner"}, "BENEFICIARY_MISMATCH"),
    ],
)
def test_beneficiary_trust_cannot_be_downgraded_by_approval(updates, reason):
    snapshot = approve(tuition())
    snapshot = snapshot.model_copy(
        update={"beneficiary": snapshot.beneficiary.model_copy(update=updates)}
    )
    outcome = result(snapshot)
    assert (outcome.decision, outcome.tier, outcome.reason_code) == (Decision.HOLD, Tier.T3, reason)


@pytest.mark.parametrize(
    "change",
    [
        {"held": True},
        {"risk_floor": Tier.T3},
    ],
)
def test_holds_and_risk_floor_override_legitimate_approval(change):
    outcome = result(approve(tuition()).model_copy(update=change))
    assert (outcome.decision, outcome.tier, outcome.reason_code) == (
        Decision.HOLD,
        Tier.T3,
        "SECURITY_HOLD",
    )


def test_on_hold_payment_is_held_without_separate_hold_flag():
    snapshot = approve(tuition())
    snapshot = snapshot.model_copy(
        update={"intent": snapshot.intent.model_copy(update={"state": PaymentState.ON_HOLD})}
    )
    assert result(snapshot).decision == Decision.HOLD


@pytest.mark.parametrize(
    "field,value",
    [
        ("intent_id", "other"),
        ("intent_revision", 2),
        ("funding_owner_id", "other"),
        ("source_account_id", "other"),
        ("beneficiary_id", "other"),
        ("beneficiary_fingerprint", "other"),
        ("purpose", "ALLOWANCE"),
        ("obligation_id", "other"),
        ("source_currency", Currency.CNY),
        ("destination_currency", Currency.IDR),
        ("source_total_minor", 1),
        ("destination_amount_minor", 1),
        ("quote_id", "other"),
        ("quote_expiry", NOW),
        ("policy_version", "other"),
        ("terms_hash", "other"),
    ],
)
def test_every_immutable_approval_field_is_compared(field, value):
    snapshot = approve(tuition(), **{field: value})
    outcome = result(snapshot)
    assert outcome.decision == Decision.REQUIRE_APPROVAL
    assert outcome.reason_code == "APPROVAL_TERMS_MISMATCH"


@pytest.mark.parametrize(
    "state", [state for state in ApprovalState if state != ApprovalState.APPROVED]
)
def test_only_current_unconsumed_approved_authority_is_usable(state):
    assert result(approve(tuition(), state=state)).decision == Decision.REQUIRE_APPROVAL


def test_expiry_is_exclusive_and_owner_cannot_be_replaced_by_student_or_sponsor():
    assert result(approve(tuition(), expires_at=NOW)).reason_code == "APPROVAL_EXPIRED"
    assert result(approve(tuition(), approver_actor_id="stu_001")).decision != Decision.ALLOW
    snapshot = approve(tuition())
    intent = snapshot.intent.model_copy(update={"funding_owner_id": "stu_001"})
    account = snapshot.account.model_copy(update={"owner_id": "stu_001"})
    own = snapshot.model_copy(update={"intent": intent, "account": account})
    assert result(own).decision != Decision.ALLOW
    assert result(approve(own)).decision == Decision.ALLOW


@pytest.mark.parametrize(
    "updates",
    [
        {"revoked": True},
        {"expires_at": NOW},
        {"starts_at": NOW + timedelta(seconds=1)},
        {"owner_id": "other"},
        {"delegate_id": "other"},
        {"account_id": "other"},
        {"beneficiary_id": "other"},
        {"beneficiary_fingerprint": "other"},
        {"currency": Currency.CNY},
        {"purpose": "TUITION"},
        {"per_transfer_limit_minor": 1},
    ],
)
def test_missing_or_ineligible_mandate_requires_exact_t2_approval(updates):
    snapshot = allowance()
    snapshot = snapshot.model_copy(update={"mandate": snapshot.mandate.model_copy(update=updates)})
    outcome = result(snapshot)
    assert (outcome.decision, outcome.tier) == (Decision.REQUIRE_APPROVAL, Tier.T2)
    assert result(approve(snapshot)).decision == Decision.ALLOW


def test_missing_mandate_and_routine_threshold_require_t2():
    snapshot = allowance()
    assert result(snapshot.model_copy(update={"mandate": None})).tier == Tier.T2
    snapshot = snapshot.model_copy(
        update={"rules": snapshot.rules.model_copy(update={"routine_threshold_minor": 1})}
    )
    assert result(snapshot).decision == Decision.REQUIRE_APPROVAL


def test_risk_floor_raises_t1_to_t2_but_never_waives_approval():
    snapshot = allowance().model_copy(update={"risk_floor": Tier.T2})
    assert result(snapshot).decision == Decision.REQUIRE_APPROVAL
    assert result(approve(snapshot)).decision == Decision.ALLOW


@pytest.mark.parametrize("kind,tier", [("allowance", Tier.T1), ("tuition", Tier.T2)])
def test_balance_and_quote_rejections_preserve_effective_policy_tier(kind, tier):
    snapshot = allowance() if kind == "allowance" else approve(tuition())
    insufficient = snapshot.model_copy(
        update={"account": snapshot.account.model_copy(update={"available_minor": 0})}
    )
    assert result(insufficient).tier == tier
    assert result(insufficient).decision == Decision.DENY
    assert result(snapshot, now=NOW + timedelta(minutes=15)).tier == tier


@pytest.mark.parametrize("state", ["COMPLETED", "RESERVED"])
def test_cumulative_completed_and_reserved_spending_blocks_split_attempts(state):
    snapshot = allowance()
    snapshot = snapshot.model_copy(update={"spending": (spent(60_000_000, state=state),)})
    assert result(snapshot).decision == Decision.REQUIRE_APPROVAL
    capped = snapshot.model_copy(
        update={"account": snapshot.account.model_copy(update={"daily_limit_minor": 100_000_000})}
    )
    assert result(approve(capped)).reason_code == "LIMIT_EXCEEDED"


def test_current_reservation_is_counted_once_and_does_not_require_second_balance():
    snapshot = allowance()
    amount = snapshot.intent.source_total_minor
    snapshot = snapshot.model_copy(
        update={
            "account": snapshot.account.model_copy(
                update={
                    "available_minor": 0,
                    "daily_limit_minor": amount,
                    "monthly_limit_minor": amount,
                }
            ),
            "spending": (spent(amount, intent_id=snapshot.intent.id),),
        }
    )
    assert result(snapshot).decision == Decision.ALLOW
    other = snapshot.model_copy(update={"spending": (spent(amount),)})
    assert result(other).reason_code == "INSUFFICIENT_FUNDS"


def test_completed_current_intent_or_changed_reservation_never_reexecutes():
    snapshot = allowance()
    with pytest.raises(ServiceUnavailable):
        result(snapshot.model_copy(update={"spending": (spent(1, intent_id=snapshot.intent.id),)}))
    outcome = result(
        snapshot.model_copy(
            update={
                "spending": (
                    spent(
                        snapshot.intent.source_total_minor,
                        intent_id=snapshot.intent.id,
                        state="COMPLETED",
                    ),
                )
            }
        )
    )
    assert outcome.decision == Decision.DENY


@pytest.mark.parametrize(
    "field", ["daily_limit_minor", "monthly_limit_minor", "per_transfer_limit_minor"]
)
def test_approval_cannot_override_hard_account_caps(field):
    snapshot = approve(tuition())
    snapshot = snapshot.model_copy(
        update={"account": snapshot.account.model_copy(update={field: 1})}
    )
    assert result(snapshot).reason_code == "LIMIT_EXCEEDED"


def test_timezone_controls_day_and_month_rollover_not_utc_date():
    snapshot = allowance()
    now = datetime(2026, 10, 31, 18, tzinfo=UTC)  # Nov 1, 01:00 in Jakarta.
    earlier = now - timedelta(hours=2)  # Oct 31, 23:00 in Jakarta.
    snapshot = snapshot.model_copy(
        update={
            "spending": (spent(145_000_000, at=earlier),),
            "quote": snapshot.quote.model_copy(update={"expires_at": now + timedelta(minutes=5)}),
            "intent": snapshot.intent.model_copy(
                update={"quote_expiry": now + timedelta(minutes=5)}
            ),
        }
    )
    assert result(snapshot, now=now).decision == Decision.ALLOW
    same_period = snapshot.model_copy(update={"spending": (spent(145_000_000, at=now),)})
    assert result(same_period, now=now).decision == Decision.REQUIRE_APPROVAL


@pytest.mark.parametrize(
    "change",
    [
        {"id": "other"},
        {"source_total_minor": 1},
        {"destination_amount_minor": 1},
        {"source_currency": Currency.CNY},
        {"destination_currency": Currency.IDR},
        {"expires_at": NOW + timedelta(minutes=16)},
    ],
)
def test_quote_must_match_stored_intent_exactly(change):
    snapshot = approve(tuition())
    snapshot = snapshot.model_copy(update={"quote": snapshot.quote.model_copy(update=change)})
    assert result(snapshot).decision != Decision.ALLOW


def test_expired_quote_and_stale_hash_cannot_be_approved_away():
    assert (
        result(approve(tuition()), now=NOW + timedelta(minutes=15)).reason_code == "QUOTE_EXPIRED"
    )
    assert (
        result(approve(tuition()), action=ACTION.model_copy(update={"terms_hash": "old"})).decision
        != Decision.ALLOW
    )
    assert (
        result(
            approve(tuition()), action=ACTION.model_copy(update={"resource_id": "other"})
        ).decision
        == Decision.DENY
    )


@pytest.mark.parametrize(
    "part,updates",
    [
        ("rules", {"version": "old"}),
        ("rules", {"effective_to": NOW}),
        ("university_policy", {"certainty": "UNKNOWN"}),
        ("university_policy", {"effective_from": NOW + timedelta(seconds=1)}),
        ("university_policy", {"university_id": "other"}),
        ("university_policy", {"id": "other"}),
        ("obligation", {"id": "other"}),
        ("obligation", {"student_id": "other"}),
    ],
)
def test_tuition_requires_current_matching_obligation_and_policy(part, updates):
    snapshot = approve(tuition())
    snapshot = snapshot.model_copy(
        update={part: getattr(snapshot, part).model_copy(update=updates)}
    )
    assert result(snapshot).decision != Decision.ALLOW


@pytest.mark.parametrize(
    "updates",
    [
        {"purposes": frozenset({"ALLOWANCE"})},
        {"currency_pairs": frozenset({(Currency.CNY, Currency.IDR)})},
    ],
)
def test_disallowed_policy_purpose_or_currency_is_denied(updates):
    snapshot = approve(tuition())
    snapshot = snapshot.model_copy(update={"rules": snapshot.rules.model_copy(update=updates)})
    assert result(snapshot).decision == Decision.DENY


def test_unusable_spending_data_never_defaults_to_zero():
    snapshot = allowance()
    for entries in (
        (spent(1), spent(1)),
        (spent(1, at=NOW + timedelta(seconds=1)),),
        (spent(1).model_copy(update={"currency": Currency.CNY}),),
        (spent(1).model_copy(update={"account_id": "other"}),),
    ):
        with pytest.raises(ServiceUnavailable):
            result(snapshot.model_copy(update={"spending": entries}))


def test_inputs_require_exact_integer_money_and_real_timezone():
    account = tuition().account
    for change in (
        {"available_minor": 1.2},
        {"available_minor": True},
        {"timezone": "Imaginary/Zone"},
    ):
        with pytest.raises(ValidationError):
            type(account).model_validate(account.model_dump() | change)


def test_accounting_period_coverage_is_required_and_must_be_current():
    snapshot = allowance()
    for field in ("spending_day", "spending_month"):
        data = snapshot.model_dump()
        del data[field]
        with pytest.raises(ValidationError):
            type(snapshot).model_validate(data)
        with pytest.raises(ServiceUnavailable):
            result(snapshot.model_copy(update={field: NOW.date() - timedelta(days=1)}))


def test_changed_revision_requires_fresh_t2_approval_even_under_mandate():
    snapshot = allowance()
    snapshot = snapshot.model_copy(
        update={"intent": snapshot.intent.model_copy(update={"intent_revision": 2})}
    )
    assert result(snapshot).decision == Decision.REQUIRE_APPROVAL


@pytest.mark.parametrize(
    "balance,partial_allowed,decision",
    [
        (0, True, Decision.DENY),
        (1, True, Decision.DENY),
        (3_000_000, False, Decision.DENY),
        (3_000_000, True, Decision.ALLOW),
    ],
)
def test_current_tuition_balance_and_partial_payment_policy_are_enforced(
    balance, partial_allowed, decision
):
    snapshot = approve(tuition())
    amount_due = max(snapshot.obligation.amount_due_minor, balance)
    posted = amount_due - balance
    state = (
        TuitionState.PAID
        if balance == 0
        else TuitionState.PARTIALLY_POSTED
        if posted
        else TuitionState.UNPAID
    )
    obligation = type(snapshot.obligation).model_validate(
        snapshot.obligation.model_dump()
        | {
            "amount_due_minor": amount_due,
            "posted_minor": posted,
            "balance_minor": balance,
            "state": state,
        }
    )
    snapshot = snapshot.model_copy(
        update={
            "obligation": obligation,
            "university_policy": snapshot.university_policy.model_copy(
                update={"partial_payment_allowed": partial_allowed}
            ),
        }
    )
    assert result(snapshot).decision == decision


def test_reconciliation_only_allows_scoped_student_submission():
    snapshot = ReconciliationSnapshot(
        tenant_id="demo_001",
        case_id="case_001",
        student_id="stu_001",
        submission_allowed=True,
    )
    action = ACTION.model_copy(
        update={"action": "SUBMIT_RECONCILIATION", "resource_id": "case_001"}
    )
    assert evaluate_reconciliation(ACTOR_EXECUTOR, action, snapshot).decision == Decision.ALLOW
    for change in ({"tenant_id": "other"}, {"student_id": "other"}, {"submission_allowed": False}):
        assert (
            evaluate_reconciliation(
                ACTOR_EXECUTOR, action, snapshot.model_copy(update=change)
            ).decision
            == Decision.DENY
        )


@pytest.mark.parametrize("topup_allowed,decision", [(False, Decision.DENY), (True, Decision.ALLOW)])
def test_remaining_tuition_topup_obeys_institution_policy(topup_allowed, decision):
    snapshot = tuition()
    obligation = type(snapshot.obligation).model_validate(
        snapshot.obligation.model_dump()
        | {
            "amount_due_minor": 3_000_000,
            "posted_minor": 1_000_000,
            "balance_minor": 2_000_000,
            "state": TuitionState.PARTIALLY_POSTED,
        }
    )
    snapshot = approve(
        snapshot.model_copy(
            update={
                "obligation": obligation,
                "university_policy": snapshot.university_policy.model_copy(
                    update={
                        "topup_allowed": topup_allowed,
                    }
                ),
            }
        )
    )
    outcome = result(snapshot)
    assert outcome.decision == decision
    if not topup_allowed:
        assert outcome.reason_code == "TOPUP_NOT_PERMITTED"


def test_recovery_topup_must_equal_remaining_balance_even_if_partial_payments_are_allowed():
    snapshot = tuition()
    obligation = type(snapshot.obligation).model_validate(
        snapshot.obligation.model_dump()
        | {
            "amount_due_minor": 4_000_000,
            "posted_minor": 1_000_000,
            "balance_minor": 3_000_000,
            "state": TuitionState.PARTIALLY_POSTED,
        }
    )
    snapshot = approve(
        snapshot.model_copy(
            update={
                "obligation": obligation,
                "university_policy": snapshot.university_policy.model_copy(
                    update={
                        "topup_allowed": True,
                        "partial_payment_allowed": True,
                    }
                ),
            }
        )
    )
    assert result(snapshot).decision == Decision.DENY


@pytest.mark.parametrize(
    "state,reason",
    [
        (TuitionState.AWAITING_POSTING, "POSTING_WINDOW_ACTIVE"),
        (TuitionState.RECONCILIATION_PENDING, "RECONCILIATION_NEEDS_INFO"),
        (TuitionState.EXCEPTION, "RECONCILIATION_NEEDS_INFO"),
        (TuitionState.ESCALATED, "RECONCILIATION_NEEDS_INFO"),
    ],
)
def test_unresolved_obligation_holds_new_draft_even_with_exact_owner_approval(state, reason):
    snapshot = tuition()
    obligation = type(snapshot.obligation).model_validate(
        snapshot.obligation.model_dump() | {"state": state}
    )
    intent = snapshot.intent.model_copy(
        update={
            "id": "new_intent",
            "intent_id": "new_intent",
            "state": PaymentState.DRAFT,
        }
    )
    snapshot = approve(snapshot.model_copy(update={"obligation": obligation, "intent": intent}))
    action = ACTION.model_copy(update={"resource_id": intent.id})
    outcome = result(snapshot, action=action)
    assert (outcome.decision, outcome.reason_code) == (Decision.HOLD, reason)
