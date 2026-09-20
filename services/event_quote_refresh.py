"""Refresh executable evidence without preserving obsolete quotes or depth."""
QUOTE_FIELDS = ('yes_bid', 'yes_ask', 'no_bid', 'no_ask', 'yes_bid_size',
                'yes_ask_size', 'no_bid_size', 'no_ask_size', 'quote_as_of',
                'timestamp', 'updated_at', 'quote_time', 'last_trade_time', 'trade_time',
                'quote_retrieved_at', 'quote_time_basis', 'quote_timestamp_source',
                'quote_provider_timestamp_raw')


def replace_quote(market, quote):
    for field in QUOTE_FIELDS:
        market.pop(field, None)
    if not quote or quote.get('symbol') != market.get('symbol'):
        raise ValueError('Provider returned no matching fresh Event quote.')
    market.update(quote)
    return market


def refresh_markets(markets, connection, guard=lambda: None):
    from datetime import datetime
    from event_algo import _market_cutoff
    from services.webull_service import get_webull_event_snapshots
    selected = [m for m in markets if (_market_cutoff(m) or datetime.min) > datetime.utcnow()
                and str(m.get('tradable_status') or '').upper() != 'CO']
    errors = []
    for start in range(0, len(selected), 100):
        guard()
        batch = selected[start:start + 100]
        try:
            quotes = get_webull_event_snapshots(*connection, symbols=[m['symbol'] for m in batch], force=True)
        except Exception as exc:
            for market in batch:
                for field in QUOTE_FIELDS:
                    market.pop(field, None)
            errors.append('Event quote refresh failed: ' + type(exc).__name__)
            continue
        for market in batch:
            try:
                replace_quote(market, quotes.get(market['symbol']))
            except ValueError as exc:
                errors.append(market['symbol'] + ': ' + str(exc))
        guard()
    return errors


def expire_prediction(market, now, ttl):
    """Repricing must not extend the life of a forecast from an earlier batch."""
    from services.event_market_timing import observation_time
    metadata = market.get('_model_metadata') or {}
    if metadata.get('status') not in ('success', 'cached'):
        return
    timestamp = observation_time(metadata.get('cached_at') or metadata.get('generated_at'))
    if timestamp is not None and -5 <= (observation_time(now) - timestamp).total_seconds() <= ttl:
        return
    for field in ('model_probability_yes', 'model_confidence', 'probability_yes', 'confidence'):
        market.pop(field, None)
    market['_model_metadata'] = {**metadata, 'status': 'stale',
                                 'error': 'Forecast expired or has no verifiable generation time; awaiting reevaluation'}
