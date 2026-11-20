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

export const allocationPercentage = (usedAmount, availableAmount) => {
  const used = Number(usedAmount);
  const available = Number(availableAmount);
  if (!Number.isFinite(used) || !Number.isFinite(available) || used <= 0 || available <= 0) return 0;
  return Math.round(Math.max(0, Math.min(100, (used / available) * 100)) * 100) / 100;
};

export const MIXED_EQUITY_QUANTITY_MESSAGE = 'Webull OpenAPI accepts whole shares or a fractional Market order under one share. Enter whole shares for a Limit order.';

export const isMixedEquityQuantity = (quantity) => {
  const shares = Number(quantity);
  return Number.isFinite(shares) && shares > 1 && !Number.isInteger(shares);
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

export const accountLabel = (account, fallbackId = '') => {
  const name = account?.account_label || account?.account_name || 'Webull Account';
  const id = account?.account_id_masked || (account?.account_id ? `••••${String(account.account_id).slice(-4)}` : (fallbackId ? `••••${String(fallbackId).slice(-4)}` : ''));
  return id ? `${name} (${id})` : name;
};

export const sanitizeTotpCode = (value) => String(value ?? '')
  .replace(/\D/g, '')
  .slice(0, 6);

export const formatBufferPercent = (value, defaultPct = 3.00) => {
  const num = parseFloat(value);
  if (!Number.isFinite(num) || num < 0) return defaultPct.toFixed(2);
  return num.toFixed(2);
};

export const formatQuantityForTicket = (value, precision = 6) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return '';
  return numeric.toFixed(precision).replace(/\.?0+$/, '');
};

export const generatedQuantityForTicket = (instrumentType, value) => {
  if (instrumentType === 'EQUITY' || instrumentType === 'EVENT') {
    return floorQuantityForTicket(value, 5);
  }
  return formatQuantityForTicket(value, 6);
};

// State math for the ticket's Order Value ($) field. The typed text is
// kept verbatim in quoteQuantity and the entry NEVER changes the entrust
// mode: the cash conversion is decided on the completed value when the
// field loses focus (quoteBlurCashAmount). Switching modes mid-typing
// swaps the rendered input element and swallows keystrokes — typing
// "500" used to arrive as "50", because the partial value "5" already
// satisfied the sub-share cash gate and flipped the ticket to the
// cash-amount input.
export const quoteValueEntry = ({ rawValue, instrumentType, price, fractionalQuantityAllowed }) => {
  const quoteVal = String(rawValue ?? '').replace(/[^0-9.]/g, '');
  const numQuote = parseFloat(quoteVal) || 0;
  const mult = instrumentType === 'OPTION' ? 100 : 1;
  const unitCost = Number(price) * mult;
  const rawQuantity = numQuote > 0 && unitCost > 0 ? numQuote / unitCost : 0;
  const wholeQuantity = Math.floor(rawQuantity);
  const computedQty = (fractionalQuantityAllowed || instrumentType === 'EQUITY')
    ? generatedQuantityForTicket(instrumentType, rawQuantity)
    : wholeQuantity > 0 ? String(wholeQuantity) : '';
  return { quoteVal, numQuote, rawQuantity, computedQty };
};

// On blur, a completed sub-share dollar entry converts to Webull's
// cash-amount mode, carrying the typed text exactly as entered. Returns
// null when the entry stays a shares entry.
export const quoteBlurCashAmount = ({
  quoteQuantity,
  instrumentType,
  side,
  orderType,
  tradingSession,
  isAlgoEnabled,
  isBracketEnabled,
  price,
}) => {
  const text = String(quoteQuantity ?? '');
  const dollars = parseFloat(text.replace(/[^0-9.]/g, '')) || 0;
  const unitPrice = Number(price);
  const rawQuantity = dollars > 0 && unitPrice > 0 ? dollars / unitPrice : 0;
  return shouldUseEquityCashAmount({
    instrumentType,
    side,
    orderType,
    tradingSession,
    isAlgoEnabled,
    isBracketEnabled,
    dollars,
    rawQuantity,
  }) ? text : null;
};

// Manual switch to cash-amount mode: any value the user already typed
// wins; the default applies only when nothing was entered.
export const cashAmountCarry = ({ totalCashAmount, quoteQuantity }) => (
  totalCashAmount || quoteQuantity || '25.00'
);
