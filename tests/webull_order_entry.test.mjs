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

import {
  cashAmountCarry,
  quoteBlurCashAmount,
  quoteValueEntry,
} from '../frontend/src/utils/webullOrderEntry.mjs';

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


// Typing a dollar value keeps every keystroke verbatim (regression: the
// old mid-typing flip to cash-amount mode swapped the rendered input and
// swallowed a digit — "500" arrived as "50").
const antPrice = 101.23;
const typedSteps = ['5', '50', '500'].map((rawValue) => quoteValueEntry({
  rawValue, instrumentType: 'EQUITY', price: antPrice, fractionalQuantityAllowed: true,
}));
assert.deepEqual(typedSteps.map((s) => s.quoteVal), ['5', '50', '500']);
assert.equal(typedSteps[2].computedQty, '4.93924');

// The cash conversion is decided on the completed value at blur: $500 at
// $101.23 buys more than one share, so it stays a shares entry...
const blurCtx = {
  instrumentType: 'EQUITY', side: 'BUY', orderType: 'MARKET',
  tradingSession: 'CORE', isAlgoEnabled: false, isBracketEnabled: false,
  price: antPrice,
};
assert.equal(quoteBlurCashAmount({ ...blurCtx, quoteQuantity: '500' }), null);
// ...while a genuine sub-share amount converts, carrying the typed text.
assert.equal(quoteBlurCashAmount({ ...blurCtx, quoteQuantity: '50' }), '50');
assert.equal(quoteBlurCashAmount({ ...blurCtx, quoteQuantity: '50', orderType: 'LIMIT' }), null);
assert.equal(quoteBlurCashAmount({ ...blurCtx, quoteQuantity: '' }), null);

// Manual mode switch: a typed value always wins over the $25.00 default.
assert.equal(cashAmountCarry({ totalCashAmount: '', quoteQuantity: '3' }), '3');
assert.equal(cashAmountCarry({ totalCashAmount: '', quoteQuantity: '500' }), '500');
assert.equal(cashAmountCarry({ totalCashAmount: '75.00', quoteQuantity: '3' }), '75.00');
assert.equal(cashAmountCarry({ totalCashAmount: '', quoteQuantity: '' }), '25.00');

console.log('Webull order-entry regression checks passed.');
