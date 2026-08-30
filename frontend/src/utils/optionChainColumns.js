import { buildOptionStrategyLegs } from './optionStrategies';

export const OPTION_COLUMN_GROUPS = Object.freeze([
  {
    id: 'quote',
    label: 'Quote',
    items: [
      ['bid', 'Bid'], ['ask', 'Ask'], ['last', 'Last'], ['volume', 'Volume'],
      ['mid', 'Mid'], ['open_interest', 'Open Int'], ['bid_size', 'Bid Size'],
      ['ask_size', 'Ask Size'], ['change', 'Change'], ['percent_change', '% Change'],
      ['open', 'Open'], ['high', 'High'], ['low', 'Low'],
      ['change_open', 'Change (Open)'], ['percent_change_open', '% Change (Open)'],
    ],
  },
  {
    id: 'greeks',
    label: 'Greeks',
    items: [['delta', 'Delta'], ['gamma', 'Gamma'], ['theta', 'Theta'], ['vega', 'Vega'], ['rho', 'Rho']],
  },
  {
    id: 'analysis',
    label: 'Analysis',
    items: [
      ['implied_volatility', 'Impl Vol'], ['breakeven', 'Breakeven'],
      ['itm_percent', 'ITM Percent'], ['otm_percent', 'OTM Percent'],
      ['to_bep_percent', 'TO BEP %'], ['intrinsic_value', 'Intrinsic Value'],
      ['time_value', 'Time Value'], ['iv_percentile', 'IV Percentile'],
      ['iv_5_day_change', 'IV Five-Day Change'],
    ],
  },
].map((group) => ({ ...group, items: group.items.map(([id, label]) => ({ id, label })) })));

export const OPTION_COLUMNS = Object.freeze(
  Object.fromEntries(OPTION_COLUMN_GROUPS.flatMap((group) => group.items).map((item) => [item.id, item])),
);

export const FOCUS_OPTIONS = Object.freeze([
  { id: 'price', label: 'Price Change Focus' },
  { id: 'greeks', label: 'Greeks Focus' },
  { id: 'volatility', label: 'Volatility Focus' },
]);

export const DEFAULT_FOCUS_COLUMNS = Object.freeze({
  price: ['bid', 'ask', 'last', 'volume', 'mid', 'open_interest', 'change', 'percent_change', 'delta', 'theta', 'itm_percent'],
  greeks: ['volume', 'open_interest', 'delta', 'gamma', 'theta', 'vega', 'rho', 'implied_volatility', 'breakeven', 'to_bep_percent'],
  volatility: ['vega', 'implied_volatility', 'iv_percentile', 'iv_5_day_change'],
});

export const OPTION_FOCUS_STORAGE_KEY = 'webull_option_focus_columns_v1';

export function loadFocusColumns() {
  if (typeof window === 'undefined') return { ...DEFAULT_FOCUS_COLUMNS };
  try {
    const saved = JSON.parse(window.localStorage.getItem(OPTION_FOCUS_STORAGE_KEY) || '{}');
    const valid = new Set(Object.keys(OPTION_COLUMNS));
    return Object.fromEntries(FOCUS_OPTIONS.map(({ id }) => {
      const values = Array.isArray(saved[id]) ? saved[id].filter((item) => valid.has(item)) : [];
      return [id, values.length ? values : [...DEFAULT_FOCUS_COLUMNS[id]]];
    }));
  } catch {
    return { ...DEFAULT_FOCUS_COLUMNS };
  }
}

export function saveFocusColumns(profiles) {
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(OPTION_FOCUS_STORAGE_KEY, JSON.stringify(profiles));
  }
}

const finite = (value) => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));

export function formatOptionMetric(id, value) {
  if (!finite(value)) return '—';
  const number = Number(value);
  if (['volume', 'open_interest', 'bid_size', 'ask_size'].includes(id)) return Math.round(number).toLocaleString();
  if (['percent_change', 'percent_change_open', 'implied_volatility', 'itm_percent', 'otm_percent', 'to_bep_percent', 'iv_percentile', 'iv_5_day_change'].includes(id)) {
    return `${number.toFixed(2)}%`;
  }
  if (['delta', 'gamma', 'theta', 'vega', 'rho'].includes(id)) return number.toFixed(4);
  return `$${number.toFixed(2)}`;
}

const contractForLeg = (leg, currentRows, nextRows, expiration) => {
  if (leg.instrument_type === 'EQUITY') return null;
  const rows = leg.option_expire_date === expiration ? currentRows : nextRows;
  const row = rows.find((item) => Number(item.strike) === Number(leg.strike_price));
  return leg.option_type === 'CALL' ? row?.call : row?.put;
};

const sumIfComplete = (resolved, field, underlyingPrice) => {
  let total = 0;
  for (const { leg, contract } of resolved) {
    const sign = leg.side === 'BUY' ? 1 : -1;
    if (leg.instrument_type === 'EQUITY') {
      if (field === 'delta') total += sign * Number(leg.quantity || 0);
      else if (['gamma', 'theta', 'vega', 'rho'].includes(field)) total += 0;
      else if (['bid', 'ask', 'last', 'mid', 'open', 'high', 'low', 'previous_close'].includes(field)) total += sign * Number(leg.quantity || 0) * underlyingPrice;
      continue;
    }
    if (!finite(contract?.[field])) return null;
    total += sign * Number(leg.quantity || 1) * Number(contract[field]);
  }
  return total;
};

