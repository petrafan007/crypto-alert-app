from datetime import datetime, timedelta
from core.extensions import db
from models import Coin
from trading_models import PortfolioValueHistory, AllActivity
from credentials import User, Credential
from log import logger
from services.credential_service import get_user_credentials
import threading
import time
import json
import math

_snapshot_cooldown = {}
_SNAPSHOT_COOLDOWN_SECS = 30

PORTFOLIO_HISTORY_RANGE_CONFIG = {
    "4H": {"duration_ms": 4 * 60 * 60 * 1000, "increment_ms": 1 * 60 * 60 * 1000, "points": 4},
    "12H": {"duration_ms": 12 * 60 * 60 * 1000, "increment_ms": 2 * 60 * 60 * 1000, "points": 6},
    "1D": {"duration_ms": 24 * 60 * 60 * 1000, "increment_ms": 4 * 60 * 60 * 1000, "points": 6},
    "3D": {"duration_ms": 72 * 60 * 60 * 1000, "increment_ms": 12 * 60 * 60 * 1000, "points": 6},
    "7D": {"duration_ms": 168 * 60 * 60 * 1000, "increment_ms": 24 * 60 * 60 * 1000, "points": 7},
    "4W": {"duration_ms": 4 * 7 * 24 * 60 * 60 * 1000, "increment_ms": 7 * 24 * 60 * 60 * 1000, "points": 4},
    "3M": {"duration_ms": 90 * 24 * 60 * 60 * 1000, "increment_ms": 30 * 24 * 60 * 60 * 1000, "points": 3},
    "6M": {"duration_ms": 180 * 24 * 60 * 60 * 1000, "increment_ms": 30 * 24 * 60 * 60 * 1000, "points": 6},
    "1Y": {"duration_ms": 365 * 24 * 60 * 60 * 1000, "increment_ms": 30 * 24 * 60 * 60 * 1000, "points": 12},
}

def compute_portfolio_total_value(user_id, username=None, cred=None, include_staking=True):
    """Return the portfolio total exactly as displayed in the dashboard widget."""
    total_value = 0.0
    regular_total = 0.0
    staking_total = 0.0

    try:
        portfolio = get_portfolio_data_for_user(user_id)
        for coin in portfolio:
            val = coin.get("current_value") or 0.0
            regular_total += val
        total_value = regular_total
    except Exception as portfolio_err:
        logger.error(f"Portfolio aggregation error for user {user_id}: {portfolio_err}")
        return 0.0

    if not include_staking:
        return total_value

    try:
        if cred is None:
            resolved_username = username
            if not resolved_username:
                user_obj = User.query.get(user_id)
                if user_obj:
                    resolved_username = user_obj.username
            if resolved_username:
                cred = get_user_credentials(resolved_username)
        if cred:
            from services.staking_service import calculate_staking_value_for_user
            staking_active, staking_pending = calculate_staking_value_for_user(cred, user_id)
            staking_total = staking_active + staking_pending
            total_value += staking_total
    except Exception as staking_err:
        logger.error(f"Staking aggregation error for user {user_id}: {staking_err}")

    return total_value

def record_true_portfolio_value():
    """Record the total portfolio value for all users."""
    try:
        users_with_creds = db.session.query(User).join(
            Credential, User.username == Credential.username
        ).filter(
            db.and_(Credential._api_key.isnot(None), Credential._api_secret.isnot(None))
        ).all()

        for user in users_with_creds:
            try:
                cred_obj = get_user_credentials(user.username)
                total_value = compute_portfolio_total_value(
                    user.id,
                    username=user.username,
                    cred=cred_obj
                )
                total_value = round(total_value, 2)

                if total_value > 0:
                    record_portfolio_history(user.id, total_value)
                    logger.info(f"Recorded portfolio value of ${total_value:.2f} for user {user.username}")

            except Exception as e:
                db.session.rollback()
                logger.error(f"Error recording portfolio value for {user.username}: {e}")

    except Exception as e:
        logger.error(f"Error in record_true_portfolio_value: {e}")

