# Synthetic orders in v3.9.0

Ladders, single targets and trailing strategies support Binance.US spot crypto and Webull crypto, stocks and ETFs. The shared Synthetic Orders table appears in Consolidated Orders and both broker trading pages. The dashboard widget links to consolidated order management.

## Execution behavior

- BUY and SELL use mirrored target, activation and trailing rules. SELL trails market highs; BUY trails market lows. A trailing trigger submits the full remaining strategy quantity.
- Profit targets and protection share one total quantity. Each ladder distributes that quantity across its own steps; fills on either side reduce the available remainder on both sides. If both protection and profit conditions apply on a tick, protection is evaluated first.
- A single protection stop can execute a market order in the strategy's direction or cancel the remaining strategy without trading. Earlier `SELL_ALL` action names are compatibility identifiers; BUY protection buys the remainder.
- Each live submission has a durable intent and unique client ID saved before transmission. A timeout or uncertain response blocks additional submissions until broker reconciliation resolves it. The engine never automatically retransmits an uncertain intent. An unresolved intent may require checking broker history and account permissions.
- Submission acknowledgements are distinct from fills. Only broker-reported filled quantities contribute to progress. Actual average execution price is shown separately from trigger price. Partial fills remain visible if an execution is cancelled or rejected.
- Cancelling stops future strategy evaluation and requests cancellation of any unresolved execution. The parent remains `CANCEL_PENDING` until the broker confirms its final state. Completed fills cannot be cancelled.
- PostgreSQL session advisory locks serialize each parent across worker instances and cancellation requests, including across commits. Binance paper account locks and Webull paper account row locks protect simulated accounting.
- Paper executions update the selected broker's simulated balances, positions, order record and execution journal in one transaction. No live order is sent for a paper strategy.

## Validation and monitoring

Live creation applies the user's configured 2FA and test-mode settings and validates Webull account authorization and token environment. Quantity precision, market lot/notional rules and configured maximum USD order value are checked at creation and again before submission. Available holdings/cash are checked before live submission; these strategies do not open short positions. Binance symbols must support market orders. Webull fractional stock/ETF executions require at least $5 and quantities with at most five decimal places.

Webull stocks and ETFs execute market orders only during regular exchange hours, using the market calendar for holidays and early closes. Crypto is monitored continuously. Quotes are requested from the order's venue/environment; local cached Coin prices are not execution fallbacks. Timestamped Webull quotes older than 120 seconds during trading are rejected. Missing quotes and closed-market waits are shown in the monitoring column. A successful quote request without a provider timestamp cannot establish trade-time freshness.

Strategies run on the application worker and require that worker, market data and broker connectivity to remain available. They are polled triggers, not exchange-hosted stops. Trigger prices are not guaranteed fill prices; market execution can slip or fail broker checks. Strategy creation does not reserve live assets or buying power. Other account activity can leave insufficient funds when a later trigger fires; the strategy then stops with an error rather than silently reporting success.

## Tables and themes

The shared table shows broker/account, asset class, paper/live mode, strategy type, quantity, configured targets/trails, activation, watermark, current stop, confirmed filled/remaining/pending quantity, monitoring timestamp/errors and cancellation state. Expanded details include planned steps and individual execution records with client/broker IDs and actual average fill prices.

Broker, strategy, status, mode and search filters apply consistently. Completed includes standalone `FILLED` and protection `STOPPED_OUT` orders. Trading pages scope rows to their broker, mode and selected Webull account. The table polls every five seconds, preserves prior resource rows on failed automatic refreshes and labels stale data. The widget polls every fifteen seconds. Light and dark styling uses application theme variables, and narrow screens scroll tables horizontally.

## Upgrade handling

The migration adds nullable engine-version and monitoring fields plus a new execution journal without rewriting old execution history. Newly created strategies use engine version 2. Older active/submitted strategies are held as `NEEDS_REVIEW` instead of being resumed with potentially incorrect saved settings or unverified fills. Older terminal history remains visible with explicitly unverified totals.

For each older strategy, review broker history and open orders first. The old engine did not reliably retain submission IDs or actual fills, so cancelling its local strategy does not establish whether an earlier broker order filled or remains open. Cancel any old broker order through broker order management as needed, then recreate only the intended remaining quantity. The upgrade does not infer a replacement order or send compensating trades.

## Verification

The focused Python suite covers the 18 BUY/SELL × three profit modes × three protection modes, partial fills, live submission/reconciliation, uncertain outcomes, cancellation, paper accounting/rollback, API payloads, 2FA/mode controls, quantity and risk checks, legacy records, market hours, stale quotes and credential redaction. All broker I/O in these tests is mocked. No real-money order is needed for release verification.

```sh
.venv/bin/python -m unittest tests.test_synthetic_order_lifecycle tests.test_max_order_size_and_trailing tests.test_ladder_and_webull_synthetic tests.test_smart_bracket_orders tests.test_webull_paper_trading_service tests.test_webull_service tests.test_webull_event_order_2fa tests.test_webull_scheduled_orders
node --test frontend/src/utils/syntheticOrders.test.mjs
node tests/synthetic_orders.browser.mjs /path/to/installed/playwright
npm --prefix frontend run build
```

The browser harness uses local fixtures in six broker/theme scenarios. It checks filters, precision, editor payloads and side changes, text contrast, automatic refresh failure handling and narrow-screen scrolling. `CHROMIUM_PATH` can select an installed browser. The optional `tests.test_synthetic_postgres_lock` accepts `SYNTHETIC_LOCK_TEST_DATABASE_URI` to test actual PostgreSQL lock exclusion across commits; it uses only SELECT/advisory-lock calls and does not modify tables.

Broker references: [Webull order detail by client ID](https://developer.webull.com/apis/docs/reference/order-detail/), [Webull order-query guidance](https://developer.webull.com/apis/docs/reference/order-query/), and [Binance.US API documentation](https://docs.binance.us/).
