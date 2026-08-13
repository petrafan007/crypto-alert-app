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
    try:
        prc_val = float(price) if price is not None else 0.0
    except (ValueError, TypeError):
        return 0.0
    if prc_val <= 0: return 0.0
    prc = Decimal(str(prc_val))
    tick = Decimal(str(tick_size))
    step_str = f"{tick:.10f}".rstrip('0')
    precision = len(step_str.split('.')[-1]) if '.' in step_str else 0
    prc = (prc / tick).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick
    if precision == 0:
        return int(prc)
    else:
        return float(prc.quantize(Decimal(10) ** -precision, rounding=ROUND_DOWN))

def normalize_price_str(value, tick_size=None):
    """Normalize and format a price or quantity string for Binance.US API regex (^([0-9]{1,20})(\\.[0-9]{1,20})?$)."""
    if value is None or str(value).strip() == '':
        return None
    try:
        from decimal import Decimal, ROUND_DOWN
        val_float = float(value)
        if val_float <= 0:
            return None
        if tick_size and float(tick_size) > 0:
            tick = Decimal(str(float(tick_size)))
            tick_str = f"{tick:.10f}".rstrip('0')
            precision = len(tick_str.split('.')[-1]) if '.' in tick_str else 0
            prc = (Decimal(str(val_float)) / tick).quantize(Decimal('1'), rounding=ROUND_DOWN) * tick
            if precision == 0:
                return str(int(prc))
            return f"{prc.quantize(Decimal(10) ** -precision, rounding=ROUND_DOWN):f}"
        else:
            d = Decimal(str(val_float))
            s = f"{d:f}"
            if '.' in s:
                s = s.rstrip('0').rstrip('.')
            return s
    except Exception:
        # Fallback ensuring leading digit if it starts with dot
        s = str(value).strip()
        if s.startswith('.'):
            s = '0' + s
        return s
