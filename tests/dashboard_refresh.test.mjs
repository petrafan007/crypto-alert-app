import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createDashboardRefreshCoordinator, sameDashboardOrder, cancellationOutcome, recentFillRevision } from '../frontend/src/utils/dashboardRefresh.mjs';

const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

test('a mutation rejects delayed reads even if the transport ignores abort; bursts coalesce', async () => {
  const old = deferred();
  const started = deferred();
  const accepted = [];
  const tickets = [];
  let active = 0;
  const refresh = createDashboardRefreshCoordinator(async ticket => {
    assert.equal(++active, 1);
    tickets.push(ticket);
    if (ticket.id === 1) { started.resolve(); await old.promise; }
    if (ticket.isCurrent()) accepted.push(ticket.id);
    active--;
  });
  const done = refresh.request();
  await started.promise;
  refresh.request();
  refresh.request({ invalidate: true });
  refresh.request();
  assert.equal(tickets[0].signal.aborted, true);
  old.resolve();
  await done;
  assert.deepEqual(accepted, [2]);
  assert.equal(tickets[1].generation, 1);
});

test('cleanup rejects unfinished responses and queued work; a fresh mount runs normally', async () => {
  const old = deferred();
  const started = deferred();
  let applied = 0;
  const refresh = createDashboardRefreshCoordinator(async ticket => {
    started.resolve(); await old.promise;
    if (ticket.isCurrent()) applied++;
  });
  const done = refresh.request();
  await started.promise;
  refresh.request();
  refresh.stop();
  old.resolve();
  await done;
  await refresh.request();
  assert.equal(applied, 0);
  const remount = createDashboardRefreshCoordinator(async ticket => { if (ticket.isCurrent()) applied++; });
  await remount.request();
  assert.equal(applied, 1);
});

test('failed reads do not stop future polling', async () => {
  let calls = 0;
  const errors = [];
  const refresh = createDashboardRefreshCoordinator(async () => { if (++calls === 1) throw Error('offline'); }, e => errors.push(e.message));
  await refresh.request();
  await refresh.request();
  assert.equal(calls, 2);
  assert.deepEqual(errors, ['offline']);
});

test('cancellation matches only the exact provider/account/namespace and scoped aliases', () => {
  const order = { provider: 'webull', account_id: 'A', order_id: '123', client_order_id: 'client-1' };
  assert.ok(sameDashboardOrder(order, { ...order, order_id: 'client-1' }));
  for (const other of [{ ...order, account_id: 'B' }, { ...order, account_id: undefined },
    { ...order, provider: 'binance' }, { ...order, test_mode: true },
    { ...order, environment: 'sandbox' }, { ...order, order_id: 'ladder_123' }]) {
    assert.equal(sameDashboardOrder(order, other), false);
  }
  assert.equal(sameDashboardOrder({ orderId: 1, symbol: 'BTCUSD' }, { orderId: 1, symbol: 'ETHUSD' }), false);
  assert.equal(sameDashboardOrder({}, {}), false);
});

test('HTTP success cannot turn rejection or acknowledgement into confirmed cancellation', () => {
  assert.equal(cancellationOutcome({ success: false, status: 'CANCELLED' }), 'failed');
  assert.equal(cancellationOutcome({}), 'failed');
  assert.equal(cancellationOutcome({ success: true }), 'pending');
  assert.equal(cancellationOutcome({ success: true, ladder_order: { status: 'CANCEL_PENDING' } }), 'pending');
  assert.equal(cancellationOutcome({ success: true, status: 'CANCELED' }), 'confirmed');
  assert.equal(cancellationOutcome({ success: true, trailing_order: { status: 'CANCELLED' } }), 'confirmed');
});

test('fill revisions distinguish accounts and cumulative fills, and ignore old/non-final orders', () => {
  const now = Date.parse('2026-11-14T12:00:00Z');
  const fill = { provider: 'webull', account_id: 'A', id: 1, symbol: 'NVDA', status: 'FILLED', filled_quantity: 2, created_time: '2026-11-14T11:59:00Z' };
  const revision = recentFillRevision(fill, now);
  assert.ok(revision);
  assert.equal(revision, recentFillRevision({ ...fill }, now));
  assert.notEqual(revision, recentFillRevision({ ...fill, account_id: 'B' }, now));
  assert.notEqual(revision, recentFillRevision({ ...fill, filled_quantity: 3 }, now));
  assert.equal(recentFillRevision({ ...fill, status: 'OPEN' }, now), null);
  assert.equal(recentFillRevision(fill, now + 600000), null);
});

