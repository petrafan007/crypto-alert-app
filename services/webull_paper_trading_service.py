import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from core.extensions import db
from models import WebullTestAccount, WebullTestPosition, WebullTestOrder
from credentials import Credential, UserSetting
from services.webull_paper_rules import (
    EQUITY_LIKE_TYPES,
    canonical_paper_instrument_type,
    paper_order_fills_immediately,
    paper_position_valuation,
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
        account.cash_balance = amount if amount >= 0 else 0.0
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


def fetch_live_price(
    user_id: int,
    symbol: str,
    instrument_type: str = 'EQUITY',
    *,
    option_type: Optional[str] = None,
    option_strike: Optional[float] = None,
    option_expiration: Optional[str] = None,
) -> float:
    """Fetch live real-world pricing for paper order execution and valuation across all asset classes."""
    clean_sym = (symbol or '').upper().strip()
    clean_type = (instrument_type or 'EQUITY').upper().strip()

    # 1. EVENT contracts trade between $0.01 and $0.99
    if clean_type == 'EVENT':
        existing = WebullTestPosition.query.filter_by(user_id=user_id, symbol=clean_sym).first()
        if existing and existing.last_price and 0.01 <= existing.last_price <= 0.99:
            return float(existing.last_price)
        if existing and existing.cost_price and 0.01 <= existing.cost_price <= 0.99:
            return float(existing.cost_price)
        return 0.50

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
            curr_price = fetch_live_price(user_id, pos.symbol, pos.instrument_type)

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
    net_liquidation = cash + total_market_value
    short_market_value = sum(
        abs(float(pos.market_value or 0.0)) for pos in positions if str(pos.side or '').upper() == 'SHORT'
    )
    buying_power = max(0.0, cash - (short_market_value * 1.5))

    return {
        'account_id': 'TEST_PAPER_ACCOUNT',
        'account_name': 'Webull Paper Account',
        'account_type': 'CASH',
        'is_paper': True,
        'currency': account.currency or 'USD',
        'cash_balance': round(cash, 2),
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
        curr_price = pos.last_price or fetch_live_price(user_id, pos.symbol, pos.instrument_type)
        pos.last_price = curr_price
        multiplier = int(pos.contract_multiplier or (100 if pos.instrument_type == 'OPTION' else 1))
        qty = float(pos.quantity or 0.0)
        cost = float(pos.cost_price or 0.0)
        is_short = str(pos.side or '').upper() == 'SHORT'
        valuation = paper_position_valuation(pos.side, qty, cost, curr_price, multiplier)
        mv = round(valuation['market_value'], 2)
        cost_basis = valuation['cost_basis']
        display_qty = -qty if is_short else qty
        pnl = round(valuation['unrealized_pnl'], 2)
        pnl_rate = round((pnl / cost_basis * 100) if cost_basis > 0 else 0.0, 2)

        rows.append({
            'id': f"paper_pos_{pos.id}",
            'account_id': 'TEST_PAPER_ACCOUNT',
            'account_name': 'Webull Paper Account',
            'symbol': pos.symbol,
            'underlying_symbol': pos.underlying_symbol or pos.symbol,
            'instrument_type': pos.instrument_type,
            'side': pos.side,
            'quantity': display_qty,
            'amount': display_qty,
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
    account = get_or_create_webull_test_account(user_id)
    cash = float(account.cash_balance or 0.0)

    # 1. Handle Multi-leg Combo Orders (OTO, OCO, OTOCO)
    combo_orders = data.get('combo_orders')
    if combo_orders and isinstance(combo_orders, list):
        if len(combo_orders) < 2:
            raise ValueError("Webull combo orders require at least 2 legs.")
        combo_type = str(data.get('combo_type') or 'OTO').upper()
        clean_combo_id = f"SIM_COMBO_{uuid.uuid4().hex[:10].upper()}"

        # Find primary leg (first leg, or leg with role PRIMARY / MASTER)
        primary_leg = combo_orders[0]
        for leg in combo_orders:
            if str(leg.get('combo_type') or '').upper() in {'PRIMARY', 'MASTER'}:
                primary_leg = leg
                break

        primary_sym = (primary_leg.get('symbol') or data.get('symbol') or '').upper().strip()
        primary_qty = float(primary_leg.get('quantity') or 0.0)
        if primary_qty <= 0:
            raise ValueError("Primary combo leg requires a positive quantity.")
        primary_side = str(primary_leg.get('side') or 'BUY').upper()
        primary_type = str(primary_leg.get('order_type') or 'LIMIT').upper()
        primary_lpx = float(primary_leg.get('limit_price') or 0.0)

        live_px = fetch_live_price(user_id, primary_sym, 'EQUITY')
        fill_px = primary_lpx if (primary_type == 'LIMIT' and primary_lpx > 0) else live_px
        if fill_px <= 0:
            fill_px = 100.0

        trade_amount = round(primary_qty * fill_px, 2)
        if primary_side in {'BUY', 'BUY_TO_OPEN'}:
            if cash < trade_amount:
                raise ValueError(
                    f"Insufficient paper cash for primary combo leg. Required: ${trade_amount:,.2f}, Available: ${cash:,.2f}. "
                    f"Please use the Deposit button to add simulated funds."
                )
            account.cash_balance = cash - trade_amount

            pos = WebullTestPosition.query.filter_by(
                user_id=user_id, symbol=primary_sym, instrument_type='EQUITY', side='LONG'
            ).first()
            if pos:
                new_qty = float(pos.quantity) + primary_qty
                new_cost = ((float(pos.cost_price) * float(pos.quantity)) + (fill_px * primary_qty)) / new_qty
                pos.quantity = new_qty
                pos.cost_price = round(new_cost, 4)
                pos.last_price = fill_px
                pos.updated_at = datetime.utcnow()
            else:
                pos = WebullTestPosition(
                    user_id=user_id,
                    symbol=primary_sym,
                    underlying_symbol=primary_sym,
                    instrument_type='EQUITY',
                    side='LONG',
                    quantity=primary_qty,
                    cost_price=round(fill_px, 4),
                    last_price=fill_px,
                    contract_multiplier=1,
                )
                db.session.add(pos)

        # Record all legs in webull_test_orders
        for idx, leg in enumerate(combo_orders):
            is_master = (leg == primary_leg)
            l_sym = (leg.get('symbol') or primary_sym).upper().strip()
            l_side = str(leg.get('side') or 'SELL').upper()
            l_type = str(leg.get('order_type') or 'LIMIT').upper()
            l_qty = float(leg.get('quantity') or primary_qty)
            l_px = float(leg.get('limit_price')) if leg.get('limit_price') is not None else None
            l_spx = float(leg.get('stop_price')) if leg.get('stop_price') is not None else None

            leg_order_id = f"{clean_combo_id}_LEG{idx + 1}"
            test_order = WebullTestOrder(
                order_id=leg_order_id,
                user_id=user_id,
                symbol=l_sym,
                instrument_type='EQUITY',
                side=l_side,
                order_type=l_type,
                quantity=l_qty,
                limit_price=l_px,
                stop_price=l_spx,
                filled_price=fill_px if is_master else None,
                filled_quantity=primary_qty if is_master else 0.0,
                status='Filled' if is_master else 'Working',
                combo_type=combo_type,
                combo_orders=str(combo_orders),
                time_in_force=leg.get('time_in_force', 'DAY'),
            )
            db.session.add(test_order)

        account.updated_at = datetime.utcnow()
        db.session.commit()

        return {
            'success': True,
            'order_id': clean_combo_id,
            'client_combo_order_id': clean_combo_id,
            'symbol': primary_sym,
            'side': primary_side,
            'instrument_type': 'EQUITY',
            'filled_price': fill_px,
            'filled_quantity': primary_qty,
            'total_amount': trade_amount,
            'status': 'Filled',
            'legs_count': len(combo_orders),
            'message': f"Simulated {combo_type} combo order submitted ({len(combo_orders)} legs). Primary leg filled at ${fill_px:,.2f}.",
            'is_paper': True,
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

    # Event-specific parameter extraction
    event_outcome = str(data.get('event_outcome') or 'yes').lower().strip() if instrument_type == 'EVENT' else None

    # Fetch live execution quote
    live_price = fetch_live_price(
        user_id, underlying_sym or symbol, instrument_type,
        option_type=option_type, option_strike=option_strike, option_expiration=option_expiration
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
        if not float(quantity).is_integer() or quantity < 1:
            raise ValueError("Event contracts require a whole number of contracts.")
        if quantity > 50000:
            raise ValueError("Maximum quantity for event contracts is 50,000.")
        if limit_price is not None and not (0.01 <= limit_price <= 0.99):
            raise ValueError("Event contract limit price must be between $0.01 and $0.99.")
        fill_price = limit_price if (limit_price and 0.01 <= limit_price <= 0.99) else 0.50

    # Options contract display symbol
    contract_symbol = symbol
    if instrument_type in {'OPTION', 'OPTIONS'} and option_strike and option_expiration:
        contract_symbol = f"{underlying_sym} {option_expiration} ${option_strike:g} {option_type}"

    total_trade_amount = round(quantity * fill_price * multiplier, 2)

    is_buy = side in {'BUY', 'BUY_TO_OPEN'}
    is_sell = side in {'SELL', 'SELL_TO_CLOSE'}
    is_short = side in {'SHORT', 'SELL_TO_OPEN'}

    # Stop, trailing, and auction orders must never fabricate an immediate
    # weekend fill. They remain cancellable working orders until a future
    # trigger/auction processor can fill them against a qualifying quote.
    if not paper_order_fills_immediately(order_type):
        if is_buy and cash < total_trade_amount:
            raise ValueError(
                f"Insufficient paper cash. Available: ${cash:,.2f}, Required: ${total_trade_amount:,.2f}."
            )
        if is_sell:
            available_position = _find_or_merge_position(user_id, contract_symbol, instrument_type, 'LONG')
            available_quantity = float(available_position.quantity or 0.0) if available_position else 0.0
            if available_quantity < quantity:
                raise ValueError(
                    f"Cannot sell {quantity} units of {contract_symbol}. You only hold {available_quantity}."
                )
        if is_short and cash < total_trade_amount * 1.5:
            raise ValueError(
                f"Insufficient margin for simulated short sale. Required: ${total_trade_amount * 1.5:,.2f}, Available: ${cash:,.2f}."
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
            'message': f"Simulated {side} {order_type} order accepted for {quantity} {contract_symbol} and queued as Working.",
            'is_paper': True,
        }

    if is_buy:
        if cash < total_trade_amount:
            raise ValueError(
                f"Insufficient paper cash. Available: ${cash:,.2f}, Required: ${total_trade_amount:,.2f}. "
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

        if not pos or float(pos.quantity) < quantity:
            avail = float(pos.quantity) if pos else 0.0
            raise ValueError(f"Cannot sell {quantity} units of {contract_symbol}. You only hold {avail}.")

        account.cash_balance = cash + total_trade_amount

        if float(pos.quantity) == quantity:
            db.session.delete(pos)
        else:
            pos.quantity = float(pos.quantity) - quantity
            pos.last_price = fill_price
            pos.updated_at = datetime.utcnow()

    elif is_short:
        margin_required = total_trade_amount * 1.5
        if cash < margin_required:
            raise ValueError(
                f"Insufficient margin for simulated short sale. Required: ${margin_required:,.2f}, Available: ${cash:,.2f}."
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

    if is_buy and (tp_px or sl_px):
        opp_side = 'SELL'
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
