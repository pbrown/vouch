# Vouch v0.1 — Build Plan (April 22 to June 22, 2026)

Eight weeks. The flagship artifact is a fully working Vouch system running against a rich simulated procurement scenario ("Acme Industrial" with agent "Astra"). Real production deployment on Jonah begins Week 7 as a pilot, after the simulation proves the framework.

**Stack:** Python core (SDK, runtime, CLI, graduation engine, simulation). Next.js + TypeScript operator UI. Postgres for storage. FastAPI for the HTTP surface. Claude Code as primary driver for code changes. Cursor for visual review.

**Daily rhythm:** One meaningful commit every day. One visible improvement. Weekly post summarizing what shipped.

**The eight-week arc in one paragraph:** Weeks 1-2, build the simulated procurement scenario and Vouch's capture layer. Week 3, wire tiers and corrections against the simulation. Week 4, metrics and manual graduation working end-to-end in simulation. Week 5, clustering, automatic proposals, and all six canned scenarios runnable. Week 6, docs, polish, v0.1 OSS launch with the simulation as the reference example. Week 7, Amit/Huub conversation with demo in hand, Jonah pilot starts, conference CFPs submitted. Week 8, publications, analysts, community.

---

## Tonight — April 22, 2026

Two hours. Repo exists, local dev environment runs, first commit lands. Full step-by-step in `TONIGHT_CHECKLIST.md`.

Ship criterion: `docker compose up -d && cd ui && npm run dev` works, CI is green, CLAUDE.md is written, repo is public on GitHub.

---

## Week 0 — Simulation scaffolding (Apr 23 to 27)

**Goal:** The Acme Industrial scenario is modeled. Seed data for suppliers, SKUs, POs, and reviewers is generated. The simulation runner skeleton exists. No Vouch capture wired yet.

**Monday Apr 23 — Seed data generation.**
Generate `examples/acme-industrial/seed/suppliers.json` (500 suppliers across 12 categories) using an LLM one-shot. Generate 2000 SKUs. Generate 1000 initial POs distributed across supplier tiers and states (open, acknowledged, shipped, received, invoiced, paid). Commit all three files. Hand-review a sample of 30 suppliers for plausibility; re-generate if anything looks obviously wrong.

**Tuesday Apr 24 — Reviewer personas and event generator rules.**
Commit `reviewers.json` with Priya, Marcus, Diana. Commit `event-generators.yaml` with rules for how many of each event type generate per simulated day. Write the first pass of Astra's prompt templates (5 task types, one template each).

**Wednesday Apr 25 — Simulation runner skeleton.**
`runner.py` that can advance simulated time, generate events according to the rules, and invoke `agent.py` (stub) for each event. No LLM calls yet; stub returns empty outputs. Get the time-advancement loop working, prove you can generate a day of events.

**Thursday Apr 26 — Astra's real LLM calls.**
Implement `agent.py` so each task invokes OpenAI or Anthropic with the task-specific prompt. Log every draft to the console. Run a simulated day and eyeball 10 drafts per task type. Tune prompts until output looks plausible.

**Friday Apr 27 — Simulated reviewer logic.**
Implement `reviewers.py` with rule-based edits for 70% of cases and LLM-driven edits for the remaining 30%. Tune edit rates to match the target patterns in `SIMULATION_SPEC.md`. Run a simulated week and verify edit rate histograms look right.

**Ship criterion for Week 0:** `python runner.py --scenario nominal --days 7` produces realistic drafts and realistic edits for all 5 task types. Outputs are sane. Nothing is captured by Vouch yet.

**Week 0 public post (Friday):** "Starting a 6-week build of an OSS trust runtime for AI agents. First step: realistic procurement simulation. Here's the scenario." Short post with a screenshot of a sample supplier PO ack draft and the simulated reviewer edit.

---

## Week 1 — Vouch capture layer + simulation handshake (Apr 28 to May 4)

**Goal:** Every draft and every reviewer edit in the simulation flows into Vouch's captures and corrections tables. No tiers yet, no UI yet.

**What you build:**

*SDK (sdk-python).* One decorator: `@vouch.task(name="po_acknowledgement")`. Wraps Astra's per-task functions. Captures args, runs the function, captures the return, POSTs to the runtime. Target: under 200 lines.

