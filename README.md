# Rantau

A simulated financial agent for students from Southeast Asia studying in mainland
China and their sponsors. All quotes, payments and university records are synthetic.

Product sources: [MVP specification](Rantau-MVP-Spec.md) and
[team roadmap](Rantau-3Dev-Roadmap.md). Development follows [AGENTS.md](AGENTS.md).

## Local setup

Use Python 3.12, uv, Node 22.13+ and npm. Copy `.env.example` to ignored `.env` if
needed. Set `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` locally to configure the classifier;
offline tests and the explicit synthetic harness need neither.

```powershell
uv sync --locked
uv run python -m scripts.export_openapi
Push-Location frontend
npm ci
npm run generate:contracts
npm run dev
Pop-Location
```

In another terminal, run `uv run python -m backend.server --host 127.0.0.1 --port 8000`.
Open the frontend at `http://127.0.0.1:3000` and backend docs at
`http://127.0.0.1:8000/docs`. With Docker running, `docker compose up --build`
starts PostgreSQL, backend and frontend. Container services use service DNS.

`/health` reports process liveness. `/ready` reports 503 until the domain services
are integrated; it reports configured authentication readiness separately. Backend
authentication is opt-in as described below. Agent domain services remain unwired,
so a valid session alone does not enable the connected financial workflow. No
identity is accepted from headers/chat text, and no fake financial gate is connected.

## Student chat

Use the **Chat** and **Scenarios** navigation tabs to switch between the connected
agent workspace and scripted examples. The active tab stays highlighted; changing
views clears the visible conversation so fixture state never carries into Chat.
This is the first working interface, with further layout refinement expected
after integrated agent testing.

The workspace uses a light theme with neutral form focus indicators. Scroll within
the conversation to read older messages, or continue scrolling past its edge to
move the page. New replies follow the bottom only while you are already there;
use **Latest messages** to return after reading history.

Open `http://127.0.0.1:3000/student/chat/preview` to explore the isolated fixture
preview. Select a scenario, then use the suggested messages or type a message to
advance its scripted steps. It demonstrates clarification, an exact quote,
sponsor waiting, provider delivery versus university posting, missing-reference
evidence, shortfall escalation, uncertain outcomes and expired quotes. It makes
no model or backend calls and cannot authenticate, request real approval or move
money. The November 2026 fixture clock is displayed beside the sample details.
New chat resets the conversation; changing the scenario clears its state.

`/student/chat` is the connected workspace. For local development, create an
ignored `frontend/.env.local` containing only:

```dotenv
AGENT_API_ORIGIN=http://127.0.0.1:8000
```

Restart Next.js after changing this server-only setting. Compose supplies
`http://backend:8000` instead. The student chat relay accepts only
message/conversation fields, forwards the browser's session cookie to the fixed
agent endpoint, rejects foreign origins, disables caching and never forwards
claimed actor/role headers or browser bearer tokens. It does not create a
session; B-01 supplies backend verification. The sponsor workspace at `/sponsor`
uses fixed same-origin relays for sign-in, session, approval list and owner
decisions. Both flows keep API keys and session tokens out of browser code.
Missing trusted adapters/configuration produce a visible unavailable state,
with no fallback to mocks. Session expiry clears the visible chat conversation.

The current agent HTTP contract supplies assistant text, tool events and resource
references. The connected page renders text safely and keeps structured details
empty until an agreed trusted adapter supplies them; it does not parse monetary
amounts or approval states out of prose. Rich financial panels currently use
generated contract types in the isolated preview. A-04/B/C must connect persisted
intents, approval continuation and scoped financial details. There are no payment
or approval execution buttons in this A-06 slice. Browser messages live only in
component memory and clear on reload/new chat; server draft-memory limits still apply.

## Backend demo authentication (B-01)

Use a dedicated, disposable PostgreSQL database for this synthetic demo. No tables
or accounts are created at application startup. Add these values to your ignored
local `.env` (keep both passwords private, distinct, and 12–128 characters):

