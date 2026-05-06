import hmac
import hashlib
import time
import requests
import json
from datetime import datetime, timedelta
from flask import current_app, jsonify, make_response
from flask_login import current_user
from core.extensions import db
from log import logger
from models import StakedCoin
from trading_models import StakingOrder
from services.binance_service import fetch_binance_price
from services.common import _coerce_float

def binance_us_api_call(cred, endpoint, method='GET', params_dict=None, use_trading_keys=False):
    """Make a signed call to the Binance.US SAPI endpoints."""
    try:
        if use_trading_keys:
            api_key = cred.trading_api_key
            api_secret = cred.trading_api_secret
        else:
            api_key = cred.api_key
            api_secret = cred.api_secret

        if not api_key or not api_secret:
            raise ValueError("Missing API keys for Binance.US call")

        base_url = "https://api.binance.us"
        url = f"{base_url}{endpoint}"
        
        timestamp = int(time.time() * 1000)
        params = params_dict.copy() if params_dict else {}
        params['timestamp'] = timestamp
        
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(
            api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        url = f"{url}?{query_string}&signature={signature}"
        headers = {'X-MBX-APIKEY': api_key}
        
        if method == 'GET':
            return requests.get(url, headers=headers, timeout=20)
        elif method == 'POST':
            return requests.post(url, headers=headers, timeout=20)
        
    except Exception as e:
        logger.error(f"Binance.US API call failed: {e}")
        raise

def calculate_staking_value_for_user(cred, user_id=None):
    """Return tuple (active_value_usd, pending_value_usd) for Binance.US staking balances."""
    active_value = 0.0
    pending_value = 0.0

    if not cred:
        return active_value, pending_value

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
            for record in staked_records:
                asset = (record.symbol or '').upper()
                amount = float(record.amount or 0.0)
                status = (record.status or 'active').lower()
                
                if active_api_ok and status == 'active' and asset in found_symbols:
                    continue
                
                if not asset or amount <= 0:
                    continue
                
                price = fetch_binance_price(asset) or _fallback_price(asset)
                if price:
                    active_value += amount * price
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
            return default_result

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
        
        asset_metadata = {}
        asset_metadata_by_product = {}
        active_api_ok = False
        
        try:
            balance_response = binance_us_api_call(cred, '/sapi/v1/staking/stakingBalance', method='GET', use_trading_keys=True)
            if balance_response.status_code == 200:
                balance_payload = balance_response.json()
                if isinstance(balance_payload, dict) and (balance_payload.get('success') is True or balance_payload.get('code') == '000000'):
                    staking_data = balance_payload.get('data', [])
                    active_api_ok = True
                elif isinstance(balance_payload, list):
                    staking_data = balance_payload
                    active_api_ok = True
            else:
                return default_result
        except Exception:
            return default_result

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
                        price = fetch_binance_price(asset) or get_local_price(asset)
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
            price = fetch_binance_price(asset) or get_local_price(asset)
            current_value = amount * price if price else 0.0
            
            metadata = get_asset_metadata(asset, staked.get('productId'))
            apy = _coerce_float(metadata.get('apy') or metadata.get('apr') or staked.get('apy'), 0.0)

            pos = {
                'asset': asset, 'amount': amount, 'currentValue': round(current_value, 2),
                'currentPrice': price, 'apy': apy, 'status': 'active'
            }
            positions.append(pos)
            active_positions.append(pos)
            active_usd += current_value
            total_apy += apy

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
            'pendingPositions': pending_positions, 'summary': summary,
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
