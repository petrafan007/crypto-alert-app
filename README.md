# Crypto & Securities Dashboard

**Crypto & Securities Dashboard** is a comprehensive, non-custodial digital-asset and securities portfolio management and trading platform for Binance.US and Webull. It provides real-time portfolio tracking, automated price alerts, exchange-scoped order workflows, built-in staking management, and AI-powered market sentiment analysis. Webull supports explicitly authorized, account-scoped equity/ETF, crypto, single-leg and documented multi-leg option strategies, futures, and event contract orders; no provider data or orders cross exchange boundaries.

**URL: https://csdapp.online**

**Last Updated**: August 2026

## 🚀 Key Features & Capabilities

- **📊 Real-Time Portfolio & Watchlist Tracking**
  - **Live Binance.US Sync**: Real-time balance and transaction history synchronization with Binance.US.
  - **Interactive Customizable Dashboard Grid**: Modern drag-and-drop (`⠿`) reordering, multi-handle resizing, and custom panel visibility for all upper dashboard widgets.
  - **Market Gauges & Performance**: Built-in Fear & Greed Index, CBBI Bull Run Peak Confidence metric, Staking Yield overview, and 7-day multi-interval performance tickers.
  - **True Portfolio Trend Charts**: Saved, user-selectable quick ranges from 1H through All-time with live portfolio net-worth updates.
  - **Cryptocurrency Vector Icons**: Rich, high-resolution coin icons for effortless asset recognition across all tables.
  - **Webull Read-Only Views**: Imported Webull equities, ETFs, crypto, and contract-mapped options can appear alongside Binance.US holdings, with exchange-aware order views and Webull price charts that overlay completed Webull trades. Option charts, quotes, and Greeks remain contract-specific and safely report missing OPRA data.

- **⚡ Professional Trading Terminal (USD & USDT)**
  - **Dual-Quote Currency Trading**: Instant one-click spot trading for both **USD** and **USDT** quote pairs directly from Portfolio and Watchlist rows.
  - **Advanced Order Execution**: Support for Market Orders, Limit Orders, Stop-Loss Limit, and OCO (One-Cancels-the-Other) protective orders.
  - **Searchable Pair Selector**: Real-time typeahead search across all 54+ active Binance.US USD pairs and 200+ USDT pairs.
  - **TradingView Advanced Chart & Personal Trade Chart**: Free hosted Advanced Chart with native symbol search, 80+ indicators, 100+ drawing tools, comparisons, date ranges, details, hotlists, calendar, and export/popup controls, plus a separate exact-pair line chart with Binance.US buy/sell markers.
  - **Paginated Order History**: Independent order history tab with 20-row pagination and symbol filtering.

- **🛡️ Autonomous Crash Protection & Volatility Auto-Sell**
  - **Executive Volatility Auto-Sell**: Set custom 1-hour drop thresholds (e.g. >5%) per coin. If a market dump occurs, the background daemon cancels conflicting orders, then executes a protected sell into USDT to protect capital.
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
  - `credentials.py`: User, Credential, UserSetting, OnboardingDefaultProfile, DesktopToken, CredentialEncryptionKey
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
- **AI Analysis**: Multi-provider support (OpenAI, Z.AI, Perplexity, Gemini). Integrated NewsAPI grounding plus web search (Brave Search with DuckDuckGo fallback).
- **Telegram API**: Price alert notifications via Bot API.

---

### 🚨 CRITICAL RULE FOR GITHUB PUSHES:
**GOING FORWARD, YOU MUST ALWAYS REFERENCE YOUR UPDATES/FIXES IN THIS README FILE WITH EVERY PUSH TO GITHUB.**

---

## Version History & Changelog

Historical changelog entries retain the product name used when they were originally released. The application domain, repository slug, deployment folders, database, and service identifiers intentionally remain unchanged by the v2.45.0 brand update.

## v2.63.5 (August 2026)

- **Account Deletion Fix**: Fixed an `ImportError` (`UserSettingSetting` typo) and missing table deletions in `/api/account/delete` that prevented users from deleting their own accounts from the Settings page.

## v2.63.4 (August 2026)

- **AI Scheduling Fix**: Resolved a schedule time-parsing error for strings formatted like `07:30`, and fixed a frontend bug where switching to workflow tabs was bypassing the user's scheduled frequency.

## v2.63.3 (August 2026)

- **AI Cache Hotfix**: Removed an invalid reference to a non-existent `symbol` attribute on `AIConversation` records during cache hydration.

## v2.63.2 (August 2026)

- **Dashboard Drag-and-Drop Hotfix**: Removed stale `onDragStop` and `onResizeStop` references that caused runtime reference crashes during dashboard panel customization.

## v2.63.1 (August 2026)

- Fixed a bug where the manual "Generate Market Analysis" and "Generate Portfolio Review" buttons were failing to forcefully trigger fresh analyses, causing them to silently fallback to outdated cached results.

## v2.63.0 (August 2026)

- Completely redesigned the default dashboard layout for new users, condensing the view to focus only on the 7 core panels (Asset Performance, Allocations, Portfolio Trend, Fear & Greed, Top Crypto/Stock Movers, and CBBI).
- Enabled dynamic drag-and-drop panel collision, allowing panels to cleanly swap or push each other out of the way when reordering.
- Fixed a CSS glitch that caused the panel resize corner handle to render as a bulky box instead of a clean arrow on hover.
- Fixed a flexbox rendering bug where the navigation bar user profile badge was being squished when the Customize Layout button loaded in.

## v2.62.6 (August 2026)

- Rebranded the platform copyright to "Cavallaro Services, LLC".
- Added a signed-in user badge to the primary application header, featuring a circular avatar with the initial of the user's username.

## v2.62.5 (August 2026)

- Removed legacy OpenAI models and replaced them with the modern suite (`gpt-5.4-mini`, `gpt-5.4`, `gpt-5.5`, `gpt-5.6-luna`, `gpt-5.6-terra`, and `gpt-5.6-sol`).
- Expanded the AI reasoning effort selector to include "Light", "Medium", "High", and "Extra High", and made it available globally across all supported AI providers in Settings and Onboarding.

## v2.62.4 (August 2026)

- Fixed a "GET method not supported" error bug on the registration and onboarding routes caused by a backend route naming collision with the React frontend router.
- Addressed an infinite onboarding redirect loop by decoupling the `/login` client-side route from the `checkAuthStatus()` forced redirection, allowing unauthenticated users to safely reset to the login screen after exiting setup.

## v2.62.3 (August 2026)

- **Onboarding Exchange Logo Normalization**:
  - Replaced hardcoded internal logo SVG primitives in the Onboarding workflow with the canonical, accurate Binance.US and Webull vectorized assets matching the dashboard UI.
- **Onboarding Completion Redirection Loop Resolution**:
  - Eliminated a caching guard condition within the application context session manager that prevented session hydration on Onboarding finish, resolving an infinite loop redirection that locked users on the setup review step.

## v2.62.2 (August 2026)

- **Password Manager Modal Bleed-Through Prevention**:
  - Elevated the `LegalModal` container and backdrop `z-index` to `2147483647` (maximum browser integer).
  - Configured the underlying signup form to automatically hide and become `inert` whenever a legal modal is active, preventing browser extension autofill badges (such as Keeper, 1Password, or Bitwarden) from rendering on top of legal modal text and controls.
- **Workflow Branding & Version Footers**:
  - Added the official copyright and version notice footer ("Crypto & Securities Dashboard version {APP_VERSION}. © 2026 Cavallaro Services. All rights reserved.") to the bottom of the signup workflow card and onboarding process pages.

## v2.62.1 (August 2026)

- **Registration Session & Onboarding Transition Fix**:
  - Resolved an issue where newly registered users were redirected back to the login screen after clicking "Create Account & Continue".
  - Configured Flask-Login unauthorized handler for API routes to return clean JSON (HTTP 401) instead of redirecting API callers to `/login`.
  - Configured persistent session cookies on registration and ensured credential-sharing (`withCredentials: true`) on signup requests so users transition smoothly into the onboarding wizard (`/onboarding`).
- **Interactive In-Page Legal Modals**:
  - Replaced external page links on the signup form with non-disruptive modal overlays for **Terms of Service**, **Privacy Policy**, and **Acceptable Use Policy**.
  - Users can review complete legal policies directly inside modal popups and close them with the "X" button without losing their entered form data or leaving the signup page.
- **Trading Risk Disclosures**:
  - Created comprehensive **Trading Risk Disclosures** detailing asset volatility, options/derivatives risks, non-custodial software boundaries, API third-party dependencies, and automated signal disclaimers.
  - Linked the "trading-risk disclosures" text on the registration form to open in a dedicated modal overlay, and added `/risk-disclosure` to the router and application footer.

## v2.62.0 (August 2026)

- **Complete New-User Onboarding**:
  - Replaced the legacy welcome modal with a resumable six-stage onboarding workspace covering account security, exchange selection, Binance.US and Webull setup, AI providers, search/news grounding, Telegram, and final review.
  - The complete experience is theme-aware, includes a visible light/dark switch, uses Binance.US and Webull branding, and supports Back, safe exit, saved resumption, optional-step skipping, and direct Edit actions from the final review.
- **Required Exchange Gate**:
  - New users must choose Binance.US, Webull, or both and successfully verify at least one selected exchange before Dashboard or application API access is allowed. Existing users are not placed into onboarding after upgrade.
  - Selecting both runs Binance.US first and Webull second. Webull may be skipped only after Binance.US succeeds; Webull onboarding uses Production OpenAPI and then allows detected live and paper account selection and optional portfolio import.
- **Trading Security and Credential Validation**:
  - Authenticator 2FA remains optional during setup, but deferring it leaves live trade placement and cancellation locked while eligible Webull paper trading remains available.
  - Binance.US onboarding requires Reading and Spot Trading permission before encrypted credentials are saved. Telegram credentials are saved only after the bot delivers a test message.
- **Independent Starting Defaults**:
  - Added a one-time, non-secret onboarding default profile for workflow prompts, sentiment settings, portfolio execution-safety values, and FIFO cost basis. Each newly registered user receives independent copies without inheriting credentials or account data.
  - Added regression coverage for the server-side onboarding gate, existing-user compatibility, the one-exchange completion rule, and cross-user default isolation.

## v2.61.5 (August 2026)

- **Cloudflare-Aware HTTPS Origin Handling**:
  - The application now accepts forwarded protocol and host values only when the request comes from the loopback Cloudflare Tunnel process. Public URL generation therefore uses `https://csdapp.online` without allowing direct LAN clients to spoof forwarded origin headers.
  - Desktop update links now use Flask's routed external-URL generation instead of manually concatenating the raw request root.
- **Secure Authentication Cookies**:
  - Session and remember-me cookies now require HTTPS and explicitly use `Secure`, `HttpOnly`, and `SameSite=Lax` protections.
  - Direct unencrypted LAN requests remain available for service diagnostics, but authenticated browser use is intentionally restricted to the public HTTPS domain.

## v2.61.4 (August 2026)

- **Smooth Mirrored Option Scrolling**:
  - Dual-sided option matrices now move their complete metric tracks continuously by pixel while either bottom slider is dragged. The opposite side follows at the mirrored position without rounding or snapping to whole columns.
  - Horizontal trackpad and Shift+wheel movement uses the same continuous mirrored position while the centered Strike column and two sticky header rows remain fixed in the existing unified table.
- **Correct Calls-Only and Puts-Only Shapes**:
  - **All Calls & Puts** keeps the full `Calls | Strike | Puts` matrix.
  - **Calls Only** removes the complete put side and renders `Calls | Strike`; **Puts Only** removes the complete call side and renders `Strike | Puts`, with no duplicate or empty half-table.

## v2.61.3 (August 2026)

- **Reliable Option-Table Headers**:
  - Dual-sided strategy views now render Calls, Strike, Puts, both header rows, and every data row in one continuous semantic table. The two native sticky header rows remain attached directly to the table body with no detached panes, gaps, or independent alignment calculations.
  - The mirrored bottom controls change the visible left/right metric-column window in the single table, preserving the centered strike while avoiding separate horizontally scrolling table sections.
  - Single-pane strategy tables now use the table viewport itself for horizontal and vertical scrolling, allowing both header rows to remain pinned without an intervening overflow container.
- **Theme-Aware Option Scrolling**:
  - The options matrix vertical scrollbar now matches the thin six-pixel scrollbar used by dashboard panels and the AI Copilot, including transparent dark-mode tracks and the lighter theme-aware track and thumb colors.
- **Convert Dust Table Contrast**:
  - Binance.US Convert Dust column headers now use distinct dark- and light-theme backgrounds with high-contrast header text, making every heading readable in either theme.

## v2.61.2 (August 2026)

- **Correct Split Option-Table Geometry**:
  - Dual-pane strategies now reserve a compact, fixed-width center strike column instead of allowing the general table width rule to stretch the anchor across the page.
  - Added permanently visible left and right horizontal scroll controls along the bottom of the split matrix. Moving either side mirrors the other side around the strike column, while trackpad or wheel-based horizontal movement over the quote panes remains synchronized.
  - The strategy heading row and the individual quote/Greek/analysis heading row remain pinned at the top during vertical scrolling, including the centered Strike and Anchor headings.
  - Single-pane strategy layouts remain unchanged.
- **Non-Disruptive Option Quote Refreshes**:
  - Scheduled, focus-triggered, and manual refreshes now keep the current option matrix mounted and merge fresh contracts by strike, updating displayed quote and analysis values in place.
  - Strategy, focus profile, selected contract, vertical position, and mirrored horizontal positions remain stable during background updates. A failed background refresh leaves the last valid values visible with a warning instead of replacing the matrix with a loading or error screen.

## v2.61.0 (August 2026)

- **Strategy-Aware Option Tables**:
  - Changing the option strategy now rebuilds every visible row from the selected strategy legs instead of leaving the matrix on single-contract values. Multi-leg quotes use execution-aware bid/ask combinations, Greeks use signed leg quantities, and liquidity reflects the least-liquid leg.
  - Single Option, Covered Option, Vertical, Butterfly, Condor, Calendar, and Diagonal use a fixed center strike with independently visible horizontal scrollbars whose positions move as mirrors. Straddle, Strangle, Collar, Iron Butterfly, and Iron Condor use a single-side matrix and one horizontal scrollbar.
  - Strategy rows display their actual strike combinations. Calendar and Diagonal rows use the next listed expiration supplied with the active chain.
- **Option Focus Profiles and Column Customization**:
  - Added Price Change, Greeks, and Volatility Focus profiles with the requested defaults and a pencil action beside each profile.
  - Added the split **Option Items** modal with Quote, Greeks, and Analysis groups, an ordered Selected Items panel, per-profile reset, and persistent local preferences. User-facing captions include **% Change** and **% Change (Open)**.
  - Added provider-backed bid/ask sizes, OHLC, open interest, Greeks, implied volatility, and probability fields. Mid, open change, intrinsic value, time value, and single-contract break-even values are derived from those quotes; unavailable historical volatility values display an em dash rather than a fabricated number.
- **Strategy Help Placement**:
  - Strategy illustrations now open above the selector, or to its left when there is insufficient space above, so the guidance cannot cover or interfere with the native strategy menu.

## v2.60.0 (August 2026)

- **Options Strategies and Fresh Chain Data**:
  - Added a strategy selector between **Display** and **Strikes** for Single, Covered, Straddle, Strangle, Vertical, Butterfly, Condor, Collar with Stock, Iron Butterfly, Iron Condor, Calendar, and Diagonal orders. Each strategy has a keyboard-accessible hover/focus card with a compact payoff illustration and explanation.
  - Added **Width** controls with Auto and 1-10 strike intervals for width-based strategies. The unsupported Ratio choice remains visible but disabled so the interface never sends an undocumented Webull strategy value.
  - Option-chain requests now reject mismatched responses, cancel superseded requests, clear prior-contract data while loading, refresh automatically and on window focus, and block selection once freshness expires instead of silently allowing stale quotes.
- **Options Table Clarity and Accessibility**:
  - Order and holdings tables now keep the Symbol column to the underlying ticker only. Expiration, Strike, and Call/Put appear in dedicated columns, while order timestamps are split into separate Eastern **Date** and **Time** columns.
  - Removed the repeated, truncated option-contract subtitle. Visible ticket values and accessible names now identify the same contract, quantity, order value, strategy, and legs.
- **Paper Trading Accuracy and Safety**:
  - Simulated option market orders can fill only during the regular U.S. options session (weekdays, 9:30 a.m.-4:00 p.m. Eastern). Weekend and after-hours option orders remain working rather than receiving fabricated fills.
  - Paper cancellations no longer request a two-factor code; live cancellations retain the existing six-digit authenticator requirement.
  - Paper order messages and every updated Webull surface use human-readable order-type captions rather than provider codes such as `STOP_LOSS_LIMIT`.
- **Eastern Time Consistency**:
  - User-facing dates and times across the dashboard, orders, staking, tax, charts, validation, price history, and Webull views now use `America/New_York` explicitly, including daylight-saving transitions, instead of relying on the browser timezone or treating database UTC values as local time.

## v2.59.4 (August 2026)

