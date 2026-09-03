"""Provider-neutral asset identity and display helpers.

The same ticker can represent different instruments (for example Binance ETH
and a Webull ETH ETF).  These helpers deliberately rely on provider metadata;
they never infer an ETF from a hard-coded ticker list.
"""

STABLE_SYMBOLS = {
    'USD', 'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP', 'EURC', 'PYUSD',
}


def _metadata(asset):
    if not isinstance(asset, dict):
        return ''
    keys = (
        'instrument_type', 'instrumentType', 'asset_type', 'assetType',
        'security_type', 'securityType', 'product_type', 'productType',
        'security_sub_type', 'securitySubType', 'instrument_category',
        'instrumentCategory', 'asset_class', 'assetClass', 'display_name',
        'displayName', 'security_name', 'securityName', 'asset_name',
        'assetName', 'name',
    )
    return ' '.join(str(asset.get(key) or '').strip() for key in keys).upper()


def is_etf_asset(asset):
    if not isinstance(asset, dict):
        return False
    explicit = next((asset.get(key) for key in ('is_etf', 'isETF', 'etf')
                     if asset.get(key) not in (None, '')), None)
    if explicit is True or str(explicit or '').lower() in {'true', 'yes', 'etf', '1'}:
        return True
    instrument_type = ' '.join(str(asset.get(key) or '').strip() for key in (
        'instrument_type', 'instrumentType', 'asset_type', 'assetType',
        'security_type', 'securityType', 'product_type', 'productType',
        'asset_class', 'assetClass',
    )).upper()
    # An option/future/event can reference an ETF in its name without being an
    # ETF position itself.
    if any(token in instrument_type for token in ('OPTION', 'FUTURE', 'EVENT', 'CONTRACT')):
        return False
    metadata = _metadata(asset)
    return 'EXCHANGE TRADED FUND' in metadata or any(
        token in metadata.split() for token in ('ETF',)
    )


def is_cash_or_stable_asset(asset):
    if isinstance(asset, str):
        asset = {'symbol': asset}
    asset = asset or {}
    symbol = str(asset.get('symbol') or asset.get('ticker') or asset.get('asset') or '').strip().upper()
    metadata = _metadata(asset)
    return symbol in STABLE_SYMBOLS or any(
        phrase in metadata for phrase in ('CASH', 'FIAT', 'STABLECOIN', 'STABLE COIN', 'MONEY MARKET')
    )


def display_symbol(asset):
    asset = asset if isinstance(asset, dict) else {'symbol': asset}
    raw = str(asset.get('display_symbol') or asset.get('displaySymbol')
               or asset.get('symbol') or asset.get('ticker') or asset.get('asset') or '—').strip()
    if not raw or raw == '—':
        return '—'
    if raw.upper().endswith(' ETF'):
        return raw
    return f'{raw.upper()} ETF' if is_etf_asset(asset) else raw.upper()
