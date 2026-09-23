# Jev decision engine — v4.0.0

Jev is a separate, opt-in TypeSafe evaluation subsystem using Vercel AI Gateway. It consumes existing market prices, computed strategy features and retrieved news; it neither browses nor computes authoritative indicators. Generative AI configurations remain independent.

## Configure it

1. Open **Settings → AI Providers & Models → Jev Decision Engine (Experimental)**.
2. Choose **Vercel AI Gateway**, keep model **typesafe-ai/jev**, and enter your **Vercel AI Gateway API key**. The application's credential encryption must already be configured, as for other provider keys.
3. Click **Save Jev Settings**, then **Test Jev Connection**. Testing sends one small evaluation and can incur provider charges. The saved key is masked; saving the mask preserves it. Clear the field and save to remove the key.
4. Turn on **Enable Jev**. Select **Shadow** for sentiment comparisons and/or **Enable quant shadow observations**, then save. Sentiment runs also require the application's main AI toggle. Quant observations require an operating crypto quant scan.
5. Inspect recent evaluations in the Jev card or **Quantitative Strategy Engine → Jev quant shadow research**. The background worker processes the durable queue; ordinary sentiment refreshes and quant scans produce observations.
6. To use accepted Jev sentiment, select **Jev-first**. Keep generative fallback enabled unless explicit failures are preferable to generative calls. Low direction probability, low reported confidence, conflicted evidence, missing evidence/price, malformed replies, and unavailable providers abstain. Existing primary/fallback generative settings handle escalation.

Everything defaults to off. The dedicated Save button updates only Jev configuration and does not require entering unrelated exchange credentials. Settings and connection testing are authenticated and use the current user's stored key. No key is sent back to the browser. Paper gating is unavailable in this version, including through crafted settings requests.

## Contracts and storage

The native HTTP endpoint is `https://ai-gateway.vercel.sh/v1/evaluate`, with a map of named questions and model `typesafe-ai/jev`. All six questions for a use case share one request. Vercel Choice probabilities and separate TypeSafe confidence metadata remain distinct. Scores are interpolated on a zero-based wire scale; the UI and deterministic reason convert to 1–5. The client requests zero data retention, disallows redirects, retries transient failures at most once within the configured timeout budget, and applies a process-local failure cooldown. Provider error bodies are never exposed.

