import assert from 'node:assert/strict';
import test from 'node:test';
import {
  portfolioRowIdentity, watchlistRowIdentity, orderMatchesRow, binanceBaseAsset, sortDashboardRows,
  parseSortPreference, nextSortPreference, createRowEditLedger, createWatchlistIntents,
} from '../frontend/src/utils/dashboardRows.mjs';

const symbols = rows => rows.map(row => row.symbol);
const BTC = { id: 1, symbol: 'BTC', sentiment: 'Hold', change_24h: 2 };
const ETH = { id: 2, symbol: 'ETH', sentiment: 'Hold', change_24h: 2 };

test('default order is alphabetical and independent of the incoming order (F21)', () => {
  assert.deepEqual(symbols(sortDashboardRows([BTC, ETH], { key: null })), ['BTC', 'ETH']);
  assert.deepEqual(symbols(sortDashboardRows([ETH, BTC], { key: null })), ['BTC', 'ETH']);
});

test('equal and missing sort values fall back to row identity in both directions (F22)', () => {
  for (const direction of ['asc', 'desc']) {
    for (const key of ['sentiment', 'change_24h', 'market_cap']) {
      assert.deepEqual(symbols(sortDashboardRows([ETH, BTC], { key, direction })), ['BTC', 'ETH'], `${key} ${direction}`);
      assert.deepEqual(symbols(sortDashboardRows([BTC, ETH], { key, direction })), ['BTC', 'ETH'], `${key} ${direction}`);
    }
  }
});

test('a chosen value sort still orders by that value, with missing values last', () => {
  const rows = [{ symbol: 'A', change_24h: 1 }, { symbol: 'B', change_24h: null }, { symbol: 'C', change_24h: 5 }];
  assert.deepEqual(symbols(sortDashboardRows(rows, { key: 'change_24h', direction: 'desc' })), ['C', 'A', 'B']);
  assert.deepEqual(symbols(sortDashboardRows(rows, { key: 'change_24h', direction: 'asc' })), ['A', 'C', 'B']);
});

test('same ticker at two providers has a fixed order and distinct identities (F11, F22)', () => {
  const binance = { id: 7, symbol: 'ETH' };
  const webull = { id: 'webull-7', symbol: 'ETH', source: 'webull', is_external: true, account_id: 'A' };
  assert.deepEqual(sortDashboardRows([webull, binance], null), [binance, webull]);
  assert.notEqual(portfolioRowIdentity(binance), portfolioRowIdentity(webull));
  assert.notEqual(watchlistRowIdentity({ symbol: 'ETH' }), watchlistRowIdentity({ symbol: 'ETH', provider: 'webull' }));
  assert.equal(watchlistRowIdentity({ id: 'temp-1', symbol: 'eth' }), watchlistRowIdentity({ id: 9, symbol: 'ETH' }));
});

test('sort preferences are validated per table and cycle back to the default (F23)', () => {
  assert.deepEqual(parseSortPreference('{"key":"amount","direction":"desc"}', ['symbol', 'amount']), { key: 'amount', direction: 'desc' });
  assert.deepEqual(parseSortPreference('{"key":"amount","direction":"desc"}', ['symbol', 'current_price']), { key: null, direction: 'asc' });
  assert.deepEqual(parseSortPreference('not json', ['symbol']), { key: null, direction: 'asc' });
  const first = nextSortPreference({ key: null, direction: 'asc' }, 'amount');
  const second = nextSortPreference(first, 'amount');
  assert.deepEqual([first.direction, second.direction], ['asc', 'desc']);
  assert.deepEqual(nextSortPreference(second, 'amount'), { key: null, direction: 'asc' });
  assert.deepEqual(nextSortPreference(second, null), { key: null, direction: 'asc' });
});

test('pending orders match one provider, account, instrument and exact pair (F10)', () => {
  const rowA = { symbol: 'NVDA', source: 'webull', account_id: 'A', instrument_type: 'EQUITY' };
  const rowB = { ...rowA, account_id: 'B' };
  const order = { provider: 'webull', symbol: 'NVDA', account_id: 'A' };
  assert.equal(orderMatchesRow(order, rowA), true);
  assert.equal(orderMatchesRow(order, rowB), false);
  assert.equal(orderMatchesRow(order, { symbol: 'NVDA' }), false, 'a Webull order never highlights a Binance row');
  assert.equal(orderMatchesRow(order, { symbol: 'NVDA', provider: 'webull' }), true, 'watchlist rows combine accounts');
  assert.equal(orderMatchesRow({ ...order, instrument_type: 'OPTION' }, rowA), false);
  const noAccount = { provider: 'webull', symbol: 'NVDA' };
  assert.equal(orderMatchesRow(noAccount, rowA, { symbolAccounts: new Set(['A']) }), true);
  assert.equal(orderMatchesRow(noAccount, rowA, { symbolAccounts: new Set(['A', 'B']) }), false, 'missing account is not every account');

  assert.equal(binanceBaseAsset('BTCUSDT'), 'BTC');
  assert.equal(binanceBaseAsset('USDTUSD'), 'USDT');
  assert.equal(orderMatchesRow({ provider: 'binance', symbol: 'ETHUSDT' }, { symbol: 'ETH' }), true);
  assert.equal(orderMatchesRow({ provider: 'binance', symbol: 'USDTUSD' }, { symbol: 'USD' }), false);
  assert.equal(orderMatchesRow({ provider: 'binance', symbol: 'ETHWUSDT' }, { symbol: 'ETH' }), false);
  assert.equal(orderMatchesRow({ provider: 'binance', symbol: 'ETHUSDT' }, { symbol: 'ETH', source: 'webull' }), false);
});

