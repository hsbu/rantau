# Dev B progress

Owner: Identity, authorization, approvals, fraud and sponsor UI. Updated: 2026-10-16.
Scope and acceptance: [MVP](../../Rantau-MVP-Spec.md) and [roadmap](../../Rantau-3Dev-Roadmap.md).
Workflow: [AGENTS.md section 7](../../AGENTS.md#7-mandatory-progress-workflow-and-documentation-limits).
Shared kickoff evidence: [S-01/S-02 under Dev A](progress-a.md).

`[x]` means implementation and required available checks passed; review/merge status stays separate.
These rows are seeded from the roadmap. No Dev B completion evidence has been recorded here; unchecked rows do not assert that the owner has done no work elsewhere.
When work changes, update its existing row, including concrete paths/behavior in `Desc`, exact validation results/PR in `Status / evidence`, and the date.

| Check | Ticket | Task | Desc | Status / evidence | Updated |
|---|---|---|---|---|---|
| [ ] | B-01 | Demo authentication and scoped access | Authenticate student and sponsor separately; derive actor server-side; enforce tenant/resource scope and student sharing consent. Connect verified sessions without trusting role claims from chat or request fields. | No completion evidence recorded. Depends on S-01. | — |
| [ ] | B-02 | Deterministic policy gate / T0–T3 | Check owner, verified beneficiary, balance, cumulative limits/reservations, mandate, quote expiry, current approval/terms, holds and state; return `ALLOW`, `REQUIRE_APPROVAL`, `HOLD` or `DENY` with a reason and audit reference. | No completion evidence recorded. Depends on B-01 and typed account mocks. | — |
| [ ] | B-03 | Bound approvals and mandates | Record authenticated funding-owner approval for exact immutable terms, with expiry and single use. Invalidate changed terms; count mandate spending and reservations cumulatively. | No completion evidence recorded. Depends on B-01/B-02. | — |
| [ ] | B-04 | Sponsor approval dashboard | Build `frontend/app/sponsor/` to show authorized amount, currencies, beneficiary and costs; approve/reject through the sponsor's protected session. Student chat cannot approve. | No completion evidence recorded. Depends on B-03. | — |
| [ ] | B-05 | Fraud hard rules and advisory LLM assessment | Hold changed/unverified beneficiaries independently of model scoring; return structured advisory scam indicators while keeping legitimate known-payee payments possible after compliant authorization. | No completion evidence recorded. Depends on B-02 and the KB adapter. | — |
| [ ] | B-06 | Holds, audit and security cases | Create scoped persistent holds/cases and redacted audit events with actor, reason and decision. The agent may place a hold but cannot clear it; unrelated actors cannot retrieve cases. | No completion evidence recorded. Depends on B-02. | — |
| [ ] | B-07 | Security regression suite | Cover SEC-01–09 with database assertions: zero unauthorized debit, forged approval/role rejection, cumulative limits, injection, privacy, immutable terms and valid-payment recovery. | No completion evidence recorded. Depends on B-02–B-06. | — |

Keep implementation decisions, exact check results and blockers in these rows or a short section in this file. Do not create a separate report per task or session. Never commit credentials, raw tokens, private balances or student records as evidence.
