
from datetime import timedelta, datetime
import requests
import threading
from flask import send_file, request, jsonify, render_template, current_app, redirect, url_for
from flask_login import current_user, login_required, login_user, logout_user
from models import Coin, WatchlistCoin, Notification, PriceHistory
from credentials import Credential, User, UserSetting
from core.extensions import db
from log import logger
from routes.helpers import *

from flask import Blueprint
market_bp = Blueprint('market', __name__)



@market_bp.route("/api/pionex-price")
@login_required
def api_pionex_price():
    symbol = request.args.get("symbol", "").upper()
    try:
        # Pionex uses lowercase and USDT pairs, e.g., piusdt
        pair = f"{symbol.lower()}usdt"
        url = f"https://api.pionex.com/api/v1/market/ticker?symbol={pair}"
        r = requests.get(url, timeout=10)
        data = r.json()
        price = float(data["data"]["price"])
        return jsonify({"price": price})
    except Exception as e:
        return jsonify({"price": None, "error": str(e)})

@market_bp.route("/api/chart_history/<symbol>")
@login_required
def chart_history(symbol):
    """Get price history for the last 7 days and return 7 evenly spaced points using ORM"""
    try:
        from models import PriceHistory
        now = int(time.time())
        cutoff = now - 7 * 24 * 60 * 60
        
        # Get all price points for the last 7 days using ORM
        rows = PriceHistory.query.filter(
            PriceHistory.symbol == symbol.upper(),
            PriceHistory.timestamp >= cutoff
        ).order_by(PriceHistory.timestamp.asc()).all()
        
        if not rows:
            return jsonify({"prices": []})

        # Build 7 points: latest at now, then at now-1d, now-2d, ..., now-6d
        points = []
        timestamps = [row.timestamp for row in rows]
        prices = [row.price for row in rows]
        
        for i in range(6, -1, -1):  # 6 days ago to today
            target_ts = now - i * 24 * 60 * 60
            # Find the latest price at or before target_ts
            idx = None
            for j in range(len(timestamps)):
                if timestamps[j] > target_ts:
                    break
                idx = j
            
            if idx is not None:
                points.append([target_ts * 1000, prices[idx]])
            else:
                # If no earlier price, use the earliest available
                points.append([target_ts * 1000, prices[0]])
        
        return jsonify({"prices": points})
    except Exception as e:
        logger.error(f"chart_history: Exception for {symbol}: {e}", exc_info=True)
        return jsonify({"prices": [], "error": str(e)}), 200

@market_bp.route("/api/coingecko_chart/<slug>")
def coingecko_chart(slug):
    now = time.time()
    # Serve from cache if fresh
    cached = COINGECKO_CHART_CACHE.get(slug)
    if cached and now - cached[1] < COINGECKO_CHART_CACHE_TTL:
        return jsonify(cached[0])
    url = f"https://api.coingecko.com/api/v3/coins/{slug}/market_chart?vs_currency=usd&days=7"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 429:
            # Fallback: use local DB
            prices = get_last_7d_prices(slug.upper())
            if prices and len(prices) >= 2:
                # Synthesize CoinGecko-like response
                now_ms = int(time.time()) * 1000
                step = 24 * 60 * 60 * 1000 // max(len(prices)-1, 1)
                price_points = [[now_ms - step * (len(prices)-1-i), p] for i, p in enumerate(prices)]
                data = {"prices": price_points}
                return jsonify(data)
            return jsonify({"error": "CoinGecko rate limit reached and no local data available."}), 429
        if r.status_code != 200:
            return jsonify({"error": f"CoinGecko error {r.status_code} for slug {slug}"}), 404
        data = r.json()
        if "prices" not in data or not data["prices"]:
            # Fallback: use local DB
            prices = get_last_7d_prices(slug.upper())
            if prices and len(prices) >= 2:
                now_ms = int(time.time()) * 1000
                step = 24 * 60 * 60 * 1000 // max(len(prices)-1, 1)
                price_points = [[now_ms - step * (len(prices)-1-i), p] for i, p in enumerate(prices)]
                data = {"prices": price_points}
                return jsonify(data)
            return jsonify({"error": f"No price data for slug {slug}"}), 404
        COINGECKO_CHART_CACHE[slug] = (data, now)
        return jsonify(data)
    except Exception as e:
        # Fallback: use local DB
        prices = get_last_7d_prices(slug.upper())
        if prices and len(prices) >= 2:
            now_ms = int(time.time()) * 1000
            step = 24 * 60 * 60 * 1000 // max(len(prices)-1, 1)
            price_points = [[now_ms - step * (len(prices)-1-i), p] for i, p in enumerate(prices)]
            data = {"prices": price_points}
            return jsonify(data)
        return jsonify({"error": str(e)}), 500

