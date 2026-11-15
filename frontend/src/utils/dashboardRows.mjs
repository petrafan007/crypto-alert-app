// Row identity, order matching, ordering and local-edit bookkeeping for the
// Dashboard portfolio and watchlist tables. Pure functions: no React, no I/O.

const text = value => String(value ?? '').trim();
const upper = value => text(value).toUpperCase();

export const rowProvider = row => (
  row && (row.is_external === true || row.source === 'webull' || row.provider === 'webull') ? 'webull' : 'binance'
);
export const rowAccount = row => text(row?.webull_account_id ?? row?.account_id);
export const rowSymbol = row => upper(row?.symbol);

// Portfolio ids are unique per provider table (Binance coin id, `webull-<holding id>`),
// so provider + id identifies one holding in one account. Symbol is only a
// fallback for rows that have no id yet.
export function portfolioRowIdentity(row) {
  const id = text(row?.id);
  return `${rowProvider(row)}:${id || `sym:${rowSymbol(row)}`}`;
}

// Watchlist identity must be the same before and after the server assigns an
// id, so it uses the instrument the user chose rather than a database id.
export function watchlistRowIdentity(row) {
  const provider = rowProvider(row);
  if (provider !== 'webull') return `binance:${rowSymbol(row)}`;
  return `webull:${rowSymbol(row)}:${upper(row?.instrument_type) || 'EQUITY'}:${upper(row?.event_outcome)}`;
}

const orderProvider = order => (
  String(order?.provider || order?.source || order?.exchange || 'binance').toLowerCase() === 'webull' ? 'webull' : 'binance'
);
const orderAccount = order => text(order?.account_id ?? order?._webull_account_id ?? order?.webull_account_id);

const BINANCE_QUOTES = ['USDT', 'USDC', 'USD'];
// 'BTCUSDT' -> 'BTC'. A pair is only split on a known quote suffix; a prefix
// test would let 'USD' claim 'USDTUSD' or 'ETH' claim an unrelated longer pair.
export function binanceBaseAsset(pair) {
  const symbol = upper(pair);
  const quote = BINANCE_QUOTES.find(candidate => symbol.length > candidate.length && symbol.endsWith(candidate));
  return quote ? symbol.slice(0, -quote.length) : symbol;
}

const instrumentClass = value => {
  const type = upper(value);
  if (['OPTION', 'OPTIONS'].includes(type)) return 'OPTION';
  if (['EVENT', 'EVENT_CONTRACT', 'PREDICTION'].includes(type)) return 'EVENT';
  if (type === 'CRYPTO') return 'CRYPTO';
  if (['FUTURES', 'FUTURE'].includes(type)) return 'FUTURES';
  return type ? 'EQUITY' : '';
};

// `symbolAccounts` is the set of Webull accounts that hold this symbol. It is
// used only to resolve an order that names no account: such an order may
// highlight a row when that is unambiguous, never every account at once.
export function orderMatchesRow(order, row, { symbolAccounts } = {}) {
  if (!order || !row) return false;
  const provider = rowProvider(row);
  if (orderProvider(order) !== provider) return false;
  const symbol = rowSymbol(row);
  if (!symbol) return false;
  const orderSymbol = upper(order.symbol);
  if (provider === 'binance') {
    if (orderSymbol) return orderSymbol === symbol || binanceBaseAsset(orderSymbol) === symbol;
    return upper(order.asset) === symbol;
  }
  if (orderSymbol !== symbol && upper(order.asset) !== symbol) return false;
  const orderClass = instrumentClass(order.instrument_type);
  const rowClass = instrumentClass(row.instrument_type);
  if (orderClass && rowClass && orderClass !== rowClass) return false;
  const account = rowAccount(row);
  if (!account) return true; // the row itself combines accounts (watchlist)
  const placedIn = orderAccount(order);
  if (placedIn) return placedIn === account;
  return !symbolAccounts || symbolAccounts.size <= 1;
}

export const NUMERIC_SORT_KEYS = new Set([
  'amount', 'current_price', 'current_value', 'avg_entry', 'pct_change', 'change_24h', 'volatility_pct',
  'high_low_24h', 'volume_24h', 'market_cap', 'pnl_usd', 'allocation_pct', 'target_price', 'down_alert', 'up_alert',
]);

const STABLE_QUOTES = ['USD', 'USDT', 'USDC', 'BUSD', 'DAI'];
const isStableRow = row => STABLE_QUOTES.includes(rowSymbol(row))
  || (rowProvider(row) === 'webull' && upper(row?.instrument_type) === 'CASH');
const numberOrNull = value => (value === undefined || value === null ? null : Number(value));

export function sortValue(row, key) {
  if (!row) return null;
  if (key === 'pnl_usd') {
    if (row.current_price && row.avg_entry && row.amount) return row.amount * (row.current_price - row.avg_entry);
    if (row.current_value !== undefined && row.cost_basis !== undefined && row.cost_basis > 0) return row.current_value - row.cost_basis;
    return null;
  }
  if (key === 'allocation_pct') return numberOrNull(row.current_value);
  if (key === 'avg_entry' || key === 'current_price') return isStableRow(row) ? 1.0 : numberOrNull(row[key]);
  if (['pct_change', 'change_24h', 'current_value'].includes(key)) return numberOrNull(row[key]);
  if (key === 'sentiment') {
    return typeof row.sentiment === 'object' ? (row.sentiment?.score ?? row.sentiment?.label ?? '') : (row.sentiment || '');
  }
  return row[key];
}

// Plain code-unit comparison: the tie-break must not depend on browser locale.
const compareText = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

