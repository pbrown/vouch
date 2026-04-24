# Vouch — PRFAQ

*Vouch: the trust runtime that vouches for your AI agents based on accumulated evidence. Every agent action runs through Vouch with a trust tier, a capture trail, and a reversible rollback path. Tasks earn autonomy over time.*

---

## Press Release

**FOR IMMEDIATE RELEASE — June 8, 2026**

### Vouch launches: the open-source trust runtime that vouches for your AI agents

**San Francisco, CA** — Today the Vouch project releases version 0.1, an open-source runtime that governs what AI agents do, measures how well they do it, and lets individual task types graduate from human-supervised to AI-drafted to auto-executed as evidence accumulates. Every agent action (an API call, a form submission, a click in a legacy portal) runs through Vouch with a trust tier, a capture trail, and a reversible rollback path. Vouch is the missing layer between agents that demo well and agents that actually earn responsibility in production.

Most teams building AI products today draw an arbitrary supervision line on day one and never change it. The agent drafts, the human reviews, every time, forever. The line never moves because nobody has a system for measuring when a specific task type is ready to need less attention. Engineers spend their time prompt-tuning instead of measuring what's already working. Reviewers burn out doing work the system could be trusted to do. And when something does break, the audit trail is whatever Slack thread somebody remembers.

Vouch treats trust as a measurable, dynamic, per-task-type property. The runtime captures every input, every output, every human edit, and every override. A graduation engine runs nightly and proposes tier shifts when the evidence supports them. Acknowledgements for routine purchase orders under $5,000 to known suppliers, edited less than 2% of the time across 300 runs, should graduate to auto-execute with 10% sample QA. A spike in edit rate after a prompt or model change should demote that task back to mandatory review until the next revision clears. Every shift is version-pinned, auditable, and reversible with one click.

Vouch governs agent actions regardless of mechanism. API calls are tasks. UI clicks are tasks. Email sends are tasks. The runtime doesn't care whether an agent is hitting a clean REST endpoint or clicking through a 1990s enterprise portal with no API. Both get the same trust tiers, the same capture, the same graduation engine. This matters because the workflows with the highest economic upside for AI agents (procurement, claims, prior authorization, logistics, legal operations) live largely in systems that APIs don't cover. Computer use made those systems reachable. Vouch makes them deployable.

Inventry.ai is the first production deployment. Jonah, Inventry's procurement and supplier-communications agent, runs on Vouch across a mix of ERP API calls and direct portal work across 400+ supplier sites. In the first six weeks of dogfooding, four task types graduated from human-required to AI-drafted, and two task types graduated all the way to auto-execute with sample QA. Average purchase order acknowledgement cycle time dropped from 4.2 hours to 18 minutes. The procurement team's review queue shrank by 47%. Edit rates on remaining drafts improved because the eval set is now built from real corrections, not from what the engineers thought might break.

"We've been duct-taping this loop together inside Inventry for a year," said Pooja Brown, Vouch maintainer and CTO at Inventry.ai. "The interesting problem isn't the agent. It's the system around the agent that vouches for it. Once you name that system, most other decisions get simpler."

Vouch 0.1 includes the workflow runtime, the corrections schema and clustering layer, the graduation engine, an operator UI, action capture primitives for both API and computer-use actions, and reference integrations for procurement and back-office operations. It's MIT licensed. Get started at github.com/poojabrown/pramana.

---

## External FAQ

**What problem does Vouch solve?**

AI agents have become capable enough to do real work inside real systems. The blocker is no longer model quality. It's deployment risk and review burden. Teams either run agents fully supervised (humans review every action, which kills the ROI) or fully autonomous (which kills confidence the first time the agent does something wrong). Vouch is the in-between: every task starts fully supervised and earns autonomy over time based on evidence.

**Who is this for?**

Engineering and operations teams running AI agents where mistakes have real consequences. Procurement, finance, insurance claims, healthcare prior authorization, legal operations, supply chain, HR back office. Anywhere an agent acts inside a system of record, across multiple systems, or on behalf of a company that has audit and compliance needs.

**Should I use APIs or computer use for my agent's actions?**

Use APIs whenever they exist and are sufficient. They are faster, more auditable per-action, and less brittle. Use computer use when the API doesn't exist, doesn't cover the workflow, is gated behind a tier you don't have, or requires a partnership that takes longer than the workload is worth. Vouch does not push you toward either. A single workflow can mix API tasks and computer-use tasks freely. The runtime treats both as actions with trust tiers.

**Why do so many high-value workflows need computer use?**

