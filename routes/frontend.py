
from datetime import timedelta, datetime
import requests
import threading
from flask import send_file, request, jsonify, render_template, current_app, redirect, url_for
from flask_login import current_user, login_required, login_user, logout_user
from models import Coin, WatchlistCoin, Notification, PriceHistory
from credentials import Credential, User, UserSetting
from core.extensions import db
from log import logger
from routes.helpers import *

from flask import Blueprint
frontend_bp = Blueprint('frontend', __name__)



@frontend_bp.route("/")
@login_required
def dashboard():
    # Serve the React app
    return serve_react_app()

@frontend_bp.route('/favicon.ico')
def favicon():
    """Return 204 No Content for favicon requests"""
    return '', 204

@frontend_bp.route("/trading")
@login_required
def trading_page():
    """Serve the trading page"""
    return serve_react_app()

@frontend_bp.route("/watchlist")
@login_required
def watchlist_page():
    """Serve the watchlist page"""
    return serve_react_app()

@frontend_bp.route("/staking")
@login_required
def staking_page():
    """Serve the staking page"""
    return serve_react_app()

@frontend_bp.route("/tax-report")
@login_required
def tax_report_page():
    """Serve the tax report page"""
    return serve_react_app()

@frontend_bp.route("/help")
@login_required
def help_page():
    """Serve the help page"""
    return serve_react_app()