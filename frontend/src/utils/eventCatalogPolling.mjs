export const EVENT_SEARCH_DEBOUNCE_MS = 600;
export const EVENT_CATALOG_POLL_INITIAL_DELAY_MS = 1_500;
export const EVENT_CATALOG_POLL_MAX_DELAY_MS = 15_000;
export const EVENT_CATALOG_POLL_MAX_ATTEMPTS = 6;

export function createEventCatalogPoller(request, options = {}) {
  const setTimer = options.setTimer || window.setTimeout.bind(window);
  const clearTimer = options.clearTimer || window.clearTimeout.bind(window);
  const createAbortController = options.createAbortController || (() => new AbortController());
  const maxAttempts = options.maxAttempts || EVENT_CATALOG_POLL_MAX_ATTEMPTS;
  let timer = null;
  let controller = null;
  let generation = 0;
  let pollAttempts = 0;

  const clearScheduledPoll = () => {
    if (timer !== null) {
      clearTimer(timer);
      timer = null;
    }
  };

  const stop = () => {
    generation += 1;
    clearScheduledPoll();
    controller?.abort();
    controller = null;
  };

  const start = (params, initialDelay = 0) => {
    stop();
    const activeGeneration = generation;
    pollAttempts = 0;

    const schedule = (delay) => {
      clearScheduledPoll();
      timer = setTimer(() => {
        timer = null;
        run();
      }, delay);
    };

    const run = () => {
      if (activeGeneration !== generation) return;
      const activeController = createAbortController();
      controller = activeController;
      Promise.resolve(request(params, { signal: activeController.signal }))
        .then((result) => {
          if (controller === activeController) controller = null;
          if (activeGeneration !== generation || activeController.signal.aborted || !result?.loading) return;
          if (pollAttempts >= maxAttempts) {
            options.onExhausted?.();
            return;
          }
          pollAttempts += 1;
          schedule(Math.min(
            EVENT_CATALOG_POLL_INITIAL_DELAY_MS * (2 ** (pollAttempts - 1)),
            EVENT_CATALOG_POLL_MAX_DELAY_MS,
          ));
        })
        .catch((error) => {
          if (controller === activeController) controller = null;
          if (activeGeneration !== generation || activeController.signal.aborted) return;
          options.onError?.(error);
        });
    };

    schedule(initialDelay);
  };

  return { start, stop };
}