test('a Webull synthetic order highlights a stock watchlist row once the row reports Webull (F10b)', () => {
  const synthetic = { provider: 'webull', source: 'webull', symbol: 'ANT', instrument_type: 'EQUITY', account_id: 'A', is_synthetic: true, is_conditional: true };
  // The generic watchlist payload for a stock row now carries the Webull
  // identity (the same shape as a Webull watchlist item), so the order
  // matches and the row takes the pending-order highlight.
  const markedRow = { symbol: 'ANT', asset_type: 'stock', source: 'webull', provider: 'webull', is_external: true, instrument_type: 'EQUITY' };
  assert.equal(orderMatchesRow(synthetic, markedRow), true);
  // Before the payload fix the same row arrived with no provider fields,
  // was classified as Binance, and the Webull order could never match it.
  assert.equal(orderMatchesRow(synthetic, { symbol: 'ANT', asset_type: 'stock' }), false);
  // A Binance order still never highlights the Webull stock row.
  assert.equal(orderMatchesRow({ provider: 'binance', symbol: 'ANTUSDT' }, markedRow), false);
});


test('a refresh requested before a save cannot restore the old value (F27)', () => {
  let time = 0;
  const ledger = createRowEditLedger({ now: () => time, ttlMs: 1000 });
  const before = ledger.mark();
  ledger.record('watchlist:binance:BTC', { favorite: true });
  const after = ledger.mark();
  const stale = { symbol: 'BTC', favorite: false, current_price: 5 };
  assert.deepEqual(ledger.overlay('watchlist:binance:BTC', stale, before), { symbol: 'BTC', favorite: true, current_price: 5 });
  assert.equal(ledger.overlay('watchlist:binance:BTC', stale, after), stale, 'a read that began after the save is authoritative');
  assert.equal(ledger.overlay('watchlist:binance:ETH', stale, before), stale, 'other rows are untouched');
  time = 5000;
  assert.equal(ledger.overlay('watchlist:binance:BTC', stale, before), stale, 'old edits expire');
});

test('watchlist add/remove: the latest decision wins over late lists and requests (F25, F26)', () => {
  const ledger = createRowEditLedger();
  const intents = createWatchlistIntents();
  const sol = { id: 'temp-1', symbol: 'SOL', pendingAdd: true };
  const id = watchlistRowIdentity(sol);
  const server = [{ id: 1, symbol: 'BTC' }];

  const addSeq = ledger.tick();
  intents.begin(id, 'add', sol, addSeq);
  assert.deepEqual(symbols(intents.merge(server, ledger.mark())), ['SOL', 'BTC'], 'unconfirmed add survives a list without it');
  // A same-ticker Webull row is a different instrument and does not confirm the add.
  intents.merge([...server, { id: 'webull-watchlist-4', symbol: 'SOL', provider: 'webull' }], ledger.mark());
  assert.ok(intents.get(id), 'only the exact row confirms an add');

  const confirmed = { id: 9, symbol: 'SOL' };
  assert.equal(intents.settle(id, addSeq, ledger.tick(), confirmed), true);
  assert.deepEqual(symbols(intents.merge(server, addSeq)), ['SOL', 'BTC'], 'a list requested before confirmation cannot drop it');
  intents.merge([...server, confirmed], ledger.mark());
  assert.equal(intents.get(id), undefined, 'confirmed by a newer list');

  const before = ledger.mark();
  const removeSeq = ledger.tick();
  intents.begin(id, 'remove', confirmed, removeSeq);
  assert.deepEqual(symbols(intents.merge([...server, confirmed], before)), ['BTC'], 'an older list cannot bring a removed row back');
  assert.equal(intents.settle(id, addSeq, ledger.tick()), false, 'an earlier request finishing late is ignored');
  intents.settle(id, removeSeq, ledger.tick());
  assert.deepEqual(symbols(intents.merge([...server, confirmed], before)), ['BTC']);
  assert.deepEqual(symbols(intents.merge(server, ledger.mark())), ['BTC']);
  assert.equal(intents.get(id), undefined, 'a list requested after confirmation is authoritative');

  // Remove then re-add: an old list that still has the row must not count as confirmation.
  const old = ledger.mark();
  const reAdd = ledger.tick();
  intents.begin(id, 'add', sol, reAdd);
  intents.merge([...server, confirmed], old);
  assert.ok(intents.isCurrent(id, reAdd));
});