References: [Vercel HTTP evaluation API](https://vercel.com/docs/ai-gateway/modalities/evaluation#http-api), [TypeSafe confidence metadata](https://vercel.com/changelog/typesafe-ai-jev-now-available-on-ai-gateway).

New files: `services/jev_service.py`, `jev_contracts.py`, `jev_settings.py`, `jev_evaluations.py`, `jev_sentiment.py`, `jev_quant_overlay.py`, and `jev_outcomes.py`. The native transport avoids a JavaScript SDK dependency in the Python backend.

`JevEvaluation` stores bounded canonical state, SHA-256 state hash, state/question versions, model/provider, probabilities/confidence, usage/reported cost, latency, failure/abstention status, timestamps, frozen settings, baseline quant decisions and links to sentiment history or external Webull signals. API keys and full account/article payloads are excluded. Raw provider responses exist only in the client result, not in durable records.

Additive startup migration in `database.py` creates `jev_evaluations` and its indexes, adds `credentials.ai_gateway_key`, and adds these `user_settings` columns:

| Setting | Default |
|---|---|
| `jev_enabled` | false |
| `jev_transport` | vercel |
| `jev_model` | typesafe-ai/jev |
| `jev_endpoint` | Vercel `/v1/evaluate` |
| `jev_timeout_seconds` | 3.0 |
| `jev_confidence_threshold` | 0.80 |
| `jev_conflict_threshold` | 0.50 |
| `jev_sentiment_mode` | off (`off`, `shadow`, `first`) |
| `jev_generative_fallback_enabled` | true |
| `jev_quant_shadow_enabled` | false |

Custom endpoints require exact inclusion in the operator's comma-separated `JEV_ALLOWED_ENDPOINTS` environment variable and HTTPS. This prevents arbitrary settings URLs receiving stored credentials. Direct TypeSafe/OpenRouter wire adapters are not implemented.

## Timing and trade isolation

Sentiment shadow uses the existing search results, records an immutable input snapshot, and queues evaluation after the generative result. Jev-first uses deterministic queries through the existing search providers. Portfolio, watchlist and Webull stock/ETF/crypto signals use the integration; options/event-contract sentiment is excluded. Stablecoin fast paths remain intact. The existing audit scheduling guard applies to sentiment evaluations.

News requires a recorded retrieval time at or before the decision time. Future publication/retrieval timestamps and malformed timestamps are excluded. Missing publication dates remain explicitly unknown. Quant snapshots copy the existing deterministic signal/checks and pre-entry account summary; they do not recompute indicators or fetch future evidence. Delayed shadow calls receive only the frozen state.

Quant persistence happens after the paper decision commits. A dedicated `jev-shadow-worker` claims each row atomically, commits/closes its transaction, then calls Vercel. It never calls order-entry code or changes the base signal. Pending work is bounded to 100 records per user, stale queued observations abstain after five minutes, and interrupted worker claims fail explicitly after two minutes rather than silently duplicating provider calls. Disabling Jev prevents queued calls from starting. The worker lives in the existing application background-job lifecycle.

## Outcomes, calibration and current limits

Fixed-horizon labels are defined by contract: bullish means future return strictly above 0%; downside means future return at or below -2%. The default quant horizon is 24 hours; sentiment uses its configured horizon. Binance sentiment outcomes require recorded Binance prices within 15 minutes of the target. Quant outcomes use later immutable scan snapshots for the same user, symbol and Webull market source; they never substitute Binance quotes. Continued quant shadow collection is needed to obtain those future observations. Linked Webull results are reused only when their evaluation timestamps meet the same tolerance. Missing/late prices remain unscored. Manual refresh does not shorten earlier horizons.

Calibration cohorts separate use case, market source, instrument type, actual model, question version and horizon. The authenticated telemetry endpoint provides Brier scores, probability buckets, accuracy/coverage at multiple thresholds, score-versus-return buckets, latency percentiles, error/timeout/abstention/fallback rates, reported cost and the latest evaluations. The dashboard shows a bounded 30-day sample (up to 2,000 rows), not an unlimited accounting ledger. Missing cost is unknown, never assumed free; combined generative fallback cost is unavailable when the existing cascade does not report it.

MFE/MAE fields are reserved but remain null without reliable full-window bars; sparse price samples must not be presented as exact extrema. Evidence conflict, catalyst, regime and support judgments have no automatically inferred price-based ground truth. They are retained as research observations. No profitable-trading claim or empirically optimal threshold is implied.

Shadow-on/off paper-ledger parity is covered by execution tests. Confirm-only/confirm-veto paper branches, gate-performance replay and threshold promotion remain a later phase requiring chronological development/held-out evidence. Historical states must be available at decision time; asking a current model to judge old history is not an unbiased historical forecast. The first implementation does not certify calibration or economic improvement.

## Verification and rollout

Automated service tests use mocked responses and never require a paid key. Tests cover credential round trips, typed native responses, bounded retry/auth/timeout behavior, redacted errors, label mapping, abstention/fallback, immutable snapshots, future-evidence exclusion, fixed-horizon grading, user-isolated telemetry, identical paper entries with shadow on/off, kill-switch preservation, storage failure isolation, and absence of open worker transactions during HTTP.

Run the Jev suites with `.venv/bin/python -m unittest tests.test_jev_service tests.test_jev_settings tests.test_jev_sentiment tests.test_jev_quant_overlay tests.test_jev_outcomes -q`. `JEV_TEST_DATABASE_URI` optionally runs database fixtures in unique schemas on an explicitly isolated PostgreSQL test instance. `QUANT_TEST_DATABASE_URI` enables the existing PostgreSQL paper-ledger regression tests. Never point these variables at the personal-instance database.

The browser test `tests/browser/jev_settings.mjs` exercises the real settings tab against local API fixtures, including mobile layout. Run it against the frontend dev server with `PLAYWRIGHT_MODULE` pointing to an installed Playwright module if needed.

The repository release routine publishes v4.0.0 and upgrades the personal instance. Normal startup applies the additive migration and starts the Jev worker; deployment verification must confirm both services, port 5010, the Jev schema and the release commit.

### Implementation verification — September 23, 2026

- 100 Jev and quantitative-engine tests passed with the database suites enabled against a temporary UTF-8 PostgreSQL 17 instance. This includes actual paper-ledger parity and concurrent worker-claim tests; the instance was stopped and removed afterward.
- The additive migration passed a separate PostgreSQL test: repeated application preserved an existing credential and enabled AI setting while defaulting Jev to off.
- Related sentiment/outcome, external-signal, credential and Telegram settings regressions passed in isolated SQLite tests.
- The real Settings tab passed browser fixture checks for placement, defaults, save/reload, masked key, connection testing, quant shadow controls and a 390-pixel mobile viewport.
- `npm run build`, Python compilation for all 24 modified/new modules, and `git diff --check` passed. Built frontend artifacts are included.
- Live Vercel authentication/inference has not been tested with a real account key. No API key was required or used by automated tests. Release and deployment verification are performed separately from these isolated implementation tests.
