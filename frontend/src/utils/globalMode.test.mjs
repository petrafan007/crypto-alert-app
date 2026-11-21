import test from 'node:test';
import assert from 'node:assert/strict';
import {
  normalizeGlobalMode,
  toWebullTradingMode,
  createModeRaceGuard,
  canPerformRowAction,
} from './globalMode.mjs';

test('normalizeGlobalMode enforces valid values and admin gate on QSE', () => {
  assert.equal(normalizeGlobalMode('real', false), 'real');
  assert.equal(normalizeGlobalMode('paper', false), 'paper');
  assert.equal(normalizeGlobalMode('qse', false), 'real');
  assert.equal(normalizeGlobalMode('qse', true), 'qse');
  assert.equal(normalizeGlobalMode('PAPER', false), 'paper');
  assert.equal(normalizeGlobalMode('garbage', true), 'real');
  assert.equal(normalizeGlobalMode(null, true), 'real');
});

test('toWebullTradingMode maps global modes accurately', () => {
  assert.equal(toWebullTradingMode('real'), 'REAL');
  assert.equal(toWebullTradingMode('paper'), 'TEST');
  assert.equal(toWebullTradingMode('qse'), 'QUANT');
});

test('createModeRaceGuard drops stale responses across mode switches (S9)', () => {
  const guard = createModeRaceGuard('real');
  const realTicket = guard.issueTicket();
  assert.equal(guard.isCurrent(realTicket), true);

  // Switch to paper while real request is still in-flight
  guard.setMode('paper');
  assert.equal(guard.isCurrent(realTicket), false);

  const paperTicket1 = guard.issueTicket();
  const paperTicket2 = guard.issueTicket();
  assert.equal(guard.isCurrent(paperTicket1), false);
  assert.equal(guard.isCurrent(paperTicket2), true);

  // Switching to QSE invalidates pending paper ticket
  guard.setMode('qse');
  assert.equal(guard.isCurrent(paperTicket2), false);
});

test('canPerformRowAction blocks all actions in QSE and restricts Paper actions', () => {
  for (const action of ['buy', 'sell', 'hide', 'watchlist_add', 'watchlist_remove', 'alert', 'stake']) {
    assert.equal(canPerformRowAction('qse', action), false, `QSE must block ${action}`);
  }
  assert.equal(canPerformRowAction('paper', 'buy'), true);
  assert.equal(canPerformRowAction('paper', 'sell'), true);
  assert.equal(canPerformRowAction('paper', 'hide'), true);
  assert.equal(canPerformRowAction('paper', 'watchlist_add'), true);
  assert.equal(canPerformRowAction('paper', 'watchlist_remove'), true);
  assert.equal(canPerformRowAction('paper', 'stake'), false);
  assert.equal(canPerformRowAction('paper', 'alert'), false);
  assert.equal(canPerformRowAction('real', 'stake'), true);
  assert.equal(canPerformRowAction('real', 'alert'), true);
});

import { cutoffFromSymbol, valueForColumn } from './positions.mjs';

test('cutoffFromSymbol returns numeric ms and valueForColumn cutoff returns ISO string without throwing', () => {
  const ms = cutoffFromSymbol('KXBTCD-26NOV2017-T85000');
  assert.equal(typeof ms, 'number');
  assert.equal(Number.isFinite(ms), true);
  const iso = valueForColumn({ symbol: 'KXBTCD-26NOV2017-T85000', instrument_type: 'EVENT' }, 'cutoff');
  assert.equal(typeof iso, 'string');
  assert.ok(iso.endsWith('Z'));
});
