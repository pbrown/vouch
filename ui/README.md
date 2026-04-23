# Vouch

The trust runtime for AI agent actions. Vouch captures what your agents do, captures what humans correct, and lets individual task types graduate from human-supervised to AI-drafted to auto-executed as evidence accumulates.

**Status:** pre-0.1. Active development. First release targeting June 8, 2026.

## Why

Every AI agent team today draws an arbitrary supervision line on day one and never moves it. The agent drafts, the human reviews, every time, forever. The line never moves because nobody has a system for measuring when a task type is ready to need less attention. Vouch is that system.

## Packages

- `sdk-python/` — Python SDK that agents install
- `runtime/` — FastAPI runtime that captures agent actions and corrections
- `ui/` — Next.js operator UI for reviewers and operators
- `cli/` — Python CLI for workflow management
- `examples/` — Reference integrations

## Local development

```bash
docker compose up -d
cd sdk-python && uv sync
cd ../runtime && uv sync
cd ../ui && npm install
```

See `docs/` for getting started.

## License

MIT