test('a source that answered replaces its orders; a failed source keeps its last orders (F17)', async () => {
  const { mergePendingOrders, pendingOrderScope } = await import('../frontend/src/utils/dashboardRefresh.mjs');
  const binance = { order_id: 1, provider: 'binance', symbol: 'ETHUSDT' };
  const webullA = { order_id: '7', provider: 'webull', account_id: 'A', symbol: 'NVDA' };
  const webullB = { order_id: '8', provider: 'webull', account_id: 'B', symbol: 'NVDA' };
  const ladder = { order_id: 'ladder_21', provider: 'webull', account_id: 'A', symbol: 'NVDA' };
  const previous = [binance, webullA, webullB, ladder];
  assert.deepEqual(previous.map(pendingOrderScope), ['binance', 'webull:A', 'webull:B', 'synthetic']);
  const ids = result => result.orders.map(order => order.order_id).sort();
  const scopes = (...failed) => ['binance', 'synthetic', 'webull:A', 'webull:B'].map(key => ({ key, complete: !failed.includes(key), reason: `${key} down` }));

  // Everything answered with nothing: a genuine empty list clears every highlight.
  assert.deepEqual(ids(mergePendingOrders(previous, { pending_orders: [], scopes: scopes() })), []);
  // Binance failed: only its last order is kept, and the reason is reported.
  const outage = mergePendingOrders(previous, { pending_orders: [webullB], scopes: scopes('binance') });
  assert.deepEqual(ids(outage), [1, '8']);
  assert.deepEqual(outage.reasons, ['binance down']);
  // One Webull account failed: the other account's empty answer still clears its order.
  assert.deepEqual(ids(mergePendingOrders(previous, { pending_orders: [], scopes: scopes('webull:B') })), ['8']);
  // All Webull accounts unavailable at once; synthetic strategies are a separate source.
  assert.deepEqual(ids(mergePendingOrders(previous, { pending_orders: [], scopes: [{ key: 'webull:*', complete: false }, { key: 'synthetic', complete: true }] })), ['7', '8']);
  // A kept order is not duplicated when the partial answer already lists it.
  assert.deepEqual(ids(mergePendingOrders(previous, { pending_orders: [binance], scopes: scopes('binance') })), [1]);
  // No scope information: the list is taken as it is. A missing list is not an empty list.
  assert.deepEqual(ids(mergePendingOrders(previous, { pending_orders: [] })), []);
  assert.equal(mergePendingOrders(previous, { error: 'offline' }), null);
});

test('orders are never carried across a change of live/paper mode (F18)', async () => {
  const { mergePendingOrders } = await import('../frontend/src/utils/dashboardRefresh.mjs');
  const live = [{ order_id: '7', provider: 'webull', account_id: 'A', symbol: 'NVDA' }];
  const failed = { pending_orders: [], scopes: [{ key: 'webull:*', complete: false }] };
  assert.equal(mergePendingOrders(live, { ...failed, mode: 'production:live' }, 'production:live').orders.length, 1);
  const switched = mergePendingOrders(live, { ...failed, mode: 'production:paper' }, 'production:live');
  assert.deepEqual(switched.orders, []);
  assert.equal(switched.mode, 'production:paper');
});

test('the refresh record keeps the most recent entries only (F38)', async () => {
  const { createRefreshDiagnostics, refreshRequestId } = await import('../frontend/src/utils/dashboardRefresh.mjs');
  const diagnostics = createRefreshDiagnostics(3, () => 'now');
  for (let i = 1; i <= 5; i++) diagnostics.record('start', { request: String(i) });
  assert.deepEqual(diagnostics.entries().map(entry => entry.request), ['3', '4', '5']);
  diagnostics.entries()[0].request = 'changed';
  assert.equal(diagnostics.entries()[0].request, '3', 'callers get copies');
  assert.equal(refreshRequestId({ id: 12, generation: 4 }), '12.4');
});
