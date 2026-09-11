import os
import sqlite3
from typing import Dict, Any, List
from core.config import tracer

# Resolve path to SQLite DB relative to backend/ regardless of launch CWD
_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'datasources', 'database', 'insurance_support.db'
)

def get_policy_details(logger, policy_number):

    with tracer.start_as_current_span(
        "sqlite_get_policy_details"
    ) as span:

        conn = None

        try:

            span.set_attribute(
                "policy_number",
                policy_number
            )

            logger.info(
                f"🔍 Fetching policy details for: {policy_number}"
            )

            conn = sqlite3.connect(_DB_PATH)

            cursor = conn.cursor()

            span.set_attribute("db.system", "sqlite")
            span.set_attribute("db.operation", "SELECT")
            span.set_attribute("db.table", "policies")

            cursor.execute(
                """
                SELECT p.*, c.first_name, c.last_name
                FROM policies p
                JOIN customers c
                    ON p.customer_id = c.customer_id
                WHERE p.policy_number = ?
                """,
                (policy_number,)
            )

            result = cursor.fetchone()

            if result:

                span.set_attribute(
                    "lookup_status",
                    "found"
                )

                logger.info(
                    f"✅ Policy found: {policy_number}"
                )

                columns = [
                    desc[0]
                    for desc in cursor.description
                ]

                response = dict(zip(columns, result))

                span.set_attribute(
                    "policy_type",
                    str(response.get("policy_type", ""))
                )

                span.set_attribute(
                    "policy_status",
                    str(response.get("status", ""))
                )

                return response

            span.set_attribute(
                "lookup_status",
                "not_found"
            )

            logger.warning(
                f"❌ Policy not found: {policy_number}"
            )

            return {
                "error": "Policy not found"
            }

        except Exception as e:

            span.record_exception(e)

            span.set_attribute(
                "lookup_status",
                "failed"
            )
            span.set_attribute(
                "error.message",
                str(e)
            )

            logger.exception(
                f"Error retrieving policy {policy_number}"
            )

            raise

        finally:

            if conn:
                conn.close()

def get_claim_status(
    logger,
    claim_id: str = None,
    policy_number: str = None
) -> Dict[str, Any]:

    with tracer.start_as_current_span(
        "sqlite_get_claim_status"
    ) as span:

        conn = None

        try:

            span.set_attribute(
                "db.system",
                "sqlite"
            )

            span.set_attribute(
                "db.operation",
                "SELECT"
            )

            span.set_attribute(
                "db.table",
                "claims"
            )

            if claim_id:
                span.set_attribute(
                    "claim_id",
                    claim_id
                )

            if policy_number:
                span.set_attribute(
                    "policy_number",
                    policy_number
                )

            logger.info(
                f"🔍 Fetching claim status - Claim ID: {claim_id}, Policy: {policy_number}"
            )

            conn = sqlite3.connect(_DB_PATH)

            cursor = conn.cursor()

            if claim_id:

                cursor.execute(
                    """
                    SELECT c.*, p.policy_type
                    FROM claims c
                    JOIN policies p
                        ON c.policy_number = p.policy_number
                    WHERE c.claim_id = ?
                    """,
                    (claim_id,)
                )

            elif policy_number:

                cursor.execute(
                    """
                    SELECT c.*, p.policy_type
                    FROM claims c
                    JOIN policies p
                        ON c.policy_number = p.policy_number
                    WHERE c.policy_number = ?
                    ORDER BY c.claim_date DESC
                    LIMIT 3
                    """,
                    (policy_number,)
                )

            else:

                span.set_attribute(
                    "lookup_status",
                    "invalid_request"
                )

                return {
                    "error": "Either claim_id or policy_number is required"
                }

            results = cursor.fetchall()

            if results:

                span.set_attribute(
                    "lookup_status",
                    "found"
                )

                span.set_attribute(
                    "claim_count",
                    len(results)
                )

                logger.info(
                    f"✅ Found {len(results)} claim(s)"
                )

                columns = [
                    desc[0]
                    for desc in cursor.description
                ]

                return [
                    dict(zip(columns, row))
                    for row in results
                ]

            span.set_attribute(
                "lookup_status",
                "not_found"
            )

            logger.warning(
                "❌ No claims found"
            )

            return {
                "error": "Claim not found"
            }

        except Exception as e:

            span.record_exception(e)

            span.set_attribute(
                "lookup_status",
                "failed"
            )

            span.set_attribute(
                "error.message",
                str(e)
            )

            logger.exception(
                f"Error retrieving claim status. Claim ID={claim_id}, Policy={policy_number}"
            )

            raise

        finally:

            if conn:
                conn.close()

