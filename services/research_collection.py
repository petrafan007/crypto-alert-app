"""Independent collectors: market-data GETs only; no trading or AI dependencies."""
import json
import time
import threading
from uuid import uuid4
from datetime import timedelta
from sqlalchemy import select
from core.extensions import db
from research_data_models import ResearchCollectionConfig as Config, ResearchCollectionState as State, utcnow
from services.research_archive import LANES, CollectionPaused, settings, save_capture

WEBULL_PATHS = {
    'option_catalog':'/trading/instruments/options/contracts/list',
    'option_quotes':'/market-data/options/snapshots/list',
    'stock_quotes':'/market-data/stocks/snapshots/list',
    'stock_bars':'/openapi/market-data/stock/bars',
    'webull_crypto_quotes':'/market-data/crypto/snapshots/list',
    'webull_crypto_bars':'/market-data/crypto/bars/list',
    'futures_catalog':'/openapi/instrument/futures/by-code',
    'futures_quotes':'/market-data/futures/snapshots/list',
    'futures_bars':'/market-data/futures/bars/list',
    'event_catalog':'/trading/instruments/event-contracts/markets/list',
    'event_quotes':'/market-data/event-contracts/snapshots/list',
    'event_depth':'/market-data/event-contracts/depths/list',
    'event_trades':'/market-data/event-contracts/ticks/list',
}
PUBLIC_PATHS = {'crypto_depth':'/api/v3/depth', 'crypto_trades':'/api/v3/aggTrades', 'crypto_bars':'/api/v3/klines'}


def rotated(rows, offset, limit):
    if not rows:
        return [], 0
    offset %= len(rows)
    return (rows[offset:]+rows[:offset])[:limit], (offset+limit) % len(rows)


def next_cursor(body, *fields):
    if not isinstance(body, dict):
        return None
    inner = body.get('data') if isinstance(body.get('data'),dict) else body
    return next((inner[key] for key in fields if inner.get(key)), None)


