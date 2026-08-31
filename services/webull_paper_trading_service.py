import logging
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from core.extensions import db
from models import WebullTestAccount, WebullTestPosition, WebullTestOrder
from credentials import Credential, UserSetting
from services.webull_paper_rules import (
    ACTIVE_PAPER_ORDER_STATUSES,
    EQUITY_LIKE_TYPES,
    canonical_paper_instrument_type,
    grouped_reserved_quantity,
    paper_order_fills_immediately,
    paper_order_type_label,
    paper_position_valuation,
    paper_reservation_group,
)

logger = logging.getLogger(__name__)

DEFAULT_INITIAL_PAPER_BALANCE = 0.0

FUTURES_TICKER_MAP = {
    'ES': 'ES=F',
    'NQ': 'NQ=F',
    'YM': 'YM=F',
    'RTY': 'RTY=F',
    'MES': 'MES=F',
    'MNQ': 'MNQ=F',
    'CL': 'CL=F',
    'GC': 'GC=F',
    'SI': 'SI=F',
    'BTC': 'BTC=F',
}


def _find_or_merge_position(user_id: int, symbol: str, instrument_type: str, side: str):
    """Return one authoritative paper position for a contract/symbol and side."""
    clean_symbol = str(symbol or '').upper().strip()
    clean_type = canonical_paper_instrument_type(clean_symbol, instrument_type)
    clean_side = str(side or 'LONG').upper().strip()
    query = WebullTestPosition.query.filter_by(
        user_id=user_id, symbol=clean_symbol, side=clean_side,
    )
    candidates = query.all()
    if clean_type in EQUITY_LIKE_TYPES:
        candidates = [row for row in candidates if str(row.instrument_type or '').upper() in EQUITY_LIKE_TYPES]
    else:
        candidates = [row for row in candidates if str(row.instrument_type or '').upper() == clean_type]
    if not candidates:
        return None

    primary = next((row for row in candidates if str(row.instrument_type or '').upper() == clean_type), candidates[0])
    if len(candidates) > 1:
        total_qty = sum(float(row.quantity or 0.0) for row in candidates)
        weighted_cost = sum(float(row.cost_price or 0.0) * float(row.quantity or 0.0) for row in candidates)
        primary.quantity = total_qty
        primary.cost_price = round(weighted_cost / total_qty, 4) if total_qty > 0 else 0.0
        primary.last_price = next((float(row.last_price) for row in candidates if row.last_price), primary.last_price)
        for duplicate in candidates:
            if duplicate is not primary:
                db.session.delete(duplicate)
    primary.instrument_type = clean_type
    primary.updated_at = datetime.utcnow()
    return primary


def _normalize_equity_like_positions(user_id: int) -> None:
    """Upgrade legacy paper equity rows and collapse duplicate symbol rows."""
    positions = WebullTestPosition.query.filter_by(user_id=user_id).all()
    keys = {
        (row.symbol, row.instrument_type, row.side)
        for row in positions
        if str(row.instrument_type or '').upper() in EQUITY_LIKE_TYPES
    }
    for symbol, instrument_type, side in keys:
        _find_or_merge_position(user_id, symbol, instrument_type, side)


def _instrument_types_match(left: str, right: str) -> bool:
    left_type = str(left or '').upper().strip()
    right_type = str(right or '').upper().strip()
    return left_type in EQUITY_LIKE_TYPES and right_type in EQUITY_LIKE_TYPES or left_type == right_type


def _reserved_long_quantity(user_id: int, symbol: str, instrument_type: str) -> float:
    """Return shares already committed to active paper sell orders."""
    clean_symbol = str(symbol or '').upper().strip()
    orders = WebullTestOrder.query.filter_by(user_id=user_id, symbol=clean_symbol).all()
    matching_orders = [
        order for order in orders
        if _instrument_types_match(order.instrument_type, instrument_type)
    ]
    return grouped_reserved_quantity(matching_orders)


def _available_long_quantity(user_id: int, symbol: str, instrument_type: str) -> float:
    position = _find_or_merge_position(user_id, symbol, instrument_type, 'LONG')
    held = float(position.quantity or 0.0) if position else 0.0
    return max(0.0, held - _reserved_long_quantity(user_id, symbol, instrument_type))


def _available_short_quantity(user_id: int, symbol: str, instrument_type: str) -> float:
    """Return short units not already committed to working buy-to-close orders."""
    position = _find_or_merge_position(user_id, symbol, instrument_type, 'SHORT')
    held = float(position.quantity or 0.0) if position else 0.0
    clean_symbol = str(symbol or '').upper().strip()
    orders = WebullTestOrder.query.filter_by(user_id=user_id, symbol=clean_symbol).all()
    matching_orders = [order for order in orders if _instrument_types_match(order.instrument_type, instrument_type)]
    reserved = grouped_reserved_quantity(matching_orders, {'BUY_TO_CLOSE', 'COVER'})
    return max(0.0, held - reserved)


def _reserved_cash_amount(user_id: int) -> float:
    """Return cash committed to active paper buys, grouping mutually exclusive exits."""
    groups = {}
    orders = WebullTestOrder.query.filter_by(user_id=user_id).all()
    for order in orders:
        if str(order.status or '').upper().strip() not in ACTIVE_PAPER_ORDER_STATUSES:
            continue
        if str(order.side or '').upper().strip() not in {'BUY', 'BUY_TO_OPEN', 'BUY_TO_CLOSE', 'COVER'}:
            continue
        price = float(order.limit_price or order.stop_price or 0.0)
        if price <= 0:
            price = fetch_live_price(user_id, order.symbol, order.instrument_type)
        multiplier = 100 if str(order.instrument_type or '').upper() in {'OPTION', 'OPTIONS'} else 1
        outstanding = max(0.0, float(order.quantity or 0.0) - float(order.filled_quantity or 0.0))
        reservation = outstanding * max(0.0, price) * multiplier
        group = paper_reservation_group(order.order_id)
        groups[group] = max(groups.get(group, 0.0), reservation)
    return round(sum(groups.values()), 2)


