# Crypto Alert App

**Crypto Alert App** is a comprehensive, non-custodial cryptocurrency portfolio management and trading platform designed exclusively for Binance.US. It provides users with real-time portfolio tracking, automated price alerts, one-click trading, built-in staking management, and AI-powered market sentiment analysis. 

**Last Updated**: August 2026

## 🚀 Key Features & Capabilities

- **📊 Real-Time Portfolio & Watchlist Tracking**
  - **Live Binance.US Sync**: Real-time balance and transaction history synchronization with Binance.US.
  - **Interactive Customizable Dashboard Grid**: Modern drag-and-drop (`⠿`) reordering, multi-handle resizing, and custom panel visibility for all upper dashboard widgets.
  - **Market Gauges & Performance**: Built-in Fear & Greed Index, CBBI Bull Run Peak Confidence metric, Staking Yield overview, and 7-day multi-interval performance tickers.
  - **True Portfolio Trend Charts**: Multi-timeframe portfolio net worth graphs (1D, 7D, 30D, 1Y, All-time) with live updates.
  - **Cryptocurrency Vector Icons**: Rich, high-resolution coin icons for effortless asset recognition across all tables.

- **⚡ Professional Trading Terminal (USD & USDT)**
  - **Dual-Quote Currency Trading**: Instant one-click spot trading for both **USD** and **USDT** quote pairs directly from Portfolio and Watchlist rows.
  - **Advanced Order Execution**: Support for Market Orders, Limit Orders, Stop-Loss Limit, and OCO (One-Cancels-the-Other) protective orders.
  - **Searchable Pair Selector**: Real-time typeahead search across all 54+ active Binance.US USD pairs and 200+ USDT pairs.
  - **High-Performance TradingView Charts**: Lightweight Charts engine with candlestick series, volume histogram, technical indicators (MA7, MA25, MA99, Bollinger Bands, RSI, MACD, Stochastic, ATR), and exact-price buy/sell execution markers.
  - **Paginated Order History**: Independent order history tab with 20-row pagination and symbol filtering.

- **🛡️ Autonomous Crash Protection & Volatility Auto-Sell**
  - **Executive Volatility Auto-Sell**: Set custom 1-hour drop thresholds (e.g. >5%) per coin. If a market dump occurs, the background daemon automatically executes a market sell into USDT to protect capital.
  - **Pre-Execution Conflict Resolution**: Automatically scans and cancels conflicting open orders (limit/stop-loss) to unlock 100% of your coin's balance before placing emergency sales.
  - **Granular Price & Volatility Alerts**: Automated 24/7 background monitors with instant multi-channel push alerts via Telegram and desktop notifications.

- **🤖 AI Market Copilot & Automated Sentiment Analysis**
  - **Multi-Provider AI Intelligence**: Seamless integration with **OpenAI (GPT-4o, o1, o3-mini)**, **Google Gemini**, **Z.AI**, and **Perplexity**.
  - **Live Web-Grounded Analysis**: Automated sentiment analysis and market outlook generation powered by real-time web search (Brave Search / DuckDuckGo).
  - **Interactive AI Copilot Sidebar**: Context-aware crypto strategist that analyzes your active portfolio holdings, pending orders, and recent market movements to deliver tailored trading intelligence.
  - **Historical Prediction Ledger**: Transparent performance tracking that evaluates and scores AI recommendation accuracy over time.

- **💰 Native Binance.US Staking & Yield Management**
  - **Staking Hub**: Monitor and manage staking positions for all supported proof-of-stake cryptocurrencies directly in-app.
  - **One-Click Stake & Unstake**: Effortlessly deposit into or redeem from staking positions.
  - **Daily Reward Tracking**: Real-time tracking of today's rewards, average APY, active staked amounts, and pending releases.

- **📑 Tax Reporting & Complete Activity Ledger**
  - **Capital Gains & Losses**: Automated tax summary computation with custom tax-year filtering.
  - **Unified Transaction Log**: Complete audit trail logging every buy, sell, deposit, withdrawal, staking reward, and fee.

- **🔐 Non-Custodial Security Architecture**
  - **Local AES-256 Credential Encryption**: API keys and secrets are securely encrypted at rest.
  - **Optional 2FA Protection**: Add two-factor authentication security for all trade execution endpoints.
  - **Self-Hosted Privacy**: Your keys, trades, and portfolio data stay completely under your control on your private server.

## 🚨 CRITICAL DEVELOPMENT RULE ⚠️
**ANYTIME you make changes to the code (Python backend), you MUST rebuild/restart the service for changes to take effect!**
```bash
sudo systemctl restart crypto-dashboard.service
```
**Per verification rules, you must confirm the service is healthy (Active: running) and the app is reachable after every restart.**

## Architecture & Database

The application utilizes a **unified PostgreSQL database**.

### Database Schema Overview:
- **Unified PostgreSQL Database**: All tables (`coins`, `credentials`, `exchange_logs`, etc.) are in the `cryptoalertapp` database.
- **Models Location**: 
  - `models.py`: Coin, WatchlistCoin, Notification, StakedCoin, StakingReward, AIPrompt, DefaultAIPrompt, AIConversation, AICache, AIAnalysisSchedule, PriceHistory
  - `credentials.py`: User, Credential, UserSetting, DesktopToken, CredentialEncryptionKey
  - `trading_models.py`: TestOrder, RealOrder, TradingSettings, AllActivity, PortfolioValueHistory, StakingOrder
- **PostgreSQL Connection**: `postgresql:///cryptoalertapp?host=/var/run/postgresql&port=5433`

### 🚨 CRITICAL RULES FOR DATABASE ACCESS:
1. **NEVER** use `sqlite3.connect()` - ALL database access MUST use SQLAlchemy ORM
2. **NEVER** use raw SQL queries - Use ORM query methods (`.query.filter()`, `.filter_by()`, etc.)
3. **ALWAYS** use `db.session.add()`, `db.session.commit()`, `db.session.rollback()` for writes
4. **ALWAYS** handle exceptions with `db.session.rollback()` in except blocks

## Binance.US API Key Consolidation
- **Architecture**: A single **"Binance.US API Key and Secret"** is used for ALL operations (Portfolio Sync, Price Tracking, Trading, Staking).
- **Implementation**: `binance_us_api_call` uses `api_key` regardless of flag. **Binance.US Client** MUST be initialized with `tld='us'`.

