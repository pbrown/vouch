@AGENTS.md
# Vouch — context for Claude Code

## What this is

Vouch is the trust runtime for AI agent actions. Three core concepts:

- **Tasks** have a trust tier: `human_only`, `ai_draft`, or `auto`
- **Captures** are recorded every time an agent runs a task
- **Corrections** are recorded when a human edits an agent's output
- **Graduations** move tasks between tiers based on accumulated correction data

## Stack

- Python 3.12, uv for packages, FastAPI, SQLAlchemy, Alembic, Pydantic
- Next.js 14 App Router, TypeScript, Tailwind, Recharts
- Postgres 16 (local via Docker)

## Package boundaries

- `sdk-python/` — installed by agents. Must be tiny, stable, backward-compatible.
- `runtime/` — the HTTP service. All persistence lives here.
- `ui/` — Next.js app, talks to runtime via fetch.
- `cli/` — operator tooling. Reads and writes workflow YAML.

## Conventions

- Pydantic for every data contract at a package boundary.
- SQLAlchemy ORM, never raw SQL in business logic.
- Alembic migrations for every schema change, no exceptions.
- Type hints required. Pyright strict mode.
- Tests run on every commit via GitHub Actions.

## Related repos

Inventry's Jonah is the first production deployment. Sibling checkout at `~/code/inventry/`. When instrumenting Jonah, always work on a feature branch in the Inventry repo.

## Things NOT to do

- Do not commit secrets. `.env` files are gitignored.
- Do not push breaking changes to `sdk-python/` without a migration note.
- Do not use raw SQL where SQLAlchemy would work.