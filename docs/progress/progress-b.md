# Dev B progress

Owner: Identity, authorization, approvals, fraud and sponsor UI. Updated: 2026-10-17.
Scope and acceptance: [MVP](../../Rantau-MVP-Spec.md) and [roadmap](../../Rantau-3Dev-Roadmap.md).
Workflow: [AGENTS.md section 7](../../AGENTS.md#7-mandatory-progress-workflow-and-documentation-limits).
Shared kickoff evidence: [S-01/S-02 under Dev A](progress-a.md).

`[x]` means implementation and required available checks passed; review/merge status stays separate.
These rows are seeded from the roadmap. No Dev B completion evidence has been recorded here; unchecked rows do not assert that the owner has done no work elsewhere.
When work changes, update its existing row, including concrete paths/behavior in `Desc`, exact validation results/PR in `Status / evidence`, and the date.

| Check | Ticket | Task | Desc | Status / evidence | Updated |
|---|---|---|---|---|---|
| [ ] | B-01 | Demo authentication and scoped access | In progress: prepare separate credential-authenticated student/sponsor sessions and tenant/resource/consent checks in `backend/authz/`, preserving the existing `ActorContext`. Proposed login/session/logout and student sharing-consent interfaces, shared wiring and persistent tables are detailed below for coordination before implementation. | Design prepared on `feat/demo-authentication`, based on current `main` (`1e299e0`, matches fetched `origin/main` on 2026-10-17). Local commit — awaiting push/PR instruction. Shared-interface/schema agreement is pending; no authentication implementation or passing application-test claim. `python -` documentation assertions passed (seven unique unchecked task rows, columns, local links and five proposed endpoints); `git diff --check` and `python scripts/check_repo_hygiene.py` passed on 2026-10-17. System Python has no pytest, the project environment is absent and Docker is stopped; local PostgreSQL 17 is running but no database was accessed. Next: approve the interface proposal, then implement with failing security tests first and isolated database validation. | 2026-10-17 |
| [ ] | B-02 | Deterministic policy gate / T0–T3 | Check owner, verified beneficiary, balance, cumulative limits/reservations, mandate, quote expiry, current approval/terms, holds and state; return `ALLOW`, `REQUIRE_APPROVAL`, `HOLD` or `DENY` with a reason and audit reference. | No completion evidence recorded. Depends on B-01 and typed account mocks. | — |
| [ ] | B-03 | Bound approvals and mandates | Record authenticated funding-owner approval for exact immutable terms, with expiry and single use. Invalidate changed terms; count mandate spending and reservations cumulatively. | No completion evidence recorded. Depends on B-01/B-02. | — |
| [ ] | B-04 | Sponsor approval dashboard | Build `frontend/app/sponsor/` to show authorized amount, currencies, beneficiary and costs; approve/reject through the sponsor's protected session. Student chat cannot approve. | No completion evidence recorded. Depends on B-03. | — |
| [ ] | B-05 | Fraud hard rules and advisory LLM assessment | Hold changed/unverified beneficiaries independently of model scoring; return structured advisory scam indicators while keeping legitimate known-payee payments possible after compliant authorization. | No completion evidence recorded. Depends on B-02 and the KB adapter. | — |
| [ ] | B-06 | Holds, audit and security cases | Create scoped persistent holds/cases and redacted audit events with actor, reason and decision. The agent may place a hold but cannot clear it; unrelated actors cannot retrieve cases. | No completion evidence recorded. Depends on B-02. | — |
| [ ] | B-07 | Security regression suite | Cover SEC-01–09 with database assertions: zero unauthorized debit, forged approval/role rejection, cumulative limits, injection, privacy, immutable terms and valid-payment recovery. | No completion evidence recorded. Depends on B-02–B-06. | — |

## B-01 design for shared-interface agreement

Prepared 2026-10-17 following the request to begin Dev B work. This is a proposal, not an activated authentication or financial policy. B-01 remains unchecked until implementation and required checks pass. Keep the existing public `ActorContext`, money, approval and payment contracts unchanged.

**Approach:** use opaque server sessions backed by PostgreSQL. This fits the existing cookie-only chat relay and permits immediate logout/revocation and consent checks. Signed self-contained tokens would require an additional revocation mechanism; process-local sessions would lose authority state on restart and are unsuitable for integrated use. Typed repository fakes may be used only in tests while Dev C's storage is coordinated.

**Identity and credentials:** provision synthetic student and sponsor identities through an explicit isolated-demo bootstrap command; do not expose registration, caller-selected roles or default passwords. Credentials come from ignored local configuration, are salted/hashed before storage, and never enter logs, responses or model context. Login verifies credentials and issues a fresh cryptographically random token. Store only its digest. Resolve actor ID, tenant, role and scopes from current trusted records on every authenticated request; reject inactive actors, revoked sessions and expired sessions. Proposed initial session lifetime: one hour, independent of financial approval expiry.

**Proposed HTTP additions (require agreement):**

| Method / path | Request and result | Enforcement |
|---|---|---|
| `POST /api/v1/auth/login` | Strict `{username, password}`; return `{authenticated: true, role}` and a session cookie. | Generic credential failure; bounded input; trusted-origin check and bounded login attempts. Never accept actor, tenant, scopes or role in the request. |
| `GET /api/v1/auth/session` | Return `{authenticated: true, role}` after verifying the cookie. | No raw token, credential digest, session ID or private account data in JSON. |
| `POST /api/v1/auth/logout` | Empty body; revoke the current session and clear its cookie. | Trusted-origin check; no financial mutation. |
| `PUT /api/v1/student/sharing-consents/{sponsor_id}` | Strict `{allowed_shared_fields, expires_at}`; return the saved sharing summary without credentials/session data. | Verified student grants only their own data to an existing same-tenant sponsor. Proposed fields: `tuition_summary`, `payment_summary`, `case_summary`; cannot grant payment authority. |
| `DELETE /api/v1/student/sharing-consents/{sponsor_id}` | Revoke the student's grant; return 204. | Verified student and trusted-origin check; subsequent sponsor reads must observe revocation. |

The session cookie is host-only, `HttpOnly`, `SameSite=Strict`, `Path=/`, with `Secure` required outside explicit local development. State-changing routes validate a configured trusted frontend origin; do not trust forwarded identity/host claims. Missing trusted configuration/storage remains a sanitized 503; invalid credentials/sessions return a generic 401; unauthorized resource reads return a non-disclosing 404. Financial/approval endpoints remain outside this ticket.

**Storage and ownership agreement:** coordinate shared `actors`, `auth_credentials`, `auth_sessions` and `student_sponsor_consents` tables/migrations with Dev C. Require tenant-bound identity/session lookups, unique token digests, expiry/revocation timestamps, credential hashes and explicit consent fields. Bootstrap must be explicit, restricted to an isolated demo tenant and fail outside development/test. No table creation or identity seeding at application startup. No migration or database change is authorized by this proposal alone.

**Access and integration:** `backend/authz/` supplies session verification plus reusable tenant, ownership, sponsor-role and field-specific sharing checks. Students cannot enter sponsor decision paths; sponsors may read consented student summaries but never acquire authority over student-owned funds. Shared integration updates `backend/dependencies.py` and `backend/main.py` only after agreement, exports agreed HTTP shapes through the existing contract generator, and documents sanitized configuration in `.env.example`/README. `/ready` continues reporting unavailable domain services until A/C wiring exists. Dev A consumes verified sessions; Dev C enforces the access checks on every domain read and the later B-02 gate inside execution transactions.

**Validation required:** write and observe failing tests before product code. Cover separate credentials/sessions, forged identity headers/body/chat, token tampering/fixation, expiry/logout/revocation, disabled actors, tenant isolation, sponsor-role restrictions, missing/expired/revoked/field-limited consent, cross-tenant grants, origin checks, login-attempt limits and sanitized errors. Exercise an isolated PostgreSQL database for persistence/restart and immediate consent revocation. Run the complete backend suite, strict mypy, Ruff, contract generation/typecheck where shared HTTP models change, diff checks and index hygiene. Keep credentials, tokens, DB data and generated output ignored. Record actual commands/results here; do not label B-01 complete using test-only repositories.

Keep implementation decisions, exact check results and blockers in these rows or a short section in this file. Do not create a separate report per task or session. Never commit credentials, raw tokens, private balances or student records as evidence.
