"""Read-only entitlement probes. Never starts execution or writes observations."""
from datetime import datetime, timedelta

from services import portfolio_engine as engine
from services.portfolio_strategy_data import PortfolioMarketData
from services.portfolio_strategy_signals import in_session


def check_data_access(cfg, provider=None):
    settings = engine.settings_for(cfg)
    watches = engine.loads(cfg.watchlists_json, {})
    report = {}
    data = provider
    for module in engine.MODULES:
        if not settings[module]['enabled']:
            report[module] = {'status': 'DISABLED', 'message': 'New-entry data requests are disabled.'}
            continue
        symbols = watches.get(module, [])
        if not symbols:
            report[module] = {'status': 'IDLE', 'message': 'Watchlist is empty.'}
            continue
        if module == 'events':
            from event_algo import EventStrategyConfig
            row = EventStrategyConfig.query.filter_by(user_id=cfg.user_id).first()
            report[module] = {'status': 'READY' if row and row.enabled and not row.kill_switch else 'DISABLED',
                              'message': 'Event collection must be enabled in its existing controls; fresh eligible decisions are checked during scans.'}
            continue
        symbol, now = symbols[0], datetime.utcnow()
        try:
            data = data or PortfolioMarketData(cfg.user_id)
            instrument = 'EQUITY'
            if module == 'futures':
                symbol, _, _ = data.future(symbol, now)
                instrument = 'FUTURES'
            elif module == 'crypto':
                instrument = 'CRYPTO'
            # Raw snapshots test entitlement even while exchanges are closed.
            from services.webull_service import get_webull_market_snapshot, get_webull_option_contracts, _get_webull_option_snapshots
            quote = get_webull_market_snapshot(*data.connection, symbol=symbol, instrument_type=instrument)
            if module == 'options':
                contracts = get_webull_option_contracts(*data.connection, underlying_symbol=symbol, root_symbol=symbol,
                    start_date=str(now.date()+timedelta(days=20)), end_date=str(now.date()+timedelta(days=65)), max_pages=10)
                standard = [c for c in contracts if c.get('def_type') == 'STANDARD']
                if not standard:
                    raise ValueError('No standard option contracts available.')
                quotes = _get_webull_option_snapshots(*data.connection, symbols=[standard[0]['symbol']])
                if not quotes:
                    raise ValueError('No option snapshots returned.')
            elif module == 'crypto' or in_session(now):
                data.bars(symbol, instrument, now, interval='H1' if module == 'crypto' else 'M1' if module == 'futures' else 'D')
            if not quote:
                raise ValueError('No snapshot returned.')
            report[module] = {'status': 'ACCESS_CONFIRMED',
                'message': f'{symbol}: provider access confirmed. Scan-time freshness, full watchlist, strategy conditions and warm-up still apply.'}
        except Exception as exc:
            report[module] = {'status': engine.data_status(exc), 'message': str(exc)[:300]}
    return report
