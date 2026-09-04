# CONTEXT.md — Domain Vocabulary

Read this before any domain conversation. When a term is ambiguous, resolve it here first.
This describes an **imaginary insurance company** used to build and test the platform —
all data is synthetic; nothing here refers to a real insurer or real customers.

---

## Core distinction: person status vs. policy status

- A **person** has exactly one identity and one account status (user type below).
- A **policy** has its own lifecycle phase (journey phases below).
- One person can hold many policies in different phases at once (e.g., an in-force
  auto policy, a lapsed health policy, and a pending life application).
- "Customer journey phase" therefore always means **the phase of a specific policy or
  application**, never a property of the person — except for pre-application phases
  (Visitor / Lead / Quote), which attach to the person because no policy exists yet.

---

## User types (roles)

| Role | Is | Is NOT |
| --- | --- | --- |
| **Visitor** | Anonymous, unauthenticated. Can ask general product/FAQ questions. | A lead — we know nothing about them; nothing is persisted against an identity. |
| **Prospect** | Registered identity with no issued policy. May have quotes or in-progress applications. | A customer — has no policy; sees no policy/billing/claims data. |
| **Customer** | Registered identity holding at least one policy (any phase from application onward). | Automatically entitled to all data — access is always scoped to policies they own. |
| **Agent / Partner** | External distributor acting on behalf of their **book of business** (the set of customers they service). | An employee. Can access only their own book, never all customers. |
| **Employee (CSR)** | Internal customer-service staff. Receives human escalations; broad read access, actions audited. | An admin — cannot manage users or configuration. |
| **Admin** | Internal role for user management, configuration, and oversight. | A day-to-day servicing role. |
| **System / AI agents** | The LangGraph agents. They act **on behalf of** the requesting user and carry that user's authority into every tool call. | An independent principal — an AI agent has no access of its own; the tool layer checks the human user's role and attributes on every call. |

---

## Customer journey phases

Phases are per policy/application unless marked (person). Claims is modeled as a
phase, not a separate sub-journey.

### Pre-customer (person-level)
1. **Visitor** — anonymous browsing, general questions.
2. **Lead** — shared contact details; may have a rough premium indication.
3. **Quote generated** — holds a concrete quote; has not applied.

### Onboarding (per application)
4. **Application started / filled** — proposal form in progress or submitted.
5. **KYC done** — identity/address verification complete.
6. **Medical / risk assessment** — (life/health) medicals scheduled or completed.
7. **Underwriting done** — outcome: accepted, accepted with loading, postponed, or declined.
8. **Initial payment done** — first premium paid.
9. **Policy issued** — active, within the free-look period (regulatory window allowing
   cancellation with full refund).

### Active servicing (per policy)
10. **In-force** — steady state: endorsements, premium payments, statements.
11. **Claim in progress** — a claim is open on the policy
    (intimated → documents → assessment → approved/rejected → settled).
12. **Renewal due / grace period** — renewal payment window open before lapse.

### Terminal states (per policy)
13. **Lapsed** — grace period missed; may be revivable.
14. **Cancelled / surrendered** — terminated by customer choice.
15. **Matured / expired** — term completed normally.
16. **Win-back** — former customer with no active policy; treated like a prospect
    with history.

---

## Authentication vs. authorization

These words are used precisely in this project:

- **Authentication** = "who are you?" — **one identity, one login flow for every role.**
  Whether someone is a customer is NOT an authentication concern (customer status
  changes; identity does not).
- **Authorization** = "what can you do?" — two layers:
  - **Role (RBAC):** which capabilities exist for this user type
    (an agent can list their book; a customer cannot list anyone).
  - **Attributes (ABAC):** what those capabilities apply to — policy ownership,
    journey phase, policy status (a customer in "application started" has no billing
    to query; claims data is only discussable with the policy owner).
- Authorization is **enforced in the tool layer**, never delegated to the LLM.
  Guiding rule: **LLMs reason; systems decide.**

---

## Policy–agent association & commissions

- Every policy carries a **servicing agent** reference: the agent/partner who sold or
  services it. Policies sold directly by the company have no agent (**direct policies**).
- **Commission payouts** attach to the policy–agent association: the agent earns
  commissions on issued policies in their book (new business and renewals). Commission
  data is visible to the owning agent, employees, and admins — never to the customer
  through the AI assistant.
- A policy whose agent has left/been terminated is an **orphan policy** until reassigned;
  it behaves like a direct policy for access purposes in the meantime.

---

## Other terms

- **Book of business** — the set of customers an agent/partner services, **derived from
  the policies associated with that agent** (not maintained as a separate list); the
  boundary of that agent's data access and the basis of their commission payouts.
- **Journey phase as AI context** — the requesting user's role and relevant policy
  phases are passed to the supervisor agent as routing/response context (e.g., a user
  in "renewal due" gets renewal-aware answers). Context informs the AI; it never
  grants access.
- **Free-look period** — post-issuance window in which the customer may cancel for a
  full refund.
- **Grace period** — window after a missed renewal premium during which the policy
  stays in force.
- **Escalation** — handoff from the AI to a human CSR (Employee role), triggered by
  low confidence, explicit customer request, or repeated failure.
