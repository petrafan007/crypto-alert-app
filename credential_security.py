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
KEY_FILE_ENV = "CREDENTIALS_KEY_FILE"


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
    # Never accept a new credential write without encryption.
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
    # The key never lives in the database it protects: environment first,
    # then an owner-only key file. A key still found in the database (older
    # releases kept it there) is moved to the key file once.
    raw_key = os.getenv(ENV_KEY_NAME) or _read_key_file()
    if not raw_key:
        raw_key = _load_persisted_key()
        if raw_key:
            _migrate_key_out_of_database(raw_key)
    if not raw_key:
        raise EncryptionKeyError(
            "Credential encryption key is not configured. Set it in Settings or via environment."
        )

    normalized_key = _normalize_key(raw_key)
    return Fernet(normalized_key.encode("utf-8"))


def key_file_path() -> str:
    """Owner-only key file, outside the database and outside Git (instance/ is ignored)."""
    default = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "credentials.key")
    return os.getenv(KEY_FILE_ENV, default)


def _read_key_file() -> Optional[str]:
    try:
        with open(key_file_path(), "r", encoding="utf-8") as handle:
            value = handle.read().strip()
        return value or None
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.error("Credential key file could not be read: %s", exc)
        return None


def _write_key_file(normalized: str) -> None:
    """Atomically write the key with 0600 permissions, then verify it reads back."""
    path = key_file_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    temporary = f"{path}.{os.getpid()}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(normalized + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    os.chmod(path, 0o600)
    if _read_key_file() != normalized:
        raise EncryptionKeyError("The credential key file did not read back correctly.")


def _delete_database_key() -> None:
    if not has_app_context():
        return
    try:
        db.session.execute(text(f"DELETE FROM {SETTINGS_TABLE} WHERE key = :key"), {'key': SETTINGS_KEY})
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error("Could not remove the credential key from the database: %s", exc)


def _migrate_key_out_of_database(raw_key: str) -> None:
    """Write the database-held key to the key file, then remove it from the database."""
    try:
        normalized = _normalize_key(raw_key)
        existing = _read_key_file()
        if existing and existing != normalized:
            logger.error("The credential key file differs from the database key; leaving both untouched.")
            return
        if not existing:
            _write_key_file(normalized)
        _delete_database_key()
        logger.warning("Moved the credential encryption key out of the database into %s. "
                       "Keep a copy of this file somewhere safe: without it, saved API keys cannot be decrypted.",
                       key_file_path())
    except Exception as exc:
        logger.error("Could not move the credential key out of the database: %s", exc)


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
    """Load a legacy encryption key from the database (releases before v4.17.5)."""
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
    """Save a new encryption key to the key file (never the database) and use it."""
    normalized = _normalize_key(raw_value or "")
    _write_key_file(normalized)
    _delete_database_key()
    # Ensure in-process lookups (and any child processes) see the key.
    os.environ[ENV_KEY_NAME] = normalized
    _get_fernet.cache_clear()
    logger.info("Credential encryption key saved to %s.", key_file_path())


def clear_persisted_encryption_key() -> None:
    """Remove the saved key file and any legacy database copy."""
    try:
        os.unlink(key_file_path())
    except FileNotFoundError:
        logger.debug("No credential key file to remove.")
    _delete_database_key()
    _get_fernet.cache_clear()
    logger.info("Persisted credential encryption key cleared.")


def is_persisted_key_available() -> bool:
    return _read_key_file() is not None or _load_persisted_key() is not None


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