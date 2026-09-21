"""Webull Scheduled Fractional Order Service.

Coordinates creation, cancellation, querying, and 9:30:00 AM ET regular session open
execution of pending fractional stock and ETF orders.
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import logging
from typing import Any, Dict, List, Optional

from core.time_utils import utc_now

from core.extensions import db
from credentials import Credential, UserSetting, User
from models import WebullScheduledOrder
from services.market_calendar_service import (
    get_next_regular_market_open,
    is_regular_market_hours,
)
from services.notification_service import (
    create_system_notification,
    send_telegram_message,
)
from services.webull_service import (
    WebullConnectionError,
    get_webull_market_snapshot,
    normalize_webull_environment,
    place_webull_order,
)

logger = logging.getLogger(__name__)

DEFAULT_PRICE_CEILING_BUFFER = 0.03  # +3% default buffer above reference quote


def create_scheduled_fractional_order(
    user_id: int,
    account_id: str,
    symbol: str,
    *,
    account_name: Optional[str] = None,
    instrument_type: str = 'EQUITY',
    side: str = 'BUY',
    entrust_type: str = 'QTY',
    quantity: Optional[float] = None,
    total_cash_amount: Optional[float] = None,
    reference_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Validate and persist a pending fractional order queued for the next 9:30 AM ET market open."""
    clean_symbol = ''.join(char for char in str(symbol or '').strip().upper() if char.isalnum())
    clean_account_id = str(account_id or '').strip()
    clean_instrument = str(instrument_type or 'EQUITY').strip().upper()
    clean_side = str(side or 'BUY').strip().upper()
    clean_entrust = str(entrust_type or 'QTY').strip().upper()

    if not clean_symbol:
        raise ValueError('Choose a valid stock or ETF symbol.')
    if not clean_account_id:
        raise ValueError('Choose a Webull account to place the scheduled order.')
    if clean_instrument not in {'EQUITY', 'STOCK', 'ETF'}:
        raise ValueError('Scheduled orders currently support stocks and ETFs only.')
    clean_instrument = 'EQUITY'

    if clean_side != 'BUY':
        raise ValueError('Scheduled market-open orders currently support BUY orders only.')

    parsed_qty: Optional[float] = None
    parsed_cash: Optional[float] = None

    if clean_entrust == 'AMOUNT':
        try:
            parsed_cash = round(float(total_cash_amount or 0), 2)
            if parsed_cash < 5.0:
                raise ValueError('Fractional cash orders require a minimum amount of $5.00.')
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc) if 'minimum' in str(exc) else 'Enter a valid cash amount ($ USD).')
        parsed_qty = None
    else:
        clean_entrust = 'QTY'
        try:
            if quantity is None:
                raise ValueError('Enter an order quantity.')
            quantity_decimal = Decimal(str(quantity))
            decimal_places = max(0, -quantity_decimal.normalize().as_tuple().exponent)
            if not quantity_decimal.is_finite() or quantity_decimal <= 0:
                raise ValueError('Quantity must be greater than zero.')
            if not float(quantity_decimal).is_integer() and decimal_places > 5:
                raise ValueError('Webull stock and ETF fractional quantities support at most 5 decimal places.')
            parsed_qty = float(quantity_decimal)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(str(exc) if 'Quantity' in str(exc) or 'decimal' in str(exc) else 'Enter a valid quantity.')
        parsed_cash = None

    # Calculate next market open (9:30:00 AM Eastern Time)
    target_utc, target_et, target_date_str = get_next_regular_market_open()

    # Price Ceiling Protection: Use explicit max_price if provided, else default to +3% above reference_price
    parsed_max_price: Optional[float] = None
    parsed_ref_price: Optional[float] = None
    if reference_price is not None:
        try:
            val = float(reference_price)
            if val > 0:
                parsed_ref_price = round(val, 2)
        except (TypeError, ValueError):
            pass

    if max_price is not None and str(max_price).strip():
        try:
            p_max = float(max_price)
            if p_max <= 0:
                raise ValueError('Price ceiling must be greater than zero.')
            parsed_max_price = round(p_max, 2)
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc) if 'greater than zero' in str(exc) else 'Enter a valid price ceiling.')
    elif parsed_ref_price is not None and parsed_ref_price > 0:
        # User confirmed default: +3% buffer above current quote
        parsed_max_price = round(parsed_ref_price * (1.0 + DEFAULT_PRICE_CEILING_BUFFER), 2)

    parsed_min_price: Optional[float] = None
    if min_price is not None and str(min_price).strip():
        try:
            p_min = float(min_price)
            if p_min > 0:
                parsed_min_price = round(p_min, 2)
        except (TypeError, ValueError):
            pass

    order = WebullScheduledOrder(
        user_id=user_id,
        account_id=clean_account_id,
        account_name=str(account_name).strip() if account_name else None,
        symbol=clean_symbol,
        instrument_type=clean_instrument,
        side=clean_side,
        order_type='MARKET',
        entrust_type=clean_entrust,
        quantity=parsed_qty,
        total_cash_amount=parsed_cash,
        reference_price=parsed_ref_price,
        max_price=parsed_max_price,
        min_price=parsed_min_price,
        target_execution_time=target_utc.replace(tzinfo=None),
        target_trading_day=target_date_str,
        status='PENDING',
    )
    db.session.add(order)
    db.session.commit()

    # Create notification and send alert
    amount_str = f"${parsed_cash:.2f}" if clean_entrust == 'AMOUNT' else f"{parsed_qty:g} shares"
    ceiling_str = f" (Ceiling: ${parsed_max_price:.2f})" if parsed_max_price else ""
    target_et_str = target_et.strftime('%a, %b %d at 9:30 AM %Z')
    user_msg = (
        f"Scheduled 9:30 AM buy for {amount_str} of {clean_symbol} queued for {target_et_str}{ceiling_str}."
    )

    try:
        create_system_notification(
            user_id_or_name=user_id,
            category='trade_alert',
            symbol=clean_symbol,
            message=user_msg,
            current_price=parsed_ref_price or 0.0,
            table_type='portfolio',
        )
    except Exception as n_err:
        logger.warning(f"[SCHEDULED_ORDER] Notification creation failed: {n_err}")

    try:
        user = User.query.get(user_id)
        if user and getattr(user, 'telegram_chat_id', None):
            send_telegram_message(
                user.username,
                f"⏰ Webull Scheduled Order Queued:\nBuy {amount_str} of {clean_symbol} on {target_et_str}{ceiling_str}.",
            )
    except Exception as t_err:
        logger.warning(f"[SCHEDULED_ORDER] Telegram alert failed: {t_err}")

    logger.info(
        f"[SCHEDULED_ORDER] Created scheduled order #{order.id}: user={user_id} "
        f"symbol={clean_symbol} {amount_str} target={target_date_str} 9:30 AM ET"
    )
    return order.to_dict()


