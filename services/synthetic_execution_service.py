"""Shared safety, market data and durable execution for synthetic orders.

A committed intent precedes live submission. Uncertain responses are reconciled by
client ID; they are never automatically re-submitted. Session advisory locks remain
held across commits, serializing workers and cancellation for each parent.
"""
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import hashlib
import math
import threading
from uuid import uuid4

from sqlalchemy import inspect, text
from core.extensions import db
from core.time_utils import utc_now
from credentials import Credential, UserSetting
from trading_models import SyntheticExecution, TradingSettings, TestOrder, TestPortfolio

OPEN_EXECUTIONS = {'SUBMITTING', 'SUBMITTED', 'PARTIALLY_FILLED', 'UNKNOWN'}
WORKING_PARENTS = ('ACTIVE', 'PARTIALLY_FILLED', 'TRIGGERED', 'SUBMITTED', 'CANCEL_PENDING')
_local_locks = [threading.RLock() for _ in range(127)]


def positive(value, label, optional=False):
    if optional and value in (None, ''):
        return None
    try:
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise ValueError()
        return number
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f'{label} must be a finite positive number.') from None


def trailing_parameters(value, kind):
    value = positive(value, 'Trail distance')
    kind = str(kind or 'PERCENT').upper()
    if kind not in {'PERCENT', 'AMOUNT'} or (kind == 'PERCENT' and value >= 100):
        raise ValueError('Choose a dollar trail or a percentage greater than 0 and less than 100.')
    return value, kind


def validate_identity(symbol, side, broker, instrument_type, trading_session, account_id, test_mode):
    symbol, side, broker = str(symbol or '').strip().upper(), str(side or '').upper(), str(broker or '').lower()
    instrument_type = str(instrument_type or 'CRYPTO').upper()
    instrument_type = 'EQUITY' if instrument_type == 'STOCK' else instrument_type
    if broker not in {'binance', 'webull'} or side not in {'BUY', 'SELL'}:
        raise ValueError('Choose Binance.US or Webull and a BUY or SELL side.')
    if not symbol or len(symbol) > 20 or not all(c.isalnum() or c in '.-' for c in symbol):
        raise ValueError('Choose a valid asset symbol.')
    if instrument_type not in {'CRYPTO', 'EQUITY', 'ETF'} or (broker == 'binance' and instrument_type != 'CRYPTO'):
        raise ValueError('Synthetic orders support Binance.US crypto and Webull crypto, stocks and ETFs.')
    trading_session = str(trading_session or 'CORE').upper()
    if instrument_type != 'CRYPTO' and trading_session != 'CORE':
        raise ValueError('Synthetic stock/ETF orders execute market orders during Regular Hours (CORE).')
    account_id = str(account_id or '').strip() or None
    if broker == 'webull':
        if test_mode:
            account_id = 'TEST_PAPER_ACCOUNT'
        elif not account_id or account_id.startswith(('TEST_', 'QUANT_')):
            raise ValueError('Select a live Webull account for a real synthetic order.')
        if instrument_type == 'CRYPTO' and not symbol.endswith('USD'):
            symbol += 'USD'
    return symbol, side, broker, instrument_type, 'CORE', account_id


def environment_for(user_id, broker):
    setting = UserSetting.query.filter_by(user_id=user_id).first()
    return (getattr(setting, 'webull_environment', None) or 'production') if broker == 'webull' else 'production'


def webull_credentials(parent):
    cred = Credential.query.filter_by(user_id=parent.user_id).first()
    env = parent.environment or environment_for(parent.user_id, 'webull')
    if not cred or not cred.webull_app_key or not cred.webull_app_secret or not cred.webull_access_token:
        raise ValueError('Connect Webull before creating or executing synthetic orders.')
    if cred.webull_token_environment != env or cred.webull_token_status != 'NORMAL':
        raise ValueError('The Webull token is expired or belongs to another environment.')
    return cred, env


def binance_client(user_id=None, public=False):
    from binance.client import Client
    # The pinned 1.0.19 SDK always pings in __init__ and has no ping=False
    # argument. Suppress only that eager network call, retaining normal ping().
    class LazyClient(Client):
        def __init__(self, *args, **kwargs):
            self._initializing = True
            super().__init__(*args, **kwargs)
            self._initializing = False

        def ping(self):
            return {} if self._initializing else super().ping()

    if public:
        return LazyClient(tld='us', requests_params={'timeout': 10})
    cred = Credential.query.filter_by(user_id=user_id).first()
    if not cred or not cred.trading_api_key or not cred.trading_api_secret:
        raise ValueError('Connect Binance.US trading credentials before placing this order.')
    return LazyClient(cred.trading_api_key, cred.trading_api_secret, tld='us', requests_params={'timeout': 10})


