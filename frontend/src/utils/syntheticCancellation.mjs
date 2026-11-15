// A local strategy ID must be resolved before considering its broker.
export function syntheticCancellationEndpoint(order) {
  const id = String(order.order_id || order.orderId || order.id || '');
  const match = /^(ladder|trail)[_-](\d+)$/.exec(id);
  if (!match) return null;
  return `/api/trading/${match[1] === 'ladder' ? 'ladder' : 'trailing'}-orders/${match[2]}/cancel`;
}