## Trigger Logic & Portfolio Sync
1. **Background Jobs**: Every 30 seconds, background jobs check all coins/watchlist entries for each user.
2. **Price Fetch**: If `alert_enabled=True` and coin is not hidden, fetch latest price from Binance.US (`tld='us'`).
3. **Alerts**: Calculate up/down thresholds based on user settings. If price crosses below/above threshold, trigger Telegram/Desktop notification.
4. **Sync**: Balances are synced from Binance.US every 30 minutes.
5. **Visibility**: `get_portfolio_data_for_user` includes any coin with USD value ≥ $1.00 OR if it's manually unhidden (`hidden=False`) OR if `force_visible=True`.
6. **Auto-Hide**: Coins with value < $1.00 are automatically hidden unless `force_visible=True`.

## File Structure & Components

### Backend Python Architecture (Modularized)
- **`main.py`**: Application entry point, Flask initialization, and configuration.
- **`routes/`**: Blueprint modules for domain-specific routing (`auth.py`, `ai.py`, `portfolio.py`, `system.py`).
- **`services/`**: External integrations and background tasks (`binance_service.py`, `scheduler_tasks.py`, `portfolio_service.py`, etc.).
- **`models.py`, `credentials.py`, `trading_models.py`**: SQLAlchemy ORM models.
- **`database.py`**: SQLAlchemy initialization.

### Frontend React Files
- **`frontend/src/`**: React 18 + Vite frontend source.
  - **`Dashboard.jsx`**: Portfolio overview, charts, and real-time value.
  - **`Portfolio.jsx`**: Holdings management.
  - **`Trading.jsx`**: Real-time trading interface.
  - **`Staking.jsx`**: Binance.US staking integration.
  - **`Settings.jsx`**: Application configuration and AI prompt management.

## Service Management & Ports
**Service Name**: `crypto-dashboard.service`

**Ports**:
- **Default Application Port**: `5016` (Used for both running directly or via systemd service)

**Restart Command**: `sudo systemctl restart crypto-dashboard.service`
**Check Logs Command**: `sudo journalctl -u crypto-dashboard.service -f`

## External Integrations
- **Binance.US API (EXCLUSIVE)**: Use `tld='us'` for all client initializations.
- **AI Analysis**: Multi-provider support (OpenAI, Z.AI, Perplexity, Gemini). Integrated web search (Brave Search with DuckDuckGo fallback).
- **Telegram API**: Price alert notifications via Bot API.

---

### 🚨 CRITICAL RULE FOR GITHUB PUSHES:
**GOING FORWARD, YOU MUST ALWAYS REFERENCE YOUR UPDATES/FIXES IN THIS README FILE WITH EVERY PUSH TO GITHUB.**

---

## Version History & Changelog

## v1.77-beta (August 2026)

### Copilot Scrollbar Polish, Table Header USDT Total Value, Volatility Alignment & Action Buttons
- **AI Copilot Sidebar Scrollbar Polish**: Restyled the AI Copilot sidebar scrollbar in both Dark Mode (subtle, sleek rounded slate `#475569` on transparent track) and Light Mode (crisp, high-contrast `#94a3b8` thumb on subtle track), matching the Recent Order History widget design.
- **Portfolio Table Header USDT Total**: Added a live, right-aligned **Total Value: $X,XXX.XX USDT** indicator in the Portfolio section header.
- **Volatility Centering & Badge Anchoring**: Reworked `renderVolatilityCell` to keep the input box and `%` sign centered across all rows while cleanly anchoring active Auto-Sell/Auto-Buy trigger badges (`⚡`/`🚀`) to the right edge.
- **Real Action Icon Buttons**: Upgraded bare emojis for Alerts (`🔔`), News (`📰`), and Notes (`✏️`) into styled action button pills with distinct backgrounds, borders, and hover states for high contrast on light mode, dark mode, and yellow pending-order highlighted rows.
- **News Cache Symbol Indexing**: Enhanced `get_user_latest_news_cache` to index news by both coin ID and uppercase symbol, ensuring instant tooltip news previews for both Portfolio and Watchlist assets.
- **Version Bump**: Synchronized metadata to `v1.77-beta`.

## v1.76-beta (August 2026)

### Price Alert onBlur Auto-Save for Portfolio & Watchlist
- **Blur Auto-Save (`onBlur`)**: Added `onBlur` event listeners to all Price Down and Price Up alert textboxes in both Portfolio and Watchlist tables. Alert thresholds are now automatically saved to the database upon clicking outside the input or tabbing away, matching the existing `Enter` key behavior.
- **Race-Condition Free Typing**: Maintained local input sanitization during active typing without firing API requests until the input loses focus (`onBlur`) or `Enter` is pressed.
- **Version Bump**: Synchronized metadata to `v1.76-beta`.

## v1.75-beta (August 2026)

### USD/USDT Trading Action Guards, Watchlist Table Streamlining & Immediate Auto-Buy Balance Validation
- **USD Trading Guards**: Explicitly grayed out and disabled the `Buy` and `Sell` action buttons for fiat `USD` in both Portfolio and Watchlist tables.
- **USDT Self-Pairing Guards**: Disabled `Buy with USDT`, `Sell for USDT`, `Trigger Auto-Buy (USDT)`, and `Trigger Auto-Sell (USDT)` when interacting with `USDT` to prevent self-pairing trading attempts.
- **Watchlist Table Clean-Up**: Removed the redundant `Sell` button from the Watchlist table, keeping Watchlist focused exclusively on monitoring and opportunistic buy orders.
- **Immediate Auto-Buy $1.00 Balance Banner**: The Auto-Buy confirmation modal now immediately displays a prominent warning banner and disables input fields if the available uncommitted quote balance is less than the $1.00 minimum required.
- **Version Bump**: Synchronized metadata to `v1.75-beta`.

## v1.74-beta (August 2026)

### Dual-Quote Auto-Sell (USD/USDT) & Smart Auto-Buy with Real-Time Balance Commitment Accounting
- **Dual-Quote Auto-Sell**: Split the Auto-Sell action into `Trigger Auto-Sell (USD)` and `Trigger Auto-Sell (USDT)`, allowing automated protection against market drawdowns targeting either quote currency.
- **Automated Surge Auto-Buy**: Added `Trigger Auto-Buy (USD)` and `Trigger Auto-Buy (USDT)` for all Portfolio and Watchlist assets, executing automatic market buy orders when coins experience upward price surges over user-configured volatility hours.
- **Balance Commitment & Over-Allocation Guard**: Integrated real-time uncommitted balance tracking ($B_{\text{available}} = \max(0, \text{Free} - \text{Reserved})$), preventing users from allocating more USD or USDT than what is freely available across multiple active Auto-Buy triggers, enforced with a $1.00 minimum order floor.
- **Dual Volatility Parameter Synchronization**: Tied execution logic directly to the configured `volatility_hours` duration in Settings and individual coin `volatility_pct` thresholds in tables.
- **Version Bump**: Synchronized metadata to `v1.74-beta`.

