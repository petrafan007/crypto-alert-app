# Quantitative Strategy Engine (v2.91.0) - Administrator Documentation

The Quantitative Strategy Engine is a robust, paper-ledger simulation system designed to test and validate multi-asset trading algorithms. This engine allows you to allocate virtual equity across five distinct asset modules, run deterministic algorithms to simulate entries and exits, and synthesize those outcomes via a 3-Tier localized AI architecture governed by a Master CIO agent.

This documentation serves as an administrator's guide to the end-to-end workflow, background behaviors, and module setups.

---

## 1. Core Architecture and Data Flow

The Quantitative Strategy Engine operates on a scheduled, background execution pipeline rather than executing in real-time alongside front-end requests. This ensures continuous, uninterrupted monitoring of market conditions.

1. **Market Data Ingestion:** Background workers (`run_scan` in `services/portfolio_engine.py`) wake up on intervals to fetch standardized OHLCV (Open, High, Low, Close, Volume) data for all assets tracked in your selected modules.
2. **Algorithmic Evaluation:** The engine passes the ingested market data through purely deterministic, math-driven algorithms (`services/portfolio_strategy_signals.py`). No AI models are involved in this direct signaling phase.
3. **Ledger Execution:** If an algorithm triggers an entry or exit signal based on your predefined settings (e.g., RSI thresholds, ATR multipliers), the engine manages the paper ledger—updating your positions, recording P&L, and subtracting estimated slippage and fees.
4. **AI Synthesis (Autonomous Audit):** On your defined `Audit Interval (Hours)`, the system takes a snapshot of the portfolio's current state and initiates the AI evaluation cascade:
   - **Localized AI Agents:** The engine spins up independent AI agents for each active module (Equities, Options, Crypto, Futures, Events). Each agent receives isolated data specific to its module and uses its distinct `auditor_prompt`.
   - **Master CIO Synthesis:** Once all localized agents have responded, the Master CIO receives their insights, alongside overarching metrics like total equity, cash allocation, and cross-module correlations, to generate the final autonomous portfolio report.
5. **System Logging:** Every scan start/stop, executed lot, and AI evaluation is logged to the database and can be reviewed via the **View Logs** modal in the UI.

---

## 2. Module Configuration and Algorithms

The engine supports five distinct asset modules, each utilizing its own mathematical strategy. You must allocate your target equity percentage (e.g., 20% to Crypto) and configure the specific strategy parameters.

### Equities
- **Strategy:** Mean-reversion and relative momentum. 
- **Mechanics:** Buys when the asset is above a long-term SMA, showing positive relative momentum against a benchmark, but temporarily pulling back (low RSI). Exits when momentum breaks or RSI becomes overbought.
- **Key Settings:** `trend_sma_days`, `rsi_period`, `rsi_entry_threshold`.

### Options
- **Strategy:** Premium collection via defined-risk OTM credit spreads.
- **Mechanics:** Scans live option chains for short legs at a specific Delta and long legs providing defined width. Evaluates Implied Volatility Rank (IVR) and only engages when IVR is high.
- **Key Settings:** `target_delta` (e.g., 16 Delta), `target_dte` (Days to Expiration, e.g., 45 days), `min_ivr`.

### Crypto
- **Strategy:** Donchian Channel breakout with regime filtering.
- **Mechanics:** A trend-following system that buys when an asset breaks above its recent high channel and exits when it breaks below its low channel. It uses ATR (Average True Range) for trailing stops.
- **Key Settings:** `entry_channel_periods`, `exit_channel_periods`, `atr_stop_multiplier`.

### Futures
- **Strategy:** Opening range breakout with directional VWAP confirmation.
- **Mechanics:** Identifies the high and low of the initial opening range (e.g., first 15 minutes of the session). Enters a position only if the price breaks the range and is confirmed by trading on the correct side of the Volume-Weighted Average Price (VWAP).
- **Key Settings:** `opening_range_minutes`.

### Event Contracts
- **Strategy:** Mean-reversion around binary outcome probabilities.
- **Mechanics:** Capitalizes on overreactions in event markets by entering when contract probabilities deviate significantly from mathematical baselines.
- **Key Settings:** `probability_threshold`.

---

## 3. The 3-Tier AI Integration and Failover

The engine ensures high availability for autonomous reporting by utilizing a localized 3-Tier AI Failover system. This is configured in the **Master AI Configuration** modal.

### Setting Up Tiers
You can assign different models and providers to three distinct tiers:
- **Primary:** Your fastest or most capable model (e.g., `gemini-3.8-flash`).
- **Secondary:** A reliable backup (e.g., `gpt-4o`).
- **Tertiary:** A robust local fallback (e.g., Ollama `qwen2.5:14b`).

### Execution Logic
When the `Audit Interval (Hours)` triggers the autonomous audit:
1. The engine attempts to call the **Primary** model for the Localized Equities Agent.
2. If the Primary model fails (e.g., API timeout or rate limit), the engine automatically fails over to the **Secondary** model, and then the **Tertiary** model.
3. This 3-Tier failover applies individually to *every* module's localized agent, and finally to the Master CIO's synthesis step.

---

## 4. Administrative Safeguards

The engine runs autonomously, but it includes built-in safeguards to prevent catastrophic runaway behavior in the simulation.

- **Global Circuit Breaker:** The system monitors your `Total Portfolio Equity`. If the simulation experiences a rapid drawdown exceeding 10% of the peak equity, the engine triggers an automatic `kill_switch`. All future entries are blocked until an administrator manually intervenes and resets the engine.
- **Stall Detection (Lease Tokens):** Background workers acquire a lease token in the database (`lease_until`). If a worker stalls (e.g., server crash), the token expires after 10 minutes, allowing a healthy worker process to safely resume operations without causing duplicate entries.
- **Rate-Limited API Queries:** The market data ingestion is deliberately paced to avoid breaching exchange API limits, using cached session bounds to prevent querying closed markets.

---

## 5. Reviewing Operations (Logs and UI)

To monitor the health of the engine:
1. Navigate to the **Quant Strategy Dashboard**.
2. Click **View Logs**.
3. You will see detailed, chronological `PortfolioEngineLog` entries including:
   - `SCAN_START` / `SCAN_COMPLETE`: Proves the background worker is actively evaluating data.
   - `POSITION_OPENED` / `POSITION_CLOSED`: Provides algorithmic reasons and executed prices for ledger adjustments.
   - `AUDIT_START` / `AUDIT_MODULE` / `AUDIT_MASTER`: Details the AI cascade when the Master CIO is synthesizing its report.

By understanding the deterministic foundation of the strategies, paired with the sophisticated autonomous AI reporting, administrators can safely deploy and validate multi-asset portfolios in a risk-free environment.