- **Paper Position and Reservation Safety**:
  - Active simulated sell orders now reserve their shares. A second sell, immediate sale, bracket, or combo is rejected when it would exceed the remaining unreserved long position.
  - Working simulated buys reserve cash, working short entries reserve margin, and all paper-ledger mutations for one account are serialized to prevent simultaneous orders from overspending or overselling.
  - Take-profit/stop-loss brackets and OCO combo legs share one reservation because only one mutually exclusive exit can execute. Standalone OCO legs no longer fabricate a filled primary order.
- **Short Position Clarity and Closing**:
  - Paper holdings show a positive absolute quantity with an explicit **Long** or **Short** position label; a short remains a signed liability in market value, net liquidation, and unrealized P&L calculations.
  - Selecting a simulated short exposes **Cover / Buy to Close** and prevents opening simultaneous long and short positions in the same instrument.
- **Safe Paper Reset and Existing-Ledger Reconciliation**:
  - Resetting a paper account cancels every active simulated order before clearing positions, so no orphan working order can survive a reset.
  - The v2.59.4 personal-instance upgrade cancels the known uncovered test sell orders and closes the two known test short positions. No live Webull order or holding is changed.

## v2.59.3 (August 2026)

- **Readable Webull Order Captions**:
  - Webull tables, combo-order controls, order review, cancellation, percentage-price, and 2FA dialogs now translate provider codes into consistent human-readable captions while preserving the exact backend values sent to Webull.
  - Auction orders display their full names and abbreviations, including **Market on Open (MOO)**, **Market on Close (MOC)**, and **Limit on Open (LOO)**. Sides, statuses, combo roles, and time-in-force values receive the same readable treatment where displayed.
- **Test-Mode Focus**:
  - The Webull AI Analysis tab and content are hidden while Test Mode is active. Switching into Test Mode from AI Analysis safely returns the workspace to Place Order.
- **Default Account Star**:
  - Replaced the text label beneath the Webull account selector with a star immediately to its left. An outlined star saves the selected live account as the default; a filled gold star identifies the account that opens from **Trading → Webull**.
  - The paper account cannot replace the saved live default while Test Mode is active.
- **Paper Cash Verification**:
  - Confirmed that the paper-cash card reads the authoritative simulated ledger rather than a live Webull balance or a browser-only estimate. The personal-instance upgrade reconciles the known pre-v2.59.2 short-sale proceeds that the earlier simulator did not credit.

## v2.59.2 (August 2026)

- **Paper Ledger Integrity**:
  - Paper holdings are now the sole position source while Test Mode is active and are no longer overwritten by imported live Webull holdings. Legacy duplicate equity/ETF rows are consolidated into one authoritative paper position.
  - Simulated shorts now credit sale proceeds to paper cash, render as negative positions/liabilities, calculate inverse unrealized P&L, and reduce net liquidation and buying power correctly.
  - Known ETFs such as SPY retain their ETF identity from instrument selection through confirmation, order storage, holdings, quotes, and history.
- **Order Review & Lifecycle Accuracy**:
  - Short order buttons now say **Short** rather than **Sell**. Paper and live review surfaces include trailing-stop type/amount and every enabled take-profit/stop-loss bracket price.
  - Stop, stop-limit, trailing-stop, MOO, MOC, and LOO paper orders no longer fabricate immediate weekend fills. They enter the cancellable `Working` ledger with zero filled quantity until a qualifying trigger or auction execution is available.
- **Strict Live/Paper Isolation**:
  - Open Orders, Order History, Trade Chart, Combo Orders, holdings, and account controls now show only simulated records in Test Mode and only real Webull records in live mode.
  - The server-side Test Mode setting is authoritative for placement, cancellation, market-chart holding resolution, and order reads. A stale or modified browser payload cannot opt out of Test Mode and reach the live order path.
  - Added regression coverage for ETF classification, deferred conditional/auction order behavior, and signed short-position valuation.

## v2.59.1 (August 2026)

- **Paper-Order 2FA Flow Correction**:
  - **Test-Mode-Only Bypass**: Webull simulated paper orders now proceed from the paper ticket to the normal simulated-order review confirmation without requesting a TOTP code, even when "Require 2FA for Trading" is enabled.
  - **Live Trading Protection Preserved**: Live Webull order placement continues to require the configured 2FA verification. The backend paper engine remains isolated behind explicit Test Mode and `TEST_PAPER_ACCOUNT` checks before any live Webull credential or order path is reached.
  - **Help Documentation**: Clarified that the authenticator-code exception applies only to Webull simulated paper order placement and never to live Webull orders.

## v2.59.0 (August 2026)

- **Webull Holdings Table & Trade Action Overhaul**:
  - **Direct Order Ticket Focus & Smooth Scrolling**: Fixed the "Trade" button in the Webull Holdings table. Rather than errantly jumping to the top of the browser page (`top: 0`) above the TradingView chart, clicking "Trade" on any owned asset now smoothly scrolls directly to the Order Ticket panel (`#webull-order-ticket-section`) with proper viewport offset below the navbar.
  - **Visual Ticket Load Pulse**: Added a cyan accent glow and border animation (`boxShadow: 0 0 35px rgba(56, 189, 248, 0.75)`) that illuminates the order panel upon clicking "Trade", providing immediate, unmistakable visual feedback that the selected asset has been loaded into the ticket.
  - **Complete Order Pre-population**: Clicking "Trade" now pre-populates all necessary ticket fields:
    - Automatically sets action to `SELL` for the held position.
    - Dynamically detects and sets the exact quantity held (`quantity ?? amount`), accounting for both live brokerage holdings and simulated paper positions.
    - Populates the current/last market price and immediately updates `livePrice` for accurate ticket total calculations.
    - Accurately resolves asset classes for `EQUITY`, `CRYPTO`, `OPTION` (with contract identity, expiration, strike, type, and 100x multiplier calculations), `FUTURES` (with contract symbol and selection), and `EVENT` contracts (with outcome and limit price).
  - **Centered Symbol Column**: Centered the `Symbol` column across all Webull tables (Holdings Table, Open Orders Table, and AI Signal Table) for a clean, balanced visual alignment matching standard exchange terminals. Centered both table headers (`th`) and cell contents (`td`), aligning the cryptocurrency/equity vector logos, ticker symbols, and badges seamlessly.
  - **Enhanced Trade Button Feedback**: Centered the `Action` column and added hover state micro-interactions to the "Trade" action badge.

## v2.58.0 (August 2026)

- **Comprehensive Multi-Asset QA & Architectural Scouring for Webull Trading Platform**:
  - **Full Asset Class Coverage & Verification**: Audited and confirmed flawless end-to-end wiring across all supported Webull asset classes:
    - **Equities & ETFs**: Full support for Market, Limit, Stop Loss, Stop Loss Limit, Trailing Stop Loss, Market on Open (MOO), Market on Close (MOC), and Limit on Open (LOO) orders across Regular (`CORE`), Extended (`ALL`), and Overnight (`NIGHT`) trading sessions.
    - **Fractional Cash Amount Trading**: Enhanced simulated paper trading to support fractional share purchases specified by cash dollar amount (`entrust_type: AMOUNT`, min $5.00), computing exact fractional shares based on real-time execution pricing.
    - **Cryptocurrency**: Confirmed 24/7 continuous session trading with high decimal precision on Webull Crypto pairs (e.g. `BTCUSD`, `ETHUSD`, `SOLUSD`) with proper pair formatting and isolation.
    - **Options**: Validated single-leg Call and Put options execution with strict 100x contract multiplier calculations for notional value, cash requirements, and position valuation. Added `underlying_symbol` tracking and independent contract identification to ensure different strikes and expirations on the same underlying equity never collide. Option positions now accurately mark to market using live option chain premiums rather than underlying equity prices.
    - **Futures**: Audited CME, NYMEX, COMEX, and CBOT contracts (`ES`, `NQ`, `YM`, `RTY`, `MES`, `MNQ`, `CL`, `GC`, `SI`, `BTC`), verifying contract multiplier handling and live quote fallback mapping for offline/simulated trading.
    - **Event Contracts (Prediction Markets)**: Verified limit order pricing ($0.01 to $0.99), binary outcomes (`YES` / `NO`), and quantity limits (up to 50,000 contracts).
    - **Advanced Multi-Leg Combo & Bracket Orders**: Fully wired and verified OTO (One Triggers Other), OCO (One Cancels Other), OTOCO (One Triggers One Cancels Other), and primary orders with attached Take-Profit and Stop-Loss brackets across both live OpenAPI and simulated paper trading modes.
  - **Automated Open Orders & History Tab Synchronization**:
    - Enhanced `/api/webull/open-orders` to seamlessly return working and open simulated orders when in Test Mode (`TEST_PAPER_ACCOUNT`), ensuring open orders immediately populate the table upon placement.
    - Added instant history refresh upon order placement across single, bracket, and combo orders.
  - **Paper Order Cancellation Flow**:
    - Wired `/api/webull/orders/cancel` to cleanly cancel simulated paper orders (`SIM_...`), transitioning their status to `Cancelled` and immediately reflecting in the open orders and history tables.
  - **Option Ticket Quote Synchronization**:
    - Synchronized `livePrice` state immediately upon selecting option contracts from the interactive Option Chain, ensuring real-time contract premium displays in the ticket without delay.

## v2.57.1 (August 2026)

- **Un-Funded Default for Webull Paper Trading**:
  - **Zero Initial Balance**: Webull Paper Trading accounts now initialize with an unfunded `$0.00` cash balance rather than being automatically pre-funded with money. Users have complete control over how much simulated capital to deposit.
  - **Account Reset to $0.00**: Resetting the paper trading account clears all simulated positions and resets the cash balance back to `$0.00` (instead of $10,000).
- **Streamlined Test Mode Banner**:
  - **Removed Redundant Button**: Eliminated the redundant `+ Add Funds` button from the active Test Mode banner. The primary `💰 Deposit Fake Money` button in the header serves as the sole, convenient deposit entry point.

## v2.57.0 (August 2026)

- **Full Webull Test Mode & Paper Trading Simulation**:
  - **Dedicated Settings-Style Test Mode Toggle**: Added a persistent, smooth toggle switch (`FaToggleOn` / `FaToggleOff` with `#4fd1c5` teal accent) in the Webull Trading header matching the design in Settings, allowing instant switching between Live Webull OpenAPI trading and simulated Paper Trading.
  - **Interactive Fake Money Deposit System**: Added a conditionally rendered `💰 Deposit Fake Money` button and modal that appears whenever Test Mode is enabled. Users can deposit quick presets (+$1,000, +$5,000, +$10,000), enter custom dollar amounts, or reset the simulated cash balance back to $10,000.
  - **Full Multi-Asset Simulated Execution on Real-Time Market Quotes**: Enables paper order execution across the complete Webull Trading suite—including Stocks, ETFs, Crypto, single-leg Options (with 100x contract multipliers), Futures, and Advanced combo/bracket orders. Orders fill against real-time live quotes (via Webull snapshots, Binance quotes, or Yahoo Finance fallbacks) without transmitting actual orders or risking live capital.
  - **Simulated Paper Holdings & Isolated Portfolio Engine**: Tracks simulated cash balances, positions with volume-weighted average cost bases, live mark-to-market values, and unrealized P&L in PostgreSQL (`webull_test_accounts`, `webull_test_positions`, `webull_test_orders`), completely isolated from live brokerage assets.
  - **Clear Paper Trading Status Indicators**: Added prominent cyan/teal visual indicators and banners across the trading interface, trade tickets, and confirmation dialogs to ensure full visibility when operating in Paper Trading mode.
  - **Removed Redundant "Refresh Webull" Button**: Cleaned up the Webull Trading page header by eliminating the unnecessary manual `🔄 Refresh Webull` button, as all market pricing and account interactions update dynamically.

## v2.56.3 (August 2026)

- **Frontend Sentiment Cell ReferenceError Resolution**:
  - **Fixed Undefined Identifier**: Resolved a runtime `ReferenceError: reason is not defined` in `Dashboard.jsx` (`renderSentimentCell`), ensuring the dotted underline and title tooltips render reliably across all coins and watchlists.

- **Z.AI Model Modernization (GLM-4.5-Flash)**:
  - **Replaced Delisted GLM-4.7-Flash**: Replaced the nonexistent/deprecated `glm-4.7-flash` model identifier across all configuration menus, validation routines, and backend clients with Z.AI's active, high-speed free tier model: `glm-4.5-flash`.
  - **Automated Setting Migration**: Automatically migrated all user and fallback settings configured with `glm-4.7-flash` or `glm-4.7-flashx` to `glm-4.5-flash`, restoring the Z.AI secondary AI tier to fully operational status.
  - **Active Catalog Alignment**: Updated `/api/ai/models` to reflect Z.AI's current global model catalog (`glm-4.5-flash`, `glm-4.5`, `glm-4.5-air`, `glm-4.6`, `glm-4.7`, `glm-5.2`, `glm-5.3`, `glm-5.3-flash`).

## v2.56.2 (August 2026)

- **Sentiment Reason & Thesis Explanation Integrity**:
  - **Sanitized Fallback Parsing**: Fixed an issue in `parse_sentiment_json` where non-standard JSON responses or fallback extractions could inadvertently assign structural key labels (such as `"recommendation"`, `"action"`, or `"sentiment"`) as the explanatory text. Sentiment reasons are now strictly validated and sanitized to ensure a substantive 1–2 sentence thesis rationale is always presented.
  - **Dedicated Webull Sentiment Prompts**: Explicitly enforced dedicated equity research prompts (`WEBULL_EQUITY_RESEARCH_PROMPT` and `WEBULL_CRYPTO_RESEARCH_PROMPT`) and rigorous JSON schema instructions in `services/webull_signal_service.py` to prevent falling back to open-ended long-form coin analysis essays.

- **Failover Pipeline Diagnostics in Tooltips ("Buffed Tooltip")**:
  - **Full Failover Visibility**: Enhanced the sentiment hover tooltip to display the complete failover pipeline status across all configured tiers (Primary, Secondary, Tertiary).
  - **Provider Error Diagnostics**: When failover occurs, the tooltip explicitly logs why earlier providers failed (e.g. `429 Quota Exceeded`, `429 Server Overloaded`, `Request Timed Out`), providing complete transparency into why a fallback tier succeeded.
  - **Persistent Failover Telemetry**: Added `failover_history` tracking across `ExternalSentimentSignal`, `SentimentHistory`, `Coin`, and `WatchlistCoin` database models and API payloads.

## v2.56.1 (August 2026)

- **Unified Toast Notification System**:
  - **Eliminated Ad-Hoc Fixed Banners**: Removed legacy hard-coded floating notification banners in the upper-right corner of the dashboard (`top: 20px, right: 20px`). All application errors, alerts, and operational notices now route through the unified, glassmorphic global Toast Notifications system at the bottom right.
  - **Enhanced Toast Categories**: Added dedicated visual styling, accent glow borders, and distinct status icons for `error` (❌), `system_error`, `warning` (⚠️), `success` (✅), and `info` (ℹ️) toast types.
  - **Unconditional Critical Delivery**: Ensured that critical system alerts, order feedback, and error notifications are always immediately displayed to the user even if optional background price-alert polling is disabled in user settings.
  - **Global Helper**: Introduced `frontend/src/utils/toast.js` (`showAppToast`) for consistent toast dispatching across all frontend components and modals.

- **Resilient Webull Market Data & Sentiment Fallback**:
  - **Automatic yfinance Candlestick Fallback**: Wrapped Webull historical stock and ETF bar requests (`get_webull_market_bars`) with an automatic, silent fallback to Yahoo Finance (`_fetch_yfinance_klines`) when Webull OpenAPI returns `HTTP 404: INTERNAL_SERVER_ERROR` due to unentitled historical bar subscriptions.
  - **Live Webull Snapshot Anchoring**: In `create_webull_signal`, live stock/ETF pricing is retrieved directly from Webull's working `/market-data/stocks/snapshots/list` endpoint, guaranteeing that manual and scheduled AI sentiment analysis runs smoothly without throwing market-data connection errors.
  - **NaN Bar Sanitization**: Automatically filters out unclosed after-hours bars with NaN values before snapshot calculation.

## v2.56.0 (August 2026)

- **Webull Order Ticket Layout Re-alignment**:
  - **Stacked Order Controls**: Moved Order Types directly underneath Order Side in the Webull trading ticket (`/trading/webull`), resolving inline horizontal crowding and creating an intuitive vertical progression.
  - **Balanced 3-Column Grid for Equities**: Styled Order Side as a full-width 3-column segmented grid when Equities is selected, neatly presenting `Buy`, `Sell`, and `Short` side options.

- **Webull Futures Catalogue Lookup Fix**:
  - **Mandatory Category Parameter**: Fixed HTTP 400 `Parameters not valid` error on Webull futures product-code lookups by including the required `category=US_FUTURES` query parameter in Webull OpenAPI requests.
  - **Resilient Fallbacks**: Added standard CME/CBOT/NYMEX/COMEX futures product definitions so the futures interface initializes seamlessly without error banners even if the provider lookup fluctuates.

