const DEFAULT_COLUMNS = [
  'symbol', 'asset_type', 'side', 'quantity', 'average_price', 'mark',
  'market_value', 'open_pnl', 'open_pnl_pct', 'status',
];

const COLUMN_DEFINITIONS = [
  { id: 'account', label: 'Account', type: 'text' },
  { id: 'side', label: 'Side / outcome', type: 'text' },
  { id: 'status', label: 'Status', type: 'text' },
  { id: 'cutoff', label: 'Trading cutoff', type: 'timestamp' },
  { id: 'countdown', label: 'Time to cutoff', type: 'countdown' },
  { id: 'confirmed_outcome', label: 'Confirmed result', type: 'text' },
  { id: 'contract_multiplier', label: 'Contract multiplier', type: 'number' },
  { id: 'symbol', label: 'Symbol / ticker', type: 'symbol', locked: true },
  { id: 'quantity', label: 'Quantity', type: 'number' },
  { id: 'available_quantity', label: 'Available quantity', type: 'number' },
  { id: 'market_value', label: 'Market value', type: 'currency' },
  { id: 'mark', label: 'Mark', type: 'currency' },
  { id: 'average_price', label: 'AVG Price', type: 'currency' },
  { id: 'last', label: 'Last', type: 'currency' },
  { id: 'day_pnl', label: '1D open P&L', type: 'pnl' },
  { id: 'day_pnl_pct', label: '1D open P&L %', type: 'pnl_percent' },
  { id: 'open_pnl', label: 'Open P&L', type: 'pnl' },
  { id: 'open_pnl_pct', label: 'Open P&L %', type: 'pnl_percent' },
  { id: 'bid', label: 'Bid', type: 'currency' },
  { id: 'ask', label: 'Ask', type: 'currency' },
  { id: 'bid_size', label: 'Bid size', type: 'number' },
  { id: 'ask_size', label: 'Ask size', type: 'number' },
  { id: 'dte', label: 'Days to expiration', type: 'number' },
  { id: 'delta', label: 'Delta', type: 'decimal' },
  { id: 'gamma', label: 'Gamma', type: 'decimal' },
  { id: 'theta', label: 'Theta', type: 'decimal' },
  { id: 'vega', label: 'Vega', type: 'decimal' },
  { id: 'rho', label: 'Rho', type: 'decimal' },
  { id: 'implied_volatility', label: 'Implied volatility', type: 'volatility' },
  { id: 'underlying_symbol', label: 'Underlying', type: 'text' },
  { id: 'asset_type', label: 'Asset type', type: 'text' },
  { id: 'expiration_date', label: 'Expiration date', type: 'date' },
  { id: 'strike', label: 'Strike', type: 'currency' },
  { id: 'contract_type', label: 'Contract type', type: 'text' },
  { id: 'underlying_price', label: 'Underlying price', type: 'currency' },
  { id: 'iv_rank', label: 'IV rank', type: 'volatility' },
  { id: 'iv_52_week_high', label: 'IV 52 week high', type: 'volatility' },
  { id: 'iv_52_week_low', label: 'IV 52 week low', type: 'volatility' },
  { id: 'historical_volatility', label: 'Historical volatility', type: 'volatility' },
  { id: 'days_to_last_trade', label: 'Days to last day to trade', type: 'number' },
  { id: 'last_trade_date', label: 'Last day to trade', type: 'date' },
  { id: 'settlement_type', label: 'Settlement type', type: 'text' },
];

const COLUMN_MAP = new Map(COLUMN_DEFINITIONS.map((column) => [column.id, column]));


function firstValue(position, ...keys) {
  for (const key of keys) {
    const value = position?.[key];
    if (value !== null && value !== undefined && value !== '') return value;
  }
  return null;
}

function numericValue(position, ...keys) {
  const value = firstValue(position, ...keys);
  if (value === null) return null;
  const parsed = Number(String(value).replace(/[,$%]/g, ''));
  return Number.isFinite(parsed) ? parsed : null;
}

