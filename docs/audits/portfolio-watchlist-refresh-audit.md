# Portfolio, watchlist, and order-display audit

**Date:** November 14, 2026
**Reviewed release:** v4.16.1, commit `99d72e5b78365882ed4c75920d814c075c0c435c`
**Status:** Implementation authorized November 14, 2026. v4.16.2, v4.16.3 and v4.16.4 are released; remaining findings are tracked below.

## Implementation ledger and handoff

The user authorized implementation of this audit on November 14, 2026, including checking off completed work and preserving a handoff. The original findings below describe v4.16.1; their evidence and proposed fixes are retained as the baseline. This ledger records subsequent work and supersedes the original review-only status.

**Batches:** v4.16.2 (released) — dashboard refresh/cancellation foundation; v4.16.3 (released) — row identity, stable ordering, watchlist add/remove, saved-edit protection, lifecycle cleanup; v4.16.4 (released) — per-source completeness, holdings membership, alert boxes.
**Release/deployment:** v4.16.2 was published and deployed to the personal instance on November 14, 2026 (commit `5cc9eb25`; service active, port 5010 responding, checkout on the tag). The original author's session ended before recording that here; it was re-verified before v4.16.3 work began. The user approved publishing v4.16.3 on November 15, 2026; it is published as GitHub release `v4.16.3` and the personal instance was upgraded through the release routine in `AGENTS.md` (unrelated files preserved, frontend rebuilt, service restarted, port 5010 and tag checked). The user approved v4.16.4 the same day; it is published as GitHub release `v4.16.4` and deployed through the same routine.
**Database/dependencies:** No schema changes, new dependencies, live order actions, or manual portfolio/watchlist mutations in either batch. Browser tests intercept all API calls with fixtures.

A checked item is complete within the stated finding's frontend scope. “Partial” means useful changes landed but the finding must remain open. Backend completeness/cache limitations are not implied to be solved by frontend race protection.

- [x] **F01 — Done: Old pending-order responses can undo a successful cancellation visually.** One refresh generation rejects pre-mutation responses; confirmed cancellations stay suppressed for the current dashboard session, including stale follow-up cache results. Cross-worker freshness remains F29.
- [x] **F02 — Done: Portfolio freshness IDs are often assigned after the response arrives.** Snapshot tickets are allocated before I/O. Portfolio rows and totals are applied only inside the accepted cycle; post-action callbacks no longer assign freshness on arrival. Sentiment field edits remain F27.
- [x] **F03 — Done: Refresh cycles can overlap, with extra refreshes inside them.** Main polling and order-action refreshes coalesce into one cycle (v4.16.2). v4.16.3 replaced the per-click sentiment timers with one shared poller that never overlaps itself, reads only the tables it needs, and applies results through the same freshness and saved-edit guards.
- [x] **F04 — Done: A normal refresh first applies an older database snapshot, then a live snapshot.** Saved snapshot is used only at mount, labeled while updating. Subsequent refreshes use live rows; embedded fast orders cannot replace dedicated order state.
- [x] **F05 — Done: An empty order list is sometimes treated as “use the previous list”.** Explicit empty pending-order arrays clear highlights; absent/malformed arrays and failed HTTP reads retain the accepted list. Per-provider partial failures remain F17.
- [x] **F06 — Done: Pending orders have multiple writable copies and cancellation uses old render values.** One publisher updates the current pending-order ref, React order state, and row flags. Cancellation reads the current ref, not a pre-await render closure.
- [x] **F07 — Done: Outstanding dashboard reads and deferred work survive cleanup.** Main snapshot reads abort on cleanup/auth change (v4.16.2). v4.16.3: settings, trading-pair and staking reads are tied to the signed-in user and aborted on cleanup; the sentiment poller and hover timer stop on unmount; the auto-buy balance lookup only answers the most recently opened modal.
- [x] **F08 — Done: Refresh merging can keep holdings that are absent from the new snapshot.** v4.16.4: both portfolio endpoints report, per provider, whether their rows are the whole current set. A row missing from a complete snapshot is removed; a row missing from an incomplete snapshot (or from a response with no completeness information) is kept with a notice.
- [x] **F09 — Done: Totals have competing writers and a separate stale startup cache.** Removed unscoped financial caches and competing total readers. Totals come with the accepted row snapshot; valid zero is preserved, missing fields retain last values with a freshness message.
- [x] **F10 — Done: Matching a pending order does not fully identify its account or instrument.** v4.16.3: one matcher compares provider, Webull account, instrument class and the exact symbol or trading pair (split on a known quote suffix, no prefix matching). An order with no account highlights a row only when one account holds that symbol. The server's Binance base-asset derivation uses the same suffix rule.
- [x] **F11 — Done: Some local updates and React row keys identify a row too loosely.** v4.16.3: one identity per table drives React keys, hidden rows, optimistic items and every callback (favorite, alert, alert type/value, auto-buy/sell, volatility, sentiment, notes, news). Notes name their table to the server, which previously could save a watchlist note onto a portfolio coin with the same numeric id; Webull watchlist notes now save.
- [x] **F12 — Done: Cancellation can remove more than the intended local order.** Local cancellation suppression compares provider, account, environment/mode, synthetic/native namespace, scoped ID aliases, and Binance pair.
- [ ] **F13 — Open: A synthetic parent and its broker child can both reserve the same cash.** Not started.
- [ ] **F14 — Open: Native OCO cash reservations can be counted as two independent purchases.** Not started.
- [ ] **F15 — Open: Some reservations still use original quantities after partial fills.** Not started.
- [ ] **F16 — Open: New conditional strategies are not fully represented by older pending-order formatters.** Not started.
- [x] **F17 — Done: Temporary broker failures can look like “all orders disappeared”.** v4.16.4: `/api/pending-orders` lists each source asked (Binance.US, synthetic strategies, each Webull account) with `complete` and a reason. The dashboard replaces the orders of every source that answered, keeps the last accepted orders of a source that failed, and names the failure above the portfolio. Confirmed local cancellations are still suppressed. A response Webull returns in an unexpected shape is still treated as empty until F33/F34.
- [x] **F18 — Done: The fast and live pending sources have different mode and freshness rules.** v4.16.4: every pending-order reader reports the same `environment:live|paper` mode; the fast reader no longer shows live Webull orders in paper mode; the dashboard never carries orders across a mode change. There is no numeric snapshot revision: ordering inside one browser relies on the single refresh cycle (F01/F02), and cross-process freshness remains F29.
- [ ] **F19 — Open: Yellow cash highlighting conflates several different meanings.** Not started.
- [x] **F20 — Done: HTTP 200 can be mistaken for successful cancellation.** Explicit application success is required. Final cancellation, acknowledgement/CANCEL_PENDING, and rejection are distinct; both brokers route synthetic IDs to status-bearing strategy endpoints.
- [x] **F21 — Done: The default BTC/ETH row order has no stable definition.** v4.16.3: with no chosen column both tables are alphabetical by symbol with a full-identity tie-break; both watchlist queries now have an explicit server order. Verified with the server order alternating on every refresh.
- [x] **F22 — Done: Equal sort values have no deterministic tie-breaker.** v4.16.3: every sort falls back to symbol, provider, account, instrument and id; rows with no value go last in both directions.
- [x] **F23 — Done: Sorting the portfolio silently changes the watchlist sort.** v4.16.3: separate sort state and saved preferences per table, validated against that table's sortable columns. The retired shared setting seeds the portfolio only, because it cannot say which table it was meant for; the watchlist starts from the stable default.
- [x] **F24 — Done: Changing-value sorts and temporary pinning can move rows without explaining why.** v4.16.3: each table states its order in words ("Order: A–Z by symbol", or the chosen column with "rows move as values change" and a reset). A third header click returns to the default. A newly added row takes its alphabetical place immediately; under a value sort it is held at the top labelled "Adding…" until confirmed.
- [x] **F25 — Done: Optimistic watchlist additions are keyed only by ticker.** v4.16.3: additions are tracked by provider, symbol and instrument; only the exact row confirms, replaces or removes a pending addition.
- [x] **F26 — Done: Watchlist removals can reappear, and removal failure is not rolled back.** v4.16.3: the latest add/remove decision per row is kept until a list requested after the server confirmed it; requests for one row are sent in order; a failed removal restores the row and reports the error. The server removes the exact Webull instrument when no id exists yet.
- [x] **F27 — Done: Refreshes can overwrite a newly saved favorite, alert, note, or automation setting.** v4.16.3: saved fields are remembered per row and re-applied over any refresh that was requested before the save, for both tables and for the sentiment poller.
- [x] **F28 — Done: Editable fields do not consistently follow refreshed values.** v4.16.4: alert and volatility boxes use one field component with a saved value and a typing state. An untouched box follows refreshes; typing is never overwritten; a refused save returns to the saved value; leaving a box unchanged saves nothing. Editor keys use full row identity.
- [ ] **F29 — Open: Webull order caches are private to each process, including invalidation.** Not started.
- [ ] **F30 — Open: Multiple backend jobs can write the same portfolio snapshot out of order.** Not started.
- [ ] **F31 — Open: Older imported order records can overwrite newer terminal states or fill totals.** Not started.
- [ ] **F32 — Open: Display GET requests also change persisted portfolio/watchlist state.** Not started.
- [ ] **F33 — Open: Missing/malformed snapshot data is not always distinguished from a genuine empty account.** Display side only so far (v4.16.4): `/api/coin-data` no longer answers a server error with an empty portfolio and HTTP 200, and a coin that cannot be serialized marks its provider incomplete. The Webull importer's own removal rules are not yet changed.
- [ ] **F34 — Open: A single page can be treated as the entire Webull open-order set.** Not started.
- [x] **F35 — Done: A recent fill can repeatedly trigger refreshes and success toasts.** Fill notifications deduplicate full identity/fill revisions; removed the nested portfolio read (v4.16.2). v4.16.4: a complete snapshot with no holdings is accepted, so the last holding leaves the table after it is sold.
- [x] **F36 — Done: Synthetic recovery changes do not immediately synchronize every dashboard view.** Dashboard listens to synthetic updates and invalidates older reads before requesting a coordinated refresh.
- [x] **F37 — Done: The recovery modal can receive the wrong late lookup result.** v4.16.3: each opening owns a cancellable lookup; a superseded or late answer is ignored, and the decision is submitted for the strategy on screen.
- [ ] **F38 — Partial: Current tests and logs do not establish absence of these races.** Added deterministic coordinator tests and actual Dashboard browser fixtures (v4.16.2); row identity/sort/intent unit tests and five table browser scenarios, plus a late-lookup recovery scenario (v4.16.3). Cross-tab/worker tests, request diagnostics, and the reservation/server acceptance scenarios are still open.

