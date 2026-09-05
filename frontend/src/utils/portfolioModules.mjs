export const MODULES = ['equities', 'options', 'crypto', 'futures', 'events'];
export const DEFAULT_WEIGHTS = { equities: 35, options: 25, crypto: 20, futures: 10, events: 10 };
export const moduleEnabled = (settings, key) => settings?.[key]?.enabled ?? key !== 'futures';
const positive = value => Number.isFinite(Number(value)) && Number(value) > 0 ? Number(value) : 0;
const preferences = settings => Object.fromEntries(MODULES.map(key =>
  [key, positive(settings?.[key]?.allocation_preference) || DEFAULT_WEIGHTS[key]]));

// Largest-remainder rounding keeps the displayed percentages at exactly 100.00.
export function normalizeAllocations(weights = DEFAULT_WEIGHTS, settings = {}) {
  const active = MODULES.filter(key => moduleEnabled(settings, key));
  const result = Object.fromEntries(MODULES.map(key => [key, 0]));
  if (!active.length) return result;
  let source = weights;
  let sum = active.reduce((total, key) => total + positive(source[key]), 0);
  if (!sum) {
    source = preferences(settings);
    sum = active.reduce((total, key) => total + source[key], 0);
  }
  const parts = active.map(key => {
    const quota = positive(source[key]) / sum * 10000;
    return { key, units: Math.floor(quota + 1e-8), fraction: quota - Math.floor(quota + 1e-8) };
  });
  let remainder = 10000 - parts.reduce((total, part) => total + part.units, 0);
  const ranked = [...parts].sort((a, b) => b.fraction - a.fraction || MODULES.indexOf(a.key) - MODULES.indexOf(b.key));
  for (let i = 0; i < remainder; i++) ranked[i].units += 1;
  for (const part of parts) result[part.key] = part.units / 100;
  return result;
}

export function toggleModule(config, key, enabled) {
  const module_settings = { ...config.module_settings,
    [key]: { ...config.module_settings?.[key], enabled } };
  const allocation_weights = { ...(config.allocation_weights || config.allocations || DEFAULT_WEIGHTS) };
  return { ...config, module_settings, allocation_weights,
    allocations: normalizeAllocations(allocation_weights, module_settings) };
}

export function changeAllocation(config, key, value) {
  const active = MODULES.filter(module => moduleEnabled(config.module_settings, module));
  if (!active.includes(key) || active.length < 2 || !Number.isFinite(Number(value))) return config;
  const selected = Math.round(Math.max(0, Math.min(100, Number(value))) * 100) / 100;
  const weights = { ...(config.allocation_weights || config.allocations || DEFAULT_WEIGHTS) };
  const memory = preferences(config.module_settings);
  for (const module of MODULES) memory[module] = positive(weights[module]) || memory[module];
  let activeTotal = active.reduce((total, module) => total + positive(weights[module]), 0);
  if (!activeTotal) {
    for (const module of active) weights[module] = memory[module];
    activeTotal = active.reduce((total, module) => total + weights[module], 0);
  }
  const others = active.filter(module => module !== key);
  let source = weights;
  let otherTotal = others.reduce((total, module) => total + positive(source[module]), 0);
  if (!otherTotal) {
    source = memory;
    otherTotal = others.reduce((total, module) => total + source[module], 0);
  }
  const next = { ...weights, [key]: activeTotal * selected / 100 };
  for (const module of others) next[module] = activeTotal * (100 - selected) / 100 * positive(source[module]) / otherTotal;
  // Scale the complete relative vector, including inactive preferences, without rounding it.
  const scale = 100 / MODULES.reduce((total, module) => total + positive(next[module]), 0);
  const module_settings = { ...config.module_settings };
  for (const module of MODULES) {
    next[module] = positive(next[module]) * scale;
    module_settings[module] = { ...config.module_settings?.[module],
      allocation_preference: next[module] > 0 ? next[module] : memory[module] * scale };
  }
  return { ...config, allocation_weights: next, module_settings,
    allocations: normalizeAllocations(next, module_settings) };
}

export function moduleStatusLabel(status) {
  return ({ DISABLED: 'Disabled', SUBSCRIPTION_REQUIRED: 'Subscription required',
    WARMING_UP: 'Warming up', READY: 'Ready', SCANNED: 'Ready',
    AWAITING_SCAN: 'Awaiting scan', IDLE: 'Idle', MARKET_CLOSED: 'Market closed',
    DATA_LIMITED: 'Data unavailable' })[status] || 'Awaiting scan';
}