// The permanent order of two rows when nothing else separates them.
export function compareRowIdentity(a, b) {
  return compareText(rowSymbol(a), rowSymbol(b))
    || compareText(rowProvider(a), rowProvider(b))
    || compareText(rowAccount(a), rowAccount(b))
    || compareText(upper(a?.instrument_type), upper(b?.instrument_type))
    || compareText(upper(a?.event_outcome), upper(b?.event_outcome))
    || compareText(text(a?.id), text(b?.id));
}

// With no chosen column the order is alphabetical by symbol. With a chosen
// column, rows with no value go last in either direction and equal values fall
// back to the identity order, so the incoming server order never decides.
export function sortDashboardRows(rows, config) {
  if (!Array.isArray(rows)) return [];
  const key = config?.key || null;
  const descending = config?.direction === 'desc';
  const numeric = NUMERIC_SORT_KEYS.has(key);
  const missing = value => value === null || value === undefined || value === '' || (numeric && Number.isNaN(Number(value)));
  return [...rows].sort((a, b) => {
    if (key) {
      const aValue = sortValue(a, key);
      const bValue = sortValue(b, key);
      const aMissing = missing(aValue);
      const bMissing = missing(bValue);
      if (aMissing !== bMissing) return aMissing ? 1 : -1;
      if (!aMissing) {
        const order = numeric
          ? Number(aValue) - Number(bValue)
          : String(aValue).toLowerCase().localeCompare(String(bValue).toLowerCase());
        if (order) return descending ? -order : order;
      }
    }
    return compareRowIdentity(a, b);
  });
}

export const DEFAULT_SORT = Object.freeze({ key: null, direction: 'asc' });

// A saved preference only applies to the table it was saved for, and only for
// a column that table can still sort by.
export function parseSortPreference(raw, sortableKeys) {
  try {
    const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;
    if (parsed && typeof parsed === 'object' && parsed.key && sortableKeys.includes(parsed.key)) {
      return { key: parsed.key, direction: parsed.direction === 'desc' ? 'desc' : 'asc' };
    }
  } catch { /* An unreadable preference is the same as none. */ }
  return { ...DEFAULT_SORT };
}

export function nextSortPreference(current, key) {
  if (!key) return { ...DEFAULT_SORT };
  if (current?.key !== key) return { key, direction: 'asc' };
  if (current.direction === 'asc') return { key, direction: 'desc' };
  return { ...DEFAULT_SORT }; // third click returns to the stable default
}

// Remembers fields the user just saved so that a refresh which was requested
// before the save cannot put the old value back on screen.
export function createRowEditLedger({ now = Date.now, ttlMs = 120000 } = {}) {
  let clock = 0;
  const edits = new Map(); // identity -> Map(field -> { value, seq, at })
  const prune = () => {
    const cutoff = now() - ttlMs;
    for (const [identity, fields] of edits) {
      for (const [field, edit] of fields) if (edit.at < cutoff) fields.delete(field);
      if (!fields.size) edits.delete(identity);
    }
  };
  return {
    // Capture before issuing a read; pass the value to overlay() with its result.
    mark: () => clock,
    tick: () => ++clock,
    record(identity, patch) {
      if (!patch || typeof patch !== 'object') return clock;
      prune();
      const seq = ++clock;
      const fields = edits.get(identity) || new Map();
      for (const [field, value] of Object.entries(patch)) fields.set(field, { value, seq, at: now() });
      edits.set(identity, fields);
      return seq;
    },
    overlay(identity, row, readMark) {
      const fields = edits.get(identity);
      if (!fields) return row;
      prune();
      let next = row;
      for (const [field, edit] of fields) {
        if (readMark !== undefined && edit.seq <= readMark) continue; // the read began after this save
        if (next === row) next = { ...row };
        next[field] = edit.value;
      }
      return next;
    },
    clear() { edits.clear(); },
  };
}

// Tracks the user's latest add/remove decision per watchlist row so that an
// older list or an earlier request finishing late cannot undo it.
export function createWatchlistIntents() {
  const intents = new Map(); // identity -> { kind, seq, item, settledSeq }
  return {
    begin(identity, kind, item, seq) { intents.set(identity, { kind, seq, item, settledSeq: null }); },
    isCurrent: (identity, seq) => intents.get(identity)?.seq === seq,
    settle(identity, seq, settledSeq, item) {
      const intent = intents.get(identity);
      if (intent?.seq !== seq) return false;
      intent.settledSeq = settledSeq;
      if (item) intent.item = item;
      return true;
    },
    drop(identity, seq) {
      if (intents.get(identity)?.seq === seq) intents.delete(identity);
    },
    get: identity => intents.get(identity),
    pendingAdds: () => new Set([...intents].filter(([, intent]) => intent.kind === 'add').map(([identity]) => identity)),
    clear() { intents.clear(); },
    // `readMark` is the ledger clock captured when the list request started.
    merge(serverList, readMark) {
      if (!Array.isArray(serverList)) return serverList;
      const present = new Set(serverList.map(watchlistRowIdentity));
      let list = serverList;
      const additions = [];
      for (const [identity, intent] of [...intents]) {
        const authoritative = intent.settledSeq !== null && readMark !== undefined && readMark >= intent.settledSeq;
        if (intent.kind === 'add') {
          if (present.has(identity)) {
            if (readMark === undefined || readMark >= intent.seq) intents.delete(identity);
          } else if (authoritative) intents.delete(identity);
          else additions.push(intent.item);
        } else if (authoritative) intents.delete(identity);
        else list = list.filter(row => watchlistRowIdentity(row) !== identity);
      }
      return additions.length ? [...additions, ...list] : list;
    },
  };
}