### Batch v4.16.2 changes and verification

- Implementation: `frontend/src/pages/Dashboard.jsx` and `frontend/src/utils/dashboardRefresh.mjs`.
- Regression tests: `tests/dashboard_refresh.test.mjs` and `tests/dashboard_refresh.browser.mjs`; existing synthetic cancellation routing remains covered by `tests/synthetic_cancellation.test.mjs`.
- Passed: 15 Node test cases across the coordinator, cancellation routing, and existing synthetic order utilities (including delayed response rejection, coalescing, cleanup/remount, scoped aliases, result classification, and fill revisions).
- Passed: seven browser scenarios using the actual Dashboard and confirmation modal in React StrictMode: confirmed cancellation with delayed/stale results, unresolved cancellation, HTTP-200 rejection, empty orders, HTTP source failure, genuine zero totals, and missing totals retaining last values. Both NVDA and USD highlights are observed, including transient DOM changes.
- Passed: production frontend build (`npm run build`, 1,165 modules), `git diff --check`, and the asset-serving unittest using the personal instance virtualenv. The system Python initially lacked `flask_sqlalchemy`; rerunning with the app virtualenv passed.
- Released and deployed: GitHub release `v4.16.2` from commit `5cc9eb25`; personal instance fast-forwarded to the tag with unrelated files preserved, frontend rebuilt, service restarted, `/login` on port 5010 returned 200 serving the released bundle.

Reproduce tests from the source repository:

```bash
node --test tests/dashboard_refresh.test.mjs tests/synthetic_cancellation.test.mjs
PLAYWRIGHT_MODULE_PATH=/path/to/playwright node tests/dashboard_refresh.browser.mjs
cd frontend && npm run build
```

The browser harness uses installed Playwright and Chromium (`CHROMIUM_PATH` overrides `/usr/bin/chromium`), builds its fixture bundle in the system temporary directory, and removes it on exit. It mocks authentication and the independent widget grid; dashboard rows, totals, refresh logic, order calculations, and cancellation modal run from production source.

### Batch v4.16.3 changes and verification

