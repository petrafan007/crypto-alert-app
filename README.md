# Crypto Alert App

**Last Updated**: May 2026

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

## Service Management & Ports
**Service Name**: `crypto-dashboard.service`

**Ports**:
- **Development/Source Port**: `5011` (Used when running `main.py` directly for local testing)
- **Production Systemd Port**: `5010` (Used by the active local production instance running as a background service)

**Restart Command**: `sudo systemctl restart crypto-dashboard.service`
**Check Logs Command**: `sudo journalctl -u crypto-dashboard.service -f`

## External Integrations
- **Binance.US API (EXCLUSIVE)**: Use `tld='us'` for all client initializations.
- **AI Analysis**: Multi-provider support (OpenAI, Z.AI, Perplexity, Gemini). Integrated web search (Brave Search with DuckDuckGo fallback).
- **Telegram API**: Price alert notifications via Bot API.

## Recent Major Updates (May 2026)
- **Modular Architecture Refactoring**: Migrated the monolithic `main.py` into a clean Flask Blueprint architecture (`routes/` and `services/`).
- **GitHub Portability**: Removed local hardcoded paths, extracted credentials into `.env`, and implemented a clean `.gitignore`.
- **PostgreSQL Migration**: Completed refactoring to ORM. Legacy SQLite databases were purged.
- **Unified Credentials**: Centralized API key management.
- **Staking System**: Full Binance.US staking support with real-time APY.
