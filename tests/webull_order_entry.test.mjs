import assert from 'node:assert/strict';

import {
  accountLabel,
  allocationPercentage,
  floorCashAmountForTicket,
  floorQuantityForTicket,
  quantityDecimalPlaces,
  shouldUseEquityCashAmount,
} from '../frontend/src/utils/webullOrderEntry.mjs';

assert.equal(floorQuantityForTicket(0.317657, 5), '0.31765');
assert.equal(floorQuantityForTicket(0.31765, 5), '0.31765');
assert.equal(floorCashAmountForTicket(100.24), 100.24);
assert.equal(quantityDecimalPlaces('0.317657'), 6);
assert.equal(quantityDecimalPlaces('0.31765'), 5);
assert.equal(allocationPercentage(5.20, 100.24), 5.19);
assert.equal(allocationPercentage(100.24, 100.24), 100);
assert.equal(allocationPercentage(150, 100), 100);
assert.equal(allocationPercentage(5, 0), 0);

assert.equal(
  accountLabel({ account_label: 'Individual Cash', account_id: '12345678' }),
  'Individual Cash (••••5678)'
);
assert.equal(
  accountLabel({ account_name: 'Margin Account', account_id_masked: '••••9999' }),
  'Margin Account (••••9999)'
);
assert.equal(
  accountLabel(null, '87654321'),
  'Webull Account (••••4321)'
);

const aaplCashBuy = {
  instrumentType: 'EQUITY',
  side: 'BUY',
  orderType: 'MARKET',
  tradingSession: 'CORE',
  isAlgoEnabled: false,
  isBracketEnabled: false,
  dollars: 100.24,
  rawQuantity: 0.317657,
};
assert.equal(shouldUseEquityCashAmount(aaplCashBuy), true);
assert.equal(shouldUseEquityCashAmount({ ...aaplCashBuy, side: 'SELL' }), false);
assert.equal(shouldUseEquityCashAmount({ ...aaplCashBuy, tradingSession: 'ALL' }), false);
assert.equal(shouldUseEquityCashAmount({ ...aaplCashBuy, rawQuantity: 1.25 }), false);

import { sanitizeTotpCode, formatBufferPercent } from '../frontend/src/utils/webullOrderEntry.mjs';

assert.equal(sanitizeTotpCode('123456'), '123456');
assert.equal(sanitizeTotpCode('123 456'), '123456');
assert.equal(sanitizeTotpCode('123-456-789'), '123456');
assert.equal(sanitizeTotpCode('abc'), '');
assert.equal(sanitizeTotpCode(null), '');

assert.equal(formatBufferPercent('3.00'), '3.00');
assert.equal(formatBufferPercent('3'), '3.00');
assert.equal(formatBufferPercent('2.5'), '2.50');
assert.equal(formatBufferPercent(''), '3.00');
assert.equal(formatBufferPercent('-1'), '3.00');
assert.equal(formatBufferPercent('abc'), '3.00');

console.log('Webull order-entry regression checks passed.');