*Runtime (runtime).* FastAPI with two endpoints: `POST /v1/captures` and `POST /v1/corrections`. Pydantic models for payloads. SQLAlchemy writes to Postgres. Alembic migration for the initial schema.

*Schema (first migration).*
```
captures(id, task_name, input_json, output_json, model, prompt_version, agent_version, status, started_at, completed_at, created_at)
corrections(id, capture_id, original_output_json, edited_output_json, edit_diff_json, edit_severity, reviewer_id, edit_tags, submitted_at, created_at)
```

*Simulation wire-up.* Add `@vouch.task()` decorators to Astra's 5 task functions. Modify `reviewers.py` so that when an edit happens, it POSTs a correction to Vouch's runtime.

**Daily shape:**
- Mon Apr 28: SDK decorator + HTTP client
- Tue Apr 29: FastAPI runtime + captures endpoint + Postgres schema
- Wed Apr 30: Corrections endpoint + diff computation (`deepdiff`)
- Thu May 1: Wire SDK into Astra's task functions
- Fri May 2: Run a 30-day simulated scenario end to end, query Postgres to verify captures and corrections are flowing

**Ship criterion for Week 1:**
```sql
select task_name, count(*) as captures, count(c.id) as corrections
from captures
left join corrections c on c.capture_id = captures.id
group by task_name;
```
Returns a row per task type with realistic counts from a 30-day simulated run.

**Week 1 public post:** "Day 7: Vouch is capturing Astra (a simulated procurement agent I built this week). 4,200 captures, 380 corrections across 5 task types. Here's the schema and the first query."

---

## Week 2 — Workflow YAML, trust tiers, operator UI scaffolding (May 5 to 11)

**Goal:** Workflow YAML defines the 5 tasks with initial tiers. Simulation routes through tiers. Basic operator UI shows captures and corrections.

**What you build:**

*Workflow YAML.*
```yaml
workflow: astra
version: 1
tasks:
  - name: po_acknowledgement
    handler: acme.astra.po_ack
    mechanism: email
    tier: ai_draft
  - name: supplier_followup
    handler: acme.astra.supplier_followup
    mechanism: email
    tier: ai_draft
  - name: invoice_three_way_match
    handler: acme.astra.invoice_match
    mechanism: api
    tier: ai_draft
  - name: low_stock_reorder
    handler: acme.astra.reorder_proposal
    mechanism: api
    tier: human_only
  - name: new_supplier_engagement
    handler: acme.astra.new_supplier
    mechanism: email
    tier: human_only
```

*Tier enum + SDK routing.* `human_only` → agent not called, task marked pending_human. `ai_draft` → agent runs, output marked pending_review. `auto` → agent runs, output executes, sample_qa_rate triggers async review.

*Workflow versions table.* Every tier change writes a new version row. Atomic swap via version pointer.

*Next.js operator UI.* One page: `/captures` lists recent captures with inline diff view using `react-diff-viewer-continued`. One page: `/workflow` shows current tiers per task, with a dropdown to change tier.

**Daily shape:**
- Mon May 5: Workflow YAML schema + loader
- Tue May 6: SDK tier routing logic + workflow_versions migration
- Wed May 7: Next.js scaffold + captures list page
- Thu May 8: Diff view component + workflow page with tier dropdown
- Fri May 9: Run simulation, change a tier mid-run, verify behavior flips

**Ship criterion for Week 2:** Operator changes a task's tier in the UI during a running simulation, and subsequent simulated runs of that task honor the new tier.

**Week 2 public post:** "Day 14: trust tiers working. Changed supplier follow-up from ai_draft to human_only during a live simulation and watched the agent step back from that work. Here's the UI."

---

## Week 3 — Correction tagging + metrics (May 12 to 18)

**Goal:** Corrections are tagged by type in the UI. Metrics service computes per-task rolling windows. UI shows metrics charts.

**What you build:**

*Correction tagging.* Extend corrections UI: reviewers (or in simulation, the simulated reviewer logic) tag each edit with a type (tone, factual, formatting, personalization, policy, other).

