"""Account-scoped staking discovery and durable, at-most-once purchase submission."""
import json
import uuid
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from datetime import datetime

from core.extensions import db
from models import StakingPurchase, StakedCoin, Coin
from trading_models import RealOrder, StakingOrder
from services.staking_service import staking_catalog, binance_us_api_call, invalidate_staking_cache


def trading_client(cred, allow_read=False):
    from binance.client import Client
    key = getattr(cred, 'trading_api_key', None)
    secret = getattr(cred, 'trading_api_secret', None)
    if allow_read and not (key and secret):
        key, secret = getattr(cred, 'api_key', None), getattr(cred, 'api_secret', None)
    if not (key and secret):
        raise ValueError('Configure Binance.US API credentials in Settings.')
    return Client(key, secret, tld='us', requests_params={'timeout': (3, 8)})



def discovery(cred):
    from concurrent.futures import ThreadPoolExecutor
    client = trading_client(cred, allow_read=True)
    # Decrypted credentials/client belong to this request; no scoped DB session in threads.
    with ThreadPoolExecutor(max_workers=3) as pool:
        account_task = pool.submit(client.get_account)
        rules_task = pool.submit(client.get_exchange_info)
        prices_task = pool.submit(client.get_all_tickers)
        assets = staking_catalog(cred)
        account, rules, tickers = account_task.result(), rules_task.result(), prices_task.result()
    prices = {row['symbol']: float(row['price']) for row in tickers}
    balances = {}
    for row in account.get('balances', []):
        symbol = row['asset']
        free = float(row.get('free', 0))
        if free <= 0:
            continue
        price = 1 if symbol in ('USD', 'USDT') else prices.get(symbol + 'USDT', prices.get(symbol + 'USD', 0))
        balances[symbol] = {'symbol': symbol, 'balance': free, 'locked': float(row.get('locked', 0)),
                            'price': price, 'value': free * price}
    pairs = {row['symbol']: row for row in rules.get('symbols', []) if row.get('status') == 'TRADING'
             and row.get('isSpotTradingAllowed', True) and row.get('quoteOrderQtyMarketAllowed', True)}
    for asset in assets:
        asset['quoteAssets'] = [quote for quote in ('USD', 'USDT') if asset['stakingAsset'] + quote in pairs]
    unique = {row['stakingAsset']: row for row in sorted(assets, key=lambda row: row['apy'])
              if row.get('status', 'ACTIVE') not in ('DISABLED', 'SUSPENDED')}
    recommendations = sorted(unique.values(), key=lambda row: (-row['apy'], row['stakingAsset']))[:5]
    return {'assets': assets, 'balances': balances, 'recommendations': recommendations,
            'asOf': datetime.utcnow().isoformat() + 'Z'}


def receipt(intent):
    return {'id': intent.id, 'status': intent.status, 'asset': intent.asset,
            'quoteAsset': intent.quote_asset, 'quoteAmount': intent.quote_amount,
            'stakeRequested': intent.stake_requested, **json.loads(intent.result or '{}')}


def save(intent, status, **values):
    result = json.loads(intent.result or '{}')
    result.update(values)
    intent.status = status
    intent.result = json.dumps(result)
    db.session.commit()
    return receipt(intent)


