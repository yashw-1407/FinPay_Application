"""
FinPay Monthly Reconciliation Service.
Designed for Finance and Admin officers to audit transaction flows,
monthly cashback caps, category disbursements, and wallet balance consistency.
"""

import datetime
from typing import Dict, Any, List, Optional
from backend.database import get_db
from backend.repository import FinPayRepository


def get_monthly_reconciliation(month_str: Optional[str] = None) -> Dict[str, Any]:
    """
    Computes financial reconciliation metrics for a given calendar month (YYYY-MM).
    If month_str is None, uses the current month.
    """
    if not month_str:
        month_str = datetime.datetime.now().strftime("%Y-%m")

    with get_db() as conn:
        cursor = conn.cursor()

        # 1. Overall Volume Summary
        cursor.execute(
            """
            SELECT
                COUNT(*) as total_count,
                COALESCE(SUM(CASE WHEN m.category_code = 'TOPUP' THEN t.amount_paise ELSE 0 END), 0) as total_topups_paise,
                COALESCE(SUM(CASE WHEN m.category_code != 'TOPUP' THEN t.amount_paise ELSE 0 END), 0) as total_payments_paise,
                COALESCE(SUM(t.cashback_paise), 0) as total_cashback_paise
            FROM "TRANSACTION" t
            JOIN MERCHANT m ON t.merchant_id = m.merchant_id
            WHERE strftime('%Y-%m', t.created_at) = ?;
            """,
            (month_str,)
        )
        vol_row = cursor.fetchone()
        total_tx = vol_row["total_count"]
        total_topups = vol_row["total_topups_paise"]
        total_payments = vol_row["total_payments_paise"]
        total_cashback = vol_row["total_cashback_paise"]

        # 2. Category-wise Breakdown
        cursor.execute(
            """
            SELECT
                m.category_code,
                COUNT(t.transaction_id) as tx_count,
                COALESCE(SUM(t.amount_paise), 0) as category_amount_paise,
                COALESCE(SUM(t.cashback_paise), 0) as category_cashback_paise
            FROM "TRANSACTION" t
            JOIN MERCHANT m ON t.merchant_id = m.merchant_id
            WHERE strftime('%Y-%m', t.created_at) = ?
            GROUP BY m.category_code
            ORDER BY category_amount_paise DESC;
            """,
            (month_str,)
        )
        category_breakdown = [dict(r) for r in cursor.fetchall()]

        # 3. Merchant-wise Breakdown
        cursor.execute(
            """
            SELECT
                m.merchant_id,
                m.merchant_name,
                m.category_code,
                COUNT(t.transaction_id) as tx_count,
                COALESCE(SUM(t.amount_paise), 0) as merchant_amount_paise,
                COALESCE(SUM(t.cashback_paise), 0) as merchant_cashback_paise
            FROM "TRANSACTION" t
            JOIN MERCHANT m ON t.merchant_id = m.merchant_id
            WHERE strftime('%Y-%m', t.created_at) = ?
            GROUP BY m.merchant_id, m.merchant_name, m.category_code
            ORDER BY merchant_amount_paise DESC;
            """,
            (month_str,)
        )
        merchant_breakdown = [dict(r) for r in cursor.fetchall()]

        # 4. Total Current System Wallet Balances
        cursor.execute("SELECT COALESCE(SUM(balance_paise), 0) as total_system_balance FROM WALLET;")
        total_wallet_balance = cursor.fetchone()["total_system_balance"]

        # 5. Full list of transactions for this month
        all_month_tx = FinPayRepository.get_all_transactions(conn, month_str)

        return {
            "reconciliation_month": month_str,
            "summary": {
                "total_transactions": total_tx,
                "total_payments_paise": total_payments,
                "total_topups_paise": total_topups,
                "total_cashback_paise": total_cashback,
                "net_student_outflow_paise": total_payments - total_cashback,
                "total_system_balance_paise": total_wallet_balance
            },
            "category_breakdown": category_breakdown,
            "merchant_breakdown": merchant_breakdown,
            "transactions": all_month_tx
        }

