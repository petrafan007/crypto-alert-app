"""Typed response contracts with instructions from the editable prompt catalog."""
from services.prompt_catalog import prompt_for

DECISION_SENTIMENT_CONTRACT_VERSION = 'sentiment-v3'
DECISION_CRYPTO_QUANT_CONTRACT_VERSION = 'crypto-quant-v3'
STATE_SCHEMA_VERSION = 'decision-state-v1'


def build_sentiment_questions(user_id=None, is_watchlist=False, overrides=None):
    key = 'decision.watchlist_sentiment' if is_watchlist else 'decision.sentiment'
    return prompt_for(user_id, key, overrides)


def build_crypto_quant_questions(user_id=None, overrides=None):
    return prompt_for(user_id, 'decision.crypto_quant', overrides)


def build_event_questions(user_id=None, overrides=None):
    return prompt_for(user_id, 'decision.contract_probability', overrides)
