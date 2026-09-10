"""Build the complete cross-provider holdings snapshot used by Portfolio Review."""


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _money(value):
    numeric = _number(value, None)
    return "unavailable" if numeric is None else f"${numeric:,.2f}"


def format_portfolio_review_holdings(binance_holdings, webull_rows):
    """Format all visible Binance.US and Webull assets, including cash reserves."""
    lines = []
    for holding in binance_holdings:
        quantity = _number(getattr(holding, 'amount', 0))
        price = _number(
            getattr(holding, 'current_price', None),
            _number(getattr(holding, 'initial_price', 0)),
        )
        lines.append(
            f"- Binance.US | {str(getattr(holding, 'symbol', '')).upper()} | CRYPTO | "
            f"quantity={quantity:g} | current_price={_money(price)} | market_value={_money(quantity * price)}"
        )

    for row in webull_rows:
        quantity = _number(row.get('amount'))
        instrument_type = str(row.get('instrument_type') or 'SECURITY').upper()
        account = str(row.get('account_label') or 'Webull account')
        details = [
            f"quantity={quantity:g}",
            f"current_price={_money(row.get('current_price'))}",
            f"market_value={_money(row.get('current_value'))}",
        ]
        if instrument_type != 'CASH':
            details.extend([
                f"cost_basis={_money(row.get('cost_basis'))}",
                f"unrealized_pnl={_money(row.get('webull_unrealized_pnl'))}",
            ])
        lines.append(
            f"- Webull | {account} | {str(row.get('symbol') or '').upper()} | {instrument_type} | "
            + " | ".join(details)
        )

    return "\n".join(lines) if lines else "No visible portfolio holdings or cash balances."


def build_portfolio_review_holdings(user_id):
    """Load the current unified portfolio and serialize it for the AI workflow."""
    from models import Coin
    from services.webull_import_service import get_webull_portfolio_rows

    binance_holdings = Coin.query.filter(
        Coin.user_id == user_id,
        Coin.hidden == False,
        Coin.amount > 0,
    ).order_by(Coin.symbol.asc()).all()
    webull_rows = get_webull_portfolio_rows(user_id)
    return format_portfolio_review_holdings(binance_holdings, webull_rows)
