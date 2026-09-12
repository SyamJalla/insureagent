"""Billing tools — money movement: bills, due dates, payments."""
from app.auth.models import RequestContext
from app.enterprise_db import fetch_all
from app.tools.policy_tools import _scope


def get_billing_info(ctx: RequestContext, policy_number: str):
    clause, params = _scope(ctx)
    rows = fetch_all(
        "SELECT b.*, p.billing_frequency, p.premium_amount FROM billing b "
        "JOIN policies p ON b.policy_number = p.policy_number "
        "WHERE b.policy_number = %s" + clause +
        " ORDER BY b.due_date DESC LIMIT 5",
        (policy_number, *params),
    )
    return rows or {"error": "No billing records found or not accessible"}


def get_payment_history(ctx: RequestContext, policy_number: str):
    clause, params = _scope(ctx)
    rows = fetch_all(
        "SELECT pay.* FROM payments pay "
        "JOIN billing b ON pay.bill_id = b.bill_id "
        "JOIN policies p ON b.policy_number = p.policy_number "
        "WHERE b.policy_number = %s" + clause +
        " ORDER BY pay.payment_date DESC LIMIT 10",
        (policy_number, *params),
    )
    return rows or {"error": "No payment history found or not accessible"}
