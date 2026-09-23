# Version 4.0.0 QA audit and detailed remediation plan

**Audit date:** September 23, 2026  
**Application baseline:** v4.0.0, commit `0240359e894294e9ce2a17b3855ba60e2f7a5e56`  
**Status:** Findings and proposed work only. No fixes implemented.  
**Authorization:** The current task authorizes creation of this report only. It does not authorize application edits, migrations, destructive tests, commits, releases, or deployment.

## 1. Executive assessment

The audit identified serious errors in financial calculations, broken Webull workflows, unsupported dashboard claims, incomplete APIs, accessibility defects, and gaps in regression coverage. The production build passing does not establish that these features work.

The highest priorities are financial-data correctness, removal of fabricated market information, Webull connection and order-screen failures, sentiment outcome grading, and account-deletion integrity. Other findings concern still-registered legacy paths or dormant code; those are explicitly distinguished from defects reproduced in current user flows.

This document preserves all 31 findings from the delivered audit, adds specific implementation contracts and acceptance criteria, and records the Jev coverage assessment. It does not attribute code to AI authorship: the observable problems are hardcoded claims, disconnected controls, stubs, and untested execution paths.

### Evidence vocabulary

- **Reproduced:** A controlled execution demonstrated the failure. Provider calls were mocked where appropriate; this does not imply a live broker transaction occurred.
- **Browser reproduced:** The built frontend demonstrated the behavior in a browser using controlled API responses.
- **Code/schema confirmed:** The relevant implementation or database relationship establishes the defect, but the potentially destructive or external action was not executed.
- **Static candidate:** Reachability or data-flow analysis identifies a concern that requires verification before deletion or a broader behavioral claim.
- **Unverified:** The audit did not establish a pass or a production defect.

### Priority definitions

- **P1 / High:** Incorrect financial results, misleading financial information, failure of an essential connected-account workflow, or significant user-data integrity concerns.
- **P2 / Medium:** Broken supported functionality, misleading success responses, accessibility barriers, or unreliable recovery.
- **P3 / Low:** Dormant defects, visual polish, cleanup, or documentation drift without a demonstrated primary-flow failure.

Priority is remediation order, not a security vulnerability severity rating. This was not a dedicated penetration test.

## 2. Audit coverage and limitations

| Verification | Result | Interpretation |
|---|---|---|
| Frontend production build | Passed; 1,161 modules transformed | Bundling succeeds; undefined runtime names still exist |
| Python syntax checks | 193 modules passed | Syntax validity, not runtime correctness |
| JavaScript tests | 44 passed, zero failed | Existing tested utility/contracts passed |
| Python discovery | 783 executions, 781 passed, two failed, zero skipped | Two failures are the same test imported into a second module |
| Unique Python test identifiers | 733 | 50 executions are duplicates |
| Existing browser suites | Four passed, two unsuccessful | Jev settings, order tables, positions, and release-2.94.0 checks passed; audit-progress and goal-tracking fixtures are incomplete |
| Browser route/theme/viewport sweep | 68 page loads | 17 routes, widths 1,440 and 390, light and dark themes |
| Frontend dependency audit | Zero reported advisories | Time-bound npm result; not a full dependency/security assessment |
| Route map | 307 distinct method/path pairs; no duplicate pair found | Does not establish route correctness |
| Git whitespace validation | Passed | No tracked application changes from audit |

The Python suite ran against an isolated UTF-8 PostgreSQL 17 instance where applicable. The frontend was built from an isolated repository copy. Browser tests used API fixtures and did not validate production account data end to end. Temporary processes, databases, copies, and scratch artifacts were removed after the audit.

The existing `docs/CODEX_JEV_INTEGRATION_SPEC.md` was untracked before this report task and was not changed. The report is the only intentional new artifact of this task.

### Known testing qualifications

1. `test_scan_warming_up_status_does_not_degrade_worker` mocks the primary quote as warming up, but its options/futures mocks do not return the expected three-item result. Their unpacking failures correctly produce degraded data status. This is an invalid fixture expectation, not proof that the production worker mishandles warming-up status.
2. Audit-progress and goal-tracking browser tests first lacked Jev telemetry response fields. An in-memory fixture adjustment exposed additional missing quantitative `settings`/array fields. Both suites remain unsuccessful and require current API-shaped fixtures before their feature assertions are meaningful.
3. A staking page error caused by an incorrectly shaped audit fixture disappeared when the fixture was corrected. It is not included as an application defect.
4. TradingView/external-widget network failures were intentionally induced by blocked external resources. They are not classified as application bugs.
5. No live trade, real paid Vercel inference, destructive account deletion, or production-data mutation was performed. Broker behavior, actual provider credentials, and complete financial/legal compliance are not certified.
6. The audit does not prove that every possible branch is defect-free. Counts of static warnings must not be treated as counts of independently confirmed bugs.

## 3. Remediation contracts shared by all findings

These are requirements for a future authorized implementation, not actions taken now.

1. Preserve user, account, provider, environment, and paper/live boundaries. Never infer a live account or execution mode as a fallback.
2. Unknown financial data must remain explicitly unknown. Do not replace unavailable quotes, fees, confidence, multipliers, or outcomes with plausible-looking constants.
3. Preserve upstream records as evidence. Derived report corrections must not silently rewrite broker history or trade execution records.
4. Every asynchronous or external failure needs a structured outcome and safe diagnostic context. Never log credentials, full sensitive provider bodies, or private message contents as error context.
5. Add tests that reproduce behavior, not assertions that merely duplicate implementation. Reuse existing test modules and fixtures where practical.
6. Each finding has its own acceptance gate below. A successful build alone cannot close a runtime or financial-calculation finding.
7. Schema migrations, if required, must be additive first, repeatable, and tested against isolated PostgreSQL. No production backfill or deletion is authorized by this document.
8. Proposed paths and helper signatures below are design choices, not claims that those files/functions already exist. Line references identify the audited baseline and can move later.

## 4. Detailed findings and exact proposed fixes

### QA-01 — Webull token initiation references an undefined request body

**Priority:** P1. **Evidence:** Reproduced.  
**Location:** [routes/system.py](../routes/system.py), `api_initiate_webull_token`, approximately line 1982.

**Observed:** A user with saved Webull credentials and no pending token receives HTTP 500 before the provider is called. `force = bool(data.get(...))` accesses undefined `data`. A pending-token early return can conceal the defect.

**Implementation:**

1. Parse an optional JSON object once at handler entry. An absent body means `{}`; malformed JSON or a non-object body returns a structured 400 response.
2. Read `force` from JSON when present; otherwise read the query parameter for backward compatibility. Accept JSON booleans and query strings `true`, `false`, `1`, `0`; reject other supplied values. Do not use Python truthiness for the string `false`.
3. Preserve the existing pending-challenge deduplication: an active, same-environment `PENDING` challenge returns its existing state even if `force` is supplied. Document that `force` means refresh a normal token, not send duplicate SMS challenges.
4. For a normal same-environment token and `force=false`, retain the connection-check path. Otherwise initiate once, persist token state transactionally, and return the existing sanitized response shape.
5. Keep credential validation before any provider request and rollback on persistence/provider failure.

