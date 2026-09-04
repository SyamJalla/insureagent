# InsureAgent

A multi-agent insurance customer-support **web application** for an imaginary insurance
company. Users log in (customers, prospects, agents, employees, admins — see
[CONTEXT.md](CONTEXT.md)) and chat with an AI assistant. A LangGraph supervisor agent
routes each question to a specialist agent (policy, billing, claims, general help, or
human escalation); a final answer agent composes the response. The backend resolves each
user's identity server-side, so a customer asking "what is my premium?" gets the answer
for *their own* policies without ever typing a policy number.

Specialist agents answer from two local data sources: a **SQLite** database of synthetic
customer/policy/claim/billing records, and a **ChromaDB** vector collection of insurance
FAQs (RAG for general knowledge only — never customer data). LLM calls go to OpenAI;
traces to a self-hosted **Langfuse**.

## What this is NOT

- Not backed by real data — every record is synthetic; demo accounts use a shared
  password printed by the seed script.
- Not yet enforcing tool-layer authorization — user identity flows *into* the agent
  graph, but the underlying tools don't yet reject cross-customer lookups. Planned
  after the `utils.py` refactor.
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
   LANGFUSE_SECRET_KEY=sk-lf-...      # optional; tracing disabled without it
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_BASE_URL=http://localhost:3000
   ```

2. **Start Langfuse** (optional, tracing): `docker compose up -d` → UI at
   http://localhost:3000. Change the `# CHANGEME` credentials in `docker-compose.yml`
   before exposing anywhere.

3. **Build the data sources** (writes to `datasources/`, git-ignored):

   ```bash
   python create_vectordb.py     # FAQ vector DB + synthetic insurance DB
   python scripts/seed_users.py  # demo user accounts + policy-agent links
   ```

   The seed script prints the demo logins (e.g. `customer1@demo.local` / `demo123`).

## Running

```bash
uvicorn app.main:app --reload
```

Open http://localhost:8000 — log in with a seeded account and chat. API docs at
http://localhost:8000/docs.

## Architecture

```
Frontend (static chat page — pure API consumer, JWT only)
   ↓
API layer (FastAPI: auth, conversations; middleware builds RequestContext)
   ↓
Conversation service (sessions, history, context assembly)
   ↓
Agent layer (LangGraph: supervisor → specialists → final answer)
   ↓
Tool layer (typed tools; future authorization enforcement — "LLMs reason; systems decide")
   ↓
SQLite (customer/policy data) · ChromaDB (FAQ RAG) · OpenAI · Langfuse
```

Each layer knows only the one below it. `RequestContext` (who is asking: user, role,
owned policies — resolved server-side from the JWT) flows downward on every request.
Full design: [docs/design/phase1-backbone.md](docs/design/phase1-backbone.md).

## Layout

| Path | Contents |
| --- | --- |
| `app/` | The application package: `api/` routers, `auth/` (JWT provider, RequestContext), `conversations/` (store + service), `agents/runner.py` (sole importer of `utils.py`), `static/` chat UI, `config.py` Pydantic settings. |
| `utils.py` | Legacy: all agent nodes, tools, graph wiring. Refactor pending (Jayanth). |
| `scripts/seed_users.py` | Demo users + policy-agent associations. Owns all schema extensions. |
| `create_vectordb.py` | One-time setup: FAQ vector DB + synthetic SQLite data. |
| `prompts/` | One YAML prompt file per agent. |
| `datasources/` | Generated SQLite DB and Chroma vector store. Git-ignored. |
| `docs/` | Design docs (`design/`), future ADRs (`adr/`). |
| `notes/` | Team notes, target architecture, work split. |
| `docker-compose.yml` | Self-hosted Langfuse stack for tracing. |

## Known rough edges

- `utils.py` (~1800 lines) mixes agent logic, tools, DB access, and graph wiring;
  its split is Jayanth's workstream. `app/agents/runner.py` is the only import seam.
- `runner.py` patches `utils.ask_user` so clarification questions become chat replies
  instead of blocking console `input()` — should become a first-class graph outcome
  in the refactor.
- The graph is invoked synchronously per message (single worker blocks during LLM
  calls); fine for demo scale, revisit before load testing.
- Prompts are file-based YAML rather than versioned in Langfuse.
