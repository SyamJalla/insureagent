# InsureAgent — Project Instructions

- **Domain vocabulary:** read [CONTEXT.md](CONTEXT.md) before any domain conversation;
  resolve ambiguous terms there first (user types, journey phases, auth vs. authz).
- **Decisions:** `docs/adr/` holds numbered decision records — read before proposing
  architectural changes; do not re-litigate recorded decisions. (Directory created with
  the first ADR.)
- **Overview & setup:** [README.md](README.md).
- **Environment:** conda env `genai` (Python 3.11) — see README.

Guiding rule for all agent/tool code: **LLMs reason; systems decide.** Authorization is
enforced in the tool layer, never by the LLM.
