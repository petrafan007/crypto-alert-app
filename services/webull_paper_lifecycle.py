"""Forward-only paper fills and explicit cash settlement of expired paper options."""
import json
import math
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from core.extensions import db
from models import WebullTestOrder, WebullTestPosition
from services.portfolio_strategy_signals import session_bounds, in_session

ET = ZoneInfo('America/New_York')
OPTION_SYMBOL = re.compile(r'^(.+?)\s+(\d{4}-\d{2}-\d{2})\s+\$([\d.]+)\s+(CALL|PUT)$')


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def expiry_close(expiration):
    day = datetime.fromisoformat(str(expiration)[:10]).date()
    for _ in range(8):
        bounds = session_bounds(day)
        if bounds:
            return bounds[1]
        day -= timedelta(days=1)
    raise ValueError('No exchange session found for expiration.')


def day_order_close(created):
    created = utc(created)
    day = created.astimezone(ET).date()
    for _ in range(8):
        bounds = session_bounds(day)
        if bounds and bounds[1] > created:
            return bounds[1]
        day += timedelta(days=1)
    raise ValueError('No exchange session found for DAY order.')


def historical_expiry_price(symbol, expiration):
    import yfinance as yf
    close = expiry_close(expiration)
    day = close.astimezone(ET).date()
    rows = yf.Ticker(symbol).history(start=day.isoformat(), end=(day + timedelta(days=1)).isoformat(), auto_adjust=False, timeout=8)
    for stamp, row in rows.iterrows():
        if stamp.date() == day and float(row['Close']) > 0:
            return float(row['Close'])
    raise ValueError('Official-date closing price unavailable; settlement remains pending.')


def reconcile_paper_options(user_id, now=None, close_resolver=None, quote_resolver=None):
    from services.webull_paper_trading_service import _lock_webull_test_account, fetch_live_price
    now = utc(now or datetime.now(timezone.utc))
    account = _lock_webull_test_account(user_id)
    orders = WebullTestOrder.query.filter_by(user_id=user_id).order_by(WebullTestOrder.id).all()
    positions = WebullTestPosition.query.filter_by(user_id=user_id, instrument_type='OPTION').filter(WebullTestPosition.quantity > 0).all()
    for order in orders:
        if order.status not in ('Working', 'Open'):
            continue
        match = OPTION_SYMBOL.match(order.symbol)
        expired = bool(match and expiry_close(match[2]) <= now)
        if not expired and order.time_in_force == 'DAY' and order.instrument_type not in ('CRYPTO', 'EVENT'):
            expired = day_order_close(order.created_at) <= now
        if expired:
            order.status = 'Expired'
            order.updated_at = now.replace(tzinfo=None)
            # Zero-fill orders expire as instructions; they never become holdings.
            continue
    for pos in positions:
        if not pos.option_expiration or expiry_close(pos.option_expiration) > now:
            continue
        event_id = f'SIM_EXPIRY_{pos.id}'
        if any(order.order_id == event_id for order in orders):
            continue
        try:
            underlying = (close_resolver or historical_expiry_price)(pos.underlying_symbol or pos.symbol.split()[0], pos.option_expiration)
        except Exception:
            continue
        if underlying is None or not math.isfinite(float(underlying)) or float(underlying) <= 0:
            continue
        intrinsic = max(0.0, float(underlying) - pos.option_strike) if pos.option_type == 'CALL' else max(0.0, pos.option_strike - float(underlying))
        intrinsic = round(intrinsic, 4)
        qty = pos.quantity
        signed = -1 if pos.side == 'SHORT' else 1
        cash_adjustment = round(signed * intrinsic * qty * (pos.contract_multiplier or 100), 2)
        account.cash_balance = round(account.cash_balance + cash_adjustment, 2)
        db.session.add(WebullTestOrder(order_id=event_id, user_id=user_id, symbol=pos.symbol, instrument_type='OPTION',
            side='SETTLEMENT', order_type='EXPIRATION_SETTLEMENT', quantity=qty, filled_quantity=0,
            filled_price=intrinsic, status='Settled', created_at=now.replace(tzinfo=None), updated_at=now.replace(tzinfo=None),
            combo_orders=json.dumps({'event': 'paper_cash_settlement', 'effective_at': expiry_close(pos.option_expiration).isoformat(),
                'underlying_close': underlying, 'cash_adjustment': cash_adjustment,
                'note': 'Paper option cash settlement at expiration intrinsic value; no physical exercise or broker trade.'})))
        pos.quantity = 0
        pos.last_price = intrinsic
        pos.updated_at = now.replace(tzinfo=None)
    # Working options receive only new, observed fills; never reconstruct a past fill.
    if in_session(now):
        for order in orders:
            match = OPTION_SYMBOL.match(order.symbol)
            if order.status not in ('Working', 'Open') or order.combo_type or not match or order.order_type not in ('MARKET', 'LIMIT'):
                continue
            if order.side not in ('BUY', 'BUY_TO_OPEN', 'SELL', 'SELL_TO_CLOSE'):
                continue
            try:
                price = (quote_resolver or fetch_live_price)(user_id, match[1], 'OPTION', option_expiration=match[2], option_strike=float(match[3]), option_type=match[4], execution_side=order.side)
            except Exception:
                continue
            if price is None or not math.isfinite(price) or price <= 0:
                continue
            buying = order.side in ('BUY', 'BUY_TO_OPEN')
            if order.order_type == 'LIMIT' and (order.limit_price is None or (price > order.limit_price if buying else price < order.limit_price)):
                continue
            qty = max(0, order.quantity - (order.filled_quantity or 0))
            if qty <= 0:
                continue
            pos = WebullTestPosition.query.filter_by(user_id=user_id, symbol=order.symbol, side='LONG').first()
            if buying:
                # Retain cash reserved for all other active instructions.
                from services.webull_paper_trading_service import _reserved_cash_amount, _current_short_margin, _reserved_short_margin
                order.status = 'Processing'
                db.session.flush()
                available = account.cash_balance - _reserved_cash_amount(user_id) - _current_short_margin(user_id) - _reserved_short_margin(user_id)
                order.status = 'Working'
                if available < qty * price * 100:
                    continue
                if pos is None:
                    pos = WebullTestPosition(user_id=user_id, symbol=order.symbol, underlying_symbol=match[1], instrument_type='OPTION', side='LONG', quantity=0, cost_price=0,
                        option_expiration=match[2], option_strike=float(match[3]), option_type=match[4], contract_multiplier=100)
                    db.session.add(pos)
                pos.cost_price = (pos.cost_price * pos.quantity + price * qty) / (pos.quantity + qty)
                pos.quantity += qty
                account.cash_balance -= qty * price * 100
            else:
                if pos is None or pos.quantity < qty:
                    continue
                pos.quantity -= qty
                account.cash_balance += qty * price * 100
            pos.last_price = price
            pos.updated_at = now.replace(tzinfo=None)
            order.filled_price = price
            order.filled_quantity = order.quantity
            order.status = 'Filled'
            order.updated_at = now.replace(tzinfo=None)
    db.session.commit()
