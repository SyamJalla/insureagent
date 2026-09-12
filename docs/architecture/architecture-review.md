# Architecture Review — the Reference Architecture in the Agentic AI Ecosystem

**Subject:** `Multi-Agent Architecture_123.drawio.png` (this folder).
**Nature of the artifact:** a deliberately context-free **reference architecture** —
drawn blank-slate by the architect to be exhaustive about the whole piece rather
than scoped to the current build. Reviewed accordingly: the primary question is
*"did the exhaustive sweep catch everything critical?"*, with the comparison to
our current implementation as its own snapshot section (§3). Versions will be
built on top of this reference.
**Prepared:** 2026-09-11 · Syam (with Claude) · Domain model per the [README](../../README.md)

---

## 1. Exhaustiveness check — does the reference cover the whole use case?

"AI for an insurance company" is not one use case. Mapped against our own domain
model (user types × journey phases × interaction modes), it spans:

| Dimension | Range |
| --- | --- |
| **Interaction mode** | *Inform* (answer questions) → *Act* (execute changes: pay, file, update, endorse) → *Proact* (reach out: renewal due, lapse warning, claim update) |
| **User type** | Customers · Prospects (quote → application → KYC journeys) · Agents/partners (book of business, commissions) · Employees (CSR copilot, underwriting assist) · Admins |
| **Journey coverage** | All 16 domain-model phases — from anonymous visitor to claim settlement to win-back |

**Where the reference is genuinely exhaustive:** the *infrastructure* sweep.
Channels, security, safety stages, orchestration, model gateway, tool gateway,
RAG pipeline, state stores, async, secrets, observability, evaluation, CI/CD —
as a platform-capability inventory it misses very little; the blank-slate
exercise did its job on the "how" axis.

**Where the sweep still has blind spots — capability *semantics*, not boxes.**
The gaps are things a box can't show, and they're exactly the critical points
the exhaustive intent wanted to catch:

- **The action loop** — infrastructure for writes exists (tool gateway, events),
  but not the *semantics*: propose → confirm → execute, idempotency, approval
  gates by risk tier. "Pay my premium" is a different engineering problem than
  "what is my premium," and no box encodes that difference.
- **Proactive agency** — EventBridge is drawn, but the concept of the platform
  *initiating* contact (renewal due, lapse warning, claim update) is absent as
  a capability. Our domain-model journey phases are a ready-made trigger model.
- **Selling/onboarding journeys** — prospect → quote → application → KYC has no
  home in the agent layer, though the industry is furthest ahead exactly there
  (instant-issue underwriting for standard risks is shipping commercially).
- **Employee copilots** — the CSR who receives an escalation gets a case, but
  no AI-assisted console; underwriting/fraud assist absent from the agent roster.
- **Memory *policy*** — long-term memory is drawn as storage, but the critical
  decision is what the assistant may remember about a customer and who sees it.

**Verdict:** as a reference architecture it is near-exhaustive on platform
infrastructure and incomplete on *agent capabilities* — the inform/act/proact
axis. Adding that axis (even as annotations) would complete the blank-slate
goal, and it becomes the natural **version map**: each release lights up a set
of boxes plus one capability level (see §4.1).

## 2. How this design sits in the agentic ecosystem

Checked pattern-by-pattern against where the ecosystem has landed in 2026:

**Orchestration — supervisor + specialist agents: mainstream and validated.**
Every major framework (LangGraph, CrewAI, Semantic Kernel, AutoGen, OpenAI
Agents SDK) converged on orchestrator/worker with handoffs. Our LangGraph choice
is orthodox; no strategic risk. The ecosystem's frontier has moved to *dynamic
planning* (agents that decompose novel tasks) — we don't need that for servicing
flows; static routing is the right call for a regulated domain.

**Tools — our Tool Gateway is convergent with MCP; we should make it MCP.**
The Model Context Protocol has become *the* standard for agent↔tool integration
(now under the Linux Foundation's Agentic AI Foundation, alongside A2A;
Gartner projects 40% of enterprise apps embedding agents by end-2026, MCP at the
core). The diagram already lists "MCP Servers" in the integration layer, but as
one item among REST/GraphQL. The stronger move: **the tool gateway's contract
*is* MCP** — policy/claims/billing tools exposed as MCP servers with our
RequestContext authorization behind them. Same layering we already designed, but
the tools become reusable by any MCP client (a future CSR copilot, an IDE agent,
a partner integration) instead of being LangGraph-only. This is the single
highest-leverage ecosystem alignment available to us.