def record_portfolio_history(user_id, value):
    """Utility function to record portfolio value in history table"""
    try:
        history_record = PortfolioValueHistory(
            user_id=user_id,
            value=value,
            timestamp=datetime.utcnow(),
            date=datetime.utcnow().strftime('%Y-%m-%d')
        )
        db.session.add(history_record)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to record portfolio history for user {user_id}: {e}")

def get_portfolio_data_for_user(user_id):
    """Get comprehensive portfolio data from all crypto databases."""
    try:
        cost_basis_map = get_cost_basis_from_transactions(user_id)
        all_coins = Coin.query.filter_by(user_id=user_id).all()
        
        portfolio = []
        for coin in all_coins:
            try:
                symbol = coin.symbol.upper()
                amount = float(coin.amount or 0.0)
                
                if symbol in ['USD', 'USDT', 'USDC', 'DAI']:
                    current_price = 1.0
                else:
                    current_price = coin.current if coin.current and coin.current > 0 else (coin.avg_entry or 0)
                
                current_value = amount * current_price if current_price else 0.0
                
                if current_value < 1.0 and coin.hidden and not coin.force_visible:
                    continue
                    
                cost_info = cost_basis_map.get(coin.symbol.upper())
                if cost_info and cost_info.get('quantity', 0) > 0 and coin.amount > 0:
                    effective_avg_entry = cost_info['cost_basis'] / cost_info['quantity']
                    derived_cost_basis = effective_avg_entry * coin.amount
                elif coin.initial_value and coin.initial_value > 0:
                    effective_avg_entry = (coin.initial_value / coin.amount) if coin.amount else coin.avg_entry or 0
                    derived_cost_basis = coin.initial_value
                else:
                    effective_avg_entry = coin.avg_entry or 0
                    derived_cost_basis = effective_avg_entry * coin.amount if coin.amount else 0

                pct_change = 0
                if effective_avg_entry and effective_avg_entry > 0:
                    pct_change = ((current_price - effective_avg_entry) / effective_avg_entry) * 100

                portfolio.append({
                    "id": coin.id,
                    "symbol": coin.symbol,
                    "amount": coin.amount,
                    "avg_entry": effective_avg_entry,
                    "initial_value": derived_cost_basis,
                    "purchase_date": coin.purchase_date,
                    "current_price": current_price,
                    "current_value": current_value,
                    "pct_change": pct_change,
                    "sentiment": getattr(coin, 'sentiment', None),
                    "alert_enabled": coin.alert_enabled,
                    "note": coin.note,
                    "custom_lower_val": coin.custom_lower_val,
                    "custom_upper_val": coin.custom_upper_val,
                    "custom_lower_type": coin.custom_lower_type,
                    "custom_upper_type": coin.custom_upper_type
                })
            except Exception as e:
                logger.error(f"Error processing coin {coin.symbol}: {e}")
        return portfolio
    except Exception as e:
        logger.error(f"Error getting portfolio data: {e}")
        return []

def get_cost_basis_from_transactions(user_id):
    """Derive current cost basis for each asset from transaction history."""
    try:
        rows = AllActivity.query.filter(
            AllActivity.user_id == user_id,
            AllActivity.asset.isnot(None),
            AllActivity.asset != ''
        ).order_by(AllActivity.date.asc(), AllActivity.id.asc()).all()

        aggregates = {}
        for row in rows:
            symbol = (row.asset or '').upper()
            if not symbol: continue
            amount = row.amount or 0.0
            cost_component = row.cost_basis or 0.0
            info = aggregates.setdefault(symbol, {'quantity': 0.0, 'cost_basis': 0.0})
            
            if amount > 0:
                info['quantity'] += amount
                info['cost_basis'] += max(cost_component, 0.0)
            elif amount < 0:
                sold_qty = abs(amount)
                prev_qty = info['quantity']
                prev_cost = info['cost_basis']
                if prev_qty > 0:
                    reduction = (prev_cost / prev_qty) * sold_qty if not cost_component else cost_component
                    info['quantity'] = max(prev_qty - sold_qty, 0.0)
                    info['cost_basis'] = max(prev_cost - reduction, 0.0)
            
            if info['quantity'] < 1e-9: info['quantity'] = 0.0
            if info['cost_basis'] < 1e-6: info['cost_basis'] = 0.0
        return aggregates
    except Exception as e:
        logger.error(f"Error computing cost basis: {e}")
        return {}