Because they live in 1990s-era enterprise software, long-tail vertical SaaS, and partner portals where APIs are incomplete, expensive, or nonexistent. A mid-market manufacturer might buy from 400 suppliers; 95% of them communicate through web portals or email. An insurance adjuster navigates 5-10 systems per claim; APIs cover maybe 30% of the work. A prior-authorization workflow touches every insurance payer's portal, and each portal has its own UI that changes weekly. The economic pull into these domains is enormous and APIs have not caught up. Computer use is the bridge.

**How is this different from LangSmith, Braintrust, Patronus, or Inspect AI?**

Those are eval and observability tools. They measure quality. They do not change behavior. Vouch closes the loop: the corrections you capture become the eval fixtures, the eval results gate the tier shifts, the tier shifts change what the runtime does next time. Vouch can run on top of any of those tools or replace the eval layer entirely.

**How is this different from Temporal, Restate, or other durable execution engines?**

Temporal solves general workflow durability. Vouch is AI-native: every task is versioned by prompt, model, retrieval index, and (for computer-use tasks) page and DOM snapshot; every output is captured with the inputs that produced it; the workflow definition itself is mutated by the graduation engine. You can run Vouch on top of Temporal and we recommend it for production deployments.

**What does Vouch do for computer-use actions specifically?**

Five primitives on top of whatever computer-use provider you use. *Action capture*: every click, type, and form submit is recorded with before and after screenshots plus DOM state. *Scoped credentials*: agents authenticate with tier-appropriate permissions, so low-trust tasks run with read-only or sandboxed access. *Dry-run mode*: high-tier actions can be replayed against a staging environment before hitting production. *Screenshot diffs*: human review can be a single visual comparison instead of reading a transcript. *Atomic rollback*: when a tier shift is reverted, in-flight computer-use sessions complete under their original credentials. None of this exists in raw computer-use SDKs.

**What does the developer experience look like?**

You define a workflow in YAML or Python. Each task gets a handler, an action mechanism (API, computer use, email, or custom), and an initial tier. You wrap your agent calls with the Vouch SDK. Corrections flow into the system automatically. The graduation engine runs in the background. The operator UI shows you what's happening and proposes tier shifts you approve.

**Do I need to use a specific agent or computer-use framework?**

No. Vouch is framework-agnostic. First-class adapters for Claude Agent SDK, Claude computer use, OpenAI Agents SDK, LangGraph, browser-use, and Playwright-based agents. A direct API works with anything.

**Can I roll back a tier shift?**

One click in the operator UI, or one CLI command. The runtime version-pins the workflow definition so a rollback restores the prior behavior atomically. All in-flight tasks complete under their original tier.

**What's the smallest useful integration?**

One workflow, one task, one human reviewer. If your team has a draft-and-review loop or a repeatable UI action sequence anywhere, you can wire Vouch in for that single task type and start collecting data within an hour. The graduation engine becomes useful around 200 captured corrections per task type.

**Is there hosted Vouch?**

Not in 0.1. The OSS runtime is the entire product. We will evaluate hosted offerings based on community demand, with computer-use sandboxing and multi-tenant operator UI as the most likely first hosted features.

**What's on the roadmap?**

0.2: multi-reviewer routing, reviewer agreement scoring, expanded replay and deterministic re-execution for computer-use sessions. 0.3: automatic prompt and selector revision suggestions from clustered corrections. 0.4: cross-workflow learning so corrections in one workflow inform tier proposals in similar ones. 1.0: production-grade durable execution, multi-tenant operator UI, SOC2-ready audit trail, hosted computer-use sandbox.

---

## Internal FAQ

**Why now?**

Three things converged in the last twelve months. Agent models got capable enough to do real work without constant guidance. Computer use shipped at production quality and made every legacy system reachable. And eval tooling matured to the point where the primitives Vouch depends on are commodity. The combination created an urgent gap: teams want to deploy capable agents into systems of record but have no safe way to do it. Eighteen months ago this would have been too early. Eighteen months from now somebody else builds it. The window is now.

**Why is the "mechanism-agnostic" framing important?**

Because it makes Vouch useful from day one for teams that don't touch computer use, while still being the obvious choice when they do. An agent calling a `wire_transfer` API needs the same trust gating as an agent clicking "Send Wire" in a UI. Both actions move money. Both benefit from tier graduation. If we positioned Vouch as a computer-use tool specifically, we'd exclude every team whose first agent talks to well-designed APIs and shrink our addressable surface by 80%. The trust runtime is the product. Computer use is the expansion pack.

**Then why does computer use show up so prominently in the pitch?**

