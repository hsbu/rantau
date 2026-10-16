# Rantau

A simulated financial agent for students from Southeast Asia studying in mainland
China and their sponsors. All quotes, payments and university records are synthetic.

Product sources: [MVP specification](Rantau-MVP-Spec.md) and
[team roadmap](Rantau-3Dev-Roadmap.md). Development follows [AGENTS.md](AGENTS.md).

## Local setup

Use Python 3.12, uv, Node 22.13+ and npm. Copy `.env.example` to ignored `.env` if
needed. Set `OPENAI_API_KEY` and `OPENAI_MODEL` locally to configure the classifier;
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
it demonstrates graph routing, not live model quality or real payments. The OpenAI
adapter uses a configurable model with structured output and safe failure handling.
Live API access requires separate verification. Keep task updates in the shared
progress folder: [Dev A](docs/progress/progress-a.md),
[Dev B](docs/progress/progress-b.md), and [Dev C](docs/progress/progress-c.md).
Each owner updates their task checkboxes, descriptions and validation evidence in
the same commit/PR as the work. See `AGENTS.md` section 7 for the full workflow.
