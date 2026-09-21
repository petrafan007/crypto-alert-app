"""Reject missing and example session keys instead of signing forgeable cookies."""
def require_session_secret(value):
    if not isinstance(value, str) or len(value.strip()) < 32 or any(
        marker in value.lower() for marker in ('super-secret', 'change-me', 'changeme', 'your-secret')
    ):
        raise RuntimeError('Set a strong, unique SECRET_KEY of at least 32 characters before starting the app.')
    return value
