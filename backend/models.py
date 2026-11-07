"""
FinPay Domain Models, Constants and Conversions.
Ensures consistency with integer paise, basis points, and enumerations.
"""

from enum import Enum
from typing import Optional, Dict, Any


class WalletTierEnum(str, Enum):
    BASIC = "BASIC"
    PRIME = "PRIME"
    PREMIUM = "PREMIUM"


class CategoryCodeEnum(str, Enum):
    CANTEEN = "CANTEEN"
    STATIONERY = "STATIONERY"
    TRANSPORT = "TRANSPORT"
    HOSTEL = "HOSTEL"
    ONLINE = "ONLINE"
    TOPUP = "TOPUP"


def paise_to_rupees_str(paise: int) -> str:
    """Format paise to human-readable Indian Rupee string (e.g. 10050 paise -> '₹100.50')."""
    sign = "-" if paise < 0 else ""
    abs_paise = abs(paise)
    rupees = abs_paise // 100
    remainder = abs_paise % 100
    return f"{sign}₹{rupees}.{remainder:02d}"


def rupees_to_paise(rupees: float) -> int:
    """Converts rupee decimal to whole paise (floor/int)."""
    return int(round(rupees * 100))

