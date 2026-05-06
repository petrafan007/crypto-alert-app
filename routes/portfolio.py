import json
import datetime
import time

from flask import Blueprint, request, jsonify, session, make_response
from flask_login import login_required, current_user
import traceback

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
    trigger_portfolio_snapshot
)
from services.binance_service import (
    fetch_binance_price, fetch_binance_price, build_order_config,
    get_symbol_filters, get_trade_fee_for_symbol,
    sync_portfolio_from_binance, update_all_coin_prices_from_binance
)
from services.staking_service import (
    build_staking_balance_view, calculate_staking_value_for_user,
    binance_us_api_call
)
from services.credential_service import get_user_credentials
from services.notification_service import notify_order_fill
from services.common import _coerce_float, format_price, format_quantity
from credential_security import decrypt_secret
from transaction_utils import recalculate_asset_activity

# Stubs for missing functions/constants (to be moved/removed later)
_KLINES_CACHE = {}
_KLINES_CACHE_TTL = 300
def _coerce_activity_datetime(dt): return dt # TODO: move to common
def build_order_config(order_type, side, amount, data, symbol): 
    from services.binance_service import build_order_config as boc
    return boc(order_type, side, amount, data, symbol)
def update_portfolio_from_real_order(*args, **kwargs): pass # TODO
def update_test_portfolio(*args, **kwargs): pass # TODO

