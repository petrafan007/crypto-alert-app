"""Shared safety, market data and durable execution for synthetic orders.

A committed intent precedes live submission. Uncertain responses are reconciled by
client ID; they are never automatically re-submitted. Session advisory locks remain
held across commits, serializing workers and cancellation for each parent.
"""
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
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
from log import logger

OPEN_EXECUTIONS = {'SUBMITTING', 'SUBMITTED', 'PARTIALLY_FILLED', 'UNKNOWN'}
WORKING_PARENTS = ('ACTIVE', 'PARTIALLY_FILLED', 'TRIGGERED', 'SUBMITTED', 'CANCEL_PENDING')
# Stock/ETF synthetic orders run in Regular Hours ('CORE') or in Regular plus
# Extended Hours ('ALL', 4:00 AM - 8:00 PM ET). Webull accepts only whole-share
# Limit orders in extended hours, so an execution there is a Limit order
# capped this far past the trigger price, cancelled if it has not filled in time.
DEFAULT_LIMIT_CAP_PCT = 1.0
MIN_LIMIT_CAP_PCT = 0.1
MAX_LIMIT_CAP_PCT = 5.0
EXTENDED_LIMIT_TIMEOUT_SECONDS = 300
EXTENDED_TIMEOUT_MESSAGE = ('The synthetic limit order did not fill within 5 minutes and was cancelled at Webull. '
                            'Review any partial fill before creating a new order.')
EQUITY_HOURS_WAIT = {
    'CORE': 'Waiting for regular market hours (9:30 AM - 4:00 PM ET on trading days).',
    'ALL': 'Waiting for market hours; this order runs 4:00 AM - 8:00 PM ET on trading days.',
}
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
    if instrument_type == 'CRYPTO' or broker != 'webull':
        trading_session = 'CORE'
    elif trading_session == 'NIGHT':
        raise ValueError('Synthetic stock/ETF orders run in Regular Hours or Regular + Extended Hours (4:00 AM - 8:00 PM ET). '
                         'Overnight is not supported because no overnight price feed is available.')
    elif trading_session not in {'CORE', 'ALL'}:
        raise ValueError('Choose Regular Hours or Regular + Extended Hours for this synthetic order.')
    account_id = str(account_id or '').strip() or None
    if broker == 'webull':
        if test_mode:
            account_id = 'TEST_PAPER_ACCOUNT'
        elif not account_id or account_id.startswith(('TEST_', 'QUANT_')):
            raise ValueError('Select a live Webull account for a real synthetic order.')
        if instrument_type == 'CRYPTO' and not symbol.endswith('USD'):
            symbol += 'USD'
    return symbol, side, broker, instrument_type, trading_session, account_id


def limit_cap(value, trading_session):
    """Validate the extended-hours price cap; only stock/ETF 'ALL' orders use it."""
    if trading_session != 'ALL':
        return None
    if value in (None, ''):
        return DEFAULT_LIMIT_CAP_PCT
    try:
        cap = float(value)
    except (TypeError, ValueError):
        cap = float('nan')
    if not math.isfinite(cap) or not MIN_LIMIT_CAP_PCT <= cap <= MAX_LIMIT_CAP_PCT:
        raise ValueError(f'The extended-hours price cap must be between {MIN_LIMIT_CAP_PCT:g}% and {MAX_LIMIT_CAP_PCT:g}%.')
    return cap


def require_whole_shares(quantity, trading_session, instrument_type):
    if trading_session == 'ALL' and instrument_type != 'CRYPTO' and not float(quantity).is_integer():
        raise ValueError('Extended-hours synthetic orders require whole shares, because Webull accepts only whole-share '
                         'orders outside Regular Hours.')


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


def reference_price(symbol, client=None, broker='binance', instrument_type='CRYPTO', user_id=None, environment=None,
                    trading_session='CORE'):
    """Only use a fresh request for the exact venue/instrument; never the Coin table.

    Webull's basic snapshot reports only the regular-session price, so a stock
    order that runs in extended hours reads Yahoo's extended-hours price there.
    While the market is closed it uses Yahoo's latest price (normally the last
    after-hours trade) when available, which is more current than the close.
    """
    if broker == 'webull' and instrument_type != 'CRYPTO' and str(trading_session or 'CORE').upper() == 'ALL':
        from services.market_calendar_service import equity_session_phase
        from services.extended_hours_quote_service import get_extended_hours_price
        phase = equity_session_phase(utc_now(aware=True))
        if phase == 'EXTENDED':
            return positive(get_extended_hours_price(symbol)[0], 'Extended-hours reference price')
        if phase is None:
            try:
                return positive(get_extended_hours_price(symbol, require_fresh=False)[0], 'Extended-hours reference price')
            except ValueError:
                pass
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