def reference_price(symbol, client=None, broker='binance', instrument_type='CRYPTO', user_id=None, environment=None):
    """Only use a fresh request for the exact venue/instrument; never the Coin table."""
    if broker == 'webull':
        from types import SimpleNamespace
        from services.webull_service import get_webull_market_snapshot
        cred, env = webull_credentials(SimpleNamespace(user_id=user_id, environment=environment))
        quote = get_webull_market_snapshot(cred.webull_app_key, cred.webull_app_secret, env,
                                          cred.webull_access_token, symbol=symbol, instrument_type=instrument_type)
        stamp = quote.get('as_of')
        if stamp:
            try:
                if str(stamp).replace('.', '', 1).isdigit():
                    seconds = float(stamp)
                    if seconds > 1e12:
                        seconds /= 1000
                    observed = datetime.fromtimestamp(seconds, timezone.utc)
                else:
                    observed = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
                    if observed.tzinfo is None:
                        observed = observed.replace(tzinfo=timezone.utc)
                # Equity orders can be configured when closed, but never executed then.
                from services.portfolio_strategy_signals import in_session
                if (instrument_type == 'CRYPTO' or in_session(utc_now(aware=True))) and not -5 <= (utc_now(aware=True) - observed).total_seconds() <= 120:
                    raise ValueError('The Webull quote is stale; monitoring will wait for a current quote.')
            except (OverflowError, OSError):
                raise ValueError('The Webull quote timestamp is invalid.') from None
        return positive(quote.get('price') or quote.get('regular_price'), 'Webull reference price')
    ticker = (client or binance_client(public=True)).get_symbol_ticker(symbol=symbol)
    return positive(ticker.get('price'), 'Binance.US reference price')


def market_is_open(parent):
    if parent.broker == 'webull' and parent.instrument_type != 'CRYPTO':
        from services.portfolio_strategy_signals import in_session
        return in_session(utc_now(aware=True))
    return True


def quantity_rules(parent):
    if parent.broker == 'webull':
        return {'step': Decimal('0.00001') if parent.instrument_type != 'CRYPTO' else Decimal('0.00000001')}
    info = binance_client(public=True).get_symbol_info(parent.symbol)
    if not info or info.get('status') != 'TRADING' or 'MARKET' not in info.get('orderTypes', []):
        raise ValueError('This Binance.US symbol is not available for market orders.')
    filters = {f['filterType']: f for f in info.get('filters', [])}
    lots = [filters[k] for k in ('LOT_SIZE', 'MARKET_LOT_SIZE') if k in filters]
    steps = [Decimal(f.get('stepSize', '0')) for f in lots if Decimal(f.get('stepSize', '0')) > 0]
    return {'step': max(steps or [Decimal('0.00000001')]), 'lots': lots,
            'notional': filters.get('NOTIONAL') or filters.get('MIN_NOTIONAL') or {},
            'quote': info.get('quoteAsset'), 'base': info.get('baseAsset')}


def normalize_quantity(quantity, rules):
    step = rules['step']
    return float((Decimal(str(round(quantity, 12))) / step).to_integral_value(rounding=ROUND_DOWN) * step)


def check_quantity(parent, quantity, price, rules):
    positive(quantity, 'Execution quantity')
    for lot in rules.get('lots', []):
        if quantity < float(lot.get('minQty') or 0) or (float(lot.get('maxQty') or 0) > 0 and quantity > float(lot['maxQty'])):
            raise ValueError('A ladder step is outside the broker market quantity limits. Increase its allocation or use fewer steps.')
    notional = rules.get('notional', {})
    if notional.get('applyToMarket', notional.get('applyMinToMarket', True)) and quantity * price < float(notional.get('minNotional') or 0):
        raise ValueError('A ladder step is below the broker minimum order value. Increase its allocation or use fewer steps.')
    if notional.get('applyMaxToMarket', False) and quantity * price > float(notional.get('maxNotional') or float('inf')):
        raise ValueError('A ladder step exceeds the broker maximum order value.')
    if parent.broker == 'webull' and parent.instrument_type != 'CRYPTO' and not float(quantity).is_integer() and quantity * price < 5:
        raise ValueError('Each fractional stock/ETF execution must be worth at least $5.')


