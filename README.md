# Crypto Alert App

**Crypto Alert App** is a comprehensive, non-custodial cryptocurrency portfolio management and trading platform designed exclusively for Binance.US. It provides users with real-time portfolio tracking, automated price alerts, one-click trading, built-in staking management, and AI-powered market sentiment analysis. 

**Last Updated**: August 2026

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

## v1.32-beta (August 2026)

### Settings UI Overhaul
- **Right-aligned Header Controls**: All action buttons (AI toggle, Run Sentiment Analysis Now, Sync Coins, Save Settings, Reset Password, Upgrade App, Include Beta) are now right-aligned in a flex row.
- **Run Sentiment Analysis Now in Header**: Moved from a standalone card to the header bar, placed to the left of Sync Coins, matching the same outline style.
- **Removed Force Analysis Card**: Eliminated the redundant ⚡ Force Analysis section from the settings grid; the functionality lives in the header button.
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

## Fixes & Hotfixes (v1.2 → v1.32)

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

