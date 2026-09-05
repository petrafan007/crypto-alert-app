import test from 'node:test';
import assert from 'node:assert/strict';
import { MODULES, reallocateEnabled, moduleStatusLabel } from '../frontend/src/utils/portfolioModules.mjs';

test('reallocation is explicit, preserves source weights, and assigns only enabled modules', () => {
  const weights = { equities: 35, options: 25, crypto: 20, futures: 10, events: 10 };
  const before = { ...weights };
  const next = reallocateEnabled(weights, { options: { enabled: false }, futures: { enabled: false } });
  assert.deepEqual(weights, before);
  assert.equal(next.options, 0);
  assert.equal(next.futures, 0);
  assert.equal(Math.round(Object.values(next).reduce((n, x) => n + x, 0) * 100), 10000);
  assert.ok(next.equities > next.crypto && next.crypto > next.events);
});
test('zero weights distribute exactly and all-disabled refuses to allocate', () => {
  const weights = Object.fromEntries(MODULES.map(m => [m, 0]));
  const settings = Object.fromEntries(MODULES.map(m => [m, { enabled: m !== 'options' && m !== 'futures' }]));
  const next = reallocateEnabled(weights, settings);
  assert.equal(next.equities, 33.33);
  assert.equal(next.crypto, 33.33);
  assert.equal(next.events, 33.34);
  assert.throws(() => reallocateEnabled(weights, Object.fromEntries(MODULES.map(m => [m, { enabled: false }]))), /Enable/);
});
test('health labels distinguish disabled, entitlement, warm-up and ready states', () => {
  assert.deepEqual(['DISABLED', 'SUBSCRIPTION_REQUIRED', 'WARMING_UP', 'READY'].map(moduleStatusLabel),
    ['Disabled', 'Subscription required', 'Warming up', 'Ready']);
});
