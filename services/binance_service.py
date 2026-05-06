import time
import os
from datetime import datetime, timedelta
from flask import current_app
from core.extensions import db
from models import Coin
from trading_models import RealOrder, AllActivity, PortfolioValueHistory
from log import logger
from transaction_utils import recalculate_asset_activity
from services.trading_service import calculate_avg_entry_fifo
from services.notification_service import notify_order_fill
import hmac
import hashlib
import requests
import json

_EXCHANGE_INFO_CACHE = {
    'timestamp': None,
    'exchange_info': None,
    'fees': {}
}

def build_order_config(order_type, side, amount, data, symbol):
    """Build the order configuration for different order types"""
    params = {
        'symbol': symbol,
        'side': side,
        'type': order_type,
    }

    if order_type == 'MARKET':
        if side == 'BUY' and data.get('quoteQuantity'):
             params['quoteOrderQty'] = data.get('quoteQuantity')
        else:
            params['quantity'] = amount
    else: # For LIMIT, STOP_LOSS, etc.
        params['quantity'] = amount

    if order_type in ['LIMIT', 'LIMIT_MAKER', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT']:
        limit_price = data.get('price')
        if not limit_price:
            raise ValueError("Limit price required for limit orders")
        params['price'] = limit_price
    
    if order_type in ['LIMIT', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT', 'LIMIT_MAKER']:
        params['timeInForce'] = data.get('timeInForce', 'GTC')

    if order_type in ['STOP_LOSS', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT', 'TAKE_PROFIT_LIMIT', 'OCO']:
        stop_price = data.get('stopPrice')
        if not stop_price:
            raise ValueError("Stop price required for stop orders")
        params['stopPrice'] = stop_price

    if order_type == 'OCO':
        stop_limit_price = data.get('stopLimitPrice')
        if not stop_limit_price:
            raise ValueError("Stop limit price required for OCO orders")
        params['stopLimitPrice'] = stop_limit_price
        params['stopLimitTimeInForce'] = data.get('stopLimitTimeInForce', 'GTC')

    return params

def get_cached_exchange_info(client, force_refresh=False):
    """Return exchange info and cache it for short periods to reduce request weight."""
    now = time.time()
    if force_refresh or not _EXCHANGE_INFO_CACHE['timestamp'] or (now - (_EXCHANGE_INFO_CACHE['timestamp'] or 0)) > 60:
        try:
            info = client.get_exchange_info()
            _EXCHANGE_INFO_CACHE['exchange_info'] = info
            _EXCHANGE_INFO_CACHE['timestamp'] = now
            return info
        except Exception as e:
            logger.error(f"Failed to refresh exchange info: {e}")
            return _EXCHANGE_INFO_CACHE.get('exchange_info')
    return _EXCHANGE_INFO_CACHE.get('exchange_info')

def get_trade_fee_for_symbol(client, symbol):
    """Retrieve actual maker/taker fee for a symbol using Binance API (get_trade_fee)."""
    try:
        if symbol in _EXCHANGE_INFO_CACHE['fees']:
            fee_entry = _EXCHANGE_INFO_CACHE['fees'][symbol]
            if time.time() - fee_entry.get('ts', 0) < 60:
                return fee_entry['fee']

        fee_info = client.get_trade_fee(symbol=symbol)
        if isinstance(fee_info, list) and len(fee_info) > 0:
            maker = float(fee_info[0].get('maker', 0.0))
            taker = float(fee_info[0].get('taker', 0.0))
            fee = {'maker': maker, 'taker': taker}
            _EXCHANGE_INFO_CACHE['fees'][symbol] = {'fee': fee, 'ts': time.time()}
            return fee
        return None
    except Exception as e:
        logger.error(f"Failed to get trade fee for {symbol}: {e}")
        return None

def get_symbol_filters(client, symbol):
    """Get trading filters for a specific symbol from Binance.US"""
    try:
        exchange_info = get_cached_exchange_info(client)
        if not exchange_info: return None
        for sym in exchange_info['symbols']:
            if sym['symbol'] == symbol:
                filters = {}
                for f in sym['filters']:
                    if f['filterType'] == 'LOT_SIZE':
                        filters['minQty'] = float(f['minQty'])
                        filters['maxQty'] = float(f['maxQty'])
                        filters['stepSize'] = float(f['stepSize'])
                    elif f['filterType'] == 'PRICE_FILTER':
                        filters['minPrice'] = float(f['minPrice'])
                        filters['maxPrice'] = float(f['maxPrice'])
                        filters['tickSize'] = float(f['tickSize'])
                    elif f['filterType'] in ['MIN_NOTIONAL', 'NOTIONAL']:
                        filters['minNotional'] = float(f.get('minNotional', f.get('notional', 0)))
                filters['baseAssetPrecision'] = sym['baseAssetPrecision']
                filters['quotePrecision'] = sym['quotePrecision']
                return filters
        return None
    except Exception as e:
        logger.error(f"Error getting symbol filters: {e}")
        return None

class BinanceRateLimiter:
    """Circuit breaker and rate limiter for Binance API calls"""
    def __init__(self, interval_seconds=120):
        self.interval = interval_seconds
        self.last_call_times = {}  # {symbol: timestamp}
        self.failure_counts = {}   # {symbol: count}
        self.circuit_open = False
        self.circuit_open_until = None
        
    def can_call(self, symbol):
        """Check if we can call API for this symbol"""
        if self.circuit_open:
            if time.time() < self.circuit_open_until:
                return False
            else:
                # Circuit breaker timeout expired, try again
                self.circuit_open = False
                self.failure_counts.clear()
        
        last_call = self.last_call_times.get(symbol, 0)
        return (time.time() - last_call) >= self.interval
    
    def record_call(self, symbol):
        """Record successful API call"""
        self.last_call_times[symbol] = time.time()
        if symbol in self.failure_counts:
            self.failure_counts[symbol] = 0
    
    def record_failure(self, symbol):
        """Record failed API call and open circuit if needed"""
        self.failure_counts[symbol] = self.failure_counts.get(symbol, 0) + 1
        
        if self.failure_counts[symbol] >= 5:
            # Open circuit breaker for 30 minutes
            self.circuit_open = True
            self.circuit_open_until = time.time() + 1800
            logger.critical(f"🚨 Circuit breaker OPEN for Binance API after {self.failure_counts[symbol]} failures. Cooling down for 30 minutes.")

# Global rate limiter instance
binance_rate_limiter = BinanceRateLimiter(interval_seconds=120)  # 2 minutes

STABLE_COINS = {"USDT", "USDC", "DAI", "TUSD", "USDP", "EURC", "PYUSD", "USD"}

def fetch_binance_price(symbol):
    """
    Fetch current price from Binance.US exclusively (no fallbacks)
    """
    symbol = symbol.upper()

    if symbol in STABLE_COINS:
        return 1.0

    try:
        from binance.client import Client
        from dotenv import load_dotenv
        load_dotenv('/home/jcavallarojr/crypto_alert_app/.env')

        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')

        if api_key and api_secret:
            client = Client(api_key=api_key, api_secret=api_secret, testnet=False, tld='us')
            ticker = client.get_symbol_ticker(symbol=f"{symbol}USDT")
            return float(ticker['price'])
        else:
            # Try public client if keys missing
            client = Client(tld='us')
            ticker = client.get_symbol_ticker(symbol=f"{symbol}USDT")
            return float(ticker['price'])
    except Exception as e:
        logger.error(f"Error fetching Binance price for {symbol}: {e}")
        return None

def sync_binance_account(user_id, username, client, cred):
    """Synchronize Binance account data with rate limiting"""
    try:
        logger.info(f"Starting Binance sync for user {user_id} with conservative rate limiting")
        
        account_info = client.get_account()
        time.sleep(2)
        
        user_assets = []
        for balance in account_info['balances']:
            asset = balance['asset']
            total = float(balance['free'] or 0) + float(balance['locked'] or 0)
            if total > 0:
                user_assets.append(asset)
        
        all_trades = []
        for asset in user_assets:
            if asset in ['USDT', 'USD']:
                continue
            
            trading_pairs = [f"{asset}USD", f"{asset}USDT"]
            for symbol in trading_pairs:
                try:
                    trades = client.get_my_trades(symbol=symbol, limit=100)
                    if trades:
                        all_trades.extend(trades)
                    time.sleep(3)
                except Exception as e:
                    error_msg = str(e)
                    if "1003" in error_msg or "Way too much request weight" in error_msg:
                        break
                    continue
        
        if all_trades:
            process_binance_trades(user_id, all_trades)
        
        update_coins_from_binance_balances(user_id, account_info['balances'], client=client)
        
        try:
            from services.portfolio_service import compute_portfolio_total_value, record_portfolio_history
            total_value = compute_portfolio_total_value(user_id, username=username, cred=cred)
            total_value = round(total_value, 2)

            if total_value > 0:
                record_portfolio_history(user_id, total_value)
                logger.info(f"Recorded portfolio value of ${total_value:.2f} for user {user_id}")
        except Exception as e:
            logger.error(f"Error recording portfolio value during sync: {e}")
            
        sync_real_order_statuses_for_user(user_id, username, client)
        logger.info(f"Successfully completed Binance sync for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error syncing Binance account: {e}")
        raise

def sync_real_order_statuses_for_user(user_id, username, client):
    """Fetch Binance order statuses and notify user when fills are detected."""
    try:
        orders = RealOrder.query.filter_by(user_id=user_id).all()
        if not orders:
            return

        final_statuses = {'CANCELED', 'REJECTED', 'EXPIRED'}
        polling_statuses = {'NEW', 'PARTIALLY_FILLED', 'PENDING_CANCEL', 'PENDING_CANCELLED', 'STOPPED', 'FILLED'}
        finalized_orders = []
        relevant_orders = []
        for order in orders:
            status = (order.status or '').upper()
            if not order.binance_order_id or not order.symbol:
                continue
            if status in final_statuses:
                if not order.fill_notified:
                    finalized_orders.append(order)
                continue
            if status not in polling_statuses:
                continue
            if order.fill_notified and status in ('FILLED',):
                continue
            relevant_orders.append(order)

        for order in finalized_orders:
            order.fill_notified = True

        if not relevant_orders:
            return

        any_updates = bool(finalized_orders)
        for order in relevant_orders:
            symbol = str(order.symbol or '').upper()
            order_id = int(order.binance_order_id)

            try:
                order_info = client.get_order(symbol=symbol, orderId=order_id)
            except Exception as api_err:
                logger.warning(f"Failed to fetch order {order_id} for user {user_id}: {api_err}")
                continue

            new_status = (order_info.get('status') or order.status or '').upper()
            executed_qty = float(order_info.get('executedQty') or 0)
            cumulative_quote = float(order_info.get('cummulativeQuoteQty') or 0)
            price = float(order_info.get('price') or order.price or 0)
            update_time = order_info.get('updateTime') or order_info.get('time')

            status_changed = new_status != (order.status or '').upper()
            qty_changed = abs(executed_qty - (order.executed_qty or 0.0)) > 1e-12
            quote_changed = abs(cumulative_quote - (order.cumulative_quote_qty or 0.0)) > 1e-8

            if status_changed:
                order.status = new_status
                any_updates = True

            if qty_changed:
                order.executed_qty = executed_qty
                any_updates = True

            if quote_changed:
                order.cumulative_quote_qty = cumulative_quote
                any_updates = True

            if executed_qty > 0:
                fill_price = cumulative_quote / executed_qty if cumulative_quote > 0 else price
                order.avg_fill_price = fill_price

            if update_time:
                try:
                    order.updated_at = datetime.utcfromtimestamp(update_time / 1000)
                except Exception:
                    order.updated_at = datetime.utcnow()

            if new_status == 'FILLED':
                if not order.filled_at:
                    try:
                        order.filled_at = datetime.utcfromtimestamp(update_time / 1000) if update_time else datetime.utcnow()
                    except Exception:
                        order.filled_at = datetime.utcnow()
                    any_updates = True

                if not order.fill_notified:
                    quote_amount = cumulative_quote
                    if quote_amount <= 0 and executed_qty > 0:
                        quote_amount = executed_qty * (price or order.avg_fill_price or order.price or 0.0)

                    notify_order_fill(
                        order,
                        username=username,
                        executed_qty=executed_qty,
                        quote_qty=quote_amount,
                        fill_price=order.avg_fill_price
                    )
                    order.fill_notified = True
                    any_updates = True

            time.sleep(0.15)

        if any_updates:
            db.session.commit()
        else:
            db.session.rollback()

    except Exception as exc:
        logger.error(f"Error syncing real order statuses: {exc}")
        db.session.rollback()

def process_binance_trades(user_id, trades):
    """Process Binance trades and update all_activities table"""
    if not trades:
        return
        
    processed_count = 0
    updated_assets = set()
    
    for trade in trades:
        try:
            trade_time = datetime.utcfromtimestamp(trade['time'] / 1000)
            symbol = trade['symbol']
            
            if symbol.endswith('USDT'):
                asset = symbol.replace('USDT', '')
            elif symbol.endswith('USD'):
                asset = symbol.replace('USD', '')
            else:
                asset = symbol
            
            qty = float(trade['qty'])
            price = float(trade['price'])
            commission = float(trade.get('commission', 0))
            commission_asset = trade.get('commissionAsset', '')
            trade_type = 'BUY' if trade['isBuyer'] else 'SELL'
            usd_value = qty * price
            
            if trade_type == 'BUY':
                proceeds = 0
                cost_basis = usd_value + (commission if commission_asset in ['USDT', 'USD'] else 0)
                amount = qty
            else:
                proceeds = usd_value - (commission if commission_asset in ['USDT', 'USD'] else 0)
                cost_basis = 0
                amount = -qty
            
            txid = f"binance_{trade['id']}_{symbol}"
            existing_tx = AllActivity.query.filter_by(txid=txid).first()
            if not existing_tx:
                new_activity = AllActivity(
                    date=trade_time,
                    type=trade_type,
                    asset=asset,
                    amount=amount,
                    proceeds=proceeds,
                    cost_basis=cost_basis,
                    gain_loss=0,
                    fee=commission,
                    description=f"Binance {trade_type} {qty:.8f} {asset} @ ${price:.2f}",
                    txid=txid,
                    status='completed',
                    details=f"Trade ID: {trade['id']}, Order ID: {trade['orderId']}, Commission: {commission} {commission_asset}",
                    user_id=user_id,
                    avg_entry=price,
                    price_sold_at=price,
                    exchange='binance'
                )
                db.session.add(new_activity)
                processed_count += 1
                updated_assets.add(asset)
            
        except Exception as e:
            logger.error(f"Error processing trade {trade.get('id', 'unknown')}: {e}")
            continue
    
    try:
        db.session.commit()
        if processed_count > 0:
            update_average_entry_prices(user_id, trades)
            for asset in updated_assets:
                try:
                    recalculate_asset_activity(
                        user_id=user_id,
                        asset=asset,
                        price_provider=lambda sym: fetch_binance_price(sym),
                        logger=logger
                    )
                except Exception as recalc_err:
                    logger.warning(f"Failed to recalculate activity for {asset}: {recalc_err}")
    except Exception as e:
        logger.error(f"Error committing trade data: {e}")
        db.session.rollback()

def update_average_entry_prices(user_id, trades):
    """Update average entry prices in coins table based on new trades"""
    try:
        assets = set()
        for trade in trades:
            symbol = trade['symbol']
            if symbol.endswith('USDT'):
                asset = symbol.replace('USDT', '')
            elif symbol.endswith('USD'):
                asset = symbol.replace('USD', '')
            else:
                asset = symbol
            assets.add(asset)
        
        for asset in assets:
            try:
                coin = Coin.query.filter_by(user_id=user_id, symbol=asset).first()
                target_amount = coin.amount if coin else None

                new_avg_entry, cost_basis, total_amount = calculate_avg_entry_fifo(
                    user_id,
                    asset,
                    target_amount=target_amount
                )
                
                if cost_basis >= 1.0 and total_amount > 0:
                    if coin:
                        coin.avg_entry = new_avg_entry
                        coin.updated_at = datetime.utcnow()
                        db.session.commit()
                else:
                    if coin:
                        coin.avg_entry = 0
                        coin.updated_at = datetime.utcnow()
                        db.session.commit()
            except Exception as e:
                logger.error(f"Error updating average entry for {asset}: {e}")
                continue
    except Exception as e:
        logger.error(f"Error updating average entry prices: {e}")

def update_coins_from_binance_balances(user_id, balances, client=None):
    """Update coins table with current balances from Binance.US"""
    try:
        updated_count = 0
        added_count = 0
        assets_from_binance = set()

        for balance in balances:
            asset = balance['asset']
            assets_from_binance.add(asset)
            total = float(balance['free'] or 0) + float(balance['locked'] or 0)

            try:
                existing_coin = Coin.query.filter_by(user_id=user_id, symbol=asset).first()

                if asset == 'ONT' and total > 0:
                    if existing_coin:
                        existing_coin.amount = total
                        existing_coin.hidden = False
                        existing_coin.auto_hidden = False
                        existing_coin.updated_at = datetime.utcnow()
                    else:
                        new_ont = Coin(
                            symbol=asset, user_id=user_id, amount=total,
                            hidden=False, auto_hidden=False, updated_at=datetime.utcnow(),
                            is_manual=False, alert_enabled=True
                        )
                        db.session.add(new_ont)
                    db.session.commit()
                    updated_count += 1
                    continue
                    
                if total <= 0.00000001:
                    if existing_coin and abs(existing_coin.amount) > 0.00000001:
                        existing_coin.amount = 0
                        existing_coin.updated_at = datetime.utcnow()
                        db.session.commit()
                        updated_count += 1
                    continue

                if existing_coin:
                    old_amount = existing_coin.amount
                    amount_increase = total - old_amount

                    if amount_increase > 0.00000001:
                        recent_cutoff = datetime.utcnow() - timedelta(minutes=10)
                        recent_trade_amount = db.session.query(db.func.sum(AllActivity.amount)).filter(
                            AllActivity.user_id == user_id, AllActivity.asset == asset,
                            AllActivity.type == 'BUY', AllActivity.date >= recent_cutoff,
                            AllActivity.status == 'completed'
                        ).scalar() or 0

                        if amount_increase > recent_trade_amount + 0.00000001:
                            purchase_amount = amount_increase - recent_trade_amount
                            try:
                                current_market_price = fetch_binance_price(asset) or 0
                                if current_market_price > 0:
                                    estimated_cost_per_unit = current_market_price * 1.01
                                    cost_basis = purchase_amount * estimated_cost_per_unit
                                    fee = cost_basis - (purchase_amount * current_market_price)

                                    purchase_transaction = AllActivity(
                                        date=datetime.utcnow(), type='BUY', asset=asset,
                                        amount=purchase_amount, proceeds=0, cost_basis=cost_basis,
                                        gain_loss=0, fee=fee, description=f"Binance USD BUY {purchase_amount:.8f} {asset}",
                                        txid=None, status='completed', details="Direct USD purchase detected",
                                        user_id=user_id, avg_entry=estimated_cost_per_unit, exchange='binance'
                                    )
                                    db.session.add(purchase_transaction)
                            except Exception as e:
                                logger.warning(f"Could not calculate USD purchase details for {asset}: {e}")

                    existing_coin.amount = total
                    existing_coin.updated_at = datetime.utcnow()
                    
                    usd_value = total * (existing_coin.current or 0)
                    if existing_coin.hidden and usd_value >= 1.00:
                        existing_coin.hidden = False
                    
                    db.session.commit()
                    updated_count += 1
                else:
                    try:
                        current_price = fetch_binance_price(asset) or 0
                        if current_price > 0:
                            avg_entry = current_price * 1.01
                            new_coin = Coin(
                                symbol=asset, user_id=user_id, current=current_price,
                                amount=total, avg_entry=avg_entry, initial_value=total * avg_entry,
                                purchase_date=datetime.utcnow().strftime('%Y-%m-%d'),
                                is_manual=False, alert_enabled=True, hidden=False, updated_at=datetime.utcnow()
                            )
                            db.session.add(new_coin)
                            
                            new_purchase = AllActivity(
                                date=datetime.utcnow(), type='BUY', asset=asset,
                                amount=total, proceeds=0, cost_basis=total * avg_entry,
                                gain_loss=0, fee=(total * avg_entry * 0.01),
                                description=f"Binance USD BUY {total:.8f} {asset}",
                                txid=None, status='completed', details="Direct USD purchase detected",
                                user_id=user_id, avg_entry=avg_entry, exchange='binance'
                            )
                            db.session.add(new_purchase)
                            db.session.commit()
                            added_count += 1
                        else:
                            new_coin = Coin(
                                symbol=asset, user_id=user_id, current=0, amount=total, avg_entry=0,
                                purchase_date=datetime.utcnow().strftime('%Y-%m-%d'),
                                is_manual=False, alert_enabled=True, hidden=False, updated_at=datetime.utcnow()
                            )
                            db.session.add(new_coin)
                            db.session.commit()
                            added_count += 1
                    except Exception as e:
                        db.session.rollback()
                        logger.warning(f"Could not add new coin {asset}: {e}")
                        
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error updating coin {asset}: {e}")

        try:
            stale_coins = Coin.query.filter(
                Coin.user_id == user_id,
                Coin.symbol.notin_(assets_from_binance),
                Coin.amount > 0.00000001
            ).all()
            for coin in stale_coins:
                coin.amount = 0
                coin.updated_at = datetime.utcnow()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error zeroing absent assets: {e}")

    except Exception as e:
        logger.error(f"Error updating coins from Binance balances: {e}")
sync_portfolio_from_binance = sync_binance_account
update_all_coin_prices_from_binance = lambda: None