**Acceptance:** Cover missing credentials, absent body, malformed body, each accepted false/true representation, pending deduplication, normal-token reuse, forced normal refresh, environment mismatch, and provider failure. Assert provider call counts and absence of key/token material in responses/logs. A fresh valid request must reach the provider instead of raising `NameError`.

### QA-02 — Live Synthetic Orders and missing-price scheduling reference undefined variables

**Priority:** P1. **Evidence:** Synthetic Orders browser reproduced; scheduling branch code confirmed.  
**Location:** [frontend/src/pages/WebullTrading.jsx](../frontend/src/pages/WebullTrading.jsx), approximately lines 7364 and 1550.

**Observed:** The live Synthetic Orders tab passes undefined `effectiveAccountId`. Scheduling can reference undefined `selectedHolding` when earlier price sources are absent.

**Implementation:**

1. Trace the account state already used by working live order panels. Derive a single explicit selected account identifier from that state and pass it consistently to Synthetic Orders. Do not substitute the first account or a paper account.
2. If no live account is selected, render a selection-required state and make no synthetic-order request. On account/mode changes, cancel or ignore stale responses from the prior selection.
3. Resolve the scheduling holding from the current account plus instrument identity, including contract identifier where relevant. Use this actual holding in the price fallback; do not create an unrelated alias merely to silence lint.
4. Only accept finite positive prices. If no quote is available, show a clear unavailable state; permit explicit user price entry only where the scheduled order type supports it. Disable submission when its required price is absent.

**Acceptance:** Open Synthetic Orders in real and paper modes; switch two accounts; test no selected account; ensure requests stay account-scoped. Open scheduling with a live quote, holding-only quote, zero/NaN quote, and no quote. No reference errors, stale-account data, or implicit live submission is allowed.

### QA-03 — Webull sentiment grading silently fails

**Priority:** P1. **Evidence:** Reproduced with one due signal; zero grades and no grading-helper invocation.  
**Location:** [services/webull_signal_service.py](../services/webull_signal_service.py), `evaluate_due_webull_signals`, approximately line 252.

**Observed:** `_latest_market_price` is undefined. The broad per-signal exception handler rolls back without exposing why grading stopped. Linked Jev evaluations consequently lack outcomes.

**Implementation:**

1. Introduce one tested, read-only quote-resolution helper returning a price, quote timestamp, and source/status. Reuse existing Webull market snapshot/bar and option snapshot adapters; do not route outcome grading through an order function.
2. Supply the persisted signal's full instrument identity. Inspect available signal fields and original captured metadata; if an option cannot be identified unambiguously, retain an explicit unscored state instead of using the underlying stock. Add persisted identity fields only if necessary and never guess historical contract IDs.
3. Validate finite positive prices and timestamps. Apply the signal's existing outcome policy and Jev's documented target-time tolerance separately; a current quote must not be presented as an exact historical-horizon price.
4. Use the shared trading calendar from QA-22 for session-sensitive instruments; crypto remains independently available.
5. Preserve per-signal commits so one failure cannot erase prior grades. Log a sanitized signal/user/provider identifier and failure category; return or expose attempted, graded, skipped, and failed counts without changing legacy callers unexpectedly.
6. For prior due records, recompute only where reliable target-window evidence exists. Otherwise report missing/late data; do not invent historical outcomes.

**Acceptance:** Due crypto and equity signals grade exactly once; future/already-graded signals remain unchanged; expired credentials, missing option identity, stale quotes, and connector failures remain explicitly unscored. One failed signal must not prevent a later valid signal grading. A linked Jev record receives an outcome only within its stated tolerance.

### QA-04 — Long-term tax classification uses an incorrect 365-day threshold

**Priority:** P1. **Evidence:** Reproduced.  
**Location:** [routes/portfolio.py](../routes/portfolio.py), `_build_tax_transactions`, approximately line 4819; [tests/test_tax_report_calculations.py](../tests/test_tax_report_calculations.py).

**Observed:** January 1, 2024 to December 31, 2024 is classified long-term. The existing `test_exact_365_day_holding_is_long_term` encodes this incorrect result.

