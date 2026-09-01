import assert from 'node:assert/strict';
import test from 'node:test';

import {
  EVENT_SEARCH_DEBOUNCE_MS,
  createEventCatalogPoller,
} from './eventCatalogPolling.mjs';

function createFakeTimers() {
  let nextId = 1;
  const scheduled = new Map();
  return {
    setTimer(callback, delay) {
      const id = nextId++;
      scheduled.set(id, { callback, delay });
      return id;
    },
    clearTimer(id) {
      scheduled.delete(id);
    },
    async runNext() {
      const next = scheduled.entries().next().value;
      assert.ok(next, 'expected a scheduled timer');
      const [id, timer] = next;
      scheduled.delete(id);
      timer.callback();
      await Promise.resolve();
      await Promise.resolve();
    },
    get size() {
      return scheduled.size;
    },
    nextDelay() {
      return scheduled.entries().next().value?.[1].delay;
    },
  };
}

test('polls until the catalog response is complete, then clears its timer', async () => {
  const timers = createFakeTimers();
  const requests = [];
  const responses = [{ loading: true }, { loading: true }, { loading: false }];
  const poller = createEventCatalogPoller(
    (params) => {
      requests.push(params);
      return responses.shift();
    },
    { setTimer: timers.setTimer, clearTimer: timers.clearTimer },
  );

  poller.start({ category: 'CRYPTO', query: 'btc' }, EVENT_SEARCH_DEBOUNCE_MS);
  assert.equal(timers.nextDelay(), EVENT_SEARCH_DEBOUNCE_MS);
  await timers.runNext();
  assert.equal(timers.nextDelay(), 1_500);
  await timers.runNext();
  assert.equal(timers.nextDelay(), 3_000);
  await timers.runNext();

  assert.equal(requests.length, 3);
  assert.deepEqual(requests[2], { category: 'CRYPTO', query: 'btc' });
  assert.equal(timers.size, 0);
});

test('only sends the final query after a debounced search input sequence', async () => {
  const timers = createFakeTimers();
  const requests = [];
  const poller = createEventCatalogPoller(
    (params) => {
      requests.push(params.query);
      return { loading: false };
    },
    { setTimer: timers.setTimer, clearTimer: timers.clearTimer },
  );

  poller.start({ query: 'b' }, EVENT_SEARCH_DEBOUNCE_MS);
  poller.start({ query: 'bt' }, EVENT_SEARCH_DEBOUNCE_MS);
  poller.start({ query: 'btc' }, EVENT_SEARCH_DEBOUNCE_MS);
  assert.equal(timers.size, 1);
  await timers.runNext();

  assert.deepEqual(requests, ['btc']);
  assert.equal(timers.size, 0);
});

test('stops timers and aborts stale requests when polling is replaced or stopped', async () => {
  const timers = createFakeTimers();
  let resolveFirstRequest;
  let firstSignal;
  const requests = [];
  const poller = createEventCatalogPoller(
    (params, { signal }) => {
      requests.push(params.query);
      if (params.query === 'old') {
        firstSignal = signal;
        return new Promise((resolve) => { resolveFirstRequest = resolve; });
      }
      return { loading: true };
    },
    { setTimer: timers.setTimer, clearTimer: timers.clearTimer },
  );

  poller.start({ query: 'old' });
  await timers.runNext();
  poller.start({ query: 'new' });
  assert.equal(firstSignal.aborted, true);
  await timers.runNext();
  poller.stop();
  resolveFirstRequest({ loading: true });
  await Promise.resolve();
  await Promise.resolve();

  assert.deepEqual(requests, ['old', 'new']);
  assert.equal(timers.size, 0);
});

test('does not schedule another poll after a request error or exhausted retry budget', async () => {
  const timers = createFakeTimers();
  let errorCount = 0;
  const errorPoller = createEventCatalogPoller(
    () => Promise.reject(new Error('network unavailable')),
    { setTimer: timers.setTimer, clearTimer: timers.clearTimer, onError: () => { errorCount += 1; } },
  );
  errorPoller.start({ query: 'btc' });
  await timers.runNext();
  assert.equal(errorCount, 1);
  assert.equal(timers.size, 0);

  let exhausted = 0;
  const boundedPoller = createEventCatalogPoller(
    () => ({ loading: true }),
    { setTimer: timers.setTimer, clearTimer: timers.clearTimer, maxAttempts: 1, onExhausted: () => { exhausted += 1; } },
  );
  boundedPoller.start({ query: 'btc' });
  await timers.runNext();
  await timers.runNext();
  assert.equal(exhausted, 1);
  assert.equal(timers.size, 0);
});