def get_comprehensive_crypto_data_for_user(user_id, limit_transactions=50, days_history=30):
    """Get comprehensive crypto data including portfolio, transactions, and portfolio history."""
    try:
        data = {
            "portfolio": get_portfolio_data_for_user(user_id),
            "recent_transactions": [],
            "portfolio_value_history": [],
            "summary": {}
        }
        
        transactions = AllActivity.query.filter_by(user_id=user_id).order_by(AllActivity.date.desc()).limit(limit_transactions).all()
        for tx in transactions:
            data["recent_transactions"].append({
                "date": tx.date, "type": tx.type, "asset": tx.asset, "amount": tx.amount,
                "proceeds": tx.proceeds, "cost_basis": tx.cost_basis, "gain_loss": tx.gain_loss,
                "fee": tx.fee, "description": tx.description, "txid": tx.txid,
                "status": tx.status, "details": tx.details
            })
        
        cutoff_date = datetime.now() - timedelta(days=days_history)
        history = PortfolioValueHistory.query.filter(
            PortfolioValueHistory.user_id == user_id,
            PortfolioValueHistory.timestamp >= cutoff_date
        ).order_by(PortfolioValueHistory.timestamp.desc()).all()
        
        for entry in history:
            data["portfolio_value_history"].append({
                "timestamp": int(entry.timestamp.timestamp()) if entry.timestamp else 0,
                "date": entry.timestamp.strftime('%Y-%m-%d %H:%M:%S') if entry.timestamp else entry.date,
                "value": entry.value
            })
        
        total_val = sum(c.get("current_value", 0) for c in data["portfolio"])
        initial_val = sum(c.get("initial_value", 0) for c in data["portfolio"])
        data["summary"] = {
            "total_value": total_val,
            "total_initial_value": initial_val,
            "pnl": total_val - initial_val,
            "pnl_pct": ((total_val - initial_val) / initial_val * 100) if initial_val > 0 else 0
        }
        
        return data
    except Exception as e:
        logger.error(f"Error getting comprehensive crypto data: {e}")
        return {}

def trigger_portfolio_snapshot(user_id: int, username: str) -> None:
    """Fire-and-forget: write a PortfolioValueHistory row immediately after a
    real trade or staking action so the portfolio chart updates at once rather
    than waiting up to 5 minutes for the background sync loop.

    A 30-second per-user cooldown prevents duplicate rows when multiple events
    fire in quick succession.
    """
    now = time.time()
    if now - _snapshot_cooldown.get(user_id, 0) < _SNAPSHOT_COOLDOWN_SECS:
        logger.info(f"[snapshot] Cooldown active — skipping immediate snapshot for user {user_id}")
        return
    _snapshot_cooldown[user_id] = now

    def _run():
        from flask import current_app
        # We'll use the current_app's context to run the snapshot
        # Since we're in a factory, we must ensure we have an app context
        try:
            # Check if we are already in an app context (might be if called from a request)
            # but usually background threads need their own.
            # However, in this pattern, we'll try to get the app from current_app
            # which works if the thread was started from an active context.
            app = current_app._get_current_object()
            with app.app_context():
                try:
                    cred = get_user_credentials(username)
                    total_value = compute_portfolio_total_value(user_id, username=username, cred=cred)
                    total_value = round(total_value, 2)
                    if total_value > 0:
                        record_portfolio_history(user_id, total_value)
                        logger.info(f"[snapshot] Recorded ${total_value:.2f} for user {user_id} after trade/stake")
                except Exception as exc:
                    logger.error(f"[snapshot] Failed to record snapshot for user {user_id}: {exc}")
        except Exception as e:
            logger.error(f"[snapshot] Could not get app context for background thread: {e}")

    threading.Thread(target=_run, daemon=True).start()

