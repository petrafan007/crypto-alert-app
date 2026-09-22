import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSyntheticPayload, strategyKind, matchesStatus, number, trailLabel, orderKey, strategySummary } from './syntheticOrders.mjs';
const config = { hasDownsideProtection: true, upsideMode: 'LADDER', upsidePreset: 'CUSTOM', upsideRungs: [{ target_price: '123.12345678', price_offset_pct: 23, percentage_of_total: 100 }], downsideMode: 'TRAILING', downsideTrailValue: '5', downsideTrailType: 'AMOUNT', downsideActivationPrice: '120' };
test('preserves protection, custom target precision, allocation and dollar trail units', () => {
  const payload = buildSyntheticPayload(config);
  assert.equal(payload.downside_mode, 'TRAILING'); assert.equal(payload.has_stop_loss, true);
  assert.equal(payload.custom_rungs[0].target_price, 123.12345678); assert.equal(payload.custom_rungs[0].percentage_of_total, 100);
  assert.equal(payload.downside_trail_type, 'AMOUNT'); assert.equal(payload.downside_activation_price, 120);
  assert.match(strategySummary(config)[1], /5 USD/);
});
test('turning protection off does not retain a stale stop', () => {
  const payload = buildSyntheticPayload({ ...config, hasDownsideProtection: false, downsideTargetPrice: 95 });
  assert.equal(payload.downside_mode, 'NONE'); assert.equal(payload.has_stop_loss, false); assert.equal(payload.downside_target_price, null);
});
test('classifies pure ladders and unified trailing strategies correctly', () => {
  assert.equal(strategyKind({ upside_mode: 'LADDER', downside_mode: 'NONE' }), 'LADDER');
  assert.equal(strategyKind({ upside_mode: 'TRAILING', downside_mode: 'NONE' }), 'TRAILING');
  assert.equal(strategyKind({ upside_mode: 'LADDER', downside_mode: 'SINGLE' }), 'BRACKET');
});
test('completed includes trailing fills and stopped-out strategies, failed stays separate', () => {
  for (const status of ['FILLED', 'COMPLETED', 'STOPPED_OUT']) assert.ok(matchesStatus({ status }, 'COMPLETED'));
  assert.equal(matchesStatus({ status: 'FAILED' }, 'CANCELLED'), false);
  assert.ok(matchesStatus({ status: 'SUBMITTED' }, 'ACTIVE'));
});
test('preserves small trigger prices, quantities above one and unique identities', () => {
  assert.match(number(1.23456789), /23456789/); assert.match(number(0.00000012), /00000012/);
  assert.equal(trailLabel(5, 'AMOUNT'), '5 USD'); assert.equal(trailLabel(5, 'PERCENT'), '5%');
  assert.notEqual(orderKey({ parentKind: 'LADDER', id: 1 }), orderKey({ parentKind: 'TRAILING', id: 1 }));
});
