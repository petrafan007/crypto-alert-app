"""Use the portfolio Event watchlist for collection and consumption alike."""
import json
from portfolio_algo_models import PortfolioStrategyConfig


def configured_universe(user_id, config):
    portfolio = PortfolioStrategyConfig.query.filter_by(user_id=user_id).first()
    if portfolio is not None:
        return {'scope': 'PORTFOLIO_EVENT_SERIES', 'symbols': json.loads(portfolio.watchlists_json).get('events', []), 'durations': []}
    return {'scope': 'STANDALONE_SYMBOL_DURATION', 'symbols': json.loads(config.symbols), 'durations': json.loads(config.durations)}


def collection_targets(user_id, config, connection):
    portfolio = PortfolioStrategyConfig.query.filter_by(user_id=user_id).first()
    if portfolio is None:
        return [(symbol, duration, 'CRYPTO', None) for symbol in json.loads(config.symbols)[:10]
                for duration in json.loads(config.durations)[:8]], []
    watches = json.loads(portfolio.watchlists_json).get('events', [])
    if not watches:
        return [], []
    from services.webull_service import get_webull_event_categories, get_webull_event_series
    targets, missing = [], set(watches)
    for category in get_webull_event_categories(*connection):
        code = category.get('category_code')
        if not code:
            continue
        for series in get_webull_event_series(*connection, category_id=code):
            symbol = series.get('series_symbol')
            if symbol in missing:
                targets.append((symbol, None, code, symbol))
                missing.remove(symbol)
        if not missing:
            break
    return targets, sorted(missing)


def matches_series(market, series):
    return not series or market.get('series_symbol') == series or str(market.get('symbol') or '').startswith(series+'-')
