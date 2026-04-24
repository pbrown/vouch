# Vouch Simulation — Acme Industrial

The simulation is the first proof that Vouch works. It's also the toy-procurement example that ships with the OSS and the demo asset for every conference, publication, and analyst briefing in the first 90 days. Budget for it accordingly; it's a first-class deliverable, not a test fixture.

## The scenario

**Acme Industrial** is a fake mid-market manufacturer with 500 suppliers across 12 categories: raw materials, fasteners, electronics, packaging, chemicals, adhesives, lubricants, fabricated components, MRO supplies, services, logistics, and finished goods resale. This isn't flavor text. The category mix determines task distribution and edit-rate variance.

Acme's procurement agent is **Astra**. Astra handles five task types:

1. **PO acknowledgement.** Supplier emails back confirming a purchase order. Astra drafts a structured reply confirming receipt, noting any discrepancies, and setting expectation for delivery.
2. **Supplier follow-up.** When an order is past its expected ship date, Astra drafts a chase email. Tone and escalation level depend on supplier tier and delay length.
3. **Invoice three-way match.** When an invoice arrives, Astra reconciles PO + goods receipt + invoice. Drafts an approval-for-payment message on clean matches, a discrepancy flag on mismatches.
4. **Low-stock reorder proposal.** When inventory of a SKU hits reorder threshold, Astra drafts a reorder proposal with quantity and supplier selection.
5. **New-supplier initial engagement.** When procurement wants to source from a new supplier, Astra drafts an intro + RFQ email.

Acme has three simulated reviewers with distinct personas:

- **Priya** — senior buyer. Handles high-value POs ($25K+) and strategic suppliers. Strict on tone, especially in supplier follow-ups. Moderate edit rate across task types but high severity when she edits.
- **Marcus** — junior buyer. Handles routine acknowledgements and low-value reorders. Light-touch editor, mostly signature and salutation tweaks.
- **Diana** — accounts payable lead. Owns invoice three-way match review. Sharp eye for discrepancies, zero tolerance for miscategorized line items.

## Edit patterns by task × reviewer

The core design insight: each task-reviewer combination has a characteristic edit rate and severity distribution. This is what makes graduation proposals interesting. Vouch should be able to graduate PO acks reviewed by Marcus to auto-execute long before it graduates supplier follow-ups reviewed by Priya.

Target edit patterns (calibrated so simulated runs produce realistic graduation arcs):

| Task | Reviewer | Edit rate | Severity | Common edit types |
|---|---|---|---|---|
| PO ack (routine, known supplier) | Marcus | 2% | Low | Signature/closing tweaks |
| PO ack (high-value, strategic) | Priya | 8% | Medium | Tone, delivery expectation language |
| Supplier follow-up (1-day late) | Marcus | 12% | Low | Softening language |
| Supplier follow-up (week+ late, strategic) | Priya | 35% | High | Escalation level, relationship-aware phrasing |
| Invoice match (clean) | Diana | 4% | Low | Minor line-item wording |
| Invoice match (discrepancy flagged) | Diana | 65% | High | Category corrections, policy citations |
| Low-stock reorder (routine) | Marcus | 6% | Low | Quantity adjustments |
| Low-stock reorder (capex threshold) | Priya | 28% | High | Vendor selection, spending justification |
| New supplier engagement | Priya | 42% | High | Everything; she essentially rewrites |

## Event stream design

The simulation runs at variable speed. Default: 1 simulated day = 2 minutes real time. Over 3 hours you run 90 simulated days.

Each simulated day produces:
- 20-40 PO acknowledgements (supplier responses to existing POs)
- 5-15 supplier follow-ups (orders past due)
- 15-30 invoice three-way matches
- 3-8 low-stock reorder proposals
- 0-2 new-supplier engagements

Every event has a timestamp, a supplier (from the 500-supplier pool), a value, and a category. Input data is pre-generated for reproducibility. Astra's drafts are real LLM calls (this is what Vouch is evaluating) against either OpenAI gpt-4o-mini or Claude Haiku 4.5 (cheaper, faster for 6000+ simulated calls).

Simulated reviewers make edits following the patterns above plus noise. Roughly 70% of edits follow rule-based patterns. 30% use an LLM to generate a plausible edit with persona conditioning ("You are Priya, a senior buyer. Edit this draft as you would").

## Canned scenarios

Six scripted scenarios the simulation can run on command. Each one is a demo-able moment for talks, videos, and documentation.

**Scenario A: Nominal operation.** 90 simulated days. By simulated day 45, PO ack (Marcus) graduates from `ai_draft` to `auto` with 10% sample QA. By day 70, clean invoice match (Diana) graduates. Supplier follow-ups never graduate. Demo moment: "here's what six weeks of operation looks like, and here's what graduated."

