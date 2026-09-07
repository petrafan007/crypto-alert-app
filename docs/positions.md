# Positions views and column layouts (v2.93.0)

Positions are filled holdings; unfilled instructions remain under Open Orders. An expired event holding remains a position while settlement is pending.

## Where to find positions

- **Webull Trading:** Positions uses the selected Real Trading, Test, or Quantitative Strategy mode. Holdings below the order ticket use the same table, initially filtered to the ticket’s asset class. Expanded details retain Load trade ticket / Open position controls in real and test modes.
- **Orders (`/orders?tab=positions`):** Positions provides Real Trading (Binance.US and imported Webull holdings), Webull Test Mode, and administrator-only Quantitative Strategy selections. These selections inspect holdings without changing the saved Webull trading mode. Real and simulated portfolios remain separate.

Real holdings use the existing imported portfolio feed and its asset-visibility settings. Use the account filter to narrow the selected mode. Refresh positions reloads the selected feed; loading and failures are displayed explicitly. Quantitative access continues to require administrator authorization on the server.

## Table controls

Select All assets for the portfolio overview, or an asset view for relevant defaults. Each view shows a count. Filters support account, instrument/name, and days to expiration. Switching asset views clears the expiration filter.

Drag the handle beside a column heading onto another heading to move it. Click the heading text to sort. Customize columns includes show/hide checkboxes and left/right arrow buttons usable with keyboard or touch. The instrument column stays visible but can move. Reset to defaults affects only the selected asset view.

Layouts are saved per signed-in user and asset view in browser local storage, shared between Webull Trading and Orders and across trading modes. They persist after refresh on this browser; they do not sync across devices. If browser storage is blocked, changes still work for the current table session. The older, unscoped column preferences are not migrated because they have no user identity.

Click a row or its instrument button to expand details. Dialogs support Escape, focus containment, and return focus to the triggering control. Wide tables scroll horizontally; column controls work on small screens.

## Contract data

Event columns show the purchased YES/NO outcome independently from the confirmed settlement result. The table distinguishes Active, Awaiting settlement, Settlement delayed, and unavailable status. Delay requires a recorded delay/error or passage of the provider's expected settlement time; elapsed trading cutoff alone means awaiting settlement. Cutoffs are shown in Eastern time with the time-zone abbreviation, and countdowns update every second.

Saved user-scoped event observations supply contract questions, conditions, thresholds, and settlement checks. When title or cutoff is missing, the table requests metadata for that exact held contract from Webull. Missing or delisted metadata remains unavailable; trade prices never establish settlement. Quote marks and ledger values are not replaced by metadata lookup responses. Metadata retrieval does not place or settle orders.

Option spread details include both legs. Quantitative option/futures market values represent allocated collateral plus unrealized P&L, consistent with the paper ledger; the expanded details identify this valuation basis. Missing provider fields display a dash. Fees display only when recorded in the position response.

## Verification

Run `node --test tests/positions.test.mjs` and `python -m unittest tests.test_position_metadata`. The browser regression test is `tests/browser/positions.mjs`: start Vite on port 5178, then run it with Playwright installed and Chromium available. `PLAYWRIGHT_MODULE`, `CHROMIUM_PATH`, and `POSITIONS_TEST_ORIGIN` can override their locations. API requests are mocked; the test does not place orders or access a live account.
