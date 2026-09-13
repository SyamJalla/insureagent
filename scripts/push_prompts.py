"""Seed/refresh the prompts/*.yaml files into Langfuse Prompt Management.

Each YAML becomes a Langfuse prompt (same name, labeled 'production').
Re-running after editing a YAML creates a new version. Requires the Langfuse
stack to be up (docker compose up -d).

Run:  python scripts/push_prompts.py
"""
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tracing import get_tracer  # noqa: E402


def main() -> None:
    tracer = get_tracer()
    if not tracer.enabled:
        raise SystemExit("Langfuse is not reachable — start it first (docker compose up -d)")
    client = tracer._client
    for path in sorted(Path("prompts").glob("*.yaml")):
        name = path.stem
        text = yaml.safe_load(path.read_text(encoding="utf-8"))["prompt"]
        client.create_prompt(name=name, prompt=text, labels=["production"], type="text")
        print(f"pushed {name} ({len(text)} chars)")
    client.flush()
    print("done — set PROMPT_SOURCE=langfuse to serve prompts from Langfuse")


if __name__ == "__main__":
    main()
