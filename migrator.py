import ast
import re
import os

mapping = {
    'api_account': 'auth_bp',
    'delete_account': 'auth_bp',
    'api_get_credentials': 'auth_bp',
    'onboarding': 'auth_bp',
    'register': 'auth_bp',
    'register_user': 'auth_bp',
    'reset_password': 'auth_bp',
    'test_session': 'auth_bp',
    
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

    'send_support_message': 'system_bp',
    'api_sync_coins': 'portfolio_bp',

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
    'login': 'frontend_bp',
    'staking_page': 'frontend_bp',
    'tax_report_page': 'frontend_bp',
    'trading_page': 'frontend_bp',
    'watchlist_page': 'frontend_bp',
    'api_portfolio_review_workflow': 'ai_bp',
    'api_ai_settings': 'ai_bp'
}

BP_FILES = {
    'auth_bp': 'routes/auth.py',
    'portfolio_bp': 'routes/portfolio.py',
    'system_bp': 'routes/system.py',
    'ai_bp': 'routes/ai.py',
    'market_bp': 'routes/market.py',
    'frontend_bp': 'routes/frontend.py'
}

def init_new_bps():
    if not os.path.exists('routes/market.py'):
        with open('routes/market.py', 'w', encoding='utf-8') as f:
            f.write("from flask import Blueprint, jsonify, request, render_template, current_app, send_from_directory\n")
            f.write("from flask_login import login_required, current_user\n")
            f.write("from log import logger\n")
            f.write("from core.extensions import db\n")
            f.write("from credentials import Credential\n")
            f.write("from models import Coin, Transaction, UserSetting\n")
            f.write("\nmarket_bp = Blueprint('market', __name__)\n\n")

    if not os.path.exists('routes/frontend.py'):
        with open('routes/frontend.py', 'w', encoding='utf-8') as f:
            f.write("from flask import Blueprint, render_template, send_from_directory, current_app, redirect, url_for\n")
            f.write("from flask_login import login_required, current_user\n")
            f.write("import os\n")
            f.write("\nfrontend_bp = Blueprint('frontend', __name__)\n\n")

def run_migration():
    init_new_bps()
    
    with open('main.py', 'r', encoding='utf-8') as f:
        source = f.read()
    
    tree = ast.parse(source)
    lines = source.splitlines()
    
    appends = {k: [] for k in BP_FILES.values()}
    
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if node.name in mapping:
                bp_name = mapping[node.name]
                bp_file = BP_FILES[bp_name]
                
                start_lineno = node.decorator_list[0].lineno if node.decorator_list else node.lineno
                end_lineno = getattr(node, 'end_lineno', -1)
                
                if end_lineno != -1:
                    func_source = '\n'.join(lines[start_lineno-1:end_lineno])
                    # Rename @app.route to @{bp_name}.route
                    func_source = re.sub(r'@app\.route', f'@{bp_name}.route', func_source)
                    appends[bp_file].append(func_source)
    
    for filepath, funcs in appends.items():
        if funcs:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write('\n\n' + '\n\n'.join(funcs) + '\n')
            print(f"Appended {len(funcs)} functions to {filepath}")

if __name__ == '__main__':
    run_migration()
