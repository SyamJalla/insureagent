# InsureAgent — Project Instructions

- **Overview, setup, and domain model** (user types, journey phases, auth vs. authz):
  [README.md](README.md) — read the Domain model section before any domain conversation.
- **Designs & decisions:** `docs/design/` (walkthroughs), `docs/architecture/`
  (reference architecture + review). Read before proposing architectural changes.
- **Environment:** conda env `genai` (Python 3.11) — see README.

Guiding rule for all agent/tool code: **LLMs reason; systems decide.** Authorization is
enforced in the tool layer, never by the LLM.