- **Webull Event Contracts (Binary Outcome Contracts) Asset Class**:
  - **Dedicated Asset Class**: Added **Event Contracts** as a new asset class positioned immediately to the right of Futures (`Equities & ETFs` | `Crypto` | `Options (Calls & Puts)` | `Futures` | `Event Contracts`).
  - **Event Contract Setup Card**: Category explorer (`Economics`, `Financials`, `Politics`, `Climate`, `Crypto`, `Sports`), market dropdowns, and custom symbol lookups.
  - **Binary Outcome Selector**: Intuitive `YES` / `NO` toggle with real-time implied probability calculation.
  - **Webull API Compliance**: Enforces strict Webull Event Contract requirements: limit orders only ($0.01 – $0.99), DAY time in force, whole contract quantities up to 50,000 contracts, settling at $1.00 on win or $0.00 on loss.
  - **Crypto Isolation**: All cryptocurrency trading paths and rules remain completely separate and unaffected.

## v2.55.0 (August 2026)

- **Comprehensive Webull Stock Orders API Integration**:
  - **All Supported Stock Order Types**: Enabled complete support for `MARKET`, `LIMIT`, `STOP_LOSS`, `STOP_LOSS_LIMIT`, `TRAILING_STOP_LOSS`, `MARKET_ON_OPEN` (MOO), `MARKET_ON_CLOSE` (MOC), and `LIMIT_ON_OPEN` (LOO) for equities.
  - **Full Order Sides**: Added native support for `BUY`, `SELL`, and `SHORT` positions on stocks and ETFs.
  - **Flexible Entrust Modes (Shares vs. Cash)**: Added toggle between standard share quantity (`QTY`, including fractional shares) and dollar cash amount (`AMOUNT`, min $5.00) for cash-based fractional stock investing.
  - **Equity Trailing Stops**: Trailing stop loss orders for stocks with customizable dollar amount or percentage trail offsets.
  - **Attached Take-Profit / Stop-Loss Brackets**: Easily attach automated profit targets and stop loss protection directly from the standard stock order ticket.
  - **Institutional Algorithmic Execution**: Added automated algorithmic trading support for `TWAP` (Time-Weighted Average Price), `VWAP` (Volume-Weighted Average Price), and `POV` (Percentage of Volume) orders during regular hours (`CORE`) with participation caps and execution windows.
  - **Multi-Leg Combo Order Builder**: Dedicated Combo Orders tab to configure and submit native Webull conditional combo orders (`OTO`, `OCO`, `OTOCO`) with linked execution legs and unified combo order IDs.
  - **Strict Crypto Isolation**: All cryptocurrency trading paths, validations, and rules remain strictly isolated and unaffected.

## v2.54.1 (August 2026)

- **Webull Futures Catalogue Hotfix**:
  - Removed the optional Futures Product Classes request from the trading ticket path. Webull's current production deployment was returning `HTTP 400: Parameters not valid` for that parameterless informational endpoint, which blocked the ticket before contract lookup.
  - The ticket now loads product codes directly and continues to resolve exact Futures contracts through Webull's dedicated contract endpoint.

## v2.54.0 (August 2026)

- **Webull Futures Asset Class**:
  - Added a distinct **Futures** asset class with Webull product catalogue lookup, exact contract selection, entitled futures quote retrieval, historical-bar support, and live order submission using Webull's `FUTURES` instrument contract.
  - Futures orders support Buy/Sell, whole-contract quantities, Market, Limit, Stop Loss, Stop Loss Limit, and Trailing Stop Loss orders, plus DAY/GTC time in force. The server rechecks the exact tradable contract before order transmission.
  - The ticket does not invent a futures cash value: Webull calculates applicable margin and notional for the selected contract at order acceptance.
- **Webull Account Asset-Lane Protection**:
  - Crypto Webull accounts visibly disable **Stocks & ETFs**, **Options (Calls & Puts)**, and **Futures**. Non-Crypto Webull accounts visibly disable **Crypto**.
  - The same account/asset restriction is enforced server-side, preventing a modified browser request from crossing account classes.

## v2.53.3 (August 2026)

- **Web Search & News Settings Clarity**:
  - Moved the credential from the unrelated system settings area to **Settings → Web Search & News** and renamed it **NewsAPI.org API Key**.
  - The field now explains that it is used only for NewsAPI.org article-search grounding, not for an AI provider.
- **Webull Options Ticket Safety & Accuracy**:
  - Calls and puts may be bought, while sales are restricted to closing an exact contract already held in the selected Webull account—matching the underlying, CALL/PUT, strike, and expiration. Naked/short option sales are blocked in both the browser and server.
  - The ticket disables every execution control when a buy cannot afford one 100-share contract or a sell has no matching owned contract. Contract selection remains available so another contract can be chosen.
  - Order values and totals are now always valid dollar amounts (`$0.00` when no executable quantity exists), never `NaN` or a placeholder dash. Missing market quotes are no longer substituted with an invented $1.00 option premium.
  - Every submitted option order performs a fresh Webull balance/positions preflight before 2FA or order transmission, enforcing current cash coverage and exact-contract ownership.

## v2.53.2 (August 2026)

- **Sentiment Provider Chain & Error Attribution Hotfix**:
  - Sentiment analysis now uses only the primary, secondary, and tertiary AI providers explicitly selected in Settings. An unused API key can no longer silently add a provider such as OpenAI to the failover chain.
  - Corrected the Inception Labs sentiment endpoint to `api.inceptionlabs.ai`, matching the app's connection test endpoint and eliminating the prior TLS failure.
  - The Portfolio and Watchlist sentiment rows now update on every provider attempt. Their tooltip and provider/model/tier metadata show the active provider while retrying and the exact provider that most recently failed, rather than stale details from a prior successful analysis.

## v2.53.1 (August 2026)

- **Hotfix: Sentiment Refresh TypeError**:
  - Fixed a crash (`TypeError: O.toUpperCase is not a function`) that occurred when clicking the sentiment refresh button on any Binance portfolio coin. The `handleSingleSentimentRefresh` function was receiving the full coin object as `target` but only extracted `.symbol` when `source === 'webull'`, leaving a bare object when called from Binance portfolio rows. Now correctly extracts `target.symbol` for any object target and also detects Webull holdings via `is_external` in addition to `source === 'webull'` for robustness.

## v2.53.0 (August 2026)

- **Webull Options Chain Layout, Expiration Dropdown & Live Search Upgrade**:
  - **Inline Order Panel Placement**: Repositioned the Options Chain Matrix to display directly inside the Order Panel, immediately below the Asset Class switcher (`Equities & ETFs | Crypto | Options`) when Options is selected, creating a natural and intuitive top-to-bottom workflow.
  - **Clean Expiration Date Dropdown**: Replaced the horizontal sliding pills bar with a sleek, theme-aware `<select>` dropdown displaying clear expiration dates and Days to Expiration (DTE), organized seamlessly alongside the View Mode toggle and strike range selector.
  - **Live Searchable Stock Selector with Favorites**: Upgraded the underlying stock selector from a static text field and lookup button to the full-featured `SearchablePairSelect` component (`traditional` mode). Supports instant live filtering as you type, custom ticker typing, holding badges (`💼 My Holdings`), and pinning favorite stocks to the top (`⭐ Pinned / Favorites`).
  - **Bidirectional Symbol Synchronization**: Selecting any stock or ETF in the Options Chain automatically updates the underlying contract, loads the option book, and updates the active order ticket.

## v2.52.1 (August 2026)

- **Webull Options Chain Table Complete Theme Awareness**:
  - **Dark & Light Mode Parity**: Fixed an issue where unscoped `td` rules from `light-theme.css` bled white cell backgrounds into the Options Chain in dark mode.
  - **Airtight Specificity in `WebullOptionChain.css`**: Explicitly declared dark mode backgrounds (`#0f172a`, alternating `#131d31`, hover `#1e293b`) with `!important` to eliminate white cell bleaching and ensure high contrast in dark mode.
  - **Dynamic Theme Synchronization**: Added a real-time DOM mutation observer in `WebullOptionChain.jsx` to dynamically detect theme toggle changes (`light-mode` vs `dark-mode`) and update styling immediately without page reloads.
  - **Scoped Table Selectors in `light-theme.css`**: Prefixed global table rules with `body.light-mode` to prevent theme leakage across pages.

## v2.52.0 (August 2026)

- **Full Webull Options Trading & Live Options Chain/Book**:
  - **Live Options Chain Matrix**: Added a professional, high-performance Straddle-view Options Chain (`WebullOptionChain`) to Webull Trading. View Calls on the left, Strike Price in the center, and Puts on the right with real-time Bids, Asks, Midpoints, Last Prices, Volume, Open Interest, and Implied Volatility (IV).
  - **Dynamic Expiration Date Selector**: Scrollable horizontal expiration pill bar displaying valid expiration dates and Days to Expiration (`DTE`) tags (e.g., `0DTE`, `7d`, `14d`, `30d`, `LEAPS`).
  - **In-The-Money (ITM) vs Out-of-The-Money (OTM) Shading**: Subtle visual color coding distinguishing ITM Calls and Puts, with a distinct real-time spot price divider line tracking the underlying stock price.
  - **Click-to-Trade Order Ticket Integration**: Clicking any **Ask** price instantly populates the order ticket to **BUY** (Call or Put) at the Ask/Mid limit price; clicking any **Bid** price instantly populates the ticket to **SELL** at the Bid/Mid limit price. Eliminates manual guessing of strikes, dates, and contracts.
  - **Multi-Source Market Data Engine**: Fixed Webull OpenAPI option contract catalog query parameters (`category: 'US_OPTION'`, `status: 'LISTING'`) and established a resilient market data bridge with Yahoo Finance (`yfinance`) for live and settled off-hours Bids, Asks, and Greeks when Webull developer accounts lack standalone OPRA non-display subscriptions.
  - **Off-Hours / After-Hours Safeguards**: Off-hours and weekend quotes are clearly badged with "Market Closed (Closing Quotes)", allowing comprehensive option analysis and order staging even when markets are shut.

## v2.51.1 (August 2026)

- **Orders Page Market Analysis & Portfolio Review Rehydration**:
  - Normalized backend workflow responses (`/api/ai/workflow-latest`) and live workflow executions (`/api/ai/market-analysis-workflow`, `/api/ai/portfolio-review-workflow`), ensuring existing database records and newly generated analyses display immediately with full Markdown formatting, timestamp, and model metadata rather than showing "Not available".
  - Fixed prompt modal retrieval (`/api/ai/*-workflow-prompt`) in `Orders.jsx` to load and display saved custom prompts properly.
- **Binance AI Analysis Dashboard Cleanup**:
  - Removed duplicate Market Analysis and Portfolio Review sections from the bottom of the Binance AI Analysis page (`AIDashboard.jsx`), cleanly scoping macro and portfolio workflows to their dedicated tabs on the Orders page.
- **Webull AI Analysis Theme Awareness & Parity**:
  - Updated the Webull Historical Prediction Ledger table container and class hierarchy (`prediction-ledger-table` within `prediction-table-container`) to match Binance's styling, ensuring seamless dark mode and light mode theme awareness and eliminating unstyled white header blocks.
  - Removed manual "Generate Thesis" button and ad-hoc trigger box from the Webull AI Analysis tab; predictions are generated based on configured user settings and automated schedules.
  - Removed separate "Scheduled Webull AI Research Automation" card from the Webull tab. Webull signals now use the exact same universal sentiment settings that Binance uses:
    - Cadence (`sentiment_analysis_frequency_hours`)
    - Horizon (`forecast_horizon_hours`)
    - Analysis windows (`ai_analysis_window_start`, `ai_analysis_window_end`)
    - Global AI enable toggle (`is_ai_enabled`)
  - Integrated Webull holdings into manual force runs ("Run Sentiment Analysis Now" in Settings), evaluating Webull assets concurrently with Binance portfolio and watchlist coins.

## v2.51.0 (August 2026)

- **Webull AI Analysis Parity with Binance**: Completely revamped the Webull AI Analysis tab in the Webull Trading terminal (`WebullTrading.jsx`) with a dedicated `WebullAIDashboard` component matching Binance's AI Analysis interface in look, feel, and functionality:
  - **Empirical Performance KPIs**: Scorecards tracking Webull Overall Accuracy, Bullish Win Rate, Bearish Win Rate, and Top Performing Model.
  - **Interactive Sentiment Timeline Chart**: Visualizes Webull asset price history with overlaid sentiment prediction markers and outcome badges (`Correct`, `Wrong`, `Neutral`), featuring an automated `yfinance` candlestick bar fallback for equities and ETFs.
  - **Historical Prediction Ledger**: Paginated, sortable ledger of Webull signals (`ExternalSentimentSignal`) with detailed asset-class badges (`STOCK`, `ETF`, `CRYPTO`, `OPTION`), initial prices, forecast horizons, evaluation prices, returns, outcome badges, and a "Thesis" button opening the full Markdown-formatted research modal.
  - **Recommendation Type Accuracy & AI Model Leaderboard**: Empirical win rates and correct/wrong/neutral breakdowns for each recommendation signal, plus a competitive leaderboard comparing AI models (OpenAI, Gemini, Perplexity, Z.AI, DeepSeek).
  - **On-Demand AI Sentiment Prediction & Thesis Engine**: Interactive asset selector across all Webull holdings and watchlist items with an on-demand thesis generator (`Create Stored Signal / Generate Thesis`).
  - **Flexible Market-Hours Handling**: Allows manual on-demand Webull AI analysis anytime (including evenings and weekends) anchored to the latest available closing bars and market data.
- **Universal Market Analysis & Portfolio Review Tabs on Orders Page**: Added two dedicated, full-width tabs to the Orders page (`Orders.jsx`):
  - **Market Analysis Tab**: Full-width universal macro analysis covering traditional securities (S&P 500, Nasdaq, 10Y Yields, Federal Reserve policy) and crypto markets (Bitcoin dominance, liquidity, market structure), with an on-demand refresh trigger, prompt viewer modal, and AI provider/model badge.
  - **Portfolio Review Tab**: Full-width universal portfolio intelligence evaluating cross-broker asset allocation, sector weights, concentration risks, and tactical rebalancing across all connected Binance.US and Webull holdings, with an on-demand refresh trigger, prompt viewer modal, and AI provider/model badge.
- **Webull AI Accuracy Backend API**: Added `/api/webull/ai-accuracy` and wired `build_webull_accuracy_response` to aggregate empirical metrics from `ExternalSentimentSignal`, supporting `broker=webull` across sentiment accuracy endpoints.

## v2.50.0 (August 2026)

- **Universal Multi-Asset AI Agentic Workflow Prompts**: Updated all 6 agentic workflow prompts (`Market Analysis`, `Portfolio Review`, `Asset & News Analysis`, `Portfolio Sentiment Analysis`, `Watchlist Sentiment Analysis`, and `AI Copilot Prompts` [Pre-Search and Post-Search stages]) to provide explicit, context-aware instructions for both cryptocurrency and traditional securities (equities, ETFs, options) across Binance.US and Webull.
- **Asset-Aware Agentic Pipeline & Search Grounding**: Upgraded Stage 1 search query generation and Stage 2 news retrieval to dynamically recognize asset classes, generating equity-specific queries (earnings, SEC filings, analyst consensus) for stocks and protocol-specific queries (on-chain metrics, tokenomics, protocol upgrades) for cryptocurrencies. Wired Webull equity and crypto analyses directly into customizable user prompt overrides.
- **Universal Multi-Asset Sentiment Strategy & Thresholds**: Sentiment variable rules (`Buy Immediately`, `Consider Buying`, `Hold`, `Consider Selling`, `Sell Immediately`), lookback horizons, and evaluation windows now apply universally to all traditional securities and cryptocurrencies across Binance.US and Webull.
- **Settings Page Tabbed Layout Navigation**: Redesigned the Settings interface with an organized, responsive 7-tab navigation bar (`Exchange & Broker APIs`, `AI Providers & Models`, `AI Workflow Prompts`, `Sentiment & Strategy`, `Web Search & News`, `Security & 2FA`, `Notifications & System`) eliminating long vertical scrolling while keeping primary actions (Save Settings, Run Sentiment Now, Sync Coins, Upgrade App) pinned at the top.

## v2.49.0 (August 2026)

- **Webull Percentage Order Price Helper**: Added the dual-mode `%` price calculation modal to the Webull Trading terminal for `LIMIT`, `STOP_LOSS`, and `STOP_LOSS_LIMIT` orders, allowing price generation anchored to either Average Entry cost basis or the live market price.
- **Stop-Loss Limit Dual-Price Protection for Equities & Crypto**: Supports fraction-of-a-fraction buffered stop-loss limit placement on Webull, automatically calculating the stop trigger price and limit execution price to safeguard against severe price slippage while ensuring fast fills.
- **Order Value Allocation Shortcut**: Added a percentage quick-step shortcut to the Order Value ($ USD) field to rapidly allocate buying power or position size (25%, 50%, 75%, 100%).
- **Smart Trading Session Routing for Cash Accounts**: Implemented automated US Eastern Time (ET) session defaulting for cash-based accounts (Individual Cash, Roth IRA, Rollover IRA). Automatically defaults to Regular Hours (`CORE`: 9:30 AM–4:00 PM ET), Extended Hours (`ALL`: 4:00 PM–8:00 PM & 4:00 AM–9:30 AM ET), or Overnight Hours (`NIGHT`: 8:00 PM–4:00 AM ET and weekends), while keeping the dropdown freely editable.