## v1.73-beta (August 2026)

### Recent Trades, Top Movers Data Fix & Done Editing Auto-Save
- **Recent Order History Feed Fix**: Resolved response handling and endpoint routing in `RecentTradesWidget.jsx` to load live order executions seamlessly from `/api/trading/real-orders` and `/api/orders`.
- **Top Gainers & Losers (24h) Data Integration**: Connected `TopMoversWidget.jsx` directly to `/api/coin-performance` to calculate and render real-time 24h gainers and dip opportunities across portfolio and watchlist assets.
- **Done Editing Auto-Save**: Clicking **✓ Done Editing** in the top navbar now explicitly commits and saves layout modifications to persistent browser storage.
- **Version Bump**: Synchronized metadata to `v1.73-beta`.

## v1.72-beta (August 2026)

### Smart Grid Hole-Detection & Default Panel Sizing for Restored Widgets
- **First Open Spot Placement (`findFirstAvailableSpot`)**: When restoring or adding a new widget from the *+ Add / Restore Panels* dropdown, the grid layout engine scans row-by-row to detect the first available open slot in the dashboard and places the widget right there instead of dropping it at the bottom-left corner.
- **Full Standard Default Sizing (`w: 3, h: 3`)**: Restored panels now open at the full, standard size of metric cards (matching Fear & Greed / CBBI / Staking) instead of collapsing into a miniature 1x1 or 2x2 box.
- **Version Bump**: Synchronized metadata to `v1.72-beta`.

## v1.71-beta (August 2026)

### Freeform Dashboard Grid Layout & Drag-Drop Snapping Fix
- **Freeform Layout Positioning (`compactType={null}`)**: Removed aggressive vertical compaction in `ResponsiveGridLayout` so panels no longer jump or snap unexpectedly to fill gaps in upper rows when resizing adjacent panels.
- **Independent Row Drag & Placement**: Fixed the issue where panels (such as Fear & Greed Index) could not be dropped between lower-row panels or placed into custom row positions below gaps.
- **Version Bump**: Synchronized metadata to `v1.71-beta`.

## v1.70-beta (August 2026)

### Dashboard Layout History Management & 7 New Modular Panels
- **Layout History Stack & Undo (`↩ Undo`)**: Added a 5-step undo history engine to the Customize Layout toolbar. Users can undo panel drag/moves, resizes, panel additions, and panel removals sequentially.
- **Explicit Save & Cancel (`💾 Save` / `✕ Cancel`)**: Added explicit Save and Cancel controls in Customize Layout mode. Clicking **Save** persists layout states with live visual feedback, while **Cancel** cleanly rolls back all modifications to the state when edit mode was entered.
- **7 New Modular Dashboard Widgets**: Introduced 7 new widgets available directly within the *＋ Add / Restore Panels* menu:
  1. **🔥 Top Gainers & Losers**: 24h market momentum tracker across portfolio and watchlist assets.
  2. **📜 Recent Order History**: Real-time filled trade feed with timestamps, side badges, and execution totals.
  3. **🤖 AI Copilot Market Pulse**: Macro market sentiment scoring, catalyst summaries, and AI market commentary.
  4. **🌾 Staking Yield & Rewards Tracker**: Projected daily, monthly, and yearly staking yield breakdowns with APR metrics.
  5. **🛡️ Portfolio Risk & Drawdown Monitor**: Peak ATH drawdown analysis, asset concentration gauges, and risk profiling.
  6. **⚡ Quick Trade Mini-Terminal**: Fast market buy/sell order launcher directly from the main dashboard.
  7. **⛽ Network Gas & Fee Monitor**: Live blockchain network fee trackers for Bitcoin, Ethereum, and Solana.
- **Version Bump**: Synchronized metadata across `version.js`, `package.json`, and UI footer to `v1.70-beta`.

## v1.69-beta (August 2026)

### Coin Performance Customization & Trade Menu UX Enhancements
- **Generic Crypto Coin Header Icon**: Replaced the broken icon character next to "Coin Performance" with a clean vector cryptocurrency coin icon.
- **Removed Header Subtitle Clutter**: Removed the subtext *"Holdings worth at least $1, excluding stablecoins"* for a clean widget layout.
- **Interactive Coin Filter Modal (`✏️`)**: Added an edit pencil button on the Coin Performance widget header in Customize Layout mode, opening a coin filter modal that allows users to selectively toggle which coins from their Portfolio and Watchlist appear in the performance table.
- **Multi-Source Performance Calculation**: Enhanced backend `/api/coin-performance` to calculate multi-timeframe price changes (7D, 3D, 1D, 12H, 1H) across both active portfolio holdings and watchlist assets.
- **Trade Menu Outside-Click & Scroll Dismissal**: Fixed the floating trade action menu (Buy/Sell quote currency & Trigger Auto-Sell) to automatically close whenever clicking outside the menu or scrolling the page/containers.
- **Version Bump**: Synchronized metadata to `v1.69-beta`.

## v1.68-beta (August 2026)

### Pre-Execution Open Order Conflict Resolution for Auto-Sell
- **Automatic Conflicting Order Cancellation**: Integrated pre-check logic into the backend Auto-Sell executor (`execute_auto_sell`). Prior to submitting a market sell order, the system scans for any active open orders on Binance.US for that specific coin (such as open limit sells, stop-loss limits, or OCO orders) and automatically cancels them to immediately unlock 100% of the coin's asset balance.
- **Dynamic Post-Cancel Balance Refresh**: Re-queries Binance's live free balance post-cancellation, recalculates optimal lot size formatting, and executes the market sell into USDT without manual intervention or order failure.
- **Enhanced Multi-Channel Logging**: Detailed notes of cancelled orders are recorded in `AllActivity`, dispatched via Telegram alerts, and saved as user notifications.
- **Version Bump**: Synchronized metadata across `version.js`, `package.json`, and UI footer to `v1.68-beta`.

