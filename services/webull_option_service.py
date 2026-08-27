"""Read-only option-contract identity and display helpers for Webull."""

from core.extensions import db
from services.webull_service import WebullConnectionError, get_webull_option_contracts


def _pick(payload, *keys):
    for key in keys:
        value = payload.get(key) if isinstance(payload, dict) else None
        if value not in (None, ''):
            return value
    return None


def _numeric(value):
    try:
        return float(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None


def _contract_identity(contract):
    return {
        'instrument_id': _pick(contract, 'instrument_id', 'instrumentId', 'contract_id', 'contractId', 'id'),
        'symbol': _pick(contract, 'symbol', 'contract_symbol', 'contractSymbol', 'option_symbol', 'optionSymbol'),
        'underlying_symbol': _pick(contract, 'underlying_symbol', 'underlyingSymbol', 'underlying'),
        'option_expiration': _pick(contract, 'option_expire_date', 'optionExpireDate', 'expiration_date', 'expirationDate', 'expiry_date'),
        'option_strike': _numeric(_pick(contract, 'strike_price', 'strikePrice', 'strike')),
        'option_type': _pick(contract, 'option_type', 'optionType', 'put_call', 'putCall'),
        'option_multiplier': _numeric(_pick(contract, 'multiplier', 'contract_multiplier', 'contractMultiplier')),
    }


def resolve_option_contract(holding, app_key, app_secret, environment, access_token):
    """Fill missing option identity using Webull's static contract list.

    An exact contract display symbol is preferred.  If Webull supplied static
    strike/expiration/type fields, those form a second exact match.  We never
    guess based on the underlying alone.
    """
    if getattr(holding, 'instrument_id', None):
        return holding
    underlying = getattr(holding, 'underlying_symbol', None)
    if not underlying:
        raise WebullConnectionError('Webull did not provide this option’s contract ID or underlying symbol. Refresh the portfolio import after the contract metadata is available.')
    contracts = get_webull_option_contracts(
        app_key, app_secret, environment, access_token, underlying_symbol=underlying,
    )
    target_symbol = str(getattr(holding, 'symbol', '')).upper()
    candidates = []
    for raw in contracts:
        identity = _contract_identity(raw)
        if not identity['instrument_id']:
            continue
        if str(identity['symbol'] or '').upper() == target_symbol:
            candidates = [identity]
            break
        if (
            getattr(holding, 'option_expiration', None) and getattr(holding, 'option_strike', None) is not None
            and getattr(holding, 'option_type', None)
            and str(identity['option_expiration'] or '') == str(holding.option_expiration)
            and identity['option_strike'] == holding.option_strike
            and str(identity['option_type'] or '').upper() == str(holding.option_type).upper()
        ):
            candidates.append(identity)
    if len(candidates) != 1:
        raise WebullConnectionError('Webull could not uniquely resolve this option contract. Its position is preserved, but no quote or chart will be shown until the contract identifier is available.')
    identity = candidates[0]
    holding.instrument_id = str(identity['instrument_id'])
    for field in ('underlying_symbol', 'option_expiration', 'option_strike', 'option_type', 'option_multiplier'):
        if identity.get(field) not in (None, ''):
            setattr(holding, field, str(identity[field]).upper() if field == 'option_type' else identity[field])
    db.session.commit()
    return holding


def option_contract_label(holding):
    """Compact human-readable contract label with no assumptions."""
    parts = [str(getattr(holding, 'underlying_symbol', None) or getattr(holding, 'symbol', '')).upper()]
    if getattr(holding, 'option_expiration', None):
        parts.append(str(holding.option_expiration))
    if getattr(holding, 'option_strike', None) is not None:
        parts.append(f'${float(holding.option_strike):g}')
    if getattr(holding, 'option_type', None):
        parts.append(str(holding.option_type).upper())
    return ' · '.join(parts)