**Agent-to-agent — A2A exists (v1.0, Apr 2026, 150+ orgs in production); we
don't need it yet.** A2A matters when agents cross trust boundaries — e.g., a
partner's underwriting agent negotiating with ours, or the vendor-orchestration
pattern (Zowie-style platforms already connect external claims/fraud agents).
Right call: design nothing for it now, but keep the supervisor's agent interface
clean enough that a remote A2A agent could later stand behind the same seam.

**Identity — our RequestContext is the pattern the ecosystem is converging on.**
The industry's answer to "what may an agent do?" is delegated, on-behalf-of
authority: the agent carries the *user's* scoped identity, never its own
super-permissions (signed Agent Cards in A2A, OAuth on-behalf-of flows, agent
identity products). That is *exactly* our domain authorization rule and the RequestContext
implementation. We are ahead of most reference architectures here — the diagram
should make the delegated-authority arrow explicit because it's a genuine
strength.

**Memory — the diagram's long-term memory box maps to a real product category
(Mem0, Zep, LangMem), not a build.** Episodic/semantic memory with per-user
scoping and privacy controls is commodity infrastructure now. Decision needed is
*policy*, not engineering: what may the assistant remember about a customer
across conversations, and who can see it. That's a domain-model-level decision.

**Guardrails — buy the commodity layer, own the policy layer.** The ecosystem
moved from regex filters to model-based guardrails (Bedrock Guardrails, NeMo,
Llama Guard family) with prompt-injection defense as an arms race no small team
should fight alone. Krishna's middleware should orchestrate off-the-shelf
checks + our domain policies, not implement detection from scratch.

**Evals in CI — the diagram already includes what most teams lack.** Agent
tests, RAG eval, LLM regression in the pipeline matches emerging best practice
(golden datasets, LLM-as-judge). Our gap is practice, not architecture: no
golden dataset exists yet. Start it now — every real test conversation from the
demo becomes a seed.

**Model gateway — correct box, don't build it.** Model routing by
cost/complexity is commodity (LiteLLM-class gateways, Bedrock intelligent
routing). Adopt one when multi-model actually arrives (the open-source
Llama/Qwen experiments are the natural trigger).

