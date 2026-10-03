"""Offline tests for tier-specific prompts, providers, and routing."""
from contextlib import contextmanager
from importlib import import_module
from types import ModuleType, SimpleNamespace
import sys

import pytest
from pydantic import ValidationError

from app.agents.prompt_source import FilePromptSource
from app.agents.supervisor import supervisor_node
from app.api.conversation_router import SendMessageRequest
from app.llm import gateway, tier_router
from app.llm.models import LlmRequest, LlmResponse
from app.llm.provider import LayaClassifier, OpenAiProvider
from app.llm.tier_router import TierRouter


def _install_fake_laya(monkeypatch, router_class):
    laya_module = ModuleType("laya")
    laya_module.__path__ = []
    integrations_module = ModuleType("laya.integrations")
    integrations_module.__path__ = []
    langchain_module = ModuleType("laya.integrations.langchain")
    langchain_module.LayaRouter = router_class
    monkeypatch.setitem(sys.modules, "laya", laya_module)
    monkeypatch.setitem(sys.modules, "laya.integrations", integrations_module)
    monkeypatch.setitem(sys.modules, "laya.integrations.langchain", langchain_module)


def test_laya_example_uses_laya_router(monkeypatch):
    calls = {}

    class FakeLayaRouter:
        def __init__(self, *, criteria, instructions):
            calls["criteria"] = criteria
            calls["instructions"] = instructions
            self.last_decision = None

        def invoke(self, user_input):
            calls["user_input"] = user_input
            self.last_decision = {
                "answers": {"route": {"answer_confidence": 0.91}}
            }
            return "billing"

    _install_fake_laya(monkeypatch, FakeLayaRouter)
    laya_example = import_module("scripts.laya_example")
    router_config = {
        "question": {"prompt": "Choose a department."},
        "allowed_answers": {"billing": "Payments", "fallback": "Other"},
    }

    result = laya_example.classify("Pay my bill", router_config)

    assert result == {"decision": "billing", "confidence": 0.91}
    assert calls == {
        "criteria": router_config["allowed_answers"],
        "instructions": router_config["question"]["prompt"],
        "user_input": "Pay my bill",
    }


def test_tier3_router_prompt_selects_first_domain_for_multi_domain_requests():
    config = tier_router._load_router_config()

    assert "first actionable department" in config["question"]["prompt"]
    assert "spans multiple departments" in config["question"]["prompt"]
    assert "spanning multiple actionable domains" not in config["allowed_answers"]["fallback"]