def session_phase(parent, now=None):
    """Return 'CORE', 'EXTENDED' or None (closed) for this parent's trading hours."""
    if parent.broker != 'webull' or parent.instrument_type == 'CRYPTO':
        return 'CORE'
    from services.market_calendar_service import equity_session_phase
    phase = equity_session_phase(now or utc_now(aware=True))
    if str(parent.trading_session or 'CORE').upper() == 'ALL':
        return phase
    return 'CORE' if phase == 'CORE' else None


def market_is_open(parent):
    return session_phase(parent) is not None


def waiting_message(parent):
    return EQUITY_HOURS_WAIT.get(str(parent.trading_session or 'CORE').upper(), EQUITY_HOURS_WAIT['CORE'])


def parse_activate_at(value):
    """Normalize an optional post-dated activation time to naive UTC.

    Accepts None/'' (no scheduling), a datetime, or an ISO-8601 string.
    Aware values are converted to UTC; naive values are assumed to be UTC.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            raise ValueError('Enter a valid start date and time.') from None
    else:
        raise ValueError('Enter a valid start date and time.')
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    if parsed > utc_now(aware=False) + timedelta(days=366):
        raise ValueError('The start time must be within the next 366 days.')
    return parsed


def activation_pending(parent, now=None):
    """True while a post-dated synthetic order is still dormant."""
    activate_at = getattr(parent, 'activate_at', None)
    if activate_at is None:
        return False
    return activate_at > (now or utc_now(aware=False))


def activation_message(parent):
    """Human-readable dormant message, with the start shown in Eastern Time."""
    from zoneinfo import ZoneInfo
    activate_at = getattr(parent, 'activate_at', None)
    if activate_at is None:
        return ''
    eastern = activate_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('America/New_York'))
    return f"Scheduled: monitoring starts {eastern.strftime('%b %-d, %Y at %-I:%M %p %Z')}."


def parent_reference_price(parent):
    return reference_price(parent.symbol, broker=parent.broker, instrument_type=parent.instrument_type,
                           user_id=parent.user_id, environment=parent.environment,
                           trading_session=parent.trading_session or 'CORE')


def extended_limit_price(side, price, cap_pct):
    """A Limit price past the trigger by ``cap_pct`` so the order fills like a market order, capped."""
    cap = (cap_pct if cap_pct else DEFAULT_LIMIT_CAP_PCT) / 100.0
    raw = Decimal(str(price)) * Decimal(str(1 + cap if side == 'BUY' else 1 - cap))
    step = Decimal('0.01') if raw >= 1 else Decimal('0.0001')
    rounding = 'ROUND_DOWN' if side == 'BUY' else 'ROUND_UP'
    return float(raw.quantize(step, rounding=rounding))


def is_budget(parent):
    """A buy ladder/bracket sized by a quote budget instead of a shared base quantity."""
    return bool(getattr(parent, 'quote_budget', None)) and parent.side == 'BUY' and not getattr(parent, 'conditional_spec', None)


def budget_used_pct(parent, rows):
    """Percent of a budget strategy's quote budget its executions have used.

    Executions are replayed oldest first. A ladder step claims its share of
    the budget, capped by what is left; a single or trailing branch claims all
    that is left. Each execution uses its claim in proportion to how much of
    its requested quantity filled, so fill prices never enter the accounting
    and a fully filled final claim uses the budget exactly.
    """
    rungs = {r.id: r for r in (getattr(parent, 'rungs', None) or [])}
    used = 0.0
    for row in sorted(rows, key=lambda r: r.id or 0):
        requested = float(row.quantity or 0)
        if requested <= 0:
            continue
        left = max(0.0, 100.0 - used)
        rung = rungs.get(row.rung_id)
        claim = min(float(rung.percentage_of_total or 0), left) if rung is not None else left
        used += claim * min(1.0, float(row.filled_quantity or 0) / requested)
    return min(100.0, used)


def budget_remaining(parent, rows):
    """Quote currency of a budget strategy not yet used by fills."""
    return float(parent.quote_budget) * max(0.0, 100.0 - budget_used_pct(parent, rows)) / 100.0


def budget_quantity(parent, quote_amount, price, trigger_price=None):
    """Base quantity that ``quote_amount`` buys at the price this execution can pay at most."""
    extended = session_phase(parent) == 'EXTENDED' and not parent.test_mode
    basis = extended_limit_price(parent.side, trigger_price if trigger_price is not None else price, parent.limit_cap_pct) if extended else price
    qty = float(quote_amount) / float(basis)
    return math.floor(qty + 1e-9) if extended and parent.instrument_type != 'CRYPTO' else qty


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


def webull_buy_cash(parent):
    if parent.test_mode:
        from services.webull_paper_trading_service import available_paper_buy_cash
        return available_paper_buy_cash(parent.user_id)
    from services.webull_service import get_webull_account_balance
    cred, env = webull_credentials(parent)
    balance = get_webull_account_balance(cred.webull_app_key, cred.webull_app_secret, env,
                                         cred.webull_access_token, parent.account_id)
    if isinstance(balance, dict):
        for key in ('available_cash', 'availableCash', 'free_cash', 'freeCash', 'total_cash_balance'):
            value = balance.get(key)
            if value in (None, ''):
                continue
            amount = float(str(value).replace(',', '').replace('$', ''))
            if math.isfinite(amount):
                return max(0.0, amount)
            break
    raise ValueError('Could not verify available cash in the selected Webull account.')


def check_live_funding(parent, quantity, price, rules):
    """Recheck the selected account immediately before transmission; never open a short."""
    if parent.test_mode:
        return
    if parent.broker == 'binance':
        asset = rules['base'] if parent.side == 'SELL' else rules['quote']
        balance = binance_client(parent.user_id).get_asset_balance(asset=asset)
        available = float((balance or {}).get('free') or 0)
        required = quantity if parent.side == 'SELL' else quantity * price
    elif parent.side == 'BUY':
        available = webull_buy_cash(parent)
        required = quantity * price
    else:
        from services.webull_service import get_webull_account_positions
        cred, env = webull_credentials(parent)
        args = (cred.webull_app_key, cred.webull_app_secret, env, cred.webull_access_token, parent.account_id)
        positions = get_webull_account_positions(*args)
        def matches(position):
            symbol = str(position.get('symbol') or '').upper()
            if parent.instrument_type == 'CRYPTO' and not symbol.endswith('USD'):
                symbol += 'USD'
            return symbol == parent.symbol and str(position.get('side') or '').upper() != 'SHORT'
        available = sum(max(0, float(p.get('available_quantity', p.get('quantity', 0)) or 0)) for p in positions if matches(p))
        required = quantity
    if not math.isfinite(available) or available + 1e-10 < required:
        raise ValueError('The selected account no longer has sufficient available assets or cash for this execution.')


def get_synthetic_locked_funds(user_id, symbol, side, broker='binance', test_mode=False, exclude_order_id=None, account_id=None):
    """Calculate the total quantity (for SELL) or quote budget/cost (for BUY) tied up in working synthetic orders."""
    from trading_models import LadderOrder, TrailingOrder
    clean_sym = str(symbol or '').strip().upper()
    clean_side = str(side or '').strip().upper()
    clean_broker = str(broker or 'binance').strip().lower()

    base_asset = next((clean_sym[:-len(q)] for q in ('USDT', 'USDC', 'USD') if clean_sym.endswith(q)), clean_sym)
    quote_asset = 'USD' if clean_sym.endswith('USD') and not clean_sym.endswith('USDT') else 'USDT' if clean_sym.endswith('USDT') else 'USD'

    total_locked = 0.0

    # 1. Trailing Orders
    trails = TrailingOrder.query.filter(
        TrailingOrder.user_id == user_id,
        TrailingOrder.status.in_(WORKING_PARENTS),
        TrailingOrder.test_mode == test_mode,
        TrailingOrder.side == clean_side
    ).all()
    for to in trails:
        if exclude_order_id and str(exclude_order_id) in (f"trail_{to.id}", str(to.id)):
            continue
        if account_id and to.account_id != account_id:
            continue
        to_broker = (to.broker or 'binance').lower()
        if clean_broker and to_broker != clean_broker:
            continue
        to_sym = (to.symbol or '').upper()
        to_base = next((to_sym[:-len(q)] for q in ('USDT', 'USDC', 'USD') if to_sym.endswith(q)), to_sym)
        to_quote = 'USD' if to_sym.endswith('USD') and not to_sym.endswith('USDT') else 'USDT' if to_sym.endswith('USDT') else 'USD'
        if clean_side == 'SELL' and to_base == base_asset:
            total_locked += float(to.to_dict().get('remaining_quantity') or 0.0)
        elif clean_side == 'BUY' and to_quote == quote_asset:
            total_locked += float(to.to_dict().get('remaining_quantity') or 0.0) * float(to.current_stop_price or 0.0)

    # 2. Ladder Orders
    ladders = LadderOrder.query.filter(
        LadderOrder.user_id == user_id,
        LadderOrder.status.in_(WORKING_PARENTS),
        LadderOrder.test_mode == test_mode,
        LadderOrder.side == clean_side
    ).all()
    for lo in ladders:
        if exclude_order_id and str(exclude_order_id) in (f"ladder_{lo.id}", str(lo.id)):
            continue
        if account_id and lo.account_id != account_id:
            continue
        lo_broker = (lo.broker or 'binance').lower()
        if clean_broker and lo_broker != clean_broker:
            continue
        lo_sym = (lo.symbol or '').upper()
        lo_base = next((lo_sym[:-len(q)] for q in ('USDT', 'USDC', 'USD') if lo_sym.endswith(q)), lo_sym)
        lo_quote = 'USD' if lo_sym.endswith('USD') and not lo_sym.endswith('USDT') else 'USDT' if lo_sym.endswith('USDT') else 'USD'
        lo_details = lo.to_dict()
        rem_qty = float(lo_details.get('remaining_quantity', lo.total_quantity) or 0.0)
        if clean_side == 'SELL' and lo_base == base_asset:
            total_locked += rem_qty
        elif clean_side == 'BUY' and lo_quote == quote_asset:
            tot_qty = float(lo.total_quantity or 1.0)
            if is_budget(lo):
                total_locked += budget_remaining(lo, executions(lo, 'LADDER'))
            elif lo.total_budget_usd:
                total_locked += float(lo.total_budget_usd) * (rem_qty / tot_qty)
            else:
                if lo.conditional_spec:
                    import json
                    legs = json.loads(lo.conditional_spec)['legs']
                    candidates = legs[1:] if lo.conditional_phase == 'EXIT' else legs[:1] if lo.conditional_phase == 'ENTRY' else legs
                    from services.pending_order_serializer import leg_reserve_price
                    lo_px = max(leg_reserve_price(leg, lo.limit_cap_pct) for leg in candidates)
                else:
                    lo_px = float(lo.upside_target_price or lo.downside_target_price or 0.0)
                total_locked += rem_qty * lo_px

    return total_locked


def check_synthetic_order_capacity(user_id, symbol, side, quantity, broker='binance', test_mode=False, account_id=None):
    """
    Check if existing pending synthetic orders tie up available funds when creating a new (non-replacement) synthetic order.
    Raises ValueError with user-friendly message if funds are exhausted.
    """
    if test_mode:
        return
    clean_sym = str(symbol or '').strip().upper()
    clean_side = str(side or '').strip().upper()
    clean_broker = str(broker or 'binance').strip().lower()
    qty = float(quantity or 0.0)

    locked = get_synthetic_locked_funds(user_id, clean_sym, clean_side, broker=clean_broker, test_mode=False, account_id=account_id)
    if locked <= 0:
        return

    if clean_broker == 'binance':
        try:
            client = binance_client(user_id)
            account = client.get_account()
        except Exception as err:
            logger.warning(f"Could not fetch Binance balance in check_synthetic_order_capacity: {err}")
            return
        balances = {b['asset']: float(b.get('free') or 0.0) for b in account.get('balances', [])}
        if clean_side == 'SELL':
            base_asset = next((clean_sym[:-len(q)] for q in ('USDT', 'USDC', 'USD') if clean_sym.endswith(q)), clean_sym)
            avail = balances.get(base_asset, 0.0)
            if avail <= locked or (qty > max(0.0, avail - locked) + 1e-8):
                raise ValueError('Pending synthetic order ties up all available funds. Replace the existing order instead.')
        elif clean_side == 'BUY':
            quote_asset = 'USD' if clean_sym.endswith('USD') and not clean_sym.endswith('USDT') else 'USDT' if clean_sym.endswith('USDT') else 'USD'
            avail = balances.get(quote_asset, 0.0)
            if avail <= locked:
                raise ValueError('Pending synthetic order ties up all available funds. Replace the existing order instead.')
    elif clean_broker == 'webull':
        try:
            from services.webull_service import get_webull_account_positions, get_webull_account_balance
            from trading_models import WebullCredential
            cred = WebullCredential.query.filter_by(user_id=user_id).first()
            if not cred or not cred.webull_app_key:
                return
            env = 'trade'
            args = (cred.webull_app_key, cred.webull_app_secret, env, cred.webull_access_token, account_id)
            if clean_side == 'SELL':
                positions = get_webull_account_positions(*args)
                def matches(position):
                    s = str(position.get('symbol') or '').upper()
                    if not s.endswith('USD'):
                        s += 'USD'
                    return s == clean_sym and str(position.get('side') or '').upper() != 'SHORT'
                avail = sum(max(0, float(p.get('available_quantity', p.get('quantity', 0)) or 0)) for p in positions if matches(p))
                if avail <= locked or (qty > max(0.0, avail - locked) + 1e-8):
                    raise ValueError('Pending synthetic order ties up all available funds. Replace the existing order instead.')
            elif clean_side == 'BUY':
                balance = get_webull_account_balance(*args)
                avail = float(balance.get('available_cash', balance.get('total_cash_balance', 0)) or 0)
                if avail <= locked:
                    raise ValueError('Pending synthetic order ties up all available funds. Replace the existing order instead.')
        except Exception as webull_err:
            if isinstance(webull_err, ValueError) and 'Pending synthetic order' in str(webull_err):
                raise
            logger.warning(f"Could not verify Webull balance in check_synthetic_order_capacity: {webull_err}")



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
    if getattr(parent, 'conditional_spec', None):
        from services.synthetic_conditional_service import phase_rows
        summary_rows = phase_rows(parent, rows)
    else:
        summary_rows = rows
    total = float(parent.total_quantity if kind == 'LADDER' else parent.quantity)
    filled = sum(float(x.filled_quantity or 0) for x in summary_rows)
    reserved = sum(max(0, x.quantity - (x.filled_quantity or 0)) for x in rows if x.status in OPEN_EXECUTIONS)
    verified = parent.engine_version == 2
    from trading_models import SyntheticRecovery
    recovery = SyntheticRecovery.query.filter_by(user_id=parent.user_id, parent_kind=kind, parent_id=parent.id).first() if inspect(parent).persistent else None
    unresolved = any(x.status in OPEN_EXECUTIONS for x in rows)
    failed = parent.status == 'FAILED'
    label = ('Partially filled — remainder cancelled' if filled else 'Failed — no shares filled') if failed else ('Partially filled — remainder cancelled' if filled and parent.status == 'CANCELLED' else parent.status.replace('_', ' ').title())
    if unresolved:
        label = 'Awaiting broker confirmation' if any(x.status in {'UNKNOWN', 'SUBMITTING'} for x in rows) else ('Cancellation pending' if parent.cancel_requested else 'Partially filled — working' if filled else 'Submitted')
    if unresolved and any('cancellation requested' in (x.error_message or '').lower() for x in rows):
        label = 'Cancellation pending — awaiting broker confirmation'
    budget = {}
    if kind == 'LADDER' and is_budget(parent):
        used = budget_used_pct(parent, rows)
        budget = {'budget_used_pct': used, 'budget_remaining': float(parent.quote_budget) * max(0.0, 100.0 - used) / 100.0}
    return {**budget, 'status_label': label, 'recovery_available': failed and not unresolved and verified and not recovery,
            'recovery_action': recovery.action if recovery else None,
            'replacement_id': recovery.replacement_id if recovery else None,
            'filled_quantity': filled if verified else None, 'remaining_quantity': max(0, total - filled) if verified else None, 'pending_quantity': reserved if verified else None,
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


def submit_execution(parent, kind, quantity, price, leg, rung=None, explicit_limit=None, trigger_price=None):
    rules = quantity_rules(parent)
    quantity = normalize_quantity(quantity, rules)
    # Workers only call this while the parent's session is open; an
    # extended-hours session is the one case that needs a capped Limit order.
    extended = session_phase(parent) == 'EXTENDED' and not parent.test_mode
    limit_price = None
    if extended:
        if not float(quantity).is_integer():
            raise ValueError('Extended-hours executions require whole shares.')
        limit_price = extended_limit_price(parent.side, trigger_price if trigger_price is not None else price, getattr(parent, 'limit_cap_pct', None))
    if explicit_limit is not None:
        limit_price = positive(explicit_limit, "Limit price")
    use_limit = extended or explicit_limit is not None
    funding_price = limit_price if use_limit and parent.side == 'BUY' else price
    check_quantity(parent, quantity, price, rules)
    check_order_limit(parent, quantity, funding_price, rules)
    check_live_funding(parent, quantity, funding_price, rules)
    row = SyntheticExecution(user_id=parent.user_id, parent_kind=kind, parent_id=parent.id,
                             rung_id=rung.id if rung else None, leg=leg, quantity=quantity,
                             client_order_id='syn' + uuid4().hex[:29], filled_quantity=0, status='SUBMITTING',
                             order_type='LIMIT' if use_limit else 'MARKET', limit_price=limit_price)
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
            if use_limit:
                result = place_webull_order(cred.webull_app_key, cred.webull_app_secret, env, cred.webull_access_token,
                    account_id=parent.account_id, symbol=parent.symbol, instrument_type=parent.instrument_type,
                    side=parent.side, order_type='LIMIT', quantity=quantity, limit_price=limit_price,
                    time_in_force='DAY', support_trading_session=parent.trading_session, client_order_id=row.client_order_id)
            else:
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
                row.error_message = f'Broker rejected this execution: {exc}'
    db.session.commit()
    return row


def _limit_timeout_applies(parent):
    """Whether the 5-minute synthetic Limit timeout may fire for this parent.

    The timeout exists for extended-hours marketable limits. A conditional
    synthetic Limit on a Webull stock/ETF that has never traded (an IPO
    still in price discovery) is exempt: its order is meant to rest at the
    broker until trading opens, not be timed out from under the synthetic.
    Any doubt (other order kinds, quote unavailable) keeps the timeout.
    """
    if parent.broker != 'webull' or parent.instrument_type not in {'EQUITY', 'ETF'}:
        return True
    if getattr(parent, 'strategy_type', None) != 'LIMIT' or not getattr(parent, 'conditional_spec', None):
        return True
    try:
        from services.webull_service import get_webull_market_snapshot
        cred, env = webull_credentials(parent)
        quote = get_webull_market_snapshot(cred.webull_app_key, cred.webull_app_secret, env,
                                           cred.webull_access_token, symbol=parent.symbol,
                                           instrument_type=parent.instrument_type)
    except Exception:
        return True
    return bool(quote.get('has_traded'))


NOT_FOUND_EXECUTION_MESSAGE = ('Webull reports no order with this client ID, so the submission '
                               'never reached the broker. The execution is closed as cancelled.')


def _broker_order_not_found(exc):
    """True only when the broker definitively states the order does not exist.

    Webull answers an order-detail lookup for an unknown client_order_id with
    HTTP 417 / OPENAPI_PARAM_ERR / "Order not present." (verified live against
    a phantom execution and a bogus client ID). Any other failure (network,
    5xx, throttling) is ambiguous and must keep waiting: the order may exist.
    """
    if 'not present' not in str(exc).lower():
        return False
    return (getattr(exc, 'error_code', None) == 'OPENAPI_PARAM_ERR'
            or getattr(exc, 'http_status', None) == 417)


def _resolve_not_found(row):
    """Close an UNKNOWN execution the broker has never heard of."""
    row.status = 'CANCELLED'
    row.error_message = NOT_FOUND_EXECUTION_MESSAGE
    row.updated_at = utc_now(aware=False)


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
        except Exception as exc:
            if row.status == 'UNKNOWN' and parent.broker == 'webull' and _broker_order_not_found(exc):
                _resolve_not_found(row)
            else:
                row.error_message = 'Awaiting broker confirmation. No additional order will be sent while this execution is unresolved.'
        timed_out = row.order_type == 'LIMIT' and not parent.cancel_requested and row.created_at is not None and (
            utc_now(aware=False) - row.created_at).total_seconds() >= EXTENDED_LIMIT_TIMEOUT_SECONDS
        if timed_out and not _limit_timeout_applies(parent):
            timed_out = False
        if row.order_type == 'LIMIT' and row.status == 'CANCELLED' and not parent.cancel_requested \
                and row.error_message != NOT_FOUND_EXECUTION_MESSAGE:
            row.error_message = EXTENDED_TIMEOUT_MESSAGE
        if (parent.cancel_requested or timed_out) and row.status in OPEN_EXECUTIONS:
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
                if timed_out:
                    row.error_message = EXTENDED_TIMEOUT_MESSAGE if row.status == 'CANCELLED' else 'Limit order timed out; cancellation requested. Awaiting final broker confirmation.'
            except Exception as exc:
                if row.status == 'UNKNOWN' and parent.broker == 'webull' and _broker_order_not_found(exc):
                    _resolve_not_found(row)
                else:
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
