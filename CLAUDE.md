# InsureAgent — Project Instructions

- **Overview, setup, and domain model** (user types, journey phases, auth vs. authz):
  [README.md](README.md) — read the Domain model section before any domain conversation.
- **Designs & decisions:** module docstrings are the design record;
  `docs/architecture/` holds the reference architecture diagram. Past design
  walkthroughs live in git history (`git log -- docs/`).
- **Environment:** conda env `genai` (Python 3.11) — see README.

Guiding rule for all agent/tool code: **LLMs reason; systems decide.** Authorization is
enforced in the tool layer, never by the LLM.
