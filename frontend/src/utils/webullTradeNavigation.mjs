const NON_TRADABLE_CASH_SYMBOLS = new Set([
  'USD', 'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP', 'EURC', 'PYUSD',
]);

const assetType = (asset = {}) => String(
  asset.instrument_type
  || asset.instrumentType
  || asset.asset_type
  || asset.assetType
  || asset.security_type
  || asset.securityType
  || ''
).trim().toUpperCase();

export const isNonTradableWebullCashAsset = (asset = {}) => {
  const symbol = String(asset.symbol || asset.ticker || asset.asset || '').trim().toUpperCase();
  const type = assetType(asset);
  const isCrypto = /crypto|coin|token/i.test(type);
  return symbol === 'USD'
    || (NON_TRADABLE_CASH_SYMBOLS.has(symbol) && !isCrypto)
    || /(?:^|[\s_\-/])(CASH|FIAT|STABLECOIN|STABLE COIN|MONEY MARKET)(?:$|[\s_\-/])/.test(type);
};

export const webullInstrumentTypeForAsset = (asset = {}) => {
  if (isNonTradableWebullCashAsset(asset)) return null;
  const type = assetType(asset);
  if (type === 'OPTION' || type === 'OPTIONS') return 'OPTION';
  if (type === 'FUTURE' || type === 'FUTURES') return 'FUTURES';
  if (type === 'EVENT' || type === 'EVENT_CONTRACT') return 'EVENT';
  if (/crypto|coin|token/i.test(type)) return 'CRYPTO';
  return 'EQUITY';
};

export const normalizeWebullTradeSymbol = (symbol, instrumentType = null) => {
  const normalized = String(symbol || '').trim().toUpperCase();
  if (!/^[A-Z0-9.\-_]{1,80}$/.test(normalized)) return '';
  if (normalized === 'USD' || (instrumentType !== 'CRYPTO' && NON_TRADABLE_CASH_SYMBOLS.has(normalized))) return '';
  return normalized;
};

export const webullTradeTargetForAsset = (asset = {}) => {
  const instrumentType = webullInstrumentTypeForAsset(asset);
  const symbol = normalizeWebullTradeSymbol(asset.symbol || asset.ticker || asset.asset, instrumentType);
  return instrumentType && symbol ? { symbol, instrumentType } : null;
};
