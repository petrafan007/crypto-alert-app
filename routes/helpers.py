from log import logger
from core.extensions import db
from models import Coin, WatchlistCoin
from credentials import Credential, User, UserSetting
import requests
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from collections import defaultdict, deque
import math
import numpy as np
import threading
import time
import hashlib
import hmac
import base64
import json
import jwt
from cryptography.fernet import Fernet
import os
from flask import request, jsonify, make_response, current_app as app, has_request_context
from credential_security import decrypt_secret
from services.trading_service import get_cost_basis_for_asset, calculate_avg_entry_fifo
from services.credential_service import get_user_credentials
from services.staking_service import (
    calculate_staking_value_for_user, binance_us_api_call, binance_has_staking_permission,
    build_staking_balance_view, _build_staking_dashboard_payload, _dashboard_staking_response
)

STABLE_COINS = {'USDT', 'USD', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP'}

def is_stablecoin(symbol):
    """Check if a given cryptocurrency symbol is a stablecoin"""
    return (symbol or '').strip().upper() in STABLE_COINS

background_threads = {}
AUTO_ALERT_CACHE = {}
ALERT_CHECK_INTERVAL = 300

def _format_date_only(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d')
    return str(value)[:10]

def _safe_decimal(value):
    if value is None:
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    value_str = str(value).strip()
    if not value_str:
        return Decimal('0')
    try:
        return Decimal(value_str)
    except Exception:
        return Decimal('0')

def _parse_transaction_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.utcfromtimestamp(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except Exception:
            try:
                return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
            except Exception:
                return datetime.utcnow()
    return datetime.utcnow()

def _load_transaction_details(raw_details):
    if not raw_details:
        return {}
    if isinstance(raw_details, dict):
        return raw_details
    try:
        return json.loads(raw_details)
    except Exception:
        return {}

def _is_auto_generated_detail(raw_details):
    if not raw_details:
        return False
    if isinstance(raw_details, str):
        return raw_details.strip().lower().startswith('auto-generated from')
    return False

def _extract_trade_numbers(details_dict, fallback_fee):
    if not isinstance(details_dict, dict):
        return Decimal('0'), Decimal('0'), fallback_fee
    total_after = _safe_decimal(details_dict.get('total_value_after_fees'))
    filled_value = _safe_decimal(details_dict.get('filled_value'))
    total_fees = _safe_decimal(details_dict.get('total_fees'))
    if total_fees <= 0:
        commission_info = details_dict.get('commission_detail_total')
        if isinstance(commission_info, dict):
            total_fees = _safe_decimal(commission_info.get('total_commission'))
    if total_fees <= 0:
        total_fees = _safe_decimal(details_dict.get('fee'))
    if total_after <= 0 and filled_value > 0 and total_fees > 0:
        total_after = filled_value - total_fees
    fee_used = total_fees if total_fees > 0 else fallback_fee
    return total_after, filled_value, fee_used

def _try_binance_symbol_pairs(client, symbol, extra_pairs=None):
    symbol = (symbol or '').upper()
    if not symbol:
        return None, None
    candidate_pairs = [f"{symbol}USDT", f"{symbol}USD"]
    if extra_pairs:
        candidate_pairs.extend(extra_pairs)
    for market in candidate_pairs:
        try:
            ticker = client.get_symbol_ticker(symbol=market)
            price = float(ticker['price'])
            return price, market
        except Exception:
            continue
    return None, None

def get_last_7d_prices(symbol):
    try:
        from models import PriceHistory
        cutoff = datetime.utcnow() - timedelta(days=7)
        rows = PriceHistory.query.filter(
            PriceHistory.symbol == symbol.upper(),
            PriceHistory.timestamp >= cutoff.timestamp()
        ).order_by(PriceHistory.timestamp.asc()).all()
        return [r.price for r in rows]
    except Exception as e:
        logger.error(f"Error in get_last_7d_prices: {e}")
        return []


def fetch_news_sentiment(symbol, username=None):
    """Return a bounded lightweight news sentiment score from configured NewsAPI.

    Legacy recommendation/alert helpers call this function directly. Resolving the
    active username at request time ensures those news consumers use the same
    NewsAPI integration as the primary AI workflows instead of a missing stub.
    """
    try:
        if not username and has_request_context():
            from flask_login import current_user
            if getattr(current_user, 'is_authenticated', False):
                username = current_user.username
        if not username:
            return 0.0

        from services.ai_service import news_api_search
        articles = news_api_search(symbol, username, lookback_hours=24, max_results=10)
        if not articles:
            return 0.0

        positive = {'gain', 'gains', 'rise', 'rises', 'surge', 'surges', 'bullish', 'rally', 'rallies', 'approval', 'adoption', 'upgrade'}
        negative = {'drop', 'drops', 'fall', 'falls', 'plunge', 'plunges', 'bearish', 'hack', 'lawsuit', 'ban', 'liquidation', 'liquidations'}
        score = 0
        for article in articles:
            words = set((f"{article.get('title', '')} {article.get('snippet', '')}").lower().split())
            score += len(words & positive) - len(words & negative)
        return max(-1.0, min(1.0, score / max(len(articles) * 2, 1)))
    except Exception as exc:
        logger.warning(f"News sentiment lookup failed for {symbol}: {exc}")
        return 0.0

def create_extension_jwt(user):
    if not jwt:
        raise RuntimeError("PyJWT not installed. Please add PyJWT to requirements and install.")
    payload = {
        "sub": user.id,
        "username": user.username,
        "exp": datetime.utcnow() + timedelta(hours=24),
        "iat": datetime.utcnow(),
        "scope": "extension"
    }
    token = jwt.encode(payload, app.config['SECRET_KEY'], algorithm="HS256")
    # PyJWT>=2 returns str; ensure str
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token

def get_user_from_bearer():
    if not jwt:
        raise RuntimeError("PyJWT not installed. Please add PyJWT to requirements and install.")
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth.split(' ', 1)[1].strip()
    try:
        data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
        if data.get("scope") != "extension":
            return None
        user_id = data.get('sub')
        return db.session.get(User, user_id)
    except Exception as e:
        logger.error(f"JWT decode error: {e}")
        return None

def get_manual_tax_investment(user_id, source='binance'):
    try:
        setting = UserSetting.query.filter_by(user_id=user_id).first()
        field = 'tax_webull_manual_invested_updated' if str(source).lower() == 'webull' else 'tax_manual_invested_updated'
        value = getattr(setting, field, None) if setting else None
        if not value:
            return 0.0
        return float(value)
    except (ValueError, TypeError):
        return 0.0
    except Exception as e:
        logger.error(f"Failed to fetch manual tax investment for user {user_id}: {e}")
        return 0.0

def set_manual_tax_investment(user_id, amount, source='binance'):
    try:
        amount_value = float(amount or 0.0)
    except (TypeError, ValueError):
        amount_value = 0.0

    try:
        setting = UserSetting.query.filter_by(user_id=user_id).first()
        if not setting:
            setting = UserSetting(user_id=user_id)
            db.session.add(setting)
        
        field = 'tax_webull_manual_invested_updated' if str(source).lower() == 'webull' else 'tax_manual_invested_updated'
        setattr(setting, field, amount_value)
        db.session.commit()
        return amount_value, datetime.utcnow().isoformat()
    except Exception as e:
        logger.error(f"Failed to set manual tax investment for user {user_id}: {e}")
        db.session.rollback()
        return False

def fetch_crypto_price(symbol):
    """Fetch crypto price from Binance.US only"""
    symbol = symbol.upper()
    if symbol in STABLE_COINS:
        return 1.0

    try:
        from binance.client import Client
        client = Client(tld='us')
        price, market = _try_binance_symbol_pairs(client, symbol)
        if price is not None:
            return price
    except Exception as e:
        logger.error(f"Binance.US price failed for {symbol}: {e}")

    logger.error(f"Failed to fetch price for {symbol} from Binance.US.")
    return None

def set_initial_price_on_gift(user_id, symbol, date_str):
    """
    Sets the avg_entry price for a coin if it was received as a gift/bonus/transfer/receive,
    and only if it does not already have an avg_entry price.
    """
    symbol = symbol.upper()
    coin = Coin.query.filter_by(user_id=user_id, symbol=symbol).first()
    if not coin or coin.avg_entry and coin.avg_entry > 0:
        return  # Already set

    # Try to get current price from Binance as approximation
    try:
        current_price = fetch_crypto_price(symbol)
        price = current_price if current_price else 0.0
    except Exception as e:
        logger.error(f"Failed to fetch price for {symbol}: {e}")
        price = 0.0

    if coin:
        coin.avg_entry = price
        coin.purchase_date = _format_date_only(date_str)
        db.session.commit()

def calculate_auto_alert(symbol, alert_type, avg_entry=None):
    prices = get_last_7d_prices(symbol)
    logger.info(f"[calculate_auto_alert] Prices for {symbol}: {prices}")
    if not prices or (avg_entry is not None and (not avg_entry or avg_entry == 0)):
        logger.warning(f"[calculate_auto_alert] No prices or bad avg_entry for {symbol}. Returning 10.0")
        return 10.0

    try:
        reference_price = avg_entry if avg_entry else prices[0]
        mean_price = np.mean(prices)
        std_pct = np.std(prices) / mean_price * 100 if mean_price else 0

        # Fetch 7d volume from CoinGecko
        # Use default volume since CoinGecko is not allowed (Binance-only)
        try:
            # Could potentially fetch from Binance 24hr ticker but using default for now
            avg_vol = 1000000  # Default volume
        except Exception as e:
            logger.error(f"Error setting volume for {symbol}: {e}")
            avg_vol = 1

        sentiment = fetch_news_sentiment(symbol)  # Replace fetch_sentiment with fetch_news_sentiment
        if sentiment is None:
            sentiment = 0  # Default to neutral if sentiment unavailable
            
        logger.info(f"[calculate_auto_alert] std_pct={std_pct} avg_vol={avg_vol}, sentiment={sentiment}")

        # --- AI-inspired scaling ---
        min_spread = 5
        max_spread = 50

        vol_factor = 1 / (1 + math.exp(-0.25 * (std_pct - 10)))
        vol_norm = min(max((math.log10(avg_vol) - 5) / 5, 0), 1)
        sent_factor = 1 + 0.2 * sentiment

        risk_score = 0.7 * vol_factor + 0.2 * vol_norm + 0.1 * sent_factor
        spread = min_spread + (max_spread - min_spread) * min(max(risk_score, 0), 1)

        spread = round(spread, 2)
        logger.info(f"[calculate_auto_alert] Final value for {symbol} {alert_type}: {spread}")
        return spread
        
    except Exception as e:
        logger.error(f"Error in calculate_auto_alert for {symbol}: {e}")
        return 10.0  # Safe fallback value

def ensure_background_jobs():
    """Ensure background jobs are running"""
    global background_threads
    try:
        from services.scheduler_tasks import start_background_jobs
        from flask import current_app
        
        thread_list = list(background_threads.values()) if isinstance(background_threads, dict) else list(background_threads)
        alive_threads = [t for t in thread_list if hasattr(t, 'is_alive') and t.is_alive()]
        
        if not alive_threads:
            logger.warning("No background threads found, starting them now...")
            app_obj = current_app._get_current_object() if current_app else None
            if app_obj:
                started = start_background_jobs(app_obj)
                if isinstance(started, dict):
                    background_threads = started
                elif isinstance(started, list):
                    background_threads = {f"thread_{i}": t for i, t in enumerate(started)}
                return True
        return len(alive_threads) > 0
    except Exception as e:
        logger.error(f"Error in ensure_background_jobs: {e}")
        return False

def clear_alert_state(user_id=None):
    """Clear alert_state entries. If user_id is provided, clear only entries for that user.
    Returns count of entries removed.
    """
    fn = "alert_state.json"
    removed = 0
    if not os.path.exists(fn):
        return removed
    try:
        with open(fn, 'r') as f:
            import json as _json
            state = _json.load(f)
    except Exception:
        state = {}
    if user_id is None:
        removed = len(state)
        with open(fn, 'w') as f:
            import json as _json
            _json.dump({}, f)
        logger.info(f"[ALERT_STATE] Cleared all entries ({removed})")
        return removed
    # filter user-specific keys
    prefix = f"{user_id}:"
    new_state = {k: v for k, v in state.items() if not k.startswith(prefix)}
    removed = len(state) - len(new_state)
    with open(fn, 'w') as f:
        import json as _json
        _json.dump(new_state, f)
    logger.info(f"[ALERT_STATE] Cleared {removed} entries for user {user_id}")
    return removed

def sync_binance_logs():
    """Sync Binance trade history for every user with Binance credentials."""
    try:
        from binance.client import Client

        users = db.session.query(User.id.label('user_id'), User.username, Credential.api_key, Credential.api_secret)\
            .join(Credential, User.username == Credential.username)\
            .filter(Credential._api_key.isnot(None), Credential._api_secret.isnot(None)).all()

        if not users:
            logger.warning("No Binance API credentials found")
            return

        for user in users:
            user_id = user.user_id
            username = user.username
            api_key = decrypt_secret(user.api_key)
            api_secret = decrypt_secret(user.api_secret)

            if not api_key or not api_secret:
                logger.debug(f"Skipping user {username}: missing Binance credentials")
                continue

            try:
                client = Client(api_key=api_key, api_secret=api_secret, testnet=False, tld='us')
            except Exception as client_error:
                logger.error(f"Failed to create Binance client for {username}: {client_error}")
                continue

            try:
                account_info = client.get_account()
            except Exception as account_error:
                logger.error(f"Failed to fetch account info for {username}: {account_error}")
                continue

            balances = account_info.get('balances', [])
            assets_with_balance = [
                balance['asset']
                for balance in balances
                if float(balance.get('free') or 0) > 0 or float(balance.get('locked') or 0) > 0
            ]

            if not assets_with_balance:
                logger.info(f"No Binance balances found for user {username}")
                continue

            logger.info(f"Syncing Binance logs for user {username}: {assets_with_balance}")

            all_trades = []
            for asset in assets_with_balance:
                if asset in ('USDT', 'USD'):
                    continue

                for quote in ('USD', 'USDT'):
                    symbol = f"{asset}{quote}"
                    try:
                        trades = client.get_my_trades(symbol=symbol, limit=100)
                        if trades:
                            all_trades.extend(trades)
                            logger.info(f"Found {len(trades)} trades for {symbol} (user {username})")
                    except Exception as pair_error:
                        error_text = str(pair_error)
                        if 'Invalid symbol' in error_text or 'not found' in error_text.lower():
                            logger.debug(f"Trading pair {symbol} unavailable for {username}")
                        else:
                            logger.warning(f"Error fetching trades for {symbol} ({username}): {pair_error}")
                        continue
                    finally:
                        time.sleep(0.2)

            if all_trades:
                process_binance_trades(user_id, all_trades)
            else:
                logger.info(f"No recent trades to record for user {username}")

            try:
                update_coins_from_binance_balances(user_id, balances)
            except Exception as balance_error:
                logger.error(f"Failed to update coins table for {username}: {balance_error}")

        logger.info("Binance logs sync completed successfully")

    except Exception as e:
        logger.error(f"Error in sync_binance_logs: {e}")
        raise

def _coerce_activity_datetime(value):
    """Coerce incoming date values to naive UTC datetimes for storage."""
    if isinstance(value, datetime):
        return value
    dt_obj = _parse_transaction_datetime(value)
    if dt_obj.tzinfo is not None:
        return dt_obj.astimezone(timezone.utc).replace(tzinfo=None)
    return dt_obj

def _format_activity_date(value):
    """Format activity dates for JSON responses."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)

def _calculate_portfolio_performance(transactions, coins):
    """
    Derive realized/unrealized performance metrics from raw transaction rows and current holdings.
    Returns a dictionary with totals and per-asset breakdowns.
    """
    real_transactions = []
    for tx in transactions:
        details_raw = tx.get('details')
        if _is_auto_generated_detail(details_raw):
            continue
        asset = (tx.get('asset') or '').upper()
        if not asset:
            continue
        real_transactions.append({
            'id': tx.get('id'),
            'date': tx.get('date'),
            'asset': asset,
            'type': tx.get('type', '').upper(),
            'amount': _safe_decimal(tx.get('amount')),
            'cost_basis': _safe_decimal(tx.get('cost_basis')),
            'proceeds': _safe_decimal(tx.get('proceeds')),
            'fee': _safe_decimal(tx.get('fee')),
            'details': tx.get('details')
        })

    if real_transactions:
        real_transactions.sort(key=lambda item: (_parse_transaction_datetime(item['date']), item['id']))

    fifo_lots = defaultdict(deque)
    realized_pnl = Decimal('0')
    total_fees_paid = Decimal('0')
    total_buy_cost = Decimal('0')
    total_sell_proceeds = Decimal('0')

    for tx in real_transactions:
        tx_type = tx['type']
        amount = tx['amount']
        if amount == 0:
            continue
        details_dict = _load_transaction_details(tx['details'])
        total_after_fees, filled_value, fee_used = _extract_trade_numbers(details_dict, tx['fee'])
        fee_used = fee_used if fee_used > 0 else tx['fee']
        asset = tx['asset']

        if tx_type == 'BUY':
            if amount <= 0:
                continue
            total_fees_paid += fee_used
            if total_after_fees > 0:
                total_cost = total_after_fees
            else:
                total_cost = tx['cost_basis'] + fee_used
            fifo_lots[asset].append({'amount': amount, 'cost': total_cost})
            total_buy_cost += total_cost

        elif tx_type == 'SELL':
            quantity = abs(amount)
            if quantity <= 0:
                continue
            total_fees_paid += fee_used
            if total_after_fees > 0:
                net_proceeds = total_after_fees
            else:
                proceeds = tx['proceeds']
                if proceeds > 0:
                    net_proceeds = proceeds - fee_used
                elif filled_value > 0:
                    net_proceeds = filled_value - fee_used
                else:
                    net_proceeds = proceeds

            total_sell_proceeds += net_proceeds

            cost_total = Decimal('0')
            remaining = quantity
            lots = fifo_lots[asset]

            while remaining > 0 and lots:
                lot = lots[0]
                lot_amount = lot['amount']
                lot_cost = lot['cost']
                if lot_amount <= 0:
                    lots.popleft()
                    continue
                slice_amount = min(remaining, lot_amount)
                proportion = slice_amount / lot_amount
                cost_slice = lot_cost * proportion
                cost_total += cost_slice
                lot['amount'] = lot_amount - slice_amount
                lot['cost'] = lot_cost - cost_slice
                if lot['amount'] <= Decimal('1e-10'):
                    lots.popleft()
                remaining -= slice_amount

            recorded_cost_basis = tx['cost_basis']
            if recorded_cost_basis > 0 and cost_total < recorded_cost_basis:
                cost_total = recorded_cost_basis

            realized_pnl += net_proceeds - cost_total

    remaining_costs = {}
    for asset, lots in fifo_lots.items():
        remaining_cost = Decimal('0')
        remaining_amount = Decimal('0')
        for lot in lots:
            lot_amount = lot['amount']
            lot_cost = lot['cost']
            if lot_amount > 0 and lot_cost > 0:
                remaining_cost += lot_cost
                remaining_amount += lot_amount
        if remaining_amount > 0:
            remaining_costs[asset] = {
                'amount': remaining_amount,
                'cost': remaining_cost
            }

    holdings_value = Decimal('0')
    holdings_cost = Decimal('0')
    holdings_map = {}

    for coin in coins:
        amount = _safe_decimal(getattr(coin, 'amount', 0))
        if amount <= Decimal('0.0000001'):
            continue
        asset = (getattr(coin, 'symbol', '') or '').upper()
        if not asset:
            continue
        current_price = _safe_decimal(getattr(coin, 'current', 0))
        current_value = amount * current_price

        remaining_entry = remaining_costs.get(asset)
        if remaining_entry:
            derived_cost = remaining_entry['cost']
        else:
            initial_value = _safe_decimal(getattr(coin, 'initial_value', 0))
            if initial_value > 0:
                derived_cost = initial_value
            else:
                avg_entry = _safe_decimal(getattr(coin, 'avg_entry', 0))
                derived_cost = avg_entry * amount

        avg_price = derived_cost / amount if amount > 0 else Decimal('0')

        holdings_map[asset] = {
            'amount': float(amount),
            'cost_basis': float(derived_cost),
            'avg_price_per_unit': float(avg_price),
            'current_price': float(current_price),
            'current_value': float(current_value),
            'source': 'portfolio_table'
        }

        holdings_value += current_value
        holdings_cost += derived_cost

    unrealized_pnl = holdings_value - holdings_cost
    total_pnl = realized_pnl + unrealized_pnl

    fifo_snapshot = {
        asset: [
            {
                'amount': float(lot['amount']),
                'cost': float(lot['cost'])
            }
            for lot in lots if lot['amount'] > 0 and lot['cost'] > 0
        ]
        for asset, lots in fifo_lots.items() if any(lot['amount'] > 0 and lot['cost'] > 0 for lot in lots)
    }

    return {
        'realized_pnl': float(realized_pnl),
        'unrealized_pnl': float(unrealized_pnl),
        'total_pnl': float(total_pnl),
        'holdings_value': float(holdings_value),
        'holdings_cost': float(holdings_cost),
        'total_fees_paid': float(total_fees_paid),
        'total_buy_cost': float(total_buy_cost),
        'total_sell_proceeds': float(total_sell_proceeds),
        'holdings_map': holdings_map,
        'fifo_lots': fifo_snapshot
    }

def coin_to_dict(c):
    return {
        "id": c.id,
        "symbol": c.symbol,
        "avg_entry": round(c.avg_entry or 0, 6),
        "current": round(c.current or 0, 6),
        "amount": round(c.amount or 0, 6),
        "current_value": round((c.current or 0) * (c.amount or 0), 6),
        "custom_lower_pct": c.custom_lower_pct,
        "custom_upper_pct": c.custom_upper_pct,
        "alert_enabled": c.alert_enabled,
        "favorite": c.is_manual,
        "hidden": c.hidden,
        "auto_hidden": c.auto_hidden,
        "force_visible": c.force_visible,
        "pct_change": round(((c.current - c.avg_entry) / c.avg_entry * 100) if c.avg_entry else 0.0, 6),
    }

def binance_has_staking_permission(cred):
    """Best-effort check to see if the key can access staking endpoints."""
    try:
        # Probe the staking listing endpoint - Binance.US returns 403/401 when the
        # key lacks Earn/Staking access, otherwise it responds with 200 + JSON.
        response = binance_us_api_call(cred, '/sapi/v1/staking/asset', method='GET', use_trading_keys=True)
        if response.status_code == 200:
            return True

        # Interpret common “permission denied” signals; allow other statuses to fall through.
        try:
            payload = response.json()
            message = str(payload.get('msg') or payload)
        except ValueError:
            message = response.text

        lower_msg = (message or '').lower()
        if response.status_code in (401, 403) or 'permission' in lower_msg or 'not authorized' in lower_msg:
            return False

        logger.warning(
            "Binance staking permission probe returned unexpected status %s: %s",
            response.status_code,
            message,
        )
        return None
    except Exception as exc:
        logger.error(f"Failed to inspect Binance staking permissions: {exc}", exc_info=True)
        return None

def _respond_with_staking_dashboard_payload(cred):
    payload = _build_staking_dashboard_payload(cred)
    response = make_response(jsonify(payload))
    cache_header = 'no-store, no-cache, must-revalidate, max-age=0, private'
    response.headers['Cache-Control'] = cache_header
    response.headers['CDN-Cache-Control'] = 'no-store'
    response.headers['Surrogate-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

def _dashboard_staking_response(cred):
    if not cred:
        response = make_response(jsonify({
            'totalStakedValue': 0,
            'activePositions': 0,
            'pendingPositions': 0,
            'todayRewards': 0,
            'avgApy': 0,
            'activeValue': 0,
            'pendingValue': 0,
            'totalValue': 0
        }))
        response.headers['Cache-Control'] = 'no-store'
        return response
    return _respond_with_staking_dashboard_payload(cred)


def get_coin_sentiment(symbol, coin=None, current_price=None, username=None):
    """
    Returns the AI-generated sentiment for a coin from the coins table.
    The sentiment is determined by the 3-stage agentic AI workflow and stored in the coins table.
    Valid values are 'Buy', 'Sell', or 'Hold'.
    If sentiment cannot be pulled or is invalid, returns 'Error'. NEVER falls back to 'Hold'.
    """
    try:
        if not coin:
            # If coin object not provided, try to get it from the database
            coin = db.session.query(Coin).filter_by(symbol=symbol).first()
            if not coin:
                return "Error"
        
        # Return the AI-generated sentiment if available
        if hasattr(coin, 'sentiment') and coin.sentiment in ['Buy', 'Sell', 'Hold']:
            return coin.sentiment
        elif hasattr(coin, 'sentiment') and coin.sentiment:
            return coin.sentiment
            
        # If no valid sentiment is available, return 'Error' (NEVER fall back to 'Hold')
        return "Error"
        
    except Exception as e:
        logger.error(f"Error in get_coin_sentiment for {symbol}: {e}")
        return "Error"

def format_iso_utc(dt):
    """Format datetime as UTC ISO 8601 string with Z indicator so browsers correctly convert to local time."""
    if not dt:
        return None
    if isinstance(dt, str):
        if not dt.endswith('Z') and not '+' in dt and not '-' in dt[10:]:
            return f"{dt}Z"
        return dt
    if hasattr(dt, 'tzinfo') and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()

def get_user_latest_news_cache(user_id):
    """
    Returns a dictionary mapping both coin_id (int) and symbol (upper str) to its latest AI news analysis dict:
    {
        key: {
            'text': str,
            'created_at': isoformat_str
        }
    }
    """
    try:
        from models import AIConversation, Coin
        rows = AIConversation.query.filter(
            AIConversation.user_id == user_id,
            AIConversation.prompt_type == 'coin_analysis',
            AIConversation.sender == 'ai'
        ).order_by(AIConversation.id.desc()).all()

        cache = {}
        coin_ids = {row.coin_id for row in rows if row.coin_id is not None}
        coins_by_id = {}
        if coin_ids:
            coins_by_id = {
                coin.id: coin.symbol
                for coin in Coin.query.filter(
                    Coin.user_id == user_id,
                    Coin.id.in_(coin_ids),
                ).all()
            }
        for row in rows:
            entry = {
                'text': row.body or '',
                'created_at': format_iso_utc(row.created_at)
            }
            if row.coin_id is not None and row.coin_id not in cache:
                cache[row.coin_id] = entry
            symbol = coins_by_id.get(row.coin_id)
            if symbol:
                sym = str(symbol).strip().upper()
                if sym and sym not in cache:
                    cache[sym] = entry
        return cache
    except Exception as e:
        logger.error(f"Error fetching latest news cache for user {user_id}: {e}")
        return {}

def apply_auto_visibility_rules(coin, _current_value):
    """Apply automatic Portfolio visibility rules based on the held amount."""
    changed = False
    try:
        amount = float(getattr(coin, 'amount', 0) or 0)
    except (TypeError, ValueError):
        amount = 0.0

    # Filled positions are Portfolio holdings from 0.0001 units upward. Below
    # that, an unfilled/pending BUY stays represented in the Watchlist instead.
    if amount >= 0.0001:
        if getattr(coin, 'auto_hidden', False):
            if getattr(coin, 'hidden', False):
                coin.hidden = False
                changed = True
            coin.auto_hidden = False
            changed = True
        # If manually hidden, we respect it unless it's auto_hidden
    else:
        if not getattr(coin, 'force_visible', False) and not getattr(coin, 'is_manual', False):
            if not getattr(coin, 'hidden', False):
                coin.hidden = True
                changed = True
            if not getattr(coin, 'auto_hidden', False):
                coin.auto_hidden = True
                changed = True
    
    return changed


from pathlib import Path
import re
from flask import current_app, Response


def serve_react_app():
    """Serve the current React index without changing fingerprinted module URLs."""
    index_path = Path(current_app.static_folder or '') / 'index.html'
    logger.info(f"Serving React index from {index_path}")
    try:
        content = index_path.read_text(encoding='utf-8')
    except FileNotFoundError:
        logger.warning("React index file missing, falling back to send_static_file")
        resp = current_app.send_static_file('index.html')
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp

    # Vite fingerprints asset filenames. Keep module URLs canonical: adding a
    # query only to the HTML entry loads it again when a lazy chunk imports it,
    # creating a second React root and a different authentication context.
    resp = Response(content, mimetype='text/html')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

__all__ = [name for name in globals() if not name.startswith('__')]
