from flask import current_app
import os
from core.extensions import db

def init_db(app=None):
    """Initialize the database with all models"""
    # Import models here to avoid circular imports
    from models import Coin, WatchlistCoin, Notification, AIPrompt, DefaultAIPrompt, StakedCoin, StakingReward, AIConversation, AICache, AIAnalysisSchedule, PriceHistory, WebullAccountSnapshot, WebullHolding, ExternalSentimentSignal
    from credentials import User, Credential, UserSetting, DesktopToken
    from trading_models import TestOrder, RealOrder, TestPortfolio, TradingSettings, AllActivity, PortfolioValueHistory, StakingOrder
    
    target_app = app if app is not None else current_app
    ctx = target_app.app_context() if target_app else None
    
    def run_migrations():
        try:
            db.create_all()
        except Exception as e:
            print(f"db.create_all error: {e}")
        
        # Ensure recently added columns exist in PostgreSQL
        columns_to_ensure = [
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
            ("credentials", "webull_app_key", "VARCHAR"),
            ("credentials", "webull_app_secret", "VARCHAR"),
            ("credentials", "webull_access_token", "VARCHAR"),
            ("credentials", "webull_token_environment", "VARCHAR(20)"),
            ("credentials", "webull_token_status", "VARCHAR(20)"),
            ("credentials", "webull_token_expires_at", "TIMESTAMP"),
            ("webull_holdings", "webull_position_id", "VARCHAR(100)"),
            ("webull_holdings", "instrument_id", "VARCHAR(100)"),
            ("webull_holdings", "underlying_symbol", "VARCHAR(40)"),
            ("webull_holdings", "option_expiration", "VARCHAR(20)"),
            ("webull_holdings", "option_strike", "FLOAT"),
            ("webull_holdings", "option_type", "VARCHAR(12)"),
            ("webull_holdings", "option_multiplier", "FLOAT"),
            ("webull_holdings", "custom_lower_type", "VARCHAR(10) DEFAULT '#'"),
            ("webull_holdings", "custom_upper_type", "VARCHAR(10) DEFAULT '#'"),
            ("webull_holdings", "custom_lower_val", "FLOAT"),
            ("webull_holdings", "custom_upper_val", "FLOAT"),
            ("webull_holdings", "custom_lower_pct", "FLOAT"),
            ("webull_holdings", "custom_upper_pct", "FLOAT"),
            ("webull_holdings", "alert_enabled", "BOOLEAN DEFAULT FALSE"),
            ("webull_holdings", "volatility_pct", "FLOAT"),
            ("webull_holdings", "sentiment_tracking_enabled", "BOOLEAN DEFAULT TRUE"),
            ("portfolio_value_history", "source", "VARCHAR(20) DEFAULT 'all'"),
            ("coins", "sentiment_reason", "TEXT"),
            ("watchlist", "sentiment_reason", "TEXT"),
            ("coins", "cached_news", "TEXT"),
            ("watchlist", "cached_news", "TEXT"),
            ("coins", "cached_news_date", "TIMESTAMP"),
            ("watchlist", "cached_news_date", "TIMESTAMP"),
            ("watchlist", "sentiment_last_updated", "TIMESTAMP"),
            ("ai_prompts", "watchlist_sentiment_prompt_pre", "TEXT"),
            ("ai_prompts", "watchlist_sentiment_prompt_post", "TEXT"),
            ("ai_prompts", "copilot_chat_pre", "TEXT"),
            ("ai_prompts", "copilot_chat_post", "TEXT"),
            ("default_ai_prompts", "watchlist_sentiment_prompt_pre", "TEXT"),
            ("default_ai_prompts", "watchlist_sentiment_prompt_post", "TEXT"),
            ("default_ai_prompts", "copilot_chat_pre", "TEXT"),
            ("default_ai_prompts", "copilot_chat_post", "TEXT"),
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
            ("user_settings", "max_slippage_pct", "FLOAT DEFAULT 2.0"),
            ("coins", "sentiment_tracking_enabled", "BOOLEAN DEFAULT TRUE"),
            ("watchlist", "sentiment_tracking_enabled", "BOOLEAN DEFAULT TRUE"),
            ("sentiment_history", "forecast_horizon_hours", "FLOAT"),
            ("sentiment_history", "target_evaluation_at", "TIMESTAMP"),
            ("sentiment_history", "evaluation_method", "VARCHAR(32)"),
            ("sentiment_history", "grading_config", "TEXT"),
            ("watchlist", "asset_type", "VARCHAR(20) DEFAULT 'crypto'"),
        ]
        for table, col, col_type in columns_to_ensure:
            try:
                with db.engine.begin() as conn:
                    conn.execute(db.text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}"))
            except Exception as ex:
                print(f"Migration note for {table}.{col}: {ex}")

        try:
            with db.engine.begin() as conn:
                conn.execute(db.text(
                    "CREATE INDEX IF NOT EXISTS ix_webull_holding_option_contract "
                    "ON webull_holdings (user_id, instrument_id)"
                ))
        except Exception as ex:
            print(f"Migration note for webull option contract index: {ex}")

        try:
            with db.engine.begin() as conn:
                conn.execute(db.text("UPDATE portfolio_value_history SET source = 'all' WHERE source IS NULL"))
        except Exception as ex:
            print(f"Migration note for portfolio history source: {ex}")

        try:
            with db.engine.begin() as conn:
                conn.execute(db.text("UPDATE coins SET avg_entry = 0.0 WHERE amount <= 0.00000001 AND symbol != 'USD' AND avg_entry > 0"))
        except Exception:
            pass

        # Seed default prompts if empty
        default_market_pre = (
            "You are an intelligent search query generator for comprehensive market analysis across cryptocurrency and traditional securities (equities and ETFs) as of {datetime}. "
            "Analyze the current macro landscape, including crypto market trends, major equity indices (S&P 500, Nasdaq), Federal Reserve interest rate expectations, sector rotations, and breaking geopolitical/economic news. "
            "Generate 1 to 3 targeted, highly effective search queries to gather real-time data on both digital assets and securities markets."
        )
        default_market_post = (
            "You are a premier cross-asset market strategist specializing in both cryptocurrency (Binance.US / Webull) and traditional securities (equities and ETFs on Webull) as of {datetime}. "
            "Synthesize the provided web search results, market indicators, and macroeconomic developments into a cohesive market briefing.\n\n"
            "Evaluate:\n"
            "1. Macroeconomic environment (interest rates, inflation, treasury yields, dollar strength).\n"
            "2. Cryptocurrency market momentum, Bitcoin/Ethereum trend strength, and altcoin dynamics.\n"
            "3. Equity market trend, sector leadership, and risk-on vs. risk-off sentiment.\n"
            "4. Cross-market correlation and actionable tactical outlook for active traders.\n\n"
            "Provide a structured, executive-ready analysis with concise bullet points and clear risk parameters."
        )
        default_port_review_pre = (
            "You are an intelligent search query generator for multi-asset portfolio review as of {datetime}. "
            "The portfolio contains holdings across both cryptocurrency (Binance.US, Webull) and traditional securities/equities (Webull). "
            "Generate 1 to 3 targeted search queries to identify breaking news, recent earnings, technical momentum shifts, and regulatory catalysts impacting these specific holdings and their respective asset classes."
        )
        default_port_review_post = (
            "You are a professional portfolio manager and multi-asset strategist evaluating a unified portfolio of cryptocurrency (Binance.US / Webull) and securities (equities, ETFs, options on Webull) as of {datetime}. "
            "Based on current live prices, cost basis, unrealized P&L, asset weighting, and recent web search news:\n"
            "1. Assess portfolio risk balance between high-volatility crypto and equity allocations.\n"
            "2. Identify top outperforming positions, concentration risks, and underperforming assets.\n"
            "3. Highlight near-term catalysts (earnings, protocol upgrades, macro events) affecting key holdings.\n"
            "4. Provide actionable portfolio rebalancing, risk mitigation, and profit-taking/stop-loss recommendations.\n\n"
            "Format your response clearly with concise sections and actionable takeaways."
        )
        default_coin_analysis_pre = (
            "You are an intelligent search query generator for single-asset research as of {datetime}. "
            "The target asset is {symbol}, which may be a cryptocurrency or a traditional equity/ETF/security traded on Binance.US or Webull. "
            "Generate 1 to 3 targeted search queries to find the latest breaking news, technical price action, earnings reports, regulatory updates, or protocol developments for {symbol}."
        )
        default_coin_analysis_post = (
            "You are a senior investment analyst evaluating {symbol} as of {datetime}. "
            "Whether {symbol} is a cryptocurrency or traditional equity/security, synthesize the live price data, consecutive hourly price/volume dynamics, and recent web search findings to deliver an in-depth asset evaluation:\n"
            "1. Key Drivers & Catalysts: Summarize recent news, corporate earnings or protocol updates, and macroeconomic tailwinds/headwinds.\n"
            "2. Technical & Volume Assessment: Analyze price momentum, key support/resistance levels, and volume behavior.\n"
            "3. Risk/Reward Profile: Evaluate downside risks versus upside potential over the immediate and medium horizons.\n"
            "4. Strategic Conclusion: Clear, definitive outlook on whether to buy, hold, accumulate on dips, or trim exposure.\n\n"
            "Keep your analysis objective, data-driven, and well-structured."
        )
        default_port_pre = (
            "You are an intelligent search query generator for multi-asset sentiment analysis as of {datetime}. "
            "I currently hold {amount} of {symbol} in my portfolio (cryptocurrency or equity/security). "
            "Search the web and find the latest news, market sentiment, technical momentum, and major catalysts for {symbol} to evaluate my position."
        )
        default_port_post = (
            "You are a cross-asset financial analysis expert with access to current web search results, live pricing, and historical price/volume data for {symbol} as of {datetime}. "
            "I currently hold {amount} of {symbol} in my portfolio across my connected exchange/broker accounts (Binance.US or Webull). "
            "Based on the current live price, the consecutive hourly price & volume history, recent market data, price trends, volume dynamics, catalysts, and risk/reward provided, evaluate whether I should hold, accumulate more, or take profits/cut losses on this holding.\n\n"
            "CRITICAL: You MUST respond with ONLY a valid JSON object in this exact format, with no other text before or after it:\n\n"
            "{\n"
            '  "sentiment": "<one of: Buy Immediately, Consider Buying, Hold, Consider Selling, Sell Immediately>",\n'
            '  "reason": "<1-2 sentences explaining your recommendation based on the live price, hourly price/volume dynamics, position risk/reward, and recent news>"\n'
            "}\n\n"
            "Do NOT include any explanation, preamble, markdown, or text outside of the JSON object."
        )
        default_wl_pre = (
            "You are an intelligent search query generator for watchlist evaluation as of {datetime}. "
            "I am currently monitoring {symbol} on my watchlist as a prospective investment opportunity (cryptocurrency or equity/security). "
            "Search the web and find the latest news, market sentiment, technical momentum, and major catalysts for {symbol} to evaluate whether now is an attractive entry point."
        )
        default_wl_post = (
            "You are a cross-asset financial analysis expert with access to current web search results, live pricing, and historical price/volume data for {symbol} as of {datetime}. "
            "I am monitoring {symbol} on my watchlist across Binance.US and Webull and evaluating whether to initiate a new position or stay on the sidelines. "
            "Based on the current live price, the consecutive hourly price & volume history, recent market data, price trends, volume dynamics, catalysts, and prospective risk/reward provided, evaluate whether I should enter the market, continue monitoring, or avoid this asset.\n\n"
            "CRITICAL: You MUST respond with ONLY a valid JSON object in this exact format, with no other text before or after it:\n\n"
            "{\n"
            '  "sentiment": "<one of: Avoid, Watch, Consider Buying, Definitely Buy>",\n'
            '  "reason": "<1-2 sentences explaining your recommendation based on current market conditions, hourly price/volume dynamics, prospective entry risk/reward, and recent news>"\n'
            "}\n\n"
            "Do NOT include any explanation, preamble, markdown, or text outside of the JSON object."
        )
        default_copilot_pre = (
            "You are the search intelligence module for the AI Copilot in Crypto & Securities Dashboard as of {datetime}. "
            "You assist an active multi-asset trader and portfolio manager who has real-time access to their live portfolio holdings, watchlist assets, pending orders, execution logs, and sentiment ratings across both Binance.US (cryptocurrency) and Webull (cryptocurrency, equities, ETFs, options). "
            "Analyze the user's inquiry, conversation context, and market themes to generate 1 to 3 targeted, highly effective search queries for real-time market data, breaking news, corporate earnings, regulatory developments, technical momentum, or protocol updates needed to provide a thorough, accurate answer."
        )
        default_copilot_post = (
            "You are the AI Copilot for Crypto & Securities Dashboard, an expert cross-asset portfolio strategist and multi-market analyst. "
            "You have direct access to the user's live portfolio, watchlist, pending orders, execution history, recent sentiment ratings & reasons, market analysis workflows, and recent sidebar conversation history across both Binance.US and Webull as of {datetime}.\n\n"
            "When answering the user:\n"
            "- Provide actionable, data-backed guidance considering technical momentum, sentiment ratings, risk/reward, and current portfolio exposure across both digital assets and traditional securities.\n"
            "- When referencing sentiment signals (e.g. 'Consider Selling', 'Consider Buying', 'Hold'), explain the underlying market drivers, catalysts, and whether contrarian opportunities or caution are warranted.\n"
            "- Directly address proposed trades, limit/stop orders, entry/exit price targets, and market trends with clear reasoning for both crypto and equities.\n"
            "- CRITICAL EXCHANGE ARCHITECTURE RULE (OCO ORDERS): On Binance and Binance.US, an OCO (One-Cancels-the-Other) order is natively created and managed by the exchange matching engine as an Order List (orderListId) containing two linked legs: a STOP_LOSS_LIMIT leg and a LIMIT_MAKER leg. When the user's data shows an active OCO order bracket with an OrderListId or paired limit/stop-loss legs, this IS a confirmed, native, fully linked exchange OCO order. The exchange automatically cancels the opposing leg if either executes or triggers. NEVER tell the user their OCO orders are 'separate independent orders', 'unlinked', or that 'Binance.US does not support an OCO wrapper'. NEVER instruct the user to 'link them into an OCO order'—they are ALREADY natively linked on the exchange. Analyze them directly as a unified OCO trading strategy.\n"
            "- Maintain a concise, structured, and professional tone with bullet points where appropriate."
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
            }.items():
                if getattr(def_prompt, field, None) is None:
                    setattr(def_prompt, field, value)
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

    if ctx:
        with ctx:
            run_migrations()
    else:
        run_migrations()
    
    return db
