# Quantitative Strategy Engine

The engine is an administrator-only, multi-asset **paper research system**. The default starting bankroll is $50,000, with relative allocation weights of 35 for equities, 25 for options, 20 for crypto, 10 for micro futures, and 10 for events. Enabled modules share 100% of the target capital proportionally. Futures is disabled by default, giving initial targets of 38.89%, 27.78%, 22.22%, 0%, and 11.11%, respectively. The 18.5% annual return setting is a research objective, not a forecast or validated strategy result.

## AI Copilot administrator context (v2.96.0)

The existing AI Copilot now receives quantitative-engine evidence only after the same administrator check used by the engine APIs. Its compact administrator layer always includes the complete current Quantitative Portfolio and Event Contract configuration—module settings, strategy prompts, allocations, watchlists, AI provider/model topology with secret values redacted, worker/account state—and historical report catalogs with archive totals. When a question concerns the quantitative engines, the context expands to current telemetry, paper positions, a bounded recent order/log window, the newest detailed audit, and exact-ID or meaningful text matches searched across the administrator's complete log and report archives.

This request-aware retrieval prevents a mature engine's multi-megabyte history from overwhelming the model while retaining access to old evidence. Every collection declares total and supplied counts, ordering, archive-search scope, and any record-detail truncation. A catalog entry establishes that a report exists; it does not imply that the report body was inspected. Administrators can reference a report or log ID in their question to retrieve that historical record directly. The Copilot must acknowledge these bounds rather than imply that unsupplied detail was inspected.

Quantitative context remains operational evidence, not brokerage state. Runtime prompt rules require the Copilot to label Quantitative Strategy Mode as an isolated paper ledger, keep it separate from provider-backed Webull Real Trading and simulated Webull Test Mode, and cite record IDs/timestamps when diagnosing engine behavior. Non-administrators do not trigger quantitative queries and receive no strategy settings, logs, reports or indirect health summary. Credentials, tokens, API keys and secret values are never placed in Copilot requests. Existing user-authored Copilot prompts are preserved; the mode, authorization and redaction rules are appended at runtime.

## Event cadence resilience (v2.95.2)

Routine AI evaluation batch and cooldown deferrals (`AI_EVALUATION_DEFERRED`) no longer flag the Event module as `DATA_LIMITED` or degrade the running paper engine. They are reported as `NO_SIGNAL` with informative status text while preserving `DATA_LIMITED` triggers for actual model, provider or quote-feed outages.

## Worker supervision hotfix (v2.95.1)

The independent Event decision handoff is included in the singleton scheduler's supervised thread registry. If that thread stops, the worker process exits and systemd restarts the complete scheduler instead of leaving Event handoff silently unavailable.

## Goal measurement and research integrity (v2.95.0)

Telemetry and newly generated audits contain deterministic `goal_tracking`: actual equity against `initial_balance × (1 + target/100)^(elapsed_days/365)`, signed dollar/percentage gaps, observed return, annualized percentage-point gap, 30/90/365-day rolling returns, net module contributions, capital utilization and snapshot coverage. The current reset generation and latest recorded valuation define the interval, not time spent waiting in the browser. Annualization begins after 30 elapsed days but is explicitly descriptive, never statistical validation. Missing days are disclosed rather than interpolated. Target changes recalculate a hypothetical target path; this is not a market benchmark or measured opportunity cost. Deposits/withdrawals are not modeled within a run; a new bankroll uses the existing explicit reset workflow.

The Master AI Configuration modal includes editable **Shared audit guidance**, applied to specialists and the master, alongside the existing CIO prompt. Module-specific auditor prompts remain in their module settings. Both interfaces display the mandatory engine/evidence instructions. New guidance tells the auditor to use the saved numeric target (normally 18.5%), not an obsolete range embedded in a custom prompt, and to separate observed defects, missing evidence and proposed experiments. Custom prompts are not silently overwritten. Existing archived reports are unchanged; new evidence must be captured in a fresh report.

Event probability calibration uses the earliest valid pre-cutoff forecast for each verified, resolved contract in the current run, including forecasts that did not produce a trade. Repeated forecasts are not independent trials. Reported diagnostics include Brier score, ten-bin calibration error and skill against a simultaneous YES bid/ask midpoint on the matched subset. SQL validates forecasts and ranks them per contract before capping the earliest 10,000 distinct resolved contracts. Duplicate outcome records prefer the latest valid update, with record ID breaking ties. Exclusion counts cover joined forecast/outcome rows across the run, so they may include duplicate outcome records; they are not counts of independent contracts. Queries return only bounded samples and aggregate counts without changing historical records. No AI call calculates these scores.

Calibration breakdowns partition this same sample by archived provider/model/strategy version, archived contract-duration label, and forecast calendar month in UTC. Metadata comes from the selected decision, not current settings, a reused market snapshot, a later forecast, or time remaining until cutoff. Missing or malformed metadata is explicitly Unknown. Matched model and market Brier scores and relative skill use the same matched subset within each group; calibration error uses all resolved contracts in that group. Overall scores continue to pool the selected sample. At most 50 groups are displayed per dimension: newest months first, otherwise largest groups with label ordering for ties. Omitted group and contract counts are disclosed, and omitted groups remain in overall metrics. These comparisons are descriptive: model groups may contain different contracts, and small samples, resolution coverage, correlated outcomes and strategy changes limit inference. They are not a controlled model comparison or statistical proof of forecast skill or profitability. Fresh audit evidence includes these breakdowns; archived reports are unchanged.

### Timely Event execution and paused-risk management

