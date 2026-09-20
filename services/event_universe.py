"""Use the portfolio Event watchlist for collection and consumption alike."""
import json
from portfolio_algo_models import PortfolioStrategyConfig


def repair_legacy_default_series():
    """Replace only the invalid shipped S&P series; retain all other settings."""
    from core.extensions import db
    changed = 0
    for portfolio in PortfolioStrategyConfig.query.with_for_update().all():
        try:
            watches = json.loads(portfolio.watchlists_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(watches, dict) or not isinstance(watches.get('events'), list) or 'KXINXD' not in watches['events']:
            continue
        events = []
        for symbol in watches['events']:
            replacement = 'KXINXU' if symbol == 'KXINXD' else symbol
            if replacement not in events:
                events.append(replacement)
        watches['events'] = events
        portfolio.watchlists_json = json.dumps(watches)
        changed += 1
    db.session.commit()
    return changed


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