## v2.48.0 (August 2026)

- **Market Session-Aware Asset Performance Calculations**: Resolved missing percentage returns (dashes) for traditional securities (stocks and ETFs like NVDA, SPCX, TSLA). Implemented market session-aware calculation windows that match against historical trading sessions, daily market closes, and hourly trading candles across market closes and weekends.
- **Unified Asset Visibility Customization**: Enhanced the Asset Performance modal (`✏️`) to include all connected Webull securities (stocks, ETFs) alongside cryptocurrencies from Binance.US and Webull.
- **Stablecoin Filtering**: Filtered out `USD` and `USDT` from the Asset Performance customize modal and performance displays, ensuring non-moving stablecoins do not clutter asset metrics.
- **Search and Panel Header Alignment**: Updated the modal search input placeholder to `"Search crypto or securities..."` and updated the panel header to `"Binance Asset Performance"` when filtering by Binance.US.

## v2.47.0 (August 2026)

- **Average Entry & Current Price Percentage Order Helper**: Added an intuitive `%` calculation button across spot order types in the Trading terminal (`LIMIT`, `LIMIT_MAKER`, `STOP_LOSS_LIMIT`, `TAKE_PROFIT_LIMIT`, and `OCO`). Clicking `%` opens a dual-mode calculator allowing price generation from either the user's Average Entry price or the live Current Market Price.
- **Stop-Loss Limit Automatic Dual-Price Population ("Fraction-of-a-Fraction")**: Entering a percentage drop on a Stop-Loss Limit sell order automatically calculates and populates both the Stop Price trigger ($P\%$ drop from reference) and the Limit Price execution cap (with a $P\%$ buffer of the difference below the trigger), preventing severe price degradation while ensuring fast execution fills.
- **Safety Guardrail Against Invalid Stop Placement**: Prevents placing a Sell Stop-Loss order above current market price when a coin is already in a drawdown from Average Entry, alerting the user with current P&L percentage and guiding them to switch to the Current Price tab.
- **Symmetric OCO & Buy Order Support**: Full support for One-Cancels-the-Other (OCO) orders with 1-click symmetric $\pm P\%$ swings (profit target and stop loss populated simultaneously) as well as Buy-side order workflows (dip accumulation, breakout stops, and dual OCO buy setups). All populated values remain completely editable.

## v2.46.0 (August 2026)

- **Complete in-app Webull guide**: Added a dedicated, linked Help section with the exact Settings workflow for selecting the matching Production/Sandbox environment, securely saving Webull OpenAPI credentials, completing the in-app/SMS verification, selecting accounts, loading the read-only preview, and importing account-scoped portfolio snapshots.
- **Webull trading safety reference**: Documented default-account selection, asset-preserving Webull navigation, account/source isolation, provider-specific order review and cancellation, the app-level six-digit 2FA confirmation, and Regular/Extended/Overnight fractional-share constraints.
- **Unified Help accuracy**: Updated Quick Start, access requirements, security, 2FA, settings, and troubleshooting guidance so Binance.US and Webull capabilities and boundaries are described consistently.

## v2.45.0 (August 2026)

- **Global product rename**: The active application name is now **Crypto & Securities Dashboard** across the native header logo, footer, browser metadata, onboarding, authentication, Help, legal, support, 2FA, and AI Copilot surfaces.
- **New native dashboard mark**: Replaced the former clock-style brand mark with an equity-and-portfolio trend icon that matches the combined crypto and securities scope. The responsive wordmark remains readable across desktop and mobile layouts.
- **Release and documentation alignment**: Updated active source documentation, default AI prompts, upgrade messaging, and GitHub distribution metadata. Existing domains, repository and folder names, Cloudflare configuration, service/database identifiers, and historical releases were intentionally preserved.

## v2.44.1 (August 2026)

- **Connected Webull account layout hotfix**: Rebuilt the account-selection row as a dedicated responsive grid. Checkboxes retain their native 18px control size, account name, masked ID, and account-type badge remain aligned, and narrow screens stack the masked ID cleanly rather than overlapping account details. This prevents Settings’ generic full-width input rule from expanding the account checkbox across its row.

## v2.44.0 (August 2026)

- **Webull current trading-contract verification**: Webull account discovery, balance/position reads, placement, and cancellation now prefer the current unified Trading API paths and order-envelope schema, retaining the legacy paths only as a compatibility fallback. Stock/ETF, crypto, and option requests use their supported order types and time-in-force values.
- **Exact option contract execution**: A Webull option ticket now carries the imported holding identity through navigation and execution. The server requires and submits the exact underlying, call/put side, strike, expiration, and one-leg quantity; it cannot silently turn an option deep link into an equity order. The ticket also uses the contract-specific quote endpoint for its live price when entitled.
- **Account-safe Webull scope**: Browser responses now expose a masked account label only, retain imported cash snapshots for buying-power display, and enforce that every Webull open-order, placement, cancellation, and saved default-account request belongs to the connected user’s enabled account set.
- **Documentation reconciliation**: Corrected the Help and exchange checklist to distinguish implemented Webull option execution from the intentionally unavailable options AI workflow, and recorded the remaining production-canary acceptance item. Automated verification does not submit a real order.

## v2.43.1 (August 2026)

- **Webull fractional-share order flow**: The selected Webull account’s fractional equity/ETF position now remains fractional in the ticket—so `MAX` correctly carries a holding such as `0.11 TSLA` instead of rounding it to zero. The quantity/value inputs and percentage controls apply the same session-aware precision.
- **Session-aware Webull validation**: Fractional stock/ETF orders are accepted only for Webull **Regular Hours (CORE)** Market orders, with the documented `0 < quantity ≤ 1` and `$5` minimum safeguards. Extended and Overnight sessions require whole shares and explain the constraint directly in the ticket; the server enforces the same policy against direct requests.
- **Shared Webull order 2FA modal**: A valid Webull order with app trading 2FA enabled now opens the native shared 2FA modal before submission. It identifies Webull, the selected account, asset, order type, quantity, estimated value, time-in-force, and trading session.
- **Visible ticket errors**: Invalid quantities, insufficient selected-account holdings, and unsupported session/order combinations now appear inline next to Quantity rather than failing silently.

## v2.43.0 (August 2026)

- **Webull Options Execution & Risk Model**: Introduced the option ticket and contract-level single-leg workflow (`CALL` / `PUT`), with the provider-envelope and exact-leg execution corrections verified in v2.44.0.
- **Interactive Options Trading Terminal**: Added an Asset Class switcher to Webull Trading allowing seamless switching between Equities/ETFs, Crypto, and Options. Clicking any option holding in the portfolio automatically populates the option contract ticket for 1-click execution.
- **Webull AI Options Boundary**: Added contract-safe option chart and quote identity. Options AI remains intentionally unavailable pending a dedicated options prompt and risk model; v2.44.0 reconciles this status across the product documentation.
- **Dashboard Webull Quick Trade Widget**: Upgraded the Dashboard Quick Trade widget to support Webull stocks, ETFs, and crypto with 1-click launch to Webull Trading, and added an exchange switcher toggle in All Accounts scope.
- **Dashboard Multi-Timeframe Performance for Webull**: Activated the 7-day, 3-day, 1-day, 12-hour, and 1-hour performance metrics table for Webull assets on the Dashboard with dynamic scope filtering and direct trading deep-links.

## v2.42.0 (August 2026)

- **7-Day Performance Chart on Symbol Hover for Webull Assets**: Enabled interactive 7-day sparkline performance chart popups on all Webull equities, ETFs, and assets in both the Portfolio and Watchlist tables. Backfilled hourly price candles with real-time stock/ETF market data.
- **Direct Webull Trading Navigation on Symbol Click**: Clicking any Webull asset in the Portfolio or Watchlist table (or inside the 7-day performance chart popup) now navigates directly to `/trading/webull` with that exact stock ticker, asset type, and side pre-selected.

## v2.41.3 (August 2026)

- **Hotfix for Binance Trading Page Estimated Fee State**: Restored missing `estimatedFee` React state hook in `Trading.jsx`. Resolves the `ReferenceError: setEstimatedFee is not defined` runtime crash on the Binance Trading page.

## v2.41.2 (August 2026)

- **Hotfix for Binance Trading Page Balance Slider**: Restored missing `balancePercentage` React state hook in `Trading.jsx`. Resolves the `ReferenceError: balancePercentage is not defined` runtime crash when opening the Binance Trading page.

## v2.41.1 (August 2026)

- **Hardened AI Copilot Native OCO Understanding**: Embedded explicit exchange architecture directives in the AI Copilot prompt engine. On Binance/Binance.US, OCO orders are natively managed by the exchange matching engine as linked Order Lists (`orderListId`) containing a `STOP_LOSS_LIMIT` leg and a `LIMIT_MAKER` leg. The Copilot is explicitly instructed that these legs are verified, natively linked orders that automatically trigger mutual cancellation upon execution, preventing false claims that orders are "unlinked" or lack an "OCO wrapper".
- **Enhanced OCO Telemetry Formatting**: Open OCO brackets now explicitly display their verified native Binance.US status, Binance Order IDs, and confirmed matching engine linkage in the Copilot context feed.

## v2.41.0 (August 2026)

- **Comprehensive Database Context for AI Copilot**: The AI Copilot now receives complete real-time awareness across your entire portfolio ecosystem, including active pending orders, full multi-asset balances, complete watchlist telemetry, and recent transaction history.
- **Intelligent OCO Bracket Awareness**: Open OCO (One-Cancels-the-Other) buy and sell orders are now properly identified and grouped by their `orderListId`, presenting the upper stop-loss limit trigger/limit price, the lower limit-maker price, exact quantities, and mutual cancellation rules to the AI.
- **Context-Aware Conversational Symbol Resolution**: When questions ask about orders (e.g. "Do you think my pending OCO order is sensible?"), the Copilot intelligently resolves intent by inspecting active exchange orders and recent conversation context rather than defaulting to an arbitrary portfolio holding.
- **Multi-Asset Holdings & Webull Integration**: Integrated imported Webull equities, ETFs, crypto, and option contracts alongside Binance.US spot balances and cash reserves (USDT/USD), displaying combined portfolio net worth.
- **Transaction History & Watchlist Feed**: Recent completed trade executions (with realized gains/losses, cost basis, and fees) and active watchlist coins (with live prices, alert thresholds, and sentiment notes) are now continuously fed into the Copilot.

## v2.40.4 (August 2026)

- **Order History & Combined Orders Fee Columns**: Added a dedicated Fee column to both the Binance.US Order History table and the Combined Orders table, displaying exact transaction commissions (e.g. BNB or USD).
- **Accurate Trade Commission & Gain/Loss Calculation**: Stop-limit and filled orders now retrieve trade execution details from Binance (`myTrades`) to record actual commission values (including BNB fees converted to USD at market prices). Realized gain/loss and short-term/loss classifications are automatically calculated for all sell activity records.
- **Improved Tax Report Display**: Fixed missing dashes (`—`) for fees, gain/loss, and trade classifications in the Tax Report ledger, with support for sub-cent fractional fee amounts.
- **Order History Loading State**: Binance.US Order History now displays a clean loading state while fetching records, eliminating the brief "No orders yet" placeholder flicker.

## v2.40.3 (August 2026)

- **Secure native cancellation confirmation**: Combined Orders and Webull Trading Open Orders now use the app's theme-aware cancellation modal rather than a browser prompt. It identifies the provider, account, side, order type, quantity, symbol, and price (or the active Auto-Buy/Auto-Sell trigger) before requiring the six-digit 2FA code.
- **Server-enforced cancellation 2FA**: Webull cancellations and app Auto-Buy/Auto-Sell trigger cancellations independently validate the user's enabled 2FA code before any provider request or trigger update, preventing direct API bypasses.

## v2.40.2 (August 2026)

- **Account-only Combined Orders column**: The centered Account column now shows only the owning account—`Binance.US` or the masked Webull account. Auto-Buy/Auto-Sell labels no longer appear there; their order identity remains in Side and Type.
- **Instant Combined Order History**: The combined History tab now reads the persisted `real_orders` and `all_activities` ledger only. It no longer starts Binance.US per-symbol or Webull history API scans when opened.

## v2.40.1 (August 2026)

- **Combined automation-order identity**: Combined Orders now also recognizes active app Auto-Buy and Auto-Sell triggers that use the established `AUTO_BUY`/`AUTO_SELL` order type. They correctly appear under the **Auto** source and **Automation** product filters with the `Crypto Alert App trigger` account label.

## v2.40.0 (August 2026)

- **Combined Orders filters**: Filter both Open Orders and Order History by source, account, symbol, product type, status, and time range without triggering additional exchange reads. Rows now include their source plus safe account/automation context and sort newest-first.
- **Resolved exchange-aware acceptance criteria**: The navigation and account-view checklist now records the explicit route, fallback, persistence, source-boundary, data-refresh, accessibility, and release/rollback rules used by the app. Every resolved item is checked so new scope is unambiguous.

## v2.39.1 (August 2026)

- **Combined app automation orders**: The Open Orders view now reads the unified Binance.US plus in-app order feed, so active Auto-Buy and Auto-Sell volatility triggers appear as `ACTIVE` orders with their automation badge. Cancelling one from this view disables the app trigger rather than attempting to cancel a nonexistent Binance.US order.
- **Correct Webull trading holdings**: The live portfolio response now includes imported, read-only Webull positions. The Webull ticket therefore matches its selected account to the correct position—such as the Individual Cash NVDA quantity—instead of displaying zero shares.
- **Entitlement-safe Webull quote**: The Webull price card now requests the basic stock snapshot only. It no longer requests the separately subscribed overnight quote field that caused Webull to reject the entire price request and leave the card at “Market Price.”

## v2.39.0 (August 2026)

- **Webull account-safe trading**: The Webull Trading account selector can now save a default account. The page uses that preference (or a Cash/equity account fallback) instead of silently defaulting to crypto, and holdings such as TSLA are resolved strictly within the selected account.
- **Webull live quote and sessions**: The trade ticket now reads the signed Webull market-snapshot endpoint, refreshes its quote every 30 seconds, and supports Regular (`CORE`), Including Extended (`ALL`), and Overnight (`NIGHT`) trading sessions for equities/ETFs.
- **Faster combined open orders**: Combined Orders streams account-scoped Webull open-order results into the table as each rate-limited account request completes rather than waiting for every account.
- **Complete automated order ledger**: Auto-Buy and Auto-Sell executions are now normalized from the activity ledger, including their order IDs, quote pair, fill price, and visible automation label.
- **Footer version integrity**: The footer now derives its version directly from `package.json`, keeping the displayed version synchronized with each release.

## v2.38.5 (August 2026)

- **Fast combined Orders loading**: The Open Orders view now renders after the Binance.US request instead of waiting for Webull to read every connected account. Webull orders merge in as soon as that read completes, with a visible refresh status.
- **On-demand history**: The expensive exchange-wide Order History scan now starts only when its tab is opened, preventing it from competing with the initial combined Orders load.

## v2.38.4 (August 2026)

### Webull Stock/ETF Table Navigation

- **Portfolio and Watchlist coverage**: Stock/ETF Buy actions in the Portfolio and Watchlist tables now open Webull Trading with the selected stock/ETF and the individual cash account preference.
- **Safe Webull stock sales**: Existing Webull stock/ETF Sell actions retain the account that owns the position.

## v2.38.3 (August 2026)

### Stock Mover Webull Navigation

- **Correct chart and orders context**: Clicking a Top Stock Gainers & Losers row now passes the selected ticker and explicitly opens Webull Trading in Stock / ETF mode.
- **Individual cash account preference**: Stock-mover navigation selects the enabled individual cash account when available, instead of inheriting a prior crypto account selection.

## v2.38.2 (August 2026)

### Watchlist Search Width Correction

- **Exact desktop width**: Enforced the Watchlist search picker at one-third of the available table width, including when other dashboard layout styles are loaded. The field still expands to full width on mobile.

## v2.38.1 (August 2026)

### Watchlist Symbol Search Hotfix

- **Restored crypto results**: Passed the required public Binance.US client to the exchange-info cache, so searches once again return matching listed crypto assets.
- **Resilient stock/ETF results**: Added a Yahoo Finance public-search fallback when the yfinance search client cannot return matches.
- **Cleaner picker layout**: Reduced the desktop Watchlist search field to one-third of the table width while preserving its full-width mobile layout.

## v2.33.0 (August 2026)

### Webull Options Data Foundation

- **Contract-safe option positions**: Webull imports now preserve a position's contract ID, underlying, expiration, strike, call/put type, and multiplier whenever Webull supplies them. A static contract lookup can resolve a missing ID only when it finds one unambiguous match—never by guessing from the underlying.
- **Option-specific chart and quote data**: The Webull Trade Chart now requests option bars, quote data, and Greeks through Webull's dedicated option endpoints using the resolved contract ID. The option panel shows its contract identity, quote/IV, and available Greeks. It will never substitute an underlying equity chart.
- **Entitlement-aware behavior**: The app clearly retains the contract details while reporting unavailable option quotes when OPRA OpenAPI data is not entitled, delayed, closed, or temporarily unavailable. No options order endpoint is used.