class Collector:
    def __init__(self, user_id, lane, options, details, stop=None):
        self.user_id, self.lane, self.options = user_id, lane, options
        self.details, self.stop = details, stop
        self.details.update(requests=0, captures=0, errors=[], coverage={})
        self.details.pop('waiting', None)
        self.details.pop('message', None)
        self.details.setdefault('cooldowns', {})
        self.details['cooldowns'] = {k:v for k,v in self.details['cooldowns'].items() if v.get('retry_at',0) > time.time()}
        self.details.setdefault('cursors', {})
        self.connection = None
        self.cycle_id = uuid4().hex
        self.deadline = time.monotonic()+(240 if lane == 'options' else 55)

    def guard(self):
        if (self.stop and self.stop.is_set()) or time.monotonic() >= self.deadline:
            raise CollectionPaused('Cycle time budget reached; next cycle resumes collection.')
        with db.engine.connect() as con:
            row = con.execute(select(Config.enabled, Config.stored_bytes, Config.settings_json).where(Config.user_id == self.user_id)).first()
        if not row or not row.enabled:
            raise CollectionPaused('Collection paused by administrator.')
        if row.stored_bytes >= json.loads(row.settings_json).get('storage_mb', 10240)*1024*1024:
            raise CollectionPaused('Archive storage limit reached; existing history is retained.')

    def fetch(self, kind, symbol, params):
        self.guard()
        key = kind+':'+symbol[:160]
        retry = max(self.details['cooldowns'].get(k, {}).get('retry_at', 0) for k in (key,kind))
        if retry > time.time():
            return None
        if self.details['requests'] >= (80 if self.lane == 'options' else 60):
            raise CollectionPaused('Cycle request budget reached; next cycle resumes collection.')
        self.details['requests'] += 1
        started = utcnow()
        db.session.commit()  # Never hold ORM locks/transactions during transport.
        try:
            if kind in WEBULL_PATHS:
                from event_algo import _webull_connection_for_user
                from services.webull_service import _webull_request, _response_payload
                if self.connection is None:
                    credential, environment = _webull_connection_for_user(self.user_id)
                    self.connection = (credential.webull_app_key, credential.webull_app_secret, environment, credential.webull_access_token)
                    db.session.commit()
                key_value, secret, environment, token = self.connection
                response = _webull_request(key_value, secret, environment, 'GET', WEBULL_PATHS[kind], query_params=params, access_token=token)
                body = _response_payload(response, 'research market data')
                source = 'WEBULL_'+environment.upper()
            elif kind in PUBLIC_PATHS:
                import requests
                response = requests.get('https://api.binance.us'+PUBLIC_PATHS[kind], params=params, timeout=10, allow_redirects=False)
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError('Unexpected public feed response.')
                body, source = response.json(), 'BINANCE_US_PUBLIC'
            elif kind=='dominance':
                import requests
                response=requests.get('https://api.coingecko.com/api/v3/global',timeout=10,allow_redirects=False)
                response.raise_for_status()
                body,source=response.json(),'COINGECKO_GLOBAL'
            elif kind=='independent_event_depth':
                import re
                import requests
                if not re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,159}',symbol):
                    raise ValueError('Invalid public market ticker.')
                response=requests.get('https://external-api.kalshi.com/trade-api/v2/markets/'+symbol+'/orderbook',
                                      params={'depth':10},timeout=10,allow_redirects=False)
                response.raise_for_status()
                if response.status_code!=200:raise ValueError('Unexpected public book response.')
                body,source=response.json(),'KALSHI_PUBLIC'
            else:
                raise ValueError('Unsupported read-only research endpoint.')
            received = utcnow()
            self.guard()
            save_capture(self.user_id, self.lane, source, kind, symbol, body, started,
                         {'endpoint':WEBULL_PATHS.get(kind, PUBLIC_PATHS.get(kind, '/trade-api/v2/markets/{ticker}/orderbook' if kind=='independent_event_depth' else '/api/v3/global')), 'parameters':params,
                          'capture_method':'REST_POLL', 'provider_timestamps':'Retained verbatim in payload; absent timestamps are UNKNOWN.',
                          'schema_version':1, 'cycle_id':self.cycle_id}, received_at=received)
            self.details['captures'] += 1
            self.details['cooldowns'].pop(key, None)
            return body
        except CollectionPaused:
            raise
        except Exception as exc:
            db.session.rollback()
            # Store a classification, never a response/header containing secrets.
            message = str(exc).lower()
            denied = any(term in message for term in ('not_subscribed', 'subscription', 'permission', '403', '401', 'unauthorized', 'forbidden'))
            rate = any(term in message for term in ('429', 'rate limit', 'too many'))
            status = 'ACCESS_REQUIRED' if denied else 'RATE_LIMITED' if rate else 'UNAVAILABLE'
            self.details['cooldowns'][kind if denied or rate else key] = {'status':status, 'retry_at':time.time()+(86400 if denied else 900)}
            self.details['errors'].append({'kind':kind, 'symbol':symbol, 'status':status, 'exception':type(exc).__name__})
            return None

    def records(self, body):
        from services.webull_service import _webull_records
        return _webull_records(body) if body is not None else []

    def options_lane(self, watches, module_settings):
        from services.portfolio_strategy_signals import in_session, utc, ET
        now = utcnow()
        if not in_session(now):
            if self.details.get('off_session_date') == str(now.date()):
                self.details['waiting'] = 'NYSE session closed; collection resumes next session. One baseline snapshot is retained per off-session UTC day.'
                return
            self.details['off_session_date'] = str(now.date())
            self.details['waiting'] = 'Off-session baseline; provider timestamps determine quote age.'
        symbols = list(dict.fromkeys((['SPY'] if watches.get('equities') else [])+sorted(set(watches.get('options', [])+watches.get('equities', [])))))[:30]
        for symbol in symbols:
            self.fetch('stock_quotes', symbol, {'symbols':symbol, 'category':'US_STOCK'})
            key='daily-bars:'+symbol
            if self.details['cursors'].get(key)!=str(now.date()):
                if self.fetch('stock_bars',symbol,{'symbol':symbol,'category':'US_STOCK','timespan':'D','count':1200}) is not None:
                    self.details['cursors'][key]=str(now.date())
        roots = list(watches.get('options', []))[:20]
        roots, _ = rotated(roots, self.details['cursors'].get('root', 0), len(roots))
        for root in roots:
            self.details['cursors']['root'] = (list(watches.get('options', [])).index(root)+1) % max(1,len(roots))
            now = utcnow()
            params = {'category':'US_OPTION', 'underlying_symbols':root, 'root_symbol':root,
                      'status':'LISTING', 'page_size':1000, 'show_deliverables':'true',
                      'start_date':str(now.date()), 'end_date':str(now.date()+timedelta(days=1095))}
            # Rotate catalogue pages over cycles instead of permanently ignoring later expiries.
            cursor = self.details['cursors'].get('catalog:'+root)
            if cursor:
                params['pagination_key'] = cursor
            body = self.fetch('option_catalog', root, params)
            if body is None:
                continue
            catalog = self.records(body)
            cursor = next_cursor(body,'pagination_key')
            self.details['cursors']['catalog:'+root] = cursor
            available = [r for r in catalog if r.get('symbol') and r.get('underlying_symbol') == root]
            # Query the strategy's exact DTE range separately so broad collection
            # cannot starve the consistent daily ATM observation.
            target = module_settings['options']['target_dte']
            near_params = {k:v for k,v in params.items() if k != 'pagination_key'}
            near_params.update(start_date=str(now.date()+timedelta(days=20)), end_date=str(now.date()+timedelta(days=65)))
            near_body = self.fetch('option_catalog', root, near_params)
            near = self.records(near_body)
            near_cursor=next_cursor(near_body,'pagination_key')
            seen=set()
            while near_cursor and near_cursor not in seen and len(seen)<9:
                seen.add(near_cursor)
                near_body=self.fetch('option_catalog',root,{**near_params,'pagination_key':near_cursor})
                if near_body is None:break
                near.extend(self.records(near_body))
                near_cursor=next_cursor(near_body,'pagination_key')
            stock = self.records(self.fetch('stock_quotes', root, {'symbols':root,'category':'US_STOCK'}))
            underlying = stock[0] if stock else {}
            price = underlying.get('price', underlying.get('last_price'))
            contracts = []
            for r in near:
                try:
                    exp = str(r['expiration_date'])[:10]
                    if r.get('def_type') != 'STANDARD' or r.get('underlying_symbol') != root or float(r['multiplier']) != 100:
                        continue
                    if not 20 <= (utc(exp).date()-utc(now).astimezone(ET).date()).days <= 65:
                        continue
                    contracts.append({**r, 'expiration':exp, 'strike':float(r['strike_price']),
                                      'option_type':{'C':'CALL','P':'PUT'}.get(r['option_type'],r['option_type'])})
                except (ValueError,KeyError,TypeError):
                    continue
            priority = []
            if contracts and price is not None:
                expiration = min({c['expiration'] for c in contracts}, key=lambda e:(abs((utc(e).date()-utc(now).astimezone(ET).date()).days-target),e))
                priority = sorted([c for c in contracts if c['expiration']==expiration], key=lambda c:(abs(c['strike']-float(price)),c['symbol']))[:80]
            other = sorted({r['symbol']:r for r in available+contracts if r['symbol'] not in {c['symbol'] for c in priority}}.values(), key=lambda r:r['symbol'])
            extra, offset = rotated(other, self.details['cursors'].get(root,0), max(0,self.options['options_contracts']-len(priority)))
            self.details['cursors'][root] = offset
            selected = priority+extra
            self.details['coverage'][root] = {'catalog_page_contracts':len(catalog), 'catalog_more_pages':bool(cursor),
                                              'selected_contracts':len(selected),
                                              'near_catalog_complete':near_body is not None and not near_cursor,
                                              'note':'Rotating bounded pages/contracts; not an entire simultaneous chain.'}
            for start in range(0,len(selected),20):
                names = [c['symbol'] for c in selected[start:start+20]]
                self.fetch('option_quotes',root,{'symbols':','.join(names),'category':'US_OPTION'})

    def events_lane(self, watches):
        from event_algo import _market_cutoff
        contracts = {}
        for series in watches.get('events', [])[:20]:
            params = {'series_symbol':series,'page_size':500}
            cursor = self.details['cursors'].get('catalog:'+series)
            if cursor:
                params['last_instrument_id'] = cursor
            body = self.fetch('event_catalog', series, params)
            rows = self.records(body)
            if body is not None:
                self.details['cursors']['catalog:'+series] = next_cursor(body,'last_instrument_id','next_last_instrument_id') or (rows[-1].get('instrument_id') if len(rows)>=500 else None)
            self.details['coverage'][series] = {'catalog_page_contracts':len(rows), 'catalog_more_pages':bool(self.details['cursors'].get('catalog:'+series))}
            for row in rows:
                symbol = str(row.get('symbol') or '')
                cutoff = _market_cutoff(row)
                if symbol.startswith(series+'-') and cutoff and cutoff > utcnow() and str(row.get('status') or '').upper() in ('LISTING',''):
                    contracts[symbol] = row
        ordered = sorted(contracts, key=lambda symbol:(_market_cutoff(contracts[symbol]),symbol))
        priority=[symbol for symbol in ordered if _market_cutoff(contracts[symbol])<=utcnow()+timedelta(minutes=30)][:min(4,self.options['event_contracts'])]
        selected, offset = rotated([symbol for symbol in ordered if symbol not in priority],self.details['cursors'].get('contracts',0),self.options['event_contracts']-len(priority))
        selected=priority+selected
        self.details['cursors']['contracts'] = offset
        self.details['coverage']['selection'] = {'active_candidates':len(ordered),'selected':len(selected),'rotation':True}
        if selected:
            self.fetch('event_quotes', ','.join(selected)[:160], {'symbols':','.join(selected),'category':'US_EVENT'})
        for symbol in selected:
            self.fetch('event_depth',symbol,{'symbol':symbol,'category':'US_EVENT','depth':10})
            # Pair exact tickers close in receipt time, keeping sources separate.
            # Public books do not establish Webull queue priority or quote age.
            if symbol in selected[:4] and self.connection and self.connection[2].upper()=='PRODUCTION':
                self.fetch('independent_event_depth',symbol,{'depth':10})
            self.fetch('event_trades',symbol,{'symbol':symbol,'category':'US_EVENT','count':1200})

    def crypto_lane(self, watches):
        key='dominance-hour'
        hour=utcnow().strftime('%Y-%m-%dT%H')
        if self.details['cursors'].get(key)!=hour:
            if self.fetch('dominance','BTC_DOMINANCE',{}) is not None:self.details['cursors'][key]=hour
        for symbol in watches.get('crypto', [])[:10]:
            # Keep exchange/quote currency explicit; USDT is never relabeled USD.
            pair = symbol if symbol.endswith(('USDT','USD','USDC')) else symbol+'USDT'
            if not pair.isalnum() or len(pair)>24:
                continue
            book = self.fetch('crypto_depth', pair, {'symbol':pair,'limit':1000})
            trades = self.fetch('crypto_trades', pair, {'symbol':pair,'limit':1000})
            params={'symbol':pair,'interval':'1m','limit':1000}
            key='minute-bar:'+pair
            if self.details['cursors'].get(key):params['startTime']=self.details['cursors'][key]-60000
            bars = self.fetch('crypto_bars', pair, params)
            if isinstance(bars,list) and bars:self.details['cursors'][key]=bars[-1][0]
            self.details['coverage'][pair] = {
                'bid_levels':len(book.get('bids',[])) if isinstance(book,dict) else None,
                'ask_levels':len(book.get('asks',[])) if isinstance(book,dict) else None,
                'aggregate_trades':len(trades) if isinstance(trades,list) else None,
                'minute_bars':len(bars) if isinstance(bars,list) else None,
                'note':'Recent overlapping windows; gaps and duplicate trade/bar IDs require analysis.'}
            # Daily/hourly backfill is refreshed once a day; tick history cannot
            # be reconstructed from candles or repeated latest-trade windows.
            for interval in ('1h','1d'):
                key = 'bars:'+pair+':'+interval
                if self.details['cursors'].get(key) != str(utcnow().date()):
                    if self.fetch('crypto_bars',pair,{'symbol':pair,'interval':interval,'limit':1000}) is not None:
                        self.details['cursors'][key] = str(utcnow().date())
            root=symbol[:-len(currency)] if (currency:=next((q for q in ('USDT','USDC','USD') if symbol.endswith(q)),None)) else symbol
            usd=root+'USD'
            self.fetch('webull_crypto_quotes',usd,{'symbols':usd,'category':'US_CRYPTO'})
            key='usd-bars:'+usd
            if self.details['cursors'].get(key)!=hour:
                if self.fetch('webull_crypto_bars',usd,{'symbols':usd,'category':'US_CRYPTO','timespan':'M60','count':1200}) is not None:self.details['cursors'][key]=hour

    def futures_lane(self,watches):
        from services.portfolio_strategy_signals import in_session
        if not in_session(utcnow()):
            self.details['waiting']='Futures research follows the strategy US cash session.'
            return
        for root in watches.get('futures',[])[:10]:
            body=self.fetch('futures_catalog',root,{'category':'US_FUTURES','code':root,'contract_type':'MONTHLY'})
            from services.webull_service import _normalise_futures_catalog_record
            rows=[_normalise_futures_catalog_record(r) for r in self.records(body)]
            active=[r for r in rows if r and r.get('symbol') and str(r.get('expiration_date') or '')>str(utcnow().date())]
            if not active:continue
            contract=min(active,key=lambda r:r['expiration_date'])
            symbol=contract['symbol']
            self.fetch('futures_quotes',symbol,{'symbols':symbol,'category':'US_FUTURES'})
            self.fetch('futures_bars',symbol,{'symbols':symbol,'category':'US_FUTURES','timespan':'M1','count':1200})


