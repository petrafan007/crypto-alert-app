// Cash held back by pending BUY orders and automation, counted once per
// obligation. Pure functions over the accepted pending-order list and rows.

const provider = order => (String(order?.provider || order?.source || order?.exchange || 'binance').toLowerCase() === 'webull' ? 'webull' : 'binance');
const isSynthetic = order => !!(order?.is_synthetic || order?.is_ladder || order?.is_trailing
  || /^(ladder|trail)_/.test(String(order?.order_id ?? '')));
const isBuy = order => String(order?.side || '').toUpperCase() === 'BUY';

// What the order would spend if it filled now: the server's figure for the
// unfilled remainder when it supplies one, else remaining quantity x price.
export function orderCost(order) {
  const explicit = order?.quantity_usdt;
  const cost = explicit !== undefined && explicit !== null
    ? Number(explicit)
    : Number(order?.quantity ?? 0) * Number(order?.trigger_price || order?.price || 0);
  return Number.isFinite(cost) && cost > 0 ? cost : 0;
}

const groupOf = order => {
  if (order.group_id) return { id: String(order.group_id), exclusive: order.group_role !== 'independent' };
  // Older Binance.US rows identify an OCO pair only by its list id.
  const listId = order.orderListId;
  if (listId !== undefined && listId !== null && String(listId) !== '-1') return { id: `binance-list-${listId}`, exclusive: true };
  return null;
};

// - A synthetic strategy and the broker order it submitted describe the same
//   shares. They are linked by the strategy's execution journal and reserve
//   cash once: the larger of the two figures.
// - Legs of one broker group that cannot all execute (an OCO pair) reserve the
//   most expensive branch, not the sum. Independent legs still add up.
// - Separate orders stay separate.
export function reservedByOrders(orders) {
  const buys = (Array.isArray(orders) ? orders : []).filter(order => isBuy(order) && orderCost(order) > 0);
  const strategies = buys.filter(isSynthetic);
  const strategyIds = new Set(strategies.map(order => String(order.order_id)));
  const childrenOf = new Map();
  const independent = [];
  for (const order of buys) {
    if (isSynthetic(order)) continue;
    const parent = order.synthetic_parent_id ? String(order.synthetic_parent_id) : '';
    if (parent && strategyIds.has(parent)) childrenOf.set(parent, (childrenOf.get(parent) || 0) + orderCost(order));
    else independent.push(order);
  }
  const synthetic = strategies.reduce((sum, order) => sum + Math.max(orderCost(order), childrenOf.get(String(order.order_id)) || 0), 0);

  let exchange = 0;
  const groups = new Map();
  for (const order of independent) {
    const group = groupOf(order);
    if (!group) { exchange += orderCost(order); continue; }
    const totals = groups.get(group.id) || { exclusive: 0, independent: 0 };
    if (group.exclusive) totals.exclusive = Math.max(totals.exclusive, orderCost(order));
    else totals.independent += orderCost(order);
    groups.set(group.id, totals);
  }
  for (const totals of groups.values()) exchange += totals.exclusive + totals.independent;
  return { exchange, synthetic };
}

const withTotal = parts => ({ ...parts, total: parts.exchange + parts.synthetic + parts.automation });

// Binance.US: orders priced in this quote currency, plus auto-buy budgets set
// aside in it on portfolio and watchlist rows.
export function binanceCashReservation(quote, orders, rows = []) {
  const clean = String(quote || '').toUpperCase();
  const matchesQuote = order => {
    const symbol = String(order?.symbol || '').toUpperCase();
    return clean === 'USDT' ? symbol.endsWith('USDT') : clean === 'USD' ? symbol.endsWith('USD') && !symbol.endsWith('USDT') : false;
  };
  const scoped = (Array.isArray(orders) ? orders : []).filter(order => provider(order) === 'binance' && matchesQuote(order));
  const automation = rows.reduce((sum, row) => {
    if (!row?.auto_buy_enabled || String(row.auto_buy_quote_currency || 'USDT').toUpperCase() !== clean) return sum;
    const amount = Number(row.auto_buy_amount || 0);
    return Number.isFinite(amount) && amount > 0 ? sum + amount : sum;
  }, 0);
  return withTotal({ ...reservedByOrders(scoped), automation });
}

// Webull: orders in one account, or in every account when none is named.
export function webullCashReservation(accountId, orders) {
  const scoped = (Array.isArray(orders) ? orders : []).filter(order => provider(order) === 'webull'
    && (!accountId || String(order.account_id || '') === String(accountId)));
  return withTotal({ ...reservedByOrders(scoped), automation: 0 });
}

// Says in words why less cash is available than the balance shows.
export function describeCashReservation(available, reservation, currency = 'USD') {
  const money = value => `${Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
  const parts = [`${money(available)} available`];
  if (reservation.exchange > 0.005) parts.push(`${money(reservation.exchange)} held by open broker orders`);
  if (reservation.synthetic > 0.005) parts.push(`${money(reservation.synthetic)} held for synthetic strategies being monitored`);
  if (reservation.automation > 0.005) parts.push(`${money(reservation.automation)} set aside for auto-buy`);
  return parts.join(' · ');
}
