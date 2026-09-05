# Webull Multi-Asset Quantitative Strategy Engine

## Overview & Architecture

The **Webull Multi-Asset Quantitative Strategy Engine** is an enterprise-grade algorithmic research and paper-trading framework designed to manage and evaluate an isolated **$50,000.00 paper bankroll** across 5 distinct asset classes:

1. **Equities & ETFs** (Target: 35% / $17,500.00)
2. **Options Strategies** (Target: 25% / $12,500.00)
3. **Cryptocurrency Spot** (Target: 20% / $10,000.00)
4. **Micro Futures** (Target: 10% / $5,000.00)
5. **Event Contracts** (Target: 10% / $5,000.00)

The target portfolio mandate is **18.5% Net Annual Return** (with an acceptable boundary of 16.5%–21.0% CAGR) with strict mathematical risk bounds, multi-factor cross-asset diversification, and an isolated paper trading ledger completely decoupled from live execution, manual Webull Test Mode, and Binance paper trading.

---

## What Has Been Completed So Far (v2.88.0)

### 1. Database & Persistence Layer
- **`portfolio_algo_models.py`**:
  - `PortfolioStrategyConfig`: Persists user-defined multi-asset allocations, total bankroll, target annual return, custom watchlist JSON arrays, strategy module configuration JSON, Master CIO prompt, and worker status.
  - `PortfolioStrategyAccount`: Dedicated paper bankroll account tracking initial balance ($50,000 baseline), cash balance, total equity, and reset timestamps.
  - `PortfolioStrategyPosition`: Tracks hypothetical positions per asset class, entry price, size, mark price, unrealized P&L, stop loss, and take-profit targets.
  - `PortfolioStrategyOrder`: Tracks hypothetical orders, execution side, fill prices, and order states.
- **`database.py`**: Integrated automatic schema migration and table creation for all 4 quantitative models on app startup.

### 2. Backend REST API
- **`routes/portfolio_algo.py` & `main.py`**:
  - `GET /api/webull/portfolio-algo/config`: Retrieves current allocations, watchlists, module parameters, account balances, and default baseline presets.
  - `POST /api/webull/portfolio-algo/config`: Updates portfolio parameters with strict 100% allocation sum check validation (rejects invalid distributions), watchlist arrays, module settings, and CIO prompts.
  - `POST /api/webull/portfolio-algo/reset-bankroll`: Resets the isolated paper bankroll back to $50,000.00 (or custom balance) and wipes quantitative test positions/orders without touching live or manual test accounts.
  - `GET /api/webull/portfolio-algo/status`: Telemetry endpoint reporting worker status, cash, total equity, unrealized P&L, watchlist counts, and open positions.
  - `POST /api/webull/portfolio-algo/master-audit`: Invokes the Master Chief Investment Officer (CIO) AI audit matrix evaluating cross-asset correlation, risk dispersion, target return feasibility, and strategic rebalancing directives.
  - Restricted strictly to system administrators via `@portfolio_admin_required`.

### 3. Frontend Dashboard & UI/UX
- **Settings Tab Upgrade (`frontend/src/pages/Settings.jsx`)**:
  - Replaced the administrative tab with **`🏛️ Quantitative Strategy Engine`** (gated strictly to `isEventStrategyAdmin`).
- **Master Ribbon (`QuantitativeStrategyEngine.jsx` & `QuantitativeStrategyEngine.css`)**:
  - Glassmorphic header card with Paper Mode and Isolated Ledger safety badges.
  - **Metrics Row**: Total Paper Bankroll ($50,000.00), Target Net Annual Return (18.5% with interactive 10%–35% slider), and Capital Allocation Sum Check (validates 100% compliance).
  - **Dynamic 5-Slice Color-Coded Bar**: Color-coded progress bar reflecting the exact distribution of capital across the 5 asset classes (Equities: Blue, Options: Violet, Crypto: Amber, Futures: Emerald, Events: Rose).
  - **Master Action Buttons**: `[ 🤖 Master Portfolio AI Audit ]`, `🔄 Reset Bankroll`, and `💾 Save Allocations & Watchlists`.
- **5 Asset Module Cards**:
  - **Equities & ETFs**: Dual-Momentum Rotation & 2-Period RSI with 200 SMA filter. Watchlist: `SPY`, `QQQ`, `IWM`, `SMH`, `XLK`, `NVDA`, `AAPL`, `MSFT`, `AMZN`, `TSLA`.
  - **Options Strategies**: Volatility Risk Premium 45-DTE Credit Spreads (IVR ≥ 40, Delta 18, 45 DTE, 50% profit target). Watchlist: `SPY`, `QQQ`, `IWM`, `NVDA`, `TSLA`.
  - **Cryptocurrency Spot**: Adaptive Donchian Breakout & ATR Stops (20/10 channel breakout with 2.5× ATR trailing stop). Watchlist: `BTC`, `ETH`, `SOL`.
  - **Micro Futures**: 15-minute Opening Range Breakout (ORB) and VWAP mean reversion with strict $250 max daily loss ceiling. Watchlist: `MES`, `MNQ`, `MGC`, `MCL`.
  - **Event Contracts**: Binary Probability & Velocity Arbitrage capturing 15-minute and hourly contracts with 1.5% net edge floor. Watchlist: `KXBTC15M`, `KXBTCD`, `KXETH15M`, `KXINXD`.
  - **Watchlist Chip Management**: Direct on-card interactive chips with removal buttons (`×`) and inline "+ Add ticker" inputs.
  - **Allocation Weight Sliders**: Sliders on each card allowing real-time capital recalculation.

