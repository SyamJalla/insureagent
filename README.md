# InsureAgent

A multi-agent insurance customer-support **web application** for an imaginary insurance
company. Users log in (customers, prospects, agents, employees, admins — see
Domain model below) and chat with an AI assistant. A LangGraph supervisor agent
routes each question to a specialist agent (policy, billing, claims, general help, or
human escalation); a final answer agent composes the response. The backend resolves each
user's identity server-side, so a customer asking "what is my premium?" gets the answer
for *their own* policies without ever typing a policy number.

Specialist agents answer from two local data sources: a **PostgreSQL** database (synthetic
customer/policy/claim/billing records plus users and conversations), and a **ChromaDB**
vector collection of insurance FAQs (RAG for general knowledge only — never customer
data). LLM calls go to OpenAI; traces to a self-hosted **Langfuse**.

## What this is NOT

- Not backed by real data — every record is synthetic; demo accounts use a shared
  password printed by the seed script.
- Not yet streaming or proactive — responses arrive whole; the platform never
  initiates contact. Both are planned phases.
- Not deployed — everything runs locally; Cognito/Postgres/cloud are later swap-ins
  behind existing interfaces (see [docs/design/phase1-backbone.md](docs/design/phase1-backbone.md)).

## Environment

Uses the shared **`genai`** conda environment (Python 3.11) — the dependencies in
`requirements.txt` install cleanly there and no version conflict justifies a separate env.

```bash
conda activate genai
pip install -r requirements.txt
```

## Setup

1. **Configure secrets.** Create a `.env` file in the project root (git-ignored):

   ```
   OPENAI_API_KEY=sk-...
   JWT_SECRET=<openssl rand -hex 32>
   APP_DB_URL=postgresql://postgres:root@localhost:5432/insureagent
   LANGFUSE_SECRET_KEY=sk-lf-...      # optional; tracing disabled without it
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_BASE_URL=http://localhost:3000
   ```

   Requires a local PostgreSQL (any recent version) reachable at `APP_DB_URL`.
   All data lives there: app-owned tables (users, conversations, messages) and
   the synthetic enterprise tables (customers, agents, policies, billing,
   payments, claims).

2. **Create/update the Postgres schema** (also creates the database itself;
   idempotent — run it after every pull that adds a migration):

   ```bash
   python scripts/db/migrate.py
   ```

   Schema DDL lives in `scripts/db/migrations/*.sql`, applied in order and
   tracked in `schema_migrations`. To change the schema: add a new numbered
   file — never edit an applied one.

3. **Start Langfuse** (optional, tracing): `docker compose up -d` → UI at
   http://localhost:3000. Change the `# CHANGEME` credentials in `docker-compose.yml`
   before exposing anywhere.

4. **Build the data sources** (writes to `datasources/`, git-ignored):

   ```bash
   python scripts/seed_enterprise.py  # synthetic insurance data (deterministic)
   python scripts/seed_users.py       # demo user accounts + agent book
   python create_vectordb.py          # FAQ vector store (ChromaDB)
   ```

   The seed script prints the demo logins (e.g. `customer1@demo.local` / `demo123`).

## Running

```bash
uvicorn app.main:app --reload
```

Open http://localhost:8000 — log in with a seeded account and chat. API docs at
http://localhost:8000/docs.

## Domain model

An imaginary insurer; all data synthetic. The rules that shape the code:

- **Person vs. policy:** a person has one identity and role; each policy has its own
  lifecycle phase. One person can hold policies in different phases at once.
- **Roles:** `prospect` (registered, no policy) · `customer` (holds ≥1 policy; access
  always scoped to *their* policies) · `agent` (external partner; sees only their book
  of business — the customers on policies carrying their `agent_id`; earns commissions
  on those policies; `agent_id NULL` = direct policy) · `employee` (CSR; receives
  escalations, audited) · `admin`. AI agents are never a principal — they act with the
  requesting user's authority (`RequestContext`), carried into every tool call.
- **Journey phases (per policy/application):** visitor → lead → quote → application →
  KYC → medical/risk assessment → underwriting → initial payment → issued (free-look)
  → in-force → claim in progress (intimated → documents → assessment →
  approved/rejected → settled) → renewal due/grace → lapsed | cancelled/surrendered |
  matured → win-back. Pre-application phases attach to the person.
- **Authentication vs. authorization:** one login flow for every role — customer
  status is *authorization* data, not an authentication branch. RBAC (role → which
  capabilities) + ABAC (ownership/phase → which records), enforced in the tool layer,
  never by the LLM: **LLMs reason; systems decide.**
- **RAG boundary:** vector store holds general knowledge only; customer-specific facts
  come from the database, always.

## Architecture

```
Frontend (static chat page — pure API consumer, JWT only)
   ↓
API layer (FastAPI: auth, conversations; middleware builds RequestContext)
   ↓
Conversation service (sessions, history, context assembly)
   ↓
Agent layer (LangGraph: supervisor → specialists → final answer)
   ↓                                    ↘ LLM gateway (model tiers, cost, retries)
Tool gateway (RBAC + ownership scoping in SQL — "LLMs reason; systems decide")
   ↓
PostgreSQL (all data) · ChromaDB (FAQ RAG) · OpenAI · Langfuse
```

Each layer knows only the one below it. `RequestContext` (who is asking: user, role,
owned policies — resolved server-side from the JWT) flows downward on every request.
Full design: [docs/design/phase1-backbone.md](docs/design/phase1-backbone.md) ·
orchestrator internals (graph, routing, tools): [docs/design/orchestrator.md](docs/design/orchestrator.md).

## Layout

| Path | Contents |
| --- | --- |
| `app/` | The application package: `api/` routers, `auth/`, `conversations/`, `agents/` (supervisor, specialists, orchestrator, runner), `tools/` (gateway + tools, RBAC/ownership), `llm/` (model gateway + router), `static/` chat UI, `config.py`. |
| `utils.py` | Retired POC (unreferenced) — kept for review; deletion is a pending commit. |
| `scripts/` | `db/migrate.py` + `db/migrations/*.sql` (all DDL), `seed_enterprise.py` (synthetic data), `seed_users.py` (demo accounts). |
| `create_vectordb.py` | One-time setup: FAQ vector store. |
| `prompts/` | One YAML prompt file per agent. |
| `datasources/` | Chroma vector store (and the obsolete pre-migration SQLite file). Git-ignored. |
| `docs/` | Design docs (`design/`), future ADRs (`adr/`). |
| `notes/` | Team notes, target architecture, work split. |
| `docker-compose.yml` | Self-hosted Langfuse stack for tracing. |

## Known rough edges

- The graph is invoked synchronously per message (single worker blocks during LLM
  calls); fine for demo scale, revisit before load testing.
- Langfuse tracing is not yet re-wired into the new agent layer (gateway logs only).
- Prompts are file-based YAML rather than versioned in Langfuse.
- Complexity-based model routing is built but shipped OFF (`COMPLEXITY_ROUTING_ENABLED`);
  flip only alongside an eval run.
