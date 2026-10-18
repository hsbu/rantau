"""Deterministic walkthrough of the demo flows against the real services.

Student and sponsor act through real sessions: the sponsor's approval is an exact-terms owner
decision that the protected executor consumes once. Development/test only; never wired into
the application.
"""

import argparse
from dataclasses import dataclass, field

from backend.approvals.finance_authority import StoredAuthority
from backend.approvals.service import ApprovalConflict, ApprovalService
from backend.approvals.wiring import build_approval_service
from backend.authz.service import AuthService
from backend.authz.storage import Database
from backend.config import Settings
from backend.contracts.models import (
    ActorContext,
    CaseSubmission,
    IntentProposal,
    PaymentIntent,
    ScopeDenied,
    ServiceUnavailable,
)
from backend.demo.reset import DEMO_ENVIRONMENTS, reset_demo_fixture
from backend.demo.scenarios import BENEFICIARY_ALIAS, OBLIGATION_ALIAS
from backend.finance.migrations import migrate_all
from backend.finance.outcomes import Created, Executed, Refused
from backend.finance.simclock import advance_sim_clock
from backend.finance.wiring import FinanceServices, build_services
from backend.university.ledger import settle_due

UNVERIFIED_PAYEE = "benef_unverified_01"
POSTING_HOURS = 25
FLOWS = ("happy", "hero", "attack")


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
    approvals: ApprovalService
    student: ActorContext
    sponsor: ActorContext
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
        report.step(self._approval_outcome(forged.intent))
        blocked = self.services.executor.execute(self.student, forged.intent.id, "replay-forged")
        assert isinstance(blocked, Refused)
        report.step(f"Execution of the forged payee: refused ({blocked.reason_code.value})")
        legitimate = self._pay(report, "replay-legit")
        self._facts(report, legitimate)
        return report

    def _reset(self, report: Report, scenario: str) -> None:
        run_no = reset_demo_fixture(self.services.database, self.tenant_id, scenario)
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
        report.step(f"Intent {created.intent.state.value}: the funding owner must approve")
        self._approve(created.intent)
        report.step("Sponsor approved the exact terms in their own session")
        executed = self.services.executor.execute(self.student, created.intent.id, key)
        assert isinstance(executed, Executed)
        report.step(f"Provider status: {executed.transfer_state.value}")
        return executed

    def _approve(self, intent: PaymentIntent) -> None:
        request = self.approvals.request(self.student, intent.id)
        self.approvals.decide(self.sponsor, request.approval_id, "APPROVED", intent.terms_hash)

    def _approval_outcome(self, intent: PaymentIntent) -> str:
        try:
            self.approvals.request(self.student, intent.id)
        except (ApprovalConflict, ScopeDenied, ServiceUnavailable):
            return "Approval cannot even be requested for the held payee"
        return "Approval was requested; the executor still re-checks the hold"

    def _advance_and_tick(self, report: Report) -> None:
        with self.services.database.connection() as connection:
            advance_sim_clock(connection, self.tenant_id, POSTING_HOURS * 3600)
            posted = settle_due(connection, self.tenant_id)
        report.step(f"Simulated clock +{POSTING_HOURS}h; university posted {posted} receipt(s)")

    def _state(self) -> str:
        return self.services.obligations.get(self.student, OBLIGATION_ALIAS).state.value

    def _facts(self, report: Report, executed: Executed) -> None:
        with self.services.database.connection() as connection:

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
                "approvals_consumed": count(
                    "SELECT count(*) FROM approvals a JOIN payment_intents i "
                    "ON i.tenant_id = a.tenant_id AND i.alias = a.intent_id "
                    "WHERE a.state = 'CONSUMED'"
                ),
                "audit_events_this_run": count(
                    "SELECT count(*) FROM audit_events a JOIN demo_state d "
                    "ON d.tenant_id = a.tenant_id AND d.run_no = a.run_no"
                ),
                "tuition_state": self._state(),
                "provider_status": executed.transfer_state.value,
            }


def build_replay(
    database: Database, auth: AuthService, student: ActorContext, sponsor: ActorContext
) -> Replay:
    services = build_services(database, auth, StoredAuthority(student.tenant_id))
    return Replay(services, build_approval_service(auth), student, sponsor, student.tenant_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay the Rantau demo flows (development only)")
    parser.add_argument("--flow", choices=(*FLOWS, "all"), default="all")
    args = parser.parse_args()
    settings = Settings()
    if settings.app_env not in DEMO_ENVIRONMENTS or not settings.database_url:
        parser.error("Replay runs only in development/test with DATABASE_URL set")
    if not (settings.auth_demo_student_password and settings.auth_demo_sponsor_password):
        parser.error("Configure the bootstrap student and sponsor passwords in the local .env")
    database = Database(settings.database_url.get_secret_value())
    migrate_all(database)
    auth = AuthService(database, settings.auth_tenant_id)
    student = auth.login(
        "student", settings.auth_demo_student_password.get_secret_value(), "replay"
    ).actor
    sponsor = auth.login(
        "sponsor", settings.auth_demo_sponsor_password.get_secret_value(), "replay"
    ).actor
    replay = build_replay(database, auth, student, sponsor)
    print("SIMULATED DEMO: no real money, bank or university is involved.")
    for flow in FLOWS if args.flow == "all" else (args.flow,):
        report = replay.run(flow)
        print(f"\n== {flow} ==")
        for line in report.steps:
            print(f"  - {line}")
        print(f"  facts: {report.facts}")


if __name__ == "__main__":
    main()
