import test from 'node:test';
import assert from 'node:assert/strict';
import { MODULES, DEFAULT_WEIGHTS, normalizeAllocations, toggleModule, changeAllocation, moduleStatusLabel } from '../frontend/src/utils/portfolioModules.mjs';

const settings = active => Object.fromEntries(MODULES.map(key => [key, { enabled: active.includes(key) }]));
const config = (active = MODULES, weights = DEFAULT_WEIGHTS) => ({
  allocation_weights: { ...weights }, module_settings: settings(active),
  allocations: normalizeAllocations(weights, settings(active)),
  watchlists: { futures: ['MES'] }, master_ai_prompt: 'Keep this mandate',
});
function invariant(cfg) {
  const active = MODULES.filter(key => cfg.module_settings[key].enabled);
  const allocations = normalizeAllocations(cfg.allocation_weights, cfg.module_settings);
  assert.equal(Math.round(Object.values(allocations).reduce((a, b) => a + b, 0) * 100), active.length ? 10000 : 0);
  for (const key of MODULES) {
    assert.ok(Number.isFinite(allocations[key]) && allocations[key] >= 0 && allocations[key] <= 100);
    if (!active.includes(key)) assert.equal(allocations[key], 0);
  }
  return allocations;
}

test('all 32 enabled combinations total 100%, with all-off reserved for cash', () => {
  for (let mask = 0; mask < 32; mask++) {
    const active = MODULES.filter((_, index) => mask & (1 << index));
    const cfg = config(active);
    const allocations = invariant(cfg);
    if (active.length === 1) assert.equal(allocations[active[0]], 100);
  }
});
test('approved examples and repeated toggles preserve preferences and unrelated settings', () => {
  const original = config();
  const before = structuredClone(original);
  let draft = original;
  for (let i = 0; i < 100; i++) {
    draft = toggleModule(draft, 'futures', false);
    assert.deepEqual(draft.allocations, { equities: 38.89, options: 27.78, crypto: 22.22, futures: 0, events: 11.11 });
    draft = toggleModule(draft, 'futures', true);
    assert.deepEqual(draft.allocations, DEFAULT_WEIGHTS);
  }
  assert.deepEqual(original, before);
  assert.deepEqual(draft.watchlists, before.watchlists);
  assert.equal(draft.master_ai_prompt, before.master_ai_prompt);
  draft = config(['equities', 'options']);
  assert.deepEqual(draft.allocations, { equities: 58.33, options: 41.67, crypto: 0, futures: 0, events: 0 });
  draft = changeAllocation(draft, 'equities', 70);
  assert.equal(draft.allocations.equities, 70);
  assert.equal(draft.allocations.options, 30);
});
test('slider redistribution retains customized ratios after 100% and reload', () => {
  let draft = config(['equities', 'options', 'crypto'], { equities: 30, options: 40, crypto: 10, futures: 10, events: 10 });
  draft = changeAllocation(draft, 'equities', 100);
  assert.equal(draft.allocations.equities, 100);
  draft = JSON.parse(JSON.stringify(draft));
  draft = changeAllocation(draft, 'equities', 50);
  assert.equal(draft.allocations.options, 40);
  assert.equal(draft.allocations.crypto, 10);
  assert.equal(draft.allocation_weights.futures, 10);
  assert.equal(draft.allocation_weights.events, 10);
});
test('all-zero active weights, disabled/single sliders and nonfinite input', () => {
  const zeros = Object.fromEntries(MODULES.map(key => [key, 0]));
  let draft = config(['equities', 'options'], zeros);
  assert.equal(draft.allocations.equities, 58.33);
  draft = changeAllocation(draft, 'equities', 100);
  draft = toggleModule(draft, 'equities', false);
  assert.equal(draft.allocations.options, 100);
  assert.strictEqual(changeAllocation(draft, 'options', 10), draft);
  assert.strictEqual(changeAllocation(draft, 'equities', 10), draft);
  draft = toggleModule(draft, 'crypto', true);
  draft = changeAllocation(draft, 'options', 30);
  assert.equal(draft.allocations.options, 30);
  assert.equal(draft.allocations.crypto, 70);
  for (const bad of [NaN, Infinity, -Infinity, 'bad']) assert.strictEqual(changeAllocation(draft, 'options', bad), draft);
  invariant(draft);
});
test('many slider moves preserve the selected value and exact totals through toggles and reloads', () => {
  let draft = config();
  const before = structuredClone(draft);
  for (let i = 0; i < 2000; i++) {
    const key = MODULES[i % 5];
    draft = toggleModule(draft, key, true);
    const active = MODULES.filter(m => draft.module_settings[m].enabled);
    const pct = (i * 7919 % 10001) / 100;
    draft = changeAllocation(draft, key, pct);
    assert.equal(draft.allocations[key], active.length === 1 ? 100 : pct);
    invariant(draft);
    if (i % 7 === 0) draft = toggleModule(draft, MODULES[(i + 2) % 5], false);
    draft = JSON.parse(JSON.stringify(draft));
    invariant(draft);
    assert.ok(Math.abs(Object.values(draft.allocation_weights).reduce((a, b) => a + b, 0) - 100) < 1e-6);
    for (const m of MODULES) assert.ok(draft.module_settings[m].allocation_preference >= 0 && draft.module_settings[m].allocation_preference <= 100);
  }
  assert.deepEqual(config(), before);
});
test('health labels distinguish disabled, entitlement, warm-up and ready states', () => {
  assert.deepEqual(['DISABLED', 'SUBSCRIPTION_REQUIRED', 'WARMING_UP', 'READY'].map(moduleStatusLabel),
    ['Disabled', 'Subscription required', 'Warming up', 'Ready']);
});
