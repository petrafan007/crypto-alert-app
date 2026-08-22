import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from main import app
from core.extensions import db
from models import DefaultAIPrompt, AIPrompt
from credentials import UserSetting

with app.app_context():
    default_port_pre = (
        "You are an intelligent search query generator for cryptocurrency analysis. "
        "I currently hold {amount} of {symbol} in my portfolio. "
        "Search the web and find the latest news, market sentiment, technical momentum, and major catalysts for {symbol} as of {datetime} to evaluate my position."
    )
    default_port_post = (
        "You are a cryptocurrency and financial analysis expert with access to current web search results, live pricing, and historical price/volume data for {symbol} as of {datetime}. "
        "I currently hold {amount} of {symbol} in my portfolio. "
        "Based on the current live price, the consecutive hourly price & volume history, recent market data, price trends, volume dynamics, catalysts, and risk/reward provided, evaluate whether I should hold, accumulate more, or take profits/cut losses on this holding.\n\n"
        "CRITICAL: You MUST respond with ONLY a valid JSON object in this exact format, with no other text before or after it:\n\n"
        "{\n"
        '  "sentiment": "<one of: Buy Immediately, Consider Buying, Hold, Consider Selling, Sell Immediately>",\n'
        '  "reason": "<1-2 sentences explaining your recommendation based on the live price, hourly price/volume dynamics, position risk/reward, and recent news>"\n'
        "}\n\n"
        "Do NOT include any explanation, preamble, markdown, or text outside of the JSON object."
    )
    default_wl_pre = (
        "You are an intelligent search query generator for cryptocurrency analysis. "
        "I am currently monitoring {symbol} on my watchlist as a prospective investment opportunity. "
        "Search the web and find the latest news, market sentiment, technical momentum, and major catalysts for {symbol} as of {datetime} to evaluate whether now is a good entry point."
    )
    default_wl_post = (
        "You are a cryptocurrency and financial analysis expert with access to current web search results, live pricing, and historical price/volume data for {symbol} as of {datetime}. "
        "I am monitoring {symbol} on my watchlist and evaluating whether to initiate a new position or stay on the sidelines. "
        "Based on the current live price, the consecutive hourly price & volume history, recent market data, price trends, volume dynamics, catalysts, and prospective risk/reward provided, evaluate whether I should enter the market, continue monitoring, or avoid this coin.\n\n"
        "CRITICAL: You MUST respond with ONLY a valid JSON object in this exact format, with no other text before or after it:\n\n"
        "{\n"
        '  "sentiment": "<one of: Avoid, Watch, Consider Buying, Definitely Buy>",\n'
        '  "reason": "<1-2 sentences explaining your recommendation based on current market conditions, hourly price/volume dynamics, prospective entry risk/reward, and recent news>"\n'
        "}\n\n"
        "Do NOT include any explanation, preamble, markdown, or text outside of the JSON object."
    )

    default_copilot_pre = (
        "You are the search intelligence module for the AI Copilot in Crypto Alert App as of {datetime}. "
        "You assist an active cryptocurrency trader and portfolio manager who has real-time access to their live portfolio, watchlist coins, pending orders, execution logs, and sentiment ratings. "
        "Analyze the user's inquiry, conversation context, and market themes to generate 1 to 3 targeted, highly effective search queries for real-time market data, breaking news, regulatory developments, technical momentum, or protocol updates needed to provide a thorough, accurate answer."
    )
    default_copilot_post = (
        "You are the AI Copilot for Crypto Alert App, an expert cryptocurrency portfolio strategist and market analyst. "
        "You have direct access to the user's live portfolio, watchlist, pending orders, recent sentiment ratings & reasons, market analysis workflows, and recent sidebar conversation history as of {datetime}.\n\n"
        "When answering the user:\n"
        "- Provide actionable, data-backed guidance considering technical momentum, sentiment ratings, risk/reward, and current portfolio exposure.\n"
        "- When referencing sentiment signals (e.g. 'Consider Selling', 'Consider Buying', 'Hold'), explain the underlying market drivers, catalysts, and whether contrarian opportunities or caution are warranted.\n"
        "- Directly address proposed trades, limit orders, entry/exit price targets, and market trends with clear reasoning.\n"
        "- Maintain a concise, structured, and professional tone with bullet points where appropriate."
    )

    print("Updating DefaultAIPrompt...")
    def_prompt = DefaultAIPrompt.query.first()
    if not def_prompt:
        def_prompt = DefaultAIPrompt()
        db.session.add(def_prompt)
    def_prompt.sentiment_prompt_pre = default_port_pre
    def_prompt.sentiment_prompt_post = default_port_post
    def_prompt.watchlist_sentiment_prompt_pre = default_wl_pre
    def_prompt.watchlist_sentiment_prompt_post = default_wl_post
    def_prompt.copilot_chat_pre = default_copilot_pre
    def_prompt.copilot_chat_post = default_copilot_post
    db.session.commit()
    print("DefaultAIPrompt updated successfully.")

    print("Updating user AIPrompt records...")
    user_prompts = AIPrompt.query.all()
    for up in user_prompts:
        print(f"Updating AIPrompt for user_id={up.user_id}...")
        up.sentiment_prompt_pre = default_port_pre
        up.sentiment_prompt_post = default_port_post
        up.watchlist_sentiment_prompt_pre = default_wl_pre
        up.watchlist_sentiment_prompt_post = default_wl_post
        up.copilot_chat_pre = default_copilot_pre
        up.copilot_chat_post = default_copilot_post
    db.session.commit()
    print(f"Updated {len(user_prompts)} AIPrompt records in database.")

    print("Updating UserSetting records...")
    user_settings = UserSetting.query.all()
    for us in user_settings:
        print(f"Updating UserSetting for user_id={us.user_id}...")
        us.copilot_chat_pre = default_copilot_pre
        us.copilot_chat_post = default_copilot_post
    db.session.commit()
    print(f"Updated {len(user_settings)} UserSetting records in database.")

    # Ensure user_settings lookback columns
    try:
        with db.engine.begin() as conn:
            conn.execute(db.text("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS sentiment_history_lookback_hours INTEGER DEFAULT 12"))
            conn.execute(db.text("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS watchlist_sentiment_history_lookback_hours INTEGER DEFAULT 12"))
            conn.execute(db.text("ALTER TABLE price_history ADD COLUMN IF NOT EXISTS volume FLOAT DEFAULT 0.0"))
            conn.execute(db.text("ALTER TABLE price_history ADD COLUMN IF NOT EXISTS quote_volume FLOAT DEFAULT 0.0"))
            print("DB columns verified and migrated.")
    except Exception as e:
        print(f"Column migration notice: {e}")

print("=== DATABASE UPDATE COMPLETE ===")
