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

In another terminal, run `uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000`.
Open the frontend at `http://127.0.0.1:3000` and backend docs at
`http://127.0.0.1:8000/docs`. With Docker running, `docker compose up --build`
starts PostgreSQL, backend and frontend. Container services use service DNS.

`/health` reports process liveness. `/ready` deliberately reports 503 until
authentication/domain services are integrated; a responding process is not a
complete financial application. Agent endpoints reject unwired authentication.
No identity is accepted from headers/chat text, and no fake financial gate is
connected. B/C services and the student chat page remain separate roadmap tickets.

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
Pop-Location
docker compose config --quiet
```

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
```

This calls the configured OpenRouter model for intent and bounded tuition-field
interpretation. Domain reads use synthetic fixtures and the explicit November
scenario clock. Replies explain scoped data deterministically. The harness can
build a typed draft preview; it cannot persist a payment intent, approve, debit,
post tuition or clear a hold. It does not install fake authentication or a fake
authorization gate in the application. `/quit` exits interactive mode.

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