## v1.67-beta (August 2026)

### Portfolio Volatility Drop Auto-Sell & App Versioning Fix
- **Trigger Auto-Sell Action**: Added a 3rd option ("Trigger Auto-Sell") to the Portfolio Sell dropdown menu on both desktop and mobile views.
- **Confirmation Modal**: Clicking "Trigger Auto-Sell" opens a confirmation modal verifying: *"You are about to enable an automatic sale of [X] when the price drops more than [Y]% within a 1-hour period. Are you sure you want to do this?"*, pulling the coin symbol and configured Volatility % directly from the table row.
- **Autonomous & Executive Market Execution**: Enabled a background monitor in the scheduler loop that compares coin price against 1-hour reference candles. If a dump occurs exceeding the threshold percentage, the backend automatically places a market sell into USDT on Binance.US, logs the activity, updates the database, generates an in-app notification, and sends a Telegram alert without requiring manual user intervention.
- **Active State Indicators**: Coins with active Auto-Sell protection display an illuminated indicator in the table and provide single-click management/disabling options.
- **Footer Version Synchronization**: Bumped application metadata across `version.js`, `package.json`, and the footer to `v1.67-beta`.

## v1.66-beta (August 2026)

### Trading Chart Exact Price Markers & Timestamp Normalization
- **Exact-Price Line Markers**: Plotted buy and sell arrow markers at the exact transaction price using a transparent series rather than snapping above/below candles.
- **Timestamp Parsing & Deduplication**: Normalized transaction timestamps between seconds and milliseconds, resolving transaction clumping and duplicate entries in the transaction modal.

## v1.65-beta (August 2026)

### USD and USDT Trading Choices from Portfolio and Watchlist
- Added USD/USDT quote-currency menus to Portfolio Buy and Sell actions.
- Added USD/USDT quote-currency menus to the existing Watchlist Buy action; Watchlist Sell was not added.
- Trading now opens the selected base/quote pair, such as `XRPUSD` or `XRPUSDT`, with the requested order side.
- Fixed quote menus rendering behind or outside table containers by mounting desktop menus at the document root.
- Fixed real quote-balance buys exhausting USD or USDT before fees: the balance slider and server now reserve the exchange taker fee and a small safety buffer before submitting an order.
- Fixed real-order portfolio updates to apply Binance's executed USD/USDT quote amount and commission immediately, preventing stale quote balances and inflated total holdings after trades.

## v1.63-beta (August 2026)

### True Drag-to-Resize Dashboard Grid, Official Cryptocurrency Icons & AI Analysis Enhancements
- **Official Cryptocurrency Coin Icons**: Added rich, high-resolution vector cryptocurrency icons alongside coin symbols across Portfolio, Watchlist, Historical Prediction Ledger, and Tax Report transaction log tables.
- **True Drag-to-Resize Widget Grid**: Integrated responsive multi-handle drag-to-resize across all upper dashboard widgets with smooth real-time resizing and grid snapping.
- **Navbar Layout Fix**: Moved the "Customize Layout" button inline with dashboard controls to ensure zero overlap with navigation items.
- **Watchlist Delete Button Styling**: Matched the Watchlist "Delete" button styling with standard gradient trade action buttons.
- **AI Analysis Page Refinements**:
  - Expanded the Sentiment vs. Price Action chart height by 24% (to 420px).
  - Reordered Prediction Ledger columns and made all headers fully sortable.
  - Enabled dynamic global coin filtering for Recommendation Type Accuracy and AI Model Leaderboards.
- **Version Bump**: Synchronized all client and package metadata to `v1.63-beta`.

## v1.62-beta (August 2026)

### Customizable Upper Dashboard Widget Grid & Modernized Tables Facelift
- **Interactive Upper Widget Grid**: Converted the 7 upper dashboard panels (Allocations Donut, Portfolio Trend Area Line, Fear & Greed Gauge, Total Portfolio Value, CBBI Bull Run Index, Staking Yield, and 7-Day Performance Tickers) into an interactive customizable grid.
  - **Edit Dashboard Mode**: Toggle button in the header enabling visual drag-and-drop (`⠿`) reordering, width span resizing (1x, 2x, 3x full-width), and one-click hiding (`✕`).
  - **Restore / Unhide Panels Drawer**: Dedicated "+ Add / Restore Panels" menu to unhide previously hidden panels at any time.
  - **Persistent Local Layout**: Automatic storage in `localStorage` with a "Reset Default" restore option.
- **Modernized Portfolio & Watchlist Tables**:
  - Full aesthetic facelift with frosted glass card containers, subtle neon borders, modern typography, and refined action buttons.
  - **100% Feature Parity Preserved**: Retained all table actions (Buy ⚡, Sell ⚡, Stake 🪙, Hide 👁️, Notes 📝, Alert Bell 🔔, Delete 🗑️), on-demand sentiment recalculation (🔄), 7-day sparkline hover popup, column sorting (`▲`/`▼`), and yellow pending order highlights.
- **Full Theme Parity**: Complete Light Mode and Dark Mode support across all new and refreshed components.
- **Version Bump**: Synchronized all client and package metadata to `v1.62-beta`.

## v1.61-beta (August 2026)

### Independent Order History View, 20-Order Pagination & Searchable Trading Pair Selectors
- **Independent Order History Filter**: Decoupled the pair filter in the Order History tab from the Place Order form. Navigating to Order History now defaults to displaying all open orders and complete trade history across all pairs (`ALL`), without interfering with or being constrained by the currently selected pair on the Place Order tab.
- **Order History Table Pagination**: Added 20-row pagination to the Order History table with responsive page controls (First, Previous, Numbered Page Pills, Next, Last) and row range indicators.
- **Searchable Trading Pair Dropdowns**:
  - Replaced the static `<select>` in the Place Order / Trading Chart header with a searchable typeahead dropdown, allowing instant real-time filtering and selection across hundreds of pairs by typing asset tickers or names (e.g. `XRP`, `SOL`, `BTC`, `USD`).
  - Replaced the Order History pair filter dropdown with a matching searchable typeahead selector featuring an "All Trading Pairs" global view option.
- **Version Bump**: Synchronized all client and package metadata to `v1.61-beta`.

## v1.60-beta (August 2026)

