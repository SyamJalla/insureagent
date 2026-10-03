"""Classify one insurance request with the Laya decision model (Tier 3 router).

Run from the repository root with: python -m scripts.laya_example
"""
from pathlib import Path
from laya.integrations.langchain import LayaRouter
import yaml

from app.config import Settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALID_DECISIONS = frozenset({"billing", "policy", "claims", "fallback"})


def classify(user_input: str, router_config: dict) -> dict:
    """Classify user_input locally with Laya; return {decision, confidence}."""
    question      = router_config["question"]
    router = LayaRouter(
        criteria=router_config["allowed_answers"],
        instructions=question["prompt"],
    )
    decision = router.invoke(user_input)
    answer = (router.last_decision or {}).get("answers", {}).get("route", {})
    raw_confidence = answer.get("answer_confidence", answer.get("confidence", 0.0))
    confidence = float(raw_confidence or 0.0)

    if decision not in VALID_DECISIONS:
        decision, confidence = "fallback", 0.0

    return {"decision": decision, "confidence": confidence}


def main() -> None:
    settings = Settings(_env_file=PROJECT_ROOT / ".env")

    router_path = PROJECT_ROOT / "prompts" / "tier3" / "router.yaml"
    with router_path.open(encoding="utf-8") as f:
        router_config = yaml.safe_load(f)

    user_input = input("Insurance request: ").strip()
    if not user_input:
        raise SystemExit("Enter a non-empty insurance request.")

    result = classify(user_input, router_config)

    confidence = result["confidence"]
    threshold  = settings.tier3_confidence_threshold   # default 0.85

    print()
    print(f"  Decision   : {result['decision']}")
    print(f"  Confidence : {confidence:.3f}  (threshold={threshold})")
    print()

    # ── Tier 3 routing decision ───────────────────────────────────────────
    if confidence >= threshold:
        print(f"  ✅ Route to → [{result['decision'].upper()} agent]")
    else:
        print(f"  ⚠️  Confidence below {threshold} — route to → [FALLBACK / human triage]")


if __name__ == "__main__":
    main()