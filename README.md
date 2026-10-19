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

`/health` reports process liveness. `/ready` remains a conservative 503 gate during
the staged agent financial integration; it reports authentication and finance
storage separately. Chat is wired to verified sessions, scoped
simulator reads, OpenRouter and PostgreSQL draft/run storage. It requires the
configuration and explicit setup below. Explicit tuition confirmation/continuation
uses B/C protected services; no identity is accepted from claimed headers/chat text.

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

To use the `/demo` controls in a browser, set `AUTH_DEMO_ADMIN_PASSWORD` (12–128
characters) and run `uv run python -m backend.authz.bootstrap --seed-admin`. It adds only
the `admin` user (`DEMO_ADMIN`, scope `demo:manage`, no payment or approval authority) to
the existing tenant and refuses to overwrite one. Sign in with it through the sponsor
sign-in form, then open `/demo`.

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
services during the remaining agent financial-workflow integration; its global
status does not serve as the read-only Chat availability probe.

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

The default Chat `VERIFY_MESSAGE` path uses B's `SecurityAgentReadPort` for
advisory assessment. It rechecks the current student session before and after
classification, combines bounded local cues with optional redacted OpenRouter
signals, and falls back to local cues if semantic assessment is unavailable.
It does not infer beneficiary legitimacy or create financial authority. With no
signals, the result still requests verification with a trusted source. This
read adapter remains advisory. Separately, the agent checks the current confirmed
tuition action before model routing: existing deterministic B hard findings or
local prompt-injection cues place a scoped persistent hold and security case
atomically. Model-only signals cannot select a hold, grant approval or change a
recipient. Without a confirmed action in this session/conversation/scenario,
message verification remains advisory and cannot target a different request. Request-scoped classifier clients are closed when
the request completes.

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
and current beneficiary ownership/purpose checks before debit. Demo reset also revokes open approvals,
mandates and consent, clears holds and resolves open cases (history is kept, sessions stay
signed in); admin provisioning is `bootstrap --seed-admin`.

`GET /api/v1/security-cases/{id}` returns a scoped `SecurityCaseView` with
`case_id`, `resource_id`, `state`, `reason`, `created_at`, `updated_at` and
`audit_event_id`. Reporter identity and evidence references remain internal.
Reads require a current real session and the existing role-specific read scope;
related funding owners and explicitly scoped reviewers use the trusted resource
adapter. Missing and inaccessible cases both return the same 404; unavailable
case storage returns a sanitized 503. Responses are `no-store`. This read endpoint
does not expose hold placement/clearing or reviewer decisions. Agent invocation
is recorded under B-07 and the read-only sponsor case panel under B-06 in
`docs/progress/progress-b.md`.

`GET /api/v1/security-cases` returns `SecurityCaseList`, a bounded page of the
same seven fields for cases in the caller's relationship scope (cases they
opened, or the tenant page for an explicitly scoped reviewer). The storage bound
is 100 cases ordered by `updated_at DESC`; an actor with no case receives
`{"cases": []}` rather than a 404, and the same session revalidation, `no-store`
and sanitized-503 rules apply. It is read-only: no hold-clear or case-decision
route is exposed. The sponsor workspace shows the signed-in sponsor's own cases
from this endpoint; clearing a hold or deciding a case still happens in separate
trusted review tooling.

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
2. Run the whole story without a browser. The student and sponsor act through real
   sessions (set both bootstrap passwords in the local `.env`); the sponsor's exact-terms
   approval is a real owner decision that the executor consumes once:

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

`/ready` reports `finance_storage` separately; `domain_services` remains false during
the staged agent financial-workflow integration. Read-only Chat handles its own
configuration/storage checks and does not change global readiness in this slice.

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

