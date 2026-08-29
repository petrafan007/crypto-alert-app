const humanizeCode = (value, fallback = '—') => {
  if (value === undefined || value === null || String(value).trim() === '') return fallback;
  return String(value)
    .trim()
    .replace(/[_-]+/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
};

export const ORDER_TYPE_LABELS = Object.freeze({
  MARKET: 'Market',
  LIMIT: 'Limit',
  STOP_LOSS: 'Stop Loss',
  STOP_LOSS_LIMIT: 'Stop Loss Limit',
  TRAILING_STOP_LOSS: 'Trailing Stop',
  MARKET_ON_OPEN: 'Market on Open (MOO)',
  MARKET_ON_CLOSE: 'Market on Close (MOC)',
  LIMIT_ON_OPEN: 'Limit on Open (LOO)',
  LIMIT_MAKER: 'Limit Maker',
  TAKE_PROFIT: 'Take Profit',
  TAKE_PROFIT_LIMIT: 'Take Profit Limit',
  OCO: 'One Cancels the Other (OCO)',
  OTO: 'One Triggers the Other (OTO)',
  OTOCO: 'One Triggers OCO (OTOCO)',
  STAKING: 'Staking',
});

export const ORDER_SIDE_LABELS = Object.freeze({
  BUY: 'Buy',
  SELL: 'Sell',
  SHORT: 'Short',
  BUY_TO_OPEN: 'Buy to Open',
  BUY_TO_CLOSE: 'Buy to Close',
  SELL_TO_OPEN: 'Sell to Open',
  SELL_TO_CLOSE: 'Sell to Close',
});

export const ORDER_STATUS_LABELS = Object.freeze({
  NEW: 'New',
  OPEN: 'Open',
  WORKING: 'Working',
  PENDING: 'Pending',
  FILLED: 'Filled',
  PARTIALLY_FILLED: 'Partially Filled',
  COMPLETED: 'Completed',
  EXECUTED: 'Executed',
  CANCELLED: 'Cancelled',
  CANCELED: 'Cancelled',
  REJECTED: 'Rejected',
  EXPIRED: 'Expired',
});

export const COMBO_ROLE_LABELS = Object.freeze({
  MASTER: 'Primary Order',
  OTO: 'Triggered Order (OTO)',
  OCO: 'Linked Order (OCO)',
  OTOCO: 'Bracket Order (OTOCO)',
});

export const TIME_IN_FORCE_LABELS = Object.freeze({
  DAY: 'Day',
  GTC: "Good 'Til Canceled (GTC)",
  IOC: 'Immediate or Cancel (IOC)',
  FOK: 'Fill or Kill (FOK)',
});

const mappedLabel = (labels, value, fallback) => {
  const clean = String(value || '').trim().toUpperCase();
  return labels[clean] || humanizeCode(value, fallback);
};

export const formatOrderType = (value, fallback = '—') => mappedLabel(ORDER_TYPE_LABELS, value, fallback);
export const formatOrderSide = (value, fallback = '—') => mappedLabel(ORDER_SIDE_LABELS, value, fallback);
export const formatOrderStatus = (value, fallback = '—') => mappedLabel(ORDER_STATUS_LABELS, value, fallback);
export const formatComboRole = (value, fallback = '—') => mappedLabel(COMBO_ROLE_LABELS, value, fallback);
export const formatTimeInForce = (value, fallback = '—') => mappedLabel(TIME_IN_FORCE_LABELS, value, fallback);
