from services.prompt_catalog import default_prompt
from flask import current_app
import os
from core.extensions import db
from services.copilot_context import DEFAULT_COPILOT_RESPONSE_PROMPT, DEFAULT_COPILOT_SEARCH_PROMPT

def _recover_startup_state(conn):
    """Recover interrupted sentiment checks without inventing acquisition costs."""
    conn.execute(db.text("""
        UPDATE coins
        SET avg_entry = 0.0
        WHERE amount <= 0.00000001
          AND symbol != 'USD'
          AND avg_entry > 0
          AND symbol NOT IN (
              SELECT symbol FROM staked_coins
              WHERE amount > 0.00000001 AND (status IS NULL OR status != 'completed')
          )
    """))
    # Clear any lingering stuck 'Checking now...' or 'Error' sentiment
    conn.execute(db.text("""
        UPDATE coins
        SET sentiment = 'Hold',
            sentiment_reason = 'Recovered from stale checking state',
            sentiment_last_updated = CURRENT_TIMESTAMP
        WHERE sentiment = 'Checking now...'
    """))
    conn.execute(db.text("""
        UPDATE watchlist
        SET sentiment = 'Watch',
            sentiment_reason = 'Recovered from stale checking state',
            sentiment_last_updated = CURRENT_TIMESTAMP
        WHERE sentiment = 'Checking now...'
    """))
    conn.execute(db.text("""
        UPDATE coins
        SET sentiment = 'Hold',
            sentiment_reason = 'Recovered from error state',
            sentiment_last_updated = CURRENT_TIMESTAMP
        WHERE sentiment = 'Error'
    """))
    conn.execute(db.text("""
        UPDATE watchlist
        SET sentiment = 'Watch',
            sentiment_reason = 'Recovered from error state',
            sentiment_last_updated = CURRENT_TIMESTAMP
        WHERE sentiment = 'Error'
    """))
    # Fix blank asset for USDT/USD trades in all_activities
    conn.execute(db.text("""
        UPDATE all_activities
        SET asset = 'USDT'
        WHERE (asset = '' OR asset IS NULL)
          AND (txid LIKE '%USDT%' OR details LIKE '%USDT%' OR description LIKE '%USDT%')
    """))


