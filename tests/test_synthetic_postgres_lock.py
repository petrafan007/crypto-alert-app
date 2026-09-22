"""Optional real PostgreSQL advisory-lock check; no tables or account data touched."""
import hashlib
import os
import unittest

from flask import Flask
from sqlalchemy import text
from core.extensions import db
from services.synthetic_execution_service import parent_lock


@unittest.skipUnless(os.environ.get('SYNTHETIC_LOCK_TEST_DATABASE_URI'), 'Set SYNTHETIC_LOCK_TEST_DATABASE_URI for the read-only PostgreSQL lock check')
class SyntheticPostgresLockTests(unittest.TestCase):
    def test_parent_lock_survives_commit_and_releases(self):
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['SYNTHETIC_LOCK_TEST_DATABASE_URI']
        db.init_app(app)
        key = int.from_bytes(hashlib.sha256(b'synthetic:TEST_RELEASE_390:-1').digest()[:8], 'big', signed=True)
        with app.app_context():
            try:
                with db.engine.connect() as contender:
                    with parent_lock('TEST_RELEASE_390', -1) as locked:
                        self.assertTrue(locked)
                        db.session.execute(text('SELECT 1'))
                        db.session.commit()
                        self.assertFalse(contender.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': key}).scalar())
                    acquired = contender.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': key}).scalar()
                    try:
                        self.assertTrue(acquired)
                    finally:
                        if acquired:
                            contender.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': key})
            finally:
                db.session.remove()
                db.engine.dispose()
