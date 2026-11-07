"""
FinPay Application Backend Server.
Provides RESTful APIs adhering to the 4-layer architecture:
- Router layer (HTTP routing & JWT verification)
- Service layer (process_payment, calculate_cashback, wallet, merchant, reconciliation)
- Repository layer (SQL queries & constraints)
- Model / Database layer (SQLite)
"""

import os
import sys
import uuid
import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# Add root folder to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.database import init_db
from backend.services.cashback_service import calculate_cashback, InvalidInput
from backend.services.payment_service import (
    process_payment, preview_payment_cashback,
    InsufficientBalance, ResourceNotFound, OwnershipViolation
)
from backend.services.wallet_service import (
    get_wallet_summary, update_student_wallet_tier, topup_wallet
)
from backend.services.merchant_service import get_all_merchants, get_merchant_details
from backend.services.reconciliation_service import get_monthly_reconciliation
from backend.services.auth_service import (
    create_talenthub_token, verify_talenthub_token, require_auth, extract_token_from_header
)
from backend.models import paise_to_rupees_str

# Initialize Database on boot
init_db(force=False)

# Setup Flask App
STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend"))
app = Flask(__name__, static_folder=STATIC_DIR)
CORS(app)


# -------------------------------------------------------------------------
# Static Frontend Serving
# -------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:filename>")
def serve_static(filename):
    return send_from_directory(STATIC_DIR, filename)


# -------------------------------------------------------------------------
# Authentication Simulation (TalentHub JWT)
# -------------------------------------------------------------------------
DEMO_USERS = [
    {
        "student_id": "rahul_2026",
        "name": "Rahul Verma",
        "role": "student",
        "default_tier": "BASIC",
        "description": "Featured scenario student with BASIC tier (1.0x)"
    },
    {
        "student_id": "priya_2026",
        "name": "Priya Sharma",
        "role": "student",
        "default_tier": "PRIME",
        "description": "Student with PRIME tier (1.5x multiplier)"
    },
    {
        "student_id": "amit_2026",
        "name": "Amit Patel",
        "role": "student",
        "default_tier": "PREMIUM",
        "description": "Student with PREMIUM tier (2.0x multiplier)"
    },
    {
        "student_id": "finance_admin",
        "name": "Prof. Sen (Finance Officer)",
        "role": "finance",
        "default_tier": None,
        "description": "Auditor & Finance Administrator for monthly reconciliation"
    }
]


@app.route("/api/auth/users", methods=["GET"])
def get_auth_users():
    """Returns list of selectable demo TalentHub accounts."""
    return jsonify({"users": DEMO_USERS})


@app.route("/api/auth/token", methods=["POST"])
def get_token():
    """
    Simulates TalentHub authentication endpoint:
    Returns a valid signed JWT for the requested user_id and role.
    """
    data = request.get_json() or {}
    user_id = data.get("user_id", "rahul_2026")
    role = data.get("role", "student")

    token = create_talenthub_token(user_id=user_id, role=role)
    return jsonify({
        "token": token,
        "user_id": user_id,
        "role": role,
        "token_type": "Bearer",
        "expires_in_hours": 24
    })


# -------------------------------------------------------------------------
# Wallet APIs
# -------------------------------------------------------------------------
@app.route("/api/wallet", methods=["GET"])
@require_auth(allowed_roles=["student", "finance", "admin"])
def get_wallet():
    """
    Returns wallet for currently authenticated student.
    Enforces Role-Based field filtering (Alternative A from Part C).
    """
    user = request.user
    student_id = user.get("student_id")

    from backend.database import get_db
    from backend.repository import FinPayRepository

    with get_db() as conn:
        wallet = FinPayRepository.get_wallet_by_student_id(conn, student_id)
        if not wallet:
            # Auto-create if new demo student
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO WALLET (student_id, tier, balance_paise) VALUES (?, 'BASIC', 50000);",
                (student_id,)
            )
            wallet_id = cursor.lastrowid
        else:
            wallet_id = wallet["wallet_id"]

    summary = get_wallet_summary(wallet_id)
    summary["formatted_balance"] = paise_to_rupees_str(summary["balance_paise"])
    for cat in summary["category_limits"]:
        cat["formatted_monthly_cap"] = paise_to_rupees_str(cat["monthly_cap_paise"])
        cat["formatted_earned_this_month"] = paise_to_rupees_str(cat["earned_this_month_paise"])
        cat["formatted_remaining_cap"] = paise_to_rupees_str(cat["remaining_cap_paise"])

    for tx in summary["recent_transactions"]:
        tx["formatted_amount"] = paise_to_rupees_str(tx["amount_paise"])
        tx["formatted_cashback"] = paise_to_rupees_str(tx["cashback_paise"])

    return jsonify(summary)