As of v2.99.19, snapshot normalization keeps provider quote time (`quote_as_of`), local retrieval time (`quote_retrieved_at`), and last-trade time separate. A cached read never changes retrieval time. [Webull describes this endpoint as a real-time snapshot](https://developer.webull.com/apis/docs/reference/event-snapshot/); when no provider quote timestamp is supplied, the existing paper-entry receipt-time assumption is retained and explicitly labeled `RETRIEVAL_ONLY`. Last-trade time is not substituted for quote time. Supplied stale, invalid or future quote timestamps cannot fall back to a fresh retrieval time. Entry requires a usable quote or retrieval timestamp within 30 seconds, allowing at most five seconds of clock skew. Unmarked legacy quote timestamps remain labeled `UNSPECIFIED_QUOTE_TIME`; historical provenance is not reconstructed. Timing alone does not prove exchange freshness or executable depth.

Underlying observations carry their own source, timestamp basis, original time and retrieval time. Streaming-cache timestamps and recorded price-history timestamps are labeled as observations rather than claimed exchange quote times. Stale, future, missing-time or invalid underlying observations are retained in the evidence but excluded from current-price model inputs and distance-to-reference calculations. Snapshot price columns use the same validated value. Contract reference prices are preserved separately from spot prices. AI context explains missing observations and the limits of retrieval-based quote timing. These changes do not supply unavailable exchange timestamps or new historical data; further source/fill validation remains part of the research backlog.

Fresh decisions trigger a post-commit handoff, complemented by an independent 15-second Event consumer. The consumer is independent of slow option-chain/equity scans, revalidates the exact contract against fresh executable quotes, and rechecks portfolio controls/generation under the same State row lock used by the supervisor. It never bypasses decision freshness, cutoff, fee, uncertainty, confidence or capital limits. Every processed eligible decision retains a generation-scoped FILLED, REJECTED, MISSED or HELD disposition in its existing evidence. New telemetry distinguishes unavailable/deferred upstream evidence from genuinely evaluated markets with no qualifying signal. Long portfolio scans cannot overwrite that independent telemetry with an empty lookup.

Repeated circuit checks no longer clear the active risk-management lease. The circuit/kill switch blocks new entries while existing risk can still be marked and exited. An explicit Stop still freezes execution, and resets invalidate in-flight work. No real broker order is submitted.

### Observation provenance and upgrade impact

The additive migration adds nullable `source` and `observed_at` columns to `portfolio_market_observations`. Existing records are retained as unverified, not relabeled as measured or deleted. New Bitcoin-dominance observations come from the current CoinGecko global response; no history is synthesized. ETH/SOL require verified observations on all seven preceding UTC dates, plus a fresh current observation. They can therefore return to WARMING_UP after upgrade; BTC does not use this filter.

New daily ATM IV observations carry Webull quote provenance. Options still require 252 measured observations and a non-flat range; no licensed historical IV feed/import is configured by this release. The UI shows remaining warm-up and unused allocation capacity. Missing observations are a data requirement, not permission to relax entry gates.

### Historical validation workbench

An administrator can upload a bounded historical JSON dataset in the Quantitative Strategy Engine telemetry panel. `POST /validation` accepts at most 5 MiB and performs deterministic computation only—no inference, new market-data requests, orders or ledger writes. It uses saved module parameters, allocation and bankroll with shared live paper commission/slippage/sizing/spot-exit functions. Supported scope is **one equity or crypto symbol**, not a complete multi-asset portfolio or an options/Event/futures validation.

The payload declares `schema_version: 1`, `module`, `symbol`, `source`, chronological `bars` (time/open/high/low/close, optional volume/available_at), `quotes` (time/price), `evaluation_start` and `split_at`. Equities require `benchmark_bars` for SPY; ETH/SOL require genuinely historical `dominance_observations` (time/value), including the seven preceding UTC days. Dataset provenance is user-declared, not independently certified. The workbench includes a schema template and downloads its results.

Separate development and held-out ledgers use only information available by each quote timestamp, with no parameter optimizer or automatic configuration change. Baseline and adverse cost/latency/missed-fill assumptions are compared explicitly. Results disclose coverage, unsupported assets, timing and accounting limitations. Passing a replay is not evidence of full-portfolio profitability; licensed, point-in-time historical datasets, wider regimes, assignment/settlement realism and longer forward observation remain research work.

## Positions display (v2.93.0)

Quantitative paper holdings are available in Webull Trading and the Positions tab on Orders. Both use the shared [Positions views and column layouts](positions.md), including event settlement details, option-spread legs, per-asset filters, and saved column order. Paper holdings remain distinct from real trading accounts. The Positions adapter preserves the engine's collateral-plus-unrealized-P&L valuation, including zero values.

## Settlement and audit integrity (v2.92.7)

An expired Event position remains open until an explicit provider result is available. The resolver selects distinct contracts before limiting each batch, prioritizes held positions, filters recently attempted contracts before the limit, and rotates other pending contracts by oldest attempt. Retried market lookups bypass cached catalogs. For production Webull-listed Kalshi contracts that lack a Webull settlement, the public [Kalshi market endpoint](https://docs.kalshi.com/api-reference/market/get-market) (and its historical counterpart on HTTP 404) supplies a narrow fallback: exact ticker and cutoff, binary finalized non-provisional market, explicit YES/NO result, matching $0/$1 payout and a valid past settlement timestamp are all required. Both sources are saved, with KALSHI_FINALIZED_MARKET provenance; no account credentials are sent. Missing or conflicting evidence stays pending. Provider outcome fields, nested resolution objects and settlement prices survive normalization. A last-traded price, even on a delisted instrument, is not settlement evidence. Pending positions retain their last actual mark and occupy the three-position limit; provider outages cannot be solved by inventing payouts or dropping risk from the ledger.

Module and CIO audits use their supplied system prompts directly, without Copilot templates or web-search synthesis. Mandatory context describes the engine as deterministic, multi-asset paper research, including saved strategy parameters, risk constraints, cash-as-unused-budget semantics, exact percentage units, and purchased versus settled Event outcomes. Current scan observations include timestamped signal checks (channel levels, ATR, trend and RSI gates), separate from old trade logs. Calendar session times, per-module realized results, and explicit operational summaries distinguish skipped market-closed scans from real data failures. The master receives these recorded summaries rather than treating specialist prose as quantitative evidence. The saved audit evidence includes inputs for each completed specialist, exact portfolio facts and explicit pending-settlement details. Custom saved prompts are preserved and supplemented with these engine rules.

Specialist calls allow 8,192 output tokens and master calls 16,384. An incomplete answer is regenerated with twice the allowance, then fails over through configured providers if necessary. Audit requests allow 120 seconds per provider request. Finish reasons, final-answer presence and an explicit end marker are checked before accepting output; the marker is removed from the displayed report. Incomplete or filtered responses cannot become successful reports. No finite token limit guarantees provider completion, so exhausted attempts retain evidence and failure diagnostics. The known drawdown percentage-scaling error is rejected before report success. Historical reports are not rewritten; their viewer displays a legacy-validation notice.

Module health now shows per-symbol progress toward the 252 measured daily IV observations required by the existing options rules, including outside trading sessions. Opening the market does not eliminate that prerequisite. Event capacity includes pending settlements. POSITION_OPENED logs are recorded with an actual lot in the same transaction as its fill; rejected qualified signals use ENTRY_SKIPPED and a reason. These informational rejections do not themselves degrade the engine.

## Portfolio reports and startup status (v2.92.2)

**View report** opens the portfolio audit archive. Select a historical report to read its original text, creation time, model, paper equity, open-position count, module assessments, and saved evidence. Older failed reports retain their actual failure reason; missing historical metrics show a dash rather than an invented zero.

**Generate Fresh Report Now** queues one background audit and returns immediately. The open report window refreshes progress automatically; closing it does not cancel generation. Audits follow the configured cadence even when paper execution is stopped or paused. Success means report generation succeeded, not that the trading strategy is healthy. Partial means the CIO report completed with unavailable module assessments; Failed and Unavailable show diagnostics and any preserved evidence.

Each module receives its own open positions. Dedicated master AI tiers use their configured providers, models, reasoning levels, and keys through the existing failover service. Existing portfolios without dedicated tiers retain their configured global cascade. A provider limitation cannot manufacture a successful or empty report.

Start displays Starting while the worker waits for its first claim. Stopped time is excluded from Event-worker stall detection, while a worker that never starts still becomes stale after the grace period. The master grid shows portfolio scan and heartbeat timestamps separately from Event AI statistics. The 10% drawdown pause remains a separate execution safeguard; generating reports cannot clear it.

## Review of v2.88.0

The initial implementation supplied the dashboard, configurable watchlists and allocation cards, four persistence tables, and administrator-only endpoints. It did **not** supply the four new execution workers, portfolio accounting, measured performance, portfolio risk controls, scheduled audits, or rebalancing. The existing Event Contract research worker was a separate subsystem.

The review found and corrected these foundation problems in v2.89.0:

| Finding | Correction |
| --- | --- |
| CIO code imported `User` from the wrong module, omitted the default prompt import, called the AI service with unsupported arguments, and expected the wrong response shape. | Uses the existing provider cascade with its actual username/messages signature and response wrapper. |
| When AI failed, the fallback asserted a 0.32 correlation, an 8.4% stress drawdown, an “optimal” verdict, and an 82% probability of profit without supporting data. | Removed those claims. Failed/unavailable AI is labeled explicitly. Quantitative evidence comes from recorded results; insufficient history produces null metrics. |
| Allocation/configuration input could accept non-finite numbers, silently clamp invalid values, overwrite unrelated module settings, or enable execution using truthy strings. | Atomic, finite, bounded validation; exact sum of rounded allocation weights; partial settings merge; explicit worker controls. |
| Bankroll configuration could diverge from account balances. Reset deleted historical positions and orders and had no explicit API confirmation. | Bankroll changes require confirmed reset. Reset archives the old run, cancels its pending exits, stops the engine, and invalidates work already in progress. No historical ledger rows are deleted. |
| Position records had no implemented stop/target or derivative collateral bookkeeping, despite the original document claiming them. | Added strategy lots with collateral, multipliers, stop/target rules, fees, realized P&L, contract details and reset generation. |
| Event simulation created repeated one-contract hypothetical fills without a portfolio bankroll limit. | Once a quantitative portfolio exists, fresh eligible Event decisions are consumed by its capital-constrained ledger. Historical Event research orders remain intact. |
| The frontend discarded status responses, displayed zero equity as the default bankroll, reset specialist prompts to unrelated text, and closed settings modals before save succeeded. | Live telemetry, null-safe balances, server-supplied defaults, and save-result-aware modal handling. |
| Startup table creation was described as a general schema migration mechanism. | This release deliberately adds new tables; existing v2.88 table definitions need no column alterations. |

## Optional modules and dynamic allocations (v2.89.4)

As of v2.91.2, module prompts saved under the older `specialist_prompt` name are automatically read as `auditor_prompt`. This preserves custom prompts and allows Start Paper Engine to validate existing configurations. If both names exist, the current `auditor_prompt` value wins, including an explicitly empty value. Saving settings writes the current name; no bankroll reset or database migration is needed.

Every module has a saved **Enabled for new entries** toggle. Save Module Settings applies it; unsaved changes are drafts. Existing configurations inherit enabled equities, options, crypto and events, and disabled futures when an explicit enabled value is absent. Re-enabling restores the preserved watchlist, strategy parameters, prompts and history.

A disabled module has a 0% target and skips entry scans and entry data requests. Disabling Events also gates the existing Event collector's automatic and manual new-entry scans; outcome resolution remains available. Existing positions still require data for marking, stops, strategy exits and allocation trims while the master engine runs. An unavailable quote retains the last actual mark and its timestamp with a diagnostic. Stop and Kill retain their engine-wide freeze semantics.

### Allocation requirements

- **Toggles rebalance automatically.** Disabling a module distributes its target proportionally among the remaining enabled modules. Its relative weight remains saved, so re-enabling it restores that weight to the calculation. A single enabled module receives 100%; disabling every module targets 100% cash.
- **Sliders move together.** Moving an enabled slider holds its selected percentage and divides the remainder proportionally among the other enabled modules. Disabled sliders and the sole enabled slider cannot be adjusted. If the other active weights are zero, their remembered proportions are used, with original weights as the fallback. Moving a slider to 100% and back preserves the other modules' custom proportions.
- **The whole draft updates immediately.** Sliders, percentage labels, dollar amounts and Capital Distribution Matrix segments reflect the same allocations. Targets use two decimal places with largest-remainder rounding to total exactly 100.00%. This replaces the separate Reallocate action from v2.89.2.
- **Saving applies the configuration together.** Save Module Settings persists relative weights and module preferences alongside the other settings. Reloading discards unsaved drafts and restores the saved configuration. Toggles preserve watchlists, strategy parameters, prompts and history.
- **Targets remain distinct from holdings.** Saving an allocation does not itself place orders or close positions. The running engine uses saved targets for budgets and normal rebalancing, with existing cash limits and fresh-price safeguards. Actual cash may remain available until a qualified entry or executable exit occurs.

| Enabled modules / action | Target allocations |
| --- | --- |
| Equities, options, crypto and events; futures disabled | 38.89% / 27.78% / 22.22% / 11.11% |
| Equities and options | 58.33% / 41.67% |
| Move equities to 70% with only equities and options enabled | 70.00% / 30.00% |
| Equities only | 100.00% equities |
| No modules enabled | 100.00% cash |

The existing `allocations_json` stores relative weights across all five modules. The API exposes these as `allocation_weights`, and `allocations` contains normalized enabled targets. Positive fallback preferences are preserved in `module_settings_json`; `cash_allocation_pct` is 100 when all modules are disabled and otherwise zero. Existing weights and enabled settings are read without a schema or data migration. When both weights and effective targets are submitted, the backend verifies that they agree before saving.

Module health distinguishes **Disabled**, **Subscription required**, **Warming up**, and **Ready**, with additional Awaiting scan, Market closed, and Data unavailable states. Ready means the last scan successfully evaluated data, not that an entry qualified. **Check saved data access** probes one watchlist symbol per enabled module without starting execution, placing orders or recording warm-up observations; access confirmation does not certify full-watchlist freshness or profitability.

CIO evidence includes recalculated enabled targets, the cash target and actual cash. Prospective correlations and specialist mandates exclude disabled modules. Historical P&L and remaining positions stay in the total portfolio evidence as actual history and exposure.

## Implemented execution

`services/portfolio_engine.py` runs a persisted five-minute supervisor. It services each module independently and records symbol-level data failures. Start, Stop, Scan now, Kill switch and Acknowledge pause are available in Settings → Quantitative Strategy Engine. Installing the release does not start the new portfolio worker. Manual scans require a started engine.

| Module | Entry and exit behavior |
| --- | --- |
| Equities & ETFs | US regular trading sessions, including exchange holidays, DST and early closes. Completed daily candles supply the configurable SMA (default 200), Wilder RSI (default 2), positive 63-session momentum and relative strength against SPY. Entry requires an oversold lower-Bollinger-band pullback and a current price above the SMA. Exits use RSI recovery, trend failure or a two-ATR initial stop. The default watchlist includes sector ETFs SMH and XLK for relative-strength comparisons. |
| Options | Reads the Webull contract catalog and executable two-sided option quotes/Greeks. Chooses the expiration closest to 45 DTE within 20–65 days, then an OTM short leg nearest absolute 0.18 delta and an outward protective leg of the same expiration/type. Enters at short bid minus long ask. Reserves the spread's maximum loss, tracks both legs, records a persistent 50%-credit GTC exit rule, and closes using short ask minus long bid. Also exits at twice entry credit or seven DTE to reduce expiry/assignment exposure. This is a standard 100-share-multiplier spread simulation; no exercise/assignment engine is modeled. |
| Crypto spot | 24/7, completed hourly 20/10 Donchian channels, a 14-period ATR and a ratcheting 2.5× ATR stop. Current prices are compared with prior completed channels, avoiding use of a forming candle's high as its own breakout threshold. ETH/SOL require measured Bitcoin dominance at or below its previous seven-day average. BTC remains eligible independently of that altcoin filter. |
| Micro futures | MES, MNQ, MGC and MCL roots resolve to an unexpired contract, with contract multipliers and initial-margin reserves. Requires every completed one-minute candle in the configurable cash-opening range (default 9:30–9:45 ET), positive volume and directional VWAP confirmation. Simulates long/short breakouts; the opposite range edge is the stop. Entries stop 15 minutes before the US cash-session close; exits begin five minutes before it. Risk sizing includes open stop risk and the session's realized losses within a maximum $250 daily risk budget. Gaps, unavailable quotes and sampling delays can produce losses beyond that budget. |
| Event contracts | Consumes fresh eligible decisions and quotes from the existing enabled Event worker, with the configured series watchlist, at least 50% confidence and 1.5% net edge after the paper fee. Uses one position per contract per run and the portfolio event allocation. Marks at executable bids and settles only from an explicit provider-confirmed YES/NO result. Quotes never imply settlement. Event collection, AI configuration, logs and historical reports remain in the existing gear modal. |

The futures implementation uses VWAP as a breakout confirmation filter. It does not add a separate, independently parameterized VWAP mean-reversion strategy. Specialist prompts inform the CIO audit; deterministic strategy rules govern entries and exits.

### Data readiness

- The v2.89.1 adapter review verified Webull crypto snapshots/completed hourly bars, stock daily history, complete expiry-filtered option catalogs and all four micro futures contract lookups against the provider. It corrected endpoint parameters, nested candle responses and option pagination. Strategy histories reject synthesized OHLC; option spreads exclude FLEX/adjusted contracts; futures execution requires actual provider contract metadata instead of generated expirations.
- Market-data calls are paced per app key and endpoint across local threads. Futures use provider symbols, multipliers and last trading dates, with catalog initial-margin amounts as paper reserve assumptions when provider margin fields are absent. These reserve amounts are not current broker margin quotes.
- Quotes must carry valid provider timestamps and be no more than two minutes old. Completed intraday/daily bars must also pass freshness and OHLC validation. Data collection that outlives the quote freshness window cannot place a fill.
- Webull supplies quotes, crypto/futures bars and options data. The existing equity history adapter may use its Yahoo Finance fallback for daily research history; entry/exit prices still require fresh Webull snapshots.
- Options IV Rank is calculated from **252 daily observed ATM IV values**, using the rolling minimum/maximum. The engine collects and persists those observations as it scans. It does not substitute IV percentile for IV Rank or create a fictitious history. A new installation must accumulate the history before options entries can qualify.
- The altcoin dominance filter needs seven previous daily CoinGecko global-market observations. Missing or stale observations produce a visible warm-up/data-limited state.
- Quote permissions, missing Greeks, unavailable histories, insufficient capital/margin, and unqualified signals can result in no trade. The dashboard exposes module diagnostics and entry counts.
- During deployment verification, the personal Webull connection returned `MARKET_DATA_NOT_SUBSCRIBED` for both `US_OPTION` and `US_FUTURES` snapshots. Their contract catalogs were accessible, but those modules require quote subscriptions before execution can be verified against live data. No subscriptions were purchased and execution remained stopped.
- Open positions continue marking and honoring existing stops when indicator history fails but a fresh executable price remains available. When the price itself is unavailable, the position retains its last mark and a diagnostic explains the limitation.

Webull's [market-data permissions](https://developer.webull.com/apis/docs/market-data-api/overview/) require appropriate OpenAPI subscriptions for options and futures. Session scheduling follows [pandas-market-calendars](https://pandas-market-calendars.readthedocs.io/en/latest/usage.html). Micro contract multipliers are essential to P&L calculations; see [CME's micro futures specifications](https://www.cmegroup.com/articles/faqs/micro-e-mini-equity-index-futures-frequently-asked-questions.html).

## Accounting and isolation

The original `PortfolioStrategyAccount`, `PortfolioStrategyPosition` and `PortfolioStrategyOrder` remain the quantitative ledger. New tables are:

- `PortfolioEngineState`: run generation, persistent kill switch, pause reason, heartbeat, scan lease, audit cadence timestamps and module diagnostics.
- `PortfolioStrategyLot`: position ownership, collateral, multiplier, exits, entry costs, realized P&L and signal identity. A unique user/run/signal constraint prevents repeated fills.
- `PortfolioEquitySnapshot`: timestamped equity, cash, realized/unrealized P&L and module contributions.
- `PortfolioAudit`: historical CIO content, provider/model, status and exact measured evidence.
- `PortfolioMarketObservation`: daily measured IV and Bitcoin dominance.

Cash is reduced by reserved capital and entry fees. Equity equals cash plus reserved capital plus unrealized P&L. Spot positions reserve their purchase value; credit spreads reserve their maximum loss; futures reserve the configured contract metadata's initial margin. Closing releases collateral and books net P&L once. Entry credit for a spread is reflected in its net collateral requirement, rather than being counted twice as free cash.

Positions are limited to their module's remaining budget and available cash. Standard positions use at most 20% of a bucket and 0.5% of portfolio equity in modeled stop/max-loss risk. Futures may use a full bucket to accommodate indivisible margin requirements, while still obeying portfolio and daily risk sizing. Unused capital stays as cash. Estimated costs are 10 bps per side for equities/crypto, $0.65 per option leg per side, $1.25 per futures contract per side and $0.015 per Event entry/early exit; provider-confirmed Event settlement has no additional simulated exit fee. Equities, crypto and futures include 5 bps adverse fill slippage. These are research assumptions, not a broker fee schedule.

Execution never calls broker order-submission methods or writes manual Webull/Binance ledgers. The existing Event decision and settlement records are read as research inputs. Existing legacy Event hypothetical orders are neither migrated into bankroll P&L nor counted twice.

State row locks serialize ledger mutations. Provider requests run outside those locks. Supervisor mutations recheck an expiring scan token; the independent Event consumer rechecks controls and reset generation under the same row lock. Stop, reset and configuration edits invalidate pending work. A second process cannot claim a live supervisor lease. After a crash, the lease expires and a later scan can recover. An unmanaged legacy position blocks Start until a confirmed reset archives it.

## Portfolio risk and rebalancing

A portfolio equity loss of **10% or more of starting bankroll** triggers a persistent new-entry pause and a system notification while retaining existing-position management. The master kill switch also blocks new Event research scans. Explicit Stop freezes execution; it does not invent liquidation prices. Acknowledgment cannot bypass the drawdown floor through Start.

Rebalancing compares deployed capital (collateral plus unrealized P&L) with target portfolio weights. Exposure more than three percentage points above target is trimmed by closing whole positions at fresh executable prices, with the reason stored in orders. Underweight buckets receive available capacity for subsequent qualified entries; the engine does not force purchases merely to eliminate cash. Both target weight and actual deployed weight are visible.

The daily futures loss ceiling and portfolio circuit breaker operate on observed paper marks. They are execution gates, not guarantees of a bounded loss during gaps or data outages.

## Performance and CIO auditing

The dashboard includes the combined equity/cash curve, open positions, costs reflected in P&L, annualized return, Sharpe, Sortino, win rate and maximum drawdown. Historical queries use daily aggregates for long histories and compute maximum drawdown from all recorded marks. Charts use daily points after 2,000 intraday observations.

- Annualized return requires at least 30 elapsed days of the current paper run.
- Sharpe and Sortino require 30 consecutive-day return observations, annualize at 365 days for the mixed 24/7 portfolio, and assume a zero risk-free rate. Undefined ratios remain unavailable.
- Win rate uses closed lots after costs. Realized and unrealized P&L are distinct.
- Cross-module Pearson correlations use at least 30 paired daily P&L changes. Zero-variance or insufficient-history pairs remain unavailable. These describe observed module P&L, not an assumed correlation between asset labels.

CIO audits use the configured existing AI provider cascade and the supplied isolated-ledger evidence. They do not add live account context or web search. Audits are advisory and cannot change allocations or execute orders. Missing AI is reported as unavailable; provider failure is recorded as failed. No deterministic replacement claims to be a successful AI verdict.

The report modal displays persisted progress for the enabled specialists and the Master CIO synthesis, with elapsed time, the active provider/model, and expandable retry/fallback reasons. Evidence preparation accounts for 5%, specialist completion for 80%, and master synthesis/validation for the remaining 15%. This estimates work completed, not a guaranteed time remaining. Failed specialist stages count as finished but are labeled unavailable; only a completed master report reaches 100%. Closing the modal or logging back in reloads the same saved state, and open modals poll every three seconds.

Gemini 3 uses `thinkingLevel` (Extra High maps to High); Gemini 2.5 retains `thinkingBudget`. Gemini credentials travel in `x-goog-api-key`. Ollama Cloud uses the local server's authenticated `/api/chat` proxy and the exact saved cloud model name. Each specialist response finishes before the next prompt, and all completed specialist assessments are included in the master request.

Transient audit-provider failures (timeouts, temporary HTTP 429 throttling, and HTTP 5xx server errors) retry the same tier, by default up to three transport attempts with approximately 15- and 30-second backoff plus jitter. `Retry-After` and Gemini `RetryInfo` delays take precedence; long reset periods are recorded as cooldowns rather than repeatedly retried. Daily quota, authentication, permission, and missing-model errors can advance directly to the next configured tier. The bounded cascade can still fall back if a cloud provider remains unavailable even with usage remaining. No unused key or unconfigured model is added to the chain. Controls: `AI_AUDIT_PROVIDER_RETRY_ATTEMPTS` (1–5), `AI_AUDIT_PROVIDER_RETRY_DELAY_SECONDS` (1–120), and the existing provider timeout and prompt-interval settings. Provider errors are stored with credentials redacted.

Protocol references: [Gemini Generate Content thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking), [Gemini retry guidance](https://ai.google.dev/gemini-api/docs/troubleshooting), [Ollama Cloud](https://docs.ollama.com/cloud), and [Ollama chat API](https://docs.ollama.com/api/chat).

As of v2.94.7, specialist prompts execute strictly one at a time with a minimum 15-second interval after each terminal response; Master CIO synthesis starts only after every enabled specialist has completed or failed. Provider generations are serialized across application processes, and autonomous Event/sentiment AI work is deferred while a quantitative audit is pending. Each provider request may wait up to 10 minutes for a response before failover. Ollama is additionally host-serialized so the application cannot load two local models concurrently; the production service is constrained to one loaded model with a 30-second keep-alive.

Audit cadence is off by default, with daily and weekly options. Daily audits run after the session close; weekly audits run after the first available session close of the week. Failed attempts are archived and do not retry every supervisor tick. The audit worker is separate from execution so a slow AI response does not hold up paper position management. The latest 50 audits, including older paper runs, can be selected in the UI; all remain in persistence.

## API

All routes require an authenticated administrator under `/api/webull/portfolio-algo`:

| Method / path | Behavior |
| --- | --- |
| `GET /config` | Saved relative weights, effective enabled targets, module preferences, account and canonical defaults. |
| `POST /config` | Atomically validate and save allocation weights/targets, watchlists, module parameters, CIO mandate and cadence. |
| `GET /status` | Worker health, Event dispositions, account, positions, curve, metrics, goal tracking, Event calibration and drift. |
| `POST /validation` | Administrator-uploaded, bounded equities/crypto historical replay; no trading or AI calls. |
| `POST /data-check` | Read-only access probe for enabled modules using saved settings. |
| `POST /control` | `action`: `start`, `stop`, `scan`, `kill`, or `acknowledge`. |
| `POST /reset-bankroll` | Requires `confirm: true`; archives current run and creates the requested $100–$1,000,000 bankroll. |
| `POST /master-audit` | Runs an on-demand CIO audit, optionally with a draft prompt. |
| `GET /audits` | Latest 50 historical audits with evidence. |

## Verification and operation

`tests/test_portfolio_algo.py` covers strategy math, holidays/early closes, validation, authentication, ledger accounting, fees, derivatives, duplicate prevention, concurrent PostgreSQL worker claims, reset fencing, the circuit breaker, Event settlement, crypto lifecycle/stops during history outages, and the actual AI call contract. Integration tests require an explicitly supplied **isolated PostgreSQL** URI through `QUANT_TEST_DATABASE_URI`. They must never target the personal-instance database.

The v2.89.1 verification passed 159 tests across the quantitative engine, Event worker, AI failover, Webull data/contracts, market-data routes and manual paper/order capability regressions. Provider regressions include actual nested crypto candle formats, required category/timespan parameters, bounded option pagination and missing futures metadata. Read-only live checks complement these tests; no paper or real orders were submitted during deployment checks.

Deployment initializes the schema once through runtime.py init-db, rebuilds the frontend and restarts the services. deploy/crypto-dashboard.service serves Gunicorn with two threaded web workers. deploy/crypto-dashboard-worker.service runs runtime.py worker, with a dedicated PostgreSQL advisory lock enforcing one scheduler and a heartbeat reporting its supervised jobs. Web requests never start background jobs. Provider cooldowns/search caches are shared through the new provider_request_states table; user_settings.telegram_notifications_enabled is an additive, default-enabled setting. It preserves existing paper research and unrelated personal-checkout files. Administrative Start and audit cadence selection are explicit operational controls; deployment does not activate them.

The remaining operational work is gathering sufficient forward observations and confirming entitled provider data. This release implements the roadmap's paper execution, telemetry, rebalancing, auditing and circuit-breaker controls; it does not establish strategy profitability or live-trading readiness.

The v2.89.2 regression coverage additionally verifies disabled entry/data gates, retained settings/history/marks, re-enable status, Event collector gating, cash-aware audit evidence, explicit allocation rounding, provider cooldown/search behavior, and singleton scheduler ownership. Provider subscriptions, quota allowances and forward-history requirements still apply.

The v2.89.4 allocation tests cover all 32 enabled-module combinations, the approved percentage examples, slider endpoints and remembered proportions, exact totals across repeated toggles/reloads, backend validation, persistence, execution budgets, existing-position management and cash-aware CIO evidence. Browser verification checks the rendered controls, draft isolation and save/reload behavior against an isolated test ledger.

## v2.98.7 configuration preservation and report health

Ordinary portfolio configuration saves merge audit cadence into the saved dedicated AI configuration, preserving providers, models, keys and shared guidance. This does not repair configuration lost before the upgrade or change the scheduler.

Report health badges use the archived structured worker/module status and risk controls. A failed report, successful generation, or wording about a risk circuit cannot establish healthy operation or an active pause. Reports without sufficient structured evidence are labeled unverified; all badges describe the report timestamp, not current telemetry. Original archived report prose is preserved.

## Audit scheduling and deferrals (v2.98.8)

The master Off/Daily/Weekly control now governs automatic portfolio audits independently of the Event operational report interval. Off disables automatic master audits; manual requests remain available. Daily runs after the latest completed NYSE session close, including early closes, with one catch-up after downtime rather than a backlog. Enabling Daily before today's close can therefore catch up the previous session. Weekly runs after the first NYSE session close of the current Eastern calendar week, moving past holidays; a missed run can catch up during that week. The last reservation timestamp prevents repeated runs for the same close, including when a manual audit has already run after it.

An automated Event AI request deferred by a pending portfolio audit is recorded as an informational skip, without provider failover, failure notification, or added failure backoff. Unfinished contracts become eligible again on the normal scan interval, subject to the existing batch budget and scheduling gates. Already completed batch results are retained. A deferral supplies no new prediction and does not authorize a trade. The separate Event operational report cadence remains configured in hours.

## Event entry and settlement controls (v2.98.12)

Entry qualification and fresh-quote revalidation now check the bid and spread of the selected YES/NO outcome. A tight spread on the other outcome cannot qualify the selected side or improve its spread score. Missing/out-of-range bids, crossed books, and explicitly supplied ask sizes below one contract or invalid sizes block entry. An unavailable ask size remains unknown; it is not evidence of available depth. Contract-wide volume/open-interest gates remain in place. This release does not add depth-aware quantity sizing or repair provider timestamp provenance.

The Event supervisor checks due settlements for administrator-owned paper configurations before applying stopped, killed, module-disabled, or master-pause entry gates. It preserves those controls and does not start scans or scheduled Event AI reports while stopped/killed/master-paused. Empty settlement queues do not require credentials or provider requests. Existing resolution throttling, provider evidence, user isolation, and duplicate-settlement prevention remain in effect. This records confirmed outcomes and settles legacy simulated Event orders; an explicit portfolio Stop still freezes portfolio ledger execution until resumed. Kill/circuit monitoring can consume confirmed outcomes under its existing position-management rules. Settlement still shares the Event worker with AI reporting; separating those workloads remains deferred.

## Saved Event risk policy (v2.99.0)

The quantitative ledger now reads the originating Event configuration at the locked entry point. Saved dollar-per-entry, open-dollar, open-position and contract-count limits replace the hard-coded entry caps. Zero limits block new entries. Missing keys receive documented defaults; malformed, negative, nonfinite or fractional count limits are rejected. Entry fees count toward dollar exposure. The ledger also applies the smaller of the saved loss allowances after reserving all existing Event stakes plus entry and estimated early-exit fees. Gains do not expand the nominal period limits.

Hourly loss uses the trailing hour. Daily loss starts at Eastern midnight, including daylight-saving offsets. Drawdown uses the high-water mark of cumulative closed-trade Event net P&L within the current portfolio generation; it is not a mark-to-market drawdown estimate. Open trades reserve their full modeled loss, rather than spending unrealized gains. Existing portfolio cash, allocation, 20%-of-module position budget and 0.5%-of-equity modeled-risk checks remain additional ceilings. Tightening limits stops or reduces new entries; it does not force liquidation of existing holdings.

The current selected-outcome ask size, when supplied, caps integer contract quantity. Absent depth remains UNKNOWN in archived fill evidence, with conservative saved dollar/count/loss limits still applied. This is a disclosed paper-fill assumption, not proof that the market could fill that quantity. Fresh quote refreshes remove old depth fields before applying the new snapshot. Each attempted fill records its saved limits and available allowance; telemetry and audit evidence read the same policy.

Regression tests use synthetic ledgers, including a temporary PostgreSQL instance to verify two concurrent entries cannot overspend saved exposure. They do not validate forecast profitability or real venue fill quality.

## Settlement timestamp evidence (v2.99.20)

New confirmed Event outcomes retain a precise provider payout timestamp only when it has an explicit timezone or numeric epoch and falls between cutoff and the local confirmation observation. Date-only, missing, ambiguous, invalid, pre-cutoff or future payout times use the observation recorded after the provider response. Saved `_settlement_timing` evidence identifies `PROVIDER_PAYOUT_TIMESTAMP` or `OBSERVED_RESOLUTION`, the reason, and the original payout value. An observation fallback describes when this system learned the result; it does not reconstruct the exchange's settlement instant.

`services.event_settlement_timing.repair_date_only_settlements` previews eligible historical corrections by default. Applying requires an explicit saved result matching the outcome, an exact date-only-to-midnight defect, and an observation at or after cutoff. It locks affected rows, limits each batch, preserves original outcome/order timestamps in evidence, and leaves monetary fields unchanged. The caller owns the transaction and commit. Matching legacy orders are scoped by user, symbol, original timestamp and configuration when available. Repeated repairs do not update already-corrected rows. Inspect skip/truncation counts before applying; this is a maintenance helper, not an automatic worker migration.

The personal-instance inspection for this release found 656 resolved outcomes before cutoff and 69 matching legacy simulated orders. All 656 saved payloads lack explicit settlement proof and instead contain near-terminal trade prices. The repair rejects them; no production history was rewritten. They remain excluded by the calibration timestamp check. Provider outcome verification and any resulting ledger/report correction remain necessary; saved legacy P&L must not be treated as verified by this timestamp release.

## Historical provider verification (v2.99.21)

The 656 historical outcomes identified in v2.99.20 were subsequently checked against the listing exchange's exact-contract finalized results. All 656 results match the saved outcomes. The v2.99.21 personal-instance upgrade replaces their date-only midnight timestamps with the provider's precise settlement timestamp and adjusts 69 matching legacy simulated-order timestamps. It records `KALSHI_FINALIZED_MARKET` provenance and the new verification observation time. Original outcome records, including their raw evidence and old observation/source fields, and affected order records are retained under `_settlement_timing.repair`. Quantities, entry prices, fees and realized P&L remain unchanged. Archived reports are not rewritten; newly generated calibration uses repaired outcomes subject to its existing user/run and pre-cutoff forecast checks. Historical verification does not establish prospective profitability.

The maintenance workflow is `collect_legacy_settlement_evidence(user_id, limit=100, after_id=0)` followed by `repair_verified_legacy_settlements(plan, user_id=..., apply=False)`, both in `services/event_settlement_repair.py`. Collection closes its database read connection before provider requests. Batches are capped at 1,000 candidates and expose a cursor and truncation flag. Preview/application makes no provider requests. Apply only after reviewing the preview, in a clean session with transaction/lock timeouts and an explicit caller commit. The plan is trusted maintenance input, not a public API. Application validates the saved provider payload again, locks and reloads current rows, and rejects outcomes changed since collection. It updates only matching paper-order timestamps; conflicts, unavailable evidence and changed records are reported and left untouched. Repeated application cannot apply the same correction twice. Provider timestamps must include a timezone; date-only or naive timestamps and boolean payout values cannot establish provider settlement proof.

## Audit ownership and provider queues (v2.99.22)

The existing independent recovery thread checks pending audits every 30 seconds. Overall audit duration defaults to 3,600 seconds, configurable through `AI_AUDIT_MAX_DURATION_SECONDS` within 900–10,800 seconds; progress never renews that overall deadline. The idle allowance is the larger of 900 seconds and the configured provider timeout plus 180 seconds. Invalid/future progress timestamps do not establish fresh ownership. Recovery preserves completed evidence, records a reason and fails the audit without inventing a verdict. It now also handles audits whose portfolio generation is missing or has changed; those audits cannot retain exclusive AI access.

Shared provider queues now use nonblocking lock attempts. Regular AI requests defer after 60 seconds of contention; portfolio audit queue allowance is the larger of 900 seconds and the provider timeout plus 180 seconds, additionally subject to the audit's own expiration checks. Queue deferral is a scheduling event, not a provider failure or a reason to try another tier. PostgreSQL locks remain scoped per user/provider, with host-wide Ollama serialization. Waiting checks persisted audit ownership every half-second, and lock connections do not retain an open transaction during provider work. Lock release/connection cleanup also runs on cancellation and errors.

Fresh, read-only checks before and after provider calls reject late output after recovery or a portfolio reset. Cancellation cannot be interpreted as a transient provider timeout and retried or failed over. Preparation evidence and completion logs are written through the same pending-audit fence as final results. An HTTP request already in progress still relies on the provider transport timeout; this does not forcibly stop an upstream inference or refund provider usage. Cooldown/backoff sleeps retain their existing bounded delays, with ownership checked before another provider attempt. No live paid AI calls are needed for regression verification.

Verification passed 57 focused tests on an isolated UTF-8 PostgreSQL instance, including full audit execution, cancellation during preparation, and deadline expiry at final publication. The full ledger suite was not certified: `test_audit_with_positions_in_every_module_and_dedicated_ai_tiers` fails while creating a holding, before invoking the audit. Entry/allocation code is unchanged by this release. The unrelated fallback-search cooldown regression below also remains open.

## Release checkpoints toward v3.00.0

- v2.99.0: Saved Event risk enforcement, reported-depth sizing, policy evidence, and concurrent-entry verification.
- v2.99.16: Repaired the dormant single-contract Event AI helper to load saved or explicitly supplied provider configuration. Regression coverage checks configuration routing, disabled/nontradable skips, and audit deferral. The active batch predictor is unchanged.
- v2.99.17: Calibration eligibility and per-contract deduplication now precede the sample limit. Database regressions cover repeated forecasts, invalid early predictions, duplicate outcomes, deterministic ties, user/run isolation, truncation and matched model/market samples.
- v2.99.18: Added matched calibration comparisons by archived model/strategy version, contract duration and UTC forecast month. Tests cover historical attribution, matched denominators, missing metadata, date boundaries and disclosed group limits.
- v2.99.19: Separated quote, retrieval, trade and underlying-observation timing; preserved timestamp basis in model context and decision evidence; rejected stale/invalid/future quotes at entry; removed stale underlying prices and spot-as-reference substitution from calculations.
- v2.99.20: Corrected new settlement timestamps and saved their basis; added a guarded historical repair with PostgreSQL regression coverage. All 656 affected historical outcomes lack explicit saved settlement proof and remain unchanged pending provider verification.
- v2.99.21: Independently verified all 656 affected historical outcomes with no winner conflicts; repaired their timestamps and 69 matching legacy paper-order timestamps, retaining original evidence and monetary values. Added bounded collection, preview, stale-row protection, rollback and calibration regression coverage.
- v2.99.22: Bounded shared provider queue waits, added fresh cancellation checks before/after AI calls, recovered obsolete-generation audits, and fenced preparation/completion writes. Verified independent recovery, deadline limits and PostgreSQL lock cleanup. The older web-search fallback cooldown regression remains open.
- Subsequent completed release checkpoints advance through v2.99.1, v2.99.2, and so on. The remaining list below defines review work, not a promise that all findings are already known.
- Reserve v3.00.0 for the final fix. Before declaring readiness, present completed fixes, test evidence, unresolved findings, and research/data limitations and obtain the user's explicit permission. Do not label incomplete review or unavailable empirical validation as 100% complete.

## Remaining review items after v2.99.22

These review findings remain deferred, not fixed or certified by this release:

- Review the legacy standalone Event hypothetical-fill path separately; the active quantitative ledger now enforces the saved Event risk policy.
- Validate exchange quote/underlying timestamps where available and measure retrieval-time assumptions against independent data; timestamp separation and stale-underlying suppression are implemented.
- Validate paper fills against historical order-book depth and adverse execution scenarios; reported-depth limits and explicit UNKNOWN handling are implemented, but missing-depth fills remain a disclosed research assumption.
- Correct Event audit sampling, missing-value/status defaults, and unsupported model conclusions; render factual report tables deterministically.
- Separate time-sensitive scans/settlement from AI reporting; add progress deadlines and latency measurements.
- Unify Event producer and portfolio watchlists and count actual AI requests against batch budgets.
- Restore shared cooldown behavior for DuckDuckGo/Google fallback searches and make the old `test_search_failure_returns_zero_sources_and_cools_down` fully offline. The current fallback makes repeated GET/POST requests during outages; this existing regression is outside the v2.99.22 audit-queue fix.
- Reconcile the older all-module audit test fixture with current allocation/risk requirements, then finish the broader ledger regression run; it currently fails before audit execution when a requested holding cannot be opened.
- Plan verified options IV history collection/import and consistent ATM/expiration methodology.
- Validate forecast skill, realistic fills/costs, correlated exposure and held-out strategy performance before expanding risk.
- Label module P&L correlations accurately and disclose the single-symbol equity/crypto replay scope.
