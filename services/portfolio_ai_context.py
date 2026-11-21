"""AI news & direction summary layer for the Quantitative Strategy Engine.

Layer 2 of the combined decision stack:
  - Layer 1 (quantitative): deterministic price/chart/volatility/volume math
  - Layer 2 (AI news/direction): summarizes news and directional context
  - Layer 3 (decision models): weighs BOTH layers to make/ratify final decision

This module NEVER places trades and NEVER overrides deterministic risk limits.
"""
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from flask import current_app, has_app_context
from core.extensions import db

logger = logging.getLogger(__name__)

_SUMMARY_CACHE = {}
_CACHE_TTL_SECONDS = 1800  # 30-minute per-symbol cache to protect scan latency


def clear_news_summary_cache():
    _SUMMARY_CACHE.clear()


def _normalize_bias(text):
    raw = str(text or '').strip().lower()
    if any(tok in raw for tok in ('strong_bullish', 'definitely buy', 'buy immediately', 'bullish', 'consider buying')):
        return 'bullish'
    if any(tok in raw for tok in ('strong_bearish', 'sell immediately', 'avoid', 'bearish', 'consider selling')):
        return 'bearish'
    if any(tok in raw for tok in ('neutral', 'hold', 'watch', 'balanced', 'mixed')):
        return 'neutral'
    return 'unknown'


def _cached_db_sentiment(user_id, symbol):
    """Read the freshest stored sentiment/reason from local DB tables (fast, no HTTP)."""
    sym = str(symbol or '').upper().strip()
    if not sym:
        return None
    cutoff = datetime.utcnow() - timedelta(hours=24)
    try:
        from models import ExternalSentimentSignal, Coin, WatchlistCoin
        sig = (ExternalSentimentSignal.query
               .filter_by(user_id=user_id, symbol=sym)
               .filter(ExternalSentimentSignal.created_at >= cutoff)
               .order_by(ExternalSentimentSignal.created_at.desc())
               .first())
        if sig and (sig.sentiment or sig.reason):
            return {
                'bias': _normalize_bias(sig.sentiment),
                'label': sig.sentiment or '',
                'reason': str(sig.reason or '')[:400],
                'as_of': sig.created_at.isoformat() + 'Z' if sig.created_at else None,
                'source': 'external_sentiment_signal',
            }
        for model in (Coin, WatchlistCoin):
            row = (model.query
                   .filter_by(user_id=user_id, symbol=sym)
                   .filter(model.sentiment_last_updated.isnot(None),
                           model.sentiment_last_updated >= cutoff)
                   .order_by(model.sentiment_last_updated.desc())
                   .first())
            if row and row.sentiment and row.sentiment not in ('Checking now...', 'Error'):
                return {
                    'bias': _normalize_bias(row.sentiment),
                    'label': row.sentiment,
                    'reason': str(row.sentiment_reason or '')[:400],
                    'as_of': row.sentiment_last_updated.isoformat() + 'Z' if row.sentiment_last_updated else None,
                    'source': 'cached_sentiment',
                }
    except Exception:
        logger.debug('Could not read cached sentiment for %s', sym, exc_info=True)
    return None


def _fetch_headlines(user_id, symbol, module):
    """Fetch bounded recent news headlines from configured financial feeds."""
    # Skip live outbound feed calls during automated unit tests unless explicitly enabled.
    if has_app_context() and current_app.config.get('TESTING') and not current_app.config.get('QSE_NEWS_FETCH_IN_TESTS'):
        return []
    try:
        from credentials import Credential
        from services.financial_feed_service import fetch_financial_feeds
        cred = Credential.query.filter_by(user_id=user_id).first()
        items = fetch_financial_feeds(symbol, cred=cred, max_results=4, system_caller='quant_engine')
        if not isinstance(items, list):
            return []
        cleaned = []
        for item in items[:4]:
            if not isinstance(item, dict):
                continue
            title = str(item.get('title') or '').strip()[:180]
            if title:
                cleaned.append({
                    'title': title,
                    'source': str(item.get('source') or 'feed')[:60],
                    'snippet': str(item.get('snippet') or '').strip()[:200],
                })
        return cleaned
    except Exception:
        logger.debug('Financial feed fetch unavailable for %s (%s)', symbol, module, exc_info=True)
        return []


