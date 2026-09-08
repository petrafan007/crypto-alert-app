import hmac
import hashlib
import time
import socket
import requests
import json
import urllib3.util.connection as urllib3_cn
from datetime import datetime, timedelta
from flask import current_app, jsonify, make_response
from flask_login import current_user
from core.extensions import db
from log import logger
from models import StakedCoin
from trading_models import StakingOrder
from services.binance_service import fetch_binance_price
from services.common import _coerce_float

# Ensure Binance.US API calls always use IPv4
try:
    urllib3_cn.allowed_gai_family = lambda: socket.AF_INET
except Exception:
    pass

# Successful read responses only; per-key locks coalesce concurrent dashboard requests.
from threading import Lock
from urllib.parse import urlencode
from copy import deepcopy

_read_cache = {}
_read_locks = [Lock() for _ in range(64)]
_cache_guard = Lock()


def invalidate_staking_cache(cred):
    with _cache_guard:
        _read_cache.clear()


def binance_us_api_call(cred, endpoint, method='GET', params_dict=None, use_trading_keys=False):
    """Signed Binance.US request, matching key pairs and bounded cached reads."""
    trading = use_trading_keys and getattr(cred, 'trading_api_key', None) and getattr(cred, 'trading_api_secret', None)
    api_key = cred.trading_api_key if trading else getattr(cred, 'api_key', None)
    api_secret = cred.trading_api_secret if trading else getattr(cred, 'api_secret', None)
    if not api_key or not api_secret:
        raise ValueError('Missing Binance.US API credentials')
    params = dict(params_dict or {})
    if endpoint == '/sapi/v1/staking/history':
        params.setdefault('limit', 200)
    key = (hashlib.sha256(api_key.encode()).hexdigest(), endpoint, urlencode(sorted(params.items())))
    ttl = 120 if endpoint.endswith('/asset') else 15
    cacheable = method == 'GET' and endpoint.startswith('/sapi/v1/staking/')
    lock = _read_locks[hash(key) % len(_read_locks)]
    with lock:
        cached = _read_cache.get(key)
        if cacheable and cached and time.monotonic() - cached[0] < ttl:
            return deepcopy(cached[1])
        params['timestamp'] = int(time.time() * 1000)
        query = urlencode(params, doseq=True)
        signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        response = requests.request(method, f'https://api.binance.us{endpoint}?{query}&signature={signature}',
                                    headers={'X-MBX-APIKEY': api_key}, timeout=(3, 8))
        if cacheable and response.status_code == 200:
            payload = response.json()
            if not isinstance(payload, dict) or (payload.get('success') is not False and str(payload.get('code', '0')) in ('0', '000000', '200')):
                with _cache_guard:
                    if len(_read_cache) > 512:
                        _read_cache.clear()
                    _read_cache[key] = (time.monotonic(), deepcopy(response))
        if method != 'GET':
            invalidate_staking_cache(cred)
        return response


def staking_rate(value):
    """Binance.US numeric APR/APY fields are fractions, including rates above 100%."""
    try:
        rate = float(str(value).replace('%', '').strip())
        return rate / 100 if '%' in str(value) else rate
    except (TypeError, ValueError):
        return 0.0


def staking_catalog(cred):
    response = binance_us_api_call(cred, '/sapi/v1/staking/asset', use_trading_keys=True)
    payload = response.json()
    if response.status_code != 200 or isinstance(payload, dict) and (payload.get('success') is False or str(payload.get('code', '0')) not in ('0', '000000', '200')):
        raise ValueError('Binance.US staking catalog is temporarily unavailable.')
    rows = payload.get('data', []) if isinstance(payload, dict) else payload
    result = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get('stakingAsset'):
            continue
        rate = row.get('apy') if row.get('apy') is not None else row.get('apr', 0)
        result.append({**row, 'apy': staking_rate(rate), 'rateLabel': 'APY' if row.get('apy') is not None else 'APR'})
    return result

