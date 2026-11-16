"""Unified, fail-closed order cancellation for order replacement.

A replacement is only safe when the original order is confirmed cancelled
before the new one is sent, and when the caller learns plainly whether the
original can be restored if the new order is then rejected. Every branch here
therefore reports ``success: False`` unless the original is known to be gone.
"""
import json
import logging
import re
from datetime import datetime

from core.extensions import db
from trading_models import LadderOrder, TrailingOrder, TestOrder, RealOrder
from services.synthetic_execution_service import WORKING_PARENTS

logger = logging.getLogger(__name__)

ACTIVE_TEST_ORDER_STATUSES = {'NEW', 'ACTIVE', 'PARTIALLY_FILLED'}
ACTIVE_REAL_ORDER_STATUSES = {'NEW', 'PARTIALLY_FILLED', 'ACTIVE', 'PENDING_NEW'}
# Binance order types that can be re-submitted with their original terms if a
# replacement is rejected after the original was cancelled.
RESTORABLE_BINANCE_TYPES = {'LIMIT', 'LIMIT_MAKER', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT'}
BINANCE_UNKNOWN_ORDER_CODES = {-2011, -2013}


def _failure(str_id, order_type, error):
    return {'success': False, 'order_id': str_id, 'order_type': order_type, 'error': error}


def _binance_client_for(user_id):
    from credentials import Credential
    creds = Credential.query.filter_by(user_id=user_id).first()
    api_key = (creds.trading_api_key or creds.api_key) if creds else None
    api_secret = (creds.trading_api_secret or creds.api_secret) if creds else None
    if not api_key or not api_secret:
        return None
    from binance.client import Client
    return Client(api_key=api_key, api_secret=api_secret, testnet=False, tld='us',
                  requests_params={'timeout': 15})


def _cancel_synthetic(kind, parent_id, user_id, str_id, symbol_mismatch):
    model, label = (LadderOrder, 'ladder') if kind == 'ladder' else (TrailingOrder, 'trailing')
    parent = model.query.filter_by(id=parent_id, user_id=user_id).first()
    if not parent:
        return _failure(str_id, label, f'Synthetic order {str_id} was not found, so nothing was replaced.')
    mismatch = symbol_mismatch(parent.symbol)
    if mismatch:
        return _failure(str_id, label, mismatch)
    if parent.status not in WORKING_PARENTS:
        return _failure(str_id, label,
                        f'Synthetic order {str_id} is {str(parent.status or "inactive").lower()} and can no longer be replaced.')
    if not parent.cancel_requested:
        if kind == 'ladder':
            from services.ladder_order_service import cancel_ladder_order
            cancel_ladder_order(parent_id, user_id)
        else:
            from services.trailing_order_service import cancel_trailing_order
            cancel_trailing_order(parent_id, user_id)
    # A replacement may only proceed once the old order is confirmed cancelled.
    # A cancellation still awaiting broker confirmation, or one that recorded a
    # fill, leaves the old order live or partly filled, so placing the
    # replacement would double the exposure.
    parent = model.query.filter_by(id=parent_id, user_id=user_id).populate_existing().first()
    if parent is not None:
        if kind == 'ladder':
            filled = sum(float(getattr(rung, 'filled_quantity', 0) or 0) for rung in (parent.rungs or []))
        else:
            filled = float(getattr(parent, 'filled_quantity', 0) or 0)
        if filled > 0:
            return _failure(str_id, label, 'The replaced order recorded a fill. No replacement was placed.')
        if parent.status == 'CANCEL_PENDING':
            return _failure(str_id, label,
                            'Cancellation of the old strategy is awaiting broker confirmation. No replacement was placed.')
        if parent.status in WORKING_PARENTS:
            return _failure(str_id, label, 'The old strategy could not be cancelled. No replacement was placed.')
    canonical = f'{"ladder" if kind == "ladder" else "trail"}_{parent_id}'
    return {'success': True, 'order_id': canonical, 'order_type': label,
            'message': f'{label.title()} order {parent_id} cancelled'}


def _cancel_binance_live(num_id, user_id, symbol, str_id):
    """Cancel a live Binance.US order and confirm nothing of it remains working."""
    real_order = RealOrder.query.filter_by(user_id=user_id, binance_order_id=num_id).first()
    target_symbol = (symbol or (real_order.symbol if real_order else '') or '').upper()
    if not target_symbol:
        return _failure(str_id, 'real_order', 'The symbol of the order being replaced is unknown, so nothing was replaced.')
    if real_order and real_order.symbol and real_order.symbol.upper() != target_symbol:
        return _failure(str_id, 'real_order',
                        f'The replacement must use the same symbol as the order it replaces ({real_order.symbol} vs {target_symbol}).')
    client = _binance_client_for(user_id)
    if client is None:
        return _failure(str_id, 'real_order', 'Binance.US trading credentials are missing, so the original order could not be cancelled.')

    try:
        snapshot = client.get_order(symbol=target_symbol, orderId=num_id)
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if code in BINANCE_UNKNOWN_ORDER_CODES:
            return _failure(str_id, 'real_order', f'Order {num_id} was not found at Binance.US, so nothing was replaced.')
        return _failure(str_id, 'real_order', f'Could not read the original order from Binance.US: {exc}')

    status = str(snapshot.get('status') or '').upper()
    executed = float(snapshot.get('executedQty') or 0)
    if status in {'FILLED', 'EXPIRED', 'REJECTED'}:
        return _failure(str_id, 'real_order', f'Order {num_id} is already {status.lower()}; nothing was replaced.')
    if status != 'CANCELED':
        try:
            result = client.cancel_order(symbol=target_symbol, orderId=num_id)
        except Exception as exc:
            return _failure(str_id, 'real_order', f'Binance.US could not cancel order {num_id}: {exc}')
        executed = float(result.get('executedQty') or executed or 0)
    from services.portfolio_service import invalidate_binance_open_orders
    invalidate_binance_open_orders(user_id)
    if real_order:
        real_order.status = 'CANCELED'
        real_order.canceled_at = real_order.updated_at = datetime.utcnow()
        db.session.commit()
    if executed > 0:
        return _failure(str_id, 'real_order', (
            f'Order {num_id} had already filled {executed:g} before it was cancelled. '
            'No replacement was placed; enter a new order for the remaining quantity.'))
    return {'success': True, 'order_id': str_id, 'order_type': 'real_order',
            'message': f'Order {num_id} cancelled', 'cancelled_binance_order': snapshot}


def cancel_any_order(replacing_order_id, user_id, symbol=None, test_mode=None, broker=None, account_id=None):
    """Cancel the order being replaced; succeed only when it is confirmed gone.

    Returns a dict with ``success``, ``order_id`` (normalized identifier),
    ``order_type`` ('ladder', 'trailing', 'test_order', 'real_order',
    'webull') and either ``message`` or ``error``. A Binance cancellation also
    returns ``cancelled_binance_order`` and a Webull one ``cancelled_order`` so
    the caller can restore the original if the replacement is rejected.
    """
    if not replacing_order_id:
        return {'success': False, 'error': 'No replacing order ID provided'}

    str_id = str(replacing_order_id).strip()

    def _symbol_mismatch(existing_symbol):
        """A replacement must target the same instrument as the order it replaces."""
        if not existing_symbol or not symbol:
            return None
        if str(existing_symbol).upper() != str(symbol).upper():
            return ('The replacement must use the same symbol as the order it replaces '
                    f'({existing_symbol} vs {symbol}).')
        return None

    # 1-2. Synthetic ladder / trailing orders (ladder_<id>, trail_<id>).
    match = re.fullmatch(r'(ladder|trail)[_-](\d+)', str_id)
    if match:
        return _cancel_synthetic('ladder' if match.group(1) == 'ladder' else 'trailing',
                                 int(match.group(2)), user_id, str_id, _symbol_mismatch)

    # 3. Webull order (prefix webull- or broker is webull).
    if str_id.startswith('webull-') or (broker and str(broker).lower() == 'webull'):
        clean_webull_id = str_id.replace('webull-', '').strip()
        cancelled_order = None
        is_test = test_mode is True or str(account_id or '').startswith('TEST_')
        if is_test:
            try:
                from services.webull_paper_trading_service import cancel_webull_test_order
                result = cancel_webull_test_order(user_id, clean_webull_id)
            except Exception as e:
                logger.warning(f"Error cancelling Webull test order {clean_webull_id} during replacement: {e}")
                return _failure(str_id, 'webull', f'Paper order {clean_webull_id} could not be cancelled: {e}')
            if isinstance(result, dict) and result.get('success') is False:
                return _failure(str_id, 'webull', result.get('message') or f'Paper order {clean_webull_id} could not be cancelled.')
        else:
            # A live replacement may only proceed once Webull accepts the
            # cancellation. Reporting success for an order that is still
            # working would leave both the old and the new order live.
            try:
                from credentials import Credential, UserSetting
                from services.webull_service import cancel_webull_order, get_webull_open_orders, normalize_webull_environment
                if not account_id:
                    raise ValueError('A Webull account is required to cancel the order being replaced.')
                setting = UserSetting.query.filter_by(user_id=user_id).first()
                credential = Credential.query.filter_by(user_id=user_id).first()
                environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')
                if not credential or not credential.webull_access_token:
                    raise ValueError('Webull is not connected or token has expired.')

                def _find_open(orders):
                    for o in orders or []:
                        ids = {str(o.get(k) or '').strip() for k in ('order_id', 'orderId', 'combo_order_id', 'client_order_id', 'id')}
                        if clean_webull_id in ids:
                            return o
                    return None

                creds = (credential.webull_app_key, credential.webull_app_secret, environment, credential.webull_access_token)
                open_order = _find_open(get_webull_open_orders(*creds, account_id=account_id))
                if open_order is None:
                    elsewhere = _find_open(get_webull_open_orders(*creds))
                    if elsewhere is not None and str(elsewhere.get('_webull_account_id') or '') != str(account_id):
                        raise ValueError(
                            'the order belongs to a different Webull account than the one selected for the replacement. '
                            'Select the account that holds the original order and try again.'
                        )
                    open_order = elsewhere
                if open_order is None:
                    raise ValueError('the order is no longer open at Webull (it may have filled or already been cancelled).')
                cancel_webull_order(
                    *creds, account_id=account_id,
                    client_order_id=str(open_order.get('client_order_id') or '').strip() or None,
                    order_id=str(open_order.get('order_id') or clean_webull_id).strip(),
                )
                cancelled_order = dict(open_order)
            except Exception as e:
                logger.warning(f"Error cancelling Webull live order {clean_webull_id} during replacement: {e}")
                return _failure(str_id, 'webull', f'Webull could not cancel order {clean_webull_id}: {e}')
        return {'success': True, 'order_id': str_id, 'order_type': 'webull',
                'message': f'Webull order {clean_webull_id} cancelled', 'cancelled_order': cancelled_order}

    # 4. Numeric order ID: a paper TestOrder, an unprefixed synthetic order, or
    # a live Binance.US order. Paper and live identifiers are never mixed: a
    # live replacement must never cancel a paper order with a colliding ID.
    if str_id.isdigit():
        num_id = int(str_id)

        if test_mode is not False:
            test_order = TestOrder.query.filter_by(user_id=user_id, id=num_id).first()
            if test_order:
                mismatch = _symbol_mismatch(test_order.symbol)
                if mismatch:
                    return _failure(str_id, 'test_order', mismatch)
                if str(test_order.status or '').upper() not in ACTIVE_TEST_ORDER_STATUSES:
                    return _failure(str_id, 'test_order',
                                    f'Test order {num_id} is {str(test_order.status or "inactive").lower()} and can no longer be replaced.')
                test_order.status = 'CANCELED'
                db.session.commit()
                return {'success': True, 'order_id': str_id, 'order_type': 'test_order',
                        'message': f'Test order {num_id} cancelled'}

        ladder = LadderOrder.query.filter_by(id=num_id, user_id=user_id).first()
        if ladder and ladder.status in WORKING_PARENTS:
            return _cancel_synthetic('ladder', num_id, user_id, f'ladder_{num_id}', _symbol_mismatch)
        trail = TrailingOrder.query.filter_by(id=num_id, user_id=user_id).first()
        if trail and trail.status in WORKING_PARENTS:
            return _cancel_synthetic('trailing', num_id, user_id, f'trail_{num_id}', _symbol_mismatch)

        if test_mode:
            # Paper mode never cancels a live exchange order. A local record of
            # a live order is only reconciled, never sent to the exchange.
            real_order = RealOrder.query.filter_by(user_id=user_id, binance_order_id=num_id).first()
            if real_order and str(real_order.status or '').upper() in ACTIVE_REAL_ORDER_STATUSES:
                real_order.status = 'CANCELED'
                db.session.commit()
                return {'success': True, 'order_id': str_id, 'order_type': 'real_order',
                        'message': f'Order {num_id} cancelled'}
            return _failure(str_id, 'test_order', f'Order {num_id} was not found among your paper orders, so nothing was replaced.')

        return _cancel_binance_live(num_id, user_id, symbol, str_id)

    # 5. Anything else cannot be located, so nothing is replaced.
    return _failure(str_id, 'unknown', f'Order {str_id} was not found, so nothing was replaced.')


def restore_binance_order(user_id, snapshot):
    """Re-submit a cancelled Binance order with its original terms.

    Returns the new order ID. Raises ValueError when the original cannot be
    restored automatically (market, stop-market, OCO or partly filled).
    """
    if not snapshot:
        raise ValueError('the original order details are unavailable.')
    order_type = str(snapshot.get('type') or '').upper()
    if order_type not in RESTORABLE_BINANCE_TYPES:
        raise ValueError(f'{order_type or "this"} orders cannot be restored automatically.')
    if snapshot.get('orderListId') not in (None, -1, '-1'):
        raise ValueError('OCO orders cannot be restored automatically.')
    if float(snapshot.get('executedQty') or 0) > 0:
        raise ValueError('the original order had partly filled.')
    client = _binance_client_for(user_id)
    if client is None:
        raise ValueError('Binance.US trading credentials are missing.')
    params = {
        'symbol': snapshot['symbol'], 'side': snapshot['side'], 'type': order_type,
        'quantity': snapshot['origQty'], 'price': snapshot['price'],
    }
    if order_type != 'LIMIT_MAKER':
        params['timeInForce'] = snapshot.get('timeInForce') or 'GTC'
    if order_type in {'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT'}:
        params['stopPrice'] = snapshot['stopPrice']
    response = client.create_order(**params)
    db.session.add(RealOrder(
        user_id=user_id, binance_order_id=response.get('orderId'), symbol=snapshot['symbol'],
        side=snapshot['side'], type=order_type, quantity=float(snapshot['origQty']),
        price=float(snapshot['price']), stop_price=snapshot.get('stopPrice') if 'stopPrice' in params else None,
        time_in_force=params.get('timeInForce', 'GTC'), status=response.get('status', 'NEW'),
        binance_client_order_id=response.get('clientOrderId'),
        created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        order_response=json.dumps({**response, 'origin': 'replacement_restore'}),
    ))
    db.session.commit()
    from services.portfolio_service import invalidate_binance_open_orders
    invalidate_binance_open_orders(user_id)
    return response.get('orderId')


def failed_replacement_note(user_id, cancel_result):
    """Explain what happened to the original after a replacement was rejected.

    Live Binance originals are restored with their own terms when possible.
    """
    if not cancel_result or not cancel_result.get('success'):
        return ''
    original = cancel_result.get('order_id')
    snapshot = cancel_result.get('cancelled_binance_order')
    if snapshot:
        try:
            restored_id = restore_binance_order(user_id, snapshot)
            return f' Your original order {original} was restored with the same terms (new order ID {restored_id}).'
        except Exception as exc:
            logger.error('Could not restore Binance order %s after a failed replacement: %s', original, exc)
            return (f' Your original order {original} had already been cancelled and could not be restored '
                    f'automatically ({exc}). No order is working now; re-enter it manually.')
    return (f' Your original order {original} had already been cancelled. '
            'No order is working now for it; re-enter it if you still want it.')
