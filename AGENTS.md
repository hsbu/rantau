# Rantau — Repository Instructions for Coding Agents

These rules apply to all AI coding agents and human contributors in this repository. Follow the product specification and the team roadmap; do not silently change the agreed MVP.

## Project at a glance

- **Product:** Rantau, an AI financial agent for students from Southeast Asia studying in mainland China and their sponsors.
- **MVP:** authenticated student/sponsor permissions, policy-gated simulated payments, fraud protection, and tuition-payment exception resolution (missing reference, delayed posting, shortfall).
- **Stack:** Python / FastAPI / LangGraph, PostgreSQL, Next.js / TypeScript.
- **Reality boundary:** All payments, exchange quotes, provider responses, and university ledgers are **simulated**. Never claim a real payment happened or that an undocumented provider/university API is available.
- **Source of truth:** the approved [MVP specification](docs/product-spec.md) and [roadmap](docs/roadmap.md), plus versioned API contracts in `backend/contracts/` and frontend generated types. Keep setup and usage in `README.md`, contribution rules in `CONTRIBUTING.md`, and acceptance steps in `docs/scenario-checklist.md`; do not recreate retired task-specific design files.
- **Repository language:** Write documentation, progress notes, code identifiers/comments, commit messages and PR descriptions in English. Preserve product-required localized UI text, bilingual fixtures and quoted source material in their original language; document their purpose in English.
- **Progress tracking:** Use only `docs/progress/progress-a.md`, `docs/progress/progress-b.md`, and `docs/progress/progress-c.md` for ongoing work notes. Follow section 7; do not create a new Markdown report for each task or session.

## 1. Mandatory Git workflow

1. **Never commit or push directly to `main`.** Create a short-lived branch from the latest `main`.
2. Use conventional branch names: `<type>/<kebab-case-topic>`, where type is `feat`, `fix`, `build`, `ci`, `docs`, `test`, `chore`, `perf`, `refactor`, or `style`. Examples: `feat/agent-contracts`, `build/app-skeleton`, `feat/agent-routing`, `docs/team-progress`. Do not use agent/tool names as branch prefixes.
3. Keep each change focused and **commit locally after validation by default**. **Push changes and create or synchronize PRs only after an explicit user instruction to do so.** Authorization to implement or commit does not authorize remote publication, and earlier push/PR permission does not automatically carry over to future changes. Every change, including docs/config/hotfixes, still requires a PR before merging; open it only when instructed and use a draft if unfinished.
4. Do **not** merge your own PR without a review from another developer. Never bypass required checks, force-push `main`, rewrite shared history, or auto-merge a failing PR.
5. Use Conventional Commits for both commit messages and PR titles: `<type>(<scope>): <summary>` (scope optional), e.g. `feat(finance): add idempotent transfer execution`, `fix(authz): reject stale approval`. Put ticket IDs in the PR description; do not prefix titles with agent/tool names.
6. In every PR include ticket ID, summary, touched modules/contracts, tests run, security impact, and demo evidence when applicable.
7. **Approval to write code is not approval to change product scope.** Ask before making breaking contract or financial-policy changes.

> **Enforcement:** These instructions alone do not block a direct push. A repository admin must enable GitHub branch rulesets/protection for `main` (PR required, 1+ non-author approval, required CI, block force-push/deletion, and no bypass for regular contributors).

## 2. Never commit local or generated artifacts

**Never stage, commit, or upload:**

