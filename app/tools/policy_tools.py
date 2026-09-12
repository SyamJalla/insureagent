"""Policy tools — the contract side: coverage, premium amount, term, vehicle.

Ownership scoping happens IN the SQL, from ctx — a customer's query is
filtered to their own customer_id regardless of what policy number the LLM
passed. Employees/admins are unrestricted; agents are scoped to their book.
"""
from app.auth.models import RequestContext, Role
from app.enterprise_db import fetch_all, fetch_one


def _scope(ctx: RequestContext) -> tuple[str, tuple]:
    """Extra WHERE clause + params enforcing ownership for the caller."""
    if ctx.user.role == Role.CUSTOMER:
        return " AND p.customer_id = %s", (ctx.user.customer_id,)
    if ctx.user.role == Role.AGENT:
        return " AND p.agent_id = %s", (ctx.user.agent_id,)
    return "", ()  # employee / admin


def get_policy_details(ctx: RequestContext, policy_number: str):
    clause, params = _scope(ctx)
    row = fetch_one(
        "SELECT p.*, c.first_name, c.last_name FROM policies p "
        "JOIN customers c ON p.customer_id = c.customer_id "
        "WHERE p.policy_number = %s" + clause,
        (policy_number, *params),
    )
    return row or {"error": "Policy not found or not accessible to this user"}


def get_auto_policy_details(ctx: RequestContext, policy_number: str):
    clause, params = _scope(ctx)
    row = fetch_one(
        "SELECT apd.*, p.status, p.premium_amount FROM auto_policy_details apd "
        "JOIN policies p ON apd.policy_number = p.policy_number "
        "WHERE apd.policy_number = %s" + clause,
        (policy_number, *params),
    )
    return row or {"error": "Auto policy details not found or not accessible"}


def list_my_policies(ctx: RequestContext):
    """Own policies (customer) / book of business (agent)."""
    clause, params = _scope(ctx)
    if not clause:
        return {"error": "Use a specific customer or policy lookup"}
    return fetch_all(
        "SELECT p.policy_number, p.policy_type, p.status, p.premium_amount, "
        "p.billing_frequency, p.start_date FROM policies p WHERE 1=1" + clause,
        params,
    )
