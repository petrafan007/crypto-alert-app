"""Asynchronous, durable imports for provider order history."""

from datetime import datetime, timedelta, timezone
import json
import time

from binance.client import Client

from core.extensions import db
from credentials import Credential, User, UserSetting
from log import logger
from models import BinanceOrder, Coin, OrderHistorySyncState
from trading_models import RealOrder
from services.webull_import_service import import_webull_orders
from services.webull_service import (
    get_webull_accounts,
    get_webull_order_history,
    get_webull_open_orders,
    normalize_webull_environment,
)


BINANCE_ORDER_HISTORY_OVERLAP = timedelta(minutes=5)
BINANCE_ORDER_HISTORY_PAGE_SIZE = 1000


def _number(value, default=0.0):
    try:
        if value is None or value == '':
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _provider_datetime(value):
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    try:
        timestamp = float(value)
        if timestamp > 100000000000:
            timestamp /= 1000
        if timestamp > 100000000:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError):
        return None


def _sync_state(user_id, provider, *, account_id='', symbol=''):
    state = OrderHistorySyncState.query.filter_by(
        user_id=user_id,
        provider=provider,
        account_id=str(account_id or ''),
        symbol=str(symbol or '').upper(),
    ).first()
    if state is None:
        state = OrderHistorySyncState(
            user_id=user_id,
            provider=provider,
            account_id=str(account_id or ''),
            symbol=str(symbol or '').upper(),
        )
        db.session.add(state)
    return state


def import_binance_orders(user_id, orders):
    """Idempotently upsert Binance.US orders into the durable external ledger."""
    now = datetime.utcnow()
    imported = 0
    latest_updated_at = None
    latest_order_id = None
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        provider_order_id = str(order.get('orderId') or order.get('order_id') or '').strip()
        symbol = str(order.get('symbol') or '').upper().strip()
        if not provider_order_id or not symbol:
            continue
        record = BinanceOrder.query.filter_by(user_id=user_id, provider_order_id=provider_order_id).first()
        if record is None:
            record = BinanceOrder(user_id=user_id, provider_order_id=provider_order_id, symbol=symbol)
            db.session.add(record)
        record.client_order_id = str(order.get('clientOrderId') or order.get('client_order_id') or '').strip() or None
        record.symbol = symbol
        record.side = str(order.get('side') or '').upper() or None
        record.order_type = str(order.get('type') or order.get('order_type') or '').upper() or None
        record.quantity = _number(order.get('origQty', order.get('quantity')))
        record.filled_quantity = _number(order.get('executedQty', order.get('filled_quantity')))
        record.price = _number(order.get('price'), None)
        cumulative_quote = _number(order.get('cummulativeQuoteQty', order.get('cumulativeQuoteQty')), 0.0)
        record.filled_price = cumulative_quote / record.filled_quantity if record.filled_quantity and cumulative_quote > 0 else record.price
        record.status = str(order.get('status') or '').upper() or None
        record.created_at = _provider_datetime(order.get('time') or order.get('transactTime')) or record.created_at
        record.updated_at = _provider_datetime(order.get('updateTime') or order.get('time')) or record.updated_at
        record.synced_at = now
        if record.updated_at and (latest_updated_at is None or record.updated_at > latest_updated_at):
            latest_updated_at = record.updated_at
        try:
            order_id_int = int(provider_order_id)
            if latest_order_id is None or order_id_int > latest_order_id:
                latest_order_id = order_id_int
        except ValueError:
            pass
        imported += 1
    db.session.commit()
    return imported, latest_updated_at, latest_order_id


