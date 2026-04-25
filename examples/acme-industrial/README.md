# Acme Industrial — example agent

Astra, a simulated procurement agent that drafts five task types (PO acks,
supplier follow-ups, three-way invoice match, low-stock reorder proposals,
new-supplier engagement). Every task function is decorated with
`@vouch.task` so captures stream to the Vouch runtime.

## Run

```bash
uv sync
cp .env.example .env   # add OPENAI_API_KEY and ANTHROPIC_API_KEY
uv run python astra.py # smoke test against Claude Haiku 4.5
uv run pytest         # mocked unit tests, no live calls
```