## v2.32.0 (August 2026)

### Webull Stored AI Signals

- **Correct-by-construction signal lifecycle**: Webull crypto and equity/ETF analysis now creates a stored, provider-neutral forecast with its entry price, prompt family, fixed horizon, immutable grading settings, and eventual outcome. It is deliberately separate from Binance's history/chart implementation, so external instruments never masquerade as Binance symbols.
- **Manual and scheduled use the same pipeline**: The Webull AI tab can create an on-demand stored signal and lists its tracking or graded outcome. Optional scheduling uses the exact same pipeline with separate crypto and equity/ETF cadence and forecast settings; it is off by default so connecting Webull cannot create surprise AI usage. Equity/ETF signals and grading wait for regular U.S. market hours rather than using a stale close.
- **Read-only safety and asset separation**: Crypto and equity/ETF prompts are separated; Webull analysis never sends an order. Options remain clearly unavailable until contract-level identifier and market-data mapping are implemented.

## v2.31.0 (August 2026)

### Webull Trade Chart

- **Read-only charting for imported Webull holdings**: The Webull Trade Chart now selects an imported holding and renders its Webull price history across 1D through ALL, defaulting to 1 Month.
- **Correct asset routing**: Equities and ETFs use Webull stock historical bars; crypto uses Webull crypto historical bars. Completed Webull purchases and sales are overlaid only for the selected symbol.
- **Safe options handling**: Imported option positions are selectable but show a clear unavailable state until an option-contract identifier mapping is implemented, preventing a chart for the wrong contract.


## v2.30.2 (August 2026)

- **Webull Brand Mark**: Replaced the temporary emoji in Portfolio source identity with the supplied blue Webull bull mark. It remains compact and exposes “Webull” on hover.

## v2.30.1 (August 2026)

- **Reliable Exchange Menu**: Fixed the Trading exchange menu to remain open while moving into it, close only on an outside click or Escape, and respect the active light/dark theme.
- **Correct Webull Order Rows**: Flattened Webull grouped order responses so their actual order-leg symbols, sides, types, quantities, timestamps, and statuses display instead of `UNKNOWN` placeholders.
- **Complete Orders Views**: Combined Open Orders now falls back to qualifying Binance.US all-order records when the dedicated open-order response lags. Combined history retains Webull rows, all history views paginate at 50 by default with 20/50/100/200 choices, and light mode uses a visible table scrollbar.
- **Compact Portfolio Identity**: Portfolio rows now use hoverable Binance and Webull source icons, followed by a crypto or traditional-asset icon, conserving table space without losing context.

## v2.30.0 (August 2026)

- **Exchange-Aware Navigation**: Replaced the single Trading link with an extensible exchange menu for Binance.US and Webull, moved AI Analysis into the Binance.US Trading tabs, and preserved existing `/trading` and `/ai-analysis` links for continuity.
- **Dedicated Webull Workspace**: Added the read-only Webull Trading page with Place Order, Open Orders, Order History, Trade Chart, and AI Analysis tabs. Webull rows remain visibly read-only and never expose Binance.US trading actions.
- **Combined Orders**: Added a top-level Orders destination that combines Binance.US and Webull open orders and history with explicit source labels. Webull open orders are retrieved through a read-only API path and are managed in Webull.
- **Documentation**: Updated the in-app Help and exchange-aware implementation checklist to describe the new navigation, source boundaries, and staged Webull AI plan.

## v2.29.0 (August 2026)

- **Dashboard Account Scope**: Added a persistent, right-aligned Dashboard selector for All Accounts, Binance.US, and Webull. Portfolio rows, allocations, totals, risk values, and Binance-only controls now respect the selected scope; Webull-only selections explicitly avoid Binance actions.

## v2.28.0 (August 2026)

- **Unified Webull Order History**: The existing Trading and Recent Order History views now merge read-only historical Webull orders across all connected accounts. Each appears with a Webull origin label and cannot open Binance.US trading or any order-management action.

## v2.27.0 (August 2026)

- **Unified Webull Portfolio Import**: Import the validated all-account Webull preview into a persistent, read-only portfolio snapshot. Webull holdings appear alongside Binance.US holdings with a visible Webull badge, while account-level net-liquidation values contribute to dashboard totals and future portfolio-history samples without double-counting cash.
- **Exchange Safety Boundary**: Imported Webull rows cannot use Binance.US alerts, AI sentiment, news, staking, hide, auto-trading, or Buy/Sell controls. Binance.US trading behavior is unchanged.

## v2.26.0 (August 2026)

### Webull All-Accounts Portfolio Preview
- **All-Accounts Selection**: Added a persisted all-connected-Webull-accounts selection mode, so the approved choice also includes newly discovered accounts.
- **Read-only Portfolio Preview**: Settings can retrieve each selected account's balance summary and open positions under Webull's production rate limits. It does not merge, persist, trade, or change Binance.US data.
- **Version Bump**: Transitioned version to `v2.26.0`.

## v2.25.0 (August 2026)

### Webull Account Discovery
- **Read-only Discovery**: After a verified Webull connection, Settings retrieves the associated account list and shows account types with masked IDs.
- **Selection Gate**: Discovery intentionally does not import balances, positions, activities, or orders. It provides the information needed for the user to decide which Webull account(s) should be included next.
- **Version Bump**: Transitioned version to `v2.25.0`.

## v2.24.3 (August 2026)

### Webull Token Endpoint Compatibility
- **SDK-first Token Requests**: Webull token creation and status checks now use the endpoint used by Webull's official Python SDK first, with the newer documented endpoint retained as a compatibility fallback.
- **Version Bump**: Transitioned version to `v2.24.3`.

## v2.24.2 (August 2026)

### Webull Production 2FA Verification
- **Secure Token Lifecycle**: Added encrypted, environment-bound storage for Webull’s access token, with token creation, status checks, expiry tracking, and automatic clearing whenever the Webull credentials or selected environment change.
- **Guided Approval Flow**: Settings now starts the Webull app/SMS verification request, gives the exact in-app approval steps, and checks the pending verification without exposing the token or secrets to the browser.
- **Read-only Validation**: Once Webull reports a normal token, the app performs only the existing signed account-list check. Position sync, portfolio merging, and trading remain out of scope.
- **Version Bump**: Transitioned version to `v2.24.2`.

## v2.24.1 (August 2026)

### Webull Runtime Compatibility Fix
- **No Encryption Downgrade**: Replaced the incompatible Webull SDK runtime dependency with a focused, read-only Webull account-list client that follows Webull's documented HMAC-SHA1 signing protocol. The app retains its current cryptography security dependency.
- **Verified Request Signing**: Added a regression test against Webull's published signature example, alongside connection-response tests.
- **Version Bump**: Transitioned version to `v2.24.1`.

## v2.24.0 (August 2026)

### Webull Connection Foundation
- **Encrypted Webull Credentials**: Added dedicated Webull App Key and App Secret storage using the app's existing encrypted-at-rest credential handling. Saved Webull secrets are never returned by the Settings API; the UI receives only a configured status and masked inputs.
- **Production and Sandbox Setup**: Settings now lets you select the matching Webull API environment, save its credentials, and use a read-only account-list request to test the connection.
- **Safety Gate**: This release does not sync Webull positions, combine portfolios, place Webull orders, or enable options trading. Those remain subsequent gated steps after a successful credential test.
- **Webull API Compatibility**: Uses Webull's documented request-signing protocol for the connection check while preserving the app's existing credential-encryption dependencies.
- **Help Update**: Documented the new connection setup and its current read-only scope.
- **Version Bump**: Transitioned version to `v2.24.0`.

## v2.23.0 (August 2026)

### Dashboard Trading Navigation
- **Allocation Slice Navigation**: Clicking an Allocations donut slice now opens that asset in the local Trading page.
- **Consistent Coin Links**: Coin symbols in Coin Performance and Recent Order History now open the same preferred market.
- **Correct Quote Selection**: Dashboard navigation prefers a live `COIN/USDT` pair, falls back to `COIN/USD` only when necessary, and routes USD or USDT itself to the valid `USDT/USD` market.
- **Version Bump**: Transitioned version to `v2.23.0`.

## v2.22.2 (August 2026)

### Reliable GitHub Release Upgrades
- **Live Release Lookup**: The in-app Upgrade App modal now queries GitHub's releases API whenever it opens or its beta preference changes. It no longer presents the version embedded in the running frontend as though it were the newest release.
- **Stale-Target Protection**: The upgrade request independently resolves GitHub's newest eligible release immediately before invoking the upgrade script, ignores any stale client version, and refuses to run if GitHub cannot be reached. Responses are explicitly non-cacheable.
- **Accurate Upgrade UI**: The confirmation button remains disabled until GitHub returns a valid release tag, and the page shows a clear lookup error instead of silently falling back to an old version.
- **Personal Instance Deployment**: This release is deployed to the configured personal instance as part of its release workflow.
- **Version Bump**: Transitioned version to `v2.22.2`.

## v2.22.1 (August 2026)

### Portfolio Trend Control Consistency
- **Theme-Aware Portfolio Trend Edit Control**: Styled the Portfolio Trend range-picker pencil to match the compact edit controls used by other dashboard panels. Its size, border, background, hover state, focus treatment, and contrast now follow the active light or dark theme instead of relying on browser-default button styling.
- **Version Bump**: Transitioned version to `v2.22.1`.

## v2.22.0 (August 2026)

### Automated Trigger Confirmation & AI Analysis Stability
- **Automated Trigger Confirmation Window**: Added a shared, persistent per-user confirmation window for both Auto-Buy and Auto-Sell, defaulting to 15 minutes and configurable from 1–1,440 minutes in Portfolio Table & Execution Safety Settings.
- **Swing-Resistant Execution**: A qualifying price surge or drop now starts a timer rather than immediately placing an order. The applicable volatility condition must still be met when the confirmation window elapses; any recovery across the threshold resets the timer. Existing Auto-Sell 2% maximum-slippage protection remains in place.
- **Clear Trigger Context**: Auto-Buy/Auto-Sell activation dialogs and dashboard details now explain the active confirmation duration and show when a qualifying trigger is currently being confirmed.
- **AI Analysis Crash Fix**: Corrected an initialization-order error in the Historical Prediction Ledger that could crash the AI Analysis page before rendering.
- **Help Update**: Documented the confirmation-window behavior and recovery reset rules.
- **Version Bump**: Transitioned version to `v2.22.0`.

## v2.21.0 (August 2026)

### Dashboard, Settings & Order History Improvements
- **Aligned Sentiment Controls**: Coin Pair and Range controls now share a consistent labeled layout in Sentiment and Trade charts.
- **Dashboard Customization**: Top Gainers & Losers supports up to 50 coins per side. The Allocations donut centers total value with tracked dollar/percentage P&L, and Portfolio Trend has a saved picker for its visible quick ranges from 1H through All-time.
- **Local Trading Navigation**: Portfolio and Watchlist ticker clicks now open the matching local Trading pair, preferring `COIN/USDT` and falling back to `COIN/USD` only when needed.
- **Settings Safety & Consistency**: Telegram bot token, Telegram chat ID, and News API key are masked; all AI provider tests use the same `Test API Connection` control; Include Beta and AI Integrations Enabled are paired header toggles.
- **NewsAPI Grounding**: AI workflows that request current news now include the configured NewsAPI feed before supplemental web-search results.
- **Ledger Usability**: Renamed the Historical Prediction Ledger, added 20/50/100/200-row pagination, and corrected sticky-header/filter layering so the Coin filter remains visible and clickable while scrolling.
- **Order Origin Audit Trail**: Order History labels manual, Auto-Sell/Auto-Buy, and `Canceled by Auto-Sell` records. Auto-Sell cancellations are persisted and the actual automated sell is imported from the activity ledger.
- **Unhide Modal Cleanup**: Invalid hidden records without a coin ticker are omitted instead of rendering as blank checkboxes.
- **Help Update**: Updated in-app Help for the current dashboard, settings, news, trading, ledger, and sentiment behavior.
- **Version Bump**: Transitioned version to `v2.21.0`.

## v2.20.1 (August 2026)

### Accuracy Card Cleanup
- **Removed Permanent Legacy Counter**: Removed the `legacy visible below` count from the Overall Accuracy card and its API summary payload. Legacy rows remain available in historical views without permanently cluttering the headline KPI.
- **Version Bump**: Transitioned version to `v2.20.1`.

## v2.20.0 (August 2026)

### Fixed-Horizon Sentiment Accuracy — Phase 1
- **Independent Forecast Horizons**: Added separate 1–168 hour portfolio and watchlist forecast horizons. Existing installations transition seamlessly by inheriting their current analysis frequencies until an explicit horizon is saved.
- **Refresh-Safe Grading**: Every new prediction stores its own target timestamp and is graded at that target independently of later scheduled or manual sentiment runs.
- **Stable Rule Snapshots**: Each prediction preserves the exact sentiment thresholds active when it was created, so later Settings changes cannot retroactively rewrite its grade.
- **Lookback Repair & Prompt Alignment**: Fixed the ignored history-lookback setting, made sentiment web searches use that configured window, and now give the AI the exact forecast horizon, target time, allowed labels, and grading boundaries.
- **Seamless Legacy History**: Existing next-check grades remain visible and labeled as legacy, while Overall, Bullish, Bearish, recommendation, and model KPIs use only the new fixed-horizon cohort.
- **Background Evaluation**: Added a minute-level evaluator that uses the closest recorded target-time market price and leaves a forecast Tracking when a trustworthy target-time price is unavailable.
- **Regression Coverage**: Added tests for legacy/KPI separation, fixed-horizon independence, threshold snapshots, frequency fallback, and bounded whole-hour settings.
- **Version Bump**: Transitioned version to `v2.20.0`.

## v2.19.0 (August 2026)

### Configurable Hold Outcomes & Transparent Accuracy KPIs
- **Independent Hold Wrong Threshold**: Activated one symmetric `Wrong Threshold (±%)` setting for Hold, replacing the hardcoded dependency on Consider Buying and Consider Selling thresholds.
- **Strict Hold Validation**: Hold Wrong must be greater than Hold Steady, both values accept at most two decimal places, and invalid combinations are rejected consistently by the browser and API.
- **Explicit Neutral Band**: Settings and chart hover help now state that Hold is Correct inside the steady range, Wrong at or beyond the symmetric Wrong threshold, and Neutral strictly between those boundaries.
- **KPI Calculation Audit**: Reverified Overall, Bullish, and Bearish rates against decisive Correct/Wrong outcomes. Hold contributes to Overall but not directional rates; Neutral, Tracking, and Unscored outcomes remain excluded from all rate denominators.
- **Visible KPI Evidence**: Each scorecard now displays its Correct numerator and decisive denominator, making valid 0% directional results directly auditable.
- **Regression Coverage**: Added mixed-outcome and zero-directional-rate tests plus symmetric Hold boundary and persistence validation.
- **Version Bump**: Transitioned version to `v2.19.0`.

## v2.18.0 (August 2026)

### Evaluation-Anchored Sentiment Grades
- **Correct Check Alignment**: Every completed grade is now plotted at the next same-coin/source sentiment check—the exact timestamp and price used to evaluate the prior recommendation—instead of appearing one check early.
- **Original Signal Inside Marker**: Each green Correct, blue Neutral, or red Wrong outcome circle contains the original H, CB, BI, CS, or SI recommendation being graded.
- **Clear Outcome Context**: Visible labels continue to show the outcome and signed percentage move, while hover details explicitly preserve the original sentiment timestamp and identify the next check that completed its grade.
- **Regression Coverage**: Added API assertions tying each evaluation timestamp to the paired next sentiment record and ensuring the latest ungraded record remains Tracking and absent from the chart.
- **Version Bump**: Transitioned version to `v2.18.0`.

## v2.17.0 (August 2026)

### Outcome-Centered Sentiment Chart & Accuracy Verification
- **Outcome-Based Markers**: Sentiment Chart marker colors and visible labels now represent the completed grade: green Correct, blue Neutral, and red Wrong.
- **Original Recommendation Preserved**: Hover details retain the original H, CB, BI, CS, or SI signal and add an explicit colored `Outcome` row immediately above its timestamp.
- **Completed Grades Only**: Tracking and Unscored signals are excluded from the chart until a subsequent same-coin/source check produces a grade.
- **Direction-Preserving Precision**: Outcome movements display at least two decimals and automatically use four decimals for nonzero moves below 0.01%, eliminating misleading `+0.0%` and `-0.0%` labels.
- **Accuracy Audit**: Independently verified overall, bullish, bearish, and per-model rates against decisive Correct/Wrong counts, and added regression assertions for the KPI formulas.
- **Version Bump**: Transitioned version to `v2.17.0`.

## v2.16.0 (August 2026)

### Persistent Three-Day Sentiment Chart Range
- **Three-Day Initial Default**: The AI Analysis Sentiment Chart now opens at 3 Days for users who have not selected a preferred range.
- **Per-User Persistence**: Selecting any supported range from 1D through ALL immediately saves that choice as the user's default for future visits and sessions.
- **Trade Chart Isolation**: The personal Trade Chart retains its existing 1 Month default; only the Sentiment Chart default changed.
- **Validated Storage**: Added a user setting, API validation, automatic database migration, and safe fallback for invalid or legacy values.
- **Version Bump**: Transitioned version to `v2.16.0`.