def check_order_limit(parent, quantity, price, rules):
    setting = TradingSettings.query.filter_by(user_id=parent.user_id).first()
    limit = float(getattr(setting, 'max_order_size_usd', 0) or 0)
    if parent.test_mode or limit <= 0:
        return
    quote = rules.get('quote', 'USD')
    rate = 1.0 if quote == 'USD' else reference_price(f'{quote}USD')
    if quantity * price * rate > limit:
        raise ValueError(f'Order exceeds the configured ${limit:,.2f} maximum order size.')


def check_live_funding(parent, quantity, price, rules):
    """Recheck the selected account immediately before transmission; never open a short."""
    if parent.test_mode:
        return
    if parent.broker == 'binance':
        asset = rules['base'] if parent.side == 'SELL' else rules['quote']
        balance = binance_client(parent.user_id).get_asset_balance(asset=asset)
        available = float((balance or {}).get('free') or 0)
        required = quantity if parent.side == 'SELL' else quantity * price
    else:
        from services.webull_service import get_webull_account_positions, get_webull_account_balance
        cred, env = webull_credentials(parent)
        args = (cred.webull_app_key, cred.webull_app_secret, env, cred.webull_access_token, parent.account_id)
        if parent.side == 'SELL':
            positions = get_webull_account_positions(*args)
            def matches(position):
                symbol = str(position.get('symbol') or '').upper()
                if parent.instrument_type == 'CRYPTO' and not symbol.endswith('USD'):
                    symbol += 'USD'
                return symbol == parent.symbol and str(position.get('side') or '').upper() != 'SHORT'
            available = sum(max(0, float(p.get('available_quantity', p.get('quantity', 0)) or 0)) for p in positions if matches(p))
            required = quantity
        else:
            balance = get_webull_account_balance(*args)
            available = float(balance.get('available_cash', balance.get('total_cash_balance', 0)) or 0)
            required = quantity * price
    if not math.isfinite(available) or available + 1e-10 < required:
        raise ValueError('The selected account no longer has sufficient available assets or cash for this execution.')


@contextmanager
def parent_lock(kind, identifier):
    key = int.from_bytes(hashlib.sha256(f'synthetic:{kind}:{identifier}'.encode()).digest()[:8], 'big', signed=True)
    with _local_locks[key % len(_local_locks)]:
        if db.engine.dialect.name != 'postgresql':
            yield True
            return
        with db.engine.connect() as connection:
            locked = connection.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': key}).scalar()
            try:
                yield bool(locked)
            finally:
                if locked:
                    connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': key})


def executions(parent, kind):
    if not inspect(parent).persistent:
        return []
    return SyntheticExecution.query.filter_by(parent_kind=kind, parent_id=parent.id, user_id=parent.user_id).order_by(SyntheticExecution.id).all()


def execution_summary(parent, kind):
    rows = executions(parent, kind)
    total = float(parent.total_quantity if kind == 'LADDER' else parent.quantity)
    filled = sum(float(x.filled_quantity or 0) for x in rows)
    reserved = sum(max(0, x.quantity - (x.filled_quantity or 0)) for x in rows if x.status in OPEN_EXECUTIONS)
    verified = parent.engine_version == 2
    return {'filled_quantity': filled if verified else None, 'remaining_quantity': max(0, total - filled) if verified else None, 'pending_quantity': reserved if verified else None,
            'execution_history_verified': verified,
            'executions': [x.to_dict() for x in rows], 'environment': parent.environment,
            'last_price': parent.last_price, 'last_checked_at': parent.last_checked_at.isoformat() if parent.last_checked_at else None,
            'monitoring_error': parent.monitoring_error, 'cancel_requested': bool(parent.cancel_requested)}