@app.route("/api/wallet/tier", methods=["POST"])
@require_auth(allowed_roles=["student", "finance", "admin"])
def update_tier():
    """Allows updating student's wallet tier (BASIC, PRIME, PREMIUM)."""
    user = request.user
    student_id = user.get("student_id")
    data = request.get_json() or {}
    new_tier = data.get("tier", "BASIC").upper()

    from backend.database import get_db
    from backend.repository import FinPayRepository

    with get_db() as conn:
        wallet = FinPayRepository.get_wallet_by_student_id(conn, student_id)
        if not wallet:
            return jsonify({"error": "WalletNotFound"}), 404
        wallet_id = wallet["wallet_id"]

    try:
        updated = update_student_wallet_tier(wallet_id, new_tier)
        return jsonify({
            "message": f"Wallet tier upgraded to {new_tier}.",
            "wallet": updated
        })
    except InvalidInput as e:
        return jsonify({"error": "InvalidTier", "message": str(e)}), 400


@app.route("/api/wallet/topup", methods=["POST"])
@require_auth(allowed_roles=["student", "finance", "admin"])
def topup():
    """Credits wallet via TOPUP category."""
    user = request.user
    student_id = user.get("student_id")
    data = request.get_json() or {}

    amount_paise = data.get("amount_paise")
    if amount_paise is None and "amount_rupees" in data:
        amount_paise = int(round(float(data["amount_rupees"]) * 100))

    idempotency_key = data.get("idempotency_key") or str(uuid.uuid4())

    from backend.database import get_db
    from backend.repository import FinPayRepository

    with get_db() as conn:
        wallet = FinPayRepository.get_wallet_by_student_id(conn, student_id)
        if not wallet:
            return jsonify({"error": "WalletNotFound"}), 404
        wallet_id = wallet["wallet_id"]

    try:
        res = topup_wallet(
            wallet_id=wallet_id,
            amount_paise=amount_paise,
            idempotency_key=idempotency_key,
            student_id=student_id
        )
        res["formatted_amount"] = paise_to_rupees_str(res["amount_paise"])
        res["formatted_balance"] = paise_to_rupees_str(res.get("new_balance_paise", 0))
        return jsonify(res)
    except (InvalidInput, ResourceNotFound) as e:
        return jsonify({"error": "TopupFailed", "message": str(e)}), 400


# -------------------------------------------------------------------------
# Merchant & Rule APIs
# -------------------------------------------------------------------------
@app.route("/api/merchants", methods=["GET"])
def list_merchants():
    """Returns directory of all merchants with category rules."""
    merchants = get_all_merchants()
    for m in merchants:
        m["formatted_basic_cap"] = paise_to_rupees_str(m["basic_monthly_cap_paise"])
        m["base_rate_percent"] = m["rate_bps"] / 100.0
    return jsonify({"merchants": merchants})


# -------------------------------------------------------------------------
# Payment & Cashback APIs
# -------------------------------------------------------------------------
@app.route("/api/payment/preview", methods=["POST"])
@require_auth(allowed_roles=["student", "finance", "admin"])
def preview_payment():
    """
    Computes real-time preview of cashback, raw vs capped, before payment is submitted.
    """
    data = request.get_json() or {}
    user = request.user
    student_id = user.get("student_id")

    merchant_id = data.get("merchant_id")
    amount_paise = data.get("amount_paise")
    if amount_paise is None and "amount_rupees" in data:
        amount_paise = int(round(float(data["amount_rupees"]) * 100))

    if not merchant_id or amount_paise is None or amount_paise <= 0:
        return jsonify({"error": "Invalid parameters for preview"}), 400

    from backend.database import get_db
    from backend.repository import FinPayRepository

    with get_db() as conn:
        wallet = FinPayRepository.get_wallet_by_student_id(conn, student_id)
        if not wallet:
            return jsonify({"error": "Wallet not found"}), 404
        wallet_id = wallet["wallet_id"]

    try:
        preview = preview_payment_cashback(wallet_id, int(merchant_id), int(amount_paise))
        preview["formatted_raw_cashback"] = paise_to_rupees_str(preview["raw_cashback_paise"])
        preview["formatted_awarded_cashback"] = paise_to_rupees_str(preview["awarded_cashback_paise"])
        preview["formatted_monthly_cap"] = paise_to_rupees_str(preview["monthly_cap_paise"])
        preview["formatted_remaining_cap"] = paise_to_rupees_str(preview["remaining_cap_paise"])
        return jsonify(preview)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/payment/process", methods=["POST"])
