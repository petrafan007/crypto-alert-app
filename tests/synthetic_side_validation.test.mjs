import test from 'node:test';
import assert from 'node:assert/strict';
import { validateLadderConfig } from '../frontend/src/utils/syntheticOrders.mjs';

// A disabled side keeps its last-edited config in the form state. That stale
// config must never block an order that does not use the side; an enabled side
// keeps every one of its checks, with the original messages.

const josephConfig = {
  // Downside (Buy the Dip) enabled: Mode C trailing stop, 3%, $80 hurdle.
  hasDownsideProtection: true,
  downsideMode: 'TRAILING',
  downsideTrailValue: '3.0',
  downsideTrailType: 'PERCENT',
  downsideActivationPrice: '80.00',
  // Upside (Breakout Entry) disabled, still showing Mode B ladder rungs at 30%.
  hasUpsideProtection: false,
  upsideMode: 'LADDER',
  rungs: [{ target_price: '90.00', percentage_of_total: 30 }],
  upsideRungs: [{ target_price: '90.00', percentage_of_total: 30 }],
};

test("Joseph's acceptance case: disabled upside with stale 30% rungs does not block a valid downside trailing stop", () => {
  assert.equal(validateLadderConfig(josephConfig), null);
});

test('disabled upside is not validated in any mode (SINGLE target, TRAILING value)', () => {
  assert.equal(validateLadderConfig({ ...josephConfig, upsideMode: 'SINGLE', upsideTargetPrice: '' }), null);
  assert.equal(validateLadderConfig({ ...josephConfig, upsideMode: 'TRAILING', upsideTrailValue: '' }), null);
  assert.equal(validateLadderConfig({ ...josephConfig, upsideMode: 'LADDER', rungs: [{ target_price: '', percentage_of_total: 30 }] }), null);
});

test('mirror: disabled downside with stale invalid config does not block a valid upside', () => {
  const base = {
    hasUpsideProtection: true,
    upsideMode: 'SINGLE',
    upsideTargetPrice: '120.00',
    hasDownsideProtection: false,
  };
  assert.equal(validateLadderConfig({ ...base, downsideMode: 'LADDER', downsideRungs: [{ target_price: '50', percentage_of_total: 30 }] }), null);
  assert.equal(validateLadderConfig({ ...base, downsideMode: 'SINGLE', downsideTargetPrice: '', downsideOffsetPct: '' }), null);
  assert.equal(validateLadderConfig({ ...base, downsideMode: 'TRAILING', downsideTrailValue: '' }), null);
});

test('enabled upside ladder whose rungs sum to 30% is still rejected with the original message', () => {
  assert.equal(
    validateLadderConfig({ ...josephConfig, hasUpsideProtection: true }),
    'Upside ladder rungs allocation must sum to 100% (currently 30.0%).'
  );
});

test('enabled upside is the default when hasUpsideProtection is absent', () => {
  const { hasUpsideProtection, ...noFlag } = josephConfig;
  assert.equal(
    validateLadderConfig(noFlag),
    'Upside ladder rungs allocation must sum to 100% (currently 30.0%).'
  );
});

test('enabled upside ladder at 100% with a rung missing its target price is rejected', () => {
  assert.equal(
    validateLadderConfig({
      hasUpsideProtection: true, upsideMode: 'LADDER',
      rungs: [{ target_price: '90', percentage_of_total: 60 }, { target_price: '', percentage_of_total: 40 }],
      hasDownsideProtection: false,
    }),
    'All upside ladder rungs must have a valid target price greater than 0.'
  );
});

test('enabled upside SINGLE without a target and TRAILING without a value are rejected', () => {
  assert.equal(
    validateLadderConfig({ hasUpsideProtection: true, upsideMode: 'SINGLE', upsideTargetPrice: '', hasDownsideProtection: false }),
    'Single target price must be greater than 0.'
  );
  assert.equal(
    validateLadderConfig({ hasUpsideProtection: true, upsideMode: 'TRAILING', upsideTrailValue: '', hasDownsideProtection: false }),
    'Trailing profit offset value must be greater than 0.'
  );
});

test('enabled downside ladder whose rungs sum to 30% is still rejected with the original message', () => {
  assert.equal(
    validateLadderConfig({
      hasUpsideProtection: false, upsideMode: 'LADDER', rungs: [],
      hasDownsideProtection: true, downsideMode: 'LADDER',
      downsideRungs: [{ target_price: '50', percentage_of_total: 30 }],
    }),
    'Downside ladder rungs allocation must sum to 100% (currently 30.0%).'
  );
});

test('enabled downside SINGLE without price or offset and TRAILING without a value are rejected', () => {
  assert.equal(
    validateLadderConfig({ hasUpsideProtection: false, hasDownsideProtection: true, downsideMode: 'SINGLE', downsideTargetPrice: '', downsideOffsetPct: '' }),
    'Downside stop loss price or percentage is required.'
  );
  assert.equal(
    validateLadderConfig({ hasUpsideProtection: false, hasDownsideProtection: true, downsideMode: 'TRAILING', downsideTrailValue: '' }),
    'Downside trailing stop offset value must be greater than 0.'
  );
});

test('both sides enabled and valid passes', () => {
  assert.equal(
    validateLadderConfig({
      hasUpsideProtection: true, upsideMode: 'LADDER',
      rungs: [
        { target_price: '110', percentage_of_total: 50 },
        { target_price: '120', percentage_of_total: 50 },
      ],
      hasDownsideProtection: true, downsideMode: 'LADDER',
      downsideRungs: [{ target_price: '90', percentage_of_total: 100 }],
    }),
    null
  );
});
