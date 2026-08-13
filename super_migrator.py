import ast
import re
import os

missing_routes = [
  "api_sync_coins", "api_test_db", "api_account", "staking_page",
  "api_dust_history", "dashboard", "api_set_initial_price",
  "api_watchlist_live", "tax_report_page", "set_custom_pct_type",
  "api_auto_alert", "api_staking_rewards", "check_credential",
  "api_cbbi_data", "hide_coin", "set_alert", "register_user",
  "api_update_note", "watchlist_page", "set_volatility_pct",
  "api_trading_pairs", "debug_background_jobs", "api_tax_report",
  "test_session", "api_staking_history", "api_coin_data",
  "trading_page", "api_test_brave_search", "delete_account",
  "api_unstake_asset", "api_hidden_coins", "export_tax_report_csv",
  "api_dust_assets", "api_stakeable_coins", "set_watch_alert",
  "debug_alerts", "api_staking_assets", "api_coin_data_live",
  "api_clear_alert_state", "set_favorite", "api_dust_convert",
  "onboarding", "api_watchlist_add", "favicon", "chart_history",
  "unhide_all", "mark_onboarding_complete", "api_pionex_price",
  "send_support_message", "api_market_data", "api_delete_coin",
  "coingecko_chart", "set_watch_alert_type", "api_fear_greed_index",
  "set_watchlist_favorite", "api_watchlist", "api_stake_asset",
  "set_custom_pct", "help_page", "api_watchlist_remove",
  "api_get_credentials", "api_tax_manual_investment", "api_test_simple",
  
  # Also these were in my mapping but maybe didn't show up in missing because of overlapping names, let's include them just in case they aren't defined in the blueprint yet:
  "login", "register", "reset_password", "api_settings",
  "api_ai_coin_analysis", "api_portfolio_review_workflow", "api_ai_settings",
  "api_test_binance_connection", "test_openai_connection", "test_zai_connection"
]

mapping = {
    'api_account': 'auth_bp',
    'delete_account': 'auth_bp',
    'api_get_credentials': 'auth_bp',
    'onboarding': 'auth_bp',
    'register': 'auth_bp',
    'register_user': 'auth_bp',
    'reset_password': 'auth_bp',
    'test_session': 'auth_bp',
    'login': 'auth_bp',
    
    'api_auto_alert': 'market_bp',
    'chart_history': 'market_bp',
    'api_coin_data': 'market_bp',
    'api_coin_data_live': 'market_bp',
    'coingecko_chart': 'market_bp',
    'api_market_data': 'market_bp',
    'api_pionex_price': 'market_bp',
    'api_cbbi_data': 'market_bp',
    'api_fear_greed_index': 'market_bp',

    'api_watchlist': 'portfolio_bp',
    'api_watchlist_live': 'portfolio_bp',
    'api_watchlist_add': 'portfolio_bp',
    'api_watchlist_remove': 'portfolio_bp',
    'set_watchlist_favorite': 'portfolio_bp',
    'set_favorite': 'portfolio_bp',
    'hide_coin': 'portfolio_bp',
    'api_hidden_coins': 'portfolio_bp',
    'unhide_all': 'portfolio_bp',
    'api_delete_coin': 'portfolio_bp',
    'api_dust_assets': 'portfolio_bp',
    'api_dust_convert': 'portfolio_bp',
    'api_dust_history': 'portfolio_bp',
    'api_staking_assets': 'portfolio_bp',
    'api_staking_history': 'portfolio_bp',
    'api_staking_rewards': 'portfolio_bp',
    'api_stake_asset': 'portfolio_bp',
    'api_stakeable_coins': 'portfolio_bp',
    'api_unstake_asset': 'portfolio_bp',
    'api_tax_report': 'portfolio_bp',
    'export_tax_report_csv': 'portfolio_bp',
    'api_tax_manual_investment': 'portfolio_bp',
    'api_sync_coins': 'portfolio_bp',

    'api_clear_alert_state': 'system_bp',
    'set_alert': 'system_bp',
    'set_custom_pct': 'system_bp',
    'set_custom_pct_type': 'system_bp',
    'api_set_initial_price': 'system_bp',
    'set_volatility_pct': 'system_bp',
    'set_watch_alert': 'system_bp',
    'set_watch_alert_type': 'system_bp',
    'api_update_note': 'system_bp',
    'api_settings': 'system_bp',
    'mark_onboarding_complete': 'system_bp',
    'send_support_message': 'system_bp',
    'check_credential': 'system_bp',
    'debug_alerts': 'system_bp',
    'debug_background_jobs': 'system_bp',
    'api_test_db': 'system_bp',
    'api_test_binance_connection': 'system_bp',
    'api_test_brave_search': 'system_bp',
    'test_openai_connection': 'system_bp',
    'api_test_simple': 'system_bp',
    'test_zai_connection': 'system_bp',
    'api_trading_pairs': 'system_bp',

    'dashboard': 'frontend_bp',
    'favicon': 'frontend_bp',
    'help_page': 'frontend_bp',
    'staking_page': 'frontend_bp',
    'tax_report_page': 'frontend_bp',
    'trading_page': 'frontend_bp',
    'watchlist_page': 'frontend_bp',
    
    'api_ai_coin_analysis': 'ai_bp',
    'api_portfolio_review_workflow': 'ai_bp',
    'api_ai_settings': 'ai_bp'
}

