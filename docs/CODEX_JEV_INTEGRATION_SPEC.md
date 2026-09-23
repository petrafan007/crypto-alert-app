# Codex Implementation Spec: Integrate TypeSafe Jev into Crypto & Securities Dashboard

**Repository:** `https://github.com/petrafan007/crypto-alert-app`  
**Prepared for:** Codex implementation  
**Reviewed against repository:** September 22, 2026  
**Primary goal:** Add Jev as a fast, low-cost, probabilistic decision layer for sentiment and quantitative research without weakening the application's deterministic risk controls, point-in-time validation, or paper-trading safety model.

---

## 1. Mission

Implement TypeSafe **Jev** as a dedicated **decision/evaluation subsystem**, not as another generic chat/completion model.

The application already has:

- multi-provider generative AI sentiment analysis with failover;
- current-news/web-search grounding;
- prediction/outcome tracking;
- external Webull signal tracking;
- a paper-only multi-asset quantitative strategy engine;
- deterministic crypto strategy logic using breakout/ATR/dominance inputs;
- chronological validation/replay and calibration infrastructure;
- hard risk controls that must remain authoritative.

Jev should complement those systems by making **fast bounded probabilistic judgments** over already-computed features and already-retrieved text/context.

### Core design principle

Use ordinary code for exact math and rules. Use Jev for ambiguous judgments.

**Good Jev questions:**

- Is the supplied news/context bullish over the selected horizon?
- Is downside risk elevated?
- Is the evidence internally conflicted?
- What market regime best fits these supplied features?
- How strong is this already-qualified setup?
- Does sentiment support, oppose, or remain neutral toward the base quantitative signal?

**Do not ask Jev to:**

- calculate RSI, ATR, moving averages, Donchian channels, P&L, allocation percentages, or other deterministic values;
- fetch market data or browse the web;
- invent prices or news;
- bypass portfolio/risk controls;
- place live orders;
- create a trade when the base deterministic strategy did not qualify one;
- generate prose explanations when a deterministic explanation or the existing generative LLM cascade is more appropriate.

---

## 2. Read This Before Editing

1. Read the repository's `AGENTS.md` first and follow it.
2. Inspect the latest branch state before changing code.
3. Preserve the current paper-only guarantees of the quantitative engine.
4. Keep provider/network calls outside database row locks and critical transaction sections.
5. Do not release, deploy, tag, or upgrade the personal instance unless explicitly requested separately.
6. Do not enable any real-money/autonomous trading path as part of this work.
7. Any Jev behavior that can affect paper-trade entry must be disabled by default until enough shadow-mode data exists to validate it.

---

## 3. Why Jev Belongs in a Separate Subsystem

The existing AI provider cascade in `services/ai_service.py` is designed around **generative models** that produce text and can perform deeper research/reasoning.

Jev is different. Its useful primitive is:

> **state in -> typed probabilistic answers out**

Examples of answer types include:

- Boolean / probability
- Choice from a defined set
- Score on an ordered scale

Therefore:

- **Do not add Jev as just another option in the existing OpenAI/Gemini/etc. chat-provider dropdown.**
- Add a separate Jev decision-engine service with its own settings, credentials, telemetry, contracts, and persistence.
- Let Jev optionally escalate uncertain cases to the existing generative provider cascade rather than trying to replace it.

---

## 4. Recommended Transport

### Default: Vercel AI Gateway

Use Vercel AI Gateway as the initial transport because it provides one stable gateway endpoint while allowing Jev to remain independently configurable.

Suggested defaults:

```text
POST https://ai-gateway.vercel.sh/v1/evaluate
Authorization: Bearer <AI_GATEWAY_API_KEY>
model: typesafe-ai/jev
```

The Jev integration must keep endpoint/model configurable so direct TypeSafe support can be added or selected later without rewriting business logic.

### Optional future transports

Support an abstraction capable of later handling:

- Vercel AI Gateway
- direct TypeSafe API
- OpenRouter Jev adapter if desired

Do **not** over-engineer all three now. Build a clean transport interface and implement Vercel first.

### Important pricing rule

Do not hardcode today's promotional pricing. Persist measured usage/cost metadata where available and make the cost table/config replaceable. Promotions and provider pricing can change.

---

## 5. Proposed Architecture

