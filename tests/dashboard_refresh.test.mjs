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
