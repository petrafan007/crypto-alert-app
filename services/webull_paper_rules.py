"""Dependency-free business rules for Webull paper trading."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

EQUITY_LIKE_TYPES = {'EQUITY', 'STOCK', 'ETF'}
KNOWN_ETF_SYMBOLS = {
    'SPY', 'QQQ', 'IWM', 'DIA', 'VTI', 'VOO', 'IVV', 'VEA', 'VWO', 'EFA',
    'EEM', 'AGG', 'BND', 'TLT', 'GLD', 'SLV', 'USO', 'XLF', 'XLK', 'XLE',
}
DEFERRED_ORDER_TYPES = {
    'STOP_LOSS', 'STOP_LOSS_LIMIT', 'TRAILING_STOP_LOSS',
    'MARKET_ON_OPEN', 'MARKET_ON_CLOSE', 'LIMIT_ON_OPEN',
}
ACTIVE_PAPER_ORDER_STATUSES = {'WORKING', 'OPEN', 'PENDING', 'PARTIALLY FILLED', 'PARTIALLY_FILLED'}
PAPER_SELL_SIDES = {'SELL', 'SELL_TO_CLOSE'}
PAPER_ORDER_TYPE_LABELS = {
    'MARKET': 'Market',
    'LIMIT': 'Limit',
    'STOP_LOSS': 'Stop Loss',
    'STOP_LOSS_LIMIT': 'Stop Loss Limit',
    'TRAILING_STOP_LOSS': 'Trailing Stop',
    'MARKET_ON_OPEN': 'Market on Open (MOO)',
    'MARKET_ON_CLOSE': 'Market on Close (MOC)',
    'LIMIT_ON_OPEN': 'Limit on Open (LOO)',
}


def canonical_paper_instrument_type(symbol: str, instrument_type: str) -> str:
    """Preserve ETF identity and normalize aliases used by paper positions."""
    clean_symbol = str(symbol or '').upper().strip()
    clean_type = str(instrument_type or 'EQUITY').upper().strip()
    if clean_type in EQUITY_LIKE_TYPES:
        return 'ETF' if clean_type == 'ETF' or clean_symbol in KNOWN_ETF_SYMBOLS else 'EQUITY'
    if clean_type == 'OPTIONS':
        return 'OPTION'
    if clean_type == 'FUTURE':
        return 'FUTURES'
    return clean_type


def us_options_market_is_open(now=None) -> bool:
    """Return whether the regular U.S. options session is currently open."""
    eastern = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/New_York'))
    if eastern.weekday() >= 5:
        return False
    current_minutes = eastern.hour * 60 + eastern.minute
    return 9 * 60 + 30 <= current_minutes < 16 * 60


def paper_order_fills_immediately(order_type: str, instrument_type: str = None, now=None) -> bool:
    """Conditional orders and closed-session options remain in the working ledger."""
    clean_instrument = canonical_paper_instrument_type('', instrument_type or '')
    if clean_instrument == 'OPTION' and not us_options_market_is_open(now):
        return False
    return str(order_type or '').upper().strip() not in DEFERRED_ORDER_TYPES


def paper_order_type_label(order_type: str) -> str:
    """Return a user-facing caption while preserving provider codes in storage."""
    clean = str(order_type or '').upper().strip()
    return PAPER_ORDER_TYPE_LABELS.get(clean, clean.replace('_', ' ').title() or 'Order')


def paper_position_valuation(side: str, quantity: float, cost_price: float, current_price: float, multiplier: int = 1):
    """Return signed market value, cost basis, and unrealized P&L."""
    qty = float(quantity or 0.0)
    cost = float(cost_price or 0.0)
    current = float(current_price or 0.0)
    contract_multiplier = int(multiplier or 1)
    absolute_market_value = qty * current * contract_multiplier
    cost_basis = qty * cost * contract_multiplier
    is_short = str(side or '').upper() == 'SHORT'
    return {
        'market_value': -absolute_market_value if is_short else absolute_market_value,
        'cost_basis': cost_basis,
        'unrealized_pnl': cost_basis - absolute_market_value if is_short else absolute_market_value - cost_basis,
    }


def paper_reservation_group(order_id: str) -> str:
    """Collapse mutually exclusive bracket/combo legs into one reservation group."""
    clean_order_id = str(order_id or '').upper().strip()
    if clean_order_id.endswith(('_TP', '_SL')):
        return clean_order_id.rsplit('_', 1)[0]
    if clean_order_id.startswith('SIM_COMBO_') and '_LEG' in clean_order_id:
        return clean_order_id.rsplit('_LEG', 1)[0]
    return clean_order_id


def grouped_reserved_quantity(orders, reserving_sides=None) -> float:
    """Return shares reserved by active sell orders without double-counting OCO siblings."""
    allowed_sides = {str(side).upper().strip() for side in (reserving_sides or PAPER_SELL_SIDES)}
    groups = {}
    for order in orders or []:
        read = order.get if isinstance(order, dict) else lambda key, default=None: getattr(order, key, default)
        status = str(read('status', '') or '').upper().strip()
        side = str(read('side', '') or '').upper().strip()
        if status not in ACTIVE_PAPER_ORDER_STATUSES or side not in allowed_sides:
            continue
        quantity = float(read('quantity', 0.0) or 0.0)
        filled_quantity = float(read('filled_quantity', 0.0) or 0.0)
        outstanding = max(0.0, quantity - filled_quantity)
        group = paper_reservation_group(read('order_id', ''))
        groups[group] = max(groups.get(group, 0.0), outstanding)
    return sum(groups.values())
