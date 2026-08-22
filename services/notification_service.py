from datetime import datetime
import requests
import pytz
from log import logger
from core.extensions import db
from models import Notification
from services.credential_service import get_user_credentials

def send_telegram_message(username, message, admin_notify=True):
    """
    Send a plain text Telegram message using stored user credentials.
    Returns True if the message was sent successfully.
    """
    try:
        cred = get_user_credentials(username)
        if not cred or not cred.telegram_token or not cred.telegram_chat_id:
            logger.error(f"[TELEGRAM] Missing Telegram credentials for user: {username}")
            return False

        url = f"https://api.telegram.org/bot{cred.telegram_token}/sendMessage"
        payload = {'chat_id': cred.telegram_chat_id, 'text': message}

        try:
            response = requests.post(url, data=payload, timeout=10)
            if response.status_code != 200:
                logger.error(f"[TELEGRAM] ERROR: {response.status_code} - {response.text}")
                return False
            return True
        except Exception as exc:
            logger.error(f"[TELEGRAM] Exception: {exc}")
            return False
    except Exception as e:
        logger.error(f"[TELEGRAM] Unexpected error: {e}")
        return False

def send_telegram_alert(username, symbol, price, alert_type, threshold, admin_notify=True):
    """Unified Telegram alert sender."""
    try:
        symbol = str(symbol).upper()
        price = round(float(price), 6)
        threshold = round(float(threshold), 6)
        alert_type_str = "fell below" if alert_type == "down" else "rose above"
        
        eastern = pytz.timezone("US/Eastern")
        now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
        now_eastern = now_utc.astimezone(eastern)
        time_str = now_eastern.strftime("%Y-%m-%d %I:%M:%S %p %Z")
        
        msg = (
            f"⚠️ {symbol} alert: Price {alert_type_str} {threshold:.6f} USDT. "
            f"Current price: {price:.6f}\n"
            f"{time_str}"
        )
        return send_telegram_message(username, msg, admin_notify=admin_notify)
    except Exception as e:
        logger.error(f"Error sending telegram alert: {e}")
        return False

def notify_order_fill(order, username, executed_qty, quote_qty, fill_price=None):
    """Send Telegram notification and persist Notification record for filled orders"""
    try:
        symbol = str(getattr(order, 'symbol', '')).upper()
        side = str(getattr(order, 'side', 'BUY')).upper()
        price = fill_price or getattr(order, 'avg_fill_price', None) or getattr(order, 'price', None) or 0.0
        try:
            price = float(price)
        except Exception:
            price = 0.0
        
        msg = (
            f"✅ ORDER FILLED: {side} {executed_qty} {symbol}\n"
            f"Price: ${price:.6f}\n"
            f"Total: ${float(quote_qty):.2f}"
        )
        send_telegram_message(username, msg)
        create_system_notification(
            user_id_or_name=username,
            category='order_filled',
            symbol=symbol,
            message=f"Filled {side} {executed_qty} {symbol} @ ${price:.4f} (Total: ${float(quote_qty):.2f})",
            current_price=price,
            direction='buy' if side == 'BUY' else 'sell'
        )
    except Exception as e:
        logger.error(f"Error notifying order fill: {e}")

def create_system_notification(
    user_id_or_name,
    category,
    symbol,
    message,
    crossing_price=0.0,
    current_price=0.0,
    direction=None,
    threshold_type=None,
    percent_value=None,
    table_type='portfolio',
    coin_id=0
):
    """Helper to persist a notification record by user_id or username"""
    try:
        if isinstance(user_id_or_name, str):
            from credentials import User
            user = User.query.filter_by(username=user_id_or_name).first()
            if not user:
                return None
            user_id = user.id
        else:
            user_id = user_id_or_name

        et = pytz.timezone('US/Eastern')
        now_et = datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(et)
        date_str = now_et.strftime('%m-%d-%Y')
        time_str = now_et.strftime('%I:%M:%S %p %Z')

        def _safe_float(val):
            if val is None:
                return 0.0
            try:
                return float(val)
            except Exception:
                return 0.0

        rec = Notification(
            user_id=user_id,
            coin_id=coin_id or 0,
            table_type=table_type or 'portfolio',
            symbol=str(symbol or '').upper(),
            date=date_str,
            time=time_str,
            crossing_price=_safe_float(crossing_price),
            current_price=_safe_float(current_price),
            direction=direction,
            threshold_type=threshold_type,
            percent_value=_safe_float(percent_value) if percent_value is not None else None,
            category=category,
            message=message
        )
        db.session.add(rec)
        db.session.commit()
        logger.info(f"[NOTIFY] Saved {category} notification for user {user_id}: {symbol} - {message}")
        return rec.id
    except Exception as e:
        logger.error(f"[NOTIFY] Failed to create notification: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return None

def save_notification_record(
    user_id,
    coin_id,
    table_type,
    symbol,
    direction,
    threshold_type,
    percent_value,
    crossing_price,
    current_price,
    category='price_alert',
    message=None,
):
    """Helper to persist a notification record"""
    return create_system_notification(
        user_id_or_name=user_id,
        category=category,
        symbol=symbol,
        message=message,
        crossing_price=crossing_price,
        current_price=current_price,
        direction=direction,
        threshold_type=threshold_type,
        percent_value=percent_value,
        table_type=table_type,
        coin_id=coin_id
    )
