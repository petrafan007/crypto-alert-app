import ast
import re
import os

mapping = {
    'dashboard': 'frontend_bp',
    'api_ai_coin_analysis': 'ai_bp',
    'api_portfolio_review_workflow': 'ai_bp',
    'api_ai_settings': 'ai_bp',
    'api_auto_alert': 'system_bp',
    'chart_history': 'market_bp',
    'api_coin_data': 'market_bp',
    'api_coin_data_live': 'market_bp',
    'coingecko_chart': 'market_bp',
    'api_market_data': 'market_bp',
    'api_pionex_price': 'market_bp',
    'api_settings': 'system_bp',
    'api_tax_manual_investment': 'portfolio_bp',
    'api_test_binance_connection': 'system_bp',
    'test_openai_connection': 'system_bp',
    'test_zai_connection': 'system_bp',
    'api_cbbi_data': 'market_bp',
    'api_fear_greed_index': 'market_bp',
    'favicon': 'frontend_bp',
    'help_page': 'frontend_bp',
    'login': 'frontend_bp',
    'onboarding': 'frontend_bp',
    'register': 'frontend_bp',
    'reset_password': 'frontend_bp',
    'staking_page': 'frontend_bp',
    'tax_report_page': 'frontend_bp',
    'trading_page': 'frontend_bp',
    'watchlist_page': 'frontend_bp'
}

BP_FILES = {
    'auth_bp': 'routes/auth.py',
    'portfolio_bp': 'routes/portfolio.py',
    'system_bp': 'routes/system.py',
    'ai_bp': 'routes/ai.py',
    'market_bp': 'routes/market.py',
    'frontend_bp': 'routes/frontend.py'
}

def run_migration():
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
                    func_source = re.sub(r'@app\.route', f'@{bp_name}.route', func_source)
                    appends[bp_file].append(func_source)
    
    for filepath, funcs in appends.items():
        if funcs:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write('\n\n' + '\n\n'.join(funcs) + '\n')
            print(f"Appended {len(funcs)} functions to {filepath}")

if __name__ == '__main__':
    run_migration()
