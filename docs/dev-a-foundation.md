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
