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
        
        creds = Credential.query.filter_by(user_id=user.id, exchange='binance_us').first()
        if not creds:
            return None
        
        # decrypted credentials
        creds.api_key = decrypt_secret(creds.api_key)
        creds.api_secret = decrypt_secret(creds.api_secret)
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
    from credential_security import _MASTER_KEY
    return _MASTER_KEY is not None

def is_persisted_key_available():
    from credential_security import KEY_FILE_PATH
    import os
    return os.path.exists(KEY_FILE_PATH)

def persist_encryption_key(password):
    from credential_security import save_key_to_file
    return save_key_to_file(password)

class EncryptionKeyError(Exception):
    pass

