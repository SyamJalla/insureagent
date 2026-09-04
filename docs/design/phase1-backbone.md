# Phase 1 Design — Application Backbone

Design walkthrough for the FastAPI backbone: auth, conversation/session management,
dummy user data, and the v1 chat frontend. Review this before implementation.
Vocabulary per [CONTEXT.md](../../CONTEXT.md).

Scope boundary (agreed): user identity flows *into* the agent graph, but tool-layer
authorization enforcement lands after the `utils.py` refactor. The existing LangGraph
workflow is wrapped, not modified.

---

## 1. Package layout

```
insureagent/
├── app/                        ← NEW installable package
│   ├── __init__.py
│   ├── main.py                 ← FastAPI app factory, router mounting, middleware
│   ├── config.py               ← Pydantic Settings (paths, JWT secret, model names — from .env)
│   ├── api/
│   │   ├── auth_router.py      ← /auth/login, /me
│   │   └── conversation_router.py
│   ├── auth/
│   │   ├── models.py           ← User, Role, RequestContext
│   │   ├── provider.py         ← AuthProvider (ABC) + JwtAuthProvider
│   │   ├── password.py         ← hashing helpers
│   │   └── dependency.py       ← FastAPI dependency: token → RequestContext
│   ├── conversations/
│   │   ├── models.py           ← Conversation, Message
│   │   ├── store.py            ← ConversationStore (ABC) + SqliteConversationStore
│   │   └── service.py          ← ConversationService (orchestrates store + agent runner)
│   ├── agents/
│   │   └── runner.py           ← AgentRunner: wraps existing utils.run_workflow()
│   └── static/                 ← login.html, chat.html, app.js, style.css
├── scripts/
│   └── seed_users.py           ← NEW seeding (users table, agent_id on policies)
├── utils.py                    ← untouched (Jayanth's refactor zone)
└── ...existing files
```

Layer rule: `api → auth/conversations → agents → utils.py`. Nothing imports upward.
`utils.py` is imported ONLY from `app/agents/runner.py` — one choke point, so when
Jayanth's refactor lands, exactly one file changes.

---

## 2. Domain contracts (class shapes)

```python
class Role(str, Enum):
    PROSPECT = "prospect"
    CUSTOMER = "customer"
    AGENT = "agent"
    EMPLOYEE = "employee"
    ADMIN = "admin"

class User(BaseModel):              # identity — auth concern only
    user_id: str
    email: EmailStr
    display_name: str
    role: Role
    customer_id: str | None         # link into existing customers table (customers only)
    agent_id: str | None            # link for agent/partner users

class RequestContext(BaseModel):    # built per-request by middleware; flows DOWN only
    user: User
    conversation_id: str | None
    correlation_id: str             # one id across API → agents → tools → Langfuse trace
    owned_policy_numbers: list[str] # resolved from DB at request time, never from client
```

`RequestContext` is the single carrier of "who is asking" — the future tool-layer
authorization checks read it. The client supplies only a JWT; everything else is
resolved server-side.

```python
class AuthProvider(ABC):            # swappable: JWT now, Cognito later
    @abstractmethod
    def authenticate(self, email: str, password: str) -> TokenPair: ...
    @abstractmethod
    def validate_token(self, token: str) -> User: ...
```

```python
class Message(BaseModel):
    message_id: str
    conversation_id: str
    sender: Literal["user", "assistant"]
    content: str
    escalated: bool = False         # drives the "connecting you to a human" UI state
    created_at: datetime

class Conversation(BaseModel):
    conversation_id: str
    user_id: str
    title: str                      # first user message, truncated
    created_at: datetime
    updated_at: datetime

class ConversationStore(ABC):       # swappable: SQLite now, Postgres/DynamoDB later
    @abstractmethod
    def create(self, user_id: str) -> Conversation: ...
    @abstractmethod
    def get(self, conversation_id: str, user_id: str) -> Conversation | None: ...
    @abstractmethod
    def list_for_user(self, user_id: str) -> list[Conversation]: ...
    @abstractmethod
    def append_message(self, message: Message) -> None: ...
    @abstractmethod
    def get_messages(self, conversation_id: str, user_id: str, limit: int = 50) -> list[Message]: ...
```

Every store read takes `user_id` — ownership is checked at the store, so there is no
code path that fetches a conversation without saying who is asking.

```python
class AgentRunner:                  # the ONLY consumer of utils.py
    def run(self, ctx: RequestContext, history: list[Message], user_input: str) -> AgentResult: ...

class AgentResult(BaseModel):
    answer: str
    escalated: bool
    trace_id: str | None
```

`run()` builds `GraphState` with `customer_id` / `conversation_history` from ctx +
history (fields that exist today but are never populated across turns), invokes the
compiled graph, and maps the final state back. Graph internals untouched.

---

## 3. API surface

```
POST /auth/login        {email, password}            → {access_token}
GET  /me                                              → {user, journey_summary}
POST /conversations                                   → Conversation
GET  /conversations                                   → [Conversation]
GET  /conversations/{id}/messages                     → [Message]
POST /conversations/{id}/messages   {content}         → Message (assistant reply)
GET  /health                                          → {status}
```

- Self-registration deferred; all accounts are seeded (agreed).
- No streaming in v1; response shape chosen so an SSE variant can be added later
  without changing the URL scheme.
- Errors: 401 bad/expired token, 403 not-your-conversation, 422 validation — typed
  error body `{code, message}`.

---

## 4. Data: seeding plan (scripts/seed_users.py)

New table `users` (user_id PK, email UNIQUE, password_hash, display_name, role,
customer_id NULL FK, agent_id NULL, created_at) + new column `policies.agent_id`
(NULL = direct policy, per CONTEXT.md). Conversations/messages tables created by the
store on first run.

Seed set (password printed on seed, e.g. all `demo123`):
- 2 customers linked to existing synthetic customers — one with an in-force policy,
  one with a claim in progress
- 1 prospect (no customer_id)
- 1 agent, assigned as agent_id on a few existing policies (their book of business)
- 1 employee (CSR), 1 admin

Runs against the existing `datasources/database/insurance_support.db`; does NOT
modify `generate_sample_data()` or any of `utils.py` (Jayanth's zone — he gets a
heads-up that schema extensions live in scripts/seed_users.py).

---

## 5. Frontend (app/static/)

- `login.html` — email/password → stores JWT in memory/sessionStorage → redirect
- `chat.html` — conversation list sidebar, message pane, input box,
  "thinking…" indicator, distinct style for `escalated: true` messages
- Plain HTML/JS, no build step; speaks ONLY the API above (React-swappable later)

---

## 6. Team touchpoints (flag before merge)

- **Krishna:** guardrails middleware slots into `app/main.py`'s middleware chain,
  after auth (so guardrails see RequestContext). Discussion point: input vs output
  guardrail placement.
- **Jayanth:** `app/agents/runner.py` is the seam his refactor targets; schema
  extensions live in the seed script, not utils.py. Discussion point: final shape of
  the conversation layer vs. his module split.

## 7. Deliberately NOT in this phase

Tool-layer authorization enforcement · Cognito/Google login · streaming · registration
· React · model routing · guardrails (Krishna) · utils.py changes (Jayanth).

## 8. Exit criterion

Two seeded customers log in separately in a browser, each asks "what is the premium
of my policy?", each receives the answer for *their own* policy without typing a
policy number, and follow-up questions work without repeating context.
