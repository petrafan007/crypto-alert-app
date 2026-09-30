# Quantitative Strategy Engine v4.5.0

This describes the historical v4.5.0 behavior. The current v4.6.0 policy and schedule are documented in [quant_strategy_v4.6.0.md](quant_strategy_v4.6.0.md).

The quantitative engine makes and grades **paper** decisions. Its saved annual target is 18.5%; that is a research objective, not a trade quota or return promise. The app still owns quote validation, allocation, sizing, fees, stops, Event settlement, and the fixed risk policies. Neither the independent strategy service nor the AI review can place a live order.

## Why the old engine went quiet

The Master cadence supported Off, Daily, and Weekly, while the separate Event reporting setting was six hours. The saved Master setting was Off. Equities required positive 200-day trend, positive absolute and SPY-relative 63-day momentum, an oversold two-day RSI, and a close below the lower Bollinger band at the same instant. Options required 252 compatible observed near-close IV sessions; the daily backfill job failed when unrelated archived Event and crypto records pushed its broad dataset over 100,000 rows. Event fills are still constrained by the saved lifetime-drawdown policy, which the AI cannot change.

## Paper decision flow

1. The app obtains completed market bars and fresh quotes, computes bounded indicators, and checks the configured watchlist and session.
2. A separate service under a restricted system account reads its active pure Python `decide(f)` source. It receives credential-free features over a group-protected Unix socket and returns an entry/no-trade proposal, reason, version, and code hash.
3. The app checks the exact proposal scope, ownership, signal age, paper mode, allocation, live quote, spread depth, maximum loss, fees, duplicate symbol and circuit. It records the proposed and final disposition in `portfolio_signal_decisions`. No-trade and data/service failures are retained.
4. Existing positions remain under app-owned exits, stops, and settlement, including when the strategy service is unavailable. Closed paper lots are graded after recorded costs. The UI shows wins, losses, breakevens, net dollars, capital used, and the measured 18.5% target path. SPY price-only and cash comparisons appear only when matching archived SPY closes exist.

Equity rotation selects up to two watched symbols ranked by completed 63-session momentum relative to SPY, subject to positive long-term trend. A separate long-trend RSI/Bollinger pullback may also qualify. A fresh in-session quote and paper controls are required for the fill. No trade count is forced.

Options initially use at least 61 completed underlying daily bars, 20/60-session realized volatility, a fresh ATM IV/underlying snapshot, a trend-aligned out-of-money defined-risk credit spread, two-sided fresh legs, reported depth and provider Greeks. **Zero future options-history days** are needed for this clearly labeled current-chain fallback. A short IV percentile requires **30 verified NYSE sessions per underlying**; annual IV rank requires **252 compatible verified sessions**. Gaps extend the calendar wait. Historical option OHLCV bars from [Webull’s documented option bars endpoint](https://developer.webull.com/apis/docs/reference/option-historical-bars/), when this connection permits access, are retained as a separate source and never stand in for historical bid/ask, IV, or Greeks.

The near-close IV job now processes each watched underlying separately, reading only its narrow-date option catalog/quotes and underlying quotes within the requested close window. Broad 1,095-day catalog pages remain in the raw archive but are excluded from this bounded IV job. Its completeness check respects early NYSE closes and records valid/invalid coverage per underlying. No paid data endpoint is enabled. The archive displays cap headroom and recent growth; existing raw captures are preserved.

Crypto keeps its completed-hour Donchian/dominance entry and ATR risk baseline. Event forecast production and its final market/risk checks remain in the app; the separate service gates only newly qualified paper entries. An exhausted Event drawdown allowance is shown as `RISK_BLOCKED`; changing that saved policy is an administrator decision.

## Daily AI source review

At 00:30 Eastern each calendar day, the singleton worker saves one review per enabled administrator. It supplies the four exact active source files, bounded decision counts, closed paper outcomes, the 18.5% target, and explicit data gaps to the configured AI cascade. Credential values are never included. The saved daily request ceiling is one to three provider attempts (default one); actual provider charge is displayed as unknown when the provider does not report it. No new market-data purchases are made.

The AI can return a complete pure `decide(f)` proposal for one module or `NO_CHANGE`. A proposed file passes an AST allowlist, deterministic repeated fixture evaluations, a 256 KiB protocol limit, and a restricted subprocess with CPU, memory, file-size and timeout ceilings. It is kept in an immutable version directory outside either app checkout. It starts in **SHADOW**. Promotion needs at least 30 *future* observation days and 20 closed paper fills after the proposal, no unobserved new-entry flips in the sampled holdout, at least half of baseline trades retained, a better net-P&L-minus-drawdown score, no worse drawdown, and no risk breach. A module accepts at most one revision per day. Three consecutive rule evaluation failures trigger an atomic return to the previous version. The administrator-only revision endpoint shows source diffs and offers rollback.

This is a conservative forward filter test. It cannot credit counterfactual fills the paper ledger never took. An AI recommendation, unit test or positive short run is not evidence of profitability. An active baseline remains until a candidate genuinely passes future outcome gates; daily source review does not imply daily code changes.

## Deployment

The released app integrates with `/run/crypto-quant-strategy/strategy.sock`. Install the `strategy_service` package at `/opt/crypto-quant-strategy`, create the `crypto-quant` system account with the app user's group for socket access, install `strategy_service/crypto-quant-strategy.service` as a system unit, and start it before the app worker. The service stores versioned rules and atomic active pointers in `/var/lib/crypto-quant-strategy`; this directory is writable only by the restricted service account. Its systemd sandbox disallows network addresses, broker credentials, home-directory access, and app-checkout writes. The app worker stays on its own account and communicates only through the Unix socket.

Run additive `runtime.py init-db` before starting the app and worker. Save the Master cadence as `six_hours` on the personal instance; the Event schedule is separate. Increase the existing research archive cap only after checking free disk and recent collection growth. Never wipe prior paper fills to make a strategy appear profitable.

## Verification and limits

The v4.5.0 focused suites cover signal separation, option fallback labels, source validation/activation/rollback, PostgreSQL paper-ledger accounting, Event handoff/settlement and point-in-time research replay. The production frontend build and Python compilation are release gates. Historical options bars have no historical bid/ask or Greeks. Provider denials remain visible; a subscription is never purchased automatically. The first new equity or options paper trade still depends on market conditions, data availability, quote quality and the unchanged risk controls.