def apply_broker_result(execution, result, broker):
    raw = result.get('raw', result)
    if isinstance(raw, dict):
        raw = raw.get('data', raw)
    if isinstance(raw, dict) and isinstance(raw.get('orders') or raw.get('items'), list):
        items = raw.get('orders') or raw.get('items')
        raw = next((item for item in items if str(item.get('client_order_id') or item.get('clientOrderId')) == execution.client_order_id), items[0] if len(items) == 1 else {})
    raw = raw if isinstance(raw, dict) else {}
    state = str(raw.get('status') or raw.get('order_status') or result.get('status') or 'SUBMITTED').upper().replace(' ', '_')
    states = {'NEW': 'SUBMITTED', 'WORKING': 'SUBMITTED', 'ACCEPTED': 'SUBMITTED', 'PENDING': 'SUBMITTED',
              'PARTIAL_FILLED': 'PARTIALLY_FILLED', 'PARTIALLYFILLED': 'PARTIALLY_FILLED',
              'CANCELED': 'CANCELLED', 'REJECTED': 'FAILED', 'EXPIRED': 'CANCELLED', 'FINAL_FILLED': 'FILLED'}
    state = states.get(state, state)
    quantity = next((raw[k] for k in ('executedQty', 'filled_quantity', 'filled_qty', 'filled_size', 'filledSize') if raw.get(k) is not None), None)
    if quantity is not None:
        quantity = float(quantity)
        if not math.isfinite(quantity) or quantity < 0 or quantity > execution.quantity + 1e-8:
            raise ValueError('Broker returned an invalid filled quantity.')
        execution.filled_quantity = max(float(execution.filled_quantity or 0), quantity)
    # Do not manufacture a full fill from an acknowledgement without fill quantity.
    if state == 'FILLED' and float(execution.filled_quantity or 0) < execution.quantity - 1e-10:
        state = 'PARTIALLY_FILLED' if execution.filled_quantity else 'SUBMITTED'
    price = next((raw[k] for k in ('filled_price', 'average_filled_price', 'avg_fill_price', 'avg_price', 'average_price') if raw.get(k)), None)
    if broker == 'binance' and execution.filled_quantity and raw.get('cummulativeQuoteQty') is not None:
        price = float(raw['cummulativeQuoteQty']) / execution.filled_quantity
    if price is not None:
        execution.filled_price = positive(price, 'Broker average fill price')
    execution.broker_order_id = str(raw.get('orderId') or raw.get('order_id') or result.get('order_id') or execution.broker_order_id or '') or None
    execution.status = state if state in OPEN_EXECUTIONS | {'FILLED', 'CANCELLED', 'FAILED'} else 'SUBMITTED'
    execution.error_message = (str(raw.get('reject_reason') or raw.get('error_message') or 'Broker rejected the order.') if state == 'FAILED' else None)
    execution.updated_at = utc_now(aware=False)


def _binance_paper(parent, execution, price, rules):
    from services.binance_fee_service import paper_rates
    from services.binance_paper_service import apply_fill
    qty = execution.quantity
    fee_rate = paper_rates(parent.symbol)['rates'][parent.side]['taker']
    fee = apply_fill(parent.user_id, rules['base'], rules['quote'], parent.side, qty, price, fee_rate)
    record = TestOrder(user_id=parent.user_id, symbol=parent.symbol, side=parent.side, type='MARKET',
                       quantity=qty, price=price, status='FILLED', simulated_fill_price=price,
                       simulated_fill_time=utc_now(aware=False), notes=f'Synthetic {execution.client_order_id}; simulated fee {fee:.8f} {rules["quote"]} equivalent ({fee_rate * 100:g}%)')
    db.session.add(record)
    db.session.flush()
    return {'order_id': str(record.id), 'status': 'FILLED', 'filled_quantity': qty, 'filled_price': price}


