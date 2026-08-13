import os
import re
import json
import time
import logging
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
from routes.helpers import decrypt_secret

logger = logging.getLogger(__name__)

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
                brave_api_key = decrypt_secret(getattr(cred, '_brave_key', None))
                brave_api_key_fallback = decrypt_secret(getattr(cred, 'brave_key_fallback', None))
                
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
    for retry in range(2):
        try:
            from bs4 import BeautifulSoup
            search_url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            resp = requests.get(search_url, headers=headers, timeout=10)
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
            logger.warning(f"DuckDuckGo fallback attempt {retry + 1} failed: {e}")
            time.sleep(1)

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
        ai_reasoning_level = (user_ai_settings.get('ai_reasoning_level') or 'medium').lower()

        cred = get_user_credentials(username)
        if not cred:
            raise ValueError(f"No credentials found for user: {username}")
        
        def _pick_key(p):
            if p == 'openai':
                return decrypt_secret(cred.openai_key_fallback) or decrypt_secret(cred._openai_key)
            if p == 'zai':
                return decrypt_secret(cred.zai_key_fallback) or decrypt_secret(cred._zai_key)
            if p == 'perplexity':
                return decrypt_secret(cred.perplexity_key_fallback) or decrypt_secret(cred._perplexity_key)
            if p == 'gemini':
                return decrypt_secret(cred.gemini_key_fallback) or decrypt_secret(cred._gemini_key)
            return None

        if is_fallback_attempt:
            provider = user_ai_settings.get('ai_provider_fallback') or 'openai'
            model = user_ai_settings.get('ai_model_fallback') or model or 'gpt-5'
            logger.info(f"⚠️ USING FALLBACK AI PROVIDER: {provider} / {model}")
        else:
            provider = user_ai_settings.get('ai_provider', 'openai')
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
                resp = client.chat_completion(messages=p_messages, model=model, max_tokens=p_max_tokens, temperature=0.2)
                if resp.get('success'):
                    return resp.get('content')
                raise Exception(f"Z.AI error: {resp.get('error')}")

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
                            elif r.status_code == 429 or "RESOURCE_EXHAUSTED" in r.text:
                                last_err = r.text
                                break  # Break version loop to trigger retry delay
                            else:
                                last_err = r.text
                        except Exception as req_ex:
                            last_err = str(req_ex)

                    if attempt < max_gemini_retries and ("429" in last_err or "RESOURCE_EXHAUSTED" in last_err):
                        delay = 12 * (attempt + 1)
                        # Try parsing retryDelay from error JSON
                        try:
                            delay_match = re.search(r'retryDelay["\']:\s*["\'](\d+)s', last_err)
                            if delay_match:
                                delay = min(int(delay_match.group(1)) + 1, 30)
                        except Exception:
                            pass
                        logger.warning(f"Gemini 429 Rate Limit (attempt {attempt + 1}/{max_gemini_retries}). Backing off for {delay}s...")
                        time.sleep(delay)
                        continue
                    elif "429" not in last_err and "RESOURCE_EXHAUSTED" not in last_err:
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

