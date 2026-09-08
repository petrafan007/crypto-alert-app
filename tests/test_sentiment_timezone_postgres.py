"""Exercise the actual PostgreSQL timestamp coercion behind the v2.94.0 repair."""
import os
import unittest
from datetime import datetime, timedelta, timezone

from flask import Flask
from sqlalchemy import text
from core.extensions import db
from models import SentimentHistory
from services.sentiment_outcome_service import repair_fixed_horizon_timestamps


@unittest.skipUnless(os.environ.get('QUANT_TEST_DATABASE_URI'), 'Requires an isolated PostgreSQL database')
class PostgresForecastTimezoneTests(unittest.TestCase):
    def test_new_york_session_preserves_utc_target_and_repairs_legacy_cast(self):
        app = Flask(__name__)
        app.config.update(SQLALCHEMY_DATABASE_URI=os.environ['QUANT_TEST_DATABASE_URI'], SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(app)
        with app.app_context():
            SentimentHistory.__table__.create(db.engine, checkfirst=True)
            db.session.execute(text("SET TIME ZONE 'America/New_York'"))
            created = datetime(2026, 9, 7, 20, tzinfo=timezone.utc)
            common = dict(user_id=99999, symbol='ETH', source_type='portfolio', sentiment='Hold', price_at_prediction=100,
                          created_at=created, evaluation_method='fixed_horizon', forecast_horizon_hours=2)
            legacy = SentimentHistory(**common, target_evaluation_at=created+timedelta(hours=2))
            fixed = SentimentHistory(**common, target_evaluation_at=(created+timedelta(hours=2)).replace(tzinfo=None))
            db.session.add_all([legacy, fixed]); db.session.commit()
            self.assertEqual(legacy.created_at.astimezone(timezone.utc), created)
            self.assertEqual(legacy.target_evaluation_at, datetime(2026, 9, 7, 18))
            self.assertEqual(fixed.target_evaluation_at, datetime(2026, 9, 7, 22))
            self.assertEqual(repair_fixed_horizon_timestamps(), 1)
            self.assertEqual(legacy.target_evaluation_at, fixed.target_evaluation_at)
            self.assertEqual(repair_fixed_horizon_timestamps(), 0)
            db.session.remove()
            db.engine.dispose()
