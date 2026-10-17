"""Deterministic walkthrough of the demo flows against the real services.

The sponsor's approval is SIMULATED here (Dev B's approval store is not connected). This tool
runs only in development/test and is never wired into the application.
"""

import argparse
from dataclasses import dataclass, field
from datetime import timedelta

from backend.authz.policy_models import MandateSnapshot
from backend.authz.policy_repository import PolicyConnection
from backend.authz.service import AuthService
from backend.authz.storage import Database
from backend.config import Settings
from backend.contracts.enums import ApprovalState, Tier
from backend.contracts.models import (
    ActorContext,
    Approval,
    CaseSubmission,
    IntentProposal,
    PaymentIntent,
    PaymentTerms,
)
from backend.demo.reset import DEMO_ENVIRONMENTS, reset_demo_fixture
from backend.demo.scenarios import BENEFICIARY_ALIAS, OBLIGATION_ALIAS
from backend.finance.authority import HoldState
from backend.finance.clock import db_now
from backend.finance.migrations import migrate_all
from backend.finance.outcomes import Created, Executed, Refused
from backend.finance.simclock import advance_sim_clock
from backend.finance.wiring import FinanceServices, build_services
from backend.university.ledger import settle_due

SIMULATED_APPROVAL_NOTE = "Sponsor approval is SIMULATED (Dev B approval store not connected)."
UNVERIFIED_PAYEE = "benef_unverified_01"
POSTING_HOURS = 25
FLOWS = ("happy", "hero", "attack")


class SimulatedSponsorApproval:
    """Stands in for the sponsor's authenticated approval for replay and demos only."""

    def __init__(self) -> None:
        self.approved: set[str] = set()

    def approval(self, connection: PolicyConnection, intent: PaymentIntent) -> Approval | None:
        if intent.id not in self.approved:
            return None
        terms = {name: getattr(intent, name) for name in PaymentTerms.model_fields}
        return Approval(
            **terms,
            id="approval_simulated",
            approver_actor_id=intent.funding_owner_id,
            expires_at=db_now(connection) + timedelta(minutes=10),
            state=ApprovalState.APPROVED,
        )

    def mandate(
        self, connection: PolicyConnection, intent: PaymentIntent
    ) -> MandateSnapshot | None:
        return None

    def hold(self, connection: PolicyConnection, intent: PaymentIntent) -> HoldState:
        return HoldState(held=False, risk_floor=Tier.T0)


@dataclass
class Report:
    flow: str
    steps: list[str] = field(default_factory=list)
    facts: dict[str, int | str] = field(default_factory=dict)

    def step(self, text: str) -> None:
        self.steps.append(text)