def parse_sentiment_json(response_text):
    """
    Parse the AI JSON output for Item 1 (phrase) and Item 2 (reason).
    Valid phrases: 'Hold', 'Buy Immediately', 'Consider Buying', 'Sell Immediately', 'Consider Selling'
    """
    VALID_PHRASES = {
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
    
    phrase = None
    reason = None
    
    clean_text = (response_text or '').strip()
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
                        if v_str.lower() in VALID_PHRASES:
                            phrase = VALID_PHRASES[v_str.lower()]
                    elif any(x in k_lower for x in ['item 2', 'item2', 'reason', 'explanation', 'description', 'summary', 'item_2']):
                        reason = v_str
                
                # If phrase not identified by key name, check dictionary values
                if not phrase:
                    for v in parsed.values():
                        if str(v).strip().lower() in VALID_PHRASES:
                            phrase = VALID_PHRASES[str(v).strip().lower()]
                            break
                if not reason:
                    for k, v in parsed.items():
                        if str(v).strip() != phrase and len(str(v).strip()) > 5:
                            reason = str(v).strip()
                            break
                            
            elif isinstance(parsed, list) and len(parsed) >= 2:
                p_cand = str(parsed[0]).strip()
                if p_cand.lower() in VALID_PHRASES:
                    phrase = VALID_PHRASES[p_cand.lower()]
                reason = str(parsed[1]).strip()
        except Exception as e:
            logger.warning(f"JSON sentiment decode error: {e}")
            
    # Fallback pattern search if structured JSON parse was incomplete
    if not phrase:
        for p_key in ['buy immediately', 'consider buying', 'sell immediately', 'consider selling', 'hold', 'strong buy', 'strong sell', 'buy', 'sell']:
            if re.search(r'\b' + re.escape(p_key) + r'\b', clean_text, re.IGNORECASE):
                phrase = VALID_PHRASES[p_key]
                break
                
    if not reason and phrase:
        remainder = re.sub(re.escape(phrase), '', clean_text, flags=re.IGNORECASE)
        remainder = re.sub(r'[\{\}\[\]"\':`]', ' ', remainder).strip()
        remainder = re.sub(r'\s+', ' ', remainder).strip()
        if len(remainder) > 5:
            reason = remainder
            
    return phrase or "Hold", reason or ""


def run_sentiment_analysis_for_user(user_id, username, force=False):
    """
    Run sentiment analysis for a user's portfolio coins.
    Parses JSON output for phrase ('Hold', 'Buy Immediately', 'Consider Buying', 'Sell Immediately', 'Consider Selling')
    and 1-2 sentence explanation stored as sentiment_reason.
    """
    count = 0
    try:
        if not is_ai_enabled(username) and not force:
            logger.info(f"Skipping sentiment analysis for {username} - AI disabled")
            return 0
        
        settings = get_user_ai_settings(username)
        if not force:
            start_str = settings.get('ai_analysis_window_start', '08:00')
            end_str = settings.get('ai_analysis_window_end', '23:59')
            if not is_user_analysis_window_active(start_str, end_str):
                logger.info(f"Skipping sentiment analysis for {username} - outside analysis window")
                return 0

        sentiment_freq_hours = settings.get('sentiment_analysis_frequency_hours', 24)
        try:
            sentiment_freq_hours = float(sentiment_freq_hours)
        except Exception:
            sentiment_freq_hours = 24.0

        threshold_raw = settings.get('ai_confidence_threshold', 70)
        try:
            confidence_threshold = float(threshold_raw)
            if confidence_threshold < 1:
                confidence_threshold *= 100
        except Exception:
            confidence_threshold = 70.0
        
        notifications_enabled = settings.get('ai_notifications_enabled', True)
        
        coins = Coin.query.filter_by(user_id=user_id, hidden=False).filter(Coin.amount > 0).all()
        if not coins:
            logger.info(f"No portfolio coins found for sentiment analysis for user {username}")
            return 0

        logger.info(f"Running sentiment analysis for {len(coins)} coins (User: {username}, Force: {force})")

        for coin_row in coins:
            coin_id = coin_row.id
            symbol = coin_row.symbol
            amount = coin_row.amount
            last_updated = coin_row.sentiment_last_updated

            if not force and last_updated:
                # Calculate elapsed time in UTC
                now_utc = datetime.now(timezone.utc)
                last_utc = last_updated if last_updated.tzinfo else last_updated.replace(tzinfo=timezone.utc)
                elapsed_hours = (now_utc - last_utc).total_seconds() / 3600.0
                if elapsed_hours < sentiment_freq_hours:
                    continue

            logger.info(f"Analyzing sentiment for {symbol} (User: {username})...")
            
            try:
                ai_prompts_obj = get_user_ai_prompts(user_id)
                sentiment_pre_prompt = (getattr(ai_prompts_obj, 'sentiment_prompt_pre', None) or "").strip()
                sentiment_post_prompt = (getattr(ai_prompts_obj, 'sentiment_prompt_post', None) or "").strip()
                
                if not sentiment_pre_prompt or not sentiment_post_prompt:
                    logger.warning(f"Missing sentiment prompts for user {username}. Marking Error.")
                    coin_row.sentiment = "Error"
                    coin_row.sentiment_reason = "Missing sentiment prompt configuration in Settings."
                    coin_row.sentiment_last_updated = datetime.utcnow()
                    db.session.commit()
                    continue

                current_datetime = format_eastern_datetime(None, "%B %d, %Y at %I:%M %p EDT")

                sentiment_request = (
                    "SENTIMENT_ANALYSIS_DATA\n"
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
                    prompt_type="sentiment_analysis",
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

                # Parse JSON output for Action phrase and Explanation reason
                sentiment_result, sentiment_reason = parse_sentiment_json(sentiment_text)

                # Update database
                coin_row.sentiment = sentiment_result
                coin_row.sentiment_reason = sentiment_reason
                coin_row.sentiment_last_updated = datetime.utcnow()
                db.session.commit()
                count += 1

                log_ai_conversation(user_id, "sentiment_analysis", "user", actual_stage3_prompt, symbol=symbol, coin_id=coin_id)
                time.sleep(0.1)
                log_ai_conversation(user_id, "sentiment_analysis", "ai", sentiment_text, symbol=symbol, coin_id=coin_id)

                # Send Telegram alert if buy/sell signal
                if notifications_enabled and sentiment_result in ['Buy Immediately', 'Consider Buying', 'Sell Immediately', 'Consider Selling']:
                    alert_msg = (
                        f"🚀 AI TRADING SIGNAL: {symbol}\n"
                        f"Signal: {sentiment_result.upper()}\n"
                        f"Reason: {sentiment_reason}\n"
                        f"Time: {current_datetime}"
                    )
                    send_telegram_message(username, alert_msg)
                    logger.info(f"Sent AI Trading Alert for {symbol} ({sentiment_result})")

                time.sleep(6)

            except Exception as coin_error:
                logger.error(f"Error processing sentiment for {symbol}: {coin_error}")
                try:
                    coin_row.sentiment = "Error"
                    coin_row.sentiment_reason = f"Analysis error: {str(coin_error)}"
                    coin_row.sentiment_last_updated = datetime.utcnow()
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                time.sleep(6)

        return count

    except Exception as e:
        logger.error(f"Error in run_sentiment_analysis_for_user for {username}: {e}")
        return count
