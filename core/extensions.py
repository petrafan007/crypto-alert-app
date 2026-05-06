from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler

# Initialize SQLAlchemy
db = SQLAlchemy()

# Initialize Flask-Login manager
login_manager = LoginManager()
login_manager.login_view = "login"

# Initialize APScheduler
scheduler = BackgroundScheduler(daemon=True)

# Centralize extensions here to prevent circular imports