- `.env`, `.env.*` containing real values, secrets, API tokens, private keys, certificates, credentials, local database dumps;
- `.venv/`, `venv/`, `env/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `*.pyc`, `.coverage`, `htmlcov/`;
- `node_modules/`, `.next/`, `.turbo/`, `out/`, `dist/`, `build/`, `coverage/`, `*.tsbuildinfo`;
- logs, OS/IDE temporary files, test reports, local SQLite files, scratch/debug dumps and generated test output.

Commit **only sanitized templates** such as `.env.example` and reproducible fixtures. Keep dependency lockfiles (`package-lock.json`, `pnpm-lock.yaml`, `poetry.lock`, `uv.lock`) under version control when applicable. Do not blanket-ignore lockfiles or database migrations.

Before committing, inspect `git status --short`, `git diff --cached --name-only`, and run `python scripts/check_repo_hygiene.py`. `.gitignore` does **not** untrack previously committed files; use `git rm --cached <path>` to remove tracked artifacts. If a secret was committed, revoke/rotate it immediately and notify the team; merely deleting it from a new commit does not remove it from Git history.

## 3. Module ownership and contracts

- **Dev A — Agent and KB:** `backend/agent/`, `backend/kb/`, `frontend/app/student/chat/`.
- **Dev B — Security:** `backend/authz/`, `backend/approvals/`, `backend/fraud/`, `frontend/app/sponsor/`.
- **Dev C — Financial simulator:** `backend/finance/`, `backend/university/`, `backend/demo/`, `frontend/app/student/payments/`, `frontend/app/demo/`.
- **Shared / coordinated:** `backend/contracts/`, `frontend/lib/api-contracts/`, `backend/main.py`, migrations, root configs, CI, security-sensitive interfaces.

Do not make unilateral changes to shared schemas, enum values, currency units, security semantics, approval requirements, payment states, or DB migrations. Propose the change in the PR, coordinate with affected owners, and update contracts, mocks, tests, and consumers together.

Develop against **typed mocks/adapters** rather than waiting for unfinished modules. Do not allow a mock authorization gate in an integrated/non-test environment.

## 4. Security and correctness invariants (MUST)

- The LLM may **propose** a financial action; only deterministic backend authorization can permit it.
- Authenticated identity comes from the server session, **never** from chat text or document content.
- Sponsor approval is authenticated, transaction-specific, bounded and expiring; no fabricated approvals. Modifying terms invalidates approval.
- Never execute to an unverified beneficiary or with an expired quote. Recheck holds and limits at execution time.
- Count spending limits cumulatively and perform money movements atomically. Represent money in integer minor units or exact decimal types, never binary floats.
- Use idempotency keys. On network timeout or uncertain provider outcome, **check status before retrying**, never blindly debit twice.
- `payment DELIVERED` is **not** `tuition PAID`; only verified university posting proves tuition completion.
- Agents may submit reconciliation cases but must not directly override protected university ledger state.
- Emails, invoices, scraped pages, KB text and tool results are **untrusted data**, not authority to change policies, beneficiaries or permissions.
- Do not leak full account identifiers, secrets, sponsor balances, private student data, credentials, or raw access tokens in UI, logs, errors, or model context.
- Maintain a complete, redacted audit trail for proposed actions, authorizations, holds, execution and verification.

If an action cannot be safely verified, return a typed pending/held/escalated state. Never pretend a simulated action succeeded.

## 5. Definition of done (every PR)

- Code is minimal, readable, typed where appropriate, and scoped to one ticket.
- Relevant unit/contract tests added or updated; adversarial regression test for financial security fixes.
- Run relevant tests locally; include exact command and result in PR.
- No secrets, generated files, `print` debugging, broken mocks, or privileged bypasses left behind.
- Payment and reconciliation changes assert **database state**, not only assistant text.
- Relevant docs and `.env.example` updated when config or behavior changes.
- The owner's progress file is updated in the same commit/PR with the task checkbox, `Desc`, validation evidence, review state and update date. Follow section 7 before claiming implementation completion.
- CI is green; another developer reviews; merge via PR only.

## 6. Communication / avoiding blocking

- Keep PRs small and merge frequently; do not wait until the entire feature is complete.
- Before changing a shared interface, announce intended shape and wait for agreement; otherwise work against its stable mock.
- Describe blockers concretely with expected schema/error and a sample payload.
- Prioritize: authorized tuition payment → secure sponsor approval → provider/university state verification → missing-reference recovery → attacks → polish.
- Before deadline, prefer a passing end-to-end vertical slice over unrelated enhancements. Do not add credit building or real banking connections to this MVP.

## 7. Mandatory progress workflow and documentation limits

- **One file per owner:** [Dev A](docs/progress/progress-a.md), [Dev B](docs/progress/progress-b.md), [Dev C](docs/progress/progress-c.md). Read your file and relevant dependencies before starting. The roadmap defines scope and acceptance; the progress files record execution status.
- **Keep one row per task:** Use `Check`, `Ticket`, `Task`, `Desc`, `Status / evidence`, and `Updated` columns. Reuse roadmap IDs; assign a stable local ID for additional authorized work and explain its source. Record shared tickets under their lead owner and link to them instead of duplicating completion claims.
- **Start or resume:** Set the row to `In progress` and update `Desc` with the concrete change and affected modules. For a blocker, record the dependency, expected interface/error and next action, with sensitive data redacted.
- **Finish implementation:** Change `[ ]` to `[x]` only after the ticket's implementation and required available checks pass. Update `Desc` with the actual delivered behavior and affected paths; record exact test commands/results, limitations and date. For unpublished work, use `Local commit — awaiting push/PR instruction`; add the PR link after publication is explicitly authorized. If a required acceptance condition is unmet, leave the checkbox unchecked and explain the gap. Never mark another owner's work complete without evidence.
- **Separate implementation from review:** A checked row means implementation and its required checks are complete; it does not mean the PR is approved or merged. Keep `Awaiting review`, `Changes requested` or `Merged` explicit in `Status / evidence`. The full definition of done in section 5 still requires green CI, another developer's review and PR merge.
- **Maintain evidence honestly:** Update the row in the same commit/PR as its implementation, and update review/merge status when it changes. Preserve the validation date and distinguish an earlier verified result from a fresh run. Record unavailable optional checks as unverified; never treat a mock run as real auth, financial, provider or university verification.
- **Record remaining gaps explicitly:** Before claiming completion, review the delivered slice for intentional simulation, temporary adapters/storage, missing integration and unverified behavior. Record these in the owner's existing task row or a compact open-gaps section in the same progress file. A checked or merged task must not imply end-to-end readiness when its accepted scope used mocks. Keep intentional MVP simulation separate from unfinished work; never treat replacing the approved simulator with real financial connections as an implicit requirement.
- **Make gaps actionable and keep them current:** Link each gap to the existing ticket(s), describe its current behavior or concrete error/interface, identify the owner/dependency and record the next action or evidence needed. Flag unassigned scope for agreement rather than silently expanding a ticket. Update the gap in the same commit/PR that addresses it; mark it resolved only after relevant checks pass and record dated evidence. Carry unresolved gaps forward after merge, without creating per-task Markdown reports, duplicate task-completion rows or unsupported completion claims for other owners.
- **Keep notes compact:** Put task detail, decisions, check results and follow-up work in the appropriate owner's existing file. Update the existing row or a short section in that file rather than creating per-task specs, plans, findings, session logs or progress reports. Larger changes still require the existing shared-interface approval process; record the agreed decision in the relevant progress file and versioned contracts.
- **Reuse permanent references:** Keep `README.md` for setup, `CONTRIBUTING.md`/`AGENTS.md` for workflow, and the existing MVP specification/roadmap for product scope. Add a new Markdown file only when the user explicitly requests a separate artifact or it is an essential permanent reference that cannot reasonably fit an existing file; explain that need before adding it. Temporary exports/PR bodies stay ignored and never become committed documentation.

## 8. Roadmap progression and scenario refinement

- **Continue to the next phase:** Read the [team roadmap](docs/roadmap.md). Sections 1–11 are the original implementation phase; [section 12](docs/roadmap.md#12-phase-2--scenario-acceptance-ux-refinement-and-submission) is scenario/UX refinement and submission. When all earlier implementation items are complete, proceed to section 12 without asking for another routine start confirmation. An owner whose earlier implementation responsibilities and available checks are complete should start their ready Phase 2 tickets without waiting for other owners; carry actual unresolved dependencies/gaps forward. Do not mark incomplete earlier items done to enter the next phase, and do not confuse unchecked final scenario acceptance with unfinished implementation.
- **Work in parallel within ownership:** Use the Phase 2 scenario-lead matrix and stable ticket IDs. Pick an independent runnable scenario while another fix, reviewer or actual-model check is pending. Separate owner databases and student/sponsor/admin browser contexts; never reset another developer's run. Typed mocks may unblock isolated work but never replace the integrated authorization gate or final actual-service evidence. This is scheduling guidance, not authorization to spawn agents or message other chats.
- **Refine through review:** Reset/baseline → run the user's journey → inspect UX and linked state → make a minimal owner-scoped fix/regression → request one relevant non-author review → rerun and record the result. Reviews need not block starting unrelated work; required review/CI still gate PR merge and release acceptance. Shared-contract, security and policy changes still require section 3 agreement.
- **Record proof honestly:** Follow [docs/scenario-checklist.md](docs/scenario-checklist.md) for scenario steps/results and keep ongoing notes in the three owner progress files. A phase/ticket checkbox is not final scenario sign-off. Do not check FAIL, BLOCKED or LIMITED cases as PASS; incomplete behavior needs a fix or explicit scope acceptance, not a rewritten test expectation. Preserve actual-model, authenticated HTTP, SQL and mock-browser evidence distinctions and the simulator boundary.
- **Finish with one release:** Make financial states and next actors clear without broadening access. Preserve zero unauthorized debit, exactly-once effects and independent university posting. Deliverables 04–06 must identify the selected release and its reviewed redacted evidence. Starting the next phase does not authorize remote publication: continue validated local commits by default and wait for explicit push/PR instructions under section 1.