```text
                         EXISTING DATA SOURCES
                                |
             +------------------+------------------+
             |                                     |
        Market / bars                          News / search
        deterministic                          current context
        calculations                               |
             |                                     |
             +------------------+------------------+
                                |
                    Canonical Jev State Builder
                                |
                                v
                     +---------------------+
                     |     Jev Service     |
                     | typed evaluation   |
                     +---------------------+
                        |              |
                        |              +--------------------+
                        |                                   |
                  high confidence                      uncertain /
                  bounded result                       conflict / error
                        |                                   |
                        v                                   v
              deterministic mapping               Existing generative
              + stored telemetry                  AI cascade if enabled
                        |
             +----------+-----------+
             |                      |
       Sentiment path          Quant shadow path
                                  |
                                  v
                       paper-only comparison/gating
                       (disabled by default)
```

---

## 6. New Files / Modules

Create the following unless repository inspection shows a cleaner established pattern.

### `services/jev_service.py`

Responsibilities:

- HTTP client for Jev/Vercel;
- authentication;
- request/response validation;
- latency measurement;
- retry/backoff;
- error normalization;
- usage/cost metadata capture;
- no business-specific sentiment/trading logic.

Suggested interface:

```python
class JevClient:
    def evaluate(
        self,
        *,
        state: str,
        questions: list[dict],
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> JevEvaluationResult:
        ...
```

The return object should expose:

```python
@dataclass
class JevEvaluationResult:
    answers: dict
    raw_response: dict
    model: str
    provider: str
    transport: str
    latency_ms: int
    usage: dict | None
    estimated_cost_usd: Decimal | None
```

### `services/jev_contracts.py`

Versioned Jev question contracts.

Do not scatter prompt/question definitions throughout unrelated services.

Example:

```python
JEV_SENTIMENT_CONTRACT_VERSION = "sentiment-v1"
JEV_CRYPTO_QUANT_CONTRACT_VERSION = "crypto-quant-v1"
```

Expose functions such as:

```python
def build_sentiment_questions() -> list[dict]: ...
def build_crypto_quant_questions() -> list[dict]: ...
```

### `services/jev_sentiment.py`

Responsibilities:

- build a compact canonical state from current market + news/search context;
- invoke Jev once with all relevant questions;
- convert typed answers into the app's existing sentiment labels;
- determine whether the result is confident enough to use;
- decide whether to escalate to existing generative AI;
- persist/link the evaluation.

### `services/jev_quant_overlay.py`

Responsibilities:

- consume already-computed quantitative features;
- never recompute authoritative indicators itself;
- create Jev state;
- evaluate setup/regime/alignment/uncertainty;
- initially operate in shadow mode only;
- later expose a bounded `confirm / veto / defer` recommendation for paper trading.

### Persistence

Prefer a dedicated model/table, e.g. `JevEvaluation`, rather than stuffing all Jev-specific fields into existing sentiment models.

If the repository's model registration/migration approach makes a separate model file awkward, add the model to the established location instead.

---

## 7. Database Model: `JevEvaluation`

Add a durable record for every consequential Jev evaluation.

Suggested fields:

```text
id
user_id
use_case                     # sentiment | quant_crypto | quant_equity | etc.
symbol
instrument_type
state_schema_version
question_schema_version
state_hash
state_json                    # compact canonical state; avoid secrets/unbounded raw articles
answers_json
probabilities_json
confidence_json
provider
model
transport
latency_ms
usage_json
estimated_cost_usd
status                        # success | abstained | error | timeout | invalid_response
error_code
error_message_safe
created_at
```

Optional linkage fields:

```text
sentiment_history_id
external_sentiment_signal_id
portfolio_order_id
portfolio_observation_id     # if a stable entity exists
```

Outcome/research fields:

```text
target_horizon
outcome_due_at
outcome_price
outcome_return_pct
max_favorable_excursion_pct
max_adverse_excursion_pct
outcome_evaluated_at
base_signal_json
action_taken                 # none | shadow | paper_confirm | paper_veto | paper_defer
counterfactual_json
```

### Indexes

At minimum:

```text
(user_id, created_at)
(user_id, symbol, created_at)
(use_case, created_at)
(status, outcome_due_at)
(question_schema_version, created_at)
```

### State privacy/storage

Store the minimum state needed to reproduce/audit an evaluation.

