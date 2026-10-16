# Rantau Dev A foundation

The requester approved S-01 contract shapes for the team on 16 October 2026.
The MVP source is [Rantau-MVP-Spec.md](../Rantau-MVP-Spec.md), with tickets in
[Rantau-3Dev-Roadmap.md](../Rantau-3Dev-Roadmap.md).

## Contracts (S-01)

Shared Python models live in `backend/contracts/`. Money uses strict safe integers:
IDR has scale 0 (whole rupiah), CNY scale 2 (fen). Quote `rate` is an exact decimal
string in destination major units per source major unit, rounded half up to the
destination minor unit. Quote totals include the explicit fee.

Payment, approval, tuition and reconciliation states are distinct. Provider
`DELIVERED` does not establish tuition `PAID`; a posted balance of zero does.
`ActorContext` is internal and never accepted from chat JSON. `terms_hash` is
opaque, produced and verified by trusted services; fixture hashes are synthetic.

`backend/contracts/http.py` lists all 21 MVP endpoints. `schema.py` exports the
catalogue and shared models without exposing executable B/C routes. Every
catalogue entry is marked `catalogue-only`. Session transport is illustrative;
Dev B owns its eventual authenticated implementation. Finance execution requires
an `Idempotency-Key` and trusted authorization inside its transaction.

Run `uv run python -m scripts.export_openapi` and generate frontend types from
`.generated/openapi.json`. Generated files remain ignored and reproducible.
The schema's security-case/audit/demo payloads remain opaque objects until their
owners supply domain shapes; no invented implementation is supplied here.

Tests use `tests/fixtures/` with an explicit fictional November clock. The two
synthetic quotes both deliver CNY 20,000, cost IDR 46,025,000 / 46,050,000, and
expire after 15 simulated minutes. Fake execution raises unavailable; requesting
an approval never manufactures an approved decision or a debit.

Do not integrate fakes into the running application. Typed read/proposal ports
are the seam for B/C implementations; the A-01 graph never receives execution,
approval-recording, hold-clearing or university-posting capabilities.

S-01 local validation: 31 contract/hygiene tests passed; strict mypy passed for
contracts, scripts and typed fixtures; Ruff passed; schema export succeeded.
The hygiene checker, ignore rules and Python dependency bootstrap ship with S-01
so this first source commit is itself reproducible and checked.

## Application skeleton (S-02)

Use the commands in the root README. Python 3.12/uv and Node 22.13+/npm are locked;
generated frontend types are rebuilt from the shared catalogue before checking.
The home page is a development status shell, not the later A-06 student chat.

`/health` reports liveness. `/ready` probes PostgreSQL connectivity without writing
schema and reports authentication/domain integration as unavailable. It remains
503 until real integrations are connected. `compose.yaml` uses service DNS for
PostgreSQL, loopback-bound host ports and explicitly synthetic local credentials.
No migration, finance table or mock gate is installed.

Local validation: Python contract/hygiene/application tests, strict mypy and Ruff;
locked frontend install, schema/type generation, TypeScript, ESLint and production
build; dependency audit reports zero vulnerabilities. Docker Compose configuration
validates. The Docker engine is unavailable, so container build/start and live
PostgreSQL connectivity have not been verified. CI repeats the available checks.

The lint setup uses ESLint 10 and TypeScript ESLint. The Next-specific shared lint
preset was omitted because its transitive glob dependency has an unpatched high
severity advisory. Next production compilation/type checks still run independently.

S-02 targeted tests: 34 passed. Strict mypy passed for 11 source files.
Both local HTTP services started: frontend returned 200 with Rantau branding;
backend /health returned 200 with simulation=true; /ready correctly returned 503
with unavailable dependency flags. This is process/startup evidence, not financial
integration or PostgreSQL runtime evidence.

## Agent foundation (A-01)

The fixed LangGraph routes ASK_POLICY, TUITION, ALLOWANCE, TRACK, RECOVER and
VERIFY_MESSAGE. Structured OpenAI classification interprets a request; it cannot
choose tools, change actor identity or supply an approval. Ambiguous requests ask
clarification. Refusals, invalid/incomplete output, timeouts and API failures yield
an unavailable result without mutations. Model selection is `OPENAI_MODEL` on the
server; the adapter uses bounded retries/output and `store=False`.

Only the user message, with common sensitive identifiers redacted, reaches the
classifier. Server actor context, session data, balances and domain responses are
not passed to it. The current adapter handles classification only; deterministic
responses use selected typed fields. Full conversational generation is not claimed.

The graph receives only `AgentReadPort`, not `PaymentPort`, an approval writer or
university operator. Delivery remains distinct from posting, and unknown outcomes
request rechecking the original provider reference. References currently accept
the synthetic `transfer_...` form; broader entity resolution belongs to later
conversation work. Payment-to-obligation linkage must be verified by the finance
adapter before reporting posting for a specific payment; A-01 does not guess it.

The two agent HTTP paths exist but remain closed to requests until Dev B supplies
`verified_actor` and trusted domain services replace `agent_services`. The run
repository is a typed integration seam; the test implementation checks tenant,
actor and session. There is no global production fake or in-memory finance ledger.
`conversation_id` is reserved for later conversation storage, not authority or an
existing durable session. A-01 runs are single-turn.

Final local validation: 60 Python tests passed, strict mypy passed for 19 source
files, Ruff passed, and the isolated six-intent harness completed. Mocked OpenAI
transport verifies configured-model/schema use, redaction, refusal, malformed and
incomplete responses, HTTP failure and timeout. No API key/model is configured,
so live model access, intent accuracy and latency have not been measured.
The standalone frontend and its CSS returned HTTP 200; an adversarial HTTP agent
request still returned 503 AUTHENTICATION_NOT_CONFIGURED. These checks are not an
end-to-end authenticated financial demo.
