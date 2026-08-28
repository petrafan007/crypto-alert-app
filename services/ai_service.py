import os
import re
import json
import time
import logging
import threading
import requests
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
import pytz
from flask import current_app, session

from core.extensions import db
from models import Coin, WatchlistCoin, AIPrompt, DefaultAIPrompt, AIConversation
from credentials import User, Credential, UserSetting
from services.credential_service import get_user_credentials
from services.analysis_service import (
    get_user_ai_settings, is_ai_enabled, get_user_ai_prompts,
    calculate_symbol_snapshot
)
from services.helpers import format_eastern_datetime, get_eastern_now
from services.notification_service import send_telegram_message, create_system_notification
from routes.helpers import decrypt_secret, is_stablecoin

logger = logging.getLogger(__name__)

WEBULL_CRYPTO_SEARCH_PROMPT = (
    "Generate 1 to 2 targeted current-market search queries for the Webull crypto holding {symbol} as of {datetime}. "
    "Focus on price catalysts, liquidity, market structure, and material crypto news."
)
WEBULL_CRYPTO_RESEARCH_PROMPT = (
    "You are a crypto market analyst. Use the supplied Webull market context and current web results for {symbol} as of {datetime}. "
    "Assess the fixed forecast horizon supplied by the application, including price movement, liquidity, market structure, catalysts, risks, and data limitations. "
    "Return ONLY JSON: {\"sentiment\": \"<Buy Immediately|Consider Buying|Hold|Consider Selling|Sell Immediately>\", \"reason\": \"<1-2 concise sentences>\"}. "
    "This is research only: do not claim to execute, place, amend, or cancel a trade."
)
WEBULL_EQUITY_SEARCH_PROMPT = (
    "Generate 1 to 2 targeted current-market search queries for the Webull equity or ETF {symbol} as of {datetime}. "
    "Focus on company or fund news, earnings or filings when relevant, sector catalysts, and material price-moving developments."
)
WEBULL_EQUITY_RESEARCH_PROMPT = (
    "You are an equity and ETF market analyst. Use the supplied Webull market context and current web results for {symbol} as of {datetime}. "
    "Assess the fixed forecast horizon supplied by the application, including company/fund and sector catalysts, price movement, material risks, and data limitations. "
    "Do not use cryptocurrency assumptions. Return ONLY JSON: {\"sentiment\": \"<Buy Immediately|Consider Buying|Hold|Consider Selling|Sell Immediately>\", \"reason\": \"<1-2 concise sentences>\"}. "
    "This is research only: do not claim to execute, place, amend, or cancel a trade."
)

_running_sentiment_users = set()
_running_sentiment_lock = threading.Lock()

def is_user_analysis_window_active(start_str, end_str):
    """Check if current Eastern time is within the user's configured window (HH:MM - HH:MM)."""
    try:
        now_et = get_eastern_now()
        current_minutes = now_et.hour * 60 + now_et.minute
        
        start_parts = [int(p) for p in (start_str or '08:00').split(':')]
        end_parts = [int(p) for p in (end_str or '23:59').split(':')]
        
        start_min = start_parts[0] * 60 + start_parts[1]
        end_min = end_parts[0] * 60 + end_parts[1]
        
        if start_min <= end_min:
            return start_min <= current_minutes <= end_min
        else:
            # Overnight window
            return current_minutes >= start_min or current_minutes <= end_min
    except Exception as e:
        logger.error(f"Error checking analysis window: {e}")
        return True

def web_search(query, max_results=2, username=None, freshness="pd"):
    """
    Search the web for real-time crypto info.
    Priority: Brave Search API -> DuckDuckGo HTML -> Binance Price fallback.
    freshness parameter options: 'pd' (past 24h / 12-24h window), 'pw' (past week), 'pm' (past month), 'py' (past year).
    """
    # 1. Try Brave Search API if credentials exist
    if username:
        try:
            cred = get_user_credentials(username)
            if cred:
                brave_api_key = cred.brave_search_api_key
                brave_api_key_fallback = cred.brave_search_api_key_fallback
                
                for key_name, api_key in [('primary', brave_api_key), ('fallback', brave_api_key_fallback)]:
                    if not api_key or not api_key.strip():
                        continue
                    try:
                        logger.info(f"Attempting Brave Search ({key_name}, freshness={freshness}) for query: {query}")
                        brave_url = "https://api.search.brave.com/res/v1/web/search"
                        headers = {
                            "Accept": "application/json",
                            "Accept-Encoding": "gzip",
                            "X-Subscription-Token": api_key.strip()
                        }
                        params = {
                            "q": query,
                            "count": max_results,
                            "search_lang": "en",
                            "country": "US",
                            "safesearch": "moderate",
                            "freshness": freshness or "pd"
                        }
                        resp = requests.get(brave_url, headers=headers, params=params, timeout=12)
                        if resp.status_code == 200:
                            data = resp.json()
                            results = []
                            for item in data.get('web', {}).get('results', [])[:max_results]:
                                results.append({
                                    'title': item.get('title', ''),
                                    'snippet': item.get('description', '')[:300],
                                    'url': item.get('url', ''),
                                    'source': f'Brave Search ({key_name})'
                                })
                            if results:
                                logger.info(f"Brave Search returned {len(results)} results")
                                return results
                    except Exception as e:
                        logger.warning(f"Brave Search error ({key_name}): {e}")
        except Exception as e:
            logger.error(f"Error accessing Brave Search credentials: {e}")

    # 2. DuckDuckGo fallback
    try:
        from bs4 import BeautifulSoup
        search_url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        resp = requests.get(search_url, headers=headers, timeout=6)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            results = []
            for result_div in soup.find_all('div', class_='result', limit=max_results):
                title_elem = result_div.find('a', class_='result__a')
                snippet_elem = result_div.find('a', class_='result__snippet')
                if title_elem:
                    results.append({
                        'title': title_elem.get_text(strip=True),
                        'snippet': snippet_elem.get_text(strip=True)[:300] if snippet_elem else '',
                        'url': title_elem.get('href', ''),
                        'source': 'DuckDuckGo'
                    })
            if results:
                return results
    except Exception as e:
        logger.warning(f"DuckDuckGo fallback failed: {e}")

    # 3. Final default
    return [{
        'title': 'Search unavailable',
        'snippet': 'Real-time web search unavailable. Using AI general knowledge.',
        'url': '',
        'source': 'System'
    }]


def news_api_search(symbol, username, lookback_hours=24, max_results=4, asset_context='crypto'):
    """Fetch recent asset-appropriate news from the user's configured NewsAPI integration.

    This is deliberately separate from general web search: when a user supplies a
    NewsAPI key, every AI workflow that asks for fresh news receives those actual
    NewsAPI articles as grounding context. General web search remains a useful
    supplemental market-data source rather than silently replacing NewsAPI.
    """
    try:
        cred = get_user_credentials(username)
        api_key = (getattr(cred, 'news_api', None) or '').strip() if cred else ''
        if not api_key:
            return []

        hours = max(1, min(int(lookback_hours or 24), 720))
        published_after = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec='seconds')
        topic = 'cryptocurrency' if str(asset_context).lower() == 'crypto' else 'stock OR equity OR ETF'
        response = requests.get(
            'https://newsapi.org/v2/everything',
            headers={'X-Api-Key': api_key},
            params={
                'q': f'({str(symbol or "market").upper()} OR {topic})',
                'language': 'en',
                'sortBy': 'publishedAt',
                'from': published_after,
                'pageSize': max(1, min(int(max_results), 20)),
            },
            timeout=12,
        )
        if response.status_code != 200:
            logger.warning('NewsAPI request failed for %s: HTTP %s', symbol, response.status_code)
            return []

        results = []
        for article in (response.json().get('articles') or [])[:max_results]:
            results.append({
                'title': article.get('title') or 'Untitled article',
                'snippet': (article.get('description') or article.get('content') or '')[:300],
                'url': article.get('url') or '',
                'source': f"NewsAPI ({(article.get('source') or {}).get('name') or 'news'})",
            })
        return results
    except Exception as exc:
        logger.warning('NewsAPI search failed for %s: %s', symbol, exc)
        return []