### 4. Dedicated ⚙️ Gear Modals
- **Event Contracts Modal**:
  - Clicking the **⚙️ Gear Icon** on the Event Contracts card opens the complete administrative controls: `Save settings`, `Start`, `Stop`, `Scan now`, `View logs`, `View Report`, `AI Configuration`, and `Kill switch`.
  - Full telemetry: Worker status, scan cadence, heartbeat, AI evaluation status pills (`SUCCESS`, `SKIPPED`, `INVALID`, etc.).
  - Research scope, durations checkboxes, collection & AI frequencies, and per-duration AI cooldowns.
  - Embedded sub-modals for logs, AI reports, and 3-tier cascade configuration. 100% of previous controls preserved.
- **Equities, Options, Crypto, and Futures Modals**:
  - Parameter tuning (SMA periods, RSI thresholds, IVR thresholds, delta targets, channel periods, ATR multipliers, ORB window, loss ceilings).
  - Domain-Specialist AI System Prompts with 1-click reset to default.

### 5. Master Portfolio AI Audit & Bankroll Reset
- **Master Portfolio AI Audit Modal**:
  - Editable Chief Investment Officer mandate prompt with reset-to-default capability.
  - Execution button returning structured cross-asset correlation analysis (Pearson r ≈ 0.32), stress drawdown assessment (-8.4% max drawdown budget), and actionable rebalancing recommendations.
- **Bankroll Reset Modal**:
  - Modal with safety confirmation to reset the isolated quantitative ledger to $50,000.00 (or custom balance) without affecting manual Webull Test Mode or Binance paper trading.

---

## What Is Left Remaining

The foundation, models, APIs, administrative interface, and Event Contract strategy worker are fully operational. The remaining roadmap focuses on activating automated background execution workers for the other 4 asset modules:

### 1. Autonomous Strategy Execution Workers
- **Equities & ETFs Worker**:
  - Implement a scheduled background worker that triggers during US Regular Trading Hours (RTH: 9:30 AM – 4:00 PM ET).
  - Ingest daily and intraday candles for the equity watchlist (`SPY`, `QQQ`, `IWM`, `SMH`, `XLK`, `NVDA`, `AAPL`, `MSFT`, `AMZN`, `TSLA`).
  - Calculate 200-day SMA trend alignment, sector relative strength, and 2-period RSI oversold pullbacks (< 10).
  - Execute paper entries and exits into `PortfolioStrategyPosition` and `PortfolioStrategyOrder` within the 35% ($17,500) capital bucket.
- **Options Volatility Worker**:
  - Ingest Webull options chain data for high-IV symbols (`SPY`, `QQQ`, `IWM`, `NVDA`, `TSLA`).
  - Identify expiration cycles closest to 45 DTE when symbol IV Rank (IVR) ≥ 40.
  - Locate 18-delta out-of-the-money credit spreads (bull put or bear call).
  - Simulate entry credit collection and register automated 50% profit-taking GTC exit rules in `PortfolioStrategyOrder`.
- **Cryptocurrency Spot Worker**:
  - 24/7 background worker monitoring `BTC`, `ETH`, and `SOL`.
  - Calculate 20-period and 10-period Donchian Channels alongside Average True Range (ATR).
  - Execute simulated breakout entries with dynamic 2.5× ATR trailing stops and Bitcoin dominance regime filtering.
- **Micro Futures Worker**:
  - Intraday worker active around the 9:30 AM ET market open.
  - Calculate the 15-minute Opening Range (High/Low between 9:30 and 9:45 AM ET) on `MES` (Micro S&P) and `MNQ` (Micro Nasdaq).
  - Generate paper breakout entries with strict VWAP filters and enforce the $250.00 maximum daily loss ceiling.

### 2. Unified Position & Performance Telemetry
- **Combined Equity Curve**:
  - Time-series tracking of total portfolio equity, cash, and unrealized/realized P&L across all 5 asset modules.
  - Performance metrics: Blended Annualized Return, Sharpe Ratio, Sortino Ratio, Win Rate, and Maximum Peak-to-Trough Drawdown.
- **Positions Overview Table**:
  - Add a dedicated "Open Positions" sub-panel on the Quantitative Strategy Engine dashboard displaying active simulated positions across Equities, Options, Crypto, Futures, and Event Contracts.

### 3. Automated Capital Rebalancing Engine
- **Drift Detection & Rebalancing**:
  - Compare actual position weights against target allocations (35% / 25% / 20% / 10% / 10%).
  - If any asset class drifts by more than ±3.0% due to market movements, generate rebalancing signals to trim outperforming classes and reallocate capital to underweight modules.

### 4. Scheduled Autonomous Master Portfolio AI Auditing
- **Automated Cadence**:
  - Schedule the Master Portfolio AI Audit to run autonomously on a recurring schedule (e.g., daily at market close or weekly).
  - Maintain a historical audit archive allowing administrators to review past CIO verdicts, correlation trends, and risk warnings over time.

### 5. Master Portfolio Circuit Breakers & Kill Switch
- **Global Portfolio Circuit Breaker**:
  - If total paper drawdown exceeds 10% of starting bankroll (e.g., portfolio drops below $45,000), trigger an autonomous engine-wide pause, liquidating or freezing simulated positions and notifying the administrator via Telegram/system toast.
