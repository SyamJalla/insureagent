# InsureAgent Delivery Plan — Story · Data · Backlog

**Basis:** existing code = the POC baseline · Jayanth's task register
(`docs/Jayanth/multi_agent_architecture_tasks_.xlsx`) = planning base · the two
roadmap sheets = supporting references. This document adds the three things the
register needs to be executable: the company story, the data to support it, and
the work expressed as user stories (each mapped to register task IDs).

---

# Part I — The Company Story

## Horizon Mutual Insurance

*(placeholder name — rename once as a team; it propagates into products, documents, and UI)*

A mid-sized regional insurer. **~1,000 customers, ~1,500 active and historical
policies, ~300 claims on record** — deliberately matching our synthetic data, so
the story and the database are the same thing. Horizon sells through two
channels: **direct** and a network of **partner agents** who earn commission on
the policies they service. It runs a small customer-service team (CSRs) that
handles anything the digital channel can't.

**The product line** (2 products per line of business — these names seed the
database and the document corpus):

| Line | Products |
| --- | --- |
| Auto | **SecureDrive Standard** · **SecureDrive Plus** (adds rental car, zero-depreciation) |
| Home | **HomeShield Basic** · **HomeShield Complete** (adds contents, natural-catastrophe) |
| Life | **LifeGuard Term** · **LifeGuard Whole** |
| Health | **CarePlus Individual** · **CarePlus Family** |

**The initiative:** Horizon is building **InsureAgent**, an AI assistant as its
digital front door. Version 1 answers and serves (conversational servicing);
version 2 acts (payments, endorsements, claim filing — with approval gates);
version 3 reaches out (renewal reminders, claim updates) and assists employees.
Guiding rule everywhere: **LLMs reason; systems decide.**

**The personas** (each maps to a seeded login — the demo *is* the story):

| Persona | Role | Situation | Demo login |
| --- | --- | --- | --- |
| **Priya** | Customer | Two policies (SecureDrive Plus, HomeShield Basic), in force, renewal approaching | customer1@demo.local |
| **Rahul** | Customer | Auto claim under assessment after an accident | customer2@demo.local |
| **Sneha** | Customer | Policy lapsed last month; wants to revive | customer3@demo.local *(new)* |
| **Anil** | Prospect | Comparing term-life options, no policy yet | prospect@demo.local |
| **Meera** | Partner agent | Services a book of ~15 policies; tracks her commissions | agent@demo.local |
| **David** | CSR | Receives escalations with full context | csr@demo.local |

**The demo arc** (the story told in five minutes): Priya asks about her premium
→ assistant knows *her* policies without being told → Rahul asks about his claim
→ gets the stage, adjuster, next steps → Anil asks what term life covers → FAQ
answer with citation, no customer data → Meera asks about her book → sees only
her policies → someone asks for a human → David gets a case with an AI-written
summary. Every scene demonstrates an architecture principle (identity, tool
authorization, RAG boundary, escalation).

# Part II — Data to Support the Story

The design is already written — [docs/design/depth-workstream.md](../design/depth-workstream.md).
This section binds it to the story; the depth doc remains the technical spec.

1. **Tranche A schema + seed enrichment** = "make the data tell the story":
   the 8 products above become `products` + `product_coverages` rows; every
   policy links to a product with coverage elections and computed lifecycle
   dates; claims get stages/adjusters/amounts; escalations become `cases`.
   Personas get seeded exactly as described (incl. Sneha, and widening Meera's
   book to ~15).
2. **Consistency as a tested property:** `verify_consistency.py` — statuses
   derived from dates, amounts ordered, every journey phase represented
   relative to *today* so the demo works on any date.
3. **Document corpus generated from the catalog** (brochures, policy wordings,
   FAQs, claims guides per product) so RAG answers can never contradict the
   database. Access-level metadata from day one.
4. Tranche B (`service_requests`, mandates, refunds) lands with the v2 action
   loop; Tranche C (quotes/applications/underwriting, commissions statements)
   with v3 — per the register's phases.

# Part III — The Backlog as User Stories

Grouped into epics; each story carries acceptance criteria and the register
task IDs it advances (`reg #`). Status: ✅ built in POC (verify against code) ·
🔨 next · 📋 planned · 🔒 decision needed first.
Personas are used as the "as a" actor wherever natural.

## Epic 1 — Identity & Access *(reg 4, 5)*

