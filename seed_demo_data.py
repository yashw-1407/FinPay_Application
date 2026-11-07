"""
FinPay Scenario Demo Seeder.
Simulates realistic transactions across campus students and merchants
to showcase monthly limits, tier multipliers, idempotency, and reconciliation.
"""

import os
import sys
import uuid
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.database import init_db, get_db
from backend.services.payment_service import process_payment


def seed_demo_scenario():
    print("Initializing clean FinPay database...")
    init_db(force=True)

    with get_db() as conn:
        cursor = conn.cursor()
        # Fetch merchants
        cursor.execute("SELECT merchant_id, merchant_name, category_code FROM MERCHANT;")
        merchants = {row["category_code"]: row["merchant_id"] for row in cursor.fetchall()}

        # Fetch student wallets
        cursor.execute("SELECT wallet_id, student_id, tier FROM WALLET;")
        wallets = {row["student_id"]: row["wallet_id"] for row in cursor.fetchall()}

    print(f"Loaded {len(wallets)} student wallets and {len(merchants)} merchant categories.")

    # 1. Rahul (BASIC tier) pays at Canteen: ₹100 -> earns ₹2 (200p) cashback
    print("Simulating Rahul's payments...")
    process_payment(
        wallet_id=wallets["rahul_2026"],
        merchant_id=merchants["CANTEEN"],
        amount_paise=10000,
        idempotency_key="demo-rahul-canteen-1",
        authenticated_student_id="rahul_2026"
    )

    # Rahul buys stationery: ₹80 (8000p) at Bookstore -> earns 1% = 80p
    process_payment(
        wallet_id=wallets["rahul_2026"],
        merchant_id=merchants["STATIONERY"],
        amount_paise=8000,
        idempotency_key="demo-rahul-stationery-1",
        authenticated_student_id="rahul_2026"
    )

    # Rahul takes Shuttle Bus: ₹30 (3000p) at Transport -> earns 3% = 90p
    process_payment(
        wallet_id=wallets["rahul_2026"],
        merchant_id=merchants["TRANSPORT"],
        amount_paise=3000,
        idempotency_key="demo-rahul-transport-1",
        authenticated_student_id="rahul_2026"
    )

    # 2. Priya (PRIME tier: 1.5x) pays at Canteen: ₹150 (15000p) -> earns 3% = 450p
    print("Simulating Priya's payments (PRIME tier)...")
    process_payment(
        wallet_id=wallets["priya_2026"],
        merchant_id=merchants["CANTEEN"],
        amount_paise=15000,
        idempotency_key="demo-priya-canteen-1",
        authenticated_student_id="priya_2026"
    )

    # 3. Amit (PREMIUM tier: 2.0x) pays Hostel Mess: ₹500 (50000p) -> earns 1% = 500p
    print("Simulating Amit's payments (PREMIUM tier)...")
    process_payment(
        wallet_id=wallets["amit_2026"],
        merchant_id=merchants["HOSTEL"],
        amount_paise=50000,
        idempotency_key="demo-amit-hostel-1",
        authenticated_student_id="amit_2026"
    )

    print("\n✔ Demo campus transactions seeded successfully!")
    print("Rahul, Priya, and Amit now have live balances, cashback earnings, and transaction histories.")


if __name__ == "__main__":
    seed_demo_scenario()