def purchase(user_id, cred, settings, data):
    """Never repeat a POST, even after process death or an ambiguous exchange timeout.

    The persisted submitting state precedes the external side effect. A replay only
    reads its receipt. Unknown submissions require exchange reconciliation, not retry.
    """
    intent_id = str(uuid.UUID(str(data.get('id', ''))))
    existing = db.session.get(StakingPurchase, intent_id)
    if existing:
        if existing.user_id != user_id:
            raise ValueError('Invalid purchase reference.')
        return receipt(existing)
    if not settings or settings.test_mode_enabled:
        raise ValueError('Enable real trading in Settings before purchasing staking assets.')
    asset = str(data.get('asset', '')).upper()
    quote = str(data.get('quoteAsset', '')).upper()
    if quote not in ('USD', 'USDT') or not asset.isalnum():
        raise ValueError('Choose a supported asset and USD or USDT balance.')
    try:
        amount = Decimal(str(data.get('quoteAmount', '0')))
        if not amount.is_finite() or amount <= 1:
            raise ValueError('Purchase amount must exceed 1 USD or USDT.')
        amount = amount.quantize(Decimal('.01'), rounding=ROUND_DOWN)
    except InvalidOperation:
        raise ValueError('Enter a valid purchase amount.')
    if amount > Decimal(str(settings.max_order_size_usd or 0)):
        raise ValueError('Purchase exceeds your configured maximum order size.')
    catalog = {row['stakingAsset']: row for row in staking_catalog(cred)}
    product = catalog.get(asset)
    if not product:
        raise ValueError('This asset is no longer available to stake on Binance.US.')
    client = trading_client(cred)
    symbol = asset + quote
    rules = client.get_symbol_info(symbol)
    if not rules or rules.get('status') != 'TRADING' or not rules.get('quoteOrderQtyMarketAllowed', True):
        raise ValueError('This market does not currently support purchases with the selected currency.')
    filters = {row['filterType']: row for row in rules.get('filters', [])}
    minimum = Decimal(str((filters.get('NOTIONAL') or filters.get('MIN_NOTIONAL') or {}).get('minNotional', 0)))
    if amount < minimum:
        raise ValueError(f'Minimum purchase is {minimum} {quote}.')
    balances = {row['asset']: Decimal(row.get('free', '0')) for row in client.get_account().get('balances', [])}
    if amount * Decimal('1.01') > balances.get(quote, Decimal(0)):
        raise ValueError(f'Insufficient free {quote}; leave 1% available for trading fees.')
    stake_requested = data.get('stake') is True
    price = Decimal(client.get_symbol_ticker(symbol=symbol)['price'])
    if not price.is_finite() or price <= 0:
        raise ValueError('A valid current market price is unavailable.')
    if stake_requested and amount / price * Decimal('.99') < Decimal(str(product.get('minStakingLimit', 0))):
        raise ValueError(f"Purchase may be below the staking minimum of {product.get('minStakingLimit')} {asset}. Increase it or choose Buy only.")
    intent = StakingPurchase(id=intent_id, user_id=user_id, asset=asset, quote_asset=quote,
                             quote_amount=str(amount), stake_requested=stake_requested, status='buy_submitting')
    db.session.add(intent)
    # Unique PK resolves concurrent submissions before either can place another order.
    from sqlalchemy.exc import IntegrityError
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = db.session.get(StakingPurchase, intent_id)
        if not existing or existing.user_id != user_id:
            raise ValueError('Invalid purchase reference.')
        return receipt(existing)
    try:
        order = client.create_order(symbol=symbol, side='BUY', type='MARKET', quoteOrderQty=str(amount),
                                    newClientOrderId='stak' + intent_id.replace('-', ''), newOrderRespType='FULL')
    except Exception:
        return save(intent, 'buy_unknown', message='Purchase confirmation unavailable. Do not buy again; check this receipt and Binance order history.')
    # Persist the exchange response before any accounting or second external action.
    save(intent, 'buy_received', order=order)
    if order.get('status') != 'FILLED':
        return save(intent, 'buy_pending', message='Order submitted but not fully filled. Staking was not submitted; check Binance order history.')
    quantity = Decimal(str(order.get('executedQty', 0)))
    if not quantity.is_finite() or quantity <= 0:
        return save(intent, 'buy_unknown', message='The exchange returned an invalid fill quantity. Check Binance order history before trading or staking.')
    fills = order.get('fills', [])
    base_fee = sum((Decimal(str(fill.get('commission', 0))) for fill in fills if fill.get('commissionAsset') == asset), Decimal(0))
    net_quantity = max(Decimal(0), quantity - base_fee)
    quote_filled = Decimal(str(order.get('cummulativeQuoteQty', 0)))
    average = float(quote_filled / quantity) if quantity else 0
    db.session.add(RealOrder(user_id=user_id, symbol=symbol, side='BUY', type='MARKET', quantity=float(quantity),
        status='FILLED', binance_order_id=order['orderId'], binance_client_order_id=order.get('clientOrderId'),
        executed_qty=float(quantity), cumulative_quote_qty=float(quote_filled), avg_fill_price=average,
        order_response=json.dumps(order), filled_at=datetime.utcnow()))
    coin = Coin.query.filter_by(user_id=user_id, symbol=asset).first()
    if coin is None:
        coin = Coin(user_id=user_id, symbol=asset, amount=0, avg_entry=0)
        db.session.add(coin)
    old_qty = float(coin.amount or 0)
    coin.avg_entry = ((coin.avg_entry or 0) * old_qty + float(quote_filled)) / (old_qty + float(net_quantity)) if net_quantity else coin.avg_entry
    coin.amount = old_qty + float(net_quantity)
    coin.current = average
    quote_coin = Coin.query.filter_by(user_id=user_id, symbol=quote).first()
    quote_fee = sum((Decimal(str(fill.get('commission', 0))) for fill in fills if fill.get('commissionAsset') == quote), Decimal(0))
    if quote_coin:
        quote_coin.amount = max(0, float(quote_coin.amount or 0) - float(quote_filled + quote_fee))

    invalidate_staking_cache(cred)
    save(intent, 'bought', purchasedQuantity=str(net_quantity), message='Purchase filled. Coins are available in your Binance account.')
    if not stake_requested:
        return receipt(intent)
    if not fills or sum((Decimal(str(fill.get('qty', 0))) for fill in fills), Decimal(0)) < quantity:
        return save(intent, 'bought_not_staked', message='Purchase filled, but complete fee details are unavailable. Verify the free balance before staking from Available Assets.')
    try:
        free = Decimal(client.get_asset_balance(asset=asset)['free'])
        stake_qty = min(net_quantity, free).quantize(Decimal('.00000001'), rounding=ROUND_DOWN)
        if stake_qty < Decimal(str(product.get('minStakingLimit', 0))) or stake_qty <= 0:
            return save(intent, 'bought_not_staked', message='Purchase filled, but the available amount is below the staking minimum. Your coins remain available.')
        if product.get('maxStakingLimit') and stake_qty > Decimal(str(product['maxStakingLimit'])):
            return save(intent, 'bought_not_staked', message='Purchase filled, but the amount exceeds the staking maximum. Stake a smaller amount from Available Assets.')
        save(intent, 'stake_submitting', stakeQuantity=str(stake_qty))
        response = binance_us_api_call(cred, '/sapi/v1/staking/stake', method='POST', use_trading_keys=True,
            params_dict={'stakingAsset': asset, 'amount': str(stake_qty), 'autoRestake': str(data.get('autoRestake') is True).lower()})
        result = response.json()
    except Exception:
        return save(intent, 'stake_unknown', message='Purchase filled. Staking confirmation is unavailable; check staking history before submitting another stake.')
    if response.status_code != 200 or not isinstance(result, dict) or result.get('success') is False or not (result.get('success') is True or result.get('code') == '000000'):
        return save(intent, 'bought_not_staked', stakingResponse=result, message='Purchase filled; Binance did not accept staking. Your purchased coins remain in your account. Check Available Assets before retrying staking.')
    save(intent, 'stake_accepted', stakingResponse=result, message='Purchase filled and staking accepted. Binance bonding and reward eligibility may take time.')
    transaction = str((result.get('data') or {}).get('purchaseRecordId', ''))
    coin.amount = max(0, float(coin.amount or 0) - float(stake_qty))
    db.session.add(StakedCoin(user_id=user_id, symbol=asset, amount=float(stake_qty), status='pending',
        stake_transaction_id=transaction, apy=product['apy'], apr=float(product.get('apr') or 0),
        reward_asset=product.get('rewardAsset', asset), unstaking_period_hours=int(product.get('unstakingPeriod') or 168), auto_restake=data.get('autoRestake') is True))
    db.session.add(StakingOrder(user_id=user_id, symbol=asset, action='stake', amount=float(stake_qty),
        status='pending', transaction_id=transaction, extra_metadata=json.dumps({'purchase_id': intent.id, 'raw_response': result})))
    db.session.commit()
    return receipt(intent)