### AI Copilot System Prompt Overhaul, Optimistic Message Management & Overload Resilience
- **Instant Optimistic Message Deletion & Archiving**: Deleting or archiving single messages (via the trash can / folder icon) or bulk selected items now removes them from the Copilot sidebar immediately without waiting for server roundtrips or requiring screen refreshes.
- **Provider Overload Fast-Fail & Key Auto-Discovery**: Removed 48s retry loops when upstream AI providers (such as Z.AI) return `429: Overloaded`, instantly discovering and failing over to secondary keys (OpenAI, Gemini, Perplexity) in milliseconds.
- **AI Copilot System Prompt Redesign**: Overhauled the default AI Copilot system instructions across database schemas, defaults, and Settings UI, framing the assistant as an expert crypto trading strategist, portfolio analyst, and market intelligence copilot.
- **Active Sidebar Stream Context Integration**: Dynamically compiles the active chronological stream of sidebar cards into Copilot prompt context—including recent Portfolio Sentiments, Watchlist Sentiments, Market Analyses, Portfolio Reviews, and prior chat dialogue.
- **Pending Orders & Limit Target Context**: Integrated live pending limit orders and target prices alongside portfolio holdings, ensuring the Copilot can provide data-backed feedback on proposed trades and buy/sell limit targets.
- **Version Bump**: Synchronized metadata to `v1.60-beta`.

## v1.59-beta (August 2026)

### AI Copilot Pipeline Optimization, Reasoning Token Fix & Error Resilience
- **Fast-Track Copilot Pipeline**: Streamlined the AI Copilot workflow by replacing the multi-stage LLM query generation pass with fast, symbol-targeted search queries, cutting Copilot response latency from 45-75 seconds down to 3-6 seconds.
- **Reasoning Model Token Budgeting**: Fixed reasoning token starvation for OpenAI reasoning models (`o1`, `o3-mini`, `gpt-5`) where internal reasoning tokens previously consumed the token budget and caused empty completion responses.
- **Symbol-Aware Context Injection**: Automatically extracts mentioned crypto assets (e.g. `XRP`, `BTC`, `SOL`, `ONT`) from the user's message, injecting live pricing, portfolio holdings, sentiment signals, sentiment reasons, and order status directly into the prompt.
- **Robust Error Recovery & Logging**: Logs user messages immediately upon receipt, guarantees graceful fallback responses when external AI provider outages occur, and adds a 90-second client timeout with descriptive error propagation in the Copilot UI.
- **Version Bump**: Synchronized metadata to `v1.59-beta`.

## v1.58-beta (August 2026)

### Contextual Trading Pair Filtering on Buy/Sell Navigation & Sentiment Contrast Optimization
- **Contextual Pair Filtering on Navigation**: Clicking "Buy" or "Sell" from the Portfolio or Watchlist tables now automatically focuses and filters the Trading page dropdown to show only relevant pairs for the selected asset (e.g. clicking XRP shows `XRP/USD` and `XRP/USDT`), eliminating unnecessary scrolling across hundreds of symbols.
- **Show All Pairs Reset Button**: Added a dedicated "🔄 Show All Pairs" reset button directly in the Trading Chart header to instantly restore the full multi-hundred pair catalog at any time.
- **High-Contrast Sentiment Badge on Pending Rows**: Redesigned sentiment pill rendering on yellow highlighted pending-order rows with a high-contrast dark capsule container (`rgba(15, 23, 42, 0.95)`), ensuring sentiment text (`Hold`, `Consider Selling`, `Consider Buying`, etc.) and refresh controls remain crisp, vivid, and easily readable.
- **Version Bump**: Synchronized metadata to `v1.58-beta`.

## v1.57-beta (August 2026)

### Complete Binance.US USD Trading Pairs Expansion & Dynamic Exchange Synchronization
- **Full Binance.US USD Pairs Catalog**: Expanded the Trading Center trading pairs list to include all 54 active USD trading pairs on Binance.US (including `XRP/USD`, `BTC/USD`, `ETH/USD`, `SOL/USD`, `ADA/USD`, `SUI/USD`, `DOGE/USD`, `LTC/USD`, `LINK/USD`, etc.) alongside all 200+ USDT trading pairs.
- **Dynamic Trading Pairs Synchronization (`GET /api/trading-pairs`)**: Updated the trading pairs backend endpoint to query live Binance.US exchange info with in-memory caching and a robust 54-pair USD fallback list, ensuring live trading pairs are always available.
- **Grouped & Organized Trading Dropdown UI**: Upgraded the Trading Chart pair selector and Open Orders history dropdown with clean `<optgroup>` categorizations (`USD Pairs` and `USDT Pairs`), enabling effortless discovery and selection of any USD or USDT pair.
- **Robust Base & Quote Asset Parser**: Enhanced symbol string parsing across the trading engine and chart components to reliably extract base and quote assets for all combinations (including `USDTUSD`, `XRPUSD`, `SUSD`).
- **Version Bump**: Synchronized metadata to `v1.57-beta`.

## v1.56-beta (August 2026)

### Sentiment Web Search Provenance & Historical Prediction Ledger Formatting
- **Web Search Provenance Tracking**: Added `sentiment_search_status` across `Coin`, `WatchlistCoin`, and `SentimentHistory` database models (with `migrations/migrate_v1_56.py`), recording detailed web search execution telemetry (`Brave Search (N results found)`, `Brave Search (N results, no specific news)`, `DuckDuckGo Fallback`, or `Web Search Unavailable`).
- **Dashboard Sentiment Tooltip Search Status**: Enhanced the tooltip when hovering over sentiment pills in the Dashboard to show exact web search engine and outcome with status icons (`✅`, `⚠️`, `❌`).
- **Historical Prediction Ledger Completed Pairs Filter**: Filtered out active tracking rows (`is_latest` / `outcome_status == 'tracking'`) from the Historical Prediction Ledger table so only validated prediction-outcome pairs with two concrete sentiment and pricing data points are displayed.
- **12-Hour AM/PM Eastern Time Formatting**: Updated signal timestamps and evaluation timestamps in the prediction ledger to clean 12-hour AM/PM Eastern time format (e.g. `9:20 PM`).
- **Version Bump**: Synchronized metadata to `v1.56-beta`.

## v1.55-beta (August 2026)

