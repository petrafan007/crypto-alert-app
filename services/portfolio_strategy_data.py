"""Read-only market data boundary for the isolated quantitative ledger."""
import json
from datetime import timedelta

from core.extensions import db
from portfolio_algo_models import PortfolioMarketObservation
from services.portfolio_strategy_signals import completed_bars, finite, fresh_quote, utc, ET


class PortfolioMarketData:
    def __init__(self, user_id):
        from event_algo import _webull_connection_for_user
        credential, environment = _webull_connection_for_user(user_id)
        self.connection = (credential.webull_app_key, credential.webull_app_secret, environment, credential.webull_access_token)
        self.user_id = user_id
        self.cache = {}

    def bars(self, symbol, instrument, now, interval='D', limit=260):
        from services.webull_service import get_webull_market_bars
        key = (symbol, instrument, interval, limit)
        if key not in self.cache:
            rows = get_webull_market_bars(*self.connection, symbol=symbol, instrument_type=instrument, interval=interval, limit=limit)
            self.cache[key] = completed_bars(rows, now, daily=interval == 'D', seconds=3600 if interval == 'H1' else 60, crypto=instrument == 'CRYPTO')
        bars = self.cache[key]
        if not bars:
            raise ValueError('No completed market candles.')
        # Daily history tolerates weekends/holidays. Quotes have a separate 2-minute gate.
        allowance = 7*86400 if interval == 'D' else 7200 if interval == 'H1' else 180
        if utc(now).timestamp()-bars[-1]['time'] > allowance:
            raise ValueError('Historical candles are stale.')
        return bars

    def quote(self, symbol, instrument, now):
        from services.webull_service import get_webull_market_snapshot
        raw = get_webull_market_snapshot(*self.connection, symbol=symbol, instrument_type=instrument)
        return fresh_quote(raw, now)

    def observe(self, series, value, now):
        day = utc(now).date()
        row = PortfolioMarketObservation.query.filter_by(user_id=self.user_id, series=series, day=day).first()
        if row is None:
            row = PortfolioMarketObservation(user_id=self.user_id, series=series, day=day, value=value)
            db.session.add(row)
        else:
            row.value = value
        db.session.commit()
        return PortfolioMarketObservation.query.filter_by(user_id=self.user_id, series=series).filter(
            PortfolioMarketObservation.day >= day-timedelta(days=370)).order_by(PortfolioMarketObservation.day).all()

    def dominance_ok(self, symbol, now):
        if symbol == 'BTC':
            return True
        if 'dominance' not in self.cache:
            import requests
            response = requests.get('https://api.coingecko.com/api/v3/global', timeout=15)
            response.raise_for_status()
            data = response.json()['data']
            fresh_quote({'price': 1, 'as_of': data['updated_at']}, now, seconds=3600)
            value = finite(data['market_cap_percentage']['btc'], 'Bitcoin dominance', 0.01, 100)
            history = self.observe('BTC_DOMINANCE', value, now)
            previous = [row.value for row in history if row.day < utc(now).date()][-7:]
            if len(previous) < 7:
                raise ValueError('Bitcoin dominance filter needs seven previous daily observations.')
            self.cache['dominance'] = value <= sum(previous)/len(previous)
        return self.cache['dominance']

    def future(self, root, now):
        from services.webull_service import get_webull_futures_contracts
        contracts = get_webull_futures_contracts(*self.connection, symbol=root)
        today = utc(now).astimezone(ET).date().isoformat()
        candidates = [c for c in contracts if str(c.get('expiration_date') or '') > today and c.get('symbol')]
        if not candidates:
            raise ValueError('No unexpired micro futures contract metadata.')
        contract = min(candidates, key=lambda c: c['expiration_date'])
        multiplier = finite(contract.get('contract_multiplier'), 'contract multiplier', 0.01)
        # Use initial margin, not the much smaller advertised day margin.
        margin = finite(contract.get('initial_margin'), 'paper margin reserve', 1)
        return contract['symbol'], multiplier, margin

    def option_quotes(self, contracts, now):
        from services.webull_service import _get_webull_option_snapshots
        quotes = _get_webull_option_snapshots(*self.connection, symbols=[c['symbol'] for c in contracts])
        result = []
        for contract in contracts:
            quote = quotes.get(contract['symbol'].upper())
            if not quote:
                continue
            try:
                bid = finite(quote.get('bid'), 'option bid', 0.000001)
                ask = finite(quote.get('ask'), 'option ask', bid)
                fresh_quote({'price': ask, 'as_of': quote.get('as_of')}, now)
                result.append({**contract, **quote, 'bid': bid, 'ask': ask})
            except ValueError:
                continue
        return result

    def options(self, symbol, settings, now):
        from services.webull_service import get_webull_option_contracts
        price = self.quote(symbol, 'EQUITY', now)
        raw = get_webull_option_contracts(*self.connection, underlying_symbol=symbol)
        contracts = []
        for c in raw:
            try:
                expiration = str(c.get('option_expire_date') or c.get('expiration_date') or c.get('expire_date'))[:10]
                dte = (utc(expiration).date()-utc(now).astimezone(ET).date()).days
                kind = str(c.get('option_type') or c.get('put_call') or c.get('call_put') or '').upper()
                kind = {'C': 'CALL', 'P': 'PUT'}.get(kind, kind)
                if 20 <= dte <= 65 and kind in ('CALL', 'PUT'):
                    contracts.append({'symbol': c.get('symbol') or c['contract_symbol'], 'expiration': expiration,
                                      'option_type': kind, 'strike': finite(c.get('strike_price', c.get('strike')), 'strike', 0.01)})
            except (ValueError, KeyError, TypeError):
                continue
        if not contracts:
            raise ValueError('No Webull option contracts in the 20–65 DTE window.')
        expiration = min({c['expiration'] for c in contracts}, key=lambda e: abs((utc(e).date()-utc(now).astimezone(ET).date()).days-settings['target_dte']))
        selected = sorted([c for c in contracts if c['expiration'] == expiration], key=lambda c: abs(c['strike']-price))[:80]
        quoted = self.option_quotes(selected, now)
        ivs = [float(c['implied_volatility']) for c in sorted(quoted, key=lambda c: abs(c['strike']-price))[:4]
               if c.get('implied_volatility') is not None and 0 < float(c['implied_volatility']) < 10]
        if not ivs:
            raise ValueError('Provider ATM implied volatility is missing.')
        current = sum(ivs)/len(ivs)
        history = self.observe('IV:'+symbol, current, now)
        values = [row.value for row in history][-252:]
        rank = 100*(current-min(values))/(max(values)-min(values)) if len(values) >= 252 and max(values)>min(values) else None
        return price, quoted, rank

    def spread_mark(self, details, now):
        legs = self.option_quotes([details['short'], details['long']], now)
        by_symbol = {leg['symbol']: leg for leg in legs}
        if len(by_symbol) != 2:
            raise ValueError('Both spread legs require fresh executable quotes; position frozen pending quotes.')
        return max(0, by_symbol[details['short']['symbol']]['ask']-by_symbol[details['long']['symbol']]['bid'])
