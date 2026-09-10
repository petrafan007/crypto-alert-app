import test from 'node:test';
import assert from 'node:assert/strict';
import {
  cleanOrderTableState,
  defaultOrderTableState,
  moveOrderTableColumn,
  resizeOrderTableColumn,
} from '../frontend/src/utils/orderTable.mjs';

const columns = [
  { id: 'created_at', label: 'Date', locked: true },
  { id: 'account', label: 'Account' },
  { id: 'symbol', label: 'Symbol' },
  { id: 'status', label: 'Status' },
];

test('Symbol is visible and pinned first in new and migrated order table layouts', () => {
  assert.deepEqual(defaultOrderTableState(columns).order, ['symbol', 'created_at', 'account', 'status']);
  const migrated = cleanOrderTableState({
    order: ['created_at', 'status', 'symbol', 'account'],
    selected: ['created_at', 'status'],
    filters: { search: 'AAPL', values: {} },
  }, columns);
  assert.deepEqual(migrated.order, ['symbol', 'created_at', 'status', 'account']);
  assert.ok(migrated.selected.includes('symbol'));
  assert.equal(migrated.filters.search, 'AAPL');
});

test('Unpinned columns reorder without displacing Symbol', () => {
  const state = defaultOrderTableState(columns);
  const moved = moveOrderTableColumn(state, 'status', 'created_at');
  assert.deepEqual(moved.order, ['symbol', 'status', 'created_at', 'account']);
  assert.deepEqual(moveOrderTableColumn(moved, 'symbol', 'account'), moved);
});

test('Order table widths are persisted and clamped without losing other state', () => {
  const state = cleanOrderTableState({
    ...defaultOrderTableState(columns),
    widths: { symbol: 190.4, status: 10, removed: 250 },
  }, columns);
  assert.deepEqual(state.widths, { symbol: 190, status: 80 });
  const resized = resizeOrderTableColumn(state, 'account', 246.7);
  assert.equal(resized.widths.account, 247);
  assert.deepEqual(resized.order, state.order);
});
