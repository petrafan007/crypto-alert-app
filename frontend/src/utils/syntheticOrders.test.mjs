import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSyntheticPayload, strategyKind, matchesStatus, number, trailLabel, orderKey, strategySummary, syntheticOrderTooltip } from './syntheticOrders.mjs';
const config = { hasDownsideProtection: true, upsideMode: 'LADDER', upsidePreset: 'CUSTOM', upsideRungs: [{ target_price: '123.12345678', price_offset_pct: 23, percentage_of_total: 100 }], downsideMode: 'TRAILING', downsideTrailValue: '5', downsideTrailType: 'AMOUNT', downsideActivationPrice: '120' };
test('preserves protection, custom target precision, allocation and dollar trail units', () => {
  const payload = buildSyntheticPayload(config);
  assert.equal(payload.downside_mode, 'TRAILING'); assert.equal(payload.has_stop_loss, true);
  assert.equal(payload.custom_rungs[0].target_price, 123.12345678); assert.equal(payload.custom_rungs[0].percentage_of_total, 100);
  assert.equal(payload.downside_trail_type, 'AMOUNT'); assert.equal(payload.downside_activation_price, 120);
  assert.match(strategySummary(config)[1], /5\.00 USD/);
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
  assert.equal(trailLabel(5, 'AMOUNT'), '5.00 USD'); assert.equal(trailLabel(5, 'PERCENT'), '5%');
  assert.notEqual(orderKey({ parentKind: 'LADDER', id: 1 }), orderKey({ parentKind: 'TRAILING', id: 1 }));
});

test('portfolio bracket tooltip includes both branches, progress, units and next pending steps', () => {
  const text = syntheticOrderTooltip({type:'LADDER',asset:'BTC',synthetic_details:{broker:'binance',symbol:'BTCUSDT',side:'SELL',status:'ACTIVE',total_quantity:.01251,filled_quantity:.00312,remaining_quantity:.00939,upside_mode:'LADDER',downside_mode:'LADDER',rungs:[
    {rung_number:1,rung_type:'TAKE_PROFIT',status:'FILLED',target_price:90515.26,quantity:.00312},
    {rung_number:2,rung_type:'TAKE_PROFIT',status:'PENDING',target_price:94825.51,quantity:.00312},
    {rung_number:5,rung_type:'STOP_LOSS',status:'PENDING',target_price:84480.91,quantity:.00416}
  ]}});
  assert.match(text,/Smart bracket SELL/);assert.match(text,/Remaining 0.00939/);
  assert.match(text,/Profit: 1\/2 steps filled · next ≥ 94,825.51 USDT/);
  assert.match(text,/Protection: 0\/1 steps filled · next ≤ 84,480.91 USDT/);
  assert.ok(text.length<450);
});
test('portfolio tooltip mirrors BUY, identifies Webull and includes amount trail activation and cancel-only', () => {
 const text=syntheticOrderTooltip({type:'LADDER',asset:'SPY',synthetic_details:{broker:'webull',symbol:'SPY',side:'BUY',status:'ACTIVE',total_quantity:10,filled_quantity:0,remaining_quantity:10,upside_mode:'TRAILING',upside_trail_type:'AMOUNT',upside_trail_value:5,upside_activation_price:90,upside_current_stop_price:95,downside_mode:'SINGLE',downside_target_price:90,stop_loss_action:'CANCEL_REMAINING'}});
 assert.match(text,/Webull/);assert.match(text,/trail 5.00 USD/);assert.match(text,/activation ≤ 90.00 USD/);assert.match(text,/Dip entry: ≤ 90.00 USD · cancel remainder only/);
});

test('BUY breakout and dip tooltip arrows follow market direction', () => {
 const text = syntheticOrderTooltip({asset:'BTC',synthetic_details:{broker:'binance',symbol:'BTCUSDT',side:'BUY',status:'ACTIVE',total_quantity:1,filled_quantity:0,remaining_quantity:1,upside_mode:'SINGLE',upside_target_price:110,downside_mode:'SINGLE',downside_target_price:90}});
 assert.match(text,/Breakout entry: ≥ 110.00 USDT/);
 assert.match(text,/Dip entry: ≤ 90.00 USDT/);
});

test('conditional strategies are described by their legs and phase, not as a ladder (F16)', () => {
  const legs = [{ side: 'BUY', order_type: 'LIMIT', price: 160 }, { side: 'SELL', order_type: 'LIMIT', price: 175 }, { side: 'SELL', order_type: 'STOP_LOSS', stop_price: 150 }];
  const details = { broker: 'webull', symbol: 'NVDA', side: 'BUY', status: 'ACTIVE', strategy_type: 'OTOCO', total_quantity: 10, filled_quantity: 0,
    remaining_quantity: 10, upside_mode: 'NONE', downside_mode: 'NONE', trading_session: 'ALL', conditional_phase: 'ENTRY', conditional_spec: { legs } };
  const entry = syntheticOrderTooltip({ type: 'LADDER', asset: 'NVDA', synthetic_details: details });
  assert.match(entry, /^OTOCO \(entry, then one-cancels-the-other exits\) BUY · Webull · synthetic · ACTIVE/);
  assert.match(entry, /Entry: BUY limit ≤ 160\.00 USD/);
  assert.match(entry, /After the entry fills: SELL limit ≥ 175\.00 USD · SELL stop ≤ 150\.00 USD/);
  assert.doesNotMatch(entry, /Ladder|Breakout entry: off|Dip entry: off/);

  const exit = syntheticOrderTooltip({ type: 'LADDER', asset: 'NVDA', synthetic_details: { ...details, side: 'SELL', conditional_phase: 'EXIT', filled_quantity: 0, total_quantity: 6, remaining_quantity: 6 } });
  assert.match(exit, /Exit: SELL limit ≥ 175\.00 USD/); assert.match(exit, /Exit: SELL stop ≤ 150\.00 USD/);
  assert.match(exit, /Only one of these can execute/);

  // The server's own leg list for the current phase takes precedence.
  const oco = syntheticOrderTooltip({ type: 'LADDER', asset: 'NVDA',
    legs: [{ side: 'BUY', order_type: 'LIMIT', price: 100 }, { side: 'BUY', order_type: 'STOP_LOSS_LIMIT', stop_price: 110, price: 111 }], waiting_legs: [],
    synthetic_details: { ...details, strategy_type: 'OCO', conditional_phase: 'SINGLE', trading_session: 'CORE' } });
  assert.match(oco, /^OCO \(one cancels the other\) BUY/);
  assert.match(oco, /Trigger: BUY limit ≤ 100\.00 USD/);
  assert.match(oco, /Trigger: BUY stop limit ≥ 110\.00 USD \(limit 111\.00 USD\)/);
  assert.match(oco, /regular market hours/);
});
