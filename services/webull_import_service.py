"""Persistence and display helpers for read-only Webull portfolio snapshots."""

from datetime import datetime

from core.extensions import db
from models import WebullAccountSnapshot, WebullHolding


def _number(value, default=0.0):
    try:
        if value is None or value == '':
            return default
        return float(str(value).replace(',', '').replace('$', '').strip())
    except (TypeError, ValueError):
        return default


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
            holding = WebullHolding.query.filter_by(
                user_id=user_id, account_id=account_id, symbol=symbol, instrument_type=instrument_type,
            ).first()
            if holding is None:
                holding = WebullHolding(
                    user_id=user_id, account_id=account_id, symbol=symbol, instrument_type=instrument_type,
                )
                db.session.add(holding)
            holding.quantity = _number(position.get('quantity'))
            holding.last_price = _number(position.get('last_price'), None)
            holding.cost_price = _number(position.get('cost_price'), None)
            # Webull may omit a position market value; calculate only when both fields exist.
            explicit_value = position.get('market_value') or position.get('current_value')
            holding.current_value = _number(explicit_value, holding.quantity * _number(position.get('last_price')))
            holding.unrealized_profit_loss = _number(position.get('unrealized_profit_loss'), None)
            holding.currency = str(position.get('currency') or snapshot.currency or 'USD')
            holding.synced_at = now
            imported_positions += 1

        existing = WebullHolding.query.filter_by(user_id=user_id, account_id=account_id).all()
        for holding in existing:
            if (holding.symbol, holding.instrument_type or 'Security') not in received_keys:
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
    return {'accounts': imported_accounts, 'positions': imported_positions, 'synced_at': now}


def get_webull_portfolio_rows(user_id):
    """Serialize imported Webull positions for the unified dashboard table."""
    rows = []
    for holding in WebullHolding.query.filter_by(user_id=user_id).order_by(WebullHolding.symbol.asc()).all():
        amount = _number(holding.quantity)
        current = _number(holding.last_price, None)
        cost = _number(holding.cost_price, None)
        value = _number(holding.current_value)
        pnl = _number(holding.unrealized_profit_loss, None)
        pct = ((current - cost) / cost * 100) if current is not None and cost and cost > 0 else None
        rows.append({
            'id': f'webull-{holding.id}', 'symbol': holding.symbol, 'amount': amount,
            'current_price': current, 'current_value': value, 'avg_entry': cost,
            'cost_basis': (cost * amount) if cost is not None else None,
            'pct_change': pct, 'webull_unrealized_pnl': pnl,
            'source': 'webull', 'source_label': 'Webull', 'is_external': True,
            'instrument_type': holding.instrument_type or 'Security', 'currency': holding.currency or 'USD',
            'last_updated': holding.synced_at.isoformat() if holding.synced_at else None,
            'sentiment_tracking_enabled': False, 'alert_enabled': False,
        })
    return rows


def get_webull_total_value(user_id):
    return sum(_number(item.total_net_liquidation_value) for item in WebullAccountSnapshot.query.filter_by(user_id=user_id).all())
