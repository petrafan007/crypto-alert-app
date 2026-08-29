import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from core.extensions import db
from models import WebullTestAccount, WebullTestPosition, WebullTestOrder
from credentials import Credential, UserSetting

logger = logging.getLogger(__name__)

DEFAULT_INITIAL_PAPER_BALANCE = 10000.0


def get_or_create_webull_test_account(user_id: int) -> WebullTestAccount:
    """Retrieve or create the simulated paper trading account for a user."""
    account = WebullTestAccount.query.filter_by(user_id=user_id).first()
    if not account:
        account = WebullTestAccount(
            user_id=user_id,
            cash_balance=DEFAULT_INITIAL_PAPER_BALANCE,
            currency='USD',
        )
        db.session.add(account)
        db.session.commit()
    return account


def deposit_fake_money(user_id: int, amount: float, reset: bool = False) -> Dict[str, Any]:
    """Deposit simulated fake money into the user's paper account, or reset it."""
    account = get_or_create_webull_test_account(user_id)
    amount = float(amount or 0.0)

    if reset:
        account.cash_balance = amount if amount > 0 else DEFAULT_INITIAL_PAPER_BALANCE
        # Reset positions if full reset requested
        WebullTestPosition.query.filter_by(user_id=user_id).delete()
    else:
        if amount <= 0:
            raise ValueError("Deposit amount must be greater than zero.")
        account.cash_balance = float(account.cash_balance or 0.0) + amount

    account.updated_at = datetime.utcnow()
    db.session.commit()
    return {
        'success': True,
        'cash_balance': account.cash_balance,
        'currency': account.currency,
        'message': f"Successfully {'reset' if reset else 'deposited'} ${amount:,.2f} simulated funds."
    }


def fetch_live_price(user_id: int, symbol: str, instrument_type: str = 'EQUITY') -> float:
    """Fetch live real-world pricing for paper order execution and valuation."""
    clean_sym = (symbol or '').upper().strip()
    clean_type = (instrument_type or 'EQUITY').upper().strip()

    # 1. Try Webull OpenAPI snapshot if user has connected credentials
    try:
        from credentials import Credential, UserSetting
        from services.webull_service import get_webull_market_snapshot, normalize_webull_environment
        cred = Credential.query.filter_by(user_id=user_id).first()
        setting = UserSetting.query.filter_by(user_id=user_id).first()
        env = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if cred and cred.webull_access_token and cred.webull_token_status == 'NORMAL':
            snap = get_webull_market_snapshot(
                cred.webull_app_key, cred.webull_app_secret, env, cred.webull_access_token,
                symbol=clean_sym, instrument_type=clean_type
            )
            price = float(snap.get('price') or snap.get('regular_price') or snap.get('close') or 0.0)
            if price > 0:
                return price
    except Exception as e:
        logger.debug(f"[PAPER_TRADING] Webull snapshot skipped for {clean_sym}: {e}")

    # 2. Crypto fallback (Binance)
    if clean_type == 'CRYPTO':
        try:
            from routes.trading import fetch_binance_price
            p = fetch_binance_price(clean_sym)
            if p and float(p) > 0:
                return float(p)
        except Exception:
            pass

    # 3. Equity / ETF fallback (Yahoo Finance)
    try:
        import yfinance as yf
        ticker = yf.Ticker(clean_sym)
        fast_info = getattr(ticker, 'fast_info', {})
        price = getattr(fast_info, 'last_price', None) or getattr(fast_info, 'regular_market_previous_close', None)
        if price and float(price) > 0:
            return float(price)
    except Exception as e:
        logger.debug(f"[PAPER_TRADING] yfinance lookup failed for {clean_sym}: {e}")

    # 4. Fallback from existing holdings or defaults
    existing = WebullTestPosition.query.filter_by(user_id=user_id, symbol=clean_sym).first()
    if existing and existing.last_price and existing.last_price > 0:
        return float(existing.last_price)
    if existing and existing.cost_price and existing.cost_price > 0:
        return float(existing.cost_price)

    return 100.0  # Safe simulation fallback if completely offline


