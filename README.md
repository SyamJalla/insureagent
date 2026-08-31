# InsureAgent

A multi-agent insurance customer-support assistant built on **LangGraph**. A supervisor
agent classifies each user query, routes it to a specialist agent (policy, billing,
claims, general help, or human escalation), and loops back until a final answer agent
composes the response.

Specialist agents answer from two local data sources: a **SQLite** database of synthetic
customer/policy/claim/billing records, and a **ChromaDB** vector collection of insurance
FAQs used for retrieval-augmented general-help answers. LLM calls go to OpenAI; traces
are sent to a self-hosted **Langfuse** instance.

## What this is NOT

- Not a production service — there is no API, no web interface, no authentication, and no
  session management. The entry point runs a single hardcoded test query.
- Not backed by real data. Every customer, policy, claim, and payment record is generated
  synthetically by `utils.generate_sample_data()`.
- Not yet modularized. `agents/` contains empty placeholder files; all agent logic
  currently lives in `utils.py`. See [notes/future-steps.txt](notes/future-steps.txt).

## Environment

Uses the shared **`genai`** conda environment (Python 3.11) — the dependencies in
`requirements.txt` install cleanly there and no version conflict justifies a separate env.

```bash
conda activate genai
pip install -r requirements.txt
```

## Setup

1. **Configure secrets.** Create a `.env` file in the project root (it is git-ignored):

   ```
   OPENAI_API_KEY=sk-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_BASE_URL=http://localhost:3000
   ```

2. **Start Langfuse** (tracing backend — Postgres, ClickHouse, Redis, MinIO):

   ```bash
   docker compose up -d
   ```

   The UI is at http://localhost:3000. Change the `# CHANGEME` credentials in
   `docker-compose.yml` before exposing this anywhere.

3. **Build the data sources** (writes to `datasources/`, both git-ignored):

   ```bash
   python create_vectordb.py
   ```

   This creates the FAQ vector collection and seeds the synthetic SQLite database.

4. **Verify the data loaded:**

   ```bash
   python retrieve_data.py
   ```

## Running

```bash
python insurance_agent.py
```

The test query is currently hardcoded near the bottom of
[insurance_agent.py](insurance_agent.py) — edit `test_query` to try a different one.

## Agent graph

```
                    ┌──────────────────┐
   user query ─────►│    supervisor    │◄──────────┐
                    └────────┬─────────┘           │
                             │ routes to           │ returns
        ┌────────────┬───────┴───────┬─────────────┤
        ▼            ▼               ▼             ▼
     policy       billing         claims      general help
                                              (FAQ retrieval)
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
       final answer ─► END        human escalation ─► END
```

Shared state flows through `GraphState` (a `TypedDict` in `utils.py`), which carries the
conversation history, extracted entities, routing decision, database lookup results, and
escalation flags.

## Layout

| Path | Contents |
| --- | --- |
| `insurance_agent.py` | Entry point — loads config, builds the graph, runs one query. |
| `utils.py` | All agent nodes, tools, graph wiring, DB and vector-store helpers. |
| `create_vectordb.py` | One-time setup: builds the FAQ vector DB and seeds SQLite. |
| `retrieve_data.py` | Smoke test for the vector store and database. |
| `insurance_data_prep.py` | Earlier data-prep script, superseded by `create_vectordb.py`. |
| `prompts/` | One YAML prompt file per agent, loaded by `utils.load_prompt()`. |
| `agents/` | Placeholder modules for the planned split of `utils.py`. Currently empty. |
| `datasources/` | Generated SQLite DB and Chroma vector store. Git-ignored. |
| `notes/` | Design notes and the roadmap. |
| `docker-compose.yml` | Self-hosted Langfuse stack for tracing. |

## Known rough edges

- `utils.py` is ~1800 lines and mixes agent logic, tool implementations, database access,
  and graph construction. Splitting it into `agents/` is the next planned step.
- `insurance_data_prep.py` writes to different paths than the rest of the project
  (`/vectordb`, `insurance_support.db` at the root) and uses a different collection name.
  Use `create_vectordb.py` instead.
- Prompts are file-based YAML rather than versioned in Langfuse.
