import os
import sys
import json
sys.path.insert(0, '/home/jcavallarojr/crypto_alert_app')
from main import app
from portfolio_algo_models import PortfolioStrategyConfig, PortfolioEngineState

with app.app_context():
    for config in PortfolioStrategyConfig.query.all():
        print(f"User {config.user_id} Worker Status: {config.worker_status}")
    for state in PortfolioEngineState.query.all():
        try:
            data = json.loads(state.telemetry_json)
            if 'error' in data:
                print(f"User {state.user_id} Error: {data['error']}")
            for k, v in data.items():
                if isinstance(v, dict) and 'status' in v:
                    print(f"User {state.user_id} Module {k}: {v['status']} - Messages: {v.get('messages')}")
        except Exception as e:
            print(f"User {state.user_id} JSON Error: {e}")

os._exit(0)