### Database Migration for Schedule Columns & Reliable Timestamp-Based Polling
- **Database Schema Migration (`migrate_v1_55.py`)**: Added missing `portfolio_schedule_start_time` and `watchlist_schedule_start_time` columns to `user_settings` table in PostgreSQL, resolving the `UndefinedColumn` / `InFailedSqlTransaction` error that previously aborted sentiment analysis execution.
- **Robust Polling & State Detection**: Updated single-coin sentiment refresh in `Dashboard.jsx` to track `sentiment_last_updated` and keep polling throughout long AI web search synthesis without prematurely terminating after the first poll.
- **Instant Pre-Analysis Flagging**: Added immediate DB commit of `sentiment = "Checking now..."` right upon entry of single-coin execution so live listeners reflect the state instantly.
- **Version Bump**: Synchronized metadata to `v1.55-beta`.

## v1.54-beta (August 2026)

### Portfolio Actions Truncation Fix & Table Proportions Tuning
- **Action Buttons Ellipsis Bugfix**: Removed legacy `nth-child` max-width and text-overflow ellipsis CSS rules that erroneously collapsed the 11th table column, restoring full visibility to all action buttons (`🔔`, `📰`, `✏️`, `Buy`, `Sell`, `Stake`, `Hide`).
- **Sentiment Alignment & Gap Removal**: Eliminated the artificial space gap between sentiment recommendation badges and per-coin refresh buttons (`🔄`) by switching to centered inline-flex grouping with a 6px gap and removing excessive column `minWidth` constraints.
- **Table Proportions Optimization**: Narrowed and centered `Current Value`, `Avg Entry`, and `% Change` columns to optimize screen real estate and prevent table overflow.
- **Version Bump**: Synchronized metadata to `v1.54-beta`.

## v1.53-beta (August 2026)

### Real-Time Sentiment Buff, Per-Coin Refresh & Portfolio Table Refinements
- **Sentiment Execution Bugfix**: Added missing `timedelta` import in `services/ai_service.py` to prevent background scheduler and manual "Run Sentiment Analysis Now" threads from crashing with a `NameError`.
- **Real-Time Sentiment Progress Indicator**: When sentiment analysis is actively processing (triggered globally or per-coin), the Sentiment cell dynamically updates in real time to display `⏳ Checking now...` with visual feedback in both the Portfolio and Watchlist tables.
- **On-the-Spot Per-Coin Sentiment Refresh**: Added a dedicated right-aligned refresh button (🔄) inside the Sentiment column for every coin in both Portfolio and Watchlist tables, allowing instant single-asset sentiment updates.
- **Portfolio Table Refinements**: Removed the "Purchase Date" UI column from the Portfolio table while preserving the underlying database timestamps, and widened the Sentiment column (`minWidth: 185px`) to prevent text wrapping or truncation on long sentiment labels.
- **Version Bump**: Synchronized metadata to `v1.53-beta`.

## v1.52-beta (August 2026)

### AI Dashboard Candlestick Chart & Binance.US Order Placement Overhaul
- **AI Dashboard Chart Time Scale Fix**: Normalized candlestick timestamps to eliminate double second conversion, fixing the x-axis tick repeating issue ("21 21 21" 1970 dates) and aligning time scale, crosshairs, and price scales with Trading Center.
- **Binance.US PERCENT_PRICE Price Collar Handling**: Added extraction and pre-validation for Binance.US price collar filters (`PERCENT_PRICE` and `PERCENT_PRICE_BY_SIDE`, 5x up / 0.2x down multiplier). Translated exchange rejection errors into descriptive, user-friendly messages displaying current price and maximum allowable bounds.
- **Take Profit Limit & Stop Loss Limit Logic Correction**: Fixed erroneous client-side and backend validation that previously conflated Take Profit rules with Stop Loss rules and erroneously blocked sell take-profit limit orders where limit price > stop price.
- **Binance.US Order Types & OCO Support**: Resolved `LIMIT_MAKER` parameter constraints (prohibiting `timeInForce`), quantized OCO limit/stop prices to exchange tick sizes, and retained `OCO` in available symbol order types.
- **Version Bump**: Synchronized metadata to `v1.52-beta`.

## v1.42-beta (August 2026)

### Coin Performance Table Reliability
- Added cached Binance.US hourly history backfill so every performance window can populate immediately without relying on the dashboard having stayed open for seven days.
- Corrected qualification rules to include only visible, non-stablecoin holdings worth at least $1.00.
- Centralized baseline selection and live snapshot collection, fixed scheduler persistence, and added failure-safe table loading states.
- Made package metadata the single source for the footer and in-app upgrade target, synchronized to `v1.42-beta`.

## v1.41-beta (August 2026)

### Live Portfolio Performance Table
- Fixed the seven-day coin history endpoint so it returns actual stored samples instead of repeated fallback points.
- Added a live percentage performance table for qualifying portfolio coins across 7 days, 3 days, 1 day, 12 hours, and 1 hour.
- Added throttled live price history snapshots during dashboard refreshes.

## v1.4-beta (August 2026)

### Granular Portfolio Volatility Alerts
- Added a Portfolio Table Settings control for configuring the volatility alert window in hours.
- Volatility alerts now compare current prices against Binance.US hourly candles for the configured window, defaulting to 24 hours.

## v1.32-beta (August 2026)

### Settings UI Overhaul
- **Right-aligned Header Controls**: All action buttons (AI toggle, Run Sentiment Analysis Now, Sync Coins, Save Settings, Reset Password, Upgrade App, Include Beta) are now right-aligned in a flex row.
- **Run Sentiment Analysis Now in Header**: Moved from a standalone card to the header bar, placed to the left of Sync Coins, matching the same outline style.
## v1.34-beta (August 2026)

### On-the-Spot Watchlist Sentiment Analysis
- **Instant Sentiment on Addition**: Adding a new cryptocurrency to the Watchlist automatically runs an on-the-spot sentiment analysis check, providing immediate AI trading sentiment and detailed explanation upon adding the coin.
- **Dedicated Single-Symbol Sentiment Engine**: Created `analyze_single_symbol_sentiment` in `services/ai_service.py` to support on-demand single-coin analysis for both portfolio and watchlist items independently of periodic batch scheduler runs.
- **Watchlist Timestamp & Reason Tracking**: Added `sentiment_last_updated` column and database migration for the `watchlist` table, enabling tooltip explanation and timestamp rendering on watchlist cards and table rows.
- **Stablecoin Optimization**: Automatically fast-paths dollar-pegged stablecoins on watchlist addition directly to "Hold" without consuming LLM API tokens.

---

## v1.33-beta (August 2026)