def cancel_scheduled_fractional_order(user_id: int, order_id: int) -> Dict[str, Any]:
    """Cancel a pending scheduled order before market open."""
    order = WebullScheduledOrder.query.filter_by(id=order_id, user_id=user_id).first()
    if not order:
        raise ValueError('Scheduled order not found.')
    if order.status != 'PENDING':
        raise ValueError(f'Order cannot be cancelled in status "{order.status}".')

    order.status = 'CANCELLED'
    order.updated_at = utc_now()
    db.session.commit()

    cancel_msg = f"Scheduled 9:30 AM buy for {order.symbol} (#{order.id}) was cancelled."
    try:
        create_system_notification(
            user_id_or_name=user_id,
            category='trade_alert',
            symbol=order.symbol,
            message=cancel_msg,
            current_price=order.reference_price or 0.0,
            table_type='portfolio',
        )
    except Exception as n_err:
        logger.warning(f"[SCHEDULED_ORDER] Notification creation failed on cancel: {n_err}")

    logger.info(f"[SCHEDULED_ORDER] Cancelled scheduled order #{order.id} for user={user_id}")
    return order.to_dict()


def get_user_scheduled_orders(
    user_id: int,
    status: Optional[str] = None,
    account_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return scheduled fractional orders for the given user, ordered by target execution time."""
    query = WebullScheduledOrder.query.filter_by(user_id=user_id)
    if status:
        query = query.filter_by(status=status.strip().upper())
    if account_id:
        query = query.filter_by(account_id=str(account_id).strip())

    orders = query.order_by(
        WebullScheduledOrder.target_execution_time.desc(),
        WebullScheduledOrder.created_at.desc(),
    ).all()
    return [order.to_dict() for order in orders]


def process_due_scheduled_orders(app=None) -> List[Dict[str, Any]]:
    """Execution worker loop iteration: find and process pending scheduled orders whose target time has arrived.

    Designed to run inside the background scheduler thread every 10-15 seconds.
    """
    ctx = None
    if app:
        ctx = app.app_context()
        ctx.push()

    processed = []
    try:
        now_utc = utc_now()
        # Find all pending orders due for execution
        pending_orders = WebullScheduledOrder.query.filter(
            WebullScheduledOrder.status == 'PENDING',
            WebullScheduledOrder.target_execution_time <= now_utc,
        ).order_by(WebullScheduledOrder.target_execution_time.asc()).all()

        if not pending_orders:
            return []

        # Check if the market is open or within regular market hours (9:30 AM - 4:00 PM ET on trading days)
        market_now_utc = datetime.now(timezone.utc)
        market_is_open = is_regular_market_hours(market_now_utc)

        for order in pending_orders:
            # Stale order check: if target execution was more than 6.5 hours ago (i.e. past normal market close)
            # and order was never executed, expire it safely to avoid stale fills.
            if (now_utc - order.target_execution_time) > timedelta(hours=6.5):
                logger.warning(
                    f"[SCHEDULED_ORDER] Order #{order.id} ({order.symbol}) target was {order.target_execution_time} UTC; "
                    "past trading hours. Marking EXPIRED."
                )
                order.status = 'EXPIRED'
                order.execution_error = 'Trading session closed before order could be executed.'
                order.executed_at = now_utc
                order.updated_at = now_utc
                db.session.commit()
                processed.append(order.to_dict())
                continue

            # If market is not yet regular hours (e.g. clock is 9:29:59 AM ET or holiday anomaly), wait for next check
            if not market_is_open:
                continue

            # Retrieve user credentials and environment
            user = User.query.get(order.user_id)
            setting = UserSetting.query.filter_by(user_id=order.user_id).first()
            credential = Credential.query.filter_by(user_id=order.user_id).first()
            environment = normalize_webull_environment(getattr(setting, 'webull_environment', None) or 'production')

            if (
                not credential
                or credential.webull_token_status != 'NORMAL'
                or credential.webull_token_environment != environment
                or not credential.webull_access_token
            ):
                error_text = 'Webull credentials not connected or token expired at execution time.'
                order.status = 'FAILED'
                order.execution_error = error_text
                order.executed_at = now_utc
                order.updated_at = now_utc
                db.session.commit()
                processed.append(order.to_dict())

                create_system_notification(
                    user_id_or_name=order.user_id,
                    category='trade_alert',
                    symbol=order.symbol,
                    message=f"❌ Scheduled 9:30 AM buy for {order.symbol} failed: {error_text}",
                    table_type='portfolio',
                )
                if user and getattr(user, 'telegram_chat_id', None):
                    send_telegram_message(
                        user.username,
                        f"❌ Scheduled Order Failed:\nCould not place 9:30 AM buy for {order.symbol}: {error_text}",
                    )
                continue

            # 1. Price Protection Ceiling check: fetch current quote at market open
            current_price = None
            try:
                quote = get_webull_market_snapshot(
                    credential.webull_app_key,
                    credential.webull_app_secret,
                    environment,
                    credential.webull_access_token,
                    symbol=order.symbol,
                    instrument_type='EQUITY',
                )
                current_price = quote.get('price') or quote.get('regular_price')
            except Exception as q_err:
                logger.warning(f"[SCHEDULED_ORDER] Unable to fetch market snapshot for {order.symbol}: {q_err}")

            effective_max_price = order.max_price
            if not effective_max_price and order.reference_price and order.reference_price > 0:
                effective_max_price = round(order.reference_price * (1.0 + DEFAULT_PRICE_CEILING_BUFFER), 2)

            # If user specified a maximum purchase price ceiling and market opened above it:
            if effective_max_price and current_price and (current_price > effective_max_price):
                skip_msg = (
                    f"Market open price (${current_price:.2f}) exceeded cutoff ceiling (${effective_max_price:.2f}). "
                    "Order safely aborted to protect against gap-up price spikes."
                )
                logger.info(f"[SCHEDULED_ORDER] Order #{order.id} ({order.symbol}) skipped price ceiling: {skip_msg}")
                order.status = 'SKIPPED_PRICE_LIMIT'
                order.executed_price = current_price
                order.execution_error = skip_msg
                order.executed_at = now_utc
                order.updated_at = now_utc
                db.session.commit()
                processed.append(order.to_dict())

                amount_text = f"${order.total_cash_amount:.2f}" if order.entrust_type == 'AMOUNT' else f"{order.quantity:g} shares"
                notif_text = (
                    f"⚠️ Scheduled Buy Aborted: {order.symbol} opened at ${current_price:.2f}, "
                    f"exceeding your ceiling of ${effective_max_price:.2f}. "
                    f"No purchase was made for {amount_text}."
                )
                create_system_notification(
                    user_id_or_name=order.user_id,
                    category='trade_alert',
                    symbol=order.symbol,
                    message=notif_text,
                    current_price=current_price,
                    crossing_price=effective_max_price,
                    table_type='portfolio',
                )
                if user and getattr(user, 'telegram_chat_id', None):
                    send_telegram_message(user.username, notif_text)
                continue

            # 2. Price is within limit: execute the fractional CORE Market Buy order
            try:
                result = place_webull_order(
                    credential.webull_app_key,
                    credential.webull_app_secret,
                    environment,
                    credential.webull_access_token,
                    account_id=order.account_id,
                    symbol=order.symbol,
                    instrument_type='EQUITY',
                    side='BUY',
                    order_type='MARKET',
                    support_trading_session='CORE',
                    entrust_type=order.entrust_type,
                    quantity=order.quantity,
                    total_cash_amount=order.total_cash_amount,
                )
                provider_id = str(result.get('order_id') or result.get('client_order_id') or '')
                order.status = 'EXECUTED'
                order.provider_order_id = provider_id
                order.executed_price = current_price
                order.executed_at = now_utc
                order.execution_error = None
                order.updated_at = now_utc
                db.session.commit()
                processed.append(order.to_dict())

                amount_text = f"${order.total_cash_amount:.2f}" if order.entrust_type == 'AMOUNT' else f"{order.quantity:g} shares"
                order_ref = f" (Order #{provider_id})" if provider_id else ""
                exec_msg = (
                    f"✅ Scheduled 9:30 AM Buy Executed: {amount_text} of {order.symbol} submitted to Webull{order_ref}."
                )
                logger.info(f"[SCHEDULED_ORDER] Order #{order.id} executed successfully: {exec_msg}")
                create_system_notification(
                    user_id_or_name=order.user_id,
                    category='trade_alert',
                    symbol=order.symbol,
                    message=exec_msg,
                    current_price=current_price or 0.0,
                    table_type='portfolio',
                )
                if user and getattr(user, 'telegram_chat_id', None):
                    send_telegram_message(user.username, exec_msg)

            except WebullConnectionError as w_err:
                err_str = str(w_err)
                logger.error(f"[SCHEDULED_ORDER] Webull rejected scheduled order #{order.id}: {err_str}")
                order.status = 'FAILED'
                order.execution_error = err_str
                order.executed_at = now_utc
                order.updated_at = now_utc
                db.session.commit()
                processed.append(order.to_dict())

                fail_msg = f"❌ Scheduled 9:30 AM buy for {order.symbol} failed: {err_str}"
                create_system_notification(
                    user_id_or_name=order.user_id,
                    category='trade_alert',
                    symbol=order.symbol,
                    message=fail_msg,
                    table_type='portfolio',
                )
                if user and getattr(user, 'telegram_chat_id', None):
                    send_telegram_message(user.username, fail_msg)

            except Exception as exc:
                logger.error(f"[SCHEDULED_ORDER] Unexpected exception executing order #{order.id}: {exc}", exc_info=True)
                order.status = 'FAILED'
                order.execution_error = f"Execution error: {exc}"
                order.executed_at = now_utc
                order.updated_at = now_utc
                db.session.commit()
                processed.append(order.to_dict())

    finally:
        if ctx:
            ctx.pop()

    return processed