## v2.15.0 (August 2026)

### Zero-Boundary Directional Rules & Steady-Range Hold Validation
- **Zero Is a Valid Wrong Boundary**: Buy Immediately, Consider Buying, Consider Selling, and Sell Immediately now accept `0.00%` for Wrong. With a bullish Correct value of 5.00 and Wrong of 0.00, zero or any decline is Wrong, a gain strictly between 0.00% and 5.00% is Neutral, and 5.00% or higher is Correct. Selling rules apply the exact inverse.
- **Meaningful Correct Thresholds**: Directional Correct values retain a 0.01% minimum, preventing an ambiguous zero point from satisfying both Correct and Wrong. Directional Correct and Wrong magnitudes remain otherwise independent.
- **Hold Is No Longer Bullish**: Hold now explicitly means the price is expected to remain steady. It is excluded from bullish and bearish win-rate calculations and retains its blue H chart marker.
- **Dedicated Hold Steady Range**: Replaced Hold Correct/Wrong inputs with one `Steady Range (±%)` value that may be 0.00%. Moves inside the range, including its exact boundaries, make Hold Correct.
- **Action-Aware Hold Failures**: Hold becomes Wrong on the upside when price reaches the Consider Buying Correct threshold, or on the downside when it reaches the Consider Selling Correct threshold. Moves outside the steady range but before either action boundary are Neutral.
- **Contradiction-Proof Validation**: Hold steady range must be smaller than both action thresholds. All nine active sentiment values are required, non-negative, and limited to two decimal places, with clear browser and API errors.
- **Updated Explanations**: Settings now says `Expects price to remain steady` for Hold and generates exact live boundary help. Sentiment Chart hover details display the Hold steady band and both derived action boundaries.
- **Upgrade-Safe Storage**: Added an automatic `sentiment_hold_steady_pct` database migration with a 1.00% default while retaining legacy v2.14 Hold columns for schema compatibility.
- **Version Bump**: Transitioned version to `v2.15.0`.

## v2.14.0 (August 2026)

### Consecutive-Check Sentiment Grading & Configurable Outcome Rules
- **Consecutive Same-Coin Validation**: Every recorded recommendation is now graded by comparing its recorded coin price with the price at the immediately following sentiment check for the same coin and portfolio/watchlist source. The newest check remains Tracking until its next check exists.
- **Five Independent Rule Sets**: Added a dedicated `Sentiment Variable Settings` section with separate Correct and Wrong percentage magnitudes for Buy Immediately, Consider Buying, Hold, Consider Selling, and Sell Immediately—ten persistent values in total.
- **Explicit Directional Boundaries**: Buy Immediately, Consider Buying, and Hold expect upward movement; Consider Selling and Sell Immediately expect downward movement. Correct and Wrong are independent positive magnitudes applied in opposite directions, exact boundary matches are decisive, and every move strictly between the two boundaries is Neutral.
- **Validated Configuration**: Every field is required, must be at least `0.01`, cannot be negative, and accepts no more than two decimal places. Both the browser and API reject invalid values, while each completed rule pair displays a live explanation of its Correct, Wrong, and Neutral ranges.
- **Stable Signal Colors**: Sentiment Chart markers remain recommendation-colored only: H blue, CB light green, BI dark green, CS light red, and SI dark red. Outcome grading cannot change a marker's recommendation color.
- **Detailed Hover Comparisons**: Compact chart labels remain unchanged, while hover details now identify the previous and next check price/time, elapsed time, active thresholds, price change, outcome, and exact grading explanation.
- **Ledger Terminology**: Renamed Updated Price/Date/Time columns to Next Check Price/Date/Time and revised AI Analysis and Help copy to describe consecutive-check validation accurately.
- **Upgrade-Safe Storage**: Added automatic database migration coverage for all ten values, with conservative 5.00% defaults for existing and new installations.
- **Version Bump**: Transitioned version to `v2.14.0`.

## v2.13.0 (August 2026)

### Date-Ranged Trade History & In-Place Sentiment Chart
- **One-Month Trade Chart Default**: The dedicated Trade Chart now opens at 1 Month instead of displaying roughly two years, with selectable 1D, 3D, 5D, 1W, 2W, 1M, 3M, 6M, 1Y, 2Y, and ALL ranges.
- **Pair-Aware Range Controls**: Both personal trade history and sentiment history retain their searchable Binance.US pair selectors and fetch price resolution appropriate to the selected period.
- **AI Chart Replaced In Place**: Replaced the existing `BTC/USDT Price Action with Overlaid AI Sentiment Signals` visualization on AI Analysis with `Sentiment Chart`. No additional Trading tab was created.
- **Exact Signal Vocabulary**: Portfolio recommendations use H (blue), CB (light green), BI (dark green), CS (light red), and SI (dark red) dots. The plot shows only compact labels such as `BI (+5.5%)`; hovering the corresponding dot reveals its exact timestamp, full recommendation, thesis, signal/evaluation prices, measured move, and outcome.
- **Shared Edge-Safe Layout**: Sentiment Chart uses the same responsive frame, right-side quote-price scale, adaptive time axis, and scoped Lightweight Charts table reset that keeps both axes fully visible on Trade Chart.
- **Long-Range Accuracy Support**: Sentiment reporting now honors 6-month, 1-year, and 2-year request windows, while ALL remains uncapped by a sentiment-history cutoff.
- **Version Bump**: Transitioned version to `v2.13.0`.

## v2.12.1 (August 2026)

### Trade Chart Axis Clipping Hotfix
- **Root-Cause Axis Repair**: Scoped-reset the application's global `table`, `tr`, and `td` rules inside Lightweight Charts. Those global rules were adding a top margin, cell padding, borders, fixed table layout, white backgrounds, and hidden overflow to the chart library's internal layout table, pushing the X-axis out of view and clipping the right-side Y-axis.
- **Full Axis Visibility**: The internal chart table now retains its intended zero-spacing layout so year/month labels, the complete right-side price scale, chart border, and arrow markers remain inside the visible canvas.
- **Version Bump**: Transitioned version to `v2.12.1`.

## v2.12.0 (August 2026)

### Arrow-Only Trade Markers, Hover Details & Chart Edge Repair
- **Uncluttered Trade Plot**: Removed every buy/sell label from the price plotting surface. Completed trades are represented only by green up arrows and red down arrows, eliminating overlapping text.
- **Trade Hover Tooltips**: Hovering directly over an arrow now shows its exact execution date/time, base-asset amount, execution price, and USD/USDT value. Multiple executions represented by the same dated arrow are listed together, and clicking still opens full transaction details.
- **Protected Chart Edges**: The Lightweight Chart now measures and resizes from its actual inner container, reserves a minimum width for the right price scale, adds safe padding around the canvas, and preserves top/bottom scale margins so axes, prices, and arrows are not clipped.
- **Version Bump**: Transitioned version to `v2.12.0`.

## v2.11.0 (August 2026)

### Exact-Pair Trade Chart & Evidence-Based AI Outcome Grading
- **Dedicated Trade Chart Tab**: Added a basic price-line chart immediately to the right of Order History. It follows the app-selected exact Binance.US pair, uses a right-side quote-price Y-axis and year/month X-axis, and overlays completed purchases with up arrows and sales with down arrows.
- **Complete Execution Labels**: Trade markers show base-asset amount, execution price, and USD/USDT value. Clicking a dated marker opens the full transaction details, including every exact execution timestamp represented on that date.
- **TradingView Cleanup**: Removed the unrequested Pair-Aware Activity section beneath the Advanced Chart. TradingView remains dedicated to its free native symbol search, indicators (including moving averages, oscillators, and Bollinger Bands), drawings, comparisons, and market tools.
- **Fixed-Horizon Sentiment Validation**: Replaced next-refresh comparisons with recorded market prices at each signal's configured portfolio or watchlist analysis horizon. Portfolio and watchlist records are evaluated independently, eliminating cross-source and irregular-refresh contradictions.
- **Consistent Outcome Semantics**: The configured neutral threshold now applies to every recommendation. Moves inside the ± band are inconclusive and excluded from win rates; decisive Buy/Hold, Sell, and Watch outcomes are graded according to their intended, context-aware direction.
- **No Fabricated Accuracy**: Removed seeded history and placeholder win rates. Tracking, neutral, unavailable-price, and unsupported signals are reported separately and never counted as wins or losses; a top model requires at least three decisive outcomes.
- **Three-Day Default**: The AI sentiment price chart and accuracy request now default to the past three days.
- **Prompt Preservation**: Application startup now fills only missing AI prompt fields and preserves every existing customization during service upgrades and restarts.
- **Version Bump**: Transitioned version to `v2.11.0`.

## v2.1.0 (August 2026)

### TradingView Advanced Chart, BTC/USDT Navigation Default & Dated Personal Trades
- **Reliable Trading Navigation Default**: Clicking `Trading` from any page—or clicking it again while already in the Trading Center—now resets the authoritative order/chart pair to `BTC/USDT`. Contextual Buy/Sell and Quick Trade links retain priority and still open their requested pair and side.
- **Full Free TradingView Advanced Chart**: Replaced the Trading Center's custom Lightweight Charts view with TradingView's hosted Advanced Chart, configured with its top, bottom, and drawing toolbars; native symbol search; chart styles and intervals; 80+ built-in indicators; 100+ drawing tools; symbol comparison; date ranges; volume and legend; details; hotlists; economic calendar; image export; Binance.US watchlist; and full-size popup.
- **Built-In Indicator Coverage**: Moving averages, RSI, MACD, Stochastic, ATR, Bollinger Bands, and Volume remain available from TradingView's `Indicators` menu. The redundant MA/Oscillator/Other button row below the former chart has been removed.
- **Pair-Aware My Trades Timeline**: Initially added personal Binance.US activity beneath TradingView; this presentation was superseded by the dedicated Trade Chart tab in v2.11.0.
- **Safe Pair Synchronization**: The app's Binance.US selector remains authoritative for the executable order ticket, balances, fees, chart default, and personal trade history. TradingView's cross-origin built-in selector remains available for independent research without silently changing the pair an order would execute against.
- **Theme & Responsive Support**: The widget reinitializes with the application's light/dark theme and uses responsive desktop, tablet, and mobile chart heights, while preserving TradingView attribution and loading/error feedback.
- **Version Bump**: Transitioned version to `v2.1.0`.

## v2.0.9 (August 2026)

### Responsive Table Actions & Accurate Position P&L
- **Overflow-Aware Actions Column**: Portfolio and Watchlist automatically replace expanded row controls with one compact `Actions` button whenever the configured columns exceed the table viewport. The compact column remains pinned at the right edge so actions are reachable without horizontal scrolling.
- **Viewport-Safe Context Menus**: The row context menu exposes Alerts, News, Notes, Buy, Sell, Stake, Cancel, and Hide where supported. Buy and Sell retain their USD/USDT and Auto-Buy/Auto-Sell submenus; menus flip and clamp to stay on-screen and close on outside clicks, page/table scrolling, viewport resizing, or another menu opening.
- **Correct Current-Position P&L**: Profit & Loss now prioritizes the actual held amount, current price, and average entry price. Backend FIFO cost basis is reconciled to the live held quantity, preventing duplicate historical activity rows from doubling the displayed position cost.
- **Binance Activity Deduplication**: Order-level and trade-fill synchronization now recognize one another by Binance order ID before changing balances or inserting activity, preventing the same fill from being recorded twice.
- **Version Bump**: Transitioned version to `v2.0.9`.

## v2.0.8 (August 2026)

### Portfolio Trend Live-Range Hotfix
- **Short-range value correction**: Fixed UTC portfolio-history timestamps being interpreted in the server's Eastern timezone, which shifted snapshots into the future and made the 1H and 4H charts appear flat despite changing stored values.
- **Crash-free range switching**: Range requests are now cancellation-safe and tied to the range that produced their data. The chart remounts only with matching data, preventing an `ALL` or `1Y` dataset from being rendered temporarily on the 1-minute scale when switching back to 1H or 4H.
- **Exact range endpoints**: Every finite trend range now includes both its true starting time and the current time, and the frontend/backend keys for 24H, 30D, and 90D are fully aligned.
- **Version Bump**: Transitioned version to `v2.0.8`.

## v2.0.7 (August 2026)

### Portfolio Trend Ranges, All-Time Labels & USD Precision
- **New 1H and 3D ranges**: Added one-hour and three-day Portfolio Trend controls, with 15-minute and 12-hour data intervals respectively.
- **True all-time trend**: The `ALL` range now reads the complete stored portfolio-value history from its first recorded snapshot through the present, instead of falling back to the one-day series. Its adaptive labels include the day or year as needed, so month-only ticks no longer repeat as `Aug`.
- **Consistent currency axis**: Portfolio Trend Y-axis labels now always display USD with exactly two decimal places.
- **Compact range controls**: Reduced the range-button sizing so all ten controls fit the chart widget without horizontal scrolling.
- **Version Bump**: Transitioned version to `v2.0.7`.

## v2.0.6 (August 2026)

### Persistent Minimized AI Copilot & Full-Edge Resizing
- **Windows-Style Minimize Tab**: The floating AI Copilot now has a minimize control. A sticky `AI Copilot` tab remains at the bottom-left of every application page while minimized, replacing the sidebar opener; clicking it restores the same floating chat.
- **Persistent Window State**: Minimized status, normal-window location, dimensions, and maximized state are saved locally. A minimized Copilot remains minimized through refreshes, page navigation, logout, and later login; restoring it returns to its previous position and size.
- **Resize From Every Edge and Corner**: The floating chat can now be resized with dedicated pointer handles on all four sides and all four corners, while retaining its viewport bounds and minimum usable dimensions.
- **Version Bump**: Transitioned version to `v2.0.6`.

## v2.0.5 (August 2026)

### Rich AI Copilot Responses & Resizable Floating Chat
- **Full Rich-Content Copilot Rendering**: AI Copilot messages now render GitHub-flavored Markdown instead of displaying its syntax as plain text, including headings, bold/italic/strikethrough and underline, ordered and unordered lists, links, quotes, code, tables, and images. The renderer sanitizes all AI-provided HTML before display, allowing useful formatting while blocking scripts, unsafe attributes, and embedded content.
- **True AI Tables**: Pipe-delimited responses such as market-comparison tables now render as readable, scrollable tables with styled headers and rows in the Copilot.
- **Floating Copilot Window**: Added the top-right expand control to the sidebar. It closes the sidebar and opens the same active conversation in an independent floating chat window that can be resized, maximized/restored, or closed with `×`; closing it leaves the Copilot closed.
- **Drag-and-Drop Floating Chat**: The floating Copilot title bar can now be dragged anywhere within the browser viewport. Pointer-based movement works with mouse or touch and keeps the window fully reachable on-screen.
- **Version Bump**: Transitioned version to `v2.0.5`.

## v2.0.4 (August 2026)

### Light-Mode Trading Visibility, Password-Manager 2FA & Pending-Buy Watchlist Routing
- **High-Contrast Light-Mode Trading Controls**: Fixed the light-mode hover treatment for inactive Buy/Sell and every Order Type selector so text remains dark and readable instead of turning nearly white against the pale control background.
- **Immediate Password-Manager 2FA Availability**: The trade-confirmation TOTP field now uses the browser-standard `one-time-code` autocomplete hint and is focused after the modal renders, so password managers can offer the six-digit code without requiring an extra click outside and back into the field.
- **No-Position Sell Protection**: Portfolio Sell controls are now greyed out and disabled, on desktop and mobile, unless the position contains at least `0.0001` of the asset.
- **Pending Buy Orders Belong to Watchlist**: Unfilled BUY orders for zero-balance assets no longer create Portfolio rows. They automatically create or unhide the corresponding Watchlist entry—including for orders created directly on Binance.US—where the existing row hover card shows the pending-order details. An asset joins Portfolio only once its filled amount reaches `0.0001`.
- **Version Bump**: Transitioned version to `v2.0.4`.

## v2.0.3 (August 2026)

### Quote-Balance Aware Buy & Auto-Buy Action Controls
- **Dynamic Quote Balance & Minimum $1.00 Validation**: Added real-time available quote currency balance evaluation (USD and USDT) for all Portfolio and Watchlist trade action buttons.
- **Pending Order & Auto-Buy Commitment Accounting**: The usable quote balance calculation now dynamically deducts quote currency locked in open exchange pending limit/stop BUY orders (e.g. pending buy on BTCUSDT) and reserved in active Auto-Buy triggers. If locked funds bring the freely usable quote balance below $1.00 (e.g., $63.18 locked leaving only $0.63 free), buy actions targeting that quote currency are immediately grayed out and disabled.
- **Main "Buy" Action Button Auto-Disabling**: The primary "Buy" button across both Portfolio and Watchlist tables (desktop and mobile) is now completely grayed out and disabled (`opacity: 0.4`, `cursor: not-allowed`) if the user holds less than the $1.00 minimum across all available quote currencies for that asset (e.g. `< $1.00` in both USD and USDT). Hovering over the disabled button displays an explanatory tooltip detailing the required quote balance.
- **Granular Quote Menu Item Disabling**: Inside the Buy quote currency dropdown (`Buy with USD`, `Trigger Auto-Buy (USD)`, `Buy with USDT`, `Trigger Auto-Buy (USDT)`), individual quote options are independently grayed out and disabled if the user's available balance in that specific quote currency is below $1.00, with dynamic hover tooltips displaying current available balance vs. minimum required.
- **Version Bump**: Transitioned version to `v2.0.3`.