Avoid storing:

- API secrets;
- complete account payloads unnecessarily;
- huge article bodies when headlines/snippets/source/timestamps are enough.

---

## 8. Credentials and Settings

The current application already encrypts AI/provider credentials. Follow the same pattern.

Add a dedicated encrypted credential such as:

```text
_ai_gateway_key
```

and a safe property/accessor:

```text
ai_gateway_key
```

Do not send the decrypted key to the frontend.

### Suggested user settings

```text
jev_enabled                      default false
jev_transport                    default "vercel"
jev_model                        default "typesafe-ai/jev"
jev_endpoint                     default Vercel evaluate endpoint
jev_timeout_seconds              default 3.0
jev_confidence_threshold         default 0.80 (experimental starting point only)
jev_sentiment_enabled            default false
jev_generative_fallback_enabled  default true
jev_quant_shadow_enabled         default false
jev_quant_paper_gate_enabled     default false
jev_quant_gate_mode              default "confirm_only" or "confirm_veto"
```

The `0.80` threshold is not a claim that 80% is optimal. It is only a starting experimental threshold. The app must eventually calibrate it using stored outcomes.

---

# PART A — SENTIMENT INTEGRATION

## 9. Phase 1: Jev Sentiment Shadow Mode

The application already has an AI sentiment workflow and prediction/outcome history. Do not replace it immediately.

First run Jev **alongside** the existing sentiment result and store both.

### Data supplied to Jev

Build state from data already available to the application at decision time:

```text
symbol
instrument_type
forecast_horizon
current_price
recent_return / price change
recent_volume context
relevant market snapshot values
current timestamp
news/search result title
news/search source
news/search publication timestamp
news/search snippet/summary
other already-grounded market context
```

Every external fact included in the state must have been available at the time of the evaluation.

### Do not let Jev browse

Jev should consume the results of the app's existing current-news/search pipeline.

For the Jev fast path, prefer deterministic search-query templates where possible instead of using an expensive generative model merely to decide what to search for.

Preserve the existing generative search path as a fallback where it adds value.

---

## 10. Sentiment Question Contract v1

Evaluate these in **one Jev request**, not one request per question.

### Q1 — Direction

Choice:

```text
strong_bullish
bullish
neutral
bearish
strong_bearish
```

Question concept:

> Given only the supplied point-in-time news and market context, which directional sentiment best describes the asset over the stated forecast horizon?

### Q2 — Materiality

Ordered score:

```text
1 negligible
2 low
3 moderate
4 high
5 very_high
```

### Q3 — Bullish over horizon

Boolean probability:

> Does the supplied evidence support a bullish interpretation over the stated forecast horizon?

### Q4 — Downside risk elevated

Boolean probability:

> Does the supplied evidence indicate elevated downside risk over the stated forecast horizon?

### Q5 — Evidence conflicted

Boolean probability:

> Is the supplied evidence materially conflicted or internally inconsistent?

### Q6 — Catalyst type

Choice:

```text
macro
asset_specific
regulatory
technical_market_structure
liquidity_flow
mixed
none_material
```

Do not ask Jev for a prose explanation.

---

## 11. Map Jev Sentiment to Existing App Labels

Preserve existing UI/business semantics.

Initial deterministic mapping:

```text
strong_bullish -> Buy Immediately
bullish        -> Consider Buying
neutral        -> Hold
bearish        -> Consider Selling
strong_bearish -> Sell Immediately
```

If watchlist semantics require `Watch` rather than `Hold`, inspect the current code and preserve the existing contract rather than forcing this mapping blindly.

### Deterministic Jev reason string

The existing UI expects a reason. Do not use a second LLM merely to narrate a high-confidence Jev result.

Create a deterministic summary, e.g.:

```text
Jev: bullish; materiality 4/5; bullish probability 0.81; elevated downside-risk probability 0.29; evidence-conflict probability 0.14.
```

Use the generative AI cascade only when configured or when deeper explanation is requested.

---

## 12. Jev -> Generative Escalation Logic

Jev should make cheap/fast bounded decisions first.

Escalate to the existing OpenAI/Gemini/etc. workflow when any of the following occur:

- response invalid or incomplete;
- Jev service unavailable;
- selected choice confidence/probability is below the configured threshold;
- evidence-conflict probability exceeds a configurable threshold;
- high materiality + low confidence;
- a user explicitly requests deeper analysis/explanation.