def init_db(app=None):
    """Initialize the database with all models"""
    # Import models here to avoid circular imports
    from services.provider_resilience import ProviderState
    from research_data_models import ResearchCollectionConfig, ResearchCollectionState, ResearchCapture, ResearchDataset, ResearchJob
    from models import (
        Coin, WatchlistCoin, Notification, AIPrompt, DefaultAIPrompt, StakedCoin, StakingReward,
        AICopilotSession, AIConversation, AICache, AIAnalysisSchedule, PriceHistory,
        WebullAccountSnapshot, WebullHolding, WebullOrder, BinanceOrder, OrderHistorySyncState,
        WebullWatchlistItem, ExternalSentimentSignal, WebullTestAccount, WebullTestPosition,
        WebullTestOrder, WebullScheduledOrder,
    )
    from event_algo_models import EventStrategyConfig, EventStrategyRun, EventStrategyLog, EventStrategyAIEvaluation, EventMarketSnapshot, EventStrategyDecision, EventStrategyOrder, EventStrategyPosition, EventStrategyPerformance, EventContractOutcome, EventStrategyReport
    from portfolio_algo_models import (PortfolioStrategyConfig, PortfolioStrategyAccount,
        PortfolioStrategyPosition, PortfolioStrategyOrder, PortfolioEngineState,
        PortfolioStrategyLot, PortfolioEquitySnapshot, PortfolioAudit, PortfolioMarketObservation,
        PortfolioSignalDecision, PortfolioStrategyRevision, PortfolioAIReview, PortfolioOptionCoverage)
    from credentials import User, Credential, UserSetting, DesktopToken, OnboardingDefaultProfile
    from trading_models import TestOrder, RealOrder, TestPortfolio, TradingSettings, AllActivity, PortfolioValueHistory, StakingOrder, TrailingOrder, LadderOrder, LadderRung, SyntheticExecution
    
    target_app = app if app is not None else current_app
    ctx = target_app.app_context() if target_app else None
    
    def run_migrations():
        try:
            db.create_all()
            PortfolioStrategyConfig.__table__.create(db.engine, checkfirst=True)
            PortfolioStrategyAccount.__table__.create(db.engine, checkfirst=True)
            PortfolioStrategyPosition.__table__.create(db.engine, checkfirst=True)
            PortfolioStrategyOrder.__table__.create(db.engine, checkfirst=True)
            WebullScheduledOrder.__table__.create(db.engine, checkfirst=True)
            TrailingOrder.__table__.create(db.engine, checkfirst=True)
            LadderOrder.__table__.create(db.engine, checkfirst=True)
            LadderRung.__table__.create(db.engine, checkfirst=True)
        except Exception as e:
            print(f"db.create_all error: {e}")
        
        # Ensure recently added columns exist in PostgreSQL
        from services.jev_settings import schema_columns as jev_schema_columns
        columns_to_ensure = [
            ('user_settings', 'ai_prompt_overrides', "TEXT DEFAULT '{}'"),
            *jev_schema_columns(),
            *[(table, column, declaration) for table in ('trailing_orders', 'ladder_orders')
              for column, declaration in (
                  ('environment', 'VARCHAR(20)'), ('engine_version', 'INTEGER'),
                  ('last_price', 'FLOAT'), ('last_checked_at', 'TIMESTAMP'),
                  ('monitoring_error', 'TEXT'), ('cancel_requested', 'BOOLEAN DEFAULT FALSE'))],
            ("trailing_orders", "broker", "VARCHAR(20) DEFAULT 'binance'"),
            ("trailing_orders", "account_id", "VARCHAR(64)"),
            ("trailing_orders", "instrument_type", "VARCHAR(20) DEFAULT 'CRYPTO'"),
            ("trailing_orders", "trading_session", "VARCHAR(20) DEFAULT 'CORE'"),
            ("ladder_orders", "strategy_type", "VARCHAR(30) DEFAULT 'SYNTHETIC'"),
            ("ladder_orders", "upside_mode", "VARCHAR(20) DEFAULT 'LADDER'"),
            ("ladder_orders", "upside_target_price", "FLOAT"),
            ("ladder_orders", "upside_trail_value", "FLOAT"),
            ("ladder_orders", "upside_trail_type", "VARCHAR(10) DEFAULT 'PERCENT'"),
            ("ladder_orders", "upside_activation_price", "FLOAT"),
            ("ladder_orders", "upside_highest_price", "FLOAT"),
            ("ladder_orders", "upside_current_stop_price", "FLOAT"),
            ("ladder_orders", "downside_mode", "VARCHAR(20) DEFAULT 'NONE'"),
            ("ladder_orders", "downside_target_price", "FLOAT"),
            ("ladder_orders", "downside_trail_value", "FLOAT"),
            ("ladder_orders", "downside_trail_type", "VARCHAR(10) DEFAULT 'PERCENT'"),
            ("ladder_orders", "downside_activation_price", "FLOAT"),
            ("ladder_orders", "downside_lowest_price", "FLOAT"),
            ("ladder_orders", "downside_current_stop_price", "FLOAT"),
            ("ladder_rungs", "rung_type", "VARCHAR(20) DEFAULT 'TAKE_PROFIT'"),
            ("portfolio_market_observations", "source", "VARCHAR(80)"),
            ("portfolio_market_observations", "observed_at", "TIMESTAMP"),
            ("user_settings", "telegram_notifications_enabled", "BOOLEAN DEFAULT TRUE"),
            ("user_settings", "ai_reasoning_level", "VARCHAR DEFAULT 'medium'"),
            ("user_settings", "ai_reasoning_level_fallback", "VARCHAR DEFAULT 'medium'"),
            ("user_settings", "ai_provider_fallback", "VARCHAR"),
            ("user_settings", "ai_model_fallback", "VARCHAR"),
            ("user_settings", "watchlist_sentiment_analysis_frequency_hours", "INTEGER DEFAULT 24"),
            ("user_settings", "volatility_hours", "INTEGER DEFAULT 24"),
            ("user_settings", "automated_trigger_confirmation_minutes", "INTEGER DEFAULT 15"),
            ("user_settings", "webull_environment", "VARCHAR(20) DEFAULT 'production'"),
            ("user_settings", "webull_account_selection_mode", "VARCHAR(20) DEFAULT 'all'"),
            ("user_settings", "webull_default_account_id", "VARCHAR(100)"),
            ("user_settings", "webull_account_aliases", "TEXT DEFAULT '{}'"),
            ("user_settings", "webull_connected_accounts", "TEXT DEFAULT '[]'"),
            ("user_settings", "webull_enabled_account_ids", "TEXT DEFAULT '[]'"),
            ("user_settings", "webull_ai_scheduling_enabled", "BOOLEAN DEFAULT FALSE"),
            ("user_settings", "webull_crypto_sentiment_frequency_hours", "INTEGER DEFAULT 24"),
            ("user_settings", "webull_equity_sentiment_frequency_hours", "INTEGER DEFAULT 24"),
            ("user_settings", "webull_crypto_sentiment_horizon_hours", "INTEGER DEFAULT 24"),
            ("user_settings", "webull_equity_sentiment_horizon_hours", "INTEGER DEFAULT 24"),
            ("user_settings", "webull_test_mode_enabled", "BOOLEAN DEFAULT FALSE"),
            ("user_settings", "tax_webull_manual_invested_updated", "VARCHAR"),
            ("user_settings", "onboarding_required", "BOOLEAN DEFAULT FALSE"),
            ("user_settings", "onboarding_completed", "BOOLEAN DEFAULT FALSE"),
            ("user_settings", "onboarding_page", "VARCHAR(40) DEFAULT 'security-choice'"),
            ("user_settings", "onboarding_exchange_choice", "VARCHAR(20)"),
            ("user_settings", "onboarding_binance_verified", "BOOLEAN DEFAULT FALSE"),
            ("user_settings", "onboarding_webull_verified", "BOOLEAN DEFAULT FALSE"),
            ("user_settings", "onboarding_two_factor_deferred", "BOOLEAN DEFAULT FALSE"),
            ("user_settings", "onboarding_ai_skipped", "BOOLEAN DEFAULT FALSE"),
            ("user_settings", "onboarding_search_skipped", "BOOLEAN DEFAULT FALSE"),
            ("user_settings", "onboarding_telegram_skipped", "BOOLEAN DEFAULT FALSE"),
            ("user_settings", "ai_provider_quaternary", "VARCHAR"),
            ("user_settings", "ai_model_quaternary", "VARCHAR"),
            ("user_settings", "ai_reasoning_level_quaternary", "VARCHAR DEFAULT 'medium'"),
            ("credentials", "webull_app_key", "VARCHAR"),
            ("credentials", "webull_app_secret", "VARCHAR"),
            ("credentials", "webull_access_token", "VARCHAR"),
            ("credentials", "webull_token_environment", "VARCHAR(20)"),
            ("credentials", "webull_token_status", "VARCHAR(20)"),
            ("credentials", "webull_token_expires_at", "TIMESTAMP"),
            ("credentials", "openai_key_quaternary", "VARCHAR"),
            ("credentials", "zai_key_quaternary", "VARCHAR"),
            ("credentials", "perplexity_key_quaternary", "VARCHAR"),
            ("credentials", "gemini_key_quaternary", "VARCHAR"),
            ("credentials", "inception_key_quaternary", "VARCHAR"),
            ("credentials", "ollama_key", "VARCHAR"),
            ("credentials", "ollama_key_fallback", "VARCHAR"),
            ("credentials", "ollama_key_tertiary", "VARCHAR"),
            ("credentials", "ollama_key_quaternary", "VARCHAR"),
            ("webull_holdings", "webull_position_id", "VARCHAR(100)"),
            ("webull_holdings", "instrument_id", "VARCHAR(100)"),
            ("webull_holdings", "display_name", "VARCHAR(200)"),
            ("webull_holdings", "is_etf", "BOOLEAN DEFAULT FALSE"),
            ("webull_holdings", "underlying_symbol", "VARCHAR(40)"),
            ("webull_holdings", "option_expiration", "VARCHAR(20)"),
            ("webull_holdings", "option_strike", "FLOAT"),
            ("webull_holdings", "option_type", "VARCHAR(12)"),
            ("webull_holdings", "option_multiplier", "FLOAT"),
            ("webull_holdings", "event_outcome", "VARCHAR(10)"),
            ("webull_holdings", "custom_lower_type", "VARCHAR(10) DEFAULT '#'"),
            ("webull_holdings", "custom_upper_type", "VARCHAR(10) DEFAULT '#'"),
            ("webull_holdings", "custom_lower_val", "FLOAT"),
            ("webull_holdings", "custom_upper_val", "FLOAT"),
            ("webull_holdings", "custom_lower_pct", "FLOAT"),
            ("webull_holdings", "custom_upper_pct", "FLOAT"),
            ("webull_holdings", "alert_enabled", "BOOLEAN DEFAULT FALSE"),
            ("webull_holdings", "volatility_pct", "FLOAT"),
            ("webull_holdings", "sentiment_tracking_enabled", "BOOLEAN DEFAULT TRUE"),
            ("webull_holdings", "hidden", "BOOLEAN DEFAULT FALSE"),
            ("webull_holdings", "auto_hidden", "BOOLEAN DEFAULT FALSE"),
            ("webull_holdings", "force_visible", "BOOLEAN DEFAULT FALSE"),
            ("webull_orders", "fee", "FLOAT"),
            ("webull_orders", "fee_asset", "VARCHAR(20)"),
            ("portfolio_value_history", "source", "VARCHAR(20) DEFAULT 'all'"),
            ("coins", "sentiment_reason", "TEXT"),
            ("watchlist", "sentiment_reason", "TEXT"),
            ("coins", "sentiment_failover_history", "TEXT"),
            ("watchlist", "sentiment_failover_history", "TEXT"),
            ("external_sentiment_signals", "failover_history", "TEXT"),
            ("sentiment_history", "failover_history", "TEXT"),
            ("coins", "cached_news", "TEXT"),
            ("watchlist", "cached_news", "TEXT"),
            ("coins", "cached_news_date", "TIMESTAMP"),
            ("watchlist", "cached_news_date", "TIMESTAMP"),
            ("watchlist", "sentiment_last_updated", "TIMESTAMP"),
            ("ai_prompts", "watchlist_sentiment_prompt_pre", "TEXT"),
            ("ai_prompts", "watchlist_sentiment_prompt_post", "TEXT"),
            ("user_settings", "copilot_chat_pre", "TEXT"),
            ("user_settings", "copilot_chat_post", "TEXT"),
            ("user_settings", "copilot_title_prompt", "TEXT"),
            ("ai_prompts", "copilot_title_prompt", "TEXT"),
            ("ai_prompts", "event_strategy_audit_prompt", "TEXT"),
            ("default_ai_prompts", "watchlist_sentiment_prompt_pre", "TEXT"),
            ("default_ai_prompts", "watchlist_sentiment_prompt_post", "TEXT"),
            ("default_ai_prompts", "copilot_chat_pre", "TEXT"),
            ("default_ai_prompts", "copilot_chat_post", "TEXT"),
            ("default_ai_prompts", "copilot_title_prompt", "TEXT"),
            ("default_ai_prompts", "event_strategy_audit_prompt", "TEXT"),
            ("coins", "auto_sell_enabled", "BOOLEAN DEFAULT FALSE"),
            ("coins", "auto_sell_volatility_pct", "FLOAT"),
            ("coins", "auto_sell_quote_currency", "VARCHAR(10) DEFAULT 'USDT'"),
            ("coins", "auto_sell_triggered_at", "TIMESTAMP"),
            ("coins", "auto_sell_confirmation_started_at", "TIMESTAMP"),
            ("coins", "auto_buy_enabled", "BOOLEAN DEFAULT FALSE"),
            ("coins", "auto_buy_volatility_pct", "FLOAT"),
            ("coins", "auto_buy_quote_currency", "VARCHAR(10) DEFAULT 'USDT'"),
            ("coins", "auto_buy_amount", "FLOAT"),
            ("coins", "auto_buy_triggered_at", "TIMESTAMP"),
            ("coins", "auto_buy_confirmation_started_at", "TIMESTAMP"),
            ("watchlist", "auto_sell_enabled", "BOOLEAN DEFAULT FALSE"),
            ("watchlist", "auto_sell_volatility_pct", "FLOAT"),
            ("watchlist", "auto_sell_quote_currency", "VARCHAR(10) DEFAULT 'USDT'"),
            ("watchlist", "auto_sell_triggered_at", "TIMESTAMP"),
            ("watchlist", "auto_sell_confirmation_started_at", "TIMESTAMP"),
            ("watchlist", "auto_buy_enabled", "BOOLEAN DEFAULT FALSE"),
            ("watchlist", "auto_buy_volatility_pct", "FLOAT"),
            ("watchlist", "auto_buy_quote_currency", "VARCHAR(10) DEFAULT 'USDT'"),
            ("watchlist", "auto_buy_amount", "FLOAT"),
            ("watchlist", "auto_buy_triggered_at", "TIMESTAMP"),
            ("watchlist", "auto_buy_confirmation_started_at", "TIMESTAMP"),
            ("price_history", "volume", "FLOAT DEFAULT 0.0"),
            ("price_history", "quote_volume", "FLOAT DEFAULT 0.0"),
            ("user_settings", "sentiment_history_lookback_hours", "INTEGER DEFAULT 12"),
            ("user_settings", "watchlist_sentiment_history_lookback_hours", "INTEGER DEFAULT 12"),
            ("user_settings", "sentiment_forecast_horizon_hours", "INTEGER"),
            ("user_settings", "watchlist_sentiment_forecast_horizon_hours", "INTEGER"),
            ("user_settings", "ai_outcome_neutral_threshold_pct", "FLOAT DEFAULT 5.0"),
            ("user_settings", "sentiment_buy_immediately_correct_pct", "FLOAT DEFAULT 5.0"),
            ("user_settings", "sentiment_buy_immediately_wrong_pct", "FLOAT DEFAULT 5.0"),
            ("user_settings", "sentiment_consider_buying_correct_pct", "FLOAT DEFAULT 5.0"),
            ("user_settings", "sentiment_consider_buying_wrong_pct", "FLOAT DEFAULT 5.0"),
            ("user_settings", "sentiment_hold_correct_pct", "FLOAT DEFAULT 5.0"),
            ("user_settings", "sentiment_hold_wrong_pct", "FLOAT DEFAULT 5.0"),
            ("user_settings", "sentiment_hold_steady_pct", "FLOAT DEFAULT 1.0"),
            ("user_settings", "sentiment_consider_selling_correct_pct", "FLOAT DEFAULT 5.0"),
            ("user_settings", "sentiment_consider_selling_wrong_pct", "FLOAT DEFAULT 5.0"),
            ("user_settings", "sentiment_sell_immediately_correct_pct", "FLOAT DEFAULT 5.0"),
            ("user_settings", "sentiment_sell_immediately_wrong_pct", "FLOAT DEFAULT 5.0"),
            ("user_settings", "sentiment_chart_default_range", "VARCHAR(10) DEFAULT '3d'"),
            ("user_settings", "event_strategy_audit_hours", "INTEGER DEFAULT 6"),
            ("user_settings", "event_strategy_audit_prompt", "TEXT"),
            ("user_settings", "max_slippage_pct", "FLOAT DEFAULT 2.0"),
            ("coins", "sentiment_tracking_enabled", "BOOLEAN DEFAULT TRUE"),
            ("watchlist", "sentiment_tracking_enabled", "BOOLEAN DEFAULT TRUE"),
            ("sentiment_history", "forecast_horizon_hours", "FLOAT"),
            ("sentiment_history", "target_evaluation_at", "TIMESTAMP"),
            ("sentiment_history", "evaluation_method", "VARCHAR(32)"),
            ("sentiment_history", "grading_config", "TEXT"),
            ("watchlist", "asset_type", "VARCHAR(20) DEFAULT 'crypto'"),
            ("webull_test_positions", "underlying_symbol", "VARCHAR(40)"),
            ("webull_test_positions", "event_outcome", "VARCHAR(10)"),
            ("event_strategy_runs", "diagnostics_json", "TEXT DEFAULT '[]'"),
            ("event_strategy_orders", "realized_pnl", "FLOAT DEFAULT 0.0"),
            ("event_strategy_orders", "settled_at", "TIMESTAMP"),
            ("event_strategy_configs", "ai_config", "TEXT DEFAULT '{}'"),
            ("ai_conversations", "client_request_id", "VARCHAR(100)"),
        ]
        # ── Guard against idle-in-transaction sessions blocking ALTER TABLE ──
        # ALTER TABLE requires AccessExclusive lock, which is incompatible
        # with AccessShareLock held by idle-in-transaction sessions from the
        # background worker or rogue processes.  Terminate them up-front and
        # use a tight lock_timeout so we fail fast instead of hanging forever.
        def _kill_idle_transactions():
            """Terminate idle-in-transaction sessions that block DDL."""
            try:
                with db.engine.begin() as conn:
                    result = conn.execute(db.text(
                        "SELECT pg_terminate_backend(pid) "
                        "FROM pg_stat_activity "
                        "WHERE state = 'idle in transaction' "
                        "  AND pid != pg_backend_pid()"
                    ))
                    killed = result.rowcount
                    if killed:
                        print(f"Migration safety: terminated {killed} idle-in-transaction session(s)")
            except Exception as ex:
                print(f"Migration safety: could not clean idle transactions: {ex}")

        for table, col, col_type in columns_to_ensure:
            try:
                with db.engine.begin() as conn:
                    conn.execute(db.text("SET LOCAL lock_timeout = '5s'"))
                    conn.execute(db.text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}"))
            except Exception as ex:
                if 'lock timeout' in str(ex).lower():
                    print(f"Migration lock timeout on {table}.{col}, clearing blockers and retrying…")
                    _kill_idle_transactions()
                    try:
                        with db.engine.begin() as conn:
                            conn.execute(db.text("SET LOCAL lock_timeout = '10s'"))
                            conn.execute(db.text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}"))
                    except Exception as retry_ex:
                        print(f"Migration FAILED for {table}.{col} after retry: {retry_ex}")
                else:
                    print(f"Migration note for {table}.{col}: {ex}")

        try:
            with db.engine.begin() as conn:
                conn.execute(db.text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_conversations_user_request "
                    "ON ai_conversations (user_id, client_request_id, sender) "
                    "WHERE client_request_id IS NOT NULL"
                ))
        except Exception as ex:
            print(f"Migration note for Copilot request idempotency index: {ex}")

        from services.event_universe import repair_legacy_default_series
        repair_legacy_default_series()

        # Sessions make manual Copilot chats explicit and isolated.  Preserve
        # existing history by grouping unassigned legacy manual messages into
        # one read-only-in-spirit session per user rather than discarding or
        # silently mixing that history into future chats.
        try:
            AICopilotSession.__table__.create(db.engine, checkfirst=True)
            legacy_user_rows = db.session.execute(db.text(
                "SELECT DISTINCT user_id FROM ai_conversations "
                "WHERE prompt_type = 'manual' AND conversation_id IS NULL"
            )).fetchall()
            for row in legacy_user_rows:
                user_id = int(row[0])
                legacy_session_id = f"legacy-copilot-{user_id}"
                session = db.session.get(AICopilotSession, legacy_session_id)
                if not session:
                    session = AICopilotSession(
                        id=legacy_session_id,
                        user_id=user_id,
                        title="Earlier Copilot history",
                    )
                    db.session.add(session)
                db.session.execute(db.text(
                    "UPDATE ai_conversations SET conversation_id = :session_id "
                    "WHERE user_id = :user_id AND prompt_type = 'manual' "
                    "AND conversation_id IS NULL"
                ), {'session_id': legacy_session_id, 'user_id': user_id})

            imported_session_rows = db.session.execute(db.text(
                "SELECT DISTINCT user_id, conversation_id FROM ai_conversations "
                "WHERE prompt_type = 'manual' AND conversation_id IS NOT NULL"
            )).fetchall()
            for row in imported_session_rows:
                user_id, session_id = int(row[0]), str(row[1])
                if not db.session.get(AICopilotSession, session_id):
                    db.session.add(AICopilotSession(
                        id=session_id,
                        user_id=user_id,
                        title="Earlier Copilot history",
                    ))
            db.session.commit()
        except Exception as ex:
            db.session.rollback()
            print(f"Migration note for Copilot sessions: {ex}")

        try:
            with db.engine.begin() as conn:
                conn.execute(db.text(
                    "CREATE INDEX IF NOT EXISTS ix_webull_holding_option_contract "
                    "ON webull_holdings (user_id, instrument_id)"
                ))
                conn.execute(db.text("""
                    CREATE TABLE IF NOT EXISTS webull_test_accounts (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL UNIQUE,
                        cash_balance FLOAT NOT NULL DEFAULT 0.0,
                        currency VARCHAR(10) NOT NULL DEFAULT 'USD',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS webull_test_positions (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        symbol VARCHAR(80) NOT NULL,
                        instrument_type VARCHAR(40) NOT NULL DEFAULT 'EQUITY',
                        side VARCHAR(20) NOT NULL DEFAULT 'LONG',
                        quantity FLOAT NOT NULL DEFAULT 0.0,
                        cost_price FLOAT NOT NULL DEFAULT 0.0,
                        last_price FLOAT DEFAULT 0.0,
                        market_value FLOAT DEFAULT 0.0,
                        unrealized_pnl FLOAT DEFAULT 0.0,
                        contract_multiplier INTEGER NOT NULL DEFAULT 1,
                        option_type VARCHAR(10),
                        option_strike FLOAT,
                        option_expiration VARCHAR(20),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT uq_webull_test_pos_user_sym_type_side UNIQUE (user_id, symbol, instrument_type, side)
                    );
                    CREATE TABLE IF NOT EXISTS webull_test_orders (
                        id SERIAL PRIMARY KEY,
                        order_id VARCHAR(80) NOT NULL UNIQUE,
                        user_id INTEGER NOT NULL,
                        symbol VARCHAR(80) NOT NULL,
                        instrument_type VARCHAR(40) NOT NULL DEFAULT 'EQUITY',
                        side VARCHAR(20) NOT NULL,
                        order_type VARCHAR(30) NOT NULL,
                        quantity FLOAT NOT NULL,
                        limit_price FLOAT,
                        stop_price FLOAT,
                        filled_price FLOAT,
                        filled_quantity FLOAT DEFAULT 0.0,
                        status VARCHAR(30) NOT NULL DEFAULT 'Filled',
                        combo_type VARCHAR(30),
                        combo_orders TEXT,
                        time_in_force VARCHAR(20) DEFAULT 'DAY',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """))
        except Exception as ex:
            print(f"Migration note for webull test tables: {ex}")

        try:
            with db.engine.begin() as conn:
                conn.execute(db.text("UPDATE portfolio_value_history SET source = 'all' WHERE source IS NULL"))
        except Exception as ex:
            print(f"Migration note for portfolio history source: {ex}")

        try:
            with db.engine.begin() as conn:
                # glm-4.7-flashx was a non-standard slug that never shipped — migrate it to the active free-tier model.
                # Note: glm-4.7-flash is now a valid Z.AI model and must NOT be migrated away.
                conn.execute(db.text("UPDATE user_settings SET ai_model = 'glm-4.5-flash' WHERE ai_model = 'glm-4.7-flashx'"))
                conn.execute(db.text("UPDATE user_settings SET ai_model_secondary = 'glm-4.5-flash' WHERE ai_model_secondary = 'glm-4.7-flashx'"))
                conn.execute(db.text("UPDATE user_settings SET ai_model_fallback = 'glm-4.5-flash' WHERE ai_model_fallback = 'glm-4.7-flashx'"))
                conn.execute(db.text("UPDATE user_settings SET ai_model_tertiary = 'glm-4.5-flash' WHERE ai_model_tertiary = 'glm-4.7-flashx'"))
        except Exception as ex:
            print(f"Migration note for Z.AI model update: {ex}")

        try:
            with db.engine.begin() as conn:
                _recover_startup_state(conn)
        except Exception as e:
            print(f"Startup migration note: {e}")

        # Seed default prompts if empty
        default_market_pre = (
            default_prompt('seed.database.default_market_pre')
        )
        default_market_post = (
            default_prompt('seed.database.default_market_post')
        )
        default_port_review_pre = (
            default_prompt('seed.database.default_port_review_pre')
        )
        default_port_review_post = (
            default_prompt('seed.database.default_port_review_post')
        )
        default_coin_analysis_pre = (
            default_prompt('seed.database.default_coin_analysis_pre')
        )
        default_coin_analysis_post = (
            default_prompt('seed.database.default_coin_analysis_post')
        )
        default_port_pre = (
            default_prompt('seed.database.default_port_pre')
        )
        default_port_post = (
            default_prompt('seed.database.default_port_post')
        )
        default_wl_pre = (
            default_prompt('seed.database.default_wl_pre')
        )
        default_wl_post = (
            default_prompt('seed.database.default_wl_post')
        )
        default_copilot_pre = DEFAULT_COPILOT_SEARCH_PROMPT
        default_copilot_post = DEFAULT_COPILOT_RESPONSE_PROMPT
        default_copilot_title_prompt = default_prompt('seed.database.default_copilot_title_prompt')
        default_event_audit_prompt = (
            default_prompt('seed.database.default_event_audit_prompt')
        )
        try:
            def_prompt = DefaultAIPrompt.query.first()
            if not def_prompt:
                def_prompt = DefaultAIPrompt()
                db.session.add(def_prompt)
            for field, value in {
                'market_analysis_pre': default_market_pre,
                'market_analysis_post': default_market_post,
                'portfolio_review_pre': default_port_review_pre,
                'portfolio_review_post': default_port_review_post,
                'coin_analysis_pre': default_coin_analysis_pre,
                'coin_analysis_post': default_coin_analysis_post,
                'sentiment_prompt_pre': default_port_pre,
                'sentiment_prompt_post': default_port_post,
                'watchlist_sentiment_prompt_pre': default_wl_pre,
                'watchlist_sentiment_prompt_post': default_wl_post,
                'copilot_chat_pre': default_copilot_pre,
                'copilot_chat_post': default_copilot_post,
                'copilot_title_prompt': default_copilot_title_prompt,
                'event_strategy_audit_prompt': default_event_audit_prompt,
            }.items():
                if getattr(def_prompt, field, None) is None:
                    setattr(def_prompt, field, value)
            # Product defaults advance with the release. Per-user custom
            # prompts remain untouched and receive mandatory runtime rules.
            def_prompt.copilot_chat_pre = default_copilot_pre
            def_prompt.copilot_chat_post = default_copilot_post
            db.session.commit()
            
            user_prompts = AIPrompt.query.all()
            for up in user_prompts:
                for field, value in {
                    'market_analysis_pre': default_market_pre,
                    'market_analysis_post': default_market_post,
                    'portfolio_review_pre': default_port_review_pre,
                    'portfolio_review_post': default_port_review_post,
                    'coin_analysis_pre': default_coin_analysis_pre,
                    'coin_analysis_post': default_coin_analysis_post,
                    'sentiment_prompt_pre': default_port_pre,
                    'sentiment_prompt_post': default_port_post,
                    'watchlist_sentiment_prompt_pre': default_wl_pre,
                    'watchlist_sentiment_prompt_post': default_wl_post,
                    'copilot_chat_pre': default_copilot_pre,
                    'copilot_chat_post': default_copilot_post,
                    'copilot_title_prompt': default_copilot_title_prompt,
                    'event_strategy_audit_prompt': default_event_audit_prompt,
                }.items():
                    if getattr(up, field, None) is None:
                        setattr(up, field, value)
            db.session.commit()

            user_settings = UserSetting.query.all()
            for us in user_settings:
                if getattr(us, 'copilot_chat_pre', None) is None:
                    us.copilot_chat_pre = default_copilot_pre
                if getattr(us, 'copilot_chat_post', None) is None:
                    us.copilot_chat_post = default_copilot_post
                if getattr(us, 'copilot_title_prompt', None) is None:
                    us.copilot_title_prompt = default_copilot_title_prompt
                if getattr(us, 'event_strategy_audit_hours', None) is None:
                    us.event_strategy_audit_hours = 6
                if getattr(us, 'event_strategy_audit_prompt', None) is None:
                    us.event_strategy_audit_prompt = default_event_audit_prompt
            db.session.commit()

            # Keep persisted AI Copilot defaults aligned with the active product brand.
            # This narrowly replaces only the former product name and leaves all other
            # user-authored prompt content untouched.
            legacy_brand = "Crypto Alert App"
            current_brand = "Crypto & Securities Dashboard"
            for prompt in [def_prompt, *user_prompts, *user_settings]:
                for field in ('copilot_chat_pre', 'copilot_chat_post'):
                    value = getattr(prompt, field, None)
                    if isinstance(value, str) and legacy_brand in value:
                        setattr(prompt, field, value.replace(legacy_brand, current_brand))
            db.session.commit()
        except Exception as seed_err:
            print(f"Error seeding default prompts: {seed_err}")
            db.session.rollback()

        try:
            # v2.87.6: Tune Event Strategy Engine active configs based on AI audit recommendations
            import json
            for cfg in EventStrategyConfig.query.all():
                modified = False
                sig = json.loads(cfg.signal_config or "{}")
                if sig.get("max_ai_calls_per_hour", 12) <= 12:
                    sig["max_ai_calls_per_hour"] = 60
                    modified = True
                if sig.get("ai_batch_size", 5) <= 5:
                    sig["ai_batch_size"] = 10
                    modified = True
                if sig.get("ai_batch_interval_seconds", 300) >= 300:
                    sig["ai_batch_interval_seconds"] = 120
                    modified = True
                if sig.get("min_net_edge", 0.03) >= 0.03:
                    sig["min_net_edge"] = 0.015
                    modified = True
                if sig.get("fee_per_contract", 0.02) >= 0.02:
                    sig["fee_per_contract"] = 0.015
                    modified = True
                if sig.get("min_confidence", 0.55) > 0.50:
                    sig["min_confidence"] = 0.50
                    modified = True
                if modified:
                    cfg.signal_config = json.dumps(sig)

                risk = json.loads(cfg.risk_config or "{}")
                if risk.get("min_volume", 1.0) >= 1.0:
                    risk["min_volume"] = 0.0
                    cfg.risk_config = json.dumps(risk)
                    modified = True

                if modified:
                    db.session.add(cfg)
            db.session.commit()
        except Exception as tuning_err:
            db.session.rollback()
            print(f"Migration note for event strategy config tuning: {tuning_err}")

    if ctx:
        with ctx:
            run_migrations()
    else:
        run_migrations()
    
    return db
