import assert from 'node:assert/strict';
import test from 'node:test';
import { buildSyntheticReview, executionEstimate, money, priceInput, normalizeSyntheticQuantity } from '../frontend/src/utils/syntheticOrders.mjs';
const fees = { takerRate:.0002, rates:{ SELL:{taker:.0002,standardTaker:.0002,otherTaker:0}, BUY:{taker:.0002}}, bnb:{enabled:false}, quantityStep:'.00001' };
const config = { hasDownsideProtection:true, upsideMode:'LADDER', downsideMode:'LADDER', upsideRungs:[{target_price:110,percentage_of_total:33.33},{target_price:120,percentage_of_total:33.33},{target_price:130,percentage_of_total:33.34}], downsideRungs:[{target_price:95,percentage_of_total:30},{target_price:90,percentage_of_total:30},{target_price:85,percentage_of_total:40}] };
test('USD/USDT display exactly two decimals; non-dollar precision and quantity are retained',()=>{
  assert.equal(money(84747.54819999999,'USDT'),'84,747.55 USDT'); assert.equal(money(0,'USD'),'0.00 USD');
  assert.equal(money(.00000012,'BTC'),'0.00000012 BTC'); assert.equal(priceInput(90800.82899999),'90800.83');
  assert.equal(normalizeSyntheticQuantity(.01251477,.00001),.01251);
});
test('both directions allocate the broker-rounded quantity and compute each fee and cumulative net',()=>{
  const review=buildSyntheticReview(config,{quantity:.01251477,currentPrice:100,fees});
  for(const b of review.branches){ assert.ok(Math.abs(b.rows.reduce((n,r)=>n+r.quantity,0)-.01251)<1e-12);
    let gross=0, fee=0;for(const r of b.rows){gross+=r.quantity*r.price; fee+=r.quantity*r.price*.0002;assert.equal(r.cumulativeGross,gross);assert.equal(r.cumulativeFee,fee);assert.ok(Math.abs(r.cumulativeNet-(gross-fee))<1e-12);}}
  assert.deepEqual(review.branches[0].rows.map(r=>r.quantity),[.00416,.00416,.00419]);
});
test('all side and mode combinations explain mirrored conditions and shared remainders',()=>{
 for(const side of ['BUY','SELL'])for(const up of ['SINGLE','LADDER','TRAILING'])for(const down of ['SINGLE','LADDER','TRAILING']){
  const r=buildSyntheticReview({...config,upsideMode:up,downsideMode:down,upsideTargetPrice:110,downsideTargetPrice:90,upsideTrailValue:2,downsideTrailValue:3},{side,quantity:10,currentPrice:100,fees});
  assert.equal(r.branches.length,2);for(const b of r.branches){assert.ok(b.explanation.length>60); assert.ok(b.rows.length>0);assert.ok(b.rows.reduce((n,row)=>n+row.quantity,0)<=10.000000001);}
 }
});
test('activation hurdle determines the peak/trough scenario, and trail math mirrors BUY',()=>{
 const sell=buildSyntheticReview({...config,upsideMode:'TRAILING',upsideTrailValue:2,upsideActivationPrice:200},{quantity:10,currentPrice:100,fees}).branches[0];
 assert.equal(sell.rows[0].price,196); assert.equal(sell.rows[0].gross,1960); assert.equal(sell.rows[0].net,1959.608); assert.match(sell.explanation,/has not reached/); assert.match(sell.explanation,/200.00 USD/);
 const buy=buildSyntheticReview({...config,upsideMode:'TRAILING',upsideTrailValue:2,upsideActivationPrice:80},{side:'BUY',quantity:10,currentPrice:100,fees}).branches[0];
 assert.equal(buy.rows[0].price,81.6);assert.match(buy.explanation,/minimum/);
 const immediate=buildSyntheticReview({...config,upsideMode:'TRAILING',upsideTrailType:'AMOUNT',upsideTrailValue:5,upsideActivationPrice:80},{quantity:10,currentPrice:100,fees}).branches[0]; assert.equal(immediate.rows[0].price,95);
});
test('cancel-only does not invent a sale or commission; disabled protection has no triggers',()=>{
 const r=buildSyntheticReview({...config,downsideMode:'SINGLE',downsideTargetPrice:95,downsideStopAction:'CANCEL_REMAINING'},{quantity:10,currentPrice:100,fees});assert.equal(r.branches[1].rows.length,0);assert.match(r.branches[1].explanation,/without placing a trade/);
 assert.equal(buildSyntheticReview({...config,hasDownsideProtection:false}).branches[1].mode,'NONE');
});
test('zero fees remain zero; missing fees stay unknown; BNB discount applies only to standard fees',()=>{
 assert.equal(executionEstimate(10,100,'SELL',{takerRate:0,bnb:{enabled:false}}).net,1000);
 assert.equal(executionEstimate(10,100,'SELL',null).fee,null);
 const r=executionEstimate(10,100,'SELL',{rates:{SELL:{taker:.0003,standardTaker:.0002,otherTaker:.0001}},bnb:{enabled:true,discountFraction:.05}});
 assert.ok(Math.abs(r.bnbFee-.29)<1e-12);assert.equal(r.fee,.3);
 assert.ok(Math.abs(executionEstimate(10,100,'BUY',fees).netQuantity-9.998)<1e-12);
});
