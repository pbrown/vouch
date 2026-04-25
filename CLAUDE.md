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


## Three prompt categories — keep them distinct

This codebase has three categories of LLM prompts. They serve different purposes and have different quality criteria. Do not conflate them when iterating, testing, or discussing changes.

### 1. Agent prompts — `examples/<scenario>/<agent>.py`

The prompts the *simulated agent* uses to draft work. In the Acme Industrial scenario this is Astra; her five prompts (`PO_ACK_PROMPT`, `SUPPLIER_FOLLOWUP_PROMPT`, `INVOICE_MATCH_PROMPT`, `REORDER_PROPOSAL_PROMPT`, `NEW_SUPPLIER_ENGAGEMENT_PROMPT`) live as Python constants in `examples/acme-industrial/astra.py`.

**Good = consistent, realistic drafts.** Inconsistency on identical input is a bug. Tighten with explicit rules until five-out-of-five runs produce equivalent outputs.

### 2. Simulated reviewer prompts — `examples/<scenario>/reviewers.py`

The prompts simulated humans (e.g., Priya, Marcus, Diana for Acme) use when making LLM-driven edits to agent drafts. Per `docs/planning/SIMULATION_SPEC.md`, roughly 30% of simulated reviewer edits are LLM-driven; the other 70% are rule-based.

**Good = plausible, varied edits within the persona.** Inconsistency is feature, not bug — real humans are inconsistent. Variance should track the persona's described edit style.

### 3. Vouch internal prompts — `runtime/src/vouch_runtime/...`

The prompts Vouch's own runtime uses for analysis. Coming in Week 5: a clustering verification prompt (LLM-as-judge for "are these corrections the same edit?") and a graduation proposal generation prompt.

**Good = correct, conservative analysis.** Strictest quality bar. Graduation decisions depend on these being right.

### Relationship
[Agent]  --draft-->  [Reviewer]  --edit-->  [Vouch captures both, then analyzes]
↑                     ↑                          ↑
|                     |                          |
Category 1           Category 2                Category 3

When iterating prompts, always state which category. "Tightened the prompt" is ambiguous; "tightened Astra's invoice match prompt" is clear.