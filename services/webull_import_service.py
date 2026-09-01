"""Persistence and display helpers for read-only Webull portfolio snapshots."""

import json
from datetime import datetime, timezone

from core.extensions import db
from models import ExternalSentimentSignal, WebullAccountSnapshot, WebullHolding, WebullOrder


def _number(value, default=0.0):
    try:
        if value is None or value == '':
            return default
        return float(str(value).replace(',', '').replace('$', '').strip())
    except (TypeError, ValueError):
        return default


def _first_value(payload, *keys):
    for key in keys:
        value = payload.get(key) if isinstance(payload, dict) else None
        if value not in (None, ''):
            return value
    return None


def _webull_order_datetime(value):
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


def _webull_order_id(order):
    return str(_first_value(order, 'order_id', 'orderId', 'id', 'client_order_id', 'clientOrderId') or '').strip()


def import_webull_orders(user_id, orders):
    """Upsert provider orders into the durable per-user Webull ledger."""
    now = datetime.utcnow()
    imported = 0
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        account_id = str(_first_value(order, '_webull_account_id', 'webull_account_id', 'account_id') or '').strip()
        provider_order_id = _webull_order_id(order)
        symbol = str(_first_value(order, 'symbol', 'ticker') or '').strip().upper()
        if not account_id or not provider_order_id or not symbol:
            continue
        record = WebullOrder.query.filter_by(
            user_id=user_id, account_id=account_id, provider_order_id=provider_order_id,
        ).first()
        if record is None:
            record = WebullOrder(
                user_id=user_id, account_id=account_id, provider_order_id=provider_order_id, symbol=symbol,
            )
            db.session.add(record)
        record.client_order_id = str(_first_value(order, 'client_order_id', 'clientOrderId') or '').strip() or None
        record.symbol = symbol
        record.instrument_type = str(_first_value(order, 'instrument_type', 'instrumentType', 'security_type', 'securityType', 'asset_type', 'assetType') or '').strip().upper() or None
        record.event_outcome = str(_first_value(order, 'event_outcome', 'eventOutcome', 'outcome') or '').strip().upper() or None
        record.side = str(_first_value(order, 'side') or '').strip().upper() or None
        record.order_type = str(_first_value(order, 'order_type', 'orderType', 'type') or '').strip().upper() or None
        record.quantity = _number(_first_value(order, 'total_quantity', 'quantity', 'order_quantity'), 0.0)
        record.filled_quantity = _number(_first_value(order, 'filled_quantity', 'executed_quantity', 'filled_qty'), 0.0)
        record.price = _number(_first_value(order, 'limit_price', 'price', 'order_price'), None)
        record.filled_price = _number(_first_value(order, 'average_filled_price', 'avg_fill_price', 'filled_price'), record.price)
        record.status = str(_first_value(order, 'status', 'order_status') or '').strip().upper() or None
        record.created_at = _webull_order_datetime(_first_value(order, 'created_at', 'create_time', 'placed_time', 'place_time', 'submitted_time', 'filled_time_at')) or record.created_at
        record.updated_at = _webull_order_datetime(_first_value(order, 'updated_at', 'update_time', 'filled_time', 'filled_time_at', 'last_updated_time')) or record.updated_at
        record.synced_at = now
        imported += 1
    db.session.commit()
    return imported


def get_webull_order_rows(user_id, *, account_id=None, limit=100):
    """Return persisted Webull orders in the same canonical shape as live history."""
    query = WebullOrder.query.filter_by(user_id=user_id)
    if account_id:
        query = query.filter_by(account_id=str(account_id))
    records = query.order_by(WebullOrder.created_at.desc(), WebullOrder.id.desc()).limit(max(1, min(int(limit or 100), 500))).all()
    account_types = {
        snapshot.account_id: snapshot.account_type
        for snapshot in WebullAccountSnapshot.query.filter_by(user_id=user_id).all()
    }
    return [{
        'id': record.provider_order_id,
        'symbol': record.symbol,
        'side': record.side or 'UNKNOWN',
        'order_type': record.order_type or 'UNKNOWN',
        'quantity': record.quantity or 0.0,
        'price': record.price or 0.0,
        'filled_quantity': record.filled_quantity or 0.0,
        'filled_price': record.filled_price or record.price or 0.0,
        'status': record.status or 'UNKNOWN',
        'created_at': record.created_at.isoformat() if record.created_at else None,
        'updated_at': record.updated_at.isoformat() if record.updated_at else None,
        'source': 'webull', 'origin': 'webull', 'origin_label': 'Webull',
        'instrument_type': record.instrument_type,
        'event_outcome': record.event_outcome,
        'webull_account_id': record.account_id,
        'webull_account_type': account_types.get(record.account_id),
    } for record in records]


