from log import logger

def _coerce_float(value, default=None):
    """Safely convert user-provided values to float, returning default on failure."""
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def format_quantity(quantity, step_size):
    """Format quantity to match step size requirement"""
    from decimal import Decimal, ROUND_DOWN
    qty = Decimal(str(quantity))
    step = Decimal(str(step_size))
    step_str = f"{step:.10f}".rstrip('0')
    precision = len(step_str.split('.')[-1]) if '.' in step_str else 0
    qty = (qty / step).quantize(Decimal('1'), rounding=ROUND_DOWN) * step
    if precision == 0:
        return int(qty)
    else:
        return float(qty.quantize(Decimal(10) ** -precision, rounding=ROUND_DOWN))

def format_price(price, tick_size):
    """Format price to match tick size requirement"""
    from decimal import Decimal, ROUND_DOWN
    if price <= 0: return 0.0
    prc = Decimal(str(price))
    tick = Decimal(str(tick_size))
    tick_str = f"{tick:.10f}".rstrip('0')
    precision = len(tick_str.split('.')[-1]) if '.' in tick_str else 0
    prc = (prc / tick).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick
    if precision == 0:
        return int(prc)
    else:
        return float(prc.quantize(Decimal(10) ** -precision, rounding=ROUND_DOWN))
