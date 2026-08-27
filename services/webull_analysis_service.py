"""Read-only market context helpers for the Webull AI research workspace."""


def build_webull_market_snapshot(bars, currency='USD'):
    """Summarize normalized Webull bars without inventing unavailable data."""
    closes = [float(bar['close']) for bar in (bars or []) if bar.get('close') not in (None, '')]
    if not closes:
        return {
            'currency': currency or 'USD', 'last_price': None, 'bar_count': 0,
            'changes': {}, 'context': 'No Webull price bars were available for this holding.',
        }

    latest = closes[-1]
    changes = {}
    for label, periods in (('1 bar', 1), ('5 bars', 5), ('20 bars', 20)):
        if len(closes) > periods and closes[-(periods + 1)] > 0:
            changes[label] = round((latest / closes[-(periods + 1)] - 1) * 100, 2)
    change_text = ', '.join(f'{label}: {value:+.2f}%' for label, value in changes.items()) or 'not enough bars for comparative change'
    return {
        'currency': currency or 'USD', 'last_price': latest, 'bar_count': len(closes), 'changes': changes,
        'context': f'Webull market data: latest price {latest:,.4f} {currency or "USD"}; {len(closes)} bars; changes: {change_text}.',
    }