def get_binance_order_rows(user_id, *, limit=None):
    """Return durable Binance order history in the shared order-table shape."""
    query = BinanceOrder.query.filter_by(user_id=user_id).order_by(
        BinanceOrder.created_at.desc(), BinanceOrder.id.desc(),
    )
    if limit is not None:
        query = query.limit(max(1, min(int(limit), 500)))
    records = query.all()
    return [{
        'id': record.provider_order_id,
        'symbol': record.symbol,
        'side': record.side or 'UNKNOWN',
        'order_type': record.order_type or 'UNKNOWN',
        'quantity': record.quantity or 0.0,
        'price': record.price or 0.0,
        'filled_quantity': record.filled_quantity or 0.0,
        'filled_price': record.filled_price or record.price or 0.0,
        'fee': record.commission or 0.0,
        'fee_asset': record.commission_asset,
        'commission': record.commission or 0.0,
        'commission_asset': record.commission_asset,
        'status': record.status or 'UNKNOWN',
        'created_at': record.created_at.isoformat() if record.created_at else None,
        'updated_at': record.updated_at.isoformat() if record.updated_at else None,
        'source': 'binance',
        'origin': 'binance',
        'origin_label': 'Binance.US',
    } for record in records]


def _binance_symbols(user_id):
    symbols = {
        str(order.symbol or '').upper()
        for order in RealOrder.query.filter_by(user_id=user_id).all()
        if order.symbol
    }
    symbols.update({
        str(order.symbol or '').upper()
        for order in BinanceOrder.query.filter_by(user_id=user_id).all()
        if order.symbol
    })
    for coin in Coin.query.filter_by(user_id=user_id).all():
        asset = str(coin.symbol or '').upper()
        if asset and asset not in {'USD', 'USDT'}:
            symbols.add(f'{asset}USD')
            symbols.add(f'{asset}USDT')
    return sorted(symbol for symbol in symbols if symbol)


def sync_binance_order_history_for_user(user_id, credential=None):
    """Backfill once, then import only recent Binance.US order changes per symbol."""
    credential = credential or Credential.query.filter_by(user_id=user_id).first()
    api_key = getattr(credential, 'trading_api_key', None) or getattr(credential, 'api_key', None)
    api_secret = getattr(credential, 'trading_api_secret', None) or getattr(credential, 'api_secret', None)
    if not api_key or not api_secret:
        return {'symbols': 0, 'orders': 0, 'skipped': 'Binance.US is not connected.'}

    client = Client(api_key=api_key, api_secret=api_secret, testnet=False, tld='us', requests_params={'timeout': 30})
    imported_total = 0
    synced_symbols = 0
    for symbol in _binance_symbols(user_id):
        state = _sync_state(user_id, 'binance', symbol=symbol)
        try:
            if state.initial_backfill_complete:
                start_at = state.last_provider_updated_at or state.last_successful_at or datetime.utcnow()
                params = {
                    'symbol': symbol,
                    'startTime': int((start_at - BINANCE_ORDER_HISTORY_OVERLAP).replace(tzinfo=timezone.utc).timestamp() * 1000),
                    'limit': BINANCE_ORDER_HISTORY_PAGE_SIZE,
                }
                batches = [client.get_all_orders(**params) or []]
            else:
                batches = []
                next_order_id = 0
                while True:
                    batch = client.get_all_orders(
                        symbol=symbol,
                        orderId=next_order_id,
                        limit=BINANCE_ORDER_HISTORY_PAGE_SIZE,
                    ) or []
                    batches.append(batch)
                    if len(batch) < BINANCE_ORDER_HISTORY_PAGE_SIZE:
                        break
                    try:
                        last_order_id = int(batch[-1]['orderId'])
                    except (KeyError, TypeError, ValueError):
                        break
                    if last_order_id < next_order_id:
                        break
                    next_order_id = last_order_id + 1
                    time.sleep(0.1)

            flattened = [order for batch in batches for order in batch]
            imported, latest_updated_at, latest_order_id = import_binance_orders(user_id, flattened)
            state.last_successful_at = datetime.utcnow()
            state.last_provider_updated_at = latest_updated_at or state.last_provider_updated_at
            state.last_provider_order_id = str(latest_order_id) if latest_order_id is not None else state.last_provider_order_id
            state.initial_backfill_complete = True
            state.last_error = None
            db.session.commit()
            imported_total += imported
            synced_symbols += 1
        except Exception as exc:
            db.session.rollback()
            state = _sync_state(user_id, 'binance', symbol=symbol)
            state.last_error = str(exc)[:1000]
            db.session.commit()
            logger.warning('Binance order-history sync failed for user %s, %s: %s', user_id, symbol, exc)
    return {'symbols': synced_symbols, 'orders': imported_total}