`OPENROUTER_MAX_TOKENS` bounds combined reasoning and visible output (default
2048, range 512–8192). An exhausted budget can return no JSON; the agent then
fails safely without acting. Optionally set `OPENROUTER_REASONING_EFFORT` to an
effort supported by the selected model; omitted/empty retains provider defaults.
For optional-reasoning classifiers, `none` can leave more budget for the schema.
Mandatory-reasoning models may reject `none`. These settings also pass through
Compose. See [OpenRouter's reasoning guidance](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).
Missing tuition funding/amount/quote selections are clarified by the deterministic
planner; model clarification is reserved for an unclear intent.

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

The KB explicitly lists two fictional simulator policies: `cn_demo_v1` keeps
partial payments and top-ups disabled; `cn_demo_v1_topup` matches C's existing
`shortfall_topup_on` scenario and permits top-ups while partial payments stay
disabled. The original default record and ZJU reference remain unchanged.
Recognition compares every policy field with its listed record, allowing only
the verification/validity timestamps to move together to the persisted seed time.
The validity offsets must match exactly, a future verification time is rejected,
and the stored policy still expires; requests never renew it. Unknown identities,
versions or changed rules stay pending. Unlisted JSON files cannot activate a
policy. Recognizing the top-up variant supplies guidance only: it does not enable
an agent payment action, grant approval or bypass the protected executor.

Shortfall guidance checks the reviewed KB first. The isolated `--web-guidance` /
`--research-shortfall` harness retains its two curated page reads. Live Chat can
use official-domain search when `AGENT_WEB_RESEARCH_ENABLED=true` is configured in
the ignored root `.env` (restart backend workers; Compose passes it through).
`OPENROUTER_RESEARCH_MODEL` optionally overrides the configured model for research;
otherwise it uses `OPENROUTER_MODEL`. The flag defaults to false.

Research uses the [OpenRouter web-search server tool](https://openrouter.ai/docs/guides/features/server-tools/web-search)
in a separate request containing a fixed public ZJU/current-international-student
topic. It sends no private conversation, financial state, user IDs or documents.
The Exa engine is restricted to `iczu.zju.edu.cn` and `cwcx.zju.edu.cn`, one search
and at most three results. Search/model usage is billed to existing OpenRouter
credits. Run a standalone public-topic check explicitly with:

```powershell
uv run python -m backend.agent.demo --search-shortfall
```

Only validated official HTTPS citation URLs are fetched. Redirects, credentials,
query/fragment URLs, nonofficial hosts and oversized/unsupported responses are
rejected; each public HTML read remains capped at six seconds and 256 KiB. No
cookies, authentication headers or environment proxy are sent to source pages.
The research lookup is bounded to 18 seconds, further reduced by the Chat turn's
remaining 21-second research deadline; it never extends the financial action
budget. A worker shares at most four public cache entries, caches successful
search results for five minutes and failures for 30 seconds, and allows only one
paid research request at a time. A busy worker returns a truthful unavailable
result rather than starting another search. Search usage and citation metadata
must validate before any discovered page is fetched; raw model prose is discarded.

Responses include cited, bounded and sanitized extractive procedural leads,
actual UTC check time and explicit date/cohort/applicability unknowns. Known
curated source dates/scopes are preserved. Source instructions that try to
override rules cause excerpts to be withheld. Raw pages are discarded; excerpts
never enter the financial model, persisted runs or executable KB policy. Leads
are **unreviewed**, not an applicable procedure. Missing or inaccessible evidence
keeps guidance pending university review, with receipt/reference and
expected-versus-posted evidence. Search never submits a case, approves a top-up,
changes the beneficiary or replaces simulator rules. The authored posting window
and scenario clock remain simulation configuration. Real university SLA research
is not a blocker to the approved simulator. Scenarios remain isolated and scripted.

Connected Chat now populates its detail panel after successful turns using
`GET /api/v1/agent/conversations/{conversation_id}/details?run_id={run_id}`.
The read requires the original current student session, an unexpired conversation,
the current scenario and the current committed run. Selected tuition, stored
quote, correlated request/approval, provider and linked recovery records are
projected into bounded fields; raw draft/account IDs, sponsor balances, terms
hashes and private evidence are excluded. Nothing is parsed from assistant prose
or chosen by guessing the latest payment. The Next.js detail relay validates the
entire snapshot, uses a fixed upstream path and forwards only the session cookie.

Cards show exact quote totals, actual approval/provider/case states and distinct
university posting status. Quote/approval expiry uses the security clock; provider
and university dates use the separate simulation clock. These are point-in-time
snapshots, refreshed after Chat turns, not live authorization. Reading details
cannot issue quotes, refresh/expire stored approvals, settle transfers, post
university credit, submit recovery or execute payments. Failed detail reads clear
old cards while retaining a successful assistant reply; session denial clears the
conversation. New chat and in-flight cancellation discard stale results. No new
financial action controls, migrations or transcript restoration are added.

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

## Durable agent drafts and run diagnostics

The connected tuition workflow supports these exact student commands after a
complete preview: `confirm tuition` (also `request tuition approval` or
`request approval`) saves a protected proposal and requests funding-owner approval
when required; `check` / `continue` reload current server authority and invoke only
the protected executor. Review the full preview before confirming. The funding
owner records approval in their authenticated workspace/API; text pasted into Chat
cannot approve anything. Exact commands need no model call or model credentials.
Every default Chat POST requires `Origin` equal to `AUTH_TRUSTED_ORIGIN`; the
same-origin frontend relay validates and forwards it with the session cookie.

`021_agent_actions.sql` stores immutable session/conversation/scenario-scoped retry
correlation. Intent creation and journal insertion commit together. A retry recovers
the same proposal; started/unknown payments are rechecked before another execution
attempt and use a stable server-owned idempotency key. No raw chat, credential,
balance, approval object or cached authorization is stored in the journal. Records
are retained during the MVP for correlation; they grant no permission. If changing
confirmed terms, cancel or revise the original request in Payments before confirming
a replacement. New sessions/scenario resets cannot resume the previous action.
Provider delivery remains separate from verified university posting.

Recovery uses the existing Chat input. Enter `recover <payment reference>` (for
example, the actual `transfer_...` reference shown in Payments) to select and
investigate a payment. The backend derives its obligation from the persisted
payment/intent relationship; it does not infer linkage from unrelated records.
`submit recovery` collects the backend receipt, provider reference, delivered
amount and authenticated student's reference claim, then submits a case through
the existing reconciliation gate when an exception requires review. Merely
investigating creates no case. `check recovery` polls existing provider status and
rechecks university records without executing another payment. These two exact
commands need no model credentials; they require a current scoped selection and
the same trusted Origin/session protections as tuition commands.

Case creation/submission and session revalidation share one transaction through
C's `create_in_transaction` / `submit_in_transaction` helpers. Retries recover the
same case even after response loss or independent resolution; case/review states
and linked university postings determine the reply. Only the independent
simulated university reviewer resolves missing-reference cases. The agent cannot
approve reconciliation or directly post credit. Provider delivery is never a
paid claim. Delayed posting remains pending until C's due-posting recheck; a
shortfall displays the exact remaining balance and current synthetic top-up
permission, requiring a separate proposal/approval for any additional payment.

For tracking/recovery without a known reference, Chat lists up to ten eligible
tuition payments using existing scoped C reads. Say `list payments`, then
`select payment 1` (or another advertised number). Listing never guesses a payment;
selection refreshes the same student's persisted payment/intent/obligation link
and changes no financial record. Exact list/selection commands work without a
model key. Options are IDs only, scoped to the verified session, conversation and
scenario. A new session, conversation or reset requires a fresh list. Exact
`submit recovery` is still required before case creation/submission. Allowances
and top-up execution are not added by these read-only choices. The existing C
intent reader fetches its scoped list; the agent refuses lists over 100 intents
rather than presenting a misleading truncated selection. A bounded DB pagination
interface remains a separate C coordination improvement if needed.

Fraud guidance translates only recognized existing B indicator codes into
advisory reasons and trusted-channel verification steps. Unknown indicator text
is never echoed, and absence of indicators never proves legitimacy. Model-only
signals cannot approve payments or clear holds; existing deterministic B rules
remain authoritative.

Recovery stores only selected payment/obligation/case IDs in the existing scoped
conversation JSON; no new migration or HTTP fields are required. Update backend
workers together: older strict draft readers do not understand new recovery
fields/options and fail closed rather than restore them. New readers also accept
older drafts with no `payment_options` field. Browser transcript restoration
remains separate work.

The approved A-03-F1 adapters implement the same memory/run interfaces using
PostgreSQL. Explicitly apply the existing B/C migrations followed by
`020_agent_storage.sql` and `021_agent_actions.sql` to the configured database:

```powershell
uv run python -m backend.agent.migrations
```

This command creates no identities, sessions or financial fixtures. It does not
run at application startup. Complete the existing explicit authentication bootstrap
and C scenario seed for an isolated demo database, and configure authentication,
`DATABASE_URL`, `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` locally. Chat uses the
verified student cookie. Open `/student/sign-in` with the configured student
credentials; successful sign-in continues to Chat. `/student/sign-in?next=payments`
continues to Payments. Only these fixed local destinations are supported. The page
reuses the existing login/session/logout relay and never selects an actor or role.
An existing student session can continue or sign out from the same page; another
role must sign out before using student credentials. Never put credentials or
API keys in browser code or chat.

Student tuition summaries show the exact outstanding amount and stored synthetic
tuition deadline in UTC, separately from quote expiry, provider delivery and
university posting windows. Displayed exchange-rate precision is rounded; exact
integer amounts, fees and backend calculations are unchanged. In the sponsor
workspace, **Summary language** switches exact-term summaries and confirmation
headings between English and Bahasa Indonesia. Language changes send no decision;
the existing explicit confirmation, terms hash and session checks remain required.

The default HTTP dependency now calls `backend.agent.wiring.configured_agent_services`.
It constructs B's real `AuthService`, C's `FinanceAgentReadPort`/scoped database reads,
the existing OpenRouter classifier and the durable graph/run factory. The fixed
fictional university binding is `uni_cn_01` to `benef_uni_cn_01`; only trusted server
code supplies it. A-04 attaches protected tuition confirmation/continuation;
A-05 attaches scoped recovery investigation, explicit case submission and status
rechecks. Deterministic fraud/hold integration uses the existing B services; only
a separate authorized reviewer can clear a hold.
SDK clients are scoped to each request and closed afterward. Missing classifier
configuration returns 503 `CLASSIFIER_NOT_CONFIGURED` on messages; missing required
finance/agent storage returns 503 `AGENT_STORAGE_UNAVAILABLE` before a model call.
No request migrates or seeds storage. Run retrieval uses the current verified
session and storage without requiring an API key or making a model request.

Scenarios stay scripted. The isolated CLI retains its explicit in-memory setup;
configured PostgreSQL adapters never fall back to process-local storage on error.

`PostgresConversations` retains only typed tuition/recovery selections and the previous
intent, scoped by tenant, student, verified session and conversation ID. Drafts
survive process/worker changes, expire after 30 idle minutes or earlier session
expiry, and are invalidated by a simulator reset. Storage is limited to 128 active
drafts per tenant and 64 KiB per draft; expired/invalid-session drafts are purged
on access. Login under a new session starts a new namespace. All resource,
permission, policy and quote checks still run again; stored IDs grant no authority.
To continue a saved draft, a client must reuse its `conversation_id` within the
same valid session. The current browser keeps that ID and visible messages only
in component memory; reload starts a new conversation. This backend change does
not restore a browser transcript or add a chat-history interface.

Workers serialize each conversation with a PostgreSQL advisory lock and a
five-second contention limit. Database work runs in bounded worker calls, including
on Windows' default event loop. No open transaction or auth/financial row locks span
model/network calls. A completed state and its run metadata commit together after
fresh session/scope/scenario checks. Errors and cancellation before commit roll
back the write; a completed commit remains recorded if the HTTP connection is
subsequently lost. Missing/corrupt storage produces a sanitized unavailable result.

`PostgresRuns` stores append-only diagnostic metadata: intent, allowlisted tool
events/resource references, scope and scenario identifiers. It stores no user text,
assistant prose, model output, credentials, account balances, full quotes or approval
objects. Records are limited to 64 events/resources and 32 KiB; identical writes
are idempotent and conflicting writes cannot replace history. There is no automatic
run-history deletion during the MVP, including on logout or fixture reset.

`GET /api/v1/agent/runs/{run_id}` keeps the existing response shape but reconstructs
a fixed safe message plus the saved diagnostics. It does not replay the original
assistant response or restore chat history. Only the original currently valid
student session can retrieve a run; logout, expiry, changed scopes/credentials or
disabled actors deny access. These are past orchestration diagnostics, not current
financial state or the authoritative B/C financial/security audit. New financial
tools must update the diagnostic allowlist and domain audit integration together.
