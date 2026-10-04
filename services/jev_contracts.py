"""Typed response contracts with instructions from the editable prompt catalog."""
from services.prompt_catalog import prompt_for

JEV_SENTIMENT_CONTRACT_VERSION = 'sentiment-v2'
JEV_CRYPTO_QUANT_CONTRACT_VERSION = 'crypto-quant-v2'
STATE_SCHEMA_VERSION = 'jev-state-v1'


def build_sentiment_questions(user_id=None, is_watchlist=False, overrides=None):
    key = 'jev.watchlist_sentiment' if is_watchlist else 'jev.sentiment'
    return prompt_for(user_id, key, overrides)


def build_crypto_quant_questions(user_id=None, overrides=None):
    return prompt_for(user_id, 'jev.crypto_quant', overrides)
