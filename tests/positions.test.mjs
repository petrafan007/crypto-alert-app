import test from 'node:test';
import assert from 'node:assert/strict';
import { ASSET_VIEWS, defaultColumnState, cleanColumnState, moveColumnState, columnStorageKey, assetType, valueForColumn, positionStatus, positionSide, normalizeRealPositions, timestamp, countdown, mergeEventMarket } from '../frontend/src/utils/positions.mjs';

test('asset layouts expose event fields without cluttering equity defaults', () => {
  for (const view of ASSET_VIEWS) {
    const state = defaultColumnState(view, true);
    assert.equal(new Set(state.order).size, state.order.length);
    assert.ok(state.selected.includes('symbol'));
    assert.ok(state.selected.includes('account'));
    assert.ok(state.selected.every(id => state.order.includes(id)));
  }
  assert.ok(defaultColumnState('Event Contracts').selected.includes('cutoff'));
  assert.ok(!defaultColumnState('Equities & ETFs').selected.includes('cutoff'));
  assert.ok(defaultColumnState('Options').selected.includes('strike'));
  assert.equal(assetType({ instrument_type: 'ETF' }), 'Equities & ETFs');
});
test('reorder moves both directions and preserves hidden columns and selection', () => {
  const state = { order: ['symbol', 'quantity', 'mark'], selected: ['symbol', 'mark'] };
  const moved = moveColumnState(state, 'symbol', 'mark');
  assert.deepEqual(moved.order, ['quantity', 'mark', 'symbol']);
  assert.deepEqual(moved.selected, state.selected);
  assert.deepEqual(moveColumnState(moved, 'symbol', 'quantity').order, state.order);
  assert.equal(moveColumnState(state, 'unknown', 'mark'), state);
});
test('saved layouts recover from malformed values and remain user and asset scoped', () => {
  assert.notEqual(columnStorageKey(1, 'All assets'), columnStorageKey(2, 'All assets'));
  assert.notEqual(columnStorageKey(1, 'Options'), columnStorageKey(1, 'Event Contracts'));
  assert.equal(columnStorageKey(null, 'Options'), null);
  for (const invalid of [null, {}, [], { order: 'bad', selected: [] }]) assert.deepEqual(cleanColumnState(invalid, 'Options'), defaultColumnState('Options'));
  const recovered = cleanColumnState({ order: ['symbol', 'symbol', 'removed'], selected: ['cutoff', 'removed'] }, 'Equities & ETFs');
  assert.equal(recovered.order.filter(id => id === 'symbol').length, 1);
  assert.deepEqual(recovered.selected, ['symbol']);
});
test('event status distinguishes cutoff from confirmed settlement and delay evidence', () => {
  const now = Date.parse('2026-09-07T15:00:00Z');
  const position = { instrument_type: 'EVENT', event_outcome: 'NO', settlement: { cutoff_at: '2026-09-07T16:00:00Z' } };
  assert.equal(positionStatus(position, now), 'Active');
  assert.equal(positionStatus(position, now + 7200000), 'Awaiting settlement');
  position.settlement.expected_at = '2026-09-07T16:30:00Z';
  assert.equal(positionStatus(position, now + 7200000), 'Settlement delayed');
  position.settlement.status = 'RESOLVED'; position.settlement.confirmed_outcome = 'YES';
  assert.equal(positionSide(position), 'NO');
  assert.equal(positionStatus(position, now), 'Settled — awaiting removal');
  assert.equal(positionStatus({ instrument_type: 'EVENT' }, now), 'Status unavailable');
});
test('zero marks and values remain zero, missing percentages use recorded cost', () => {
  const position = { instrument_type: 'EVENT', quantity: 50, market_value: 0, last_price: 0, collateral: 20, unrealized_profit_loss: -20 };
  assert.equal(valueForColumn(position, 'market_value'), 0);
  assert.equal(valueForColumn(position, 'mark'), 0);
  assert.equal(valueForColumn(position, 'open_pnl_pct'), -100);
  assert.equal(valueForColumn({ ...position, collateral: 0 }, 'open_pnl_pct'), null);
});
test('combined real holdings keep source identities and never include paper holdings', () => {
  const rows = normalizeRealPositions([{ symbol: 'BTC', amount: 2, current_value: 150, cost_basis: 100 }, { source: 'webull', symbol: 'ABC', account_id: 'abcd1234', instrument_type: 'ETF' }, { is_quant: true, symbol: 'PAPER' }, { is_paper: true }]);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].unrealized_pnl, 50);
  assert.equal(rows[0].account_label, 'Binance.US');
  assert.equal(rows[1].account_label, 'Webull ••••1234');
  assert.equal(rows[1].instrument_type, 'ETF');
});
test('cutoff timestamps and spread names preserve full contract identity', () => {
  assert.equal(timestamp('2026-09-07T15:00:00'), timestamp('2026-09-07T15:00:00Z'));
  assert.equal(countdown(1000, 1000), 'Closed');
  assert.equal(countdown(121000, 1000), '2m 0s');
  const p = { symbol: 'SPY', instrument_type: 'OPTION', details: { expiration: '2026-10-16', short: { strike: 500, option_type: 'PUT' }, long: { strike: 495, option_type: 'PUT' } } };
  assert.match(valueForColumn(p, 'symbol'), /500 \/ \$495 PUT spread/);
});

test('exact contract metadata never replaces ledger marks, values, or confirmed results', () => {
  const position = { symbol: 'KXTEST NO', instrument_type: 'EVENT', market_value: 0, last_price: 0, settlement: { confirmed_outcome: 'YES' } };
  const market = { symbol: 'KXTEST', name: 'Above threshold?', target_value: 0, last_price: .5, last_trading_date: '2026-09-07T16:00:00Z', settled_outcome: 'NO' };
  const result = mergeEventMarket(position, market);
  assert.equal(result.event_title, 'Above threshold?');
  assert.equal(result.event_threshold, 0);
  assert.equal(result.last_price, 0);
  assert.equal(result.market_value, 0);
  assert.equal(result.settlement.confirmed_outcome, 'YES');
  assert.equal(mergeEventMarket(position, { ...market, symbol: 'OTHER' }), position);
});