```dotenv
AUTH_ENABLED=true
AUTH_TENANT_ID=demo_001
AUTH_TRUSTED_ORIGIN=http://127.0.0.1:3000
AUTH_DEMO_STUDENT_PASSWORD=<local-student-password>
AUTH_DEMO_SPONSOR_PASSWORD=<different-local-sponsor-password>
```

Set `DATABASE_URL` to that isolated database, then run:

```powershell
uv run python -m backend.authz.bootstrap --migrate --seed
```

This explicitly applies the ordered, checksummed auth, policy, authority and
security migrations (`001`–`005`) and provisions the `student` and
`sponsor` usernames for `stu_001` / `par_001` in `demo_001`. Bootstrap rejects
environments other than development/test and refuses to overwrite an existing demo
tenant. Migration replays check a stored checksum. The CLI uses local settings;
no password is supplied on its command line. Remove the two bootstrap passwords
from local configuration after seeding; stored credentials use salted scrypt.
Session tokens are random and only their SHA-256 digests are stored.

The additive endpoints are:

- `POST /api/v1/auth/login`: `{username, password}`; sets the host-only `session`
  cookie and returns `{authenticated: true, role}`.
- `GET /api/v1/auth/session`: verifies the cookie against current database records.
- `POST /api/v1/auth/logout`: empty body; revokes the session and clears its cookie.
- `PUT /api/v1/student/sharing-consents/{sponsor_id}`: a student grants
  `{allowed_shared_fields, expires_at}` to a same-tenant sponsor. Allowed fields are
  `tuition_summary`, `payment_summary`, and `case_summary`.
- `DELETE /api/v1/student/sharing-consents/{sponsor_id}`: empty body; revokes that
  student's sharing grant.

State-changing requests must send `Origin` matching `AUTH_TRUSTED_ORIGIN` exactly;
forwarded identity/host headers are ignored. Plain HTTP is permitted only for
loopback development (plus the isolated test host). HTTPS cookies are `Secure`;
all session cookies are `HttpOnly`, `SameSite=Strict`, and expire after one hour.
Login admits five attempts per username and thirty per direct client address in
each fifteen-minute window, including successful attempts. Counters persist across
workers; deployments behind a proxy share its direct address until a separately
reviewed trusted-proxy configuration exists. Do not disable these limits to work
around a proxy. The `backend.server` entrypoint explicitly disables Uvicorn proxy
header processing; use it for local/container startup so caller-supplied forwarded
addresses cannot evade the client limit. Authentication errors and validation
failures are sanitized.

`backend.authz.access.AccessPolicy` provides current-session, tenant, ownership,
sponsor-role and field-specific consent guards for domain adapters. A sponsor's
approval authority over their own funds does not grant access to student records.
Consent grants visibility only and is checked against current expiry/revocation.
Dev C's scoped reads use these guards; the agent domain wiring remains pending.
The B-04 sponsor page provides browser sign-in and protected owner decisions
through fixed same-origin relays. Its complete browser-to-finance flow still
needs an integrated browser run.
Do not connect fake domain services to make Chat appear ready.

`backend.authz.policy_transaction.TransactionAuthorization` implements B-02's
existing `AuthorizationPort` against a trusted `PolicyRepository` and the caller's
PostgreSQL connection. `backend.approvals.finance.FinanceApprovalRepository`
implements the trusted C SQL handoff. The runtime finance builder installs B-03's
protected execution wrapper on a worker thread, after locking current
financial/authority state. The adapter rechecks the session and current database
clock, then records a minimal redacted decision in `policy_decisions`. It never
commits: a returned audit ID is durable only after the caller commits; a rollback
invalidates the result. Preview decisions cannot authorize a later debit.
Repository locking, complete accounting coverage and authority provenance are
documented in `backend/authz/policy_repository.py`. No financial test repository
is connected to application wiring. `/ready` still reports unavailable domain
services while the agent domain wiring remains incomplete.

