import os
import socket
from datetime import timedelta
from flask import Flask
from dotenv import load_dotenv
load_dotenv(override=True)

# Enforce IPv4 globally for urllib3/requests to avoid Binance.US rejecting IPv6 with -71012
try:
    import urllib3.util.connection as urllib3_cn
    urllib3_cn.allowed_gai_family = lambda: socket.AF_INET
except Exception:
    pass

from core.extensions import db, login_manager, scheduler
from core.proxy_security import configure_public_proxy_security
from log import logger

from routes.auth import auth_bp
from routes.portfolio import portfolio_bp
from routes.system import system_bp
from routes.ai import ai_bp
from routes.market import market_bp
from routes.frontend import frontend_bp
from routes.event_algo import event_algo_bp
from routes.portfolio_algo import portfolio_algo_bp

# Import User for login manager
from credentials import User

app = Flask(__name__, static_folder='frontend/dist', static_url_path='/static', instance_relative_config=True)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'super-secret-key')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
configure_public_proxy_security(app)

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql:///cryptoalertapp?host=/var/run/postgresql&port=5433'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 50,
    'max_overflow': 100,
    'pool_recycle': 1800,
    'pool_pre_ping': True
}
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

db.init_app(app)

login_manager.init_app(app)
login_manager.login_view = "auth.login"

@login_manager.unauthorized_handler
def handle_unauthorized():
    from flask import request, jsonify, redirect, url_for
    if request.path.startswith('/api/') or request.is_json:
        return jsonify({"error": "Authentication required", "authenticated": False}), 401
    return redirect(url_for('auth.login', next=request.url))

@login_manager.user_loader
def load_user(user_id):
    if not user_id:
        return None
    try:
        return db.session.get(User, int(user_id))
    except Exception as e:
        logger.error(f"Error loading user {user_id}: {e}")
        return None

app.register_blueprint(auth_bp)
app.register_blueprint(portfolio_bp)
app.register_blueprint(system_bp)
app.register_blueprint(ai_bp)
app.register_blueprint(market_bp)
app.register_blueprint(frontend_bp)
app.register_blueprint(event_algo_bp)
app.register_blueprint(portfolio_algo_bp)

@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()

if __name__ == '__main__':
    from database import init_db
    init_db(app)
    # Start background sync, alert monitoring, and retention loops
    try:
        from services.scheduler_tasks import start_background_jobs
        start_background_jobs(app)
    except Exception as e:
        logger.error(f"Failed to start background jobs: {e}")
    port = int(os.environ.get('PORT', 5010))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