def calculate_staking_value_for_user(cred, user_id=None):
    """Return tuple (active_value_usd, pending_value_usd) for Binance.US staking balances."""
    active_value = 0.0
    pending_value = 0.0

    if not cred:
        return active_value, pending_value

    api_key = getattr(cred, 'api_key', None) or getattr(cred, 'trading_api_key', None)
    api_secret = getattr(cred, 'api_secret', None) or getattr(cred, 'trading_api_secret', None)
    has_binance_keys = bool(api_key and api_secret)

    target_user_id = user_id or getattr(current_user, 'id', None)

    def _fallback_price(symbol, default=None):
        if target_user_id is None:
            return default
        try:
            from models import Coin as CoinModel
            coin_record = CoinModel.query.filter_by(user_id=target_user_id, symbol=symbol).first()
            if coin_record:
                candidate = coin_record.current or coin_record.avg_entry
                if candidate and candidate > 0:
                    return float(candidate)
        except Exception:
            pass
        return default

    found_symbols = set()
    active_api_ok = False
    if has_binance_keys:
        try:
            balance_response = binance_us_api_call(
                cred, '/sapi/v1/staking/stakingBalance', method='GET', use_trading_keys=True
            )
            if balance_response.status_code == 200:
                active_api_ok = True
                balance_payload = balance_response.json()
                staking_items = balance_payload.get('data', [])
                for staked in staking_items:
                    asset = str(staked.get('asset', '')).upper()
                    amount = _coerce_float(staked.get('stakingAmount'), 0.0)
                    if amount == 0.0:
                        amount = _coerce_float(staked.get('amount'), 0.0)

                    if not asset or amount <= 0:
                        continue

                    found_symbols.add(asset)
                    price = fetch_binance_price(asset) or _fallback_price(asset)
                    if price:
                        active_value += amount * price
        except Exception as staking_err:
            logger.error(f"Error calculating staking active value: {staking_err}")

    pending_api_ok = False
    if has_binance_keys:
        try:
            history_response = binance_us_api_call(
                cred, '/sapi/v1/staking/history', method='GET', params_dict={'limit': 200}, use_trading_keys=True
            )
            if history_response.status_code == 200:
                pending_api_ok = True
                history_payload = history_response.json()
                history_entries = history_payload.get('data', []) if isinstance(history_payload, dict) else history_payload

                for entry in history_entries:
                    status_raw = str(entry.get('status', '')).upper()
                    if status_raw in {'SUCCESS', 'COMPLETED', 'FAILED', 'CANCELLED', 'CANCELED'}:
                        continue
                    asset = str(entry.get('asset', '')).upper()
                    amount = _coerce_float(entry.get('amount'), 0.0) or 0.0
                    if not asset or amount <= 0:
                        continue
                    price = fetch_binance_price(asset) or _fallback_price(asset)
                    if price:
                        pending_value += amount * price
        except Exception as pending_err:
            logger.error(f"Error calculating pending staking value: {pending_err}")

    if target_user_id is not None:
        try:
            staked_records = StakedCoin.query.filter_by(user_id=target_user_id).all()
            dirty = False
            for record in staked_records:
                asset = (record.symbol or '').upper()
                amount = float(record.amount or 0.0)
                status = (record.status or 'active').lower()
                
                # If the live Binance staking API responded successfully, it is authoritative
                if active_api_ok:
                    if status == 'active' and asset not in found_symbols:
                        record.status = 'unstaked'
                        dirty = True
                    continue
                
                if status != 'active' or not asset or amount <= 0:
                    continue
                
                price = fetch_binance_price(asset) or _fallback_price(asset)
                if price:
                    active_value += amount * price
            if dirty:
                try:
                    db.session.commit()
                except Exception as commit_err:
                    db.session.rollback()
                    logger.error(f"Error committing unstaked coin updates: {commit_err}")
        except Exception as local_err:
            logger.error(f"Local staking fallback lookup failed: {local_err}")

    return active_value, pending_value

def binance_has_staking_permission(cred):
    """Best-effort check to see if the key can access staking endpoints."""
    try:
        response = binance_us_api_call(cred, '/sapi/v1/staking/asset', method='GET', use_trading_keys=True)
        if response.status_code == 200:
            return True
        try:
            payload = response.json()
            message = str(payload.get('msg') or payload)
        except ValueError:
            message = response.text
        lower_msg = (message or '').lower()
        if response.status_code in (401, 403) or 'permission' in lower_msg or 'not authorized' in lower_msg:
            return False
        return None
    except Exception as exc:
        logger.error(f"Failed to inspect Binance staking permissions: {exc}")
        return None