# Blueprint Definition
portfolio_bp = Blueprint('portfolio', __name__)



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
        chart_data = _compute_portfolio_history_series(current_user.id, req_range)
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
            asset_visibility = {}
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
                if asset_upper:
                    asset_visibility[asset_upper] = max(asset_visibility.get(asset_upper, 0.0), ref_price)
                
                pending_orders.append({
                    'order_id': order.get('orderId'),
                    'symbol': symbol,
                    'asset': asset,
                    'side': side,
                    'type': order_type,
                    'price': price,
                    'stop_price': stop_price,
                    'quantity': quantity,
                    'status': order.get('status'),
                    'time': order.get('time'),
                    'is_oco': is_oco,
                    'direction': direction,
                    'trigger_price': trigger_price,
                    'quantity_usdt': quote_amount
                })
            
            coin_updates = False
            for asset_symbol, price_hint in asset_visibility.items():
                coin = Coin.query.filter_by(user_id=current_user.id, symbol=asset_symbol).first()
                if coin:
                    if coin.hidden:
                        coin.hidden = False
                        coin_updates = True
                    if coin.auto_hidden:
                        coin.auto_hidden = False
                        coin_updates = True
                    if not coin.force_visible:
                        coin.force_visible = True
                        coin_updates = True
                    if coin.amount is None:
                        coin.amount = 0.0
                        coin_updates = True
                    if price_hint and (not coin.current or coin.current == 0):
                        coin.current = price_hint
                        coin_updates = True
                else:
                    coin = Coin(
                        user_id=current_user.id,
                        symbol=asset_symbol,
                        amount=0.0,
                        current=price_hint or 0.0,
                        avg_entry=price_hint or 0.0,
                        initial_value=0.0,
                        purchase_date=datetime.utcnow().strftime('%Y-%m-%d'),
                        alert_enabled=True,
                        is_manual=False,
                        hidden=False,
                        auto_hidden=False,
                        force_visible=True
                    )
                    db.session.add(coin)
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
    """Get canonical list of supported Binance.US spot order types and TimeInForce options"""
    try:
        # Canonical Binance.US spot order types (authoritative source)
        order_types = [
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


@portfolio_bp.route('/api/trading/klines/<symbol>', methods=['GET'])
def get_trading_klines(symbol):
    """
    Proxy endpoint for Binance.US klines/candlestick data with caching.
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
        
        if not creds:
            return jsonify({
                'success': False,
                'error': 'No Binance.US credentials found.',
                'error_code': 'missing_trading_credentials'
            }), 400
        
        api_key = decrypt_secret(creds.api_key)
        api_secret = decrypt_secret(creds.api_secret)
        if not api_key or not api_secret:
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
        # Returns: [[timestamp, open, high, low, close, volume, close_time, quote_asset_volume, trades, ...], ...]
        try:
            klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        except Exception as api_err:
            err_msg = str(api_err)
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
        
        # Query all_activities using ORM
        rows = AllActivity.query.filter(
            AllActivity.user_id == current_user.id,
            AllActivity.asset == base_asset,
            AllActivity.type.in_(['BUY', 'SELL']),
            AllActivity.exchange == 'binance'
        ).order_by(AllActivity.date.asc()).all()

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
                    'price': price_value
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
        required_fields = ['symbol', 'side', 'type', 'quantity']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
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

                if order_type in ['STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT']:
                    if formatted_price <= 0:
                        return jsonify({'success': False, 'error': 'Limit price must be greater than 0 for stop-limit orders'}), 400
                    if side == 'BUY' and formatted_price < formatted_stop_price:
                        return jsonify({'success': False, 'error': 'For buy stop-limit orders, limit price must be greater than or equal to stop price to avoid immediate execution.'}), 400
                    if side == 'SELL' and formatted_price > formatted_stop_price:
                        return jsonify({'success': False, 'error': 'For sell stop-limit orders, limit price must be less than or equal to stop price to avoid immediate execution.'}), 400
            
            # For MARKET orders, check MIN_NOTIONAL using current price
            if order_type == 'MARKET' and 'minNotional' in filters:
                try:
                    ticker = client.get_symbol_ticker(symbol=symbol)
                    current_price = float(ticker['price'])
                    order_value = formatted_quantity * current_price
                    if order_value < filters['minNotional']:
                        return jsonify({
                            'success': False, 
                            'error': f'Order value too small. Minimum order value for {symbol} is ${filters["minNotional"]:.2f}. Your order value is approximately ${order_value:.2f} at current market price. Please increase quantity.'
                        }), 400
                except Exception as price_error:
                    logger.warning(f"Could not check MIN_NOTIONAL for MARKET order: {price_error}")
            
            # Validate with Binance test endpoint
            client.create_test_order(**test_params)
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Binance order validation failed: {e}\n{traceback.format_exc()}")
            
            # Parse Binance error for more specific messaging
            if 'LOT_SIZE' in error_msg:
                return jsonify({
                    'success': False, 
                    'error': f'Invalid quantity. The quantity has too many decimal places or doesn\'t meet the step size requirement for {symbol}. Please adjust your order quantity.'
                }), 400
            elif 'MIN_NOTIONAL' in error_msg:
                return jsonify({
                    'success': False, 
                    'error': f'Order value too small. The total order value (quantity × price) is below the minimum required for {symbol}. Please increase your quantity or choose a different trading pair.'
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

        combined_orders = {}
        symbols_to_check = set()
        activity_records = []

        def normalize_timestamp(value):
            if not value:
                return None
            try:
                v = str(value)
                if v.endswith('Z'):
                    v = v.replace('Z', '+00:00')
                return datetime.fromisoformat(v).isoformat()
            except Exception:
                try:
                    return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").isoformat()
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
            order_dict = {
                'id': order.binance_order_id or f"real-{order.id}",
                'symbol': order.symbol,
                'side': order.side,
                'order_type': order.type,
                'quantity': float(order.quantity or 0.0),
                'price': float(order.price or 0.0),
                'filled_quantity': float(order.executed_qty or order.quantity or 0.0),
                'filled_price': float(order.avg_fill_price or order.price or 0.0),
                'status': order.status or 'UNKNOWN',
                'created_at': order.created_at.isoformat() if order.created_at else None,
                'updated_at': order.updated_at.isoformat() if order.updated_at else None,
                'source': 'app'
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
            text('''SELECT date, type, asset, amount, fee, status, details, txid, price_sold_at
               FROM all_activities
               WHERE user_id = :uid AND status IN ('FILLED', 'completed')'''),
            {"uid": current_user.id}
        ).mappings().all()

        activity_records = []
        for activity in activity_rows:
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

        # Attempt to fetch Binance order history directly
        try:
            # Fetch credentials using ORM
            creds = Credential.query.filter_by(user_id=current_user.id).first()

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
                                    created_at_iso = datetime.fromtimestamp(created_at / 1000).isoformat()
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
                                    'updated_at': datetime.fromtimestamp(o['updateTime'] / 1000).isoformat() if o.get('updateTime') else created_at_iso,
                                    'source': 'binance'
                                }

                                add_order(key, payload)

                        except Exception as binance_err:
                            logger.warning(f"Failed to fetch Binance orders for {trading_symbol}: {binance_err}")
                            continue
                else:
                    logger.warning("Binance credentials found but incomplete for order history fetch")
            else:
                logger.warning("No Binance credentials found for real order history")
        except Exception as cred_err:
            logger.warning(f"Could not fetch Binance order history: {cred_err}")

        # Merge historical records from all_activities (fills from other sources)
        for activity in activity_records:
            details_json = activity.get('__details_json__') or {}
            order_id = details_json.get('order_id') or activity.get('txid')
            product_id = details_json.get('product_id')
            if not order_id or not product_id:
                continue

            if activity.get('asset', '').upper() == 'USDT' and 'Auto-generated' in (activity.get('details') or ''):
                continue

            side = (details_json.get('side') or activity.get('type') or '').upper()
            quantity = details_json.get('filled_size') or activity.get('amount')
            price = details_json.get('average_filled_price') or activity.get('price_sold_at')

            try:
                quantity_val = float(quantity) if quantity not in (None, '') else 0.0
            except Exception:
                quantity_val = 0.0

            try:
                price_val = float(price) if price not in (None, '') else 0.0
            except Exception:
                price_val = 0.0

            payload = {
                'id': order_id,
                'symbol': product_id.replace('-', '').upper(),
                'side': side or 'UNKNOWN',
                'order_type': (details_json.get('order_type') or activity.get('type') or 'UNKNOWN').upper(),
                'quantity': quantity_val,
                'price': price_val,
                'filled_quantity': quantity_val,
                'filled_price': price_val,
                'status': activity.get('status', 'FILLED') or 'FILLED',
                'created_at': normalize_timestamp(details_json.get('created_time') or activity.get('date')),
                'updated_at': normalize_timestamp(details_json.get('last_fill_time') or details_json.get('created_time') or activity.get('date')),
                'source': 'history'
            }

            add_order(f"binance-{payload['symbol']}-{order_id}", payload)

        # Sort and limit
        order_list = list(combined_orders.values())
        order_list.sort(key=lambda o: o.get('created_at') or '', reverse=True)
        limited_orders = order_list if unlimited else order_list[:limit]

        return jsonify({
            'success': True,
            'orders': limited_orders
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
            issuer_name='Crypto Dashboard Trading'
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
        required_fields = ['symbol', 'side', 'type', 'quantity']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
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
        else:
            formatted_price = 0.0
        
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
            logger.info(f"Placing real order with params: {{'symbol': '{symbol}', 'side': '{side}', 'type': '{order_type}', 'quantity': {formatted_quantity}, 'price': {formatted_price}, 'order_value_usd': {order_value_usd}}}")
            order_params = build_order_config(order_type, side, formatted_quantity, data, symbol)
            
            # PLACE THE REAL ORDER
            order_response = client.create_order(**order_params)
            
            # Extract fill details
            executed_qty = float(order_response.get('executedQty', 0))
            fills = order_response.get('fills', [])
            avg_fill_price = float(fills[0].get('price', 0)) if fills else (price if price > 0 else current_price)
            total_commission = sum(float(f.get('commission', 0)) for f in fills)
            commission_asset = fills[0].get('commissionAsset', 'USDT') if fills else 'USDT'

            success_payload = {
                'success': True,
                'order': None,
                'binance_order_id': order_response['orderId'],
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
                    binance_order_id=order_response['orderId'],
                    symbol=symbol,
                    side=side,
                    type=order_type,
                    quantity=formatted_quantity,
                    price=formatted_price if formatted_price > 0 else None,
                    stop_price=order_params.get('stopPrice'),
                    time_in_force=order_response.get('timeInForce'),
                    status=order_response['status'],
                    executed_qty=executed_qty,
                    cumulative_quote_qty=float(order_response.get('cummulativeQuoteQty', 0)),
                    avg_fill_price=avg_fill_price,
                    commission=total_commission,
                    commission_asset=commission_asset,
                    binance_client_order_id=order_response.get('clientOrderId'),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                    filled_at=datetime.utcnow() if order_response['status'] == 'FILLED' else None,
                    order_response=json.dumps(order_response)
                )

                db.session.add(real_order)
                if order_response['status'] == 'FILLED':
                    real_order.fill_notified = True

                if order_response['status'] == 'FILLED' and executed_qty > 0:
                    update_portfolio_from_real_order(
                        user_id=current_user.id,
                        symbol=symbol,
                        side=side,
                        quantity=executed_qty,
                        price=avg_fill_price,
                        commission=total_commission,
                        commission_asset=commission_asset,
                        order_id=order_response['orderId']
                    )
                    notify_order_fill(
                        real_order,
                        username=current_user.username,
                        executed_qty=executed_qty,
                        quote_qty=float(order_response.get('cummulativeQuoteQty', 0)),
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

                logger.info(f"REAL ORDER PLACED for user {current_user.id}: {symbol} {side} {formatted_quantity} @ {avg_fill_price} - Order ID: {order_response['orderId']}")
            except Exception as post_err:
                logger.error(f"Order {order_response['orderId']} placed but post-processing failed: {post_err}", exc_info=True)
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
            
            if commission_rates:
                # Binance.US returns BASE rates as decimal strings (e.g., "0.00400000" = 0.4%)
                # These are BEFORE any BNB discount (5% off if using BNB for fees)
                # The actual fee at order time will be lower if BNB is enabled
                maker_rate = float(commission_rates.get('maker', '0.001'))
                taker_rate = float(commission_rates.get('taker', '0.004'))
                logger.info(f"✅ BASE rates (before BNB discount): Maker={maker_rate:.4f} ({maker_rate*100:.2f}%), Taker={taker_rate:.4f} ({taker_rate*100:.2f}%)")
            else:
                # Old format: makerCommission/takerCommission (in basis points)
                # 10 basis points = 0.1%, 40 basis points = 0.4%
                maker_commission = account.get('makerCommission', 10)
                taker_commission = account.get('takerCommission', 40)
                logger.info(f"Got old format commission (basis points): makerCommission={maker_commission}, takerCommission={taker_commission}")
                
                maker_rate = float(maker_commission) / 10000
                taker_rate = float(taker_commission) / 10000
                logger.info(f"Converted to rates - Maker: {maker_rate:.4f} ({maker_rate*100:.2f}%), Taker: {taker_rate:.4f} ({taker_rate*100:.2f}%)")
            
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
            
            return jsonify({
                'success': True,
                'balances': {
                    'base': base_free,
                    'base_locked': base_locked,
                    'base_total': base_free + base_locked,
                    'quote': quote_free,
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
    """Get all open orders"""
    try:
        settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
        
        if settings and settings.test_mode_enabled:
            # Get open test orders
            open_orders = TestOrder.query.filter_by(
                user_id=current_user.id
            ).filter(
                TestOrder.status.in_(['NEW', 'PARTIALLY_FILLED'])
            ).order_by(TestOrder.created_at.desc()).all()
            
            return jsonify({
                'success': True,
                'orders': [order.to_dict() for order in open_orders]
            })
        else:
            # Get real open orders from Binance using SQLAlchemy ORM
            creds = Credential.query.filter_by(user_id=current_user.id).first()
            
            if not creds:
                return jsonify({
                    'success': False,
                    'error': 'No Binance.US trading credentials configured',
                    'error_code': 'missing_trading_credentials'
                }), 400
            
            # Credential model properties auto-decrypt values
            trading_api_key = creds.trading_api_key
            trading_api_secret = creds.trading_api_secret
            if not trading_api_key or not trading_api_secret:
                return jsonify({
                    'success': False,
                    'error': 'No Binance.US trading credentials configured',
                    'error_code': 'missing_trading_credentials'
                }), 400
            
            from binance.client import Client
            client = Client(
                api_key=trading_api_key,
                api_secret=trading_api_secret,
                testnet=False,
                tld='us'
            )
            
            try:
                open_orders = client.get_open_orders()
            except Exception as api_err:
                err_msg = str(api_err)
                logger.error(f"Error fetching open orders from Binance: {err_msg}")
                if "API-key" in err_msg or "Invalid Api-Key" in err_msg or "invalid api-key" in err_msg.lower():
                    return jsonify({
                        'success': False,
                        'error': 'Invalid Binance API credentials',
                        'error_code': 'invalid_trading_credentials'
                    }), 400
                return jsonify({
                    'success': False,
                    'error': f'Failed to fetch open orders: {err_msg}'
                }), 502
            
            return jsonify({
                'success': True,
                'orders': open_orders
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
        required_fields = ['symbol', 'side', 'quantity', 'price', 'stopPrice', 'stopLimitPrice']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
        symbol = data['symbol'].upper()
        side = data['side'].upper()  # BUY or SELL
        quantity = float(data['quantity'])
        price = float(data['price'])
        stop_price = float(data['stopPrice'])
        stop_limit_price = float(data['stopLimitPrice'])
        stop_limit_time_in_force = data.get('stopLimitTimeInForce', 'GTC')
        
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
        
        # Update quantity to formatted value
        quantity = formatted_quantity
        
        # Validate OCO order with Binance.US (Note: Binance doesn't have a test endpoint for OCO, so we skip validation)
        # Get current market price for simulation
        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            current_price = float(ticker['price'])
        except Exception as e:
            logger.error(f"Failed to get current price for {symbol}: {e}")
            current_price = price
        
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

        # Balance check: ensure user has enough quote asset (e.g., USDT) to cover limit order + fees
        # Get balances from Binance account (or simulated account for test mode)
        try:
            account_info = client.get_account()
            # Properly extract base and quote assets
            if symbol.endswith('USD') and not symbol.endswith('USDT'):
                quote_asset = 'USD'
            else:
                quote_asset = 'USDT'
                
            balances = {b['asset']: float(b['free']) for b in account_info.get('balances', [])}
            available_quote = balances.get(quote_asset, 0.0)
        except Exception:
            available_quote = None

        # Calculate required quote - for OCO buy, we must afford the most expensive leg
        check_price = max(price, stop_limit_price) if side == 'BUY' else price
        required_quote = quantity * check_price
        estimated_fee = required_quote * fee_rate

        if available_quote is not None and (required_quote + estimated_fee) > available_quote:
            # Try to reduce quantity in steps until it fits available balance
            step = filters['stepSize']
            from decimal import Decimal
            qty_dec = Decimal(str(quantity))
            step_dec = Decimal(str(step))
            price_dec = Decimal(str(price))
            fee_rate_dec = Decimal(str(fee_rate))
            max_qty = Decimal(str(filters['maxQty']))
            min_qty = Decimal(str(filters['minQty']))

            while qty_dec >= min_qty:
                req = qty_dec * price_dec
                fee_est = req * fee_rate_dec
                if (req + fee_est) <= Decimal(str(available_quote)):
                    break
                qty_dec -= step_dec

            if qty_dec < min_qty:
                return jsonify({'success': False, 'error': 'Insufficient balance to place OCO order even after adjusting quantity.'}), 400

            # Format quantity back
            quantity = float(format_quantity(float(qty_dec), filters['stepSize']))
            required_quote = quantity * price
            estimated_fee = required_quote * fee_rate

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
        required_fields = ['symbol', 'side', 'quantity', 'price', 'stopPrice', 'stopLimitPrice']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
        symbol = data['symbol'].upper()
        side = data['side'].upper()
        quantity = float(data['quantity'])
        price = float(data['price'])
        stop_price = float(data['stopPrice'])
        stop_limit_price = float(data['stopLimitPrice'])
        stop_limit_time_in_force = data.get('stopLimitTimeInForce', 'GTC')
        
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
        
        # Update quantity to formatted value
        quantity = formatted_quantity
        
        # For BUY orders, check USDT balance and adjust quantity if needed to account for fees
        if side == 'BUY':
            try:
                # Get account balance
                account = client.get_account()
                # Properly extract base and quote assets
                if symbol.endswith('USD') and not symbol.endswith('USDT'):
                    quote_asset = 'USD'
                elif symbol.endswith('USDT'):
                    quote_asset = 'USDT'
                else:
                    quote_asset = 'USDT'

                available_balance = 0.0
                for balance in account['balances']:
                    if balance['asset'] == quote_asset:
                        available_balance = float(balance['free'])
                        break
                
                # Calculate required balance including 0.1% Binance fee
                # For OCO buy, we must afford the most expensive of the two orders
                check_price = max(price, stop_limit_price) if side == 'BUY' else price
                required_balance = quantity * check_price * 1.001  # Add 0.1% for trading fee
                
                logger.info(f"OCO Balance Check: Available {quote_asset}: {available_balance:.8f}, Required: {required_balance:.8f}")
                
                # If insufficient balance, try to reduce quantity slightly to fit within available balance
                if required_balance > available_balance:
                    # Calculate maximum quantity we can afford with fees using the safety price
                    max_affordable_quantity = (available_balance * 0.999) / check_price  # Leave 0.1% buffer for fees
                    adjusted_quantity = format_quantity(max_affordable_quantity, filters['stepSize'])
                    
                    # Check if adjusted quantity is still valid
                    if adjusted_quantity >= filters['minQty']:
                        logger.warning(f"Adjusted OCO quantity from {quantity} to {adjusted_quantity} due to balance constraints")
                        quantity = adjusted_quantity
                    else:
                        return jsonify({
                            'success': False, 
                            'error': f'Insufficient {quote_asset} balance. Available: {available_balance:.8f}, Required: {required_balance:.8f} (including fees)'
                        }), 400
                        
            except Exception as balance_err:
                logger.error(f"Balance check failed: {balance_err}")
                # Continue anyway - let Binance reject if truly insufficient
        
        # Place real OCO order
        try:
            # Use API-provided fees and validate balance similar to test path
            fee_info = get_trade_fee_for_symbol(client, symbol) or {'maker': 0.001, 'taker': 0.001}
            fee_rate = fee_info.get('taker', 0.001)

            # Get balances
            try:
                # Properly extract quote asset
                if symbol.endswith('USD') and not symbol.endswith('USDT'):
                    quote_asset = 'USD'
                elif symbol.endswith('USDT'):
                    quote_asset = 'USDT'
                else:
                    quote_asset = 'USDT'
                
                account_info = client.get_account()
                balances = {b['asset']: float(b['free']) for b in account_info.get('balances', [])}
                available_quote = balances.get(quote_asset, 0.0)
            except Exception:
                available_quote = None

            # Calculate required quote for the limit leg
            required_quote = quantity * price
            estimated_fee = required_quote * fee_rate

            if available_quote is not None and (required_quote + estimated_fee) > available_quote:
                # Try to reduce quantity to fit
                step = filters['stepSize']
                from decimal import Decimal
                qty_dec = Decimal(str(quantity))
                step_dec = Decimal(str(step))
                price_dec = Decimal(str(price))
                fee_rate_dec = Decimal(str(fee_rate))
                min_qty = Decimal(str(filters['minQty']))

                while qty_dec >= min_qty:
                    req = qty_dec * price_dec
                    fee_est = req * fee_rate_dec
                    if (req + fee_est) <= Decimal(str(available_quote)):
                        break
                    qty_dec -= step_dec

                if qty_dec < min_qty:
                    return jsonify({'success': False, 'error': 'Insufficient balance to place OCO order even after adjusting quantity.'}), 400

                quantity = float(format_quantity(float(qty_dec), filters['stepSize']))
                required_quote = quantity * price
                estimated_fee = required_quote * fee_rate

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