class AIResponseWrapper:
    """Wrapper to provide uniform `.choices[0].message.content` interface."""
    def __init__(self, text, tier="primary", provider=None, model=None, search_status=None):
        self.text = text or ""
        self.tier = tier
        self.provider = provider
        self.model = model
        self.search_status = search_status or "Brave Search"
        self.choices = [self._Choice(self.text)]
    
    class _Choice:
        def __init__(self, text):
            self.message = self._Message(text)
            self.text = text
        
        class _Message:
            def __init__(self, text):
                self.content = text
                self.role = "assistant"
    
    def __str__(self):
        return self.text

def call_ai_with_web_search(
    username,
    messages,
    model=None,
    user_id=None,
    prompt_type="coin_analysis",
    symbol=None,
    include_db_context=True,
    amount=None,
    is_fallback_attempt=False,
    tier_index=0,
    use_cache=False,
    search_lookback_hours=12,
    forecast_horizon_hours=None,
):
    """
    AGENTIC AI WORKFLOW - 3-STAGE PROCESS WITH 3-TIER CASCADE FAILOVER:
    Tier 0: Primary AI Integration
    Tier 1: Secondary AI Integration
    Tier 2: Tertiary AI Integration
    """
    try:
        if not user_id:
            user_obj = User.query.filter_by(username=username).first()
            user_id = user_obj.id if user_obj else session.get('_user_id')
        
        user_ai_settings = get_user_ai_settings(username)
        max_tokens = user_ai_settings.get('ai_max_tokens', 2000)

        cred = get_user_credentials(username)
        if not cred:
            raise ValueError(f"No credentials found for user: {username}")
        
        # Build initial list of configured tiers
        tier_configs = []
        p_provider = user_ai_settings.get('ai_provider', 'openai')
        p_model = user_ai_settings.get('ai_model')
        p_reasoning = (user_ai_settings.get('ai_reasoning_level') or 'medium').lower()
        if p_provider:
            tier_configs.append(('primary', p_provider, p_model, p_reasoning))

        s_provider = user_ai_settings.get('ai_provider_secondary') or user_ai_settings.get('ai_provider_fallback')
        s_model = user_ai_settings.get('ai_model_secondary') or user_ai_settings.get('ai_model_fallback')
        s_reasoning = (user_ai_settings.get('ai_reasoning_level_secondary') or user_ai_settings.get('ai_reasoning_level_fallback') or 'medium').lower()
        if s_provider:
            tier_configs.append(('secondary', s_provider, s_model, s_reasoning))

        t_provider = user_ai_settings.get('ai_provider_tertiary')
        t_model = user_ai_settings.get('ai_model_tertiary')
        t_reasoning = (user_ai_settings.get('ai_reasoning_level_tertiary') or 'medium').lower()
        if t_provider:
            tier_configs.append(('tertiary', t_provider, t_model, t_reasoning))

        # Auto-discover additional fallback providers from all active API keys in user credentials
        used_providers = {t[1] for t in tier_configs if t[1]}
        provider_defaults = {
            'openai': ('gpt-5', 'medium'),
            'gemini': ('gemini-3.7-flash', 'medium'),
            'perplexity': ('sonar-pro', 'medium'),
            'zai': ('glm-4.7-flash', 'medium'),
            'inception': ('mercury-2', 'medium')
        }
        for prov, (def_mod, def_reas) in provider_defaults.items():
            if prov not in used_providers:
                has_key = bool(
                    getattr(cred, f"{prov}_key", None) or 
                    getattr(cred, f"{prov}_key_fallback", None) or 
                    getattr(cred, f"{prov}_key_tertiary", None)
                )
                if has_key:
                    tier_configs.append((f"auto_fallback_{prov}", prov, def_mod, def_reas))
                    used_providers.add(prov)

        # Handle backward-compatible is_fallback_attempt flag
        if is_fallback_attempt and tier_index == 0:
            tier_index = 1

        if tier_index >= len(tier_configs):
            raise ValueError(f"No more fallback tiers available (requested tier index {tier_index})")

        current_tier_name, provider, configured_model, ai_reasoning_level = tier_configs[tier_index]

        model = configured_model or model or 'gpt-5'

        if tier_index > 0:
            logger.info(f"⚠️ USING {current_tier_name.upper()} AI PROVIDER: {provider} / {model} (reasoning: {ai_reasoning_level})")
        else:
            logger.info(f"Using PRIMARY AI Provider: {provider} / {model} (reasoning: {ai_reasoning_level})")

        def _pick_key(p):
            if current_tier_name == 'tertiary':
                return getattr(cred, f"{p}_key_tertiary", None) or getattr(cred, f"{p}_key_fallback", None) or getattr(cred, f"{p}_key", None)
            elif current_tier_name == 'secondary':
                return getattr(cred, f"{p}_key_fallback", None) or getattr(cred, f"{p}_key", None)
            else:
                return getattr(cred, f"{p}_key", None) or getattr(cred, f"{p}_key_fallback", None) or getattr(cred, f"{p}_key_tertiary", None)

        original_user_message = ""
        for msg in messages:
            if msg.get('role') == 'user':
                original_user_message = msg.get('content', '')
                break



        # Check for cached AI response
        if use_cache:
            cache_key = hashlib.md5(f"{provider}:{model}:{prompt_type}:{original_user_message}".encode()).hexdigest()
            cached = AICache.query.filter_by(cache_key=cache_key).first()
            if cached and cached.is_valid():
                logger.info(f"Returning cached AI response for {username} ({cache_key})")
                return AIResponseWrapper(cached.response, tier=current_tier_name, provider=provider, model=model, search_status="Cached Response"), ""

        # Get prompt templates
        ai_prompts = get_user_ai_prompts(user_id)
        stage1_prompt_map = {
            'coin_analysis': getattr(ai_prompts, 'coin_analysis_pre', None),
            'market_analysis': getattr(ai_prompts, 'market_analysis_pre', None),
            'portfolio_review': getattr(ai_prompts, 'portfolio_review_pre', None),
            'sentiment_analysis': getattr(ai_prompts, 'sentiment_prompt_pre', None),
            'watchlist_sentiment_analysis': getattr(ai_prompts, 'watchlist_sentiment_prompt_pre', None),
            'copilot': getattr(ai_prompts, 'copilot_chat_pre', None) or user_ai_settings.get('copilot_chat_pre'),
            'manual': getattr(ai_prompts, 'copilot_chat_pre', None) or user_ai_settings.get('copilot_chat_pre'),
            # Webull crypto may honor the user's existing crypto research prompt;
            # securities intentionally use a distinct prompt family.
            'webull_crypto_analysis': getattr(ai_prompts, 'coin_analysis_pre', None) or WEBULL_CRYPTO_SEARCH_PROMPT,
            'webull_equity_analysis': WEBULL_EQUITY_SEARCH_PROMPT,
        }

        stage1_template = stage1_prompt_map.get(prompt_type)
        if not stage1_template:
            stage1_template = user_ai_settings.get('copilot_chat_pre') or "Analyze the query and list 1 or 2 targeted search queries."

        current_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        symbol_value = symbol or "CRYPTO"
        stage1_prompt = stage1_template.replace('{symbol}', symbol_value).replace('{datetime}', current_datetime)

        stage1_messages = [
            {"role": "system", "content": stage1_prompt},
            {"role": "user", "content": f"User query: {original_user_message}\n\nGenerate search queries."}
        ]

        def _execute_ai_call(p_messages, p_max_tokens=600):
            if provider == 'openai':
                key = _pick_key('openai')
                if not key:
                    raise ValueError("OpenAI API key not configured")
                from openai import OpenAI
                client = OpenAI(api_key=key, timeout=25.0)
                # Reasoning models require enough max_completion_tokens for internal reasoning tokens + output tokens
                is_reasoning_model = any(m in (model or '').lower() for m in ['o1', 'o3', 'gpt-5', 'reasoning'])
                effective_tokens = max(p_max_tokens, 2500) if is_reasoning_model else p_max_tokens
                resp = client.chat.completions.create(
                    model=model,
                    messages=p_messages,
                    max_completion_tokens=effective_tokens
                )
                msg = resp.choices[0].message if (resp.choices and len(resp.choices) > 0) else None
                content = getattr(msg, 'content', '') or ''
                if not content and hasattr(msg, 'reasoning_content') and msg.reasoning_content:
                    content = msg.reasoning_content
                return content

            elif provider == 'zai':
                key = _pick_key('zai')
                if not key:
                    raise ValueError("Z.AI API key not configured")
                from zai_client import ZAIClient
                client = ZAIClient(key, timeout_seconds=12)
                resp = client.chat_completion(messages=p_messages, model=model, max_tokens=max(p_max_tokens, 1024), temperature=0.2)
                if resp.get('success'):
                    return resp.get('content')
                last_zai_error = resp.get('error', 'Unknown Z.AI error')
                raise Exception(f"Z.AI error: {last_zai_error}")

            elif provider == 'perplexity':
                key = _pick_key('perplexity')
                if not key:
                    raise ValueError("Perplexity API key not configured")
                r = requests.post(
                    "https://api.perplexity.ai/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": p_messages, "max_tokens": p_max_tokens},
                    timeout=15
                )
                if r.status_code == 200:
                    return r.json()['choices'][0]['message']['content']
                raise Exception(f"Perplexity error ({r.status_code}): {r.text}")

            elif provider == 'inception':
                key = _pick_key('inception')
                if not key:
                    raise ValueError("Inception Labs API key not configured")
                r = requests.post(
                    "https://api.inceptionlabs.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"model": model or "mercury-2", "messages": p_messages, "max_tokens": p_max_tokens},
                    timeout=15
                )
                if r.status_code == 200:
                    return r.json()['choices'][0]['message']['content']
                raise Exception(f"Inception Labs error ({r.status_code}): {r.text}")

            elif provider == 'gemini':
                key = _pick_key('gemini')
                if not key:
                    raise ValueError("Gemini API key not configured")
                contents = []
                system_instruction = None
                for msg in p_messages:
                    r = msg.get("role", "user")
                    text_content = msg.get("content", "")
                    if r == 'system':
                        system_instruction = {"parts": [{"text": text_content}]}
                    elif r == 'assistant':
                        contents.append({"role": "model", "parts": [{"text": text_content}]})
                    else:
                        contents.append({"role": "user", "parts": [{"text": text_content}]})
                
                # Setup reasoning effort / thinkingConfig
                budget_map = {'low': 1024, 'medium': 2048, 'high': 4096}
                budget = budget_map.get(ai_reasoning_level, 2048)
                
                gen_config = {"maxOutputTokens": p_max_tokens}
                # Only include thinkingConfig if maxOutputTokens allows space for both thinking and output
                if p_max_tokens > budget + 512:
                    gen_config["thinkingConfig"] = {"thinkingBudget": budget}
                
                req_json = {
                    "contents": contents,
                    "generationConfig": gen_config
                }
                if system_instruction:
                    req_json["systemInstruction"] = system_instruction
                
                last_err = ""
                for api_ver in ['v1beta', 'v1']:
                    url = f"https://generativelanguage.googleapis.com/{api_ver}/models/{model}:generateContent?key={key}"
                    try:
                        r = requests.post(url, json=req_json, timeout=15)
                        if r.status_code == 200:
                            res_json = r.json()
                            try:
                                return res_json['candidates'][0]['content']['parts'][0]['text']
                            except Exception:
                                return json.dumps(res_json)
                        elif r.status_code == 400 and "thinkingConfig" in gen_config:
                            # Retry without thinkingConfig in case model does not support it
                            req_json["generationConfig"] = {"maxOutputTokens": p_max_tokens}
                            r_retry = requests.post(url, json=req_json, timeout=15)
                            if r_retry.status_code == 200:
                                res_json = r_retry.json()
                                try:
                                    return res_json['candidates'][0]['content']['parts'][0]['text']
                                except Exception:
                                    return json.dumps(res_json)
                            last_err = r_retry.text
                        else:
                            last_err = r.text
                    except Exception as req_ex:
                        last_err = str(req_ex)

                raise Exception(f"Gemini API error: {last_err}")
            
            else:
                raise ValueError(f"Unsupported AI provider: {provider}")

        # Stage 1: Queries
        if prompt_type in ['sentiment_analysis', 'watchlist_sentiment_analysis']:
            search_queries = [
                f"{symbol_value} crypto current price latest news past {search_lookback_hours} hours today",
                f"{symbol_value} cryptocurrency market sentiment news past {search_lookback_hours} hours"
            ]
        elif prompt_type == 'webull_equity_analysis':
            search_queries = [f"{symbol_value} stock or ETF latest news earnings sector catalysts today"]
        elif prompt_type in ['copilot', 'manual']:
            # Fast deterministic query for real-time Copilot chat without multi-second LLM query overhead
            if symbol_value in ['PORTFOLIO', 'CRYPTO', '']:
                search_queries = ["crypto market price trend bitcoin ethereum sentiment today"]
            elif symbol_value in ['AAPL', 'NVDA', 'TSLA', 'SPCX', 'SPY', 'QQQ', 'MSFT', 'AMZN', 'GOOGL', 'META']:
                search_queries = [f"{symbol_value} stock market price catalysts sentiment today"]
            else:
                search_queries = [f"{symbol_value} cryptocurrency market price trend sentiment today"]
        else:
            try:
                search_queries_text = _execute_ai_call(stage1_messages, p_max_tokens=300)
                search_queries = [q.strip().strip('-*0123456789. ') for q in (search_queries_text or '').split('\n') if q.strip()][:2]
            except Exception as e:
                logger.warning(f"Stage 1 query generation error: {e}. Using fallback query.")
                search_queries = [f"{symbol_value} crypto news market analysis today"]

        # Stage 2: NewsAPI plus web searches. If a NewsAPI key is configured, its
        # results are always included before supplemental web-market context.
        # Brave's closest supported freshness filter is past-day; the query
        # itself carries the user's exact configured lookback window.
        search_summaries = []
        search_sources = set()
        freshness_filter = "pd"  # Brave Search API past-day (24h) parameter
        valid_search_results = 0
        symbol_mentioned = False
        clean_sym = (symbol_value or '').upper()

        asset_context = 'equity' if prompt_type == 'webull_equity_analysis' else 'crypto'
        for item in news_api_search(clean_sym, username, search_lookback_hours, max_results=4, asset_context=asset_context):
            src = item.get('source', '')
            if src:
                search_sources.add(src)
            valid_search_results += 1
            title_snip = f"{item.get('title', '')} {item.get('snippet', '')}".upper()
            if clean_sym and clean_sym in title_snip:
                symbol_mentioned = True
            search_summaries.append(f"- {item.get('title')}: {item.get('snippet')} ({item.get('url')})")

        for q in search_queries:
            if not q: continue
            results = web_search(q, max_results=2, username=username, freshness=freshness_filter)
            for item in results:
                src = item.get('source', '')
                if src:
                    search_sources.add(src)
                if src != 'System':
                    valid_search_results += 1
                    title_snip = f"{item.get('title', '')} {item.get('snippet', '')}".upper()
                    if clean_sym and clean_sym in title_snip:
                        symbol_mentioned = True
                search_summaries.append(f"- {item.get('title')}: {item.get('snippet')} ({item.get('url')})")
        
        search_text = "\n".join(search_summaries) if search_summaries else "No recent search results found."

        # Compute search status string
        if any('NewsAPI' in s for s in search_sources):
            supplemental = ' + web search' if any(('Brave' in s or 'DuckDuckGo' in s) for s in search_sources) else ''
            search_status = f"NewsAPI ({valid_search_results} results{supplemental})"
        elif any('Brave' in s for s in search_sources):
            if valid_search_results > 0:
                if symbol_mentioned:
                    search_status = f"Brave Search ({valid_search_results} results found)"
                else:
                    search_status = f"Brave Search ({valid_search_results} results, no specific news)"
            else:
                search_status = "Brave Search (0 results found)"
        elif any('DuckDuckGo' in s for s in search_sources):
            search_status = f"DuckDuckGo Fallback ({valid_search_results} results found)"
        else:
            search_status = "Web Search Unavailable"

        # Stage 3: Synthesis
        stage3_prompt_map = {
            'coin_analysis': getattr(ai_prompts, 'coin_analysis_post', None),
            'market_analysis': getattr(ai_prompts, 'market_analysis_post', None),
            'portfolio_review': getattr(ai_prompts, 'portfolio_review_post', None),
            'sentiment_analysis': getattr(ai_prompts, 'sentiment_prompt_post', None),
            'watchlist_sentiment_analysis': getattr(ai_prompts, 'watchlist_sentiment_prompt_post', None),
            'copilot': getattr(ai_prompts, 'copilot_chat_post', None) or user_ai_settings.get('copilot_chat_post'),
            'manual': getattr(ai_prompts, 'copilot_chat_post', None) or user_ai_settings.get('copilot_chat_post'),
            'webull_crypto_analysis': getattr(ai_prompts, 'coin_analysis_post', None) or WEBULL_CRYPTO_RESEARCH_PROMPT,
            'webull_equity_analysis': WEBULL_EQUITY_RESEARCH_PROMPT,
        }
        stage3_template = stage3_prompt_map.get(prompt_type)
        if not stage3_template:
            stage3_template = user_ai_settings.get('copilot_chat_post') or "Synthesize the analysis and recent market data into a clear summary."
        
        try:
            stage3_system = stage3_template.format(symbol=symbol_value, datetime=current_datetime, amount=amount_value)
        except Exception:
            stage3_system = stage3_template.replace('{symbol}', symbol_value).replace('{datetime}', current_datetime)

        if prompt_type in ['copilot', 'manual']:
            stage3_system += (
                "\n\nCRITICAL EXCHANGE ARCHITECTURE RULE (OCO ORDERS):\n"
                "- On Binance and Binance.US, an OCO (One-Cancels-the-Other) order is natively created and managed by the exchange matching engine as an Order List (orderListId) containing two linked legs: a STOP_LOSS_LIMIT leg and a LIMIT_MAKER leg.\n"
                "- When the user's data shows an active OCO order bracket with an OrderListId or paired limit/stop-loss legs, this IS a confirmed, native, fully linked exchange OCO order. The exchange automatically cancels the opposing leg if either executes or triggers.\n"
                "- NEVER tell the user their OCO orders are 'separate independent orders', 'unlinked', or that 'Binance.US does not support an OCO wrapper'. NEVER instruct the user to 'link them into an OCO order'—they are ALREADY natively linked on the exchange. Analyze them directly as a unified OCO trading strategy."
            )

        stage3_user_msg = f"{original_user_message}\n\n=== RECENT WEB SEARCH RESULTS ===\n{search_text}"

        stage3_messages = [
            {"role": "system", "content": stage3_system},
            {"role": "user", "content": stage3_user_msg}
        ]

        final_content = _execute_ai_call(stage3_messages, p_max_tokens=max_tokens)
        return AIResponseWrapper(
            final_content,
            tier=current_tier_name,
            provider=provider,
            model=model,
            search_status=search_status
        ), stage3_user_msg

    except Exception as e:
        logger.error(f"Error in call_ai_with_web_search (tier: {current_tier_name if 'current_tier_name' in locals() else tier_index}): {e}")
        
        # Check if another tier is configured and available
        next_tier_index = tier_index + 1
        if 'tier_configs' in locals() and next_tier_index < len(tier_configs):
            next_tier_name, next_provider, next_model, _ = tier_configs[next_tier_index]
            if next_provider:
                logger.info(f"⚠️ FAILING OVER TO {next_tier_name.upper()} AI PROVIDER ({next_provider})...")
                return call_ai_with_web_search(
                    username=username,
                    messages=messages,
                    model=None,
                    user_id=user_id,
                    prompt_type=prompt_type,
                    symbol=symbol,
                    include_db_context=include_db_context,
                    amount=amount,
                    tier_index=next_tier_index,
                    search_lookback_hours=search_lookback_hours,
                    forecast_horizon_hours=forecast_horizon_hours,
                )
        raise

