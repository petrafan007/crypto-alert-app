import assert from 'node:assert/strict';
import test from 'node:test';

import {
  isNonTradableWebullCashAsset,
  normalizeWebullTradeSymbol,
  webullInstrumentTypeForAsset,
  webullTradeTargetForAsset,
} from './webullTradeNavigation.mjs';

test('keeps an AAPL Webull equity deep link intact', () => {
  const asset = { symbol: 'aapl', instrument_type: 'EQUITY', source: 'webull' };

  assert.equal(isNonTradableWebullCashAsset(asset), false);
  assert.equal(webullInstrumentTypeForAsset(asset), 'EQUITY');
  assert.deepEqual(webullTradeTargetForAsset(asset), {
    symbol: 'AAPL',
    instrumentType: 'EQUITY',
  });
});

test('does not turn an imported Webull USD balance into an equity order target', () => {
  const cash = { id: 'webull-5', symbol: 'USD', instrument_type: 'CASH', source: 'webull' };

  assert.equal(isNonTradableWebullCashAsset(cash), true);
  assert.equal(webullInstrumentTypeForAsset(cash), null);
  assert.equal(webullTradeTargetForAsset(cash), null);
  assert.equal(normalizeWebullTradeSymbol('USD', 'EQUITY'), '');
});

test('retains valid Webull crypto pairs while rejecting malformed symbols', () => {
  assert.equal(normalizeWebullTradeSymbol('BTCUSD', 'CRYPTO'), 'BTCUSD');
  assert.equal(normalizeWebullTradeSymbol('AAPL&side=SELL', 'EQUITY'), '');
});