def _normalise_option_metadata(position):
    """Extract option contract identity from current and legacy Webull payloads."""
    if str(position.get('instrument_type') or '').upper() != 'OPTION':
        return {}
    details = next((position.get(key) for key in ('option', 'option_contract', 'optionContract', 'instrument') if isinstance(position.get(key), dict)), {})

    def detail_value(*keys):
        return _first_value(position, *keys) or _first_value(details, *keys)

    return {
        'webull_position_id': detail_value('position_id', 'positionId', 'id'),
        'instrument_id': detail_value('instrument_id', 'instrumentId', 'contract_id', 'contractId', 'option_id', 'optionId'),
        'underlying_symbol': detail_value('underlying_symbol', 'underlyingSymbol', 'underlying'),
        'option_expiration': detail_value('option_expire_date', 'optionExpireDate', 'expiration_date', 'expirationDate', 'expiry_date'),
        'option_strike': _number(detail_value('strike_price', 'strikePrice', 'strike'), None),
        'option_type': detail_value('option_type', 'optionType', 'put_call', 'putCall'),
        'option_multiplier': _number(detail_value('multiplier', 'contract_multiplier', 'contractMultiplier'), None),
    }


def import_webull_portfolio_snapshot(user_id, preview):
    """Upsert the latest all-account Webull snapshot for one user.

    The source is deliberately isolated from ``Coin``: imported securities may be
    equities, options, futures, or crypto and must not acquire Binance actions.
    """
    now = datetime.utcnow()
    imported_accounts = 0
    imported_positions = 0
    account_ids = set()

    for account in preview or []:
        if not isinstance(account, dict) or not account.get('account_id'):
            continue
        account_id = str(account['account_id'])
        account_ids.add(account_id)
        balance = account.get('balance') if isinstance(account.get('balance'), dict) else {}
        snapshot = WebullAccountSnapshot.query.filter_by(user_id=user_id, account_id=account_id).first()
        if snapshot is None:
            snapshot = WebullAccountSnapshot(user_id=user_id, account_id=account_id)
            db.session.add(snapshot)
        snapshot.account_type = str(account.get('account_type') or 'Webull Account')
        snapshot.account_name = str(account.get('account_name') or '')
        snapshot.currency = str(balance.get('total_asset_currency') or balance.get('currency') or 'USD')
        snapshot.total_net_liquidation_value = _number(balance.get('total_net_liquidation_value'))
        snapshot.total_cash_balance = _number(balance.get('total_cash_balance'))
        snapshot.total_market_value = _number(balance.get('total_market_value'))
        snapshot.total_unrealized_profit_loss = _number(balance.get('total_unrealized_profit_loss'), None)
        snapshot.synced_at = now
        imported_accounts += 1

        received_keys = set()
        for position in account.get('positions') or []:
            if not isinstance(position, dict):
                continue
            symbol = str(position.get('symbol') or '').strip().upper()
            instrument_type = str(position.get('instrument_type') or 'Security').strip()
            if not symbol:
                continue
            key = (symbol, instrument_type)
            received_keys.add(key)
            new_qty = _number(position.get('quantity'))
            holding = WebullHolding.query.filter_by(
                user_id=user_id, account_id=account_id, symbol=symbol, instrument_type=instrument_type,
            ).first()
            if holding is None:
                holding = WebullHolding(
                    user_id=user_id, account_id=account_id, symbol=symbol, instrument_type=instrument_type,
                    hidden=False, auto_hidden=False, force_visible=False,
                )
                db.session.add(holding)
            else:
                # If quantity changed significantly from a transaction/trade, automatically unhide
                if abs((holding.quantity or 0.0) - new_qty) > 1e-6:
                    holding.hidden = False
                    holding.auto_hidden = False
                    holding.force_visible = True
            holding.quantity = new_qty
            holding.last_price = _number(position.get('last_price'), None)
            holding.cost_price = _number(position.get('cost_price'), None)
            # Webull may omit a position market value; calculate only when both fields exist.
            explicit_value = position.get('market_value') or position.get('current_value')
            holding.current_value = _number(explicit_value, holding.quantity * _number(position.get('last_price')))
            holding.unrealized_profit_loss = _number(position.get('unrealized_profit_loss'), None)
            holding.currency = str(position.get('currency') or snapshot.currency or 'USD')
            for field, value in _normalise_option_metadata(position).items():
                setattr(holding, field, str(value).upper() if field == 'option_type' and value else value)
            holding.event_outcome = str(_first_value(position, 'event_outcome', 'eventOutcome', 'outcome') or '').upper() or None
            holding.synced_at = now
            imported_positions += 1

        # Upsert or delete the synthetic USD/CASH holding for this account.
        # Cash sits in WebullAccountSnapshot.total_cash_balance; we surface it as a
        # WebullHolding row so it appears in the portfolio table alongside equities.
        cash_balance = _number(snapshot.total_cash_balance)
        usd_holding = WebullHolding.query.filter_by(
            user_id=user_id, account_id=account_id, symbol='USD', instrument_type='CASH',
        ).first()
        if cash_balance > 0:
            if usd_holding is None:
                usd_holding = WebullHolding(
                    user_id=user_id, account_id=account_id, symbol='USD', instrument_type='CASH',
                    hidden=False, auto_hidden=False, force_visible=False,
                )
                db.session.add(usd_holding)
            else:
                # Only unhide cash if balance changed significantly (new deposit/trade fill)
                if abs((usd_holding.quantity or 0.0) - cash_balance) > 1e-4:
                    usd_holding.hidden = False
                    usd_holding.auto_hidden = False
                    usd_holding.force_visible = True
            usd_holding.quantity = cash_balance
            usd_holding.last_price = 1.0
            usd_holding.cost_price = 1.0
            usd_holding.current_value = cash_balance
            usd_holding.unrealized_profit_loss = 0.0
            usd_holding.currency = snapshot.currency or 'USD'
            usd_holding.synced_at = now
            received_keys.add(('USD', 'CASH'))
        elif usd_holding is not None:
            db.session.delete(usd_holding)

        existing = WebullHolding.query.filter_by(user_id=user_id, account_id=account_id).all()
        for holding in existing:
            key_type = holding.instrument_type or 'Security'
            if (holding.symbol, key_type) not in received_keys:
                db.session.delete(holding)

    if account_ids:
        for snapshot in WebullAccountSnapshot.query.filter_by(user_id=user_id).all():
            if snapshot.account_id not in account_ids:
                db.session.delete(snapshot)
        for holding in WebullHolding.query.filter_by(user_id=user_id).all():
            if holding.account_id not in account_ids:
                db.session.delete(holding)
    else:
        WebullHolding.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        WebullAccountSnapshot.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    db.session.commit()
    # Keep a source-specific trend series for the dashboard's Webull filter.
    # This is only a value snapshot; it does not submit or alter a Webull order.
    total_value = get_webull_total_value(user_id)
    if total_value > 0:
        from services.portfolio_service import record_portfolio_history
        record_portfolio_history(user_id, total_value, source='webull')
    return {'accounts': imported_accounts, 'positions': imported_positions, 'synced_at': now}