def _enabled_webull_account_ids(setting, accounts):
    try:
        configured = getattr(setting, 'webull_enabled_account_ids', '[]') or '[]'
        configured = json.loads(configured) if isinstance(configured, str) else configured
        enabled = {str(value).strip() for value in configured if str(value).strip()} if isinstance(configured, list) else set()
    except (AttributeError, TypeError, ValueError):
        enabled = set()
    return [str(account.get('account_id')) for account in accounts if account.get('account_id') and (not enabled or str(account['account_id']) in enabled)]


def sync_webull_order_history_for_user(user_id, credential=None, setting=None):
    """Import the newest Webull batch per enabled account without blocking a view."""
    credential = credential or Credential.query.filter_by(user_id=user_id).first()
    setting = setting or UserSetting.query.filter_by(user_id=user_id).first()
    environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
    if (
        not credential or credential.webull_token_status != 'NORMAL'
        or credential.webull_token_environment != environment or not credential.webull_access_token
    ):
        return {'accounts': 0, 'orders': 0, 'skipped': 'Webull is not connected.'}

    accounts = get_webull_accounts(
        credential.webull_app_key, credential.webull_app_secret, environment, credential.webull_access_token,
    )
    imported_total = 0
    synced_accounts = 0
    for account_id in _enabled_webull_account_ids(setting, accounts):
        state = _sync_state(user_id, 'webull', account_id=account_id)
        try:
            historical_orders = get_webull_order_history(
                credential.webull_app_key, credential.webull_app_secret, environment,
                credential.webull_access_token, page_size=100, account_id=account_id,
            )
            open_orders = get_webull_open_orders(
                credential.webull_app_key, credential.webull_app_secret, environment,
                credential.webull_access_token, page_size=100, account_id=account_id,
            )
            orders = [*historical_orders, *open_orders]
            imported_total += import_webull_orders(user_id, orders)
            updated_times = [
                _provider_datetime(order.get('updated_at') or order.get('update_time') or order.get('filled_time'))
                for order in orders if isinstance(order, dict)
            ]
            latest_updated_at = max((value for value in updated_times if value is not None), default=None)
            state.last_successful_at = datetime.utcnow()
            state.last_provider_updated_at = latest_updated_at or state.last_provider_updated_at
            state.last_provider_order_id = max((
                str(order.get('order_id') or order.get('orderId') or '')
                for order in orders if isinstance(order, dict)
            ), default=state.last_provider_order_id)
            state.initial_backfill_complete = True
            state.last_error = None
            db.session.commit()
            synced_accounts += 1
        except Exception as exc:
            db.session.rollback()
            state = _sync_state(user_id, 'webull', account_id=account_id)
            state.last_error = str(exc)[:1000]
            db.session.commit()
            logger.warning('Webull order-history sync failed for user %s, %s: %s', user_id, account_id, exc)
    return {'accounts': synced_accounts, 'orders': imported_total}


def sync_order_history_for_all_users():
    """Run one bounded background history reconciliation for connected users."""
    results = []
    for user in User.query.all():
        credential = Credential.query.filter_by(user_id=user.id).first()
        if credential is None:
            continue
        try:
            binance_result = sync_binance_order_history_for_user(user.id, credential)
        except Exception as exc:
            db.session.rollback()
            binance_result = {'error': str(exc)}
        try:
            webull_result = sync_webull_order_history_for_user(user.id, credential)
        except Exception as exc:
            db.session.rollback()
            webull_result = {'error': str(exc)}
        results.append({'user_id': user.id, 'binance': binance_result, 'webull': webull_result})
    return results