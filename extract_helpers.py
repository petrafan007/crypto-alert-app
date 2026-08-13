import os
import re
import ast

def extract_helper_source(filepath, helper_names):
    sources = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()
    
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in helper_names:
            start_lineno = node.lineno
            end_lineno = getattr(node, 'end_lineno', -1)
            if end_lineno != -1:
                sources[node.name] = '\n'.join(lines[start_lineno-1:end_lineno])
    return sources

def main():
    helpers_to_extract = [
        'get_user_from_bearer', 'get_manual_tax_investment', 'set_manual_tax_investment',
        'set_initial_price_on_gift', 'calculate_auto_alert', '_coerce_activity_datetime',
        '_format_activity_date', '_calculate_portfolio_performance',
        '_respond_with_staking_dashboard_payload', '_dashboard_staking_response',
        'coin_to_dict', 'binance_has_staking_permission', 'create_extension_jwt',
        'sync_binance_logs', 'decrypt_secret', 'ensure_background_jobs', 'fetch_crypto_price',
        'clear_alert_state'
    ]
    
    sources = extract_helper_source('main.py', helpers_to_extract)
    
    # We will just write all these helpers to routes/helpers.py
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
            
    print(f"Extracted {len(sources)} helpers to routes/helpers.py")

if __name__ == '__main__':
    main()
