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

    print("Updating DefaultAIPrompt...")
    def_prompt = DefaultAIPrompt.query.first()
    if not def_prompt:
        def_prompt = DefaultAIPrompt()
        db.session.add(def_prompt)
    def_prompt.sentiment_prompt_pre = default_port_pre
    def_prompt.sentiment_prompt_post = default_port_post
    def_prompt.watchlist_sentiment_prompt_pre = default_wl_pre
    def_prompt.watchlist_sentiment_prompt_post = default_wl_post
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
    db.session.commit()
    print(f"Updated {len(user_prompts)} AIPrompt records in database.")

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
