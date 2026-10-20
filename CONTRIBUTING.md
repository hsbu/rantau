# Contributing to Rantau

This repository uses **PR-only merging** for all human and AI contributors.
By default, validate changes and commit locally. Push changes and create or
synchronize PRs only when the user explicitly instructs you to do so; implementation
or commit approval does not grant publication permission for future changes.

## 1. Branch and PR workflow

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/finance-payment-intents
# edit, test, review staged changes
git status --short
git add <explicit-paths>  # avoid git add -A until you've inspected changes
python scripts/check_repo_hygiene.py
git diff --cached --name-only
git commit -m "feat(finance): implement payment intents"
# Stop here until the user explicitly instructs you to push/open a PR.
```

Only after the user's publication instruction:

```bash
git push -u origin feat/finance-payment-intents
# Open a pull request to main; request a review from a different developer.
```

**Do not push directly to `main`, merge without review, or force-push shared branches.** Keep commits focused and PRs small.

PR title examples: `feat(agent): add tuition clarification loop`; `fix(authz): reject stale approvals`; `test(finance): cover duplicate transfers`.

Branches use `<type>/<kebab-case-topic>`, such as `feat/agent-contracts`,
`build/app-skeleton` or `docs/team-progress`. Use the types listed in `AGENTS.md`
section 1; agent/tool names must not be branch prefixes. Commit messages and PR
titles use Conventional Commits (`<type>(<scope>): <summary>`, scope optional).

Every PR must link a roadmap ticket if available, describe behavior, list impacted API schemas, provide test evidence, and explain security implications. Check the PR template.

Write repository documentation, implementation notes, commits and PR descriptions
in English. Product-required localized UI content and original-language quotations
remain allowed; describe their purpose in English.

Maintain task status in the existing owner file under `docs/progress/`:
[Dev A](docs/progress/progress-a.md), [Dev B](docs/progress/progress-b.md),
[Dev C](docs/progress/progress-c.md). Update the task's `Desc`, evidence, date and
checkbox in the same commit as the implementation, and include it in the PR once
publication is authorized. Until then, record `Local commit — awaiting push/PR instruction`
instead of a PR link. A checked row records
implementation completion; review and merge remain separate explicit states.
Do not create a separate Markdown plan, report or progress log for each task.
Follow `AGENTS.md` section 7 for the complete workflow and file-creation limits.

Keep the documentation focused: `README.md` is the setup and usage guide;
[the product specification](docs/product-spec.md) defines approved scope;
[the roadmap](docs/roadmap.md) and [scenario checklist](docs/scenario-checklist.md)
define implementation and acceptance work. Keep dated execution notes in the three
existing progress files. Consolidate superseded task plans there instead of adding
more design/session reports. Generated evidence stays in ignored `.generated/`;
do not delete another contributor's local evidence or database during cleanup.

## 2. Ownership and change coordination

| Area | Default owner |
| --- | --- |
| Agent orchestration, KB, student chat | Dev A |
| Identity, policy gate, approvals, fraud, sponsor UI | Dev B |
| Financial provider simulator, ledger, tuition, reconciliation, demo UI | Dev C |
| Contracts, API schemas, migrations, `main.py`, root configuration | All owners affected; coordinate before changing |

For shared contracts, propose the change first. Update producer, consumer, mock and contract tests in the same coordinated PR(s).

## 3. Local configuration and generated files

- Keep real config only in ignored local `.env` files; commit `.env.example` with **placeholder values**, never actual secrets.
- Never commit `.venv`, `node_modules`, `.next`, caches, logs, `.sqlite3`, generated reports or artifacts.
- Keep fixture data **synthetic** and never commit real student/parent or bank records.
- Dependency lockfiles and schema migrations are source-controlled when generated as part of a reviewed, intentional change.
- Run `python scripts/check_repo_hygiene.py` before opening a PR; CI runs it too.
- If an ignored file was previously tracked: `git rm --cached path/to/file` followed by a PR. Rotate any leaked secrets immediately.

## 4. Tests and review

Run relevant backend tests (`pytest` from configured backend environment) and frontend type/lint/tests (using scripts in `frontend/package.json`) before requesting review. Do not invent a successful test result if a test cannot run; state the blocker.

Financial updates require state assertions for authorization, debit count, ledger, audit and failure modes. An attempted bypass of the policy gate is a release blocker.

**Reviewer checklist:** correct permissions and idempotency; no accidental public data/credentials; proper simulated status; contracts backwards-compatible or coordinated; tests meaningful; no generated artifacts.

## 5. GitHub repository settings (admin action)

Set a branch ruleset targeting `main`:

1. **Require a pull request before merging.**
2. Require at least **1 approving review** from a different developer; dismiss stale approvals after new commits where available.
3. Require status check **`Repository hygiene / check-repo-hygiene`** once the workflow has run and is selectable, plus app/test checks as they are added.
4. Block force-push and branch deletion; restrict bypass permissions.
5. Require PR branches to be up to date with `main` if the team's merge strategy permits.

Docs and CI encourage/validate repository hygiene, but **only GitHub branch protection/rulesets actually enforce PR-only merges**. If the repo plan doesn't support the desired restrictions, enforce review and PR-only merging operationally, and document the limitation.