def record_sentiment_history(user_id, symbol, sentiment, sentiment_reason, price_at_prediction, provider=None, model=None, tier=None, source_type='portfolio', coin_id=None, search_status=None, forecast_horizon_hours=24, grading_config=None):
    """Save an AI sentiment recommendation snapshot into sentiment_history for accuracy tracking."""
    try:
        from models import SentimentHistory
        from datetime import timezone
        now = datetime.now(timezone.utc)
        hist = SentimentHistory(
            user_id=user_id,
            coin_id=coin_id,
            symbol=symbol.upper(),
            source_type=source_type,
            sentiment=sentiment,
            sentiment_reason=sentiment_reason,
            price_at_prediction=float(price_at_prediction or 0.0),
            provider=provider,
            model=model,
            tier=tier,
            sentiment_search_status=search_status,
            created_at=now,
            outcome_status='tracking',
            forecast_horizon_hours=float(forecast_horizon_hours),
            target_evaluation_at=now + timedelta(hours=float(forecast_horizon_hours)),
            evaluation_method='fixed_horizon',
            grading_config=grading_config,
        )
        db.session.add(hist)
        db.session.commit()
    except Exception as e:
        logger.error(f"Error recording sentiment history: {e}")
        db.session.rollback()


def log_ai_conversation(user_id, prompt_type, sender, body, symbol=None, coin_id=None, provider=None, model=None, tier=None):
    """Helper to log conversation to ai_conversations table."""
    try:
        now = datetime.utcnow()
        conv = AIConversation(
            user_id=user_id,
            prompt_type=prompt_type,
            sender=sender,
            body=body,
            date=now.date(),
            time=now.strftime("%H:%M:%S"),
            coin_id=coin_id,
            created_at=now,
            provider=provider,
            model=model,
            tier=tier
        )
        db.session.add(conv)
        db.session.commit()
        return conv.id
    except Exception as e:
        logger.error(f"Error logging AI conversation: {e}")
        db.session.rollback()
        return None