Suggested result states:

```text
JEV_ACCEPTED
JEV_ABSTAINED_LOW_CONFIDENCE
JEV_ESCALATED_CONFLICT
JEV_ESCALATED_ERROR
JEV_FALLBACK_GENERATIVE
```

Do not silently turn an unavailable Jev response into a high-confidence neutral result.

---

## 13. Existing Sentiment Integration Points

Inspect and integrate with these existing areas rather than duplicating them:

- `services/ai_service.py`
  - `analyze_single_symbol_sentiment`
  - portfolio/watchlist sentiment batch paths
  - existing current-search/news grounding
  - provider failover
- `services/webull_signal_service.py`
- `services/external_signal_service.py`
- `services/sentiment_outcome_service.py`
- `models.py`
  - `SentimentHistory`
  - `ExternalSentimentSignal`

### Important

The existing `SentimentHistory` and `ExternalSentimentSignal` models already track predictions, horizon, outcome, provider/model provenance, and realized movement.

Link Jev evaluations to those records where practical so the application can compare:

```text
current generative sentiment vs Jev sentiment vs actual outcome
```

Do not create a completely separate grading universe if the existing outcome service can be cleanly extended.

---

# PART B — QUANTITATIVE STRATEGY ENGINE

## 14. Existing Crypto Strategy Must Remain Authoritative

The current crypto signal logic is deterministic and currently includes concepts such as:

- hourly completed bars;
- Donchian breakout channel;
- ATR;
- dominance filter/gate;
- deterministic stop construction;
- portfolio/risk controls in the paper engine.

Do not replace that strategy with Jev.

Jev should be an **overlay** that evaluates a strategy setup after deterministic feature calculation.

---

## 15. Primary Quant Hook

The most important integration point is in the portfolio engine flow after the existing crypto strategy has produced its signal/features and **before** the paper engine calls its entry function.

Conceptually:

```python
base_signal = crypto_signal(...)

jev_overlay = evaluate_crypto_setup(
    base_signal=base_signal,
    deterministic_features=...,
    portfolio_context=...,
    fresh_sentiment=...,
)

# SHADOW MODE: record only, no behavior change.

if base_signal.enter:
    # later, after validation and only if feature flag enabled:
    # bounded Jev confirm/veto/defer may affect PAPER entry.
    enter_lot(...)
```

Network I/O for Jev must occur outside database locks/critical transaction sections.

---

## 16. Quant State Contract v1

Build a compact canonical state using only values known at decision time.

Suggested fields:

```text
symbol
decision_time
timeframe
current_price
base_entry_qualified
base_exit_qualified
base_signal_reason
price_vs_donchian_upper_pct
price_vs_donchian_lower_pct
atr
atr_pct
dominance_filter_passed
recent_return_1h
recent_return_4h
recent_return_24h
recent_realized_volatility
volume_vs_recent_average
spread/liquidity metrics if reliably available
current portfolio exposure
cash/risk capacity summary
existing stop distance
fresh Jev sentiment label/probabilities if available and not stale
fresh generative sentiment summary only if already available at decision time
```

Do not fabricate unavailable features just to fill the contract.

Version the schema so historical Jev results remain interpretable after features change.

---

## 17. Quant Question Contract v1

Evaluate all questions in one request.

### Q1 — Regime

Choice:

```text
trend_up
trend_down
range
high_volatility_uncertain
```

### Q2 — Setup quality

Ordered score:

```text
1 poor
2 weak
3 fair
4 strong
5 excellent
```

### Q3 — Confirm base entry

Boolean probability:

> Given the supplied quantitative feature values and fresh sentiment context, does the evidence support the already-qualified deterministic entry?

**This question is only actionable when the deterministic base strategy already produced `enter=True`.**

### Q4 — Downside risk elevated

Boolean probability.

### Q5 — Sentiment alignment

Choice:

```text
supports
neutral
opposes
```

### Q6 — Uncertainty high

Boolean probability.

---

## 18. Required Rollout Stages for Quant

### Stage 0 — Off

No calls.

### Stage 1 — Shadow

```text
base strategy behaves exactly as it does today
Jev runs and records what it would have said
no trade decision can change
```

This must be the initial default implementation.