New demo seeds grant the student `payment:execute` and `reconciliation:submit`,
and the sponsor `payment:execute`, in addition to their existing scopes. These
only permit gate evaluation: ownership, mandate/approval, holds and financial
checks still apply. Migrations do not grant existing actors new privileges or
overwrite credentials. Existing demo tenants require an explicitly coordinated
scope update/reset; bootstrap continues refusing to overwrite them. B-03 authority
and B-06 active holds now feed C's actual simulated executor. Hold writers take
the same account/obligation/intent locks as execution before touching security
rows. `backend.fraud.finance_access.build_security_service` exposes this backend
service for payment-intent resources; no public hold-clearing endpoint is added.

`backend.approvals.service.ApprovalService` persists B-03's owner requests,
decisions and allowance mandates in PostgreSQL. `APPROVAL_TTL_SECONDS` defaults
to 600 (valid range 1–3600); approval expiry is also capped by quote expiry.
Dev C must use `backend.contracts.terms.canonical_terms_hash` when constructing
immutable intents. SHA-256 covers every `PaymentTerms` field except the hash
itself, with sorted compact JSON, exact integers and UTC-normalized timestamps
with six fractional digits. C's compatibility import delegates to that helper.
Existing immutable C intents hashed with the old zero-fraction timestamp format
fail the integrity gate; create a fresh intent and obtain fresh approval rather
than rewriting the stored digest or reusing old authority.
An approval is permission to attempt execution; current policy/balance/holds
are still checked when executing, and it never means money has moved.

The protected endpoints add student own-account review/confirmation at
`GET /api/v1/student/approvals` and
`POST /api/v1/student/approvals/{id}/decision`; the sponsor routes keep their
existing decision payloads. Both lists return masked `ApprovalView` records
without balances, bank identifiers, raw terms or student-private summaries.
`POST /api/v1/payment-intents/{id}/approval-requests` has an empty body. Owner
confirmation requires the exact reviewed `terms_hash` and trusted origin.
Stale/expired/consumed/conflicting authority returns a sanitized 409.

Sponsors manage own-account allowance mandates through GET/POST
`/api/v1/sponsor/mandates` and PUT/DELETE `/api/v1/sponsor/mandates/{id}`.
Writes require `mandate:manage`, granted to new sponsor seeds only. Existing
actors are not silently upgraded. Limits are integer minor units; source
timezone, active student relationship and verified beneficiary fingerprint
come from trusted server records. Updates retain immutable revisions and
revocation retains history. Expired mandates may be replaced; creating or
replacing one never resets account-wide spending. Reading/revoking existing
owned mandates remains available during a financial-adapter outage.

`FinanceApprovalRepository` implements the full-terms CAS state hook and is
installed in runtime approval and finance services. Missing tables or required
configuration still return sanitized 503 responses. Call
`service.invalidate_for_revision(connection, actor, intent_id)` after revising
terms. Inside protected execution, use
`await service.authorize_execution(connection, actor, action)` on the worker
thread with the caller's connection. This wraps B-02 with authority loaded
from B's store and consumes an approved T2 record once. It rechecks time-sensitive
policy after audit/session work and rolls back stale authority. C retains
locks, creates the transfer and ledger debit on that same transaction, then runs
a rejecting-only finalizer before commit to recheck authority/quote/policy
expiry and the current session. The provider is called only after commit. Rollback
restores consumption/audit, and caller idempotency must resolve prior outcomes
before invoking authorization again. Do not cache or reuse preview decisions.
Tests cover both the isolated adapter and actual default HTTP wiring with real
sessions, B authority and C's simulated SQL ledger. Test-only adapters are never
installed in application wiring. Sponsor browser sign-in, approve/reject and
student continuation against the real backend were manually verified on
2026-10-17; see B-04 in `docs/progress/progress-b.md` for database evidence.
The complete agent-driven flow remains a separate check. Real-session HTTP tests also
verify simulated T1 allowance execution, cumulative mandate limits, revocation,
and current beneficiary ownership/purpose checks before debit. Admin provisioning and
session/consent reset semantics are also separate coordinated work.

Auth tests use a fresh temporary PostgreSQL instance when `initdb` and `pg_ctl`
are on PATH. Its files remain ignored under `.generated/`. Alternatively set
`RANTAU_TEST_DATABASE_URL` to a **dedicated test database whose name starts with
`rantau_test`**. Tests truncate its auth and policy-decision tables; never point it
at an application database. CI provisions its own PostgreSQL 17 service. Tests do
not use the local application's `DATABASE_URL` or bootstrap passwords.