@market_bp.route("/api/coin-data-live")
@login_required
def api_coin_data_live():
    """Live data endpoint for background refresh - Binance only"""
    try:
        logger.error("=== API_COIN_DATA_LIVE CALLED ===")
        coins = Coin.query.filter_by(user_id=current_user.id).all()
        logger.error(f"[LIVE] DB coins: {[c.symbol for c in coins]}")
        logger.error(f"[LIVE] User ID: {current_user.id}")
        logger.error(f"[LIVE] Total coins found: {len(coins)}")

        portfolio = []
        visibility_changed = False
        price_changed = False

        def _to_float(val):
            try:
                if isinstance(val, str):
                    return float(val.replace(',', '').strip())
                return float(val)
            except Exception:
                return 0.0

        news_cache = get_user_latest_news_cache(current_user.id)

        for coin in coins:
            try:
                symbol = (coin.symbol or '').upper()
                logger.error(f"[LIVE] Processing coin: {symbol}")
                amount = _to_float(coin.amount)
                logger.error(f"[LIVE] {symbol} amount: {amount}")

                current_price = coin.current or 0.0
                if not current_price:
                    try:
                        current_price = fetch_crypto_price(coin.symbol)
                        coin.current = current_price
                        price_changed = True
                    except Exception as e:
                        logger.error(f"[LIVE] Failed to fetch price for {symbol}: {e}")
                        try:
                            current_price = float((coin.avg_entry or 0)) if not isinstance(coin.avg_entry, str) else float(coin.avg_entry.replace(',', '').strip())
                        except Exception:
                            current_price = 0.0

                current_value = amount * current_price if current_price else 0.0
                logger.error(f"[LIVE] {symbol} current_value: {current_value}")

                if apply_auto_visibility_rules(coin, current_value):
                    visibility_changed = True

                if coin.hidden:
                    logger.error(f"[LIVE] {symbol} skipped: hidden flag")
                    continue

                if amount <= 0 and not coin.force_visible:
                    logger.error(f"[LIVE] {symbol} skipped: amount <= 0 and not force_visible")
                    continue

                avg_entry_val = _to_float(coin.avg_entry)
                pct_change = 0.0
                if avg_entry_val > 0:
                    pct_change = ((current_price - avg_entry_val) / avg_entry_val) * 100

                sentiment = get_coin_sentiment(symbol, coin, current_price, current_user.username)
                coin_news = news_cache.get(coin.id, {})

                logger.error(f"[LIVE] {symbol} included in portfolio response")
                portfolio.append({
                    "id": coin.id,
                    "symbol": symbol,
                    "amount": amount,
                    "initial_price": avg_entry_val,
                    "avg_entry": avg_entry_val,
                    "initial_value": (coin.initial_value if _to_float(coin.initial_value) > 0 else (avg_entry_val * amount if avg_entry_val and amount else 0.0)),
                    "purchase_date": coin.purchase_date,
                    "current_price": current_price,
                    "current_value": current_value,
                    "pct_change": pct_change,
                    "sentiment": sentiment,
                    "sentiment_reason": getattr(coin, 'sentiment_reason', "") or "",
                    "alert_enabled": coin.alert_enabled,
                    "note": coin.note,
                    "custom_lower_val": coin.custom_lower_val,
                    "custom_upper_val": coin.custom_upper_val,
                    "custom_lower_type": coin.custom_lower_type or "#",
                    "custom_upper_type": coin.custom_upper_type or "#",
                    "down_alert": coin.custom_lower_val,
                    "up_alert": coin.custom_upper_val,
                    "favorite": coin.is_manual,
                    "force_visible": coin.force_visible,
                    "volatility_pct": coin.volatility_pct,
                    "sentiment_last_updated": format_iso_utc(coin.sentiment_last_updated) if hasattr(coin, 'sentiment_last_updated') and coin.sentiment_last_updated else None,
                    "cached_news": coin_news.get('text', ''),
                    "cached_news_date": coin_news.get('created_at', None)
                })
            except Exception as e:
                logger.error(f"[LIVE] Error processing coin {getattr(coin,'symbol','?')}: {e}", exc_info=True)
                try:
                    symbol = (coin.symbol or '').upper()
                    amount = _to_float(getattr(coin, 'amount', 0))
                    avg_entry_val = _to_float(getattr(coin, 'avg_entry', 0))
                    current_price = _to_float(getattr(coin, 'current', 0)) or avg_entry_val
                    current_value = amount * (current_price or 0)
                    cid = getattr(coin, 'id', None)
                    fallback_news = news_cache.get(cid, {}) if cid else {}
                    logger.error(f"[LIVE] {symbol} fallback included in portfolio response")
                    portfolio.append({
                        "id": getattr(coin, 'id', None),
                        "symbol": symbol,
                        "amount": amount,
                        "initial_price": avg_entry_val,
                        "avg_entry": avg_entry_val,
                        "initial_value": (getattr(coin, 'initial_value', 0) if _to_float(getattr(coin, 'initial_value', 0)) > 0 else (avg_entry_val * amount if avg_entry_val and amount else 0.0)),
                        "purchase_date": getattr(coin, 'purchase_date', None),
                        "current_price": current_price,
                        "current_value": current_value,
                        "pct_change": 0.0,
                        "sentiment": getattr(coin, 'sentiment', 'Error') or 'Error',
                        "sentiment_reason": getattr(coin, 'sentiment_reason', "") or "",
                        "alert_enabled": getattr(coin, 'alert_enabled', True),
                        "note": getattr(coin, 'note', ''),
                        "custom_lower_val": getattr(coin, 'custom_lower_val', None),
                        "custom_upper_val": getattr(coin, 'custom_upper_val', None),
                        "custom_lower_type": (getattr(coin, 'custom_lower_type', None) or "#"),
                        "custom_upper_type": (getattr(coin, 'custom_upper_type', None) or "#"),
                        "down_alert": getattr(coin, 'custom_lower_val', None),
                        "up_alert": getattr(coin, 'custom_upper_val', None),
                        "favorite": getattr(coin, 'is_manual', False),
                        "force_visible": getattr(coin, 'force_visible', False),
                        "volatility_pct": getattr(coin, 'volatility_pct', None),
                        "sentiment_last_updated": format_iso_utc(getattr(coin, 'sentiment_last_updated', None)),
                        "cached_news": fallback_news.get('text', ''),
                        "cached_news_date": fallback_news.get('created_at', None)
                    })
                except Exception:
                    logger.error(f"[LIVE] {symbol} fallback failed, coin skipped")
                    pass

        if visibility_changed or price_changed:
            db.session.commit()

        logger.error(f"[LIVE] Final portfolio response: {[c['symbol'] for c in portfolio]}")
        return jsonify({"portfolio": portfolio})

    except Exception as e:
        logger.error(f"Error in api_coin_data_live: {e}")
        db.session.rollback()
        return jsonify({"portfolio": [], "error": "Error retrieving portfolio data"}), 500