def _reserved_short_margin(user_id: int) -> float:
    """Return margin committed to active simulated short-entry orders."""
    reserved = 0.0
    orders = WebullTestOrder.query.filter_by(user_id=user_id).all()
    for order in orders:
        if str(order.status or '').upper().strip() not in ACTIVE_PAPER_ORDER_STATUSES:
            continue
        if str(order.side or '').upper().strip() not in {'SHORT', 'SELL_TO_OPEN'}:
            continue
        price = float(order.limit_price or order.stop_price or 0.0)
        if price <= 0:
            price = fetch_live_price(user_id, order.symbol, order.instrument_type)
        outstanding = max(0.0, float(order.quantity or 0.0) - float(order.filled_quantity or 0.0))
        reserved += outstanding * max(0.0, price) * 1.5
    return round(reserved, 2)


def _current_short_margin(user_id: int) -> float:
    """Return margin held against currently open simulated short positions."""
    reserved = 0.0
    positions = WebullTestPosition.query.filter_by(user_id=user_id, side='SHORT').all()
    for position in positions:
        price = float(position.last_price or position.cost_price or 0.0)
        multiplier = int(position.contract_multiplier or 1)
        reserved += float(position.quantity or 0.0) * max(0.0, price) * multiplier * 1.5
    return round(reserved, 2)


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


def _lock_webull_test_account(user_id: int) -> WebullTestAccount:
    """Serialize paper-ledger mutations for one user to prevent reservation races."""
    get_or_create_webull_test_account(user_id)
    return WebullTestAccount.query.filter_by(user_id=user_id).with_for_update().one()


def deposit_fake_money(user_id: int, amount: float, reset: bool = False) -> Dict[str, Any]:
    """Deposit simulated fake money into the user's paper account, or reset it."""
    account = _lock_webull_test_account(user_id)
    amount = float(amount or 0.0)

    if reset:
        account.cash_balance = amount if amount >= 0 else 0.0
        cancelled_orders = 0
        active_orders = WebullTestOrder.query.filter_by(user_id=user_id).all()
        for order in active_orders:
            if str(order.status or '').upper().strip() in ACTIVE_PAPER_ORDER_STATUSES:
                order.status = 'Cancelled'
                order.updated_at = datetime.utcnow()
                cancelled_orders += 1
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
        'message': (
            f"Successfully reset paper funds to ${amount:,.2f}, cleared positions, and cancelled "
            f"{cancelled_orders} active simulated order(s)."
            if reset else f"Successfully deposited ${amount:,.2f} simulated funds."
        )
    }


