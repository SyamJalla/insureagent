"""Tool gateway tests: RBAC, validation, and the one that matters most —
a customer cannot read another customer's data even when the LLM asks.
Runs against the seeded Postgres database."""
import psycopg2
import pytest

from app.auth.models import RequestContext, Role, User
from app.config import get_settings
from app.tools.gateway import ToolGateway


def _ctx(role: Role, customer_id=None, agent_id=None, policies=()) -> RequestContext:
    return RequestContext(
        user=User(
            user_id="TEST", email="t@t", display_name="T",
            role=role, customer_id=customer_id, agent_id=agent_id,
        ),
        correlation_id="test-corr",
        owned_policy_numbers=list(policies),
    )


@pytest.fixture(scope="module")
def foreign_policy():
    """A policy owned by someone other than CUST00023."""
    conn = psycopg2.connect(get_settings().app_db_url)
    cur = conn.cursor()
    cur.execute(
        "SELECT policy_number FROM policies WHERE customer_id != 'CUST00023' LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()
    return row[0]


gw = ToolGateway()


def test_customer_reads_own_policy():
    ctx = _ctx(Role.CUSTOMER, customer_id="CUST00023")
    result = gw.invoke(ctx, "get_policy_details", {"policy_number": "POL000001"})
    assert result.ok and result.data.get("policy_number") == "POL000001"


def test_customer_cannot_read_foreign_policy(foreign_policy):
    ctx = _ctx(Role.CUSTOMER, customer_id="CUST00023")
    result = gw.invoke(ctx, "get_policy_details", {"policy_number": foreign_policy})
    assert result.ok  # tool ran, but ownership scoping filtered the row
    assert "error" in result.data


def test_employee_reads_any_policy(foreign_policy):
    ctx = _ctx(Role.EMPLOYEE)
    result = gw.invoke(ctx, "get_policy_details", {"policy_number": foreign_policy})
    assert result.ok and "error" not in result.data


def test_prospect_denied_policy_tool():
    ctx = _ctx(Role.PROSPECT)
    result = gw.invoke(ctx, "get_policy_details", {"policy_number": "POL000001"})
    assert not result.ok and "may not use" in result.error


def test_prospect_allowed_faq():
    ctx = _ctx(Role.PROSPECT)
    specs = gw.specs_for(["search_faq", "get_policy_details"], ctx)
    assert [s["function"]["name"] for s in specs] == ["search_faq"]


def test_missing_required_arg_rejected():
    ctx = _ctx(Role.CUSTOMER, customer_id="CUST00023")
    result = gw.invoke(ctx, "get_policy_details", {})
    assert not result.ok and "missing required" in result.error


def test_unexpected_arg_rejected():
    ctx = _ctx(Role.CUSTOMER, customer_id="CUST00023")
    result = gw.invoke(
        ctx, "get_policy_details", {"policy_number": "POL000001", "customer_id": "CUST00999"}
    )
    assert not result.ok and "unexpected argument" in result.error


def test_agent_scoped_to_book(foreign_policy):
    conn = psycopg2.connect(get_settings().app_db_url)
    cur = conn.cursor()
    cur.execute("SELECT policy_number FROM policies WHERE agent_id='AGT001' LIMIT 1")
    in_book = cur.fetchone()[0]
    cur.execute("SELECT policy_number FROM policies WHERE agent_id IS NULL LIMIT 1")
    direct = cur.fetchone()[0]
    conn.close()
    ctx = _ctx(Role.AGENT, agent_id="AGT001")
    assert "error" not in gw.invoke(ctx, "get_policy_details", {"policy_number": in_book}).data
    assert "error" in gw.invoke(ctx, "get_policy_details", {"policy_number": direct}).data