def build_staking_balance_view(cred, asset_param=None):
    """Consolidated staking balance data used by both balance and dashboard endpoints."""
    default_summary = {
        'activeCount': 0, 'pendingCount': 0, 'activeUsd': 0.0, 'pendingUsd': 0.0,
        'totalUsd': 0.0, 'avgApy': 0.0
    }
    default_result = {
        'balances': [], 'activePositions': [], 'pendingPositions': [],
        'pendingTransactions': [], 'summary': default_summary, 'totalStakedValue': 0.0
    }

    try:
        api_key = getattr(cred, 'api_key', None) or getattr(cred, 'trading_api_key', None)
        api_secret = getattr(cred, 'api_secret', None) or getattr(cred, 'trading_api_secret', None)
        if not api_key or not api_secret:
            return {**default_result, 'error': 'Staking balance unavailable; check the Binance.US API connection.'}

        params = {}
        if asset_param:
            params['asset'] = asset_param
        
        from models import Coin as CoinModel
        user_id = getattr(current_user, 'id', None)

        def get_local_price(symbol, default=None):
            if not user_id: return default
            try:
                coin_record = CoinModel.query.filter_by(user_id=user_id, symbol=symbol).first()
                if coin_record:
                    candidate = coin_record.current or coin_record.avg_entry
                    if candidate and candidate > 0: return float(candidate)
            except Exception: pass
            return default
        
        staking_data = []
        price_cache = {}
        def asset_price(symbol):
            if symbol not in price_cache:
                price_cache[symbol] = get_local_price(symbol) or fetch_binance_price(symbol)
            return price_cache[symbol]

        asset_metadata = {}
        asset_metadata_by_product = {}
        active_api_ok = False
        
        try:
            balance_response = binance_us_api_call(cred, '/sapi/v1/staking/stakingBalance', method='GET', use_trading_keys=True)
            if balance_response.status_code == 200:
                balance_payload = balance_response.json()
                if isinstance(balance_payload, dict) and balance_payload.get('success') is not False and 'data' in balance_payload:
                    staking_data = balance_payload.get('data', [])
                    active_api_ok = True
                elif isinstance(balance_payload, list):
                    staking_data = balance_payload
                    active_api_ok = True
            else:
                return {**default_result, 'error': 'Staking balance unavailable; check the Binance.US API connection.'}
        except Exception:
            return {**default_result, 'error': 'Staking balance unavailable; check the Binance.US API connection.'}

        try:
            asset_response = binance_us_api_call(cred, '/sapi/v1/staking/asset', method='GET', use_trading_keys=True)
            if asset_response.status_code == 200:
                asset_payload = asset_response.json()
                asset_iterable = asset_payload.get('data') if isinstance(asset_payload, dict) else asset_payload
                for asset_info in (asset_iterable or []):
                    symbol = str(asset_info.get('stakingAsset') or asset_info.get('asset') or '').upper()
                    product_key = str(asset_info.get('productId') or asset_info.get('product') or '')
                    if symbol:
                        asset_metadata.setdefault(symbol, asset_info)
                        if product_key:
                            asset_metadata_by_product[f"{symbol}:{product_key}"] = asset_info
        except Exception: pass

        def get_asset_metadata(symbol: str, product_id=None):
            normalized = (symbol or '').upper()
            if not normalized: return None
            if product_id:
                prod_key = f"{normalized}:{product_id}"
                if prod_key in asset_metadata_by_product: return asset_metadata_by_product[prod_key]
            return asset_metadata.get(normalized)

        # Pending transactions (history)
        pending_transactions = []
        try:
            history_response = binance_us_api_call(cred, '/sapi/v1/staking/history', method='GET', params_dict={'limit': 200}, use_trading_keys=True)
            if history_response.status_code == 200:
                history_data = history_response.json().get('data', []) if isinstance(history_response.json(), dict) else history_response.json()
                for txn in history_data:
                    status_raw = str(txn.get('status', '')).upper()
                    if status_raw and status_raw not in {'SUCCESS', 'COMPLETED', 'FAILED', 'CANCELLED', 'CANCELED'}:
                        asset = str(txn.get('asset', '')).upper()
                        amount = _coerce_float(txn.get('amount'), 0.0)
                        price = asset_price(asset)
                        pending_transactions.append({
                            'tranId': txn.get('tranId'), 'asset': asset, 'amount': amount,
                            'status': status_raw, 'initiatedTime': txn.get('initiatedTime'),
                            'currentPrice': price, 'currentValue': round(amount * price, 2) if price else 0.0
                        })
        except Exception: pass

        staked_coin_records = StakedCoin.query.filter_by(user_id=user_id).all()
        db_lookup = {}
        for record in staked_coin_records:
            db_lookup.setdefault(record.symbol.upper(), []).append(record)

        positions = []
        active_positions = []
        pending_positions = []
        active_usd = 0.0
        pending_usd = 0.0
        total_usd = 0.0
        total_apy = 0.0
        found_symbols = set()

        for staked in staking_data:
            asset = str(staked.get('asset', '')).upper()
            found_symbols.add(asset)
            amount = _coerce_float(staked.get('stakingAmount') or staked.get('amount'), 0.0)
            price = asset_price(asset)
            current_value = amount * price if price else 0.0
            
            metadata = get_asset_metadata(asset, staked.get('productId')) or {}
            raw_apy = metadata.get('apy') or metadata.get('apr') or metadata.get('annualPercentageRate') or metadata.get('rewardRate') or metadata.get('estApr') or staked.get('apy') or staked.get('apr') or 0.0
            try:
                apy = float(str(raw_apy).replace('%', '').strip())
                if '%' in str(raw_apy):
                    apy = apy / 100.0
            except Exception:
                apy = 0.0

            pos = {
                'asset': asset, 'amount': amount, 'currentValue': round(current_value, 2),
                'currentPrice': price, 'apy': apy, 'status': 'active'
            }
            positions.append(pos)
            active_positions.append(pos)
            active_usd += current_value
            total_apy += apy

        # Pending records are distinct from active exchange balances. History IDs
        # prevent counting a locally recorded request and its exchange entry twice.
        seen_transactions = set()
        for txn in pending_transactions:
            transaction_id = str(txn.get('tranId') or '')
            if transaction_id:
                seen_transactions.add(transaction_id)
            pending_positions.append({**txn, 'stakingAmount': txn['amount'], 'status': txn['status']})
            pending_usd += txn.get('currentValue', 0)
        for record in staked_coin_records:
            if str(record.status or '').lower() not in ('pending', 'bonding', 'unstaking'):
                continue
            if str(record.stake_transaction_id or '') in seen_transactions or record.symbol in found_symbols:
                continue
            price = asset_price(record.symbol) or 0
            value = float(record.amount or 0) * price
            pending_positions.append({'id': record.id, 'asset': record.symbol, 'stakingAmount': record.amount,
                'currentValue': value, 'status': record.status})
            pending_usd += value

        summary = {
            'activeCount': len(active_positions),
            'pendingCount': len(pending_positions),
            'activeUsd': round(active_usd, 2),
            'pendingUsd': round(pending_usd, 2),
            'totalUsd': round(active_usd + pending_usd, 2),
            'avgApy': round((total_apy / len(active_positions) * 100) if active_positions else 0, 2)
        }

        return {
            'balances': positions, 'activePositions': active_positions,
            'pendingPositions': pending_positions, 'pendingTransactions': pending_transactions, 'summary': summary,
            'totalStakedValue': summary['totalUsd']
        }
    except Exception as e:
        logger.error(f"Error building staking balance view: {e}")
        return default_result

