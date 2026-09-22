"""Redact common bearer credentials before formatting application logs."""
import logging
import re

_TOKEN = re.compile(r'(?<![0-9])\d{7,12}:[A-Za-z0-9_-]{30,50}')
_QUERY = re.compile(r'(?i)([?&](?:api_?key|api_secret|telegram_token|token|value|secret|signature)=)[^\s&]+')
_MAPPING_SECRET = re.compile(r'''(?i)(['"](?:app_key|app_secret|access_token|api_key|api_secret|trading_api_key|trading_api_secret)['"]\s*:\s*)(['"])(.*?)\2''')

class SecretRedactionFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        message = _MAPPING_SECRET.sub(r'\1\2[REDACTED]\2', message)
        record.msg = _QUERY.sub(r'\1[REDACTED]', _TOKEN.sub('[REDACTED_TELEGRAM_TOKEN]', message))
        record.args = ()
        return True