## v2.0.2 (August 2026)

### Zero-Balance Pending Order Auto-Hide, High-Contrast Sentiment Pills & Tax Report Hook Fix
- **Zero-Balance Pending Order Cancellation Auto-Hide**: Fixed an issue where canceling a pending order for an asset the user did not own (e.g. TRUMP with `0.0000` holdings) left the coin visible in the Portfolio table. Both the frontend state and backend order cancellation endpoints now automatically detect when a canceled order was the last remaining order for a zero-balance coin, immediately removing the entry from the table and resetting `force_visible = False`, `hidden = True`, and `auto_hidden = True` in the database.
- **High-Contrast "Not Tracked" Sentiment Badge on Yellow Rows**: Wrapped disabled/untracked sentiment badges in the same high-contrast dark capsule container (`rgba(15, 23, 42, 0.92)`) used for active recommendations on yellow highlighted pending-order rows, ensuring "🚫 Not Tracked" text remains vivid, crisp, and easily readable.
- **Tax Report React Error #310 Resolution**: Fixed a `Minified React error #310` ("Rendered more hooks than during previous render") on `/tax-report` caused by `useMemo` hooks being placed below conditional `if (loading)` and `if (error)` early returns. Reordered all hook declarations before conditional returns, ensuring 100% stable hook call order across every render.
- **Version Bump**: Transitioned version to `v2.0.2`.

## v2.0.1 (August 2026)

### Volatility Alert Zero-Balance & Hidden Coin Filtering
- **Volatility Alert Loop Filter Hardening**: Fixed a bug where background volatility price-swing monitors (`volatility_alert_loop`) continued dispatching Telegram alerts and system notifications for closed portfolio positions (coins with `0.00` balance and `hidden = True`, such as PURR) and hidden watchlist coins. The query and handler now strictly require portfolio coins to be visible (`hidden = False`, `amount > 0`, or `force_visible = True`) and watchlist coins to be unhidden (`hidden = False`).
- **Hidden & Closed Position Trigger Auto-Disable**: Hiding a coin via `/api/hide-coin` or auto-hiding when selling 100% of a holding now automatically resets `auto_sell_enabled` and `auto_buy_enabled` to `False` to prevent orphaned background triggers on zero-balance assets.
- **Watchlist Background AI Sentiment Query Filter**: Updated background scheduled sentiment analysis to filter exclusively for unhidden watchlist coins (`WatchlistCoin.hidden == False`), preventing background LLM token consumption on deleted/hidden watchlist items.
- **Version Bump**: Bumped release version to `v2.0.1`.

## v2.0.0 (August 2026)

### Official Release 2.0: OCO Balance Fix, 2FA Login Verification, AI Prediction Neutral Threshold, Real-Time Staking APY & Tax Report Upgrades
- **Pending Order Placeholders Display Fix**: Fixed an issue where pending order placeholders (coins with active open orders but 0.0000 holdings, such as TRUMP) erroneously populated `avg_entry` with the pending limit price and computed an unrealized `% Change` against live prices. Average entry and % change now cleanly display `—` for pending-only rows until real execution fills occur.
- **Watchlist Add Zero-Disappearance Fix**: Resolved the race condition where newly added watchlist coins temporarily disappeared during background polling by making optimistic additions permanently persistent across in-flight background cycles until server confirmation.
- **2-Tier Slippage & Capital Protection Architecture**: Implemented a unified pre-flight order book depth simulation and exchange-level IOC (Immediate-Or-Cancel) limit price floor for all automated volatility sales and purchases. Before placing an order, the system simulates fills across live bids/asks to verify that estimated slippage does not exceed `max_slippage_pct` (configurable in Settings, default 2.00%). If liquidity is too thin, the order is aborted with zero loss and a Telegram alert is sent; if liquid, the order is submitted with an IOC price floor so Binance's matching engine guarantees no execution can occur below your protection floor.
- **2FA Verification on Login Screen**: Added two-factor authentication verification to the login flow. When a user has 2FA enabled on their profile, entering their username and password automatically opens a 6-digit TOTP code input step before granting access.
- **Watchlist Add 0ms Persistence**: Fixed a race condition where background polling wiped out newly added coins before the server add completed by locking optimistic additions in an un-wipeable ref map until confirmed.
- **OCO Order Balance Check Fix**: Fixed a bug where OCO sell orders checked quote asset balances (e.g. USDT) instead of base asset balances (e.g. PURR), rejecting valid sell orders when USDT balance was $0.00. The quote balance check is now properly scoped to Buy orders, and Sell orders validate available base asset balance.
- **AI Recommendation Outcome Neutral Threshold**: Added a configurable `AI Outcome Neutral Threshold (%)` setting in Settings (default 5.00%). As of v2.11.0, the threshold applies consistently to every recommendation and neutral moves are excluded from accuracy.
- **Historical Prediction Ledger Coin Filter & Default Sort**: Added an interactive coin filter dropdown directly in the "Coin" table header on the Historical Prediction Ledger with Select All, Deselect All, and individual coin toggles. Fixed default table sorting strictly to updated Date & Time descending, ensuring temporary column header sorts reset cleanly on reload.
- **Auto-Inclusion of New Portfolio Coins in AI Analysis**: Newly acquired portfolio coins are now automatically checked and included by default across all AI analysis list views, charts, and prediction ledgers.
- **Real-Time Staking APY & Reward Rate Sync**: Ensured staking reward rates and estimated APY/APR percentages are continuously normalized and synchronized in real time from live Binance.US staking endpoints (`/sapi/v1/staking/asset`).
- **Tax Report Upgrades & Annual Filtering**: Added annual tax year selectors (e.g. 2026, 2025, 2024, or All Years), dynamic summary metrics for Realized Gain/Loss, Short-Term vs. Long-Term capital gains separation, and enhanced CSV export naming.
- **Quick Trade Terminal Routing**: Updated the Quick Trade widget to use React Router navigation state prefill so the selected coin and order side (Buy/Sell) apply immediately on the Trading page.
- **Watchlist Add Race Condition — Root Cause Fix**: Root-caused the remaining Watchlist "add flickers away then reappears" bug to out-of-order network responses: `/api/watchlist-live` fetch duration varies per request (live Binance price lookups per coin), so an older, slower background poll could resolve *after* a newer one and silently overwrite a just-added coin with stale data. Every watchlist-live call site (10-second background poll, auto-buy/auto-sell cancel refresh, single-coin sentiment refresh polling) now tags its request with a monotonically increasing sequence id and discards any response older than the last one actually applied, making the optimistic add permanently stable regardless of network timing.
- **2FA Order Confirmation Friendly Labels**: The Two-Factor Authentication order confirmation modal now displays human-readable Action (`Sell BTC for USDT` / `Buy BTC with USDT` / `Stake BTC`) and Type (`Stop Loss Limit`, `Take Profit Limit`, `OCO (One-Cancels-Other)`, etc.) instead of raw exchange enum values like `SELL BTCUSDT` and `STOP_LOSS_LIMIT`. Also applied the existing friendly Side/Type formatters to the Test Order History table for consistency with the real Open Orders/Order History tables.
- **Watchlist Add Race Condition — Structural Fix**: The prior fetch-sequence guard alone wasn't sufficient: a newly-added watchlist coin is still missing most server-computed fields (`current_value`, 24h stats, etc.), so sorting it alongside fully-populated confirmed rows under the active column sort could shove it out of view depending on the sort column, which looked identical to the coin vanishing. Unconfirmed additions are now rendered pinned at the top of the table, completely bypassing the sort, until the server confirms the row — eliminating the flicker regardless of sort column or network timing.
- **Watchlist Add Disappearing Bug — Actual Root Cause Found & Fixed**: The real cause of the add-then-vanish-then-reappear behavior was a backend bug, not a frontend race: `POST /api/watchlist/add` (and the unhide/manual-sync-coins paths) called a function named `backfill_7d_prices` that had been renamed to `ensure_price_history` in `services/price_history_service.py` but never updated at its 3 call sites. This raised an unhandled `NameError` *after* the new coin had already been committed to the database, so the request returned `500` — the frontend correctly rolled back its optimistic UI on that failure — while the coin silently persisted server-side and reappeared (out of order) on the next background poll. Fixed all 3 call sites to use `ensure_price_history` via a proper background-thread-safe wrapper, so adding/unhiding a coin now succeeds and returns immediately with no error.
- **Unified Pending Order / Auto-Buy / Auto-Sell Hover Box**: Removed the separate native browser tooltip on the ⚡/🚀 Auto-Sell/Auto-Buy icons in the Volatility column, which was rendered above all page content and could visually mask the main yellow row-hover box. All pending order, Auto-Buy, and Auto-Sell details for a row — in any combination — now surface exclusively through the single unified yellow hover box.
- **Auto-Buy/Auto-Sell Row Hover Box Suppression Fix**: Found the actual reason the unified hover box appeared to be "overridden" whenever a row had an active Auto-Buy or Auto-Sell trigger: the box's hover handler excluded all `<input>`/`<select>` elements to avoid interrupting other controls, but the Auto-Buy/Auto-Sell ⚡/🚀 indicators live directly inside the Volatility % input cell, so hovering the very icon that indicates a trigger landed on the excluded input and suppressed the box. The exclusion now only applies to buttons and the symbol cell, so the box reliably appears for any row with a pending order, Auto-Buy, and/or Auto-Sell, in any combination.
- **Pending Order Hover Box Off-Screen Positioning Fix**: Found the real reason the hover box still appeared missing on rows further down the Portfolio/Watchlist tables: `.table-container` sets `contain: layout`, which makes it a containing block for `position: fixed` descendants, so the box's fixed coordinates were being resolved relative to the table instead of the browser viewport — only rows near the top of the table (small offset) rendered the box in a visible spot, while every row further down drifted increasingly off-screen. The box is now rendered through a React portal directly into `document.body` (the same pattern already used for the trade quote menu), so its `position: fixed` coordinates are always viewport-relative regardless of ancestor CSS.
- **Pending Order Hover Box — Actual Root Cause (Undefined Variable Crash)**: Root-caused via live browser reproduction (Playwright + a minted debug session) that the hover box never appeared for any row with an active Auto-Buy or Auto-Sell trigger because `generateOrderTooltipText` referenced an undefined variable, `volatilityHours`, instead of the real state variable `volatilityHoursSetting`. This threw an uncaught `ReferenceError` inside the row's `onMouseMove` handler the instant it tried to describe an Auto-Buy/Auto-Sell trigger, aborting the handler before it ever called `setOrderTooltip` — so the box silently never rendered for those rows, while coins with only a plain pending order (no trigger) never hit that code path and worked fine. Fixed the variable reference; the two hover-suppression and off-screen-positioning fixes above were real but secondary issues uncovered along the way.
- **Version Bump**: Transitioned official release version to `v2.0.0`.

## v1.99-beta (August 2026)

### Coin Performance Fit & Theme Scrollbars, Portfolio 24h Change, Watchlist Add Fix, Exact Chart Markers & Eastern Time Tables
- **Coin Performance Panel Fitting & Theme-Aware Scrollbar**: Adjusted cell padding (`5px 8px`) and header spacing in `PortfolioPerformanceTable.jsx` and `theme.css` so 5 coins fit cleanly without triggering vertical scrollbars. Added the sleek theme-aware `.custom-scrollbar` class for instances where 6+ coins are displayed.
- **24-Hour % Change Column for Portfolio Table**: Added `change_24h` (`24h % Change`) to `PORTFOLIO_COLUMN_DEFINITIONS`, with full sorting and colored percentage display, so users can selectively add 24h market momentum to their Portfolio table via the Table Column Customization modal (`⚙️`).
- **Watchlist Add/Flicker Bugfix**: Fixed a race condition where background polling (`/api/watchlist-live`) cleared optimistic temporary items before the backend addition completed. Preserved pending optimistic items across background polling updates until server confirmation.
- **Exact-Price Trading Chart Execution Markers**: Reworked trade execution markers in `TradingChart.jsx` to render on dedicated transparent overlay line series at the exact weighted-average execution price (e.g. $0.15) rather than snapping below the candle low or above the high.
- **Separate Date & Time Columns in Eastern Time**: Split the combined Date column in both Open Orders and Order History tables (and Test Orders) into separate **Date** and **Time** columns, and formatted all displayed timestamps strictly in **Eastern Time** (`America/New_York`).
- **UTC Timestamp Normalization & Chronological Sorting**: Fixed a timezone parsing mismatch in `/api/trading/real-orders` where local-time timestamps caused trades to appear out of sequence and hours apart; all order records now normalize to UTC ISO-8601 with chronological descending sort.
- **Version Bump**: Synchronized metadata to `v1.99-beta`.

## v1.98-beta (August 2026)

### Adaptive Dynamic Decimal Precision for Portfolio & Watchlist Prices
- **Tiered Decimal Formatting for Current Price**: Replaced fixed 2-decimal formatting with adaptive decimal precision scaling based on coin price magnitude across both the Portfolio and Watchlist tables:
  - **$\ge \$1.00$**: 2 decimal places (e.g. `$45,120.50`, `$1.52`, `$1.00`)
  - **$\$0.01$ to $\$0.999...$**: 3 decimal places (e.g. `$0.150`, `$0.975`, `$0.042`)
  - **$\$0.0010$ to $\$0.0099...$**: 4 decimal places (e.g. `$0.0045`, `$0.0089`)
  - **$\$0.00010$ to $\$0.00099...$**: 5 decimal places (e.g. `$0.00045`, `$0.00082`)
  - **$<\$0.00010$**: 6 decimal places max (e.g. `$0.000012`, `$0.000085`)
- **Version Bump**: Synchronized metadata to `v1.98-beta`.

## v1.97-beta (August 2026)

### Pair-Aware Trade Menus, Faster Order-Fill Detection, Auto-Buy Avg Entry Fix & Blank Alert Defaults
- **Pair-Aware Buy/Sell & Auto-Buy/Auto-Sell Menus**: The Portfolio/Watchlist Buy and Sell dropdowns now only show "with USD"/"for USD" and "Trigger Auto-Buy/Auto-Sell (USD)" options for coins that actually have a live USD pair on Binance.US (same check applied to USDT), based on a new `/api/trading-pairs`-backed lookup, instead of always showing all four options regardless of pair availability.
- **Faster Order-Fill Detection**: Added a new lightweight `real_order_status_loop` background job that checks only pending real orders every 15 seconds (instead of waiting for the full 5-minute Binance account sync). Newly detected fills — full or partial — now immediately update the coin's amount via `update_portfolio_from_real_order`, so the Portfolio table reflects new trades within seconds instead of up to 5 minutes later.
- **Auto-Buy Average Entry Price Fix**: Fixed `execute_auto_buy` to properly recompute a weighted-average entry price when a volatility-triggered purchase adds to (or creates) a holding, instead of only bumping the amount and leaving `avg_entry` stale or at 0 — this was the root cause of coins like PURR showing "—" for Avg Entry after an Auto-Buy execution.
- **Avg Entry Backfill & Safer New-Coin Creation**: The periodic balance sync now backfills a missing/zero `avg_entry` from the latest known price instead of leaving it blank, and no longer creates a brand-new coin record with `avg_entry=0` when a live price isn't available yet (it waits for the next cycle instead).
- **Blank Price Alerts by Default**: Fixed the Portfolio table's Price Up/Down alert cells defaulting to a non-blank `0.00%` for new coins (caused by the `Coin` model defaulting the alert type to percent-mode with a `0.0` value). New coins now render blank until you configure an alert, matching the Watchlist table's existing behavior.
- **Removed Watchlist Sell Button**: Removed the redundant Sell button from Watchlist table rows, keeping Watchlist focused exclusively on monitoring and opportunistic buy orders.
- **Version Bump**: Synchronized metadata to `v1.97-beta`.

## v1.96-beta (August 2026)

### Allocations Donut Center Value, Always-Visible Widget Edit Buttons, Top Movers Hover Highlight & Uniform Table Rows
- **Allocations Donut Center Total & True Centering**: The "Allocations" doughnut chart now displays the total portfolio value in its center hole via a custom Chart.js plugin. The legend was moved to a self-contained absolutely-positioned column so the ring itself always stays centered within the panel, regardless of the legend's width.
- **Always-Visible Coin Performance Edit Button**: Added a persistent ✏️ edit button directly in the "Coin Performance" widget header, matching Top Gainers & Losers and Recent Order History, so it's accessible without needing to enter "Customize Layout" mode. Removed the now-redundant edit-mode-only pencil icons for Coin Performance and Recent Order History from the widget grid's drag header.
- **Top Gainers & Losers Row Hover Highlight**: Hovering any coin row in the Top Gainers & Losers widget now highlights the row for clearer visual feedback.
- **Uniform Portfolio & Watchlist Table Rows**: Removed the alternating zebra-stripe row background on the Portfolio and Watchlist tables — all rows now share the same base background color unless they have an active special state (pending order, Auto-Buy/Auto-Sell highlight).
- **Allocations Donut Total Value Consistency**: Fixed a mismatch where the doughnut's center total was re-summed only from the coins actually rendered as slices, which could differ from the authoritative "Total Portfolio Value" widget (which includes staking balances and sub-$1 dust). The center value now uses the same authoritative total passed down from the Dashboard, so both numbers always match even when tiny-value coins don't get their own visible slice.
- **Allocations Donut Stale-Value Bugfix**: Root-caused the remaining discrepancy to the center total being drawn via a Chart.js canvas plugin, whose `afterDraw` closure only gets re-applied by `react-chartjs-2` when the chart's dataset changes — not on every totalValue update — causing it to display a stale, lagging number. Replaced the canvas plugin with a plain React DOM overlay positioned over the ring, which always reflects the current render's value. The center total is now also formatted to 2 decimal places to match the Portfolio Value widget exactly.
- **Version Bump**: Synchronized metadata to `v1.96-beta`.