def test_prompt_source_prefers_tier_override_and_falls_back_to_root(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    tier_dir = prompts / "tier2"
    tier_dir.mkdir(parents=True)
    (prompts / "billing_agent.yaml").write_text("prompt: root", encoding="utf-8")
    (tier_dir / "billing_agent.yaml").write_text("prompt: tier two", encoding="utf-8")
    (prompts / "claims_agent.yaml").write_text("prompt: root claims", encoding="utf-8")
    monkeypatch.setattr("app.agents.prompt_source._PROMPTS_DIR", prompts)

    source = FilePromptSource(tier=2)

    assert source.get("billing_agent") == "tier two"
    assert source.get("claims_agent") == "root claims"


def test_prompt_source_falls_back_to_tier1_canonical_prompt(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    tier1 = prompts / "tier1"
    tier1.mkdir(parents=True)
    (tier1 / "supervisor.yaml").write_text("prompt: tier one supervisor", encoding="utf-8")
    monkeypatch.setattr("app.agents.prompt_source._PROMPTS_DIR", prompts)

    assert FilePromptSource(tier=3).get("supervisor") == "tier one supervisor"
    assert FilePromptSource().get("supervisor") == "tier one supervisor"


def test_tier2_gateway_uses_separate_supervisor_and_specialist_models(monkeypatch):
    settings = SimpleNamespace(
        groq_api_key="configured",
        tier2_supervisor_model="groq-supervisor",
        tier2_specialist_model="groq-specialist",
    )
    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(
        gateway, "ModelRouter", lambda complexity_routing_enabled: object()
    )
    monkeypatch.setattr("app.llm.provider.GroqProvider", lambda _key: object())

    llm = gateway.build_gateway_for_tier(2)

    assert llm._models == {
        gateway.ModelTier.FAST: "groq-specialist",
        gateway.ModelTier.STANDARD: "groq-supervisor",
        gateway.ModelTier.REASONING: "groq-specialist",
    }


def test_tier1_gateway_uses_explicit_default_model(monkeypatch):
    settings = SimpleNamespace()
    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway, "build_default_gateway", lambda: "openai-tier-1")

    assert gateway.build_gateway_for_tier(1) == "openai-tier-1"


def test_tier1_gateway_assigns_models_by_agent_role(monkeypatch):
    settings = SimpleNamespace(
        openai_api_key="configured",
        tier1_specialist_model="gpt-5.1-mini",
        tier1_supervisor_model="gpt-4o-mini",
        complexity_routing_enabled=True,
    )
    monkeypatch.setattr(gateway, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway, "OpenAiProvider", lambda _key: object())
    monkeypatch.setattr(gateway, "ModelRouter", lambda enabled: enabled)

    llm = gateway.build_default_gateway()

    assert llm._models == {
        gateway.ModelTier.FAST: "gpt-5.1-mini",
        gateway.ModelTier.STANDARD: "gpt-4o-mini",
        gateway.ModelTier.REASONING: "gpt-5.1-mini",
    }


@pytest.mark.parametrize(
    ("model", "reject_temperature"),
    [("gpt-5.1-mini", True), ("future-model-id", True), ("gpt-4o-mini", False)],
)
def test_openai_provider_retries_without_unsupported_temperature(model, reject_temperature):
    class UnsupportedTemperatureError(Exception):
        param = "temperature"
        code = "unsupported_value"

    class FakeCompletions:
        calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if reject_temperature and "temperature" in kwargs:
                raise UnsupportedTemperatureError()
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
                usage=None,
            )

    completions = FakeCompletions()
    provider = OpenAiProvider.__new__(OpenAiProvider)
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    provider.complete(LlmRequest(agent="policy_agent", messages=[]), model)

    assert completions.calls[-1]["model"] == model
    if reject_temperature:
        assert len(completions.calls) == 2
        assert completions.calls[0]["temperature"] == 0.0
        assert "temperature" not in completions.calls[1]
    else:
        assert len(completions.calls) == 1
        assert completions.calls[0]["temperature"] == 0.0


def test_supervisor_uses_json_for_clarification_without_tools(monkeypatch):
    class FakeLlm:
        request = None

        def complete(self, request, correlation_id=None):
            self.request = request
            return LlmResponse(
                content='{"clarification_question":"What is your policy number?"}',
                model="test-model",
            )

    llm = FakeLlm()
    monkeypatch.setattr("app.agents.supervisor.load_prompt", lambda *_args, **_kwargs: "prompt")
    config = {
        "configurable": {
            "ctx": SimpleNamespace(correlation_id="test"),
            "llm": llm,
            "tools": object(),
            "tier": 2,
        }
    }

    result = supervisor_node({"user_input": "What does my policy cover?"}, config)

    assert llm.request.tools is None
    assert result["outcome"] == "clarification"
    assert result["clarification_question"] == "What is your policy number?"


def test_tier3_classification_selects_domain_agent(monkeypatch):
    settings = SimpleNamespace(
        active_tier=1,
        tier3_confidence_threshold=0.85,
        tier3_worker_model="worker-model",
        tier2_specialist_model="fallback-model",
    )

    classifier_created = []

    class FakeClassifier:
        def __init__(self):
            classifier_created.append(True)

        def classify(self, user_input, router_config):
            assert user_input == "What is my premium?"
            assert router_config["question"]["name"] == "insurance_request_classification"
            return {"decision": "policy", "confidence": 0.95}

    monkeypatch.setattr(tier_router, "get_settings", lambda: settings)
    monkeypatch.setattr("app.llm.provider.LayaClassifier", FakeClassifier)
    monkeypatch.setattr(
        tier_router,
        "_load_router_config",
        lambda: {"question": {"name": "insurance_request_classification"}},
    )

    assert TierRouter(tier=3).resolve("What is my premium?") == (
        "policy_agent",
        "worker-model",
    )
    assert classifier_created == [True]