- Findings closed: F03, F07, F10, F11, F21–F27, F37. F38 advanced. Totals after this batch: 21 done, 2 partial (F35, F38), 15 open (F08, F13–F19, F28–F34).
- Implementation: new `frontend/src/utils/dashboardRows.mjs` (row identity, order matching, ordering, saved-edit ledger, watchlist intents); `frontend/src/pages/Dashboard.jsx`; `frontend/src/components/SyntheticRecoveryHost.jsx`; `routes/portfolio.py` (watchlist order, exact Webull removal, Binance base asset); `routes/system.py` (`/api/update-note` accepts `table_type`).
- Behaviour the user will notice: both tables default to A–Z and say so; the watchlist no longer follows the portfolio's sort; a third click on a header returns to A–Z; a failed watchlist removal or hide puts the row back with a message.
- Passed: 15 Node tests (`tests/dashboard_rows.test.mjs`, `tests/dashboard_refresh.test.mjs`, `tests/synthetic_cancellation.test.mjs`).
- Passed: `tests/dashboard_tables.browser.mjs` — stable-order (server order alternating, default and tied sorts, no transient swap), independent-sorts (including reload), exact-row-highlights (same ticker at two providers and two accounts), watchlist-removal (failure rollback; an older list cannot bring a removed row back), saved-edit-survives-refresh.
- Passed: the seven existing `tests/dashboard_refresh.browser.mjs` scenarios and `tests/synthetic_recovery.browser.mjs` with the new late-lookup case.
- Python: `python -m unittest discover -s tests -p 'test_*.py'` runs 1,152 tests. One failure and nine errors occur identically on the released v4.16.2 code and on this batch (`test_webull_service` open-order cache count, eight `test_order_replacement` cases, `test_event_recalibration` setUpClass, one `test_decision_integrity` case). They are pre-existing, not caused by this work, and are not yet fixed.
- Not covered: a UI-driven watchlist addition (the add/re-add ordering is covered by unit tests only); no live broker or real-account run was used.

### Batch v4.16.4 changes and verification

- Findings closed: F08, F17, F18, F28, F35. F33 advanced on the display side. Totals after this batch: 26 done, 1 partial (F38), 11 open (F13–F16, F19, F29–F34).
- Server: `routes/portfolio.py` (`scopes`, `complete`, `mode` on `/api/pending-orders`), `routes/market.py` (`sources`, `pending_mode` on both portfolio endpoints; error instead of an empty list), `services/portfolio_service.py` (`get_pending_order_mode`; fast reader honours paper mode).
- Dashboard: `mergePendingOrders`/`pendingOrderScope` in `frontend/src/utils/dashboardRefresh.mjs`; `acceptPendingOrders` and source-aware `applyPortfolioUpdate` in `Dashboard.jsx`; new `frontend/src/components/CommittedInput.jsx`.
- Behaviour the user will notice: during a Binance.US or Webull outage the affected rows keep their highlight and a line above the portfolio says which source is unavailable; a sold holding disappears on the next complete refresh.
- Passed: 63 Node tests, including two new order-merge cases.
- Passed: `tests/test_pending_order_completeness.py` (4 cases: failed and answering sources, genuine empty, Webull session unable to read, paper mode).
- Passed: `tests/dashboard_tables.browser.mjs` now has eight scenarios; new ones are holdings-membership, order-source-outage and alert-box-follows-saved-value. The seven refresh scenarios and the recovery test still pass.
- Python suite: 1,156 tests; the same ten pre-existing failures as before and no others.
- Not covered: no real broker outage was induced; the outage behaviour is verified with fixtures and mocked providers only.

### Next work

1. Reservations and order descriptions: F13–F16 and F19.
2. Server caches and competing writers: F29–F34. Session-local confirmed cancellation suppression is not shared cache invalidation. F33/F34 should also make an unexpected Webull open-order response count as unavailable rather than empty.
3. Finish F38 with the remaining acceptance scenarios and request diagnostics.
4. Update this ledger with each verified fix and release. Preserve unrelated files in the personal checkout; do not use `upgrade.sh` unchanged because it performs hard resets/forced checkouts. Neither batch needed migrations.

Browser tests need an installed Playwright and the system Chromium, for example:

```bash
export PLAYWRIGHT_MODULE_PATH=/var/www/html/visasentinel/node_modules/playwright CHROMIUM_PATH=/usr/bin/chromium
node tests/dashboard_refresh.browser.mjs && node tests/dashboard_tables.browser.mjs && node tests/synthetic_recovery.browser.mjs
```

Python tests run with the personal instance's virtualenv (`/home/jcavallarojr/crypto_alert_app/venv/bin/python`); the source checkout's own `venv` lacks `flask_sqlalchemy`.

## Original audit boundaries

The original review used source inspection and in-memory reproductions, without placing/cancelling live orders or changing portfolio/watchlist records. Implementation and verification after approval are recorded above; the observations below remain historical evidence, not a claim that all findings are still unfixed.

## What explains the two symptoms

### NVDA and USD briefly turned yellow again after cancellation

The current code permits this sequence:

1. A background request starts while the NVDA BUY strategy is still active. Its response includes that pending strategy.
2. Cancellation succeeds. The dashboard removes the strategy from its local list and clears the pending indication.
3. The older background response arrives afterward. Nothing rejects that old pending-order response, so it restores the strategy to the displayed pending list.
4. NVDA becomes yellow because the restored list says it has a pending order. USD becomes yellow because the same restored BUY order reserves cash.
5. A newer response reports that the strategy is cancelled and clears both indications again.

There are additional ways for the same stale state to return: a fast portfolio response can overwrite newer order information, and an explicitly empty order list can incorrectly fall back to the old nonempty list.

**Evidence level:** These paths exist in the released code. The empty-list defect was reproduced using the actual `applyPortfolioUpdate` function, without modifying application files. However, the browser's original request trace was not captured. I cannot honestly identify which particular response arrived last during your exact flash, or prove that every step above occurred in that exact order. This is an evidenced explanation of how the observed flash can occur, rather than a recovered recording of that event. There is no evidence here that yellow highlighting meant Webull recreated the cancelled order.

### BTC and ETH swapped watchlist positions

This has a concrete ordering problem independent of network races:

- With no selected sort column, the frontend displays the order returned by the server.
- Both crypto watchlist queries call `.all()` without requesting a database order. Database results are not promised to retain the same row order between reads.
- The live endpoint also writes updated prices back to the database. Repeated updates do not establish a stable display order.
- Even with a selected sort column, equal values have no secondary ordering rule. Their relative positions inherit the incoming server order.
- Portfolio and watchlist share the same saved sort setting. Sorting the portfolio can change the watchlist too.

**Reproduction using the actual sorting function:** With default sorting, incoming `[BTC, ETH]` displays as `[BTC, ETH]`, but incoming `[ETH, BTC]` displays as `[ETH, BTC]`. With both rows having the same sentiment and sorting by sentiment, the same reversal occurs.

If you deliberately selected a changing value, such as percentage change, rows changing position as their values cross would be expected sorting behavior. That is separate from the unstable default/equal-value ordering defects. The audit did not have access to your browser's saved sort setting at the time of the swap, so it cannot choose conclusively between those paths for that particular event.

