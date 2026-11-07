"""
FinPay SQLite Database Connection & Initialization
Adheres strictly to the Lab 4 Final Detailed Design (Option A: RDBMS-only, 3NF/BCNF normalized).
Stores all monetary values as integer paise (no floats) and rates in basis points (bps).
"""

import sqlite3
import os
from typing import Generator
from contextlib import contextmanager

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DB_DIR, "finpay.db")


def get_db_connection() -> sqlite3.Connection:
    """Creates a connection to SQLite with foreign keys enforced and row_factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for SQLite database transactions."""
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(force: bool = False):
    """
    Initializes the FinPay database tables and seeds reference data.
    If force=True, drops and recreates tables.
    """
    with get_db() as conn:
        cursor = conn.cursor()

        if force:
            cursor.executescript("""
                DROP TABLE IF EXISTS "TRANSACTION";
                DROP TABLE IF EXISTS MERCHANT;
                DROP TABLE IF EXISTS WALLET;
                DROP TABLE IF EXISTS CASHBACK_RULE;
                DROP TABLE IF EXISTS WALLET_TIER;
            """)

        # 1. WALLET_TIER Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS WALLET_TIER (
                tier TEXT PRIMARY KEY,
                rate_mult_x10 INTEGER NOT NULL CHECK(rate_mult_x10 > 0),
                cap_mult_x10 INTEGER NOT NULL CHECK(cap_mult_x10 > 0)
            );
        """)

        # 2. CASHBACK_RULE Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS CASHBACK_RULE (
                category_code TEXT PRIMARY KEY,
                rate_bps INTEGER NOT NULL CHECK(rate_bps >= 0),
                basic_monthly_cap_paise INTEGER NOT NULL CHECK(basic_monthly_cap_paise >= 0)
            );
        """)

        # 3. WALLET Table (student_id UNIQUE -> TalentHub student)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS WALLET (
                wallet_id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT UNIQUE NOT NULL,
                tier TEXT NOT NULL,
                balance_paise INTEGER NOT NULL CHECK(balance_paise >= 0),
                FOREIGN KEY(tier) REFERENCES WALLET_TIER(tier) ON DELETE RESTRICT
            );
        """)

        # 4. MERCHANT Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS MERCHANT (
                merchant_id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_name TEXT NOT NULL,
                category_code TEXT NOT NULL,
                FOREIGN KEY(category_code) REFERENCES CASHBACK_RULE(category_code) ON DELETE RESTRICT
            );
        """)

        # 5. TRANSACTION Table
        # Constraints: amount_paise > 0, cashback_paise >= 0, UNIQUE(wallet_id, idempotency_key)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS "TRANSACTION" (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_id INTEGER NOT NULL,
                merchant_id INTEGER NOT NULL,
                idempotency_key TEXT NOT NULL,
                amount_paise INTEGER NOT NULL CHECK(amount_paise > 0),
                cashback_paise INTEGER NOT NULL CHECK(cashback_paise >= 0),
                created_at TEXT NOT NULL,
                UNIQUE(wallet_id, idempotency_key),
                FOREIGN KEY(wallet_id) REFERENCES WALLET(wallet_id) ON DELETE RESTRICT,
                FOREIGN KEY(merchant_id) REFERENCES MERCHANT(merchant_id) ON DELETE RESTRICT
            );
        """)

        # Performance index on (wallet_id, created_at) as specified in Lab 4 doc
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_trans_wallet_created
            ON "TRANSACTION" (wallet_id, created_at);
        """)

        # Seed initial fixed data from Lab 4 DDR Specification
        # Seed WALLET_TIER: BASIC (10, 10), PRIME (15, 15), PREMIUM (20, 20)
        cursor.execute("SELECT COUNT(*) FROM WALLET_TIER")
        if cursor.fetchone()[0] == 0:
            tiers = [
                ("BASIC", 10, 10),
                ("PRIME", 15, 15),
                ("PREMIUM", 20, 20),
            ]
            cursor.executemany(
                "INSERT INTO WALLET_TIER (tier, rate_mult_x10, cap_mult_x10) VALUES (?, ?, ?);",
                tiers
            )

        # Seed CASHBACK_RULE: CANTEEN, STATIONERY, TRANSPORT, HOSTEL, ONLINE, TOPUP
        cursor.execute("SELECT COUNT(*) FROM CASHBACK_RULE")
        if cursor.fetchone()[0] == 0:
            rules = [
                ("CANTEEN", 200, 5000),      # 2.0%, ₹50 cap
                ("STATIONERY", 100, 2000),   # 1.0%, ₹20 cap
                ("TRANSPORT", 300, 10000),   # 3.0%, ₹100 cap
                ("HOSTEL", 50, 20000),       # 0.5%, ₹200 cap
                ("ONLINE", 100, 3000),       # 1.0%, ₹30 cap
                ("TOPUP", 0, 0),             # 0%, no cashback
            ]
            cursor.executemany(
                "INSERT INTO CASHBACK_RULE (category_code, rate_bps, basic_monthly_cap_paise) VALUES (?, ?, ?);",
                rules
            )

        # Seed Merchants
        cursor.execute("SELECT COUNT(*) FROM MERCHANT")
        if cursor.fetchone()[0] == 0:
            merchants = [
                ("Campus Central Canteen", "CANTEEN"),
                ("Nescafe Canteen Corner", "CANTEEN"),
                ("University Bookstore & Stationery", "STATIONERY"),
                ("Print & Xerox Centre", "STATIONERY"),
                ("Campus Green Shuttle Bus", "TRANSPORT"),
                ("Metro Campus Feeder", "TRANSPORT"),
                ("Hostel Dining Mess", "HOSTEL"),
                ("Hostel Laundry Service", "HOSTEL"),
                ("University Online Exam Portal", "ONLINE"),
                ("Library Online Subscriptions", "ONLINE"),
                ("FinPay Campus Top-up Desk", "TOPUP"),
            ]
            cursor.executemany(
                "INSERT INTO MERCHANT (merchant_name, category_code) VALUES (?, ?);",
                merchants
            )

        # Seed default test student wallets:
        # 1. Rahul (from Scenario docx): Rahul has BASIC wallet, starts with ₹500 (50,000 paise)
        # 2. Priya (PRIME wallet, starts with ₹1,000 = 100,000 paise)
        # 3. Amit (PREMIUM wallet, starts with ₹2,000 = 200,000 paise)
        cursor.execute("SELECT COUNT(*) FROM WALLET")
        if cursor.fetchone()[0] == 0:
            wallets = [
                ("rahul_2026", "BASIC", 50000),
                ("priya_2026", "PRIME", 100000),
                ("amit_2026", "PREMIUM", 200000),
            ]
            cursor.executemany(
                "INSERT INTO WALLET (student_id, tier, balance_paise) VALUES (?, ?, ?);",
                wallets
            )


if __name__ == "__main__":
    init_db(force=True)
    print("Database initialized successfully at:", DB_PATH)

