"""
FinPay Payment Processing Service.
Implements process_payment() as specified in the Lab 4 Detailed Design (Part B & Part C).
Coordinates payment transaction, raw cashback calculation, monthly cap application,
and strict database-level idempotency checks inside an atomic transaction.
"""

import datetime
from typing import Dict, Any, Optional
from backend.database import get_db
from backend.repository import FinPayRepository
from backend.services.cashback_service import calculate_cashback, InvalidInput


class InsufficientBalance(Exception):
    """Raised when wallet does not have enough balance for payment."""
    pass


class ResourceNotFound(Exception):
    """Raised when wallet, merchant, or rule is not found."""
    pass


class OwnershipViolation(Exception):
    """Raised when logged-in student attempts to access/pay from another student's wallet."""
    pass


def process_payment(
    wallet_id: int,
    merchant_id: int,
    amount_paise: int,
    idempotency_key: str,
    authenticated_student_id: Optional[str] = None,
    allow_admin_bypass: bool = False
) -> Dict[str, Any]:
    """
    Executes a FinPay payment atomically:
    1. Checks ownership: wallet.student_id == authenticated_student_id
    2. Checks idempotency: UNIQUE(wallet_id, idempotency_key)
    3. Handles TOPUP merchant vs Category Payment
    4. Applies calculate_cashback() and monthly category cap
    5. Updates wallet balance and records TRANSACTION in a single DB transaction.
    """
    if not idempotency_key or not idempotency_key.strip():
        raise InvalidInput("An idempotency_key is required for all payments.")

    if amount_paise <= 0:
        raise InvalidInput("Payment amount must be greater than zero.")

    now = datetime.datetime.now()
    created_at_iso = now.strftime("%Y-%m-%d %H:%M:%S")
    current_month_str = now.strftime("%Y-%m")

    with get_db() as conn:
        # Step 1: Check Idempotency First
        existing_tx = FinPayRepository.get_transaction_by_idempotency(conn, wallet_id, idempotency_key)
        if existing_tx:
            # Idempotent replay: return existing result, NO second debit or cashback
            wallet = FinPayRepository.get_wallet_by_id(conn, wallet_id)
            return {
                "is_idempotent_replay": True,
                "message": "Payment was already processed previously (Idempotent replay).",
                "transaction_id": existing_tx["transaction_id"],
                "wallet_id": existing_tx["wallet_id"],
                "merchant_id": existing_tx["merchant_id"],
                "merchant_name": existing_tx["merchant_name"],
                "category_code": existing_tx["category_code"],
                "amount_paise": existing_tx["amount_paise"],
                "cashback_paise": existing_tx["cashback_paise"],
                "created_at": existing_tx["created_at"],
                "current_balance_paise": wallet["balance_paise"] if wallet else 0
            }

        # Step 2: Fetch and validate Wallet
        wallet = FinPayRepository.get_wallet_by_id(conn, wallet_id)
        if not wallet:
            raise ResourceNotFound(f"Wallet with id {wallet_id} not found.")

        # Step 3: Service-layer ownership verification (Part C Security Design)
        if authenticated_student_id and not allow_admin_bypass:
            if wallet["student_id"] != authenticated_student_id:
                raise OwnershipViolation(
                    f"Access Denied: Wallet belongs to student '{wallet['student_id']}', "
                    f"not authenticated user '{authenticated_student_id}'."
                )

        # Step 4: Fetch Merchant and Category Cashback Rule
        merchant = FinPayRepository.get_merchant(conn, merchant_id)
        if not merchant:
            raise ResourceNotFound(f"Merchant with id {merchant_id} not found.")

        category_code = merchant["category_code"]
        rate_bps = merchant["rate_bps"]
        basic_monthly_cap_paise = merchant["basic_monthly_cap_paise"]

        tier_name = wallet["tier"]
        tier = FinPayRepository.get_tier(conn, tier_name)
        if not tier:
            raise ResourceNotFound(f"Wallet tier '{tier_name}' not found.")

        rate_mult_x10 = tier["rate_mult_x10"]
        cap_mult_x10 = tier["cap_mult_x10"]

        # Step 5: Check if TOPUP or Purchase
        if category_code == "TOPUP":
            # Top-up credits the wallet
            raw_cashback = 0
            awarded_cashback = 0
            new_balance = wallet["balance_paise"] + amount_paise
        else:
            # Regular purchase: must have enough balance
            if wallet["balance_paise"] < amount_paise:
                raise InsufficientBalance(
                    f"Insufficient funds: available {wallet['balance_paise']} paise, "
                    f"required {amount_paise} paise."
                )

            # Raw cashback algorithm (No decimals, cut off once)
            raw_cashback = calculate_cashback(amount_paise, rate_bps, rate_mult_x10)

            # Monthly Cap Calculation: (basic_cap * cap_multiplier) // 10
            monthly_cap_paise = (basic_monthly_cap_paise * cap_mult_x10) // 10

            # Sum of cashback already earned in this category during the current calendar month
            already_earned = FinPayRepository.get_monthly_cashback_sum(
                conn, wallet_id, category_code, current_month_str
            )

            # Awarded = MIN(raw, MAX(cap - earned, 0))
            remaining_cap = max(monthly_cap_paise - already_earned, 0)
            awarded_cashback = min(raw_cashback, remaining_cap)

            # Net wallet update: balance - amount + awarded_cashback
            new_balance = wallet["balance_paise"] - amount_paise + awarded_cashback

        # Step 6: Atomic DB Update (Balance update + Transaction row insertion)
        FinPayRepository.update_wallet_balance(conn, wallet_id, new_balance)

        tx_id = FinPayRepository.insert_transaction(
            conn=conn,
            wallet_id=wallet_id,
            merchant_id=merchant_id,
            idempotency_key=idempotency_key,
            amount_paise=amount_paise,
            cashback_paise=awarded_cashback,
            created_at=created_at_iso
        )

        return {
            "is_idempotent_replay": False,
            "message": "Payment processed successfully.",
            "transaction_id": tx_id,
            "wallet_id": wallet_id,
            "student_id": wallet["student_id"],
            "merchant_id": merchant_id,
            "merchant_name": merchant["merchant_name"],
            "category_code": category_code,
            "amount_paise": amount_paise,
            "raw_cashback_paise": raw_cashback,
            "cashback_paise": awarded_cashback,
            "previous_balance_paise": wallet["balance_paise"],
            "new_balance_paise": new_balance,
            "idempotency_key": idempotency_key,
            "created_at": created_at_iso
        }


