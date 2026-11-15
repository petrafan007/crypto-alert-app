import assert from 'node:assert/strict';
import { test } from 'node:test';
import { reservedByOrders, binanceCashReservation, webullCashReservation, describeCashReservation, orderCost } from '../frontend/src/utils/cashReservations.mjs';

const buy = (order_id, quantity_usdt, extra = {}) => ({ order_id, provider: 'webull', account_id: 'A', symbol: 'NVDA', side: 'BUY', quantity_usdt, ...extra });

test('a synthetic strategy and the broker order it submitted hold cash once (F13)', () => {
  const strategy = buy('ladder_21', 1000, { is_synthetic: true, is_ladder: true });
  const child = buy('900', 1010, { synthetic_parent_id: 'ladder_21' });
  assert.deepEqual(reservedByOrders([strategy, child]), { exchange: 0, synthetic: 1010 }, 'the larger of the two figures, not their sum');
  // One step of a larger strategy is already inside the strategy's remainder.
  assert.deepEqual(reservedByOrders([strategy, buy('901', 300, { synthetic_parent_id: 'ladder_21' })]), { exchange: 0, synthetic: 1000 });
  // The same symbol, size and price without a journal link is a separate order.
  assert.deepEqual(reservedByOrders([strategy, buy('902', 1000)]), { exchange: 1000, synthetic: 1000 });
  // A linked order whose strategy is not in the list is still a real broker order.
  assert.deepEqual(reservedByOrders([child]), { exchange: 1010, synthetic: 0 });
});

test('alternative legs of one broker group hold the most expensive branch (F14)', () => {
  const oco = [buy('1', 500, { group_id: 'webull-combo-x', group_role: 'exclusive' }), buy('2', 520, { group_id: 'webull-combo-x', group_role: 'exclusive' })];
  assert.deepEqual(reservedByOrders(oco), { exchange: 520, synthetic: 0 });
  // An entry plus its alternative follow-on legs: the entry adds to one branch.
  const otoco = [buy('3', 400, { group_id: 'g', group_role: 'independent' }), ...oco.map(order => ({ ...order, group_id: 'g' }))];
  assert.deepEqual(reservedByOrders(otoco), { exchange: 920, synthetic: 0 });
  // Two separate groups and a plain order all stand on their own.
  assert.deepEqual(reservedByOrders([...oco, buy('4', 100, { group_id: 'other', group_role: 'exclusive' }), buy('5', 50)]), { exchange: 670, synthetic: 0 });
  // Older Binance.US rows identify an OCO pair by list id only.
  const binance = [{ order_id: 1, provider: 'binance', symbol: 'BTCUSDT', side: 'BUY', quantity_usdt: 200, orderListId: 7 },
    { order_id: 2, provider: 'binance', symbol: 'BTCUSDT', side: 'BUY', quantity_usdt: 210, orderListId: 7 },
    { order_id: 3, provider: 'binance', symbol: 'ETHUSDT', side: 'BUY', quantity_usdt: 40, orderListId: -1 }];
  assert.deepEqual(reservedByOrders(binance), { exchange: 250, synthetic: 0 });
});

test('cost uses the unfilled remainder, and sells hold no cash (F15)', () => {
  assert.equal(orderCost({ quantity: 6, price: 10 }), 60, 'remaining quantity x price when no figure is supplied');
  assert.equal(orderCost({ quantity: 6, price: 10, quantity_usdt: 0 }), 0);
  assert.deepEqual(reservedByOrders([{ ...buy('9', 500), side: 'SELL' }]), { exchange: 0, synthetic: 0 });
});

test('reservations are scoped to one quote currency or one Webull account, and kinds stay separate (F19)', () => {
  const orders = [
    { order_id: 1, provider: 'binance', symbol: 'BTCUSDT', side: 'BUY', quantity_usdt: 100 },
    { order_id: 2, provider: 'binance', symbol: 'BTCUSD', side: 'BUY', quantity_usdt: 70 },
    { order_id: 'ladder_3', provider: 'binance', symbol: 'ETHUSDT', side: 'BUY', quantity_usdt: 30, is_ladder: true },
    buy('4', 900), buy('5', 50, { account_id: 'B' }),
  ];
  const rows = [{ symbol: 'SOL', auto_buy_enabled: true, auto_buy_amount: 25, auto_buy_quote_currency: 'USDT' },
    { symbol: 'ADA', auto_buy_enabled: true, auto_buy_amount: 10, auto_buy_quote_currency: 'USD' },
    { symbol: 'XRP', auto_buy_enabled: false, auto_buy_amount: 999, auto_buy_quote_currency: 'USDT' }];
  assert.deepEqual(binanceCashReservation('USDT', orders, rows), { exchange: 100, synthetic: 30, automation: 25, total: 155 });
  assert.deepEqual(binanceCashReservation('USD', orders, rows), { exchange: 70, synthetic: 0, automation: 10, total: 80 });
  assert.deepEqual(webullCashReservation('A', orders), { exchange: 900, synthetic: 0, automation: 0, total: 900 });
  assert.deepEqual(webullCashReservation(null, orders), { exchange: 950, synthetic: 0, automation: 0, total: 950 });
  assert.equal(describeCashReservation(845, binanceCashReservation('USDT', orders, rows), 'USDT'),
    '845.00 USDT available · 100.00 USDT held by open broker orders · 30.00 USDT held for synthetic strategies being monitored · 25.00 USDT set aside for auto-buy');
  assert.equal(describeCashReservation(10, { exchange: 0, synthetic: 0, automation: 5, total: 5 }), '10.00 USD available · 5.00 USD set aside for auto-buy');
});
