"""Capital-gains engine shared by the Binance.US and Webull tax reports.

Rules implemented here:

* Lots are tracked per account or wallet (``asset_key``), never pooled across
  accounts, which IRS rules require for digital assets from 2025.
* Accounting methods: FIFO, LIFO, HIFO (highest unit cost first) and specific
  identification (a sale's ``lot_selection`` lists acquisition IDs to use first).
* Holding period is compared by calendar date: long term only when the sale
  date is after the one-year anniversary of the acquisition date.
* Transfers use their direction: inbound transfers add a lot (flagged when no
  basis is known); outbound transfers remove lots without a taxable event.
* Staking rewards, interest, airdrops and similar receipts are ordinary income
  at their USD value when received and start a lot with that basis.
* Sales that exceed known lots use a zero basis for the excess and are
  flagged for review instead of passing silently.
* Wash sales (securities only) disallow a loss when substantially identical
  shares are bought within 30 days before or after the sale; the disallowed
  loss is added to the replacement lot's basis and its holding period.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

ACQUISITION_TYPES = {'BUY', 'GIFT'}
TRANSFER_TYPES = {'TRANSFER', 'RECEIVE', 'DEPOSIT', 'SEND', 'WITHDRAW', 'WITHDRAWAL'}
INCOME_TYPES = {'STAKING', 'STAKING_REWARD', 'REWARD', 'INTEREST', 'AIRDROP', 'BONUS', 'DIVIDEND', 'MINING', 'INCOME'}
DISPOSAL_TYPES = {'SELL', 'SETTLEMENT', 'EXPIRATION'}
STABLE_ASSETS = {'USD', 'USDT', 'USDC', 'BUSD', 'DAI', 'FDUSD', 'USDG'}
METHODS = {'FIFO', 'LIFO', 'HIFO'}
WASH_SALE_WINDOW_DAYS = 30
EPSILON = 1e-12


def to_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def one_year_anniversary(acquired):
    """Anniversary date of an acquisition; Feb 29 maps to Feb 28."""
    day = acquired.date() if isinstance(acquired, datetime) else acquired
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return day.replace(year=day.year + 1, day=28)


def holding_term(acquired, sold):
    """'long_term' when held more than one year, compared by date only."""
    if not acquired or not sold:
        return 'unclassified'
    sold_day = sold.date() if isinstance(sold, datetime) else sold
    return 'long_term' if sold_day > one_year_anniversary(acquired) else 'short_term'


def _float(value, default=0.0):
    try:
        number = float(value)
        return number if number == number else default
    except (TypeError, ValueError):
        return default


def _unit_price(tx, quantity):
    price = _float(tx.get('price_sold_at')) or _float(tx.get('avg_entry'))
    if price > 0:
        return price
    cost, proceeds = _float(tx.get('cost_basis')), _float(tx.get('proceeds'))
    if quantity > 0 and cost > 0:
        return cost / quantity
    if quantity > 0 and proceeds > 0:
        return proceeds / quantity
    if str(tx.get('asset') or '').upper() in STABLE_ASSETS:
        return 1.0
    return 0.0


class _Lot:
    __slots__ = ('source_id', 'amount', 'cost', 'acquired', 'holding_date', 'wash_adjustment')

    def __init__(self, source_id, amount, cost, acquired):
        self.source_id = source_id
        self.amount = amount
        self.cost = cost
        self.acquired = acquired
        self.holding_date = acquired  # shifted earlier by a wash-sale carryover
        self.wash_adjustment = 0.0

    @property
    def unit_cost(self):
        return self.cost / self.amount if self.amount > EPSILON else 0.0


def _ordered_lots(lots, method, selection):
    if selection:
        chosen = [lot for sid in selection for lot in lots if str(lot.source_id) == str(sid)]
        rest = [lot for lot in lots if lot not in chosen]
        return chosen + _ordered_lots(rest, method, None)
    if method == 'LIFO':
        return list(reversed(lots))
    if method == 'HIFO':
        return sorted(lots, key=lambda lot: (-lot.unit_cost, lot.acquired or datetime.min))
    return list(lots)


def _run(transactions, method, adjustments=None):
    """One pass over the ledger. ``adjustments`` carries wash-sale effects."""
    adjustments = adjustments or {}
    lots_by_key = defaultdict(list)
    rows = []
    sale_details = []
    ordered = sorted(transactions, key=lambda tx: (to_datetime(tx.get('date')) or datetime.min, str(tx.get('id') or '')))
    for tx in ordered:
        tx_type = str(tx.get('type') or '').upper()
        asset = str(tx.get('asset') or '').upper().strip()
        key = str(tx.get('_asset_key') or f"{(tx.get('exchange') or 'binance').lower()}:{asset}").upper()
        raw_amount = _float(tx.get('amount'))
        quantity = abs(raw_amount)
        fee = abs(_float(tx.get('fee')))
        price = _unit_price(tx, quantity)
        tx_date = to_datetime(tx.get('date'))
        review = list(tx.get('_review') or [])
        if tx.get('fee_estimated'):
            review.append('Fee is estimated; the broker did not report it.')
        row = {
            'id': tx.get('id'), 'date': tx_date.isoformat() if tx_date else tx.get('date'),
            'type': tx_type, 'asset': asset, 'asset_key': key,
            'display_symbol': tx.get('display_symbol') or asset,
            'is_etf': bool(tx.get('is_etf')), 'instrument_type': tx.get('instrument_type'),
            'instrument_id': tx.get('instrument_id'), 'account': tx.get('account'),
            'amount': raw_amount, 'proceeds': _float(tx.get('proceeds')), 'fee': fee,
            'fee_asset': tx.get('fee_asset'), 'fee_estimated': bool(tx.get('fee_estimated')),
            'txid': tx.get('txid'), 'cost_basis': _float(tx.get('cost_basis')),
            'price_sold_at': price or tx.get('price_sold_at'), 'avg_entry': price or tx.get('avg_entry'),
            'exchange': tx.get('exchange') or 'binance', 'gain_loss': None, 'gain_loss_type': None,
            'holding_days': None, 'acquisition_date': None, 'short_term_gain_loss': None,
            'long_term_gain_loss': None, 'unclassified_gain_loss': None, 'income': None,
            'wash_sale_disallowed': 0.0, 'adjustment_code': '', 'needs_review': review,
            'reported_on': tx.get('reported_on'),
            'lot_selection': tx.get('lot_selection'),
        }
        lots = lots_by_key[key]

        if tx_type in INCOME_TYPES and quantity > 0:
            value = _float(tx.get('usd_value')) or quantity * price
            if value <= 0:
                review.append('Income value unknown; enter the USD value when received.')
            row.update(income=value, cost_basis=value)
            lots.append(_Lot(tx.get('id'), quantity, value, tx_date))
            rows.append(row)
            continue

        if tx_type in TRANSFER_TYPES:
            inbound = raw_amount > 0 and tx_type not in {'SEND', 'WITHDRAW', 'WITHDRAWAL'}
            if inbound and quantity > 0:
                cost = _float(tx.get('cost_basis'))
                if cost <= 0:
                    review.append('Transferred in without a cost basis; enter what you originally paid.')
                lots.append(_Lot(tx.get('id'), quantity, cost, to_datetime(tx.get('acquired_date')) or tx_date))
                row['cost_basis'] = cost
            elif quantity > 0:
                # Moving coins out of this wallet is not a sale; their lots leave with them.
                remaining = quantity
                while remaining > EPSILON and lots:
                    lot = lots[0]
                    take = min(remaining, lot.amount)
                    lot.cost -= take * lot.unit_cost
                    lot.amount -= take
                    remaining -= take
                    if lot.amount <= EPSILON:
                        lots.pop(0)
            rows.append(row)
            continue

        if tx_type in ACQUISITION_TYPES and quantity > 0:
            cost = _float(tx.get('cost_basis'))
            if cost <= 0:
                proceeds = _float(tx.get('proceeds'))
                cost = (proceeds + fee) if proceeds > 0 else price * quantity + fee
            lot = _Lot(tx.get('id'), quantity, cost, tx_date)
            carry = adjustments.get(('lot', str(tx.get('id'))))
            if carry:
                lot.cost += carry['amount']
                lot.wash_adjustment = carry['amount']
                lot.holding_date = (tx_date - timedelta(days=carry['days'])) if tx_date else tx_date
                row['wash_sale_basis_added'] = carry['amount']
            lots.append(lot)
            row['cost_basis'] = lot.cost
            rows.append(row)
            continue

        if tx_type not in DISPOSAL_TYPES or quantity <= 0:
            rows.append(row)
            continue

        proceeds = _float(tx.get('proceeds'))
        if proceeds <= 0:
            proceeds = max(price * quantity - fee, 0.0)
        row['proceeds'] = proceeds
        per_unit = proceeds / quantity
        remaining, cost_total = quantity, 0.0
        gains = {'short_term': 0.0, 'long_term': 0.0, 'unclassified': 0.0}
        acquisitions, slices = [], []
        for lot in _ordered_lots(lots, method, tx.get('lot_selection')):
            if remaining <= EPSILON:
                break
            take = min(remaining, lot.amount)
            if take <= EPSILON:
                continue
            cost = take * lot.unit_cost
            term = holding_term(lot.holding_date, tx_date)
            gains[term] += take * per_unit - cost
            cost_total += cost
            if lot.holding_date and tx_date:
                acquisitions.append((lot.holding_date, max(0, (tx_date - lot.holding_date).days)))
            slices.append({'lot': str(lot.source_id), 'quantity': take, 'cost': cost,
                           'acquired': lot.holding_date, 'term': term})
            lot.amount -= take
            lot.cost -= cost
            remaining -= take
        lots[:] = [lot for lot in lots if lot.amount > EPSILON]
        if remaining > EPSILON and key.count(':') == 1:
            # Crypto sold from a wallet with no matching purchase was almost
            # always bought in another wallet and moved without a recorded
            # transfer. Use that wallet's lots, and ask for the transfer.
            asset_suffix = ':' + key.split(':', 1)[1]
            borrowed = 0.0
            for other_key, other_lots in lots_by_key.items():
                if remaining <= EPSILON:
                    break
                if other_key == key or other_key.count(':') != 1 or not other_key.endswith(asset_suffix):
                    continue
                for lot in _ordered_lots(other_lots, method, None):
                    if remaining <= EPSILON:
                        break
                    take = min(remaining, lot.amount)
                    if take <= EPSILON:
                        continue
                    cost = take * lot.unit_cost
                    term = holding_term(lot.holding_date, tx_date)
                    gains[term] += take * per_unit - cost
                    cost_total += cost
                    if lot.holding_date and tx_date:
                        acquisitions.append((lot.holding_date, max(0, (tx_date - lot.holding_date).days)))
                    slices.append({'lot': str(lot.source_id), 'quantity': take, 'cost': cost,
                                   'acquired': lot.holding_date, 'term': term})
                    lot.amount -= take
                    lot.cost -= cost
                    remaining -= take
                    borrowed += take
                other_lots[:] = [lot for lot in other_lots if lot.amount > EPSILON]
            if borrowed > EPSILON:
                review.append(f'{borrowed:g} of this sale used purchases recorded in another wallet. '
                              'Add the transfer between wallets to confirm the cost basis.')
        if remaining > EPSILON:
            gains['unclassified'] += remaining * per_unit
            review.append(f'Sold {remaining:g} more than the recorded purchases; zero cost basis used for that part. '
                          'Add the missing purchase or transfer-in to correct it.')
            row['missing_basis_quantity'] = remaining

        gain = proceeds - cost_total
        disallowed = adjustments.get(('sale', str(tx.get('id'))), 0.0)
        if disallowed:
            gain += disallowed
            terms_with_loss = [t for t in ('short_term', 'long_term') if gains[t] < 0]
            for term in terms_with_loss or ['short_term']:
                share = disallowed if len(terms_with_loss) <= 1 else disallowed * gains[term] / sum(gains[t] for t in terms_with_loss)
                gains[term] += share
            row.update(wash_sale_disallowed=disallowed, adjustment_code='W')
        used_terms = sorted({s['term'] for s in slices} | ({'unclassified'} if remaining > EPSILON else set()))
        row.update({
            'cost_basis': cost_total, 'gain_loss': gain,
            'short_term_gain_loss': gains['short_term'], 'long_term_gain_loss': gains['long_term'],
            'unclassified_gain_loss': gains['unclassified'],
            'gain_loss_type': 'mixed' if len(used_terms) > 1 else (used_terms[0] if used_terms else None),
        })
        if acquisitions:
            oldest_date, oldest_days = min(acquisitions, key=lambda item: item[0])
            row['acquisition_date'] = oldest_date.isoformat()
            row['holding_days'] = oldest_days if len(acquisitions) == 1 else None
        rows.append(row)
        sale_details.append({'tx': tx, 'row': row, 'slices': slices, 'date': tx_date, 'key': key,
                             'security': tx.get('_security_key'), 'quantity': quantity,
                             'pre_wash_gain': proceeds - cost_total})

    open_lots = {
        key: [{'amount': lot.amount, 'cost': lot.cost,
               'acquisition_date': lot.acquired.isoformat() if lot.acquired else None,
               'source_id': lot.source_id}
              for lot in lots if lot.amount > EPSILON]
        for key, lots in lots_by_key.items() if any(lot.amount > EPSILON for lot in lots)
    }
    return rows, open_lots, sale_details


def _wash_sale_adjustments(transactions, sale_details):
    """Disallowed losses and replacement-lot carryovers for securities."""
    buys = defaultdict(list)
    for tx in transactions:
        if str(tx.get('type') or '').upper() == 'BUY' and tx.get('_security_key'):
            buys[tx['_security_key']].append({'tx': tx, 'date': to_datetime(tx.get('date')),
                                              'available': abs(_float(tx.get('amount')))})
    adjustments = {}
    for sale in sorted(sale_details, key=lambda s: s['date'] or datetime.min):
        loss = sale['pre_wash_gain']
        if loss >= 0 or not sale['security'] or not sale['date']:
            continue
        consumed = {s['lot'] for s in sale['slices']}
        window_start = sale['date'] - timedelta(days=WASH_SALE_WINDOW_DAYS)
        window_end = sale['date'] + timedelta(days=WASH_SALE_WINDOW_DAYS)
        need = sale['quantity']
        loss_per_unit = -loss / sale['quantity']
        held_days = max((max(0, (sale['date'] - s['acquired']).days) for s in sale['slices'] if s['acquired']), default=0)
        for candidate in sorted(buys[sale['security']], key=lambda b: b['date'] or datetime.min):
            if need <= EPSILON:
                break
            if str(candidate['tx'].get('id')) in consumed or candidate['available'] <= EPSILON or not candidate['date']:
                continue
            if not (window_start <= candidate['date'] <= window_end):
                continue
            take = min(need, candidate['available'])
            candidate['available'] -= take
            need -= take
            amount = take * loss_per_unit
            adjustments[('sale', str(sale['tx'].get('id')))] = adjustments.get(('sale', str(sale['tx'].get('id'))), 0.0) + amount
            carry = adjustments.setdefault(('lot', str(candidate['tx'].get('id'))), {'amount': 0.0, 'days': 0})
            carry['amount'] += amount
            carry['days'] = max(carry['days'], held_days)
    return adjustments


def build_tax_transactions(transactions, accounting_method='FIFO', wash_sales=False):
    """Return (rows, open_lots) for a ledger, applying wash sales when asked."""
    method = str(accounting_method or 'FIFO').upper()
    if method not in METHODS:
        method = 'FIFO'
    rows, open_lots, sales = _run(transactions, method)
    if wash_sales:
        adjustments = _wash_sale_adjustments(transactions, sales)
        if adjustments:
            rows, open_lots, _ = _run(transactions, method, adjustments)
    return rows, open_lots


def summarize(rows):
    sells = [row for row in rows if row['type'] in DISPOSAL_TYPES]
    return {
        'realized_gain': sum(_float(row.get('gain_loss')) for row in sells),
        'short_term_gain_loss': sum(_float(row.get('short_term_gain_loss')) for row in rows),
        'long_term_gain_loss': sum(_float(row.get('long_term_gain_loss')) for row in rows),
        'unclassified_gain_loss': sum(_float(row.get('unclassified_gain_loss')) for row in rows),
        'income_total': sum(_float(row.get('income')) for row in rows),
        'wash_sale_disallowed_total': sum(_float(row.get('wash_sale_disallowed')) for row in rows),
        'needs_review_count': sum(1 for row in rows if row.get('needs_review')),
        'estimated_fee_rows': sum(1 for row in rows if row.get('fee_estimated')),
        'missing_basis_rows': sum(1 for row in rows if row.get('missing_basis_quantity')),
        'total_sell_proceeds': sum(_float(row.get('proceeds')) for row in sells),
    }


def form_8949_rows(rows, year=None):
    """Disposals in Form 8949 order: Part I short term, then Part II long term."""
    result = []
    for row in rows:
        if row['type'] not in DISPOSAL_TYPES or row.get('gain_loss') is None:
            continue
        sold = to_datetime(row['date'])
        if year and (not sold or sold.year != int(year)):
            continue
        term = row.get('gain_loss_type')
        part = 'II' if term == 'long_term' else 'I'
        acquired = 'VARIOUS' if row.get('gain_loss_type') == 'mixed' or not row.get('acquisition_date') \
            else to_datetime(row['acquisition_date']).strftime('%m/%d/%Y')
        quantity = abs(_float(row.get('amount')))
        result.append({
            'part': part,
            'description': f"{quantity:g} {row.get('display_symbol') or row['asset']}",
            'date_acquired': acquired,
            'date_sold': sold.strftime('%m/%d/%Y') if sold else '',
            'proceeds': round(_float(row.get('proceeds')), 2),
            'cost_basis': round(_float(row.get('cost_basis')), 2),
            'code': row.get('adjustment_code') or '',
            'adjustment': round(_float(row.get('wash_sale_disallowed')), 2),
            'gain_loss': round(_float(row.get('gain_loss')), 2),
            'term': term,
            'reported_on': row.get('reported_on') or '',
            'needs_review': '; '.join(row.get('needs_review') or []),
        })
    result.sort(key=lambda r: (r['part'], r['date_sold']))
    return result


def schedule_d_totals(rows_8949):
    totals = {}
    for part in ('I', 'II'):
        part_rows = [r for r in rows_8949 if r['part'] == part]
        totals[part] = {
            'proceeds': round(sum(r['proceeds'] for r in part_rows), 2),
            'cost_basis': round(sum(r['cost_basis'] for r in part_rows), 2),
            'adjustments': round(sum(r['adjustment'] for r in part_rows), 2),
            'gain_loss': round(sum(r['gain_loss'] for r in part_rows), 2),
            'rows': len(part_rows),
        }
    return totals