def parse_sentiment_json(response_text, is_watchlist=False):
    """
    Parse the AI JSON output for sentiment phrase and reason.
    For Portfolio (is_watchlist=False):
      Valid phrases: 'Hold', 'Buy Immediately', 'Consider Buying', 'Sell Immediately', 'Consider Selling'
    For Watchlist (is_watchlist=True):
      Valid phrases: 'Avoid', 'Watch', 'Consider Buying', 'Definitely Buy'
    """
    if is_watchlist:
        valid_phrases = {
            'avoid': 'Avoid',
            'watch': 'Watch',
            'consider buying': 'Consider Buying',
            'definitely buy': 'Definitely Buy',
            # Tolerant fallbacks
            'buy immediately': 'Definitely Buy',
            'strong buy': 'Definitely Buy',
            'buy': 'Consider Buying',
            'hold': 'Watch',
            'neutral': 'Watch',
            'sell': 'Avoid',
            'sell immediately': 'Avoid',
            'strong sell': 'Avoid',
            'do not buy': 'Avoid',
            'pass': 'Avoid',
            'ignore': 'Avoid'
        }
        default_phrase = "Watch"
    else:
        valid_phrases = {
            'buy immediately': 'Buy Immediately',
            'consider buying': 'Consider Buying',
            'sell immediately': 'Sell Immediately',
            'consider selling': 'Consider Selling',
            'hold': 'Hold',
            # Tolerant fallbacks
            'strong buy': 'Buy Immediately',
            'buy': 'Consider Buying',
            'strong sell': 'Sell Immediately',
            'sell': 'Consider Selling'
        }
        default_phrase = "Hold"
    
    phrase = None
    reason = None
    
    clean_text = (response_text or '').strip()

    # Strip markdown code fences if present
    if '```' in clean_text:
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', clean_text)
        if match:
            clean_text = match.group(1).strip()
            
    # Try finding JSON object {...} or array [...]
    json_match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', clean_text)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1))
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    k_lower = str(k).lower()
                    v_str = str(v).strip()
                    if any(x in k_lower for x in ['item 1', 'item1', 'sentiment', 'action', 'signal', 'recommendation', 'suggestion', 'item_1']):
                        if v_str.lower() in valid_phrases:
                            phrase = valid_phrases[v_str.lower()]
                    elif any(x in k_lower for x in ['item 2', 'item2', 'reason', 'explanation', 'description', 'summary', 'item_2']):
                        if v_str:
                            reason = v_str
                
                # If phrase not identified by key name, scan values
                if not phrase:
                    for v in parsed.values():
                        if str(v).strip().lower() in valid_phrases:
                            phrase = valid_phrases[str(v).strip().lower()]
                            break
                # If reason not found by key name, take first long non-phrase value
                if not reason:
                    for k, v in parsed.items():
                        candidate = str(v).strip()
                        if candidate != phrase and len(candidate) > 10:
                            reason = candidate
                            break
                            
            elif isinstance(parsed, list) and len(parsed) >= 2:
                p_cand = str(parsed[0]).strip()
                if p_cand.lower() in valid_phrases:
                    phrase = valid_phrases[p_cand.lower()]
                reason = str(parsed[1]).strip()
        except Exception as e:
            logger.warning(f"JSON sentiment decode error: {e}. Raw: {repr(json_match.group(1)[:200])}")
    else:
        # No JSON found — AI did not follow the required JSON format
        logger.warning(f"Sentiment AI response contained no JSON. Raw response: {repr(clean_text[:300])}")
            
    # Fallback: scan raw text for a sentiment phrase if JSON parse missed it
    if not phrase:
        scan_keys = list(valid_phrases.keys())
        # Sort by longest string first so multi-word matches take precedence
        scan_keys.sort(key=len, reverse=True)
        for p_key in scan_keys:
            if re.search(r'\b' + re.escape(p_key) + r'\b', clean_text, re.IGNORECASE):
                phrase = valid_phrases[p_key]
                break
                
    # Fallback: extract reason from remaining text after removing the phrase
    if not reason and phrase:
        remainder = re.sub(re.escape(phrase), '', clean_text, flags=re.IGNORECASE)
        remainder = re.sub(r'[\{\}\[\]\"\':`]', ' ', remainder).strip()
        remainder = re.sub(r'\s+', ' ', remainder).strip()
        if len(remainder) > 10:
            reason = remainder
            
    return phrase or default_phrase, reason or ""