def fetch_live_price(
    user_id: int,
    symbol: str,
    instrument_type: str = 'EQUITY',
    *,
    option_type: Optional[str] = None,
    option_strike: Optional[float] = None,
    option_expiration: Optional[str] = None,
    event_outcome: Optional[str] = None,
) -> float:
    """Fetch live real-world pricing for paper order execution and valuation across all asset classes."""
    clean_sym = (symbol or '').upper().strip()
    clean_type = (instrument_type or 'EQUITY').upper().strip()

    # 1. Event positions use the selected outcome's current Webull quote.
    if clean_type == 'EVENT':
        from credentials import Credential, UserSetting
        from services.webull_service import get_webull_event_market, normalize_webull_environment
        market_symbol = clean_sym.rsplit(' ', 1)[0] if clean_sym.endswith((' YES', ' NO')) else clean_sym
        outcome = str(event_outcome or (clean_sym.rsplit(' ', 1)[-1] if clean_sym.endswith((' YES', ' NO')) else 'YES')).lower()
        credential = Credential.query.filter_by(user_id=user_id).first()
        setting = UserSetting.query.filter_by(user_id=user_id).first()
        environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
        if not credential or not credential.webull_access_token:
            raise ValueError('Connect Webull before valuing simulated Event Contract positions.')
        market = get_webull_event_market(
            credential.webull_app_key, credential.webull_app_secret,
            environment, credential.webull_access_token,
            symbol=market_symbol,
        )
        if outcome == 'no':
            candidates = (market.get('no_bid'), market.get('no_ask'))
            if not any(value is not None for value in candidates) and market.get('last_price') is not None:
                candidates = (1 - float(market['last_price']),)
        else:
            candidates = (market.get('yes_bid'), market.get('yes_ask'), market.get('last_price'))
        valid = [float(value) for value in candidates if value is not None and float(value) >= 0]
        if not valid:
            raise ValueError('Webull returned no current price for this Event Contract outcome.')
        return sum(valid[:2]) / min(2, len(valid))

    # 2. Options pricing
    if clean_type in {'OPTION', 'OPTIONS'}:
        underlying = clean_sym.split()[0] if ' ' in clean_sym else clean_sym
        # Try Webull option chain if user has connected credentials
        try:
            from credentials import Credential, UserSetting
            from services.webull_service import get_webull_option_chain_data, normalize_webull_environment
            cred = Credential.query.filter_by(user_id=user_id).first()
            setting = UserSetting.query.filter_by(user_id=user_id).first()
            env = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
            if option_strike and option_expiration:
                chain = get_webull_option_chain_data(
                    cred.webull_app_key if cred else None,
                    cred.webull_app_secret if cred else None,
                    env,
                    cred.webull_access_token if cred else None,
                    underlying_symbol=underlying,
                    expiration_date=option_expiration,
                )
                for strike_row in chain.get('strikes', []):
                    if abs(float(strike_row.get('strike') or 0) - float(option_strike)) < 0.01:
                        side_data = strike_row.get('call' if str(option_type).upper() == 'CALL' else 'put', {})
                        opt_px = float(side_data.get('last_price') or side_data.get('mid_price') or side_data.get('ask') or side_data.get('bid') or 0.0)
                        if opt_px > 0:
                            return opt_px
        except Exception as e:
            logger.debug(f"[PAPER_TRADING] Option chain lookup skipped for {clean_sym}: {e}")

        # Fallback to existing position cost/last price (never return underlying equity price for option)
        existing = WebullTestPosition.query.filter_by(user_id=user_id, symbol=clean_sym).first()
        if existing and existing.last_price and existing.last_price > 0:
            return float(existing.last_price)
        if existing and existing.cost_price and existing.cost_price > 0:
            return float(existing.cost_price)
        return 2.50  # Sensible default option premium simulation

    # 3. FUTURES pricing
    if clean_type in {'FUTURES', 'FUTURE'}:
        # Try Webull snapshot
        try:
            from credentials import Credential, UserSetting
            from services.webull_service import get_webull_futures_snapshot, normalize_webull_environment
            cred = Credential.query.filter_by(user_id=user_id).first()
            setting = UserSetting.query.filter_by(user_id=user_id).first()
            env = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
            if cred and cred.webull_access_token and cred.webull_token_status == 'NORMAL':
                snap = get_webull_futures_snapshot(
                    cred.webull_app_key, cred.webull_app_secret, env, cred.webull_access_token, symbol=clean_sym
                )
                p = float(snap.get('price') or snap.get('last_price') or 0.0)
                if p > 0:
                    return p
        except Exception:
            pass

        # Try Yahoo Finance futures mapping (e.g. ES=F, NQ=F, CL=F, GC=F)
        root_sym = clean_sym[:2] if len(clean_sym) >= 2 and clean_sym[:2] in FUTURES_TICKER_MAP else clean_sym
        yf_ticker_sym = FUTURES_TICKER_MAP.get(root_sym, f"{root_sym}=F")
        try:
            import yfinance as yf
            ticker = yf.Ticker(yf_ticker_sym)
            fast_info = getattr(ticker, 'fast_info', {})
            p = getattr(fast_info, 'last_price', None) or getattr(fast_info, 'regular_market_previous_close', None)
            if p and float(p) > 0:
                return float(p)
        except Exception:
            pass

        existing = WebullTestPosition.query.filter_by(user_id=user_id, symbol=clean_sym).first()
        if existing and existing.last_price and existing.last_price > 0:
            return float(existing.last_price)
        return 5000.0 if 'ES' in clean_sym or 'NQ' in clean_sym else 100.0

    # 4. CRYPTO pricing
    if clean_type == 'CRYPTO':
        # Try Binance
        try:
            from routes.trading import fetch_binance_price
            p = fetch_binance_price(clean_sym)
            if p and float(p) > 0:
                return float(p)
            # Try stripping USD if e.g. BTCUSD -> BTCUSDT
            if clean_sym.endswith('USD'):
                p2 = fetch_binance_price(clean_sym + 'T')
                if p2 and float(p2) > 0:
                    return float(p2)
        except Exception:
            pass

        # Try Webull snapshot
        try:
            from credentials import Credential, UserSetting
            from services.webull_service import get_webull_market_snapshot, normalize_webull_environment
            cred = Credential.query.filter_by(user_id=user_id).first()
            setting = UserSetting.query.filter_by(user_id=user_id).first()
            env = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
            if cred and cred.webull_access_token and cred.webull_token_status == 'NORMAL':
                snap = get_webull_market_snapshot(
                    cred.webull_app_key, cred.webull_app_secret, env, cred.webull_access_token,
                    symbol=clean_sym, instrument_type='CRYPTO'
                )
                price = float(snap.get('price') or snap.get('regular_price') or snap.get('close') or 0.0)
                if price > 0:
                    return price
        except Exception:
            pass

        # Try Yahoo Finance for Crypto (e.g. BTC-USD)
        try:
            import yfinance as yf
            yf_sym = clean_sym.replace('USD', '-USD') if clean_sym.endswith('USD') else f"{clean_sym}-USD"
            ticker = yf.Ticker(yf_sym)
            fast_info = getattr(ticker, 'fast_info', {})
            price = getattr(fast_info, 'last_price', None) or getattr(fast_info, 'regular_market_previous_close', None)
            if price and float(price) > 0:
                return float(price)
        except Exception:
            pass

    # 5. EQUITY / ETF pricing
    # Try Webull snapshot first
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

    # Yahoo Finance fallback
    try:
        import yfinance as yf
        ticker = yf.Ticker(clean_sym)
        fast_info = getattr(ticker, 'fast_info', {})
        price = getattr(fast_info, 'last_price', None) or getattr(fast_info, 'regular_market_previous_close', None)
        if price and float(price) > 0:
            return float(price)
    except Exception as e:
        logger.debug(f"[PAPER_TRADING] yfinance lookup failed for {clean_sym}: {e}")

    # Fallback from existing holdings
    existing = WebullTestPosition.query.filter_by(user_id=user_id, symbol=clean_sym).first()
    if existing and existing.last_price and existing.last_price > 0:
        return float(existing.last_price)
    if existing and existing.cost_price and existing.cost_price > 0:
        return float(existing.cost_price)

    return 100.0