def preview_payment_cashback(
    wallet_id: int,
    merchant_id: int,
    amount_paise: int
) -> Dict[str, Any]:
    """
    Simulates / previews cashback calculation for UI without mutating database state.
    """
    if amount_paise <= 0:
        return {"error": "Amount must be > 0"}

    with get_db() as conn:
        wallet = FinPayRepository.get_wallet_by_id(conn, wallet_id)
        if not wallet:
            raise ResourceNotFound(f"Wallet {wallet_id} not found.")

        merchant = FinPayRepository.get_merchant(conn, merchant_id)
        if not merchant:
            raise ResourceNotFound(f"Merchant {merchant_id} not found.")

        category_code = merchant["category_code"]
        rate_bps = merchant["rate_bps"]
        basic_monthly_cap_paise = merchant["basic_monthly_cap_paise"]

        tier = FinPayRepository.get_tier(conn, wallet["tier"])
        rate_mult_x10 = tier["rate_mult_x10"]
        cap_mult_x10 = tier["cap_mult_x10"]

        if category_code == "TOPUP":
            return {
                "category_code": "TOPUP",
                "raw_cashback_paise": 0,
                "awarded_cashback_paise": 0,
                "monthly_cap_paise": 0,
                "already_earned_paise": 0,
                "remaining_cap_paise": 0,
                "is_topup": True
            }

        raw_cashback = calculate_cashback(amount_paise, rate_bps, rate_mult_x10)
        monthly_cap_paise = (basic_monthly_cap_paise * cap_mult_x10) // 10

        now = datetime.datetime.now()
        current_month_str = now.strftime("%Y-%m")
        already_earned = FinPayRepository.get_monthly_cashback_sum(
            conn, wallet_id, category_code, current_month_str
        )

        remaining_cap = max(monthly_cap_paise - already_earned, 0)
        awarded_cashback = min(raw_cashback, remaining_cap)

        effective_rate_percent = (rate_bps * rate_mult_x10) / 1000.0

        return {
            "category_code": category_code,
            "effective_rate_percent": effective_rate_percent,
            "raw_cashback_paise": raw_cashback,
            "monthly_cap_paise": monthly_cap_paise,
            "already_earned_paise": already_earned,
            "remaining_cap_paise": remaining_cap,
            "awarded_cashback_paise": awarded_cashback,
            "is_topup": False
        }

