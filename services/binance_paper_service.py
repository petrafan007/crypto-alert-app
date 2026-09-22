"""Funding and transactional accounting for the Binance.US simulated ledger."""
from contextlib import ExitStack
from decimal import Decimal, InvalidOperation
import math
from core.extensions import db
from core.time_utils import utc_now
from trading_models import TestPortfolio, TestOrder, TradingSettings, LadderOrder, TrailingOrder


def account_summary(user_id):
    rows = TestPortfolio.query.filter_by(user_id=user_id).all()
    return {'balances': {currency: sum(float(r.quantity or 0) for r in rows if r.symbol == currency) for currency in ('USD', 'USDT')},
            'holdings_count': sum(float(r.quantity or 0) > 0 and r.symbol not in {'USD', 'USDT'} for r in rows)}


def fund_account(user_id, amount, currency='USD', *, reset=False, confirmed=False):
    settings = TradingSettings.query.filter_by(user_id=user_id).first()
    if not settings or not settings.test_mode_enabled:
        raise ValueError('Enable Binance.US Test Mode before funding or resetting its paper account.')
    if currency not in {'USD', 'USDT'}:
        raise ValueError('Choose USD or USDT paper funds.')
    if reset and confirmed is not True:
        raise ValueError('Confirm the paper account reset before continuing.')
    try:
        value = Decimal(str(amount))
        if not value.is_finite() or value < 0 or value > Decimal('1000000000') or (not reset and value == 0):
            raise ValueError()
        if value != value.quantize(Decimal('.01')):
            raise ValueError()
    except (ValueError, InvalidOperation):
        raise ValueError('Enter a positive amount up to 1,000,000,000 with at most two decimal places.') from None
    from services.synthetic_execution_service import parent_lock
    with ExitStack() as locks:
        if reset:
            for model, kind in ((LadderOrder, 'LADDER'), (TrailingOrder, 'TRAILING')):
                for row in model.query.filter_by(user_id=user_id, broker='binance', test_mode=True).all():
                    if not locks.enter_context(parent_lock(kind, row.id)):
                        raise ValueError('A paper execution is in progress. Try the reset again.')
        if not locks.enter_context(parent_lock('BINANCE_PAPER', user_id)):
            raise ValueError('The paper account is busy. Try again.')
        rows = TestPortfolio.query.filter_by(user_id=user_id).populate_existing().with_for_update().all()
        if reset:
            for row in rows:
                row.quantity = row.total_cost_basis = row.realized_pnl = row.unrealized_pnl = row.avg_entry_price = 0
                row.last_updated = utc_now(aware=False)
            for order in TestOrder.query.filter_by(user_id=user_id).all():
                if order.status in {'NEW', 'ACTIVE', 'PARTIALLY_FILLED', 'TRIGGERED'}:
                    order.status = 'CANCELED'
            for model in (LadderOrder, TrailingOrder):
                for order in model.query.filter_by(user_id=user_id, broker='binance', test_mode=True).populate_existing().all():
                    if order.status not in {'COMPLETED', 'FILLED', 'STOPPED_OUT', 'CANCELLED'}:
                        order.status, order.cancel_requested = 'CANCELLED', True
                        order.monitoring_error = 'Cancelled by the user when resetting the Binance.US paper account.'
                        if isinstance(order, LadderOrder):
                            for rung in order.rungs:
                                if rung.status not in {'FILLED', 'CANCELLED'}:
                                    rung.status = 'CANCELLED'
            # Preserve history; reset never deletes records or touches live accounts.
        else:
            holding = next((r for r in rows if r.symbol == currency), None)
            if holding is None:
                holding = TestPortfolio(user_id=user_id, symbol=currency, quantity=0, total_cost_basis=0, avg_entry_price=1)
                db.session.add(holding)
            holding.quantity = float(Decimal(str(holding.quantity or 0)) + value)
            holding.total_cost_basis = holding.quantity
            holding.avg_entry_price = 1
            holding.last_updated = utc_now(aware=False)
        db.session.commit()
        return {'success': True, **account_summary(user_id), 'message': 'Paper balances reset to zero and active paper orders cancelled; history retained.' if reset else f'Deposited {value:,.2f} simulated {currency}.'}


def apply_fill(user_id, base, quote, side, quantity, price, fee_rate):
    """Mutate the ledger in the caller's transaction; fees come from received assets."""
    if not all(math.isfinite(v) for v in (quantity, price, fee_rate)) or quantity <= 0 or price <= 0 or not 0 <= fee_rate < 1:
        raise ValueError('Invalid paper fill quantity, price or fee.')
    if side not in {'BUY', 'SELL'} or base == quote:
        raise ValueError('Invalid paper fill side or currency pair.')
    rows = {r.symbol: r for r in TestPortfolio.query.filter_by(user_id=user_id).populate_existing().with_for_update().all()}
    for symbol in (base, quote):
        if symbol not in rows:
            rows[symbol] = TestPortfolio(user_id=user_id, symbol=symbol, quantity=0, total_cost_basis=0, realized_pnl=0)
            db.session.add(rows[symbol])
    asset, cash = rows[base], rows[quote]
    cost = quantity * price
    if side == 'BUY':
        if float(cash.quantity or 0) + 1e-10 < cost:
            raise ValueError(f'Insufficient paper {quote} balance. Deposit fake money first.')
        cash.quantity = max(0, cash.quantity - cost)
        asset.quantity = float(asset.quantity or 0) + quantity * (1 - fee_rate)
        asset.total_cost_basis = float(asset.total_cost_basis or 0) + cost
        asset.avg_entry_price = asset.total_cost_basis / asset.quantity
    elif side == 'SELL':
        if float(asset.quantity or 0) + 1e-10 < quantity:
            raise ValueError(f'Insufficient paper {base} balance.')
        basis = quantity * float(asset.avg_entry_price or 0)
        asset.quantity = max(0, asset.quantity - quantity)
        asset.total_cost_basis = max(0, float(asset.total_cost_basis or 0) - basis)
        asset.realized_pnl = float(asset.realized_pnl or 0) + cost * (1 - fee_rate) - basis
        cash.quantity = float(cash.quantity or 0) + cost * (1 - fee_rate)
    else:
        raise ValueError('Choose BUY or SELL.')
    cash.total_cost_basis = cash.quantity
    cash.avg_entry_price = 1
    asset.last_updated = cash.last_updated = utc_now(aware=False)
    return cost * fee_rate