def get_webull_test_account_summary(user_id: int) -> Dict[str, Any]:
    """Calculate and return full account balances, buying power, and P&L for paper trading."""
    account = get_or_create_webull_test_account(user_id)
    _normalize_equity_like_positions(user_id)
    positions = WebullTestPosition.query.filter_by(user_id=user_id).all()

    total_market_value = 0.0
    total_cost_basis = 0.0
    total_unrealized_pnl = 0.0

    for pos in positions:
        if pos.instrument_type == 'OPTION':
            curr_price = fetch_live_price(
                user_id, pos.underlying_symbol or pos.symbol, 'OPTION',
                option_type=pos.option_type, option_strike=pos.option_strike, option_expiration=pos.option_expiration
            )
        else:
            curr_price = fetch_live_price(
                user_id, pos.symbol, pos.instrument_type,
                event_outcome=pos.event_outcome,
            )

        pos.last_price = curr_price
        multiplier = int(pos.contract_multiplier or (100 if pos.instrument_type == 'OPTION' else 1))
        qty = float(pos.quantity or 0.0)
        cost = float(pos.cost_price or 0.0)

        valuation = paper_position_valuation(pos.side, qty, cost, curr_price, multiplier)
        signed_market_value = valuation['market_value']
        cost_basis = valuation['cost_basis']
        pnl = valuation['unrealized_pnl']

        pos.market_value = round(signed_market_value, 2)
        pos.unrealized_pnl = round(pnl, 2)
        pos.updated_at = datetime.utcnow()

        total_market_value += signed_market_value
        total_cost_basis += cost_basis
        total_unrealized_pnl += pnl

    db.session.commit()

    cash = float(account.cash_balance or 0.0)
    reserved_cash = _reserved_cash_amount(user_id)
    reserved_short_margin = _reserved_short_margin(user_id)
    available_cash = max(0.0, cash - reserved_cash - reserved_short_margin)
    net_liquidation = cash + total_market_value
    short_market_value = sum(
        abs(float(pos.market_value or 0.0)) for pos in positions if str(pos.side or '').upper() == 'SHORT'
    )
    buying_power = max(0.0, available_cash - (short_market_value * 1.5))

    return {
        'account_id': 'TEST_PAPER_ACCOUNT',
        'account_name': 'Webull Paper Account',
        'account_type': 'CASH',
        'is_paper': True,
        'currency': account.currency or 'USD',
        'cash_balance': round(cash, 2),
        'reserved_cash': round(reserved_cash, 2),
        'reserved_short_margin': round(reserved_short_margin, 2),
        'available_cash': round(available_cash, 2),
        'buying_power': round(buying_power, 2),
        'net_liquidation': round(net_liquidation, 2),
        'total_market_value': round(total_market_value, 2),
        'total_cost_basis': round(total_cost_basis, 2),
        'unrealized_profit_loss': round(total_unrealized_pnl, 2),
        'unrealized_profit_loss_rate': round((total_unrealized_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0.0, 2),
        'positions_count': len(positions),
    }


def get_webull_test_positions(user_id: int) -> List[Dict[str, Any]]:
    """Return all simulated paper holdings formatted to match WebullHolding schema."""
    _normalize_equity_like_positions(user_id)
    positions = WebullTestPosition.query.filter_by(user_id=user_id).all()
    rows = []
    for pos in positions:
        curr_price = (
            fetch_live_price(user_id, pos.symbol, pos.instrument_type, event_outcome=pos.event_outcome)
            if pos.instrument_type == 'EVENT'
            else pos.last_price or fetch_live_price(user_id, pos.symbol, pos.instrument_type)
        )
        pos.last_price = curr_price
        multiplier = int(pos.contract_multiplier or (100 if pos.instrument_type == 'OPTION' else 1))
        qty = float(pos.quantity or 0.0)
        cost = float(pos.cost_price or 0.0)
        is_short = str(pos.side or '').upper() == 'SHORT'
        valuation = paper_position_valuation(pos.side, qty, cost, curr_price, multiplier)
        mv = round(valuation['market_value'], 2)
        cost_basis = valuation['cost_basis']
        pnl = round(valuation['unrealized_pnl'], 2)
        pnl_rate = round((pnl / cost_basis * 100) if cost_basis > 0 else 0.0, 2)
        available_quantity = (
            _available_short_quantity(user_id, pos.symbol, pos.instrument_type)
            if is_short else _available_long_quantity(user_id, pos.symbol, pos.instrument_type)
        )

        rows.append({
            'id': f"paper_pos_{pos.id}",
            'account_id': 'TEST_PAPER_ACCOUNT',
            'account_name': 'Webull Paper Account',
            'symbol': pos.symbol,
            'underlying_symbol': pos.underlying_symbol or pos.symbol,
            'instrument_type': pos.instrument_type,
            'side': pos.side,
            'position_side': pos.side,
            'quantity': qty,
            'amount': qty,
            'available_quantity': available_quantity,
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
            'event_outcome': pos.event_outcome,
            'contract_multiplier': multiplier,
            'is_paper': True,
            'alert_enabled': False,
            'sentiment_tracking_enabled': False,
            'sentiment': 'Paper Simulated',
            'sentiment_reason': f"Simulated position entered at ${cost:,.2f}"
        })
    db.session.commit()
    return rows


def get_webull_test_orders(user_id: int) -> List[Dict[str, Any]]:
    """Return simulated paper orders history."""
    orders = WebullTestOrder.query.filter_by(user_id=user_id).order_by(WebullTestOrder.id.desc()).limit(100).all()
    rows = []
    for o in orders:
        status = o.status or 'Filled'
        filled_quantity = o.filled_quantity
        if filled_quantity is None:
            filled_quantity = o.quantity if str(status).upper() == 'FILLED' else 0.0
        rows.append({
            'order_id': o.order_id,
            'id': o.order_id,
            'account_id': 'TEST_PAPER_ACCOUNT',
            'symbol': o.symbol,
            'instrument_type': o.instrument_type,
            'side': o.side,
            'order_type': o.order_type,
            'total_quantity': float(o.quantity or 0.0),
            'quantity': float(o.quantity or 0.0),
            'filled_quantity': float(filled_quantity or 0.0),
            'price': o.limit_price or o.filled_price,
            'limit_price': o.limit_price,
            'stop_price': o.stop_price,
            'avg_price': o.filled_price or o.limit_price or 0.0,
            'status': status,
            'placed_time': o.created_at.strftime('%Y-%m-%d %H:%M:%S') if o.created_at else None,
            'created_at': o.created_at.strftime('%Y-%m-%d %H:%M:%S') if o.created_at else None,
            'combo_type': o.combo_type,
            'combo_orders': o.combo_orders,
            'time_in_force': o.time_in_force,
            'is_paper': True,
        })
    return rows


def execute_webull_test_order(user_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """Simulate execution of an order across all Webull asset classes against real live market pricing."""
    account = _lock_webull_test_account(user_id)
    cash = float(account.cash_balance or 0.0)
    reserved_cash = _reserved_cash_amount(user_id)
    cover_cash = max(0.0, cash - reserved_cash)
    available_cash = max(
        0.0,
        cover_cash - _reserved_short_margin(user_id) - _current_short_margin(user_id),
    )

    # 1. Handle Multi-leg Combo Orders (OTO, OCO, OTOCO)
    combo_orders = data.get('combo_orders')
    if combo_orders and isinstance(combo_orders, list):
        if len(combo_orders) < 2:
            raise ValueError("Webull combo orders require at least 2 legs.")
        combo_type = str(data.get('combo_type') or 'OTO').upper()
        clean_combo_id = f"SIM_COMBO_{uuid.uuid4().hex[:10].upper()}"
        explicit_primary = next((
            leg for leg in combo_orders
            if str(leg.get('combo_type') or leg.get('role') or '').upper() in {'PRIMARY', 'MASTER'}
        ), None)
        is_standalone_oco = combo_type == 'OCO' and explicit_primary is None
        primary_leg = None if is_standalone_oco else (explicit_primary or combo_orders[0])

        normalized_legs = []
        for idx, leg in enumerate(combo_orders):
            l_sym = (leg.get('symbol') or data.get('symbol') or '').upper().strip()
            l_side = str(leg.get('side') or ('SELL' if is_standalone_oco else 'BUY')).upper().strip()
            l_qty = float(leg.get('quantity') or 0.0)
            if not l_sym or l_qty <= 0:
                raise ValueError(f"Combo leg {idx + 1} requires a symbol and positive quantity.")
            normalized_legs.append({
                'source': leg,
                'symbol': l_sym,
                'side': l_side,
                'quantity': l_qty,
                'order_type': str(leg.get('order_type') or 'LIMIT').upper().strip(),
                'limit_price': float(leg.get('limit_price')) if leg.get('limit_price') is not None else None,
                'stop_price': float(leg.get('stop_price')) if leg.get('stop_price') is not None else None,
                'is_master': leg is primary_leg,
            })

        primary = next((leg for leg in normalized_legs if leg['is_master']), None)
        if primary and primary['side'] not in {'BUY', 'BUY_TO_OPEN'}:
            raise ValueError("The primary leg of a simulated OTO/OTOCO order must be a buy order.")
        if primary:
            current_short = _find_or_merge_position(user_id, primary['symbol'], 'EQUITY', 'SHORT')
            if current_short and float(current_short.quantity or 0.0) > 0:
                raise ValueError(
                    f"Cannot open a combo long in {primary['symbol']} while a short position exists. "
                    f"Cover the short first."
                )
        dependent_legs = normalized_legs if is_standalone_oco else [
            leg for leg in normalized_legs if not leg['is_master']
        ]
        if any(leg['side'] not in {'SELL', 'SELL_TO_CLOSE'} for leg in dependent_legs):
            raise ValueError("Dependent simulated combo legs must be sell-to-close orders.")

        required_by_symbol = {}
        for leg in dependent_legs:
            required_by_symbol[leg['symbol']] = max(
                required_by_symbol.get(leg['symbol'], 0.0), leg['quantity']
            )
        for leg_symbol, required_quantity in required_by_symbol.items():
            available_quantity = _available_long_quantity(user_id, leg_symbol, 'EQUITY')
            if primary and primary['symbol'] == leg_symbol:
                available_quantity += primary['quantity']
            if available_quantity < required_quantity:
                raise ValueError(
                    f"Cannot reserve {required_quantity} units of {leg_symbol} for this combo. "
                    f"Only {available_quantity} unreserved units are available."
                )

        fill_px = None
        trade_amount = 0.0
        if primary:
            live_px = fetch_live_price(user_id, primary['symbol'], 'EQUITY')
            fill_px = (
                primary['limit_price']
                if primary['order_type'] == 'LIMIT' and primary['limit_price'] and primary['limit_price'] > 0
                else live_px
            )
            if not fill_px or fill_px <= 0:
                fill_px = 100.0
            trade_amount = round(primary['quantity'] * fill_px, 2)
            if available_cash < trade_amount:
                raise ValueError(
                    f"Insufficient paper cash for primary combo leg. Required: ${trade_amount:,.2f}, "
                    f"Available after working-order reservations: ${available_cash:,.2f}."
                )
            account.cash_balance = cash - trade_amount
            pos = _find_or_merge_position(user_id, primary['symbol'], 'EQUITY', 'LONG')
            if pos:
                old_qty = float(pos.quantity or 0.0)
                new_qty = old_qty + primary['quantity']
                pos.cost_price = round(
                    ((float(pos.cost_price or 0.0) * old_qty) + (fill_px * primary['quantity'])) / new_qty,
                    4,
                )
                pos.quantity = new_qty
                pos.last_price = fill_px
                pos.updated_at = datetime.utcnow()
            else:
                db.session.add(WebullTestPosition(
                    user_id=user_id, symbol=primary['symbol'], underlying_symbol=primary['symbol'],
                    instrument_type='EQUITY', side='LONG', quantity=primary['quantity'],
                    cost_price=round(fill_px, 4), last_price=fill_px, contract_multiplier=1,
                ))

        for idx, leg in enumerate(normalized_legs):
            leg_filled = bool(leg['is_master'])
            db.session.add(WebullTestOrder(
                order_id=f"{clean_combo_id}_LEG{idx + 1}", user_id=user_id,
                symbol=leg['symbol'], instrument_type='EQUITY', side=leg['side'],
                order_type=leg['order_type'], quantity=leg['quantity'],
                limit_price=leg['limit_price'], stop_price=leg['stop_price'],
                filled_price=fill_px if leg_filled else None,
                filled_quantity=leg['quantity'] if leg_filled else 0.0,
                status='Filled' if leg_filled else 'Working', combo_type=combo_type,
                combo_orders=str(combo_orders), time_in_force=leg['source'].get('time_in_force', 'DAY'),
            ))

        account.updated_at = datetime.utcnow()
        db.session.commit()
        primary_symbol = primary['symbol'] if primary else normalized_legs[0]['symbol']
        status = 'Filled' if primary else 'Working'
        message = (
            f"Simulated {combo_type} combo submitted ({len(combo_orders)} legs); primary buy filled at ${fill_px:,.2f}."
            if primary else f"Simulated {combo_type} combo submitted ({len(combo_orders)} mutually exclusive working legs)."
        )
        return {
            'success': True, 'order_id': clean_combo_id, 'client_combo_order_id': clean_combo_id,
            'symbol': primary_symbol, 'side': primary['side'] if primary else 'SELL',
            'instrument_type': 'EQUITY', 'filled_price': fill_px,
            'filled_quantity': primary['quantity'] if primary else 0.0,
            'total_amount': trade_amount, 'status': status, 'legs_count': len(combo_orders),
            'message': message, 'is_paper': True,
        }

    # 2. Standard Single Order
    symbol = (data.get('symbol') or '').upper().strip()
    instrument_type = canonical_paper_instrument_type(symbol, data.get('instrument_type') or 'EQUITY')
    side = (data.get('side') or 'BUY').upper().strip()
    order_type = (data.get('order_type') or 'MARKET').upper().strip()
    entrust_type = (data.get('entrust_type') or 'QTY').upper().strip()
    total_cash_amount = float(data.get('total_cash_amount') or 0.0) if data.get('total_cash_amount') else None

    # Resolve multiplier
    multiplier = 100 if instrument_type in {'OPTION', 'OPTIONS'} else 1
    if data.get('contract_multiplier'):
        try:
            multiplier = int(data.get('contract_multiplier'))
        except (ValueError, TypeError):
            pass

    # Option-specific parameter extraction
    option_type = str(data.get('option_type') or 'CALL').upper() if instrument_type in {'OPTION', 'OPTIONS'} else None
    option_strike = float(data.get('option_strike')) if data.get('option_strike') else None
    option_expiration = str(data.get('option_expiration') or '').strip() if instrument_type in {'OPTION', 'OPTIONS'} else None
    underlying_sym = str(data.get('option_underlying_symbol') or symbol).upper().strip()
    option_strategy = str(data.get('option_strategy') or 'SINGLE').upper().strip()
    option_legs = data.get('option_legs')

    # Multi-leg option strategies are kept Working in paper trading until a
    # strategy-aware execution engine can price every leg atomically. This is
    # safer than fabricating weekend fills or mutating only part of a spread.
    if instrument_type == 'OPTION' and option_strategy != 'SINGLE':
        supported_strategies = {
            'COVERED_STOCK', 'VERTICAL', 'STRADDLE', 'STRANGLE', 'CALENDAR',
            'BUTTERFLY', 'CONDOR', 'IRON_BUTTERFLY', 'IRON_CONDOR',
            'COLLAR_WITH_STOCK', 'DIAGONAL',
        }
        if option_strategy not in supported_strategies:
            raise ValueError('Choose a strategy supported by the documented Webull OpenAPI. Ratio is not currently documented.')
        if not isinstance(option_legs, list) or len(option_legs) < 2:
            raise ValueError('The selected simulated option strategy requires at least two complete legs.')
        quantity = float(data.get('quantity') or 0.0)
        if quantity <= 0 or not quantity.is_integer():
            raise ValueError('Simulated option strategies require a positive whole number of strategy contracts.')
        limit_price = float(data.get('limit_price')) if data.get('limit_price') is not None else None
        stop_price = float(data.get('stop_price')) if data.get('stop_price') is not None else None
        simulated_order_id = f"SIM_{uuid.uuid4().hex[:12].upper()}"
        display_symbol = underlying_sym or symbol
        order = WebullTestOrder(
            order_id=simulated_order_id,
            user_id=user_id,
            symbol=display_symbol,
            instrument_type='OPTION',
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            filled_price=None,
            filled_quantity=0.0,
            status='Working',
            combo_type=option_strategy,
            combo_orders=json.dumps(option_legs),
            time_in_force=str(data.get('time_in_force') or 'DAY').upper(),
        )
        db.session.add(order)
        account.updated_at = datetime.utcnow()
        db.session.commit()
        return {
            'success': True,
            'order_id': simulated_order_id,
            'symbol': display_symbol,
            'side': side,
            'instrument_type': 'OPTION',
            'status': 'Working',
            'filled_quantity': 0.0,
            'legs_count': len(option_legs),
            'option_strategy': option_strategy,
            'message': (
                f"Simulated {option_strategy.replace('_', ' ').title()} strategy accepted with "
                f"{len(option_legs)} legs and queued as Working."
            ),
            'is_paper': True,
        }

    # Event-specific parameter extraction
    event_outcome = str(data.get('event_outcome') or 'yes').lower().strip() if instrument_type == 'EVENT' else None

    # Fetch live execution quote
    live_price = fetch_live_price(
        user_id, underlying_sym or symbol, instrument_type,
        option_type=option_type, option_strike=option_strike, option_expiration=option_expiration,
        event_outcome=event_outcome,
    )

    limit_price = float(data.get('limit_price')) if data.get('limit_price') is not None else None
    stop_price = float(data.get('stop_price')) if data.get('stop_price') is not None else None

    fill_price = limit_price if (order_type in {'LIMIT', 'LIMIT_ON_OPEN'} and limit_price and limit_price > 0) else live_price
    if order_type in {'STOP_LOSS', 'STOP_LOSS_LIMIT'} and stop_price and stop_price > 0:
        fill_price = limit_price if (order_type == 'STOP_LOSS_LIMIT' and limit_price and limit_price > 0) else stop_price
    if fill_price <= 0:
        fill_price = 1.0

    # Quantity calculation: support cash amount mode (fractional shares)
    quantity = float(data.get('quantity') or 0.0)
    if entrust_type == 'AMOUNT' and total_cash_amount and total_cash_amount > 0:
        if total_cash_amount < 5.0:
            raise ValueError("Total cash amount must be at least $5.00 for fractional cash orders.")
        quantity = round(total_cash_amount / fill_price, 6)
    elif quantity <= 0:
        raise ValueError("Order quantity must be greater than zero.")

    # Event contract validations
    if instrument_type == 'EVENT':
        event_rules = data.get('_event_market_rules') if isinstance(data.get('_event_market_rules'), dict) else {}
        max_quantity = float(event_rules.get('max_quantity') or 0)
        price_ranges = event_rules.get('price_ranges') if isinstance(event_rules.get('price_ranges'), list) else []
        if not max_quantity or not price_ranges:
            raise ValueError('Current Webull Event Contract rules are unavailable. Refresh the market and try again.')
        if quantity <= 0 or quantity > max_quantity:
            raise ValueError(f'Maximum quantity for this event contract is {max_quantity:g}.')
        if not event_rules.get('fractionable') and not float(quantity).is_integer():
            raise ValueError('This event contract requires a whole-number quantity.')
        if limit_price is None:
            raise ValueError('Event contracts require a limit price.')
        valid_price = False
        for price_range in price_ranges:
            try:
                start = float(price_range['start'])
                end = float(price_range['end'])
                step = float(price_range['step'])
                ticks = (limit_price - start) / step
                if start <= limit_price <= end and abs(ticks - round(ticks)) <= 1e-6:
                    valid_price = True
                    break
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue
        if not valid_price:
            raise ValueError('The limit price does not match this event contract’s current Webull price range and tick size.')
        fill_price = limit_price

    # Options contract display symbol
    contract_symbol = symbol
    if instrument_type in {'OPTION', 'OPTIONS'} and option_strike and option_expiration:
        contract_symbol = f"{underlying_sym} {option_expiration} ${option_strike:g} {option_type}"
    elif instrument_type == 'EVENT':
        contract_symbol = f"{symbol} {event_outcome.upper()}"

    total_trade_amount = round(quantity * fill_price * multiplier, 2)

    is_buy = side in {'BUY', 'BUY_TO_OPEN'}
    is_sell = side in {'SELL', 'SELL_TO_CLOSE'}
    is_short = side in {'SHORT', 'SELL_TO_OPEN'}
    is_cover = side in {'BUY_TO_CLOSE', 'COVER'}
    if not any((is_buy, is_sell, is_short, is_cover)):
        raise ValueError(f"Unsupported simulated order side: {side}.")
    existing_long = _find_or_merge_position(user_id, contract_symbol, instrument_type, 'LONG')
    existing_short = _find_or_merge_position(user_id, contract_symbol, instrument_type, 'SHORT')
    if is_short and existing_long and float(existing_long.quantity or 0.0) > 0:
        raise ValueError(
            f"Cannot open a simulated short in {contract_symbol} while a long position exists. "
            f"Sell the long position first."
        )
    if is_buy and existing_short and float(existing_short.quantity or 0.0) > 0:
        raise ValueError(
            f"Cannot open a simulated long in {contract_symbol} while a short position exists. "
            f"Use Buy to Close to cover the short first."
        )

    # Stop, trailing, and auction orders must never fabricate an immediate
    # weekend fill. They remain cancellable working orders until a future
    # trigger/auction processor can fill them against a qualifying quote.
    if not paper_order_fills_immediately(order_type, instrument_type):
        cash_for_order = cover_cash if is_cover else available_cash
        if (is_buy or is_cover) and cash_for_order < total_trade_amount:
            raise ValueError(
                f"Insufficient paper cash after working-order reservations. "
                f"Available: ${cash_for_order:,.2f}, Required: ${total_trade_amount:,.2f}."
            )
        if is_sell:
            available_quantity = _available_long_quantity(user_id, contract_symbol, instrument_type)
            if available_quantity < quantity:
                raise ValueError(
                    f"Cannot reserve {quantity} units of {contract_symbol}. "
                    f"Only {available_quantity} unreserved long units are available."
                )
        if is_cover:
            available_quantity = _available_short_quantity(user_id, contract_symbol, instrument_type)
            if available_quantity < quantity:
                raise ValueError(
                    f"Cannot reserve a cover for {quantity} units of {contract_symbol}. "
                    f"Only {available_quantity} unreserved short units are available."
                )
        if is_short and available_cash < total_trade_amount * 1.5:
            raise ValueError(
                f"Insufficient margin for simulated short sale. Required: ${total_trade_amount * 1.5:,.2f}, "
                f"Available after reservations: ${available_cash:,.2f}."
            )
        simulated_order_id = f"SIM_{uuid.uuid4().hex[:12].upper()}"
        test_order = WebullTestOrder(
            order_id=simulated_order_id,
            user_id=user_id,
            symbol=contract_symbol,
            instrument_type=instrument_type,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            filled_price=None,
            filled_quantity=0.0,
            status='Working',
            combo_type=data.get('combo_type'),
            time_in_force=data.get('time_in_force', 'DAY'),
        )
        db.session.add(test_order)
        account.updated_at = datetime.utcnow()
        db.session.commit()
        return {
            'success': True,
            'order_id': simulated_order_id,
            'symbol': contract_symbol,
            'side': side,
            'instrument_type': instrument_type,
            'filled_price': None,
            'filled_quantity': 0.0,
            'total_amount': total_trade_amount,
            'status': 'Working',
            'message': f"Simulated {side.title()} {paper_order_type_label(order_type)} order accepted for {quantity} {contract_symbol} and queued as Working.",
            'is_paper': True,
        }

    if is_buy:
        if available_cash < total_trade_amount:
            raise ValueError(
                f"Insufficient paper cash. Available after working-order reservations: ${available_cash:,.2f}, "
                f"Required: ${total_trade_amount:,.2f}. "
                f"Please use the Deposit button to add simulated funds."
            )
        account.cash_balance = cash - total_trade_amount

        pos = _find_or_merge_position(user_id, contract_symbol, instrument_type, 'LONG')

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
                symbol=contract_symbol,
                underlying_symbol=underlying_sym,
                instrument_type=instrument_type,
                side='LONG',
                quantity=quantity,
                cost_price=round(fill_price, 4),
                last_price=fill_price,
                contract_multiplier=multiplier,
                option_type=option_type,
                option_strike=option_strike,
                option_expiration=option_expiration,
                event_outcome=event_outcome,
            )
            db.session.add(pos)

    elif is_sell:
        pos = _find_or_merge_position(user_id, contract_symbol, instrument_type, 'LONG')
        available_quantity = _available_long_quantity(user_id, contract_symbol, instrument_type)
        if not pos or available_quantity < quantity:
            raise ValueError(
                f"Cannot sell {quantity} units of {contract_symbol}. "
                f"Only {available_quantity} unreserved long units are available."
            )

        account.cash_balance = cash + total_trade_amount

        if float(pos.quantity) == quantity:
            db.session.delete(pos)
        else:
            pos.quantity = float(pos.quantity) - quantity
            pos.last_price = fill_price
            pos.updated_at = datetime.utcnow()

    elif is_cover:
        pos = _find_or_merge_position(user_id, contract_symbol, instrument_type, 'SHORT')
        available_quantity = _available_short_quantity(user_id, contract_symbol, instrument_type)
        if not pos or available_quantity < quantity:
            raise ValueError(
                f"Cannot cover {quantity} units of {contract_symbol}. "
                f"Only {available_quantity} unreserved short units are available."
            )
        if cover_cash < total_trade_amount:
            raise ValueError(
                f"Insufficient paper cash to cover the short. Available after working-order reservations: "
                f"${cover_cash:,.2f}, "
                f"Required: ${total_trade_amount:,.2f}."
            )
        account.cash_balance = cash - total_trade_amount
        if float(pos.quantity) == quantity:
            db.session.delete(pos)
        else:
            pos.quantity = float(pos.quantity) - quantity
            pos.last_price = fill_price
            pos.updated_at = datetime.utcnow()

    elif is_short:
        margin_required = total_trade_amount * 1.5
        if available_cash < margin_required:
            raise ValueError(
                f"Insufficient margin for simulated short sale. Required: ${margin_required:,.2f}, "
                f"Available after reservations: ${available_cash:,.2f}."
            )
        account.cash_balance = cash + total_trade_amount
        pos = _find_or_merge_position(user_id, contract_symbol, instrument_type, 'SHORT')
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
                symbol=contract_symbol,
                underlying_symbol=underlying_sym,
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
        symbol=contract_symbol,
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
        time_in_force=data.get('time_in_force', 'DAY'),
    )
    db.session.add(test_order)

    # Handle attached Take Profit / Stop Loss Brackets
    tp_px = float(data.get('bracket_take_profit_price')) if data.get('bracket_take_profit_price') else None
    sl_px = float(data.get('bracket_stop_loss_price')) if data.get('bracket_stop_loss_price') else None
    sll_px = float(data.get('bracket_stop_loss_limit_price')) if data.get('bracket_stop_loss_limit_price') else None

    if (is_buy or is_short) and (tp_px or sl_px):
        opp_side = 'SELL' if is_buy else 'BUY_TO_CLOSE'
        available_for_exit = (
            _available_long_quantity(user_id, contract_symbol, instrument_type)
            if is_buy else _available_short_quantity(user_id, contract_symbol, instrument_type)
        )
        if available_for_exit < quantity:
            db.session.rollback()
            raise ValueError(
                f"Cannot attach exits for {quantity} units of {contract_symbol}; only "
                f"{available_for_exit} unreserved units are available."
            )
        if is_short:
            exit_reservation = quantity * multiplier * max(price for price in (tp_px, sl_px, sll_px) if price)
            cash_after_short = float(account.cash_balance or 0.0)
            cash_available_for_exit = max(0.0, cash_after_short - _reserved_cash_amount(user_id))
            if cash_available_for_exit < exit_reservation:
                db.session.rollback()
                raise ValueError(
                    f"Cannot attach the short exits. They require ${exit_reservation:,.2f} of reserved paper cash, "
                    f"but only ${cash_available_for_exit:,.2f} is available."
                )
        if tp_px:
            tp_order = WebullTestOrder(
                order_id=f"{simulated_order_id}_TP",
                user_id=user_id,
                symbol=contract_symbol,
                instrument_type=instrument_type,
                side=opp_side,
                order_type='LIMIT',
                quantity=quantity,
                limit_price=tp_px,
                status='Working',
                combo_type='STOP_PROFIT',
                time_in_force='DAY',
            )
            db.session.add(tp_order)
        if sl_px:
            sl_order = WebullTestOrder(
                order_id=f"{simulated_order_id}_SL",
                user_id=user_id,
                symbol=contract_symbol,
                instrument_type=instrument_type,
                side=opp_side,
                order_type='STOP_LOSS_LIMIT' if sll_px else 'STOP_LOSS',
                quantity=quantity,
                stop_price=sl_px,
                limit_price=sll_px,
                status='Working',
                combo_type='STOP_LOSS',
                time_in_force='DAY',
            )
            db.session.add(sl_order)

    account.updated_at = datetime.utcnow()
    db.session.commit()

    return {
        'success': True,
        'order_id': simulated_order_id,
        'symbol': contract_symbol,
        'side': side,
        'instrument_type': instrument_type,
        'filled_price': fill_price,
        'filled_quantity': quantity,
        'total_amount': total_trade_amount,
        'status': 'Filled',
        'message': f"Simulated {side} order executed for {quantity} {contract_symbol} at ${fill_price:,.2f} (Total: ${total_trade_amount:,.2f}).",
        'is_paper': True,
    }


def cancel_webull_test_order(user_id: int, order_id: str) -> Dict[str, Any]:
    """Cancel an active simulated order."""
    _lock_webull_test_account(user_id)
    order = WebullTestOrder.query.filter_by(user_id=user_id, order_id=order_id).first()
    if not order:
        raise ValueError(f"Simulated order {order_id} not found.")
    if str(order.status or '').upper().strip() not in ACTIVE_PAPER_ORDER_STATUSES:
        raise ValueError(
            f"Simulated order {order_id} is {order.status or 'not active'} and cannot be cancelled."
        )
    order.status = 'Cancelled'
    order.updated_at = datetime.utcnow()
    db.session.commit()
    return {
        'success': True,
        'order_id': order_id,
        'status': 'Cancelled',
        'message': f"Simulated order {order_id} has been cancelled."
    }
