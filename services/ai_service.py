import os
import re
import json
import time
import logging
import threading
import requests
from datetime import datetime, timezone
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
from services.notification_service import send_telegram_message
from routes.helpers import decrypt_secret, is_stablecoin

logger = logging.getLogger(__name__)

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

def web_search(query, max_results=2, username=None):
    """
    Search the web for real-time crypto info.
    Priority: Brave Search API -> DuckDuckGo HTML -> Binance Price fallback.
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
                        logger.info(f"Attempting Brave Search ({key_name}) for query: {query}")
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
                            "freshness": "pd"
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

class AIResponseWrapper:
    """Wrapper to provide uniform `.choices[0].message.content` interface."""
    def __init__(self, text):
        self.text = text or ""
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
    is_fallback_attempt=False
):
    """
    AGENTIC AI WORKFLOW - 3-STAGE PROCESS:
    Stage 1: AI analyzes prompt and generates targeted search queries
    Stage 2: Web searches executed
    Stage 3: AI synthesizes prompt + search results
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
        
        def _pick_key(p):
            if is_fallback_attempt:
                if p == 'openai':
                    return decrypt_secret(cred.openai_key_fallback) or decrypt_secret(cred.openai_key)
                if p == 'zai':
                    return decrypt_secret(cred.zai_key_fallback) or decrypt_secret(cred.zai_key)
                if p == 'perplexity':
                    return decrypt_secret(cred.perplexity_key_fallback) or decrypt_secret(cred.perplexity_key)
                if p == 'gemini':
                    return decrypt_secret(cred.gemini_key_fallback) or decrypt_secret(cred.gemini_key)
            else:
                if p == 'openai':
                    return decrypt_secret(cred.openai_key)
                if p == 'zai':
                    return decrypt_secret(cred.zai_key)
                if p == 'perplexity':
                    return decrypt_secret(cred.perplexity_key)
                if p == 'gemini':
                    return decrypt_secret(cred.gemini_key)
            return None

        if is_fallback_attempt:
            provider = user_ai_settings.get('ai_provider_fallback') or 'openai'
            model = user_ai_settings.get('ai_model_fallback') or model
            if not model:
                defaults = {'openai': 'gpt-5', 'zai': 'glm-4.7-flash', 'perplexity': 'sonar-pro', 'gemini': 'gemini-3.5-flash'}
                model = defaults.get(provider, 'gpt-5')
            ai_reasoning_level = (user_ai_settings.get('ai_reasoning_level_fallback') or 'medium').lower()
            logger.info(f"⚠️ USING FALLBACK AI PROVIDER: {provider} / {model} (reasoning: {ai_reasoning_level})")
        else:
            provider = user_ai_settings.get('ai_provider', 'openai')
            ai_reasoning_level = (user_ai_settings.get('ai_reasoning_level') or 'medium').lower()
            if not model:
                model = user_ai_settings.get('ai_model')
                if not model:
                    defaults = {'openai': 'gpt-5', 'zai': 'glm-4.7-flash', 'perplexity': 'sonar-pro', 'gemini': 'gemini-3.5-flash'}
                    model = defaults.get(provider, 'gpt-5')

        original_user_message = ""
        for msg in messages:
            if msg.get('role') == 'user':
                original_user_message = msg.get('content', '')
                break
        if not original_user_message and messages:
            original_user_message = messages[-1].get('content', '')

        # Get prompt templates
        ai_prompts = get_user_ai_prompts(user_id)
        current_datetime = format_eastern_datetime(None, "%Y-%m-%d %H:%M:%S EST")
        symbol_value = symbol if symbol else "CRYPTO"
        amount_value = str(amount) if amount is not None else "0"

        stage1_prompt_map = {
            'coin_analysis': getattr(ai_prompts, 'coin_analysis_pre', None),
            'market_analysis': getattr(ai_prompts, 'market_analysis_pre', None),
            'portfolio_review': getattr(ai_prompts, 'portfolio_review_pre', None),
            'sentiment_analysis': getattr(ai_prompts, 'sentiment_prompt_pre', None),
            'watchlist_sentiment_analysis': getattr(ai_prompts, 'watchlist_sentiment_prompt_pre', None),
            'copilot': getattr(ai_prompts, 'copilot_chat_pre', None) or user_ai_settings.get('copilot_chat_pre'),
            'manual': getattr(ai_prompts, 'copilot_chat_pre', None) or user_ai_settings.get('copilot_chat_pre'),
        }
        stage1_template = stage1_prompt_map.get(prompt_type)
        if not stage1_template:
            stage1_template = user_ai_settings.get('copilot_chat_pre') or "Analyze the query and list 1 or 2 targeted search queries."
        
        try:
            stage1_prompt = stage1_template.format(symbol=symbol_value, datetime=current_datetime, amount=amount_value)
        except Exception:
            stage1_prompt = stage1_template.replace('{symbol}', symbol_value).replace('{datetime}', current_datetime)

        stage1_messages = [
            {"role": "system", "content": stage1_prompt},
            {"role": "user", "content": original_user_message}
        ]

        def _execute_ai_call(p_messages, p_max_tokens=600):
            if provider == 'openai':
                key = _pick_key('openai')
                if not key:
                    raise ValueError("OpenAI API key not configured")
                from openai import OpenAI
                client = OpenAI(api_key=key, timeout=90.0)
                resp = client.chat.completions.create(
                    model=model,
                    messages=p_messages,
                    max_completion_tokens=p_max_tokens
                )
                return resp.choices[0].message.content

            elif provider == 'zai':
                key = _pick_key('zai')
                if not key:
                    raise ValueError("Z.AI API key not configured")
                from zai_client import ZAIClient
                client = ZAIClient(key)
                max_zai_retries = 2
                last_zai_error = ""
                for zai_attempt in range(max_zai_retries + 1):
                    resp = client.chat_completion(messages=p_messages, model=model, max_tokens=max(p_max_tokens, 1024), temperature=0.2)
                    if resp.get('success'):
                        return resp.get('content')
                    last_zai_error = resp.get('error', 'Unknown Z.AI error')
                    if zai_attempt < max_zai_retries and any(code in str(last_zai_error).lower() for code in ["429", "1305", "1302", "rate limit", "overloaded"]):
                        delay = 4 * (zai_attempt + 1)
                        logger.warning(f"Z.AI rate limit/overload (attempt {zai_attempt + 1}/{max_zai_retries}). Retrying in {delay}s...")
                        time.sleep(delay)
                    else:
                        break
                raise Exception(f"Z.AI error: {last_zai_error}")

            elif provider == 'perplexity':
                key = _pick_key('perplexity')
                if not key:
                    raise ValueError("Perplexity API key not configured")
                r = requests.post(
                    "https://api.perplexity.ai/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": p_messages, "max_tokens": p_max_tokens},
                    timeout=45
                )
                if r.status_code == 200:
                    return r.json()['choices'][0]['message']['content']
                raise Exception(f"Perplexity error: {r.text}")

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
                
                max_gemini_retries = 2
                for attempt in range(max_gemini_retries + 1):
                    last_err = ""
                    for api_ver in ['v1beta', 'v1']:
                        url = f"https://generativelanguage.googleapis.com/{api_ver}/models/{model}:generateContent?key={key}"
                        try:
                            r = requests.post(url, json=req_json, timeout=60)
                            if r.status_code == 200:
                                res_json = r.json()
                                try:
                                    return res_json['candidates'][0]['content']['parts'][0]['text']
                                except Exception:
                                    return json.dumps(res_json)
                            elif r.status_code == 400 and "thinkingConfig" in gen_config:
                                # Retry without thinkingConfig in case model does not support it
                                req_json["generationConfig"] = {"maxOutputTokens": p_max_tokens}
                                r_retry = requests.post(url, json=req_json, timeout=60)
                                if r_retry.status_code == 200:
                                    res_json = r_retry.json()
                                    try:
                                        return res_json['candidates'][0]['content']['parts'][0]['text']
                                    except Exception:
                                        return json.dumps(res_json)
                                last_err = r_retry.text
                            elif r.status_code in [429, 503] or "RESOURCE_EXHAUSTED" in r.text or "UNAVAILABLE" in r.text:
                                last_err = r.text
                                break  # Break version loop to trigger retry delay
                            else:
                                last_err = r.text
                        except Exception as req_ex:
                            last_err = str(req_ex)

                    is_retryable = any(k in last_err for k in ["429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "high demand"])
                    if attempt < max_gemini_retries and is_retryable:
                        delay = 6 * (attempt + 1)
                        # Try parsing retryDelay from error JSON
                        try:
                            delay_match = re.search(r'retryDelay["\']:\s*["\'](\d+)s', last_err)
                            if delay_match:
                                delay = min(int(delay_match.group(1)) + 1, 30)
                        except Exception:
                            pass
                        logger.warning(f"Gemini {r.status_code if 'r' in locals() else 'API'} transient issue (attempt {attempt + 1}/{max_gemini_retries}). Backing off for {delay}s...")
                        time.sleep(delay)
                        continue
                    elif not is_retryable:
                        break

                raise Exception(f"Gemini API error: {last_err}")
            
            else:
                raise ValueError(f"Unsupported AI provider: {provider}")

        # Stage 1: Queries
        if prompt_type == 'sentiment_analysis':
            # Optimize: Avoid burning a precious Gemini RPM quota just to formulate a search query
            search_queries = [f"{symbol_value} cryptocurrency news market price sentiment today"]
        else:
            try:
                search_queries_text = _execute_ai_call(stage1_messages, p_max_tokens=300)
                search_queries = [q.strip().strip('-*0123456789. ') for q in (search_queries_text or '').split('\n') if q.strip()][:2]
            except Exception as e:
                logger.warning(f"Stage 1 query generation error: {e}. Using fallback query.")
                search_queries = [f"{symbol_value} crypto news market analysis today"]

        # Stage 2: Web Searches
        search_summaries = []
        for q in search_queries:
            if not q: continue
            results = web_search(q, max_results=2, username=username)
            for item in results:
                search_summaries.append(f"- {item.get('title')}: {item.get('snippet')} ({item.get('url')})")
        
        search_text = "\n".join(search_summaries) if search_summaries else "No recent search results found."

        # Stage 3: Synthesis
        stage3_prompt_map = {
            'coin_analysis': getattr(ai_prompts, 'coin_analysis_post', None),
            'market_analysis': getattr(ai_prompts, 'market_analysis_post', None),
            'portfolio_review': getattr(ai_prompts, 'portfolio_review_post', None),
            'sentiment_analysis': getattr(ai_prompts, 'sentiment_prompt_post', None),
            'watchlist_sentiment_analysis': getattr(ai_prompts, 'watchlist_sentiment_prompt_post', None),
            'copilot': getattr(ai_prompts, 'copilot_chat_post', None) or user_ai_settings.get('copilot_chat_post'),
            'manual': getattr(ai_prompts, 'copilot_chat_post', None) or user_ai_settings.get('copilot_chat_post'),
        }
        stage3_template = stage3_prompt_map.get(prompt_type)
        if not stage3_template:
            stage3_template = user_ai_settings.get('copilot_chat_post') or "Synthesize the analysis and recent market data into a clear summary."
        
        try:
            stage3_system = stage3_template.format(symbol=symbol_value, datetime=current_datetime, amount=amount_value)
        except Exception:
            stage3_system = stage3_template.replace('{symbol}', symbol_value).replace('{datetime}', current_datetime)

        stage3_user_msg = f"{original_user_message}\n\n=== RECENT WEB SEARCH RESULTS ===\n{search_text}"

        stage3_messages = [
            {"role": "system", "content": stage3_system},
            {"role": "user", "content": stage3_user_msg}
        ]

        final_content = _execute_ai_call(stage3_messages, p_max_tokens=max_tokens)
        return AIResponseWrapper(final_content), stage3_user_msg

    except Exception as e:
        logger.error(f"Error in call_ai_with_web_search: {e}")
        if not is_fallback_attempt and user_ai_settings.get('ai_provider_fallback'):
            logger.info("Attempting AI fallback provider...")
            return call_ai_with_web_search(
                username=username,
                messages=messages,
                model=None,
                user_id=user_id,
                prompt_type=prompt_type,
                symbol=symbol,
                include_db_context=include_db_context,
                amount=amount,
                is_fallback_attempt=True
            )
        raise

def log_ai_conversation(user_id, prompt_type, sender, body, symbol=None, coin_id=None):
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
            created_at=now
        )
        db.session.add(conv)
        db.session.commit()
    except Exception as e:
        logger.error(f"Error logging AI conversation: {e}")
        db.session.rollback()

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
        sentiment_request = (
            f"{'WATCHLIST_' if is_watchlist else ''}SENTIMENT_ANALYSIS_DATA\n"
            f"symbol: {symbol}\n"
            f"amount: {amount}\n"
            f"datetime: {current_datetime}\n"
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
            amount=amount
        )

        sentiment_text = ""
        if hasattr(response, 'choices') and response.choices:
            sentiment_text = response.choices[0].message.content.strip()
        elif isinstance(response, dict) and 'content' in response:
            sentiment_text = response['content'].strip()
        else:
            sentiment_text = str(response).strip()

        sentiment_result, sentiment_reason = parse_sentiment_json(sentiment_text, is_watchlist=is_watchlist)

        # Update database
        resolved_coin_id = coin_id
        if is_watchlist:
            wl_row = WatchlistCoin.query.filter_by(user_id=user_id, symbol=symbol).first()
            if wl_row:
                wl_row.sentiment = sentiment_result
                wl_row.sentiment_reason = sentiment_reason
                if hasattr(wl_row, 'sentiment_last_updated'):
                    wl_row.sentiment_last_updated = datetime.utcnow()
                db.session.commit()
                resolved_coin_id = wl_row.id
        else:
            coin_row = Coin.query.filter_by(user_id=user_id, symbol=symbol).first()
            if coin_row:
                coin_row.sentiment = sentiment_result
                coin_row.sentiment_reason = sentiment_reason
                coin_row.sentiment_last_updated = datetime.utcnow()
                db.session.commit()
                resolved_coin_id = coin_row.id

        log_ai_conversation(user_id, prompt_type, "user", actual_stage3_prompt, symbol=symbol, coin_id=resolved_coin_id)
        time.sleep(0.1)
        log_ai_conversation(user_id, prompt_type, "ai", sentiment_text, symbol=symbol, coin_id=resolved_coin_id)

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

def run_sentiment_analysis_for_user(user_id, username, force=False):
    """
    Run sentiment analysis for a user's portfolio coins.
    Parses JSON output for phrase ('Hold', 'Buy Immediately', 'Consider Buying', 'Sell Immediately', 'Consider Selling')
    and 1-2 sentence explanation stored as sentiment_reason.
    """
    with _running_sentiment_lock:
        if user_id in _running_sentiment_users:
            logger.info(f"Sentiment analysis already in progress for user {username} (ID: {user_id}), skipping duplicate trigger.")
            return 0
        _running_sentiment_users.add(user_id)

    count = 0
    try:
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

        sentiment_freq_hours = settings.get('sentiment_analysis_frequency_hours', 24)
        try:
            sentiment_freq_hours = float(sentiment_freq_hours)
        except Exception:
            sentiment_freq_hours = 24.0

        coins = Coin.query.filter_by(user_id=user_id, hidden=False).filter(Coin.amount > 0).all()
        if not coins:
            logger.info(f"No portfolio coins found for sentiment analysis for user {username}")
            return 0

        logger.info(f"Running portfolio sentiment analysis for {len(coins)} coins (User: {username}, Force: {force})")

        for coin_row in coins:
            coin_id = coin_row.id
            symbol = coin_row.symbol
            amount = coin_row.amount
            last_updated = coin_row.sentiment_last_updated

            if is_stablecoin(symbol):
                logger.info(f"Skipping sentiment analysis for stablecoin {symbol} (marking Hold)")
                coin_row.sentiment = "Hold"
                coin_row.sentiment_reason = "Dollar-pegged stablecoin for capital preservation."
                coin_row.sentiment_last_updated = datetime.utcnow()
                db.session.commit()
                continue

            if not force and last_updated:
                now_utc = datetime.now(timezone.utc)
                last_utc = last_updated if last_updated.tzinfo else last_updated.replace(tzinfo=timezone.utc)
                elapsed_hours = (now_utc - last_utc).total_seconds() / 3600.0
                if elapsed_hours < sentiment_freq_hours:
                    continue

            logger.info(f"Analyzing portfolio sentiment for {symbol} (User: {username})...")
            
            try:
                analyze_single_symbol_sentiment(
                    user_id=user_id,
                    username=username,
                    symbol=symbol,
                    is_watchlist=False,
                    coin_id=coin_id,
                    amount=amount
                )
                count += 1
                # Pacing delay between coins to prevent hitting LLM API rate limits
                time.sleep(8)

            except Exception as coin_error:
                logger.error(f"Error processing portfolio sentiment for {symbol}: {coin_error}")
                # Extra backoff if error was due to rate limits
                if any(k in str(coin_error).lower() for k in ["429", "rate limit", "resource_exhausted", "overloaded", "1302", "1305"]):
                    logger.warning(f"Rate limit detected for {symbol}, cooling down for 15s before next coin...")
                    time.sleep(15)
                else:
                    time.sleep(8)

        return count

    except Exception as e:
        logger.error(f"Error in run_sentiment_analysis_for_user for {username}: {e}")
        return count
    finally:
        with _running_sentiment_lock:
            _running_sentiment_users.discard(user_id)

def run_watchlist_sentiment_analysis_for_user(user_id, username, force=False):
    """
    Run sentiment analysis for a user's watchlist coins.
    Parses JSON output for phrase ('Avoid', 'Watch', 'Consider Buying', 'Definitely Buy')
    and 1-2 sentence explanation stored as sentiment_reason.
    """
    with _running_sentiment_lock:
        if user_id in _running_sentiment_users:
            logger.info(f"Sentiment analysis already in progress for user {username} (ID: {user_id}), skipping duplicate trigger.")
            return 0
        _running_sentiment_users.add(user_id)

    count = 0
    try:
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

        wl_freq_hours = settings.get('watchlist_sentiment_analysis_frequency_hours', 24)
        try:
            wl_freq_hours = float(wl_freq_hours)
        except Exception:
            wl_freq_hours = 24.0

        wl_coins = WatchlistCoin.query.filter_by(user_id=user_id).all()
        if not wl_coins:
            logger.info(f"No watchlist coins found for sentiment analysis for user {username}")
            return 0

        logger.info(f"Running watchlist sentiment analysis for {len(wl_coins)} coins (User: {username}, Force: {force})")

        for wl_row in wl_coins:
            coin_id = wl_row.id
            symbol = wl_row.symbol
            last_updated = getattr(wl_row, 'sentiment_last_updated', None)

            if is_stablecoin(symbol):
                logger.info(f"Skipping sentiment analysis for watchlist stablecoin {symbol} (marking Watch)")
                wl_row.sentiment = "Watch"
                wl_row.sentiment_reason = "Dollar-pegged stablecoin for capital preservation."
                if hasattr(wl_row, 'sentiment_last_updated'):
                    wl_row.sentiment_last_updated = datetime.utcnow()
                db.session.commit()
                continue

            if not force and last_updated:
                now_utc = datetime.now(timezone.utc)
                last_utc = last_updated if last_updated.tzinfo else last_updated.replace(tzinfo=timezone.utc)
                elapsed_hours = (now_utc - last_utc).total_seconds() / 3600.0
                if elapsed_hours < wl_freq_hours:
                    continue

            logger.info(f"Analyzing watchlist sentiment for {symbol} (User: {username})...")
            
            try:
                analyze_single_symbol_sentiment(
                    user_id=user_id,
                    username=username,
                    symbol=symbol,
                    is_watchlist=True,
                    coin_id=coin_id,
                    amount=0.0
                )
                count += 1
                # Pacing delay between coins to prevent hitting LLM API rate limits
                time.sleep(8)

            except Exception as coin_error:
                logger.error(f"Error processing watchlist sentiment for {symbol}: {coin_error}")
                # Extra backoff if error was due to rate limits
                if any(k in str(coin_error).lower() for k in ["429", "rate limit", "resource_exhausted", "overloaded", "1302", "1305"]):
                    logger.warning(f"Rate limit detected for {symbol}, cooling down for 15s before next coin...")
                    time.sleep(15)
                else:
                    time.sleep(8)

        return count

    except Exception as e:
        logger.error(f"Error in run_watchlist_sentiment_analysis_for_user for {username}: {e}")
        return count
    finally:
        with _running_sentiment_lock:
            _running_sentiment_users.discard(user_id)

