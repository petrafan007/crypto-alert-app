import test from 'node:test';
import assert from 'node:assert/strict';
import { summarizeAccuracy } from '../frontend/src/utils/sentimentAccuracy.mjs';

test('successful Hold predictions do not invent directional accuracy', () => {
  const results = summarizeAccuracy([{ sentiment: 'Hold', outcome_status: 'correct', evaluation_method: 'fixed_horizon' }]);
  assert.equal(results.hold.rate, 100);
  assert.equal(results.directional.rate, null);
  assert.equal(results.bullish.evaluated, 0);
  assert.equal(results.bearish.evaluated, 0);
});
test('neutral, legacy, pending and unscored rows never inflate decisive win rates', () => {
  const results = summarizeAccuracy([
    { sentiment: 'Buy', outcome_status: 'correct', evaluation_method: 'fixed_horizon' },
    { sentiment: 'Buy', outcome_status: 'wrong', evaluation_method: 'fixed_horizon' },
    { sentiment: 'Buy', outcome_status: 'neutral', evaluation_method: 'fixed_horizon' },
    { sentiment: 'Sell', outcome_status: 'tracking', evaluation_method: 'fixed_horizon' },
    { sentiment: 'Buy', outcome_status: 'unscored', evaluation_method: 'fixed_horizon' },
    { sentiment: 'Buy', outcome_status: 'correct', evaluation_method: 'next_check' },
  ]);
  assert.equal(results.directional.rate, 50);
  assert.equal(results.directional.evaluated, 2);
  assert.equal(results.directional.neutral, 1);
  assert.equal(results.tracking, 1);
  assert.equal(results.unscored, 1);
});
