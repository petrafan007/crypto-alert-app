from credentials import User, Credential
from core.extensions import db
from log import logger

def get_user_credentials(username):
    """Retrieve user credentials from the database (PostgreSQL version)"""
    try:
        cred = Credential.query.filter_by(username=username).first()
        return cred
    except Exception as e:
        logger.error(f"Error fetching credentials for {username}: {e}")
        return None

def get_user_credentials_dict(username) -> dict:
    """Retrieve user credentials as a dictionary (PostgreSQL version)"""
    try:
        cred = Credential.query.filter_by(username=username).first()
        if cred:
            return cred.to_dict()
        return {}
    except Exception as e:
        logger.error(f"Error fetching credentials dict for {username}: {e}")
        return {}
