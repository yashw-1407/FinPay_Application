"""
FinPay Cashback Calculation Algorithm.
Defined in Laboratory 4 – Part B (AI-Assisted Algorithm Design).

Critical Function:
calculate_cashback(amount_paise, rate_bps, tier_mult_x10) -> int

Rules:
- No database access, no decimals.
- Cut off (floor DIV), never round (e.g. 6.66 becomes 6).
- Does NOT apply the monthly limit here – process_payment() does that.
- Handles edge cases: 1 paise, exact boundary amounts, top-up, amount <= 0, 64-bit safe.
"""


class InvalidInput(ValueError):
    """Raised when calculation inputs violate preconditions."""
    pass


def calculate_cashback(amount_paise: int, rate_bps: int, tier_mult_x10: int) -> int:
    """
    Computes raw cashback in integer paise for a single transaction.

    Parameters:
        amount_paise (int): Payment amount in paise (must be > 0).
        rate_bps (int): Category cashback rate in basis points (e.g., 200 for 2.0%, >= 0).
        tier_mult_x10 (int): Multiplier scaled by 10 (10 for BASIC, 15 for PRIME, 20 for PREMIUM, > 0).

    Returns:
        int: Raw cashback in paise (floor cut-off, no rounding).
    """
    if not isinstance(amount_paise, int) or not isinstance(rate_bps, int) or not isinstance(tier_mult_x10, int):
        raise InvalidInput("All inputs must be whole integers.")

    if amount_paise <= 0 or rate_bps < 0 or tier_mult_x10 <= 0:
        raise InvalidInput("Violated constraints: amount_paise > 0, rate_bps >= 0, tier_mult_x10 > 0.")

    # Top-up: 0 bps earns 0 cashback
    if rate_bps == 0:
        return 0

    # 64-bit integer numerator
    # 10000 (from basis points) * 10 (from tier multiplier scale) = 100000
    numerator = amount_paise * rate_bps * tier_mult_x10
    raw_cashback = numerator // 100000  # Floor integer division, cut off, never float

    return raw_cashback

