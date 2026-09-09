const ROUNDING_EPSILON = 1e-8;

export const floorQuantityForTicket = (value, precision) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return '';
  const scale = 10 ** precision;
  const floored = Math.floor((numeric + ROUNDING_EPSILON) * scale) / scale;
  return floored > 0 ? floored.toFixed(precision).replace(/\.?0+$/, '') : '';
};

export const floorCashAmountForTicket = (value) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return 0;
  return Math.floor((numeric + ROUNDING_EPSILON) * 100) / 100;
};

export const quantityDecimalPlaces = (value) => {
  const text = String(value ?? '').trim();
  const decimal = text.indexOf('.');
  return decimal < 0 ? 0 : text.length - decimal - 1;
};

export const shouldUseEquityCashAmount = ({
  instrumentType,
  side,
  orderType,
  tradingSession,
  isAlgoEnabled,
  isBracketEnabled,
  dollars,
  rawQuantity,
}) => (
  instrumentType === 'EQUITY'
  && side === 'BUY'
  && orderType === 'MARKET'
  && tradingSession === 'CORE'
  && !isAlgoEnabled
  && !isBracketEnabled
  && dollars >= 5
  && rawQuantity > 0
  && rawQuantity < 1
);
