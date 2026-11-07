"""
End-to-End API Test Suite for FinPay.
Tests all REST API endpoints, JWT role enforcement, wallet operations,
idempotency replay, preview calculations, and monthly reconciliation.
"""

import unittest
import json
import uuid
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.app import app
from backend.database import init_db


class TestFinPayEndToEndAPI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db(force=True)
        cls.client = app.test_client()

    def get_token(self, user_id: str = "rahul_2026", role: str = "student") -> str:
        res = self.client.post("/api/auth/token", json={"user_id": user_id, "role": role})
        self.assertEqual(res.status_code, 200)
        return json.loads(res.data)["token"]

    def test_01_auth_users_and_token(self):
        """Tests fetching user directory and issuing TalentHub JWT tokens."""
        res = self.client.get("/api/auth/users")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIn("users", data)
        self.assertGreaterEqual(len(data["users"]), 4)

        # Issue token for Rahul
        token = self.get_token("rahul_2026", "student")
        self.assertTrue(len(token) > 20)

    def test_02_wallet_summary_with_jwt(self):
        """Tests getting authenticated student's wallet summary."""
        token = self.get_token("rahul_2026", "student")
        res = self.client.get("/api/wallet", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data["student_id"], "rahul_2026")
        self.assertEqual(data["tier"], "BASIC")
        self.assertEqual(data["balance_paise"], 50000)  # Seed ₹500
        self.assertEqual(len(data["category_limits"]), 6)

    def test_03_wallet_tier_upgrade(self):
        """Tests upgrading student wallet tier from BASIC to PRIME."""
        token = self.get_token("rahul_2026", "student")
        res = self.client.post(
            "/api/wallet/tier",
            headers={"Authorization": f"Bearer {token}"},
            json={"tier": "PRIME"}
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data["wallet"]["tier"], "PRIME")

        # Revert back to BASIC for subsequent tests
        self.client.post(
            "/api/wallet/tier",
            headers={"Authorization": f"Bearer {token}"},
            json={"tier": "BASIC"}
        )

    def test_04_merchants_list(self):
        """Tests listing campus merchants and category rules."""
        res = self.client.get("/api/merchants")
        self.assertEqual(res.status_code, 200)
        merchants = json.loads(res.data)["merchants"]
        self.assertGreaterEqual(len(merchants), 10)
        canteen_m = next(m for m in merchants if m["category_code"] == "CANTEEN")
        self.assertEqual(canteen_m["rate_bps"], 200)
        self.assertEqual(canteen_m["basic_monthly_cap_paise"], 5000)

    def test_05_preview_payment_cashback(self):
        """Tests live reactive cashback calculation preview."""
        token = self.get_token("rahul_2026", "student")
        res = self.client.post(
            "/api/payment/preview",
            headers={"Authorization": f"Bearer {token}"},
            json={"merchant_id": 1, "amount_paise": 10000}  # ₹100 at Canteen
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data["raw_cashback_paise"], 200)
        self.assertEqual(data["awarded_cashback_paise"], 200)

    def test_06_process_payment_and_idempotency(self):
        """Tests executing payment and verifying duplicate idempotency rejection."""
        token = self.get_token("rahul_2026", "student")
        key = "e2e-idemp-" + str(uuid.uuid4())

        # 1st Payment: ₹100 (10,000 paise) at Canteen (Merchant 1)
        res1 = self.client.post(
            "/api/payment/process",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "merchant_id": 1,
                "amount_paise": 10000,
                "idempotency_key": key
            }
        )
        self.assertEqual(res1.status_code, 200)
        d1 = json.loads(res1.data)
        self.assertFalse(d1["is_idempotent_replay"])
        self.assertEqual(d1["amount_paise"], 10000)
        self.assertEqual(d1["cashback_paise"], 200)
        # Previous balance 50,000 -> 50,000 - 10,000 + 200 = 40,200
        self.assertEqual(d1["new_balance_paise"], 40200)

        # 2nd Payment with exact same idempotency key -> MUST replay without debiting again
        res2 = self.client.post(
            "/api/payment/process",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "merchant_id": 1,
                "amount_paise": 10000,
                "idempotency_key": key
            }
        )
        self.assertEqual(res2.status_code, 200)
        d2 = json.loads(res2.data)
        self.assertTrue(d2["is_idempotent_replay"])
        self.assertEqual(d2["current_balance_paise"], 40200)
        self.assertEqual(d2["transaction_id"], d1["transaction_id"])

    def test_07_wallet_topup(self):
        """Tests adding funds to wallet via top-up."""
        token = self.get_token("rahul_2026", "student")
        res = self.client.post(
            "/api/wallet/topup",
            headers={"Authorization": f"Bearer {token}"},
            json={"amount_paise": 20000}  # Add ₹200
        )
        self.assertEqual(res.status_code, 200)
        d = json.loads(res.data)
        self.assertEqual(d["amount_paise"], 20000)
        self.assertEqual(d["cashback_paise"], 0)  # Top-up has 0 cashback
        # Balance was 40,200 + 20,000 = 60,200
        self.assertEqual(d["new_balance_paise"], 60200)

    def test_08_reconciliation_role_security(self):
        """
        Tests Security Control B from Lab 4 Part C:
        - Student role cannot access reconciliation (403 Forbidden).
        - Finance / Admin role can access reconciliation (200 OK).
        """
        # Student attempt -> 403 Forbidden
        student_token = self.get_token("rahul_2026", "student")
        res_denied = self.client.get(
            "/api/reconciliation",
            headers={"Authorization": f"Bearer {student_token}"}
        )
        self.assertEqual(res_denied.status_code, 403)

        # Finance officer attempt -> 200 OK
        admin_token = self.get_token("finance_admin", "finance")
        res_allowed = self.client.get(
            "/api/reconciliation",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        self.assertEqual(res_allowed.status_code, 200)
        recon_data = json.loads(res_allowed.data)
        self.assertIn("summary", recon_data)
        self.assertIn("category_breakdown", recon_data)
        self.assertIn("merchant_breakdown", recon_data)
        self.assertGreaterEqual(recon_data["summary"]["total_transactions"], 1)

    def test_09_interactive_tests_endpoint(self):
        """Tests the Lab 4 interactive boundary tests runner endpoint."""
        res = self.client.get("/api/tests/run")
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data["all_passed"])
        self.assertEqual(data["total_tests"], 10)
        self.assertEqual(data["passed_tests"], 10)


if __name__ == "__main__":
    unittest.main()