**Scenario B: Prompt regression.** Run Scenario A to steady state. On simulated day 60, introduce a "broken" prompt variant that increases PO ack edit rate from 2% to 15%. Show the graduation engine correctly demote PO ack back to `ai_draft` within 2 simulated days. Demo moment: "here's how Vouch catches prompt regressions without any reviewer noticing."

**Scenario C: New supplier category.** Add 50 new suppliers in a category Astra has never seen (medical devices, different regulatory language). Show: the new supplier PO acks start at `human_only`, edit rate is 45% for two weeks, then drops as Astra's context grows, and Vouch proposes moving to `ai_draft` around simulated day 20. Demo moment: "Vouch handles novelty conservatively by design."

**Scenario D: Reviewer disagreement.** Priya edits 40% of a task type. Marcus edits the same task type at 5%. Show that Vouch's graduation engine can propose per-reviewer graduation instead of per-task graduation (v0.2 feature, stubbed for demo). Demo moment: "trust is reviewer-dependent, and Vouch can model that."

**Scenario E: Manual override and rollback.** Operator manually promotes supplier follow-up to `auto` against Vouch's recommendation. Edit rate spikes in simulated week 2. Operator rolls back in one click. Vouch flags the incident and updates its threshold model. Demo moment: "the rollback is the feature that makes the graduation safe."

**Scenario F: Long-tail eval set generation.** Show the corrections table over 90 simulated days. Show clustering pulling out 40 distinct correction patterns. Show how those become eval fixtures automatically. Demo moment: "the eval set writes itself from real reviewer behavior."

These six scenarios are the backbone of every demo you'll do. Build them explicitly, commit them to the repo, make them runnable by anyone.

## Seed data structure

```
examples/acme-industrial/
├── seed/
│   ├── suppliers.json           # 500 supplier profiles
│   ├── skus.json                # 2000 SKUs
│   ├── initial-pos.json         # 1000 POs in various states
│   ├── reviewers.json           # Priya, Marcus, Diana personas
│   └── event-generators.yaml    # Rules for generating daily events
├── scenarios/
│   ├── A-nominal.yaml
│   ├── B-prompt-regression.yaml
│   ├── C-new-category.yaml
│   ├── D-reviewer-disagreement.yaml
│   ├── E-manual-rollback.yaml
│   └── F-eval-generation.yaml
├── runner.py                    # The simulation loop
├── agent.py                     # Astra — the actual procurement agent
├── reviewers.py                 # Priya, Marcus, Diana logic
└── README.md
```

Suppliers, SKUs, and initial POs are generated once and committed. Events within a simulation run are reproducible given a seed.

## Supplier profile shape

```json
{
  "id": "sup-000347",
  "name": "Midwest Fasteners Inc.",
  "category": "fasteners",
  "tier": "strategic",
  "typical_lead_time_days": 7,
  "reliability": 0.94,
  "communication_style": "brief, professional",
  "currency": "USD",
  "preferred_po_format": "email_pdf",
  "relationship_years": 12,
  "notes": "Annual contract, net-30, quality issues in Q2 2024"
}
```

Generated with an LLM one-shot to get 500 realistic profiles across the 12 categories, then hand-reviewed for plausibility. Commit the file.

## Reviewer persona shape

```json
{
  "id": "rev-priya",
  "name": "Priya Iyer",
  "role": "Senior Buyer",
  "handles": ["high_value_po", "strategic_supplier_followup", "capex_reorder"],
  "edit_style": {
    "tone_preference": "warm but firm",
    "length_preference": "concise",
    "common_additions": ["explicit delivery commitment ask", "relationship context"],
    "common_removals": ["apology language for supplier delays"]
  },
  "edit_rate_baseline": 0.18,
  "severity_baseline": 0.6
}
```

## Astra's prompt

Single prompt template per task type, committed in the repo. Real LLM call on every event. Vouch captures input, output, prompt version. When scenarios vary the prompt (Scenario B), they do it by swapping the prompt template and bumping version.

## Time model

Simulated time is maintained by the runner. Astra's drafts get simulated timestamps that match the simulated clock. Vouch captures these timestamps. Reviewer edits happen "N hours" after the draft in simulated time. This matters for rolling-window metrics — the simulation has to produce events that look like production streams.

## What the simulation is NOT

- Not a benchmark. Numbers from the simulation are illustrative, not scientific. Anyone comparing simulations to real deployments should use Jonah's numbers when they're available.
- Not a replacement for Jonah. The simulation proves the framework works. Jonah proves it works in production on real money.
- Not meant to be general-purpose. It's procurement-specific. Someone building Vouch into healthcare prior auth will build their own simulation.

## Build order

Weeks 1-2 build the simulation skeleton. Weeks 2-3 wire Vouch to it. Week 4 runs the six scenarios and produces demo video footage. Week 5 documents it as the OSS example integration. Week 6 ships.

When Jonah pilot starts (Week 7), the simulation stays as the toy example. New users run it to understand Vouch before wiring their own agent.