imports_to_add = """
from datetime import timedelta, datetime
import requests
import threading
from flask import send_file, request, jsonify, render_template, current_app, redirect, url_for
from flask_login import current_user, login_required, login_user, logout_user
from models import Coin, Transaction, WatchlistCoin, UserSetting, Notification
from credentials import Credential, User
from core.extensions import db
from log import logger
from routes.helpers import *
from services.binance_service import BinanceService
from services.pionex_service import PionexService
from services.openai_service import OpenAIService
from services.perplexity_service import PerplexityService
from services.gemini_service import GeminiService
from services.zai_service import ZaiService
"""

def setup_files():
    # Write helpers.py
    with open('main.py', 'r', encoding='utf-8') as f:
        source = f.read()
    
    helpers_to_extract = [
        'get_user_from_bearer', 'get_manual_tax_investment', 'set_manual_tax_investment',
        'set_initial_price_on_gift', 'calculate_auto_alert', '_coerce_activity_datetime',
        '_format_activity_date', '_calculate_portfolio_performance',
        '_respond_with_staking_dashboard_payload', '_dashboard_staking_response',
        'coin_to_dict', 'binance_has_staking_permission', 'create_extension_jwt',
        'sync_binance_logs', 'decrypt_secret', 'ensure_background_jobs', 'fetch_crypto_price',
        'clear_alert_state'
    ]
    
    tree = ast.parse(source)
    lines = source.splitlines()
    sources = {}
    
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in helpers_to_extract:
            start_lineno = node.lineno
            end_lineno = getattr(node, 'end_lineno', -1)
            if end_lineno != -1:
                sources[node.name] = '\n'.join(lines[start_lineno-1:end_lineno])
                
    with open('routes/helpers.py', 'w', encoding='utf-8') as f:
        f.write("from log import logger\n")
        f.write("from core.extensions import db\n")
        f.write("from models import Coin, Transaction, UserSetting, WatchlistCoin\n")
        f.write("from credentials import Credential, User\n")
        f.write("import requests\n")
        f.write("from datetime import datetime, timedelta\n")
        f.write("import threading\n")
        f.write("import time\n")
        f.write("import hashlib\n")
        f.write("import hmac\n")
        f.write("import base64\n")
        f.write("import json\n")
        f.write("import jwt\n")
        f.write("from cryptography.fernet import Fernet\n")
        f.write("import os\n\n")
        
        f.write("background_threads = {}\n")
        f.write("AUTO_ALERT_CACHE = {}\n")
        f.write("ALERT_CHECK_INTERVAL = 300\n\n")
        
        for name, src in sources.items():
            f.write(src + '\n\n')

    # Ensure market and frontend blueprints exist
    if not os.path.exists('routes/market.py'):
        with open('routes/market.py', 'w', encoding='utf-8') as f:
            f.write("from flask import Blueprint\n")
            f.write("market_bp = Blueprint('market', __name__)\n\n")
            
    if not os.path.exists('routes/frontend.py'):
        with open('routes/frontend.py', 'w', encoding='utf-8') as f:
            f.write("from flask import Blueprint\n")
            f.write("frontend_bp = Blueprint('frontend', __name__)\n\n")

def run_migration():
    with open('main.py', 'r', encoding='utf-8') as f:
        source = f.read()
    
    tree = ast.parse(source)
    lines = source.splitlines()
    
    # We will inject the missing imports at the top of each blueprint first
    bps = [
        'routes/auth.py', 'routes/portfolio.py', 'routes/system.py', 
        'routes/ai.py', 'routes/market.py', 'routes/frontend.py'
    ]
    for bp in bps:
        if os.path.exists(bp):
            with open(bp, 'r', encoding='utf-8') as f:
                content = f.read()
            with open(bp, 'w', encoding='utf-8') as f:
                f.write(imports_to_add + "\n" + content)

    # Now append the missing functions
    appends = {k: [] for k in bps}
    
    bp_name_map = {
        'auth_bp': 'routes/auth.py',
        'portfolio_bp': 'routes/portfolio.py',
        'system_bp': 'routes/system.py',
        'ai_bp': 'routes/ai.py',
        'market_bp': 'routes/market.py',
        'frontend_bp': 'routes/frontend.py'
    }

    # Set of existing functions in blueprints to avoid duplicates
    existing = set()
    for bp in bps:
        if os.path.exists(bp):
            with open(bp, 'r', encoding='utf-8') as f:
                bp_tree = ast.parse(f.read())
            for node in ast.walk(bp_tree):
                if isinstance(node, ast.FunctionDef):
                    existing.add((bp, node.name))

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if node.name in mapping:
                bp_name = mapping[node.name]
                bp_file = bp_name_map[bp_name]
                
                # Check if it's already in the blueprint!
                if (bp_file, node.name) in existing:
                    continue
                
                start_lineno = node.decorator_list[0].lineno if node.decorator_list else node.lineno
                end_lineno = getattr(node, 'end_lineno', -1)
                
                if end_lineno != -1:
                    func_source = '\n'.join(lines[start_lineno-1:end_lineno])
                    func_source = re.sub(r'@app\.route', f'@{bp_name}.route', func_source)
                    appends[bp_file].append(func_source)
                    existing.add((bp_file, node.name))
    
    for filepath, funcs in appends.items():
        if funcs:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write('\n\n' + '\n\n'.join(funcs) + '\n')
            print(f"Appended {len(funcs)} missing functions to {filepath}")

if __name__ == '__main__':
    setup_files()
    run_migration()
    print("Migration of helper functions, imports, and missing endpoints is complete.")
