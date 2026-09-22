export const orderKey = (order) => `${order.parentKind || (order.trail_type ? 'TRAILING' : 'LADDER')}:${order.id}`;
export const isWorking = (status) => ['ACTIVE', 'PARTIALLY_FILLED', 'SUBMITTED', 'CANCEL_PENDING', 'TRIGGERED'].includes(status);
export const strategyKind = (order) => {
  if (order.parentKind === 'TRAILING' || order.trail_type) return 'TRAILING';
  if (order.downside_mode && order.downside_mode !== 'NONE') return 'BRACKET';
  return order.upside_mode === 'TRAILING' ? 'TRAILING' : order.upside_mode === 'SINGLE' ? 'SINGLE' : 'LADDER';
};
export const number = (value) => value === null || value === undefined || value === '' || !Number.isFinite(Number(value))
  ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: 12 });
export const money = (value, currency = 'USD') => value === null || value === undefined ? '—' : `${number(value)} ${currency}`;
export const timestamp = (value) => value ? new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).toLocaleString() : '—';
export const trailLabel = (value, type, currency = 'USD') => type === 'AMOUNT' ? money(value, currency) : `${number(value)}%`;
export const quoteCurrency = (order) => order.broker === 'webull' ? 'USD' : ['USDT', 'USDC', 'USD', 'BTC', 'ETH', 'BNB'].find(q => order.symbol?.endsWith(q)) || 'quote';
export function matchesStatus(order, filter) {
  if (filter === 'ALL') return true;
  if (filter === 'ACTIVE') return isWorking(order.status);
  if (filter === 'COMPLETED') return ['FILLED', 'COMPLETED', 'STOPPED_OUT'].includes(order.status);
  return order.status === filter;
}
export function buildSyntheticPayload(config) {
  const numeric = value => value === '' || value === null || value === undefined ? null : Number(value);
  const rungs = rows => (rows || []).map(r => ({ price_offset_pct: Number(r.price_offset_pct), percentage_of_total: Number(r.percentage_of_total), target_price: numeric(r.target_price) }));
  const protectedOrder = config.hasDownsideProtection ?? config.hasStopLoss ?? false;
  return {
    strategy_type: protectedOrder ? 'BRACKET' : config.upsideMode === 'TRAILING' ? 'TRAILING' : 'LADDER',
    upside_mode: config.upsideMode || 'LADDER', upside_target_price: numeric(config.upsideTargetPrice),
    upside_trail_value: numeric(config.upsideTrailValue), upside_trail_type: config.upsideTrailType || 'PERCENT',
    upside_activation_price: numeric(config.upsideActivationPrice),
    preset_name: config.upsidePreset || config.preset || 'CONSERVATIVE',
    custom_rungs: rungs(config.upsideRungs || config.rungs),
    downside_mode: protectedOrder ? config.downsideMode || 'SINGLE' : 'NONE',
    downside_target_price: protectedOrder ? numeric(config.downsideTargetPrice) : null,
    downside_trail_value: numeric(config.downsideTrailValue), downside_trail_type: config.downsideTrailType || 'PERCENT',
    downside_activation_price: numeric(config.downsideActivationPrice), downside_preset: config.downsidePreset || 'MODERATE',
    downside_rungs: rungs(config.downsideRungs), has_stop_loss: protectedOrder,
    stop_loss_action: config.downsideStopAction || config.stopLossAction || 'MARKET_SELL_ALL',
  };
}
export function strategySummary(config, currency = 'USD') {
  const payload = buildSyntheticPayload(config);
  return ['upside', 'downside'].map(prefix => {
    const mode = payload[`${prefix}_mode`];
    const label = prefix === 'upside' ? 'Target' : 'Protection';
    if (mode === 'NONE') return `${label}: off`;
    if (mode === 'TRAILING') return `${label}: trail ${trailLabel(payload[`${prefix}_trail_value`], payload[`${prefix}_trail_type`], currency)}; activation ${payload[`${prefix}_activation_price`] ? money(payload[`${prefix}_activation_price`], currency) : 'immediate'}`;
    if (mode === 'SINGLE') return `${label}: ${money(payload[`${prefix}_target_price`], currency)}${prefix === 'downside' && payload.stop_loss_action === 'CANCEL_REMAINING' ? '; cancel remaining only' : ''}`;
    return `${label}: ${(prefix === 'upside' ? payload.custom_rungs : payload.downside_rungs).map(r => `${money(r.target_price, currency)} (${number(r.percentage_of_total)}%)`).join(', ')}`;
  });
}
