"""The four domain agents. Boundary: policy = the contract; billing = money
movement; claims = claim lifecycle; general help = industry-general knowledge.
"""
import json

from app.agents.base import SpecialistAgent
from app.auth.models import RequestContext


class PolicyAgent(SpecialistAgent):
    name = "policy_agent"
    prompt_name = "policy_agent"
    tool_names = ["get_policy_details", "get_auto_policy_details", "list_my_policies"]

    def extra_fields(self, state, ctx: RequestContext, tools) -> dict:
        return {
            "customer_id": ctx.user.customer_id or "",
            "policy_number": ", ".join(ctx.owned_policy_numbers[:10]),
        }


class BillingAgent(SpecialistAgent):
    name = "billing_agent"
    prompt_name = "billing_agent"
    tool_names = ["get_billing_info", "get_payment_history", "get_policy_details"]


class ClaimsAgent(SpecialistAgent):
    name = "claims_agent"
    prompt_name = "claims_agent"
    tool_names = ["get_claim_status"]

    def extra_fields(self, state, ctx: RequestContext, tools) -> dict:
        return {
            "claim_id": "",
            "policy_number": ", ".join(ctx.owned_policy_numbers[:10]),
        }


class GeneralHelpAgent(SpecialistAgent):
    name = "general_help_agent"
    prompt_name = "general_help_agent"
    tool_names = []  # retrieval is deterministic, not an LLM decision

    def extra_fields(self, state, ctx: RequestContext, tools) -> dict:
        query = state.get("task") or state.get("user_input", "")
        result = tools.invoke(ctx, "search_faq", {"query": query})
        context = result.data if result.ok else []
        return {"faq_context": json.dumps(context, default=str)}
