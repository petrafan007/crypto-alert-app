import sys
import json
sys.path.insert(0, '/home/jcavallarojr/crypto_alert_app')
from main import app
from portfolio_algo_models import PortfolioEngineState

with app.app_context():
    for state in PortfolioEngineState.query.all():
        if state.telemetry_json:
            tel = json.loads(state.telemetry_json)
            for mod, d in tel.get('modules', {}).items():
                print(f"User {state.user_id} Module {mod}: {d.get('status')} - Messages: {d.get('messages', [])}")
        print(f"User {state.user_id} Last Scan: {state.last_scan_at}")
