# v2.94.0 behavior and verification

## Asset performance and table layout

ETH ETF and Ethereum share a ticker but represent different instruments. Previously, a Webull ETF mark around $23 was compared with Binance ETH history around $2,500, producing a false loss near 99%. Equity backfills now use unadjusted regular-session Yahoo Finance bars, stored under a separate market identity. Crypto history, including history supplied to sentiment prompts, remains Binance-scoped. No other user's Webull credentials are used to seed history.

The performance panel reports period changes; Portfolio reports profit/loss against the holding's cost basis. These percentages need not match. Equity periods retain the existing trading-session convention: 1D compares previous session close, 3D compares three sessions earlier, 7D compares five sessions earlier, 12H compares the first completed bar of the latest session, and 1H compares the prior completed bar. Incomplete history shows a missing value. The tooltip includes the price timestamp. Completed-session values remain stable while the exchange is closed.

Portfolio and Watchlist have a centered Type column. Account/type pills have moved out of Symbol. Existing saved layouts gain Type without resetting the other columns; the Positions layouts from v2.93.0 remain available in every trading mode and `/orders`.

## Paper options and history

An unfilled option instruction belongs in Open Orders. A filled contract belongs in Positions, and its original instruction remains in Order History. These views can legitimately contain entries for the same contract when a closing instruction is still working.

The paper lifecycle runs every minute in the background worker and when paper summaries, orders, or positions are read. DAY instructions expire at their applicable exchange-session close, accounting for weekends and holidays. Expired option instructions cannot fill. Working single-leg option MARKET/LIMIT buys and sells fill only during a regular session against an observed matching-contract ask/bid and a marketable limit. Unsupported conditional or multi-leg triggers are not reconstructed as historical fills. Quote availability still depends on the connected data sources.

Expired paper option holdings use an explicit **cash settlement at intrinsic value** policy: the underlying's unadjusted closing price for the expiration session determines the payment. This is a simulation policy, not physical exercise/assignment by a broker. A settlement ledger entry records its effective date, observed underlying close, and cash adjustment; it is not represented as a filled trade. The holding is retained with zero quantity and removed from open-position views. If the closing price is unavailable, the position says it is expired and awaiting settlement instead of Open.

Original historical fills are preserved. Older off-session fills are labeled as legacy simulator activity rather than verified market executions. The arbitrary $2.50 option execution fallback has been removed; unavailable current marks are identified in position details. Order History includes all saved test records and actual fill timestamps.

## Staking

The page renders while independent panels refresh. It no longer waits for `/api/coin-data`. Successful staking catalog reads are cached for two minutes; balance/history reads for fifteen seconds. Concurrent identical reads share a request; writes invalidate the cache. Signed requests use matching trading key/secret pairs when requested.

Recommended Coins to Stake ranks five distinct assets by their currently returned rate. It labels APY/APR and shows product minimums and unstaking periods. This is a yield ranking, not a prediction of investment performance. Binance.US returns numeric APR/APY as fractions, and exposes asset limits and the staking submission endpoint in its [official API documentation](https://docs.binance.us/).

Trade is available for supported USD/USDT markets when the relevant free balance exceeds $1. The modal confirms a real market purchase, optionally followed by staking the purchased quantity after base-asset fees. The existing real-mode and 2FA settings apply. Exchange minimums, the user's order-size limit, live free balances, a 1% fee buffer, and staking minimum/maximum amounts are checked. Auto-restaking is an explicit choice; APY assumes compounding. Acceptance of staking does not mean rewards start immediately.

Each purchase has a durable, account-scoped receipt. Replaying its request never places another buy or stake. A successful purchase followed by rejected staking leaves the purchased coins available and reports the partial result. Uncertain submissions are never automatically retried: refresh the receipt and inspect Binance order/staking history before submitting another transaction. Receipt refresh reads stored confirmation; it does not automatically reconcile an exchange timeout. The most recent receipt can be reopened in the same browser tab/session. Filled buys also appear in real Order History, and accepted stakes are recorded as pending until exchange balance/history data confirms them.

## Sentiment accuracy audit

The production schema stored prediction/evaluation timestamps with time zones and target timestamps without one. Passing an aware UTC target to the latter caused PostgreSQL's New York session to shift it four hours earlier in summer. Evaluation could therefore occur before the intended forecast horizon, occasionally even before the prediction.

New targets explicitly store UTC without an offset in the target column. Existing fixed-horizon targets are checked against prediction time plus recorded horizon. Incorrect targets retain their original target/outcome evidence under `_timestamp_repair_v2940` in the saved grading configuration before their grades are reset and reevaluated. No prediction records are deleted. Evaluation requires a valid same-market price observation within fifteen minutes of the target, after the prediction and no later than the current time. Missing historical evidence is shown as unscored.

The headline is now Directional Win Rate, separate from Hold Accuracy. All cards use the selected asset/date scope and display correct, decisive, neutral, pending, and unscored counts. A 100% Hold result is not evidence of bullish/bearish predictive skill. Legacy next-check grades remain visible in history but are excluded from fixed-horizon headline metrics. Small samples are identified explicitly.

## Verification

Regression tests cover ticker identity separation, UTC repair/idempotence, invalid evaluation timestamps, option calendar expiry and one-time settlement, marketable paper fills, staking key selection/cache invalidation, monetary minimums, replay protection, and partial purchase/stake failure. A separate PostgreSQL test reproduces the actual New York timestamp coercion. Browser fixtures cover independent staking rendering, recommendations, receipt persistence, Type alignment, and Webull mode switching. Existing Positions browser checks cover real/test/quant views, `/orders`, column drag/reorder, account isolation, and mobile layouts. Exchange writes are mocked in every test.

Deployment adds the `staking_purchases` table through `runtime.py init-db`; restart both the web service and background worker. The worker performs the audited timestamp repair and paper lifecycle reconciliation. Existing database records are preserved.