def test_tier3_low_confidence_falls_back_to_tier2(monkeypatch):
    settings = SimpleNamespace(
        active_tier=3,
        tier3_confidence_threshold=0.85,
        tier3_worker_model="worker-model",
        tier2_specialist_model="fallback-model",
    )

    class FakeClassifier:
        def __init__(self, **_kwargs):
            pass

        def classify(self, _user_input, _router_config):
            return {"decision": "claims", "confidence": 0.4}

    monkeypatch.setattr(tier_router, "get_settings", lambda: settings)
    monkeypatch.setattr("app.llm.provider.LayaClassifier", FakeClassifier)
    monkeypatch.setattr(
        tier_router,
        "_load_router_config",
        lambda: {"question": {"name": "insurance_request_classification"}},
    )

    assert TierRouter(tier=3).resolve("track a claim") == (None, "fallback-model")


def test_tier3_uses_local_classifier_without_credentials(monkeypatch):
    settings = SimpleNamespace(
        active_tier=3,
        tier3_confidence_threshold=0.85,
        tier3_worker_model="worker-model",
        tier2_specialist_model="fallback-model",
    )

    class FakeClassifier:
        def __init__(self):
            pass

        def classify(self, _user_input, _router_config):
            return {"decision": "fallback", "confidence": 0.0}

    monkeypatch.setattr(tier_router, "get_settings", lambda: settings)
    monkeypatch.setattr("app.llm.provider.LayaClassifier", FakeClassifier)

    assert TierRouter(tier=3).resolve("track a claim") == (None, "fallback-model")


class _FakeSpan:
    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class _FakeTracer:
    def __init__(self):
        self.span = _FakeSpan()
        self.observations = []

    @contextmanager
    def observation(self, name, *, input=None, metadata=None):
        self.observations.append((name, input, metadata))
        yield self.span


def test_laya_classifier_uses_local_router_and_traces_result(monkeypatch):
    calls = {}

    class FakeLayaRouter:
        def __init__(self, *, criteria, instructions):
            calls["criteria"] = criteria
            calls["instructions"] = instructions
            calls["instances"] = calls.get("instances", 0) + 1
            self.last_decision = None

        def invoke(self, user_input):
            calls["user_input"] = user_input
            self.last_decision = {
                "answers": {"route": {"answer_confidence": 0.93}}
            }
            return "billing"

    tracer = _FakeTracer()
    _install_fake_laya(monkeypatch, FakeLayaRouter)
    monkeypatch.setattr("app.tracing.get_tracer", lambda: tracer)
    classifier = LayaClassifier()

    result = classifier.classify(
        "When is my bill due?",
        {
            "question": {
                "name": "insurance_request_classification",
                "prompt": "Which department should own this?",
            },
            "allowed_answers": {"billing": "Billing requests", "fallback": "Other"},
        },
    )

    assert result == {"decision": "billing", "confidence": 0.93}
    assert calls == {
        "criteria": {"billing": "Billing requests", "fallback": "Other"},
        "instructions": "Which department should own this?",
        "instances": 1,
        "user_input": "When is my bill due?",
    }
    assert tracer.observations == [
        (
            "laya:classification",
            {"character_count": len("When is my bill due?")},
            {"provider": "laya", "execution": "local"},
        )
    ]
    assert tracer.span.updates[0]["output"] == result


