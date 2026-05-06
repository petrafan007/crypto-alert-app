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
    """Send Telegram notification for filled orders"""
    try:
        symbol = order.symbol
        side = order.side
        price = fill_price or order.avg_fill_price or order.price
        
        msg = (
            f"✅ ORDER FILLED: {side} {executed_qty} {symbol}\n"
            f"Price: ${price:.6f}\n"
            f"Total: ${quote_qty:.2f}"
        )
        send_telegram_message(username, msg)
    except Exception as e:
        logger.error(f"Error notifying order fill: {e}")

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
    try:
        et = pytz.timezone('US/Eastern')
        now_et = datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(et)
        date_str = now_et.strftime('%m-%d-%Y')
        time_str = now_et.strftime('%I:%M:%S %p %Z')
        rec = Notification(
            user_id=user_id,
            coin_id=coin_id,
            table_type=table_type,
            symbol=symbol,
            date=date_str,
            time=time_str,
            crossing_price=float(crossing_price),
            current_price=float(current_price),
            direction=direction,
            threshold_type=threshold_type,
            percent_value=float(percent_value) if percent_value is not None else None,
            category=category,
            message=message
        )
        db.session.add(rec)
        db.session.commit()
        logger.info(f"[NOTIFY] Saved notification {symbol} {direction} {crossing_price} -> {current_price} ({table_type}) for user {user_id}")
        return rec.id
    except Exception as e:
        logger.error(f"Failed to save notification: {e}")
        db.session.rollback()
        return None
