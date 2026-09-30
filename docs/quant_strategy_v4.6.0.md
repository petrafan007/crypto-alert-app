# Quantitative Strategy Engine v4.6.0

The engine remains **paper-only**. The 18.5% annual return target is a research objective, not a promised result or a required trade count. This release keeps evaluating opportunities after losses, records the outcomes, and schedules one useful portfolio report check per NYSE trading day.

## Paper decisions and risk

Event `max_hourly_loss`, `max_daily_loss`, and `max_drawdown` values remain in historical saved settings and evidence for compatibility, but no longer reduce entry allowance or cause a loss-only `RISK_BLOCKED` state. The observed Event high-water drawdown continues to be calculated. The portfolio 10% starting-bankroll circuit is retired; a persisted pause with exactly that old automatic reason is cleared on normal initialization. A manual kill switch remains binding. Futures daily aggregate P&L no longer forces a close or blocks a new paper entry.

Each new paper position still requires sufficient cash and module budget, a bounded per-trade risk amount, exposure and position limits, a fresh executable quote, fees and depth checks, and duplicate-signal protection. Event entries still obey saved dollars per trade, dollars and positions open, contract count, spread, volume and cutoff limits. This release does not reset a paper generation, erase historical fills, or create live brokerage orders. A category can still have zero fills when no qualified setup or affordable trade exists; its decisions and reasons remain observable.

## Reporting

The scheduler checks at **5:00 p.m. America/New_York on each NYSE trading day**, including early-close sessions. It uses the NYSE calendar for holidays and Eastern daylight saving time. There is no weekend scheduled portfolio report. Weekend crypto and Event outcomes remain in the ledger and can appear in Monday's comparison. The independent Event settlement worker continues; its former interval-based AI report worker is retired. Historical Event reports remain archived, and Event evidence is included in the Master portfolio report.

The scheduled check first verifies a portfolio scan in the preceding 15 minutes. If the worker is stale, it saves a `DATA_STALE` result and makes no AI call. If fills, closed outcomes, stable rejected-decision reasons, module health, manual control state, and strategy revisions have not materially changed since the prior report, it saves `NO_CHANGE` with no AI call. Routine quote-number changes do not by themselves cause AI analysis. Otherwise it captures timestamped portfolio evidence and runs the configured specialist/Master AI cascade. A manual Master audit remains available and is separate from the scheduled check. Provider failures retain measured evidence and an explicit failed status.

Both interval controls have been removed from the user interface. New Master config writes reject cadence values and retire a saved cadence key on the next save. Legacy database interval columns are retained for schema compatibility but no longer launch scheduled reports.

## Daily strategy review and paper experiments

The daily review runs at or after **5:30 p.m. Eastern** on each calendar day. It saves exact source hashes, recent decisions and closed paper outcomes. When no qualified decision or closed trade has changed since the prior completed review, it records `NO_CHANGE` without an AI call. A failed provider attempt can retry after 15 minutes within the saved daily request ceiling of one to three actual attempts; a completed review is not repeated that day.

An AI proposal is a complete replacement of one module's restricted `decide(f)` entry rule. The separate strategy service validates its syntax, deterministic fixture behavior and resource limits, then stores an immutable version outside the dashboard checkout. A candidate stays in `SHADOW` until at least the next Eastern calendar day supplies a forward decision that the candidate actually changes. A candidate that tries to enter through a recorded per-trade risk hold is rejected. A validated candidate can then activate as a clearly labeled **paper experiment**; proposed new entries have no invented counterfactual P&L. App-owned quote, position, cash and risk controls still decide whether a paper fill is allowed. At most one revision per module can activate on a UTC day. Three consecutive restricted rule failures restore the previous source. If the first five or more closed trades under the experiment have negative net P&L and at most one winner, the review requests an atomic rollback to the previous rule; ordinary baseline trading continues.

Paper experiments may lose money. Five outcomes are a rollback trigger for further testing, not statistical proof that a rule is good or bad. AI suggestions, one-day reports and the 18.5% target must not be reported as validated profitability. A category with no future decisions cannot be promoted merely because the AI wrote code.

## Verification and deployment

Focused v4.6.0 tests cover Event loss-versus-exposure behavior, NYSE 5 p.m. scheduling and daylight saving/early-close boundaries, no-change report fingerprints, provider retry accounting and paper experiment activation. Python compilation, frontend build and `git diff --check` are release gates. The released service source must be installed for the separate `crypto-quant-strategy.service` before the app worker is restarted. After deployment, verify the three services, the local dashboard endpoint, current report health, source/service version, and that the existing paper ledger is intact. The first natural 5 p.m. check and 5:30 p.m. review must be observed before claiming their production outcomes.