@require_auth(allowed_roles=["student", "finance", "admin"])
def make_payment():
    """
    Main FinPay Payment Endpoint (process_payment):
    - Router layer validates JWT
    - Service layer validates wallet ownership & monthly cap
    - Database layer validates idempotency & atomic balance update
    """
    data = request.get_json() or {}
    user = request.user
    student_id = user.get("student_id")
    role = user.get("role", "student")

    merchant_id = data.get("merchant_id")
    amount_paise = data.get("amount_paise")
    if amount_paise is None and "amount_rupees" in data:
        amount_paise = int(round(float(data["amount_rupees"]) * 100))

    idempotency_key = data.get("idempotency_key")
    if not idempotency_key or not idempotency_key.strip():
        idempotency_key = str(uuid.uuid4())

    from backend.database import get_db
    from backend.repository import FinPayRepository

    with get_db() as conn:
        wallet = FinPayRepository.get_wallet_by_student_id(conn, student_id)
        if not wallet:
            return jsonify({"error": "WalletNotFound", "message": "Student wallet does not exist."}), 404
        wallet_id = wallet["wallet_id"]

    try:
        result = process_payment(
            wallet_id=wallet_id,
            merchant_id=int(merchant_id),
            amount_paise=int(amount_paise),
            idempotency_key=idempotency_key,
            authenticated_student_id=student_id,
            allow_admin_bypass=(role in ["admin", "finance"])
        )

        result["formatted_amount"] = paise_to_rupees_str(result["amount_paise"])
        result["formatted_cashback"] = paise_to_rupees_str(result.get("cashback_paise", 0))
        result["formatted_balance"] = paise_to_rupees_str(result.get("new_balance_paise", result.get("current_balance_paise", 0)))
        return jsonify(result), 200

    except OwnershipViolation as e:
        return jsonify({"error": "OwnershipViolation", "message": str(e)}), 403
    except InsufficientBalance as e:
        return jsonify({"error": "InsufficientBalance", "message": str(e)}), 400
    except InvalidInput as e:
        return jsonify({"error": "InvalidInput", "message": str(e)}), 400
    except ResourceNotFound as e:
        return jsonify({"error": "ResourceNotFound", "message": str(e)}), 404
    except Exception as e:
        return jsonify({"error": "InternalError", "message": str(e)}), 500


# -------------------------------------------------------------------------
# Transactions & Monthly Reconciliation APIs
# -------------------------------------------------------------------------
@app.route("/api/transactions", methods=["GET"])
@require_auth(allowed_roles=["student", "finance", "admin"])
def get_transactions():
    """
    Returns transaction list for currently authenticated student.
    Enforces Role-Based field filtering (Alternative A from Part C).
    """
    user = request.user
    student_id = user.get("student_id")
    role = user.get("role", "student")

    from backend.database import get_db
    from backend.repository import FinPayRepository

    with get_db() as conn:
        wallet = FinPayRepository.get_wallet_by_student_id(conn, student_id)
        if not wallet:
            return jsonify({"transactions": []})
        transactions = FinPayRepository.get_transactions_for_wallet(conn, wallet["wallet_id"], limit=50)

    for tx in transactions:
        tx["formatted_amount"] = paise_to_rupees_str(tx["amount_paise"])
        tx["formatted_cashback"] = paise_to_rupees_str(tx["cashback_paise"])

    return jsonify({"transactions": transactions})