*Metrics service.* Nightly cron (in simulation: runs at end of each simulated day). For each task, compute: edit_rate_7d, edit_rate_30d, edit_rate_last_N, severity_weighted_rate, factual_error_rate, tag distribution. Writes to `metrics_snapshots` table.

*Metrics UI page.* Two-week rolling chart per task (Recharts). Shows edit rate, severity, and a tag breakdown pie chart. Side-by-side comparison if you want.

*Sample QA for auto-tier tasks.* When a task is `auto`, 10% of executions are flagged for async review. Sample QA page in UI shows flagged captures.

**Daily shape:**
- Mon May 12: Correction tagging schema + simulation updates to tag edits
- Tue May 13: Metrics computation job + snapshots schema
- Wed May 14: Metrics page charts
- Thu May 15: Sample QA flow
- Fri May 16: Run a 60-day simulation and eyeball the metrics

**Ship criterion for Week 3:** Metrics page renders a clear story. "Astra's PO ack edit rate has dropped from 8% to 2% over the last 30 simulated days." Charts look right.

**Week 3 public post:** "Day 21: measurement. Here's Astra's metrics after 60 simulated days. Three tasks are candidates for graduation based on what I'm seeing."

**Week 3 conference prep:** Start drafting the Ray Summit abstract (see `CONFERENCES.md`). Do not submit yet.

---

## Week 4 — Manual graduation + first three canned scenarios (May 19 to 25)

**Goal:** Operator can promote/demote/rollback. Three canned scenarios (A, B, E) run cleanly and produce demo-worthy footage.

**What you build:**

*Promote / demote / rollback.* UI buttons. Each action writes a new workflow_versions row. Rollback reverts to the previous version atomically. Running tasks complete under their original tier.

*Canned scenarios.*
- Scenario A (Nominal): 90-day run, shows natural graduation arc
- Scenario B (Prompt regression): 60-day baseline, then prompt swap, shows edit rate spike, operator demotes
- Scenario E (Manual rollback): operator manually graduates supplier follow-up, rollback when it goes bad

Each scenario has a YAML config that the runner can execute: `python runner.py --scenario A --days 90`.

*Demo recording setup.* Install Loom or similar. Record a 3-minute walkthrough of each scenario. These recordings are the raw material for the launch video.

**Daily shape:**
- Mon May 19: Promote/demote UI + rollback logic
- Tue May 20: Scenario A runs, record footage
- Wed May 21: Scenario B runs, record footage
- Thu May 22: Scenario E runs, record footage
- Fri May 23: Review all three recordings, note what needs to be better in the next pass

**Ship criterion for Week 4:** Three canned scenarios runnable by anyone. Three recorded demo videos committed to `docs/videos/`.

**Week 4 public post:** "Day 28: three scenarios working. Video walkthrough of Scenario B (prompt regression): Vouch caught the regression before any reviewer noticed and demoted the task back to human review within 48 simulated hours." Embed the video.

---

## Week 5 — Clustering + automatic proposals + remaining scenarios (May 26 to Jun 1)

**Goal:** Graduation engine proposes tier shifts from clustered corrections. All six canned scenarios work. Ray Summit CFP submitted.

**What you build:**

*Embedding pipeline.* Embed each correction's diff using `text-embedding-3-small`. Store in `correction_embeddings` table (or pgvector).

*Clustering.* HDBSCAN over embeddings. LLM-judge verification: "Are these N corrections semantically the same edit?" Reject unverified clusters.

*Graduation engine.* Nightly job. Per task, checks metrics against thresholds. Generates proposals with justification referencing the clusters: "PO ack edit rate is 1.8% over last 250 captures. 3 verified clusters (signature tweaks, date formatting, greeting style). No factual errors. Proposal: promote ai_draft → auto with 15% sample QA."

*Proposals inbox in UI.* Each proposal: justification, clusters summary, accept/reject.

*Scenarios C, D, F.* Implement and record.
- Scenario C (new supplier category): novelty handling
- Scenario D (reviewer disagreement): per-reviewer graduation (stubbed in 0.1)
- Scenario F (eval set generation): show corrections → clustered eval fixtures