def get_billing_info(
    logger,
    policy_number: str = None,
    customer_id: str = None
) -> Dict[str, Any]:

    with tracer.start_as_current_span(
        "sqlite_get_billing_info"
    ) as span:

        conn = None

        try:

            span.set_attribute(
                "db.system",
                "sqlite"
            )

            span.set_attribute(
                "db.operation",
                "SELECT"
            )

            span.set_attribute(
                "db.table",
                "billing"
            )

            if policy_number:
                span.set_attribute(
                    "policy_number",
                    policy_number
                )

            if customer_id:
                span.set_attribute(
                    "customer_id",
                    customer_id
                )

            logger.info(
                f"🔍 Fetching billing info - Policy: {policy_number}, Customer: {customer_id}"
            )

            conn = sqlite3.connect(_DB_PATH)

            cursor = conn.cursor()

            if policy_number:

                cursor.execute(
                    """
                    SELECT b.*, p.premium_amount, p.billing_frequency
                    FROM billing b
                    JOIN policies p
                        ON b.policy_number = p.policy_number
                    WHERE b.policy_number = ?
                    AND b.status = 'pending'
                    ORDER BY b.due_date DESC
                    LIMIT 1
                    """,
                    (policy_number,)
                )

            elif customer_id:

                cursor.execute(
                    """
                    SELECT b.*, p.premium_amount, p.billing_frequency
                    FROM billing b
                    JOIN policies p
                        ON b.policy_number = p.policy_number
                    WHERE p.customer_id = ?
                    AND b.status = 'pending'
                    ORDER BY b.due_date DESC
                    LIMIT 1
                    """,
                    (customer_id,)
                )

            else:

                span.set_attribute(
                    "lookup_status",
                    "invalid_request"
                )

                return {
                    "error": "Either policy_number or customer_id is required"
                }

            result = cursor.fetchone()

            if result:

                span.set_attribute(
                    "lookup_status",
                    "found"
                )

                logger.info(
                    "✅ Billing info found"
                )

                columns = [
                    desc[0]
                    for desc in cursor.description
                ]

                response = dict(
                    zip(columns, result)
                )

                span.set_attribute(
                    "billing_status",
                    str(response.get("status", ""))
                )

                return response

            span.set_attribute(
                "lookup_status",
                "not_found"
            )

            logger.warning(
                "❌ Billing info not found"
            )

            return {
                "error": "Billing information not found"
            }

        except Exception as e:

            span.record_exception(e)

            span.set_attribute(
                "lookup_status",
                "failed"
            )

            span.set_attribute(
                "error.message",
                str(e)
            )

            logger.exception(
                f"Error retrieving billing info. Policy={policy_number}, Customer={customer_id}"
            )

            raise

        finally:

            if conn:
                conn.close()

def get_payment_history(
    logger,
    policy_number: str
) -> List[Dict[str, Any]]:

    with tracer.start_as_current_span(
        "sqlite_get_payment_history"
    ) as span:

        conn = None

        try:

            span.set_attribute(
                "db.system",
                "sqlite"
            )

            span.set_attribute(
                "db.operation",
                "SELECT"
            )

            span.set_attribute(
                "db.table",
                "payments"
            )

            span.set_attribute(
                "policy_number",
                policy_number
            )

            logger.info(
                f"🔍 Fetching payment history for policy: {policy_number}"
            )

            conn = sqlite3.connect(_DB_PATH)

            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    p.payment_date,
                    p.amount,
                    p.status,
                    p.payment_method
                FROM payments p
                JOIN billing b
                    ON p.bill_id = b.bill_id
                WHERE b.policy_number = ?
                ORDER BY p.payment_date DESC
                LIMIT 10
                """,
                (policy_number,)
            )

            results = cursor.fetchall()

            if results:

                span.set_attribute(
                    "lookup_status",
                    "found"
                )

                span.set_attribute(
                    "records_found",
                    len(results)
                )

                logger.info(
                    f"✅ Found {len(results)} payment records"
                )

                columns = [
                    desc[0]
                    for desc in cursor.description
                ]

                response = [
                    dict(zip(columns, row))
                    for row in results
                ]

                return response

            span.set_attribute(
                "lookup_status",
                "not_found"
            )

            span.set_attribute(
                "records_found",
                0
            )

            logger.warning(
                "❌ No payment history found"
            )

            return []

        except Exception as e:

            span.record_exception(e)

            span.set_attribute(
                "lookup_status",
                "failed"
            )

            span.set_attribute(
                "error.message",
                str(e)
            )

            logger.exception(
                f"Error retrieving payment history for policy {policy_number}"
            )

            raise

        finally:

            if conn:
                conn.close()
def get_auto_policy_details(
    logger,
    policy_number: str
) -> Dict[str, Any]:

    with tracer.start_as_current_span(
        "sqlite_get_auto_policy_details"
    ) as span:

        conn = None

        try:

            span.set_attribute(
                "db.system",
                "sqlite"
            )

            span.set_attribute(
                "db.name",
                "insurance_support.db"
            )

            span.set_attribute(
                "db.operation",
                "SELECT"
            )

            span.set_attribute(
                "db.table",
                "auto_policy_details"
            )

            span.set_attribute(
                "policy_number",
                policy_number
            )

            logger.info(
                f"🔍 Fetching auto policy details for: {policy_number}"
            )

            conn = sqlite3.connect(_DB_PATH)

            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    apd.*,
                    p.policy_type,
                    p.premium_amount
                FROM auto_policy_details apd
                JOIN policies p
                    ON apd.policy_number = p.policy_number
                WHERE apd.policy_number = ?
                """,
                (policy_number,)
            )

            result = cursor.fetchone()

            if result:

                span.set_attribute(
                    "lookup_status",
                    "found"
                )

                logger.info(
                    "✅ Auto policy details found"
                )

                columns = [
                    desc[0]
                    for desc in cursor.description
                ]

                response = dict(
                    zip(columns, result)
                )

                span.set_attribute(
                    "vehicle_make",
                    str(response.get("vehicle_make", ""))
                )

                span.set_attribute(
                    "vehicle_model",
                    str(response.get("vehicle_model", ""))
                )

                span.set_attribute(
                    "policy_type",
                    str(response.get("policy_type", ""))
                )

                return response

            span.set_attribute(
                "lookup_status",
                "not_found"
            )

            logger.warning(
                "❌ Auto policy details not found"
            )

            return {
                "error": "Auto policy details not found"
            }

        except Exception as e:

            span.record_exception(e)

            span.set_attribute(
                "lookup_status",
                "failed"
            )

            span.set_attribute(
                "error.message",
                str(e)
            )

            logger.exception(
                f"Error retrieving auto policy details for policy {policy_number}"
            )

            raise

        finally:

            if conn:
                conn.close()




