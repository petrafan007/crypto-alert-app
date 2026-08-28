
from datetime import timedelta, datetime, timezone
import requests
import threading
import json
import time
import re
import traceback
from flask import Blueprint, send_file, request, jsonify, render_template, current_app, redirect, url_for, session, make_response
from flask_login import current_user, login_required, login_user, logout_user
from models import Coin, WatchlistCoin, Notification, PriceHistory
from credentials import Credential, User, UserSetting
from core.extensions import db
from log import logger
from services.price_history_service import ensure_price_history
from routes.helpers import *

# Database & Models
from core.extensions import db
from models import Coin
from trading_models import RealOrder, TestOrder, TestPortfolio, TradingSettings
from sqlalchemy import text
from credentials import Credential

# Log
from log import logger

# Modular Service Imports
from services.portfolio_service import (
    compute_portfolio_total_value, _compute_portfolio_history_series, 
    record_true_portfolio_value, sync_coins_from_transactions, 
    trigger_portfolio_snapshot, update_portfolio_from_real_order
)
from services.binance_service import (
    fetch_binance_price, build_order_config,
    get_symbol_filters, get_trade_fee_for_symbol,
    get_cached_exchange_info,
    sync_portfolio_from_binance, update_all_coin_prices_from_binance
)
from services.staking_service import (
    build_staking_balance_view, calculate_staking_value_for_user,
    binance_us_api_call
)
from services.credential_service import get_user_credentials
from services.webull_service import WebullConnectionError, get_webull_order_history, normalize_webull_environment
from services.webull_import_service import get_webull_total_value
from services.notification_service import notify_order_fill, create_system_notification, send_telegram_message
from services.common import _coerce_float, format_price, format_quantity
from credential_security import decrypt_secret
from transaction_utils import recalculate_asset_activity

# Stubs for missing functions/constants (to be moved/removed later)
_KLINES_CACHE = {}
_KLINES_CACHE_TTL = 300
def _coerce_activity_datetime(dt): return dt # TODO: move to common
def update_test_portfolio(*args, **kwargs): pass # TODO

# Blueprint Definition
portfolio_bp = Blueprint('portfolio', __name__)


def _run_price_history_backfill_bg(symbols):
    """Fire-and-forget 7-day price history backfill for one or more symbols, safe to call from a request thread."""
    app = current_app._get_current_object()

    def _worker():
        with app.app_context():
            for sym in symbols:
                try:
                    ensure_price_history(sym)
                except Exception as e:
                    logger.warning(f"Backfill price history failed for {sym}: {e}")

    threading.Thread(target=_worker, daemon=True).start()



@portfolio_bp.route('/api/sync-portfolio-from-transactions', methods=['POST'])
@login_required
def api_sync_portfolio_from_transactions():
    """Force sync portfolio with transaction data to fix discrepancies"""
    try:
        sync_coins_from_transactions()
        return jsonify({"success": True, "message": "Portfolio synced with transaction data successfully"})
    except Exception as e:
        logger.error(f"Error syncing portfolio from transactions: {e}")
        return jsonify({"success": False, "error": str(e)}), 500



