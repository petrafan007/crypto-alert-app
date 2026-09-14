import sys
sys.path.append('/home/jcavallarojr/crypto_alert_app')
from main import app
from core.extensions import db
from credentials import UserSetting

with app.app_context():
    user_settings = UserSetting.query.all()
    for s in user_settings:
        if 'ai_model' in s.setting_key or 'ai_provider' in s.setting_key:
            print(f"{s.setting_key}: {s.setting_value}")
