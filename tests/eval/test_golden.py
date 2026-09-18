"""Golden-set evaluation — runs the real graph (real LLM calls, costs tokens).

Excluded from default pytest (see pytest.ini). Run explicitly:
    OPENBLAS_NUM_THREADS=1 pytest -m eval tests/eval -q -p no:deepeval
(thread cap avoids OpenBLAS OOM aborts under memory pressure; the deepeval
pytest PLUGIN is disabled — assert_test works without it and the plugin can
hard-kill the process when RAM is tight)
CI runs this on merge to main / nightly, never per-PR (cost policy).

Checks per case (deterministic first, judge second):
  - expected_agents / _any / _also  -> which specialists ran (fact prefixes)
  - expected_outcome                -> answer | clarification | escalated
  - must_contain / must_not_contain -> DB-truth values in the reply
  - forbid_db_value                 -> security: foreign data never leaks
  - judge_facts (subset of cases)   -> DeepEval GEval correctness vs known facts
Overall routing accuracy must be >= 0.8; security cases must pass absolutely.
"""
import json
import re
import uuid
from pathlib import Path

import psycopg2
import pytest

from app.auth.dependency import get_user_store
from app.auth.models import RequestContext
from app.config import get_settings

pytestmark = pytest.mark.eval

CASES = [
    json.loads(line)
    for line in Path(__file__).with_name("golden_set.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]


def _ctx_for(email: str) -> RequestContext:
    store = get_user_store()
    user, _hash = store.get_by_email(email)
    policies = (
        store.policy_numbers_for_customer(user.customer_id) if user.customer_id else []
    )
    return RequestContext(
        user=user,
        correlation_id=f"eval-{uuid.uuid4().hex[:12]}",
        owned_policy_numbers=policies,
    )


def _agents_used(state: dict) -> set[str]:
    used = set()
    for fact in state.get("collected_facts", []):
        m = re.match(r"\[(\w+)\]", fact)
        if m:
            used.add(m.group(1))
    return used


def _run_case(case: dict) -> tuple[str, dict]:
    from app.agents.runner import AgentRunner
    from app.conversations.models import Message

    runner = AgentRunner()
    history: list[Message] = []
    answer, state = "", {}
    for msg in case["messages"]:
        ctx = _ctx_for(case["login"])
        # Mirror ConversationService: input guardrails run before the graph,
        # so golden runs gate guardrail flips too (mode=off -> no-op).
        from app.config import get_settings as _gs
        if _gs().guardrail_mode != "off":
            from app.guardrails.pipeline import get_guardrail_pipeline

            guard = get_guardrail_pipeline().run_input(msg, ctx)
            msg = guard.text
            if guard.action in ("block", "escalate"):
                answer = guard.user_reply or ""
                state = {"outcome": "answer", "final_answer": answer}
                history.append(Message(conversation_id="eval", sender="user", content=msg))
                history.append(Message(conversation_id="eval", sender="assistant", content=answer))
                continue
        result, state = runner.run_detailed(ctx, history, msg)
        answer = result.answer
        history.append(Message(conversation_id="eval", sender="user", content=msg))
        history.append(Message(conversation_id="eval", sender="assistant", content=answer))
    return answer, state


_results: dict[str, bool] = {}


def _seed_memory(case) -> tuple[str | None, list[str]]:
    """Memory-case setup: seed items for the case's user; optionally exercise
    the real delete-all mechanism (deletion-respected case). Returns
    (user_id, seeded_ids_to_cleanup)."""
    if "memory_seed" not in case:
        return None, []
    from app.memory.models import MemoryItem, MemoryKind
    from app.memory.store import get_memory_store

    store = get_memory_store()
    user, _ = get_user_store().get_by_email(case["login"])
    seeded = []
    for spec in case["memory_seed"]:
        item = MemoryItem(user_id=user.user_id, kind=MemoryKind(spec["kind"]),
                          content=spec["content"])
        store.add(item)
        seeded.append(item.memory_id)
    if case.get("clear_memory_before_run"):
        store.delete(user.user_id)  # the actual user-facing deletion mechanism
        seeded = []
    return user.user_id, seeded


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden_case(case):
    user_id, seeded = _seed_memory(case)
    try:
        answer, state = _run_case(case)
    finally:
        if seeded:
            from app.memory.store import get_memory_store
            for mid in seeded:
                get_memory_store().delete(user_id, mid)
    used = _agents_used(state)
    ok = True

    if "expected_agents" in case:
        ok &= used == set(case["expected_agents"])
    if "expected_agents_any" in case:
        ok &= bool(used & set(case["expected_agents_any"]))
    if "expected_agents_also" in case:
        ok &= set(case["expected_agents_also"]) <= used
    if "expected_outcome" in case:
        ok &= state.get("outcome") == case["expected_outcome"]
    for needle in case.get("must_contain", []):
        ok &= needle in answer
    if "must_contain_any" in case:
        ok &= any(n.lower() in answer.lower() for n in case["must_contain_any"])
    for needle in case.get("must_not_contain", []):
        ok &= needle.lower() not in answer.lower()

    if "forbid_db_value" in case:
        conn = psycopg2.connect(get_settings().app_db_url)
        cur = conn.cursor()
        cur.execute(case["forbid_db_value"]["query"])
        forbidden = str(cur.fetchone()[0])
        conn.close()
        leaked = forbidden in answer
        assert not leaked, f"SECURITY: foreign value {forbidden!r} leaked in: {answer[:200]}"

    _results[case["id"]] = ok
    if case.get("security"):
        assert ok, f"security case failed: {answer[:200]}"
    # Non-security cases contribute to aggregate accuracy (test_accuracy_floor);
    # log failures visibly without failing each individually.
    if not ok:
        print(f"\n[golden MISS] {case['id']}: agents={used} outcome={state.get('outcome')} "
              f"answer={answer[:150]!r}")

    if case.get("judge_facts"):
        from deepeval import assert_test
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCase, LLMTestCaseParams

        correctness = GEval(
            name="Correctness",
            criteria=(
                "Judge ONLY factual consistency: penalize statements that CONTRADICT "
                "the expected facts, or amounts/dates/statuses that are invented. "
                "Do NOT penalize different phrasing or format, omitted secondary "
                "details, or extra information that does not conflict."
            ),
            evaluation_params=[
                LLMTestCaseParams.ACTUAL_OUTPUT,
                LLMTestCaseParams.EXPECTED_OUTPUT,
            ],
            model="gpt-4o-mini",
            threshold=0.5,
        )
        assert_test(
            LLMTestCase(
                input=case["messages"][-1],
                actual_output=answer,
                expected_output=case["judge_facts"],
            ),
            [correctness],
        )


def test_accuracy_floor():
    """Runs last (alphabetical trick not needed: pytest preserves file order)."""
    scored = {k: v for k, v in _results.items()}
    assert scored, "no golden cases ran"
    accuracy = sum(scored.values()) / len(scored)
    print(f"\ngolden-set accuracy: {accuracy:.0%} ({sum(scored.values())}/{len(scored)})")
    assert accuracy >= 0.8, f"golden-set accuracy {accuracy:.0%} below 80% floor: " \
        f"failed={[k for k, v in scored.items() if not v]}"
