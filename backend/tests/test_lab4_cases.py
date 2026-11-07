"""
Laboratory 4 Automated Test Suite
Verifies all 10 Boundary and Edge-Case checks from Lab 4 Table 3,
along with Idempotency, Security Ownership, and Balance Constraints.
"""

import unittest
import os
import sys
import uuid
import datetime

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.database import init_db, get_db
from backend.services.cashback_service import calculate_cashback, InvalidInput
from backend.services.payment_service import process_payment, InsufficientBalance, OwnershipViolation
from backend.repository import FinPayRepository


class TestLab4BoundaryCases(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Fresh database init
        init_db(force=True)

    # -------------------------------------------------------------
    # Table 3: Boundary & Edge-Case Checks (calculate_cashback)
    # -------------------------------------------------------------

    def test_case_1_rahul_canteen_basic(self):
        """Case 1: 10,000 paise (₹100), CANTEEN (200 bps), BASIC (mult 10) -> 200 paise (₹2)"""
        # Formula: 10000 * 200 * 10 // 100000 = 200
        cashback = calculate_cashback(amount_paise=10000, rate_bps=200, tier_mult_x10=10)
        self.assertEqual(cashback, 200, "Rahul's scenario must yield exactly 200 paise (₹2)")

    def test_case_2_canteen_prime_division(self):
        """Case 2: 1234 paise, CANTEEN (200 bps), PRIME (mult 15) -> 37 paise (37.02 -> 37)"""
        # Formula: 1234 * 200 * 15 // 100000 = 3,702,000 // 100,000 = 37
        cashback = calculate_cashback(amount_paise=1234, rate_bps=200, tier_mult_x10=15)
        self.assertEqual(cashback, 37, "Must cut off once to 37 (avoid two-step truncation loss of 36)")

    def test_case_3_canteen_basic_lower_boundary_earn_1(self):
        """Case 3: 50 paise, CANTEEN (200 bps), BASIC (mult 10) -> 1 paise"""
        # Formula: 50 * 200 * 10 // 100000 = 100,000 // 100000 = 1
        cashback = calculate_cashback(amount_paise=50, rate_bps=200, tier_mult_x10=10)
        self.assertEqual(cashback, 1, "Smallest amount that earns 1 paise")

    def test_case_4_canteen_basic_lower_boundary_earn_0(self):
        """Case 4: 49 paise, CANTEEN (200 bps), BASIC (mult 10) -> 0 paise"""
        # Formula: 49 * 200 * 10 // 100000 = 98,000 // 100000 = 0 (cut off, not rounded up)
        cashback = calculate_cashback(amount_paise=49, rate_bps=200, tier_mult_x10=10)
        self.assertEqual(cashback, 0, "49 paise must yield 0 paise (no rounding up)")

    def test_case_5_stationery_basic_fraction(self):
        """Case 5: 333 paise, STATIONERY (100 bps), BASIC (mult 10) -> 3 paise"""
        # Formula: 333 * 100 * 10 // 100000 = 333,000 // 100000 = 3 (cut off 3.33)
        cashback = calculate_cashback(amount_paise=333, rate_bps=100, tier_mult_x10=10)
        self.assertEqual(cashback, 3, "333 paise must yield 3 paise")

    def test_case_6_hostel_premium(self):
        """Case 6: 100,000 paise (₹1000), HOSTEL (50 bps), PREMIUM (mult 20) -> 1000 paise (₹10)"""
        # Formula: 100000 * 50 * 20 // 100000 = 1000
        cashback = calculate_cashback(amount_paise=100000, rate_bps=50, tier_mult_x10=20)
        self.assertEqual(cashback, 1000, "100,000 paise in Hostel Premium must yield 1000 paise")

    def test_case_7_topup_no_cashback(self):
        """Case 7: 50,000 paise, TOPUP (0 bps), any tier -> 0 paise"""
        cashback = calculate_cashback(amount_paise=50000, rate_bps=0, tier_mult_x10=10)
        self.assertEqual(cashback, 0, "Top-up has 0 bps so raw cashback must be 0")

    def test_case_8_zero_or_negative_amount(self):
        """Case 8: 0 or less paise -> InvalidInput"""
        with self.assertRaises(InvalidInput):
            calculate_cashback(amount_paise=0, rate_bps=200, tier_mult_x10=10)

        with self.assertRaises(InvalidInput):
            calculate_cashback(amount_paise=-500, rate_bps=200, tier_mult_x10=10)

    # -------------------------------------------------------------
    # Table 3: Monthly Limit Checks in process_payment
    # -------------------------------------------------------------

    def test_case_9_monthly_cap_partial_remaining(self):
        """Case 9: process_payment: raw 200, CANTEEN BASIC (cap 5000), already earned 4900 -> awarded 100"""
        # Create a dedicated wallet for this test
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO WALLET (student_id, tier, balance_paise) VALUES (?, ?, ?);",
                ("test_student_cap_partial", "BASIC", 200000)
            )
            wallet_id = cursor.lastrowid

            # Find a CANTEEN merchant
            cursor.execute("SELECT merchant_id FROM MERCHANT WHERE category_code = 'CANTEEN' LIMIT 1;")
            merchant_id = cursor.fetchone()[0]

            # Pre-seed 4900 paise of CANTEEN cashback in the current month
            now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                """
                INSERT INTO "TRANSACTION" (wallet_id, merchant_id, idempotency_key, amount_paise, cashback_paise, created_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (wallet_id, merchant_id, "seed-pre-cap-partial", 245000, 4900, now_iso)
            )

        # Now make a payment of ₹100 (10,000 paise) -> raw cashback = 200 paise
        # Remaining cap is 5000 - 4900 = 100 paise. So awarded must be MIN(200, 100) = 100 paise.
        res = process_payment(
            wallet_id=wallet_id,
            merchant_id=merchant_id,
            amount_paise=10000,
            idempotency_key=str(uuid.uuid4()),
            authenticated_student_id="test_student_cap_partial"
        )
        self.assertEqual(res["raw_cashback_paise"], 200)
        self.assertEqual(res["cashback_paise"], 100, "Cashback must be capped to remaining 100 paise")

    def test_case_10_monthly_cap_exhausted(self):
        """Case 10: process_payment: raw 200, CANTEEN BASIC (cap 5000), already earned 5000 -> awarded 0"""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO WALLET (student_id, tier, balance_paise) VALUES (?, ?, ?);",
                ("test_student_cap_exhausted", "BASIC", 200000)
            )
            wallet_id = cursor.lastrowid

            cursor.execute("SELECT merchant_id FROM MERCHANT WHERE category_code = 'CANTEEN' LIMIT 1;")
            merchant_id = cursor.fetchone()[0]

            now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                """
                INSERT INTO "TRANSACTION" (wallet_id, merchant_id, idempotency_key, amount_paise, cashback_paise, created_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (wallet_id, merchant_id, "seed-pre-cap-exhausted", 250000, 5000, now_iso)
            )

        res = process_payment(
            wallet_id=wallet_id,
            merchant_id=merchant_id,
            amount_paise=10000,
            idempotency_key=str(uuid.uuid4()),
            authenticated_student_id="test_student_cap_exhausted"
        )
        self.assertEqual(res["raw_cashback_paise"], 200)
        self.assertEqual(res["cashback_paise"], 0, "Cashback must be 0 when monthly cap is fully exhausted")

    # -------------------------------------------------------------
    # Security, Idempotency & Balance Controls (Part C Design)
    # -------------------------------------------------------------

    def test_idempotency_prevents_duplicate_debit(self):
        """Verifies UNIQUE(wallet_id, idempotency_key) prevents duplicate debits."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO WALLET (student_id, tier, balance_paise) VALUES (?, ?, ?);",
                ("test_idempotency_student", "BASIC", 50000)
            )
            wallet_id = cursor.lastrowid
            cursor.execute("SELECT merchant_id FROM MERCHANT WHERE category_code = 'CANTEEN' LIMIT 1;")
            merchant_id = cursor.fetchone()[0]

        test_key = "idemp-key-" + str(uuid.uuid4())

        # First attempt: succeeds
        res1 = process_payment(
            wallet_id=wallet_id,
            merchant_id=merchant_id,
            amount_paise=10000,
            idempotency_key=test_key,
            authenticated_student_id="test_idempotency_student"
        )
        self.assertFalse(res1["is_idempotent_replay"])
        first_balance = res1["new_balance_paise"]

        # Second attempt with IDENTICAL key: must return original transaction and NOT debit again
        res2 = process_payment(
            wallet_id=wallet_id,
            merchant_id=merchant_id,
            amount_paise=10000,
            idempotency_key=test_key,
            authenticated_student_id="test_idempotency_student"
        )
        self.assertTrue(res2["is_idempotent_replay"])
        self.assertEqual(res2["current_balance_paise"], first_balance)
        self.assertEqual(res2["transaction_id"], res1["transaction_id"])

    def test_security_ownership_check(self):
        """Verifies that student A cannot pay using student B's wallet."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT wallet_id FROM WALLET WHERE student_id = 'rahul_2026';")
            rahuls_wallet_id = cursor.fetchone()[0]
            cursor.execute("SELECT merchant_id FROM MERCHANT WHERE category_code = 'CANTEEN' LIMIT 1;")
            merchant_id = cursor.fetchone()[0]

        # Hacker tries to spend from Rahul's wallet while authenticated as 'priya_2026'
        with self.assertRaises(OwnershipViolation):
            process_payment(
                wallet_id=rahuls_wallet_id,
                merchant_id=merchant_id,
                amount_paise=1000,
                idempotency_key=str(uuid.uuid4()),
                authenticated_student_id="priya_2026"  # Not the owner!
            )

    def test_insufficient_balance_rejected(self):
        """Verifies that payment fails safely if balance is insufficient."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO WALLET (student_id, tier, balance_paise) VALUES (?, ?, ?);",
                ("test_low_balance_student", "BASIC", 500)  # Only ₹5
            )
            wallet_id = cursor.lastrowid
            cursor.execute("SELECT merchant_id FROM MERCHANT WHERE category_code = 'CANTEEN' LIMIT 1;")
            merchant_id = cursor.fetchone()[0]

        with self.assertRaises(InsufficientBalance):
            process_payment(
                wallet_id=wallet_id,
                merchant_id=merchant_id,
                amount_paise=10000,  # ₹100 > ₹5
                idempotency_key=str(uuid.uuid4()),
                authenticated_student_id="test_low_balance_student"
            )


if __name__ == "__main__":
    unittest.main()

