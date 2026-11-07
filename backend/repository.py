"""
FinPay Repository Layer.
Handles parameterized queries and database access for Wallets, Merchants, Rules, and Transactions.
"""

import sqlite3
from typing import Optional, List, Dict, Any
from backend.database import get_db, get_db_connection


class FinPayRepository:

    @staticmethod
    def get_tier(conn: sqlite3.Connection, tier: str) -> Optional[Dict[str, Any]]:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT tier, rate_mult_x10, cap_mult_x10 FROM WALLET_TIER WHERE tier = ?;",
            (tier,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_all_tiers(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        cursor = conn.cursor()
        cursor.execute("SELECT tier, rate_mult_x10, cap_mult_x10 FROM WALLET_TIER;")
        return [dict(r) for r in cursor.fetchall()]

    @staticmethod
    def get_cashback_rule(conn: sqlite3.Connection, category_code: str) -> Optional[Dict[str, Any]]:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT category_code, rate_bps, basic_monthly_cap_paise FROM CASHBACK_RULE WHERE category_code = ?;",
            (category_code,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_all_cashback_rules(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        cursor = conn.cursor()
        cursor.execute("SELECT category_code, rate_bps, basic_monthly_cap_paise FROM CASHBACK_RULE;")
        return [dict(r) for r in cursor.fetchall()]

    @staticmethod
    def get_merchant(conn: sqlite3.Connection, merchant_id: int) -> Optional[Dict[str, Any]]:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT m.merchant_id, m.merchant_name, m.category_code,
                   c.rate_bps, c.basic_monthly_cap_paise
            FROM MERCHANT m
            JOIN CASHBACK_RULE c ON m.category_code = c.category_code
            WHERE m.merchant_id = ?;
            """,
            (merchant_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_all_merchants(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT m.merchant_id, m.merchant_name, m.category_code,
                   c.rate_bps, c.basic_monthly_cap_paise
            FROM MERCHANT m
            JOIN CASHBACK_RULE c ON m.category_code = c.category_code
            ORDER BY m.category_code, m.merchant_name;
            """
        )
        return [dict(r) for r in cursor.fetchall()]

    @staticmethod
    def get_wallet_by_id(conn: sqlite3.Connection, wallet_id: int) -> Optional[Dict[str, Any]]:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT w.wallet_id, w.student_id, w.tier, w.balance_paise,
                   t.rate_mult_x10, t.cap_mult_x10
            FROM WALLET w
            JOIN WALLET_TIER t ON w.tier = t.tier
            WHERE w.wallet_id = ?;
            """,
            (wallet_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_wallet_by_student_id(conn: sqlite3.Connection, student_id: str) -> Optional[Dict[str, Any]]:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT w.wallet_id, w.student_id, w.tier, w.balance_paise,
                   t.rate_mult_x10, t.cap_mult_x10
            FROM WALLET w
            JOIN WALLET_TIER t ON w.tier = t.tier
            WHERE w.student_id = ?;
            """,
            (student_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    def update_wallet_balance(conn: sqlite3.Connection, wallet_id: int, new_balance_paise: int):
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE WALLET SET balance_paise = ? WHERE wallet_id = ?;",
            (new_balance_paise, wallet_id)
        )

    @staticmethod
    def update_wallet_tier(conn: sqlite3.Connection, wallet_id: int, new_tier: str):
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE WALLET SET tier = ? WHERE wallet_id = ?;",
            (new_tier, wallet_id)
        )

    @staticmethod
    def get_transaction_by_idempotency(conn: sqlite3.Connection, wallet_id: int, idempotency_key: str) -> Optional[Dict[str, Any]]:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT t.transaction_id, t.wallet_id, t.merchant_id, t.idempotency_key,
                   t.amount_paise, t.cashback_paise, t.created_at,
                   m.merchant_name, m.category_code
            FROM "TRANSACTION" t
            JOIN MERCHANT m ON t.merchant_id = m.merchant_id
            WHERE t.wallet_id = ? AND t.idempotency_key = ?;
            """,
            (wallet_id, idempotency_key)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_transaction(conn: sqlite3.Connection, wallet_id: int, merchant_id: int,
                           idempotency_key: str, amount_paise: int, cashback_paise: int,
                           created_at: str) -> int:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO "TRANSACTION" (wallet_id, merchant_id, idempotency_key, amount_paise, cashback_paise, created_at)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (wallet_id, merchant_id, idempotency_key, amount_paise, cashback_paise, created_at)
        )
        return cursor.lastrowid

    @staticmethod
    def get_monthly_cashback_sum(conn: sqlite3.Connection, wallet_id: int, category_code: str, month_str: str) -> int:
        """
        Calculates derived /monthly_cashback for a given wallet, category, and month (YYYY-MM).
        Uses index on (wallet_id, created_at).
        """
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COALESCE(SUM(t.cashback_paise), 0)
            FROM "TRANSACTION" t
            JOIN MERCHANT m ON t.merchant_id = m.merchant_id
            WHERE t.wallet_id = ?
              AND m.category_code = ?
              AND strftime('%Y-%m', t.created_at) = ?;
            """,
            (wallet_id, category_code, month_str)
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def get_monthly_cashback_all_categories(conn: sqlite3.Connection, wallet_id: int, month_str: str) -> Dict[str, int]:
        """Returns a dict of category_code -> total_cashback_earned_paise for the month."""
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT m.category_code, COALESCE(SUM(t.cashback_paise), 0) as total_cashback
            FROM "TRANSACTION" t
            JOIN MERCHANT m ON t.merchant_id = m.merchant_id
            WHERE t.wallet_id = ?
              AND strftime('%Y-%m', t.created_at) = ?
            GROUP BY m.category_code;
            """,
            (wallet_id, month_str)
        )
        results = {}
        for r in cursor.fetchall():
            results[r["category_code"]] = int(r["total_cashback"])
        return results

    @staticmethod
    def get_transactions_for_wallet(conn: sqlite3.Connection, wallet_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT t.transaction_id, t.wallet_id, t.merchant_id, t.idempotency_key,
                   t.amount_paise, t.cashback_paise, t.created_at,
                   m.merchant_name, m.category_code
            FROM "TRANSACTION" t
            JOIN MERCHANT m ON t.merchant_id = m.merchant_id
            WHERE t.wallet_id = ?
            ORDER BY t.transaction_id DESC
            LIMIT ?;
            """,
            (wallet_id, limit)
        )
        return [dict(r) for r in cursor.fetchall()]

    @staticmethod
    def get_all_transactions(conn: sqlite3.Connection, month_str: Optional[str] = None) -> List[Dict[str, Any]]:
        cursor = conn.cursor()
        if month_str:
            cursor.execute(
                """
                SELECT t.transaction_id, t.wallet_id, w.student_id, t.merchant_id,
                       m.merchant_name, m.category_code, t.idempotency_key,
                       t.amount_paise, t.cashback_paise, t.created_at
                FROM "TRANSACTION" t
                JOIN WALLET w ON t.wallet_id = w.wallet_id
                JOIN MERCHANT m ON t.merchant_id = m.merchant_id
                WHERE strftime('%Y-%m', t.created_at) = ?
                ORDER BY t.transaction_id DESC;
                """,
                (month_str,)
            )
        else:
            cursor.execute(
                """
                SELECT t.transaction_id, t.wallet_id, w.student_id, t.merchant_id,
                       m.merchant_name, m.category_code, t.idempotency_key,
                       t.amount_paise, t.cashback_paise, t.created_at
                FROM "TRANSACTION" t
                JOIN WALLET w ON t.wallet_id = w.wallet_id
                JOIN MERCHANT m ON t.merchant_id = m.merchant_id
                ORDER BY t.transaction_id DESC;
                """
            )
        return [dict(r) for r in cursor.fetchall()]