@dataclass
class Replay:
    services: FinanceServices
    approvals: SimulatedSponsorApproval
    student: ActorContext
    tenant_id: str

    def run(self, flow: str) -> Report:
        return {"happy": self.happy, "hero": self.hero, "attack": self.attack}[flow]()

    def happy(self) -> Report:
        report = Report("happy")
        self._reset(report, "tuition_happy_path")
        executed = self._pay(report)
        report.step(f"University state: {self._state()} (provider delivered is not tuition paid)")
        held = self.services.intents.create(self.student, self._proposal())
        assert isinstance(held, Created)
        report.step(
            f"Second payment attempt: {held.intent.state.value} ({held.decision.reason_code})"
        )
        self._advance_and_tick(report)
        report.step(f"University state: {self._state()}")
        self._facts(report, executed)
        return report

    def hero(self) -> Report:
        report = Report("hero")
        self._reset(report, "tuition_missing_reference")
        executed = self._pay(report)
        report.step(f"University state: {self._state()} (payment arrived without a reference)")
        held = self.services.intents.create(self.student, self._proposal())
        assert isinstance(held, Created)
        report.step(
            f"Second payment attempt: {held.intent.state.value} ({held.decision.reason_code})"
        )
        case = self.services.cases.create(
            self.student,
            CaseSubmission(
                payment_id=executed.payment_id, obligation_id=OBLIGATION_ALIAS, evidence_ids=()
            ),
        )
        report.step(f"Case {case.state.value}: evidence gathered from backend records")
        submitted = self.services.cases.submit(self.student, case.id)
        report.step(f"Case {submitted.state.value}; university state: {self._state()}")
        self.services.review.review_submitted(self.tenant_id)
        report.step(f"University review done; state: {self._state()}")
        self._facts(report, executed)
        return report

    def attack(self) -> Report:
        report = Report("attack")
        self._reset(report, "forged_beneficiary")
        documents = self.services.reads.documents(self.student)
        report.step(f"Untrusted documents shown as data only: {len(documents)}")
        forged = self.services.intents.create(
            self.student, self._proposal(beneficiary=UNVERIFIED_PAYEE)
        )
        assert isinstance(forged, Created)
        report.step(
            f"Forged payee intent: {forged.intent.state.value} ({forged.decision.reason_code})"
        )
        self._authorize(forged.intent.id)
        blocked = self.services.executor.execute(self.student, forged.intent.id, "replay-forged")
        assert isinstance(blocked, Refused)
        report.step(f"Execution of the forged payee: refused ({blocked.reason_code.value})")
        legitimate = self._pay(report, "replay-legit")
        self._facts(report, legitimate)
        return report

    def _reset(self, report: Report, scenario: str) -> None:
        run_no = reset_demo_fixture(self.services.database, self.tenant_id, scenario)
        self.approvals.approved.clear()
        report.step(f"Reset scenario {scenario} (run {run_no})")

    def _proposal(self, beneficiary: str = BENEFICIARY_ALIAS) -> IntentProposal:
        quote = self.services.reads.quotes(self.student, OBLIGATION_ALIAS)[0]
        return IntentProposal(
            obligation_id=OBLIGATION_ALIAS,
            source_account_id="acct_idr_01",
            beneficiary_id=beneficiary,
            quote_id=quote.id,
            purpose="TUITION",
        )

    def _pay(self, report: Report, key: str = "replay-pay") -> Executed:
        created = self.services.intents.create(self.student, self._proposal())
        assert isinstance(created, Created)
        report.step(f"Intent {created.intent.state.value}: sponsor approval required")
        self._authorize(created.intent.id)
        report.step(SIMULATED_APPROVAL_NOTE)
        executed = self.services.executor.execute(self.student, created.intent.id, key)
        assert isinstance(executed, Executed)
        report.step(f"Provider status: {executed.transfer_state.value}")
        return executed

    def _authorize(self, intent_alias: str) -> None:
        self.approvals.approved.add(intent_alias)
        with self.services.database.connection() as connection:
            connection.execute(
                "UPDATE payment_intents SET state = 'AUTHORIZED' "
                "WHERE tenant_id = %s AND alias = %s AND state IN ('AWAITING_APPROVAL', 'ON_HOLD')",
                (self.tenant_id, intent_alias),
            )

    def _advance_and_tick(self, report: Report) -> None:
        with self.services.database.connection() as connection:
            advance_sim_clock(connection, self.tenant_id, POSTING_HOURS * 3600)
            posted = settle_due(connection, self.tenant_id)
        report.step(f"Simulated clock +{POSTING_HOURS}h; university posted {posted} receipt(s)")

    def _state(self) -> str:
        return self.services.obligations.get(self.student, OBLIGATION_ALIAS).state.value

    def _facts(self, report: Report, executed: Executed) -> None:
        db = self.services.database
        with db.connection() as connection:

            def count(sql: str) -> int:
                row = connection.execute(sql).fetchone()
                assert row is not None
                return int(next(iter(row.values())))

            report.facts = {
                "transfers": count("SELECT count(*) FROM transfers"),
                "debit_legs": count(
                    "SELECT count(*) FROM ledger_entries WHERE leg = 'DEBIT_FUNDING'"
                ),
                "postings": count("SELECT count(*) FROM university_postings"),
                "audit_events_this_run": count(
                    "SELECT count(*) FROM audit_events a JOIN demo_state d "
                    "ON d.tenant_id = a.tenant_id AND d.run_no = a.run_no"
                ),
                "tuition_state": self._state(),
                "provider_status": executed.transfer_state.value,
            }


def build_replay(database: Database, auth: AuthService, student: ActorContext) -> Replay:
    approvals = SimulatedSponsorApproval()
    services = build_services(database, auth, approvals)
    return Replay(services, approvals, student, student.tenant_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay the Rantau demo flows (development only)")
    parser.add_argument("--flow", choices=(*FLOWS, "all"), default="all")
    args = parser.parse_args()
    settings = Settings()
    if settings.app_env not in DEMO_ENVIRONMENTS or not settings.database_url:
        parser.error("Replay runs only in development/test with DATABASE_URL set")
    if not settings.auth_demo_student_password:
        parser.error("Configure AUTH_DEMO_STUDENT_PASSWORD (the bootstrap student password)")
    database = Database(settings.database_url.get_secret_value())
    migrate_all(database)
    auth = AuthService(database, settings.auth_tenant_id)
    student = auth.login(
        "student", settings.auth_demo_student_password.get_secret_value(), "replay"
    ).actor
    replay = build_replay(database, auth, student)
    print("SIMULATED DEMO: no real money, bank or university is involved.")
    for flow in FLOWS if args.flow == "all" else (args.flow,):
        report = replay.run(flow)
        print(f"\n== {flow} ==")
        for line in report.steps:
            print(f"  - {line}")
        print(f"  facts: {report.facts}")


if __name__ == "__main__":
    main()
