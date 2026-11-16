"""The credential encryption key lives outside the database it protects."""
import os
import stat
import tempfile
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
from flask import Flask
from sqlalchemy import text

import credential_security as cs
from core.extensions import db


class CredentialKeyFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key_path = os.path.join(self.tmp.name, 'keys', 'credentials.key')
        self.env = patch.dict(os.environ, {cs.KEY_FILE_ENV: self.key_path}, clear=False)
        self.env.start()
        os.environ.pop(cs.ENV_KEY_NAME, None)
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SECRET_KEY='test')
        db.init_app(self.app)
        self.ctx = self.app.app_context()
        self.ctx.push()
        with db.engine.begin() as connection:
            connection.execute(text('CREATE TABLE credential_settings (key VARCHAR PRIMARY KEY, value TEXT)'))
        cs._get_fernet.cache_clear()

    def tearDown(self):
        cs._get_fernet.cache_clear()
        os.environ.pop(cs.ENV_KEY_NAME, None)
        db.session.remove()
        self.ctx.pop()
        self.env.stop()
        self.tmp.cleanup()

    def db_key(self):
        return db.session.execute(text('SELECT value FROM credential_settings')).scalar()

    def test_legacy_database_key_moves_to_an_owner_only_file(self):
        key = Fernet.generate_key().decode()
        db.session.execute(text('INSERT INTO credential_settings VALUES (:k, :v)'), {'k': cs.SETTINGS_KEY, 'v': key})
        db.session.commit()
        token = Fernet(key.encode()).encrypt(b'api-secret').decode()
        self.assertEqual(cs.decrypt_secret(token), 'api-secret')
        self.assertIsNone(self.db_key())
        with open(self.key_path) as handle:
            self.assertEqual(handle.read().strip(), key)
        self.assertEqual(stat.S_IMODE(os.stat(self.key_path).st_mode), 0o600)
        cs._get_fernet.cache_clear()
        self.assertEqual(cs.decrypt_secret(token), 'api-secret')

    def test_saving_a_key_writes_the_file_never_the_database(self):
        key = Fernet.generate_key().decode()
        cs.persist_encryption_key(key)
        self.assertIsNone(self.db_key())
        self.assertTrue(cs.is_persisted_key_available())
        self.assertEqual(cs.decrypt_secret(cs.encrypt_secret('x')), 'x')

    def test_conflicting_file_and_database_keys_are_both_left_alone(self):
        file_key, db_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        os.makedirs(os.path.dirname(self.key_path))
        with open(self.key_path, 'w') as handle:
            handle.write(file_key)
        db.session.execute(text('INSERT INTO credential_settings VALUES (:k, :v)'), {'k': cs.SETTINGS_KEY, 'v': db_key})
        db.session.commit()
        cs._migrate_key_out_of_database(db_key)
        self.assertEqual(self.db_key(), db_key)


if __name__ == '__main__':
    unittest.main()
