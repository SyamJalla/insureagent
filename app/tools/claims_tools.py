"""Claims tools — claim status and history."""
from app.auth.models import RequestContext
from app.enterprise_db import fetch_all
from app.tools.policy_tools import _scope


def get_claim_status(
    ctx: RequestContext,
    claim_id: str | None = None,
    policy_number: str | None = None,
):
    clause, params = _scope(ctx)
    base = (
        "SELECT cl.*, p.policy_type FROM claims cl "
        "JOIN policies p ON cl.policy_number = p.policy_number WHERE "
    )
    if claim_id:
        rows = fetch_all(base + "cl.claim_id = %s" + clause, (claim_id, *params))
    elif policy_number:
        rows = fetch_all(
            base + "cl.policy_number = %s" + clause + " ORDER BY cl.claim_date DESC LIMIT 3",
            (policy_number, *params),
        )
    else:
        # No identifier given: fall back to the caller's own scope entirely
        if not clause:
            return {"error": "claim_id or policy_number required"}
        rows = fetch_all(
            base + "1=1" + clause + " ORDER BY cl.claim_date DESC LIMIT 5", params
        )
    return rows or {"error": "No claims found or not accessible"}
