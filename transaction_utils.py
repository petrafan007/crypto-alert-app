import json
import logging
import re
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Tuple

import requests
from sqlalchemy import text
from core.extensions import db

DEFAULT_LOGGER = logging.getLogger(__name__)


def _parse_activity_datetime(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        dt_obj = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=timezone.utc)
        return dt_obj
    except Exception:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt_obj = datetime.strptime(str(value), fmt)
                return dt_obj.replace(tzinfo=timezone.utc)
            except Exception:
                continue
    return datetime.min.replace(tzinfo=timezone.utc)


def _get_price_usdt(asset: str, price_cache: Dict[str, float], logger) -> Optional[float]:
    asset = (asset or '').upper()
    if asset in price_cache:
        return price_cache[asset]
    if asset in ('USD', 'USDT'):
        price_cache[asset] = 1.0
        return 1.0
    symbol = f"{asset}USDT"
    try:
        resp = requests.get(
            "https://api.binance.us/api/v3/ticker/price",
            params={"symbol": symbol},
            timeout=5
        )
        resp.raise_for_status()
        data = resp.json()
        price = float(data.get('price'))
        price_cache[asset] = price
        return price
    except Exception as exc:
        logger.warning(f"Failed to fetch price for {asset}: {exc}")
        price_cache[asset] = None
        return None


def _parse_commission(details: str, default_quote: str = 'USDT') -> Tuple[float, str]:
    if not details:
        return 0.0, default_quote.upper()

    details = details.strip()
    if details.startswith('{'):
        try:
            data = json.loads(details)
            total = data.get('commission_detail_total', {}).get('total_commission')
            if total in (None, '', '0'):
                total = data.get('total_fees') or data.get('fee') or data.get('totalFee')
            total = float(total or 0.0)
            product_id = data.get('product_id', '')
            if '-' in product_id:
                _, quote = product_id.split('-', 1)
            else:
                quote = default_quote
            return total, quote.upper()
        except Exception:
            pass

    match = re.search(r'Commission:\s*([0-9.eE+-]+)\s*([A-Za-z]+)', details)
    if match:
        return float(match.group(1)), match.group(2).upper()

    match = re.search(r'Fee:\s*([0-9.eE+-]+)\s*([A-Za-z]+)', details)
    if match:
        return float(match.group(1)), match.group(2).upper()

    return 0.0, default_quote.upper()


def _convert_commission_to_usd(
    base_asset: str,
    commission_value: float,
    commission_asset: str,
    trade_price: Optional[float],
    price_cache: Dict[str, float],
    price_provider: Optional[Callable[[str], Optional[float]]],
    logger
) -> float:
    if commission_value <= 0:
        return 0.0

    asset = (commission_asset or '').upper()
    if not asset:
        return 0.0

    if asset in ('USD', 'USDT'):
        return commission_value

    if asset == base_asset.upper() and trade_price:
        return commission_value * trade_price

    price = None
    if price_provider:
        try:
            price = price_provider(asset)
        except Exception as exc:
            logger.warning(f"Price provider failed for {asset}: {exc}")

    if price is None:
        price = _get_price_usdt(asset, price_cache, logger)

    if price is None:
        return 0.0
    return commission_value * price


def _determine_trade_price(row, entry_type: str, fallback_price: Optional[float]) -> Optional[float]:
    # In SQLAlchemy Row, we access by index or key. Convert to dict first in main loop to handle easily.
    price_fields = [
        row.get('price_sold_at'),
        row.get('avg_entry'),
        fallback_price,
    ]
    for candidate in price_fields:
        try:
            value = float(candidate)
            if value > 0:
                return value
        except (TypeError, ValueError):
            continue
    proceeds = row.get('proceeds')
    amount = abs(float(row.get('amount') or 0))
    if entry_type == 'SELL' and proceeds and amount:
        try:
            return float(proceeds) / amount
        except ZeroDivisionError:
            return None
    cost_basis = row.get('cost_basis')
    if entry_type == 'BUY' and cost_basis and amount:
        try:
            return float(cost_basis) / amount
        except ZeroDivisionError:
            return None
    return None


