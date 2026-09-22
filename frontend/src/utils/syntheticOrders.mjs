export const orderKey = (order) => `${order.parentKind || (order.trail_type ? 'TRAILING' : 'LADDER')}:${order.id}`;
export const isWorking = (status) => ['ACTIVE', 'PARTIALLY_FILLED', 'SUBMITTED', 'CANCEL_PENDING', 'TRIGGERED'].includes(status);
export const strategyKind = (order) => {
  if (order.parentKind === 'TRAILING' || order.trail_type) return 'TRAILING';
  if (order.downside_mode && order.downside_mode !== 'NONE') return 'BRACKET';
  return order.upside_mode === 'TRAILING' ? 'TRAILING' : order.upside_mode === 'SINGLE' ? 'SINGLE' : 'LADDER';
};
export const number = (value) => value === null || value === undefined || value === '' || !Number.isFinite(Number(value))
  ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: 12 });
export const money = (value, currency = 'USD') => value === null || value === undefined || !Number.isFinite(Number(value)) ? '—' : `${['USD', 'USDT'].includes(currency) ? Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : number(value)} ${currency}`;
export const priceInput = (value, currency = 'USD') => value === '' || value == null || !Number.isFinite(Number(value)) ? '' : Number(value).toFixed(['USD', 'USDT'].includes(currency) ? 2 : 12);
export const timestamp = (value) => value ? new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).toLocaleString() : '—';
export const trailLabel = (value, type, currency = 'USD') => type === 'AMOUNT' ? money(value, currency) : `${number(value)}%`;
export const quoteCurrency = (order) => order.broker === 'webull' ? 'USD' : ['USDT', 'USDC', 'USD', 'BTC', 'ETH', 'BNB'].find(q => order.symbol?.endsWith(q)) || 'quote';
export function matchesStatus(order, filter) {
  if (filter === 'ALL') return true;
  if (filter === 'ACTIVE') return isWorking(order.status);
  if (filter === 'COMPLETED') return ['FILLED', 'COMPLETED', 'STOPPED_OUT'].includes(order.status);
  return order.status === filter;
}

export function normalizeSyntheticQuantity(value, step) {
  const qty = Number(value);
  if (!Number.isFinite(qty) || qty <= 0 || qty > 1e12) return 0;
  if (!(Number(step) > 0)) return qty;
  const units = v => BigInt(Number(v).toFixed(12).replace('.', ''));
  const increment = units(step);
  return increment > 0n ? Number(units(qty) / increment * increment) / 1e12 : qty;
}

export function executionEstimate(quantity, price, side, fees) {
  const rates = fees?.rates?.[side];
  const rate = rates?.taker ?? fees?.takerRate;
  const known = typeof rate === 'number' && Number.isFinite(rate) && rate >= 0;
  const gross = quantity * price;
  const fee = known ? gross * rate : null;
  const discount = fees?.bnb?.enabled !== false && known
    ? gross * ((rates?.standardTaker ?? rate) * (1 - (fees?.bnb?.discountFraction ?? 0)) + (rates?.otherTaker ?? 0)) : null;
  return { quantity, price, gross, rate: known ? rate : null, fee,
    net: known ? gross - fee : null, netQuantity: known ? quantity * (1 - rate) : null,
    bnbFee: discount, bnbNet: discount === null ? null : gross - discount };
}