def _summarize_with_ai(user_id, symbol, module, headlines, cached_sentiment):
    """Use the configured AI model to summarize news and directional context."""
    if has_app_context() and current_app.config.get('TESTING') and not current_app.config.get('QSE_AI_SUMMARY_IN_TESTS'):
        return None
    if not headlines and not cached_sentiment:
        return None
    try:
        from credentials import User
        from services.ai_service import call_ai_with_web_search, is_ai_enabled
        from services.portfolio_audit_lifecycle import active_audit
        if active_audit(user_id):
            return None
        user = db.session.get(User, user_id)
        if not user or not is_ai_enabled(user.username):
            return None
        context_payload = {
            'symbol': symbol,
            'module': module,
            'cached_sentiment': cached_sentiment,
            'headlines': headlines[:4],
        }
        messages = [
            {
                'role': 'system',
                'content': (
                    'You are a concise market-news analyst for a paper trading engine. '
                    'Summarize the news and directional tone for the symbol in strict JSON with keys: '
                    'direction_bias (bullish|bearish|neutral|unknown), '
                    'catalyst_risk (low|elevated|high|unknown), '
                    'summary (1-2 plain sentences, <=320 chars). Do not issue trade orders.'
                ),
            },
            {'role': 'user', 'content': json.dumps(context_payload)},
        ]
        response, _ = call_ai_with_web_search(
            username=user.username,
            user_id=user_id,
            messages=messages,
            prompt_type='quant_news_summary',
            symbol=symbol,
            include_db_context=False,
        )
        raw = str(getattr(response, 'text', '') or '').strip()
        if not raw:
            return None
        # Strip markdown fences if present
        if raw.startswith('```'):
            raw = raw.strip('`')
            if raw.lower().startswith('json'):
                raw = raw[4:].strip()
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return None
        bias = str(parsed.get('direction_bias') or 'unknown').lower()
        if bias not in ('bullish', 'bearish', 'neutral', 'unknown'):
            bias = _normalize_bias(bias)
        risk = str(parsed.get('catalyst_risk') or 'unknown').lower()
        if risk not in ('low', 'elevated', 'high', 'unknown'):
            risk = 'unknown'
        summary = str(parsed.get('summary') or '').strip()[:400]
        if not summary:
            return None
        return {
            'direction_bias': bias,
            'catalyst_risk': risk,
            'summary': summary,
            'provider': getattr(response, 'provider', None),
            'model': getattr(response, 'model', None),
        }
    except Exception:
        logger.debug('AI news summary unavailable for %s (%s)', symbol, module, exc_info=True)
        return None


def get_news_direction_summary(user_id, symbol, module, now=None, *, allow_cache=True):
    """Build a bounded, cached news & direction summary for Layer 2 of the QSE stack."""
    sym = str(symbol or '').upper().strip()
    mod = str(module or 'equities').lower().strip()
    moment = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    as_of = moment.isoformat() if moment.tzinfo else moment.isoformat() + 'Z'
    cache_key = (int(user_id), mod, sym)
    now_mono = time.monotonic()

    if allow_cache and cache_key in _SUMMARY_CACHE:
        cached_at, payload = _SUMMARY_CACHE[cache_key]
        if now_mono - cached_at < _CACHE_TTL_SECONDS:
            return dict(payload)

    cached_sentiment = _cached_db_sentiment(user_id, sym)
    headlines = _fetch_headlines(user_id, sym, mod)
    ai_digest = _summarize_with_ai(user_id, sym, mod, headlines, cached_sentiment)

    if ai_digest:
        payload = {
            'symbol': sym,
            'module': mod,
            'direction_bias': ai_digest['direction_bias'],
            'catalyst_risk': ai_digest['catalyst_risk'],
            'summary': ai_digest['summary'],
            'headline_count': len(headlines),
            'headlines': [h['title'] for h in headlines[:4]],
            'source': 'ai_news_summary',
            'provider': ai_digest.get('provider'),
            'model': ai_digest.get('model'),
            'as_of': as_of,
        }
    elif cached_sentiment:
        payload = {
            'symbol': sym,
            'module': mod,
            'direction_bias': cached_sentiment['bias'],
            'catalyst_risk': 'unknown',
            'summary': (cached_sentiment['reason'] or f"Recent stance: {cached_sentiment['label']}")[:400],
            'headline_count': len(headlines),
            'headlines': [h['title'] for h in headlines[:4]],
            'source': cached_sentiment['source'],
            'as_of': cached_sentiment.get('as_of') or as_of,
        }
    elif headlines:
        joined = '; '.join(h['title'] for h in headlines[:3])
        payload = {
            'symbol': sym,
            'module': mod,
            'direction_bias': 'neutral',
            'catalyst_risk': 'unknown',
            'summary': f'Recent headlines ({len(headlines)}): {joined}'[:400],
            'headline_count': len(headlines),
            'headlines': [h['title'] for h in headlines[:4]],
            'source': 'news_feed',
            'as_of': as_of,
        }
    else:
        payload = {
            'symbol': sym,
            'module': mod,
            'direction_bias': 'unknown',
            'catalyst_risk': 'unknown',
            'summary': 'No recent news or directional summary available; quantitative evidence carries primary weight.',
            'headline_count': 0,
            'headlines': [],
            'source': 'unavailable',
            'as_of': as_of,
        }

    if allow_cache:
        _SUMMARY_CACHE[cache_key] = (now_mono, dict(payload))
    return payload