def _webull_account_pill_label(account_class, account_label):
    """Map Webull account class / label to the short pill text shown in the UI."""
    cls = str(account_class or '').upper()
    lbl = str(account_label or '').lower()
    if cls == 'CRYPTO' or 'crypto' in lbl:
        return 'Crypto'
    if 'rollover' in lbl or 'ROLLOVER' in cls:
        return 'Rollover IRA'
    if 'roth' in lbl or 'ROTH' in cls:
        return 'Roth IRA'
    # Individual Cash / Cash / Traditional fall through as 'Cash'
    return 'Cash'


def get_webull_portfolio_rows(user_id):
    """Serialize imported Webull positions for the unified dashboard table."""
    # Build a fast lookup from local account metadata.  Raw account numbers
    # stay server-only; dashboard rows need only a stable masked display value.
    account_meta = {}  # keyed by account_id
    try:
        from credentials import UserSetting  # local import to avoid circular deps
        setting = UserSetting.query.filter_by(user_id=user_id).first()
        raw = getattr(setting, 'webull_connected_accounts', '[]') or '[]'
        stored_accounts = json.loads(raw) if isinstance(raw, str) else (raw or [])
        for acc in stored_accounts:
            acc_id = str(acc.get('account_id') or '')
            if acc_id:
                account_meta[acc_id] = {
                    'account_id_masked': (
                        str(acc.get('account_id_masked') or '')
                        or (f"••••{str(acc.get('account_number') or '')[-4:]}" if len(str(acc.get('account_number') or '')) >= 4 else f"••••{acc_id[-4:]}")
                    ),
                    'webull_account_type': _webull_account_pill_label(
                        acc.get('account_class', ''),
                        acc.get('account_label') or acc.get('account_name', ''),
                    ),
                }
    except Exception:
        pass  # Non-fatal: pill simply won't appear if metadata is unavailable
    rows = []
    for holding in WebullHolding.query.filter_by(user_id=user_id).order_by(WebullHolding.symbol.asc()).all():
        if getattr(holding, 'hidden', False) and not getattr(holding, 'force_visible', False):
            continue
        amount = _number(holding.quantity)
        is_cash = (holding.instrument_type or '').upper() == 'CASH'
        # USD cash rows always price at $1.00; never show a % change or unrealized PnL.
        current = 1.0 if is_cash else _number(holding.last_price, None)
        cost = 1.0 if is_cash else _number(holding.cost_price, None)
        value = _number(holding.current_value) if _number(holding.current_value) else (amount if is_cash else 0.0)
        pnl = 0.0 if is_cash else _number(holding.unrealized_profit_loss, None)
        pct = None if is_cash else (((current - cost) / cost * 100) if current is not None and cost and cost > 0 else None)
        latest_signal = ExternalSentimentSignal.query.filter_by(
            user_id=user_id, provider='webull', symbol=holding.symbol,
            instrument_type=str(holding.instrument_type or '').upper(),
        ).order_by(ExternalSentimentSignal.created_at.desc()).first()
        meta = account_meta.get(str(holding.account_id) if holding.account_id else '', {})
        rows.append({
            'id': f'webull-{holding.id}', 'symbol': holding.symbol, 'amount': amount,
            'current_price': current, 'current_value': value, 'avg_entry': cost,
            'cost_basis': (cost * amount) if cost is not None else None,
            'pct_change': pct, 'webull_unrealized_pnl': pnl,
            'source': 'webull', 'source_label': 'Webull', 'is_external': True,
            'account_id': holding.account_id or '',
            'account_id_masked': meta.get('account_id_masked', ''),
            'webull_account_type': meta.get('webull_account_type', ''),
            'instrument_type': holding.instrument_type or 'Security', 'currency': holding.currency or 'USD',
            'webull_position_id': holding.webull_position_id,
            'instrument_id': holding.instrument_id,
            'underlying_symbol': holding.underlying_symbol,
            'option_expiration': holding.option_expiration,
            'option_strike': holding.option_strike,
            'option_type': holding.option_type,
            'option_multiplier': holding.option_multiplier,
            'event_outcome': holding.event_outcome,
            'hidden': bool(getattr(holding, 'hidden', False)),
            'force_visible': bool(getattr(holding, 'force_visible', False)),
            'last_updated': holding.synced_at.isoformat() if holding.synced_at else None,
            'custom_lower_type': holding.custom_lower_type or '#',
            'custom_upper_type': holding.custom_upper_type or '#',
            'custom_lower_val': holding.custom_lower_val,
            'custom_upper_val': holding.custom_upper_val,
            'custom_lower_pct': holding.custom_lower_pct,
            'custom_upper_pct': holding.custom_upper_pct,
            'volatility_pct': holding.volatility_pct,
            'alert_enabled': bool(holding.alert_enabled),
            'sentiment_tracking_enabled': holding.sentiment_tracking_enabled is not False,
            'sentiment': (latest_signal.recommendation if latest_signal else 'Hold') if holding.sentiment_tracking_enabled is not False else 'Not Tracked',
            'sentiment_reason': latest_signal.reason if latest_signal else '',
            'sentiment_last_updated': latest_signal.created_at.isoformat() if latest_signal and latest_signal.created_at else None,
            'sentiment_provider': latest_signal.ai_provider if latest_signal else None,
            'sentiment_model': latest_signal.provider_model if latest_signal else None,
            'sentiment_tier': latest_signal.ai_tier if latest_signal else None,
            'sentiment_search_status': latest_signal.search_status if latest_signal else None,
            'sentiment_failover_history': latest_signal.failover_history if latest_signal else None,
        })
    return rows


def get_webull_total_value(user_id):
    return sum(_number(item.total_net_liquidation_value) for item in WebullAccountSnapshot.query.filter_by(user_id=user_id).all())