**Managed runtimes — the AWS build-vs-buy question the diagram avoids.**
Bedrock AgentCore-class offerings (runtime, gateway, memory, identity,
observability as managed services) now cover perhaps half the diagram's boxes.
Recommendation: keep orchestration + tools + domain logic *owned* (it's our
core IP and the team's learning goal), consider managed services for the
commodity edges (guardrails, memory, model routing) — and record this as an
explicit ADR either way.

**Regulatory reality — for insurance this is not optional.** Under EU AI
Act-class regimes, AI touching claims/underwriting decisions sits in the
high-risk category: human oversight, logging, and explainability are legal
table stakes. Concretely: the audit store and human escalation are *compliance
infrastructure*, not nice-to-haves — which resolves their priority debate. Even
as an imaginary insurer, building as-if-regulated is the differentiator that
makes this project portfolio-credible.

## 3. Where do we stand — maturity vs. the ecosystem

Using a simple autonomy ladder for agentic systems:

| Level | Capability | Ecosystem (insurance, 2026) | Us |
| --- | --- | --- | --- |
| **L0** | Scripted chatbot, no LLM reasoning | Legacy | — |
| **L1** | Conversational assist: routed Q&A over live data, escalation | Table stakes; commercial platforms ship this on day one | **✅ Built (backbone branch)** — with identity-first design most demos skip |
| **L2** | Acts with approval: executes changes via governed tools, HITL gates | Where serious deployments are; vendors claim 60–80% of routine volume | **Target of this diagram** — tool gateway + verification + escalation, but the confirm/approve flow is undrawn |
| **L3** | Proactive & multi-agent: initiates contact, cross-boundary agents (A2A), instant-issue underwriting | Frontier; shipping narrowly (standard-risk instant issue) | Not scoped — journey phases give us the trigger model when ready |

Honest position: **we are a well-architected L1 targeting L2.** Compared to
commercial insurance AI platforms (Five Sigma, Cognigy, Zowie class): they beat
us on breadth (FNOL, document AI, underwriting) and polish (streaming, voice);
we are *not behind* on the two things that matter architecturally — delegated
identity and layered governance — and we own our stack, which they don't offer.
Compared to open reference architectures: ours is more honest about
authorization than most, weaker on the action loop than the best.

What we do better than the ecosystem norm: identity-first design; a written
domain model (README) — most agent projects have neither. What the
ecosystem does better than us today: streaming UX (table stakes everywhere),
actions with confirmation, evals as practice, model-based guardrails.

## 4. What would make it better — recommendations

1. **Keep the reference exhaustive; add a version overlay.** Don't scope the
   diagram down — that would defeat its purpose. Instead maintain a version map
   on top of it: which boxes + which capability level each release lights up.
   Proposed: **v1 = conversational servicing** (built: API/auth/conversation
   layers, supervisor + domain agents, RAG) · **v2 = governed actions** (tool
   gateway + action loop + guardrails + audit) · **v3 = proactive + breadth**
   (events/journey triggers, employee copilots, onboarding journeys, memory).
   The §1 matrix supplies the missing capability axis.
2. **Design the action loop as first-class** (the L2 jump): propose → confirm →
   execute with idempotency keys, approval gates by risk tier (self-service vs.
   CSR-approved vs. blocked), all through the tool gateway. This — not more
   agents — is the next architectural capability.
3. **Make the tool gateway MCP-native.** Same design, standard contract;
   unlocks reuse across future copilots and partner integrations.
4. **Adopt, don't build, the commodity edges:** model-based guardrails, memory
   store, model routing gateway. Own orchestration, tools, domain logic. Record
   as an ADR.
5. **Start the golden dataset this week** — evals are the practice gap, and
   they gate every future prompt/model change.
6. **Treat audit + human oversight as compliance infrastructure** (high-risk
   domain), which settles their priority: they land with the guardrails phase.
7. **Proactive agents as a named future phase**, triggered off journey phases —
   our domain model is the differentiator there.

## 5. Diagram-level findings (condensed)

| # | Finding | Action |
| --- | --- | --- |
| 5.1 | Horizontal Cache Layer between safety and orchestration risks cross-customer leakage | Remove; cache inside model gateway / RAG / tool layer, keyed by user + scope |
| 5.2 | Generic Agent_1/Agent_2 undersell the decided domain decomposition | Name policy/claims/billing; Notification is a tool, not an agent |
| 5.3 | Audit store has no write-path drawn | Arrows from tool gateway + output stage; see §4.6 |
| 5.4 | CI/CD: no trigger semantics, eval-cost policy, rollback, approval gate, or migration step | Annotate; near-term: minimal GitHub Actions (lint + unit + routing check) needs no AWS |
| 5.5 | Long-term memory + External APIs appear without a scope decision | Mark "future phase — decision pending"; memory needs a privacy policy first (§2) |
| 5.6 | Typos: "Quadrant" → Qdrant; "Obervability" → Observability | Fix |

## 6. Proposed team-sync agenda

1. Adopt the reference architecture + agree the v1/v2/v3 version overlay (§1, §4.1) — *team*
2. Action-loop design as the next capability (§4.2) — *team; Syam to draft*
3. MCP as the tool-gateway contract — sequencing with utils.py refactor (§4.3) — *Jayanth · Syam*
4. Buy-vs-build for guardrails/memory/routing → ADR (§4.4) — *Krishna · team*
5. Golden dataset kickoff + minimal CI (§4.5, §5.4) — *Syam*
6. Diagram edits (§5) — *Jayanth*

---

*Ecosystem references: [State of Agentic AI Standards 2026](https://datalakehousehub.com/blog/state-of-agentic-ai-standards-2026/) ·
[MCP vs A2A protocol guide](https://dev.to/pockit_tools/mcp-vs-a2a-the-complete-guide-to-ai-agent-protocols-in-2026-30li) ·
[AI agent protocol ecosystem map](https://www.digitalapplied.com/blog/ai-agent-protocol-ecosystem-map-2026-mcp-a2a-acp-ucp) ·
[AI support platforms for insurance 2026](https://www.lorikeetcx.ai/articles/ai-support-insurance-2026) ·
[Insurance AI agent platforms](https://getzowie.com/blog/10-best-customer-ai-agent-platform-for-insurance-in-2026-ai-agents-and-chatbots) ·
[AI agents for claims/underwriting/fraud](https://theaiagentindex.com/resources/guides/best-ai-agents-for-insurance)*