def recalculate_asset_activity(
    user_id: Optional[int] = None,
    asset: Optional[str] = None,
    price_provider: Optional[Callable[[str], Optional[float]]] = None,
    logger: Optional[logging.Logger] = None,
):
    """
    Recalculates cost basis, proceeds, and gain/loss for transactions in Postgres.
    Removed sqlite3 dependency and db_path.
    """
    log = logger or DEFAULT_LOGGER

    if user_id is not None:
        user_ids = [user_id]
    else:
        # Get all distinct user_ids
        rows = db.session.execute(text("SELECT DISTINCT user_id FROM all_activities")).fetchall()
        user_ids = [row[0] for row in rows]

    for uid in user_ids:
        if asset is not None:
            assets = [asset.upper()]
        else:
            rows = db.session.execute(
                text("SELECT DISTINCT asset FROM all_activities WHERE user_id = :uid"),
                {'uid': uid}
            ).fetchall()
            assets = [row[0].upper() for row in rows if row[0]]

        for base_asset in assets:
            # Fetch transactions
            # Note: Postgres has 'id' usually, but existing schema might still have 'rowid' concept 
            # or we migrated rowid to id. Let's assume 'id' is the primary key in Postgres 'all_activities' table.
            # Checking trading_models.py (which I can't see right now but assuming standard migration)
            # If 'id' is the PK, use 'id'.
            
            rows = db.session.execute(
                text("""
                SELECT id, date, type, amount, proceeds, cost_basis, fee, details,
                       avg_entry, price_sold_at
                FROM all_activities
                WHERE user_id = :uid AND asset = :asset
                """),
                {'uid': uid, 'asset': base_asset}
            ).fetchall()
            
            if not rows:
                continue

            # Convert to dicts for easier handling
            # SQLAlchemy rows are accessible by column name
            row_dicts = []
            for r in rows:
                # _mapping converts Row to a dict-like interface
                row_dicts.append(dict(r._mapping))

            sorted_rows = sorted(row_dicts, key=lambda r: _parse_activity_datetime(r['date']))
            lots = []
            updates = []
            price_cache: Dict[str, float] = {}

            for row_data in sorted_rows:
                entry_type = (row_data.get('type') or '').strip().upper()
                amount_raw = float(row_data.get('amount') or 0.0)
                qty = abs(amount_raw)
                if qty <= 0:
                    continue

                if entry_type not in ('BUY', 'SELL'):
                    entry_type = 'SELL' if amount_raw < 0 else 'BUY'

                commission_value, commission_asset = _parse_commission(row_data.get('details'))
                trade_price = _determine_trade_price(row_data, entry_type, None)
                commission_usd = _convert_commission_to_usd(
                    base_asset,
                    commission_value,
                    commission_asset,
                    trade_price,
                    price_cache,
                    price_provider,
                    log
                )

                # Use 'id' for update
                row_id = row_data['id']

                if entry_type == 'BUY':
                    net_qty = qty
                    if commission_asset.upper() == base_asset:
                        net_qty = max(qty - commission_value, 0.0)
                    if net_qty <= 0:
                        continue
                    effective_price = trade_price or 0.0
                    cost_usd = (effective_price * qty) + commission_usd
                    unit_cost = cost_usd / net_qty if net_qty else effective_price
                    lots.append({'amount': net_qty, 'price': unit_cost})
                    new_amount = qty  # keep original quantity for reporting
                    updates.append({
                        'type': entry_type,
                        'amount': new_amount,
                        'proceeds': None,
                        'cost_basis': cost_usd,
                        'fee': commission_usd,
                        'gain_loss': 0.0,
                        'id': row_id
                    })
                else:  # SELL
                    removed_qty = qty
                    if commission_asset.upper() == base_asset:
                        removed_qty += commission_value

                    realized_cost = 0.0
                    amount_to_remove = removed_qty
                    while amount_to_remove > 1e-12 and lots:
                        lot = lots[0]
                        take = min(lot['amount'], amount_to_remove)
                        realized_cost += take * lot['price']
                        lot['amount'] -= take
                        amount_to_remove -= take
                        if lot['amount'] <= 1e-12:
                            lots.pop(0)

                    if amount_to_remove > 1e-12:
                        fallback_price = trade_price or row_data.get('avg_entry')
                        if fallback_price:
                            realized_cost += amount_to_remove * float(fallback_price)
                        log.warning(
                            f"Insufficient lots for {base_asset} sell on {row_data.get('date')}; "
                            "using fallback pricing for remaining amount."
                        )

                    effective_price = trade_price or 0.0
                    gross_proceeds = effective_price * qty
                    proceeds_usd = gross_proceeds - commission_usd
                    gain_loss = proceeds_usd - realized_cost
                    new_amount = -qty
                    updates.append({
                        'type': entry_type,
                        'amount': new_amount,
                        'proceeds': proceeds_usd,
                        'cost_basis': realized_cost,
                        'fee': commission_usd,
                        'gain_loss': gain_loss,
                        'id': row_id
                    })

            if updates:
                # Perform bulk update
                # Postgres usually supports executemany well with SQLAlchemy
                for update_data in updates:
                    db.session.execute(
                        text("""
                        UPDATE all_activities
                        SET type = :type, amount = :amount, proceeds = :proceeds, 
                            cost_basis = :cost_basis, fee = :fee, gain_loss = :gain_loss
                        WHERE id = :id
                        """),
                        update_data
                    )
                db.session.commit()
                log.info(
                    f"Recalculated {len(updates)} transactions for user {uid} / asset {base_asset}"
                )