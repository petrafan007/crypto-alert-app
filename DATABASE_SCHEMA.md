# Database Schema Documentation (PostgreSQL)

## 🚨 Migration Complete (January 2026)
The application has been fully migrated from multiple SQLite databases to a unified **PostgreSQL** database.

**Connection**: `postgresql:///cryptoalertapp?host=/var/run/postgresql&port=5433`

## Unified Database Tables

### coins
Stores user's cryptocurrency portfolio holdings with current balances synced from Binance.US API.

- `id` (SERIAL): Primary key
- `symbol` (VARCHAR(10)): Cryptocurrency symbol (e.g., 'BTC')
- `user_id` (INTEGER): Foreign key to users
- `current` (FLOAT): Current price in USD
- `amount` (FLOAT): Total amount held
- `alert_enabled` (BOOLEAN): Whether price alerts are enabled
- `is_manual` (BOOLEAN): Whether entry was manually added
- `hidden` (BOOLEAN): Whether the coin is hidden from the portfolio table
- `auto_hidden` (BOOLEAN): System-managed visibility flag
- `force_visible` (BOOLEAN): User override for visibility
- `custom_lower_type` (VARCHAR(10)): Type of lower threshold ('%' or '$')
- `custom_upper_type` (VARCHAR(10)): Type of upper threshold ('%' or '$')
- `custom_lower_val` (FLOAT): Custom lower threshold value
- `custom_upper_val` (FLOAT): Custom upper threshold value
- `avg_entry` (FLOAT): Average entry price
- `initial_value` (FLOAT): Initial investment value in USD
- `purchase_date` (VARCHAR(25)): Purchase date
- `sentiment` (VARCHAR(50)): AI-generated sentiment
- `sentiment_last_updated` (TIMESTAMP): Last sentiment analysis timestamp
- `note` (TEXT): User notes
- `volatility_pct` (FLOAT): Volatility alert threshold
- `last_volatility_alert_time` (TIMESTAMP): Last alert timestamp
- `updated_at` (TIMESTAMP): Last update timestamp

### user_settings
User-specific configuration for AI and application behavior.

- `id` (SERIAL): Primary key
- `user_id` (INTEGER): Foreign key to users
- `copilot_chat_pre` (TEXT): AI Copilot sidebar pre-search system prompt
- `copilot_chat_post` (TEXT): AI Copilot sidebar Stage 3 analysis prompt
- `sentiment_analysis_frequency_hours` (INTEGER): Hours between sentiment analyses (default 24)

### watchlist
Stores cryptocurrency symbols the user wants to watch.

- `id` (SERIAL): Primary key
- `symbol` (VARCHAR(10)): Cryptocurrency symbol
- `user_id` (INTEGER): Foreign key to users
- `down_alert` (FLOAT): Lower price alert threshold
- `up_alert` (FLOAT): Upper price alert threshold
- `alert_enabled` (BOOLEAN): Whether alerts are enabled
- `note` (TEXT): User notes
- `favorite` (BOOLEAN): Favorite flag
- `hidden` (BOOLEAN): Hidden flag
- `action` (VARCHAR(10)): Action type (e.g., 'Watch')
- `current_price` (FLOAT): Current price
- `sentiment` (VARCHAR(50)): Sentiment
- `volatility_pct` (FLOAT): Volatility threshold
- `last_volatility_alert_time` (TIMESTAMP): Last alert timestamp

### staked_coins
Stores active staking positions.

- `id` (SERIAL): Primary key
- `user_id` (INTEGER): Owner
- `symbol` (VARCHAR(10)): Asset symbol
- `amount` (FLOAT): Amount staked
- `staked_at` (TIMESTAMP): Stake timestamp
- `stake_transaction_id` (VARCHAR(100)): Binance ID
- `apr` (FLOAT): Annual Percentage Rate
- `apy` (FLOAT): Annual Percentage Yield
- `reward_asset` (VARCHAR(10)): Reward asset
- `unstaking_period_hours` (INTEGER): Cool-down period
- `auto_restake` (BOOLEAN): Auto-restake flag
- `status` (VARCHAR(20)): 'active', 'unstaking', 'completed'
- `unstake_requested_at` (TIMESTAMP): Request time
- `unstake_available_at` (TIMESTAMP): Completion time

### staking_rewards
Stores historical staking rewards.