## Scope and evidence

The review covered dashboard initialization, timed refreshes, post-action refreshes, optimistic updates, portfolio/watchlist merging, row identity, sorting, pending highlights, cash reservations, synthetic order display, and related server readers, caches, order imports, and background portfolio writers.

Primary files reviewed:

- `frontend/src/pages/Dashboard.jsx`
- `frontend/src/components/SyntheticOrdersTable.jsx`
- `frontend/src/components/SyntheticRecoveryHost.jsx`
- `frontend/src/utils/syntheticOrders.mjs`
- `routes/market.py`
- `routes/portfolio.py`
- `routes/system.py`
- `services/portfolio_service.py`
- `services/webull_service.py`
- `services/webull_import_service.py`
- `services/order_history_sync_service.py`
- `services/binance_service.py`
- `services/scheduler_tasks.py`
- Existing cancellation, synthetic lifecycle, and browser-test coverage relevant to these paths.

**How to read the findings:** “Confirmed code defect” means the behavior follows from the inspected code; it does not mean every user has experienced it. “Structural risk” means the protection is missing, but the audit did not reproduce an actual production collision. “Behavior needing clarification” means the interface can mislead or move unexpectedly even when the underlying data is valid.

The following list includes every distinct problem identified in this scoped audit. It is not a mathematical guarantee that no other defect exists in the application.

## A. Refresh ordering and cancellation races

### F01 — Old pending-order responses can undo a successful cancellation visually

**Priority:** Highest. **Finding:** Confirmed code defect.

**Problem:** The main poll, initial load, replacement handlers, and cancellation handlers all write the pending-order list. There is no common request sequence or cancellation barrier. An old response can put a just-cancelled strategy back into the UI.

**Evidence:** `Dashboard.jsx`: `fetchData`, `handleConfirmCancelOrder`, replacement refresh callbacks, and direct `setPendingOrders` calls around lines 2255–2383 and 3022–3279.

**Proposed fix:** Give every order read a request-time identity and mutation generation. A successful cancellation/replacement makes all older reads ineligible to update the screen. Start its follow-up reads only after the action finishes. Preserve a confirmed local cancellation until a genuinely newer authoritative result can supersede it; never hide an unresolved broker child merely because cancellation was requested.

### F02 — Portfolio freshness IDs are often assigned after the response arrives

**Priority:** Highest. **Finding:** Confirmed code defect.

**Problem:** The existing “ignore older responses” mechanism cannot reliably determine request age. Several callbacks call `nextPortfolioFetchId()` only after their network request has completed. A slow old request can receive the newest number.

**Evidence:** `Dashboard.jsx`: live refresh around line 2382, filled-order refresh around 2489, and post-action `.then(...)` callbacks such as 3022.

**Proposed fix:** Allocate the ID before issuing the request. Carry it through the entire response application. Use the same guard for every path that writes portfolio rows or totals.

### F03 — Refresh cycles can overlap, with extra refreshes inside them

**Priority:** High. **Finding:** Confirmed code defect.

**Problem:** A new ten-second refresh starts even if the preceding one is still waiting for a broker or price service. Fill checks and post-action handlers can start still more reads. `Promise.allSettled` does not serialize separate refresh cycles.

**Evidence:** `Dashboard.jsx`: `setInterval(fetchData(false), 10000)`, `fetchData`, and `checkForFilledOrders`.

**Proposed fix:** Allow one coordinated refresh cycle at a time. Coalesce extra requests into one follow-up refresh, rather than stacking them. Keep cancellation/mutation invalidation independent of that scheduling rule.

### F04 — A normal refresh first applies an older database snapshot, then a live snapshot

**Priority:** High. **Finding:** Confirmed code defect.

**Problem:** `fetchData(false)` still fetches and applies `/api/coin-data` before its later `/api/coin-data-live` request. The first application uses an unguarded `setPortfolio(withFlags)`. The dashboard can step backward before stepping forward again.

**Evidence:** `Dashboard.jsx`: the unconditional first portfolio request around 2240–2277 and the subsequent live branch.

**Proposed fix:** Use the fast snapshot for initial hydration only, with an explicit freshness label. Subsequent refreshes should apply one validated portfolio result. Embedded cached orders must not overwrite a newer dedicated order lookup.

### F05 — An empty order list is sometimes treated as “use the previous list”

**Priority:** Highest. **Finding:** Confirmed code defect; reproduced.

**Problem:** “There are no pending orders” should clear highlighting. Instead, initialization only adopts a nonempty list, and `applyPortfolioUpdate` falls back to the old ref when an explicit empty list is supplied.

**Evidence:** `Dashboard.jsx`: `incomingPending.length > 0` and the `ordersToCheck` expression requiring `pendingOrdersList.length > 0`.

**Proposed fix:** Distinguish three cases: a valid empty list, unavailable order data, and no order data included. Accept a valid empty list as authoritative. Preserve previous data only when the source explicitly failed or did not report that scope.

### F06 — Pending orders have multiple writable copies and cancellation uses old render values

**Priority:** High. **Finding:** Confirmed code defect.

**Problem:** Code writes both React state and `pendingOrdersRef`, while an effect copies state back into the ref. Cancellation also uses the `pendingOrders` array captured by an earlier render when updating other rows. These mechanisms do not form one atomic update.

**Evidence:** `Dashboard.jsx`: `pendingOrdersRef`, the effect around line 331, and cancellation calculations using `pendingOrders.filter(...)`.

**Proposed fix:** Use one controlled pending-order state update function or reducer. Publish the accepted order list and its derived row/cash indicators together. Avoid reading old render closures after awaited operations.

### F07 — Outstanding dashboard reads and deferred work survive cleanup

**Priority:** Medium. **Finding:** Structural risk.

**Problem:** The main effect clears its interval, but does not abort its running requests or clear/guard the delayed initial-load callback. Logging out, navigating away, or remounting can leave old work finishing later. The effect also captures initial authentication state.

**Evidence:** `Dashboard.jsx`: main refresh effect, its 50ms `setTimeout`, empty dependency list, and cleanup that clears only the interval/listener.

**Proposed fix:** Cancel outstanding dashboard reads and deferred callbacks on cleanup. Check the current user/session generation immediately before applying a response. Resume correctly after development-mode effect remounts.

### F08 — Refresh merging can keep holdings that are absent from the new snapshot

**Priority:** High. **Finding:** Confirmed code defect; reproduced.

**Problem:** `applyPortfolioUpdate` starts from the previous portfolio and overlays incoming rows. It does not remove an old holding simply because a complete new snapshot omits it. A sold, hidden, or removed holding can remain as a ghost row with its previous positive amount.

