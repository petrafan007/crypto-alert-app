import assert from 'node:assert/strict';

import {
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

console.log('Webull order-entry regression checks passed.');