Because it's the forcing function that made this a market. Without computer use, the "trust runtime" pitch is a nice-to-have. With computer use, teams are suddenly facing agents that can do destructive things in systems they didn't even have APIs into, and there is no safety layer for that. We use computer use to explain the urgency, and the neutral trust-runtime framing to explain the product.

**What are the target industries beyond procurement?**

Insurance claims operations. Healthcare prior authorization. Legal and litigation support. Logistics and freight operations. Property management. HR back office. Financial services KYC/AML and onboarding. Common pattern across all of them: regulated, legacy systems, multiple inter-system workflows per case, clear money or compliance thresholds, humans currently in the loop doing work that should compound.

**What's the technical moat?**

Four layers. The graduation algorithm itself, which is a non-stationary multi-armed bandit problem with asymmetric costs and concept drift. The corrections clustering layer, which needs diff-aware embeddings and an LLM-judge verification pass to avoid conflating semantically distinct edits. The action-capture and replay primitives for computer use, which are genuinely novel and require deep integration with multiple computer-use providers. And the accumulated correction history at adopting teams, which becomes the product after three months of use; switching runtimes means losing the trust-graduation state and the action-replay history.

**What's the business moat?**

Inventry as a live public case study, plus the portfolio of domain-specific tier defaults. No pure framework project has the former. We can publish "what we learned graduating Jonah from human-required to auto-execute on PO acknowledgements over six months" with real numbers from a real procurement workload. That paper is the marketing. The opinionated tier defaults for procurement, claims, prior auth, and legal ops are the Trojan horse for adoption: we ship a framework and an opinion about which tasks belong in which tier on day one.

**Why open source instead of building a closed product?**

Adoption needs trust, and the kind of teams running agents inside their ERP, their claims system, or their patient-facing prior-auth flow will not install a closed runtime that captures every action and every credential. OSS removes that objection. The business model, if there is one, is hosted computer-use sandboxing, support contracts, or premium features for compliance-heavy industries. The OSS bet is that the runtime becomes infrastructure and the company that maintains it captures value downstream.

**What's the riskiest assumption?**

That the graduation engine can build trustworthy tier-shift proposals from correction data, especially in the visual and DOM-noisy domain of computer use. If clustering or signal extraction fails there, the safety story degrades to "we capture everything and let humans review forever" which is useful but not magical. We mitigate by requiring human approval on every shift in 0.1, then loosening as we accumulate data on shift quality. If visual-domain clustering never gets good enough, the product is still differentiated as the safest computer-use runtime, just without the auto-graduation magic.

**What could a competitor do to kill this?**

Anthropic, OpenAI, or one of the agent platforms could ship trust tiers and graduation as native features. Durable-execution vendors (Temporal, Restate) could add AI-native extensions. LangChain could bolt on a Vouch-style layer. We assume one or more of them will try. Our defense is depth, opinionation, credibility, and the long tail: by the time they notice, we have six months of public correction data from a real procurement deployment, three published case studies across different verticals, a working operator UI built for ops teams not engineers, and a community. We compete on being the best at this single thing across multiple action mechanisms and providers, not on being a platform.

**What are we explicitly not building in 0.1?**

Hosted multi-tenant infrastructure. Automatic prompt or selector rewriting. Anything that touches the underlying agent's reasoning beyond version pinning. A no-code workflow builder. Compliance certifications. A computer-use provider of our own (we integrate, we do not compete). All of these are real future opportunities and all would slow 0.1 to a crawl.

**Why Inventry and Jonah specifically?**

Three reasons. Procurement is the cleanest domain for trust tiers: clear money thresholds, regulatory pressure, well-defined task types. Jonah already runs in production with humans in the loop, so correction data exists from day one. And Inventry the company is willing to publish numbers, which most enterprises will not. Without a public case study, the OSS pitch is hand-wavy. With Jonah, it is concrete.

**What does success look like in six months?**

Inventry running four workflows on Vouch with measurable improvement in procurement cycle time and reviewer load. Five other teams in production across at least two different verticals. Two published case studies besides Inventry. 500 GitHub stars. Three external contributors. One conference talk accepted.

**What does success look like in eighteen months?**

Vouch is the obvious answer when someone asks "how do I deploy a production AI agent that touches real systems safely?" The graduation pattern shows up in vendor pitches and competitor docs as table stakes. Inventry has a measurable competitive advantage from running on it. A funded company exists either as the maintainer or as a hosted offering, and either outcome is fine.

**What if Tribe wants to fund this?**

Then Vouch becomes the proof of CTO-level technical depth that gets the offer, and the discussion shifts to whether Vouch is the wedge product for a new Tribe-incubated company or shared infrastructure across Tribe's portfolio. Either is a great outcome.
