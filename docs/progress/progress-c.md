# Dev C progress

Owner: Financial provider/university simulator, ledger, reconciliation, seeds and status/demo UI. Updated: 2026-10-17.
Scope and acceptance: [MVP](../../Rantau-MVP-Spec.md) and [roadmap](../../Rantau-3Dev-Roadmap.md).
Workflow: [AGENTS.md section 7](../../AGENTS.md#7-mandatory-progress-workflow-and-documentation-limits).
Shared kickoff evidence: [S-01/S-02 under Dev A](progress-a.md).

`[x]` means implementation and required available checks passed; review/merge status stays separate.
Rows follow the roadmap. Work is on the unpublished, uncommitted branch `feat/finance-foundation`; nothing is pushed.
When work changes, update its existing row, including concrete paths/behavior in `Desc`, exact validation results/PR in `Status / evidence`, and the date.

| Check | Ticket | Task | Desc | Status / evidence | Updated |
|---|---|---|---|---|---|
| [ ] | S-03 | Seed database and scenarios | Shared schema/seed/reset coordination. C-owned tables, scenarios and CLI reset are delivered under C-01. Still open: provisioning of a demo-admin actor and reset of B's consent state are B decisions (gaps G-4, G-13). | In progress. Depends on S-01 and Dev B. | 2026-10-17 |
| [x] | C-01 | Migrations and fixture reset | `migrations/010_audit_events.sql` (append-only audit), `011_finance_core.sql` (accounts, quotes, intents with DB-immutable terms, transfers with one-unresolved-per-obligation index, balanced ledger, spend entries, idempotency keys), `012_university.sql` (postings, one per transfer). `backend/demo/` scenarios (`tuition_happy_path`, `forged_beneficiary`, `demo_long_quotes`), seed through service code, `python -m backend.demo.reset [--migrate] [--scenario]` (development/test only). Reset touches only C tables and keeps audit/identity rows. Policy validity is rebased onto the run clock (gap G-6). C applies its migrations with its own runner (`backend/finance/migrations.py`) after B's unchanged `migrate()`; no other developer's file is edited. | Local, uncommitted — awaiting commit by the owner. 2026-10-17 fresh: `uv run pytest tests -q`: 443 passed (329 baseline + 114 new; real PostgreSQL 18 locally); `uv run mypy`: 61 files passed; `uv run ruff check .`: passed. Reset isolation covered by `tests/demo/test_reset.py` and `tests/finance/test_reset_isolation.py`. No HTTP reset endpoint yet (decision: CLI first; gap G-4). | 2026-10-17 |
| [ ] | C-02 | Obligation, beneficiary and FX quotes | Delivered: `backend/finance/money.py` (exact conversion, pricing, basis-point fees, safe parsing), `quotes.py` (`mock_remit_a`/`mock_remit_b`, persisted expiring quotes, comparison by total landed cost), `university/obligations.py` (state derived from ledger rows). Pending: scoped HTTP reads (`GET /quotes`, `/tuition/obligations*`), masked beneficiary read, `AgentReadPort`. | In progress. 28 money, 5 quote and 6 obligation-state tests pass (see C-01 run). Needs approval of additive contract changes before routes. | 2026-10-17 |
| [ ] | C-03 | Payment intents and protected ledger executor | Delivered at service level: `finance/intents.py` (server-derived immutable terms, canonical SHA-256 `terms.py`, gate on create, cancel), `policy_repo.py` (`PolicyRepository` for Dev B's gate), `executor.py` (one transaction: ordered locks, replay by `(tenant, actor, key)` with request fingerprint, B's real `TransactionAuthorization`, independent integrity and limit re-checks, atomic debit, balanced ledger, spend entry, transfer, audit). Pending: provider submission and outcome transaction (C-04), HTTP routes, B-03 approval consumption. | In progress. Tests use B's real gate with a test-only authority source (`tests/finance/authority.py`); concurrency tests (8 parallel executes, one key, many keys, split payments) pass repeatedly (5 runs) and fail when the account lock is removed (mutation check, restored). Not integrated: approvals/mandates/holds are scripted, not B-03/B-06. | 2026-10-17 |
| [ ] | C-04 | Provider state, timeout and duplicate control | Not started beyond the stored `PROCESSING` transfer with unset `provider_submitted_at`. | No completion evidence recorded. Depends on C-03. | — |
| [ ] | C-05 | University obligation and posting service | `university_postings` table (unique per institution+transfer) and pure state derivation exist; receipts, SimClock, settlement and review service are pending. | No completion evidence recorded. | — |
| [ ] | C-06 | Reconciliation and three exception branches | Not started. | No completion evidence recorded. Depends on C-04/C-05. | — |
| [ ] | C-07 | Payment status and demo pages | Not started (CLAUDE.md rules for the frontend directories are written). | No completion evidence recorded. | — |
| [ ] | C-08 | Financial and concurrency tests | Started inside C-03: TC-06 (idempotency), atomic balance, split-limit evasion, ledger invariants, TC-04 (student self-funded), forged unverified payee held (SEC-05 service level), static guards (no floats, no test fakes in app code, no backend-only actions in agent/kb). TC-01 (endpoint), TC-05, TC-07..10 and the remaining SEC cases pending. | In progress; see C-03 evidence. | 2026-10-17 |

## Open gaps and blockers

| ID | Gap | Owner / dependency | Next action |
|---|---|---|---|
| G-1 | B-03 approvals, mandates and `authorize_execution` are not built; tests script approval. T2 is not verified end to end. | Dev B | Implement approval store with atomic consumption; then replace `ScriptedAuthority` with the real source. |
| G-2 | Canonical terms hash lives in `backend/finance/terms.py`, not in shared contracts. | Dev B + C | Agree location; B-03 adopts the same canonicalization. |
| G-3 | C runs its own migration runner (`finance/migrations.py`); B's bootstrap applies only auth migrations. | Dev B | Agree a single ordered list or discovery. |
| G-4 | No demo-admin actor or scope; HTTP `/demo/*` not built. | Dev B | Provision admin; then add endpoints (fail closed meanwhile). |
| G-5 | Hold/risk-floor source does not exist; the test authority returns scripted values. Integrated wiring must refuse to start without it. | Dev B (B-05/B-06) | Provide a minimal hold reader. |
| G-6 | Dev A's KB policy validity (31 Oct–31 Dec) clashes with the real clock. C rebases its seeded policy; A's `known_policy` would still treat it as unknown. | Dev A | Rebase or inject a scenario clock in the KB. |
| G-7 | `TransactionAuthorization.evaluate` is async over synchronous work; services use `asyncio.run` in a worker thread. | Dev B | Provide a synchronous entry point. |
| G-8 | No HTTP routes, `PaymentPort`/`UniversityPort`/`AgentReadPort` implementations or `/ready` wiring yet; `tests/test_application.py` currently asserts those routes are absent. | A/B/C | After contract approval; update that guard test together. |
| G-9 | Additive contract changes pending approval: `IDEMPOTENCY_KEY_REUSED`, `TuitionObligationDetail`, optional execute body `terms_hash`, `PaymentIntentView`, recheck/demo endpoints. | Owner approval | Approve or amend before routes. |
| G-10 | Provider submission, university posting, reconciliation, shortfall and UI are not built; a debited transfer stays `PROCESSING`. | Dev C | Next branch. |
| G-11 | Fixture numbers (balances, limits, routine threshold) are authored assumptions. | Product owner | Confirm. |
| G-12 | Local DB tests need PostgreSQL on PATH (`C:\Program Files\PostgreSQL\18\bin`); Docker is stopped; CI uses PostgreSQL 17. | Dev C | Verify in CI after publication is authorized. |
| G-13 | Reset keeps sessions and restores no consent changes; B's note asks for session/consent invalidation. | Dev B | Agree behaviour. |

Keep implementation decisions, exact check results and blockers in these rows or this section. Do not create a separate report per task or session. Evidence identifies synthetic fixtures and database state without exposing real account data.