const executionQuote = (resolved, side, underlyingPrice) => {
  let total = 0;
  for (const { leg, contract } of resolved) {
    const sign = leg.side === 'BUY' ? 1 : -1;
    if (leg.instrument_type === 'EQUITY') {
      total += sign * Number(leg.quantity || 0) * underlyingPrice;
      continue;
    }
    const field = side === 'bid'
      ? (leg.side === 'BUY' ? 'bid' : 'ask')
      : (leg.side === 'BUY' ? 'ask' : 'bid');
    if (!finite(contract?.[field])) return null;
    total += sign * Number(leg.quantity || 1) * Number(contract[field]);
  }
  return total;
};

export function buildStrategyMetrics({ strategy, chainRows, nextRows, row, optionType, width, expiration, expirations, underlyingPrice }) {
  const contract = optionType === 'CALL' ? row?.call : row?.put;
  if (!contract || strategy === 'SINGLE') return contract;
  try {
    const legs = buildOptionStrategyLegs({
      strategy,
      chainRows,
      nextChainRows: nextRows,
      anchorStrike: row.strike,
      optionType,
      side: 'BUY',
      width: width === 'auto' ? 1 : width,
      expiration,
      expirations,
    });
    const resolved = legs.map((leg) => ({ leg, contract: contractForLeg(leg, chainRows, nextRows, expiration) }));
    if (resolved.some(({ leg, contract: item }) => leg.instrument_type !== 'EQUITY' && !item)) return null;

    const result = { strategy_legs: legs, metric_scope: 'strategy' };
    result.bid = executionQuote(resolved, 'bid', underlyingPrice);
    result.ask = executionQuote(resolved, 'ask', underlyingPrice);
    ['last', 'mid', 'open', 'high', 'low', 'previous_close', 'change', 'change_open', 'delta', 'gamma', 'theta', 'vega', 'rho', 'intrinsic_value', 'time_value']
      .forEach((field) => { result[field] = sumIfComplete(resolved, field, underlyingPrice); });

    const optionContracts = resolved.filter(({ leg }) => leg.instrument_type === 'OPTION');
    ['volume', 'open_interest', 'bid_size', 'ask_size'].forEach((field) => {
      const values = optionContracts.map(({ contract: item }) => item?.[field]).filter(finite).map(Number);
      result[field] = values.length === optionContracts.length ? Math.min(...values) : null;
    });
    ['implied_volatility', 'itm_percent', 'otm_percent', 'iv_percentile', 'iv_5_day_change'].forEach((field) => {
      const values = optionContracts.map(({ contract: item, leg }) => ({ value: item?.[field], weight: Number(leg.quantity || 1) }));
      result[field] = values.every(({ value }) => finite(value))
        ? values.reduce((sum, item) => sum + Number(item.value) * item.weight, 0) / values.reduce((sum, item) => sum + item.weight, 0)
        : null;
    });
    result.percent_change = finite(result.last) && finite(result.previous_close) && Number(result.previous_close) !== 0
      ? ((Number(result.last) - Number(result.previous_close)) / Math.abs(Number(result.previous_close))) * 100 : null;
    result.percent_change_open = finite(result.last) && finite(result.open) && Number(result.open) !== 0
      ? ((Number(result.last) - Number(result.open)) / Math.abs(Number(result.open))) * 100 : null;
    // Multi-leg positions may have zero, one, or several break-even points.
    // Do not display an invented single number in a column with singular meaning.
    result.breakeven = null;
    result.to_bep_percent = null;
    result.analysis_note = 'Multi-leg break-even depends on the full payoff and may contain multiple points.';
    return result;
  } catch (error) {
    return { strategy_error: error.message };
  }
}

export function optionMetricTitle(id, metrics) {
  if (metrics?.strategy_error) return metrics.strategy_error;
  if (!finite(metrics?.[id])) {
    if (metrics?.metric_scope === 'strategy' && ['breakeven', 'to_bep_percent'].includes(id)) return metrics.analysis_note;
    if (['iv_percentile', 'iv_5_day_change'].includes(id)) return 'Unavailable because the provider did not return the required historical volatility statistic.';
    return 'This value was not returned by the market-data provider.';
  }
  if (id === 'itm_percent' && metrics?.itm_percent_source === 'delta_proxy') return 'Estimated from absolute delta because Webull did not return its dedicated theoretical ITM probability.';
  if (metrics?.metric_scope === 'strategy' && ['volume', 'open_interest', 'bid_size', 'ask_size'].includes(id)) return 'Strategy liquidity uses the least-liquid option leg.';
  if (metrics?.metric_scope === 'strategy' && ['implied_volatility', 'itm_percent', 'otm_percent', 'iv_percentile', 'iv_5_day_change'].includes(id)) return 'Quantity-weighted average across the option legs.';
  return '';
}
