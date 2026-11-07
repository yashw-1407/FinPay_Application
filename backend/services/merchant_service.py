"""
FinPay Merchant Service.
Provides merchant directory and associated cashback rules.
"""

from typing import List, Dict, Any
from backend.database import get_db
from backend.repository import FinPayRepository


def get_all_merchants() -> List[Dict[str, Any]]:
    """Fetches all registered merchants with their category rules."""
    with get_db() as conn:
        return FinPayRepository.get_all_merchants(conn)


def get_merchant_details(merchant_id: int) -> Dict[str, Any]:
    """Fetches details for a single merchant."""
    with get_db() as conn:
        return FinPayRepository.get_merchant(conn, merchant_id)

