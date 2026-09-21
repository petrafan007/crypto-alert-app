"""Redact common bearer credentials before formatting application logs."""
import logging
import re

_TOKEN = re.compile(r'(?<![0-9])\d{7,12}:[A-Za-z0-9_-]{30,50}')
_QUERY = re.compile(r'(?i)([?&](?:api_?key|api_secret|telegram_token|token|value|secret|signature)=)[^\s&]+')

class SecretRedactionFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        record.msg = _QUERY.sub(r'\1[REDACTED]', _TOKEN.sub('[REDACTED_TELEGRAM_TOKEN]', message))
        record.args = ()
        return True
