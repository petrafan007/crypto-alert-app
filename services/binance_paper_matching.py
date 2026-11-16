"""Exchange-faithful matching for Binance.US paper (Test Mode) orders.

A paper order behaves the way Binance.US would treat the same live order:

* MARKET orders fill at the current market price.
* LIMIT orders fill immediately only when marketable, at the market price
  (the price improvement a live taker receives); otherwise they rest.
* LIMIT_MAKER orders that would match immediately are rejected.
* Stop and take-profit orders are rejected when their trigger would fire
  immediately; otherwise they rest until the market reaches the trigger. A
  *_LIMIT variant then works as a limit order at its limit price.
* The two legs of a paper OCO share an ``oco_group``; when one fills the
  other is cancelled.

Resting orders are matched by a background loop against public prices.
"""
import logging
import uuid
from datetime import datetime

from core.extensions import db
from trading_models import TestOrder, TestPortfolio

logger = logging.getLogger(__name__)

RESTING_STATUSES = ('NEW', 'TRIGGERED')
QUOTES = ('USDT', 'USDC', 'USD', 'BTC', 'ETH', 'BNB')
STOP_TYPES = {'STOP_LOSS', 'STOP_LOSS_LIMIT'}
TAKE_PROFIT_TYPES = {'TAKE_PROFIT', 'TAKE_PROFIT_LIMIT'}
LIMIT_TYPES = {'LIMIT', 'LIMIT_MAKER'}


class PaperOrderRejected(ValueError):
    """The paper order would be rejected by Binance.US."""


def split_symbol(symbol):
    quote = next((q for q in QUOTES if symbol.endswith(q) and len(symbol) > len(q)), None)
    if not quote:
        raise PaperOrderRejected('Unsupported paper quote currency.')
    return symbol[:-len(quote)], quote


def new_oco_group():
    return uuid.uuid4().hex[:16]


def trigger_reached(order_type, side, stop_price, market):
    """Whether a stop/take-profit trigger has been reached at ``market``."""
    if not stop_price or not market:
        return False
    if order_type in STOP_TYPES:
        return market <= stop_price if side == 'SELL' else market >= stop_price
    if order_type in TAKE_PROFIT_TYPES:
        return market >= stop_price if side == 'SELL' else market <= stop_price
    return False


def limit_marketable(side, limit_price, market):
    if not limit_price or not market:
        return False
    return limit_price >= market if side == 'BUY' else limit_price <= market


def immediate_fill_price(order_type, side, price, stop_price, market, *, triggered=False):
    """Return the fill price if the order executes now, else None."""
    if order_type == 'MARKET':
        return market
    if order_type in LIMIT_TYPES:
        return market if limit_marketable(side, price, market) else None
    if order_type in STOP_TYPES | TAKE_PROFIT_TYPES:
        if not (triggered or trigger_reached(order_type, side, stop_price, market)):
            return None
        if order_type.endswith('_LIMIT'):
            return market if limit_marketable(side, price, market) else None
        return market
    return None


def validate_new_order(order_type, side, price, stop_price, market):
    """Reject orders Binance.US itself would reject at submission."""
    if order_type == 'LIMIT_MAKER' and limit_marketable(side, price, market):
        raise PaperOrderRejected('Order would immediately match and take (LIMIT_MAKER orders must rest on the book).')
    if order_type in STOP_TYPES | TAKE_PROFIT_TYPES and trigger_reached(order_type, side, stop_price, market):
        raise PaperOrderRejected('Stop price would trigger immediately.')


def reserved_by_resting_orders(user_id, asset, *, exclude_ids=()):
    """Paper funds already committed to resting orders, by the asset they spend."""
    total = 0.0
    seen_groups = set()
    for order in TestOrder.query.filter(TestOrder.user_id == user_id,
                                        TestOrder.status.in_(RESTING_STATUSES)).all():
        if order.id in exclude_ids:
            continue
        group = getattr(order, 'oco_group', None)
        if group:
            # The two OCO legs hold funds for one branch, not both.
            if group in seen_groups:
                continue
            seen_groups.add(group)
        try:
            base, quote = split_symbol(order.symbol)
        except PaperOrderRejected:
            continue
        if order.side == 'BUY' and quote == asset:
            if group:
                legs = TestOrder.query.filter_by(user_id=user_id, oco_group=group).all()
                total += max(float(l.quantity or 0) * float(l.price or l.stop_price or 0) for l in legs)
            else:
                total += float(order.quantity or 0) * float(order.price or order.stop_price or 0)
        elif order.side == 'SELL' and base == asset:
            total += float(order.quantity or 0)
    return total