### Stage 2 — Paper confirm-only

After enough held-out evidence exists:

- base strategy must first qualify entry;
- Jev may confirm it;
- if Jev does not confirm, mark the entry as deferred/skipped in the Jev-enabled experimental branch;
- maintain a baseline counterfactual showing what the original strategy would have done.

### Stage 3 — Paper confirm/veto

Only after validation:

- base strategy qualifies entry;
- Jev can `confirm`, `veto`, or `defer` based on calibrated thresholds;
- hard risk controls remain authoritative;
- preserve baseline counterfactual results.

### Never as part of this implementation

```text
Jev creates a trade when base_signal.enter == false
Jev changes live brokerage orders
Jev bypasses kill switches
Jev increases size beyond risk constraints
Jev disables stop-loss logic
Jev turns a paper engine into a live engine
```

---

# PART C — MEASURE WHETHER JEV ACTUALLY HELPS

## 19. Prediction / Outcome Grading

Jev should earn influence through measured evidence.

For each evaluation, grade future outcomes at supported horizons such as:

```text
15m
1h
4h
24h
7d
```

Use only horizons for which reliable point-in-time market data exists.

Capture:

```text
future return
max favorable excursion (MFE)
max adverse excursion (MAE)
realized paper trade P&L if applicable
whether Jev confirmed/vetoed/deferred
what the baseline strategy would have done
```

---

## 20. Calibration Metrics

### Boolean questions

Track:

- Brier score;
- calibration buckets;
- accuracy at multiple probability thresholds;
- coverage/abstention rate.

Example buckets:

```text
0.50-0.59
0.60-0.69
0.70-0.79
0.80-0.89
0.90-1.00
```

If Jev says `0.80` repeatedly, approximately 80% of comparable labeled outcomes should eventually support that probability for the probability to be considered calibrated.

### Choice questions

Where a ground-truth label can be defined, track:

- confusion matrix;
- top-choice accuracy;
- multiclass Brier/log loss if probabilities are available;
- calibration by selected-choice confidence.

### Score questions

Track score buckets against realized outcomes. Do not assume a 5/5 setup is useful until the data demonstrates it.

---

## 21. Trading Metrics: Baseline vs Jev Overlay

Run the same chronological dataset through multiple variants.

At minimum:

```text
A. Current baseline strategy
B. Baseline + Jev shadow observations
C. Baseline + Jev confirm-only gate
D. Baseline + Jev confirm/veto gate
```

Compare:

```text
net return
annualized return where appropriate
maximum drawdown
Sharpe/Sortino if already part of the project methodology
profit factor
expectancy per trade
win rate
number of trades
turnover
fees
slippage
average hold time
MFE/MAE
capital utilization
```

The important measurement is **incremental improvement over the existing baseline**, not whether the Jev-enabled strategy looks profitable in isolation.

---

## 22. Prevent Lookahead / Leakage

This is non-negotiable.

Every Jev state item must satisfy:

```text
available_at <= decision_time
```

Do not include:

- articles published later;
- revised indicator values based on incomplete future bars;
- outcome information;
- later sentiment evaluations;
- future portfolio state.

Use the project's existing chronological development/held-out replay methodology.

Never tune Jev thresholds on the held-out set and then report that same held-out result as unbiased validation.

---

## 23. Counterfactual Recording

For every paper decision affected by a Jev gate, preserve:

```text
what baseline would have done
what Jev-enabled branch did
why Jev affected it
Jev probability/confidence
subsequent market outcome
```

Example:

```json
{
  "baseline_action": "ENTER",
  "jev_action": "VETO",
  "jev_confirm_probability": 0.31,
  "jev_downside_risk_probability": 0.84,
  "actual_return_24h_pct": -4.2,
  "counterfactual_result": "veto_helped"
}
```

This is essential for proving whether Jev adds economic value.

---

# PART D — SPEED, RELIABILITY, AND COST

## 24. Latency Instrumentation

Measure every call with a monotonic timer.

Persist/report:

```text
request latency ms
p50 latency
p95 latency
p99 latency if sample size supports it
error rate
timeout rate
fallback rate
```

Do not infer speed from provider marketing numbers. Measure the application's actual deployed path.

---

## 25. Cost Instrumentation

Capture provider-reported usage when available.

Track:

```text
evaluations per day
input units/tokens if reported
cost per evaluation
cost per 1,000 evaluations
cost by use case
cost by symbol
monthly Jev cost
generative fallback cost
combined Jev + fallback cost
```

The most useful cost comparison is:

```text
current generative sentiment cost
vs
Jev-first + generative-on-uncertainty cost
```

Do not hardcode temporary free promotions into business logic.

---

## 26. Network Behavior

Recommended starting policy:

```text
timeout: ~3 seconds
retry: maximum 1 transient retry
retry on: 408, 429, selected 5xx/network failures
no retry on: auth failures, malformed request, invalid contract
```

Implement modest exponential backoff/jitter consistent with project conventions.

Do not let Jev block a scheduler indefinitely.

Add a small circuit-breaker or cooldown if repeated provider failures would otherwise create a request storm.

---

## 27. Batch Questions, Not Separate Calls

Jev can evaluate multiple typed questions against the same state.

Use one evaluation request per symbol/state where practical:

```text
BAD:
6 questions -> 6 API calls

GOOD:
1 state + 6 questions -> 1 API call
```

Initially keep different symbols as separate evaluation records so outcome grading and auditing remain clean.

---

# PART E — FRONTEND / SETTINGS

## 28. Settings UI

In `frontend/src/pages/Settings.jsx`, add a dedicated section:

```text
Jev Decision Engine (Experimental)
```

Do not bury Jev inside the normal generative model selector.

Suggested controls:

```text
Enable Jev
Transport: Vercel AI Gateway
API key: masked input
Model: typesafe-ai/jev
Confidence threshold
Enable Jev sentiment
Use generative fallback when uncertain
Enable quant shadow mode
Enable Jev paper gate   [OFF by default]
Paper gate mode         [confirm-only / confirm-veto]
Test connection
```

### Display telemetry

Where useful, show:

```text
last successful call
last latency
last safe error
number of evaluations
fallback percentage
recent Brier/calibration result
estimated recent cost
```

Do not expose raw credentials.

---

## 29. Quant UI

In the existing quantitative strategy/admin UI, add Jev telemetry only after the backend is stable.

Useful per-signal display:

```text
Base signal: ENTER QUALIFIED
Jev mode: SHADOW
Regime: trend_up
Setup quality: 4/5
Confirm entry: 0.83
Downside risk: 0.26
Sentiment alignment: supports
Uncertainty: 0.18
Action taken: none (shadow)
```

This is research telemetry, not a guarantee of profitability.

---

# PART F — TESTS

## 30. Required Tests

Add tests following existing project conventions.

Suggested files:

```text
tests/test_jev_service.py
tests/test_jev_sentiment.py
tests/test_jev_quant_overlay.py
tests/test_jev_outcomes.py
```

### Service tests

- valid Boolean response parses correctly;
- valid Choice response parses correctly;
- valid Score response parses correctly;
- malformed JSON rejected;
- missing required answers rejected;
- timeout normalized;
- 429 retry behavior bounded;
- auth error not retried indefinitely;
- key never appears in logs/error payloads;
- latency is recorded.

### Sentiment tests

- stablecoins retain existing fast-path behavior;
- disabled Jev makes no call;
- shadow mode does not alter current displayed/business result;
- deterministic five-label mapping is correct;
- low confidence triggers configured fallback;
- conflict triggers configured fallback;
- Jev unavailable does not leave sentiment permanently stuck in a checking state;
- outcome history links correctly.

### Quant tests

- Jev never creates an entry when base signal is false;
- shadow mode changes zero paper decisions;
- Jev cannot bypass kill switch/risk controls;
- Jev cannot alter live brokerage order code;
- Jev call is not made while a DB row lock is held;
- paper confirm-only behavior works behind feature flag;
- unavailable/invalid Jev produces explicit abstention, not fabricated confidence;
- counterfactual baseline is recorded when Jev gate changes a paper decision.

### Point-in-time tests

- future news is excluded;
- future bars are excluded;
- incomplete bar behavior remains consistent with current quant logic;
- replay produces traceable/versioned Jev state.

---

# PART G — ACCEPTANCE CRITERIA

## 31. Definition of Done for This Codex Task

The first implementation should deliver **infrastructure + sentiment capability + quant shadow mode**.

It should **not** automatically turn on Jev paper gating.

