# Dev C progress

Owner: Financial provider/university simulator, ledger, reconciliation, seeds and status/demo UI. Updated: 2026-10-16.
Scope and acceptance: [MVP](../../Rantau-MVP-Spec.md) and [roadmap](../../Rantau-3Dev-Roadmap.md).
Workflow: [AGENTS.md section 7](../../AGENTS.md#7-mandatory-progress-workflow-and-documentation-limits).
Shared kickoff evidence: [S-01/S-02 under Dev A](progress-a.md).

`[x]` means implementation and required available checks passed; review/merge status stays separate.
These rows are seeded from the roadmap. No Dev C completion evidence has been recorded here; unchecked rows do not assert that the owner has done no work elsewhere.
When work changes, update its existing row, including concrete paths/behavior in `Desc`, exact validation results/PR in `Status / evidence`, and the date.

| Check | Ticket | Task | Desc | Status / evidence | Updated |
|---|---|---|---|---|---|
| [ ] | S-03 | Seed database and scenarios | Establish the shared PostgreSQL schema/migration, isolated demo tenant, deterministic fixtures, reset command and stable scenario/fixture IDs; coordinate with shared owners. | No completion evidence recorded. Depends on S-01. | — |
| [ ] | C-01 | Migrations and fixture reset | Implement repeatable accounts, obligation, trusted beneficiary, two synthetic quotes and scenario flags. Keep resets tenant-isolated and all data synthetic. | No completion evidence recorded. Depends on S-01; coordinate with S-03 rather than duplicating schema work. | — |
| [ ] | C-02 | Obligation, beneficiary and FX quotes | Expose scoped CNY balance, masked verified recipient, exact IDR→CNY quote math, fees, expiry and provenance from trusted simulator adapters. | No completion evidence recorded. Depends on C-01. | — |
| [ ] | C-03 | Payment intents and protected ledger executor | Create immutable terms and execute through the real authorization gate inside an atomic transaction; enforce idempotency, one debit, balance/limit reservations and redacted audit. | No completion evidence recorded. Depends on C-01 and B-02's interface. Test-only fake gates must never enter integrated execution. | — |
| [ ] | C-04 | Provider state, timeout and duplicate control | Model `PROCESSING`, `DELIVERED`, `FAILED` and `OUTCOME_UNKNOWN`; reconcile the original provider reference before retrying, without a second debit or unearned failure state. | No completion evidence recorded. Depends on C-03. | — |
| [ ] | C-05 | University obligation and posting service | Keep provider delivery separate from university posting; privileged simulated university service posts atomically once and derives tuition balance/state from verified ledger rows. | No completion evidence recorded. Depends on C-01. | — |
| [ ] | C-06 | Reconciliation and three exception branches | Resolve missing-reference evidence through authorized university review; return `AWAITING_POSTING` within the posting window; compute exact shortfall and propose a newly authorized permitted top-up or escalation. | No completion evidence recorded. Depends on C-04/C-05. Agent submission cannot directly post credit. | — |
| [ ] | C-07 | Payment status and demo pages | Build `frontend/app/student/payments/` and `frontend/app/demo/` with distinct provider/university status, protected fixture reset/injection and redacted audit inspection. | No completion evidence recorded. Depends on C-02–C-06 contracts. | — |
| [ ] | C-08 | Financial and concurrency tests | Cover TC-01–10 and concurrent retries with actual database assertions: no overdraw, at most one debit, at most one university posting and no duplicate after unknown provider outcomes. | No completion evidence recorded. Depends on C-03–C-06. | — |

Keep implementation decisions, exact check results and blockers in these rows or a short section in this file. Do not create a separate report per task or session. Evidence must identify the synthetic fixture/run and database state without exposing real account data.