### Z.AI Error Resolution & Global Endpoint Routing
- **Optimized Endpoint Priority**: Reordered candidate endpoints in `zai_client.py` to prioritize global production endpoints (`https://api.z.ai/api/paas/v4` and `https://open.bigmodel.cn/api/paas/v4`) ahead of the specialized coding plan endpoint (`api/coding/paas/v4`), eliminating false `429 (code 1305)` "service overloaded" errors on standard accounts.
- **Rate-Limit & Overload Resilience**: Added retry loops with exponential backoff for Z.AI rate limits and temporary traffic spikes (`1302` / `1305` / `该模型当前访问量过大`).
- **Flash Model Sibling Failover**: Added automatic fallback to sibling flash models (`glm-4.7-flash` ↔ `glm-4.5-flash`) if an upstream flash model is experiencing global congestion.
- **Reasoning Content Extraction**: Automatically extracts `reasoning_content` when reasoning models spend generation tokens in thought blocks, preventing empty responses.
- **Clear Account Balance Guidance**: Specific error messaging for error code `1113` advising when a paid model requires account recharge.

### Sentiment Check Pacing & Rate-Limit Prevention
- **Staggered Coin Execution**: Paced portfolio sentiment analysis loops with an 8-second delay between coins and a 15-second cooldown upon rate-limit detection, preventing burst traffic from exhausting LLM API RPM (requests per minute) limits.
- **Stablecoin Fast-Path**: Automatically bypasses LLM and web search calls for dollar-pegged stablecoins (USDT, USD, USDC, DAI, TUSD, USDP, EURC, PYUSD), immediately setting sentiment to "Hold" and conserving API quota.
- **Sentiment Concurrency Lock**: Per-user mutex ensures only one sentiment analysis run executes at a time per user, preventing race conditions between background scheduler jobs and manual triggers.
- **Gemini 503 High Demand Recovery**: Extended Gemini retry handling to gracefully back off and retry during temporary `503 UNAVAILABLE` ("This model is currently experiencing high demand") spikes before falling back to secondary providers.

---

## v1.32-beta (August 2026)

### Settings UI Layout Overhaul
- **Reorganized Settings Grid (2-column layout)**:
  - Row 1: Binance.US API Key & Secret | Two-Factor Authentication (2FA)
  - Row 2: Primary AI Integration | Fallback AI Integration
  - Bottom: Notifications & Tax Configuration side-by-side at half width
  - Credential Encryption spans full width (admin only)
- **Primary AI Integration label**: Renamed from "AI Integration" for clarity alongside the new Fallback card.

### Fallback AI Integration & Automatic Failover
- **Fallback AI Provider**: Added a second AI provider/model/key configuration slot. If the primary AI call fails, the system automatically retries with the fallback provider.
- **Fallback Key Storage**: `openai_key_fallback`, `zai_key_fallback`, `perplexity_key_fallback`, `gemini_key_fallback` columns added to credentials.
- **Test Fallback AI Connection**: Dedicated button to verify the fallback provider independently.
- **Fallback Reasoning Level**: Separate reasoning effort dropdown for Gemini fallback models.

### Sentiment Tooltip Fix
- **Enforced JSON response format**: Rewrote `sentiment_prompt_post` in DB to explicitly require `{"sentiment": "...", "reason": "..."}` JSON with no extra text, eliminating cases where the AI returned a bare word with no reason.
- **Improved `parse_sentiment_json`**: Added structured logging when AI returns no JSON, improved reason extraction for long-form values, and raised threshold for "remainder" fallback to 10 characters.
- **Tooltip now shows reason**: Hovering over a sentiment badge (Hold/Buy/Sell) in the portfolio table shows the AI's 1-2 sentence explanation.

### Portfolio Value Widget & Live Price Refresh Fix
- **Live Background Price Refresh**: Updated `portfolio_alert_loop` to refresh real-time Binance prices for all active portfolio assets (regardless of whether alert thresholds are configured), keeping the total portfolio valuation continuously accurate.
- **SQLAlchemy Thread Session Recovery**: Fixed broken transaction state handling in background scheduler worker threads (`safe_background_iteration`). Unhandled exceptions now execute a clean `db.session.rollback()` and `db.session.remove()`, preventing background threads from getting stuck in an invalid transaction state loop.
- **Binance Balance Sync Price Refresh**: Added automatic price updates during the periodic 5-minute Binance account balance sync.
- **Portfolio History Recording**: Automatically records periodic portfolio total value data points into `portfolio_value_history` for trend charts.

### DB Schema & Migration Hardening
- Fixed database schema migrations in `database.py` to target the correct `watchlist` table name.
- Ensured independent `engine.begin()` transactions per column migration to prevent lock contention.
- Hardened `UserSetting` querying and `sanitizedModel` declaration in settings load path.

### AI Integration Updates
- **Z.AI Model Expansion**: Added support for GLM-4.5, GLM-4.5 Flash (Free), GLM-4.5 Air, GLM-4 Plus, and GLM-5.2 with resilient multi-endpoint fallback.
- **Unified Test AI Connection**: Streamlined provider connection test buttons in Settings.

---

## v1.31-beta (August 2026)

### Gemini Model Expansion & Reasoning
- **Gemini 3.5 / 3.6 / 3.7 Flash** added to the AI model dropdown.
- **Reasoning Effort Dropdown**: New "Low / Medium / High" selector for Gemini models, mapping to `thinkingBudget` tokens (1024 / 2048 / 4096).
- **Gemini Rate Limit Backoff**: Implemented exponential backoff with `retryDelay` parsing on Gemini 429 responses.

### Coin News Daily Caching
- **News icon on portfolio/watchlist rows**: Each coin row now has a newspaper icon that displays the latest cached AI-generated news summary in a tooltip.
- **Daily cache**: News is fetched once per day per coin and stored in `cached_news` / `cached_news_date` columns.
- **UTC→local timezone conversion**: Fixed sentiment and news `Last Updated` timestamps to display in the user's local time.

### Sentiment Error Handling
- **Error state**: If AI analysis fails, `sentiment` is set to `"Error"` with a red badge and `⚠️ Error` label.
- **Reason stored on error**: `sentiment_reason` is populated with the exception message for debugging.

---

## v1.3-beta (August 2026)