def analyze_single_symbol_sentiment(user_id, username, symbol, is_watchlist=False, coin_id=None, amount=0.0):
    """
    Run on-demand sentiment analysis for a single symbol (Portfolio coin or Watchlist coin).
    Updates the database with parsed sentiment and reason, logs the AI conversation,
    and returns (sentiment, sentiment_reason).
    """
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return "Error", "Invalid coin symbol"

    if is_stablecoin(symbol):
        logger.info(f"Skipping sentiment analysis for stablecoin {symbol} (marking {'Watch' if is_watchlist else 'Hold'})")
        sentiment_res = "Watch" if is_watchlist else "Hold"
        reason_res = "Dollar-pegged stablecoin for capital preservation."
        if is_watchlist:
            wl_row = WatchlistCoin.query.filter_by(user_id=user_id, symbol=symbol).first()
            if wl_row:
                wl_row.sentiment = sentiment_res
                wl_row.sentiment_reason = reason_res
                if hasattr(wl_row, 'sentiment_last_updated'):
                    wl_row.sentiment_last_updated = datetime.utcnow()
                db.session.commit()
        else:
            coin_row = Coin.query.filter_by(user_id=user_id, symbol=symbol).first()
            if coin_row:
                coin_row.sentiment = sentiment_res
                coin_row.sentiment_reason = reason_res
                coin_row.sentiment_last_updated = datetime.utcnow()
                db.session.commit()
        return sentiment_res, reason_res

    if not is_ai_enabled(username):
        logger.info(f"AI disabled for {username}, skipping sentiment analysis for {symbol}")
        default_sentiment = "Watch" if is_watchlist else "Hold"
        default_reason = "AI integration disabled in Settings."
        if is_watchlist:
            wl_row = WatchlistCoin.query.filter_by(user_id=user_id, symbol=symbol).first()
            if wl_row:
                wl_row.sentiment = default_sentiment
                wl_row.sentiment_reason = default_reason
                if hasattr(wl_row, 'sentiment_last_updated'):
                    wl_row.sentiment_last_updated = datetime.utcnow()
                db.session.commit()
        return default_sentiment, default_reason

    try:
        settings = get_user_ai_settings(username)
        notifications_enabled = settings.get('ai_notifications_enabled', True)
        ai_prompts_obj = get_user_ai_prompts(user_id)
        
        if is_watchlist:
            sentiment_pre_prompt = (getattr(ai_prompts_obj, 'watchlist_sentiment_prompt_pre', None) or "").strip()
            sentiment_post_prompt = (getattr(ai_prompts_obj, 'watchlist_sentiment_prompt_post', None) or "").strip()
            prompt_type = "watchlist_sentiment_analysis"
        else:
            sentiment_pre_prompt = (getattr(ai_prompts_obj, 'sentiment_prompt_pre', None) or "").strip()
            sentiment_post_prompt = (getattr(ai_prompts_obj, 'sentiment_prompt_post', None) or "").strip()
            prompt_type = "sentiment_analysis"

        if not sentiment_pre_prompt or not sentiment_post_prompt:
            logger.warning(f"Missing sentiment prompts for user {username} (watchlist={is_watchlist}). Marking Error.")
            err_sentiment = "Error"
            err_reason = "Missing sentiment prompt configuration in Settings."
            if is_watchlist:
                wl_row = WatchlistCoin.query.filter_by(user_id=user_id, symbol=symbol).first()
                if wl_row:
                    wl_row.sentiment = err_sentiment
                    wl_row.sentiment_reason = err_reason
                    if hasattr(wl_row, 'sentiment_last_updated'):
                        wl_row.sentiment_last_updated = datetime.utcnow()
                    db.session.commit()
            else:
                coin_row = Coin.query.filter_by(user_id=user_id, symbol=symbol).first()
                if coin_row:
                    coin_row.sentiment = err_sentiment
                    coin_row.sentiment_reason = err_reason
                    coin_row.sentiment_last_updated = datetime.utcnow()
                    db.session.commit()
            return err_sentiment, err_reason

        current_datetime = format_eastern_datetime(None, "%B %d, %Y at %I:%M %p EDT")
        
        # Mark coin as Checking now... in DB so any live queries show real-time progress
        try:
            if is_watchlist:
                wl_live = WatchlistCoin.query.filter_by(user_id=user_id, symbol=symbol).first()
                if wl_live:
                    wl_live.sentiment = "Checking now..."
                    db.session.commit()
            else:
                c_live = Coin.query.filter_by(user_id=user_id, symbol=symbol).first()
                if c_live:
                    c_live.sentiment = "Checking now..."
                    db.session.commit()
        except Exception as mark_err:
            logger.warning(f"Could not mark {symbol} as Checking now...: {mark_err}")
            db.session.rollback()

        # Look up live price from Binance or local coin record to anchor sentiment analysis
        current_price = None
        try:
            from routes.helpers import fetch_crypto_price
            current_price = fetch_crypto_price(symbol)
        except Exception:
            pass
        if current_price is None and not is_watchlist:
            c = Coin.query.filter_by(user_id=user_id, symbol=symbol).first()
            if c and c.current:
                current_price = c.current
        elif current_price is None and is_watchlist:
            w = WatchlistCoin.query.filter_by(user_id=user_id, symbol=symbol).first()
            if w and hasattr(w, 'current_price') and w.current_price:
                current_price = w.current_price

        price_str = f"${current_price:,.2f}" if current_price is not None else "N/A"

        # Fetch the configured history window and bind this prediction to a
        # separate, fixed future evaluation horizon.
        lookback_hours = 12
        forecast_horizon_hours = 24
        try:
            if is_watchlist:
                lookback_hours = int(settings.get('watchlist_sentiment_history_lookback_hours', 12) or 12)
                forecast_horizon_hours = int(settings.get('watchlist_sentiment_forecast_horizon_hours', 24) or 24)
            else:
                lookback_hours = int(settings.get('sentiment_history_lookback_hours', 12) or 12)
                forecast_horizon_hours = int(settings.get('sentiment_forecast_horizon_hours', 24) or 24)
        except Exception:
            lookback_hours, forecast_horizon_hours = 12, 24
        lookback_hours = max(1, min(72, lookback_hours))
        forecast_horizon_hours = max(1, min(168, forecast_horizon_hours))

        from services.sentiment_outcome_service import (
            format_forecast_rules, get_sentiment_thresholds, serialize_grading_config,
        )
        grading_thresholds = get_sentiment_thresholds(
            UserSetting.query.filter_by(user_id=user_id).first()
        )
        grading_config = serialize_grading_config(grading_thresholds)
        rule_text = format_forecast_rules(grading_thresholds, is_watchlist=is_watchlist)
        forecast_target = datetime.now(timezone.utc) + timedelta(hours=forecast_horizon_hours)

        from services.price_history_service import get_last_nh_price_and_volume
        _, price_vol_history_text = get_last_nh_price_and_volume(symbol, lookback_hours=lookback_hours)

        sentiment_request = (
            f"{'WATCHLIST_' if is_watchlist else ''}SENTIMENT_ANALYSIS_DATA\n"
            f"symbol: {symbol}\n"
            f"current_price: {price_str}\n"
            f"amount: {amount}\n"
            f"datetime: {current_datetime}\n"
            f"history_lookback_hours: {lookback_hours}\n"
            f"forecast_horizon_hours: {forecast_horizon_hours}\n"
            f"forecast_target_utc: {forecast_target.isoformat()}\n"
            f"IMPORTANT: Make exactly one recommendation for the price move from the current live price to the fixed target above. Do not grade against the next analysis run. A manual refresh creates another independent forecast and does not shorten this horizon.\n"
            f"Use only the allowed recommendation labels and calibrate the choice to these exact grading boundaries:\n{rule_text}\n"
            f"The current live price is {price_str}. Base momentum, support/resistance, volume dynamics, and the forecast strictly on this live price, the hourly price & volume history below, and fresh news/market data from the past {lookback_hours} hours.\n\n"
            f"{price_vol_history_text}\n"
        )

        response, actual_stage3_prompt = call_ai_with_web_search(
            username=username,
            messages=[
                {"role": "system", "content": sentiment_post_prompt},
                {"role": "user", "content": sentiment_request}
            ],
            user_id=user_id,
            prompt_type=prompt_type,
            symbol=symbol,
            amount=amount,
            search_lookback_hours=lookback_hours,
            forecast_horizon_hours=forecast_horizon_hours,
        )

        sentiment_text = ""
        if hasattr(response, 'choices') and response.choices:
            sentiment_text = response.choices[0].message.content.strip()
        elif isinstance(response, dict) and 'content' in response:
            sentiment_text = response['content'].strip()
        else:
            sentiment_text = str(response).strip()

        sentiment_result, sentiment_reason = parse_sentiment_json(sentiment_text, is_watchlist=is_watchlist)

        resp_tier = getattr(response, 'tier', 'primary')
        resp_provider = getattr(response, 'provider', None)
        resp_model = getattr(response, 'model', None)
        resp_search_status = getattr(response, 'search_status', None) or 'Brave Search'

        # Update database
        resolved_coin_id = coin_id
        snapshot_price = 0.0
        if is_watchlist:
            wl_row = WatchlistCoin.query.filter_by(user_id=user_id, symbol=symbol).first()
            if wl_row:
                wl_row.sentiment = sentiment_result
                wl_row.sentiment_reason = sentiment_reason
                wl_row.sentiment_last_updated = datetime.utcnow()
                wl_row.sentiment_provider = resp_provider
                wl_row.sentiment_model = resp_model
                wl_row.sentiment_tier = resp_tier
                wl_row.sentiment_search_status = resp_search_status
                db.session.commit()
                resolved_coin_id = wl_row.id
                snapshot_price = float(getattr(wl_row, 'current_price', 0.0) or 0.0)
        else:
            coin_row = Coin.query.filter_by(user_id=user_id, symbol=symbol).first()
            if coin_row:
                coin_row.sentiment = sentiment_result
                coin_row.sentiment_reason = sentiment_reason
                coin_row.sentiment_last_updated = datetime.utcnow()
                coin_row.sentiment_provider = resp_provider
                coin_row.sentiment_model = resp_model
                coin_row.sentiment_tier = resp_tier
                coin_row.sentiment_search_status = resp_search_status
                db.session.commit()
                resolved_coin_id = coin_row.id
                snapshot_price = float(getattr(coin_row, 'current', 0.0) or getattr(coin_row, 'avg_entry', 0.0) or 0.0)

        if not snapshot_price or snapshot_price <= 0:
            try:
                from routes.trading import fetch_binance_price
                snapshot_price = float(fetch_binance_price(symbol) or 0.0)
            except Exception:
                pass

        record_sentiment_history(
            user_id=user_id,
            symbol=symbol,
            sentiment=sentiment_result,
            sentiment_reason=sentiment_reason,
            price_at_prediction=snapshot_price,
            provider=resp_provider,
            model=resp_model,
            tier=resp_tier,
            source_type='watchlist' if is_watchlist else 'portfolio',
            coin_id=resolved_coin_id,
            search_status=resp_search_status,
            forecast_horizon_hours=forecast_horizon_hours,
            grading_config=grading_config,
        )

        log_ai_conversation(user_id, prompt_type, "user", actual_stage3_prompt, symbol=symbol, coin_id=resolved_coin_id, provider=resp_provider, model=resp_model, tier=resp_tier)
        time.sleep(0.1)
        log_ai_conversation(user_id, prompt_type, "ai", sentiment_text, symbol=symbol, coin_id=resolved_coin_id, provider=resp_provider, model=resp_model, tier=resp_tier)

        # Send Telegram alert if notable trading signal
        if notifications_enabled:
            should_notify = False
            if is_watchlist and sentiment_result in ['Definitely Buy', 'Consider Buying']:
                should_notify = True
            elif not is_watchlist and sentiment_result in ['Buy Immediately', 'Consider Buying', 'Sell Immediately', 'Consider Selling']:
                should_notify = True

            if should_notify:
                alert_msg = (
                    f"🚀 AI {'WATCHLIST' if is_watchlist else 'PORTFOLIO'} SIGNAL: {symbol}\n"
                    f"Signal: {sentiment_result.upper()}\n"
                    f"Reason: {sentiment_reason}\n"
                    f"Time: {current_datetime}"
                )
                send_telegram_message(username, alert_msg)
                create_system_notification(
                    user_id_or_name=user_id,
                    category='sentiment_alert',
                    symbol=symbol,
                    message=f"AI Signal: {sentiment_result} — {sentiment_reason}",
                    table_type='watchlist' if is_watchlist else 'portfolio'
                )
                logger.info(f"Sent AI Trading Alert for {symbol} ({sentiment_result})")

        return sentiment_result, sentiment_reason

    except Exception as e:
        logger.error(f"Error in analyze_single_symbol_sentiment for {symbol}: {e}")
        try:
            if is_watchlist:
                wl_row = WatchlistCoin.query.filter_by(user_id=user_id, symbol=symbol).first()
                if wl_row:
                    wl_row.sentiment = "Error"
                    wl_row.sentiment_reason = f"Analysis error: {str(e)}"
                    if hasattr(wl_row, 'sentiment_last_updated'):
                        wl_row.sentiment_last_updated = datetime.utcnow()
                    db.session.commit()
            else:
                coin_row = Coin.query.filter_by(user_id=user_id, symbol=symbol).first()
                if coin_row:
                    coin_row.sentiment = "Error"
                    coin_row.sentiment_reason = f"Analysis error: {str(e)}"
                    coin_row.sentiment_last_updated = datetime.utcnow()
                    db.session.commit()
        except Exception:
            db.session.rollback()
        raise e