## v1.95-beta (August 2026)

### Top Movers Polish, Trading Chart Marker Scoping, Volatility Cell Alignment & Per-Coin Sentiment Toggle
- **Top Gainers & Losers Slider & Navigation**: Restyled the "Coins Per Side" range slider with a slim custom thumb/track so it visually docks flush at min/max (previously appeared to stop short of 25). Clicking any coin in the Top Gainers & Losers widget now navigates to the Trading page with that coin's USDT pair pre-selected for quick chart viewing.
- **Trading Chart Marker Pair Scoping**: Fixed the Trading Center chart so buy/sell transaction markers only reflect trades for the currently selected pair. Previously the chart fetched transactions with `all_coins=true` and never filtered them, causing every coin's trade history to appear as arrows regardless of which pair's chart was open.
- **Volatility % Cell Alignment**: Reworked the Portfolio/Watchlist Volatility % cell to a fixed 3-column layout so the ⚡ Auto-Sell and 🚀 Auto-Buy indicators no longer push the centered input/percentage off-center — ⚡ is always anchored to the left edge of the cell and 🚀 to the right edge, independently of the input.
- **Per-Coin Sentiment Tracking Toggle**: Added the ability to double-click a cell in the Sentiment column (Portfolio or Watchlist) to enable or disable AI sentiment tracking for that specific coin. Disabled coins display a muted "🚫 Not Tracked" label and are skipped by both the scheduled sentiment analysis and "Run Sentiment Analysis Now". New `sentiment_tracking_enabled` column added to `coins` and `watchlist` tables (defaults to enabled) with a new `/api/toggle-sentiment-tracking` endpoint.
- **Help Documentation Updated**: Documented the Top Movers click-to-chart behavior and the new per-coin sentiment tracking toggle in the Help page.
- **Version Bump**: Synchronized metadata to `v1.95-beta`.

## v1.94-beta (August 2026)

### Market-Wide Top Gainers & Losers with Configurable Count & Ownership Highlighting
- **Exchange-Wide Momentum Data**: The "Top Gainers & Losers (24h)" dashboard widget no longer limits results to your Portfolio/Watchlist holdings. Added `/api/market-movers`, which reuses the existing cached Binance.US 24hr ticker snapshot (`client.get_ticker()`, no symbol filter) to surface `priceChangePercent` across every USD/USDT pair the exchange lists, deduplicated by base asset (preferring the USDT-quoted pair) and excluding stablecoins.
- **Editable Coin Count**: Added a ✏️ edit button (matching the Recent Order History widget pattern) opening a modal to configure how many gainers and losers to display per side (3–25, default 10), persisted to `localStorage`.
- **Owned Coin Highlighting**: Any coin in the gainers/losers lists that's currently held in the user's Portfolio is visually highlighted with an accent border and a ★ badge.
- **Tighter List Spacing & Theme-Aware Scrollbars**: Reduced internal padding/margins across the widget so 10 coins per side fit without a scrollbar, and replaced the default browser scrollbar with the same theme-aware `.custom-scrollbar` styling used by the AI Copilot Sidebar and Recent Order History widget.
- **Version Bump**: Synchronized metadata to `v1.94-beta`.

## v1.93-beta (August 2026)

### Complete Help & Documentation Overhaul
- **Table of Contents Navigation**: Replaced the single-page Help document with a grouped, anchor-linked Table of Contents (Getting Started, Account Setup, Dashboard, Portfolio & Watchlist, Automated Protection, Trading & Staking, AI Features, Reports & Settings, Help) with scroll-based active-section highlighting and "Back to Table of Contents" links on every section.
- **Full Feature Coverage**: Added dedicated sections covering previously undocumented functionality: Security & Non-Custodial Architecture, AI Provider Setup (Primary/Secondary/Tertiary failover, custom prompts, web search grounding), Dashboard Widgets (all 14 widgets), Customizing Your Layout (drag/resize/hide/undo/save), the full Portfolio Table action set (Buy/Sell, Stake, Hide, Notes, Alerts, Sentiment, News), Watchlist, a deep-dive on Auto-Buy & Auto-Sell Volatility Triggers with worked examples, an expanded Trading Center walkthrough, Staking, AI Analysis Page, AI Copilot Sidebar, Tax Report, and Other Settings.
- **Buy/Sell Terminology Clarification**: Clarified throughout that USD and USDT are simply the two settlement/quote currencies on Binance.US — any listed coin can be bought or sold against either, rather than treating USD/USDT as the only tradable assets.
- **Version Bump**: Synchronized metadata to `v1.93-beta`.

## v1.92-beta (August 2026)

### Table Column Resizing, Actions Alignment, Cancel Menu Clamping, Sort Persistence & Trigger Price Fixes
- **Live Volatility % Sync for Auto-Buy/Auto-Sell Trigger Price**: Fixed an issue where editing a coin's Volatility % on the Portfolio table after an Auto-Buy or Auto-Sell trigger was already enabled did not update the trigger's displayed price in Open Orders, Order History, or Cancel modals. Synchronized `/api/set-volatility-pct` and state updates so active trigger thresholds update immediately.
- **Cancel Context Menu Viewport Boundary Clamping**: Resolved right-edge clipping when opening the Cancel Orders dropdown for coins near the right edge of the screen. Implemented responsive viewport boundary detection (`Math.max(16, Math.min(rect.right - 360, window.innerWidth - 376))`) and CSS max-width containment.
- **Table Column Sort Persistence Across Background Updates**: Fixed an issue where 5-minute background auto-refresh cycles reset or scrambled table sorting. Implemented a robust `getSortValue` numeric comparator handling computed columns (`current_value`, `avg_entry`, `pct_change`, `pnl_usd`, `allocation_pct`) with null safety and continuous `localStorage` persistence.
- **Calculated Trigger Prices in Tables & Modals**:
  - Replaced `"TRIGGER"` placeholders in Open Orders with actual calculated trigger dollar amounts (`ref_price * (1 ± vol / 100)`).
  - Added formatted trigger prices in Cancel dropdown context menus (e.g., `+5% surge @ $1.42 ($50.00 USDT)`).
  - Added dedicated `Trigger Price: $...` rows in `CancelOrderConfirmModal` and `CancelOrderModal`.
- **Unified "ACTIVE" Status Across Orders Page & Database**:
  - Normalized order statuses across Open Orders and Order History to consistently show `ACTIVE` instead of mixed `NEW`/`ACTIVE`.
  - Retroactively migrated database order records from `NEW` to `ACTIVE`.
- **Portfolio Data Key & Action Button Alignment Fixes**:
  - Restored proper payload mapping for `current_value`, `avg_entry`, `pct_change`, and stake value validation.
  - Increased `actions` column default width (`440px` for Portfolio, `350px` for Watchlist), wrapped action buttons in a flex container (`actions-cell-content`), and removed `overflow: visible` to prevent buttons from spilling outside the table card.
  - Configured `tableLayout: 'fixed'`, `<colgroup>`, and enhanced `.col-resizer-handle` grab bars with `body.is-resizing-columns` cursor locking.
- **Version Bump**: Synchronized metadata to `v1.92-beta`.

## v1.91-beta (August 2026)

### Trading Chart Overhaul, Auto-Buy/Sell Tracking & Multi-Order Cancel Workflow
- **TradingView Charting Overhaul**: Polished candlestick rendering, technical indicator overlays, and crosshair responsiveness in `TradingChart.jsx`.
- **Auto-Buy & Auto-Sell Visual Tracking**: Added distinct table row highlight color schemes for active Auto-Buy (Electric Violet), Auto-Sell (Magenta), and combined dual triggers (Purple-to-Magenta gradient).
- **SearchablePairSelect Dropdown Alignment**: Fixed z-index layering and boundary alignment for trading pair selection dropdowns across the Trading Center.
- **Multi-Order Cancellation Workflow**: Enhanced multi-order resolution allowing users to cancel specific individual exchange orders or automated volatility triggers from a unified contextual menu.
- **Version Bump**: Synchronized metadata to `v1.91-beta`.

## v1.90-beta (August 2026)

### Table Column Customization, Drag-and-Drop Reordering, Width Resizing & Trading Pair Favorites
- **Table Column Customization Modal**: Added `TableColumnModal.jsx` allowing users to toggle column visibility, reset defaults, and customize Portfolio and Watchlist table layouts.
- **Drag-and-Drop Column Reordering**: Integrated HTML5 drag-and-drop column headers allowing custom ordering persisted in `localStorage`.
- **Interactive Column Resizing**: Added draggable `.col-resizer-handle` dividers on column headers to adjust column widths on the fly.
- **Trading Pair Favorites**: Added star icon favorites to `SearchablePairSelect.jsx` to quickly bookmark and filter preferred trading pairs.
- **Cancel Order Button in Portfolio**: Integrated direct Cancel action buttons on Portfolio table rows for coins with pending orders or active triggers.
- **Version Bump**: Synchronized metadata to `v1.90-beta`.

## v1.89-beta (August 2026)

### Modernized Trading Center Tab Architecture (Place Order, Open Orders, Order History)
- **Three-Tab Trading Architecture**: Split Trading Center into dedicated **Place Order**, **Open Orders**, and **Order History** tabs with badge count indicators.
- **Dedicated Open Orders Table**: Added full open orders management view with live cancel actions, pair filtering, and real-time trigger tracking.
- **Enhanced Order History Table**: Added comprehensive order history view with canceled order toggle, pagination controls, and execution pricing breakdowns.
- **Version Bump**: Synchronized metadata to `v1.89-beta`.

## v1.88-beta (August 2026)

### AI Copilot Full Portfolio & Watchlist Context Injection
- **Global Context Pre-Search Prompt**: Overhauled the AI Copilot pre-search generation prompt to inject the user's complete portfolio, watchlist, open orders, and market trends rather than restricting analysis to a single-coin template.
- **Cross-Asset Market Intelligence**: Enabled multi-asset comparative reasoning and portfolio-wide risk synthesis in AI conversational responses.
- **Version Bump**: Synchronized metadata to `v1.88-beta`.

## v1.87-beta (August 2026)

### Watchlist Sentiment Lookback Window & Prompt Alignment
- **Configurable Sentiment Lookback Setting**: Added user setting for Watchlist AI sentiment lookback window.
- **Pre & Post Prompt Synchronization**: Aligned pre-search query generation and post-search reasoning prompts with configurable price and volume lookback timeframes.
- **Automated Database Prompt Migrations**: Added `update_db_prompts.py` to upgrade existing user AI prompts during deployment.
- **Version Bump**: Synchronized metadata to `v1.87-beta`.

## v1.86-beta (August 2026)

### Real-Time Volume Tracking in PriceHistory & 12h Price/Volume Context Injection
- **Real-Time Volume Tracking**: Added 24h quote volume logging to `PriceHistory` in `price_history_service.py`.
- **12h Price & Volume Context in AI Sentiment**: Injected 12-hour historical price and volume trend context into AI market sentiment analysis prompts for higher prediction accuracy.
- **Settings UI Controls**: Added lookback window configuration sliders in `Settings.jsx`.
- **Version Bump**: Synchronized metadata to `v1.86-beta`.

## v1.85-beta (August 2026)

### Mobile Panel Visibility, Table Horizontal Scrolling & Cache-Busting Headers
- **Full Mobile Panel Visibility**: Forced default panel visibility on mobile layouts to prevent collapsed or missing dashboard widgets.
- **Smooth Table Horizontal Scrolling**: Wrapped portfolio and watchlist tables in dedicated scroll containers with enforced min-widths for touch navigation.
- **Cache-Busting Asset Delivery**: Added cache-control headers and versioned asset parameters to prevent stale mobile browser bundles.
- **Version Bump**: Synchronized metadata to `v1.85-beta`.

## v1.84-beta (August 2026)

### Mobile Header Centering, Theme Toggle Alignment & Widget Grid Panels
- **Mobile Header Alignment**: Fixed header logo centering and theme toggle placement on mobile screens.
- **Widget Grid Responsive Layout**: Refactored `DashboardWidgetGrid.jsx` to adapt dynamically between desktop grid and mobile single-column layouts.
- **Version Bump**: Synchronized metadata to `v1.84-beta`.

## v1.83-beta (August 2026)

### Multi-Line Toast Signals, Chart Acronyms & Historical Prediction Delta Fix
- **Multi-Line Toast Notifications**: Formatted toast alert signals across multiple readable lines with distinct emoji headers and asset badges.
- **Chart Signal Indicators**: Added standardized technical signal acronyms on TradingView chart overlays.
- **Historical Prediction Ledger Delta Sign Fix**: Corrected outcome percentage delta signs in the AI prediction ledger.
- **Version Bump**: Synchronized metadata to `v1.83-beta`.

## v1.82-beta (August 2026)

### Global Toast Notifications System
- **Real-Time Global Toast Notifications**: Added `ToastNotifications.jsx` component for immediate desktop and mobile alerts upon order executions, cancellations, price alerts, and AI sentiment updates.
- **Notification Settings Toggle**: Added user preference toggle in `Settings.jsx` to enable or mute toast alerts.
- **Notification Service Integration**: Integrated toast events with `notification_service.py` and `scheduler_tasks.py`.
- **Version Bump**: Synchronized metadata to `v1.82-beta`.

## v1.81-beta (August 2026)

### Table Dash Fallbacks for Stablecoins & Watchlist Column Repositioning
- **Stablecoin Table Dashes**: Cleanly displayed dashes (`—`) for USD/USDT Avg Entry, % Change, and Sentiment in Portfolio tables.
- **Watchlist Column Alignment**: Repositioned the Sentiment column in Watchlist tables for better visual balance.
- **Version Bump**: Synchronized metadata to `v1.81-beta`.

## v1.80-beta (August 2026)

### Order History Field Mapping & Recent Trades Settings Modal
- **Recent Trades Field Normalization**: Fixed field mapping in `RecentTradesWidget.jsx` for filled prices, execution timestamps, and fees.
- **Recent Trades Settings Modal**: Added custom settings modal allowing users to configure maximum displayed orders and status filters.
- **Version Bump**: Synchronized metadata to `v1.80-beta`.

## v1.79-beta (August 2026)

### Auto-Buy Allocation Accounting in Trading Balances & Sliders
- **Usable Balance Protection**: Factored in active Auto-Buy reserve allocations when calculating usable quote currency balances in the Trading Center (`routes/portfolio.py` and `Trading.jsx`).
- **Balance Slider Adjustment**: Adjusted the trading balance slider to prevent orders from exceeding usable balances after Auto-Buy reservations.
- **Version Bump**: Synchronized metadata to `v1.79-beta`.


## v1.78-beta (August 2026)

### Modern Order Placement Redesign, Default Trading Pair Fallback & Convert Dust Table Contrast Fix
- **Default Trading Pair Fallback (`BTCUSDT`)**: Sanitized trading pair initialization in `Trading.jsx` to prevent bare fiat strings (like `USD` or `USDT`) from attempting to load chart data, defaulting reliably to `BTCUSDT` when opening the Trading Center.
- **Convert Dust Modal Dark Mode Contrast Fix**: Resolved an issue where alternating table rows displayed white backgrounds in Dark Mode due to global CSS selector precedence, ensuring high-contrast dark translucent rows and crisp readability.
- **Order Placement Section Redesign**:
  - Implemented sleek glassmorphic top header cards displaying Base Asset Available (with approximate USD value), Quote Asset Available, and a live Real-time Price card with pulsing direction indicator.
  - Modernized Order Side selection with vibrant Emerald Green (Buy) and Crimson (Sell) segmented pill controls with neon active glow.
  - Implemented modern segmented pill controls for Order Types (Market, Limit, Stop-Loss, Stop-Loss-Limit, Take-Profit, Take-Profit-Limit, OCO, Limit Maker).
  - Added streamlined input fields with embedded **`MAX`** balance button and real-time 2-way Quote Quantity sync.
  - Modernized the balance slider with custom glowing thumb and quick percentage selector pills (`0%`, `25%`, `50%`, `75%`, `100%`).
  - Added a clean Order Summary card with estimated fee and net receivable breakdown.
  - Upgraded action submit button to a high-impact glowing full-width button with reactive order state.
- **Version Bump**: Synchronized metadata to `v1.78-beta`.

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
