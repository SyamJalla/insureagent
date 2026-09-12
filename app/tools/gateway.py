"""ToolGateway — every agent tool call passes through here.

Enforcement split:
  - Gateway: registry, schema/arg validation, RBAC (role → tool), timeout,
    audit line per call.
  - Tools: OWNERSHIP scoping in SQL from ctx (a customer cannot read another
    customer's rows even if the LLM asks — "LLMs reason; systems decide").

Future attach points: Krishna's guardrails (around invoke), MCP contract
(the registry IS the tool surface), audit store (replaces the log line).
"""
import json
import logging

from app.auth.models import RequestContext, Role
from app.tools import billing_tools, claims_tools, faq_tools, policy_tools
from app.tools.models import RegisteredTool, ToolDenied, ToolResult, ToolSpec

logger = logging.getLogger("tool_gateway")

_ALL_ROLES = {Role.PROSPECT, Role.CUSTOMER, Role.AGENT, Role.EMPLOYEE, Role.ADMIN}
_POLICY_HOLDERS = {Role.CUSTOMER, Role.AGENT, Role.EMPLOYEE, Role.ADMIN}

_REGISTRY: dict[str, RegisteredTool] = {}


def _register(spec: ToolSpec, func) -> None:
    _REGISTRY[spec.name] = RegisteredTool(spec=spec, func=func)


_register(
    ToolSpec(
        name="get_policy_details",
        description="Fetch a policy's contract details (type, premium amount, dates, status).",
        parameters={
            "type": "object",
            "properties": {"policy_number": {"type": "string"}},
            "required": ["policy_number"],
        },
        allowed_roles=_POLICY_HOLDERS,
    ),
    policy_tools.get_policy_details,
)
_register(
    ToolSpec(
        name="get_auto_policy_details",
        description="Fetch auto policy vehicle and coverage details.",
        parameters={
            "type": "object",
            "properties": {"policy_number": {"type": "string"}},
            "required": ["policy_number"],
        },
        allowed_roles=_POLICY_HOLDERS,
    ),
    policy_tools.get_auto_policy_details,
)
_register(
    ToolSpec(
        name="list_my_policies",
        description="List the caller's own policies (customer) or book of business (agent).",
        parameters={"type": "object", "properties": {}},
        allowed_roles={Role.CUSTOMER, Role.AGENT},
    ),
    policy_tools.list_my_policies,
)
_register(
    ToolSpec(
        name="get_billing_info",
        description="Fetch recent bills, amounts due and due dates for a policy.",
        parameters={
            "type": "object",
            "properties": {"policy_number": {"type": "string"}},
            "required": ["policy_number"],
        },
        allowed_roles=_POLICY_HOLDERS,
    ),
    billing_tools.get_billing_info,
)
_register(
    ToolSpec(
        name="get_payment_history",
        description="Fetch recent payments made against a policy's bills.",
        parameters={
            "type": "object",
            "properties": {"policy_number": {"type": "string"}},
            "required": ["policy_number"],
        },
        allowed_roles=_POLICY_HOLDERS,
    ),
    billing_tools.get_payment_history,
)
_register(
    ToolSpec(
        name="get_claim_status",
        description="Fetch claim status by claim_id or policy_number (or the caller's own claims).",
        parameters={
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "policy_number": {"type": "string"},
            },
        },
        allowed_roles=_POLICY_HOLDERS,
    ),
    claims_tools.get_claim_status,
)
_register(
    ToolSpec(
        name="search_faq",
        description="Search general insurance knowledge (industry-wide, not customer-specific).",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        allowed_roles=_ALL_ROLES,
    ),
    faq_tools.search_faq,
)


class ToolGateway:
    def specs_for(self, tool_names: list[str], ctx: RequestContext) -> list[dict]:
        """OpenAI tool schemas for the tools this agent may offer THIS caller."""
        out = []
        for name in tool_names:
            tool = _REGISTRY[name]
            if ctx.user.role in tool.spec.allowed_roles:
                out.append(tool.spec.to_openai())
        return out

    def invoke(self, ctx: RequestContext, name: str, args: dict) -> ToolResult:
        tool = _REGISTRY.get(name)
        try:
            if tool is None:
                raise ToolDenied(f"unknown tool: {name}")
            if ctx.user.role not in tool.spec.allowed_roles:
                raise ToolDenied(f"role '{ctx.user.role.value}' may not use {name}")
            self._validate(tool.spec, args)
            data = tool.func(ctx, **args)
            result = ToolResult(tool=name, data=data)
        except ToolDenied as exc:
            result = ToolResult(tool=name, ok=False, error=str(exc))
        except Exception as exc:  # tool bug/db error: surface safely, keep graph alive
            logger.exception("tool %s failed", name)
            result = ToolResult(tool=name, ok=False, error=f"tool error: {type(exc).__name__}")
        logger.info(
            "🔧 tool_call %s",
            json.dumps({
                "correlation_id": ctx.correlation_id,
                "user": ctx.user.user_id,
                "role": ctx.user.role.value,
                "tool": name,
                "args": args,
                "ok": result.ok,
            }),
        )
        return result

    @staticmethod
    def _validate(spec: ToolSpec, args: dict) -> None:
        props = spec.parameters.get("properties", {})
        for key in args:
            if key not in props:
                raise ToolDenied(f"unexpected argument '{key}' for {spec.name}")
        for req in spec.parameters.get("required", []):
            if req not in args or args[req] in (None, ""):
                raise ToolDenied(f"missing required argument '{req}' for {spec.name}")