function assetType(position) {
  const value = String(position?.instrument_type || position?.asset_type || 'Security').toUpperCase();
  if (value.includes('OPTION')) return 'Options';
  if (/CRYPTO|COIN|TOKEN/.test(value)) return 'Crypto';
  if (value.includes('FUTURE')) return 'Futures';
  if (/EQUITY|STOCK|ETF|SECURITY/.test(value)) return 'Equities & ETFs';
  if (value === 'CASH') return 'Cash';
  if (value.includes('EVENT')) return 'Event Contracts';
  return value.charAt(0) + value.slice(1).toLowerCase();
}

function optionExpiration(position) {
  return firstValue(position, 'option_expiration', 'expiration_date', 'expiry_date') ?? position.details?.expiration;
}

function daysToDate(value) {
  if (!value) return null;
  const target = new Date(`${String(value).slice(0, 10)}T12:00:00`);
  if (Number.isNaN(target.getTime())) return null;
  const today = new Date();
  const current = new Date(today.getFullYear(), today.getMonth(), today.getDate(), 12);
  return Math.max(0, Math.ceil((target.getTime() - current.getTime()) / 86400000));
}

function positionDte(position) {
  return numericValue(position, 'days_to_expiration', 'dte') ?? daysToDate(optionExpiration(position));
}

function valueForColumn(position, columnId) {
  switch (columnId) {
    case 'symbol': return String(position?.symbol || '—').toUpperCase();
    case 'account': return firstValue(position, 'account_label', 'account_name', 'webull_account_type', 'source_label') || '—';
    case 'side': return positionSide(position);
    case 'status': return positionStatus(position);
    case 'cutoff': return position.settlement?.cutoff_at || position.cutoff_at || position.details?.cutoff_at || null;
    case 'countdown': return timestamp(valueForColumn(position, 'cutoff'));
    case 'confirmed_outcome': return position.settlement?.confirmed_outcome || null;
    case 'contract_multiplier': return numericValue(position, 'contract_multiplier', 'option_multiplier') ?? position.details?.multiplier ?? null;
    case 'quantity': return numericValue(position, 'quantity', 'amount');
    case 'available_quantity': return numericValue(position, 'available_quantity');
    case 'market_value': return numericValue(position, 'current_value', 'market_value', 'market_value_usd');
    case 'mark': return numericValue(position, 'mark', 'mark_price', 'current_price', 'last_price');
    case 'average_price': return numericValue(position, 'average_price', 'avg_entry', 'cost_price');
    case 'last': return numericValue(position, 'last_price', 'current_price');
    case 'day_pnl': return numericValue(position, 'day_profit_loss', 'day_pnl', 'today_profit_loss', 'todays_return');
    case 'day_pnl_pct': return numericValue(position, 'day_profit_loss_rate', 'day_pnl_pct', 'today_profit_loss_rate', 'todays_return_pct');
    case 'open_pnl': return numericValue(position, 'webull_unrealized_pnl', 'unrealized_profit_loss', 'unrealized_pnl', 'unrealized_gain');
    case 'open_pnl_pct': {
      const explicit = numericValue(position, 'unrealized_profit_loss_rate', 'open_pnl_pct', 'pct_change');
      if (explicit !== null) return explicit;
      const cost = numericValue(position, 'cost_basis', 'collateral');
      const pnl = valueForColumn(position, 'open_pnl');
      return cost > 0 && pnl !== null ? pnl / cost * 100 : null;
    }
    case 'bid': return numericValue(position, 'bid', 'bid_price');
    case 'ask': return numericValue(position, 'ask', 'ask_price');
    case 'bid_size': return numericValue(position, 'bid_size', 'bidSize');
    case 'ask_size': return numericValue(position, 'ask_size', 'askSize');
    case 'dte': return positionDte(position);
    case 'delta': return numericValue(position, 'delta');
    case 'gamma': return numericValue(position, 'gamma');
    case 'theta': return numericValue(position, 'theta');
    case 'vega': return numericValue(position, 'vega');
    case 'rho': return numericValue(position, 'rho');
    case 'implied_volatility': return numericValue(position, 'implied_volatility', 'iv');
    case 'underlying_symbol': return firstValue(position, 'underlying_symbol', 'underlying');
    case 'asset_type': return assetType(position);
    case 'expiration_date': return optionExpiration(position);
    case 'strike':
      if (position.details?.short && position.details?.long) return null;
      return numericValue(position, 'option_strike', 'strike_price', 'strike') ?? position.details?.strike ?? null;
    case 'contract_type': return firstValue(position, 'option_type', 'contract_type', 'put_call') ?? (position.details?.short ? `${position.details.short.option_type} credit spread` : position.details?.option_type);
    case 'underlying_price': return numericValue(position, 'underlying_price');
    case 'iv_rank': return numericValue(position, 'iv_rank');
    case 'iv_52_week_high': return numericValue(position, 'iv_52_week_high', 'iv52_week_high');
    case 'iv_52_week_low': return numericValue(position, 'iv_52_week_low', 'iv52_week_low');
    case 'historical_volatility': return numericValue(position, 'historical_volatility');
    case 'days_to_last_trade': return numericValue(position, 'days_to_last_trade') ?? daysToDate(firstValue(position, 'last_trade_date'));
    case 'last_trade_date': return firstValue(position, 'last_trade_date');
    case 'settlement_type': return firstValue(position, 'settlement_type');
    default: return null;
  }
}

