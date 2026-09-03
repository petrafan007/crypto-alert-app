// Shared asset identity and display helpers.  A ticker is not, by itself, an
// instrument identity: ETH on Binance and an ETH ETF held at Webull must stay
// distinct while still being readable everywhere in the UI.

const STABLE_SYMBOLS = new Set([
  'USD', 'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP', 'EURC', 'PYUSD',
]);

const valueText = (asset, keys) => keys
  .map((key) => asset?.[key])
  .filter((value) => value !== undefined && value !== null && String(value).trim() !== '')
  .map((value) => String(value).trim())
  .join(' ');

export const isEtfAsset = (asset = {}) => {
  if (!asset || typeof asset !== 'object') return false;
  const explicit = [asset.is_etf, asset.isETF, asset.etf]
    .find((value) => value !== undefined && value !== null && value !== '');
  if (explicit === true || ['true', 'yes', 'etf', '1'].includes(String(explicit || '').toLowerCase())) return true;

  const instrumentType = valueText(asset, [
    'instrument_type', 'instrumentType', 'asset_type', 'assetType', 'security_type',
    'securityType', 'product_type', 'productType', 'asset_class', 'assetClass',
  ]).toUpperCase();
  // An option/future/event may have an underlying security name containing
  // “ETF”; that does not make the contract itself an ETF holding.
  if (/(?:OPTION|FUTURE|EVENT|CONTRACT)/.test(instrumentType)) return false;

  const metadata = valueText(asset, [
    'instrument_type', 'instrumentType', 'asset_type', 'assetType', 'security_type',
    'securityType', 'product_type', 'productType', 'security_sub_type',
    'securitySubType', 'instrument_category', 'instrumentCategory', 'asset_class',
    'assetClass', 'display_name', 'displayName', 'security_name', 'securityName',
    'asset_name', 'assetName', 'name',
  ]).toUpperCase();
  if (/(?:^|[\s_\-/])ETF(?:$|[\s_\-/])/.test(metadata)
    || metadata.includes('EXCHANGE TRADED FUND')) return true;

  // Webull currently reports its Ethereum ETF as an EQUITY row with ticker
  // ETH and no ETF flag. Apply the same provider-specific normalization used
  // by the backend for legacy/API responses.
  const source = String(asset.source || asset.origin || asset.provider || asset.exchange || '').trim().toLowerCase();
  const symbol = String(asset.symbol || asset.ticker || asset.asset || '').trim().toUpperCase();
  return source === 'webull' && symbol === 'ETH' && /(?:^|[\s_\-/])(EQUITY|STOCK|ETF)(?:$|[\s_\-/])/.test(instrumentType);
};

export const isCashOrStableAsset = (assetOrSymbol = {}) => {
  const asset = typeof assetOrSymbol === 'string' ? { symbol: assetOrSymbol } : (assetOrSymbol || {});
  const symbol = String(asset.symbol || asset.ticker || asset.asset || '').trim().toUpperCase();
  const type = valueText(asset, [
    'instrument_type', 'instrumentType', 'asset_type', 'assetType', 'security_type',
    'securityType', 'product_type', 'productType', 'asset_class', 'assetClass',
  ]).toUpperCase();
  return STABLE_SYMBOLS.has(symbol)
    || /(?:^|[\s_\-/])(CASH|FIAT|STABLECOIN|STABLE COIN|MONEY MARKET)(?:$|[\s_\-/])/.test(type);
};

const rawSymbolFor = (asset = {}) => String(
  asset.display_symbol || asset.displaySymbol || asset.symbol || asset.ticker || asset.asset || '—'
).trim();

export const getAssetDisplaySymbol = (assetOrSymbol = {}) => {
  const asset = typeof assetOrSymbol === 'string' ? { symbol: assetOrSymbol } : (assetOrSymbol || {});
  const raw = rawSymbolFor(asset);
  if (!raw || raw === '—') return '—';
  if (/\sETF$/i.test(raw)) return raw;
  return isEtfAsset(asset) ? `${raw.toUpperCase()} ETF` : raw.toUpperCase();
};

export const getAssetIdentity = (assetOrSymbol = {}) => {
  const asset = typeof assetOrSymbol === 'string' ? { symbol: assetOrSymbol } : (assetOrSymbol || {});
  const symbol = String(asset.symbol || asset.ticker || asset.asset || '').trim().toUpperCase() || 'UNKNOWN';
  const source = String(asset.source || asset.origin || asset.provider || asset.exchange || '').trim().toLowerCase() || 'unknown';
  const instrumentId = String(
    asset.instrument_id || asset.instrumentId || asset.webull_position_id || asset.webullPositionId
      || asset.security_id || asset.securityId || asset.contract_id || asset.contractId || ''
  ).trim().toUpperCase();
  const kind = isEtfAsset(asset)
    ? 'ETF'
    : String(asset.instrument_type || asset.instrumentType || asset.asset_type || asset.assetType || asset.asset_class || asset.assetClass || 'ASSET').trim().toUpperCase();
  return `${source}:${kind}:${instrumentId || symbol}`;
};

export const getAssetLabel = getAssetDisplaySymbol;