**Evidence:** `Dashboard.jsx`: `applyPortfolioUpdate`, `prevMap`, and the final traversal of previous rows. Passing a complete empty snapshot retained the old holding in the in-memory reproduction.

**Proposed fix:** Replace membership for each successfully refreshed provider/account scope, while preserving stable visual order for surviving rows. Retain old rows only for explicitly unavailable scopes, not for a successful complete empty response.

### F09 — Totals have competing writers and a separate stale startup cache

**Priority:** High. **Finding:** Confirmed code defect/risk.

**Problem:** `/api/coin-data`, `/api/coin-data-live`, `/api/true-portfolio-value`, and `/api/account-summary` independently set totals. They can represent different times. Missing values are sometimes converted to zero. Startup totals are also loaded from browser keys that are not scoped by user/account/environment.

**Evidence:** `Dashboard.jsx`: total/account-total state initialization around 140–163; multiple setters in `fetchData`; `scopedTotalValue` falling back from zero totals to other sources.

**Proposed fix:** Apply rows and their matching totals from the same accepted snapshot. Distinguish a valid zero from missing data. Retain last good totals on failure, with a freshness indicator. Remove unscoped financial-value caches or key them by authenticated user, account scope, and live/paper environment.

## B. Order identity, highlighting, and cash calculations

### F10 — Matching a pending order does not fully identify its account or instrument

**Priority:** High. **Finding:** Confirmed code defect.

**Problem:** Matching is provider-aware but not account-aware or instrument-aware. The same ticker in two Webull accounts can highlight both rows. Prefix matching such as `startsWith(symbol + 'USD')` can also match more than the intended Binance pair.

**Evidence:** `Dashboard.jsx`: `getPendingOrdersForCoin` around lines 199–216.

**Proposed fix:** Match a full identity: provider, account where applicable, instrument/contract, and normalized exact symbol/pair. Use a deliberate aggregate rule only for rows that truly combine accounts. Do not silently treat a missing account as every account.

### F11 — Some local updates and React row keys identify a row too loosely

**Priority:** High. **Finding:** Confirmed code defect.

**Problem:** Watchlist rows use `key={item.symbol}`. Other callbacks update rows by symbol or numeric ID alone. Binance and Webull can have the same symbol, and separate database tables can reuse numeric IDs. React or a callback can target the wrong logical row.

**Evidence:** `Dashboard.jsx`: watchlist row key around 6361; portfolio key around 5789; alert/news/favorite updates using symbol-only or ID-only comparisons; `optimisticHiddenCoins` keyed only by ID.

**Proposed fix:** Use one composite row identity everywhere, including React keys, editor keys, hidden-row sets, optimistic items, callback matching, and tooltips. Include provider and account/instrument where needed.

### F12 — Cancellation can remove more than the intended local order

**Priority:** High. **Finding:** Confirmed code defect.

**Problem:** Local cancellation filtering compares only `order_id || orderId || id`. If two accounts/providers use the same identifier, removing one can temporarily remove the other from the screen.

**Evidence:** `Dashboard.jsx`: `handleConfirmCancelOrder` filtering `pendingOrders` by `orderId` without provider/account scope.

**Proposed fix:** Remove only the exact composite order identity. Include aliases for a broker order/client ID only within that same provider/account. Reconcile all affected views from the accepted result.

### F13 — A synthetic parent and its broker child can both reserve the same cash

**Priority:** High. **Finding:** Structural risk supported by the returned data shapes.

**Problem:** The pending endpoint appends synthetic parents and also appends native Webull open orders. A submitted synthetic child can appear in both. The cash calculation sums both entries without linking them.

**Evidence:** `routes/portfolio.py`: synthetic append followed by `webull_entries`; `Dashboard.jsx`: `getWebullCashBalance` and synthetic/native BUY reservation loops.

**Proposed fix:** Link parents to broker children through the execution journal's client and broker IDs. Count their outstanding quantity once, while retaining execution detail. Do not guess that two unrelated orders are duplicates merely because symbol, size, and price match.

### F14 — Native OCO cash reservations can be counted as two independent purchases

**Priority:** High. **Finding:** Confirmed calculation gap.

**Problem:** The Webull pending formatter labels entries `is_oco: False`, and the Webull cash helper adds every BUY leg. It does not preserve or use the native OCO/group relationship as the Binance helper partly does.

**Evidence:** `routes/portfolio.py`: Webull pending-order formatter; `Dashboard.jsx`: `getWebullCashBalance`, compared with `getQuoteBalance`'s `orderListId` handling.

**Proposed fix:** Preserve group identifiers and model OCO/OTO/OTOCO obligations correctly. Reserve the applicable mutually exclusive amount, not the sum of every possible branch. Keep separate live orders separate.

### F15 — Some reservations still use original quantities after partial fills

**Priority:** High. **Finding:** Confirmed code defect.

**Problem:** Binance pending formatting uses `origQty` without subtracting `executedQty`. Fast trailing formatting uses the original trailing quantity. This can overstate remaining reserved funds and extend cash highlighting after part of the trade is complete.

**Evidence:** `routes/portfolio.py`: Binance `quantity`/`quote_amount` construction; `services/portfolio_service.py`: fast trailing `quantity` and `quantity_usdt`.

**Proposed fix:** Derive outstanding quantity consistently from confirmed fills and unresolved child quantity. Use the same normalized values in fast and live responses. Recompute reservations as fills are confirmed.

### F16 — New conditional strategies are not fully represented by older pending-order formatters

**Priority:** High. **Finding:** Confirmed code defect.

**Problem:** OCO/OTO/OTOCO can now be stored with `conditional_spec`, no ladder rungs, and no legacy upper/lower target fields. Pending formatters still derive the next price mainly from ladder rungs and legacy targets. They can report a zero price/budget or misleading ladder description for a real working conditional strategy. Fast ladder entries also omit some detail supplied by the full endpoint.

**Evidence:** `services/portfolio_service.py`: `get_fast_pending_orders`; `routes/portfolio.py`: synthetic ladder pending formatter; `services/synthetic_conditional_service.py`: creation and entry/exit phase changes.

**Proposed fix:** Create one shared pending-strategy serializer that understands each strategy and phase. Return actionable leg prices, outstanding quantity, current side, journal linkage, and consistent descriptions. Use it in both fast and live endpoints.

### F17 — Temporary broker failures can look like “all orders disappeared”

**Priority:** High. **Finding:** Confirmed code defect.

**Problem:** The pending endpoint catches a Binance or Webull-account lookup failure, logs it, and returns a successful response containing only the sources that worked. The frontend cannot tell whether a missing account has zero orders or failed to report them. Fast pending collection similarly swallows source errors.

