from log import logger
from core.extensions import db
from credentials import Credential
from credential_security import decrypt_secret

def get_user_credentials(username):
    """Get decrypted Binance.US credentials for a user by username"""
    try:
        from credentials import User
        user = User.query.filter_by(username=username).first()
        if not user:
            return None
        
        creds = Credential.query.filter_by(user_id=user.id).first()
        return creds
    except Exception as e:
        logger.error(f"Credential retrieval error for user {username}: {e}")
        return None

def get_user_credentials_dict(username) -> dict:
    """Get credentials as a dictionary for easier use"""
    creds = get_user_credentials(username)
    if not creds:
        return {}
    return {
        'api_key': creds.api_key,
        'api_secret': creds.api_secret
    }

def is_encryption_available():
    from credential_security import is_encryption_available as _is_avail
    return _is_avail()

def is_persisted_key_available():
    from credential_security import is_persisted_key_available as _is_persisted
    return _is_persisted()

def persist_encryption_key(password):
    from credential_security import persist_encryption_key as _persist
    return _persist(password)

from credential_security import EncryptionKeyError