The task is complete when all of the following are true:

1. Jev has a dedicated backend service and versioned contracts.
2. Vercel AI Gateway transport works through a configurable endpoint/model.
3. Jev API credentials are encrypted/masked following existing project patterns.
4. A `JevEvaluation` persistence layer records state/version/probability/latency/cost/provenance.
5. Sentiment can run Jev in shadow mode alongside the current system.
6. Jev can optionally become the fast sentiment decision path with generative fallback on uncertainty.
7. The current stablecoin fast path remains intact.
8. Existing prediction/outcome grading can associate real outcomes with Jev evaluations.
9. Crypto quant Jev overlay runs in **shadow mode only by default**.
10. Quant shadow mode records Jev regime/setup/confirm/risk/alignment/uncertainty outputs.
11. Shadow mode causes **zero difference** in paper trades.
12. Jev can never create a trade when the deterministic strategy has no qualified entry.
13. Existing hard risk/kill/capital controls cannot be bypassed by Jev.
14. No live brokerage submission path is added or altered to depend on Jev.
15. Latency, errors, fallbacks, model/version, and cost/usage are observable.
16. All Jev inputs remain point-in-time safe.
17. Tests cover normal, timeout, malformed, low-confidence, and provider-failure cases.
18. Frontend settings clearly label Jev as experimental and keep paper gating OFF by default.
19. Repository verification required by `AGENTS.md` passes.
20. No release/deployment/tag is performed unless separately requested.

---

# PART H — IMPLEMENTATION ORDER

## 32. Recommended Sequence

### Step 1 — Foundation

- inspect current settings/credential routes and migration conventions;
- add encrypted gateway credential;
- add Jev settings;
- implement `jev_service.py`;
- implement versioned contracts;
- add mocked service tests.

### Step 2 — Persistence

- add `JevEvaluation`;
- create migration;
- add repository/service helpers;
- add outcome-link fields;
- test persistence and no-secret behavior.

### Step 3 — Sentiment Shadow

- reuse existing search/news collection;
- build Jev state;
- evaluate sentiment contract;
- store results;
- link to current sentiment history;
- do not change current visible sentiment decision yet.

### Step 4 — Jev Fast Sentiment Mode

- add deterministic Jev-to-existing-label mapping;
- add confidence/conflict gating;
- add generative fallback;
- add deterministic reason string;
- compare latency/cost/outcomes against current flow.

### Step 5 — Quant Shadow

- hook after deterministic `crypto_signal(...)` feature calculation;
- construct point-in-time state;
- evaluate quant contract;
- store evaluation and baseline decision;
- make no entry/exit changes.

### Step 6 — Calibration / Replay

- add historical/counterfactual comparison;
- calculate Brier/calibration metrics;
- compare baseline vs Jev overlay on chronological held-out data;
- surface enough telemetry to decide whether Jev deserves paper-gate influence.

### Step 7 — Optional Paper Gate Later

Only implement/enable after sufficient evidence exists and only behind an explicit setting.

Do not enable automatically as part of this first task.

---

# PART I — EXAMPLE PAYLOADS

## 33. Example Sentiment State

Keep the actual serialized format compact and stable.

```text
Asset: BTC-USD
Instrument: crypto
Decision time: 2026-09-22T20:00:00Z
Forecast horizon: 24h
Price: 123456.78
Return 1h: +0.7%
Return 24h: +3.8%
Volume vs recent average: +37%

Current evidence available by decision time:
1. Source: Example News
   Published: 2026-09-22T18:10:00Z
   Headline: ...
   Snippet: ...
2. Source: Example Wire
   Published: 2026-09-22T19:05:00Z
   Headline: ...
   Snippet: ...
```

Questions: use `sentiment-v1` contract.

---

## 34. Example Quant State

```text
Asset: BTC-USD
Decision time: 2026-09-22T20:00:00Z
Timeframe: 1h
Current price: 123456.78
Base entry qualified: true
Base signal: Donchian breakout
Price vs prior Donchian upper: +0.42%
ATR: 1830.21
ATR percent: 1.48%
Dominance gate passed: true
Return 1h: +0.7%
Return 4h: +2.1%
Return 24h: +3.8%
Volume vs recent average: +37%
Current crypto exposure: 8.4%
Available risk capacity: yes
Existing deterministic stop distance: 2.96%
Fresh sentiment direction: bullish
Fresh bullish probability: 0.81
Fresh downside-risk probability: 0.29
```