| # | Story | Acceptance | Status |
| --- | --- | --- | --- |
| 1.1 | As any user, I can log in with email/password and get a session that expires. | JWT issued/validated; expiry enforced; bad credentials rejected | ✅ |
| 1.2 | As the platform, I resolve each request to who is asking — role + owned policies — server-side, never from client input. | RequestContext built per request; client supplies only the token | ✅ |
| 1.3 | As the team, we have a written RBAC matrix: role × capability × data scope. | Matrix doc approved; drives tool gateway checks | 🔨 reg 5 |
| 1.4 | As an admin, I can create/disable users. | Admin endpoints; audit of changes | 📋 |
| 1.5 | As a user, I can log in via Cognito/Google when we move to cloud. | AuthProvider swap, no caller changes | 📋 reg 33–34 phase |

## Epic 2 — Conversational Servicing *(reg 3, 8, 9)*

| # | Story | Acceptance | Status |
| --- | --- | --- | --- |
| 2.1 | As Priya, I can hold multi-turn conversations that survive page reload, and only I can see them. | Conversation store scoped by user; history restores | ✅ |
| 2.2 | As Priya, I get answers about *my* policies without typing a policy number. | Identity context flows into the graph; clarification when ambiguous | ✅ |
| 2.3 | As Rahul, I can ask my claim's stage, adjuster, and next steps. | Needs Tranche A claim lifecycle data | 🔨 |
| 2.4 | As Priya, I see responses stream in instead of waiting on a spinner. | SSE on the message endpoint; UI renders tokens | 📋 reg 3 |
| 2.5 | As Sneha, the assistant knows my policy lapsed and explains revival. | Journey-phase data + phase-aware supervisor context | 🔨 |
| 2.6 | As Meera, I can ask about my book of business and see only my policies' customers. | Agent-scope queries; cross-book access refused | 📋 (after reg 6) |

## Epic 3 — Story & Data (Tranche A) *(reg 27 extended)*

| # | Story | Acceptance | Status |
| --- | --- | --- | --- |
| 3.1 | As the team, our database embodies Horizon Mutual: products, coverages, policy lifecycle, claim stages, adjusters, cases. | Tranche A DDL applied; seed enriched; personas seeded | 🔨 |
| 3.2 | As the team, seed data is provably consistent on any demo date. | verify_consistency.py green; runs in CI | 🔨 |
| 3.3 | As the team, every journey phase has at least one demo-able customer. | Phase coverage report from the seed script | 🔨 |

## Epic 4 — Knowledge & RAG *(reg 17-19-ish, register's vector work redirected)*

| # | Story | Acceptance | Status |
| --- | --- | --- | --- |
| 4.1 | As Anil, I get accurate general answers ("what does term life cover?") with source citations. | Corpus + citations in answers | 📋 |
| 4.2 | As Horizon, retrievable documents are generated from our catalog and can never contradict the database. | Corpus build from products; spot-check passes | 📋 |
| 4.3 | As Horizon, internal/agent documents never surface to customers. | access_level filter from RequestContext; negative tests 100% | 📋 |
| 4.4 | As the team, retrieval quality is a number, not a feeling. | Golden set; hit@3 ≥ 0.8 in CI | 📋 reg 29 |

## Epic 5 — Tool Gateway & Authorization *(reg 6, 7 — Critical)*

| # | Story | Acceptance | Status |
| --- | --- | --- | --- |
| 5.1 | As Horizon, every tool call checks the caller's authority before touching data — the LLM cannot bypass it. | Tools take RequestContext; cross-customer lookups refused; tested incl. IDOR-style attempts (reg 30) | 🔨 reg 6 |
| 5.2 | As the team, tools live in a registry with typed schemas, timeouts, and audit of every call. | Tool registry + executor; `required` fields fixed | 📋 reg 7 |
| 5.3 | As the team, tools speak MCP so future clients (CSR copilot, partners) can reuse them. | Tool layer exposed as MCP server | 🔒 decision D4 |

## Epic 6 — Guardrails & Safety *(reg 12, 13 — Krishna's lane)*

| # | Story | Acceptance | Status |
| --- | --- | --- | --- |
| 6.1 | As Horizon, malicious prompts (injection, jailbreak) are detected before reaching agents. | Input guardrail middleware after auth; adversarial tests pass | 📋 |
| 6.2 | As Horizon, responses are checked for PII leakage and policy compliance before delivery. | Output guardrail stage; leakage tests | 📋 |
| 6.3 | As a compliance reviewer, I can reconstruct any interaction: who asked, tools run, data returned, answer given. | Audit records keyed by correlation_id | 📋 reg 16(M2) |

