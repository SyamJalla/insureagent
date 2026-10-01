"""Offline tests for tier-specific prompts, providers, and routing."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agents.prompt_source import FilePromptSource
from app.agents.supervisor import supervisor_node
from app.api.conversation_router import SendMessageRequest
from app.llm import gateway, tier_router
from app.llm.models import LlmResponse
from app.llm.tier_router import TierRouter


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
        laya_api_key="configured",
        laya_base_url="https://laya.example",
        tier3_router_model="router-model",
    )

    class FakeClassifier:
        def __init__(self, **_kwargs):
            pass

        def classify(self, user_input, router_prompt):
            assert user_input == "What is my premium?"
            assert router_prompt == "router prompt"
            return {"decision": "policy", "confidence": 0.95}

    monkeypatch.setattr(tier_router, "get_settings", lambda: settings)
    monkeypatch.setattr("app.llm.provider.LayaClassifier", FakeClassifier)
    monkeypatch.setattr(
        "app.agents.prompt_source.get_prompt_source",
        lambda **_kwargs: SimpleNamespace(get=lambda _name: "router prompt"),
    )

    assert TierRouter(tier=3).resolve("What is my premium?") == (
        "policy_agent",
        "worker-model",
    )


def test_tier3_low_confidence_falls_back_to_tier2(monkeypatch):
    settings = SimpleNamespace(
        active_tier=3,
        tier3_confidence_threshold=0.85,
        tier3_worker_model="worker-model",
        tier2_specialist_model="fallback-model",
        laya_api_key="configured",
        laya_base_url="https://laya.example",
        tier3_router_model="router-model",
    )

    class FakeClassifier:
        def __init__(self, **_kwargs):
            pass

        def classify(self, _user_input, _router_prompt):
            return {"decision": "claims", "confidence": 0.4}

    monkeypatch.setattr(tier_router, "get_settings", lambda: settings)
    monkeypatch.setattr("app.llm.provider.LayaClassifier", FakeClassifier)
    monkeypatch.setattr(
        "app.agents.prompt_source.get_prompt_source",
        lambda **_kwargs: SimpleNamespace(get=lambda _name: "router prompt"),
    )

    assert TierRouter(tier=3).resolve("track a claim") == (None, "fallback-model")


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