**Evidence:** `routes/portfolio.py`: Binance lookup exception, per-account Webull exception, final response; `services/portfolio_service.py`: caught synthetic/Webull/cache errors.

**Proposed fix:** Return per-provider/account completeness and freshness. A successful empty scope clears its previous orders. An unavailable scope retains its last confirmed state with a visible warning. Confirmed local cancellations must not be resurrected by that fallback.

### F18 — The fast and live pending sources have different mode and freshness rules

**Priority:** High. **Finding:** Confirmed contract inconsistency.

**Problem:** Fast synthetic reads filter `test_mode=False`, and fast Webull reads use the local order table. The full endpoint separately handles Webull test mode and broker lookups. The dashboard receives both shapes without a common mode/version contract.

**Evidence:** `services/portfolio_service.py`: `get_fast_pending_orders`; `routes/portfolio.py`: `api_pending_orders`; dashboard initialization versus background branch.

**Proposed fix:** Specify user, account scope, environment, live/paper mode, snapshot revision, and completeness explicitly. All readers must honor the same contract. Switching modes invalidates in-flight results and their cached snapshots.

### F19 — Yellow cash highlighting conflates several different meanings

**Priority:** Medium. **Finding:** Behavior needing clarification.

**Problem:** Cash rows become “pending-order” rows whenever calculated available cash is below the displayed total. That difference can include auto-buy budgets, not just submitted exchange orders. Incorrect duplicate reservations amplify the confusion.

**Evidence:** `Dashboard.jsx`: `getQuoteBalance`, `getWebullCashBalance`, `hasLockedQuote`, and `hasExchangeOrder` around line 5753.

**Proposed fix:** Keep a clear distinction between a pending broker order, a monitored synthetic strategy, and an allocation reserved for automation. Derive each from the same accepted state and explain the cash amount in the tooltip. Do not fix this by hiding legitimate reservations.

### F20 — HTTP 200 can be mistaken for successful cancellation

**Priority:** High. **Finding:** Confirmed code defect.

**Problem:** Dashboard cancellation accepts `response.data.success || response.status === 200`. An API response with a failure result but HTTP 200 can make the UI remove the order even though cancellation failed.

**Evidence:** `Dashboard.jsx`: both broker/generic cancellation success conditions; paper cancellation routes can return serialized service results directly.

**Proposed fix:** Require an explicit successful application result and inspect its final/pending status. Treat rejection, acknowledgement, and confirmed cancellation separately. Keep the row and show the error on a failed result.

## C. Watchlist ordering and local edits

### F21 — The default BTC/ETH row order has no stable definition

**Priority:** High. **Finding:** Confirmed code defect; reproduced in the display function.

**Problem:** Both crypto watchlist queries omit `ORDER BY`, while the frontend defaults to no selected sort and displays the incoming order. Refreshes are therefore allowed to move BTC and ETH even if the user never asked to sort them.

**Evidence:** `routes/portfolio.py`: `api_watchlist` around 6027 and `api_watchlist_live` around 6097; `Dashboard.jsx`: default `sortConfig` around 602 and `sortData` around 2664.

**Proposed fix:** Define a stable default order on the server and preserve it in the UI. Recommended review choice: alphabetical order with a full-identity tie-breaker, unless you prefer a separately persisted manual order. Price updates alone must not change default row positions.

### F22 — Equal sort values have no deterministic tie-breaker

**Priority:** High. **Finding:** Confirmed code defect; reproduced.

**Problem:** Equal numeric values, two missing values, or equal text values return comparison result zero. Stable JavaScript sorting preserves incoming order—not a permanent user order—so varying server order still moves tied rows.

**Evidence:** `Dashboard.jsx`: numeric and text comparators in `sortData`.

**Proposed fix:** For every sort, compare the selected value first, then a stable secondary key such as symbol/provider/account/instrument. Specify consistent placement of missing values. This does not require replacing JavaScript's sort implementation.

### F23 — Sorting the portfolio silently changes the watchlist sort

**Priority:** High. **Finding:** Confirmed code defect/interaction.

**Problem:** Both tables share `sortConfig`, `handleSort`, and the `dashboardSortConfig` browser key. Sorting a portfolio-only field can leave the watchlist sorting on values it does not even display.

**Evidence:** `Dashboard.jsx`: the single sort state, both header click handlers, and both table renderers.

**Proposed fix:** Separate portfolio and watchlist sort state and saved preferences. Validate a restored preference against that table's supported columns, and show an unambiguous sort indicator on the affected table.

### F24 — Changing-value sorts and temporary pinning can move rows without explaining why

**Priority:** Medium. **Finding:** Behavior needing clarification.

**Problem:** Sorting by live price/change/sentiment recalculates order on refresh. Newly added rows are also pinned to the top until confirmation, then released into the active sort. These movements can be legitimate but look random without a visible policy.

**Evidence:** `Dashboard.jsx`: `getDisplayWatchlist`, `pendingAddedWatchlistSymbolsRef`, and render-time `sortData`.

**Proposed fix:** Keep default ordering stable. Only reorder by changing values when that is the user's explicit watchlist sort choice. Clearly indicate that choice, and make “adding/confirmed” transitions predictable. Do not apply a hidden price sort as a stability fix.

### F25 — Optimistic watchlist additions are keyed only by ticker

**Priority:** High. **Finding:** Confirmed code defect.

**Problem:** The optimistic-add map, duplicate checks, confirmation replacement, and error cleanup use just the symbol. A Webull security and a Binance asset with the same symbol can confirm, suppress, overwrite, or remove the wrong item.

**Evidence:** `Dashboard.jsx`: `mergeWatchlistPreservingPending`, `addToWatchlist`, and `getDisplayWatchlist`.

**Proposed fix:** Use full watchlist identity for optimistic maps and all callbacks. Carry provider/type into temporary rows. Confirm only the exact pending addition returned by that request.

### F26 — Watchlist removals can reappear, and removal failure is not rolled back

**Priority:** High. **Finding:** Confirmed code defect/race risk.

**Problem:** Removal immediately filters the row, but an older list fetch or an earlier add response can put it back. Removal catches errors and only logs them. The Binance removal filter is also symbol-only and can affect a same-ticker Webull row locally.

**Evidence:** `Dashboard.jsx`: `deleteWatchlistItem`, optimistic add completion callbacks, and list application.

**Proposed fix:** Track the latest mutation intent per full row identity. Reject earlier reads/add completions. Preserve the removal until a post-removal authoritative read confirms it. On failure, restore the affected row and show a useful error, without undoing a newer user action.

### F27 — Refreshes can overwrite a newly saved favorite, alert, note, or automation setting

**Priority:** High. **Finding:** Structural risk.