Questions: use `crypto-quant-v1` contract.

---

# PART J — HOW TO JUDGE SUCCESS

## 35. Success Is Not "Jev Returned an Answer"

The integration is successful only if measured data shows useful improvement in one or more of these dimensions without unacceptable degradation elsewhere:

```text
lower sentiment inference cost
lower sentiment latency
same or better calibrated prediction quality
fewer expensive generative calls
better paper-trade expectancy
lower drawdown
better risk-adjusted return
better rejection of bad base entries
stable operational reliability
```

A fast answer that does not improve calibration or economic outcomes is not useful simply because it is fast.

Likewise, a profitable backtest is not sufficient if it resulted from lookahead, leakage, repeated threshold tuning, or an unrepresentative development sample.

---

# PART K — CODEX EXECUTION INSTRUCTIONS

## 36. How Codex Should Execute This Task

Before editing, Codex should:

1. Read `AGENTS.md`.
2. Inspect the current implementation of all files named in this spec.
3. Locate the exact settings API routes, model registration, migration pattern, and test conventions instead of guessing filenames that are not present.
4. Produce a concise implementation plan identifying files to add/modify.
5. Implement in small coherent commits/changes, preserving current behavior behind disabled/shadow flags.
6. Use mocked Jev responses in automated tests; tests must not require paid network calls.
7. Run the project's required backend/frontend verification.
8. Show a final summary with:
   - files changed;
   - migrations created;
   - settings added;
   - tests run/results;
   - any unresolved limitations;
   - exact manual steps required to enter a Vercel AI Gateway key and enable Jev shadow mode.

### Do not stop at scaffolding

The implementation should include working backend calls, persistence, settings integration, sentiment shadow path, quant shadow path, and tests—not just placeholder classes/TODOs.

### Do not turn on paper gating automatically

The first production-safe state is:

```text
sentiment Jev: configurable
quant Jev: shadow only
live trading influence: none
paper gate: disabled
```

---

# 37. Source References Used for This Design

Repository:

- `https://github.com/petrafan007/crypto-alert-app`
- `https://github.com/petrafan007/crypto-alert-app/blob/main/AGENTS.md`
- `https://github.com/petrafan007/crypto-alert-app/blob/main/README.md`
- `https://github.com/petrafan007/crypto-alert-app/blob/main/docs/quantitative_strategy_engine.md`
- `https://github.com/petrafan007/crypto-alert-app/blob/main/services/ai_service.py`
- `https://github.com/petrafan007/crypto-alert-app/blob/main/services/portfolio_engine.py`
- `https://github.com/petrafan007/crypto-alert-app/blob/main/services/portfolio_strategy_signals.py`
- `https://github.com/petrafan007/crypto-alert-app/blob/main/services/webull_signal_service.py`
- `https://github.com/petrafan007/crypto-alert-app/blob/main/services/sentiment_outcome_service.py`
- `https://github.com/petrafan007/crypto-alert-app/blob/main/models.py`
- `https://github.com/petrafan007/crypto-alert-app/blob/main/credentials.py`
- `https://github.com/petrafan007/crypto-alert-app/blob/main/frontend/src/pages/Settings.jsx`

Jev / TypeSafe / Vercel:

- TypeSafe API docs: `https://api.typesafe.ai/docs`
- Vercel AI Gateway Jev model: `https://vercel.com/ai-gateway/models/jev`
- Vercel Jev gateway/API documentation and release notes: search Vercel docs/changelog for `TypeSafe Jev AI Gateway evaluate` and verify current endpoint/model before implementation.

---

## Final Engineering Principle

Treat Jev as a **measurable probabilistic sensor** inside the application—not an oracle.

The app should know exactly:

- what information Jev saw;
- what version of the question contract it answered;
- what probabilities/confidence it returned;
- how long it took;
- what it cost;
- what action, if any, depended on it;
- what subsequently happened in the market;
- whether using Jev improved results versus the existing baseline.

If the data eventually demonstrates that Jev improves the strategy, then promote it gradually from shadow -> paper confirmation -> paper veto/confirmation. If the evidence does not support it, keep it as a sentiment/research accelerator instead of letting it influence trades.
