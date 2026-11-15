# Synthetic equity and ETF execution and recovery (v4.16.0)

In Webull Trading → Conditional Orders, select **Synthetic · managed by this app** and choose **Regular Hours** or **Regular + Extended Hours**. Synthetic mode supports OCO, OTO and OTOCO with Limit, Stop Loss or Stop Loss Limit legs, with a shared whole-share quantity. Webull native conditional orders remain available separately for regular hours.

Regular Hours means 9:30 AM–4 PM ET on exchange trading days. Regular + Extended Hours means 4 AM–8 PM ET on trading days, following the exchange holiday/early-close calendar. Creation while closed is allowed; monitoring waits for the selected session. Overnight is unsupported. The app server and worker must remain running. Pre-market and after-hours prices come from Yahoo Finance minute bars and may lag; stale quotes pause monitoring.

## Execution and fills

Entered Limit and Stop Limit prices are preserved. A plain stop or existing bracket/trailing/ladder strategy sends a Market child during regular hours, or a whole-share Limit child in extended hours. Its price cap (default 1%, allowed 0.1%–5%) is measured from the trigger price. A gap does not widen that cap. Every extended-hours ladder step must allocate whole shares.

An unfilled live synthetic Limit child times out after five minutes. Cancellation acknowledgement alone does not establish a final state: the app waits for broker confirmation. A limit price, trigger crossing, or submitted order does not guarantee a fill.

OCO gives the first eligible trigger ownership of the shared quantity. It never fires the other leg while an execution is pending or after the strategy stops. OTO/OTOCO children activate only after a final broker entry status. A fully filled entry activates the children for its full quantity. A partially filled entry whose remainder was cancelled activates children only for the confirmed filled quantity; the unfilled entry quantity is recorded. A zero-fill rejection does not activate children. The position can be unprotected while entry confirmation is pending. Short entries are not opened: live funding and available-position checks run before transmission.

## Persistent history and notifications

Both Orders → Order History and Webull Trading → Order History contain a **Synthetic Strategy History** table. The Webull table covers all Webull accounts in the selected live/paper mode; every row identifies its account. The chart's selected account does not hide another account's strategies.

* **Failed — no shares filled**: a confirmed stopped attempt with no fills.
* **Partially filled — remainder cancelled**: some shares traded and the remainder stopped. Filled trades remain in the account.
* **Partially filled — working / Submitted**: the broker order is still open.
* **Awaiting broker confirmation / Cancellation pending**: the outcome is unresolved; recovery cannot submit another order.
* **Completed / Filled**: confirmed completion of the phase shown. OTO/OTOCO rows identify the current phase, and Details retains entry and exit execution records.

Click a failure status or **Review issue** to open recovery. New failures observed while the app is open also raise a brief, clickable warning toast, deduplicated across tabs in the same browser. Existing failures remain in history after reload or after missing a toast. A temporary unavailable quote and a closed selected session remain monitoring/waiting states rather than falsely claiming a failed broker order.

## Recovery choices

1. **Replace / Retry** opens an editor for the unfilled remainder. Keep the existing strategy or choose OCO, OTO, OTOCO, Limit, Stop, Trailing, or Ladder for eligible Webull stocks/ETFs. Review legs, session and cap before confirmation. A current-strategy ladder restarts its allocation percentages over the remainder; trailing watermarks are retained. Choose another strategy type to configure new targets or a new trail.
2. **Use Regular Hours** creates a new strategy for the unfilled remainder using the saved terms in Regular Hours. Plain stops/legacy strategies use Market execution; entered Limit/Stop Limit prices remain limits. Conditions already met may trigger as soon as monitoring resumes. For failed OTO/OTOCO exits, only the exit phase is re-armed; it never replays the entry.
3. **Keep Cancelled** records that decision and submits nothing. Closing the modal leaves the stopped strategy unchanged.

Live replacement/re-arming requires a fresh authenticator code. Ownership, account, remaining quantity, session and final broker state are checked on the server. The decision and replacement are saved atomically under the parent lock; repeated clicks or requests cannot create a second replacement. The original failure and fills stay in history with the recovery decision and replacement ID. No existing active order is silently switched to another session by this upgrade.

## Upgrade and verification

Startup adds nullable conditional-specification/phase fields to `ladder_orders` and creates `synthetic_recoveries` with a unique per-user/per-strategy decision key. It does not rewrite existing strategy terms. Runtime initialization explicitly verifies both additions.

Verification uses isolated databases and mocked broker calls for sequencing, partial fills, timeouts, session routing, price preservation, ownership, 2FA and idempotent recovery. Browser checks exercise history, all recovery choices, rejected 2FA, clickable warning toasts and light/dark/mobile rendering. No verification test places live trades.

## Dashboard cancellation correction (v4.16.1)

Dashboard cancellations route local `ladder_` / `trail_` identifiers to the synthetic cancellation endpoints before broker routing. The Webull broker cancellation endpoint independently intercepts these identifiers and validates ownership, account, mode and fresh live 2FA. An untriggered strategy cancels locally; a submitted child is reconciled/cancelled using its durable broker identifiers. Pending broker confirmation does not remove the strategy from the dashboard as if cancellation were complete. The confirmation names the synthetic strategy and displays its account, session and saved upper/lower triggers.
