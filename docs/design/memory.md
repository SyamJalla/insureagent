# Memory Block — Policy (D3) + Contracts

Lean by design: §1 is the decision record the team ratifies; §2 the contracts;
§3 the build steps. Implementation follows immediately.

## 1. Memory policy (decision D3 — proposed defaults, amend at sync)

| Question | Decision |
| --- | --- |
| **What may be remembered** | Episodic: per-conversation summaries (user intent, what was answered, actions taken) referencing entities by ID (claim CLM…, policy POL…) — no free-text PII beyond what the summary needs. Semantic: durable service facts & preferences (contact preference, recurring concerns, product interests). NEVER: passwords/credentials, payment instruments, health details, verbatim message dumps. |
| **Whose memory is it** | The user's, strictly. Retrieval is scoped by `user_id` in the store query (same enforcement style as the tool gateway). CSR/admin do NOT browse customer memory in v1 (revisit with the CSR console). |
| **Retention** | Episodic summaries: 180 days. Semantic facts: until superseded or deleted. TTL enforced by a sweep in the store, not by hope. |
| **User control** | View + delete (per-item and clear-all) via API from day one; UI affordance later. Deletion is hard (rows gone), not soft. |
| **Authority** | Memory is CONTEXT, never authority: every retrieved item carries its date and is prompt-marked "from previous conversations — may be outdated; verify current facts via tools." The DB remains the source of truth. Memory suggests; systems confirm. |
| **Injection stance** | Summaries are derived from user text → treated as data, never instructions. Summarizer output is stored plain; retrieval block is wrapped in a data-only frame. Adversarial memory case goes into the golden set. |

## 2. Contracts

```python
class MemoryKind(str, Enum):
    EPISODIC = "episodic"      # conversation summary
    SEMANTIC = "semantic"      # durable fact/preference

class MemoryItem(BaseModel):
    memory_id: str
    user_id: str
    kind: MemoryKind
    content: str               # summary text or fact statement
    intents: list[str] = []    # episodic: main intents of the conversation
    actions: list[str] = []    # episodic: what the agents did
    source_conversation_id: str | None
    created_at: datetime       # carried into prompts (staleness signal)

class MemoryStore(ABC):        # Postgres rows + Chroma embeddings (episodic)
    def add(self, item: MemoryItem) -> None: ...
    def semantic_facts(self, user_id: str) -> list[MemoryItem]: ...
    def similar_episodes(self, user_id: str, query: str, k: int = 3) -> list[MemoryItem]: ...
    def list_for_user(self, user_id: str) -> list[MemoryItem]: ...        # "my memory"
    def delete(self, user_id: str, memory_id: str | None = None) -> int: ...  # None = all
    def sweep_expired(self) -> int: ...

class ShortTermMemory(ABC):    # per-conversation scratch; Postgres now, Redis swap-in
    def get(self, conversation_id: str) -> dict: ...
    def set(self, conversation_id: str, state: dict, ttl_s: int = 3600) -> None: ...
```

**Write path:** `Summarizer` (LLM gateway, FAST tier) runs when a conversation
accumulates N=4 new messages since its last summary — one call extracts
summary/intents/actions + at most 2 candidate semantic facts. Triggered inline
after the reply (cheap), async later.
**Read path:** runner's context assembly calls `semantic_facts` +
`similar_episodes(query)` and appends a dated, data-framed block to the
verified session context. Behind `MEMORY_ENABLED=false` until the golden set
gains memory cases (recall / deletion-respected / stale-doesn't-override-DB).

## 3. Build steps

1. Migration 004 (`memory_items`, `conversation_scratch`) + `MemoryStore`
   Postgres impl + Chroma `user_memory` collection (user_id-filtered).
2. Summarizer + write path (observable in DBeaver/Langfuse; no behavior change).
3. Read path + `MEMORY_ENABLED` flag + memory endpoints (GET/DELETE `/me/memory`).
4. Golden cases + flag flip alongside an eval run.
5. Later: Redis `ShortTermMemory` impl when action-loop/pending-state needs it;
   scheduled buy-vs-build review against Mem0/Zep once v1 requirements are real.