## Finance, university simulator and demo (Dev C)

Apply the ordered auth and finance migrations, then reset the isolated demo fixture
(development/test only; touches Dev C tables, never identities or audit history):

```powershell
uv run python -m backend.demo.reset --migrate --scenario tuition_happy_path
```

Scenarios: `tuition_happy_path`, `forged_beneficiary`, `demo_long_quotes`,
`tuition_missing_reference`, `shortfall_topup_off`, `shortfall_topup_on`,
`provider_timeout`, `provider_unavailable`, `delayed_posting`. All data is synthetic.

Finance routes live under `/api/v1` (obligations, quotes, payment intents, transfers,
reconciliations, audit) and demo controls under `/api/v1/demo` (administrator only).
Payment writes use B's stored approval/mandate/hold readers and protected consumption;
no scripted authority is installed in the application. The provider and university are
simulated: payment delivery is never tuition paid, and posting happens only when the
simulated clock reaches the receipt's posting time (`POST /demo/university/tick`,
`POST /tuition/obligations/{id}/recheck`).

Finance tests need PostgreSQL binaries on PATH (for example
`C:\Program Files\PostgreSQL\18\bin`) or `RANTAU_TEST_DATABASE_URL`; they use their own
`rantau_test_finance` database. The `/student/payments` and `/demo` pages read the backend
through the server-only `FINANCE_API_ORIGIN` (falls back to `AGENT_API_ORIGIN`) and relay
mutations through fixed-path same-origin handlers.

## Demo runbook (simulated)

1. Prepare the isolated database once (see the backend authentication section for
   bootstrap): `uv run python -m backend.authz.bootstrap --migrate --seed`, then
   `uv run python -m backend.demo.reset --migrate --scenario tuition_missing_reference`.
2. Run the whole story without a browser. The sponsor's approval is **simulated** because
   Dev B's approval store is not connected; the real gate, ledger, provider and university run:

   ```powershell
   uv run python -m backend.demo.replay --flow all
   ```

   `happy` shows provider delivery is not tuition paid, then the university posts after the
   simulated clock moves. `hero` recovers a payment that arrived without a reference and
   posts it once with no second debit. `attack` plants untrusted messages, holds a forged
   payee with zero debit, and still pays the verified university.
3. In the browser, `/student/payments` shows the trust timeline, pending requests with exact
   terms, quotes, receipts and untrusted messages (English or `?lang=id`). `/demo` offers
   scenario reset, clock, fault injection, the university tick and the redacted audit trail
   for a demo administrator. `/sponsor` provides sponsor browser sign-in and
   approval decisions. Dedicated student and administrator sign-in pages are not built yet.
4. With Docker running, the same setup commands can be run through
   `docker compose run --rm backend uv run --no-sync python -m backend.demo.reset --migrate`
   (not verified on this machine).

`/ready` reports `finance_storage` separately; `domain_services` stays false until the agent
is wired to trusted services.

## Checks and isolated demo

```powershell
uv run pytest tests -v
uv run mypy
uv run ruff check .
uv run python scripts/check_repo_hygiene.py
uv run python -m backend.agent.demo --fake-classifier
uv run python -m scripts.export_openapi
Push-Location frontend
npm run generate:contracts
npm run typecheck
npm run lint
npm run build
npm exec -- playwright install chromium
npm run test:e2e
Pop-Location
docker compose config --quiet
```

Browser checks start a production frontend on port 3100 and an isolated transport
test double on port 8101. Both ports must be free; they do not use the real backend
or model. Test artifacts stay in ignored `.generated/`.