def submit_execution(parent, kind, quantity, price, leg, rung=None):
    rules = quantity_rules(parent)
    quantity = normalize_quantity(quantity, rules)
    check_quantity(parent, quantity, price, rules)
    check_order_limit(parent, quantity, price, rules)
    check_live_funding(parent, quantity, price, rules)
    row = SyntheticExecution(user_id=parent.user_id, parent_kind=kind, parent_id=parent.id,
                             rung_id=rung.id if rung else None, leg=leg, quantity=quantity,
                             client_order_id='syn' + uuid4().hex[:29], filled_quantity=0, status='SUBMITTING')
    db.session.add(row)
    db.session.flush()
    if parent.test_mode:
        account_lock = parent_lock('BINANCE_PAPER', parent.user_id) if parent.broker == 'binance' else nullcontext(True)
        with account_lock as locked:
            if not locked:
                db.session.rollback()
                raise ValueError('Paper account is busy; try again.')
            # Paper accounting and execution journal commit atomically.
            try:
                if parent.broker == 'webull':
                    from services.webull_paper_trading_service import execute_webull_test_order
                    result = execute_webull_test_order(parent.user_id, {
                        'symbol': parent.symbol, 'instrument_type': parent.instrument_type,
                        'side': parent.side, 'order_type': 'MARKET', 'quantity': quantity,
                        'support_trading_session': 'CORE'}, commit=False, execution_price=price,
                        execution_id=row.client_order_id)
                else:
                    result = _binance_paper(parent, row, price, rules)
                apply_broker_result(row, result, parent.broker)
            except Exception:
                db.session.rollback()
                raise
            db.session.commit()
            return row
    # Persist the unique client ID before any external side effect.
    db.session.commit()
    try:
        if parent.broker == 'webull':
            from services.webull_service import place_webull_order
            cred, env = webull_credentials(parent)
            result = place_webull_order(cred.webull_app_key, cred.webull_app_secret, env, cred.webull_access_token,
                account_id=parent.account_id, symbol=parent.symbol, instrument_type=parent.instrument_type,
                side=parent.side, order_type='MARKET', quantity=quantity, support_trading_session='CORE',
                client_order_id=row.client_order_id)
        else:
            result = binance_client(parent.user_id).create_order(symbol=parent.symbol, side=parent.side,
                type='MARKET', quantity=format(Decimal(str(quantity)), 'f'), newClientOrderId=row.client_order_id,
                newOrderRespType='FULL')
        apply_broker_result(row, result, parent.broker)
    except Exception as exc:
        # Even a timeout can mean the exchange accepted the order. Never retry transmission.
        row.status = 'UNKNOWN'
        row.error_message = 'Submission outcome is uncertain; checking the broker before any further execution.'
        from binance.exceptions import BinanceAPIException
        from services.webull_service import WebullConnectionError
        if isinstance(exc, (BinanceAPIException, WebullConnectionError)):
            code = getattr(exc, 'status_code', None) or getattr(exc, 'http_status', None)
            if code and 400 <= int(code) < 500 and int(code) not in {408, 429}:
                row.status = 'FAILED'
                row.error_message = 'Broker rejected this execution. Check account permissions, balance and order limits.'
    db.session.commit()
    return row


def reconcile_executions(parent, kind):
    rows = executions(parent, kind)
    for row in rows:
        if row.status not in OPEN_EXECUTIONS or parent.test_mode:
            continue
        try:
            if parent.broker == 'binance':
                result = binance_client(parent.user_id).get_order(symbol=parent.symbol, origClientOrderId=row.client_order_id)
            else:
                from services.webull_service import get_webull_order_detail
                cred, env = webull_credentials(parent)
                result = get_webull_order_detail(cred.webull_app_key, cred.webull_app_secret, env, cred.webull_access_token,
                    account_id=parent.account_id, client_order_id=row.client_order_id)
            apply_broker_result(row, result, parent.broker)
        except Exception:
            row.error_message = 'Awaiting broker confirmation. No additional order will be sent while this execution is unresolved.'
        if parent.cancel_requested and row.status in OPEN_EXECUTIONS:
            try:
                if parent.broker == 'binance':
                    result = binance_client(parent.user_id).cancel_order(symbol=parent.symbol, origClientOrderId=row.client_order_id)
                    apply_broker_result(row, result, parent.broker)
                else:
                    from services.webull_service import cancel_webull_order
                    cred, env = webull_credentials(parent)
                    cancel_webull_order(cred.webull_app_key, cred.webull_app_secret, env, cred.webull_access_token,
                        account_id=parent.account_id, client_order_id=row.client_order_id)
                    # Cancellation acknowledgement is not final; reconcile on the next cycle.
            except Exception:
                row.error_message = 'Cancellation requested; waiting for the broker to confirm the final order state.'
    return rows


def cancel_parent(model, kind, identifier, user_id):
    with parent_lock(kind, identifier) as locked:
        if not locked:
            raise ValueError('An execution is in progress. Refresh and try cancelling again.')
        parent = model.query.filter_by(id=identifier, user_id=user_id).populate_existing().first()
        if not parent:
            raise ValueError('Synthetic order not found.')
        if parent.status in {'COMPLETED', 'FILLED', 'CANCELLED', 'STOPPED_OUT'}:
            raise ValueError(f'This order is already {parent.status}.')
        parent.cancel_requested = True
        rows = reconcile_executions(parent, kind)
        parent.status = 'CANCEL_PENDING' if any(r.status in OPEN_EXECUTIONS for r in rows) else 'CANCELLED'
        if kind == 'LADDER':
            for rung in parent.rungs:
                if rung.status == 'PENDING':
                    rung.status = 'CANCELLED'
        parent.updated_at = utc_now(aware=False)
        db.session.commit()
        return parent.to_dict()