**Rule source:** The IRS requires more than one year and begins counting on the day after acquisition. See [IRS Topic 409](https://www.irs.gov/taxtopics/tc409). This fix addresses the ordinary holding-period calculation, not all instrument-specific tax rules.

**Implementation:**

1. Extract a date-based holding-period classifier; do not use elapsed seconds or `>=365` as the legal test.
2. Normalize tax dates through one documented report timezone/date policy. Preserve an original broker trade date when supplied; do not allow arbitrary server timezone to change classification.
3. For ordinary acquisitions, classify disposal on the one-year anniversary as short-term and after it as long-term. Specify February 29 anniversary handling explicitly and verify that boundary against authoritative guidance before implementation is accepted; do not hide a leap-date assumption in a generic date library.
4. Apply classification per consumed lot slice. Preserve mixed-term sales and unknown-date classification. Do not extrapolate this rule to special contract tax treatment.
5. Replace the incorrect test and recalculate derived report output on read. No broker record rewrite is required.

**Acceptance:** January 1, 2024 to December 31, 2024 is short-term; January 1, 2024 to January 1, 2025 is short-term; January 2, 2025 is long-term. Include ordinary/leap-year boundaries, leap-day acquisition with a source-backed expected result, mixed lots, missing dates, and report-timezone boundaries. The leap-day rule is an explicit validation prerequisite, not an implementation guess.

### QA-05 — Webull tax values omit contract multipliers

**Priority:** P1. **Evidence:** Standard option example reproduced; futures exposure identified in shared calculation.  
**Location:** [routes/portfolio.py](../routes/portfolio.py), `_build_webull_tax_report`, approximately line 4914.

**Observed:** One standard 100-share option bought at $2 and sold at $3 with $0.01 fees each produces $0.98 gain instead of $99.98.

**Implementation:**

1. Normalize each fill into quantity, quoted price, contract multiplier, currency, actual fees, account, instrument ID, and execution time before tax-lot construction.
2. Calculate gross monetary value as `abs(filled_quantity) * filled_price * multiplier`; keep quantity in original units/contracts for lot matching. Add acquisition fees to basis and subtract disposal fees once.
3. Source option/futures multipliers from authoritative instrument metadata or a verified existing normalized contract model. Do not assume all options are standard 100-share contracts or use one futures multiplier globally.
4. For instruments requiring an unknown multiplier, return an incomplete-calculation warning and exclude unsupported monetary totals rather than silently using 1. Ordinary unit-priced assets use multiplier 1.
5. Preserve multiplier and source in report provenance. If historical orders lack the metadata, add an explicit enrichment path; do not infer from current holdings when the contract identity differs.
6. Use Decimal or equivalent precise monetary arithmetic internally and round at defined output boundaries. This does not establish full options/futures tax compliance.

**Acceptance:** Reproduce $200.01 basis, $299.99 proceeds, and $99.98 gain for the standard example. Cover fractional fills, adjusted options, two different futures multipliers, missing multiplier, and multiplier-1 assets. Verify fees are not multiplied or counted twice. Unknown contract values must not look complete.

### QA-06 — Tax lots cross Webull account boundaries

**Priority:** P1. **Evidence:** Reproduced.  
**Location:** [routes/portfolio.py](../routes/portfolio.py), approximately line 4925.

**Observed:** Account B's sale consumes account A's acquisition. The reproduction reports $119.98 instead of $19.98 gain.

**Implementation:**

1. Replace the concatenated asset-only key with a canonical lot identity containing provider, environment, account ID, currency, instrument type, and stable instrument identity. Keep contract variants distinct.
2. Carry account identity through raw transactions, normalized rows, remaining-lot output, and manual adjustments. Do not rely on an account appearing only inside `txid`.
3. Missing account identity must create an explicitly unassigned/incomplete pool and must never match an identified account's lots.
4. A cross-account transfer needs explicit paired transfer records carrying original basis/date; do not implement transfer handling by pooling unrelated accounts.
5. Aggregate account-specific results only after lot matching, and expose account identity in exported detail.

**Acceptance:** A buys at $100, B buys at $200, B sells at $220: consume B's lot and leave A's lot untouched; gain is $19.98 with the audit fees. Repeat with identical symbols across currencies, contracts, and missing accounts. Verify legitimate recorded transfers preserve basis without global pooling.

### QA-07 — Executed portions of canceled orders are omitted from tax history

**Priority:** P1. **Evidence:** Reproduced.  
**Location:** [routes/portfolio.py](../routes/portfolio.py), approximately line 4888.

**Observed:** A canceled order with a 0.5-unit execution produces no tax row. The same status-based design risks excluding fills on still-open orders.

**Implementation:**

1. Prefer individual execution records with stable fill IDs, execution timestamps, quantities, prices, and fees. Include actual positive executions regardless of the unfilled remainder's status.
2. If the current model only stores cumulative fills, normalize one cumulative execution aggregate per provider/account/order and replace that aggregate on refresh; never append the entire cumulative quantity again.
3. Do not treat order creation/update time as an exact fill time when executions span dates. Mark aggregate timing limitations and prevent a false claim of precise tax-date allocation until broker fills are available.
4. Keep genuine zero-fill orders excluded. Flag contradictory provider data rather than fabricating an execution from the requested order price.

**Acceptance:** Canceled partial, open partial, and completed orders include only actual filled quantities; zero-fill orders do not appear. Repeated synchronization is idempotent. An increase from 0.5 to 0.75 cumulative quantity does not yield 1.25. Multi-date fills retain their actual execution dates when available.

### QA-08 — FIFO/LIFO selection is saved but ignored

**Priority:** P1. **Evidence:** Code confirmed.  
**Location:** [frontend/src/pages/Settings.jsx](../frontend/src/pages/Settings.jsx), approximately line 4808; [routes/portfolio.py](../routes/portfolio.py), `_build_tax_transactions`; Help tax guidance.

**Implementation:**

1. Keep the existing offered FIFO and LIFO methods and implement both. Change the calculator contract to accept an explicit validated method; pass the current user's setting from every report/export caller. Existing unset settings default to FIFO.
2. FIFO consumes the oldest remaining eligible lot; LIFO consumes the newest. Use a stable sequence/ID tie-breaker for equal acquisition dates. Partial consumption must conserve remaining quantity and basis.
3. Apply QA-06 account/instrument boundaries before either selection rule. Return the applied method in report metadata and display/export it.
4. Reject unsupported method submissions rather than silently coercing them. Remove HIFO claims from Help for this repair; HIFO is not part of the proposed implementation.
5. Describe the selection as the report's calculation method, not a guarantee that it is permissible for every asset/jurisdiction/account. Do not alter broker source history when the method changes.

**Acceptance:** For buys of one unit at $100 and one at $200, then a sale at $250 before fees, FIFO gain is $150 and LIFO gain is $50. Cover partial lots, mixed holding periods, same-time lots, user isolation, save/reload, export agreement, default FIFO, and invalid settings. Reopening the report must use the saved method.

### QA-09 — Optional dashboard cards display fabricated live information

**Priority:** P1. **Evidence:** Browser and code confirmed, including AI-disabled state.  
**Locations:** [AIPulseWidget.jsx](../frontend/src/components/AIPulseWidget.jsx), [RiskMonitorWidget.jsx](../frontend/src/components/RiskMonitorWidget.jsx), [GasMonitorWidget.jsx](../frontend/src/components/GasMonitorWidget.jsx), and their Dashboard registrations.

**Observed:** AI Pulse shows bullish 72/100, confidence 88%, and fixed headlines. Risk Monitor uses constant -4.2% drawdown and claims volatility protection is enabled. Gas Monitor uses constant network fees. Hidden-by-default does not prevent users enabling these cards.

**Implementation:**

1. Remove the AI Pulse and Gas Monitor cards from the production widget registry for this repair because the inspected implementations have no data source. Remove their hardcoded production data and retire their persisted layout IDs gracefully. Do not relabel fabricated data as current data.
2. Retain Risk Monitor's genuinely calculated concentration information. Remove hardcoded drawdown and protection text. Render drawdown as unavailable until a defined, validated history calculation exists; display protection status only from an explicit effective setting for the selected scope, otherwise unknown.
3. Preserve unrelated layout choices when obsolete widget IDs are removed. Do not reset a user's entire dashboard.
4. Any later restoration of AI Pulse/Gas Monitor is separate feature work requiring a timestamped data contract, provenance, loading/stale/error states, and meaningful methodology. It is not required to close this misleading-display defect.

**Acceptance:** With AI disabled, enabled, unavailable, and with old widget preferences, none of the fabricated strings/figures appear. Unknown risk/protection values are labeled unknown. Other widgets retain their saved placement. Registry and Help no longer advertise the retired cards as available live features.

### QA-10 — CBBI fetch failures become a fabricated fresh 25% reading

**Priority:** P1. **Evidence:** Reproduced.  
**Location:** [routes/market.py](../routes/market.py), approximately line 847; CBBI widget consumer.

**Implementation:**

1. Delete the exception fallback that inserts `0.25` under the current timestamp.
2. Define a response contract with `status` (`ok`, `stale`, `unavailable`), actual observation timestamp, optional last successful data, and sanitized error category. Keep any compatibility fields truthful while updating all consumers.
3. On failure with cached data, preserve the original data timestamp and display a stale badge. On failure without data, return a structured unavailable response and render no numerical reading. Do not stamp retrieval failure time as observation time.
4. Define and test the cache freshness threshold in one named configuration constant. Cache real observations only, never synthetic fallback values.

**Acceptance:** Successful fetch displays the actual value/time. A failed fetch with cache shows the old value as stale; without cache it shows unavailable. No exception path can generate a new numerical observation. Invalid upstream shapes and out-of-range values follow the same unavailable/stale behavior.

### QA-11 — Account deletion is incomplete and can violate Jev foreign keys

**Priority:** P1. **Evidence:** Schema/code confirmed; deletion was not executed.  
**Location:** [routes/auth.py](../routes/auth.py), `delete_account`, approximately line 606; [models.py](../models.py), Jev foreign keys near line 805.

**Implementation:**

1. Inventory every mapped user-owned model, including indirect ownership through account/signal/order relationships. Classify each as delete, retain under an explicit policy, or shared/global. Produce the complete mapping before changing deletion behavior.
2. Include Jev evaluations, Webull orders/watchlists, synthetic/ladder/trailing executions, strategy/research records, and all existing credential/session data. Delete dependent records before referenced parents within one transaction, or introduce verified database cascades through a migration. Do not mix assumptions about ORM cascades with bulk query deletion.
3. Stop or fence user-owned workers and invalidate tokens so asynchronous work cannot recreate records after deletion. Check user existence at job execution boundaries.
4. Roll back the complete operation on failure and return failure; only logout and report completion after commit. Never claim all data was deleted if retained data exists under policy.
5. Preserve other users and shared market/reference data. Any historical orphan cleanup is a separate reviewed migration, not an incidental startup operation.

**Acceptance:** Requires explicit authorization for destructive testing even in disposable fixtures under the repository guardrails. Once authorized, create a user with records in every inventoried model, including linked Jev evaluations; delete that test user and verify all designated records/tokens disappear, other-user/shared data remains, and injected failure rolls back. Test in PostgreSQL with foreign keys active. No production deletion/backfill is authorized by this report.

### QA-12 — Tax inline editing posts to a nonexistent route

**Priority:** P2. **Evidence:** Registered method/path mismatch confirmed; POST resolves to 405.  
**Location:** [frontend/src/pages/TaxReport.jsx](../frontend/src/pages/TaxReport.jsx), approximately line 300.

**Implementation:**

1. Do not add a generic arbitrary-field `/api/logs/update` endpoint. Introduce a scoped tax-adjustment resource, proposed `PATCH /api/tax/transactions/{source}/{source_id}`, with account/provider identity supplied and verified server-side.
2. Classify rows as user-created manual records or imported broker records. Imported executions remain immutable; permitted tax corrections are separate override records with original value, new value, reason, author, and timestamp. Derived gain/term/total cells remain read-only.
3. Enumerate editable fields and their types explicitly. For manual rows this may include transaction date, type, asset identity, quantity, unit price, and fee; for imported rows restrict corrections to supported tax metadata/adjustments, never the broker execution itself. Publish editable capabilities per row from the backend rather than guessing in JSX.
4. Return a normalized recalculated report or trigger a report refetch on success. Do not update one table cell while leaving gains, remaining lots, and summary totals stale.
5. Return 400/403/404/409 appropriately; ownership must be checked against the actual source record, not only an integer ID that can collide across tables. Include a revision token to prevent lost updates.

**Acceptance:** Valid manual edits persist and recompute totals; imported financial-source fields cannot be rewritten; permitted overrides retain provenance. Cross-user/account requests fail, invalid numbers/dates fail, concurrent stale revisions fail, and a failed save leaves displayed report values unchanged. Verify both tax provider pages.

### QA-13 — Staking Yield requests a nonexistent API and invents APR values

**Priority:** P2. **Evidence:** Browser reproduced; arithmetic defect code confirmed.  
**Location:** [frontend/src/components/StakingYieldWidget.jsx](../frontend/src/components/StakingYieldWidget.jsx), approximately line 20.

**Implementation:**

1. Replace `/api/staking-balances` with an adapter over the existing authenticated staking data used by the working staking page. If that response lacks valuation/rate fields, add a narrowly scoped summary to that real service rather than creating a disconnected second staking implementation.
2. Define position inputs as current USD value, simple annual rate, rate kind (APR/APY), timestamp, and source. Preserve zero; use explicit null checks instead of `rate || default`.
3. For APR positions, estimated annual reward is the sum of `position_value * APR / 100`. Weighted average APR is that sum divided by covered value times 100. Do not apply an unweighted average to the full portfolio.
4. Keep APY distinct; do not label an APY as APR without an explicitly supported conversion. Show coverage and exclude unknown-rate/value positions from a numeric estimate, marking it partial.
5. Remove 4.8% and 5% fallbacks. Implement loading, empty, stale, partial, and error states. Estimates must be labeled estimates and must not be described as guaranteed rewards.

**Acceptance:** $100 at 10% plus $900 at 2% yields $28/year and 2.8% weighted APR. Zero-rate positions remain zero. Unknown rates do not acquire defaults. HTTP failures produce an unavailable state. Requests use an implemented authenticated route and data remains user-scoped.

### QA-14 — Quick Trade percentages are decorative and Webull routing loses identity

**Priority:** P2. **Evidence:** Code confirmed.  
**Location:** [frontend/src/components/QuickTradeWidget.jsx](../frontend/src/components/QuickTradeWidget.jsx), state near line 38 and navigation near line 47.

**Implementation:**

1. Carry a validated trade-prefill object through the existing navigation mechanism: provider, account, mode, instrument ID/type, side, and selected allocation percentage. No order is submitted from the widget.
2. Define sell percentages against available sellable position quantity; buy percentages against available buying power in the correct account/currency. Compute the preview in the destination ticket from current data and actual contract multiplier/lot increments.
3. Use the actual selected holding's instrument type/account and explicit mode. If an instrument is unsupported by the destination ticket, disable it with an explanation instead of coercing it to EQUITY.
4. Revalidate balance, price, lot size, and permissions before submission. Clear or recompute the prefill when the destination account/instrument/mode changes. Stale navigation state cannot authorize a trade.

**Acceptance:** 25/50/75/100% selections produce different correct ticket previews; users must still review and submit. Crypto/options cannot arrive as equities. Account/mode switching invalidates stale sizing. Zero balance, missing price, and unsupported instruments prevent an actionable misleading preview.

### QA-15 — Immediate portfolio snapshots lose Flask application context

**Priority:** P2. **Evidence:** Reproduced in a real background thread.  
**Location:** [services/portfolio_service.py](../services/portfolio_service.py), `trigger_portfolio_snapshot`, approximately line 298.

**Implementation:**

1. Resolve `current_app._get_current_object()` in the caller's active context before starting the thread, or pass the actual application instance explicitly from the owning background-job service. Never resolve the proxy for the first time inside the child thread.
2. Enter `with app.app_context()` in the worker and use a worker-local database session lifecycle. Roll back on failure and release session resources on exit.
3. Protect cooldown/in-flight state from concurrent calls. Reserve an in-flight slot atomically, start the cooldown after successful persistence, and release the reservation on failure so an immediate retry is possible.
4. Keep snapshot failures isolated from the successful trade/staking action. If a caller lacks an application instance/context, fail observably without spawning a doomed thread.

**Acceptance:** A joined real-thread test saves the snapshot from a parent request/app context. Simultaneous triggers produce one snapshot; failed persistence allows retry; sessions are cleaned up; no context exception occurs. Verify the documented zero-value policy separately rather than changing it incidentally.

### QA-16 — Legacy Binance log synchronization calls undefined helpers

**Priority:** P2. **Evidence:** Code confirmed.  
**Location:** [routes/helpers.py](../routes/helpers.py), approximately lines 453 and 458; `/api/logs` and `/api/logs/sync` in [routes/system.py](../routes/system.py).

**Implementation:**

1. Replace the obsolete helper calls with a compatibility adapter to the maintained Binance order-history synchronization service. Inspect that service's input/return contract and explicitly map it; do not invent no-op definitions to make the names resolve.
2. A user-triggered sync must target only the authenticated user. Retain cross-user synchronization only in the separately authorized background scheduler.
3. Make GET `/api/logs` read stored logs without initiating synchronization; POST `/api/logs/sync` performs the explicit operation and returns imported/updated/skipped/error counts.
4. Preserve idempotency using provider execution/order IDs and maintain paper/live separation. Return partial/failure states when a connector step fails rather than claiming complete success.

**Acceptance:** Known trades import once, reruns do not duplicate, empty history succeeds, a second user's records remain untouched, and provider failure is visible. GET does not invoke the connector. Existing newer order-history synchronization tests remain passing.

### QA-17 — Registered legacy AI endpoints reference missing helpers

**Priority:** P2. **Evidence:** Selected HTTP 500 paths reproduced; other missing names inspected.  
**Location:** [routes/ai.py](../routes/ai.py), notably around lines 1372, 1528, 1540, 1614, 1701, 1794, 1950, 1996, 2474, 3158, and 3468.

**Affected examples:** Analysis-window checks, portfolio data retrieval, sentiment/risk/confidence/key-insight extraction, recommendation/portfolio parsing, smart-alert generation, recommendation scoring, conversation ID generation, and `ast` usage. Market-analysis workflow, portfolio-review workflow, run-analysis, and recommendation scoring returned 500 in controlled tests.

**Implementation:**

1. Create a route-to-service inventory for every missing reference. For each route record authentication, input schema, current frontend/external caller, documented purpose, expected output, and the maintained service that owns equivalent behavior.
2. Keep supported workflows functional through explicit imports or compatibility adapters to those maintained services. Preserve analysis-window and global-AI enablement checks. Do not bypass controls to make a request return 200.
3. Use typed/validated output parsing already supported by the current AI integration; malformed model output returns a structured failure, not fabricated bullishness/confidence/recommendations.
4. Where no implementation exists and no supported consumer/contract can be established, return authenticated structured 410 with an unavailable-feature explanation and remove advertising/navigation for that route. This is the explicit disposition for unsupported legacy APIs, not silent empty-success output.
5. Replace unsafe/ad hoc parsing with validated JSON where the contract is JSON. Importing `ast` is appropriate only if a documented Python-literal compatibility contract is actually required; never introduce `eval`.
6. Inspect recommendation RSI while repairing scoring: an all-gain/no-loss window should not become RSI 0; distinguish all-gain, all-loss, flat, and insufficient-history cases. This is a static secondary issue, not an additional reproduced endpoint.

**Acceptance:** Each inventoried route has a supported success test or an explicit 410 retirement test, plus unauthenticated, AI-disabled, malformed-provider-output, and provider-failure cases. The four reproduced 500 cases cannot raise missing-name exceptions. Scoring tests include monotonic gain/loss, flat, and short series. The route inventory is required before this finding can be closed; unknown callers cannot be assumed absent.

### QA-18 — Optional AI caching and prompt substitution contain latent errors

**Priority:** P3. **Evidence:** Static; no current caller enabling the cache branch was established.  
**Location:** [services/ai_service.py](../services/ai_service.py), approximately lines 885 and 1321.

**Implementation:**

1. Import the actual cache model/hash module if retaining `use_cache`; verify the model schema and session ownership first. Cache identity must include user/provider/model, effective prompt/input, relevant parameters, and schema/version. Never share private cached output across users.
2. Define expiry and provider-failure behavior. Cache only validated successful responses, and let cache storage failure fall back to the normal request without fabricating success.
3. Trace the prompt function's actual amount input and pass it explicitly into a single template renderer. Replace only documented placeholders; reject a required missing amount instead of leaving `{amount}` in a provider prompt.
4. Preserve literal braces according to the template syntax and avoid broad replacement that corrupts JSON examples. Do not silently send unresolved required placeholders after catching an exception.

**Acceptance:** Cache miss/hit/expiry and cross-user/model separation pass with `use_cache=True`; default uncached behavior stays intact. Template tests cover amount 0, decimals, missing amount, symbol/date, literal braces, and unknown placeholders. Assert the final provider input, not just that no exception occurred.

### QA-19 — CoinGecko chart API fails before its error handling

**Priority:** P2 for a supported API; P3 if confirmed unused. **Evidence:** Reproduced.  
**Location:** [routes/market.py](../routes/market.py), approximately line 120.

**Implementation:**

1. Move chart caching behind one module-owned cache abstraction with explicit initialization, bounded entry count, TTL, and concurrency protection. Include asset/currency/range in the key; use monotonic time for expiry.
2. Validate request parameters before calling CoinGecko. Cache only schema-valid successful responses. Keep source timestamps intact on stale data if stale serving is allowed.
3. Handle upstream timeouts, rate limits, malformed responses, and unavailable data with explicit statuses. Cache lookup must be inside the controlled handler path.
4. Preserve the registered API's response contract while repairing it; retire only after the caller inventory from QA-17/28 establishes that removal is intentional.

**Acceptance:** Cold/warm/expired cache, distinct parameters, simultaneous requests, upstream 429/timeout, and malformed payloads produce defined outcomes without missing globals. No source timestamp is refreshed simply because cached data was read.

### QA-20 — Desktop-session authentication and transaction history are stubbed

**Priority:** P2. **Evidence:** Code confirmed.  
**Locations:** [routes/system.py](../routes/system.py), `get_user_from_desktop_session` near line 544; [routes/portfolio.py](../routes/portfolio.py), transaction history near line 823.

**Implementation:**

1. Map the desktop client's actual issued token format and lifecycle to the existing validated token machinery. Implement the desktop-session resolver as an adapter to that verification, including expiry/revocation and user existence. Do not accept a submitted username/user ID as authentication.
2. Ensure notification fetch, acknowledgment, and export filter by the resolved owner. Acknowledge only requested IDs owned by that user and preserve existing supported bearer flows.
3. Replace the always-empty transaction-history handler with a compatibility adapter to the maintained, account-scoped history service. Normalize pagination, ordering, instrument/provider filters, and explicit empty states; never substitute `[]` for backend failure.
4. If the desktop token format cannot be established from the actual client/issuer, keep that capability explicitly unavailable until its contract is supplied. Do not guess a credential protocol.

**Acceptance:** Valid, expired, revoked, malformed, and cross-user desktop tokens behave correctly; acknowledge/export cannot reach another user's rows. Seeded transaction history returns records in stable order; genuine no-record history is empty; connector/database failure is not indistinguishable from no records. Existing bearer authentication remains passing.

### QA-21 — Support returns delivery success after all transports fail

**Priority:** P2. **Evidence:** Reproduced with both delivery transports failing.  
**Location:** [routes/system.py](../routes/system.py), approximately lines 4707–4714.

**Implementation:**

1. Define success as acceptance by a configured mail transport, not merely attempting a send or writing a log. A spawned local mail process must be awaited with a bounded timeout and checked for successful exit.
2. Fall back to the secondary transport only after a definite primary failure. Distinguish uncertain timeout delivery from definite rejection to avoid pretending duplicates cannot occur.
3. If no transport accepts the message, return structured 503 with `success:false`; preserve the form contents/attachments in the browser for retry. Do not claim durable queuing unless a durable queue is actually implemented.
4. Return 'accepted for delivery' rather than guaranteeing receipt. Log a correlation ID, transport, and error category without private message text or attachments.

**Acceptance:** Primary success, primary failure/secondary success, both fail, nonzero child exit, and timeout all produce the appropriate user state. All-failure can never show 'Message sent successfully.' A retry preserves user input and does not run automatically in a loop.

### QA-22 — Services disagree about trading holidays and early closes

**Priority:** P2. **Evidence:** Date-specific reproduction.  
**Locations:** [services/webull_signal_service.py](../services/webull_signal_service.py), [services/market_calendar_service.py](../services/market_calendar_service.py), and [services/portfolio_strategy_signals.py](../services/portfolio_strategy_signals.py).

**Observed:** December 25, 2026 is open according to the signal helper but closed elsewhere. On November 27, 2026 at 19:00 UTC, two services consider the market open after its early close while the quant calendar considers it closed.

**Implementation:**

1. Consolidate regular-session decisions behind an exchange-calendar adapter, reusing the working `exchange_calendars` approach. Input must include timezone-aware time and instrument/venue/session policy.
2. Replace weekday/time shortcuts and fixed 16:00 closes in signal grading and scheduled-order processing. Use actual session open/close, including holidays, early closes, and DST.
3. Define regular-session boundaries consistently as open-inclusive, close-exclusive. Extended-hours orders must use an explicit supported policy rather than expanding regular hours implicitly.
4. Keep crypto's continuous market policy separate; options/futures/event contracts require their actual applicable session rules. On unknown calendars, defer new session-dependent work with an explicit reason rather than defaulting open.

**Acceptance:** The two reproduced holiday/early-close cases are closed consistently. Test normal open/close boundaries, weekends, DST transitions, supported extended-hours behavior, and continuous crypto. Scheduled work does not submit because another service guessed the market was open.

### QA-23 — Shared error boundary remains failed after route navigation

**Priority:** P2. **Evidence:** Browser reproduced.  
**Location:** [frontend/src/components/ErrorBoundary.jsx](../frontend/src/components/ErrorBoundary.jsx), and route wrapper in [frontend/src/App.jsx](../frontend/src/App.jsx).

**Implementation:**

1. Scope route errors to the route outlet and pass a route identity/reset key from a router-aware wrapper. Reset the boundary when the location changes, including intended search-based route identity if relevant.
2. Keep navigation usable outside the failed boundary. The reload button may remain, but add a local retry that resets only the failed view when safe.
3. Log the original error with route/context once; do not create automatic retry loops or clear evidence on every render.

**Acceptance:** Force Webull to throw, navigate to Settings, and verify Settings renders without browser reload. Back navigation can retry the affected route. Repeated rendering does not loop; navigation and logout remain usable. The underlying QA-02 fix must still be tested independently.

### QA-24 — Legacy and unknown URLs show an empty shell

**Priority:** P2. **Evidence:** Browser reproduced for `/watchlist`, `/ai-dashboard`, and an unknown path.  
**Location:** [frontend/src/App.jsx](../frontend/src/App.jsx), server frontend/legacy routes.

**Implementation:**

1. Add explicit legacy client redirects for `/watchlist` and `/ai-dashboard` to the current dashboard entry point, using history replacement. If a supported dashboard section selector exists, preserve the destination section through its existing contract; otherwise show a migration notice rather than inventing a tab name.
2. Add a catch-all client not-found view with a clear message and Dashboard navigation. Maintain normal authentication behavior.
3. Align server SPA routes with client routes. Unknown `/api/*` paths must return JSON errors and must never fall through to HTML SPA content.

**Acceptance:** Direct load, in-app navigation, refresh, logged-out redirect, legacy URLs, and arbitrary unknown URLs all show a meaningful state. Back navigation has no redirect loop. Missing API routes remain API errors.

### QA-25 — Dialogs lack keyboard containment, Escape dismissal, and focus restoration

**Priority:** P2. **Evidence:** Browser reproduced.  
**Location:** [frontend/src/components/AppDialog.jsx](../frontend/src/components/AppDialog.jsx).

**Implementation:**

1. Use a native modal dialog or a proven accessible dialog primitive consistent with supported browsers. Set the correct accessible name/description and modal semantics.
2. Capture the triggering element, move initial focus deliberately, cycle Tab/Shift+Tab within the dialog, and isolate background interaction while open.
3. Escape closes ordinary dialogs. If a specific irreversible operation must block dismissal while submitting, declare that state explicitly with accessible progress; do not globally disable Escape.
4. Restore focus to the still-mounted trigger on close, otherwise to a logical surviving control. Clean up listeners/inert state on unmount and handle nested dialogs in stack order.

**Acceptance:** Keyboard-only tests cover first/last control cycling, Escape, close button, restored focus, trigger removal, nested dialogs, and in-progress dismissal policy. Background controls cannot be focused or activated while modal. Screen-reader naming is verified.

### QA-26 — Hidden Copilot controls remain keyboard-focusable

**Priority:** P2. **Evidence:** DOM inspection found eight enabled focusable controls while closed.  
**Location:** [frontend/src/components/AICopilotSidebar.jsx](../frontend/src/components/AICopilotSidebar.jsx), approximately line 1224.

**Implementation:**

1. When closed, unmount interactive content or apply native `inert` plus appropriate visibility/transition handling. `aria-hidden` alone is insufficient.
2. Preserve chat state outside the conditionally mounted presentation if needed. Opening moves focus to the intended control; closing restores it to the opener.
3. Decide from actual layout whether the open sidebar is modal or nonmodal. Use modal focus containment only when the product actually blocks background interaction, and align Escape/backdrop semantics with that choice.

**Acceptance:** Repeated Tab traversal cannot enter closed controls; the closed content is absent from the accessibility tree. Open/close preserves drafts/history as intended and restores focus. Reduced-motion behavior does not leave an invisible interactive interval.

### QA-27 — Closed Copilot shadow and light-mode error contrast are inconsistent

**Priority:** P3. **Evidence:** Visually observed; no formal contrast ratio measured during audit.  
**Locations:** [AICopilotSidebar.css](../frontend/src/components/AICopilotSidebar.css), approximately line 74; [ErrorBoundary.jsx](../frontend/src/components/ErrorBoundary.jsx), approximately line 40.

**Implementation:**

1. Apply sidebar shadow only in its open state and move the complete panel outside the viewport when closed. Avoid a negative offset that leaves shadow visible. Honor reduced-motion settings.
2. Replace inline pale error-body color with theme-aware semantic text/surface tokens. Measure contrast against the actual composited background, targeting at least 4.5:1 for ordinary body text and 3:1 for large text.
3. Preserve visible keyboard focus and avoid solving the strip by globally hiding horizontal overflow, which can conceal other layout bugs.

**Acceptance:** Compare 390- and 1,440-pixel screenshots in both themes, closed/open sidebar, error screen, and reduced motion. No closed-edge shadow strip remains; measured contrast meets the chosen accessibility threshold. No new content clipping or document overflow.

### QA-28 — Unreachable frontend modules and legacy functions accumulate

**Priority:** P3. **Evidence:** Static reachability candidates, not blanket proof of safe deletion.

**Candidates from the entry-point graph:**

- `frontend/src/components/AddToWatchlist.jsx`
- `frontend/src/components/CoinAnalysisTable.jsx`
- `frontend/src/components/EventStrategyPanel.jsx`
- `frontend/src/components/OnboardingModal.jsx`
- `frontend/src/components/ReportModal.jsx`
- `frontend/src/components/TradingChart.jsx`
- `frontend/src/components/ValidationPopup.jsx`
- `frontend/src/components/WatchlistCoinAnalysisTable.jsx`
- `frontend/src/hooks/useNotificationPoller.js`
- `frontend/src/utils/technicalIndicators.js`
- `LegacyWebullOrderTable`, `LegacyEventContractOpenOrders`, and `WebullSignalTable` in WebullTrading.

**Implementation:**

1. For each candidate inspect static/dynamic imports, lazy routes, string-based loaders, tests, scripts, exports, documentation, and module side effects. Record whether it is obsolete, intentionally external, or an advertised unwired feature.
2. Delete only obsolete confirmed-unreferenced modules/functions and their exclusively unused styles/assets. For an advertised unwired feature, either wire it through the maintained implementation or explicitly remove the advertising; do not revive a duplicate old implementation merely to use a file.
3. Keep intentionally supported utility exports with a documented consumer/contract and appropriate tests. Do not delete test-only analytical utilities just because the production entry graph excludes them.

**Acceptance:** Every candidate has a recorded disposition. Production build, direct/lazy route smoke tests, and affected utility tests pass. No import/reference remains to removed modules; no side-effect initialization disappears unintentionally.

### QA-29 — Unused imports and local variables obscure real defects

**Priority:** P3. **Evidence:** Static: 227 unused Python imports, 28 Python locals, and 27 frontend bindings excluding React.

**Implementation:**

1. Review warnings against runtime exports, plugin registration, ORM model registration, and import side effects before removal. Star-import ambiguity is not proof of an undefined name.
2. Remove confirmed unnecessary imports/bindings. If a local's assignment calls a required side-effecting function, preserve the call explicitly rather than deleting its behavior.
3. Replace broad helper imports with explicit imports incrementally where ownership is understood, and add automated undefined-name/unused-name rules as described in QA-30.
4. Avoid sweeping auto-fix across the repository; isolate cleanup from financial/trading behavior repairs for reviewability.

**Acceptance:** Reviewed warnings decrease without missing model/table/route registration, changed service initialization, or failed affected tests. No new suppressions are added merely to hide the QA-01/02/03/16/17/18/19 defects.

### QA-30 — Tests and CI do not reliably gate these failures

**Priority:** P2. **Evidence:** Suite execution, script/workflow inspection, and successful build despite undefined frontend names.  
**Locations:** [frontend/package.json](../frontend/package.json), [scripts/run_full_tests.sh](../scripts/run_full_tests.sh), `.github/workflows/secret-check.yml`, browser fixtures, and [tests/test_portfolio_event_handoff.py](../tests/test_portfolio_event_handoff.py).

**Implementation:**

1. Add frontend linting with correctly configured JSX/browser/Node scopes and mandatory undefined-variable detection. Introduce unused-variable enforcement with a reviewed baseline if needed; do not disable undefined-name detection for existing debt.
2. Add Python static undefined-name checks with explicit handling of current star-export modules. Establish a reviewed baseline for unrelated style/unused warnings rather than misclassifying all diagnostics as defects.
3. Extract shared test fixtures/helpers from imported `TestCase` classes or import their modules without exposing the original class in discovery. Each logical test must execute once unless deliberately parameterized.
4. Correct the warming-up fixture: supply valid options/futures adapter tuples for modules expected to be healthy or explicitly mark those modules warming up. Keep a separate genuine adapter-failure test that expects degraded status.
5. Centralize browser API fixtures around current backend response contracts, including Jev telemetry and quantitative settings/arrays. Unexpected API requests or React error-boundary output should fail a test visibly rather than returning generic `{}` responses.
6. Enumerate all test database environment variables from the suite, including Jev, synthetic-lock, and quant variants. Configure all in the test runner against an explicitly isolated PostgreSQL database. Report skips and fail required integration jobs when database prerequisites are missing.
7. Add CI jobs for frontend dependency install/build/lint, JavaScript tests, Python checks/full required tests, and the six browser suites with isolated services. Keep secret checking. Avoid jobs requiring production credentials, paid inference, or live orders.
8. Publish test totals, unique test counts, skips, and browser failure artifacts. Treat unexplained duplicate discovery or skipped mandatory integration suites as a failed verification contract.

**Acceptance:** The original undefined names would fail CI before merge. Python discovery has no unintended duplicates; corrected warming-up and genuine-failure tests pass. All six browser suites reach and assert their intended feature states. CI runs on pull requests and the intended main-branch changes without contacting production services.

### QA-31 — Earlier issue documentation contains resolved claims

**Priority:** P3. **Evidence:** Current code/dependency checks contradict portions of the older report.  
**Location:** [docs/unresolved_issues_v3.5.6.md](unresolved_issues_v3.5.6.md).

**Implementation:**

1. Preserve the older document as a dated historical assessment. Add a prominent baseline/status notice rather than rewriting history as though the old audit never occurred.
2. Mark revalidated items individually: former Webull time-import issue, missing Fernet test import, and the prior seven npm advisories are not current findings under this audit's checks.
3. Link current issues to stable QA IDs in this report. Record verified version/date and evidence for each resolution; distinguish dependency-audit results from a blanket security certification.
4. On future remediation, append resolved commit/version and acceptance evidence to each QA item. Do not mark an item fixed because a similar file was edited.

**Acceptance:** A reader can distinguish historical and current defects without cross-reading source code. Every claimed resolved issue has verification evidence, and this report remains accurate about unimplemented work.

## 5. Jev 4.0.0: verified behavior, gaps, and proposed follow-through

### JEV-A — Settings integration exists; live inference is unverified

The Settings → AI Providers & Models Jev card and the Vercel API-key configuration are present. The existing browser settings suite passed against fixtures, including mobile layout. The quantitative path forwards substantive existing strategy features. No real Vercel key or paid request was used in the audit.

**Preserve during repairs:** Separate Jev/generative configuration, encrypted credential storage, masked-key save semantics, explicit enablement, transport/model validation, user-isolated telemetry, and absence of order-entry side effects from shadow evaluation.

**Future verification:** After separate authorization for a paid provider request, use the user's configured credential through the application; check one minimal connection test and one permitted evaluation, sanitized errors, persisted model/version/latency metadata, and no secret exposure. Test missing/invalid key, timeout, disablement, and retained masked key with mocks regardless of live access. A mocked success must never be described as verified live authentication.

### JEV-B — Webull outcome completeness depends on QA-03

Fix Webull grading before interpreting the linked telemetry as complete. Add an integration test spanning stored Webull signal → reliable target-time quote → grade → linked Jev outcome. Preserve the documented time tolerance and unscored state for missing evidence. Old observations without target-window prices must remain unscored; a current quote is not a backfill.

### JEV-C — Telemetry UI exposes only part of available diagnostics

The API computes more than the visible recent-evaluation/Brier/latency summary. This is a research UI completeness gap, not proof that the underlying telemetry is absent.

**Proposed implementation:** Add an expandable diagnostics view over the existing authenticated telemetry response with p50/p95/p99 latency, calibration buckets, sample counts, threshold coverage/accuracy, score-versus-return buckets, and distinct Choice probabilities versus TypeSafe confidence metadata. Keep use case, market, instrument, model, question version, and horizon cohorts separated. Label bounded sample/date coverage and unknown cost explicitly. Empty or tiny cohorts must show insufficient evidence rather than a confident performance claim.

**Acceptance:** Fixtures with two incompatible cohorts never merge silently; unknown confidence/cost remains unknown; probabilities and confidence have separate labels; empty and partial samples render without crashes; displayed counts/percentiles match the response. No new evaluation/provider call occurs merely by opening diagnostics.

### JEV-D — Full replay, overlay P&L, and MFE/MAE are deferred research capabilities

[docs/jev_v4.0.0.md](jev_v4.0.0.md) explicitly limits the current implementation to fixed-horizon labels and reserves MFE/MAE without claiming reliable values. Full comparative paper replay and threshold promotion are not implemented. Paper gating is intentionally unavailable, including through crafted settings requests; that is not a defect.

**Proposed later-phase design, separate from bug remediation:**

1. Specify a versioned replay contract: immutable decision-time state, baseline decision, Jev response/version, instrument/account assumptions, horizon, fee/slippage model, sizing, and capital constraints. Freeze parameters before evaluating held-out outcomes.
2. Use only evidence available at the original decision time for the decision. Future bars are allowed solely for labeling/execution simulation, never as model input. Do not call today's model on old data and present that as an unbiased historical forecast.
3. Calculate MFE/MAE only from sufficiently complete, timestamped full-window bars under a stated sampling policy; missing windows remain null. Define excursion relative to entry and direction before implementing formulas.
4. Simulate baseline and overlay with identical execution/cost/capital assumptions, including skipped trades and opportunity costs. Do not infer an economic improvement from Brier score alone.
5. Separate chronological development and held-out periods, show uncertainty/sample size, and keep real/paper execution behavior unchanged. Enabling confirm/veto gating is a separate product decision requiring explicit authorization and execution-safety tests.

**Acceptance:** Deterministic replay from frozen inputs; leakage tests; matching baseline/shadow ledgers when no gating is enabled; partial-bar cases remain unscored; reported P&L reconciles to a simulated ledger including costs. This is a defined future workstream, not a claim that the larger research specification is already satisfied.

## 6. Implementation sequence and dependencies

| Phase | Findings | Required completion evidence |
|---|---|---|
| 1: Prevent misleading output and obvious crashes | QA-01, 02, 09, 10, 21, 23 | Reproductions turn into passing tests; no fake success/data fallback |
| 2: Normalize tax evidence and calculate correctly | QA-04–08, 12 | Fill provenance, account/contract boundaries, method/date/multiplier tests, report/export reconciliation |
| 3: Restore reliable outcomes and background work | QA-22, 03, 15, 16 | Shared calendar, graded outcomes, isolated snapshots, idempotent sync |
| 4: Restore incomplete supported features | QA-13, 14, 17–20 | Real service adapters or explicit retirement, contract tests, no disconnected controls |
| 5: Repair user-data deletion | QA-11 | Complete ownership inventory and separately authorized destructive isolated tests |
| 6: Navigation and accessibility | QA-24–27 | Keyboard, screen-reader semantics, route recovery, viewport/theme checks |
| 7: Hygiene and durable gates | QA-28–31 | Reviewed cleanup, unique discovery, complete fixtures, enforced CI, accurate docs |
| Separate research work | JEV-A–D | Explicit live-test authorization where needed and research-specific acceptance evidence |

CI and focused regression tests should be introduced alongside the earliest fixes, not postponed until the end. Tax normalization (QA-05/06/07) must precede claims that method selection or editable reports are accurate. Calendar repair (QA-22) must be incorporated into the grading repair (QA-03). Cleanup should follow restored behavior so it does not hide the source of functional changes.

### Explicit prerequisites that must not be guessed

- Source-backed leap-day tax holding-period behavior and report date policy.
- Historical broker execution timestamps, option/futures contract identities, multipliers, and actual fee provenance.
- The complete user-data ownership/retention inventory for account deletion.
- Legacy route consumers and actual desktop token issuer/client contract.
- Exact maintained service response contracts before replacing incomplete adapters/fixtures.

When evidence is missing, the specified interim behavior is unavailable, unscored, incomplete, or explicitly retired as described above. It is never a fabricated value or silent success. These prerequisites are part of the implementation tasks; this report does not pretend they have already been resolved.

## 7. Completion checklist for a future authorized repair

- [ ] Every QA item has implementation evidence or an explicit reviewed disposition; static candidates are not silently deleted.
- [ ] All reproduced defects have behavior-level regression tests and no expected-failure masking.
- [ ] Tax totals reconcile with execution quantities, multipliers, fees, account-specific lots, chosen method, and holding periods.
- [ ] Unknown/stale/partial information is visible and never replaced by fabricated metrics.
- [ ] Credential, user, account, environment, and execution-mode isolation remains intact.
- [ ] Frontend build, lint, JavaScript tests, Python checks, required PostgreSQL suites, and all browser suites pass with explained unique counts/skips.
- [ ] Mobile/desktop, light/dark, keyboard navigation, error recovery, and missing-data states are rechecked.
- [ ] No live order, paid inference, destructive mutation, or release is inferred from this report's existence.
- [ ] Any later authorized release follows AGENTS.md, including versioning, source/built-artifact commits, release publication, separate personal-instance upgrade, and running-instance verification.

**Current disposition:** All fixes remain proposed. Only this report was created under the present request.