The offline demo forces six classifications and uses isolated synthetic adapters;
it demonstrates graph routing, not live model quality or real payments. The OpenRouter
adapter uses its `https://openrouter.ai/api/v1` endpoint with the compatible Python
SDK, a configurable provider/model ID, JSON-schema output and safe failure handling.
Provider routing requires parameter support and requests `data_collection: deny`.
These are provider-routing preferences, not an independent privacy/compliance guarantee.
Set the key/model
locally; the old `OPENAI_API_KEY`/`OPENAI_MODEL` variables are not used.
Live API access requires separate verification. Keep task updates in the shared
progress folder: [Dev A](docs/progress/progress-a.md),
[Dev B](docs/progress/progress-b.md), and [Dev C](docs/progress/progress-c.md).
Each owner updates their task checkboxes, descriptions and validation evidence in
the same commit/PR as the work. See `AGENTS.md` section 7 for the full workflow.

## Interactive agent and conversation state

After setting `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` in the ignored local
`.env`, start the explicit isolated harness:

```powershell
uv run python -m backend.agent.demo --openrouter
# Or send several turns in one process:
uv run python -m backend.agent.demo --openrouter --message "Pay my tuition" --message "Use the full balance"
# Opt into public official-source reads when shortfall guidance is missing:
uv run python -m backend.agent.demo --openrouter --web-guidance
# Check those sources alone, without a model/key or financial data:
uv run python -m backend.agent.demo --research-shortfall
```

This calls the configured OpenRouter model for intent and bounded tuition-field
interpretation. Domain reads use synthetic fixtures and the explicit November
scenario clock. Replies explain scoped data deterministically. The harness can
build a typed draft preview; it cannot persist a payment intent, approve, debit,
post tuition or clear a hold. It does not install fake authentication or a fake
authorization gate in the application. `/quit` exits interactive mode.

Shortfall guidance checks the reviewed KB first. With `--web-guidance`, a missing
claim triggers a bounded read of two curated ZJU pages, used only as procedural
inspiration for the fictional university. This is source discovery, not unrestricted
web search or automatic procedure extraction: keyword matches are unreviewed leads.
The response includes source links, curated publication dates (or unknown), cohort
limits and the actual UTC retrieval time. Fresh pages never change payment rules.
Without an applicable reviewed procedure, the response stays pending university
review and asks for receipt/reference and expected-versus-posted evidence. It does
not submit a case, approve a top-up or alter tuition posting. The authored 48-hour
posting window and November scenario clock remain fixture configuration; establishing
a real university SLA is not an MVP blocker.

The lookup sends only fixed public HTTPS requests, with no chat text, identifiers,
cookies, credentials or financial details. It follows no redirects/links, accepts
only uncompressed HTML up to 256 KiB per page, bounds each fetch to six seconds,
and caches results for five minutes. Downloaded text is discarded after lead detection;
it is not displayed, persisted, added to the KB or sent to the model. Missing,
oversized, unsupported or unreachable sources keep the response pending review.
Default offline runs make no network requests. Trusted application wiring can inject
`OfficialSourceLookup` into `AgentTools` later; the HTTP service still requires
trusted domain adapters and opted-in authentication. The Scenarios tab stays scripted.

A-03 remembers tuition obligation, funding and quote selections across turns.
The backend reloads current permissions, policy, quotes and verified payee each
turn; remembered IDs are not financial authority. Server wiring supplies the
university-to-beneficiary-registry mapping; document/model text cannot supply it.
Ambiguous selections ask only for the missing choice. Invalidated funding/quotes
require a fresh choice, and partial/unclear amounts require clarification.

For HTTP clients, generate one opaque `conversation_id` per new chat and send it
in the existing agent-message field on each turn. The server namespaces memory
by verified tenant, student, session and conversation ID. Omitting the ID keeps
the existing stateless behavior. A new conversation ID starts fresh; an explicit
restart clears the tuition draft. The integrated API still requires B/C services.

The initial `InMemoryConversations` adapter holds at most 128 conversations,
expires inactive drafts after 30 minutes and serializes turns for each key. It
is single-worker/process-local: restart, worker change or expiry loses the draft.
It stores no raw transcript, approval or cached authorization. Only the previous
intent, pending field and option counts accompany the current redacted user text
to the model; server IDs, balances and tool outputs stay outside model context.
The store interface allows later PostgreSQL persistence after shared schema
coordination; no database migration is introduced here.