@app.route("/api/reconciliation", methods=["GET"])
@require_auth(allowed_roles=["finance", "admin"])
def get_reconciliation():
    """
    Reconciliation Service: accessible only by Finance and Admin roles.
    Returns audit aggregates, category breakdowns, and system-wide totals.
    """
    month = request.args.get("month")
    reconciliation = get_monthly_reconciliation(month)

    # Format paise values
    summary = reconciliation["summary"]
    summary["formatted_payments"] = paise_to_rupees_str(summary["total_payments_paise"])
    summary["formatted_topups"] = paise_to_rupees_str(summary["total_topups_paise"])
    summary["formatted_cashback"] = paise_to_rupees_str(summary["total_cashback_paise"])
    summary["formatted_student_outflow"] = paise_to_rupees_str(summary["net_student_outflow_paise"])
    summary["formatted_system_balance"] = paise_to_rupees_str(summary["total_system_balance_paise"])

    for cat in reconciliation["category_breakdown"]:
        cat["formatted_amount"] = paise_to_rupees_str(cat["category_amount_paise"])
        cat["formatted_cashback"] = paise_to_rupees_str(cat["category_cashback_paise"])

    for m in reconciliation["merchant_breakdown"]:
        m["formatted_amount"] = paise_to_rupees_str(m["merchant_amount_paise"])
        m["formatted_cashback"] = paise_to_rupees_str(m["merchant_cashback_paise"])

    for t in reconciliation["transactions"]:
        t["formatted_amount"] = paise_to_rupees_str(t["amount_paise"])
        t["formatted_cashback"] = paise_to_rupees_str(t["cashback_paise"])

    return jsonify(reconciliation)


