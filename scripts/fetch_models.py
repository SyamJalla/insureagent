"""Download the local ML models at INSTALL time, not on a user's first message.

pip carries what pip can (the spaCy model is a wheel in requirements.txt);
this script fetches the two artifacts that are model files, not Python
packages, into their standard caches:

  * the prompt-injection classifier (~700 MB ONNX, HuggingFace hub cache)
  * Chroma's default embedding model  (~80 MB ONNX MiniLM, Chroma cache)

Idempotent — already-cached models return instantly. Needs no .env.
The runtime keeps its lazy-load fallback, so skipping this script only
costs a slow first use, never a failure.

Run:  python scripts/fetch_models.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def fetch_injection_model() -> None:
    print("[1/2] prompt-injection classifier (~700 MB on first run)...")
    from app.guardrails.checks.injection_classifier import _session

    if _session() is None:
        print("      FAILED — check network access to huggingface.co and re-run")
        sys.exit(1)
    print("      ok (downloaded or cached, model loads)")


def fetch_embedding_model() -> None:
    print("[2/2] embedding model MiniLM (~80 MB on first run)...")
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    DefaultEmbeddingFunction()(["warm-up"])
    print("      ok (downloaded or cached, embeds)")


if __name__ == "__main__":
    fetch_injection_model()
    fetch_embedding_model()
    print("all models ready — first chat message will not download anything")