## Epic 7 — Memory *(reg 14–20 — resequenced: policy first)*

| # | Story | Acceptance | Status |
| --- | --- | --- | --- |
| 7.1 | As Horizon, we have a memory policy: what may be remembered about a customer, TTL, deletion, who sees it. | Policy doc approved | 🔒 D3 — gates the rest |
| 7.2 | As Priya, the assistant remembers relevant preferences across conversations, per policy 7.1. | Long-term store honoring policy; deletion works | 📋 |
| 7.3 | As the team, long conversations are summarized so context stays within limits. | Summarization + retrieval | 📋 |

## Epic 8 — Actions, v2 *(the register's biggest gap — new)*

| # | Story | Acceptance | Status |
| --- | --- | --- | --- |
| 8.1 | As the team, we have an action-loop design: propose → confirm → execute, idempotency, risk-tiered approval. | Design doc approved | 🔨 design next |
| 8.2 | As Priya, I can pay a due premium in chat, confirming before execution. | service_requests + idempotency; Tranche B | 📋 |
| 8.3 | As Rahul, I can file a claim conversationally (FNOL) with document checklist. | Claim created in `intimated`; docs requested | 📋 |
| 8.4 | As Sneha, I can request revival of my lapsed policy; high-risk actions route to a human for approval. | CSR approval gate demonstrated | 📋 |

## Epic 9 — Escalation & Employee Experience *(reg 26)*

| # | Story | Acceptance | Status |
| --- | --- | --- | --- |
| 9.1 | As David, an escalation reaches me as a case with the conversation, an AI summary, and suggested next steps. | `cases` populated on escalation; CSR view | 🔨 with Tranche A |
| 9.2 | As David, I can note and resolve cases; customers see status. | Case lifecycle endpoints | 📋 |

## Epic 10 — Observability, Evals & Ops *(reg 22–25, 28–32)*

| # | Story | Acceptance | Status |
| --- | --- | --- | --- |
| 10.1 | As the team, every request is traceable end-to-end by one correlation id (API → agents → tools → LLM). | Langfuse + correlation propagation | 🔨 partial (reg 24) |
| 10.2 | As the team, a PR cannot merge if lint, unit tests, or the routing check fail. | GitHub Actions; no AWS needed | 🔨 reg 32 |
| 10.3 | As the team, agent quality is benchmarked against a golden dataset before any prompt/model change ships. | Eval suite in CI (LLM evals on merge/nightly) | 📋 reg 29 |
| 10.4 | As the team, retries/timeouts/circuit breakers protect every external call. | Bounded retries; failure-injection test | 📋 reg 25 |
| 10.5 | As Horizon, the platform runs in AWS with secrets managed and costs capped. | reg 33–34 + roadmap M2 as reference | 📋 |

## Decisions tab (resolve at the sync — not tasks)

| ID | Decision | Options / recommendation |
| --- | --- | --- |
| D1 | LLM provider: stay OpenAI or move to Bedrock Claude Sonnet (register assumes Bedrock)? | Recommend: abstract behind the model gateway now (reg 10/11), decide provider with cost data; ADR either way |
| D2 | Which effort baseline: POC roadmap (~134d) or full (~239d)? | Recommend: neither verbatim — estimate per user story at the sync |
| D3 | Memory policy (gates Epic 7). | Draft policy from README domain model; approve or amend |
| D4 | MCP as the tool contract? | Recommend yes, at Epic 5.2 time — same work, standard shape |
| D5 | Company name ("Horizon Mutual" placeholder). | 5-minute team decision; propagates into data + corpus |

## Suggested sequence (first two sprints)

**Sprint 1 — the story becomes real:** 3.1–3.3 (Tranche A + personas), 2.3/2.5
(claim & lapse conversations), 9.1 (cases), 10.2 (minimal CI), 1.3 (RBAC matrix
— feeds Epic 5). *Demo: the full persona arc.*
**Sprint 2 — trust the answers:** 5.1–5.2 (tool gateway — the Critical items),
4.1–4.4 (corpus + citations + eval), 10.1 (correlation), 8.1 (action-loop
design). *Demo: authorized tools + cited answers.*
