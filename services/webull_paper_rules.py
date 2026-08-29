"""Dependency-free business rules for Webull paper trading."""

EQUITY_LIKE_TYPES = {'EQUITY', 'STOCK', 'ETF'}
KNOWN_ETF_SYMBOLS = {
    'SPY', 'QQQ', 'IWM', 'DIA', 'VTI', 'VOO', 'IVV', 'VEA', 'VWO', 'EFA',
    'EEM', 'AGG', 'BND', 'TLT', 'GLD', 'SLV', 'USO', 'XLF', 'XLK', 'XLE',
}
DEFERRED_ORDER_TYPES = {
    'STOP_LOSS', 'STOP_LOSS_LIMIT', 'TRAILING_STOP_LOSS',
    'MARKET_ON_OPEN', 'MARKET_ON_CLOSE', 'LIMIT_ON_OPEN',
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


def paper_order_fills_immediately(order_type: str) -> bool:
    """Conditional and auction orders enter the working ledger until triggered."""
    return str(order_type or '').upper().strip() not in DEFERRED_ORDER_TYPES


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
