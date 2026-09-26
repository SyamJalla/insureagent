from contextlib import contextmanager
from contextvars import ContextVar
from types import ModuleType, SimpleNamespace
import sys

from app.tracing import Tracer


class _Observation:
    def __init__(self):
        self.id = "observation-1"
        self.trace_id = "trace-test"
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class _Client:
    def __init__(self):
        self.observation = _Observation()
        self.entered = False
        self.observations = []
        self.scores = []

    def create_trace_id(self, seed):
        return f"trace-{seed}"

    def flush(self):
        pass

    def create_score(self, **kwargs):
        self.scores.append(kwargs)

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        self.entered = True
        self.observations.append(kwargs)
        trace_context = kwargs.get("trace_context") or {}
        if trace_context.get("trace_id"):
            self.observation.trace_id = trace_context["trace_id"]
        yield self.observation


def test_log_generation_updates_entered_langfuse_observation():
    tracer = Tracer.__new__(Tracer)
    tracer._client = _Client()

    tracer.log_generation(
        agent="policy_agent",
        model="test-model",
        tier="fast",
        messages=[{"role": "user", "content": "What is my premium?"}],
        output="Your premium is $100.",
        input_tokens=12,
        output_tokens=7,
    )

    assert tracer._client.entered
    assert tracer._client.observation.updates == [
        {"output": "Your premium is $100.", "usage_details": {"input": 12, "output": 7}}
    ]


def test_nested_request_trace_reuses_root_and_resets_for_next_turn(monkeypatch):
    langfuse = ModuleType("langfuse")

    @contextmanager
    def propagate_attributes(**_kwargs):
        yield

    langfuse.propagate_attributes = propagate_attributes
    monkeypatch.setitem(sys.modules, "langfuse", langfuse)

    tracer = Tracer.__new__(Tracer)
    tracer._client = _Client()
    tracer._request_trace_active = ContextVar("test_request_trace_active", default=False)
    ctx = SimpleNamespace(
        correlation_id="turn-1",
        conversation_id="conversation-1",
        session_id=None,
        user=SimpleNamespace(user_id="user-1", role=SimpleNamespace(value="customer")),
    )

    with tracer.request_trace(ctx) as root:
        assert root is tracer._client.observation
        with tracer.request_trace(ctx) as nested:
            assert nested is None
        assert len(tracer._client.observations) == 1

    with tracer.request_trace(ctx):
        assert len(tracer._client.observations) == 2


def test_turns_share_conversation_trace_and_parent(monkeypatch):
    langfuse = ModuleType("langfuse")

    @contextmanager
    def propagate_attributes(**_kwargs):
        yield

    langfuse.propagate_attributes = propagate_attributes
    monkeypatch.setitem(sys.modules, "langfuse", langfuse)

    tracer = Tracer.__new__(Tracer)
    tracer._client = _Client()
    tracer._request_trace_active = ContextVar("test_conversation_trace_active", default=False)

    for correlation_id in ("turn-1", "turn-2"):
        ctx = SimpleNamespace(
            correlation_id=correlation_id,
            conversation_id="conversation-1",
            session_id=None,
            user=SimpleNamespace(user_id="user-1", role=SimpleNamespace(value="customer")),
        )
        with tracer.request_trace(
            ctx,
            trace_id="trace-conversation-1",
            parent_span_id="observation-conversation-root",
        ):
            pass

    request_observations = tracer._client.observations
    assert len(request_observations) == 2
    assert [item["trace_context"] for item in request_observations] == [
        {
            "trace_id": "trace-conversation-1",
            "parent_span_id": "observation-conversation-root",
        },
        {
            "trace_id": "trace-conversation-1",
            "parent_span_id": "observation-conversation-root",
        },
    ]


def test_conversation_root_returns_persistable_trace_context(monkeypatch):
    langfuse = ModuleType("langfuse")

    @contextmanager
    def propagate_attributes(**_kwargs):
        yield

    langfuse.propagate_attributes = propagate_attributes
    monkeypatch.setitem(sys.modules, "langfuse", langfuse)

    tracer = Tracer.__new__(Tracer)
    tracer._client = _Client()
    ctx = SimpleNamespace(
        session_id="login-1",
        user=SimpleNamespace(user_id="user-1", role=SimpleNamespace(value="customer")),
    )

    trace_context = tracer.create_conversation_trace(ctx, "conversation-1")

    assert trace_context == ("trace-test", "observation-1")
    assert tracer._client.observations[0]["name"] == "conversation"
    assert "trace_context" not in tracer._client.observations[0]


def test_score_can_target_a_turn_observation():
    tracer = Tracer.__new__(Tracer)
    tracer._client = _Client()

    tracer.score(
        "trace-conversation-1",
        "user_feedback",
        1.0,
        idempotency_key="message-1",
        observation_id="turn-observation-1",
    )

    assert tracer._client.scores[0]["trace_id"] == "trace-conversation-1"
    assert tracer._client.scores[0]["observation_id"] == "turn-observation-1"