def check_paper_funds(user_id, symbol, side, quantity, price):
    base, quote = split_symbol(symbol)
    balances = {r.symbol: float(r.quantity or 0) for r in TestPortfolio.query.filter_by(user_id=user_id).all()}
    if side == 'BUY':
        needed = quantity * price
        free = balances.get(quote, 0.0) - reserved_by_resting_orders(user_id, quote)
        if needed > free + 1e-9:
            raise PaperOrderRejected(f'Insufficient paper {quote} balance after open paper orders. Available: {max(free, 0):.8f} {quote}.')
    else:
        free = balances.get(base, 0.0) - reserved_by_resting_orders(user_id, base)
        if quantity > free + 1e-9:
            raise PaperOrderRejected(f'Insufficient paper {base} balance after open paper orders. Available: {max(free, 0):.8f} {base}.')


def fill_order(order, fill_price, fee_rate):
    """Apply a fill to the paper ledger in the caller's transaction."""
    from services.binance_paper_service import apply_fill
    base, quote = split_symbol(order.symbol)
    apply_fill(order.user_id, base, quote, order.side, float(order.quantity), float(fill_price), fee_rate)
    order.status = 'FILLED'
    order.simulated_fill_price = float(fill_price)
    order.simulated_fill_time = datetime.utcnow()
    commission = float(order.quantity) * float(fill_price) * fee_rate
    order.notes = f'Simulated fill at market {fill_price:g}; commission ${commission:.4f} ({fee_rate * 100:.2f}% paper rate)'
    group = getattr(order, 'oco_group', None)
    if group:
        for sibling in TestOrder.query.filter(TestOrder.user_id == order.user_id, TestOrder.oco_group == group,
                                              TestOrder.id != order.id, TestOrder.status.in_(RESTING_STATUSES)).all():
            sibling.status = 'CANCELED'
            sibling.notes = 'Cancelled because the other leg of this paper OCO filled.'


def _fee_rate(order):
    from services.binance_fee_service import paper_rates
    rates = paper_rates(order.symbol)
    # A resting limit order adds liquidity; a triggered stop takes it.
    return rates['makerRate' if order.type in LIMIT_TYPES else 'takerRate']


def _price_map():
    from services.synthetic_execution_service import binance_client
    tickers = binance_client(public=True).get_symbol_ticker()
    return {t['symbol']: float(t['price']) for t in tickers if float(t.get('price') or 0) > 0}


def match_resting_orders(price_lookup=None):
    """Fill or trigger resting paper orders whose conditions are now met."""
    resting = TestOrder.query.filter(TestOrder.status.in_(RESTING_STATUSES)).order_by(TestOrder.id).all()
    if not resting:
        return 0
    prices = price_lookup() if price_lookup else _price_map()
    from services.synthetic_execution_service import parent_lock
    from services.notification_service import create_system_notification
    filled = 0
    for user_id in sorted({o.user_id for o in resting}):
        with parent_lock('BINANCE_PAPER', user_id) as acquired:
            if not acquired:
                continue
            orders = TestOrder.query.filter(TestOrder.user_id == user_id, TestOrder.status.in_(RESTING_STATUSES)) \
                .populate_existing().order_by(TestOrder.id).all()
            for order in orders:
                if order.status not in RESTING_STATUSES:
                    continue  # cancelled as the other leg of an OCO in this pass
                market = prices.get(order.symbol)
                if not market:
                    continue
                if order.status == 'NEW' and order.type in STOP_TYPES | TAKE_PROFIT_TYPES \
                        and trigger_reached(order.type, order.side, order.stop_price, market):
                    order.status = 'TRIGGERED'
                fill_price = immediate_fill_price(order.type, order.side, order.price, order.stop_price, market,
                                                  triggered=order.status == 'TRIGGERED')
                if fill_price is None:
                    continue
                try:
                    with db.session.begin_nested():
                        fill_order(order, fill_price, _fee_rate(order))
                except ValueError as exc:
                    order.status = 'REJECTED'
                    order.notes = f'Paper fill rejected: {exc}'
                    create_system_notification(user_id, 'order_canceled', order.symbol,
                                               f'Paper order {order.id} for {order.symbol} could not fill: {exc}')
                    continue
                filled += 1
                create_system_notification(
                    user_id, 'order_filled', order.symbol,
                    f'Paper {order.side} {order.type} order {order.id} filled: {order.quantity:g} {order.symbol} at {fill_price:g}.',
                    current_price=fill_price)
            db.session.commit()
    return filled