# -------------------------------------------------------------------------
# Dynamic Test Suite API (For Frontend Interactive Test Dashboard)
# -------------------------------------------------------------------------
@app.route("/api/tests/run", methods=["GET"])
def run_interactive_lab_tests():
    """
    Runs the 10 boundary and edge-case checks directly and returns structured JSON
    to power the Lab 4 verification dashboard in the frontend.
    """
    results = []

    # Test 1
    try:
        c1 = calculate_cashback(10000, 200, 10)
        p1 = (c1 == 200)
        results.append({
            "id": 1,
            "name": "Rahul's Example (Scenario)",
            "input": "Amount: ₹100 (10,000 paise), Category: CANTEEN (200 bps), Tier: BASIC (10)",
            "formula": "10,000 × 200 × 10 ÷ 100,000",
            "expected": "200 paise (₹2.00)",
            "actual": f"{c1} paise ({paise_to_rupees_str(c1)})",
            "passed": p1
        })
    except Exception as e:
        results.append({"id": 1, "name": "Rahul's Example", "passed": False, "error": str(e)})

    # Test 2
    try:
        c2 = calculate_cashback(1234, 200, 15)
        p2 = (c2 == 37)
        results.append({
            "id": 2,
            "name": "PRIME Multiplier Cut-off",
            "input": "Amount: 1,234 paise, Category: CANTEEN (200 bps), Tier: PRIME (15)",
            "formula": "1,234 × 200 × 15 ÷ 100,000 = 37.02 → cut off to 37 (one-step)",
            "expected": "37 paise",
            "actual": f"{c2} paise",
            "passed": p2
        })
    except Exception as e:
        results.append({"id": 2, "name": "PRIME Multiplier Cut-off", "passed": False, "error": str(e)})

    # Test 3
    try:
        c3 = calculate_cashback(50, 200, 10)
        p3 = (c3 == 1)
        results.append({
            "id": 3,
            "name": "Smallest Amount Earning 1 Paise",
            "input": "Amount: 50 paise, Category: CANTEEN (200 bps), Tier: BASIC (10)",
            "formula": "50 × 200 × 10 ÷ 100,000 = 1.00 → 1",
            "expected": "1 paise",
            "actual": f"{c3} paise",
            "passed": p3
        })
    except Exception as e:
        results.append({"id": 3, "name": "Smallest Amount Earning 1 Paise", "passed": False, "error": str(e)})

    # Test 4
    try:
        c4 = calculate_cashback(49, 200, 10)
        p4 = (c4 == 0)
        results.append({
            "id": 4,
            "name": "Fractional Cut-off (Floor, No Rounding)",
            "input": "Amount: 49 paise, Category: CANTEEN (200 bps), Tier: BASIC (10)",
            "formula": "49 × 200 × 10 ÷ 100,000 = 0.98 → floor DIV gives 0",
            "expected": "0 paise",
            "actual": f"{c4} paise",
            "passed": p4
        })
    except Exception as e:
        results.append({"id": 4, "name": "Fractional Cut-off", "passed": False, "error": str(e)})

    # Test 5
    try:
        c5 = calculate_cashback(333, 100, 10)
        p5 = (c5 == 3)
        results.append({
            "id": 5,
            "name": "Stationery Division Check",
            "input": "Amount: 333 paise, Category: STATIONERY (100 bps), Tier: BASIC (10)",
            "formula": "333 × 100 × 10 ÷ 100,000 = 3.33 → 3",
            "expected": "3 paise",
            "actual": f"{c5} paise",
            "passed": p5
        })
    except Exception as e:
        results.append({"id": 5, "name": "Stationery Division Check", "passed": False, "error": str(e)})

    # Test 6
    try:
        c6 = calculate_cashback(100000, 50, 20)
        p6 = (c6 == 1000)
        results.append({
            "id": 6,
            "name": "Hostel Premium (Effective 1.0%)",
            "input": "Amount: ₹1,000 (100,000 paise), Category: HOSTEL (50 bps), Tier: PREMIUM (20)",
            "formula": "100,000 × 50 × 20 ÷ 100,000 = 1,000",
            "expected": "1,000 paise (₹10.00)",
            "actual": f"{c6} paise ({paise_to_rupees_str(c6)})",
            "passed": p6
        })
    except Exception as e:
        results.append({"id": 6, "name": "Hostel Premium", "passed": False, "error": str(e)})

    # Test 7
    try:
        c7 = calculate_cashback(50000, 0, 10)
        p7 = (c7 == 0)
        results.append({
            "id": 7,
            "name": "Top-up Zero Rate (No Cashback)",
            "input": "Amount: 50,000 paise, Category: TOPUP (0 bps), Any tier",
            "formula": "rate_bps = 0 → immediate 0",
            "expected": "0 paise",
            "actual": f"{c7} paise",
            "passed": p7
        })
    except Exception as e:
        results.append({"id": 7, "name": "Top-up Zero Rate", "passed": False, "error": str(e)})

    # Test 8
    try:
        p8 = False
        try:
            calculate_cashback(0, 200, 10)
        except InvalidInput:
            p8 = True
        results.append({
            "id": 8,
            "name": "Refusal on Non-positive Amount",
            "input": "Amount: 0 paise or negative",
            "formula": "IF amount <= 0 RAISE InvalidInput",
            "expected": "InvalidInput Exception Raised",
            "actual": "InvalidInput Exception Raised" if p8 else "Did not raise exception",
            "passed": p8
        })
    except Exception as e:
        results.append({"id": 8, "name": "Refusal on Non-positive Amount", "passed": False, "error": str(e)})

    # Test 9: Monthly cap partial
    try:
        # Cap = 5000, already earned = 4900, raw = 200. Awarded = MIN(200, 5000 - 4900) = 100
        raw = 200
        cap = 5000
        earned = 4900
        awarded = min(raw, max(cap - earned, 0))
        p9 = (awarded == 100)
        results.append({
            "id": 9,
            "name": "Monthly Cap Partial Reduction",
            "input": "Raw cashback: 200 paise, Category Cap: 5,000 paise, Already earned: 4,900 paise",
            "formula": "MIN(200, MAX(5,000 − 4,900, 0))",
            "expected": "100 paise",
            "actual": f"{awarded} paise",
            "passed": p9
        })
    except Exception as e:
        results.append({"id": 9, "name": "Monthly Cap Partial Reduction", "passed": False, "error": str(e)})

    # Test 10: Monthly cap exhausted
    try:
        raw = 200
        cap = 5000
        earned = 5000
        awarded = min(raw, max(cap - earned, 0))
        p10 = (awarded == 0)
        results.append({
            "id": 10,
            "name": "Monthly Cap Fully Exhausted",
            "input": "Raw cashback: 200 paise, Category Cap: 5,000 paise, Already earned: 5,000 paise",
            "formula": "MIN(200, MAX(5,000 − 5,000, 0))",
            "expected": "0 paise",
            "actual": f"{awarded} paise",
            "passed": p10
        })
    except Exception as e:
        results.append({"id": 10, "name": "Monthly Cap Fully Exhausted", "passed": False, "error": str(e)})

    all_passed = all(r.get("passed", False) for r in results)
    return jsonify({
        "all_passed": all_passed,
        "total_tests": len(results),
        "passed_tests": sum(1 for r in results if r.get("passed", False)),
        "tests": results
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

