# InsureAgent Project Flow

```mermaid
flowchart TD
    U[User] --> UI[Chat UI]
    UI --> API[FastAPI API]
    API --> AUTH[Authenticate and build RequestContext]
    AUTH --> CS[Conversation service]
    CS --> GR{Input guardrails enabled?}
    GR -- Block or escalate --> BLOCKED[Save canned reply]
    BLOCKED --> UI
    GR -- Continue --> SAVE_INPUT[Save user message]
    SAVE_INPUT --> RUN[Agent runner]
    RUN --> CTX[Load conversation history]
    CTX --> MR{Long-term memory enabled?}
    MR -- Yes --> RETRIEVE[Retrieve relevant user memory]
    MR -- No --> GRAPH[LangGraph agent graph]
    RETRIEVE --> GRAPH
    GRAPH --> SUP[Supervisor proposes route or plan]
    RUN --> TIER{Selected tier}
    TIER -- Tier 1 --> OPENAI[OpenAI gateway]
    TIER -- Tier 2 --> GROQ[Groq gateway]
    TIER -- Tier 3 --> LAYA[Local Laya decision classifier]
    LAYA -- Confident domain --> GROQ
    LAYA -- Low confidence or unavailable --> SUP
    SUP -- Clarification or direct reply --> REPLY[Return supervisor reply]
    SUP -- Specialist task --> SPEC[Policy, billing, claims, or general help]
    SUP -- Human escalation --> ESC[Human escalation agent]
    SPEC --> TG[Tool gateway: RBAC and ownership checks]
    TG --> DB[(PostgreSQL: customer and conversation data)]
    TG --> FAQ[(ChromaDB: general insurance FAQs)]
    TG --> SPEC
    SPEC -- Findings --> SUP
    SUP -- Plan complete --> ANSWER[Final answer agent]
    SUP -- Iteration limit --> ANSWER
    GRAPH -. Invalid/empty route fallback .-> REPLY
    GRAPH -. Runtime error fallback .-> ERROR[Graceful error reply]
    GRAPH <--> LLM[Selected LLM gateway]
    LLM <--> OPENAI
    LLM <--> GROQ
    ANSWER --> SAVE[Save assistant reply]
    ESC --> SAVE
    REPLY --> SAVE
    ERROR --> SAVE
    SAVE --> SUMMARIZE[Summarize and update user memory]
    SUMMARIZE --> DB
    SUMMARIZE --> VEC[(ChromaDB: user-memory index)]
    SUMMARIZE --> UI
    UI -. Optional user rating .-> FEEDBACK[Record feedback]
    FEEDBACK -. Monitoring only; no self-correction .-> LF[Langfuse]
    CS -. traces .-> LF[Langfuse]
```

Customer-specific facts flow through PostgreSQL tools; the FAQ vector store contains general knowledge only. The tool gateway enforces authorization independently of the LLM. Input guardrails are mode-flagged and default to off. Long-term memory retrieval is configurable; conversation history is still included, and memory summarization runs after a normal agent response. There is no consensus/voting mechanism: the supervisor routes work, and specialists return findings to it. User feedback is recorded for monitoring, not used as an automatic self-correction loop.