@portfolio_bp.route('/api/transactions', methods=['POST'])
@login_required
def add_transaction():
    """Add a new transaction to the all_activities table using ORM"""
    try:
        from trading_models import AllActivity
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['date', 'type', 'asset', 'amount']
        for field in required_fields:
            if field not in data or data[field] is None or data[field] == '':
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Generate unique transaction ID
        import uuid
        import time
        txid = f"manual_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        
        activity_date = _coerce_activity_datetime(data['date'])

        # Create new activity using ORM
        new_activity = AllActivity(
            date=activity_date,
            type=data['type'].upper(),
            asset=data['asset'].upper(),
            amount=float(data['amount']) if data['amount'] else 0.0,
            proceeds=float(data.get('proceeds', 0)) if data.get('proceeds') else 0.0,
            cost_basis=float(data.get('cost_basis', 0)) if data.get('cost_basis') else 0.0,
            gain_loss=float(data.get('gain_loss', 0)) if data.get('gain_loss') else 0.0,
            fee=float(data.get('fee', 0)) if data.get('fee') else 0.0,
            description=data.get('description', ''),
            txid=txid,
            status=data.get('status', 'completed'),
            details=data.get('details', 'Manual entry'),
            user_id=current_user.id,
            avg_entry=float(data.get('avg_entry', 0)) if data.get('avg_entry') else 0.0,
            exchange=data.get('exchange', 'manual')
        )
        
        db.session.add(new_activity)
        db.session.commit()
        
        logger.info(f"Added manual transaction: {new_activity.type} {new_activity.amount} {new_activity.asset}")
        
        return jsonify({
            "success": True,
            "message": "Transaction added successfully",
            "txid": txid
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error adding transaction: {str(e)}")
        return jsonify({"error": "Failed to add transaction"}), 500



@portfolio_bp.route("/api/true-portfolio-history")
@login_required
def api_true_portfolio_history():
    """Return portfolio trend points derived strictly from stored history."""
    try:
        req_range = request.args.get("range", "1D")
        account_scope = request.args.get('account_scope', 'all').lower()
        if account_scope not in {'all', 'binance', 'webull'}:
            return jsonify([]), 400
        chart_data = _compute_portfolio_history_series(current_user.id, req_range, account_scope)
        if chart_data:
            values = [point[1] for point in chart_data]
            logger.info(
                f"Portfolio history {req_range}: {len(chart_data)} points "
                f"(min=${min(values):.2f}, max=${max(values):.2f})"
            )
        else:
            logger.info(f"Portfolio history {req_range}: no stored points available")

        response = make_response(jsonify(chart_data))
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    except Exception as e:
        logger.error(f"true-portfolio-history error: {str(e)}")
        return jsonify([])


@portfolio_bp.route("/api/record-portfolio-value", methods=["POST"])
@login_required
def api_record_portfolio_value():
    """Manually record current portfolio value for testing"""
    try:
        # Run the portfolio value recording function
        record_true_portfolio_value()
        return jsonify({
            "success": True,
            "message": "Portfolio value recorded successfully"
        })
    except Exception as e:
        logger.error(f"Error recording portfolio value: {e}")
        return jsonify({
            "success": False,
            "message": f"Error recording portfolio value: {str(e)}"
        }), 500

    
@portfolio_bp.route("/api/binance-price")
@login_required
def api_binance_price():
    symbol = request.args.get("symbol", "").upper()
    price = fetch_binance_price(symbol)
    return jsonify({"price": price})


@portfolio_bp.route("/api/portfolio-history")
@login_required
def api_portfolio_history():
    """Legacy endpoint retained for compatibility; delegates to true portfolio history."""
    try:
        points = _compute_portfolio_history_series(current_user.id, request.args.get("range", "1D"))
        response = make_response(jsonify(points))
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response
    except Exception as e:
        logger.error(f"api_portfolio_history error: {str(e)}")
        return jsonify([])


# ---------------------------------------------------------------------------

@portfolio_bp.route("/api/staking/balance", methods=["GET"])
@login_required
def api_staking_balance():
    """Get user's staking balances from Binance.US API
    Doc: GET /sapi/v1/staking/stakingBalance
    Optional param: asset"""
    try:
        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            logger.warning("Binance API credentials not configured")
            return jsonify({'balances': [], 'totalStakedValue': 0})
        
        # Call Binance.US staking balance endpoint
        asset_param = request.args.get('asset')
        overview = build_staking_balance_view(cred, asset_param)
        logger.info(f"/api/staking/balance response summary: {overview.get('summary')}")
        return jsonify(overview)
    
    except Exception as e:
        logger.error(f"Error in api_staking_balance: {e}", exc_info=True)
        return jsonify({
            'balances': [],
            'activePositions': [],
            'pendingPositions': [],
            'pendingTransactions': [],
            'summary': {
                'activeCount': 0,
                'pendingCount': 0,
                'activeUsd': 0.0,
                'pendingUsd': 0.0,
                'totalUsd': 0.0
            },
            'totalStakedValue': 0.0
        })



@portfolio_bp.route("/api/true-portfolio-value")
@login_required
def api_true_portfolio_value():
    """Database-only portfolio value for instant loading"""
    logger.error(f"=== API_TRUE_PORTFOLIO_VALUE CALLED for user {current_user.id} (path: {request.full_path}) ===")
    logger.error(f"[DEBUG_PV] Headers: {dict(request.headers)}")
    try:
        total_value = compute_portfolio_total_value(
            current_user.id,
            username=getattr(current_user, "username", None)
        )
        result = {"total_value": round(total_value, 2)}
        logger.error(f"[JSON_DEBUG] Response for user {current_user.id}: {result}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"Database portfolio value error: {str(e)}")
        return jsonify({"total_value": 0.0})


@portfolio_bp.route('/api/account-summary')
@login_required
def api_account_summary():
    """Return dashboard totals by provider without exposing account identifiers."""
    try:
        all_accounts = float(compute_portfolio_total_value(
            current_user.id, username=getattr(current_user, 'username', None)
        ) or 0.0)
        webull = float(get_webull_total_value(current_user.id) or 0.0)
        # compute_portfolio_total_value includes the Webull account-level net value.
        binance = max(0.0, all_accounts - webull)
        return jsonify({
            'success': True,
            'totals': {
                'all': round(all_accounts, 2),
                'binance': round(binance, 2),
                'webull': round(webull, 2),
            },
        })
    except Exception as exc:
        logger.error('Account summary error: %s', exc, exc_info=True)
        return jsonify({'success': False, 'totals': {'all': 0.0, 'binance': 0.0, 'webull': 0.0}}), 500


@portfolio_bp.route("/api/true-portfolio-value-live")
@login_required
def api_true_portfolio_value_live():
    """Live portfolio value for background refresh using Binance data"""
    logger.error(f"=== API_TRUE_PORTFOLIO_VALUE_LIVE CALLED for user {current_user.id} ===")
    try:
        total_value = compute_portfolio_total_value(
            current_user.id,
            username=getattr(current_user, "username", None)
        )
        result = {"total_value": total_value}
        logger.error(f"[JSON_DEBUG] Live Response for user {current_user.id}: {result}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error getting live portfolio value: {e}")
        # Fallback to stored data
        coins = Coin.query.filter_by(user_id=current_user.id, hidden=False).all()
        total_value = sum((coin.amount or 0) * (coin.current or 0) for coin in coins)
        try:
            cred = get_user_credentials(current_user.username)
            staking_active, staking_pending = calculate_staking_value_for_user(cred, current_user.id)
            total_value += staking_active + staking_pending
        except Exception:
            pass
        return jsonify({"total_value": total_value})


@portfolio_bp.route("/portfolio")
@login_required
def portfolio_page():
    """Serve the portfolio page"""
    return serve_react_app()


@portfolio_bp.route("/api/check-trade-permission")
@login_required
def check_trade_permission():
    """Check if user's Binance API key has Spot Trading permissions.
    
    Uses GET /api/v3/account which returns canTrade: true when trading is enabled.
    Per Binance.US docs: https://docs.binance.us/
    """
    try:
        username = current_user.username
        logger.error(f"[TRADE_PERMISSION] Check requested for user: {username} (ID: {current_user.id})")
        cred = get_user_credentials(username)
        
        if not cred or not cred.api_key or not cred.api_secret:
            logger.error(f"[TRADE_PERMISSION] No API key configured for {username}")
            return jsonify({
                "has_api_key": False,
                "has_permission": False,
                "message": "No Binance API key configured."
            }), 200
        
        # IMPORTANT: /api/v3/account returns ACCOUNT capabilities, not API KEY restrictions!
        # canTrade=true just means the account TYPE supports trading, not that the API key has permission.
        # We need to test with an endpoint that requires trading permission to detect read-only keys.
        
        try:
            # Verify which API key we're using
            api_key_suffix = cred.api_key[-15:] if len(cred.api_key) > 15 else cred.api_key
            logger.error(f"[TRADE_PERMISSION] Testing API key permissions for {username} (key ends with: ...{api_key_suffix})")
            
            # IMPORTANT: /api/v3/openOrders doesn't respect API key restrictions (Binance bug)
            # Instead, try to place a TEST order which requires actual trading permission
            test_response = binance_us_api_call(
                cred,
                '/api/v3/order/test',
                method='POST',
                use_trading_keys=True,
                params_dict={
                    'symbol': 'BTCUSDT',
                    'side': 'BUY',
                    'type': 'LIMIT',
                    'timeInForce': 'GTC',
                    'quantity': '0.001',
                    'price': '10000'  # Very low price, won't execute
                }
            )
            
            logger.error(f"[TRADE_PERMISSION] Test order endpoint status: {test_response.status_code}")
            logger.error(f"[TRADE_PERMISSION] Test order response: {test_response.text[:200]}")
            
            if test_response.status_code == 200:
                # Successfully accessed trading endpoint - has permission
                logger.error(f"[TRADE_PERMISSION] ✅ {username} HAS trading permission (test order succeeded)")
                return jsonify({
                    "has_api_key": True,
                    "has_permission": True,
                    "message": ""
                }), 200
            else:
                # API returned an error (400, 401, 403, etc.)
                # Check if it's specifically a PERMISSION error
                error_code = None
                error_msg = f"API returned status {test_response.status_code}"
                try:
                    error_data = test_response.json()
                    error_code = error_data.get('code')
                    error_msg = error_data.get('msg', error_msg)
                except:
                    pass
                
                logger.warning(f"[TRADE_PERMISSION] Test order returned error {test_response.status_code}: code={error_code}, msg={error_msg}")

                # CRITICAL LOGIC: 
                # Error -2015 is "Invalid API-key, IP, or permissions for action" --> PERMISSION DENIED
                # Error -1013 is "Filter failure" --> PERMISSION GRANTED (but params bad)
                # Error -1022 is "Signature validation failed" --> PERMISSION UNKNOWN (assume OK)
                
                if error_code == -2015:
                    logger.error(f"[TRADE_PERMISSION] ❌ {username} DOES NOT have trading permission (error -2015)")
                    return jsonify({
                        "has_api_key": True,
                        "has_permission": False,
                        "message": "Spot Trading is not enabled for your API key."
                    }), 200
                else:
                    # Any other error means we passed the permission check but failed on params/balance/filters
                    # This implies the user DOES have trading permissions (or we can't tell, so give benefit of doubt)
                    logger.info(f"[TRADE_PERMISSION] ✅ {username} has permission (ignoring error {error_code}: {error_msg})")
                    return jsonify({
                        "has_api_key": True,
                        "has_permission": True,
                        "message": f"Trading permission verified (ignoring {error_msg})"
                    }), 200
                
        except Exception as api_err:
            logger.warning(f"Trade permission check failed: {api_err}")
            return jsonify({
                "has_api_key": True,
                "has_permission": False,
                "message": f"API key error: {str(api_err)}"
            }), 200
            
    except Exception as e:
        logger.error(f"Error checking trade permission: {e}")
        return jsonify({"has_api_key": False, "has_permission": False, "message": "Server error"}), 500


@portfolio_bp.route('/api/place-order', methods=['POST'])
@login_required
def api_place_order():
    """Place a trading order on Binance"""
    try:
        data = request.get_json()
        side = data.get('side')  # BUY or SELL
        symbol = data.get('symbol')  # e.g., 'BTCUSDT'
        order_type = data.get('order_type')  # MARKET, LIMIT
        quantity = data.get('quantity')
        price = data.get('price')  # Required for LIMIT orders
        
        if not all([side, symbol, order_type, quantity]):
            return jsonify({'success': False, 'error': 'Missing required fields'})
        
        # Get Binance credentials for the user
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({'success': False, 'error': 'Binance API credentials not configured'}), 401
        
        api_key = decrypt_secret(creds.api_key)
        api_secret = decrypt_secret(creds.api_secret)
        if not api_key or not api_secret:
            return jsonify({'success': False, 'error': 'Binance API credentials not configured'}), 401
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=api_key,
            api_secret=api_secret,
            tld='us'  # Use Binance.US
        )
        
        # Place order on Binance
        try:
            if order_type.upper() == 'MARKET':
                if side.upper() == 'BUY':
                    order = client.order_market_buy(
                        symbol=symbol,
                        quantity=quantity
                    )
                else:
                    order = client.order_market_sell(
                        symbol=symbol,
                        quantity=quantity
                    )
            elif order_type.upper() == 'LIMIT':
                if not price:
                    return jsonify({'success': False, 'error': 'Price required for limit orders'})
                
                if side.upper() == 'BUY':
                    order = client.order_limit_buy(
                        symbol=symbol,
                        quantity=quantity,
                        price=str(price)
                    )
                else:
                    order = client.order_limit_sell(
                        symbol=symbol,
                        quantity=quantity,
                        price=str(price)
                    )
            else:
                return jsonify({'success': False, 'error': f'Unsupported order type: {order_type}'})
            
            logger.info(f"Binance order placed successfully: {order['orderId']}")
            
            # Log the transaction to the logs database
            try:
                from trading_models import AllActivity
                
                # Extract base symbol from trading pair
                if symbol.endswith('USD') and not symbol.endswith('USDT'):
                    base_symbol = symbol[:-3]
                elif symbol.endswith('USDT'):
                    base_symbol = symbol[:-4]
                else:
                    base_symbol = symbol
                
                # Calculate proceeds and fees from order response
                executed_qty = float(order.get('executedQty', quantity))
                fills = order.get('fills', [])
                
                total_commission = 0.0
                avg_price = 0.0
                
                if fills:
                    total_price = sum(float(fill['price']) * float(fill['qty']) for fill in fills)
                    total_qty = sum(float(fill['qty']) for fill in fills)
                    avg_price = total_price / total_qty if total_qty > 0 else 0
                    total_commission = sum(float(fill['commission']) for fill in fills)
                else:
                    avg_price = float(order.get('price', price or 0))
                
                proceeds = executed_qty * avg_price
                
                # Create new activity using ORM
                new_activity = AllActivity(
                    date=datetime.utcnow(),
                    type=side.upper(),
                    asset=base_symbol.upper(),
                    amount=executed_qty if side.upper() == 'BUY' else -executed_qty,
                    proceeds=proceeds,
                    fee=total_commission,
                    txid=f"binance_{order['orderId']}",
                    status=order['status'],
                    details=f"Binance {order_type} order: {order['orderId']}",
                    avg_entry=avg_price,
                    user_id=current_user.id,
                    exchange='binance'
                )
                
                db.session.add(new_activity)
                db.session.commit()
                trigger_portfolio_snapshot(current_user.id, current_user.username)
                logger.info(f"Transaction logged to database: {base_symbol} {side}")
                
                # Update the portfolio to reflect the trade
                try:
                    # Get the executed quantity and price
                    executed_qty = float(order.get('executedQty', quantity))
                    avg_price = float(order.get('price', price or 0))
                    
                    # Update the coins table
                    if side.upper() == 'BUY':
                        # For buys, add to the existing amount or create a new entry
                        coin = Coin.query.filter_by(user_id=current_user.id, symbol=base_symbol).first()
                        if coin:
                            # Update existing coin
                            new_amount = coin.amount + executed_qty
                            new_avg_entry = ((coin.amount * coin.avg_entry) + (executed_qty * avg_price)) / new_amount
                            coin.amount = new_amount
                            coin.avg_entry = new_avg_entry
                            coin.auto_hidden = False  # Ensure coin is visible after buying
                        else:
                            # Create new coin entry
                            coin = Coin(
                                user_id=current_user.id,
                                symbol=base_symbol,
                                amount=executed_qty,
                                avg_entry=avg_price,
                                current=avg_price,
                                is_manual=False,
                                auto_hidden=False
                            )
                            db.session.add(coin)
                        
                        # Update USDT balance (subtract cost)
                        total_cost = executed_qty * avg_price
                        usdt_coin = Coin.query.filter_by(user_id=current_user.id, symbol='USDT').first()
                        if usdt_coin:
                            usdt_coin.amount -= total_cost
                    else:
                        # For sells, reduce the amount or remove the coin if fully sold
                        coin = Coin.query.filter_by(user_id=current_user.id, symbol=base_symbol).first()
                        if coin:
                            new_amount = coin.amount - executed_qty
                            if new_amount <= 0:
                                # Remove the coin if fully sold
                                db.session.delete(coin)
                            else:
                                coin.amount = new_amount
                            
                            # Update USDT balance (add proceeds)
                            total_proceeds = executed_qty * avg_price
                            usdt_coin = Coin.query.filter_by(user_id=current_user.id, symbol='USDT').first()
                            if usdt_coin:
                                usdt_coin.amount += total_proceeds
                            else:
                                usdt_coin = Coin(
                                    user_id=current_user.id,
                                    symbol='USDT',
                                    amount=total_proceeds,
                                    avg_entry=1.0,
                                    current=1.0,
                                    is_manual=False
                                )
                                db.session.add(usdt_coin)
                    
                    db.session.commit()
                    logger.info(f"Portfolio updated for {base_symbol} {side} order")
                    
                except Exception as update_error:
                    logger.error(f"Failed to update portfolio: {update_error}")
                    # Don't fail the entire request, just log the error
                
            except Exception as log_e:
                logger.error(f"Failed to log transaction: {log_e}")
            
            try:
                status = order.get('status', 'NEW')
                executed_qty_val = float(order.get('executedQty', quantity or 0))
                if status == 'FILLED':
                    fill_price_val = avg_price if avg_price > 0 else float(price or 0)
                    total_proceeds_val = proceeds if proceeds > 0 else (executed_qty_val * fill_price_val)
                    msg = f"✅ ORDER FILLED: {side.upper()} {executed_qty_val} {base_symbol}\nPrice: ${fill_price_val:.4f}\nTotal: ${total_proceeds_val:.2f}"
                    send_telegram_message(current_user.username, msg)
                    create_system_notification(
                        user_id_or_name=current_user.id,
                        category='order_filled',
                        symbol=base_symbol,
                        message=f"Filled {side.upper()} {executed_qty_val} {base_symbol} @ ${fill_price_val:.4f} (Total: ${total_proceeds_val:.2f})",
                        current_price=fill_price_val,
                        direction='buy' if side.upper() == 'BUY' else 'sell'
                    )
                elif status == 'NEW':
                    create_system_notification(
                        user_id_or_name=current_user.id,
                        category='order_placed',
                        symbol=base_symbol,
                        message=f"Placed {side.upper()} {quantity} {base_symbol} {order_type.upper()} order" + (f" @ ${price}" if price else ""),
                        current_price=float(price or avg_price or 0.0),
                        direction='buy' if side.upper() == 'BUY' else 'sell'
                    )
            except Exception as notif_err:
                logger.warning(f"Failed to send order notification: {notif_err}")

            return jsonify({
                'success': True,
                'order_id': order['orderId'],
                'status': order['status'],
                'executed_qty': order.get('executedQty', '0'),
                'message': f'Order placed successfully on Binance',
                'portfolio_updated': True
            })
            
        except Exception as binance_e:
            logger.error(f"Binance order failed: {binance_e}")
            return jsonify({
                'success': False,
                'error': f'Order placement failed: {str(binance_e)}'
            }), 500
        
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500


@portfolio_bp.route('/api/sync-portfolio', methods=['POST'])
@login_required
def api_sync_portfolio():
    """Manually sync portfolio data from Binance"""
    try:
        # First sync balances from Binance
        success, message = sync_portfolio_from_binance(current_user.id)
        if not success:
            return jsonify({'success': False, 'error': message}), 500
            
        # Then update all coin prices
        update_all_coin_prices_from_binance(current_user.id)
        
        logger.info(f"Manual portfolio sync completed for user {current_user.id}")
        return jsonify({
            'success': True, 
            'message': message + ' and updated all prices'
        })
    except Exception as e:
        logger.error(f"Manual portfolio sync failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/orders')
@login_required
def api_orders():
    """Get order history from Binance with robust error handling"""
    import traceback
    try:
        # Get Binance credentials from database
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        if not creds:
            logger.warning(f"No Binance credentials found for user {current_user.username}")
            return jsonify({
                'orders': [],
                'message': 'No Binance credentials found',
                'error_code': 'missing_binance_credentials'
            }), 400
        api_key = decrypt_secret(creds.api_key)
        api_secret = decrypt_secret(creds.api_secret)
        if not api_key or not api_secret:
            logger.warning(f"No Binance credentials found for user {current_user.username}")
            return jsonify({
                'orders': [],
                'message': 'No Binance credentials found',
                'error_code': 'missing_binance_credentials'
            }), 400
        # Initialize Binance client
        try:
            from binance.client import Client
            client = Client(
                api_key=api_key,
                api_secret=api_secret,
                testnet=False,
                tld='us'
            )
        except Exception as e:
            logger.error(f"Failed to initialize Binance client: {e}\n{traceback.format_exc()}")
            return jsonify({'orders': [], 'message': f'Failed to initialize Binance client: {str(e)}'}), 502
        # Get all orders for all symbols
        orders = []
        try:
            account = client.get_account()
            traded_symbols = set()
            for balance in account['balances']:
                try:
                    asset = balance['asset']
                    # Only add valid crypto assets (skip fiat, dust, etc.)
                    if not asset or asset in ('USD', 'USDT', 'BUSD', 'USDC', 'EUR', 'GBP', 'TRY', 'AUD', 'BRL', 'RUB', 'IDRT', 'NGN', 'UAH', 'ZAR', 'DAI', 'PAX', 'TUSD', 'USDP', 'SUSD', 'GUSD', 'VAI', 'UST', 'EURS', 'BIDR', 'BVND', 'FDUSD', 'TRXUP', 'TRXDOWN'):
                        continue
                    if float(balance['free']) > 0 or float(balance['locked']) > 0:
                        symbol = asset + 'USDT'
                        traded_symbols.add(symbol)
                except Exception as e:
                    logger.warning(f"Error processing balance entry: {e}")
                    continue
            limited_symbols = list(traded_symbols)[:5]
            for symbol in limited_symbols:
                try:
                    symbol_orders = client.get_all_orders(symbol=symbol, limit=20)
                    for order in symbol_orders:
                        orders.append({
                            'order_id': order.get('orderId'),
                            'symbol': order.get('symbol'),
                            'side': order.get('side'),
                            'type': order.get('type'),
                            'quantity': order.get('origQty'),
                            'price': order.get('price'),
                            'status': order.get('status'),
                            'time': order.get('time'),
                            'executed_quantity': order.get('executedQty')
                        })
                except Exception as e:
                    if "Too much request weight" in str(e) or "rate limit" in str(e).lower():
                        logger.warning(f"Rate limit hit while fetching orders for {symbol}")
                        break
                    else:
                        logger.warning(f"Failed to get orders for {symbol}: {e}")
                    continue
            orders.sort(key=lambda x: x['time'] if x['time'] is not None else 0, reverse=True)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error fetching Binance orders: {e}\n{traceback.format_exc()}")
            if "Too much request weight" in error_msg or "rate limit" in error_msg.lower():
                return jsonify({
                    'orders': [],
                    'message': 'Rate limit reached. Please wait a moment before refreshing orders.',
                    'rate_limited': True
                }), 429
            elif "API-key" in error_msg or "Invalid API-key" in error_msg or "permissions" in error_msg:
                return jsonify({
                    'orders': [],
                    'message': 'Invalid Binance API key or permissions. Please check your credentials.',
                    'error_code': 'invalid_binance_credentials'
                }), 400
            elif "Service unavailable" in error_msg or "restricted location" in error_msg:
                return jsonify({'orders': [], 'message': 'Binance.US service unavailable or restricted in your location.'}), 503
            else:
                return jsonify({'orders': [], 'message': f'Error fetching orders: {str(e)}'}), 502
        return jsonify({'orders': orders[:50]})
    except Exception as e:
        logger.error(f"Error in api_orders: {e}\n{traceback.format_exc()}")
        return jsonify({'orders': [], 'message': f'Internal server error: {str(e)}'}), 500



@portfolio_bp.route('/api/transaction-history')
@login_required  
def api_transaction_history():
    """Get transaction history from Binance"""
    try:
        # Return empty for now - can be implemented later if needed
        return jsonify({'transactions': []})
    except Exception as e:
        logger.error(f"Transaction history error: {str(e)}")
        return jsonify({'transactions': [], 'message': 'Unable to fetch transactions'})



@portfolio_bp.route('/api/pending-orders')
@login_required
def api_pending_orders():
    """Get all pending (open) orders from Binance.US for portfolio highlighting"""
    import traceback
    try:
        # Get Binance credentials from database
        # Get Binance credentials from database
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            logger.warning(f"No Binance credentials found for user {current_user.username}")
            return jsonify({
                'pending_orders': [],
                'message': 'No Binance credentials found',
                'error_code': 'missing_binance_credentials'
            }), 400
        api_key = decrypt_secret(creds.api_key)
        api_secret = decrypt_secret(creds.api_secret)
        if not api_key or not api_secret:
            logger.warning(f"No Binance credentials found for user {current_user.username}")
            return jsonify({
                'pending_orders': [],
                'message': 'No Binance credentials found',
                'error_code': 'missing_binance_credentials'
            }), 400
        
        # Initialize Binance client
        try:
            from binance.client import Client
            client = Client(
                api_key=api_key,
                api_secret=api_secret,
                testnet=False,
                tld='us'
            )
        except Exception as e:
            logger.error(f"Failed to initialize Binance client: {e}\n{traceback.format_exc()}")
            return jsonify({'pending_orders': [], 'message': f'Failed to initialize Binance client: {str(e)}'}), 502
        
        # Fetch all open orders (no symbol filter = get all)
        try:
            open_orders = client.get_open_orders()
            
            # Parse and format orders for frontend
            pending_orders = []
            pending_buy_assets = {}
            for order in open_orders:
                symbol = order.get('symbol', '')
                # Extract asset from symbol (remove USDT or USD suffix)
                asset = symbol.replace('USDT', '').replace('USD', '')
                
                order_type = order.get('type', 'LIMIT')
                side = order.get('side', '')  # BUY or SELL
                price = float(order.get('price', 0))
                stop_price = float(order.get('stopPrice', 0)) if order.get('stopPrice') else None
                quantity = float(order.get('origQty', 0))
                
                # Determine order direction text
                if side == 'SELL':
                    if stop_price:
                        # Stop-limit sell: triggers when price drops below stop price
                        direction = 'drops below'
                        trigger_price = stop_price
                    else:
                        # Regular limit sell: executes when price rises to limit price
                        direction = 'rises above'
                        trigger_price = price
                else:  # BUY
                    if stop_price:
                        direction = 'rises above'
                        trigger_price = stop_price
                    else:
                        direction = 'drops below'
                        trigger_price = price
                
                # Check if this is an OCO order (has both stop and limit)
                is_oco = order.get('type') == 'STOP_LOSS_LIMIT' and order.get('stopPrice') and order.get('price')
                quote_amount = quantity * (trigger_price or price or 0.0)
                asset_upper = asset.upper()
                ref_price = trigger_price or price or 0.0
                if asset_upper and side == 'BUY':
                    pending_buy_assets[asset_upper] = max(pending_buy_assets.get(asset_upper, 0.0), ref_price)
                
                pending_orders.append({
                    'order_id': order.get('orderId'),
                    'symbol': symbol,
                    'asset': asset,
                    'side': side,
                    'type': order_type,
                    'price': price,
                    'stop_price': stop_price,
                    'quantity': quantity,
                    'status': 'ACTIVE' if order.get('status') in ['NEW', 'PARTIALLY_FILLED', 'ACTIVE'] else order.get('status'),
                    'time': order.get('time'),
                    'is_oco': is_oco,
                    'direction': direction,
                    'trigger_price': trigger_price,
                    'quantity_usdt': quote_amount
                })
            
            coin_updates = False
            # An unfilled BUY is a watch target, not a portfolio position. This
            # also captures BUY orders created directly on Binance.US.
            for asset_symbol, price_hint in pending_buy_assets.items():
                coin = Coin.query.filter_by(user_id=current_user.id, symbol=asset_symbol).first()
                if coin and float(coin.amount or 0) >= 0.0001:
                    continue

                watch = WatchlistCoin.query.filter_by(user_id=current_user.id, symbol=asset_symbol).first()
                if watch:
                    if watch.hidden:
                        watch.hidden = False
                        coin_updates = True
                    if price_hint and (not watch.current_price or watch.current_price == 0):
                        watch.current_price = price_hint
                        coin_updates = True
                else:
                    db.session.add(WatchlistCoin(
                        user_id=current_user.id,
                        symbol=asset_symbol,
                        current_price=price_hint or 0.0,
                        hidden=False,
                        alert_enabled=False,
                        action='Watch',
                        sentiment='Watch'
                    ))
                    coin_updates = True

            # A zero/dust Coin record may exist from older versions. Never let
            # it surface as a pending-order Portfolio row; the Watchlist above
            # is the home for an unfilled BUY instead.
            all_user_coins = Coin.query.filter_by(user_id=current_user.id).all()
            for c in all_user_coins:
                if float(c.amount or 0) < 0.0001:
                    if c.force_visible or not c.hidden:
                        c.force_visible = False
                        c.hidden = True
                        c.auto_hidden = True
                        c.alert_enabled = False
                        c.auto_sell_enabled = False
                        c.auto_buy_enabled = False
                        coin_updates = True

            if coin_updates:
                db.session.commit()

            logger.info(f"Retrieved {len(pending_orders)} pending orders for user {current_user.username}")
            return jsonify({'pending_orders': pending_orders})
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error fetching pending orders: {e}\n{traceback.format_exc()}")
            
            if "Too much request weight" in error_msg or "rate limit" in error_msg.lower():
                return jsonify({
                    'pending_orders': [],
                    'message': 'Rate limit reached. Please wait before refreshing.',
                    'rate_limited': True
                }), 429
            elif "API-key" in error_msg or "Invalid API-key" in error_msg:
                return jsonify({
                    'pending_orders': [],
                    'message': 'Invalid Binance API credentials',
                    'error_code': 'invalid_binance_credentials'
                }), 400
            else:
                return jsonify({'pending_orders': [], 'message': f'Error: {str(e)}'}), 502
                
    except Exception as e:
        logger.error(f"Error in api_pending_orders: {e}\n{traceback.format_exc()}")
        return jsonify({'pending_orders': [], 'message': f'Internal error: {str(e)}'}), 500



@portfolio_bp.route('/api/portfolio-analysis')
@login_required
def api_portfolio_analysis():
    """Get AI-powered portfolio analysis"""
    try:
        # Get current portfolio data
        coins = Coin.query.filter_by(user_id=current_user.id, hidden=False).all()
        
        if not coins:
            return jsonify({
                'total_value': 0,
                'holdings_count': 0,
                'diversification_score': 0,
                'risk_level': 'Low',
                'recommendations': ['No holdings found']
            })
        
        total_value = 0
        holdings = []
        
        for coin in coins:
            current_price = fetch_binance_price(coin.symbol)
            value = coin.amount * current_price
            total_value += value
            
            holdings.append({
                'symbol': coin.symbol,
                'amount': coin.amount,
                'value': value,
                'price': current_price
            })
        
        # Calculate diversification score
        if total_value > 0:
            weights = [h['value'] / total_value for h in holdings]
            diversification_score = min(100, int(100 * (1 - sum(w**2 for w in weights))))
        else:
            diversification_score = 0
        
        # Determine risk level
        if total_value > 10000:
            risk_level = 'High'
        elif total_value > 5000:
            risk_level = 'Medium'
        else:
            risk_level = 'Low'
        
        # Generate recommendations
        recommendations = []
        if diversification_score < 50:
            recommendations.append("Consider diversifying your portfolio across more assets")
        if len(holdings) < 3:
            recommendations.append("Consider adding more assets to reduce concentration risk")
        if total_value > 10000:
            recommendations.append("Consider implementing stop-loss orders for risk management")
        
        return jsonify({
            'total_value': total_value,
            'holdings_count': len(holdings),
            'diversification_score': diversification_score,
            'risk_level': risk_level,
            'recommendations': recommendations
        })
    except Exception as e:
        logger.error(f"Portfolio analysis error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@portfolio_bp.route('/api/cancel-order/<order_id>', methods=['POST'])
@login_required
def api_cancel_order(order_id):
    """Cancel an existing Binance order with optional 2FA verification"""
    try:
        data = request.get_json() or {}
        symbol = (data.get('symbol') or '').upper()
        two_factor_code = (data.get('two_factor_code') or '').strip()

        if not symbol:
            return jsonify({'error': 'Symbol is required for order cancellation'}), 400

        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if settings and settings.require_2fa and settings.totp_secret:
            if not two_factor_code:
                return jsonify({'error': 'Two-factor code is required', 'requires_2fa': True}), 400
            try:
                import pyotp
                totp = pyotp.TOTP(settings.totp_secret)
                if not totp.verify(two_factor_code, valid_window=1):
                    return jsonify({'error': 'Invalid two-factor code', 'requires_2fa': True}), 400
            except Exception as totp_err:
                logger.error(f"2FA verification failed: {totp_err}")
                return jsonify({'error': 'Two-factor verification failed', 'requires_2fa': True}), 400

        # Use SQLAlchemy ORM instead of direct SQLite
        creds = Credential.query.filter_by(user_id=current_user.id).first()

        if not creds:
            return jsonify({
                'error': 'No Binance credentials found',
                'error_code': 'missing_trading_credentials'
            }), 400

        # Credential model properties auto-decrypt values
        trading_api_key = creds.trading_api_key
        trading_api_secret = creds.trading_api_secret
        portfolio_api_key = creds.api_key
        portfolio_api_secret = creds.api_secret

        api_key = trading_api_key or portfolio_api_key
        api_secret = trading_api_secret or portfolio_api_secret

        if not api_key or not api_secret:
            return jsonify({
                'error': 'Binance trading credentials are incomplete',
                'error_code': 'missing_trading_credentials'
            }), 400

        from binance.client import Client
        client = Client(
            api_key=api_key,
            api_secret=api_secret,
            testnet=False,
            tld='us'
        )

        try:
            result = client.cancel_order(symbol=symbol, orderId=int(order_id))

            try:
                order_record = RealOrder.query.filter(
                    RealOrder.user_id == current_user.id,
                    RealOrder.binance_order_id == int(order_id)
                ).first()

                if order_record:
                    order_record.status = result.get('status', 'CANCELED')
                    order_record.canceled_at = datetime.utcnow()
                    order_record.updated_at = datetime.utcnow()
                    db.session.commit()
            except Exception as db_err:
                logger.warning(f"Failed to update local order after cancellation: {db_err}")
                db.session.rollback()

            # Auto-hide zero-balance coins when all their open orders are canceled
            try:
                base_asset = symbol.replace('USDT', '').replace('USD', '').upper()
                coin_rec = Coin.query.filter_by(user_id=current_user.id, symbol=base_asset).first()
                if coin_rec and float(coin_rec.amount or 0) <= 0.00000001:
                    try:
                        open_orders = client.get_open_orders()
                        has_other = any(
                            o.get('symbol', '').upper().startswith(base_asset) and int(o.get('orderId', 0)) != int(order_id)
                            for o in open_orders
                        )
                    except Exception:
                        has_other = False
                    if not has_other:
                        coin_rec.force_visible = False
                        coin_rec.hidden = True
                        coin_rec.auto_hidden = True
                        coin_rec.alert_enabled = False
                        coin_rec.auto_sell_enabled = False
                        coin_rec.auto_buy_enabled = False
                        db.session.commit()
            except Exception as hide_err:
                logger.warning(f"Failed to auto-hide zero balance coin after cancel: {hide_err}")

            try:
                msg = f"🚫 ORDER CANCELED: {symbol} (Order ID: {order_id})"
                send_telegram_message(current_user.username, msg)
                create_system_notification(
                    user_id_or_name=current_user.id,
                    category='order_canceled',
                    symbol=symbol,
                    message=f"Order {order_id} for {symbol} has been canceled."
                )
            except Exception as cancel_notif_err:
                logger.warning(f"Failed to send cancellation notification: {cancel_notif_err}")

            return jsonify({
                'success': True,
                'message': 'Order cancelled successfully',
                'order_id': result.get('orderId'),
                'symbol': result.get('symbol'),
                'status': result.get('status')
            })
        except Exception as e:
            logger.error(f"Failed to cancel Binance order {order_id}: {e}")
            return jsonify({'error': f'Failed to cancel order: {str(e)}'}), 400

    except Exception as e:
        logger.error(f"Cancel order error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/order-status/<order_id>')
@login_required
def api_order_status(order_id):
    """Get detailed status of a specific Binance order"""
    try:
        # Get Binance credentials
        # Get Binance credentials
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({
                'error': 'No Binance credentials found',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        api_key = decrypt_secret(creds.api_key)
        api_secret = decrypt_secret(creds.api_secret)
        if not api_key or not api_secret:
            return jsonify({
                'error': 'No Binance credentials found',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=api_key,
            api_secret=api_secret,
            testnet=False,
            tld='us'
        )
        
        # Get symbol from query parameters
        symbol = request.args.get('symbol')
        if not symbol:
            return jsonify({'error': 'Symbol parameter is required'}), 400
        
        # Get order status
        try:
            order = client.get_order(symbol=symbol, orderId=int(order_id))
            return jsonify({
                'order_id': order.get('orderId'),
                'symbol': order.get('symbol'),
                'status': order.get('status'),
                'side': order.get('side'),
                'type': order.get('type'),
                'quantity': order.get('origQty'),
                'executed_quantity': order.get('executedQty'),
                'price': order.get('price'),
                'time': order.get('time')
            })
        except Exception as e:
            logger.error(f"Failed to get Binance order status {order_id}: {e}")
            return jsonify({'error': f'Failed to get order status: {str(e)}'}), 400
            
    except Exception as e:
        logger.error(f"Order status error: {str(e)}")
        return jsonify({'error': str(e)}), 500



# ========================================
# TRADING SYSTEM ENDPOINTS (Binance.US)
# ========================================

@portfolio_bp.route('/api/trading/settings', methods=['GET'])
@login_required
def get_trading_settings():
    """Get trading settings for current user"""
    try:
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        
        if not settings:
            # Create default settings
            settings = TradingSettings(
                user_id=current_user.id,
                test_mode_enabled=True,
                max_order_size_usd=1000.0,
                require_2fa=False
            )
            db.session.add(settings)
            db.session.commit()
        
        return jsonify({
            'success': True,
            'settings': settings.to_dict()
        })
    except Exception as e:
        logger.error(f"Error fetching trading settings: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/trading/settings', methods=['POST'])
@login_required
def update_trading_settings():
    """Update trading settings for current user"""
    try:
        data = request.get_json()
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        
        if not settings:
            settings = TradingSettings(user_id=current_user.id)
            db.session.add(settings)
        
        # Update settings
        if 'test_mode_enabled' in data:
            settings.test_mode_enabled = bool(data['test_mode_enabled'])
        if 'max_order_size_usd' in data:
            settings.max_order_size_usd = float(data['max_order_size_usd'])
        if 'daily_loss_limit_usd' in data:
            settings.daily_loss_limit_usd = float(data['daily_loss_limit_usd'])
        if 'require_2fa' in data:
            settings.require_2fa = bool(data['require_2fa'])
        
        settings.updated_at = datetime.utcnow()
        db.session.commit()
        
        logger.info(f"Updated trading settings for user {current_user.id}")
        return jsonify({
            'success': True,
            'settings': settings.to_dict()
        })
    except Exception as e:
        logger.error(f"Error updating trading settings: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/trading/order-types', methods=['GET'])
def get_trading_order_types():
    """Get canonical list of supported Binance.US spot order types and TimeInForce options.
    
    Optional query param: ?symbol=XRPUSDT
    When provided, filters the canonical list to only include order types
    that Binance.US actually supports for that specific trading pair.
    """
    try:
        # Canonical Binance.US spot order types (authoritative source)
        all_order_types = [
            {
                'value': 'MARKET',
                'label': 'Market Order',
                'description': 'Execute immediately at current market price',
                'requires_price': False,
                'requires_stop_price': False,
                'requires_time_in_force': False
            },
            {
                'value': 'LIMIT',
                'label': 'Limit Order',
                'description': 'Execute at specified price or better',
                'requires_price': True,
                'requires_stop_price': False,
                'requires_time_in_force': True
            },
            {
                'value': 'STOP_LOSS',
                'label': 'Stop Loss',
                'description': 'Market order triggered when price reaches stop price',
                'requires_price': False,
                'requires_stop_price': True,
                'requires_time_in_force': False
            },
            {
                'value': 'STOP_LOSS_LIMIT',
                'label': 'Stop Loss Limit',
                'description': 'Limit order triggered at stop price',
                'requires_price': True,
                'requires_stop_price': True,
                'requires_time_in_force': True
            },
            {
                'value': 'TAKE_PROFIT',
                'label': 'Take Profit',
                'description': 'Market order to secure profits at target price',
                'requires_price': False,
                'requires_stop_price': True,
                'requires_time_in_force': False
            },
            {
                'value': 'TAKE_PROFIT_LIMIT',
                'label': 'Take Profit Limit',
                'description': 'Limit order to secure profits',
                'requires_price': True,
                'requires_stop_price': True,
                'requires_time_in_force': True
            },
            {
                'value': 'LIMIT_MAKER',
                'label': 'Limit Maker',
                'description': 'Post-only limit order (maker fee only)',
                'requires_price': True,
                'requires_stop_price': False,
                'requires_time_in_force': True
            },
            {
                'value': 'OCO',
                'label': 'OCO (One-Cancels-Other)',
                'description': 'Combine limit and stop-loss orders - when one executes, the other cancels',
                'requires_price': True,
                'requires_stop_price': True,
                'requires_time_in_force': False,
                'requires_stop_limit_price': True
            }
        ]
        
        # If a symbol is provided, filter to only the order types Binance.US supports for it
        symbol = request.args.get('symbol', '').strip().upper()
        order_types = all_order_types
        
        if symbol:
            try:
                from binance.client import Client
                from credential_security import decrypt_secret
                import os
                from dotenv import load_dotenv
                load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
                
                api_key = os.getenv('BINANCE_API_KEY')
                api_secret = os.getenv('BINANCE_API_SECRET')
                
                if api_key and api_secret:
                    client = Client(api_key=api_key, api_secret=api_secret, testnet=False, tld='us')
                    exchange_info = get_cached_exchange_info(client)
                    
                    if exchange_info:
                        for sym_info in exchange_info.get('symbols', []):
                            if sym_info['symbol'] == symbol:
                                allowed_types = set(sym_info.get('orderTypes', []))
                                if sym_info.get('ocoAllowed', False) or 'STOP_LOSS_LIMIT' in allowed_types:
                                    allowed_types.add('OCO')
                                order_types = [ot for ot in all_order_types if ot['value'] in allowed_types]
                                logger.info(f"Filtered order types for {symbol}: {[ot['value'] for ot in order_types]}")
                                break
                        else:
                            logger.warning(f"Symbol {symbol} not found in exchange info, returning all order types")
            except Exception as filter_err:
                logger.warning(f"Could not filter order types for {symbol}, returning all: {filter_err}")
        
        # TimeInForce options for limit orders
        time_in_force_options = [
            {
                'value': 'GTC',
                'label': 'GTC - Good Till Cancel',
                'description': 'Order remains active until filled or cancelled'
            },
            {
                'value': 'IOC',
                'label': 'IOC - Immediate or Cancel',
                'description': 'Immediately execute as much as possible, cancel remainder'
            },
            {
                'value': 'FOK',
                'label': 'FOK - Fill or Kill',
                'description': 'Must fill entire order immediately or cancel'
            }
        ]
        
        return jsonify({
            'success': True,
            'order_types': order_types,
            'time_in_force_options': time_in_force_options
        })
        
    except Exception as e:
        logger.error(f"Error fetching order types: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def _fetch_yfinance_klines(symbol, interval='1h', limit=1000):
    """Fallback candlestick provider for equities, ETFs, and non-Binance pairs."""
    try:
        import yfinance as yf
        clean_sym = symbol.replace('USDT', '').replace('USD', '').strip().upper()
        if not clean_sym:
            return None
        yf_interval_map = {
            '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m',
            '1h': '1h', '2h': '1h', '4h': '1h', '6h': '1h', '8h': '1h', '12h': '1h',
            '1d': '1d', '3d': '1d', '1w': '1wk', '1M': '1mo',
        }
        yf_interval = yf_interval_map.get(interval, '1d')
        period_map = {'1m': '7d', '5m': '60d', '15m': '60d', '30m': '60d', '1h': '730d'}
        period = period_map.get(yf_interval, '2y')
        ticker = yf.Ticker(clean_sym)
        df = ticker.history(period=period, interval=yf_interval)
        if df is None or df.empty:
            return None
        formatted = []
        for idx, row in df.iterrows():
            formatted.append({
                'time': int(idx.timestamp()),
                'open': float(row['Open']),
                'high': float(row['High']),
                'low': float(row['Low']),
                'close': float(row['Close']),
                'volume': float(row['Volume']),
            })
        if limit and len(formatted) > limit:
            formatted = formatted[-limit:]
        return formatted
    except Exception as exc:
        logger.warning(f"yfinance klines lookup failed for {symbol}: {exc}")
        return None


@portfolio_bp.route('/api/trading/klines/<symbol>', methods=['GET'])
def get_trading_klines(symbol):
    """
    Proxy endpoint for Binance.US klines/candlestick data with caching and yfinance fallback.
    Query params: interval (default: 1d), limit (default: 1000)
    """
    try:
        symbol = symbol.upper()
        interval = request.args.get('interval', '1d')  # 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1M
        limit = int(request.args.get('limit', 1000))  # Max 1000 per Binance API
        
        # Check cache
        cache_key = f"{symbol}_{interval}_{limit}"
        now = time.time()
        if cache_key in _KLINES_CACHE:
            cached_data, cached_time = _KLINES_CACHE[cache_key]
            if now - cached_time < _KLINES_CACHE_TTL:
                logger.debug(f"Returning cached klines for {cache_key}")
                return jsonify({
                    'success': True,
                    'symbol': symbol,
                    'interval': interval,
                    'klines': cached_data,
                    'cached': True
                })
        
        # Get Binance.US credentials (use portfolio API keys for read-only price data)
        creds = Credential.query.filter(
            Credential._api_key.isnot(None), 
            Credential._api_secret.isnot(None)
        ).first()
        
        api_key = decrypt_secret(creds.api_key) if creds else None
        api_secret = decrypt_secret(creds.api_secret) if creds else None
        
        if not api_key or not api_secret:
            # Fallback to yfinance if Binance credentials are not configured
            yf_klines = _fetch_yfinance_klines(symbol, interval, limit)
            if yf_klines:
                _KLINES_CACHE[cache_key] = (yf_klines, now)
                return jsonify({
                    'success': True,
                    'symbol': symbol,
                    'interval': interval,
                    'klines': yf_klines,
                    'source': 'yfinance'
                })
            return jsonify({
                'success': False,
                'error': 'No Binance.US credentials found.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=api_key,
            api_secret=api_secret,
            testnet=False,
            tld='us'
        )
        
        # Fetch klines from Binance.US
        candidate_symbols = [symbol]
        if not symbol.endswith('USDT') and not symbol.endswith('USD'):
            candidate_symbols.extend([f"{symbol}USDT", f"{symbol}USD"])

        klines = None
        last_err = None
        for sym_try in candidate_symbols:
            try:
                klines = client.get_klines(symbol=sym_try, interval=interval, limit=limit)
                if klines:
                    symbol = sym_try
                    break
            except Exception as api_err:
                last_err = api_err

        if not klines:
            # Fallback to yfinance for equities / ETFs / non-Binance symbols
            yf_klines = _fetch_yfinance_klines(symbol, interval, limit)
            if yf_klines:
                _KLINES_CACHE[cache_key] = (yf_klines, now)
                return jsonify({
                    'success': True,
                    'symbol': symbol,
                    'interval': interval,
                    'klines': yf_klines,
                    'source': 'yfinance'
                })

            err_msg = str(last_err)
            logger.error(f"Failed to fetch klines for {symbol}: {err_msg}")
            if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
                return jsonify({
                    'success': False,
                    'error': 'Invalid Binance API credentials',
                    'error_code': 'invalid_trading_credentials'
                }), 400
            return jsonify({'success': False, 'error': f'Failed to fetch market data: {err_msg}'}), 502
        
        # Transform to frontend-friendly format
        formatted_klines = []
        for k in klines:
            formatted_klines.append({
                'time': int(k[0]) / 1000,  # Convert to seconds for Lightweight Charts
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5])
            })
        
        # Cache the result
        _KLINES_CACHE[cache_key] = (formatted_klines, now)
        
        logger.info(f"Fetched {len(formatted_klines)} klines for {symbol} ({interval})")
        return jsonify({
            'success': True,
            'symbol': symbol,
            'interval': interval,
            'klines': formatted_klines,
            'cached': False
        })
        
    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error fetching klines for {symbol}: {err_msg}")
        if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
            return jsonify({
                'success': False,
                'error': 'Invalid Binance API credentials',
                'error_code': 'invalid_trading_credentials'
            }), 400
        return jsonify({'success': False, 'error': err_msg}), 500



@portfolio_bp.route('/api/trading/transactions/<symbol>', methods=['GET'])
@login_required
def get_trading_transactions(symbol):
    """
    Get user's buy/sell transactions for a specific symbol to display on chart.
    Returns list of transactions with timestamps for chart markers.
    """
    try:
        base_asset = symbol.replace('USDT', '').replace('USD', '').upper()
        transactions = []
        from trading_models import AllActivity
        
        from flask import request
        all_coins = request.args.get('all_coins', 'false').lower() == 'true'
        
        # Query all_activities using ORM
        query = AllActivity.query.filter(
            AllActivity.user_id == current_user.id,
            AllActivity.type.in_(['BUY', 'SELL']),
            AllActivity.exchange == 'binance'
        )
        
        if not all_coins:
            query = query.filter(AllActivity.asset == base_asset)
            
        rows = query.order_by(AllActivity.date.asc()).all()

        for row in rows:
            try:
                date_text = row.date
                # Try common formats
                if isinstance(date_text, datetime):
                    date_obj = date_text
                else:
                    try:
                        date_obj = datetime.strptime(date_text, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        # Fallback: attempt ISO format
                        try:
                            date_obj = datetime.fromisoformat(date_text.replace('Z', '+00:00'))
                        except Exception:
                            logger.warning(f"Unrecognized date format in all_activities: {date_text}")
                            continue
                
                timestamp = int(date_obj.timestamp())

                price_value = None
                if row.avg_entry is not None:
                    price_value = float(row.avg_entry)
                elif row.price_sold_at is not None:
                    price_value = float(row.price_sold_at)
                else:
                    # Skip if no price available
                    continue

                transactions.append({
                    'time': timestamp,
                    'type': row.type,
                    'amount': abs(float(row.amount)) if row.amount is not None else 0.0,
                    'price': price_value,
                    'asset': row.asset
                })
            except Exception as parse_err:
                logger.warning(f"Failed to parse transaction row: {parse_err}")
                continue

        logger.info(f"Retrieved {len(transactions)} transactions for {base_asset}")
        return jsonify({
            'success': True,
            'symbol': base_asset,
            'transactions': transactions
        })
        
    except Exception as e:
        logger.error(f"Error fetching transactions for {symbol}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/trading/symbol-info/<symbol>', methods=['GET'])
@login_required
def get_symbol_info(symbol):
    """Get trading rules and filters for a specific symbol"""
    try:
        symbol = symbol.upper()
        
        # Get Binance.US Trading credentials
        # Get Binance.US credentials
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        trading_api_key = decrypt_secret(creds.trading_api_key)
        trading_api_secret = decrypt_secret(creds.trading_api_secret)
        if not trading_api_key or not trading_api_secret:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=trading_api_key,
            api_secret=trading_api_secret,
            testnet=False,
            tld='us'
        )
        
        # Get symbol filters
        filters = get_symbol_filters(client, symbol)
        if not filters:
            return jsonify({'success': False, 'error': f'Symbol {symbol} not found or not available for trading.'}), 404
        
        return jsonify({
            'success': True,
            'symbol': symbol,
            'filters': filters
        })
        
    except Exception as e:
        logger.error(f"Error getting symbol info: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/trading/test-order', methods=['POST'])
@login_required
def place_test_order():
    """Place a test order (validates with Binance.US but doesn't execute)"""
    import traceback
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['symbol', 'side', 'type']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
        has_quantity = bool(data.get('quantity'))
        has_quote = bool(data.get('quoteQuantity') or data.get('quote_quantity') or data.get('quote_amount'))
        if not has_quantity and not has_quote:
            return jsonify({'success': False, 'error': 'Missing required field: quantity'}), 400
        
        symbol = data['symbol'].upper()
        base_asset = symbol.replace('USDT', '').replace('USD', '')
        side = data['side'].upper()  # BUY or SELL
        order_type = data['type'].upper()  # MARKET, LIMIT, etc.
        quantity_input = _coerce_float(data.get('quantity'))
        quote_amount = _coerce_float(
            data.get('quoteQuantity') or data.get('quote_quantity') or data.get('quote_amount')
        )
        price = _coerce_float(data.get('price'), 0.0) or 0.0
        quantity = quantity_input or 0.0
        
        # Validate order type
        valid_order_types = ['MARKET', 'LIMIT', 'STOP_LOSS', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT', 'TAKE_PROFIT_LIMIT', 'LIMIT_MAKER']
        if order_type not in valid_order_types:
            return jsonify({'success': False, 'error': f'Invalid order type. Must be one of: {", ".join(valid_order_types)}'}), 400
        
        # Check if 2FA is required
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if settings and settings.require_2fa and settings.totp_secret:
            # Verify 2FA token
            twofa_token = data.get('twofa_token')
            if not twofa_token:
                return jsonify({'success': False, 'error': '2FA verification required', 'requires_2fa': True}), 403
            
            # Check token validity
            token_data = session.get(f'2fa_verified_{twofa_token}')
            if not token_data or token_data['user_id'] != current_user.id:
                return jsonify({'success': False, 'error': '2FA verification invalid or expired', 'requires_2fa': True}), 403
            
            # Check if token is not older than 2 minutes
            if (datetime.utcnow().timestamp() - token_data['timestamp']) > 120:
                session.pop(f'2fa_verified_{twofa_token}', None)
                return jsonify({'success': False, 'error': '2FA verification expired. Please verify again.', 'requires_2fa': True}), 403
            
            # Clear the token after use
            session.pop(f'2fa_verified_{twofa_token}', None)
        
        # Get Binance.US Trading credentials
        # Get Binance.US credentials
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found. Please add them in Settings > Binance.US Trading API.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        trading_api_key = decrypt_secret(creds.trading_api_key)
        trading_api_secret = decrypt_secret(creds.trading_api_secret)
        if not trading_api_key or not trading_api_secret:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found. Please add them in Settings > Binance.US Trading API.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=trading_api_key,
            api_secret=trading_api_secret,
            testnet=False,
            tld='us'
        )
        
        # Get symbol filters and format values according to Binance.US rules
        filters = get_symbol_filters(client, symbol)
        if not filters:
            return jsonify({'success': False, 'error': f'Unable to get trading rules for {symbol}. Please check the symbol is valid.'}), 400

        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            current_price = _coerce_float(ticker.get('price'), 0.0) or 0.0
        except Exception as price_err:
            logger.error(f"Failed to fetch current price for {symbol}: {price_err}")
            current_price = 0.0

        quantity = quantity_input
        if not quantity or quantity <= 0:
            reference_price = price if price > 0 else current_price
            if (not reference_price or reference_price <= 0) and quote_amount and quote_amount > 0:
                try:
                    ticker = client.get_symbol_ticker(symbol=symbol)
                    reference_price = _coerce_float(ticker.get('price'), 0.0) or 0.0
                    current_price = reference_price
                except Exception as refill_err:
                    logger.error(f"Failed to refresh price for {symbol}: {refill_err}")
                    reference_price = None
            if quote_amount and quote_amount > 0 and reference_price and reference_price > 0:
                quantity = quote_amount / reference_price
            else:
                return jsonify({
                    'success': False,
                    'error': 'Unable to determine order quantity. Please enter a value or wait for prices to refresh.'
                }), 400
        if quantity <= 0:
            return jsonify({'success': False, 'error': 'Quantity must be greater than zero.'}), 400
        
        # Format quantity according to LOT_SIZE filter
        formatted_quantity = format_quantity(quantity, filters['stepSize'])
        
        # Validate quantity is within bounds
        if formatted_quantity < filters['minQty']:
            return jsonify({
                'success': False, 
                'error': f'Quantity too small. Minimum quantity for {symbol} is {filters["minQty"]}. You entered {quantity} which rounds to {formatted_quantity}.'
            }), 400
        
        if formatted_quantity > filters['maxQty']:
            return jsonify({
                'success': False, 
                'error': f'Quantity too large. Maximum quantity for {symbol} is {filters["maxQty"]}. You entered {quantity}.'
            }), 400
        
        # Format price according to PRICE_FILTER
        if price > 0:
            formatted_price = format_price(price, filters['tickSize'])
            if formatted_price < filters['minPrice']:
                return jsonify({
                    'success': False, 
                    'error': f'Price too low. Minimum price for {symbol} is {filters["minPrice"]}. You entered {price}.'
                }), 400
            if formatted_price > filters['maxPrice']:
                return jsonify({
                    'success': False, 
                    'error': f'Price too high. Maximum price for {symbol} is {filters["maxPrice"]}. You entered {price}.'
                }), 400
        else:
            formatted_price = 0.0
        
        # Validate order using Binance.US test endpoint
        try:
            test_params = {
                'symbol': symbol,
                'side': side,
                'type': order_type,
                'quantity': formatted_quantity
            }
            
            # Add price for LIMIT orders
            if order_type in ['LIMIT', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT', 'LIMIT_MAKER']:
                if formatted_price <= 0:
                    return jsonify({'success': False, 'error': 'Price is required for LIMIT orders'}), 400
                
                # Check MIN_NOTIONAL (minimum order value)
                order_value = formatted_quantity * formatted_price
                if 'minNotional' in filters and order_value < filters['minNotional']:
                    return jsonify({
                        'success': False, 
                        'error': f'Order value too small. Minimum order value for {symbol} is ${filters["minNotional"]:.2f}. Your order value is ${order_value:.2f}. Please increase quantity or price.'
                    }), 400
                
                test_params['price'] = formatted_price
                test_params['timeInForce'] = 'GTC'  # Good Till Cancel
            
            # Add stopPrice for STOP orders
            if order_type in ['STOP_LOSS', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT', 'TAKE_PROFIT_LIMIT']:
                stop_price_str = data.get('stopPrice', '0')
                stop_price = float(stop_price_str) if stop_price_str and stop_price_str.strip() else 0.0
                if stop_price <= 0:
                    return jsonify({'success': False, 'error': f'stopPrice is required for {order_type} orders'}), 400
                
                # Format stop price
                formatted_stop_price = format_price(stop_price, filters['tickSize'])
                test_params['stopPrice'] = formatted_stop_price

                if order_type == 'STOP_LOSS_LIMIT':
                    if formatted_price <= 0:
                        return jsonify({'success': False, 'error': 'Limit price must be greater than 0 for stop-limit orders'}), 400
                    if side == 'BUY' and formatted_price < formatted_stop_price:
                        return jsonify({'success': False, 'error': 'For buy stop-loss limit orders, limit price must be greater than or equal to stop price.'}), 400
                    if side == 'SELL' and formatted_price > formatted_stop_price:
                        return jsonify({'success': False, 'error': 'For sell stop-loss limit orders, limit price must be less than or equal to stop price.'}), 400
                elif order_type == 'TAKE_PROFIT_LIMIT':
                    if formatted_price <= 0:
                        return jsonify({'success': False, 'error': 'Limit price must be greater than 0 for take-profit limit orders'}), 400
                    if side == 'BUY' and formatted_price > formatted_stop_price:
                        return jsonify({'success': False, 'error': 'For buy take-profit limit orders, limit price must be less than or equal to stop price.'}), 400
                    if side == 'SELL' and formatted_price < formatted_stop_price:
                        return jsonify({'success': False, 'error': 'For sell take-profit limit orders, limit price must be greater than or equal to stop price.'}), 400

            # Pre-validate price collar against current market price
            try:
                ticker = client.get_symbol_ticker(symbol=symbol)
                current_market_price = float(ticker['price'])
            except Exception:
                current_market_price = 0.0

            from services.binance_service import validate_order_price_collar
            if formatted_price > 0 and current_market_price > 0:
                valid, collar_err = validate_order_price_collar(formatted_price, side, current_market_price, filters, symbol)
                if not valid:
                    return jsonify({'success': False, 'error': collar_err}), 400
            if order_type in ['STOP_LOSS', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT', 'TAKE_PROFIT_LIMIT'] and current_market_price > 0:
                valid, collar_err = validate_order_price_collar(formatted_stop_price, side, current_market_price, filters, symbol)
                if not valid:
                    return jsonify({'success': False, 'error': collar_err}), 400
            
            # For MARKET orders, check MIN_NOTIONAL using current price
            if order_type == 'MARKET' and 'minNotional' in filters:
                order_value = formatted_quantity * (current_market_price or 1.0)
                if order_value < filters['minNotional']:
                    return jsonify({
                        'success': False, 
                        'error': f'Order value too small. Minimum order value for {symbol} is ${filters["minNotional"]:.2f}. Your order value is approximately ${order_value:.2f} at current market price. Please increase quantity.'
                    }), 400
            
            # Validate with Binance test endpoint
            client.create_test_order(**test_params)
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Binance order validation failed: {e}\n{traceback.format_exc()}")
            
            # Parse Binance error for more specific messaging
            if 'PERCENT_PRICE' in error_msg:
                mult_up = filters.get('multiplierUp', 5.0)
                mult_down = filters.get('multiplierDown', 0.2)
                return jsonify({
                    'success': False, 
                    'error': f'Price filter failure (PERCENT_PRICE): Binance.US restricts order prices to within {mult_down}x - {mult_up}x of current market price for {symbol}. Please adjust your price closer to market value.'
                }), 400
            elif 'LOT_SIZE' in error_msg:
                return jsonify({
                    'success': False, 
                    'error': f'Invalid quantity. The quantity has too many decimal places or doesn\'t meet the step size requirement for {symbol}. Please adjust your order quantity.'
                }), 400
            elif 'MIN_NOTIONAL' in error_msg or 'NOTIONAL' in error_msg:
                return jsonify({
                    'success': False, 
                    'error': f'Order value too small. The total order value (quantity × price) is below the minimum required for {symbol} (${filters.get("minNotional", 10):.2f}). Please increase your quantity.'
                }), 400
            elif 'PRICE_FILTER' in error_msg:
                return jsonify({
                    'success': False, 
                    'error': f'Invalid price. The price has too many decimal places or is outside the allowed range for {symbol}. Please adjust your price.'
                }), 400
            elif 'INSUFFICIENT_BALANCE' in error_msg or 'insufficient balance' in error_msg.lower():
                return jsonify({
                    'success': False, 
                    'error': f'Insufficient balance. You don\'t have enough funds to place this order. Please reduce the quantity or add more funds.'
                }), 400
            elif 'Invalid API-key' in error_msg or 'API-key' in error_msg:
                return jsonify({
                    'success': False, 
                    'error': 'API key invalid or expired. Please check your Binance.US API credentials in Settings and ensure they have trading permissions enabled.'
                }), 401
            elif 'IP' in error_msg and 'permissions' in error_msg.lower():
                return jsonify({
                    'success': False, 
                    'error': 'IP not whitelisted. Your current IP address is not authorized for API trading. Please add your IP to the whitelist in your Binance.US API settings.'
                }), 403
            else:
                # Generic error with full details
                return jsonify({
                    'success': False, 
                    'error': f'Order validation failed: {error_msg}'
                }), 400
        
        # Get current market price for simulation
        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            current_price = float(ticker['price'])
        except Exception as e:
            logger.error(f"Failed to get current price for {symbol}: {e}")
            current_price = formatted_price if formatted_price > 0 else 0
        
        # Calculate fill price for simulation
        if order_type == 'MARKET':
            fill_price = current_price
        elif order_type in ['LIMIT', 'LIMIT_MAKER']:
            fill_price = formatted_price
        else:
            # For stop orders, use formatted stop price
            if 'stopPrice' in test_params:
                fill_price = test_params['stopPrice']
            else:
                fill_price = current_price
        
        # Handle stopPrice for creating order record
        stop_price_for_record = None
        if 'stopPrice' in test_params:
            stop_price_for_record = test_params['stopPrice']
        
        # Get API-provided fee rates for accurate simulation
        fee_info = get_trade_fee_for_symbol(client, symbol) or {'maker': 0.001, 'taker': 0.001}
        # Use taker fee for simulation (most conservative)
        fee_rate = fee_info.get('taker', 0.001)
        simulated_commission = formatted_quantity * fill_price * fee_rate
        
        # Create test order record with formatted values
        test_order = TestOrder(
            user_id=current_user.id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=formatted_quantity,  # Use formatted quantity
            price=formatted_price if formatted_price > 0 else None,  # Use formatted price
            stop_price=stop_price_for_record,
            time_in_force='GTC' if order_type in ['LIMIT', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT', 'LIMIT_MAKER'] else None,
            status='FILLED',  # Simulate immediate fill for test orders
            simulated_fill_price=fill_price,
            simulated_fill_time=datetime.utcnow(),
            created_at=datetime.utcnow(),
            notes=f'Simulated commission: ${simulated_commission:.4f} ({fee_rate*100:.2f}% API rate)'
        )
        
        db.session.add(test_order)
        
        # Update test portfolio with formatted quantity and API-provided fee rate
        update_test_portfolio(current_user.id, symbol, side, formatted_quantity, fill_price, fee_rate)
        
        db.session.commit()
        
        logger.info(f"Test order placed successfully for user {current_user.id}: {symbol} {side} {formatted_quantity} @ {fill_price}")
        
        return jsonify({
            'success': True,
            'order': test_order.to_dict(),
            'message': f'Test order validated and simulated successfully. Quantity adjusted from {quantity} to {formatted_quantity} to match trading rules.',
            'formatted_values': {
                'quantity': formatted_quantity,
                'price': formatted_price,
                'original_quantity': quantity,
                'original_price': price
            }
        })
        
    except Exception as e:
        logger.error(f"Error placing test order: {e}\n{traceback.format_exc()}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/trading/orders', methods=['GET'])
@login_required
def get_trading_orders():
    """Get order history (test or real based on settings)"""
    try:
        # Check if user is in test mode
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        test_mode = settings.test_mode_enabled if settings else True
        
        # Get filter parameters
        limit = int(request.args.get('limit', 50))
        symbol = request.args.get('symbol')
        
        if test_mode:
            # Get test orders
            query = TestOrder.query.filter_by(user_id=current_user.id)
            if symbol:
                query = query.filter_by(symbol=symbol.upper())
            orders = query.order_by(TestOrder.created_at.desc()).limit(limit).all()
        else:
            # Get real orders
            query = RealOrder.query.filter_by(user_id=current_user.id)
            if symbol:
                query = query.filter_by(symbol=symbol.upper())
            orders = query.order_by(RealOrder.created_at.desc()).limit(limit).all()
        
        return jsonify({
            'success': True,
            'test_mode': test_mode,
            'orders': [order.to_dict() for order in orders]
        })
        
    except Exception as e:
        logger.error(f"Error fetching trading orders: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/trading/real-orders', methods=['GET'])
@login_required
def get_real_orders_only():
    """Get REAL order history only (never returns test orders)"""
    try:
        # Get filter parameters
        limit_param = request.args.get('limit', '50')
        account_scope = request.args.get('account_scope', 'all').lower()
        if account_scope not in {'all', 'binance', 'webull'}:
            account_scope = 'all'
        unlimited = False
        try:
            if isinstance(limit_param, str) and limit_param.lower() in ('all', '*', 'infinite'):
                unlimited = True
                limit = 50
            else:
                limit_value = int(limit_param)
                if limit_value <= 0:
                    unlimited = True
                    limit = 50
                else:
                    limit = limit_value
        except (TypeError, ValueError):
            limit = 50
        symbol = request.args.get('symbol')
        symbol_filter = symbol.upper() if symbol else None
        # The Combined Orders view uses the persisted ledger so entering its
        # history tab is immediate. Other consumers can explicitly retain the
        # existing live exchange-history behavior.
        history_source = str(request.args.get('history_source') or 'live').strip().lower()
        database_only = history_source == 'database'

        combined_orders = {}
        symbols_to_check = set()
        activity_records = []

        def normalize_timestamp(value):
            if not value:
                return None
            try:
                if isinstance(value, datetime):
                    if value.tzinfo is None:
                        return value.replace(tzinfo=timezone.utc).isoformat()
                    return value.astimezone(timezone.utc).isoformat()
                if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
                    timestamp = float(value)
                    if timestamp > 100000000000:
                        timestamp /= 1000
                    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
                v = str(value).strip()
                if v.endswith('Z'):
                    v = v[:-1] + '+00:00'
                if '+' in v or (len(v) > 10 and '-' in v[10:]):
                    return datetime.fromisoformat(v).astimezone(timezone.utc).isoformat()
                try:
                    return datetime.fromisoformat(v).replace(tzinfo=timezone.utc).isoformat()
                except Exception:
                    return datetime.strptime(v, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).isoformat()
            except Exception:
                return str(value)

        def add_order(unique_key, payload):
            if not payload:
                return
            created_at = payload.get('created_at')
            combined_orders[unique_key] = payload if unique_key not in combined_orders else (
                payload if created_at and created_at > combined_orders[unique_key].get('created_at', '')
                else combined_orders[unique_key]
            )

        # Include locally stored real orders (placed via the app)
        query = RealOrder.query.filter_by(user_id=current_user.id)
        if symbol_filter:
            query = query.filter_by(symbol=symbol_filter)
        query = query.order_by(RealOrder.created_at.desc())
        if not unlimited:
            query = query.limit(limit)
        stored_orders = query.all()

        for order in stored_orders:
            key = f"binance-{order.symbol}-{order.binance_order_id}" if order.binance_order_id else f"real-{order.id}"
            try:
                stored_metadata = json.loads(order.order_response or '{}')
            except Exception:
                stored_metadata = {}
            origin = stored_metadata.get('origin') or 'manual'
            order_dict = {
                'id': order.binance_order_id or f"real-{order.id}",
                'symbol': order.symbol,
                'side': order.side,
                'order_type': order.type,
                'quantity': float(order.quantity or 0.0),
                'price': float(order.price or 0.0),
                'filled_quantity': float(order.executed_qty or order.quantity or 0.0),
                'filled_price': float(order.avg_fill_price or order.price or 0.0),
                'fee': float(order.commission or 0.0),
                'fee_asset': order.commission_asset,
                'commission': float(order.commission or 0.0),
                'commission_asset': order.commission_asset,
                'status': order.status or 'UNKNOWN',
                'created_at': normalize_timestamp(order.created_at),
                'updated_at': normalize_timestamp(order.updated_at),
                'source': 'app',
                'origin': origin,
                'origin_label': stored_metadata.get('origin_label') or ('Canceled by Auto-Sell' if origin == 'auto_sell_cancellation' else 'Manual'),
                'trigger_type': 'auto_sell' if origin == 'auto_sell_cancellation' else None,
            }
            add_order(key, order_dict)

        if symbol_filter:
            symbols_to_check.add(symbol_filter)
        else:
            symbols_to_check.update({o.symbol for o in stored_orders if o.symbol})
            try:
                user_coins = Coin.query.filter_by(user_id=current_user.id).all()
                for coin in user_coins:
                    sym = (coin.symbol or '').upper()
                    if sym and sym not in ['USD', 'USDT']:
                        symbols_to_check.add(f"{sym}USDT")
                        symbols_to_check.add(f"{sym}USD")
            except Exception as coin_err:
                logger.warning(f"Failed to gather portfolio symbols for order history: {coin_err}")

        activity_rows = db.session.execute(
            text('''SELECT id, date, type, asset, amount, fee, status, exchange, description, details, txid, price_sold_at, avg_entry, proceeds
               FROM all_activities
               WHERE user_id = :uid
                 AND ((LOWER(COALESCE(exchange, '')) = 'binance' AND status IN ('FILLED', 'completed'))
                      OR txid LIKE 'auto_sell_%' OR txid LIKE 'auto_buy_%')'''),
            {"uid": current_user.id}
        ).mappings().all()

        activity_records = []
        for row in activity_rows:
            activity = dict(row)
            details_str = activity.get('details') or ''
            details_json = None
            if details_str:
                json_start = details_str.find('{')
                if json_start >= 0:
                    try:
                        details_json = json.loads(details_str[json_start:])
                    except Exception:
                        details_json = None
            if details_json:
                activity['__details_json__'] = details_json
                product_id = details_json.get('product_id')
                if product_id:
                    symbols_to_check.add(product_id.replace('-', '').upper())
                activity_records.append(activity)
            else:
                activity_records.append(activity)

        cleaned_symbols = {s for s in symbols_to_check if s}

        # Live callers retain the legacy exchange-history lookup.  Combined
        # Orders passes history_source=database and skips every network read.
        try:
            creds = Credential.query.filter_by(user_id=current_user.id).first() if not database_only else None

            if creds:
                trading_api_key = creds.trading_api_key
                trading_api_secret = creds.trading_api_secret
                portfolio_api_key = creds.api_key
                portfolio_api_secret = creds.api_secret

                api_key = trading_api_key or portfolio_api_key
                api_secret = trading_api_secret or portfolio_api_secret

                if api_key and api_secret:
                    from binance.client import Client
                    client = Client(api_key=api_key, api_secret=api_secret, testnet=False, tld='us')

                    for trading_symbol in cleaned_symbols:
                        try:
                            if unlimited:
                                fetched_orders = []
                                next_start = None
                                while True:
                                    params = {'symbol': trading_symbol, 'limit': 500}
                                    if next_start:
                                        params['startTime'] = next_start
                                    batch = client.get_all_orders(**params)
                                    if not batch:
                                        break
                                    fetched_orders.extend(batch)
                                    if len(batch) < 500:
                                        break
                                    last_time = batch[-1].get('time') or batch[-1].get('updateTime')
                                    if not last_time:
                                        break
                                    next_start = last_time + 1
                                    time.sleep(0.2)
                            else:
                                fetched_orders = client.get_all_orders(symbol=trading_symbol, limit=min(limit, 500))

                            for o in fetched_orders:
                                order_id = o.get('orderId')
                                key = f"binance-{trading_symbol}-{order_id}"

                                created_at = o.get('time') or o.get('updateTime')
                                if created_at:
                                    created_at_iso = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc).isoformat()
                                else:
                                    created_at_iso = None

                                orig_qty = float(o.get('origQty') or 0.0)
                                executed_qty = float(o.get('executedQty') or 0.0)
                                price = float(o.get('price') or 0.0)
                                cumulative_quote = float(o.get('cummulativeQuoteQty') or 0.0)

                                filled_price = 0.0
                                if executed_qty > 0:
                                    if cumulative_quote > 0:
                                        filled_price = cumulative_quote / executed_qty
                                    else:
                                        filled_price = price
                                elif price > 0:
                                    filled_price = price

                                payload = {
                                    'id': order_id or key,
                                    'symbol': trading_symbol,
                                    'side': o.get('side'),
                                    'order_type': o.get('type'),
                                    'quantity': orig_qty,
                                    'price': price,
                                    'filled_quantity': executed_qty,
                                    'filled_price': filled_price,
                                    'status': o.get('status'),
                                    'created_at': created_at_iso,
                                    'updated_at': datetime.fromtimestamp(o['updateTime'] / 1000, tz=timezone.utc).isoformat() if o.get('updateTime') else created_at_iso,
                                    'source': 'binance'
                                }

                                add_order(key, payload)

                        except Exception as binance_err:
                            logger.warning(f"Failed to fetch Binance orders for {trading_symbol}: {binance_err}")
                            continue
                else:
                    logger.warning("Binance credentials found but incomplete for order history fetch")
            elif not database_only:
                logger.warning("No Binance credentials found for real order history")
        except Exception as cred_err:
            logger.warning(f"Could not fetch Binance order history: {cred_err}")

        # Merge read-only Webull historical orders. They use their own unique
        # source keys and may represent equities, options, futures, or crypto;
        # none are treated as Binance tradable symbols.
        if account_scope != 'binance' and not database_only:
            try:
                webull_credential = Credential.query.filter_by(user_id=current_user.id).first()
                webull_setting = UserSetting.query.filter_by(user_id=current_user.id).first()
                webull_environment = normalize_webull_environment(
                    getattr(webull_setting, 'webull_environment', None) or 'production'
                )
                if (
                    webull_credential and webull_credential.webull_token_status == 'NORMAL'
                    and webull_credential.webull_token_environment == webull_environment
                    and webull_credential.webull_access_token
                ):
                    target_acc = request.args.get('account_id')
                    webull_orders = get_webull_order_history(
                        webull_credential.webull_app_key, webull_credential.webull_app_secret,
                        webull_environment, webull_credential.webull_access_token, page_size=100,
                        account_id=target_acc,
                    )
                    for order in webull_orders:
                        order_id = order.get('order_id') or order.get('orderId') or order.get('client_order_id') or order.get('clientOrderId')
                        symbol = str(order.get('symbol') or order.get('ticker') or 'UNKNOWN').upper()
                        account_id = str(order.get('_webull_account_id') or '')
                        quantity = order.get('total_quantity', order.get('quantity', order.get('order_quantity', 0)))
                        filled_quantity = order.get('filled_quantity', order.get('executed_quantity', order.get('filled_qty', 0)))
                        price = order.get('limit_price', order.get('price', order.get('order_price', 0)))
                        filled_price = order.get('average_filled_price', order.get('avg_fill_price', order.get('filled_price', price)))
                        def float_or_zero(value):
                            try:
                                return float(value or 0)
                            except (TypeError, ValueError):
                                return 0.0
                        payload = {
                            'id': order_id or f'webull-{account_id}-{symbol}', 'symbol': symbol,
                            'side': order.get('side') or 'UNKNOWN',
                            'order_type': order.get('order_type') or order.get('type') or 'UNKNOWN',
                            'quantity': float_or_zero(quantity), 'price': float_or_zero(price),
                            'filled_quantity': float_or_zero(filled_quantity), 'filled_price': float_or_zero(filled_price),
                            'status': order.get('status') or order.get('order_status') or 'UNKNOWN',
                            'created_at': normalize_timestamp(
                                order.get('created_at') or order.get('create_time') or order.get('placed_time')
                                or order.get('place_time') or order.get('submitted_time') or order.get('filled_time_at')
                            ),
                            'updated_at': normalize_timestamp(
                                order.get('updated_at') or order.get('update_time') or order.get('filled_time')
                                or order.get('filled_time_at') or order.get('last_updated_time')
                            ),
                            'source': 'webull', 'origin': 'webull', 'origin_label': 'Webull',
                            'instrument_type': order.get('instrument_type'),
                            # The combined Orders client already receives this
                            # identifier for Webull open orders.  Keep the same
                            # account scope on historical rows so account
                            # filtering cannot mix orders from another account.
                            'webull_account_id': account_id,
                            'webull_account_type': order.get('_webull_account_type'),
                        }
                        add_order(f"webull-{account_id}-{payload['id']}", payload)
            except WebullConnectionError as webull_err:
                logger.warning(f"Could not fetch Webull order history: {webull_err}")
            except Exception as webull_err:
                logger.warning(f"Unexpected Webull order-history error: {webull_err}")

        # Merge persisted Binance.US and app-automation fills.  The activity
        # ledger is intentionally sufficient for the database-only Combined
        # History view; no provider call is needed to render these rows.
        for activity in activity_records:
            details_json = activity.get('__details_json__') or {}
            txid = str(activity.get('txid') or '')
            details = activity.get('details') or ''
            activity_text = f"{details}\n{activity.get('description') or ''}"
            is_auto_sell = txid.startswith('auto_sell_') or 'Auto-Sell executed' in activity_text
            is_auto_buy = txid.startswith('auto_buy_') or 'Auto-Buy executed' in activity_text
            is_automated = is_auto_sell or is_auto_buy
            order_id = details_json.get('order_id') or txid or f"activity-{activity.get('id')}"
            product_id = details_json.get('product_id')
            asset = str(activity.get('asset') or '').upper()
            if not product_id and asset:
                quote_match = re.search(r'\b(USDT|USD)\b', activity_text)
                product_id = f"{asset}{quote_match.group(1) if quote_match else ''}"
            if not product_id:
                continue

            if asset == 'USDT' and 'Auto-generated' in activity_text:
                continue

            side = (details_json.get('side') or activity.get('type') or '').upper()
            quantity = details_json.get('filled_size') or activity.get('amount')
            price = (
                details_json.get('average_filled_price') or activity.get('price_sold_at')
                or activity.get('avg_entry')
            )

            try:
                quantity_val = float(quantity) if quantity not in (None, '') else 0.0
            except Exception:
                quantity_val = 0.0

            try:
                price_val = float(price) if price not in (None, '') else 0.0
            except Exception:
                price_val = 0.0
            if price_val <= 0 and quantity_val:
                try:
                    price_val = abs(float(activity.get('proceeds') or 0)) / abs(quantity_val)
                except Exception:
                    pass

            source = 'auto_sell' if is_auto_sell else ('auto_buy' if is_auto_buy else 'binance')
            origin_label = 'Auto-Sell' if is_auto_sell else ('Auto-Buy' if is_auto_buy else 'Binance.US')
            status = str(activity.get('status') or 'FILLED').upper()
            if status == 'COMPLETED':
                status = 'FILLED'

            payload = {
                'id': order_id,
                'symbol': product_id.replace('-', '').upper(),
                'side': side or 'UNKNOWN',
                'order_type': (details_json.get('order_type') or ('AUTO_SELL' if is_auto_sell else 'AUTO_BUY' if is_auto_buy else 'MARKET')).upper(),
                'quantity': quantity_val,
                'price': price_val,
                'filled_quantity': quantity_val,
                'filled_price': price_val,
                'fee': float(activity.get('fee') or 0.0),
                'fee_asset': 'USD',
                'commission': float(activity.get('fee') or 0.0),
                'commission_asset': 'USD',
                'status': status,
                'created_at': normalize_timestamp(details_json.get('created_time') or activity.get('date')),
                'updated_at': normalize_timestamp(details_json.get('last_fill_time') or details_json.get('created_time') or activity.get('date')),
                'source': source,
                'origin': source,
                'origin_label': origin_label,
                'trigger_type': source if is_automated else None,
            }

            add_order(f"{source}-{payload['symbol']}-{order_id}", payload)

        # Auto-sell must cancel any conflicting open orders before it can sell the
        # released balance. Preserve that causal chain in historical Order History.
        auto_sell_cancellations = set()
        for activity in activity_records:
            details = activity.get('details') or ''
            if str(activity.get('txid') or '').startswith('auto_sell_') or 'Auto-Sell executed' in details:
                auto_sell_cancellations.update(re.findall(r'#(\d+)', details))
        for payload in combined_orders.values():
            if str(payload.get('id')) in auto_sell_cancellations and str(payload.get('status', '')).upper() == 'CANCELED':
                payload['origin'] = 'auto_sell_cancellation'
                payload['origin_label'] = 'Canceled by Auto-Sell'
                payload['trigger_type'] = 'auto_sell'

        # Sort and limit
        order_list = list(combined_orders.values())
        if account_scope == 'binance':
            order_list = [o for o in order_list if o.get('source') != 'webull']
        elif account_scope == 'webull':
            order_list = [o for o in order_list if o.get('source') == 'webull']
        if symbol_filter:
            order_list = [o for o in order_list if (o.get('symbol') or '').upper() == symbol_filter]
        order_list.sort(key=lambda o: o.get('created_at') or '', reverse=True)
        limited_orders = order_list if unlimited else order_list[:limit]

        return jsonify({
            'success': True,
            'orders': limited_orders,
            'history_source': 'database' if database_only else 'live',
        })

    except Exception as e:
        logger.error(f"Error fetching real orders: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/trading/2fa/setup', methods=['POST'])
@login_required
def setup_2fa():
    """Generate and return a new TOTP secret for 2FA setup"""
    try:
        import pyotp
        import qrcode
        import io
        import base64
        
        # Generate a new secret
        secret = pyotp.random_base32()
        
        # Create provisioning URI for QR code
        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(
            name=current_user.username,
            issuer_name='Crypto & Securities Dashboard Trading'
        )
        
        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        # Store secret temporarily (not confirmed until verified)
        session['pending_totp_secret'] = secret
        
        return jsonify({
            'success': True,
            'secret': secret,
            'qr_code': f'data:image/png;base64,{img_base64}',
            'provisioning_uri': provisioning_uri
        })
        
    except Exception as e:
        logger.error(f"Error setting up 2FA: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/trading/2fa/verify-setup', methods=['POST'])
@login_required
def verify_2fa_setup():
    """Verify 2FA code and enable 2FA for trading"""
    try:
        import pyotp
        
        data = request.get_json()
        code = data.get('code')
        
        if not code:
            return jsonify({'success': False, 'error': 'Code is required'}), 400
        
        # Get pending secret from session
        secret = session.get('pending_totp_secret')
        if not secret:
            return jsonify({'success': False, 'error': 'No pending 2FA setup found. Please start setup again.'}), 400
        
        # Verify code
        totp = pyotp.TOTP(secret)
        if not totp.verify(code, valid_window=1):
            return jsonify({'success': False, 'error': 'Invalid code. Please try again.'}), 400
        
        # Save secret to database
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if not settings:
            settings = TradingSettings(user_id=current_user.id)
            db.session.add(settings)
        
        settings.totp_secret = secret
        settings.require_2fa = True
        settings.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        # Clear session
        session.pop('pending_totp_secret', None)
        
        return jsonify({
            'success': True,
            'message': '2FA enabled successfully!'
        })
        
    except Exception as e:
        logger.error(f"Error verifying 2FA setup: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/trading/2fa/disable', methods=['POST'])
@login_required
def disable_2fa():
    """Disable 2FA for trading (requires code verification)"""
    try:
        import pyotp
        
        data = request.get_json()
        code = data.get('code')
        
        if not code:
            return jsonify({'success': False, 'error': 'Code is required to disable 2FA'}), 400
        
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if not settings or not settings.totp_secret:
            return jsonify({'success': False, 'error': '2FA is not enabled'}), 400
        
        # Verify code before disabling
        totp = pyotp.TOTP(settings.totp_secret)
        if not totp.verify(code, valid_window=1):
            return jsonify({'success': False, 'error': 'Invalid code. Please try again.'}), 400
        
        # Disable 2FA
        settings.totp_secret = None
        settings.require_2fa = False
        settings.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': '2FA disabled successfully'
        })
        
    except Exception as e:
        logger.error(f"Error disabling 2FA: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/trading/2fa/verify', methods=['POST'])
@login_required
def verify_2fa_code():
    """Verify a 2FA code for order placement"""
    try:
        import pyotp
        
        data = request.get_json()
        code = data.get('code')
        
        if not code:
            return jsonify({'success': False, 'error': 'Code is required'}), 400
        
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if not settings or not settings.totp_secret:
            return jsonify({'success': False, 'error': '2FA is not enabled'}), 400
        
        # Verify code
        totp = pyotp.TOTP(settings.totp_secret)
        if not totp.verify(code, valid_window=1):
            return jsonify({'success': False, 'error': 'Invalid or expired code. Please try again.'}), 400
        
        # Generate a temporary token valid for 2 minutes
        import secrets
        token = secrets.token_urlsafe(32)
        session[f'2fa_verified_{token}'] = {
            'user_id': current_user.id,
            'timestamp': datetime.utcnow().timestamp()
        }
        
        return jsonify({
            'success': True,
            'token': token,
            'message': '2FA verified successfully'
        })
        
    except Exception as e:
        logger.error(f"Error verifying 2FA code: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/trading/portfolio', methods=['GET'])
@login_required
def get_test_portfolio():
    """Get test portfolio holdings"""
    try:
        holdings = TestPortfolio.query.filter_by(user_id=current_user.id).filter(
            TestPortfolio.quantity > 0
        ).all()
        
        logger.error(f"[TEST_PORTFOLIO] Found {len(holdings)} holdings for user {current_user.username}")
        
        # Get current prices for each holding
        from binance.client import Client
        
        # Get credentials for price fetching
        # Get credentials for price fetching using ORM
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if creds:
            api_key = creds.api_key
            api_secret = creds.api_secret
        else:
            api_key = api_secret = None

        logger.error(f"[TEST_PORTFOLIO] Credentials found: {bool(api_key)}")
        
        portfolio_data = []
        
        if api_key and api_secret:
            client = Client(
                api_key=api_key,
                api_secret=api_secret,
                testnet=False,
                tld='us'
            )
            
            for holding in holdings:
                try:
                    logger.error(f"[TEST_PORTFOLIO] Processing {holding.symbol}, quantity: {holding.quantity}")
                    
                    # Handle stablecoins (USDT, USDC, BUSD, etc.) with $1.00 price
                    if holding.symbol in ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD']:
                        current_price = 1.0
                        logger.error(f"[TEST_PORTFOLIO] {holding.symbol} is stablecoin, price = 1.0")
                    else:
                        # Fetch real-time price from Binance
                        symbol = holding.symbol + 'USDT'
                        ticker = client.get_symbol_ticker(symbol=symbol)
                        current_price = float(ticker['price'])
                        logger.error(f"[TEST_PORTFOLIO] {holding.symbol} price from API: {current_price}")
                    
                    current_value = holding.quantity * current_price
                    cost_basis = holding.quantity * holding.avg_entry_price
                    pnl = current_value - cost_basis
                    pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0
                    
                    portfolio_data.append({
                        'symbol': holding.symbol,
                        'quantity': holding.quantity,
                        'average_price': holding.avg_entry_price,
                        'current_price': current_price,
                        'current_value': current_value,
                        'cost_basis': cost_basis,
                        'pnl': pnl,
                        'pnl_pct': pnl_pct,
                        'last_updated': holding.last_updated.isoformat() if holding.last_updated else None
                    })
                except Exception as e:
                    logger.warning(f"Failed to get price for {holding.symbol}: {e}")
                    # Add holding with null price data
                    portfolio_data.append({
                        'symbol': holding.symbol,
                        'quantity': holding.quantity,
                        'average_price': holding.avg_entry_price,
                        'current_price': None,
                        'current_value': None,
                        'cost_basis': holding.quantity * holding.avg_entry_price,
                        'pnl': None,
                        'pnl_pct': None,
                        'last_updated': holding.last_updated.isoformat() if holding.last_updated else None
                    })
        
        return jsonify({
            'success': True,
            'holdings': portfolio_data
        })
        
    except Exception as e:
        logger.error(f"Error fetching test portfolio: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/trading/portfolio/backfill', methods=['POST'])
@login_required
def backfill_test_portfolio():
    """Backfill test portfolio with actual coin holdings from the coins table AND USDT from Binance"""
    try:
        from binance.client import Client
        
        # Get all coins for the user
        user_coins = Coin.query.filter_by(user_id=current_user.id).all()
        
        if not user_coins:
            return jsonify({
                'success': False,
                'error': 'No coins found in your portfolio to backfill'
            }), 400
        
        backfilled_count = 0
        
        # Backfill regular coins from coins table
        for coin in user_coins:
            # Skip if no amount or hidden
            if not coin.amount or coin.amount <= 0 or coin.hidden:
                continue
            
            # Check if already exists in test portfolio
            existing = TestPortfolio.query.filter_by(
                user_id=current_user.id,
                symbol=coin.symbol
            ).first()
            
            # Use avg_entry or current price as the entry price
            entry_price = coin.avg_entry or coin.current or 0
            
            if existing:
                # Update existing
                existing.quantity = coin.amount
                existing.avg_entry_price = entry_price
                existing.total_cost_basis = coin.amount * entry_price
                existing.last_updated = datetime.utcnow()
                logger.info(f"Updated test portfolio for {coin.symbol}: {coin.amount} @ ${existing.avg_entry_price}")
            else:
                # Create new
                test_holding = TestPortfolio(
                    user_id=current_user.id,
                    symbol=coin.symbol,
                    quantity=coin.amount,
                    avg_entry_price=entry_price,
                    total_cost_basis=coin.amount * entry_price,
                    realized_pnl=0.0,
                    unrealized_pnl=0.0,
                    last_updated=datetime.utcnow()
                )
                db.session.add(test_holding)
                logger.info(f"Added test portfolio for {coin.symbol}: {coin.amount} @ ${test_holding.avg_entry_price}")
            
            backfilled_count += 1
        
        # Now fetch USDT balance from Binance
        try:
            # Get credentials for Binance API
            # Get credentials for Binance API using ORM
            creds = Credential.query.filter_by(user_id=current_user.id).first()

            api_key = creds.api_key if creds else None
            api_secret = creds.api_secret if creds else None

            if api_key and api_secret:
                client = Client(
                    api_key=api_key,
                    api_secret=api_secret,
                    testnet=False,
                    tld='us'
                )
                
                # Get account info to fetch USDT balance
                account_info = client.get_account()
                
                # Find USDT balance
                usdt_balance = 0.0
                for balance in account_info['balances']:
                    if balance['asset'] == 'USDT':
                        usdt_balance = float(balance['free']) + float(balance['locked'])
                        break
                
                if usdt_balance > 0:
                    # Check if USDT already exists in test portfolio
                    existing_usdt = TestPortfolio.query.filter_by(
                        user_id=current_user.id,
                        symbol='USDT'
                    ).first()
                    
                    if existing_usdt:
                        # Update existing USDT
                        existing_usdt.quantity = usdt_balance
                        existing_usdt.avg_entry_price = 1.0
                        existing_usdt.total_cost_basis = usdt_balance
                        existing_usdt.last_updated = datetime.utcnow()
                        logger.info(f"Updated test portfolio USDT: ${usdt_balance:.2f}")
                    else:
                        # Create new USDT entry
                        test_usdt = TestPortfolio(
                            user_id=current_user.id,
                            symbol='USDT',
                            quantity=usdt_balance,
                            avg_entry_price=1.0,
                            total_cost_basis=usdt_balance,
                            realized_pnl=0.0,
                            unrealized_pnl=0.0,
                            last_updated=datetime.utcnow()
                        )
                        db.session.add(test_usdt)
                        logger.info(f"Added test portfolio USDT: ${usdt_balance:.2f}")
                    
                    backfilled_count += 1
                else:
                    logger.warning("No USDT balance found in Binance account")
            else:
                logger.warning("No Binance API credentials found, skipping USDT backfill")
                
        except Exception as e:
            logger.error(f"Error fetching USDT balance from Binance: {e}")
            # Continue without USDT if there's an error
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully backfilled {backfilled_count} holding(s) into test portfolio',
            'count': backfilled_count
        })
        
    except Exception as e:
        logger.error(f"Error backfilling test portfolio: {e}\n{traceback.format_exc()}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/trading/test-orders', methods=['GET'])
@login_required
def get_test_orders():
    """Get all test orders for the user"""
    try:
        limit = int(request.args.get('limit', 100))
        symbol = request.args.get('symbol')
        
        query = TestOrder.query.filter_by(user_id=current_user.id)
        
        if symbol:
            query = query.filter_by(symbol=symbol.upper())
        
        test_orders = query.order_by(TestOrder.created_at.desc()).limit(limit).all()
        
        return jsonify({
            'success': True,
            'orders': [order.to_dict() for order in test_orders]
        })
        
    except Exception as e:
        logger.error(f"Error fetching test orders: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/trading/place-order', methods=['POST'])
@login_required
def place_real_order():
    """Place a REAL order on Binance.US (requires test mode to be disabled)"""
    import traceback
    try:
        # Check trading settings
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        
        if not settings or settings.test_mode_enabled:
            return jsonify({
                'success': False,
                'error': 'Real trading is disabled. Please disable test mode in settings to place real orders.'
            }), 403
        
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['symbol', 'side', 'type']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
        has_quantity = bool(data.get('quantity'))
        has_quote = bool(data.get('quoteQuantity') or data.get('quote_quantity') or data.get('quote_amount'))
        if not has_quantity and not has_quote:
            return jsonify({'success': False, 'error': 'Missing required field: quantity'}), 400
        
        symbol = data['symbol'].upper()
        side = data['side'].upper()
        order_type = data['type'].upper()
        quantity_input = _coerce_float(data.get('quantity'))
        price = _coerce_float(data.get('price'), 0.0) or 0.0
        quote_amount = _coerce_float(
            data.get('quoteQuantity') or data.get('quote_quantity') or data.get('quote_amount')
        )
        
        # Check if 2FA is required (ALWAYS for real orders)
        if settings.require_2fa and settings.totp_secret:
            # Verify 2FA token
            twofa_token = data.get('twofa_token')
            if not twofa_token:
                return jsonify({'success': False, 'error': '2FA verification required for real orders', 'requires_2fa': True}), 403
            
            # Check token validity
            token_data = session.get(f'2fa_verified_{twofa_token}')
            if not token_data or token_data['user_id'] != current_user.id:
                return jsonify({'success': False, 'error': '2FA verification invalid or expired', 'requires_2fa': True}), 403
            
            # Check if token is not older than 2 minutes
            if (datetime.utcnow().timestamp() - token_data['timestamp']) > 120:
                session.pop(f'2fa_verified_{twofa_token}', None)
                return jsonify({'success': False, 'error': '2FA verification expired. Please verify again.', 'requires_2fa': True}), 403
            
            # Clear the token after use
            session.pop(f'2fa_verified_{twofa_token}', None)
        
        # Get Binance.US Trading credentials using SQLAlchemy ORM
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found. Please add them in Settings > Binance.US Trading API.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Credential model properties auto-decrypt values
        trading_api_key = creds.trading_api_key
        trading_api_secret = creds.trading_api_secret
        if not trading_api_key or not trading_api_secret:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found. Please add them in Settings > Binance.US Trading API.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=trading_api_key,
            api_secret=trading_api_secret,
            testnet=False,
            tld='us'
        )
        
        # Get symbol filters and latest price data
        filters = get_symbol_filters(client, symbol)
        if not filters:
            return jsonify({'success': False, 'error': f'Unable to get trading rules for {symbol}. Please check the symbol is valid.'}), 400

        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            current_price = _coerce_float(ticker.get('price'), 0.0) or 0.0
        except Exception as price_err:
            logger.warning(f"Failed to fetch current price for {symbol}: {price_err}")
            current_price = 0.0

        quantity = quantity_input or 0.0
        if quantity <= 0:
            reference_price = price if price > 0 else current_price
            if (not reference_price or reference_price <= 0) and quote_amount and quote_amount > 0:
                try:
                    ticker = client.get_symbol_ticker(symbol=symbol)
                    reference_price = _coerce_float(ticker.get('price'), 0.0) or 0.0
                    current_price = reference_price
                except Exception as refill_err:
                    logger.error(f"Failed to refresh price for {symbol}: {refill_err}")
                    reference_price = None
            if quote_amount and quote_amount > 0 and reference_price and reference_price > 0:
                quantity = quote_amount / reference_price

        if quantity is None or quantity <= 0:
            return jsonify({
                'success': False,
                'error': 'Unable to determine order quantity. Please enter a value or wait for prices to refresh.'
            }), 400
        
        # Format quantity according to LOT_SIZE filter
        formatted_quantity = format_quantity(quantity, filters['stepSize'])
        
        # Validate quantity is within bounds
        if formatted_quantity < filters['minQty']:
            return jsonify({
                'success': False, 
                'error': f'Quantity too small. Minimum quantity for {symbol} is {filters["minQty"]}. You entered {quantity} which rounds to {formatted_quantity}.'
            }), 400
        
        if formatted_quantity > filters['maxQty']:
            return jsonify({
                'success': False, 
                'error': f'Quantity too large. Maximum quantity for {symbol} is {filters["maxQty"]}. You entered {quantity}.'
            }), 400
        
        # Format price according to PRICE_FILTER
        if price > 0:
            formatted_price = format_price(price, filters['tickSize'])
            if formatted_price < filters['minPrice']:
                return jsonify({
                    'success': False, 
                    'error': f'Price too low. Minimum price for {symbol} is {filters["minPrice"]}. You entered {price}.'
                }), 400
            if formatted_price > filters['maxPrice']:
                return jsonify({
                    'success': False, 
                    'error': f'Price too high. Maximum price for {symbol} is {filters["maxPrice"]}. You entered {price}.'
                }), 400
            data['price'] = str(formatted_price)
        else:
            formatted_price = 0.0

        # Format stopPrice according to PRICE_FILTER if present
        stop_price = _coerce_float(data.get('stopPrice'), 0.0) or 0.0
        formatted_stop_price = 0.0
        if stop_price > 0:
            formatted_stop_price = format_price(stop_price, filters['tickSize'])
            data['stopPrice'] = str(formatted_stop_price)

        # Validate order type specific rules
        if order_type in ['LIMIT', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT', 'LIMIT_MAKER']:
            if formatted_price <= 0:
                return jsonify({'success': False, 'error': 'Price is required for limit orders'}), 400

        if order_type in ['STOP_LOSS', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT', 'TAKE_PROFIT_LIMIT']:
            if formatted_stop_price <= 0:
                return jsonify({'success': False, 'error': f'Stop price is required for {order_type} orders'}), 400

        if order_type == 'STOP_LOSS_LIMIT':
            if side == 'BUY' and formatted_price < formatted_stop_price:
                return jsonify({'success': False, 'error': 'For buy stop-loss limit orders, limit price must be greater than or equal to stop price.'}), 400
            if side == 'SELL' and formatted_price > formatted_stop_price:
                return jsonify({'success': False, 'error': 'For sell stop-loss limit orders, limit price must be less than or equal to stop price.'}), 400
        elif order_type == 'TAKE_PROFIT_LIMIT':
            if side == 'BUY' and formatted_price > formatted_stop_price:
                return jsonify({'success': False, 'error': 'For buy take-profit limit orders, limit price must be less than or equal to stop price.'}), 400
            if side == 'SELL' and formatted_price < formatted_stop_price:
                return jsonify({'success': False, 'error': 'For sell take-profit limit orders, limit price must be greater than or equal to stop price.'}), 400

        # Pre-validate price collar against current market price
        from services.binance_service import validate_order_price_collar
        if formatted_price > 0 and current_price > 0:
            valid, collar_err = validate_order_price_collar(formatted_price, side, current_price, filters, symbol)
            if not valid:
                return jsonify({'success': False, 'error': collar_err}), 400
        if formatted_stop_price > 0 and current_price > 0:
            valid, collar_err = validate_order_price_collar(formatted_stop_price, side, current_price, filters, symbol)
            if not valid:
                return jsonify({'success': False, 'error': collar_err}), 400

        # Reserve the exchange fee before submitting real buy orders. Binance.US charges
        # this fee in the quote asset, so a 100% quote balance order would otherwise fail.
        if side == 'BUY':
            try:
                fee_info = get_trade_fee_for_symbol(client, symbol) or {}
                fee_rate = max(
                    _coerce_float(fee_info.get('maker'), 0.001) or 0.001,
                    _coerce_float(fee_info.get('taker'), 0.004) or 0.004
                )
                fee_reserve_rate = fee_rate + 0.001
                quote_asset = 'USDT' if symbol.endswith('USDT') else 'USD' if symbol.endswith('USD') else None
                reference_price = formatted_price if formatted_price > 0 else current_price

                if quote_asset and reference_price > 0:
                    account = client.get_account()
                    balances = {balance['asset']: _coerce_float(balance.get('free'), 0.0) or 0.0 for balance in account.get('balances', [])}
                    available_quote = balances.get(quote_asset, 0.0)
                    max_spendable_quote = available_quote / (1 + fee_reserve_rate)
                    requested_quote = quote_amount if order_type == 'MARKET' and has_quote else formatted_quantity * reference_price

                    if requested_quote > max_spendable_quote:
                        adjusted_quantity = format_quantity(max_spendable_quote / reference_price, filters['stepSize'])
                        if adjusted_quantity < filters['minQty']:
                            return jsonify({
                                'success': False,
                                'error': f'Insufficient {quote_asset} balance after reserving trading fees. Available: {available_quote:.8f} {quote_asset}.'
                            }), 400

                        formatted_quantity = adjusted_quantity
                        if order_type == 'MARKET' and has_quote:
                            adjusted_quote = max(0.0, int(max_spendable_quote * 100) / 100)
                            quote_amount = adjusted_quote
                            data['quoteQuantity'] = f'{adjusted_quote:.2f}'
                            data['quote_quantity'] = data['quoteQuantity']
                            data['quote_amount'] = data['quoteQuantity']

                        logger.info(
                            f'Reduced {symbol} buy order to reserve fees: requested={requested_quote:.8f} '
                            f'{quote_asset}, submitted={quote_amount if order_type == "MARKET" and has_quote else formatted_quantity * reference_price:.8f} '
                            f'{quote_asset}, available={available_quote:.8f}, fee_rate={fee_rate:.6f}'
                        )
            except Exception as balance_err:
                logger.warning(f'Could not reserve quote balance for {symbol} buy order: {balance_err}')

        # Get current price for order size validation
        try:
            reference_price_for_value = formatted_price if formatted_price > 0 else current_price
            if not reference_price_for_value or reference_price_for_value <= 0:
                raise ValueError("Unable to determine current market price for valuation.")
            order_value_usd = formatted_quantity * reference_price_for_value
            
            # Check MIN_NOTIONAL
            if 'minNotional' in filters and order_value_usd < filters['minNotional']:
                return jsonify({
                    'success': False, 
                    'error': f'Order value too small. Minimum order value for {symbol} is ${filters["minNotional"]:.2f}. Your order value is ${order_value_usd:.2f}. Please increase quantity or price.'
                }), 400
            
            # Check max order size
            if order_value_usd > settings.max_order_size_usd:
                return jsonify({
                    'success': False,
                    'error': f'Order size ${order_value_usd:.2f} exceeds maximum allowed ${settings.max_order_size_usd:.2f}'
                }), 400
        except Exception as e:
            logger.error(f"Failed to validate order size: {e}")
            return jsonify({'success': False, 'error': f'Failed to validate order: {str(e)}'}), 400
        
        # Place REAL order on Binance.US
        try:
            logger.info(f"Placing real order with params: {{'symbol': '{symbol}', 'side': '{side}', 'type': '{order_type}', 'quantity': {formatted_quantity}, 'price': {formatted_price}, 'stopPrice': {formatted_stop_price}, 'order_value_usd': {order_value_usd}}}")
            order_params = build_order_config(order_type, side, formatted_quantity, data, symbol)
            
            # PLACE THE REAL ORDER
            order_response = client.create_order(**order_params)
            
            # Extract fill details
            executed_qty = float(order_response.get('executedQty', 0))
            executed_quote_qty = float(order_response.get('cummulativeQuoteQty') or order_response.get('cumulativeQuoteQty') or 0)
            fills = order_response.get('fills', [])
            avg_fill_price = float(fills[0].get('price', 0)) if fills else (price if price > 0 else current_price)
            total_commission = sum(float(f.get('commission', 0)) for f in fills)
            commission_asset = fills[0].get('commissionAsset', 'USDT') if fills else 'USDT'

            binance_order_id = order_response.get('orderId') or order_response.get('orderListId')
            status = order_response.get('status', 'NEW')

            success_payload = {
                'success': True,
                'order': None,
                'binance_order_id': binance_order_id,
                'message': f'Real order placed successfully. Quantity adjusted from {quantity} to {formatted_quantity} to match trading rules.' if quantity != formatted_quantity else 'Real order placed successfully',
                'formatted_values': {
                    'quantity': formatted_quantity,
                    'price': formatted_price,
                    'original_quantity': quantity,
                    'original_price': price
                }
            }

            try:
                real_order = RealOrder(
                    user_id=current_user.id,
                    binance_order_id=binance_order_id,
                    symbol=symbol,
                    side=side,
                    type=order_type,
                    quantity=formatted_quantity,
                    price=formatted_price if formatted_price > 0 else None,
                    stop_price=order_params.get('stopPrice'),
                    time_in_force=order_response.get('timeInForce', 'GTC'),
                    status=status,
                    executed_qty=executed_qty,
                    cumulative_quote_qty=executed_quote_qty,
                    avg_fill_price=avg_fill_price,
                    commission=total_commission,
                    commission_asset=commission_asset,
                    binance_client_order_id=order_response.get('clientOrderId'),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                    filled_at=datetime.utcnow() if status == 'FILLED' else None,
                    order_response=json.dumps(order_response)
                )

                db.session.add(real_order)
                if status == 'FILLED':
                    real_order.fill_notified = True

                if status == 'FILLED' and executed_qty > 0:
                    update_portfolio_from_real_order(
                        user_id=current_user.id,
                        symbol=symbol,
                        side=side,
                        quantity=executed_qty,
                        price=avg_fill_price,
                        commission=total_commission,
                        commission_asset=commission_asset,
                        order_id=binance_order_id,
                        quote_quantity=executed_quote_qty
                    )
                    notify_order_fill(
                        real_order,
                        username=current_user.username,
                        executed_qty=executed_qty,
                        quote_qty=executed_quote_qty,
                        fill_price=avg_fill_price
                    )

                db.session.commit()
                trigger_portfolio_snapshot(current_user.id, current_user.username)
                success_payload['order'] = real_order.to_dict()

                try:
                    recalculate_asset_activity(
                        user_id=current_user.id,
                        asset=symbol.replace('USDT', '').replace('USD', ''),
                        price_provider=lambda sym: fetch_binance_price(sym),
                        logger=logger
                    )
                except Exception as recalc_err:
                    logger.warning(f"Failed to recalculate activity after real order for {symbol}: {recalc_err}")

                logger.info(f"REAL ORDER PLACED for user {current_user.id}: {symbol} {side} {formatted_quantity} @ {avg_fill_price} - Order ID: {binance_order_id}")
            except Exception as post_err:
                logger.error(f"Order {binance_order_id} placed but post-processing failed: {post_err}", exc_info=True)
                db.session.rollback()

            return jsonify(success_payload)
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to place real order: {error_msg}\n{traceback.format_exc()}")
            if "API-key" in error_msg or "Invalid Api-Key" in error_msg or "invalid api-key" in error_msg.lower():
                return jsonify({
                    'success': False,
                    'error': 'Invalid Binance API credentials',
                    'error_code': 'invalid_trading_credentials'
                }), 400
            return jsonify({'success': False, 'error': f'Order placement failed: {error_msg}'}), 400

    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error in place_real_order: {err_msg}\n{traceback.format_exc()}")
        db.session.rollback()
        if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
            return jsonify({
                'success': False,
                'error': 'Invalid Binance API credentials',
                'error_code': 'invalid_trading_credentials'
            }), 400
        return jsonify({'success': False, 'error': err_msg}), 500



@portfolio_bp.route('/api/trading/fees/<symbol>', methods=['GET'])
@login_required
def get_trading_fees(symbol):
    """Get actual trading fees for a symbol from Binance.US"""
    try:
        symbol = symbol.upper()
        
        # ALWAYS fetch actual fees from Binance.US API
        # Test mode only affects order execution, not fee display
        # Get Binance trading credentials using SQLAlchemy ORM
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({
                'success': False,
                'error': 'No trading API credentials found',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Credential model properties auto-decrypt values
        trading_api_key = creds.trading_api_key
        trading_api_secret = creds.trading_api_secret
        if not trading_api_key:
            return jsonify({
                'success': False,
                'error': 'No trading API credentials found',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        from binance.client import Client
        client = Client(
            api_key=trading_api_key,
            api_secret=trading_api_secret,
            testnet=False,
            tld='us'
        )
        
        # Method 1: Try to get symbol-specific trading fee
        try:
            # Call the trading fee API endpoint
            fee_data = client.get_trade_fee(symbol=symbol)
            logger.info(f"Binance.US get_trade_fee() raw response: {fee_data}")
            
            if fee_data and len(fee_data) > 0:
                symbol_fee = fee_data[0]
                logger.info(f"Symbol fee data: {symbol_fee}")
                maker_rate = float(symbol_fee.get('makerCommission', 0.001))
                taker_rate = float(symbol_fee.get('takerCommission', 0.001))
                
                logger.info(f"Parsed rates - Maker: {maker_rate}, Taker: {taker_rate}")
                
                return jsonify({
                    'success': True,
                    'fees': {
                        'maker': f"{maker_rate:.6f}",
                        'taker': f"{taker_rate:.6f}",
                        'makerRate': maker_rate,
                        'takerRate': taker_rate
                    }
                })
        except Exception as e:
            err_msg = str(e)
            logger.warning(f"Could not fetch symbol-specific fees: {err_msg}\n{traceback.format_exc()}")
            if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
                return jsonify({
                    'success': False,
                    'error': 'Invalid Binance API credentials',
                    'error_code': 'invalid_trading_credentials'
                }), 400
        
        # Method 2: Fall back to account-level commission rates
        try:
            account = client.get_account()
            logger.info(f"Binance.US account data keys: {list(account.keys())}")
            
            commission_rates = account.get('commissionRates', {})
            logger.info(f"Binance.US commission rates (raw): {commission_rates}")
            
            tier_0_pairs = ['BTCUSD', 'BTCUSDT', 'BTCUSDC']
            is_tier_0 = symbol in tier_0_pairs
            
            if is_tier_0:
                maker_rate = 0.0
                taker_rate = 0.0
            elif commission_rates:
                raw_maker = float(commission_rates.get('maker', '0.001'))
                raw_taker = float(commission_rates.get('taker', '0.004'))
                maker_rate = raw_maker if raw_maker > 0 else 0.001
                taker_rate = raw_taker if raw_taker > 0 else 0.004
            else:
                maker_commission = account.get('makerCommission', 10)
                taker_commission = account.get('takerCommission', 40)
                maker_rate = (float(maker_commission) / 10000) if float(maker_commission) > 0 else 0.001
                taker_rate = (float(taker_commission) / 10000) if float(taker_commission) > 0 else 0.004
            
            return jsonify({
                'success': True,
                'fees': {
                    'maker': f"{maker_rate:.6f}",
                    'taker': f"{taker_rate:.6f}",
                    'makerRate': maker_rate,
                    'takerRate': taker_rate
                }
            })
        except Exception as e:
            err_msg = str(e)
            logger.error(f"Error fetching account commission rates: {err_msg}")
            if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
                return jsonify({
                    'success': False,
                    'error': 'Invalid Binance API credentials',
                    'error_code': 'invalid_trading_credentials'
                }), 400
            # Last resort: use default Binance.US rates (0.1% maker, 0.4% taker)
            return jsonify({
                'success': True,
                'fees': {
                    'maker': '0.001000',
                    'taker': '0.001000',
                    'makerRate': 0.001,
                    'takerRate': 0.001
                }
            })

    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error in get_trading_fees: {err_msg}\n{traceback.format_exc()}")
        if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
            return jsonify({
                'success': False,
                'error': 'Invalid Binance API credentials',
                'error_code': 'invalid_trading_credentials'
            }), 400
        return jsonify({'success': False, 'error': err_msg}), 500



@portfolio_bp.route('/api/trading/price/<symbol>', methods=['GET'])
@login_required
def get_current_price(symbol):
    """Get current market price for a trading pair"""
    try:
        symbol = symbol.upper()
        
        # Get Binance credentials using SQLAlchemy ORM
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({
                'success': False,
                'error': 'No Binance.US credentials found',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Credential model properties auto-decrypt values
        api_key = creds.api_key
        api_secret = creds.api_secret
        if not api_key or not api_secret:
            return jsonify({
                'success': False,
                'error': 'No Binance.US credentials found',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        from binance.client import Client
        client = Client(
            api_key=api_key,
            api_secret=api_secret,
            testnet=False,
            tld='us'
        )
        
        # Get current price
        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
        except Exception as api_err:
            err_msg = str(api_err)
            logger.error(f"Error fetching price ticker for {symbol}: {err_msg}")
            if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
                return jsonify({
                    'success': False,
                    'error': 'Invalid Binance API credentials',
                    'error_code': 'invalid_trading_credentials'
                }), 400
            return jsonify({'success': False, 'error': f'Failed to fetch price: {err_msg}'}), 502
        base_price = float(ticker['price'])
        
        # Parse symbol to get base and quote assets
        if symbol.endswith('USD') and not symbol.endswith('USDT'):
            base_asset = symbol[:-3]
            quote_asset = 'USD'
        elif symbol.endswith('USDT'):
            base_asset = symbol[:-4]
            quote_asset = 'USDT'
        else:
            base_asset = symbol
            quote_asset = 'USDT'
        
        return jsonify({
            'success': True,
            'prices': {
                'base': base_price,  # Price of base asset in quote asset
                'quote': 1.0,  # Quote asset is always 1 (USDT/USD)
                'base_asset': base_asset,
                'quote_asset': quote_asset
            }
        })
        
    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error fetching price for {symbol}: {err_msg}")
        if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
            return jsonify({
                'success': False,
                'error': 'Invalid Binance API credentials',
                'error_code': 'invalid_trading_credentials'
            }), 400
        return jsonify({'success': False, 'error': err_msg}), 500



@portfolio_bp.route('/api/trading/balances/<symbol>', methods=['GET'])
@login_required
def get_trading_balances(symbol):
    """Get user balances for trading pair assets
    
    If test mode is enabled: fetch from test_portfolio table
    If test mode is disabled: fetch from Binance.US API
    """
    try:
        symbol = symbol.upper()
        
        # Properly extract base and quote assets
        # For USDTUSD: base=USDT, quote=USD
        # For BTCUSD: base=BTC, quote=USD
        # For BTCUSDT: base=BTC, quote=USDT
        if symbol.endswith('USD') and not symbol.endswith('USDT'):
            # USD pairs (e.g., BTCUSD, USDTUSD)
            base_asset = symbol[:-3]  # Remove 'USD' suffix
            quote_asset = 'USD'
        elif symbol.endswith('USDT'):
            # USDT pairs (e.g., BTCUSDT)
            base_asset = symbol[:-4]  # Remove 'USDT' suffix
            quote_asset = 'USDT'
        else:
            # Fallback
            base_asset = symbol
            quote_asset = 'USDT'
        
        # Check if user is in test mode
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        test_mode = settings.test_mode_enabled if settings else True
        
        logger.info(f"[BALANCE] Fetching balances for {symbol} (base={base_asset}, quote={quote_asset}), test_mode={test_mode}")
        
        if test_mode:
            # Get balances from test portfolio
            base_holding = TestPortfolio.query.filter_by(
                user_id=current_user.id,
                symbol=base_asset
            ).first()
            
            quote_holding = TestPortfolio.query.filter_by(
                user_id=current_user.id,
                symbol=quote_asset
            ).first()
            
            base_free = base_holding.quantity if base_holding else 0.0
            quote_free = quote_holding.quantity if quote_holding else 0.0
            
            logger.info(f"[BALANCE] Test portfolio: {base_asset}={base_free:.8f}, {quote_asset}={quote_free:.8f}")
            
            return jsonify({
                'success': True,
                'balances': {
                    'base': base_free,
                    'base_locked': 0.0,
                    'base_total': base_free,
                    'quote': quote_free,
                    'quote_locked': 0.0,
                    'quote_total': quote_free,
                    'base_asset': base_asset,
                    'quote_asset': quote_asset
                },
                'test_mode': True
            })
        else:
            # Get actual balances from Binance.US API using SQLAlchemy ORM
            creds = Credential.query.filter_by(user_id=current_user.id).first()
            
            if not creds:
                return jsonify({
                    'success': False,
                    'error': 'No Binance.US API credentials configured',
                    'error_code': 'missing_trading_credentials'
                }), 400
            
            # Credential model properties auto-decrypt values
            # Try trading credentials first, fall back to portfolio credentials
            trading_api_key = creds.trading_api_key
            trading_api_secret = creds.trading_api_secret
            portfolio_api_key = creds.api_key
            portfolio_api_secret = creds.api_secret
            api_key = trading_api_key or portfolio_api_key
            api_secret = trading_api_secret or portfolio_api_secret
            
            if not api_key or not api_secret:
                return jsonify({
                    'success': False,
                    'error': 'No Binance.US API credentials configured',
                    'error_code': 'missing_trading_credentials'
                }), 400
            
            from binance.client import Client
            client = Client(
                api_key=api_key,
                api_secret=api_secret,
                testnet=False,
                tld='us'
            )
            
            # Get account info directly from Binance.US
            try:
                account = client.get_account()
            except Exception as api_err:
                err_msg = str(api_err)
                logger.error(f"[BALANCE] Binance API error for {symbol}: {err_msg}")
                if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
                    return jsonify({
                        'success': False,
                        'error': 'Invalid Binance API credentials',
                        'error_code': 'invalid_trading_credentials'
                    }), 400
                return jsonify({
                    'success': False,
                    'error': f'Failed to fetch balances: {err_msg}'
                }), 502
            
            # Extract only the relevant asset balances
            base_free = 0
            base_locked = 0
            quote_free = 0
            quote_locked = 0
            
            for balance in account['balances']:
                asset = balance['asset']
                if asset in [base_asset, quote_asset]:
                    free_balance = float(balance['free'])
                    locked_balance = float(balance.get('locked', 0))
                    total_balance = free_balance + locked_balance
                    
                    if asset == base_asset:
                        base_free = free_balance
                        base_locked = locked_balance
                    elif asset == quote_asset:
                        quote_free = free_balance
                        quote_locked = locked_balance
                    
                    logger.info(f"[BALANCE] Real Binance: {asset}: free={free_balance:.8f}, locked={locked_balance:.8f}, total={total_balance:.8f}")

            # Compute active Auto-Buy allocations for quote_asset to protect reserved funds
            reservations = []
            quote_reserved = 0.0
            seen_symbols = set()

            try:
                portfolio_auto_buys = Coin.query.filter(
                    Coin.user_id == current_user.id,
                    Coin.auto_buy_enabled == True,
                    Coin.auto_buy_amount > 0
                ).all()

                for c in portfolio_auto_buys:
                    sym = (c.symbol or '').upper()
                    quote_curr = (getattr(c, 'auto_buy_quote_currency', None) or 'USDT').upper()
                    amt = float(c.auto_buy_amount or 0.0)
                    if quote_curr == quote_asset and amt > 0 and sym not in seen_symbols:
                        quote_reserved += amt
                        seen_symbols.add(sym)
                        reservations.append({
                            'symbol': sym,
                            'amount': amt,
                            'quote_currency': quote_curr,
                            'source': 'portfolio'
                        })

                watchlist_auto_buys = WatchlistCoin.query.filter(
                    WatchlistCoin.user_id == current_user.id,
                    WatchlistCoin.auto_buy_enabled == True,
                    WatchlistCoin.auto_buy_amount > 0
                ).all()

                for w in watchlist_auto_buys:
                    sym = (w.symbol or '').upper()
                    quote_curr = (getattr(w, 'auto_buy_quote_currency', None) or 'USDT').upper()
                    amt = float(w.auto_buy_amount or 0.0)
                    if quote_curr == quote_asset and amt > 0 and sym not in seen_symbols:
                        quote_reserved += amt
                        seen_symbols.add(sym)
                        reservations.append({
                            'symbol': sym,
                            'amount': amt,
                            'quote_currency': quote_curr,
                            'source': 'watchlist'
                        })
            except Exception as res_err:
                logger.error(f"Error computing auto-buy reservations: {res_err}")

            quote_usable = max(0.0, round(quote_free - quote_reserved, 2))
            
            return jsonify({
                'success': True,
                'balances': {
                    'base': base_free,
                    'base_locked': base_locked,
                    'base_total': base_free + base_locked,
                    'quote': quote_free,
                    'quote_usable': quote_usable,
                    'quote_reserved_auto_buy': quote_reserved,
                    'quote_reservations': reservations,
                    'quote_locked': quote_locked,
                    'quote_total': quote_free + quote_locked,
                    'base_asset': base_asset,
                    'quote_asset': quote_asset
                },
                'test_mode': False
            })
        
    except Exception as e:
        logger.error(f"Error fetching balances for {symbol}: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/trading/open-orders', methods=['GET'])
@login_required
def get_open_orders():
    """Get all open orders including in-app auto triggers"""
    try:
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        open_orders = []
        
        if settings and settings.test_mode_enabled:
            # Get open test orders
            test_orders = TestOrder.query.filter_by(
                user_id=current_user.id
            ).filter(
                TestOrder.status.in_(['NEW', 'PARTIALLY_FILLED'])
            ).order_by(TestOrder.created_at.desc()).all()
            open_orders = [order.to_dict() for order in test_orders]
        else:
            # Get real open orders from Binance using SQLAlchemy ORM
            creds = Credential.query.filter_by(user_id=current_user.id).first()
            
            if creds and creds.trading_api_key and creds.trading_api_secret:
                from binance.client import Client
                client = Client(
                    api_key=creds.trading_api_key,
                    api_secret=creds.trading_api_secret,
                    testnet=False,
                    tld='us'
                )
                try:
                    open_orders = client.get_open_orders() or []
                except Exception as api_err:
                    err_msg = str(api_err)
                    logger.error(f"Error fetching open orders from Binance: {err_msg}")
                    # If Binance fails, we log and still return in-app auto triggers
                    open_orders = []

        formatted_open_orders = []
        for ord in open_orders:
            o_dict = ord if isinstance(ord, dict) else (ord.to_dict() if hasattr(ord, 'to_dict') else {})
            o_copy = dict(o_dict)
            status = o_copy.get('status', 'ACTIVE')
            if status in ['NEW', 'PARTIALLY_FILLED']:
                status = 'ACTIVE'
            o_copy['status'] = status
            if o_copy.get('time') and not o_copy.get('created_at'):
                try:
                    o_copy['created_at'] = datetime.fromtimestamp(o_copy['time'] / 1000, tz=timezone.utc).isoformat()
                except Exception:
                    pass
            formatted_open_orders.append(o_copy)

        # Collect active in-app Auto-Buy and Auto-Sell triggers
        auto_triggers = []
        user_portfolio_coins = Coin.query.filter_by(user_id=current_user.id).all()
        user_watchlist_coins = WatchlistCoin.query.filter_by(user_id=current_user.id).all()

        for c in user_portfolio_coins:
            ref_price = float(getattr(c, 'current', 0.0) or getattr(c, 'current_price', 0.0) or 0.0)
            if getattr(c, 'auto_buy_enabled', False):
                quote = (getattr(c, 'auto_buy_quote_currency', None) or 'USDT').upper()
                pair_sym = f"{c.symbol}{quote}"
                vol = float(c.auto_buy_volatility_pct or c.volatility_pct or 0.0)
                amt = float(getattr(c, 'auto_buy_amount', 0.0) or 0.0)
                trigger_price = round(ref_price * (1.0 + vol / 100.0), 6) if ref_price > 0 and vol > 0 else None
                auto_triggers.append({
                    'id': f"autobuy-portfolio-{c.id}",
                    'orderId': f"autobuy-portfolio-{c.id}",
                    'order_id': f"autobuy-portfolio-{c.id}",
                    'symbol': pair_sym,
                    'base_symbol': c.symbol,
                    'side': 'AUTO_BUY',
                    'type': 'AUTO_BUY',
                    'order_type': 'AUTO_BUY',
                    'origQty': amt,
                    'quantity': amt,
                    'price': trigger_price,
                    'trigger_price': trigger_price,
                    'executedQty': 0,
                    'filled_quantity': 0,
                    'status': 'ACTIVE',
                    'time': int(time.time() * 1000),
                    'created_at': getattr(c, 'auto_buy_triggered_at', None).replace(tzinfo=timezone.utc).isoformat() if getattr(c, 'auto_buy_triggered_at', None) else datetime.now(timezone.utc).isoformat(),
                    'is_auto_trigger': True,
                    'trigger_type': 'auto_buy',
                    'table_type': 'portfolio',
                    'trigger_details': f"+{vol}% surge @ ${trigger_price:.4f} (${amt:.2f} {quote})" if trigger_price else f"+{vol}% surge trigger (${amt:.2f} {quote})"
                })
            if getattr(c, 'auto_sell_enabled', False):
                quote = (getattr(c, 'auto_sell_quote_currency', None) or 'USDT').upper()
                pair_sym = f"{c.symbol}{quote}"
                vol = float(c.auto_sell_volatility_pct or c.volatility_pct or 0.0)
                amt = float(getattr(c, 'amount', 0.0) or getattr(c, 'auto_sell_amount', 0.0) or 0.0)
                trigger_price = round(ref_price * (1.0 - vol / 100.0), 6) if ref_price > 0 and vol > 0 else None
                auto_triggers.append({
                    'id': f"autosell-portfolio-{c.id}",
                    'orderId': f"autosell-portfolio-{c.id}",
                    'order_id': f"autosell-portfolio-{c.id}",
                    'symbol': pair_sym,
                    'base_symbol': c.symbol,
                    'side': 'AUTO_SELL',
                    'type': 'AUTO_SELL',
                    'order_type': 'AUTO_SELL',
                    'origQty': amt,
                    'quantity': amt,
                    'price': trigger_price,
                    'trigger_price': trigger_price,
                    'executedQty': 0,
                    'filled_quantity': 0,
                    'status': 'ACTIVE',
                    'time': int(time.time() * 1000),
                    'created_at': getattr(c, 'auto_sell_triggered_at', None).replace(tzinfo=timezone.utc).isoformat() if getattr(c, 'auto_sell_triggered_at', None) else datetime.now(timezone.utc).isoformat(),
                    'is_auto_trigger': True,
                    'trigger_type': 'auto_sell',
                    'table_type': 'portfolio',
                    'trigger_details': f"-{vol}% drop @ ${trigger_price:.4f} for {quote}" if trigger_price else f"-{vol}% drop trigger"
                })

        for w in user_watchlist_coins:
            ref_price = float(getattr(w, 'current', 0.0) or getattr(w, 'current_price', 0.0) or 0.0)
            if getattr(w, 'auto_buy_enabled', False):
                quote = (getattr(w, 'auto_buy_quote_currency', None) or 'USDT').upper()
                pair_sym = f"{w.symbol}{quote}"
                vol = float(w.auto_buy_volatility_pct or w.volatility_pct or 0.0)
                amt = float(getattr(w, 'auto_buy_amount', 0.0) or 0.0)
                trigger_price = round(ref_price * (1.0 + vol / 100.0), 6) if ref_price > 0 and vol > 0 else None
                auto_triggers.append({
                    'id': f"autobuy-watchlist-{w.id}",
                    'orderId': f"autobuy-watchlist-{w.id}",
                    'order_id': f"autobuy-watchlist-{w.id}",
                    'symbol': pair_sym,
                    'base_symbol': w.symbol,
                    'side': 'AUTO_BUY',
                    'type': 'AUTO_BUY',
                    'order_type': 'AUTO_BUY',
                    'origQty': amt,
                    'quantity': amt,
                    'price': trigger_price,
                    'trigger_price': trigger_price,
                    'executedQty': 0,
                    'filled_quantity': 0,
                    'status': 'ACTIVE',
                    'time': int(time.time() * 1000),
                    'created_at': getattr(w, 'auto_buy_triggered_at', None).replace(tzinfo=timezone.utc).isoformat() if getattr(w, 'auto_buy_triggered_at', None) else datetime.now(timezone.utc).isoformat(),
                    'is_auto_trigger': True,
                    'trigger_type': 'auto_buy',
                    'table_type': 'watchlist',
                    'trigger_details': f"+{vol}% surge @ ${trigger_price:.4f} (${amt:.2f} {quote})" if trigger_price else f"+{vol}% surge trigger (${amt:.2f} {quote})"
                })
            if getattr(w, 'auto_sell_enabled', False):
                quote = (getattr(w, 'auto_sell_quote_currency', None) or 'USDT').upper()
                pair_sym = f"{w.symbol}{quote}"
                vol = float(w.auto_sell_volatility_pct or w.volatility_pct or 0.0)
                amt = float(getattr(w, 'amount', 0.0) or getattr(w, 'auto_sell_amount', 0.0) or 0.0)
                trigger_price = round(ref_price * (1.0 - vol / 100.0), 6) if ref_price > 0 and vol > 0 else None
                auto_triggers.append({
                    'id': f"autosell-watchlist-{w.id}",
                    'orderId': f"autosell-watchlist-{w.id}",
                    'order_id': f"autosell-watchlist-{w.id}",
                    'symbol': pair_sym,
                    'base_symbol': w.symbol,
                    'side': 'AUTO_SELL',
                    'type': 'AUTO_SELL',
                    'order_type': 'AUTO_SELL',
                    'origQty': amt,
                    'quantity': amt,
                    'price': trigger_price,
                    'trigger_price': trigger_price,
                    'executedQty': 0,
                    'filled_quantity': 0,
                    'status': 'ACTIVE',
                    'time': int(time.time() * 1000),
                    'created_at': getattr(w, 'auto_sell_triggered_at', None).replace(tzinfo=timezone.utc).isoformat() if getattr(w, 'auto_sell_triggered_at', None) else datetime.now(timezone.utc).isoformat(),
                    'is_auto_trigger': True,
                    'trigger_type': 'auto_sell',
                    'table_type': 'watchlist',
                    'trigger_details': f"-{vol}% drop @ ${trigger_price:.4f} for {quote}" if trigger_price else f"-{vol}% drop trigger"
                })

        combined_orders = formatted_open_orders + auto_triggers
        combined_orders.sort(key=lambda o: o.get('created_at') or '', reverse=True)
        return jsonify({
            'success': True,
            'orders': combined_orders
        })
        
    except Exception as e:
        logger.error(f"Error fetching open orders: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



@portfolio_bp.route('/api/trading/test-oco-order', methods=['POST'])
@login_required
def place_test_oco_order():
    """Place a test OCO order (validates with Binance.US but doesn't execute)"""
    import traceback
    try:
        data = request.get_json()
        
        # Validate required fields for OCO
        required_fields = ['symbol', 'side', 'price', 'stopPrice', 'stopLimitPrice']
        for field in required_fields:
            if field not in data or data[field] is None or data[field] == '':
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
        has_quantity = bool(data.get('quantity'))
        has_quote = bool(data.get('quoteQuantity') or data.get('quote_quantity') or data.get('quote_amount'))
        if not has_quantity and not has_quote:
            return jsonify({'success': False, 'error': 'Missing required field: quantity'}), 400
        
        symbol = data['symbol'].upper()
        side = data['side'].upper()  # BUY or SELL
        price = float(data['price'])
        stop_price = float(data['stopPrice'])
        stop_limit_price = float(data['stopLimitPrice'])
        stop_limit_time_in_force = data.get('stopLimitTimeInForce', 'GTC')
        
        quantity = _coerce_float(data.get('quantity'), 0.0) or 0.0
        quote_amount = _coerce_float(
            data.get('quoteQuantity') or data.get('quote_quantity') or data.get('quote_amount')
        )
        if quantity <= 0 and quote_amount and quote_amount > 0 and price > 0:
            quantity = quote_amount / price
        
        # Validate prices
        if price <= 0 or stop_price <= 0 or stop_limit_price <= 0:
            return jsonify({'success': False, 'error': 'All prices must be greater than 0'}), 400
        
        # Get Binance.US Trading credentials using SQLAlchemy ORM
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Credential model properties auto-decrypt values
        trading_api_key = creds.trading_api_key
        trading_api_secret = creds.trading_api_secret
        if not trading_api_key or not trading_api_secret:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=trading_api_key,
            api_secret=trading_api_secret,
            testnet=False,
            tld='us'
        )
        
        # Get symbol filters to format quantity properly
        filters = get_symbol_filters(client, symbol)
        if not filters:
            return jsonify({'success': False, 'error': f'Unable to get trading filters for {symbol}'}), 400
        
        # Format quantity according to LOT_SIZE filter
        formatted_quantity = format_quantity(quantity, filters['stepSize'])
        
        if formatted_quantity < filters['minQty']:
            return jsonify({'success': False, 'error': f'Quantity {formatted_quantity} is below minimum {filters["minQty"]}'}), 400
        
        if formatted_quantity > filters['maxQty']:
            return jsonify({'success': False, 'error': f'Quantity {formatted_quantity} exceeds maximum {filters["maxQty"]}'}), 400
        
        # Update quantity and prices to formatted values
        quantity = formatted_quantity
        price = format_price(price, filters['tickSize'])
        stop_price = format_price(stop_price, filters['tickSize'])
        stop_limit_price = format_price(stop_limit_price, filters['tickSize'])
        
        # Get current market price for simulation
        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            current_price = float(ticker['price'])
        except Exception as e:
            logger.error(f"Failed to get current price for {symbol}: {e}")
            current_price = price

        # Pre-validate price collars
        from services.binance_service import validate_order_price_collar
        for p_val, p_name in [(price, 'Limit Price'), (stop_price, 'Stop Price'), (stop_limit_price, 'Stop Limit Price')]:
            valid, collar_err = validate_order_price_collar(p_val, side, current_price, filters, symbol)
            if not valid:
                return jsonify({'success': False, 'error': f'{p_name}: {collar_err}'}), 400
        
        # Validate price relationships
        if side == 'SELL':
            if not (price > current_price > stop_price):
                return jsonify({'success': False, 'error': 'For SELL OCO: Limit Price > Market Price > Stop Price'}), 400
        else:  # BUY
            if not (price < current_price < stop_price):
                return jsonify({'success': False, 'error': 'For BUY OCO: Limit Price < Market Price < Stop Price'}), 400
        
        # Use API-provided fees when possible
        fee_info = get_trade_fee_for_symbol(client, symbol) or {'maker': 0.001, 'taker': 0.001}
        # For simulation assume taker fee for immediate fills
        fee_rate = fee_info.get('taker', 0.001)

        # Balance check: ensure user has enough quote asset for BUY, or enough base asset for SELL
        try:
            account_info = client.get_account()
            balances = {b['asset']: float(b['free']) for b in account_info.get('balances', [])}
        except Exception:
            balances = {}

        if side == 'BUY':
            if symbol.endswith('USD') and not symbol.endswith('USDT'):
                quote_asset = 'USD'
            else:
                quote_asset = 'USDT'
            available_quote = balances.get(quote_asset, 0.0)
            check_price = max(price, stop_limit_price)
            required_quote = quantity * check_price
            estimated_fee = required_quote * fee_rate

            if available_quote is not None and (required_quote + estimated_fee) > available_quote:
                step = filters['stepSize']
                from decimal import Decimal
                qty_dec = Decimal(str(quantity))
                step_dec = Decimal(str(step))
                price_dec = Decimal(str(check_price))
                fee_rate_dec = Decimal(str(fee_rate))
                min_qty = Decimal(str(filters['minQty']))

                while qty_dec >= min_qty:
                    req = qty_dec * price_dec
                    fee_est = req * fee_rate_dec
                    if (req + fee_est) <= Decimal(str(available_quote)):
                        break
                    qty_dec -= step_dec

                if qty_dec < min_qty:
                    return jsonify({'success': False, 'error': f'Insufficient {quote_asset} balance to place OCO buy order.'}), 400

                quantity = float(format_quantity(float(qty_dec), filters['stepSize']))
        elif side == 'SELL':
            base_asset = symbol.replace('USDT', '').replace('USD', '')
            available_base = balances.get(base_asset, 0.0)
            if available_base is not None and quantity > available_base:
                adjusted_quantity = float(format_quantity(available_base, filters['stepSize']))
                if adjusted_quantity < filters['minQty']:
                    return jsonify({'success': False, 'error': f'Insufficient {base_asset} balance. Available: {available_base:.8f}'}), 400
                quantity = adjusted_quantity

        # Create test order records (OCO creates 2 orders)
        # Limit order (simulate filled leg)
        limit_order = TestOrder(
            user_id=current_user.id,
            symbol=symbol,
            side=side,
            type='LIMIT_MAKER',  # Fixed: use 'type' not 'order_type'
            quantity=quantity,
            price=price,
            status='FILLED',  # Simulate immediate fill
            simulated_fill_price=price,
            simulated_fill_time=datetime.utcnow(),
            created_at=datetime.utcnow()
        )

        # Stop limit order (not filled in simulation, cancelled by limit fill)
        stop_order = TestOrder(
            user_id=current_user.id,
            symbol=symbol,
            side=side,
            type='STOP_LOSS_LIMIT',  # Fixed: use 'type' not 'order_type'
            quantity=quantity,
            price=stop_limit_price,
            stop_price=stop_price,
            status='CANCELED',  # Other leg cancelled in OCO
            created_at=datetime.utcnow()
        )
        
        db.session.add(limit_order)
        db.session.add(stop_order)
        
        # Update test portfolio (only for the filled leg)
        update_test_portfolio(current_user.id, symbol, side, quantity, price)
        
        db.session.commit()
        
        logger.info(f"Test OCO order placed for user {current_user.id}: {symbol} {side} {quantity}")
        
        return jsonify({
            'success': True,
            'orders': [limit_order.to_dict(), stop_order.to_dict()],
            'message': 'Test OCO order validated and simulated successfully'
        })
        
    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error placing test OCO order: {err_msg}\n{traceback.format_exc()}")
        db.session.rollback()
        if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
            return jsonify({
                'success': False,
                'error': 'Invalid Binance API credentials',
                'error_code': 'invalid_trading_credentials'
            }), 400
        return jsonify({'success': False, 'error': err_msg}), 500



@portfolio_bp.route('/api/trading/oco-order', methods=['POST'])
@login_required
def place_real_oco_order():
    """Place a real OCO order on Binance.US"""
    import traceback
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['symbol', 'side', 'price', 'stopPrice', 'stopLimitPrice']
        for field in required_fields:
            if field not in data or data[field] is None or data[field] == '':
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
        has_quantity = bool(data.get('quantity'))
        has_quote = bool(data.get('quoteQuantity') or data.get('quote_quantity') or data.get('quote_amount'))
        if not has_quantity and not has_quote:
            return jsonify({'success': False, 'error': 'Missing required field: quantity'}), 400
        
        symbol = data['symbol'].upper()
        side = data['side'].upper()
        price = float(data['price'])
        stop_price = float(data['stopPrice'])
        stop_limit_price = float(data['stopLimitPrice'])
        stop_limit_time_in_force = data.get('stopLimitTimeInForce', 'GTC')
        
        quantity = _coerce_float(data.get('quantity'), 0.0) or 0.0
        quote_amount = _coerce_float(
            data.get('quoteQuantity') or data.get('quote_quantity') or data.get('quote_amount')
        )
        if quantity <= 0 and quote_amount and quote_amount > 0 and price > 0:
            quantity = quote_amount / price
        
        # Validate prices
        if price <= 0 or stop_price <= 0 or stop_limit_price <= 0:
            return jsonify({'success': False, 'error': 'All prices must be greater than 0'}), 400
        
        # Get Binance.US Trading credentials using SQLAlchemy ORM
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Credential model properties auto-decrypt values
        trading_api_key = creds.trading_api_key
        trading_api_secret = creds.trading_api_secret
        if not trading_api_key or not trading_api_secret:
            return jsonify({
                'success': False,
                'error': 'No Binance.US trading credentials found.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=trading_api_key,
            api_secret=trading_api_secret,
            testnet=False,
            tld='us'
        )
        
        # Get symbol filters to format quantity properly
        filters = get_symbol_filters(client, symbol)
        if not filters:
            return jsonify({'success': False, 'error': f'Unable to get trading filters for {symbol}'}), 400
        
        # Format quantity according to LOT_SIZE filter
        formatted_quantity = format_quantity(quantity, filters['stepSize'])
        
        if formatted_quantity < filters['minQty']:
            return jsonify({'success': False, 'error': f'Quantity {formatted_quantity} is below minimum {filters["minQty"]}'}), 400
        
        if formatted_quantity > filters['maxQty']:
            return jsonify({'success': False, 'error': f'Quantity {formatted_quantity} exceeds maximum {filters["maxQty"]}'}), 400
        
        # Update quantity and prices to formatted values
        quantity = formatted_quantity
        price = format_price(price, filters['tickSize'])
        stop_price = format_price(stop_price, filters['tickSize'])
        stop_limit_price = format_price(stop_limit_price, filters['tickSize'])

        # Get current market price for pre-validations
        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            current_price = float(ticker['price'])
        except Exception as e:
            logger.error(f"Failed to get current price for {symbol}: {e}")
            current_price = price

        # Pre-validate price collars
        from services.binance_service import validate_order_price_collar
        for p_val, p_name in [(price, 'Limit Price'), (stop_price, 'Stop Price'), (stop_limit_price, 'Stop Limit Price')]:
            valid, collar_err = validate_order_price_collar(p_val, side, current_price, filters, symbol)
            if not valid:
                return jsonify({'success': False, 'error': f'{p_name}: {collar_err}'}), 400
        
        # Balance validation before submitting OCO order
        if side == 'BUY':
            try:
                # Properly extract quote asset
                if symbol.endswith('USD') and not symbol.endswith('USDT'):
                    quote_asset = 'USD'
                else:
                    quote_asset = 'USDT'

                account = client.get_account()
                available_balance = 0.0
                for balance in account.get('balances', []):
                    if balance['asset'] == quote_asset:
                        available_balance = float(balance['free'])
                        break

                fee_info = get_trade_fee_for_symbol(client, symbol) or {'maker': 0.001, 'taker': 0.001}
                fee_rate = float(fee_info.get('taker', 0.001))

                # For OCO buy, we must afford the most expensive of the two legs
                check_price = max(price, stop_limit_price)
                required_balance = quantity * check_price * (1.0 + fee_rate + 0.001)

                logger.info(f"OCO Buy Balance Check: Available {quote_asset}: {available_balance:.8f}, Required: {required_balance:.8f}")

                if required_balance > available_balance:
                    max_affordable_quantity = (available_balance * 0.999) / (check_price * (1.0 + fee_rate))
                    adjusted_quantity = format_quantity(max_affordable_quantity, filters['stepSize'])

                    if adjusted_quantity >= filters['minQty']:
                        logger.warning(f"Adjusted OCO buy quantity from {quantity} to {adjusted_quantity} due to balance constraints")
                        quantity = adjusted_quantity
                    else:
                        return jsonify({
                            'success': False,
                            'error': f'Insufficient {quote_asset} balance to place buy order. Available: {available_balance:.8f}, Required: {required_balance:.8f} (including fees)'
                        }), 400
            except Exception as balance_err:
                logger.error(f"OCO buy balance check failed: {balance_err}")
        elif side == 'SELL':
            try:
                base_asset = symbol.replace('USDT', '').replace('USD', '')
                account = client.get_account()
                available_base = 0.0
                for balance in account.get('balances', []):
                    if balance['asset'] == base_asset:
                        available_base = float(balance['free'])
                        break

                logger.info(f"OCO Sell Balance Check: Available {base_asset}: {available_base:.8f}, Required: {quantity:.8f}")

                if quantity > available_base:
                    adjusted_quantity = format_quantity(available_base, filters['stepSize'])
                    if adjusted_quantity >= filters['minQty']:
                        logger.warning(f"Adjusted OCO sell quantity from {quantity} to {adjusted_quantity} to match available {base_asset} balance")
                        quantity = adjusted_quantity
                    else:
                        return jsonify({
                            'success': False,
                            'error': f'Insufficient {base_asset} balance to place sell order. Available: {available_base:.8f}, Required: {quantity:.8f}'
                        }), 400
            except Exception as balance_err:
                logger.error(f"OCO sell base balance check failed: {balance_err}")

        # Place real OCO order on Binance.US
        try:
            order_response = client.create_oco_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                stopPrice=stop_price,
                stopLimitPrice=stop_limit_price,
                stopLimitTimeInForce=stop_limit_time_in_force
            )
            
            # Save both legs of the OCO to database
            order_list_id = order_response['orderListId']
            
            # Save both legs of the OCO to database - avoid invalid kwarg 'binance_order_list_id'
            for order_report in order_response.get('orderReports', []):
                ro = RealOrder(
                    user_id=current_user.id,
                    binance_order_id=order_report.get('orderId'),
                    symbol=order_report.get('symbol'),
                    side=order_report.get('side'),
                    type=order_report.get('type'),
                    quantity=float(order_report.get('origQty', 0)),
                    price=float(order_report.get('price')) if float(order_report.get('price', 0) or 0) > 0 else None,
                    stop_price=float(order_report.get('stopPrice')) if float(order_report.get('stopPrice', 0) or 0) > 0 else None,
                    status=order_report.get('status'),
                    executed_qty=float(order_report.get('executedQty', 0)),
                    commission=0,
                    order_response=str(order_report),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.session.add(ro)
            
            db.session.commit()
            trigger_portfolio_snapshot(current_user.id, current_user.username)
            
            logger.info(f"Real OCO order placed for user {current_user.id}: {symbol} {side} {quantity}")
            
            return jsonify({
                'success': True,
                'orderListId': order_list_id,
                'orders': order_response['orderReports'],
                'message': 'Real OCO order placed successfully'
            })
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to place real OCO order: {error_msg}\n{traceback.format_exc()}")
            if "API-key" in error_msg or "Invalid Api-Key" in error_msg or "invalid api-key" in error_msg.lower():
                return jsonify({
                    'success': False,
                    'error': 'Invalid Binance API credentials',
                    'error_code': 'invalid_trading_credentials'
                }), 400
            if 'PERCENT_PRICE' in error_msg:
                mult_up = filters.get('multiplierUp', 5.0)
                mult_down = filters.get('multiplierDown', 0.2)
                return jsonify({
                    'success': False,
                    'error': f'Price filter failure (PERCENT_PRICE): Binance.US restricts order prices to within {mult_down}x - {mult_up}x of current market price (${current_price:,.6f}) for {symbol}. Please adjust your price closer to market value.'
                }), 400
            if 'MIN_NOTIONAL' in error_msg or 'NOTIONAL' in error_msg:
                return jsonify({
                    'success': False,
                    'error': f"Order value too small. Minimum required order value for {symbol} is ${filters.get('minNotional', 10):.2f}."
                }), 400
            if 'LOT_SIZE' in error_msg:
                return jsonify({
                    'success': False,
                    'error': f"Invalid quantity. Quantity must be between {filters.get('minQty')} and {filters.get('maxQty')} in steps of {filters.get('stepSize')}."
                }), 400
            if 'PRICE_FILTER' in error_msg:
                return jsonify({
                    'success': False,
                    'error': f"Invalid price. Price must be between {filters.get('minPrice')} and {filters.get('maxPrice')} in increments of {filters.get('tickSize')}."
                }), 400
            if 'INSUFFICIENT_BALANCE' in error_msg or 'Account has insufficient balance' in error_msg:
                return jsonify({
                    'success': False,
                    'error': 'Insufficient balance in your Binance.US account to execute this OCO order.'
                }), 400
            return jsonify({'success': False, 'error': f'OCO order placement failed: {error_msg}'}), 400

    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error in place_real_oco_order: {err_msg}\n{traceback.format_exc()}")
        db.session.rollback()
        if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
            return jsonify({
                'success': False,
                'error': 'Invalid Binance API credentials',
                'error_code': 'invalid_trading_credentials'
            }), 400
        return jsonify({'success': False, 'error': err_msg}), 500

@portfolio_bp.route("/api/sync-coins", methods=["POST"])
@login_required
def api_sync_coins():
    """
    MANUAL SYNC: Backfill 7 days of historical price data for existing coins in portfolio.
    Used for recovery when automatic hourly collection missed intervals or after app downtime.
    Does NOT modify portfolio holdings - only updates price data.
    """
    try:
        logger.info(f"Starting price sync for user {current_user.id}")
        
        # Get existing coins from user's portfolio (including hidden ones for recovery)
        coins = Coin.query.filter_by(user_id=current_user.id).all()
        if not coins:
            logger.info(f"Portfolio empty for user {current_user.id}. Attempting initial sync from Binance.")
            success, message = sync_portfolio_from_binance(current_user.id)
            if success:
                coins = Coin.query.filter_by(user_id=current_user.id).all()
            
            if not coins:
                return jsonify({
                    "success": False,
                    "error": "No coins in portfolio. Add some coins first, then sync prices."
                })
        
        symbols = list({c.symbol.upper() for c in coins})
        logger.info(f"Syncing price history for {len(symbols)} symbols: {symbols}")
        
        synced_count = 0
        
        # Update price history for each symbol
        for symbol in symbols:
            try:
                # Delete existing price history for this symbol
                try:
                    PriceHistory.query.filter_by(symbol=symbol.upper()).delete()
                    db.session.commit()
                except Exception as e:
                    logger.error(f"Error clearing price history for {symbol}: {e}")
                    db.session.rollback()
                
                # Use Binance only for price history
                try:
                    ensure_price_history(symbol)  # Fetch/store 7 days of hourly history for this symbol
                    logger.info(f"Backfill completed for {symbol}")
                    synced_count += 1
                except Exception as e:
                    logger.warning(f"Binance price fetch failed for {symbol}: {e}")
            
            except Exception as e:
                logger.error(f"Error updating price history for {symbol}: {str(e)}")
                continue
        
        return jsonify({
            "success": True,
            "message": f"Successfully updated price history for {synced_count} of {len(symbols)} coins"
        })
        
    except Exception as e:
        logger.error(f"Error in api_sync_coins: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "error": f"Price sync failed: {str(e)}"
        })

@portfolio_bp.route("/api/unhide-all", methods=["POST"])
@login_required
def unhide_all():
    data = request.get_json()
    coin_ids = data.get('coin_ids', [])
    
    if not coin_ids:
        return jsonify({"success": False, "error": "No coins selected"})
    
    # Only unhide the selected coins
    Coin.query.filter(
        Coin.user_id == current_user.id,
        Coin.hidden.is_(True),
        Coin.id.in_(coin_ids)
    ).update(
        {
            Coin.hidden: False,
            Coin.auto_hidden: False,
            Coin.force_visible: True
        },
        synchronize_session=False
    )
    
    db.session.commit()
    return jsonify({"success": True})

@portfolio_bp.route('/api/tax/manual-investment', methods=['GET', 'POST'])
@login_required
def api_tax_manual_investment():
    try:
        if request.method == 'GET':
            amount = get_manual_tax_investment(current_user.id)
            return jsonify({
                'success': True,
                'amount': amount
            })

        data = request.get_json(force=True, silent=True) or {}
        amount = _coerce_float(data.get('amount'), 0.0) or 0.0
        updated_amount, updated_at = set_manual_tax_investment(current_user.id, amount)
        return jsonify({
            'success': True,
            'amount': updated_amount,
            'updated_at': updated_at
        })
    except Exception as e:
        logger.error(f"Manual tax investment update failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to update manual investment amount'}), 500

@portfolio_bp.route('/api/tax-report')
@login_required
def api_tax_report():
    """Generate comprehensive tax report with cost basis and gain/loss calculations"""
    try:
        from trading_models import AllActivity
        from models import Coin
        # Use actual Binance balances from coins table, not calculated transaction totals
        # sync_coins_from_transactions() overwrites correct balances with wrong calculated amounts
        
        # Get all completed transactions using ORM
        activities = AllActivity.query.filter(
            AllActivity.user_id == current_user.id,
            AllActivity.status.in_(['FILLED', 'completed'])
        ).order_by(AllActivity.date.asc()).all()
        
        # Convert to list of dictionaries
        transactions = []
        for activity in activities:
            tx_dict = {
                'id': activity.id,
                'date': activity.date,
                'type': activity.type,
                'asset': activity.asset,
                'amount': activity.amount,
                'proceeds': activity.proceeds,
                'cost_basis': activity.cost_basis,
                'gain_loss': activity.gain_loss,
                'fee': activity.fee,
                'txid': activity.txid,
                'status': activity.status,
                'details': activity.details,
                'price_sold_at': activity.price_sold_at,
                'exchange': activity.exchange or 'coinbase'  # Default to coinbase for legacy records
            }
            transactions.append(tx_dict)
        
        # Calculate tax information for each transaction for table display
        tax_data = []
        for tx in transactions:
            asset = tx['asset']
            tx_type = tx['type']
            amount = float(tx['amount'] or 0)
            proceeds = float(tx['proceeds'] or 0)
            fee = float(tx['fee'] or 0)
            date = tx['date']
            
            cost_basis_val = float(tx['cost_basis'] or 0)
            gain_loss_val = float(tx['gain_loss']) if tx['gain_loss'] is not None else None
            if gain_loss_val is None and tx_type == 'SELL' and (proceeds > 0 or cost_basis_val > 0):
                gain_loss_val = (proceeds - fee) - cost_basis_val if proceeds > 0 else -cost_basis_val

            tax_info = {
                'id': tx['id'],
                'date': _format_activity_date(tx['date']),
                'type': tx_type,
                'asset': asset,
                'amount': amount,
                'proceeds': proceeds,
                'fee': fee,
                'txid': tx['txid'],
                'cost_basis': cost_basis_val,
                'gain_loss': gain_loss_val,
                'gain_loss_type': 'short_term' if (gain_loss_val is not None and gain_loss_val >= 0) else ('loss' if (gain_loss_val is not None and gain_loss_val < 0) else None),
                'price_sold_at': tx.get('price_sold_at'),  # USDT price at sale/purchase
                'exchange': tx.get('exchange', 'coinbase')  # Exchange source
            }
            
            tax_data.append(tax_info)
        
        # Get actual current holdings from the coins table (which reflects real balances)
        current_coins = Coin.query.filter_by(user_id=current_user.id, hidden=False).all()

        performance = _calculate_portfolio_performance(transactions, current_coins)
        current_holdings = performance['holdings_map']
        portfolio_holdings_value = float(performance['holdings_value'])
        portfolio_holdings_cost = performance['holdings_cost']

        staking_active_value = 0.0
        staking_pending_value = 0.0
        try:
            username = getattr(current_user, 'username', None)
            cred = get_user_credentials(username) if username else None
            # Only attempt if we have credentials to avoid ValueError spam
            if cred and (cred.api_key or cred.openai_key or cred.zai_key):
                 # Try-catch specifically for the configuration error
                try:
                    staking_active_value, staking_pending_value = calculate_staking_value_for_user(
                        cred,
                        current_user.id
                    )
                except ValueError as ve:
                    # Expected if keys are missing/invalid
                    logger.warning(f"Skipping staking value for tax report: {ve}")
                    staking_active_value = 0.0
                    staking_pending_value = 0.0
            else:
                 staking_active_value = 0.0
                 staking_pending_value = 0.0

        except Exception as staking_err:
            logger.error(f"Tax report staking valuation error: {staking_err}", exc_info=True)
            staking_active_value = 0.0
            staking_pending_value = 0.0

        total_staking_value = staking_active_value + staking_pending_value
        combined_holdings_value = portfolio_holdings_value + total_staking_value

        manual_invested = get_manual_tax_investment(current_user.id)
        user_setting_for_tax = UserSetting.query.filter_by(user_id=current_user.id).first()
        manual_updated_at = None  # This field is deprecated in new schema

        # Calculate summary statistics for the table/meta data
        valid_transactions = [t for t in tax_data if t['gain_loss'] is not None]
        sell_transactions = [t for t in valid_transactions if t['type'] == 'SELL']
        
        # Calculate total gain/loss as: Current Holdings Value - (Manual Contributions + Total Fees)
        total_gain_loss = combined_holdings_value - (manual_invested + performance['total_fees_paid'])

        summary = {
            'total_transactions': len(tax_data),  # Total including orphaned
            'valid_transactions': len(valid_transactions),  # Only those with proper cost basis
            'total_buys': len([t for t in tax_data if t['type'] == 'BUY']),
            'total_sells': len([t for t in tax_data if t['type'] == 'SELL']),
            'valid_sells': len(sell_transactions),  # Only sells with cost basis
            'excluded_sells': len([t for t in tax_data if t['type'] == 'SELL' and t['gain_loss'] is None]),
            'total_gifts': len([t for t in tax_data if t['type'] in ['GIFT', 'BONUS', 'TRANSFER', 'RECEIVE']]),
            'total_gain_loss': total_gain_loss,
            'realized_gain': performance['realized_pnl'],
            'unrealized_gain': performance['unrealized_pnl'],
            'manual_invested_amount': manual_invested,
            'manual_invested_updated_at': manual_updated_at,
            'tracked_cost_basis': portfolio_holdings_cost,
            'current_holdings_value': combined_holdings_value,
            'current_holdings_cost_basis': portfolio_holdings_cost,
            'portfolio_holdings_value': portfolio_holdings_value,
            'staking_active_value': staking_active_value,
            'staking_pending_value': staking_pending_value,
            'staking_total_value': total_staking_value,
            'total_fees_paid': performance['total_fees_paid'],
            'total_buy_volume': performance['total_buy_cost'],
            'total_sell_proceeds': performance['total_sell_proceeds'],
            'assets_traded': list(set(t['asset'] for t in tax_data)),
            'assets_with_current_holdings': len(current_holdings),
            'date_range': {
                'start': min(t['date'] for t in tax_data) if tax_data else None,
                'end': max(t['date'] for t in tax_data) if tax_data else None
            }
        }
        
        return jsonify({
            'transactions': tax_data,
            'summary': summary,
            'current_holdings': current_holdings,
            'fifo_lots': performance['fifo_lots']
        })
        
    except Exception as e:
        logger.error(f"Error generating tax report: {str(e)}")
        return jsonify({"error": "Failed to generate tax report"}), 500

@portfolio_bp.route("/api/hide-coin", methods=["POST"])
@login_required
def hide_coin():
    data = request.get_json()
    coin_id = data.get("coin_id") or data.get("id")  # Support both coin_id and id
    hidden = data.get("hidden", True)
    
    logger.info(f"Hide coin request: coin_id={coin_id}, hidden={hidden}, user_id={current_user.id}")
    
    coin = None
    if coin_id is not None:
        try:
            coin = Coin.query.filter_by(id=int(coin_id), user_id=current_user.id).first()
        except (ValueError, TypeError):
            pass
    if not coin:
        sym = data.get('symbol') or (str(coin_id) if isinstance(coin_id, str) and not coin_id.isdigit() else None)
        if sym:
            sym_clean = str(sym).upper()
            from models import WebullHolding
            wb_holding = WebullHolding.query.filter_by(symbol=sym_clean, user_id=current_user.id).first()
            if wb_holding:
                wb_holding.hidden = hidden
                db.session.commit()
                return jsonify({"success": True})
            coin = Coin.query.filter_by(symbol=sym_clean, user_id=current_user.id).first()
            if not coin:
                coin = Coin(symbol=sym_clean, user_id=current_user.id, hidden=hidden, amount=0.0)
                db.session.add(coin)
                db.session.commit()
                return jsonify({"success": True})
    if coin:
        logger.info(f"Found coin: {coin.symbol}, current hidden status: {coin.hidden}")
        coin.hidden = hidden
        if hidden:  # Automatically disable alerts when hiding
            coin.alert_enabled = False
            coin.force_visible = False
            coin.auto_hidden = False
            coin.auto_sell_enabled = False
            coin.auto_buy_enabled = False
        else:
            coin.auto_hidden = False
            coin.force_visible = True
        db.session.commit()
        logger.info(f"Coin {coin.symbol} hidden status updated to: {coin.hidden}")
        # If unhidden, trigger backfill for this coin
        if not hidden:
            _run_price_history_backfill_bg([coin.symbol])
        return jsonify({"success": True})
    else:
        logger.error(f"Coin not found: coin_id={coin_id}, user_id={current_user.id}")
    return jsonify({"success": False, "error": "Coin not found"}), 404

@portfolio_bp.route("/api/set-favorite", methods=["POST"])
@login_required
def set_favorite():
    data = request.get_json()
    coin_id = data.get("id")
    favorite = data.get("favorite", False)
    coin = Coin.query.filter_by(id=coin_id, user_id=current_user.id).first()
    if coin:
        coin.is_manual = favorite  # Assuming `is_manual` is used for favorite
        db.session.commit()
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Coin not found"}), 404

@portfolio_bp.route("/api/delete-coin", methods=["POST"])
@login_required
def api_delete_coin():
    data = request.get_json()
    coin_id = data.get("id")
    coin = Coin.query.filter_by(id=coin_id, user_id=current_user.id).first()
    if coin:
        db.session.delete(coin)
        db.session.commit()
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Coin not found"}), 404

@portfolio_bp.route("/api/watchlist")
@login_required
def api_watchlist():
    wl = WatchlistCoin.query.filter_by(user_id=current_user.id, hidden=False).all()
    news_cache = get_user_latest_news_cache(current_user.id)
    try:
        from routes.market import _get_binance_24h_tickers
        ticker_map = _get_binance_24h_tickers()
    except Exception:
        ticker_map = {}
    
    # Use stored current prices for instant response
    watchlist_data = []
    for w in wl:
        current_price = w.current_price or 0.0
        w_sym = (w.symbol or '').upper()
        w_news = news_cache.get(w.id) or news_cache.get(w_sym) or {}
        ticker_info = ticker_map.get(f"{w_sym}USDT") or ticker_map.get(f"{w_sym}USD") or {}
        high_24h = float(ticker_info['highPrice']) if ticker_info.get('highPrice') else None
        low_24h = float(ticker_info['lowPrice']) if ticker_info.get('lowPrice') else None
        volume_24h = float(ticker_info.get('quoteVolume') or ticker_info.get('volume') or 0.0) if (ticker_info.get('quoteVolume') or ticker_info.get('volume')) else None
        change_24h = float(ticker_info['priceChangePercent']) if ticker_info.get('priceChangePercent') else None
        
        watchlist_data.append({
            "id": w.id,
            "symbol": w.symbol,
            "asset_type": getattr(w, 'asset_type', 'crypto') or 'crypto',
            "alert_enabled": w.alert_enabled,
            "down_val": w.down_alert,
            "up_val": w.up_alert,
            "note": w.note,
            "favorite": w.favorite,
            "hidden": w.hidden,
            "action": "Watch",  # Simplified to avoid database locks
            "current_price": current_price,
            "high_24h": high_24h,
            "low_24h": low_24h,
            "volume_24h": volume_24h,
            "change_24h": change_24h,
            "sentiment": w.sentiment or "Watch",
            "sentiment_reason": getattr(w, 'sentiment_reason', "") or "",
            "sentiment_last_updated": w.sentiment_last_updated.isoformat() if getattr(w, 'sentiment_last_updated', None) else None,
            "sentiment_provider": getattr(w, 'sentiment_provider', None),
            "sentiment_model": getattr(w, 'sentiment_model', None),
            "sentiment_tier": getattr(w, 'sentiment_tier', None),
            "sentiment_search_status": getattr(w, 'sentiment_search_status', None),
            "sentiment_tracking_enabled": getattr(w, 'sentiment_tracking_enabled', True) is not False,
            "volatility_pct": w.volatility_pct,
            "auto_sell_enabled": getattr(w, 'auto_sell_enabled', False),
            "auto_sell_volatility_pct": getattr(w, 'auto_sell_volatility_pct', None),
            "auto_sell_quote_currency": getattr(w, 'auto_sell_quote_currency', 'USDT') or 'USDT',
            "auto_sell_triggered_at": w.auto_sell_triggered_at.isoformat() if getattr(w, 'auto_sell_triggered_at', None) else None,
            "auto_sell_confirmation_started_at": w.auto_sell_confirmation_started_at.isoformat() if getattr(w, 'auto_sell_confirmation_started_at', None) else None,
            "auto_buy_enabled": getattr(w, 'auto_buy_enabled', False),
            "auto_buy_volatility_pct": getattr(w, 'auto_buy_volatility_pct', None),
            "auto_buy_quote_currency": getattr(w, 'auto_buy_quote_currency', 'USDT') or 'USDT',
            "auto_buy_amount": getattr(w, 'auto_buy_amount', None),
            "auto_buy_triggered_at": w.auto_buy_triggered_at.isoformat() if getattr(w, 'auto_buy_triggered_at', None) else None,
            "auto_buy_confirmation_started_at": w.auto_buy_confirmation_started_at.isoformat() if getattr(w, 'auto_buy_confirmation_started_at', None) else None,
            "cached_news": w_news.get('text', ''),
            "cached_news_date": w_news.get('created_at', None)
        })
    
    return jsonify(watchlist_data)

@portfolio_bp.route("/api/watchlist-live")
@login_required
def api_watchlist_live():
    """Live watchlist data for background refresh"""
    wl = WatchlistCoin.query.filter_by(user_id=current_user.id, hidden=False).all()
    news_cache = get_user_latest_news_cache(current_user.id)
    try:
        from routes.market import _get_binance_24h_tickers
        ticker_map = _get_binance_24h_tickers()
    except Exception:
        ticker_map = {}
    
    # Fetch current prices for all watchlist items
    watchlist_data = []
    for w in wl:
        asset_type = getattr(w, 'asset_type', 'crypto') or 'crypto'
        try:
            if asset_type == 'stock':
                current_price = _fetch_stock_price_yf(w.symbol)
            else:
                current_price = fetch_binance_price(w.symbol)
            w.current_price = current_price
        except Exception as e:
            logger.error(f"Failed to fetch price for {w.symbol}: {e}")
            current_price = w.current_price or 0.0
        
        w_sym = (w.symbol or '').upper()
        w_news = news_cache.get(w.id) or news_cache.get(w_sym) or {}
        ticker_info = ticker_map.get(f"{w_sym}USDT") or ticker_map.get(f"{w_sym}USD") or {}
        high_24h = float(ticker_info['highPrice']) if ticker_info.get('highPrice') else None
        low_24h = float(ticker_info['lowPrice']) if ticker_info.get('lowPrice') else None
        volume_24h = float(ticker_info.get('quoteVolume') or ticker_info.get('volume') or 0.0) if (ticker_info.get('quoteVolume') or ticker_info.get('volume')) else None
        change_24h = float(ticker_info['priceChangePercent']) if ticker_info.get('priceChangePercent') else None

        watchlist_data.append({
            "id": w.id,
            "symbol": w.symbol,
            "asset_type": asset_type,
            "alert_enabled": w.alert_enabled,
            "down_val": w.down_alert,
            "up_val": w.up_alert,
            "note": w.note,
            "favorite": w.favorite,
            "hidden": w.hidden,
            "action": "Watch",
            "current_price": current_price,
            "high_24h": high_24h,
            "low_24h": low_24h,
            "volume_24h": volume_24h,
            "change_24h": change_24h,
            "sentiment": w.sentiment or "Watch",
            "sentiment_reason": getattr(w, 'sentiment_reason', "") or "",
            "sentiment_last_updated": w.sentiment_last_updated.isoformat() if getattr(w, 'sentiment_last_updated', None) else None,
            "sentiment_provider": getattr(w, 'sentiment_provider', None),
            "sentiment_model": getattr(w, 'sentiment_model', None),
            "sentiment_tier": getattr(w, 'sentiment_tier', None),
            "sentiment_search_status": getattr(w, 'sentiment_search_status', None),
            "sentiment_tracking_enabled": getattr(w, 'sentiment_tracking_enabled', True) is not False,
            "volatility_pct": w.volatility_pct,
            "auto_sell_enabled": getattr(w, 'auto_sell_enabled', False),
            "auto_sell_volatility_pct": getattr(w, 'auto_sell_volatility_pct', None),
            "auto_sell_quote_currency": getattr(w, 'auto_sell_quote_currency', 'USDT') or 'USDT',
            "auto_sell_triggered_at": w.auto_sell_triggered_at.isoformat() if getattr(w, 'auto_sell_triggered_at', None) else None,
            "auto_sell_confirmation_started_at": w.auto_sell_confirmation_started_at.isoformat() if getattr(w, 'auto_sell_confirmation_started_at', None) else None,
            "auto_buy_enabled": getattr(w, 'auto_buy_enabled', False),
            "auto_buy_volatility_pct": getattr(w, 'auto_buy_volatility_pct', None),
            "auto_buy_quote_currency": getattr(w, 'auto_buy_quote_currency', 'USDT') or 'USDT',
            "auto_buy_amount": getattr(w, 'auto_buy_amount', None),
            "auto_buy_triggered_at": w.auto_buy_triggered_at.isoformat() if getattr(w, 'auto_buy_triggered_at', None) else None,
            "auto_buy_confirmation_started_at": w.auto_buy_confirmation_started_at.isoformat() if getattr(w, 'auto_buy_confirmation_started_at', None) else None,
            "cached_news": w_news.get('text', ''),
            "cached_news_date": w_news.get('created_at', None)
        })
    
    try:
        db.session.commit()
    except Exception as e:
        logger.error(f"Failed to commit watchlist price updates: {e}")
    
    return jsonify(watchlist_data)

@portfolio_bp.route("/api/watchlist/search-symbol")
@login_required
def api_watchlist_search_symbol():
    """Search for stocks/ETFs and crypto pairs to add to the watchlist.
    Returns combined results tagged with asset_type ('stock' or 'crypto').
    """
    q = (request.args.get('q') or '').strip().upper()
    if not q or len(q) < 1:
        return jsonify({"results": []})

    results = []
    seen = set()  # (symbol, asset_type)

    # --- Crypto: check against Binance.US pairs ---
    try:
        # Exchange information is public data, so searching must not depend on the
        # user's API credentials.  get_cached_exchange_info requires a client; the
        # v2.38.0 picker omitted it, causing every crypto lookup to be swallowed by
        # this block's exception handler and return no results.
        from binance.client import Client
        exchange_info = get_cached_exchange_info(Client(tld='us')) or {}
        symbols_info = exchange_info.get('symbols', [])
        for sym_info in symbols_info:
            base = (sym_info.get('baseAsset') or '').upper()
            quote = (sym_info.get('quoteAsset') or '').upper()
            if quote not in ('USD', 'USDT'):
                continue
            pair = f"{base}{quote}"
            if q in base or q in pair:
                key = (base, 'crypto')
                if key not in seen:
                    seen.add(key)
                    results.append({
                        'symbol': base,
                        'display': f"{base} / {quote}",
                        'name': f"{base} Crypto",
                        'asset_type': 'crypto',
                        'pair': pair,
                    })
    except Exception as e:
        logger.warning(f"Crypto pair search error: {e}")

    # --- Stocks/ETFs: search via yfinance, with Yahoo's public search endpoint
    # as a fallback when the yfinance search client has no results. ---
    stock_results_found = False
    try:
        import yfinance as yf
        search = yf.Search(q, max_results=10, enable_fuzzy_query=True)
        quotes = search.quotes or []
        for item in quotes:
            sym = (item.get('symbol') or '').upper().strip()
            name = item.get('longname') or item.get('shortname') or sym
            q_type = (item.get('quoteType') or '').upper()
            # Only include equities and ETFs; skip crypto (handled above), futures, forex, etc.
            if q_type in ('EQUITY', 'ETF', 'MUTUALFUND') or (q_type == '' and sym):
                # Filter out obvious non-US / OTC junk
                exchange = (item.get('exchange') or '').upper()
                if exchange in ('PNK', 'OTC', 'GREY'):
                    continue
                key = (sym, 'stock')
                if sym and key not in seen:
                    seen.add(key)
                    stock_results_found = True
                    results.append({
                        'symbol': sym,
                        'display': f"{sym} — {name}",
                        'name': name,
                        'asset_type': 'stock',
                        'exchange': exchange,
                        'quote_type': q_type,
                    })
    except ImportError:
        logger.warning("yfinance not installed; stock search unavailable")
    except Exception as e:
        logger.warning(f"yfinance search error for '{q}': {e}")

    if not stock_results_found:
        try:
            response = requests.get(
                'https://query1.finance.yahoo.com/v1/finance/search',
                params={'q': q, 'quotesCount': 10, 'newsCount': 0},
                timeout=5,
            )
            response.raise_for_status()
            for item in response.json().get('quotes', []):
                sym = (item.get('symbol') or '').upper().strip()
                name = item.get('longname') or item.get('shortname') or sym
                q_type = (item.get('quoteType') or '').upper()
                exchange = (item.get('exchange') or '').upper()
                if q_type not in ('EQUITY', 'ETF', 'MUTUALFUND') or exchange in ('PNK', 'OTC', 'GREY'):
                    continue
                key = (sym, 'stock')
                if sym and key not in seen:
                    seen.add(key)
                    results.append({
                        'symbol': sym,
                        'display': f"{sym} — {name}",
                        'name': name,
                        'asset_type': 'stock',
                        'exchange': exchange,
                        'quote_type': q_type,
                    })
        except Exception as e:
            logger.warning(f"Yahoo stock search fallback error for '{q}': {e}")

    # Sort: exact symbol matches first
    results.sort(key=lambda r: (r['symbol'] != q, r['asset_type'] != 'crypto', r['symbol']))
    return jsonify({"results": results[:20]})


def _fetch_stock_price_yf(symbol):
    """Fetch the latest market price for a stock/ETF using yfinance."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        price = getattr(info, 'last_price', None) or getattr(info, 'regularMarketPrice', None)
        if price and float(price) > 0:
            return float(price)
    except Exception as e:
        logger.warning(f"yfinance price fetch failed for {symbol}: {e}")
    return 0.0


@portfolio_bp.route("/api/watchlist/add", methods=["POST"])
@login_required
def api_watchlist_add():
    data = request.get_json() or {}
    symbol = data.get("symbol", "").upper().strip()
    asset_type = (data.get("asset_type") or "crypto").strip().lower()
    if asset_type not in ("crypto", "stock"):
        asset_type = "crypto"
    if not symbol:
        return jsonify({"success": False, "error": "Missing symbol"}), 400

    exists = WatchlistCoin.query.filter_by(user_id=current_user.id, symbol=symbol).first()
    if exists:
        if exists.hidden:
            exists.hidden = False
        exists.asset_type = asset_type  # Update asset_type in case user re-adds with correct type
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Symbol added to watchlist",
            "item": {
                "id": exists.id,
                "symbol": exists.symbol,
                "asset_type": getattr(exists, 'asset_type', asset_type) or asset_type,
                "alert_enabled": exists.alert_enabled,
                "down_val": exists.down_alert,
                "up_val": exists.up_alert,
                "note": exists.note,
                "favorite": exists.favorite,
                "hidden": False,
                "action": "Watch",
                "current_price": exists.current_price or 0.0,
                "sentiment": exists.sentiment or "Watch",
                "sentiment_reason": getattr(exists, 'sentiment_reason', "") or "",
                "sentiment_last_updated": exists.sentiment_last_updated.isoformat() if getattr(exists, 'sentiment_last_updated', None) else None,
                "sentiment_provider": getattr(exists, 'sentiment_provider', None),
                "sentiment_model": getattr(exists, 'sentiment_model', None),
                "sentiment_tier": getattr(exists, 'sentiment_tier', None),
                "sentiment_search_status": getattr(exists, 'sentiment_search_status', None),
                "sentiment_tracking_enabled": getattr(exists, 'sentiment_tracking_enabled', True) is not False,
                "volatility_pct": exists.volatility_pct,
                "cached_news": "",
                "cached_news_date": None
            }
        })
    
    current_price = 0.0
    try:
        if asset_type == 'stock':
            current_price = _fetch_stock_price_yf(symbol)
        else:
            current_price = fetch_binance_price(symbol) or 0.0
    except Exception as e:
        logger.warning(f"Failed to fetch initial price for {symbol}: {e}")

    wl = WatchlistCoin(symbol=symbol, user_id=current_user.id, current_price=current_price, hidden=False, alert_enabled=False)
    wl.asset_type = asset_type
    db.session.add(wl)
    db.session.commit()

    # Trigger backfill for this symbol in a background thread
    _run_price_history_backfill_bg([symbol])

    # Trigger on-the-spot sentiment check in a background thread so add is instantaneous
    user_id = current_user.id
    username = current_user.username
    wl_id = wl.id
    app = current_app._get_current_object()

    def _run_watchlist_sentiment_bg():
        with app.app_context():
            try:
                from services.ai_service import analyze_single_symbol_sentiment
                analyze_single_symbol_sentiment(
                    user_id=user_id,
                    username=username,
                    symbol=symbol,
                    is_watchlist=True,
                    coin_id=wl_id,
                    amount=0.0
                )
            except Exception as ex:
                logger.error(f"Background watchlist sentiment check error for {symbol}: {ex}")

    threading.Thread(target=_run_watchlist_sentiment_bg, daemon=True).start()

    return jsonify({
        "success": True,
        "symbol": symbol,
        "current_price": current_price,
        "id": wl.id,
        "item": {
            "id": wl.id,
            "symbol": wl.symbol,
            "alert_enabled": wl.alert_enabled,
            "down_val": wl.down_alert,
            "up_val": wl.up_alert,
            "note": wl.note,
            "favorite": wl.favorite,
            "hidden": False,
            "action": "Watch",
            "current_price": current_price,
            "sentiment": "Checking now...",
            "sentiment_reason": "",
            "sentiment_last_updated": None,
            "sentiment_provider": None,
            "sentiment_model": None,
            "sentiment_tier": None,
            "sentiment_search_status": None,
            "sentiment_tracking_enabled": True,
            "volatility_pct": wl.volatility_pct,
            "cached_news": "",
            "cached_news_date": None
        }
    })

@portfolio_bp.route("/api/watchlist/remove", methods=["POST"])
@login_required
def api_watchlist_remove():
    data = request.get_json()
    symbol = data.get("symbol", "").upper()
    wl = WatchlistCoin.query.filter_by(user_id=current_user.id, symbol=symbol).first()
    if wl:
        db.session.delete(wl)
        db.session.commit()
    return jsonify({"success": True})

@portfolio_bp.route("/api/hidden-coins")
@login_required
def api_hidden_coins():
    try:
        try:
            update_all_coin_prices_from_binance(current_user.id)
            db.session.commit()  # Ensure all changes are saved
        except Exception as e:
            logger.error(f"Failed to update coin prices: {str(e)}")
            db.session.rollback()
        # Legacy/sync artifacts without a ticker are not actionable coins and used
        # to render as a blank checkbox in the Unhide Coins modal.
        coins = [coin for coin in Coin.query.filter_by(user_id=current_user.id, hidden=True).all()
                 if str(getattr(coin, 'symbol', '') or '').strip()]
        logger.debug(f"Hidden coins for user {current_user.id}: {[c.symbol for c in coins]}")
        result = [coin_to_dict(c) for c in coins]
        logger.debug(f"/api/hidden-coins result: {result}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"/api/hidden-coins failed: {str(e)}", exc_info=True)
        # Always return a valid JSON list, never a 500
        return jsonify([])

@portfolio_bp.route("/api/staking/assets", methods=["GET"])
@login_required
def api_staking_assets():
    """Get available staking assets with details from Binance.US API
    Doc: GET /sapi/v1/staking/asset"""
    try:
        cred = get_user_credentials(current_user.username)
        
        if not cred or not cred.api_key or not cred.api_secret:
            logger.warning("Binance API credentials not configured for staking")
            return jsonify([])
        
        # Call Binance.US staking asset information endpoint
        response = binance_us_api_call(cred, '/sapi/v1/staking/asset', method='GET', use_trading_keys=True)
        
        if response.status_code == 200:
            raw_payload = response.json()
            staking_assets = raw_payload.get('data', []) if isinstance(raw_payload, dict) else (raw_payload or [])
            normalized_assets = []
            for asset in staking_assets:
                if not isinstance(asset, dict):
                    continue
                a_copy = dict(asset)
                raw_rate = a_copy.get('apy') or a_copy.get('apr') or a_copy.get('annualPercentageRate') or a_copy.get('rewardRate') or a_copy.get('estApr') or a_copy.get('interestRate') or 0.0
                try:
                    rate_num = float(str(raw_rate).replace('%', '').strip())
                    if rate_num > 1.0:
                        rate_num = rate_num / 100.0
                except Exception:
                    rate_num = 0.0
                a_copy['apy'] = rate_num
                a_copy['apr'] = rate_num
                normalized_assets.append(a_copy)
            logger.info(f"Retrieved {len(normalized_assets)} staking assets from Binance.US")
            return jsonify(normalized_assets)
        else:
            logger.error(f"Binance.US staking API error: {response.status_code} - {response.text}")
            return jsonify([])
    
    except Exception as e:
        logger.error(f"Critical error in api_staking_assets: {e}", exc_info=True)
        return jsonify([])

@portfolio_bp.route("/api/staking/stakeable-coins", methods=["GET"])
@login_required
def api_stakeable_coins():
    """Get list of stakeable coin symbols from Binance.US API
    Doc: GET /sapi/v1/staking/asset (extract stakingAsset symbols)"""
    try:
        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            logger.warning("Binance API credentials not configured")
            return jsonify([])
        
        # Call Binance.US staking asset information endpoint
        response = binance_us_api_call(cred, '/sapi/v1/staking/asset', method='GET', use_trading_keys=True)
        
        if response.status_code == 200:
            staking_assets = response.json()
            # Extract just the stakingAsset symbols
            stakeable_coins = [asset.get('stakingAsset') for asset in staking_assets if asset.get('stakingAsset')]
            logger.info(f"Retrieved {len(stakeable_coins)} stakeable coins from Binance.US API")
            return jsonify(stakeable_coins)
        else:
            logger.error(f"Binance.US staking API error: {response.status_code} - {response.text}")
            return jsonify([])
    
    except Exception as e:
        logger.error(f"Error in api_stakeable_coins: {e}")
        return jsonify([])

@portfolio_bp.route("/api/staking/stake", methods=["POST"])
@login_required
def api_stake_asset():
    """Stake an asset using Binance.US API
    Doc: POST /sapi/v1/staking/stake
    Params: stakingAsset, amount, autoRestake (optional), twofa_token (optional)"""
    try:
        from models import StakedCoin
        data = request.get_json()
        
        staking_asset = data.get('stakingAsset', '').upper()
        amount = float(data.get('amount', 0))
        auto_restake = data.get('autoRestake', True)
        twofa_token = data.get('twofa_token')
        
        if not staking_asset or amount <= 0:
            return jsonify({"error": "Invalid staking asset or amount"}), 400
        
        # Check if 2FA is required
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if settings and settings.require_2fa and settings.totp_enabled:
            if not twofa_token:
                return jsonify({"error": "2FA verification required", "requires_2fa": True}), 403
            
            # Verify 2FA token from session
            token_data = session.get(f'2fa_verified_{twofa_token}')
            if not token_data:
                return jsonify({"error": "Invalid or expired 2FA token"}), 403
            
            # Check if token is still valid (2 minutes)
            from datetime import datetime
            token_timestamp = token_data.get('timestamp', 0)
            if datetime.utcnow().timestamp() - token_timestamp > 120:
                session.pop(f'2fa_verified_{twofa_token}', None)
                return jsonify({"error": "2FA token expired. Please verify again."}), 403
            
            # Verify user ID matches
            if token_data.get('user_id') != current_user.id:
                return jsonify({"error": "Invalid 2FA token"}), 403
            
            # Clear the token after use
            session.pop(f'2fa_verified_{twofa_token}', None)
        
        # Get user credentials
        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            return jsonify({"error": "Binance API credentials not configured"}), 400

        permission_check = binance_has_staking_permission(cred)
        if permission_check is False:
            return jsonify({
                "error": "Your Binance trading API key does not have Earn/Staking permissions enabled.",
                "action": "Update the API key on Binance.US to allow Earn/Staking or create a new key with that permission."
            }), 403
        
        # Find the coin in portfolio
        coin = Coin.query.filter_by(user_id=current_user.id, symbol=staking_asset).first()
        if not coin:
            return jsonify({"error": f"{staking_asset} not found in portfolio"}), 404
        
        if coin.amount < amount:
            return jsonify({"error": f"Insufficient balance. Available: {coin.amount} {staking_asset}"}), 400
        
        # Call Binance.US staking API
        # POST /sapi/v1/staking/stake
        params = {
            'stakingAsset': staking_asset,
            'amount': str(amount),
            'autoRestake': str(auto_restake).lower()
        }
        
        try:
            logger.info(f"Calling Binance staking API for {current_user.username}: {params}")
            response = binance_us_api_call(cred, '/sapi/v1/staking/stake', method='POST', params_dict=params, use_trading_keys=True)
            
            if response.status_code == 200:
                result = response.json()
                
                # Deduct from coins table
                coin.amount -= amount
                
                # Get staking asset info for APR/APY
                asset_response = binance_us_api_call(cred, '/sapi/v1/staking/asset', method='GET', params_dict={'stakingAsset': staking_asset}, use_trading_keys=True)
                product_info = {}
                if asset_response.status_code == 200:
                    assets = asset_response.json()
                    if isinstance(assets, list) and len(assets) > 0:
                        product_info = assets[0]
                
                # Add to staked_coins table
                staked_coin = StakedCoin(
                    user_id=current_user.id,
                    symbol=staking_asset,
                    amount=amount,
                    stake_transaction_id=result.get('data', {}).get('purchaseRecordId', ''),
                    apr=float(product_info.get('apr', 0)),
                    apy=float(product_info.get('apy', 0)),
                    reward_asset=product_info.get('rewardAsset', staking_asset),
                    unstaking_period_hours=int(product_info.get('unstakingPeriod', 168)),
                    auto_restake=auto_restake,
                    status='active'
                )
                
                db.session.add(staked_coin)
                db.session.commit()
                trigger_portfolio_snapshot(current_user.id, current_user.username)

                # Record staking transaction in exchange_logs (staking_orders)
                try:
                    engine_logs = db.engine
                    metadata = {
                        'purchaseRecordId': result.get('data', {}).get('purchaseRecordId', ''),
                        'raw_response': result
                    }
                    usd_value = None
                    try:
                        price = fetch_binance_price(staking_asset)
                        usd_value = float(price) * float(amount) if price else None
                    except Exception:
                        usd_value = None

                    from trading_models import StakingOrder
                    
                    # Record staking transaction using ORM
                    new_staking_order = StakingOrder(
                        user_id=current_user.id,
                        symbol=staking_asset,
                        action='stake',
                        amount=float(amount),
                        status='completed',
                        transaction_id=result.get('data', {}).get('purchaseRecordId', ''),
                        auto_restake=auto_restake,
                        apr=float(product_info.get('apr', 0)),
                        apy=float(product_info.get('apy', 0)),
                        reward_asset=product_info.get('rewardAsset', staking_asset),
                        usd_value=usd_value,
                        extra_metadata=json.dumps(metadata)
                    )
                    
                    db.session.add(new_staking_order)
                    db.session.commit()
                except Exception as log_err:
                    logger.error(f"Failed to insert staking_orders record: {log_err}", exc_info=True)
                
                logger.info(f"Successfully staked {amount} {staking_asset} for user {current_user.username}")
                return jsonify({
                    "success": True,
                    "message": f"Successfully staked {amount} {staking_asset}",
                    "purchaseRecordId": result.get('data', {}).get('purchaseRecordId', '')
                })
            elif response.status_code == 401:
                logger.error(f"Binance staking API authorization error: {response.text}")
                return jsonify({
                    "error": "Binance rejected the staking request due to missing permissions.",
                    "details": "Enable Earn/Staking on the trading API key in Binance.US and try again.",
                    "requires_staking_permission": True
                }), 403
            else:
                logger.error(f"Binance staking API error: {response.status_code} - {response.text}")
                return jsonify({"error": f"Staking failed: {response.text}"}), response.status_code
        
        except Exception as e:
            db.session.rollback()
            logger.error(f"Binance staking API error: {e}", exc_info=True)
            return jsonify({"error": f"Staking failed: {str(e)}"}), 500
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in api_stake_asset: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@portfolio_bp.route("/api/staking/unstake", methods=["POST"])
@login_required
def api_unstake_asset():
    """Unstake an asset using Binance.US API
    Doc: POST /sapi/v1/staking/unstake
    Params: stakedCoinId, amount, twofa_token (optional)"""
    try:
        from models import StakedCoin
        data = request.get_json()
        
        staked_coin_id = data.get('stakedCoinId')
        amount = float(data.get('amount', 0))
        twofa_token = data.get('twofa_token')
        
        if not staked_coin_id or amount <= 0:
            return jsonify({"error": "Invalid staked coin ID or amount"}), 400

        # Check if 2FA is required
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if settings and settings.require_2fa and settings.totp_enabled:
            if not twofa_token:
                return jsonify({"error": "2FA verification required", "requires_2fa": True}), 403
            
            # Verify 2FA token from session
            token_data = session.get(f'2fa_verified_{twofa_token}')
            if not token_data:
                return jsonify({"error": "Invalid or expired 2FA token"}), 403
            
            # Check if token is still valid (2 minutes)
            from datetime import datetime
            token_timestamp = token_data.get('timestamp', 0)
            if datetime.utcnow().timestamp() - token_timestamp > 120:
                session.pop(f'2fa_verified_{twofa_token}', None)
                return jsonify({"error": "2FA token expired. Please verify again."}), 403
            
            # Verify user ID matches
            if token_data.get('user_id') != current_user.id:
                return jsonify({"error": "Invalid 2FA token"}), 403
            
            # Clear the token after use
            session.pop(f'2fa_verified_{twofa_token}', None)
        
        # Get user credentials
        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            return jsonify({"error": "Binance API credentials not configured"}), 400
        
        # Find the staked coin
        staked_coin = StakedCoin.query.filter_by(id=staked_coin_id, user_id=current_user.id).first()
        if not staked_coin:
            return jsonify({"error": "Staked position not found"}), 404
        
        if staked_coin.amount < amount:
            return jsonify({"error": f"Insufficient staked balance. Available: {staked_coin.amount}"}), 400
        
        # Call Binance.US unstake API
        # POST /sapi/v1/staking/unstake
        params = {
            'stakingAsset': staked_coin.symbol,
            'amount': str(amount)
        }
        
        try:
            response = binance_us_api_call(cred, '/sapi/v1/staking/unstake', method='POST', params_dict=params, use_trading_keys=True)
            
            if response.status_code == 200:
                result = response.json()
                
                # Calculate when unstaking completes
                unstaking_hours = staked_coin.unstaking_period_hours or 168
                available_at = datetime.utcnow() + timedelta(hours=unstaking_hours)

                if abs(staked_coin.amount - amount) < 1e-10:
                    # Full unstake - update existing record
                    staked_coin.status = 'unstaking'
                    staked_coin.unstake_requested_at = datetime.utcnow()
                    staked_coin.unstake_available_at = available_at
                else:
                    # Partial unstake - keep existing record active but reduced
                    # Create a NEW record for the unstaking part
                    staked_coin.amount -= amount
                    
                    new_unstaking_record = StakedCoin(
                        user_id=staked_coin.user_id,
                        symbol=staked_coin.symbol,
                        amount=amount,
                        staked_at=staked_coin.staked_at,
                        stake_transaction_id=staked_coin.stake_transaction_id,
                        apr=staked_coin.apr,
                        apy=staked_coin.apy,
                        reward_asset=staked_coin.reward_asset,
                        unstaking_period_hours=staked_coin.unstaking_period_hours,
                        auto_restake=staked_coin.auto_restake,
                        status='unstaking',
                        unstake_requested_at=datetime.utcnow(),
                        unstake_available_at=available_at
                    )
                    db.session.add(new_unstaking_record)

                # Log a local StakingOrder for immediate history feedback
                try:
                    from trading_models import StakingOrder
                    new_order = StakingOrder(
                        user_id=current_user.id,
                        symbol=staked_coin.symbol,
                        amount=amount,
                        action='unstake',
                        status='PROCESSING',
                        timestamp=datetime.utcnow(),
                        usd_value=0.0 # Will be updated by sync
                    )
                    db.session.add(new_order)
                except Exception as order_err:
                    logger.warning(f"Failed to log local unstake order: {order_err}")
                
                db.session.commit()
                trigger_portfolio_snapshot(current_user.id, current_user.username)
                
                logger.info(f"Successfully initiated unstake of {amount} {staked_coin.symbol} for user {current_user.username}")
                return jsonify({
                    "success": True,
                    "message": f"Unstaking {amount} {staked_coin.symbol}. Available in {unstaking_hours} hours",
                    "unstakeAvailableAt": available_at.isoformat()
                })
            else:
                logger.error(f"Binance unstaking API error: {response.status_code} - {response.text}")
                return jsonify({"error": f"Unstaking failed: {response.text}"}), response.status_code
        
        except Exception as e:
            db.session.rollback()
            logger.error(f"Binance unstaking API error: {e}", exc_info=True)
            return jsonify({"error": f"Unstaking failed: {str(e)}"}), 500
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in api_unstake_asset: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@portfolio_bp.route("/api/dust/assets", methods=["GET"])
@login_required
def api_dust_assets():
    """GET /sapi/v1/asset/query/dust-assets — list convertible dust balances.
    Query param: toAsset (BNB|BTC|ETH|USDT, default BNB)
    """
    try:
        to_asset = request.args.get("toAsset", "BNB").upper()
        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            return jsonify({"error": "Binance API credentials not configured"}), 400

        response = binance_us_api_call(
            cred,
            "/sapi/v1/asset/query/dust-assets",
            method="GET",
            params_dict={"toAsset": to_asset},
            use_trading_keys=False,
        )

        if response.status_code == 200:
            data = response.json()
            return jsonify({"success": True, "data": data})
        else:
            logger.error(f"Binance dust-assets error: {response.status_code} {response.text}")
            return jsonify({"success": False, "error": response.text}), response.status_code

    except Exception as exc:
        logger.error(f"Error in api_dust_assets: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500

@portfolio_bp.route("/api/dust/convert", methods=["POST"])
@login_required
def api_dust_convert():
    """POST /sapi/v1/asset/dust — convert selected dust assets.
    Body JSON: { fromAssets: ["LTC","XRP",...], toAsset: "BNB", twofa_token: "<token>" }
    """
    try:
        data = request.get_json() or {}
        from_assets = data.get("fromAssets", [])
        to_asset = (data.get("toAsset") or "BNB").upper()
        twofa_token = data.get("twofa_token")

        if not from_assets:
            return jsonify({"error": "No assets selected for conversion"}), 400
        if to_asset not in ("BNB", "BTC", "ETH", "USDT"):
            return jsonify({"error": f"Invalid toAsset: {to_asset}"}), 400

        # 2FA check
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        if settings and settings.require_2fa and settings.totp_secret:
            if not twofa_token:
                return jsonify({"error": "2FA verification required", "requires_2fa": True}), 403
            token_data = session.get(f"2fa_verified_{twofa_token}")
            if not token_data or token_data.get("user_id") != current_user.id:
                return jsonify({"error": "Invalid or expired 2FA token", "requires_2fa": True}), 403
            if datetime.utcnow().timestamp() - token_data.get("timestamp", 0) > 120:
                session.pop(f"2fa_verified_{twofa_token}", None)
                return jsonify({"error": "2FA token expired. Please verify again.", "requires_2fa": True}), 403
            session.pop(f"2fa_verified_{twofa_token}", None)

        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            return jsonify({"error": "Binance API credentials not configured"}), 400

        # Build params — Binance expects fromAsset repeated for each coin
        params = {"toAsset": to_asset}
        for asset in from_assets:
            params.setdefault("fromAsset", [])
            if isinstance(params["fromAsset"], list):
                params["fromAsset"].append(asset)
            else:
                params["fromAsset"] = [params["fromAsset"], asset]

        # binance_us_api_call flattens lists automatically via requests
        response = binance_us_api_call(
            cred,
            "/sapi/v1/asset/dust",
            method="POST",
            params_dict=params,
            use_trading_keys=False,
        )

        if response.status_code == 200:
            result = response.json()
            logger.info(
                f"Dust conversion success for user {current_user.id}: "
                f"{from_assets} -> {to_asset}"
            )
            # Trigger immediate portfolio snapshot so chart updates without waiting 5 min
            trigger_portfolio_snapshot(current_user.id, current_user.username)
            return jsonify({"success": True, "data": result})
        else:
            logger.error(f"Binance dust convert error: {response.status_code} {response.text}")
            return jsonify({"success": False, "error": response.text}), response.status_code

    except Exception as exc:
        logger.error(f"Error in api_dust_convert: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500

@portfolio_bp.route("/api/dust/history", methods=["GET"])
@login_required
def api_dust_history():
    """GET /sapi/v1/asset/query/dust-logs — dust conversion history."""
    try:
        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            return jsonify({"error": "Binance API credentials not configured"}), 400

        params = {}
        if request.args.get("startTime"):
            params["startTime"] = request.args.get("startTime")
        if request.args.get("endTime"):
            params["endTime"] = request.args.get("endTime")

        response = binance_us_api_call(
            cred,
            "/sapi/v1/asset/query/dust-logs",
            method="GET",
            params_dict=params,
            use_trading_keys=False,
        )

        if response.status_code == 200:
            return jsonify({"success": True, "data": response.json()})
        else:
            return jsonify({"success": False, "error": response.text}), response.status_code

    except Exception as exc:
        logger.error(f"Error in api_dust_history: {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 500

@portfolio_bp.route("/api/staking/history", methods=["GET"])
@login_required
def api_staking_history():
    """Get staking transaction history from Binance.US API
    Doc: GET /sapi/v1/staking/history
    Optional params: asset, startTime, endTime, page, limit"""
    try:
        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            logger.warning("Binance API credentials not configured")
            return jsonify([])
        
        # Call Binance.US staking history endpoint
        # GET /sapi/v1/staking/history
        params = {}
        if request.args.get('asset'):
            params['asset'] = request.args.get('asset')
        if request.args.get('startTime'):
            params['startTime'] = request.args.get('startTime')
        if request.args.get('endTime'):
            params['endTime'] = request.args.get('endTime')
        if request.args.get('page'):
            params['page'] = request.args.get('page')
        if request.args.get('limit'):
            params['limit'] = request.args.get('limit')
        
        response = binance_us_api_call(cred, '/sapi/v1/staking/history', method='GET', params_dict=params, use_trading_keys=True)
        
        if response.status_code == 200:
            history_data = response.json()
            if isinstance(history_data, dict):
                history_entries = history_data.get('data', [])
            else:
                history_entries = history_data

            normalized = []
            for entry in history_entries:
                status_raw = str(entry.get('status', '')).upper()
                entry_type_raw = str(entry.get('type', '')).lower()
                
                # Check for unstake/redeem FIRST to avoid mislabeling as stake
                if 'unstake' in entry_type_raw or 'redeem' in entry_type_raw:
                    entry_type = 'unstake'
                elif 'stake' in entry_type_raw:
                    entry_type = 'stake'
                else:
                    entry_type = entry_type_raw or 'unknown'

                normalized.append({
                    'asset': str(entry.get('asset', '')).upper(),
                    'amount': _coerce_float(entry.get('amount'), entry.get('amount')) or 0.0,
                    'type': entry_type,
                    'initiatedTime': entry.get('initiatedTime'),
                    'status': status_raw if status_raw else 'UNKNOWN',
                    'tranId': entry.get('tranId'),
                    'raw': entry
                })

            logger.info(f"Retrieved {len(normalized)} staking history records from Binance.US")
            return jsonify(normalized)
        else:
            logger.error(f"Binance staking history API error: {response.status_code} - {response.text}")
            return jsonify([])
    
    except Exception as e:
        logger.error(f"Error in api_staking_history: {e}", exc_info=True)
        return jsonify([])

@portfolio_bp.route("/api/staking/rewards", methods=["GET"])
@login_required
def api_staking_rewards():
    """Get staking rewards history from Binance.US API
    Doc: GET /sapi/v1/staking/stakingRewardsHistory
    Optional params: asset, startTime, endTime, page, limit"""
    try:
        cred = get_user_credentials(current_user.username)
        if not cred or not cred.api_key or not cred.api_secret:
            logger.warning("Binance API credentials not configured")
            return jsonify([])
        
        # Call Binance.US staking rewards history endpoint
        # GET /sapi/v1/staking/stakingRewardsHistory
        params = {}
        if request.args.get('asset'):
            params['asset'] = request.args.get('asset')
        if request.args.get('startTime'):
            params['startTime'] = request.args.get('startTime')
        if request.args.get('endTime'):
            params['endTime'] = request.args.get('endTime')
        if request.args.get('page'):
            params['page'] = request.args.get('page')
        if request.args.get('limit'):
            params['limit'] = request.args.get('limit')
        
        response = binance_us_api_call(cred, '/sapi/v1/staking/stakingRewardsHistory', method='GET', params_dict=params, use_trading_keys=True)
        
        if response.status_code == 200:
            result = response.json()
            # Response format: {"code":"000000","message":"success","data":[{...}],"total":1,"success":true}
            rewards_data = result.get('data', [])
            
            # Convert string values to floats for frontend compatibility
            for r in rewards_data:
                if 'usdValue' in r:
                    try:
                        r['usdValue'] = float(r['usdValue'])
                    except (ValueError, TypeError):
                        r['usdValue'] = 0.0
                if 'amount' in r:
                    try:
                        r['amount'] = float(r['amount'])
                    except (ValueError, TypeError):
                        r['amount'] = 0.0
                        
            logger.info(f"Retrieved {len(rewards_data)} staking reward records from Binance.US")
            return jsonify(rewards_data)
        else:
            logger.error(f"Binance staking rewards API error: {response.status_code} - {response.text}")
            return jsonify([])
    
    except Exception as e:
        logger.error(f"Error in api_staking_rewards: {e}", exc_info=True)
        return jsonify([])

@portfolio_bp.route("/api/set-watchlist-favorite", methods=["POST"])
@login_required
def set_watchlist_favorite():
    data = request.get_json()
    symbol = data.get("symbol", "").upper()
    favorite = data.get("favorite", False)
    w = WatchlistCoin.query.filter_by(user_id=current_user.id, symbol=symbol).first()
    if w:
        w.favorite = favorite
        db.session.commit()
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Watchlist coin not found"}), 404

@portfolio_bp.route("/api/tax-report/export", methods=["GET"])
@login_required
def export_tax_report_csv():
    try:
        from trading_models import AllActivity
        import io
        import csv
        
        activities = AllActivity.query.filter_by(user_id=current_user.id).order_by(AllActivity.date.desc()).all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Headers
        writer.writerow(['Date', 'Type', 'Asset', 'Amount', 'Price Traded At', 'Proceeds', 'Fee', 'Cost Basis', 'Gain/Loss', 'Description', 'Exchange', 'TxID'])
        
        for act in activities:
            writer.writerow([
                act.date,
                act.type,
                act.asset,
                act.amount,
                act.price_sold_at or '',
                act.proceeds or 0,
                act.fee or 0,
                act.cost_basis or 0,
                act.gain_loss or 0,
                act.description or '',
                act.exchange or '',
                act.txid or ''
            ])
            
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f"crypto_tax_report_{datetime.now().strftime('%Y%m%d')}.csv"
        )
    except Exception as e:
        logger.error(f"Error exporting tax report: {e}")
        return jsonify({"error": "Failed to export tax report"}), 500
