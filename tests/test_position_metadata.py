import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from flask_login import LoginManager
from core.extensions import db
from services.position_metadata import apply_event_metadata, enrich_event_positions
from event_algo_models import EventMarketSnapshot, EventContractOutcome


class PositionMetadataTests(unittest.TestCase):
    def test_confirmed_result_never_replaces_purchased_outcome_or_zero_value(self):
        row = {'symbol': 'KXTEST', 'event_outcome': 'NO', 'market_value': 0}
        snapshot = SimpleNamespace(raw_json=json.dumps({'name': 'Bitcoin above threshold?', 'target_value': 70000, 'yes_condition': 'Above $70,000'}), cutoff_at=datetime(2026, 9, 7, 16))
        outcome = SimpleNamespace(cutoff_at=snapshot.cutoff_at, settlement_status='RESOLVED', outcome='YES', observed_at=datetime(2026, 9, 7, 16, 5))
        result = apply_event_metadata(row, snapshot, outcome)
        self.assertEqual(result['event_outcome'], 'NO')
        self.assertEqual(result['market_value'], 0)
        self.assertEqual(result['settlement']['confirmed_outcome'], 'YES')
        self.assertEqual(result['settlement']['cutoff_at'], '2026-09-07T16:00:00Z')
        self.assertEqual(result['event_title'], 'Bitcoin above threshold?')

    def test_missing_or_malformed_metadata_does_not_invent_settlement(self):
        for raw in ('invalid json', '[]', '{}'):
            row = apply_event_metadata({'settlement': {'cutoff_at': '2026-09-07T16:00:00Z'}}, SimpleNamespace(raw_json=raw, cutoff_at=None))
            self.assertIsNone(row['settlement']['confirmed_outcome'])
            self.assertEqual(row['settlement']['cutoff_at'], '2026-09-07T16:00:00Z')
            self.assertEqual(row['settlement']['status'], 'UNKNOWN')

    def test_enrichment_queries_latest_per_contract_and_current_user_only(self):
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        db.init_app(app)
        with app.app_context():
            EventMarketSnapshot.__table__.create(db.engine)
            EventContractOutcome.__table__.create(db.engine)
            for user, symbol, name in [(1, 'KXTEST', 'Old'), (1, 'KXTEST', 'Current'), (2, 'KXTEST', 'Other user'), (1, 'KXSECOND', 'Second')]:
                db.session.add(EventMarketSnapshot(user_id=user, contract_symbol=symbol, raw_json=json.dumps({'name': name}), cutoff_at=datetime(2026, 9, 7, 16)))
            db.session.add(EventContractOutcome(user_id=2, contract_symbol='KXTEST', settlement_status='RESOLVED', outcome='YES'))
            db.session.commit()
            rows = enrich_event_positions(1, [{'symbol': 'KXTEST NO', 'instrument_type': 'EVENT'}, {'symbol': 'KXSECOND', 'instrument_type': 'EVENT'}, {'symbol': 'AAPL', 'instrument_type': 'EQUITY'}])
            self.assertEqual(rows[0]['event_title'], 'Current')
            self.assertEqual(rows[1]['event_title'], 'Second')
            self.assertIsNone(rows[0]['settlement']['confirmed_outcome'])
            self.assertNotIn('settlement', rows[2])
            db.session.remove()
            db.engine.dispose()

    def test_quant_positions_route_preserves_ledger_values_and_contract_context(self):
        from routes.portfolio_algo import portfolio_algo_bp
        app = Flask(__name__)
        app.config.update(SECRET_KEY='positions-test', TESTING=True)
        manager = LoginManager(app)
        @manager.user_loader
        def load_user(value):
            return SimpleNamespace(id=int(value), is_admin=True, is_authenticated=True)
        app.register_blueprint(portfolio_algo_bp)
        client = app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = '1'
        position = {'id': 7, 'symbol': 'KXTEST', 'module': 'events', 'instrument_type': 'EVENT', 'mark': 0, 'quantity': 50, 'collateral': 20, 'market_value_usd': 0, 'purchased_outcome': 'NO', 'settlement': {'status': 'PENDING', 'cutoff_at': '2026-09-07T16:00:00Z'}}
        with patch('services.portfolio_engine.portfolio_status', return_value={'positions': [position]}), patch('services.position_metadata.enrich_event_positions', side_effect=lambda user, rows: rows):
            response = client.get('/api/webull/portfolio-algo/positions')
        self.assertEqual(response.status_code, 200)
        row = response.json['positions'][0]
        self.assertEqual(row['market_value'], 0)
        self.assertEqual(row['purchased_outcome'], 'NO')
        self.assertEqual(row['settlement'], position['settlement'])
        self.assertEqual(row['cost_basis'], 20)