**Problem:** Those actions update local rows, but their completion does not invalidate older portfolio/watchlist reads. Some callbacks also update by symbol or ID alone. A slower refresh can put the old setting back on screen.

**Evidence:** `Dashboard.jsx`: favorite/alert/auto-buy/auto-sell handlers, note/news updates, and `applyWatchlistUpdate`/`applyPortfolioUpdate`.

**Proposed fix:** Extend the same mutation barrier to all relevant row edits. Track per-field/per-row pending edits where appropriate. Apply a committed server result only to its exact row, and ignore superseded responses.

### F28 — Editable fields do not consistently follow refreshed values

**Priority:** Medium. **Finding:** Confirmed interface consistency gap.

**Problem:** Several alert inputs use `defaultValue`. That initializes a field when it mounts, but does not automatically replace it when a background refresh returns a different saved value. A row can show one state in its data/tooltip and another in its input. Weak row/editor keys increase the risk.

**Evidence:** `Dashboard.jsx`: `renderPortfolioAlertCell`, watchlist alert cells, volatility inputs, `defaultValue`, and editor keys based on row ID/symbol plus direction.

**Proposed fix:** Use field state that distinguishes an active unsaved edit from the last committed server value. Preserve typing while editing; adopt newer committed values after save, cancellation, or an appropriate external refresh. Use full row identity in editor keys.

## D. Server caches and competing background syncs

### F29 — Webull order caches are private to each process, including invalidation

**Priority:** High. **Finding:** Confirmed architecture risk.

**Problem:** Webull open-order results can be cached for 45 seconds. `clear_webull_order_cache()` clears only the Python process that handled the action. Another web worker or the background worker can still serve an older list. A request already in progress can also repopulate a cache after invalidation. Binance's fast cache has a separate 60-second window.

**Evidence:** `services/webull_service.py`: module dictionaries, `clear_webull_order_cache`, `get_webull_open_orders`; `services/portfolio_service.py`: `_FAST_BINANCE_ORDERS_CACHE`.

**Proposed fix:** Use shared, revision-aware invalidation across workers, with user/account/environment scope. Prevent older fetches from repopulating a newer revision. Request a properly rate-limited fresh order result after a mutation. Preserve caching where it is safe; do not simply hammer Webull on every render.

### F30 — Multiple backend jobs can write the same portfolio snapshot out of order

**Priority:** High. **Finding:** Structural risk.

**Problem:** The periodic Webull sync, open-order watcher, and post-transaction thread can each fetch and import a portfolio for the same user. The import has no shared per-user fetch-to-commit lock or rejection of an older observation. A slow older sync can overwrite a newer one. Binance sync also reads balances, performs slow trade-history work, then applies the earlier balance snapshot.

**Evidence:** `services/scheduler_tasks.py`: portfolio/open-order loops; `routes/system.py`: `_schedule_webull_transaction_refresh`; `services/webull_import_service.py`: `refresh_webull_portfolio_snapshot` and `import_webull_portfolio_snapshot`; `services/binance_service.py`: `sync_binance_account`.

**Proposed fix:** Coordinate snapshot writers across processes and reject stale observations. Protect the fetch-to-commit interval or apply a reliable revision rule, not just a lock around the final SQL update. Coalesce transaction-triggered refreshes. Fetch current Binance balances close to the write rather than applying a balance read from before long history work.

### F31 — Older imported order records can overwrite newer terminal states or fill totals

**Priority:** High. **Finding:** Confirmed missing safeguard; production regression not reproduced.

**Problem:** Webull and Binance order imports assign incoming status and filled quantity without first rejecting an older provider observation. Webull synchronization combines history and open-order lists with different cache lifetimes. A stale OPEN copy can overwrite a newer cancellation/fill, and a smaller old fill total can replace a larger one.

**Evidence:** `services/webull_import_service.py`: `import_webull_orders`; `services/order_history_sync_service.py`: `import_binance_orders`, `sync_webull_order_history_for_user`, and `sync_webull_account_orders`.

**Proposed fix:** Reconcile by full order identity and provider observation time/revision. Keep cumulative fills monotonic, protect confirmed terminal states from stale open-list copies, and obtain uncached order detail when snapshots conflict. Do not fabricate a terminal result from an unavailable provider response.

### F32 — Display GET requests also change persisted portfolio/watchlist state

**Priority:** High. **Finding:** Confirmed competing-writer design problem.

**Problem:** The pending-order reader can add/unhide watchlist items and hide dust holdings while disabling related flags. Portfolio GETs update prices/visibility, and the live watchlist GET writes prices. These endpoints are called from multiple browser refresh paths while background jobs write the same records. This makes a simple screen refresh more than a read.

**Evidence:** `routes/portfolio.py`: `api_pending_orders` around 928–979 and `api_watchlist_live`; `routes/market.py`: both coin-data endpoints and their commits.

**Proposed fix:** Separate display reads from controlled synchronization writes. Preserve existing intended behavior—such as placing an externally discovered unfilled BUY in the watchlist—in one supervised, idempotent sync path. Read endpoints should report accepted state, not change visibility/alert settings as a side effect of fetching highlights. Moving those behaviors requires explicit tests so features are not silently removed.

### F33 — Missing/malformed snapshot data is not always distinguished from a genuine empty account

**Priority:** High. **Finding:** Structural risk.

**Problem:** A non-list positions response is normalized to an empty list. The snapshot importer removes holdings absent from the received snapshot and removes accounts absent from the preview. Without a completeness contract, a malformed or unexpectedly empty response can be treated as “these holdings no longer exist.”

**Evidence:** `services/webull_service.py`: `get_webull_account_positions`, `get_webull_portfolio_preview`; `services/webull_import_service.py`: missing-position/account cleanup in `import_webull_portfolio_snapshot`.

**Proposed fix:** Validate response shape and per-account completeness before treating absence as removal. Preserve last confirmed holdings on uncertainty. Apply removals only from an explicitly complete, newer, authoritative snapshot. This is a proposed code change; no cleanup or destructive database operation was run in this audit.

### F34 — A single page can be treated as the entire Webull open-order set

**Priority:** High for accounts exceeding the page limit. **Finding:** Confirmed code gap.

**Problem:** `get_webull_open_orders` requests up to 100 results and does not follow subsequent pages. Downstream highlighting and sync logic can treat the returned set as complete even when more orders exist.

**Evidence:** `services/webull_service.py`: `get_webull_open_orders`, `safe_page_size`, and the single per-account request/response loop.

**Proposed fix:** Follow the provider's actual pagination contract, retain group relationships, and mark a truncated/failed list incomplete. Test a multi-page account and a failure on a later page before allowing absence to clear rows or reservations.

## E. Notifications, related order views, and diagnosis

