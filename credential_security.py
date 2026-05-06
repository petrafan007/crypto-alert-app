import base64
import logging
import os
import threading
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from core.extensions import db
from flask import has_app_context

logger = logging.getLogger(__name__)

ENV_KEY_NAME = "CREDENTIALS_ENCRYPTION_KEY"
SETTINGS_TABLE = "credential_settings"
SETTINGS_KEY = "credentials_encryption_key"


class EncryptionKeyError(RuntimeError):
    """Raised when the credential encryption key is missing or invalid."""


def is_encryption_available() -> bool:
    """Return True if a valid Fernet key is configured."""
    try:
        _get_fernet()
        return True
    except EncryptionKeyError:
        return False


def encrypt_secret(value: Optional[str]) -> Optional[str]:
    """
    Encrypt a secret value using the configured Fernet key.
    """
    if not value:
        return None
    fernet = _get_fernet()
    token = fernet.encrypt(value.encode("utf-8"))
    return token.decode("utf-8")

# Alias for backward compatibility
encrypt_credential = encrypt_secret

def decrypt_secret(value: Optional[str]) -> Optional[str]:
    """
    Attempt to decrypt a secret value.
    """
    if not value:
        return None
    try:
        fernet = _get_fernet()
    except EncryptionKeyError:
        logger.warning(
            "Credential encryption key is not configured; returning stored credential as-is."
        )
        return value

    try:
        decoded = fernet.decrypt(value.encode("utf-8"))
        return decoded.decode("utf-8")
    except InvalidToken:
        # Value was likely stored before encryption was enabled.
        logger.debug("Credential value could not be decrypted; treating as plaintext.")
        return value

# Alias for backward compatibility
decrypt_credential = decrypt_secret


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    raw_key = os.getenv(ENV_KEY_NAME)
    if not raw_key:
        raw_key = _load_persisted_key()
    if not raw_key:
        raise EncryptionKeyError(
            "Credential encryption key is not configured. Set it in Settings or via environment."
        )

    normalized_key = _normalize_key(raw_key)
    return Fernet(normalized_key.encode("utf-8"))


def _looks_base64(candidate: bytes) -> bool:
    """Best-effort detection to avoid double-encoding a key."""
    try:
        base64.urlsafe_b64decode(candidate)
        return True
    except Exception:
        return False


def _normalize_key(raw_value: str) -> str:
    """
    Validate and normalize a user-supplied key into a Fernet-compatible, URL-safe base64 string.
    """
    if raw_value is None:
        raise EncryptionKeyError("Empty encryption key provided.")

    cleaned = raw_value.strip()
    if not cleaned:
        raise EncryptionKeyError("Empty encryption key provided.")

    key_bytes = cleaned.encode("utf-8")

    # Support raw 32-byte keys and already-base64 values.
    if len(key_bytes) == 32 and not _looks_base64(key_bytes):
        key_bytes = base64.urlsafe_b64encode(key_bytes)

    try:
        decoded = base64.urlsafe_b64decode(key_bytes)
    except Exception as exc:
        raise EncryptionKeyError("Invalid Fernet key provided.") from exc

    if len(decoded) != 32:
        raise EncryptionKeyError("Invalid Fernet key provided.")

    return key_bytes.decode("utf-8")


def _load_persisted_key() -> Optional[str]:
    """Load the encryption key from the database."""
    if not has_app_context():
        # If we are outside of an app context (e.g. some scripts), we can't check DB.
        # Fallback to env var or fail.
        return None

    try:
        # We use raw SQL to avoid importing models here to avoid circular imports
        # although CredentialEncryptionKey is in credentials.py
        result = db.session.execute(
            text(f"SELECT value FROM {SETTINGS_TABLE} WHERE key = :key"),
            {'key': SETTINGS_KEY}
        ).fetchone()
        
        return result[0] if result and result[0] else None
    except Exception as exc:
        logger.error("Failed to load persisted encryption key: %s", exc)
        return None


def persist_encryption_key(raw_value: str) -> None:
    """
    Persist a new encryption key into database, update the process env var, and refresh the cached Fernet instance.
    """
    raw_value = raw_value or ""
    normalized = _normalize_key(raw_value)

    if has_app_context():
        try:
            # Upsert logic for Postgres/Generic SQL
            # First try update
            result = db.session.execute(
                text(f"UPDATE {SETTINGS_TABLE} SET value = :value WHERE key = :key"),
                {'value': normalized, 'key': SETTINGS_KEY}
            )
            if result.rowcount == 0:
                # If no row updated, insert
                db.session.execute(
                    text(f"INSERT INTO {SETTINGS_TABLE} (key, value) VALUES (:key, :value)"),
                    {'key': SETTINGS_KEY, 'value': normalized}
                )
            db.session.commit()
        except Exception as e:
            logger.error(f"Failed to persist encryption key to DB: {e}")
            db.session.rollback()

    # Ensure in-process lookups (and any child processes) see the key.
    os.environ[ENV_KEY_NAME] = normalized

    # Reset cached Fernet so subsequent encrypt/decrypt calls use the new key.
    _get_fernet.cache_clear()
    logger.info("Credential encryption key persisted successfully.")


def clear_persisted_encryption_key() -> None:
    """
    Remove the stored encryption key. This forces the system to fallback to env or error.
    """
    if has_app_context():
        try:
            db.session.execute(
                text(f"DELETE FROM {SETTINGS_TABLE} WHERE key = :key"),
                {'key': SETTINGS_KEY}
            )
            db.session.commit()
        except Exception as e:
            logger.error(f"Failed to clear encryption key from DB: {e}")
            db.session.rollback()

    _get_fernet.cache_clear()
    logger.info("Persisted credential encryption key cleared.")


def is_persisted_key_available() -> bool:
    return _load_persisted_key() is not None


def normalize_secret_for_storage(value: Optional[str]) -> Optional[str]:
    """Ensure a secret is stored with a single layer of encryption using the current key."""
    if not value:
        return None

    plaintext = value
    # Fernet tokens generated by cryptography always start with 'gAAAA'. Use that
    # pattern to unwrap any nested encryption layers that may have been introduced
    # by previous tooling bugs.
    max_layers = 5  # sanity guard to avoid accidental infinite loops
    while isinstance(plaintext, str) and plaintext.startswith("gAAAA") and max_layers > 0:
        candidate = decrypt_secret(plaintext)
        if candidate == plaintext:
            break
        plaintext = candidate
        max_layers -= 1

    return encrypt_secret(plaintext if isinstance(plaintext, str) else str(plaintext))