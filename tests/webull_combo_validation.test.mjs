import test from 'node:test';
import assert from 'node:assert/strict';
import { validateWebullComboLegs } from '../frontend/src/utils/webullComboValidation.mjs';

const dip = { combo_type: 'OCO', side: 'BUY', order_type: 'LIMIT', limit_price: 160 };
const breakout = { combo_type: 'OCO', side: 'BUY', order_type: 'STOP_LOSS_LIMIT', limit_price: 165.05, stop_price: 165 };

test('valid OCO dip/breakout pair passes', () => {
  assert.deepEqual(validateWebullComboLegs([dip, breakout], { symbol: 'NVDA' }), []);
});

test('identical linked legs are refused, but a master leg may share a price', () => {
  assert.match(validateWebullComboLegs([dip, { ...dip, limit_price: '160.00' }])[0], /identical/);
  assert.deepEqual(validateWebullComboLegs([{ ...dip, combo_type: 'MASTER' }, dip]), []);
  assert.deepEqual(validateWebullComboLegs([dip, { ...dip, side: 'SELL' }]), []);
});

test('swapped stop-limit prices and near-equal linked prices are refused', () => {
  assert.match(validateWebullComboLegs([dip, { ...breakout, limit_price: 160.05 }])[0], /swapped/);
  assert.match(validateWebullComboLegs([dip, { ...dip, limit_price: 160.05 }])[0], /too close/);
});

test('regular-hours check only applies when requested', () => {
  const saturday = new Date('2026-11-14T19:15:00Z');
  const mondayMidday = new Date('2026-11-16T17:00:00Z');
  assert.match(validateWebullComboLegs([dip, breakout], { checkMarketHours: true, now: saturday }).join(' '), /regular market hours/);
  assert.deepEqual(validateWebullComboLegs([dip, breakout], { checkMarketHours: true, now: mondayMidday }), []);
  assert.deepEqual(validateWebullComboLegs([dip, breakout], { now: saturday }), []);
});