function formatNumber(value, maximumFractionDigits = 6) {
  if (value === null) return '—';
  return Number(value).toLocaleString('en-US', { maximumFractionDigits });
}

function formatCurrency(value) {
  if (value === null) return '—';
  const digits = Math.abs(value) < 1 ? 4 : 2;
  return Number(value).toLocaleString('en-US', {
    style: 'currency', currency: 'USD', minimumFractionDigits: digits, maximumFractionDigits: digits,
  });
}

function formatDate(value) {
  if (!value) return '—';
  const parsed = new Date(`${String(value).slice(0, 10)}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatVolatility(value) {
  if (value === null) return '—';
  const percent = Math.abs(value) <= 2 ? value * 100 : value;
  return `${percent.toFixed(2)}%`;
}

function formatCell(value, type) {
  if (value === null || value === undefined || value === '') return '—';
  if (type === 'timestamp') return formatTimestamp(value);
  if (type === 'countdown') return countdown(value);
  if (type === 'currency') return formatCurrency(value);
  if (type === 'number') return formatNumber(value);
  if (type === 'decimal') return Number(value).toFixed(4);
  if (type === 'volatility') return formatVolatility(value);
  if (type === 'date') return formatDate(value);
  return String(value);
}

function optionSymbol(position) {
  const symbol = String(position.symbol || position.underlying_symbol || '—').toUpperCase();
  if (assetType(position) !== 'Options') return symbol;
  const expiration = optionExpiration(position);
  if (position.details?.short && position.details?.long) return `${position.symbol} ${position.details.expiration} $${position.details.short.strike} / $${position.details.long.strike} ${position.details.short.option_type} spread`;
  const strike = valueForColumn(position, 'strike');
  const contractType = String(valueForColumn(position, 'contract_type') || '').toLowerCase();
  const dateLabel = expiration ? new Date(`${String(expiration).slice(0, 10)}T12:00:00`).toLocaleDateString('en-US', { month: 'numeric', day: 'numeric' }) : '';
  return [position.underlying_symbol || symbol, dateLabel, strike === null ? '' : `$${formatNumber(strike, 4)}`, contractType ? contractType.charAt(0).toUpperCase() + contractType.slice(1) : ''].filter(Boolean).join(' ');
}


export const ASSET_VIEWS = ['All assets', 'Equities & ETFs', 'Crypto', 'Options', 'Futures', 'Event Contracts'];
const VIEW_COLUMNS = {
  'Options': ['symbol', 'side', 'quantity', 'expiration_date', 'strike', 'contract_type', 'average_price', 'mark', 'market_value', 'open_pnl', 'open_pnl_pct', 'status'],
  'Futures': ['symbol', 'side', 'quantity', 'contract_multiplier', 'expiration_date', 'average_price', 'mark', 'market_value', 'open_pnl', 'status'],
  'Event Contracts': ['symbol', 'side', 'quantity', 'average_price', 'mark', 'market_value', 'open_pnl', 'open_pnl_pct', 'cutoff', 'countdown', 'status'],
};
const SPECIAL_COLUMNS = {
  'Options': ['dte', 'delta', 'gamma', 'theta', 'vega', 'rho', 'implied_volatility', 'strike', 'contract_type', 'underlying_price', 'iv_rank', 'iv_52_week_high', 'iv_52_week_low', 'historical_volatility'],
  'Futures': ['days_to_last_trade', 'last_trade_date', 'settlement_type'],
  'Event Contracts': ['cutoff', 'countdown', 'confirmed_outcome'],
};
export function availableColumns(view) {
  const excluded = view === 'All assets' ? [] : Object.entries(SPECIAL_COLUMNS).filter(([asset]) => asset !== view).flatMap(([, ids]) => ids);
  return COLUMN_DEFINITIONS.filter(column => !excluded.includes(column.id));
}
export function defaultColumnState(view, showAccount = false) {
  const selected = [...(VIEW_COLUMNS[view] || DEFAULT_COLUMNS)];
  if (showAccount) selected.splice(1, 0, 'account');
  return { selected, order: [...selected, ...availableColumns(view).map(c => c.id).filter(id => !selected.includes(id))], widths: {} };
}
export function cleanColumnState(saved, view, showAccount = false) {
  const defaults = defaultColumnState(view, showAccount);
  if (!Array.isArray(saved?.order) || !Array.isArray(saved?.selected)) return defaults;
  const valid = new Set(availableColumns(view).map(c => c.id));
  const order = [...new Set(saved.order.filter(id => valid.has(id)))];
  const selected = [...new Set(['symbol', ...saved.selected.filter(id => valid.has(id))])];
  const widths = Object.fromEntries(Object.entries(saved.widths || {}).flatMap(([id, width]) => {
    const numericWidth = Number(width);
    return valid.has(id) && Number.isFinite(numericWidth)
      ? [[id, Math.max(80, Math.min(800, Math.round(numericWidth)))]]
      : [];
  }));
  return { order: [...order, ...defaults.order.filter(id => !order.includes(id))], selected, widths };
}
export function moveColumnState(state, source, target) {
  if (source === target || !state.order.includes(source) || !state.order.includes(target)) return state;
  const order = [...state.order];
  const targetIndex = order.indexOf(target);
  order.splice(order.indexOf(source), 1);
  order.splice(targetIndex, 0, source);
  return { ...state, order };
}
export function resizeColumnState(state, id, width) {
  if (!state.order.includes(id) || !Number.isFinite(Number(width))) return state;
  return {
    ...state,
    widths: {
      ...(state.widths || {}),
      [id]: Math.max(80, Math.min(800, Math.round(Number(width)))),
    },
  };
}
export function columnStorageKey(userId, view) {
  return userId == null ? null : `positions-columns-v2:${encodeURIComponent(userId)}:${encodeURIComponent(view)}`;
}
export function cutoffFromSymbol(symbol) {
  if (!symbol) return null;
  const match = String(symbol).trim().toUpperCase().match(
    /-(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})(\d{2})(?:(\d{2}))?(?:-|$)/
  );
  if (!match) return null;
  const months = {
    JAN: '01', FEB: '02', MAR: '03', APR: '04', MAY: '05', JUN: '06',
    JUL: '07', AUG: '08', SEP: '09', OCT: '10', NOV: '11', DEC: '12',
  };
  const year = `20${match[1]}`;
  const month = months[match[2]];
  const day = match[3];
  const hour = match[4];
  const minute = match[5] || '00';
  if (!month) return null;

  const testIso = `${year}-${month}-${day}T${hour}:${minute}:00`;
  let offset = '-04:00';
  try {
    const probeDate = new Date(`${testIso}Z`);
    const tzStr = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', timeZoneName: 'short' }).format(probeDate);
    if (tzStr.includes('EST')) offset = '-05:00';
  } catch {
    offset = '-04:00';
  }
  const parsed = Date.parse(`${testIso}${offset}`);
  return Number.isFinite(parsed) ? parsed : null;
}
export function timestamp(value) {
  if (!value) return null;
  const text = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    let offset = '-04:00';
    try {
      const probe = new Date(`${text}T12:00:00Z`);
      const tzStr = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', timeZoneName: 'short' }).format(probe);
      if (tzStr.includes('EST')) offset = '-05:00';
    } catch {
      offset = '-04:00';
    }
    const endOfDay = Date.parse(`${text}T23:59:59${offset}`);
    return Number.isFinite(endOfDay) ? endOfDay : null;
  }
  const parsed = Date.parse(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(text) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(text) ? `${text}Z` : text);
  return Number.isFinite(parsed) ? parsed : null;
}
export function formatTimestamp(value) {
  const parsed = timestamp(value);
  return parsed === null ? '—' : new Date(parsed).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'numeric', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
}
export function countdown(value, now = Date.now()) {
  if (value === null) return '—';
  const seconds = Math.ceil((value - now) / 1000);
  if (seconds <= 0) return 'Closed';
  if (seconds >= 86400) return `${Math.floor(seconds / 86400)}d ${Math.floor(seconds % 86400 / 3600)}h`;
  if (seconds >= 3600) return `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}
export function positionSide(position) {
  if (assetType(position) === 'Event Contracts') {
    const outcome = firstValue(position, 'purchased_outcome', 'event_outcome', 'side', 'position_side')
      || position.details?.outcome
      || String(position.symbol || '').match(/[\s-](YES|NO)$/i)?.[1];
    return ['YES', 'NO'].includes(String(outcome).toUpperCase()) ? String(outcome).toUpperCase() : 'Unknown outcome';
  }
  return firstValue(position, 'position_side', 'side') || (numericValue(position, 'quantity', 'amount') < 0 ? 'SHORT' : 'LONG');
}
export function instrumentName(position) {
  if (assetType(position) === 'Event Contracts') return position.event_title || position.display_name || position.details?.title || position.symbol || '—';
  return assetType(position) === 'Options' ? optionSymbol(position) : position.display_name || position.display_symbol || position.symbol || '—';
}
export function positionStatus(position, now = Date.now()) {
  if (assetType(position) !== 'Event Contracts') return position.position_status || 'Open';
  const settlement = position.settlement || {};
  const status = String(settlement.status || '').toUpperCase();
  if (status === 'RESOLVED') return 'Settled — awaiting removal';
  if (['DELAYED', 'ERROR', 'FAILED'].includes(status)) return 'Settlement delayed';
  const cutoff = cutoffFromSymbol(position.symbol) || timestamp(settlement.cutoff_at || position.cutoff_at || position.details?.cutoff_at);
  if (cutoff !== null && cutoff > now) return 'Active';
  if (cutoff !== null && cutoff <= now) {
    const expected = timestamp(settlement.expected_at);
    return expected !== null && expected < now ? 'Settlement delayed' : 'Awaiting settlement';
  }
  return 'Status unavailable';
}
export { COLUMN_DEFINITIONS, COLUMN_MAP, assetType, valueForColumn, formatCell, formatCurrency, optionSymbol };

export function normalizeRealPositions(rows) {
  return rows.filter(p => !p.is_paper && !p.is_quant && !['webull_quant', 'webull_test'].includes(p.source)).map(p => {
    const webull = p.source === 'webull';
    return {
      ...p,
      instrument_type: p.instrument_type || (webull ? 'EQUITY' : 'CRYPTO'),
      source: webull ? 'webull' : 'binance',
      account_id: webull ? p.account_id : 'binance',
      account_label: webull ? [p.webull_account_type || p.account_name || 'Webull', p.account_id_masked || (p.account_id ? `••••${String(p.account_id).slice(-4)}` : '')].filter(Boolean).join(' ') : 'Binance.US',
      unrealized_pnl: p.unrealized_pnl ?? p.webull_unrealized_pnl ?? (numericValue(p, 'current_value') !== null && numericValue(p, 'cost_basis') > 0 ? numericValue(p, 'current_value') - numericValue(p, 'cost_basis') : null),
    };
  });
}

export function mergeEventMarket(position, market) {
  if (!market || market.unavailable || assetType(position) !== 'Event Contracts') return position;
  const symbol = String(position.symbol || '').replace(/ (YES|NO)$/i, '');
  if (market.symbol !== symbol) return position;
  return {
    ...position,
    event_title: position.event_title || market.name || market.title,
    event_rules: position.event_rules || (typeof market.provider_rules === 'string' ? market.provider_rules : market.yes_condition || market.description),
    event_threshold: position.event_threshold ?? market.target_value,
    settlement: {
      ...position.settlement,
      cutoff_at: position.settlement?.cutoff_at || market.last_trading_date,
      expected_at: position.settlement?.expected_at || market.expected_exp_date,
    },
  };
}