@market_bp.route("/api/coin-data")
@login_required
def api_coin_data():
    """Get user's cryptocurrency portfolio data with Binance balance sync"""
    logger.error("=== API_COIN_DATA CALLED ===")
    try:
        coins = Coin.query.filter_by(user_id=current_user.id).all()
        # logger.error(f"[DEBUG] DB coins: {[c.symbol for c in coins]}")
        # logger.error(f"[DEBUG] User ID: {current_user.id}")
        # logger.error(f"[DEBUG] Total coins found: {len(coins)}")

        portfolio = []
        visibility_changed = False
        price_changed = False

        def _to_float(val):
            try:
                if isinstance(val, str):
                    return float(val.replace(',', '').strip())
                return float(val)
            except Exception:
                return 0.0

        news_cache = get_user_latest_news_cache(current_user.id)

        for coin in coins:
            try:
                symbol = coin.symbol.upper()
                # logger.error(f"[DEBUG] Processing coin: {symbol}")
                amount = _to_float(coin.amount)
                # logger.error(f"[DEBUG] {symbol} amount: {amount}")

                if symbol in ['USD', 'USDT', 'USDC', 'DAI']:
                    current_price = 1.0
                else:
                    current_price = coin.current or _to_float(coin.avg_entry) or 0

                current_value = amount * current_price if current_price else 0
                # logger.error(f"[DEBUG] {symbol} current_value: {current_value}")

                if apply_auto_visibility_rules(coin, current_value):
                    visibility_changed = True

                if coin.hidden:
                    # logger.error(f"[DEBUG] {symbol} skipped: hidden flag")
                    continue

                if amount <= 0 and not coin.force_visible:
                    # logger.error(f"[DEBUG] {symbol} skipped: amount <= 0 and not force_visible")
                    continue

                cost_basis = get_cost_basis_for_asset(current_user.id, symbol)
                avg_entry_val = _to_float(coin.avg_entry)
                pct_change = round(((current_price - avg_entry_val) / avg_entry_val * 100), 6) if avg_entry_val and current_price else 0.0
                purchase_date = coin.purchase_date
                coin_news = news_cache.get(coin.id, {})

                # logger.error(f"[DEBUG] {symbol} included in portfolio response")
                portfolio.append({
                    "id": coin.id,
                    "symbol": symbol,
                    "initial_price": avg_entry_val,
                    "avg_entry": avg_entry_val,
                    "initial_value": (coin.initial_value if _to_float(coin.initial_value) > 0 else (avg_entry_val * amount if avg_entry_val and amount else 0.0)),
                    "purchase_date": purchase_date,
                    "current_price": current_price,
                    "amount": amount,
                    "cost_basis": cost_basis,
                    "current_value": round(current_value, 6),
                    "pct_change": pct_change,
                    "custom_lower_pct": coin.custom_lower_pct,
                    "custom_upper_pct": coin.custom_upper_pct,
                    "custom_lower_type": coin.custom_lower_type or "#",
                    "custom_upper_type": coin.custom_upper_type or "#",
                    "custom_lower_val": coin.custom_lower_val,
                    "custom_upper_val": coin.custom_upper_val,
                    "down_alert": coin.custom_lower_val,
                    "up_alert": coin.custom_upper_val,
                    "alert_enabled": coin.alert_enabled,
                    "favorite": coin.is_manual,
                    "hidden": coin.hidden,
                    "has_note": False,
                    "hasPendingOrder": False,
                    "sentiment": coin.sentiment or get_coin_sentiment(symbol, coin=coin, current_price=current_price, username=current_user.username),
                    "sentiment_reason": getattr(coin, 'sentiment_reason', "") or "",
                    "force_visible": coin.force_visible,
                    "volatility_pct": coin.volatility_pct,
                    "sentiment_last_updated": format_iso_utc(coin.sentiment_last_updated) if hasattr(coin, 'sentiment_last_updated') and coin.sentiment_last_updated else None,
                    "cached_news": coin_news.get('text', ''),
                    "cached_news_date": coin_news.get('created_at', None)
                })
            except Exception as e:
                logger.error(f"[api_coin_data] Error processing coin {getattr(coin,'symbol','?')}: {e}", exc_info=True)
                continue

        if visibility_changed or price_changed:
            db.session.commit()

        # logger.error(f"[DEBUG] Final portfolio response: {[c['symbol'] for c in portfolio]}")
        return jsonify({"portfolio": portfolio})
    except Exception as e:
        logger.error(f"api_coin_data error: {str(e)}")
        logger.error(f"Exception type: {type(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        logger.error(f"Unexpected error in api_coin_data: {str(e)}")
        return jsonify({"portfolio": []})

@market_bp.route("/api/auto-alert")
@login_required
def api_auto_alert():
    coin_id = request.args.get("id")
    symbol = request.args.get("symbol")
    alert_type = request.args.get("type")
    try:
        now = datetime.utcnow()
        cache_key = None
        initial_price = None

        # Portfolio coin
        if coin_id:
            coin = Coin.query.filter_by(id=coin_id, user_id=current_user.id).first()
            if not coin:
                logger.error(f"[auto-alert] Coin not found for id={coin_id}")
                return jsonify({"value": 10.0})
            symbol = coin.symbol
            initial_price = coin.initial_price
            cache_key = (symbol, alert_type)
        elif symbol:
            cache_key = (symbol.upper(), alert_type)
            wl = WatchlistCoin.query.filter_by(user_id=current_user.id, symbol=symbol.upper()).first()
            if wl:
                initial_price = None  # Use first price from get_last_7d_prices

        # Check cache
        cached = AUTO_ALERT_CACHE.get(cache_key)
        if cached and (datetime.utcnow() - cached['updated']) < timedelta(hours=2):
            logger.error(f"[auto-alert] Returning cached value for {cache_key}: {cached['value']}")
            return jsonify({"value": cached['value']})

        # Calculate and cache
        value = calculate_auto_alert(symbol, alert_type, initial_price)
        logger.error(f"[auto-alert] Calculated value for {symbol} {alert_type}: {value} (initial_price={initial_price})")
        AUTO_ALERT_CACHE[cache_key] = {'value': value, 'updated': now}
        return jsonify({"value": value})
    except Exception as e:
        logger.error(f"auto-alert error: {str(e)}")
        return jsonify({"value": 10.0})

@market_bp.route('/api/market-data/<symbol>')
@login_required
def api_market_data(symbol):
    """Get market data for a specific symbol from Binance"""
    try:
        # Get Binance credentials for the user
        creds = Credential.query.filter_by(user_id=current_user.id).first()
        
        if not creds:
            return jsonify({'error': 'Binance API credentials not configured'}), 401
        
        api_key = decrypt_secret(creds.api_key)
        api_secret = decrypt_secret(creds.api_secret)
        if not api_key or not api_secret:
            return jsonify({'error': 'Binance API credentials not configured'}), 401
        
        # Initialize Binance client
        from binance.client import Client
        client = Client(
            api_key=api_key,
            api_secret=api_secret,
            tld='us'  # Use Binance.US
        )
        
        # Get 24hr ticker data
        ticker_symbol = f"{symbol}USDT" if not symbol.endswith('USDT') else symbol
        ticker = client.get_24hr_ticker(symbol=ticker_symbol)
        
        market_data = {
            'price': float(ticker['lastPrice']),
            'change_24h': float(ticker['priceChangePercent']),
            'high_24h': float(ticker['highPrice']),
            'low_24h': float(ticker['lowPrice']),
            'volume_24h': float(ticker['volume'])
        }
        
        return jsonify(market_data)
        
    except Exception as e:
        logger.error(f"Error fetching market data for {symbol}: {e}")
        return jsonify({'error': 'Failed to fetch market data'}), 500
        return jsonify(market_data)
    except Exception as e:
        logger.error(f"Market data error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@market_bp.route('/api/widgets/fear-greed', methods=['GET'])
def api_fear_greed_index():
    """Proxy endpoint for Fear & Greed Index to avoid CORS issues"""
    try:
        import requests
        response = requests.get('https://api.alternative.me/fng/', timeout=10)
        response.raise_for_status()
        return jsonify(response.json())
    except Exception as e:
        logger.error(f"Error fetching Fear & Greed Index: {e}")
        return jsonify({"error": "Failed to fetch Fear & Greed Index"}), 500

@market_bp.route('/api/widgets/cbbi', methods=['GET'])
def api_cbbi_data():
    """Proxy endpoint for CBBI data to avoid CORS issues"""
    try:
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get('https://colintalkscrypto.com/cbbi/data/latest.json', 
                              timeout=10, 
                              headers=headers,
                              verify=True)
        response.raise_for_status()
        data = response.json()
        
        # Extract the Confidence data which contains the actual CBBI values (not 2YMA)
        if isinstance(data, dict):
            if 'Confidence' in data:
                # Use Confidence data which is the actual CBBI score
                cbbi_data = data['Confidence']
                return jsonify({"confidence": cbbi_data})
            elif 'confidence' in data and 'Confidence' in data['confidence']:
                # Data is structured differently - extract Confidence
                return jsonify({"confidence": data['confidence']['Confidence']})
            elif 'confidence' not in data:
                # Raw timestamp data - wrap it properly (fallback)
                return jsonify({"confidence": data})
            else:
                # Already has proper structure
                return jsonify(data)
        else:
            # Unexpected data format
            raise Exception("Unexpected API response format")
            
    except Exception as e:
        logger.error(f"Error fetching CBBI data: {e}")
        # Return mock data if the real API fails
        from datetime import datetime
        current_timestamp = int(datetime.now().timestamp())
        mock_data = {
            "confidence": {
                str(current_timestamp): 0.25  # 25% confidence (moderate risk)
            }
        }
        return jsonify(mock_data)