- `id` (SERIAL): Primary key
- `user_id` (INTEGER): Owner
- `staked_coin_id` (INTEGER): Foreign key to staked_coins
- `asset` (VARCHAR(10)): Reward asset
- `amount` (FLOAT): Reward amount
- `usd_value` (FLOAT): USD value
- `earned_at` (TIMESTAMP): Receipt time
- `auto_restaked` (BOOLEAN): Auto-restake status
- `tran_id` (BIGINT): Binance transaction ID

### staking_orders
Record of staking/unstaking requests.

- `id` (SERIAL): Primary key
- `user_id` (INTEGER): Owner
- `symbol` (VARCHAR(20)): Asset
- `action` (VARCHAR(20)): 'STAKE' or 'UNSTAKE'
- `amount` (FLOAT): Amount
- `status` (VARCHAR(20)): 'SUCCESS', 'PENDING', etc.
- `transaction_id` (VARCHAR(100)): External ID
- `apr` (FLOAT) / `apy` (FLOAT): Rates at time of order
- `reward_asset` (VARCHAR(20)): Asset for rewards
- `usd_value` (FLOAT): USD value at order time
- `created_at` (TIMESTAMP): Order creation time

### credentials
Encrypted storage for API credentials and provider settings.

- `id` (SERIAL): Primary key
- `user_id` (INTEGER): Foreign key to users
- `api_key` / `api_secret` (VARCHAR): **Unified Binance.US Credentials** (Encrypted)
- `openai_key` / `zai_key` / `perplexity_key` / `gemini_key` (VARCHAR): AI Keys (Encrypted)
- `ai_provider` (VARCHAR): Selected provider
- `telegram_token` / `telegram_chat_id` (VARCHAR): Telegram setup (Encrypted)
- `brave_search_api_key` / `brave_search_api_key_fallback` (TEXT): Web Search Keys (Encrypted)

### users
Account information and login metadata.

- `id` (SERIAL): Primary key
- `username` (VARCHAR(80)): Unique username
- `pwd_hash` (VARCHAR(128)): Password hash
- `email` (VARCHAR(120)): Unique email
- `last_login` (TIMESTAMP): Last login timestamp

### all_activities
Comprehensive transaction log for all exchanges and actions.

- `id` (SERIAL): Primary key
- `user_id` (INTEGER): Owner
- `date` (TIMESTAMP): Transaction timestamp (UTC)
- `type` (VARCHAR(20)): 'BUY', 'SELL', 'DEPOSIT', 'WITHDRAWAL'
- `asset` (VARCHAR(10)): Symbol
- `amount` (FLOAT): Quantity
- `proceeds` (FLOAT): USD proceeds
- `cost_basis` (FLOAT): USD cost basis
- `gain_loss` (FLOAT): USD gain/loss
- `fee` (FLOAT): Transaction fee
- `txid` (VARCHAR(100)): Transaction identifier
- `status` (VARCHAR(20)): 'completed', etc.
- `avg_entry` (FLOAT): Price per unit
- `price_sold_at` (FLOAT): Exit price
- `exchange` (VARCHAR(20)): 'binance' or 'coinbase'

### portfolio_value_history
Historical snapshots of total portfolio value.

- `id` (SERIAL): Primary key
- `user_id` (INTEGER): Owner
- `date` (VARCHAR(30)): Date string
- `timestamp` (TIMESTAMP): Precision time
- `value` (FLOAT): USD total value
- `change_24h` / `change_pct_24h` (FLOAT): Performance metrics

### price_history
Asset price time-series data for hover charts.

- `id` (SERIAL): Primary key
- `symbol` (VARCHAR(20)): Asset
- `price` (FLOAT): Price in USD
- `timestamp` (BIGINT): Unix timestamp
- `exchange` (VARCHAR(20)): 'binance'

### ai_prompts / default_ai_prompts
Customized and default AI analysis instructions.

- `user_id` / `id` (INTEGER): Key
- `coin_analysis_pre` / `post` (TEXT): Coin analysis logic
- `market_analysis_pre` / `post` (TEXT): Market review logic
- `sentiment_prompt_pre` / `post` (TEXT): Sentiment logic

### desktop_tokens
Authentication tokens for the cross-platform desktop application.

- `id` (SERIAL): Primary key
- `user_id` (INTEGER): Owner
- `token` (VARCHAR(64)): Unique access token
- `created_at` / `last_used` (TIMESTAMP): Timing

### credential_settings
System-wide persistent configuration.

- `key` (VARCHAR): Identifier (e.g., encryption key)
- `value` (TEXT): Stored value

## Security
Sensitive data (API keys, tokens) is encrypted using **Fernet symmetric encryption**. Encryption keys are managed through the `credential_settings` table and system-level configuration.