### F35 — A recent fill can repeatedly trigger refreshes and success toasts

**Priority:** Medium. **Finding:** Confirmed code defect.

**Problem:** Each refresh finds orders filled within the last five minutes, shows “Order filled! Portfolio updated,” and makes another live portfolio request. It does not remember which fill has already been handled. Empty resulting portfolios are also ignored by this path because it requires a nonempty array.

**Evidence:** `Dashboard.jsx`: `checkForFilledOrders` around 2475–2491.

**Proposed fix:** Handle a fill once per full order identity and new confirmed fill revision. Coalesce its refresh with the main cycle. Accept a complete empty portfolio after the last holding is sold.

### F36 — Synthetic recovery changes do not immediately synchronize every dashboard view

**Priority:** Medium. **Finding:** Confirmed event-wiring gap.

**Problem:** Recovery emits `app:synthetic-updated`; the synthetic tables listen to that event. Dashboard's refresh effect listens to `app:refresh-dashboard`, so its portfolio/watchlist highlights can wait for the next regular poll after a recovery decision or strategy cancellation elsewhere.

**Evidence:** `frontend/src/components/SyntheticRecoveryHost.jsx`: recovery success dispatch; `SyntheticOrdersTable.jsx`: update listener; `Dashboard.jsx`: main effect listeners.

**Proposed fix:** Route relevant order changes through one dashboard invalidation/refresh event contract, including cancellation, replacement, recovery, and mode/account changes. Invalidate old reads before starting the coordinated refresh.

### F37 — The recovery modal can receive the wrong late lookup result

**Priority:** Medium. **Finding:** Structural risk.

**Problem:** Opening recovery starts an asynchronous strategy-list lookup. Opening a different strategy before the earlier lookup completes can let the earlier result replace the newer modal's data. That lookup does not have the main poll's stopped/request-generation protection.

**Evidence:** `frontend/src/components/SyntheticRecoveryHost.jsx`: the `app:synthetic-recovery` handler, `candidate`, awaited list request, and subsequent `setOrder`/settings updates.

**Proposed fix:** Give each modal opening its own request identity and cancellation. Apply fetched order details only if the same modal request is still current. Revalidate the exact strategy again when submitting the chosen action.

### F38 — Current tests and logs do not establish absence of these races

**Priority:** High verification gap. **Finding:** Confirmed coverage/observability gap.

**Problem:** The existing cancellation tests verify routing, ownership, 2FA, and cancellation-pending behavior. They do not simulate the complete dashboard receiving responses in reversed order after cancellation. Existing browser scenarios do not establish stable BTC/ETH ordering across repeated refreshes. There is also no shared browser/server snapshot/request revision trail sufficient to reconstruct the reported flashes precisely.

**Evidence:** `tests/test_dashboard_synthetic_cancellation.py`, `tests/synthetic_cancellation.test.mjs`, synthetic lifecycle/browser coverage, and the refresh response/application code.

**Proposed fix:** Add deterministic delayed-response browser tests and structured diagnostic IDs. Record request start, response revision/scope, mutation generation, applied/rejected decision, and order-state transition without recording credentials or 2FA codes. Include representative real-account read-only observation after approval; never require a live trade to test UI races.

## Approved implementation order

1. **Stop stale-state resurrection:** F01–F08, F17–F18, F20, and F36. Establish shared freshness, mutation, completeness, and cleanup rules before changing individual visual symptoms.
2. **Make row identity and sorting deterministic:** F10–F12 and F21–F28. Separate table sorts and define the default ordering policy you approve.
3. **Make reservations and order descriptions consistent:** F13–F16 and F19. Share normalization between fast/live readers and account for groups, fills, parents, and children.
4. **Coordinate server writers and caches:** F29–F34. Implement cross-process freshness and completeness safeguards while respecting provider rate limits and existing features.
5. **Finish related UI and verification work:** F09, F35, F37–F38, alongside tests for every earlier phase. Publish a release and upgrade the personal instance only after the approved scope is implemented and checked.

## Acceptance checks for the approved fixes

- Cancel an untriggered synthetic BUY while holding an older pending-order response. Release the old response afterward: neither the security nor its cash row may regain a pending highlight.
- Repeat with two responses arriving in reverse order, a very slow refresh, failed follow-up requests, another browser tab, and two application workers.
- Keep a submitted child visible while its cancellation remains unresolved; clear it only after final confirmation. Do not mistake a failure or an acknowledgement for completed cancellation.
- Verify that a genuine empty pending-order list clears highlights and a genuine empty portfolio removes the final holding.
- Verify that an unavailable provider/account retains its last confirmed rows with a warning, without reviving a locally confirmed cancellation.
- Refresh BTC/ETH repeatedly under no sort, equal-value sorts, and deliberate live-value sorts. Default and tied ordering must stay stable; only an explicit changing-value sort may reorder by its displayed values.
- Sort the portfolio and confirm the watchlist does not change. Reload and verify separate saved sort preferences.
- Test duplicate symbols across Binance/Webull, the same security in two Webull accounts, and matching numeric IDs from separate tables. Updating or cancelling one must not affect another.
- Add/remove/re-add a watchlist item while delaying each response. The latest user intent must win, and a failed action must be reported and rolled back safely.
- Edit alerts/favorites/notes during refreshes. Saved values must not revert; in-progress typing must not be overwritten.
- Verify each reservation once for native OCO, synthetic parent plus child, partial fills, and OTO/OTOCO entry/exit transitions.
- Return stale OPEN data after a confirmed fill/cancellation. Stored order state and cumulative fills must not move backward.
- Race periodic and transaction-triggered portfolio imports in isolated tests. An older snapshot must not overwrite a newer snapshot or a current visibility decision.
- Test malformed positions data, zero holdings, multiple open-order pages, and a later-page failure without treating incomplete data as an empty account.
- Leave the dashboard or log out during delayed reads. No old response may update a new session or start abandoned polling work.
- Handle each fill notification once, and verify recovery always opens the strategy the user selected.

## Limits and decisions for review

- The two symptoms have concrete code explanations, but the original browser request history and saved sort setting were not available. The report does not invent that missing evidence.
- Stable default ordering needs a product decision: the proposed default is alphabetical, with explicit changing-value sorts and an optional separately persisted manual order if desired.
- Normal price changes, confirmed fills, and explicitly selected changing-value sorts can legitimately change the display. The goal is to remove unexplained reversals and stale-state flashes, not hide real market/account updates.
- Broker latency, data outages, and network failures cannot be abolished. Their UI behavior can be made explicit and consistent instead of temporarily presenting contradictory state.
- Implementation was subsequently authorized by the user on November 14, 2026. The ledger above records what has actually been completed.
