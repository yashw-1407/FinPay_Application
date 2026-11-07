"""
FinPay Wallet Management Service.
Handles student wallet lookups, balance queries, tier updates, and category limits.
"""

import datetime
from typing import Dict, Any, List, Optional
from backend.database import get_db
from backend.repository import FinPayRepository
from backend.services.payment_service import process_payment, ResourceNotFound, InvalidInput


def get_wallet_summary(wallet_id: int) -> Dict[str, Any]:
    """
    Returns full wallet profile, current balance, tier multipliers,
    and monthly category cashback limits vs earned amounts for current month.
    """
    with get_db() as conn:
        wallet = FinPayRepository.get_wallet_by_id(conn, wallet_id)
        if not wallet:
            raise ResourceNotFound(f"Wallet {wallet_id} not found.")

        tier_name = wallet["tier"]
        tier = FinPayRepository.get_tier(conn, tier_name)
        rules = FinPayRepository.get_all_cashback_rules(conn)

        now = datetime.datetime.now()
        current_month_str = now.strftime("%Y-%m")

        earned_map = FinPayRepository.get_monthly_cashback_all_categories(
            conn, wallet_id, current_month_str
        )

        category_limits = []
        for r in rules:
            cat = r["category_code"]
            basic_cap = r["basic_monthly_cap_paise"]
            rate_bps = r["rate_bps"]
            # cap = (basic_cap * cap_mult_x10) // 10
            monthly_cap = (basic_cap * tier["cap_mult_x10"]) // 10 if cat != "TOPUP" else 0
            earned = earned_map.get(cat, 0)
            remaining = max(monthly_cap - earned, 0)
            percent_used = round((earned / monthly_cap * 100), 1) if monthly_cap > 0 else 0.0

            category_limits.append({
                "category_code": cat,
                "base_rate_bps": rate_bps,
                "effective_rate_percent": (rate_bps * tier["rate_mult_x10"]) / 1000.0,
                "monthly_cap_paise": monthly_cap,
                "earned_this_month_paise": earned,
                "remaining_cap_paise": remaining,
                "percent_used": min(percent_used, 100.0)
            })

        transactions = FinPayRepository.get_transactions_for_wallet(conn, wallet_id, limit=20)

        return {
            "wallet_id": wallet["wallet_id"],
            "student_id": wallet["student_id"],
            "tier": wallet["tier"],
            "rate_mult_x10": tier["rate_mult_x10"],
            "cap_mult_x10": tier["cap_mult_x10"],
            "balance_paise": wallet["balance_paise"],
            "current_month": current_month_str,
            "category_limits": category_limits,
            "recent_transactions": transactions
        }


def update_student_wallet_tier(wallet_id: int, new_tier: str) -> Dict[str, Any]:
    """Updates a wallet's tier (e.g. BASIC -> PRIME -> PREMIUM)."""
    with get_db() as conn:
        tier_info = FinPayRepository.get_tier(conn, new_tier)
        if not tier_info:
            raise InvalidInput(f"Invalid tier '{new_tier}'. Allowed: BASIC, PRIME, PREMIUM.")

        FinPayRepository.update_wallet_tier(conn, wallet_id, new_tier)
        updated = FinPayRepository.get_wallet_by_id(conn, wallet_id)
        return dict(updated)


def topup_wallet(wallet_id: int, amount_paise: int, idempotency_key: str, student_id: str) -> Dict[str, Any]:
    """
    Credits a student's wallet via the designated TOPUP merchant.
    Maintains normalized audit trail in TRANSACTION table.
    """
    if amount_paise <= 0:
        raise InvalidInput("Top-up amount must be greater than zero.")

    with get_db() as conn:
        # Find the TOPUP merchant
        cursor = conn.cursor()
        cursor.execute("SELECT merchant_id FROM MERCHANT WHERE category_code = 'TOPUP' LIMIT 1;")
        row = cursor.fetchone()
        if not row:
            raise ResourceNotFound("Top-up merchant not configured.")
        topup_merchant_id = row[0]

    return process_payment(
        wallet_id=wallet_id,
        merchant_id=topup_merchant_id,
        amount_paise=amount_paise,
        idempotency_key=idempotency_key,
        authenticated_student_id=student_id
    )