def get_last_scheduled_time(anchor_time_str, freq_hours_int, now_utc=None):
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    
    try:
        h, m = map(int, anchor_time_str.split(':'))
    except Exception:
        h, m = 8, 0
    
    import pytz
    eastern = pytz.timezone('US/Eastern')
    now_est = now_utc.astimezone(eastern)
    
    start_of_day = now_est.replace(hour=h, minute=m, second=0, microsecond=0)
    
    if freq_hours_int <= 0:
        freq_hours_int = 24
        
    yesterday_anchor = start_of_day - timedelta(days=1)
    last_scheduled_est = yesterday_anchor
    current_step = yesterday_anchor
    
    max_steps = 100
    steps = 0
    while current_step <= now_est and steps < max_steps:
        last_scheduled_est = current_step
        current_step += timedelta(hours=freq_hours_int)
        steps += 1
        
    return last_scheduled_est.astimezone(pytz.utc)

def run_sentiment_analysis_for_user(user_id, username, force=False, symbol=None):
    """
    Run sentiment analysis for a user's portfolio coins.
    Parses JSON output for phrase ('Hold', 'Buy Immediately', 'Consider Buying', 'Sell Immediately', 'Consider Selling')
    and 1-2 sentence explanation stored as sentiment_reason.
    """
    if not symbol:
        with _running_sentiment_lock:
            if user_id in _running_sentiment_users:
                logger.info(f"Sentiment analysis already in progress for user {username} (ID: {user_id}), skipping duplicate trigger.")
                return 0
            _running_sentiment_users.add(user_id)

    count = 0
    try:
        try:
            db.session.rollback()
        except Exception:
            pass

        if not is_ai_enabled(username) and not force:
            logger.info(f"Skipping portfolio sentiment analysis for {username} - AI disabled")
            return 0
        
        settings = get_user_ai_settings(username)
        if not force:
            start_str = settings.get('ai_analysis_window_start', '08:00')
            end_str = settings.get('ai_analysis_window_end', '23:59')
            if not is_user_analysis_window_active(start_str, end_str):
                logger.info(f"Skipping portfolio sentiment analysis for {username} - outside analysis window")
                return 0

        portfolio_start_time = settings.get('portfolio_schedule_start_time', '08:00')
        sentiment_freq_hours = settings.get('sentiment_analysis_frequency_hours', 24)
        try:
            sentiment_freq_hours = int(float(sentiment_freq_hours))
        except Exception:
            sentiment_freq_hours = 24

        last_scheduled_utc = get_last_scheduled_time(portfolio_start_time, sentiment_freq_hours)

        if symbol:
            if is_stablecoin(symbol):
                logger.info(f"Skipping sentiment analysis for stablecoin {symbol}")
                return 0
            try:
                c_init = Coin.query.filter_by(user_id=user_id, symbol=symbol.upper().strip(), hidden=False).first()
                if c_init:
                    c_init.sentiment = "Checking now..."
                    db.session.commit()
            except Exception:
                db.session.rollback()
            coins = Coin.query.filter_by(user_id=user_id, symbol=symbol.upper().strip(), hidden=False).all()
        else:
            coins = Coin.query.filter_by(user_id=user_id, hidden=False).filter(Coin.amount > 0).all()
            coins = [c for c in coins if not is_stablecoin(c.symbol)]
            coins = [c for c in coins if getattr(c, 'sentiment_tracking_enabled', True) is not False]

        if not coins:
            logger.info(f"No portfolio coins found for sentiment analysis for user {username} (symbol={symbol})")
            return 0

        logger.info(f"Running portfolio sentiment analysis for {len(coins)} coins (User: {username}, Force: {force}, Symbol: {symbol})")

        for coin_row in coins:
            coin_id = coin_row.id
            sym = coin_row.symbol
            amount = coin_row.amount
            last_updated = coin_row.sentiment_last_updated

            if is_stablecoin(sym):
                logger.info(f"Skipping sentiment analysis for stablecoin {sym}")
                continue

            if not force and last_updated:
                last_utc = last_updated if last_updated.tzinfo else last_updated.replace(tzinfo=timezone.utc)
                if last_utc >= last_scheduled_utc:
                    continue

            logger.info(f"Analyzing portfolio sentiment for {sym} (User: {username})...")
            
            try:
                analyze_single_symbol_sentiment(
                    user_id=user_id,
                    username=username,
                    symbol=sym,
                    is_watchlist=False,
                    coin_id=coin_id,
                    amount=amount
                )
                count += 1
                if not symbol:
                    # Pacing delay between batch coins to prevent hitting LLM API rate limits
                    time.sleep(8)

            except Exception as coin_error:
                logger.error(f"Error processing portfolio sentiment for {sym}: {coin_error}")
                if not symbol:
                    # Extra backoff if error was due to rate limits
                    if any(k in str(coin_error).lower() for k in ["429", "rate limit", "resource_exhausted", "overloaded", "1302", "1305"]):
                        logger.warning(f"Rate limit detected for {sym}, cooling down for 15s before next coin...")
                        time.sleep(15)
                    else:
                        time.sleep(8)

        return count

    except Exception as e:
        logger.error(f"Error in run_sentiment_analysis_for_user for {username}: {e}")
        return count
    finally:
        if not symbol:
            with _running_sentiment_lock:
                _running_sentiment_users.discard(user_id)