### AI Copilot Sidebar
- **3-Stage Agentic Workflow**: Copilot chat uses Stage 1 (query generation) → Stage 2 (web search) → Stage 3 (synthesis) pipeline for all responses.
- **Conversation History**: Full conversation history is loaded from `ai_conversations` and injected as context.
- **Workflow Context Injection**: Portfolio data, coin prices, and sentiment scores are injected into the Copilot system prompt.
- **Message Ordering**: Fixed Copilot message appending so new messages appear at the bottom of the scroll container.
- **AI Sender Styling**: AI responses visually distinct from user messages.

### Portfolio Review Consolidation
- **Risk Assessment merged into Portfolio Review**: Eliminated the standalone Risk Assessment workflow; consolidated into a richer Portfolio Review that covers risk, allocation, and recommendations.
- **Agentic Web Search wired to Portfolio Review**: `portfolio_review_workflow` now calls `call_ai_with_web_search` for live market context.

### Sentiment JSON Parsing (Initial Implementation)
- **`parse_sentiment_json`**: New parser for AI sentiment responses supporting dict, list, and bare-text formats.
- **`sentiment_reason` column**: Added to `coins` and `watchlist_coins` tables.
- **Hover tooltip**: Sentiment badge in portfolio table shows dotted underline and reason on hover.

### Settings & Prompts
- **Full AI prompt settings restored**: All six prompt slots (pre/post for coin analysis, market analysis, portfolio review, sentiment, copilot) visible and editable in Settings.
- **`is_stablecoin` helper**: Added to skip sentiment analysis for stablecoins (USDT, USDC, etc.).

---

## v1.2-beta (August 2026)

- **Dynamic Order Types Per Trading Pair**: The Order Type dropdown on the trading page now dynamically filters to only show order types that Binance.US actually supports for the selected trading pair, preventing failed order submissions due to unsupported order types.

---

## v1.35-beta (August 2026)

- **Dedicated Watchlist Sentiment Analysis Prompts**:
  - Split sentiment settings into distinct **Portfolio Sentiment Analysis** (for owned coins) and **Watchlist Sentiment Analysis** (for prospective coins).
  - Watchlist prompts provide custom tailored stage 1 query generation and stage 3 synthesis evaluating whether to initiate a new position.
  - Added dedicated database columns (`watchlist_sentiment_prompt_pre`, `watchlist_sentiment_prompt_post`, `watchlist_sentiment_analysis_frequency_hours`).
- **4-Option Watchlist Sentiment Classification**:
  - Watchlist sentiment classifies prospective entries into: **Avoid** (Red), **Watch** (Sky Blue), **Consider Buying** (Soft Green), and **Definitely Buy** (Vibrant Green).
  - Added resilient JSON parsing and tolerance mapping for all 4 watchlist signals alongside the 5 portfolio actions.
- **Independent Sentiment Schedulers & On-The-Spot Analysis**:
  - Independent frequency intervals for portfolio and watchlist coins.
  - Background scheduler automatically evaluates both portfolio and watchlist queues with rate-limit pacing and concurrency locks.
  - Instant on-the-spot sentiment check triggers when a coin is added to the watchlist.
- **Footer Version Synchronization**:
  - Synchronized footer version display and `package.json` to `v1.35-beta`.

---

## Fixes & Hotfixes (v1.2 → v1.35)

- **Telegram Alert State Persistence**: Alert states persisted to `alert_state.json` to prevent duplicate alerts across service restarts.
- **Credential Deadlock Prevention**: Fixed credential model mutation deadlock on reads; scoped background jobs to main process only.
- **Order History RowMapping Crash**: Fixed crash when iterating order history results with SQLAlchemy RowMapping.
- **Trading Pair Persistence**: Selected trading pair is now persisted across page refreshes.
- **Order Price Formatting**: Normalized `price`/`stopPrice` parameter formatting to satisfy Binance API precision requirements.
- **Stale Balance Race Condition**: Resolved race condition causing stale balances during rapid trading operations.
- **Staking Assets (IPv4)**: Enforced IPv4 DNS resolution for Binance.US staking eligibility API calls.
- **2FA Verification KeyError**: Fixed KeyError in 2FA verification flow and stop-loss limit order execution.
- **Tax Report 500 Error**: Fixed missing `__all__` exports, datetime module shadowing, and `get_cost_basis_for_asset` NameError.
- **Hidden Coins Bug**: Fixed coins being unhidden by Binance background sync, overriding manual hide actions.
- **Portfolio Load Time**: Reduced portfolio page load from ~15s to sub-second.
- **Refresh Logouts**: Fixed session expiry causing unexpected logouts on manual portfolio refresh.
- **serve_react_app**: Restored accidentally removed helper function causing 404 on all React routes.
- **Fee Display & Calculation**: Improved fee rate calculation accuracy and fee section visibility in trading UI.

---

## Recent Major Updates (June 2026)
- **Trading Chart Markers & Transaction Modal (v1.12-beta)**: Upgraded the trading chart to aggregate buys and sells across all cryptocurrencies into singular daily markers. Hovering over a marker now cleanly displays the total aggregated USDT value for that day. Clicking an arrow opens a detailed, interactive React-Bootstrap modal that allows cycling through exact transaction details (Coin Name, Exact Time, Price, Amount, and USDT Value) for that specific day's trades.
- **Instant Price Alerts on Order Fill (v1.11-beta)**: Addressed missing instant price alerts when an order fills. The system now immediately evaluates price thresholds using the actual fill price, bypassing the standard polling delay.
- **Trading Quantity Recalculation Fix (v1.11-beta)**: Fixed a bug where trading quantities (base asset) didn't recalculate properly when using the USD slider or typing a USD value, then changing the Limit/Stop price. The app now defers calculation to the backend to mathematically guarantee the correct asset quantity based on the exact Limit/Stop/Worst-Case price at the time of execution.
- **Application Upgrade Modal UI (v1.11-beta)**: Fixed an issue where the "Confirm Application Upgrade" modal appeared misaligned in the bottom-left corner and caused unexpected scrolling. Refactored the modal to use React-Bootstrap's `Modal` component, ensuring it is properly centered, accessible, and correctly overlays the screen.

## Recent Major Updates (May 2026)
- **Modular Architecture Refactoring**: Migrated the monolithic `main.py` into a clean Flask Blueprint architecture (`routes/` and `services/`).
- **GitHub Portability**: Removed local hardcoded paths, extracted credentials into `.env`, and implemented a clean `.gitignore`.
- **PostgreSQL Migration**: Completed refactoring to ORM. Legacy SQLite databases were purged.
- **Unified Credentials**: Centralized API key management.
- **Staking System**: Full Binance.US staking support with real-time APY.