**Daily shape:**
- Mon May 26: Embedding pipeline + clustering
- Tue May 27: LLM-judge verification
- Wed May 28: Graduation engine + thresholds + proposals UI
- Thu May 29: Scenarios C and F
- Fri May 30: Scenario D (stubbed per-reviewer); record all three

**Sat May 31:** Submit Ray Summit CFP. Deadline likely around June 1.

**Ship criterion for Week 5:** All six scenarios runnable and recorded. Ray Summit CFP submitted.

**Week 5 public post:** "Day 35: Vouch proposed its first automatic tier shift. Here's the clustering algorithm and why LLM-judges matter." Include the verified-cluster output from Scenario A.

---

## Week 6 — Docs, v0.1 OSS launch (Jun 2 to 8)

**Goal:** v0.1 ships Monday June 8. Simulation is the featured example. Strangers can install Vouch and run the simulation in ten minutes.

**What you build:**

*Docs.* README + Getting Started (10-minute quickstart running the simulation) + Workflow YAML Reference + SDK Reference + Runtime API Reference + Operator UI Walkthrough + Scenarios Guide. Host on Mintlify or Nextra.

*Claude Agent SDK adapter.* `sdk-python/src/vouch/adapters/claude_agent.py`.

*Computer use minimal slice.* `sdk-python/src/vouch/adapters/playwright.py`. Capture clicks, screenshots, DOM. Behind "experimental" flag.

*CLI.* `vouch init`, `vouch status`, `vouch promote`, `vouch rollback`, `vouch scenario`.

*Launch video.* 5-minute version: Acme Industrial intro → Astra doing its thing → first graduation (Scenario A condensed) → the prompt regression rollback (Scenario B). Hosted on Loom, YouTube, embedded on site.

*Publish.* PyPI: `vouch-sdk`, `vouch-runtime`, `vouch-cli`. Docker Hub: `vouch/runtime`, `vouch/ui`. GitHub release tagged v0.1.0.

*Launch post.* "Introducing Vouch: the trust runtime for AI agent actions. I spent six weeks building this and dogfooding it on a realistic procurement simulation. Here's what I learned and here's why it's the missing layer for deploying agents safely." HN, LinkedIn, X, Substack.

**Daily shape:**
- Mon Jun 2: Docs site + README + Getting Started quickstart
- Tue Jun 3: Claude Agent SDK adapter + remaining docs
- Wed Jun 4: CLI + Playwright capture + launch video editing
- Thu Jun 5: Package everything, test on clean machine
- Fri Jun 6: Pre-launch doc review, line up announcements
- Sat Jun 7: Write launch threads. Rest.
- Mon Jun 8: Launch. Monitor. Respond to every comment for 12 hours.

**Ship criterion for Week 6:** Someone new to the project clones the repo, runs `docker compose up && vouch scenario A`, and sees Vouch do its thing in under 10 minutes.

**Week 6 public post:** The launch post.

---

## Week 7 — Amit/Huub conversation + Jonah pilot + CFPs (Jun 9 to 15)

**Goal:** Pitch Jonah as production case study with working demo. Start Jonah instrumentation. Submit QCon SF CFP.

**What you build:**

*Amit/Huub conversation.* Monday Jun 9. Show the launch. Show the simulation running. Show the Jonah angle. Ask for Jonah as the second public case study (after the simulation, which is already public from the launch). The ask is now much smaller: "Vouch is live, 800 GitHub stars from the launch last week, Stripe/Anthropic/Inventry-competitor-names are asking how to adopt. Let's wire Jonah so Inventry is the first named production deployment." Use the updated `AMIT_HUUB_ONEPAGER.md` as the handout.

*Jonah integration, Week 1 style.* Add the Vouch SDK to one Jonah task behind a feature flag. Capture captures and corrections. No behavior change.

*Second external case study outreach.* Five LinkedIn/email pitches to potential second-team adopters via Tribe network or cold outreach.

*QCon SF CFP.* Submit before deadline (usually mid-June).

*Polish based on launch feedback.* Every issue filed on GitHub post-launch gets triaged. Fix the top 5 rough edges.