def collect_once(user_id, lane, stop=None):
    if lane not in LANES:
        raise ValueError('Unknown collection lane.')
    from services.event_runtime import job_slot
    from portfolio_algo_models import PortfolioStrategyConfig
    from services.portfolio_engine import settings_for
    with job_slot(user_id, 'research-'+lane):
        cfg = db.session.get(Config,user_id)
        portfolio = PortfolioStrategyConfig.query.filter_by(user_id=user_id).first()
        if not cfg or not cfg.enabled or portfolio is None:
            return
        state = State.query.filter_by(user_id=user_id,lane=lane).first()
        if state is None:
            state = State(user_id=user_id,lane=lane,details_json='{}')
            db.session.add(state)
        if state.next_run_at and state.next_run_at > utcnow():
            return
        opts, details = settings(cfg), json.loads(state.details_json)
        watches, module_settings = json.loads(portfolio.watchlists_json), settings_for(portfolio)
        state.status, state.heartbeat_at = 'COLLECTING', utcnow()
        state.next_run_at = utcnow()+timedelta(seconds=opts[lane+'_seconds'])
        db.session.commit()
        collector = Collector(user_id,lane,opts,details,stop)
        started = time.monotonic()
        try:
            if lane=='options': collector.options_lane(watches,module_settings)
            elif lane=='events': collector.events_lane(watches)
            elif lane=='futures': collector.futures_lane(watches)
            else: collector.crypto_lane(watches)
            status = 'PARTIAL' if details['errors'] or details['cooldowns'] else 'WAITING' if details.get('waiting') else 'RECORDING'
        except CollectionPaused as exc:
            status, details['message'] = 'PAUSED', str(exc)
        except Exception as exc:
            db.session.rollback()
            status, details['message'] = 'ERROR', type(exc).__name__
        state = State.query.filter_by(user_id=user_id,lane=lane).populate_existing().one()
        details['elapsed_seconds'] = round(time.monotonic()-started,3)
        state.status, state.heartbeat_at, state.details_json = status, utcnow(), json.dumps(details)
        state.next_run_at = max(state.next_run_at,utcnow()+timedelta(seconds=5))
        db.session.commit()


def collection_loop(app, lane, stop_event=None):
    from credentials import User
    from event_algo import is_event_strategy_admin
    from services.provider_resilience import AIRequestDeferred
    stop = stop_event or threading.Event()
    while not stop.is_set():
        with app.app_context():
            try:
                users = [r.user_id for r in Config.query.filter_by(enabled=True).all()]
                for user_id in users:
                    if is_event_strategy_admin(db.session.get(User,user_id)):
                        try:
                            collect_once(user_id,lane,stop)
                        except AIRequestDeferred:
                            db.session.rollback()
            except Exception as exc:
                db.session.rollback()
                app.logger.warning('Research %s collection failed: %s',lane,type(exc).__name__)
            finally:
                db.session.remove()
        stop.wait(5)