def _build_staking_dashboard_payload(cred):
    overview = build_staking_balance_view(cred)
    summary = overview.get('summary', {})
    
    total_rewards_usd = 0.0
    try:
        from models import StakingReward
        rewards = StakingReward.query.filter_by(user_id=current_user.id).all()
        total_rewards_usd = sum(r.usd_value for r in rewards if r.usd_value)
    except Exception: pass

    return {
        'totalStakedValue': summary.get('totalUsd', 0.0),
        'activePositions': summary.get('activeCount', 0),
        'pendingPositions': summary.get('pendingCount', 0),
        'totalRewards': round(total_rewards_usd, 2),
        'avgApy': summary.get('avgApy', 0.0),
        'activeValue': summary.get('activeUsd', 0.0),
        'pendingValue': summary.get('pendingUsd', 0.0),
        'totalValue': summary.get('totalUsd', 0.0)
    }

def _dashboard_staking_response(cred):
    if not cred:
        return make_response(jsonify({
            'totalStakedValue': 0, 'activePositions': 0, 'pendingPositions': 0,
            'totalRewards': 0, 'avgApy': 0, 'activeValue': 0, 'pendingValue': 0, 'totalValue': 0
        }))
    return make_response(jsonify(_build_staking_dashboard_payload(cred)))
