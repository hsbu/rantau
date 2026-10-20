# Rantau

**An AI financial assistant for students from Southeast Asia studying in mainland China and the people who sponsor them.**

Built by **Punteun Shenzhen**, Institut Teknologi Bandung, for **FinTechathon 2026 — Topic C**.

Rantau brings tuition planning, exchange-route comparison, funding-owner approval,
payment tracking and tuition exception recovery into one workspace. It answers a
question that a transfer receipt alone cannot settle: **has the university actually
credited the student's tuition?**

> This is a sandbox MVP. Balances, exchange quotes, transfers, providers and
> university ledgers are simulated. No real money moves. Live agent interpretation
> uses OpenRouter when configured; model requests may consume provider credits.

[Getting started](#getting-started-with-docker) · [Local development](#local-development) ·
[Demo walkthrough](#demo-walkthrough) · [Tests](#testing-and-quality-checks) ·
[Project layout](#project-layout) · [Team](#team)

## What Rantau does

- **Plan tuition payments:** read the student's obligation, credited amount, balance
  and deadline; compare simulated IDR-to-CNY routes with itemized fees and expiry.
- **Keep approval separate from execution:** sponsors approve their own funding;
  students confirm payments from their own accounts. Changed terms require fresh
  authority. A message claiming approval never substitutes for a protected decision.
- **Track the original payment:** distinguish provider delivery from university
  credit, check uncertain outcomes and prevent duplicate debits during retries.
- **Resolve tuition exceptions:** investigate missing references, wait for delayed
  posting and calculate exact shortfalls. Recovery submission does not itself mark
  tuition paid; the university simulator posts credit independently.
- **Protect the workflow:** enforce verified recipients, spending limits, expiring
  approvals, security holds, scoped access and redacted audit records.
- **Explain the next step:** show connected tuition, quote, approval, payment and
  recovery panels alongside Chat. Sponsor summaries support English and Indonesian.

The language model classifies requests within a fixed LangGraph workflow. Financial
rules, approvals and ledger changes are enforced by backend services. User-facing
financial responses are generated from checked state and templates, rather than
unrestricted model-written payment instructions.

## Architecture

```mermaid
flowchart LR
    User[Student or sponsor] --> Web[Next.js workspace and same-origin relays]
    Web --> API[FastAPI authenticated services]
    API --> Agent[LangGraph agent]
    Agent --> Model[OpenRouter intent classification]
    Agent --> Gate[Authorization and approval services]
    API --> Gate
    Gate --> Finance[Protected financial simulator]
    Finance --> Provider[Simulated payment provider]
    Finance --> University[Independent university posting and recovery]
    API --> DB[(PostgreSQL)]
    Finance --> DB
    University --> DB
```

| Layer | Implementation |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript; server-side relays keep provider keys out of the browser |
| Agent | Python, LangGraph, configurable OpenRouter model, bounded policy/source lookup |
| API and security | FastAPI, verified database sessions, exact-term approvals and deterministic policy checks |
| Persistence | PostgreSQL 17; migrations, ledger, approvals, cases, conversation drafts and audit metadata |
| Quality checks | pytest, mypy, Ruff, TypeScript, ESLint and Playwright; GitHub Actions |

Provider delivery and tuition completion are separate states. All monetary
calculations use integers: IDR is stored in whole rupiah and CNY in fen
(100 fen = CNY 1).

## Prerequisites

Choose Docker for the complete sandbox, or install the local toolchain for development.

| Tool | Docker sandbox | Local development |
| --- | --- | --- |
| Git | Required | Required |
| Docker Engine/Desktop with Compose v2 | Required | Optional, for PostgreSQL |
| Python | Included in image | Python 3.12 recommended; supported range is 3.12–3.13 |
| uv | Included in image; build pins 0.11.27 | Required; 0.11.27 matches CI |
| Node.js and npm | Included in image | Node.js 22.13+; Node 22 matches CI |
| PostgreSQL | Included, version 17 | PostgreSQL 17 recommended |
| OpenRouter account/key | Needed for connected natural-language Chat | Needed for connected natural-language Chat |

The scripted Scenarios page and offline agent harness need no model key. Payment,
Sponsor and Demo services still require database setup and real sandbox sessions.
The offline harness is not a substitute for authenticated integration testing.

## Getting started with Docker

The commands below use PowerShell and run from the repository root. The same
`git`, `docker`, `uv` and `npm` commands work in other shells; adapt file-copy and
environment-variable syntax as needed.

### 1. Clone and configure

```powershell
git clone https://github.com/hsbu/rantau.git
Set-Location rantau
Copy-Item .env.example .env
```

Edit the ignored `.env` file. At minimum, configure:

```dotenv
AUTH_ENABLED=true
AUTH_TENANT_ID=demo_001
AUTH_TRUSTED_ORIGIN=http://127.0.0.1:3000
AUTH_DEMO_STUDENT_PASSWORD=<choose-a-private-student-password>
AUTH_DEMO_SPONSOR_PASSWORD=<choose-a-different-sponsor-password>
AUTH_DEMO_ADMIN_PASSWORD=<choose-a-different-admin-password>
OPENROUTER_API_KEY=<your-private-openrouter-key>
OPENROUTER_MODEL=<provider/model-id>
```

Replace every placeholder. Choose distinct passwords of 12–128 characters. The
model must support JSON-schema structured output. Leave optional web research
disabled for the initial setup. Never copy `.env` into the frontend or commit it.

Compose configures the backend database connection using the `db` service name.
The database username/password in `compose.yaml` are disposable local-demo
credentials, not deployment secrets. Ports 3000, 8000 and 5432 must be free.

### 2. Build, initialize and start

```powershell
docker compose build
docker compose up -d db
docker compose run --rm backend uv run --no-sync python -m backend.authz.bootstrap --migrate --seed --seed-admin
docker compose run --rm backend uv run --no-sync python -m backend.agent.migrations
docker compose run --rm backend uv run --no-sync python -m backend.demo.reset --scenario tuition_happy_path
docker compose up -d backend frontend
```

These explicit steps create the synthetic `student`, `sponsor` and `admin`
identities, apply all authentication/finance/agent migrations and initialize a
scenario. Application startup never creates identities, migrates or seeds data.
Bootstrap deliberately refuses to overwrite an existing demo tenant. On subsequent
starts, use `docker compose up -d`; do not repeat the identity-seeding command.

### 3. Open the workspaces

| Workspace | URL | Sign in as |
| --- | --- | --- |
| Student entry | http://127.0.0.1:3000/student/sign-in | `student` |
| Connected Chat | http://127.0.0.1:3000/student/chat | Current student session |
| Payment status and student approval | http://127.0.0.1:3000/student/payments | Current student session |
| Sponsor decisions | http://127.0.0.1:3000/sponsor | `sponsor` |
| Demo controls | http://127.0.0.1:3000/demo | `admin` |
| Scripted Scenarios | http://127.0.0.1:3000/student/chat/preview | No account required |
| API documentation | http://127.0.0.1:8000/docs | Protected endpoints still require a session |

Use the passwords chosen in `.env`; there is no shared default password. There is
no dedicated administrator sign-in page: use the existing form at `/sponsor` with
`admin`, then navigate to `/demo`. The sponsor page will correctly reject the admin
role for the sponsor inbox; the authenticated admin session can access Demo.

The seeded tenant already links the student to the sponsor's permitted funding
account. This permission does not grant the sponsor unrestricted access to the
student's private records; summary sharing is controlled separately by consent.
The default fixture starts with CNY 20,000 tuition due, IDR 60,000,000 in the
student account and IDR 150,000,000 in the sponsor account.

Use separate browser profiles or private windows for the student, sponsor and
administrator. Tabs in one browser profile share a session cookie and cannot
represent independent actors simultaneously. Use `127.0.0.1` consistently; changing
to `localhost` changes the cookie host and trusted browser origin.

### 4. Check and stop the stack

```powershell
docker compose ps
docker compose logs --tail 80 backend frontend
Invoke-RestMethod http://127.0.0.1:8000/health
docker compose down
```

`/health` reports process liveness. **`/ready` currently always returns HTTP 503**
because its `domain_services` gate is still hard-coded false. It reports individual
database, authentication, finance-storage and classifier checks, but is not yet a
passing deployment-readiness probe—even when the configured application works.

`docker compose down` preserves the database volume. After bootstrap, passwords
can be removed from `.env`; recreate the backend container to remove them from its
environment. Keep them privately for sign-in. The replay CLI needs the student and
sponsor passwords configured again when explicitly used.

## Local development

Use this route when editing Python or frontend source. Do not run the Docker
backend/frontend at the same time on the same ports.

### Install dependencies and generate API types

```powershell
uv sync --locked
uv run python -m scripts.export_openapi
npm --prefix frontend ci
npm --prefix frontend run generate:contracts
```

The schema exporter writes `.generated/openapi.json`; the frontend generator writes
`frontend/lib/api-contracts/generated.d.ts`. Both are ignored outputs. Regenerate
when API contracts change; do not hand-edit or commit generated types.

### Initialize the local database

Copy/configure `.env` as above. For the PostgreSQL service supplied by Compose:

```powershell
docker compose up -d db
uv run python -m backend.authz.bootstrap --migrate --seed --seed-admin
uv run python -m backend.agent.migrations
uv run python -m backend.demo.reset --scenario tuition_happy_path
```

The template's host connection points to
`postgresql://rantau_demo:local_demo_only@127.0.0.1:5432/rantau_demo`.
For your own PostgreSQL instance, create a dedicated empty database and set
`DATABASE_URL` accordingly. If the tenant is already initialized, skip bootstrap
and apply migrations only. A scenario reset replaces the current financial run;
it is not needed just to restart the servers.

Create `frontend/.env.local` containing only the server-side relay origin:

```dotenv
AGENT_API_ORIGIN=http://127.0.0.1:8000
```

`FINANCE_API_ORIGIN` is optional and falls back to `AGENT_API_ORIGIN`. Restart
Next.js after changing either setting. The root `.env` is read by the Python
application and Compose; Next.js reads its own environment file.

### Start both servers

Terminal 1, from the repository root:

```powershell
uv run python -m backend.server --host 127.0.0.1 --port 8000
```

Terminal 2, also from the repository root:

```powershell
npm --prefix frontend run dev
```

The workspace is at http://127.0.0.1:3000. For a local production build instead of
the development server:

```powershell
npm --prefix frontend run build
$env:HOSTNAME = "127.0.0.1"
$env:PORT = "3000"
npm --prefix frontend run start
```

The build script prepares Next.js standalone output and static assets. Keep
`.next/`, dependency folders, credentials and local database files out of Git.

## Demo walkthrough

1. Select `tuition_missing_reference` in the administrator's Demo workspace and
   confirm the reset. Begin a new student conversation afterward.
2. As the student, ask: **“Help me pay my tuition using my sponsor's account.”**
   Review the CNY obligation, IDR principal, fee, total debit, recipient and expiry.
   Supply a missing funding or route choice if asked.
3. Send **`confirm tuition`**. In the separate sponsor workspace, review the exact
   request and explicitly approve it. Approval alone does not transfer funds.
4. Return to the student and send **`continue`**. Verify provider delivery and
   university credit separately; the missing-reference scenario is not paid yet.
5. Send **`list payments`**, then **`select payment 1`** if it is the intended
   payment. Review the payment details before sending **`submit recovery`**.
6. In the independent administrator workspace, run the **University tick**.
   Return to the student and send **`check recovery`**. Tuition is paid only after
   the linked university posting is verified, with no second debit.

For self-funding, request the student's own account and review/approve the request
in Payments before continuing. For changed terms, review the revised draft and
send `confirm revision`; valid replacements need fresh owner approval. Partial
tuition payments and arbitrary recipients remain blocked by the agreed policy.

The Scenarios page is a separate scripted preview with no API/model calls. It does
not prove that authentication, approvals or financial execution work. The scenario
table below describes the available fixtures. For connected journeys, verify the
payment record and university credit independently in their respective workspaces.

### Available simulator scenarios

| Scenario ID | Purpose |
| --- | --- |
| `tuition_happy_path` | Verified university payment with normal delivery/posting |
| `tuition_missing_reference` | Delivered funds require recovery before university credit |
| `delayed_posting` | Provider delivery precedes the university posting window |
| `shortfall_topup_off` | Exact shortfall; additional payment forbidden by synthetic policy |
| `shortfall_topup_on` | Exact shortfall; protected top-up workflow requires fresh authority |
| `provider_timeout` | Provider accepts a payment but its response is lost |
| `provider_unavailable` | Authoritative failure; preserve debit/reversal history and avoid blind retry |
| `forged_beneficiary` | Untrusted instructions and an unverified recipient |
| `demo_long_quotes` | Longer quote expiry for a recorded walkthrough |

### Reset and replay

Only reset a database/run you own; a reset replaces synthetic balances and financial
records, closes open authority and invalidates existing agent selections. Identities
and historical audit records are retained. Do not reset another person's rehearsal.

```powershell
uv run python -m backend.demo.reset --scenario tuition_missing_reference
uv run python -m backend.demo.replay --flow all
```

`replay` runs the `happy`, `hero` and `attack` flows with real local student/sponsor
sessions and simulated financial services. **It resets the scenario for each flow.**
It needs the configured bootstrap passwords and is not an actual-model browser demo.
For Docker, prefix each Python command with
`docker compose run --rm backend uv run --no-sync` and omit the host `uv run`.

## Configuration reference

| Setting | Purpose / default |
| --- | --- |
| `APP_ENV` | `development` for this sandbox; bootstrap/reset refuse non-development/test environments |
| `DATABASE_URL` | Dedicated PostgreSQL connection; host uses `127.0.0.1`, containers use `db` |
| `AUTH_ENABLED` | Must be `true` for integrated authenticated services; template default is `false` |
| `AUTH_TENANT_ID` | Explicit seeded tenant: `demo_001` |
| `AUTH_TRUSTED_ORIGIN` | Exact browser origin, normally `http://127.0.0.1:3000`; no trailing slash |
| `AUTH_DEMO_STUDENT_PASSWORD` / `AUTH_DEMO_SPONSOR_PASSWORD` | Initial private credentials; also needed by the explicitly invoked replay CLI |
| `AUTH_DEMO_ADMIN_PASSWORD` | Initial private credential for optional demo administration |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | Server-only live intent-classification configuration |
| `OPENROUTER_MAX_TOKENS` | Shared reasoning/output budget, 512–8192; default `2048` |
| `OPENROUTER_REASONING_EFFORT` | Optional provider-supported reasoning effort; omit for provider defaults |
| `APPROVAL_TTL_SECONDS` | Owner approval lifetime, 1–3600 seconds; default `600`, capped by quote expiry |
| `AGENT_API_ORIGIN` | Next.js server-only backend destination; set in `frontend/.env.local` for host development |
| `FINANCE_API_ORIGIN` | Optional server-only Payments/Demo destination; defaults to the agent origin |
| `AGENT_WEB_RESEARCH_ENABLED` | Default `false`; explicitly enables bounded, billed official-source research |
| `OPENROUTER_RESEARCH_MODEL` | Optional research-capable model override; otherwise uses the classifier model |

Optional web research sends fixed public topics, not private chat or financial
state. Official-source excerpts remain cited, unreviewed leads: they cannot activate
payment policy, change recipients, clear holds or authorize a transfer. Model
capabilities and output budgets vary; an unsupported configuration fails safely.

## Testing and quality checks

Run from the repository root unless stated otherwise. Use a dedicated test database,
never the demo database or a database containing information you need to retain.

### Backend

```powershell
uv run pytest tests -v
uv run mypy
uv run ruff check .
uv run python scripts/check_repo_hygiene.py
```

Database tests either create a temporary PostgreSQL cluster using `initdb` and
`pg_ctl` on `PATH`, or use `RANTAU_TEST_DATABASE_URL`. If supplying that variable,
the database name must start with `rantau_test` and the role must be able to create
and drop the suite's sibling databases. **Tests truncate tables and drop/recreate
test databases**, including `rantau_test_finance`. Use a separate test PostgreSQL
instance/role rather than an application or shared development database.

### Frontend

```powershell
uv run python -m scripts.export_openapi
npm --prefix frontend run generate:contracts
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run build
```

Then install Chromium and run Playwright from the frontend directory:

```powershell
Push-Location frontend
npx playwright install chromium
npm run test:e2e
Pop-Location
```

On Linux, use `npx playwright install --with-deps chromium` if browser dependencies
are missing. Playwright uses ports 3100, 8101 and 8102 and starts its own mocked
agent/finance backends. A passing browser suite is not evidence of live-model
behavior or real-session financial integration; those are separate scenario checks.

Additional configuration/offline checks:

```powershell
docker compose config --quiet
uv run python -m backend.agent.demo --fake-classifier
```

Do not paste unfiltered `docker compose config` output into reports: expanded
configuration may contain locally supplied credentials. CI runs backend tests,
typing/lint, frontend generation/build/browser checks and repository hygiene; its
workflow is in [.github/workflows/ci.yml](.github/workflows/ci.yml).

## Evidence and current limitations

The [shared execution-evidence archive](https://drive.google.com/drive/folders/1VRynaCanS2q4AlguVjaf-M5s9FVr8flS)
contains scenario records and available screenshots. Captures identify their own
build, model and evidence level where recorded. Historical results are not a claim
that every scenario passed on the current checkout.

A read-only local export can capture the current simulator run and persisted agent
diagnostics before a reset:

```powershell
uv run python -m scripts.capture_demo_evidence --output .generated/acceptance/hero/before-posting.json
```

Use a new filename for each checkpoint. This output is ignored, bounded and requires
redaction/review before sharing. It does not replace browser screenshots, a video,
security evidence or independent scenario review. Do not commit logs, screenshots,
database dumps or generated acceptance output.

Current boundaries:

- All financial connections and executable university policies are simulated;
  official university references do not verify the synthetic posting timetable.
- Agent replies use checked-state templates; open-ended conversational generation
  is not implemented. Model interpretation remains a bounded routing task.
- Drafts persist in PostgreSQL within the original valid session, with a 30-minute
  idle expiry. Browser reload starts a new conversation; transcript restoration
  and a chat-history interface are not implemented.
- Allowance services and policy-permitted top-ups have protected backend workflows;
  complete agent execution/UI journeys for both are not established by the current
  agent slice. Shortfall guidance is not evidence of agent-executed top-up.
- General web search, additional institutions and automatic activation of researched
  policies are outside the approved source-lookup scope.
- `/ready` is not a passing deployment probe. Public production deployment, native
  device/accessibility verification, final release replay and independent scenario
  acceptance must be assessed separately from historical/local test results.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Chat reports `CLASSIFIER_NOT_CONFIGURED` | Set both OpenRouter settings and restart/recreate the backend. Scripted Scenarios does not exercise the live classifier. |
| Chat reports `AGENT_STORAGE_UNAVAILABLE` | Check the dedicated database connection and run the explicit agent migration command after auth setup. No automatic fallback is installed. |
| Sign-in fails or returns unavailable | Check `AUTH_ENABLED`, tenant configuration, migrated schema and seeded credentials. Bootstrap does not reset existing passwords. |
| HTTP 403 on a write | Match `AUTH_TRUSTED_ORIGIN` exactly to the frontend URL; use the intended account and cookie host. |
| HTTP 429 on sign-in | Wait for the login-throttle window instead of retrying repeatedly. Counters persist across workers. |
| Sponsor inbox is empty | Confirm the student submitted a request for that sponsor's account. Access to student summaries also requires the relevant student consent. |
| Quote or approval expired | Refresh current terms and obtain a fresh protected decision. Do not reuse a stale confirmation. |
| A request timed out | Check the original payment/request status before retrying; a lost response does not prove failure. |
| Types are missing | Export OpenAPI and regenerate frontend contracts before typechecking/building. |
| Playwright cannot start | Build first, install Chromium and free ports 3100/8101/8102. |
| Browser cannot reach a container service | Browser URLs use host ports; server-to-server container connections use service names. |

If changing host ports, update the browser origin and server-only relay origins
consistently. Report reproducible issues through the repository without credentials,
session cookies or private account information.

## Project layout

| Location | Purpose |
| --- | --- |
| [Backend](backend/) | Agent, authentication, approvals, security, payment simulation and university services |
| [API contracts](backend/contracts/) | Typed request, response and domain models; interactive API documentation is served at `/docs` |
| [Frontend](frontend/app/) | Student, sponsor and demo workspaces |
| [Database migrations](migrations/) | Versioned PostgreSQL schema changes applied by the explicit setup commands |
| [Utility scripts](scripts/) | Schema export, repository hygiene and bounded local evidence capture |
| [Tests](tests/) / [browser tests](frontend/tests/) | Automated checks described in the testing section |

This README contains the product description, setup instructions, operating guide
and known limitations. Temporary exports and test evidence belong in ignored
`.generated/`, not in the source package.

## Team

**Punteun Shenzhen — Institut Teknologi Bandung**

| Member | Team role |
| --- | --- |
| Muhamad Hasbullah Faris | Team leader |
| Nazwan Siddqi Muttaqin | Team member |
| Muhammad Zidni Alkindi | Team member |
| Nathaniel Jonathan Rusli | Team member |
| Sebastian Enrico Nathanael | Team member |

## Support and reuse

Report reproducible setup or product issues through the repository. Keep credentials,
session cookies and private account information out of issue reports. All financial
operations remain simulated. The repository currently has no license file; no
open-source license grant is implied by this README.
