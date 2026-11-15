import assert from 'node:assert/strict';
import { syntheticCancellationEndpoint } from '../frontend/src/utils/syntheticCancellation.mjs';
assert.equal(syntheticCancellationEndpoint({order_id:'ladder_21',provider:'webull'}), '/api/trading/ladder-orders/21/cancel');
assert.equal(syntheticCancellationEndpoint({order_id:'trail_9',source:'webull'}), '/api/trading/trailing-orders/9/cancel');
assert.equal(syntheticCancellationEndpoint({orderId:'ladder-21'}), '/api/trading/ladder-orders/21/cancel');
assert.equal(syntheticCancellationEndpoint({order_id:'broker-client-id',provider:'webull'}), null);
console.log('Dashboard synthetic cancellation routing passed.');
