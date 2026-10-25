"""Currency conversion for RANKING quotes only (€0.40 vs ¥58 can't be compared as raw numbers).

Fixed, approximate rates. A real system would load daily rates (e.g. from the ECB) into a table and convert at
the quote date. Stored prices are never converted: the original price and currency stay the source of truth.
"""

from decimal import Decimal

USD_PER_UNIT = {"USD": 1.0, "EUR": 1 / 0.92, "JPY": 1 / 150, "CNY": 1 / 7.2}


def to_usd(amount: float | Decimal, currency: str) -> float | None:
    """Approximate USD value, or None for a currency we have no rate for (it then sorts last)."""
    rate = USD_PER_UNIT.get(currency)
    return None if rate is None else round(float(amount) * rate, 4)
