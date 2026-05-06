import os
import re

def move_functions():
    with open('main.py', 'r') as f:
        main_content = f.read()

    # Move logic to Analysis Service
    analysis_funcs = [
        'get_ai_cache', 'set_ai_cache', 'clear_expired_ai_cache', 'is_ai_enabled',
        'call_ai_with_web_search', 'log_ai_conversation', 'get_ai_conversations_count',
        'get_ai_conversations', 'get_conversation_context', 'run_sentiment_analysis_for_user',
        'fetch_news_sentiment', 'get_coin_sentiment', 'extract_sentiment', 'extract_risk_level',
        'extract_confidence', 'extract_key_insights', 'parse_ai_recommendation',
        'parse_portfolio_analysis', 'basic_recommendation_analysis', 'basic_portfolio_analysis',
        'generate_smart_alerts_for_user', 'score_recommendation', 'process_ai_conversation'
    ]
    
    # Move logic to Portfolio Service
    portfolio_funcs = [
        'get_coin_id_by_symbol', 'sync_coin_table_with_logs', 'get_last_7d_prices',
        'sync_coins_with_activities', 'trigger_portfolio_snapshot', 'get_true_portfolio_value',
        'sync_portfolio_from_binance'
    ]

    # ... and many more. But instead of manual move which is risky, 
    # the proper Flask way is to import from services IN THE BLUEPRINTS.
    # The blueprints ALREADY have the services imported in many places, 
    # but the service files themselves might be using proxies to main.py.

    # Let's check services/helpers.py
    with open('services/helpers.py', 'r') as f:
        helpers_content = f.read()
    
    if "importlib.import_module(\"main\")" in helpers_content:
        print("CRITICAL: Found importlib proxy in services/helpers.py. This is the circular source.")

move_functions()