**Daily shape:**
- Mon Jun 9: Amit/Huub conversation. Afternoon: kick off Jonah feature branch.
- Tue Jun 10: Wire SDK into Jonah's first task. Staging deploy.
- Wed Jun 11: Jonah production rollout at 10% behind flag.
- Thu Jun 12: QCon SF CFP submitted.
- Fri Jun 13: Second-team outreach + launch-feedback triage.

**Ship criterion for Week 7:** Jonah is capturing to Vouch in production at 10%. QCon CFP submitted. At least one second-team prospect is scheduled for a week 8 call.

**Week 7 public post:** "One week after launch: Jonah (Inventry's production procurement agent) is now also running on Vouch. Here's what wiring a real agent to Vouch looks like." Live case study in progress.

---

## Week 8 — Supply chain attention + analyst briefings (Jun 16 to 22)

**Goal:** Supply chain publications, analysts, and conferences know Vouch exists. Multiple briefings booked. Community seeded.

**What you build:**

*Case study PDF.* Convert the Jonah + simulation story into a sales asset Inventry can share. Double-duty for Vouch awareness.

*Analyst briefings.* Pitch Gartner (procurement/supply chain AI), Forrester, Spend Matters, Ardent Partners. Three briefings booked for July.

*Publication pitches.* Spend Matters, Supply Chain Dive, Bloomberg Supply Chain, CIO Journal. Two pitches per week, tracked.

*ProcureCon CFP.* Submit for fall 2026.

*Podcast outreach.* Supply Chain Now, The Procure Cast, Latent Space, The Batch.

*Community.* Discord or Slack, gated behind "installed and captured." 50 seed members.

**Daily shape:**
- Mon Jun 16: Case study PDF + slide deck
- Tue Jun 17: Five analyst pitches + two publication pitches
- Wed Jun 18: ProcureCon CFP + ASCM 2027 planning
- Thu Jun 19: Podcast/newsletter pitches
- Fri Jun 20: Community setup + first 10 invites

**Ship criterion for Week 8:** Three analyst briefings booked for July. Two publication pitches landed. Two conference submissions in. 50-member community seeded.

**Week 8 public post:** Eight-week retrospective. What shipped, what broke, what I learned, what's next.

---

## What's explicitly out of v0.1

Temporal. Multi-tenant. Automatic prompt rewriting. SOC2. Hosted Vouch. Multi-reviewer agreement scoring. Cross-workflow learning. Selector auto-repair for computer use. No-code workflow builder. Broader computer-use provider support beyond Playwright + Claude Agent SDK adapter.

## Parallel threads running all eight weeks

**Writing in public (weekly).** LinkedIn post every Friday.

**Substack (biweekly starting Week 2).** Six long-form essays mapped in `SUPPLY_CHAIN_ATTENTION.md`.

**Inventry comms.** Weekly Slack update to Amit and Huub starting Week 7 (Jonah pilot starts).

**Journaling.** One line per day: what worked, what didn't. Raw material for the Week 8 retrospective.

## Risks, named

**Simulation feels fake in demos.** If the simulation doesn't convince, the whole launch is weaker. Mitigation: multiple canned scenarios with distinct outcomes; record recordings early in Week 4 so you can iterate; get 2-3 procurement-savvy reviewers to preview before launch.

**Amit/Huub conversation goes sideways.** Less load-bearing than before. Vouch is already launched. Inventry is a strong second case study; if they say no, find a different case study through Tribe network. Not a blocker.

**Clustering quality in Week 5.** If clusters are noisy, graduation proposals are weak. Mitigation: Week 4 manual graduation is useful product regardless. Ship to Week 4 level if Week 5 drags.

**Launch day timing.** June 8 is aggressive. If Week 5 slips, launch slips to June 15. Don't ship broken to hit date.

**Burnout.** Six days on, one off. Sunday truly off. Weekly posts keep you honest. Daily commits keep you moving.

---

## The arc, in one line

Tonight: repo exists. Week 0: simulation scenario modeled. Week 1: captures flow. Week 2: tiers route. Week 3: metrics rendered. Week 4: manual graduation + three scenarios. Week 5: automatic proposals + all six scenarios. Week 6: OSS launch. Week 7: Amit/Huub + Jonah pilot. Week 8: analysts, press, community.