def get_webull_test_account_summary(user_id: int) -> Dict[str, Any]:
    """Calculate and return full account balances, buying power, and P&L for paper trading."""
    account = get_or_create_webull_test_account(user_id)
    positions = WebullTestPosition.query.filter_by(user_id=user_id).all()

    total_market_value = 0.0
    total_cost_basis = 0.0
    total_unrealized_pnl = 0.0

    for pos in positions:
        curr_price = fetch_live_price(user_id, pos.symbol, pos.instrument_type)
        pos.last_price = curr_price
        multiplier = int(pos.contract_multiplier or 1)
        qty = float(pos.quantity or 0.0)
        cost = float(pos.cost_price or 0.0)

        mv = qty * curr_price * multiplier
        cost_basis = qty * cost * multiplier
        if pos.side == 'SHORT':
            pnl = cost_basis - mv
        else:
            pnl = mv - cost_basis

        pos.market_value = round(mv, 2)
        pos.unrealized_pnl = round(pnl, 2)
        pos.updated_at = datetime.utcnow()

        total_market_value += mv
        total_cost_basis += cost_basis
        total_unrealized_pnl += pnl

    db.session.commit()

    cash = float(account.cash_balance or 0.0)
    net_liquidation = cash + total_market_value

    return {
        'account_id': 'TEST_PAPER_ACCOUNT',
        'account_name': 'Webull Paper Account',
        'account_type': 'CASH',
        'is_paper': True,
        'currency': account.currency or 'USD',
        'cash_balance': round(cash, 2),
        'buying_power': round(cash, 2),
        'net_liquidation': round(net_liquidation, 2),
        'total_market_value': round(total_market_value, 2),
        'total_cost_basis': round(total_cost_basis, 2),
        'unrealized_profit_loss': round(total_unrealized_pnl, 2),
        'unrealized_profit_loss_rate': round((total_unrealized_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0.0, 2),
        'positions_count': len(positions),
    }


def get_webull_test_positions(user_id: int) -> List[Dict[str, Any]]:
    """Return all simulated paper holdings formatted to match WebullHolding schema."""
    positions = WebullTestPosition.query.filter_by(user_id=user_id).all()
    rows = []
    for pos in positions:
        curr_price = pos.last_price or fetch_live_price(user_id, pos.symbol, pos.instrument_type)
        pos.last_price = curr_price
        multiplier = int(pos.contract_multiplier or 1)
        qty = float(pos.quantity or 0.0)
        cost = float(pos.cost_price or 0.0)
        mv = round(qty * curr_price * multiplier, 2)
        cost_basis = qty * cost * multiplier
        pnl = round((cost_basis - mv) if pos.side == 'SHORT' else (mv - cost_basis), 2)
        pnl_rate = round((pnl / cost_basis * 100) if cost_basis > 0 else 0.0, 2)

        rows.append({
            'id': f"paper_pos_{pos.id}",
            'account_id': 'TEST_PAPER_ACCOUNT',
            'account_name': 'Webull Paper Account',
            'symbol': pos.symbol,
            'instrument_type': pos.instrument_type,
            'side': pos.side,
            'quantity': qty,
            'amount': qty,
            'cost_price': cost,
            'last_price': curr_price,
            'current_price': curr_price,
            'market_value': mv,
            'current_value': mv,
            'unrealized_profit_loss': pnl,
            'webull_unrealized_pnl': pnl,
            'unrealized_profit_loss_rate': pnl_rate,
            'currency': 'USD',
            'option_type': pos.option_type,
            'option_strike': pos.option_strike,
            'option_expiration': pos.option_expiration,
            'contract_multiplier': multiplier,
            'is_paper': True,
            'alert_enabled': False,
            'sentiment_tracking_enabled': False,
            'sentiment': 'Paper Simulated',
            'sentiment_reason': f"Simulated position entered at ${cost:,.2f}"
        })
    return rows


def get_webull_test_orders(user_id: int) -> List[Dict[str, Any]]:
    """Return simulated paper orders history."""
    orders = WebullTestOrder.query.filter_by(user_id=user_id).order_by(WebullTestOrder.id.desc()).limit(100).all()
    rows = []
    for o in orders:
        rows.append({
            'order_id': o.order_id,
            'account_id': 'TEST_PAPER_ACCOUNT',
            'symbol': o.symbol,
            'instrument_type': o.instrument_type,
            'side': o.side,
            'order_type': o.order_type,
            'total_quantity': float(o.quantity or 0.0),
            'filled_quantity': float(o.filled_quantity or o.quantity or 0.0),
            'price': o.limit_price or o.filled_price,
            'avg_price': o.filled_price or o.limit_price or 0.0,
            'status': o.status or 'Filled',
            'placed_time': o.created_at.strftime('%Y-%m-%d %H:%M:%S') if o.created_at else None,
            'time_in_force': o.time_in_force,
            'is_paper': True,
        })
    return rows


def execute_webull_test_order(user_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """Simulate execution of an order against real live market pricing."""
    account = get_or_create_webull_test_account(user_id)
    symbol = (data.get('symbol') or '').upper().strip()
    instrument_type = (data.get('instrument_type') or 'EQUITY').upper().strip()
    side = (data.get('side') or 'BUY').upper().strip()
    order_type = (data.get('order_type') or 'MARKET').upper().strip()
    quantity = float(data.get('quantity') or 0.0)
    limit_price = float(data.get('limit_price')) if data.get('limit_price') is not None else None
    stop_price = float(data.get('stop_price')) if data.get('stop_price') is not None else None

    # Determine contract multiplier
    multiplier = 100 if instrument_type == 'OPTION' else 1
    if data.get('contract_multiplier'):
        try:
            multiplier = int(data.get('contract_multiplier'))
        except (ValueError, TypeError):
            pass

    if quantity <= 0:
        raise ValueError("Order quantity must be greater than zero.")

    # Get live execution price
    live_price = fetch_live_price(user_id, symbol, instrument_type)
    fill_price = limit_price if (order_type == 'LIMIT' and limit_price and limit_price > 0) else live_price
    if fill_price <= 0:
        fill_price = 1.0

    total_trade_amount = round(quantity * fill_price * multiplier, 2)
    cash = float(account.cash_balance or 0.0)

    # Validate buying power
    is_buy = side in {'BUY', 'BUY_TO_OPEN'}
    is_sell = side in {'SELL', 'SELL_TO_CLOSE'}
    is_short = side in {'SHORT', 'SELL_TO_OPEN'}

    if is_buy:
        if cash < total_trade_amount:
            raise ValueError(
                f"Insufficient paper cash. Available: ${cash:,.2f}, Required: ${total_trade_amount:,.2f}. "
                f"Please use the Deposit button to add simulated funds."
            )
        # Deduct cash
        account.cash_balance = cash - total_trade_amount

        # Update or create position
        pos = WebullTestPosition.query.filter_by(
            user_id=user_id, symbol=symbol, instrument_type=instrument_type, side='LONG'
        ).first()

        if pos:
            new_qty = float(pos.quantity) + quantity
            new_cost = ((float(pos.cost_price) * float(pos.quantity)) + (fill_price * quantity)) / new_qty
            pos.quantity = new_qty
            pos.cost_price = round(new_cost, 4)
            pos.last_price = fill_price
            pos.updated_at = datetime.utcnow()
        else:
            pos = WebullTestPosition(
                user_id=user_id,
                symbol=symbol,
                instrument_type=instrument_type,
                side='LONG',
                quantity=quantity,
                cost_price=round(fill_price, 4),
                last_price=fill_price,
                contract_multiplier=multiplier,
                option_type=data.get('option_type'),
                option_strike=float(data.get('option_strike')) if data.get('option_strike') else None,
                option_expiration=data.get('option_expiration'),
            )
            db.session.add(pos)

    elif is_sell:
        pos = WebullTestPosition.query.filter_by(
            user_id=user_id, symbol=symbol, instrument_type=instrument_type, side='LONG'
        ).first()

        if not pos or float(pos.quantity) < quantity:
            avail = float(pos.quantity) if pos else 0.0
            raise ValueError(f"Cannot sell {quantity} shares/contracts of {symbol}. You only hold {avail}.")

        # Add proceeds to cash
        account.cash_balance = cash + total_trade_amount

        if float(pos.quantity) == quantity:
            db.session.delete(pos)
        else:
            pos.quantity = float(pos.quantity) - quantity
            pos.last_price = fill_price
            pos.updated_at = datetime.utcnow()

    elif is_short:
        # Opening short
        margin_required = total_trade_amount * 1.5  # 150% margin requirement for shorts
        if cash < margin_required:
            raise ValueError(
                f"Insufficient margin for short sale. Required: ${margin_required:,.2f}, Available: ${cash:,.2f}."
            )
        pos = WebullTestPosition.query.filter_by(
            user_id=user_id, symbol=symbol, instrument_type=instrument_type, side='SHORT'
        ).first()
        if pos:
            new_qty = float(pos.quantity) + quantity
            new_cost = ((float(pos.cost_price) * float(pos.quantity)) + (fill_price * quantity)) / new_qty
            pos.quantity = new_qty
            pos.cost_price = round(new_cost, 4)
            pos.last_price = fill_price
            pos.updated_at = datetime.utcnow()
        else:
            pos = WebullTestPosition(
                user_id=user_id,
                symbol=symbol,
                instrument_type=instrument_type,
                side='SHORT',
                quantity=quantity,
                cost_price=round(fill_price, 4),
                last_price=fill_price,
                contract_multiplier=multiplier,
            )
            db.session.add(pos)

    # Record test order
    simulated_order_id = f"SIM_{uuid.uuid4().hex[:12].upper()}"
    test_order = WebullTestOrder(
        order_id=simulated_order_id,
        user_id=user_id,
        symbol=symbol,
        instrument_type=instrument_type,
        side=side,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
        stop_price=stop_price,
        filled_price=fill_price,
        filled_quantity=quantity,
        status='Filled',
        combo_type=data.get('combo_type'),
        combo_orders=str(data.get('combo_orders')) if data.get('combo_orders') else None,
        time_in_force=data.get('time_in_force', 'DAY'),
    )
    db.session.add(test_order)
    account.updated_at = datetime.utcnow()
    db.session.commit()

    return {
        'success': True,
        'order_id': simulated_order_id,
        'symbol': symbol,
        'side': side,
        'instrument_type': instrument_type,
        'filled_price': fill_price,
        'filled_quantity': quantity,
        'total_amount': total_trade_amount,
        'status': 'Filled',
        'message': f"Simulated {side} order executed for {quantity} {symbol} at ${fill_price:,.2f} (Total: ${total_trade_amount:,.2f}).",
        'is_paper': True,
    }


def cancel_webull_test_order(user_id: int, order_id: str) -> Dict[str, Any]:
    """Cancel an active simulated order."""
    order = WebullTestOrder.query.filter_by(user_id=user_id, order_id=order_id).first()
    if not order:
        raise ValueError(f"Simulated order {order_id} not found.")
    order.status = 'Cancelled'
    order.updated_at = datetime.utcnow()
    db.session.commit()
    return {
        'success': True,
        'order_id': order_id,
        'status': 'Cancelled',
        'message': f"Simulated order {order_id} has been cancelled."
    }
