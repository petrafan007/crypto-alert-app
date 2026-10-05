"""Unified order cancellation and replacement service."""
import logging
import re
from core.extensions import db
from trading_models import LadderOrder, TrailingOrder, TestOrder, RealOrder
from services.synthetic_execution_service import WORKING_PARENTS

logger = logging.getLogger(__name__)


def cancel_any_order(replacing_order_id, user_id, symbol=None, test_mode=None, broker=None, account_id=None):
    """
    Cancel an existing order of ANY type (synthetic ladder, trailing stop, paper test order,
    real Binance order, or Webull order) during an order replacement operation.

    Returns a dict with:
        'success': bool,
        'order_id': str (normalized identifier of the replaced order),
        'order_type': str ('ladder', 'trailing', 'test_order', 'real_order', 'webull', 'unknown'),
        'message': str
    """
    if not replacing_order_id:
        return {'success': False, 'error': 'No replacing order ID provided'}

    str_id = str(replacing_order_id).strip()

    # 1. Synthetic Ladder Order (explicit prefix ladder_<id> or ladder-<id>)
    if re.fullmatch(r'ladder[_-](\d+)', str_id):
        match = re.fullmatch(r'ladder[_-](\d+)', str_id)
        ladder_id = int(match.group(1))
        ladder = LadderOrder.query.filter_by(id=ladder_id, user_id=user_id).first()
        if not ladder:
            logger.warning(f"Ladder order {ladder_id} not found for user {user_id} during replacement")
            return {'success': True, 'order_id': str_id, 'order_type': 'ladder', 'message': 'Ladder order not found or already inactive'}
        if ladder.status in WORKING_PARENTS and not ladder.cancel_requested:
            from services.ladder_order_service import cancel_ladder_order
            cancel_ladder_order(ladder_id, user_id)
        return {'success': True, 'order_id': str_id, 'order_type': 'ladder', 'message': f'Ladder order {ladder_id} cancelled'}

    # 2. Synthetic Trailing Order (explicit prefix trail_<id> or trail-<id>)
    if re.fullmatch(r'trail[_-](\d+)', str_id):
        match = re.fullmatch(r'trail[_-](\d+)', str_id)
        trail_id = int(match.group(1))
        trail = TrailingOrder.query.filter_by(id=trail_id, user_id=user_id).first()
        if not trail:
            logger.warning(f"Trailing order {trail_id} not found for user {user_id} during replacement")
            return {'success': True, 'order_id': str_id, 'order_type': 'trailing', 'message': 'Trailing order not found or already inactive'}
        if trail.status in WORKING_PARENTS and not trail.cancel_requested:
            from services.trailing_order_service import cancel_trailing_order
            cancel_trailing_order(trail_id, user_id)
        return {'success': True, 'order_id': str_id, 'order_type': 'trailing', 'message': f'Trailing order {trail_id} cancelled'}

    # 3. Webull Order (prefix webull- or broker is webull)
    if str_id.startswith('webull-') or (broker and str(broker).lower() == 'webull'):
        clean_webull_id = str_id.replace('webull-', '').strip()
        is_test = test_mode is True or str(account_id or '').startswith('TEST_')
        if is_test:
            try:
                from services.webull_paper_trading_service import cancel_webull_test_order
                cancel_webull_test_order(user_id, clean_webull_id)
            except Exception as e:
                logger.warning(f"Error cancelling Webull test order {clean_webull_id} during replacement: {e}")
        else:
            try:
                from services.webull_service import cancel_webull_order_sync
                cancel_webull_order_sync(user_id=user_id, account_id=account_id, order_id=clean_webull_id, combo_type='NORMAL')
            except Exception as e:
                logger.warning(f"Error cancelling Webull live order {clean_webull_id} during replacement: {e}")
        return {'success': True, 'order_id': str_id, 'order_type': 'webull', 'message': f'Webull order {clean_webull_id} cancelled'}

    # 4. Numeric order ID (could be TestOrder, RealOrder, or unprefixed synthetic order)
    if str_id.isdigit():
        num_id = int(str_id)

        # Check if it matches an active TestOrder
        test_order = TestOrder.query.filter_by(user_id=user_id, id=num_id).first()
        if test_order:
            if test_order.status in {'NEW', 'ACTIVE', 'PARTIALLY_FILLED'}:
                test_order.status = 'CANCELED'
                db.session.commit()
            return {'success': True, 'order_id': str_id, 'order_type': 'test_order', 'message': f'Test order {num_id} cancelled'}

        # Check if it's an unprefixed LadderOrder or TrailingOrder
        ladder = LadderOrder.query.filter_by(id=num_id, user_id=user_id).first()
        if ladder and ladder.status in WORKING_PARENTS:
            from services.ladder_order_service import cancel_ladder_order
            cancel_ladder_order(num_id, user_id)
            return {'success': True, 'order_id': f'ladder_{num_id}', 'order_type': 'ladder', 'message': f'Ladder order {num_id} cancelled'}

        trail = TrailingOrder.query.filter_by(id=num_id, user_id=user_id).first()
        if trail and trail.status in WORKING_PARENTS:
            from services.trailing_order_service import cancel_trailing_order
            cancel_trailing_order(num_id, user_id)
            return {'success': True, 'order_id': f'trail_{num_id}', 'order_type': 'trailing', 'message': f'Trailing order {num_id} cancelled'}

        # Check if it's a live Binance order recorded in RealOrder
        real_order = RealOrder.query.filter_by(user_id=user_id, binance_order_id=num_id).first()
        if real_order and real_order.status in {'NEW', 'PARTIALLY_FILLED', 'ACTIVE'}:
            real_order.status = 'CANCELED'
            db.session.commit()

        # Attempt Binance cancellation via API if live trading is active or credentials exist
        if not test_mode:
            try:
                from credentials import Credential
                creds = Credential.query.filter_by(user_id=user_id).first()
                if creds and creds.trading_api_key and creds.trading_api_secret:
                    from binance.client import Client
                    client = Client(api_key=creds.trading_api_key, api_secret=creds.trading_api_secret, testnet=False, tld='us')
                    target_symbol = symbol or (real_order.symbol if real_order else None)
                    if target_symbol:
                        client.cancel_order(symbol=target_symbol.upper(), orderId=num_id)
            except Exception as e:
                logger.warning(f"Could not cancel Binance order {num_id} during replacement: {e}")

        return {'success': True, 'order_id': str_id, 'order_type': 'real_order', 'message': f'Order {num_id} cancelled'}

    # 5. String-based fallback (e.g. clientOrderId or other order format)
    test_order = TestOrder.query.filter_by(user_id=user_id).filter(
        (TestOrder.notes.ilike(f"%{str_id}%")) | (TestOrder.validation_response.ilike(f"%{str_id}%"))
    ).first()
    if test_order and test_order.status in {'NEW', 'ACTIVE', 'PARTIALLY_FILLED'}:
        test_order.status = 'CANCELED'
        db.session.commit()
        return {'success': True, 'order_id': str_id, 'order_type': 'test_order', 'message': f'Test order {str_id} cancelled'}

    return {'success': True, 'order_id': str_id, 'order_type': 'unknown', 'message': f'Processed replacement for order {str_id}'}
