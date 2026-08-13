import os

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

bps = [
    'routes/auth.py',
    'routes/portfolio.py',
    'routes/system.py',
    'routes/ai.py',
    'routes/market.py',
    'routes/frontend.py'
]

for bp in bps:
    with open(bp, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Prepend the imports
    with open(bp, 'w', encoding='utf-8') as f:
        f.write(imports_to_add + "\n" + content)
        
print("Injected imports into all blueprints!")
