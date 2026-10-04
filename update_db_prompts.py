from services.prompt_catalog import default_prompt
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from main import app
from core.extensions import db
from models import DefaultAIPrompt, AIPrompt
from credentials import UserSetting
from services.copilot_context import DEFAULT_COPILOT_RESPONSE_PROMPT, DEFAULT_COPILOT_SEARCH_PROMPT

with app.app_context():
    default_market_pre = (
        default_prompt('seed.update_db_prompts.default_market_pre')
    )
    default_market_post = (
        default_prompt('seed.update_db_prompts.default_market_post')
    )
    default_port_review_pre = (
        default_prompt('seed.update_db_prompts.default_port_review_pre')
    )
    default_port_review_post = (
        default_prompt('seed.update_db_prompts.default_port_review_post')
    )
    default_coin_analysis_pre = (
        default_prompt('seed.update_db_prompts.default_coin_analysis_pre')
    )
    default_coin_analysis_post = (
        default_prompt('seed.update_db_prompts.default_coin_analysis_post')
    )
    default_port_pre = (
        default_prompt('seed.update_db_prompts.default_port_pre')
    )
    default_port_post = (
        default_prompt('seed.update_db_prompts.default_port_post')
    )
    default_wl_pre = (
        default_prompt('seed.update_db_prompts.default_wl_pre')
    )
    default_wl_post = (
        default_prompt('seed.update_db_prompts.default_wl_post')
    )

    default_copilot_pre = DEFAULT_COPILOT_SEARCH_PROMPT
    default_copilot_post = DEFAULT_COPILOT_RESPONSE_PROMPT

    print("Updating DefaultAIPrompt...")
    def_prompt = DefaultAIPrompt.query.first()
    if not def_prompt:
        def_prompt = DefaultAIPrompt()
        db.session.add(def_prompt)
    def_prompt.market_analysis_pre = default_market_pre
    def_prompt.market_analysis_post = default_market_post
    def_prompt.portfolio_review_pre = default_port_review_pre
    def_prompt.portfolio_review_post = default_port_review_post
    def_prompt.coin_analysis_pre = default_coin_analysis_pre
    def_prompt.coin_analysis_post = default_coin_analysis_post
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
        up.market_analysis_pre = default_market_pre
        up.market_analysis_post = default_market_post
        up.portfolio_review_pre = default_port_review_pre
        up.portfolio_review_post = default_port_review_post
        up.coin_analysis_pre = default_coin_analysis_pre
        up.coin_analysis_post = default_coin_analysis_post
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