def test_llm_and_laya_calls_print_debug_logs(monkeypatch, capsys):
    class FakeProvider:
        def complete(self, request, model):
            return LlmResponse(content="ok", model=model, input_tokens=10, output_tokens=20)

        def moderate(self, text):
            return SimpleNamespace(flagged=False, scores={})

    class FakeRouter:
        def tier_for(self, _agent, _complexity):
            return gateway.ModelTier.FAST

    llm = gateway.LlmGateway(
        FakeProvider(),
        FakeRouter(),
        {
            gateway.ModelTier.FAST: "fast-model",
            gateway.ModelTier.STANDARD: "standard-model",
            gateway.ModelTier.REASONING: "reasoning-model",
        },
    )
    llm.complete(LlmRequest(agent="billing_agent", messages=[{"role": "user", "content": "hi"}]))
    llm_output = capsys.readouterr().out
    assert "llm" in llm_output.lower()
    assert "billing_agent" in llm_output
    assert "fast-model" in llm_output

    class FakeLayaRouter:
        last_decision = {"answers": {"route": {"answer_confidence": 0.93}}}

        def __init__(self, **_kwargs):
            pass

        def invoke(self, user_input):
            assert user_input == "When is my bill due?"
            return "billing"

    tracer = _FakeTracer()
    _install_fake_laya(monkeypatch, FakeLayaRouter)
    monkeypatch.setattr("app.tracing.get_tracer", lambda: tracer)
    classifier = LayaClassifier()
    classifier.classify(
        "When is my bill due?",
        {
            "question": {"name": "insurance_request_classification", "prompt": "Which department?"},
            "allowed_answers": {"billing": "Billing requests", "fallback": "Other"},
        },
    )
    laya_output = capsys.readouterr().out
    assert "laya" in laya_output.lower()
    assert "billing" in laya_output
    assert "0.93" in laya_output


def test_laya_classifier_returns_fallback_for_invalid_response(monkeypatch):
    class FakeLayaRouter:
        last_decision = {"answers": {"route": {"answer_confidence": 0.99}}}

        def __init__(self, **_kwargs):
            pass

        def invoke(self, _user_input):
            return "unknown"

    _install_fake_laya(monkeypatch, FakeLayaRouter)
    classifier = LayaClassifier()

    result = classifier.classify(
        "Hello",
        {
            "question": {
                "name": "insurance_request_classification",
                "prompt": "Classify the request",
            },
            "allowed_answers": {"fallback": "Other"},
        },
    )

    assert result == {"decision": "fallback", "confidence": 0.0}


def test_laya_classifier_returns_fallback_when_router_fails(monkeypatch):
    class FakeLayaRouter:
        last_decision = None

        def __init__(self, **_kwargs):
            pass

        def invoke(self, _user_input):
            raise RuntimeError("local inference failed")

    tracer = _FakeTracer()
    _install_fake_laya(monkeypatch, FakeLayaRouter)
    monkeypatch.setattr("app.tracing.get_tracer", lambda: tracer)
    classifier = LayaClassifier()

    result = classifier.classify(
        "Hello",
        {
            "question": {
                "name": "insurance_request_classification",
                "prompt": "Classify the request",
            },
            "allowed_answers": {"fallback": "Other"},
        },
    )

    assert result == {"decision": "fallback", "confidence": 0.0}
    assert tracer.span.updates[0]["level"] == "ERROR"


def test_supervisor_honors_server_selected_tier3_route():
    state = {
        "user_input": "What is my premium?",
        "tier3_agent_override": "policy_agent",
    }
    config = {
        "configurable": {
            "ctx": SimpleNamespace(correlation_id="test"),
            "llm": object(),
            "tools": object(),
        }
    }

    result = supervisor_node(state, config)

    assert result["next_agent"] == "policy_agent"
    assert result["task"] == "What is my premium?"
    assert result["tier3_agent_override"] is None


@pytest.mark.parametrize("tier", [0, 4, -1])
def test_request_rejects_tiers_outside_supported_range(tier):
    with pytest.raises(ValidationError):
        SendMessageRequest.model_validate({"content": "hello", "tier": tier})