def run_watchlist_sentiment_analysis_for_user(user_id, username, force=False, symbol=None):
    """
    Run sentiment analysis for a user's watchlist coins.
    Parses JSON output for phrase ('Avoid', 'Watch', 'Consider Buying', 'Definitely Buy')
    and 1-2 sentence explanation stored as sentiment_reason.
    """
    if not symbol:
        with _running_sentiment_lock:
            if user_id in _running_sentiment_users:
                logger.info(f"Sentiment analysis already in progress for user {username} (ID: {user_id}), skipping duplicate trigger.")
                return 0
            _running_sentiment_users.add(user_id)

    count = 0
    try:
        try:
            db.session.rollback()
        except Exception:
            pass

        if not is_ai_enabled(username) and not force:
            logger.info(f"Skipping watchlist sentiment analysis for {username} - AI disabled")
            return 0
        
        settings = get_user_ai_settings(username)
        if not force:
            start_str = settings.get('ai_analysis_window_start', '08:00')
            end_str = settings.get('ai_analysis_window_end', '23:59')
            if not is_user_analysis_window_active(start_str, end_str):
                logger.info(f"Skipping watchlist sentiment analysis for {username} - outside analysis window")
                return 0

        watchlist_start_time = settings.get('watchlist_schedule_start_time', '08:00')
        wl_freq_hours = settings.get('watchlist_sentiment_analysis_frequency_hours', 24)
        try:
            wl_freq_hours = int(float(wl_freq_hours))
        except Exception:
            wl_freq_hours = 24

        wl_last_scheduled_utc = get_last_scheduled_time(watchlist_start_time, wl_freq_hours)

        if symbol:
            if is_stablecoin(symbol):
                logger.info(f"Skipping watchlist sentiment analysis for stablecoin {symbol}")
                return 0
            try:
                w_init = WatchlistCoin.query.filter_by(user_id=user_id, symbol=symbol.upper().strip(), hidden=False).first()
                if w_init:
                    w_init.sentiment = "Checking now..."
                    db.session.commit()
            except Exception:
                db.session.rollback()
            wl_coins = WatchlistCoin.query.filter_by(user_id=user_id, symbol=symbol.upper().strip(), hidden=False).all()
        else:
            wl_coins = WatchlistCoin.query.filter_by(user_id=user_id, hidden=False).all()
            wl_coins = [w for w in wl_coins if not is_stablecoin(w.symbol)]
            wl_coins = [w for w in wl_coins if getattr(w, 'sentiment_tracking_enabled', True) is not False]

        if not wl_coins:
            logger.info(f"No watchlist coins found for sentiment analysis for user {username} (symbol={symbol})")
            return 0

        logger.info(f"Running watchlist sentiment analysis for {len(wl_coins)} coins (User: {username}, Force: {force}, Symbol: {symbol})")

        for wl_row in wl_coins:
            coin_id = wl_row.id
            sym = wl_row.symbol
            last_updated = getattr(wl_row, 'sentiment_last_updated', None)

            if is_stablecoin(sym):
                logger.info(f"Skipping sentiment analysis for watchlist stablecoin {sym}")
                continue

            if not force and last_updated:
                last_utc = last_updated if last_updated.tzinfo else last_updated.replace(tzinfo=timezone.utc)
                if last_utc >= wl_last_scheduled_utc:
                    continue

            logger.info(f"Analyzing watchlist sentiment for {sym} (User: {username})...")
            
            try:
                analyze_single_symbol_sentiment(
                    user_id=user_id,
                    username=username,
                    symbol=sym,
                    is_watchlist=True,
                    coin_id=coin_id,
                    amount=0.0
                )
                count += 1
                if not symbol:
                    # Pacing delay between batch coins to prevent hitting LLM API rate limits
                    time.sleep(8)

            except Exception as coin_error:
                logger.error(f"Error processing watchlist sentiment for {sym}: {coin_error}")
                if not symbol:
                    # Extra backoff if error was due to rate limits
                    if any(k in str(coin_error).lower() for k in ["429", "rate limit", "resource_exhausted", "overloaded", "1302", "1305"]):
                        logger.warning(f"Rate limit detected for {sym}, cooling down for 15s before next coin...")
                        time.sleep(15)
                    else:
                        time.sleep(8)

        return count

    except Exception as e:
        logger.error(f"Error in run_watchlist_sentiment_analysis_for_user for {username}: {e}")
        return count
    finally:
        if not symbol:
            with _running_sentiment_lock:
                _running_sentiment_users.discard(user_id)