export function buildSyntheticReview(config, { side = 'SELL', quantity = 0, currentPrice = 0, baseAsset = 'ASSET', quoteAsset = 'USD', fees = null, quantityStep } = {}) {
  const payload = buildSyntheticPayload(config);
  const step = quantityStep ?? fees?.quantityStep;
  const total = normalizeSyntheticQuantity(quantity, step);
  const market = Number(currentPrice) || 0;
  const sell = side === 'SELL';
  const branches = ['upside', 'downside'].map(prefix => {
    const mode = payload[`${prefix}_mode`];
    const label = prefix === 'upside' ? 'Upside strategy' : 'Downside strategy';
    const direction = (prefix === 'upside') === sell ? 'rises to or above' : 'falls to or below';
    let rows = [], explanation = '';
    if (mode === 'NONE') return { prefix, mode, label, explanation: 'Disabled. This side will not submit an order.', rows };
    if (mode === 'TRAILING') {
      const activation = payload[`${prefix}_activation_price`];
      const value = payload[`${prefix}_trail_value`];
      const kind = payload[`${prefix}_trail_type`];
      const pending = activation > 0 && (sell ? market < activation : market > activation);
      const anchor = pending ? activation : market;
      const stop = kind === 'AMOUNT' ? anchor + (sell ? -value : value) : anchor * (1 + (sell ? -value : value) / 100);
      explanation = `${activation ? `Activation requires the observed market price to ${sell ? 'reach or exceed' : 'reach or fall below'} ${money(activation, quoteAsset)}. ${pending ? 'It has not reached that hurdle yet.' : 'That hurdle is already satisfied at the current reference price.'}` : 'Activation is immediate when the strategy is created.'} `
        + `The ${sell ? 'highest' : 'lowest'} price means the ${sell ? 'maximum' : 'minimum'} price the server observes from activation onward, not an all-time or daily ${sell ? 'high' : 'low'}. `
        + `${pending ? 'If the first activating observation equals the hurdle' : 'Using the current reference price'}, the starting ${sell ? 'peak' : 'trough'} is ${money(anchor, quoteAsset)} and the trigger is ${money(stop, quoteAsset)}. `
        + `The trigger follows each new ${sell ? 'high' : 'low'} at ${trailLabel(value, kind, quoteAsset)} ${sell ? 'below' : 'above'} it. A price ${sell ? 'at or below' : 'at or above'} that trigger submits a market ${side.toLowerCase()} for the remaining quantity. `
        + `A later ${sell ? 'higher peak' : 'lower trough'} changes the trigger and proceeds. ${pending ? 'The first observed activating price can pass the hurdle, so this is a hurdle-price scenario.' : 'This is the current-price scenario, not a known future peak or fill.'}`;
      if (anchor > 0 && stop > 0) rows = [{ ...executionEstimate(total, stop, side, fees), name: 'Trailing trigger scenario', condition: `${sell ? 'Price ≤ peak' : 'Price ≥ trough'} ${sell ? '−' : '+'} ${trailLabel(value, kind, quoteAsset)}`, remaining: true }];
    } else if (mode === 'SINGLE') {
      const target = payload[`${prefix}_target_price`];
      const cancelOnly = prefix === 'downside' && payload.stop_loss_action === 'CANCEL_REMAINING';
      explanation = `When price ${direction} ${money(target, quoteAsset)}, ${cancelOnly ? 'cancel the unfilled strategy without placing a trade. Proceeds and trading fees for this cancellation are 0.00.' : `submit a market ${side.toLowerCase()} for the remaining quantity.`}`;
      if (!cancelOnly && target > 0) rows = [{ ...executionEstimate(total, target, side, fees), name: 'Single trigger', condition: `Price ${direction} ${money(target, quoteAsset)}`, remaining: true }];
    } else {
      let allocated = 0, cumulativeGross = 0, cumulativeFee = 0, cumulativeNet = 0;
      const rungs = prefix === 'upside' ? payload.custom_rungs : payload.downside_rungs;
      rows = rungs.map((rung, index) => {
        const rawQty = index === rungs.length - 1 ? total - allocated : total * rung.percentage_of_total / 100;
        const qty = Math.min(Math.max(0, total - allocated), normalizeSyntheticQuantity(Number(rawQty.toFixed(8)), step));
        allocated = Number((allocated + qty).toFixed(12));
        const target = rung.target_price || market * (1 + rung.price_offset_pct / 100);
        const estimate = executionEstimate(qty, target, side, fees);
        cumulativeGross += estimate.gross; cumulativeFee += estimate.fee ?? 0; cumulativeNet += estimate.net ?? 0;
        return { ...estimate, name: `Rung ${index + 1}`, condition: `Price ${direction} ${money(target, quoteAsset)}`,
          cumulativeGross, cumulativeFee: estimate.fee === null ? null : cumulativeFee, cumulativeNet: estimate.net === null ? null : cumulativeNet };
      });
      explanation = `Each rung submits a market ${side.toLowerCase()} when price ${direction} its trigger. Rung quantities are capped by the strategy's unfilled remainder. If a quote crosses several rungs, each qualifying step is processed after the previous execution is confirmed.`;
    }
    return { prefix, mode, label, explanation, rows };
  });
  return { side, baseAsset, quoteAsset, total, requested: Number(quantity), market, branches, fees, quantityStep: step };
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
