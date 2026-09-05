export const MODULES = ['equities', 'options', 'crypto', 'futures', 'events'];

export function reallocateEnabled(allocations, settings) {
  const keys = MODULES.filter(key => settings?.[key]?.enabled ?? key !== 'futures');
  if (!keys.length) throw new Error('Enable at least one module before reallocating.');
  const weights = Object.fromEntries(keys.map(key => [key, Number(allocations[key] ?? 0)]));
  if (Object.values(weights).some(n => !Number.isFinite(n) || n < 0)) throw new Error('Enter valid allocations before reallocating.');
  const sum = keys.reduce((n, key) => n + weights[key], 0);
  const next = Object.fromEntries(MODULES.map(key => [key, 0]));
  let remaining = 10000;
  keys.forEach((key, index) => {
    const cents = index === keys.length - 1 ? remaining : Math.floor(sum ? weights[key] / sum * 10000 : 10000 / keys.length);
    next[key] = cents / 100;
    remaining -= cents;
  });
  return next;
}

export function moduleStatusLabel(status) {
  return ({ DISABLED: 'Disabled', SUBSCRIPTION_REQUIRED: 'Subscription required',
    WARMING_UP: 'Warming up', READY: 'Ready', SCANNED: 'Ready',
    AWAITING_SCAN: 'Awaiting scan', IDLE: 'Idle', MARKET_CLOSED: 'Market closed',
    DATA_LIMITED: 'Data unavailable' })[status] || 'Awaiting scan';
}