def _compute_portfolio_history_series(user_id, range_key):
    """Return evenly spaced portfolio history points straight from stored values."""
    config = PORTFOLIO_HISTORY_RANGE_CONFIG.get(range_key, PORTFOLIO_HISTORY_RANGE_CONFIG["1D"])
    now_ms = int(time.time() * 1000)
    duration_ms = config["duration_ms"]
    start_ms = now_ms - duration_ms

    end_ts = math.ceil(now_ms / 1000)
    start_ts = max(0, math.floor(start_ms / 1000) - 3600)

    # Query portfolio history using ORM
    raw_rows = PortfolioValueHistory.query.filter(
        PortfolioValueHistory.user_id == user_id,
        PortfolioValueHistory.timestamp >= datetime.utcfromtimestamp(start_ts),
        PortfolioValueHistory.timestamp <= datetime.utcfromtimestamp(end_ts)
    ).order_by(PortfolioValueHistory.timestamp.asc()).all()

    if not raw_rows:
        return []

    raw_data = [(int(row.timestamp.timestamp()) * 1000, round(float(row.value), 2)) for row in raw_rows if row.value is not None]
    if not raw_data:
        return []

    chart_data = []
    data_len = len(raw_data)
    data_idx = 0
    current_value = raw_data[0][1]

    for i in range(config["points"]):
        target_ms = now_ms - (config["points"] - 1 - i) * config["increment_ms"]

        while data_idx < data_len and raw_data[data_idx][0] <= target_ms:
            current_value = raw_data[data_idx][1]
            data_idx += 1

        chart_data.append([target_ms, current_value])

    return chart_data

def sync_coins_from_transactions(user_id=None):
    """
    Synchronize coins table with calculated balances from transaction history using ORM.
    This ensures portfolio matches actual transaction data.
    """
    from flask_login import current_user
    if user_id is None:
        user_id = current_user.id
        
    try:
        from trading_models import AllActivity
        from models import Coin
        from sqlalchemy import case, func
        
        logger.info(f"Syncing coins table from transactions for user {user_id}")
        
        transaction_assets_query = db.session.query(
            AllActivity.asset,
            func.sum(case(
                (AllActivity.type.in_(['BUY', 'GIFT', 'BONUS', 'TRANSFER', 'RECEIVE']), AllActivity.amount),
                (AllActivity.type == 'SELL', -AllActivity.amount),
                else_=0
            )).label('net_amount'),
            func.min(AllActivity.date).label('first_date'),
            func.avg(case(
                (db.and_(AllActivity.type == 'BUY', AllActivity.amount > 0), AllActivity.proceeds / AllActivity.amount),
                else_=None
            )).label('avg_buy_price')
        ).filter(
            AllActivity.status == 'FILLED',
            AllActivity.user_id == user_id
        ).group_by(AllActivity.asset).having(func.sum(case(
            (AllActivity.type.in_(['BUY', 'GIFT', 'BONUS', 'TRANSFER', 'RECEIVE']), AllActivity.amount),
            (AllActivity.type == 'SELL', -AllActivity.amount),
            else_=0
        )) > 0.000001).all()
        
        for asset, net_amount, first_date, avg_buy_price in transaction_assets_query:
            coin = Coin.query.filter_by(user_id=user_id, symbol=asset).first()
            if not coin:
                coin = Coin(
                    user_id=user_id,
                    symbol=asset,
                    amount=float(net_amount),
                    initial_price=float(avg_buy_price or 0.0),
                    purchase_date=_format_date_only(first_date),
                    current=float(avg_buy_price or 0.0),
                    hidden=False,
                    alert_enabled=True
                )
                db.session.add(coin)
            else:
                if not coin.initial_price or coin.initial_price == 0:
                    coin.initial_price = float(avg_buy_price or 0.0)
        
        db.session.commit()
        logger.info(f"Successfully synced {len(transaction_assets_query)} assets for user {user_id}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error syncing coins from transactions: {e}")

def _format_date_only(value):
    """Format a date value as YYYY-MM-DD."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d')
    return str(value)[:10]
