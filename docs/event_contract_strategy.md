# Webull Event Contract Strategy Engine

The v2.79 engine is intentionally paper-only and signal-only. It records
the market evidence needed to decide whether an Event Contract strategy has a
repeatable edge before any automatic execution is considered.

## Safety boundary

- The engine hard-codes `PAPER` mode and cannot switch to live execution.
- `signals_only` is forced on by configuration normalization.
- The scanner never calls the live Webull order endpoint or the ordinary order
  placement flow.
- Starting the worker requires Webull paper/test mode to be enabled in CSD.
- A persisted kill switch disables new strategy entries and survives restarts.

## Current workflow

1. Configure BTC/ETH and the event durations to study.
2. Run a one-shot scan or start the persisted background paper worker.
3. Fetch the current Webull catalog and verified quotes through the existing
   Event Contract service.
4. Store normalized market snapshots with provider and receive timestamps.
5. Evaluate each contract using explicit quote, freshness, liquidity, time,
   edge, and confidence gates.
6. Ask the configured AI cascade (primary, then secondary, then tertiary) for
   a strict YES probability and confidence estimate. Each attempt, selected
   tier/model, response status, and bounded rationale are stored with the
   decision; missing or malformed responses are rejected rather than treated as
   a probability.
7. Persist a decision trace with a human-readable question, underlying,
   duration, condition, cutoff, and model provenance. A failed cascade produces
   `AI_PROVIDER_ERROR` or `AI_RESPONSE_INVALID`; a quote-less market is skipped
   without spending an AI call.
8. Resolve expired contracts only from explicit Webull settlement fields. If
   Webull has not published a result, the record remains `PENDING`.
9. Optionally create hypothetical fills for eligible signals and review their
   settled paper performance. This never calls an order-placement endpoint.

## Cadence, cache, and reliability controls

The Settings → Event Contract Strategy Engine tab exposes independent controls
for snapshot collection, worker scans, AI batch spacing, batch size, hourly AI
budget, prediction-cache TTL, search/context refresh, retry backoff, and a
separate cooldown for each configured contract duration. Snapshots continue to
be collected even when AI calls are throttled. A successful prediction is reused
only while its material-market fingerprint and cache TTL remain valid; failed
providers are retried with exponential backoff and never become a trade signal.

The persisted supervisor watches each paper worker heartbeat. A stale heartbeat
marks the worker degraded, writes an `EventStrategyLog` record, emits a
rate-limited toast, and lets the supervisor reacquire the scan on its next
iteration. The application service remains managed by systemd with
`Restart=always`, so a process crash is also restarted automatically.

## HTTP API

- `GET/PUT /api/webull/event-algo/config`
- `GET /api/webull/event-algo/status`
- `GET /api/webull/event-algo/logs`
- `POST /api/webull/event-algo/start`
- `POST /api/webull/event-algo/stop`
- `POST /api/webull/event-algo/kill-switch`
- `POST /api/webull/event-algo/scan`
- `GET /api/webull/event-algo/decisions`
- `GET /api/webull/event-algo/opportunities`
- `POST /api/webull/event-algo/resolve`
- `POST /api/webull/event-algo/simulate`
- `GET /api/webull/event-algo/performance`

## Evidence gate before execution

The AI output is still an advisory probability, not a guarantee. Automatic
paper orders remain disabled until the model has enough forward observations to
evaluate net expectancy, profit factor, calibration, drawdown, fill quality,
and stability across 15-minute and hourly contracts. A positive return alone is
not sufficient.
