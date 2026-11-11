"""Finite-number and KRX tick helpers extracted for offline analysis."""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import math


class TradingError(ValueError):
    pass

def number(value):
    n = float(value)
    if not math.isfinite(n):
        raise TradingError('유효하지 않은 숫자입니다.')
    return n

def tick_price(price, up=False):
    p = number(price)
    if p <= 0:
        raise TradingError('가격은 양수여야 합니다.')
    # KRX ordinary shares (KOSPI/KOSDAQ), official post-2023 schedule.
    step = 1 if p < 2000 else 5 if p < 5000 else 10 if p < 20000 else 50 if p < 50000 else 100 if p < 200000 else 500 if p < 500000 else 1000
    mode = ROUND_CEILING if up else ROUND_FLOOR
    return max(step, int((Decimal(str(p)) / step).to_integral_value(rounding=mode)) * step)
