// One cycle owns all dashboard snapshot reads. Mutations invalidate even reads
// whose transport ignores AbortSignal; repeated refresh requests coalesce.
export function createDashboardRefreshCoordinator(run, onError = console.error) {
  let generation = 0;
  let sequence = 0;
  let stopped = false;
  let running = null;
  let queued = false;
  let controller;

  function request({ invalidate = false } = {}) {
    if (stopped) return Promise.resolve();
    if (invalidate) {
      generation += 1;
      controller?.abort();
    }
    queued = true;
    if (!running) {
      running = Promise.resolve().then(async () => {
        while (queued && !stopped) {
          queued = false;
          controller = new AbortController();
          const startedGeneration = generation;
          const signal = controller.signal;
          const ticket = {
            id: ++sequence,
            generation: startedGeneration,
            signal,
            isCurrent: () => !stopped && !signal.aborted && generation === startedGeneration,
          };
          try {
            await run(ticket);
          } catch (error) {
            if (ticket.isCurrent()) onError(error);
          }
        }
      }).finally(() => {
        running = null;
        if (queued && !stopped) request();
      });
    }
    return running;
  }

  return {
    request,
    stop() {
      stopped = true;
      generation += 1;
      queued = false;
      controller?.abort();
    },
  };
}

const provider = order => String(order.provider || order.source || order.exchange || 'binance').toLowerCase();
const account = order => String(order.account_id ?? order._webull_account_id ?? order.webull_account_id ?? '');
const primaryId = order => String(order.order_id ?? order.orderId ?? order.id ?? '');
const synthetic = order => /^(ladder|trail)[_-]\d+$/.test(primaryId(order));

// Missing scope is never a wildcard. IDs/aliases are comparable only inside
// the same provider/account/environment and synthetic/native namespace.
export function sameDashboardOrder(a, b) {
  if (provider(a) !== provider(b) || account(a) !== account(b)
    || String(a.environment || '') !== String(b.environment || '')
    || Boolean(a.test_mode) !== Boolean(b.test_mode) || synthetic(a) !== synthetic(b)) return false;
  if (provider(a) === 'binance' && String(a.symbol || '').toUpperCase() !== String(b.symbol || '').toUpperCase()) return false;
  const aliases = order => [primaryId(order), order.client_order_id, order.clientOrderId]
    .filter(value => value !== undefined && value !== null && String(value) !== '').map(String);
  const ids = new Set(aliases(a));
  return aliases(b).some(id => ids.has(id));
}

export function cancellationOutcome(data) {
  if (data?.success !== true) return 'failed';
  const status = String(data.ladder_order?.status || data.trailing_order?.status || data.status || data.order?.status || '').toUpperCase();
  if (['CANCELLED', 'CANCELED'].includes(status)) return 'confirmed';
  if (['REJECTED', 'FAILED', 'ERROR'].includes(status)) return 'failed';
  // Success without a final state is an acknowledgement, not proof that the
  // broker has stopped working the order. The next read reconciles it.
  return 'pending';
}

export function recentFillRevision(order, now = Date.now()) {
  if (String(order.status).toUpperCase() !== 'FILLED' || !primaryId(order)) return null;
  const time = order.filled_time || order.updated_time || order.created_time;
  const timestamp = Date.parse(time);
  if (!Number.isFinite(timestamp) || timestamp < now - 5 * 60 * 1000 || timestamp > now) return null;
  return JSON.stringify([provider(order), account(order), order.environment, Boolean(order.test_mode),
    order.symbol, primaryId(order), order.executedQty ?? order.filled_quantity ?? order.quantity, time]);
}
