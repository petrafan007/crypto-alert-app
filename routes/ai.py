import json
import datetime
from datetime import timedelta
import time

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user

# Database & Models
from core.extensions import db
from models import AIPrompt, AIConversation
from credentials import User, Credential, UserSetting

# AI Clients
try:
    import google.generativeai as genai  # optional; app uses REST API directly
except ImportError:
    genai = None

# Log
from log import logger

# Import helpers from main (to be refactored later into services)
from main import (
    serve_react_app,
    decrypt_secret,
    format_eastern_datetime, get_ai_cache, get_comprehensive_crypto_data_for_user,
    get_eastern_now, get_user_ai_prompts, get_user_ai_settings,
    get_user_credentials, is_ai_enabled, is_user_analysis_window_active,
    log_ai_communication, run_sentiment_analysis_for_user, set_ai_cache,
    ALLOWED_WORKFLOW_TYPES, _get_latest_conversation_row,
    basic_portfolio_analysis, basic_recommendation_analysis, calculate_symbol_snapshot,
    calculate_volatility, call_ai_with_web_search, extract_confidence,
    extract_key_insights, extract_risk_level, extract_sentiment, fetch_news_sentiment,
    format_eastern_datetime_ampm, generate_conversation_id, generate_smart_alerts_for_user,
    get_ai_conversations, get_ai_conversations_count, get_coin_id_by_symbol,
    get_eastern_datetime, get_eastern_now_iso, get_last_7d_prices, is_analysis_window_active,
    is_stablecoin, log_ai_conversation, parse_ai_recommendation, parse_portfolio_analysis,
    process_ai_conversation, score_recommendation, should_run_ai_analysis,
    update_ai_analysis_schedule
)
import threading
import numpy as np

# Blueprint Definition
ai_bp = Blueprint('ai', __name__)


# --- AI Provider Connection Test Endpoints ---
@ai_bp.route('/api/test-openai-connection', methods=['POST', 'GET'])
@login_required
def test_openai_connection():
    try:
        from flask import request
        payload = request.get_json(silent=True) or {}
        username = current_user.username
        ai_settings = get_user_ai_settings(username)
        # Sanitize model to OpenAI-supported list only
        openai_models = {
            'gpt-5', 'gpt-5-mini', 'gpt-5-nano',
            'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano',
            'o4-mini', 'o3', 'o3-mini'
        }
        requested_model = payload.get('model')
        model = requested_model if requested_model in openai_models else 'gpt-5'
        key = payload.get('openai_key')

        cred = get_user_credentials(username)
        openai_api_key = key if key else decrypt_secret(getattr(cred, '_openai_key', None))
        if not openai_api_key:
            return jsonify(success=False, message='OpenAI API key missing'), 400
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_api_key, timeout=20.0)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role":"user","content":"ping"}],
                max_completion_tokens=5
            )
            ok = bool(getattr(resp, 'choices', None))
            return jsonify(success=ok, message='OpenAI connection OK' if ok else 'OpenAI responded without choices')
        except Exception as e:
            return jsonify(success=False, message=f'OpenAI error: {e}'), 400
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@ai_bp.route('/api/test-zai-connection', methods=['POST', 'GET'])
@login_required
def test_zai_connection():
    try:
        from flask import request
        payload = request.get_json(silent=True) or {}
        username = current_user.username
        ai_settings = get_user_ai_settings(username)
        # Sanitize model to Z.AI-supported list only
        zai_models = {
            'glm-4.7', 'glm-4.7-flash', 'glm-4.7-flashx'
        }
        requested_model = payload.get('model')
        model = requested_model if requested_model in zai_models else 'glm-4.7-flash'
        key = payload.get('zai_key')

        cred = get_user_credentials(username)
        zai_api_key = key if key else decrypt_secret(getattr(cred, '_zai_key', None))
        if not zai_api_key:
            return jsonify(success=False, message='Z.AI API key missing'), 400
        try:
            from zai_client import ZAIClient
            client = ZAIClient(zai_api_key)
            resp = client.chat_completion(
                messages=[{"role":"user","content":"ping"}],
                model=model,
                max_tokens=5,
                temperature=0.0
            )
            ok = bool(resp) and resp.get('success')
            return jsonify(success=bool(ok), message='Z.AI connection OK' if ok else f"Z.AI error: {resp}")
        except Exception as e:
            return jsonify(success=False, message=f'Z.AI error: {e}'), 400
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@ai_bp.route('/api/test-perplexity-connection', methods=['POST'])
@login_required
def test_perplexity_connection():
    try:
        from flask import request
        import requests
        payload = request.get_json(silent=True) or {}
        username = current_user.username
        ai_settings = get_user_ai_settings(username)
        # Sanitize model to current Perplexity models
        allowed = {'sonar-pro', 'sonar', 'sonar-reasoning'}
        requested = payload.get('model')
        model = requested if requested in allowed else 'sonar-pro'
        key = payload.get('perplexity_key')

        cred = get_user_credentials(username)
        api_key = key if key else decrypt_secret(getattr(cred, '_perplexity_key', None))
        if not api_key:
            return jsonify(success=False, message='Perplexity API key missing'), 400
        for m in [model, 'sonar-pro', 'sonar', 'sonar-reasoning']:
            r = requests.post(
                'https://api.perplexity.ai/chat/completions',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'model': m, 'messages': [{"role":"user","content":"ping"}], 'max_tokens': 5},
                timeout=20
            )
            if r.status_code == 200:
                return jsonify(success=True, message=f'Perplexity connection OK (model {m})')
        return jsonify(success=False, message=f'Perplexity error: {r.text}'), 400
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@ai_bp.route('/api/test-gemini-connection', methods=['POST'])
@login_required
def test_gemini_connection():
    try:
        from flask import request
        import requests
        payload = request.get_json(silent=True) or {}
        username = current_user.username
        ai_settings = get_user_ai_settings(username)
        model = payload.get('model') or ai_settings.get('ai_model') or 'gemini-2.5-pro'
        key = payload.get('gemini_key')

        cred = get_user_credentials(username)
        api_key = key if key else decrypt_secret(getattr(cred, '_gemini_key', None))
        if not api_key:
            return jsonify(success=False, message='Gemini API key missing'), 400

        contents = [{"role":"user","parts":[{"text":"ping"}]}]
        for api_ver in ['v1beta', 'v1', 'v1alpha']:
            r = requests.post(
                f'https://generativelanguage.googleapis.com/{api_ver}/models/{model}:generateContent?key={api_key}',
                json={'contents': contents},
                timeout=20
            )
            if r.status_code == 200:
                return jsonify(success=True, message=f'Gemini connection OK ({api_ver})')
        # Enhance error message for quota/rate-limit responses
        try:
            err = r.json()
            code = err.get('error', {}).get('code')
            msg = err.get('error', {}).get('message')
            retry_delay = None
            for d in err.get('error', {}).get('details', []) or []:
                if d.get('@type', '').endswith('RetryInfo') and 'retryDelay' in d:
                    retry_delay = d.get('retryDelay')
                    break
            friendly = f"Gemini error (code {code}): {msg}"
            if retry_delay:
                friendly += f" | Suggested retry in {retry_delay}"
            return jsonify(success=False, message=friendly), 429 if code == 429 else 400
        except Exception:
            return jsonify(success=False, message=f'Gemini error: {r.text}'), 400
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500



@ai_bp.route('/api/test-ai-connection-generic', methods=['POST'])
@login_required
def test_ai_connection_generic():
    """Generic endpoint to test ANY AI provider with a specific key (useful for fallback testing)"""
    try:
        from flask import request
        import requests
        payload = request.get_json(silent=True) or {}
        provider = payload.get('provider')
        api_key = payload.get('api_key')
        model = payload.get('model')

        if not provider or not api_key:
            return jsonify(success=False, message='Provider and API key are required'), 400

        if provider == 'openai':
            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key, timeout=10.0)
                # Default to gpt-4o-mini for cheap testing if no model
                test_model = model or 'gpt-4o-mini'
                resp = client.chat.completions.create(
                    model=test_model,
                    messages=[{"role":"user","content":"ping"}],
                    max_completion_tokens=5
                )
                return jsonify(success=True, message=f'OpenAI connection OK ({test_model})')
            except Exception as e:
                return jsonify(success=False, message=f'OpenAI error: {e}'), 400

        elif provider == 'zai':
            try:
                from zai_client import ZAIClient
                client = ZAIClient(api_key)
                test_model = model or 'glm-4.7-flash'
                resp = client.chat_completion(
                    messages=[{"role":"user","content":"ping"}],
                    model=test_model,
                    max_tokens=5
                )
                if resp.get('success'):
                    return jsonify(success=True, message=f'Z.AI connection OK ({test_model})')
                else:
                    return jsonify(success=False, message=f"Z.AI error: {resp.get('error')}"), 400
            except Exception as e:
                return jsonify(success=False, message=f'Z.AI error: {e}'), 400

        elif provider == 'perplexity':
            try:
                test_model = model or 'sonar'
                # Perplexity supported models
                allowed = {'sonar-pro', 'sonar', 'sonar-reasoning', 'llama-3.1-sonar-small-128k-online', 'llama-3.1-sonar-large-128k-online', 'llama-3.1-sonar-huge-128k-online'}
                # Basic validation, but let's be lenient
                r = requests.post(
                    'https://api.perplexity.ai/chat/completions',
                    headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                    json={'model': test_model, 'messages': [{"role":"user","content":"ping"}], 'max_tokens': 5},
                    timeout=20
                )
                if r.status_code == 200:
                    return jsonify(success=True, message=f'Perplexity connection OK ({test_model})')
                return jsonify(success=False, message=f'Perplexity error: {r.text}'), 400
            except Exception as e:
                return jsonify(success=False, message=f'Perplexity error: {e}'), 400

        elif provider == 'gemini':
            try:
                test_model = model or 'gemini-1.5-flash'
                # Simple generateContent test
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{test_model}:generateContent?key={api_key}"
                r = requests.post(
                    url,
                    headers={'Content-Type': 'application/json'},
                    json={"contents": [{"parts": [{"text": "ping"}]}]},
                    timeout=20
                )
                if r.status_code == 200:
                    return jsonify(success=True, message=f'Gemini connection OK ({test_model})')
                return jsonify(success=False, message=f'Gemini error: {r.text}'), 400
            except Exception as e:
                return jsonify(success=False, message=f'Gemini error: {e}'), 400

        else:
            return jsonify(success=False, message=f'Unsupported provider: {provider}'), 400

    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


# View Prompt endpoints — return latest Stage 3 (user) prompt per section
@ai_bp.route('/api/ai/market-analysis-workflow-prompt', methods=['GET'])
@login_required
def api_market_analysis_workflow_prompt():
    row = _get_latest_conversation_row(current_user.id, 'market_analysis', 'user')
    if not row:
        return jsonify({
            'error': 'not_found',
            'message': 'No saved Market Analysis prompt found for current user. Run the workflow first.'
        }), 404
    return jsonify(row)


@ai_bp.route('/api/ai/risk-assessment-workflow-prompt', methods=['GET'])
@login_required
def api_risk_assessment_workflow_prompt():
    row = _get_latest_conversation_row(current_user.id, 'risk_assessment', 'user')
    if not row:
        return jsonify({
            'error': 'not_found',
            'message': 'No saved Risk Assessment prompt found for current user. Run the workflow first.'
        }), 404
    return jsonify(row)


@ai_bp.route('/api/ai/portfolio-review-workflow-prompt', methods=['GET'])
@login_required
def api_portfolio_review_workflow_prompt():
    row = _get_latest_conversation_row(current_user.id, 'portfolio_review', 'user')
    if not row:
        return jsonify({
            'error': 'not_found',
            'message': 'No saved Portfolio Review prompt found for current user. Run the workflow first.'
        }), 404
    return jsonify(row)


# Latest AI result per section — for dashboard rehydration after reload
@ai_bp.route('/api/ai/workflow-latest', methods=['GET'])
@login_required
def api_ai_workflow_latest():
    # type must be one of market_analysis|risk_assessment|portfolio_review
    t = (request.args.get('type') or '').strip().lower().replace('-', '_')
    if t not in ALLOWED_WORKFLOW_TYPES:
        return jsonify({'error': 'invalid_type', 'allowed': list(ALLOWED_WORKFLOW_TYPES)}), 400
    row = _get_latest_conversation_row(current_user.id, t, 'ai')
    if not row:
        return jsonify({'error': 'not_found', 'message': f'No AI result found for {t}. Run the workflow.'}), 404
    return jsonify(row)


@ai_bp.route('/api/force-sentiment-analysis', methods=['POST'])
@login_required
def force_sentiment_analysis():
    """Force run sentiment analysis for current user"""
    try:
        # Run in a separate thread so valid response returns immediately
        def run_async():
            with current_app.app_context():
                run_sentiment_analysis_for_user(current_user.id, current_user.username, force=True)
        
        thread = threading.Thread(target=run_async)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Sentiment analysis started in background'
        })
    except Exception as e:
        logger.error(f"Force analysis failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@ai_bp.route("/ai-dashboard")
@login_required
def ai_dashboard_page():
    """Serve the AI dashboard page (legacy route)"""
    return serve_react_app()


@ai_bp.route("/ai-analysis")
@login_required
def ai_analysis_page():
    """Serve the AI Analysis page (new route)"""
    return serve_react_app()


@ai_bp.route("/api/ai/settings", methods=["GET", "POST"])
@login_required
def api_ai_settings():
    """Handle AI settings GET and POST requests"""
    try:
        # Get the current user
        username = current_user.username
        if not username:
            return jsonify({"error": "User not authenticated"}), 401
        
        if request.method == "GET":
            # Return AI settings
            logger.error(f"=== DEBUG: api_ai_settings GET called for user: {username} ===")
            ai_settings = get_user_ai_settings(username)
            logger.error(f"=== DEBUG: Base AI settings loaded ===")
            
            # Get user object to get user_id for AI prompts
            logger.error(f"=== DEBUG: Querying User with username: {username} ===")
            user_obj = User.query.filter_by(username=username).first()
            logger.error(f"=== DEBUG: User query result: {user_obj is not None} ===")
            logger.error(f"=== DEBUG: User object found: {user_obj is not None} ===")
            if user_obj:
                logger.error(f"=== DEBUG: User ID: {user_obj.id} ===")
                # Get AI prompts from database
                ai_prompts = get_user_ai_prompts(user_obj.id)
                logger.error(f"=== DEBUG: AI prompts found: {ai_prompts is not None} ===")
                if ai_prompts:
                    # Convert AI prompts to the format expected by frontend
                    ai_settings['ai_prompts'] = {
                        'market_analysis_pre': ai_prompts.market_analysis_pre or '',
                        'market_analysis_post': ai_prompts.market_analysis_post or '',
                        'risk_assessment_pre': ai_prompts.risk_assessment_pre or '',
                        'risk_assessment_post': ai_prompts.risk_assessment_post or '',
                        'portfolio_review_pre': ai_prompts.portfolio_review_pre or '',
                        'portfolio_review_post': ai_prompts.portfolio_review_post or '',
                        'coin_analysis_pre': ai_prompts.coin_analysis_pre or '',
                        'coin_analysis_post': ai_prompts.coin_analysis_post or '',
                        'sentiment_prompt_pre': ai_prompts.sentiment_prompt_pre or '',
                        'sentiment_prompt_post': ai_prompts.sentiment_prompt_post or ''
                    }
                    logger.error("=== DEBUG: AI prompts added to settings ===")
                else:
                    logger.error("=== DEBUG: No AI prompts found, using defaults ===")
            else:
                logger.error("=== DEBUG: User not found in database! ===")
            
            # Remove the old ai_custom_prompts if it exists
            if 'ai_custom_prompts' in ai_settings:
                del ai_settings['ai_custom_prompts']
                
            logger.error("=== DEBUG: Final AI settings response generated ===")
            return jsonify(ai_settings)
        
        elif request.method == "POST":
            # Save AI settings
            data = request.get_json()
            if not data:
                return jsonify({"error": "No data provided"}), 400
            
            # Update AI settings in database
            user_obj = User.query.filter_by(username=username).first()
            if not user_obj:
                return jsonify({"error": "User not found"}), 404

            cred = Credential.query.filter_by(user_id=user_obj.id).first()
            if not cred:
                cred = Credential(user_id=user_obj.id, username=username)
                db.session.add(cred)
            
            # Handle API keys separately
            if 'openai_key' in data:
                cred.openai_key = data.pop('openai_key')
            if 'zai_key' in data:
                cred.zai_key = data.pop('zai_key')
            if 'perplexity_key' in data:
                cred.perplexity_key = data.pop('perplexity_key')
            if 'gemini_key' in data:
                cred.gemini_key = data.pop('gemini_key')

            # Update each setting
            # Update UserSetting columns
            user_setting = UserSetting.query.filter_by(user_id=user_obj.id).first()
            if not user_setting:
                user_setting = UserSetting(user_id=user_obj.id)
                db.session.add(user_setting)
            
            # Map of allowed fields to update
            allowed_fields = [
                'ai_enabled', 'ai_provider', 'ai_model', 'ai_risk_tolerance',
                'ai_confidence_threshold', 'ai_notifications_enabled', 'ai_analysis_frequency',
                'ai_cache_duration_hours', 'ai_analysis_window_start', 'ai_analysis_window_end',
                'ai_max_tokens', 'ai_web_search_enabled', 'tax_manual_invested_updated', 
                'tax_cost_basis_method'
            ]

            for key, value in data.items():
                logger.error(f"=== DEBUG LOOP: checking key '{key}' against allowed list. In list? {key in allowed_fields} ===")
                if key == "ai_prompts" and isinstance(value, dict):
                    # Update AIPrompt fields for this user
                    ai_prompts = AIPrompt.query.filter_by(user_id=user_obj.id).first()
                    if not ai_prompts:
                        ai_prompts = AIPrompt(user_id=user_obj.id)
                        db.session.add(ai_prompts)
                    # Update all known prompt fields if present in payload
                    prompt_fields = [
                        'market_analysis_pre', 'market_analysis_post',
                        'risk_assessment_pre', 'risk_assessment_post',
                        'portfolio_review_pre', 'portfolio_review_post',
                        'coin_analysis_pre', 'coin_analysis_post',
                        'sentiment_prompt_pre', 'sentiment_prompt_post'
                    ]
                    for field in prompt_fields:
                        if field in value:
                            setattr(ai_prompts, field, value[field])
                    continue 

                # Explicit column updates
                if key in allowed_fields:
                    logger.error(f"=== DEBUG: Updating {key} to {value} ===")
                    # Handle type conversions if necessary (frontend sends JSON types, DB expects specific types)
                    # For boolean fields
                    if key in ['ai_enabled', 'ai_notifications_enabled', 'ai_web_search_enabled']:
                         setattr(user_setting, key, bool(value))
                    # For int fields
                    elif key in ['ai_cache_duration_hours', 'ai_max_tokens']:
                        try:
                            setattr(user_setting, key, int(value))
                        except:
                            pass
                    # For float fields
                    elif key in ['ai_confidence_threshold']:
                        try:
                            setattr(user_setting, key, float(value))
                        except:
                            pass
                    # For string fields
                    else:
                        setattr(user_setting, key, str(value))
            db.session.commit()
            return jsonify({"success": True, "message": "AI settings updated"})
            
    except Exception as e:
        logger.error(f"Error in AI settings endpoint: {e}")
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@ai_bp.route('/api/ai/models', methods=['GET'])
@login_required
def get_ai_models():
    # These are the hardcoded models from the settings validation logic
    openai_models = {
        'gpt-5', 'gpt-5-mini', 'gpt-5-nano', 'gpt-4.1', 'gpt-4.1-mini',
        'gpt-4.1-nano', 'o4-mini', 'o3', 'o3-mini',
    }
    zai_models = {
        'glm-4.7', 'glm-4.7-flash', 'glm-4.7-flashx',
    }
    perplexity_models = {
        'sonar-pro', 'sonar', 'sonar-reasoning',
    }
    gemini_models = {
        'gemini-3-flash-preview', 'gemini-3-pro-preview',
    }
    
    # Create a dictionary of labels for the models
    model_labels = {
        'gpt-5': 'GPT-5',
        'gpt-5-mini': 'GPT-5 Mini',
        'gpt-5-nano': 'GPT-5 Nano',
        'gpt-4.1': 'GPT-4.1',
        'gpt-4.1-mini': 'GPT-4.1 Mini',
        'gpt-4.1-nano': 'GPT-4.1 Nano',
        'o4-mini': 'o4 Mini',
        'o3': 'o3',
        'o3-mini': 'o3 Mini',
        'glm-4.7': 'GLM-4.7',
        'glm-4.7-flash': 'GLM-4.7 Flash',
        'glm-4.7-flashx': 'GLM-4.7 FlashX',
        'sonar-pro': 'Sonar Pro',
        'sonar': 'Sonar',
        'sonar-reasoning': 'Sonar Reasoning',
        'gemini-3-flash-preview': 'Gemini 3 Flash (preview)',
        'gemini-3-pro-preview': 'Gemini 3 Pro (preview)',
    }
    
    def get_model_options(models):
        return sorted([{'value': m, 'label': model_labels.get(m, m)} for m in models], key=lambda x: x['label'])

    return jsonify({
        'openai': get_model_options(openai_models),
        'zai': get_model_options(zai_models),
        'perplexity': get_model_options(perplexity_models),
        'gemini': get_model_options(gemini_models),
    })


@ai_bp.route("/api/test-binance-connection", methods=["GET", "POST"])
@login_required
def api_test_binance_connection():
    """Test Binance.US Portfolio API connection (production only, no testnet)"""
    try:
        # ALWAYS use production Binance.US - testnet is geo-restricted for US users
        api_key = None
        api_secret = None
        testnet = False  # Force production for US users
        
        # Check if keys provided in request body (for testing new keys)
        if request.method == 'POST':
            data = request.get_json() or {}
            api_key = data.get('api_key')
            api_secret = data.get('api_secret')
        
        # Fallback to credentials from database
        if not api_key or not api_secret:
            # Get credentials from credentials table
            creds = Credential.query.filter_by(user_id=current_user.id).first()
            
            if creds:
                api_key = decrypt_secret(creds.api_key)
                api_secret = decrypt_secret(creds.api_secret)
            
        if not api_key or not api_secret:
            return jsonify({
                "success": False,
                "message": "Binance API key and secret are required"
            }), 400
            
        # Import Binance client

        from binance.client import Client
        from binance.exceptions import BinanceAPIException
        
        # If we get a location restriction error, default to testnet and inform user
        location_restricted = False
        binance_type = "Binance"
        
        # Connect to Binance.US only (US users cannot use regular Binance)
        connection_attempts = []
        
        try:
            logger.info(f"Attempting Binance.US connection with testnet={testnet}")
            client = Client(
                api_key,
                api_secret,
                testnet=testnet,
                tld='us',
                requests_params={
                    'timeout': 15,  # Increased timeout
                }
            )
            binance_type = "Binance.US"
            account = client.get_account()
            logger.info("Binance.US connection successful")
            
        except BinanceAPIException as api_e:
            connection_attempts.append(f"Binance.US: {api_e.message}")
            logger.warning(f"Binance.US failed: {api_e.message}")
            
            return jsonify({
                "success": False,
                "message": "Binance.US connection failed",
                "details": f"API Error: {api_e.message}",
                "suggestion": "For US users: 1) Verify your Binance.US API keys are correct, 2) Ensure your Binance.US account is verified, 3) Check API permissions include 'Read Info'",
                "attempts": connection_attempts
            }), 400
                
        except Exception as e:
            connection_attempts.append(f"Binance.US: {str(e)}")
            logger.warning(f"Binance.US connection failed: {e}")
            
            return jsonify({
                "success": False,
                "message": "Binance.US connection failed",
                "details": f"Connection Error: {str(e)}",
                "suggestion": "For US users: 1) Verify your Binance.US API keys are correct, 2) Check your network connection, 3) Ensure your Binance.US account is verified",
                "attempts": connection_attempts
            }), 400
            
        # Get balances (filter out zero balances)
        balances = [
            {"asset": b['asset'], "free": b['free'], "locked": b['locked']}
            for b in account['balances'] 
            if float(b['free']) > 0 or float(b['locked']) > 0
        ]
        
        # Update last connection time
        try:
            user_obj = User.query.filter_by(username=current_user.username).first()
            if user_obj:
                user_obj.binance_connected = True
                user_obj.binance_connected_at = datetime.utcnow()
                db.session.commit()
        except Exception as e:
            logger.warning(f"Could not update connection timestamp: {e}")
        
        success_message = f"{binance_type} {'Testnet ' if testnet else ''}API connection successful"
        if location_restricted:
            success_message += " (automatically switched to testnet due to location restrictions)"
        
        return jsonify({
            "success": True,
            "message": success_message,
            "location_restricted": location_restricted,
            "using_testnet": testnet,
            "account": {
                "makerCommission": account.get('makerCommission'),
                "takerCommission": account.get('takerCommission'),
                "buyerCommission": account.get('buyerCommission'),
                "sellerCommission": account.get('sellerCommission'),
                "canTrade": account.get('canTrade'),
                "canWithdraw": account.get('canWithdraw'),
                "canDeposit": account.get('canDeposit'),
                "balances": balances
            }
        })
        
    except BinanceAPIException as e:
        logger.error(f"Binance API error: {e.message}")
        return jsonify({
            "success": False,
            "message": f"Binance API error: {e.message}",
            "code": e.code,
            "suggestion": "Check your API credentials and try enabling testnet mode"
        }), 400
        
    except Exception as e:
        logger.error(f"Binance connection test failed: {str(e)}")
        return jsonify({
            "success": False,
            "message": f"Connection test failed: {str(e)}",
            "suggestion": "Check your network connection and API credentials"
        }), 500


@ai_bp.route("/api/test-trading-connection", methods=["POST"])
@login_required
def api_test_trading_connection():
    """Test Binance.US Trading API connection"""
    try:
        data = request.get_json()
        trading_api_key = data.get('trading_api_key')
        trading_api_secret = data.get('trading_api_secret')
        
        if not trading_api_key or not trading_api_secret:
            return jsonify({
                "success": False,
                "message": "Trading API key and secret are required"
            }), 400
        
        # Import Binance client
        from binance.client import Client
        from binance.exceptions import BinanceAPIException
        
        try:
            logger.info(f"Testing Binance.US Trading API connection for user {current_user.username}")
            client = Client(
                trading_api_key,
                trading_api_secret,
                testnet=False,
                tld='us',
                requests_params={
                    'timeout': 15,
                }
            )
            
            # Test API connection and permissions
            account = client.get_account()
            
            # Check if trading is enabled
            can_trade = account.get('canTrade', False)
            
            if not can_trade:
                return jsonify({
                    "success": False,
                    "message": "Trading is not enabled for this API key. Please enable SPOT trading permissions."
                }), 400
            
            logger.info("Binance.US Trading API connection successful")
            
            return jsonify({
                "success": True,
                "message": "Trading API connection successful! SPOT trading is enabled.",
                "account": {
                    "canTrade": can_trade,
                    "canWithdraw": account.get('canWithdraw'),
                    "canDeposit": account.get('canDeposit')
                }
            })
            
        except BinanceAPIException as api_e:
            logger.warning(f"Binance.US Trading API failed: {api_e.message}")
            return jsonify({
                "success": False,
                "message": f"Binance.US API Error: {api_e.message}",
                "suggestion": "Verify your Trading API credentials are correct and have SPOT trading permissions"
            }), 400
            
    except Exception as e:
        logger.error(f"Trading connection test failed: {str(e)}")
        return jsonify({
            "success": False,
            "message": f"Connection test failed: {str(e)}",
            "suggestion": "Check your network connection and Trading API credentials"
        }), 500


@ai_bp.route("/api/test-openai-connection")
@login_required
def api_test_openai_connection():
    """Test OpenAI API connection with proper error detection"""
    try:
        # Get current user
        username = current_user.username
        user_id = current_user.id
        
        # Use the proper database access method
        cred = get_user_credentials(username)
            
        if not cred or not cred.openai_key:
            return jsonify({
                "success": False,
                "message": "No OpenAI API key configured"
            }), 400
        
        # Test OpenAI connection using the new client format
        try:
            from openai import OpenAI
            client = OpenAI(api_key=cred.openai_key)
            # Get user's preferred model for testing - this will apply normalization
            user_settings = get_user_ai_settings(username)
            test_model = user_settings.get('ai_model', 'gpt-5')
            
            # Prepare test message
            test_messages = [{"role": "user", "content": "Hello"}]
            
            # Log the request
            log_ai_communication("REQUEST", user_id, "openai", test_model, test_messages, prompt_type="connection_test", api_key=cred.openai_key)
            
            # Make the API call
            response = client.chat.completions.create(
                model=test_model,
                messages=test_messages,
                max_completion_tokens=5
            )
            
            # Log the successful response
            log_ai_communication("RESPONSE", user_id, "openai", test_model, test_messages, response=response, prompt_type="connection_test", api_key=cred.openai_key)
            
            return jsonify({
                "success": True,
                "message": "OpenAI connection successful - API key is valid"
            })
            
        except ImportError:
            log_ai_communication("RESPONSE", user_id, "openai", test_model, test_messages, error=ImportError("OpenAI package not installed"), prompt_type="connection_test", api_key=cred.openai_key)
            return jsonify({
                "success": False,
                "message": "OpenAI package not installed"
            }), 400
            
        except Exception as openai_error:
            # Log the error response
            log_ai_communication("RESPONSE", user_id, "openai", test_model, test_messages, error=openai_error, prompt_type="connection_test", api_key=cred.openai_key)
            
            error_msg = str(openai_error)
            _ = type(openai_error).__name__
            
            # Check for specific error types
            if "authentication" in error_msg.lower() or "invalid" in error_msg.lower() or "revoked" in error_msg.lower():
                return jsonify({
                    "success": False,
                    "message": "Error: The API key is not valid or has been revoked"
                }), 400
            elif "quota" in error_msg.lower() or "billing" in error_msg.lower():
                return jsonify({
                    "success": False,
                    "message": "Error: API quota exceeded or billing issue"
                }), 400
            elif "rate" in error_msg.lower():
                return jsonify({
                    "success": False,
                    "message": "Error: Rate limit exceeded"
                }), 400
            else:
                return jsonify({
                    "success": False,
                    "message": f"OpenAI connection failed: {error_msg}"
                }), 400
            
    except Exception as e:
        logger.error(f"Test OpenAI connection error: {str(e)}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500


@ai_bp.route("/api/test-zai-connection")
@login_required
def api_test_zai_connection():
    """Test Z.AI API connection with proper error detection"""
    try:
        # Get the current user
        user_id = current_user.id
        username = current_user.username
        
        # Use the proper database access method
        cred = get_user_credentials(username)
            
        if not cred:
            logger.error(f"No credentials found for user {username}")
            return jsonify({
                "success": False,
                "message": "No credentials found"
            }), 400
            
        if not cred.zai_key:
            logger.error(f"No Z.AI API key configured for user {username}")
            return jsonify({
                "success": False,
                "message": "No Z.AI API key configured"
            }), 400
        
        # Test Z.AI connection
        try:
            from zai_client import ZAIClient
            # Prepare test message
            test_messages = [{"role": "user", "content": "Hello"}]
            # Log the request
            log_ai_communication("REQUEST", user_id, "zai", "glm-4.7-flash", test_messages, prompt_type="connection_test", api_key=cred.zai_key)
            # Make the API call through our wrapper
            result = ZAIClient(cred.zai_key).chat_completion(test_messages, model="glm-4.7-flash", max_tokens=5)
            if result.get("success"):
                log_ai_communication("RESPONSE", user_id, "zai", "glm-4.7-flash", test_messages, response=result, prompt_type="connection_test", api_key=cred.zai_key)
                return jsonify({"success": True, "message": "Z.AI connection successful - API key is valid"})
            else:
                log_ai_communication("RESPONSE", user_id, "zai", "glm-4.7-flash", test_messages, error=Exception(result.get("error")), prompt_type="connection_test", api_key=cred.zai_key)
                return jsonify({"success": False, "message": f"Z.AI error: {result.get('error')}"}), 500
        except ImportError:
            return jsonify({"success": False, "message": "Z.AI client wrapper not available"}), 500
            
        except ImportError:
            log_ai_communication("RESPONSE", user_id, "zai", "glm-4.7-flash", test_messages, error=ImportError("Z.AI package not installed"), prompt_type="connection_test", api_key=cred.zai_key)
            return jsonify({
                "success": False,
                "message": "Z.AI package not installed"
            }), 500
            
        except Exception as zai_error:
            log_ai_communication("RESPONSE", user_id, "zai", "glm-4.7-flash", test_messages, error=zai_error, prompt_type="connection_test", api_key=cred.zai_key)
            error_msg = str(zai_error)
            
            # Provide specific error messages based on error type
            if "authentication" in error_msg.lower() or "invalid" in error_msg.lower():
                return jsonify({
                    "success": False,
                    "message": "Invalid Z.AI API key - please check your key"
                }), 400
            elif "quota" in error_msg.lower() or "billing" in error_msg.lower():
                return jsonify({
                    "success": False,
                    "message": "Z.AI billing issue - please check your account"
                }), 400
            elif "rate" in error_msg.lower():
                return jsonify({
                    "success": False,
                    "message": "Z.AI rate limit exceeded - please try again later"
                }), 429
            else:
                return jsonify({
                    "success": False,
                    "message": f"Z.AI connection failed: {error_msg}"
                }), 500
                
    except Exception as e:
        logger.error(f"Test Z.AI connection error: {str(e)}")
        return jsonify({"error": str(e)}), 500


@ai_bp.route('/api/ai/market-analysis')
@login_required
def api_ai_market_analysis():
    """Get overall market analysis using OpenAI with caching"""
    try:
        # Check cache first
        cache_key = f"market_analysis_{current_user.id}"
        cached_result = get_ai_cache(current_user.id, cache_key, "market_analysis")
        
        if cached_result:
            logger.info(f"Returning cached market analysis for user {current_user.id}")
            return jsonify(cached_result)
        
        # Check if AI is enabled
        if not is_ai_enabled(current_user.username):
            logger.info(f"AI is disabled for user {current_user.id}")
            return jsonify({
                "sentiment": "neutral",
                "risk_level": "moderate", 
                "confidence": 50,
                "summary": "AI analysis is disabled. Enable AI in Settings to use this feature.",
                "full_analysis": "AI analysis is disabled.",
                "key_insights": ["AI is disabled", "Enable AI in Settings", "Check AI killswitch setting"]
            })
        
        # Check if we're in the analysis window or if this is a manual request
        user_settings = get_user_ai_settings(current_user.username)
        analysis_window_start = user_settings.get('ai_analysis_window_start', '08:00')
        analysis_window_end = user_settings.get('ai_analysis_window_end', '23:59')
        
        if not is_user_analysis_window_active(analysis_window_start, analysis_window_end):
            logger.info(f"Outside analysis window for user {current_user.id}")
            return jsonify({
                "sentiment": "neutral",
                "risk_level": "moderate", 
                "confidence": 50,
                "summary": f"Analysis window: {analysis_window_start} - {analysis_window_end}. Use 'Run Analysis Now' for manual analysis.",
                "full_analysis": "Outside scheduled analysis window.",
                "key_insights": ["Outside analysis window", "Use manual analysis button", f"Window: {analysis_window_start} - {analysis_window_end}"]
            })
        
        # Get user's AI settings
        user_settings = get_user_ai_settings(current_user.username)
        current_timestamp = format_eastern_datetime(None, "%Y-%m-%d %H:%M:%S EST")
        risk_appetite = user_settings.get('ai_risk_tolerance', 'moderate')
        confidence_threshold = user_settings.get('ai_confidence_threshold', 75)

        prompt = (
            "MARKET_ANALYSIS_DATA\n"
            f"datetime: {current_timestamp}\n"
            f"risk_appetite: {risk_appetite}\n"
            f"confidence_threshold: {confidence_threshold}\n"
        )
        
        # Call AI API with web search (always enabled)
        try:
            # Get model setting
            model = user_settings.get('ai_model', 'gpt-5')
            
            # Get AI prompts from database
            ai_prompts_obj = get_user_ai_prompts(current_user.id)
            system_content = (ai_prompts_obj.market_analysis_post or "").strip() if ai_prompts_obj else ""
            if not system_content:
                return jsonify({
                    "error": "Missing market analysis post prompt. Configure it in Settings."
                }), 400
            
            response, _ = call_ai_with_web_search(
                username=current_user.username,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                model=model,
                user_id=current_user.id,
                prompt_type="market_analysis",
                include_db_context=False
            )
            
            analysis = response.choices[0].message.content
            
            # Log the AI conversation
            log_ai_conversation(current_user.id, "market_analysis", "user", prompt)
            log_ai_conversation(current_user.id, "market_analysis", "ai", analysis)
            
            # Parse the response to extract structured data
            result = {
                "sentiment": extract_sentiment(analysis),
                "risk_level": extract_risk_level(analysis),
                "confidence": extract_confidence(analysis),
                "summary": analysis[:200] + "..." if len(analysis) > 200 else analysis,
                "full_analysis": analysis,
                "key_insights": extract_key_insights(analysis)
            }
            
            # Cache the result
            cache_duration = user_settings.get('ai_cache_duration_hours', 4)
            set_ai_cache(current_user.id, cache_key, "market_analysis", result, cache_duration)
            
            # Update analysis schedule
            update_ai_analysis_schedule(current_user.id)
            
            return jsonify(result)
            
        except Exception as openai_error:
            logger.error(f"OpenAI API error: {openai_error}")
            return jsonify({"error": "Failed to get AI analysis"}), 500
            
    except Exception as e:
        logger.error(f"Error in market analysis: {str(e)}")
        return jsonify({"error": str(e)}), 500


@ai_bp.route('/api/ai/recommendations')
@login_required
def api_ai_recommendations():
    """Get AI trading recommendations using OpenAI with caching"""
    try:
        # Check cache first
        cache_key = f"recommendations_{current_user.id}"
        cached_result = get_ai_cache(current_user.id, cache_key, "recommendations")
        
        if cached_result:
            logger.info(f"Returning cached recommendations for user {current_user.id}")
            return jsonify(cached_result)
        
        # Check if AI is enabled
        if not is_ai_enabled(current_user.username):
            logger.info(f"AI is disabled for user {current_user.id}")
            return jsonify({
                "recommendations": [],
                "message": "AI analysis is disabled. Enable AI in Settings to use this feature."
            })
        
        # Check analysis frequency and usage limits
        user_settings = get_user_ai_settings(current_user.username)
        analysis_frequency = user_settings.get('ai_analysis_frequency', 'daily')
        analysis_window_start = user_settings.get('ai_analysis_window_start', '08:00')
        analysis_window_end = user_settings.get('ai_analysis_window_end', '23:59') if analysis_frequency == 'hourly' else '23:59'
        
        # Check for recent manual analysis (within last 30 minutes)
        recent_analysis = False
        daily_analysis_done = False
        
        try:
            # Use SQLAlchemy ORM instead of legacy SQLite
            from datetime import datetime, timedelta
            
            # Check for RECENT (cooldown) logic regardless of frequency
            cutoff = datetime.utcnow() - timedelta(minutes=30)
            recent_count = AIConversation.query.filter(
                AIConversation.user_id == current_user.id,
                AIConversation.prompt_type == 'market_analysis',
                AIConversation.created_at >= cutoff
            ).count()
            recent_analysis = recent_count > 0

            # Daily Frequency Logic: Check if ANY analysis occurred TODAY
            if analysis_frequency == 'daily':
                # Get start of day in Eastern Time (approximated by server time for now, or use get_eastern_now if available contextually)
                # Using server local time for consistency with database logging usually
                now_local = datetime.now()
                start_of_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                
                daily_count = AIConversation.query.filter(
                    AIConversation.user_id == current_user.id,
                    AIConversation.prompt_type == 'market_analysis',
                    AIConversation.sender == 'ai', # Only count completed AI responses
                    AIConversation.created_at >= start_of_day
                ).count()
                
                if daily_count > 0:
                    daily_analysis_done = True

        except Exception as e:
            logger.error(f"Error checking recent analysis: {e}")
        
        # If Daily and one is done -> Stop.
        if analysis_frequency == 'daily' and daily_analysis_done:
            logger.info(f"Daily analysis already completed for user {current_user.id}")
            return jsonify({
                "recommendations": [],
                "message": "Daily analysis already completed for today. Check back tomorrow or use 'Run Analysis Now'."
            })

        # Check window
        if not is_user_analysis_window_active(analysis_window_start, analysis_window_end) and not recent_analysis:
            logger.info(f"Outside analysis window and no recent analysis for user {current_user.id}")
            return jsonify({
                "recommendations": [],
                "message": f"Analysis window: {analysis_window_start} - {analysis_window_end}. Use 'Run Analysis Now' for manual analysis."
            })
        
        # Get user's AI settings
        user_settings = get_user_ai_settings(current_user.username)
        confidence_threshold = user_settings.get('ai_confidence_threshold', 75)
        
        # Get portfolio data to analyze (excluding stablecoins)
        portfolio = get_portfolio_data_for_user(current_user.id)
        non_stablecoin_portfolio = [coin for coin in portfolio if not is_stablecoin(coin.get('symbol', ''))]
        
        # If only stablecoins in portfolio, return empty recommendations
        if not non_stablecoin_portfolio:
            logger.info(f"Only stablecoins in portfolio for user {current_user.id}, skipping recommendations")
            return jsonify({
                "recommendations": [],
                "message": "Portfolio contains only stablecoins. No trading recommendations needed for stable assets."
            })
        
        # Get risk assessment request prompt template (no hardcoded defaults)
        recommendations = []
        
        # Get model setting
        model = user_settings.get('ai_model', 'gpt-5')
        
        # Analyze each coin in portfolio (excluding stablecoins)
        for coin in non_stablecoin_portfolio[:5]:  # Limit to top 5 non-stablecoin coins
            try:
                symbol = coin['symbol']
                current_price = coin.get('current_price', 0)
                
                if current_price <= 0:
                    continue
                
                # Get price history
                price_data = get_last_7d_prices(symbol)
                if not price_data or len(price_data) < 2:
                    continue
                
                # Calculate basic technical indicators
                price_change = ((price_data[-1] - price_data[0]) / price_data[0]) * 100
                volatility = calculate_volatility(price_data)
                
                # Create AI prompt for this specific coin
                full_prompt = (
                    "RISK_ASSESSMENT_DATA\n"
                    f"symbol: {symbol}\n"
                    f"current_price: {current_price}\n"
                    f"price_change: {price_change}\n"
                    f"volatility: {volatility}\n"
                    f"amount: {coin.get('amount', 0)}\n"
                    f"current_value: {coin.get('current_value', 0)}\n"
                    f"risk_tolerance: {user_settings.get('ai_risk_tolerance', 'moderate')}\n"
                )
                
                # Call AI API with web search (always enabled)
                try:
                    # Get AI prompts from database
                    ai_prompts_obj = get_user_ai_prompts(current_user.id)
                    system_content = (ai_prompts_obj.risk_assessment_post or "").strip() if ai_prompts_obj else ""
                    if not system_content:
                        raise ValueError("Missing risk assessment post prompt. Configure it in Settings.")
                    
                    response, _ = call_ai_with_web_search(
                        username=current_user.username,
                        messages=[
                            {"role": "system", "content": system_content},
                            {"role": "user", "content": full_prompt}
                        ],
                        model=model,
                        user_id=current_user.id,
                        prompt_type="risk_assessment",
                        symbol=symbol
                    )
                    
                    analysis = response.choices[0].message.content
                    
                    # Log the AI conversation
                    log_ai_conversation(current_user.id, "risk_assessment", "user", full_prompt)
                    log_ai_conversation(current_user.id, "risk_assessment", "ai", analysis)
                    
                    # Parse the AI response
                    signal, confidence, entry_price, stop_loss, take_profit, reasoning = parse_ai_recommendation(analysis, current_price)
                    
                    # Only include if confidence meets threshold
                    if confidence >= confidence_threshold:
                        recommendations.append({
                            "symbol": symbol,
                            "signal": signal,
                            "confidence": round(confidence, 1),
                            "current_price": round(current_price, 2),
                            "price_change": round(price_change, 2),
                            "entry_price": round(entry_price, 2),
                            "stop_loss": round(stop_loss, 2),
                            "take_profit": round(take_profit, 2),
                            "reasoning": reasoning,
                            "ai_analysis": analysis
                        })
                        
                except Exception as openai_error:
                    logger.error(f"OpenAI API error for {symbol}: {openai_error}")
                    # Fallback to basic analysis
                    signal, confidence, entry_price, stop_loss, take_profit, reasoning = basic_recommendation_analysis(price_change, volatility, current_price)
                    
                    if confidence >= confidence_threshold:
                        recommendations.append({
                            "symbol": symbol,
                            "signal": signal,
                            "confidence": round(confidence, 1),
                            "current_price": round(current_price, 2),
                            "price_change": round(price_change, 2),
                            "entry_price": round(entry_price, 2),
                            "stop_loss": round(stop_loss, 2),
                            "take_profit": round(take_profit, 2),
                            "reasoning": reasoning
                        })
                    
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")
                continue
        
        # Sort by confidence
        recommendations.sort(key=lambda x: x['confidence'], reverse=True)
        
        result = {
            "recommendations": recommendations,
            "total": len(recommendations)
        }
        
        # Cache the result
        cache_duration = user_settings.get('ai_cache_duration_hours', 4)
        set_ai_cache(current_user.id, cache_key, "recommendations", result, cache_duration)
        
        # Update analysis schedule
        update_ai_analysis_schedule(current_user.id)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error generating recommendations: {e}")
        return jsonify({"error": str(e)}), 500



@ai_bp.route('/api/ai/portfolio-analysis')
@login_required
def api_ai_portfolio_analysis():
    """Get AI portfolio analysis using OpenAI with caching"""
    try:
        # Check cache first
        cache_key = f"portfolio_analysis_{current_user.id}"
        cached_result = get_ai_cache(current_user.id, cache_key, "portfolio_analysis")
        
        if cached_result:
            logger.info(f"Returning cached portfolio analysis for user {current_user.id}")
            return jsonify(cached_result)
        
        # Check if AI is enabled
        if not is_ai_enabled(current_user.username):
            logger.info(f"AI is disabled for user {current_user.id}")
            return jsonify({
                "health_score": 50,
                "diversification_score": 50,
                "risk_adjusted_return": 50,
                "recommendations": ["AI analysis is disabled. Enable AI in Settings to use this feature."],
                "ai_analysis": "AI analysis is disabled."
            })
        
        # Check if analysis should run
        if not should_run_ai_analysis(current_user.id) and not is_analysis_window_active():
            logger.info(f"AI analysis not scheduled for user {current_user.id}")
            return jsonify({
                "health_score": 50,
                "diversification_score": 50,
                "risk_adjusted_return": 50,
                "recommendations": ["Analysis not scheduled. Use 'Run Analysis Now' button for manual analysis."],
                "ai_analysis": "Analysis not scheduled."
            })
        
        # Get user's AI settings
        user_settings = get_user_ai_settings(current_user.username)
        
        # Get portfolio data (excluding stablecoins)
        portfolio = get_portfolio_data_for_user(current_user.id)
        non_stablecoin_portfolio = [coin for coin in portfolio if not is_stablecoin(coin.get('symbol', ''))]
        
        if not portfolio:
            return jsonify({
                "health_score": 0,
                "diversification_score": 0,
                "risk_adjusted_return": 0,
                "recommendations": ["No portfolio data available for analysis"]
            })
        
        # If only stablecoins in portfolio, return special analysis
        if not non_stablecoin_portfolio:
            logger.info(f"Only stablecoins in portfolio for user {current_user.id}, returning stablecoin analysis")
            return jsonify({
                "health_score": 100,
                "diversification_score": 50,
                "risk_adjusted_return": 100,
                "recommendations": [
                    "Portfolio contains only stablecoins",
                    "Stablecoins provide price stability but limited growth potential",
                    "Consider adding some volatile assets for growth opportunities",
                    "Current portfolio is very low risk"
                ],
                "ai_analysis": "Portfolio consists entirely of stablecoins, which are designed to maintain a stable value. This provides excellent price stability but limited growth potential. Consider diversifying with some volatile assets for growth opportunities."
            })
        
        # Calculate basic portfolio metrics (NO initial_value)
        total_value = sum(coin.get('current_value', 0) for coin in portfolio)
        # Build summary with amount and current value for each coin
        portfolio_summary = []
        for coin in portfolio:
            symbol = coin['symbol']
            amount = coin.get('amount', 0)
            current_price = coin.get('current_price', 0)
            current_value = coin.get('current_value', 0)
            portfolio_summary.append(f"{symbol}: {amount:.6f} @ ${current_price:.2f} = ${current_value:.2f}")
        portfolio_summary_text = "\n".join(portfolio_summary)
        prompt = (
            "PORTFOLIO_REVIEW_DATA\n"
            f"total_coins: {len(portfolio)}\n"
            f"total_value: {total_value}\n"
            f"risk_tolerance: {user_settings.get('ai_risk_tolerance', 'moderate')}\n"
            f"confidence_threshold: {user_settings.get('ai_confidence_threshold', 75)}\n"
            "portfolio_summary:\n"
            f"{portfolio_summary_text}\n"
        )
        
        # Call OpenAI API with web search
        try:
            # Get model setting
            model = user_settings.get('ai_model', 'gpt-5')
            
            # Get AI prompts from database
            ai_prompts_obj = get_user_ai_prompts(current_user.id)
            system_content = (ai_prompts_obj.portfolio_review_post or "").strip() if ai_prompts_obj else ""
            if not system_content:
                return jsonify({
                    "error": "Missing portfolio review post prompt. Configure it in Settings."
                }), 400
            
            response, _ = call_ai_with_web_search(
                username=current_user.username,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                model=model,
                user_id=current_user.id,
                prompt_type="portfolio_review"
            )
            
            analysis = response.choices[0].message.content
            
            # Log the AI conversation
            log_ai_conversation(current_user.id, "portfolio_review", "user", prompt)
            log_ai_conversation(current_user.id, "portfolio_review", "ai", analysis)
            
            # Parse the AI response
            health_score, diversification_score, risk_adjusted_return, recommendations = parse_portfolio_analysis(analysis)
            
            result = {
                "health_score": round(health_score, 1),
                "diversification_score": round(diversification_score, 1),
                "risk_adjusted_return": round(risk_adjusted_return, 1),
                "recommendations": recommendations,
                "ai_analysis": analysis
            }
            
            # Cache the result
            cache_duration = user_settings.get('ai_cache_duration_hours', 4)
            set_ai_cache(current_user.id, cache_key, "portfolio_analysis", result, cache_duration)
            
            # Update analysis schedule
            update_ai_analysis_schedule(current_user.id)
            
            return jsonify(result)
            
        except Exception as openai_error:
            logger.error(f"OpenAI API error: {openai_error}")
            # Fallback to basic analysis
            return basic_portfolio_analysis(portfolio, total_value, 0.0)
            
    except Exception as e:
        logger.error(f"Error in portfolio analysis: {e}")
        return jsonify({"error": str(e)}), 500


@ai_bp.route('/api/ai/market-analysis/<symbol>')
@login_required
def api_ai_symbol_analysis(symbol):
    """Get detailed AI analysis for a specific symbol"""
    try:
        # Get price data
        price_data = get_last_7d_prices(symbol)
        if not price_data or len(price_data) < 2:
            return jsonify({"error": "Insufficient price data"}), 400
        
        snapshot = calculate_symbol_snapshot(symbol)
        if not snapshot:
            return jsonify({"error": "Insufficient price data"}), 400

        reasoning = (
            f"Analysis of {symbol} shows a {snapshot['price_change_7d']:.1f}% price change over 7 days. "
            f"Current price is ${snapshot['current_price']:.2f} with {snapshot['volatility']:.1%} volatility. "
            f"Technical indicators suggest a {snapshot['signal'].lower()} signal with {snapshot['confidence']}% confidence. "
            f"Recommended entry at ${snapshot['entry_price']:.2f} with stop loss at ${snapshot['stop_loss']:.2f} "
            f"and take profit at ${snapshot['take_profit']:.2f}."
        )

        return jsonify({
            "symbol": symbol,
            "signal": snapshot['signal'],
            "overall_confidence": snapshot['confidence'],
            "sentiment_score": max(0, min(100, 50 + (snapshot['price_change_7d'] * 2))),
            "risk_level": max(0, min(100, int(snapshot['volatility'] * 100))),
            "current_price": snapshot['current_price'],
            "entry_price": snapshot['entry_price'],
            "stop_loss": snapshot['stop_loss'],
            "take_profit": snapshot['take_profit'],
            "technical_indicators": snapshot['technical_indicators'],
            "price_metrics": {
                "pct_1d": snapshot['pct_1d'],
                "pct_3d": snapshot['pct_3d'],
                "pct_7d": snapshot['pct_7d']
            },
            "patterns": snapshot['patterns'],
            "reasoning": reasoning,
            "risk_factors": snapshot['risk_factors'],
            "recommendation": {
                "signal": snapshot['signal'],
                "confidence": snapshot['confidence'],
                "technical_score": snapshot['technical_score'],
                "risk_penalty": max(0, min(20, int(snapshot['volatility'] * 100)))
            },
            "data_source": "price_history (Binance.US 7d hourly)",
            "series_window": {
                "points": len(price_data)
            }
        })
        
    except Exception as e:
        logger.error(f"Error in symbol analysis: {e}")
        return jsonify({"error": str(e)}), 500


@ai_bp.route('/api/ai/smart-alerts')
@login_required
def api_ai_smart_alerts():
    """Get smart alerts based on AI analysis"""
    try:
        # Check if AI is enabled
        if not is_ai_enabled(current_user.username):
            return jsonify({
                'alerts': [],
                'total': 0,
                'high_priority': 0,
                'message': 'AI analysis is disabled. Enable AI in Settings to use this feature.'
            })
        
        # Check if we're in the analysis window OR if there's recent analysis activity
        # Check analysis frequency and settings
        user_settings = get_user_ai_settings(current_user.username)
        analysis_frequency = user_settings.get('ai_analysis_frequency', 'daily')
        analysis_window_start = user_settings.get('ai_analysis_window_start', '08:00')
        analysis_window_end = user_settings.get('ai_analysis_window_end', '23:59') if analysis_frequency == 'hourly' else '23:59'
        
        # Check for recent manual analysis (within last 30 minutes)
        recent_analysis = False
        daily_analysis_done = False
        
        try:
            # Use SQLAlchemy ORM instead of legacy SQLite
            from datetime import datetime, timedelta
            
            # Check for RECENT (cooldown) logic
            cutoff = datetime.utcnow() - timedelta(minutes=30)
            recent_count = AIConversation.query.filter(
                AIConversation.user_id == current_user.id,
                AIConversation.prompt_type == 'market_analysis',
                AIConversation.created_at >= cutoff
            ).count()
            recent_analysis = recent_count > 0

            # Daily Frequency Logic: Check if ANY analysis occurred TODAY
            if analysis_frequency == 'daily':
                # Get start of day in Eastern Time (approximated by server time)
                now_local = datetime.now()
                start_of_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                
                daily_count = AIConversation.query.filter(
                    AIConversation.user_id == current_user.id,
                    AIConversation.prompt_type == 'market_analysis',
                    AIConversation.sender == 'ai',
                    AIConversation.created_at >= start_of_day
                ).count()
                
                if daily_count > 0:
                    daily_analysis_done = True
                    
        except Exception as e:
            logger.error(f"Error checking recent analysis: {e}")
        
        # If Daily and one is done -> Stop, unless we want alerts to be checked regardless? 
        # Usually smart alerts are DERIVED from analysis. If analysis is done, we might just want to RETURN the alerts from database?
        # But for now let's respect the user request to not "trigger" things multiple times.
        if analysis_frequency == 'daily' and daily_analysis_done:
             # Just return existing alerts if available, or empty if we consider the "Action" of checking to be the trigger.
             # Ideally we should fetch stored alerts. But the current implementation generates them on the fly?
             # Line 15922: alerts = generate_smart_alerts_for_user(current_user.id)
             # Let's assume generate_smart_alerts checks DB.
             # If the user's main complaint is "API USAGE", we should avoid calls.
             # generate_smart_alerts might call LLM if not cached?
             pass 

        if not is_user_analysis_window_active(analysis_window_start, analysis_window_end) and not recent_analysis:
            return jsonify({
                'alerts': [],
                'total': 0,
                'high_priority': 0,
                'message': f'Analysis window: {analysis_window_start} - {analysis_window_end}. Use "Run Analysis Now" for manual analysis.'
            })
        
        alerts = generate_smart_alerts_for_user(current_user.id)
        return jsonify({
            'alerts': alerts,
            'total': len(alerts),
            'high_priority': len([a for a in alerts if a.get('priority') == 'high'])
        })
    except Exception as e:
        logger.error(f"Error in smart alerts: {e}")
        return jsonify({'error': str(e)}), 500


@ai_bp.route('/api/ai/recommendation-score/<symbol>')
@login_required
def api_ai_recommendation_score(symbol):
    """Get detailed recommendation scoring for a specific symbol"""
    try:
        # Get price data
        price_data = get_last_7d_prices(symbol)
        if not price_data or len(price_data) < 7:
            return jsonify({'error': 'Insufficient price data'}), 400
        
        # Get sentiment
        sentiment = fetch_news_sentiment(symbol)
        
        # Calculate volatility
        returns = [(price_data[i] - price_data[i-1]) / price_data[i-1] for i in range(1, len(price_data))]
        volatility = np.std(returns) if returns else 0
        
        # Prepare analysis data
        analysis_data = {
            'price_data': price_data,
            'sentiment': sentiment,
            'volatility': volatility,
            'portfolio_correlation': 0.5,  # Placeholder - could be calculated vs user's portfolio
            'market_timing': 0.6  # Placeholder - could be based on market cycles
        }
        
        # Score the recommendation
        confidence_score = score_recommendation(symbol, analysis_data)
        
        # Get technical indicators
        sma_7 = np.mean(price_data[-7:])
        sma_14 = np.mean(price_data[-14:]) if len(price_data) >= 14 else sma_7
        current_price = price_data[-1]
        
        # Calculate RSI
        gains = [max(price_data[i] - price_data[i-1], 0) for i in range(1, len(price_data))]
        losses = [max(price_data[i-1] - price_data[i], 0) for i in range(1, len(price_data))]
        avg_gain = np.mean(gains[-14:]) if len(gains) >= 14 else np.mean(gains)
        avg_loss = np.mean(losses[-14:]) if len(losses) >= 14 else np.mean(losses)
        rs = avg_gain / avg_loss if avg_loss > 0 else 0
        rsi = 100 - (100 / (1 + rs))
        
        return jsonify({
            'symbol': symbol,
            'confidence_score': round(confidence_score, 1),
            'technical_indicators': {
                'sma_7': round(sma_7, 2),
                'sma_14': round(sma_14, 2),
                'rsi': round(rsi, 1),
                'current_price': round(current_price, 2)
            },
            'sentiment_score': round(abs(sentiment) * 100, 1),
            'volatility_score': round((1 - volatility) * 100, 1),
            'analysis_factors': {
                'trend_strength': 'strong_uptrend' if current_price > sma_7 > sma_14 else 'strong_downtrend' if current_price < sma_7 < sma_14 else 'sideways',
                'momentum': 'bullish' if current_price > sma_7 else 'bearish',
                'rsi_signal': 'oversold' if rsi < 30 else 'overbought' if rsi > 70 else 'neutral'
            }
        })
        
    except Exception as e:
        logger.error(f"Error in recommendation scoring: {e}")
        return jsonify({'error': str(e)}), 500



@ai_bp.route('/api/ai/conversations')
@login_required
def api_ai_conversations():
    """Get AI conversations for user with optional filtering"""
    try:
        # Check if user is authenticated
        if not current_user.is_authenticated:
            logger.error("User not authenticated for AI conversations")
            return jsonify({'error': 'User not authenticated'}), 401
        
        limit = request.args.get('limit', 10, type=int)  # Default to 10 for pagination
        offset = request.args.get('offset', 0, type=int)
        search_term = request.args.get('search', None)
        include_hidden = request.args.get('include_hidden', 'false').lower() == 'true'
        filter_sentiment = request.args.get('filter_sentiment', 'false').lower() == 'true'
        prompt_type_filter = request.args.get('prompt_type')
        
        logger.info(f"Getting AI conversations for user {current_user.id}, limit={limit}, offset={offset}, filter_sentiment={filter_sentiment}")
        
        conversations = get_ai_conversations(
            current_user.id, 
            limit, 
            offset, 
            search_term, 
            include_hidden,
            filter_sentiment,
            prompt_type_filter
        )
        
        # Get total count with the same filters
        total_count = get_ai_conversations_count(
            current_user.id, 
            search_term, 
            include_hidden,
            filter_sentiment,
            prompt_type_filter
        )
        
        logger.info(f"Retrieved {len(conversations)} conversations out of {total_count} total")
        
        return jsonify({
            'conversations': conversations,
            'total': total_count,
            'has_more': (offset + len(conversations)) < total_count,
            'limit': limit,
            'offset': offset
        })
        
    except Exception as e:
        logger.error(f"Error getting AI conversations: {e}")
        # Return empty conversations instead of 500 error
        return jsonify({
            'conversations': [],
            'total': 0,
            'error': 'Failed to load conversations'
        })


@ai_bp.route('/api/ai/conversation', methods=['POST'])
@login_required
def api_ai_conversation():
    """Process user message and get AI response"""
    try:
        data = request.get_json()
        message = data.get('message', '').strip()
        conversation_id = data.get('conversation_id', None)
        
        if not message:
            return jsonify({'error': 'Message is required'}), 400
        
        # Process the conversation
        ai_response, conversation_id = process_ai_conversation(current_user.id, message, conversation_id)
        
        return jsonify({
            'response': ai_response,
            'conversation_id': conversation_id
        })
        
    except Exception as e:
        logger.error(f"Error processing AI conversation: {e}")
        return jsonify({
            'response': 'I apologize, but I encountered an error processing your request. Please try again later.',
            'conversation_id': conversation_id
        })


@ai_bp.route('/api/ai/conversations/<int:message_id>', methods=['DELETE'])
@login_required
def api_delete_ai_conversation(message_id):
    """Delete a specific AI conversation message using ORM"""
    try:
        from models import AIConversation
        # Find the message and verify ownership
        message = AIConversation.query.filter_by(id=message_id, user_id=current_user.id).first()
        
        if not message:
            return jsonify({'error': 'Message not found or access denied'}), 404
        
        # Delete the message
        db.session.delete(message)
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting AI conversation: {e}")
        return jsonify({'error': str(e)}), 500


@ai_bp.route('/api/ai/conversations/<int:message_id>/archive', methods=['PATCH'])
@login_required
def api_archive_ai_conversation(message_id):
    """Archive a specific AI conversation message using ORM"""
    try:
        from models import AIConversation
        # Find the message and verify ownership
        message = AIConversation.query.filter_by(id=message_id, user_id=current_user.id).first()
        
        if not message:
            return jsonify({'error': 'Message not found or access denied'}), 404
        
        # Archive the message (set is_hidden = True)
        message.is_hidden = True
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error archiving AI conversation: {e}")
        return jsonify({'error': str(e)}), 500


@ai_bp.route('/api/ai/news-analysis', methods=['POST'])
@login_required
def api_ai_news_analysis():
    """Get AI news analysis for a specific coin using 3-stage agentic workflow with coin_analysis prompts"""
    try:
        data = request.get_json()
        symbol = data.get('symbol', '').upper()
        use_cache = data.get('use_cache', False)
        force_fresh = data.get('force_fresh', False)
        
        if not symbol:
            return jsonify({'error': 'Symbol is required'}), 400
        
        # Check if AI is enabled
        if not is_ai_enabled(current_user.username):
            return jsonify({
                'error': 'AI analysis is disabled. Enable AI in Settings to use this feature.'
            }), 400
        
        # Check for cached analysis if use_cache is True and not forcing fresh
        if use_cache and not force_fresh:
            try:
                # Get coin_id for this symbol and user (check both portfolio and watchlist)
                coin_id = get_coin_id_by_symbol(symbol, current_user.id)
                
                # If not in portfolio, check if it's in watchlist
                if not coin_id:
                    from models import WatchlistCoin
                    watchlist_coin = WatchlistCoin.query.filter_by(
                        user_id=current_user.id, 
                        symbol=symbol.upper(),
                        hidden=False
                    ).first()
                    
                    if not watchlist_coin:
                        return jsonify({
                            'error': f'Coin {symbol} not found in your portfolio or watchlist.',
                            'no_coin': True
                        }), 404
                
                # Check ai_conversations for recent coin analysis (last 2 hours) by coin_id
                from datetime import datetime, timedelta
                cutoff_time = datetime.utcnow() - timedelta(hours=2)
                
                # Use SQLAlchemy ORM instead of legacy SQLite
                cached_row = AIConversation.query.filter(
                    AIConversation.user_id == current_user.id,
                    AIConversation.coin_id == coin_id,
                    AIConversation.prompt_type == 'coin_analysis',
                    AIConversation.sender == 'ai',
                    AIConversation.created_at >= cutoff_time
                ).order_by(AIConversation.id.desc()).first()
                
                if cached_row:
                    cached_analysis = cached_row.body
                    # Format the timestamp
                    try:
                        timestamp_formatted = cached_row.created_at.strftime("%B %d, %Y at %I:%M %p UTC") if cached_row.created_at else "Unknown"
                    except Exception:
                        timestamp_formatted = str(cached_row.created_at)
                    
                    return jsonify({
                        'symbol': symbol,
                        'analysis': cached_analysis,
                        'timestamp': timestamp_formatted,
                        'prompt_used': 'Cached analysis',
                        'cached': True
                    })
                else:
                    # NO CACHE EXISTS - Return error instead of falling back to fresh analysis
                    return jsonify({
                        'error': f'No cached analysis found for {symbol}. Use the refresh button (🔄) to generate fresh analysis.',
                        'no_cache': True
                    }), 404
            except Exception as cache_error:
                logger.warning(f"Cache check failed for {symbol}: {cache_error}")
                return jsonify({
                    'error': f'Cache check failed for {symbol}. Use the refresh button (🔄) to generate fresh analysis.',
                    'cache_error': True
                }), 500
        
        # Get user's AI prompts from database (NO HARDCODING)
        ai_prompts_obj = get_user_ai_prompts(current_user.id)
        if not ai_prompts_obj:
            return jsonify({
                'error': 'No AI prompts configured. Please check your settings.'
            }), 400
            
        # Use coin_analysis prompts for the 3-stage workflow
        coin_pre_prompt = ai_prompts_obj.coin_analysis_pre
        coin_post_prompt = ai_prompts_obj.coin_analysis_post
        if not coin_pre_prompt or not coin_post_prompt:
            return jsonify({'error': 'coin_analysis_pre and coin_analysis_post must be set in the database.'}), 400

        # Replace placeholders
        current_datetime = format_eastern_datetime(None, "%B %d, %Y at %I:%M %p EST")
        coin_pre_prompt = coin_pre_prompt.replace('{symbol}', symbol).replace('{datetime}', current_datetime)
        coin_post_prompt = coin_post_prompt.replace('{symbol}', symbol).replace('{datetime}', current_datetime)

        # Get model setting
        user_settings = get_user_ai_settings(current_user.username)
        model = user_settings.get('ai_model', 'gpt-5')

        # Capture current_user attributes before threading (Flask-Login context not available in threads)
        username = current_user.username
        user_id = current_user.id

        # === Gather coin data for the specific symbol ===
        from models import Coin
        coin_obj = Coin.query.filter_by(user_id=user_id, symbol=symbol, hidden=False).first()
        
        # Get coin_id for logging
        coin_id = coin_obj.id if coin_obj else None

        # Prepare the user's original message for the 3-stage agentic workflow
        original_user_message = (
            "NEWS_ANALYSIS_DATA\n"
            f"symbol: {symbol}\n"
            f"datetime: {current_datetime}\n"
        )

        try:
            # Call the 3-stage agentic workflow with proper message structure
            # The call_ai_with_web_search function will:
            # 1. Use coin_analysis_pre for Stage 1 (search query generation)
            # 2. Execute web searches in Stage 2
            # 3. Use coin_analysis_post for Stage 3 (final analysis with search results)
            ai_response, stage3_prompt = call_ai_with_web_search(
                username=username,
                messages=[{"role": "user", "content": original_user_message}],
                model=model,
                user_id=user_id,
                prompt_type="coin_analysis",
                symbol=symbol,
                amount=coin_obj.amount if coin_obj else None
            )

            if not ai_response:
                raise Exception("No response received from AI analysis")

            analysis = ai_response.choices[0].message.content

            # Log the AI conversation for copilot sidebar with proper timing
            log_ai_conversation(user_id, "coin_analysis", "user", original_user_message, symbol=symbol, coin_id=coin_id)
            time.sleep(0.1)
            log_ai_conversation(user_id, "coin_analysis", "ai", analysis, symbol=symbol, coin_id=coin_id)

            return jsonify({
                'symbol': symbol,
                'analysis': analysis,
                'timestamp': current_datetime,
                'prompt_used': f"Coin Pre: {coin_pre_prompt[:100]}..., Coin Post: {coin_post_prompt[:100]}...",
                'cached': False
            })

        except Exception as analysis_error:
            logger.error(f"Error during AI analysis for {symbol}: {analysis_error}")
            return jsonify({
                'error': f'AI analysis failed: {str(analysis_error)}'
            }), 500
            
    except Exception as e:
        logger.error(f"Error in news analysis endpoint: {e}")
        return jsonify({'error': str(e)}), 500
            
    except Exception as e:
        logger.error(f"Error in news analysis: {e}")
        return jsonify({'error': str(e)}), 500


@ai_bp.route('/api/ai/run-analysis', methods=['POST'])
@login_required
def api_run_ai_analysis():
    """Manually trigger AI analysis"""
    try:
        
        # Get user's portfolio
        portfolio = get_portfolio_data_for_user(current_user.id)
        
        if not portfolio:
            return jsonify({
                'success': False,
                'message': 'No portfolio data found. Add some coins to your portfolio first.',
                'results': []
            })
        
        # Get user's AI settings
        user_settings = get_user_ai_settings(current_user.username)
        
        # Run analysis for all unhidden portfolio coins
        analysis_results = []
        conversation_id = generate_conversation_id()
        
        for coin in portfolio:
            symbol = coin['symbol']
            current_price = coin.get('current_price', 0)
            
            if current_price <= 0:
                continue
            
            # Get price data
            price_data = get_last_7d_prices(symbol)
            if not price_data or len(price_data) < 2:
                continue
            
            # Calculate basic metrics
            price_change = ((price_data[-1] - price_data[0]) / price_data[0]) * 100
            volatility = calculate_volatility(price_data)
            
            # Run market analysis
            try:
                market_prompt = (
                    "MARKET_ANALYSIS_COIN_DATA\n"
                    f"symbol: {symbol}\n"
                    f"current_price: {current_price}\n"
                    f"price_change: {price_change}\n"
                    f"volatility: {volatility}\n"
                )
                
                # Log the prompt
                log_ai_conversation(current_user.id, "market_analysis", "user", market_prompt, conversation_id)
                
                # Get AI prompts from database
                ai_prompts_obj = get_user_ai_prompts(current_user.id)
                system_content = (ai_prompts_obj.market_analysis_post or "").strip() if ai_prompts_obj else ""
                if not system_content:
                    logger.error(f"Missing market analysis post prompt for user {current_user.username}. Configure it in Settings.")
                    continue
                
                # Use the web search enabled AI function
                messages = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": market_prompt}
                ]
                
                response, _ = call_ai_with_web_search(
                    username=current_user.username,
                    messages=messages,
                    user_id=current_user.id,
                    prompt_type="market_analysis"
                )
                
                ai_response = response.choices[0].message.content
                
                # Log the response
                log_ai_conversation(current_user.id, "market_analysis", "ai", ai_response, conversation_id, symbol)
                
                # Coin analysis table removed - all AI conversations are now stored in ai_conversations table
                # The conversation is already logged above via log_ai_conversation()
                
                analysis_results.append({
                    'symbol': symbol,
                    'analysis': ai_response,
                    'price_change': price_change,
                    'volatility': volatility
                })
                
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")
                continue
        
        return jsonify({
            'success': True,
            'results': analysis_results,
            'conversation_id': conversation_id,
            'message': f'Analysis completed for {len(analysis_results)} coins'
        })
        
    except Exception as e:
        logger.error(f"Error running AI analysis: {e}")
        return jsonify({'error': str(e)}), 500


@ai_bp.route('/api/ai/coin-analysis', methods=['GET', 'POST'])
@login_required
def api_ai_coin_analysis():
    """Get coin analysis data or run new analysis for both portfolio and watchlist coins"""
    try:
        if request.method == 'GET':
            # Get all coin analysis for current user (both portfolio and watchlist) using ORM
            from models import Coin, WatchlistCoin
            
            # Get portfolio coins (excluding hidden)
            portfolio_coins = Coin.query.filter_by(user_id=current_user.id, hidden=False).order_by(Coin.symbol).all()
            
            # Get watchlist coins (excluding hidden)
            watchlist_coins = WatchlistCoin.query.filter_by(user_id=current_user.id, hidden=False).order_by(WatchlistCoin.symbol).all()
            
            # Coin analysis table was removed - all AI conversations are now in ai_conversations table
            # Return empty analysis list since the coin_analysis table no longer exists
            coin_analyses = []
                    
            return jsonify({'coin_analyses': coin_analyses})
            
        elif request.method == 'POST':
            # POST method: Run new analysis for a specific coin
            data = request.get_json()
            source = data.get('source', 'portfolio')  # 'portfolio' or 'watchlist'
            coin_id = data.get('coin_id')
            watchlist_coin_id = data.get('watchlist_coin_id')
            
            # Validate parameters
            if source == 'portfolio' and not coin_id:
                return jsonify({"error": "coin_id is required for portfolio analysis"}), 400
            elif source == 'watchlist' and not watchlist_coin_id:
                return jsonify({"error": "watchlist_coin_id is required for watchlist analysis"}), 400
            
            # Get coin symbol from database using ORM
            from models import Coin, WatchlistCoin
            
            if source == 'portfolio':
                coin = Coin.query.filter_by(id=coin_id, user_id=current_user.id).first()
            else:  # watchlist
                coin = WatchlistCoin.query.filter_by(id=watchlist_coin_id, user_id=current_user.id).first()
            
            if not coin:
                return jsonify({"error": "Coin not found"}), 404
            
            symbol = coin.symbol
            
            # Check if AI is enabled
            if not is_ai_enabled(current_user.username):
                return jsonify({"error": "AI is disabled"}), 403
            
            # Get AI settings and prompts from database - never hardcode prompts per instructions
            user_settings = get_user_ai_settings(current_user.username)

            # Format prompt with variables - use human-readable date format
            current_datetime = format_eastern_datetime(None, '%B %d, %Y at %I:%M %p EST')
            formatted_prompt = (
                "COIN_ANALYSIS_DATA\n"
                f"symbol: {symbol}\n"
                f"datetime: {current_datetime}\n"
            )
            
            # Enhanced logging for debugging
            logger.info("=== COIN ANALYSIS DEBUG ===")
            logger.info(f"Symbol: {symbol}")
            logger.info(f"Source: {source}")
            logger.info(f"Coin ID: {coin_id}")
            logger.info(f"Watchlist Coin ID: {watchlist_coin_id}")
            logger.info(f"Formatted Prompt: {formatted_prompt}")
            logger.info(f"Current Datetime: {current_datetime}")
            logger.info("=== END COIN ANALYSIS DEBUG ===")
            
            # Call AI API
            try:
                # Get user AI settings to determine provider and model
                user_settings = get_user_ai_settings(current_user.username)
                ai_provider = user_settings.get('ai_provider', 'openai')
                model_name = user_settings.get('ai_model', 'gpt-5')
                
                # Log the full prompt being sent to AI
                logger.info("=== FULL PROMPT TO AI ===")
                # Get AI prompts from database
                ai_prompts_obj = get_user_ai_prompts(current_user.id)
                system_content = (ai_prompts_obj.coin_analysis_post or "").strip() if ai_prompts_obj else ""
                if not system_content:
                    return jsonify({"error": "Missing coin analysis post prompt. Configure it in Settings."}), 400
                
                logger.info(f"System message: {system_content}")
                logger.info(f"User message: {formatted_prompt}")
                logger.info(f"Provider: {ai_provider}")
                logger.info(f"Model: {model_name}")
                logger.info("=== END FULL PROMPT TO AI ===")
                
                response, _ = call_ai_with_web_search(
                    username=current_user.username,
                    messages=[
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": formatted_prompt}
                    ],
                    user_id=current_user.id,
                    prompt_type="coin_analysis",
                    symbol=symbol  # Pass the symbol for variable substitution
                )
                
                # Handle different response formats
                logger.info("=== AI RESPONSE DEBUG ===")
                logger.info(f"Response type: {type(response)}")
                logger.info(f"Response: {response}")
                
                if hasattr(response, 'choices') and response.choices:
                    # OpenAI format
                    analysis_report = response.choices[0].message.content
                    logger.info(f"OpenAI format - Analysis report: {analysis_report}")
                elif isinstance(response, dict) and 'content' in response:
                    # Z.AI format
                    analysis_report = response['content']
                    logger.info(f"Z.AI format - Analysis report: {analysis_report}")
                    logger.info(f"Z.AI content length: {len(analysis_report) if analysis_report else 0}")
                    logger.info(f"Z.AI content is empty: {analysis_report == ''}")
                elif isinstance(response, dict) and 'error' in response:
                    # Error response from Z.AI
                    error_msg = response.get('error', {}).get('message', 'Unknown error')
                    logger.error(f"Z.AI Error: {error_msg}")
                    raise Exception(f"AI API error: {error_msg}")
                else:
                    # Fallback for other formats
                    analysis_report = str(response)
                    logger.info(f"Fallback format - Analysis report: {analysis_report}")
                
                # Check if analysis report is empty
                if not analysis_report or analysis_report.strip() == '':
                    logger.error(f"EMPTY ANALYSIS REPORT! Response was: {response}")
                    raise Exception("AI returned empty analysis report")
                
                logger.info("=== END AI RESPONSE DEBUG ===")
                
                # Log the conversation for sidebar display in proper order
                try:
                    # Generate a shared conversation ID to group the request and response
                    conversation_id = generate_conversation_id()
                    
                    # FIXED: Log the user's FULL request FIRST with timestamp to ensure proper order
                    import time
                    time.sleep(0.1)  # Small delay to ensure proper ordering
                    
                    log_ai_conversation(
                        user_id=current_user.id,
                        prompt_type="coin_analysis",
                        sender="user",
                        body=formatted_prompt,  # Use the FULL prompt that was sent to AI, not just "Analyze {symbol}"
                        conversation_id=conversation_id
                    )
                    
                    # Small delay to ensure the AI response comes after the user message
                    time.sleep(0.1)
                    
                    # Log the AI's response SECOND
                    try:
                        log_ai_conversation(
                            user_id=current_user.id,
                            prompt_type="coin_analysis",
                            sender="ai",
                            body=analysis_report,
                            conversation_id=conversation_id
                        )
                        logger.info(f"Coin analysis conversation logged for {symbol} with conversation_id: {conversation_id}")
                    except Exception as e:
                        logger.error(f"Error logging coin analysis conversation: {e}")
                except Exception as e:
                    logger.error(f"Conversation logging failed: {e}")
                
                # Coin analysis storage removed - all AI conversations now stored in ai_conversations table
                # The conversation is already logged above via log_ai_conversation()
                # No need for separate coin_analysis table storage
                
                return jsonify({
                    "success": True,
                    "report": analysis_report,
                    "ordinal": 1,  # Default ordinal since we're not tracking in separate table
                    "date": datetime.now().strftime('%Y-%m-%d'),
                    "time": datetime.now().strftime('%H:%M:%S')
                })
                
            except Exception as e:
                logger.error(f"Error in coin analysis: {e}")
                return jsonify({"error": f"Analysis failed: {str(e)}"}), 500
                
    except Exception as e:
        logger.error(f"Error in coin analysis endpoint: {e}")
        return jsonify({"error": str(e)}), 500


# NEW AI TRADING DASHBOARD ENDPOINTS - 3-STAGE AGENTIC WORKFLOWS

@ai_bp.route('/api/ai/market-analysis-workflow', methods=['GET'])
@login_required
def api_market_analysis_workflow():
    """Execute 3-stage agentic Market Analysis workflow using user's custom prompts"""
    try:
        from datetime import timedelta
        from models import AIConversation
        username = current_user.username
        user_id = current_user.id
        
        # Get user's AI settings for cache and analysis window
        user_settings = get_user_ai_settings(username)
        cache_duration_hours = user_settings.get('ai_cache_duration_hours', 4)
        analysis_window_start = user_settings.get('ai_analysis_window_start', '08:00')
        analysis_window_end = user_settings.get('ai_analysis_window_end', '23:59')
        
        logger.info(f"[AI_DEBUG] Settings for {username}: Window={analysis_window_start}-{analysis_window_end}, Cache={cache_duration_hours}h")
        
        # Check if we're in the analysis window (unless manual request)
        manual_request = request.args.get('manual', 'false').lower() == 'true'
        if not manual_request and not is_user_analysis_window_active(analysis_window_start, analysis_window_end):
            logger.info(f"[AI_DEBUG] User {username} outside analysis window ({analysis_window_start}-{analysis_window_end})")
            
            # Identify most recent cache (expired or not) to show instead of blank
            last_conv = AIConversation.query.filter_by(
                user_id=user_id, 
                prompt_type='market_analysis_workflow',
                sender='ai'
            ).order_by(AIConversation.created_at.desc()).first()
            
            if last_conv:
                try:
                    cached_data = json.loads(last_conv.body)
                    cached_data['cache_info'] = {
                        "status": "expired_window_inactive",
                        "cached_at": last_conv.created_at.isoformat(),
                        "expires_at": (last_conv.created_at + timedelta(hours=cache_duration_hours)).isoformat()
                    }
                    return jsonify(cached_data)
                except:
                    pass

            return jsonify({
                "success": False,
                "message": f"Analysis window: {analysis_window_start} - {analysis_window_end}. Use manual refresh for off-hours analysis.",
                "stage1": {"status": "skipped", "reason": "outside_analysis_window"},
                "stage2": {"status": "skipped", "reason": "outside_analysis_window"},
                "stage3": {"status": "skipped", "reason": "outside_analysis_window"},
                "cache_info": {"status": "analysis_window_inactive"}
            })
        
        # Check 4-hour scheduling (unless manual request)
        if not manual_request and not should_run_ai_analysis(user_id):
            logger.info(f"[AI_DEBUG] User {username} skipped due to schedule (run recently)")
            
            # Identify most recent cache (expired or not) to show instead of blank
            last_conv = AIConversation.query.filter_by(
                user_id=user_id, 
                prompt_type='market_analysis_workflow',
                sender='ai'
            ).order_by(AIConversation.created_at.desc()).first()
            
            if last_conv:
                try:
                    cached_data = json.loads(last_conv.body)
                    cached_data['cache_info'] = {
                        "status": "expired_schedule_blocked",
                        "cached_at": last_conv.created_at.isoformat(),
                        "expires_at": (last_conv.created_at + timedelta(hours=cache_duration_hours)).isoformat()
                    }
                    return jsonify(cached_data)
                except:
                    pass

            return jsonify({
                "success": False,
                "message": f"AI analysis scheduled every {cache_duration_hours} hours. Use manual refresh to run immediately.",
                "stage1": {"status": "skipped", "reason": "schedule_not_ready"},
                "stage2": {"status": "skipped", "reason": "schedule_not_ready"},
                "stage3": {"status": "skipped", "reason": "schedule_not_ready"},
                "cache_info": {"status": "schedule_blocked"}
            })
        
        # Check cache unless manual request
        if not manual_request:
            # Check for recent cached analysis
            from datetime import timedelta
            cache_timestamp = datetime.utcnow() - timedelta(hours=cache_duration_hours)
            
            # models imported at top
            cached_result = AIConversation.query.filter(
                AIConversation.user_id == user_id,
                AIConversation.prompt_type == 'market_analysis_workflow',
                AIConversation.sender == 'ai',
                AIConversation.created_at > cache_timestamp
            ).order_by(AIConversation.created_at.desc()).first()
            
            if cached_result:
                logger.info(f"[AI_DEBUG] Cache HIT for {username}")
                try:
                    cached_data = json.loads(cached_result.body)
                    cached_data['cache_info'] = {
                        "status": "cache_hit",
                        "cached_at": cached_result.created_at.isoformat(),
                        "expires_at": (cached_result.created_at + timedelta(hours=cache_duration_hours)).isoformat()
                    }
                    return jsonify(cached_data)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse cached market analysis for user {user_id}")
            else:
                logger.info(f"[AI_DEBUG] Cache MISS for {username}")
        
        logger.info(f"=== MARKET ANALYSIS WORKFLOW START - User: {username} ===")
        
        # Capture the start time for accurate "generated_at" timestamp
        analysis_start_time = get_eastern_now_iso()
        
        # Execute 3-stage agentic workflow for market analysis
        # NOTE: call_ai_with_web_search will use the proper database prompts from ai_prompts table
        # We just need to provide a simple trigger message to start the workflow
        market_analysis_messages = [
            {
                "role": "user",
                "content": "Market analysis request"  # This gets replaced by the actual Stage 3 prompt
            }
        ]
        
        # Execute the agentic workflow - this will return response and actual Stage 3 prompt
        response, actual_user_prompt = call_ai_with_web_search(
            username=username,
            messages=market_analysis_messages,
            user_id=user_id,
            prompt_type='market_analysis',  # Uses market_analysis_pre and market_analysis_post from database
            symbol=None,
            model=None  # Use user's preferred model
        )
        
        # Extract the analysis content
        if hasattr(response, 'choices') and response.choices:
            analysis_content = response.choices[0].message.content
        else:
            raise Exception("Invalid AI response format")
        
        # Structure the response with workflow stages
        workflow_result = {
            "success": True,
            "timestamp": get_eastern_now().isoformat(),
            "stage1": {
                "status": "completed",
                "description": "Data Gathering - Generated targeted search queries for current market information"
            },
            "stage2": {
                "status": "completed", 
                "description": "Web Search - Executed searches for real-time market data and news"
            },
            "stage3": {
                "status": "completed",
                "description": "Analysis Synthesis - Combined search results with user prompts for comprehensive analysis",
                "content": analysis_content
            },
            "analysis": {
                "content": analysis_content,
                "type": "market_analysis",
                "generated_at": analysis_start_time
            },
            "cache_info": {
                "status": "fresh_analysis",
                "generated_at": analysis_start_time,
                "expires_at": (get_eastern_now() + timedelta(hours=cache_duration_hours)).isoformat()
            }
        }
        
        # Save conversations to AI Copilot sidebar using the ACTUAL Stage 3 prompt
        try:
            import time
            
            # Use the ACTUAL Stage 3 prompt that was sent to AI (not hardcoded)
            # Log user message first 
            log_ai_conversation(user_id, "market_analysis", "user", actual_user_prompt)
            
            # Add small delay to ensure proper chronological order
            time.sleep(0.1)
            
            # Then log ai response 
            log_ai_conversation(user_id, "market_analysis", "ai", analysis_content)
            
            logger.info(f"Market analysis conversations saved to AI Copilot for user {user_id}")
            
        except Exception as conversation_error:
            logger.error(f"Failed to save market analysis conversations: {conversation_error}")
        
        # Store workflow result in AIConversation table for caching only
        try:
            now = get_eastern_now()
            ai_conversation = AIConversation(
                user_id=user_id,
                date=now.strftime('%Y-%m-%d'),
                time=now.strftime('%I:%M %p %Z'),
                prompt_type='market_analysis_workflow',
                sender='ai',
                body=json.dumps(workflow_result),
                created_at=now,
                is_hidden=1  # Hidden from AI Copilot since it's already saved by log_ai_conversation
            )
            db.session.add(ai_conversation)
            db.session.commit()
            logger.info(f"Market analysis workflow cache stored for user {user_id}")
            
            # Update the AI analysis schedule based on user settings
            update_ai_analysis_schedule(user_id)
            
        except Exception as db_error:
            logger.error(f"Failed to store market analysis cache: {db_error}")
            # Continue without caching
        
        logger.info(f"=== MARKET ANALYSIS WORKFLOW COMPLETE - User: {username} ===")
        return jsonify(workflow_result)
        
    except Exception as e:
        logger.error(f"Market analysis workflow error for user {username}: {e}")
        try:
            db.session.rollback()
        except:
            pass
        return jsonify({
            "success": False,
            "error": str(e),
            "stage1": {"status": "failed", "error": str(e)},
            "stage2": {"status": "failed", "error": str(e)},
            "stage3": {"status": "failed", "error": str(e)},
            "cache_info": {"status": "error"}
        }), 500


@ai_bp.route('/api/ai/risk-assessment-workflow', methods=['GET'])
@login_required
def api_risk_assessment_workflow():
    """Execute 3-stage agentic Risk Assessment workflow using user's custom prompts"""
    try:
        from datetime import timedelta
        from models import AIConversation
        username = current_user.username
        user_id = current_user.id
        manual_request = request.args.get('manual', 'false').lower() == 'true'
        user_settings = get_user_ai_settings(username)
        cache_duration_hours = user_settings.get('ai_cache_duration_hours', 4)

        # Always run for manual requests, otherwise check schedule/cache
        if not manual_request:
            if not should_run_ai_analysis(user_id):
                # Identify most recent cache (expired or not) to show instead of blank
                last_conv = AIConversation.query.filter_by(
                    user_id=user_id, 
                    prompt_type='risk_assessment_workflow',
                    sender='ai'
                ).order_by(AIConversation.created_at.desc()).first()
                
                if last_conv:
                    try:
                        cached_data = json.loads(last_conv.body)
                        cached_data['cache_info'] = {
                            "status": "expired_schedule_blocked",
                            "cached_at": last_conv.created_at.isoformat(),
                            "expires_at": (last_conv.created_at + timedelta(hours=cache_duration_hours)).isoformat()
                        }
                        return jsonify(cached_data)
                    except:
                        pass
                
                return jsonify({
                    "success": False,
                    "message": f"AI analysis scheduled every {cache_duration_hours} hours. Use manual refresh to run immediately.",
                    "stage1": {"status": "skipped", "reason": "schedule_not_ready"},
                    "stage2": {"status": "skipped", "reason": "schedule_not_ready"},
                    "stage3": {"status": "skipped", "reason": "schedule_not_ready"},
                    "cache_info": {"status": "schedule_blocked"}
                })
            cache_timestamp = datetime.now() - timedelta(hours=cache_duration_hours)
            cached_result = db.session.query(AIConversation).filter(
                AIConversation.user_id == user_id,
                AIConversation.prompt_type == 'risk_assessment_workflow',
                AIConversation.sender == 'ai',
                AIConversation.created_at > cache_timestamp
            ).order_by(AIConversation.created_at.desc()).first()
            if cached_result:
                try:
                    cached_data = json.loads(cached_result.body)
                    cached_data['cache_info'] = {
                        "status": "cache_hit",
                        "cached_at": cached_result.created_at.isoformat(),
                        "expires_at": (cached_result.created_at + timedelta(hours=cache_duration_hours)).isoformat()
                    }
                    return jsonify(cached_data)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse cached risk assessment for user {user_id}")

        logger.info(f"=== RISK ASSESSMENT WORKFLOW START - User: {username} ===")
        analysis_start_time = get_eastern_now_iso()

        # === STAGE 1: Send risk_assessment_pre to AI ===
        ai_prompts = get_user_ai_prompts(user_id)
        if not ai_prompts or not ai_prompts.risk_assessment_pre:
            raise Exception("No risk_assessment_pre prompt configured for this user.")
        stage1_prompt = ai_prompts.risk_assessment_pre
        stage1_messages = [{"role": "system", "content": stage1_prompt}]
        # Send to AI (Stage 1)
        stage1_response, _ = call_ai_with_web_search(
            username=username,
            messages=stage1_messages,
            user_id=user_id,
            prompt_type='risk_assessment',
            symbol=None,
            model=None
        )
        if hasattr(stage1_response, 'choices') and stage1_response.choices:
            stage1_content = stage1_response.choices[0].message.content
        else:
            raise Exception("Invalid AI response format at Stage 1")

        # === STAGE 2: Brave search + coin data + risk_assessment_post ===
        # Gather non-stablecoin, non-hidden coins
        from models import Coin
        coins = Coin.query.filter_by(user_id=user_id, hidden=False).all()
        non_stablecoins = [c for c in coins if not is_stablecoin(c.symbol)]
        coin_data_lines = []
        for c in non_stablecoins:
            amount = float(c.amount or 0.0)
            current_price = float(c.current or 0.0)
            current_value = current_price * amount
            coin_data_lines.append(
                f"{c.symbol}: {amount:.6f} (value: ${current_value:,.2f} @ ${current_price:.4f})"
            )
        coin_data = "\n".join(coin_data_lines)

        # Use Brave search results from Stage 1 (already included in call_ai_with_web_search context)
        if not ai_prompts.risk_assessment_post:
            raise Exception("No risk_assessment_post prompt configured for this user.")
        stage2_prompt = ai_prompts.risk_assessment_post
        # Combine context
        stage2_context = f"{stage2_prompt}\n\nUSER COIN DATA:\n{coin_data if coin_data else 'No non-stablecoin holdings.'}"
        stage2_messages = [
            {"role": "system", "content": stage2_context},
            {"role": "user", "content": stage1_content}
        ]
        # Send to AI (Stage 2)
        stage2_response, actual_user_prompt = call_ai_with_web_search(
            username=username,
            messages=stage2_messages,
            user_id=user_id,
            prompt_type='risk_assessment',
            symbol=None,
            model=None
        )
        if hasattr(stage2_response, 'choices') and stage2_response.choices:
            analysis_content = stage2_response.choices[0].message.content
        else:
            raise Exception("Invalid AI response format at Stage 2")

        # === LOGGING ===
        import time
        log_ai_conversation(user_id, "risk_assessment", "user", actual_user_prompt)
        time.sleep(0.1)
        log_ai_conversation(user_id, "risk_assessment", "ai", analysis_content)

        # === RESPONSE ===
        workflow_result = {
            "success": True,
            "timestamp": get_eastern_now().isoformat(),
            "stage1": {
                "status": "completed",
                "description": "Sent risk_assessment_pre to AI"
            },
            "stage2": {
                "status": "completed",
                "description": "Brave search + coin data + risk_assessment_post sent to AI"
            },
            "stage3": {
                "status": "completed",
                "description": "AI generated holistic risk assessment",
                "content": analysis_content
            },
            "analysis": {
                "content": analysis_content,
                "type": "risk_assessment",
                "generated_at": analysis_start_time
            },
            "cache_info": {
                "status": "fresh_analysis",
                "generated_at": analysis_start_time,
                "expires_at": (get_eastern_now() + timedelta(hours=cache_duration_hours)).isoformat()
            }
        }

        # Store workflow result in AIConversation table for caching only
        try:
            now = get_eastern_now()
            ai_conversation = AIConversation(
                user_id=user_id,
                date=now.strftime('%Y-%m-%d'),
                time=now.strftime('%I:%M %p %Z'),
                prompt_type='risk_assessment_workflow',
                sender='ai',
                body=json.dumps(workflow_result),
                created_at=now,
                is_hidden=1
            )
            db.session.add(ai_conversation)
            db.session.commit()
            logger.info(f"Risk assessment workflow cache stored for user {user_id}")
            update_ai_analysis_schedule(user_id)
        except Exception as db_error:
            logger.error(f"Failed to store risk assessment cache: {db_error}")

        logger.info(f"=== RISK ASSESSMENT WORKFLOW COMPLETE - User: {username} ===")
        return jsonify(workflow_result)

    except Exception as e:
        logger.error(f"Risk assessment workflow error for user {username}: {e}")
        try:
            db.session.rollback()
        except:
            pass
        return jsonify({
            "success": False,
            "error": str(e),
            "stage1": {"status": "failed", "error": str(e)},
            "stage2": {"status": "failed", "error": str(e)},
            "stage3": {"status": "failed", "error": str(e)},
            "cache_info": {"status": "error"}
        }), 500


@ai_bp.route('/api/ai/portfolio-review-workflow', methods=['GET', 'POST'])
@login_required
def api_portfolio_review_workflow():
    """Trigger Portfolio Review workflow and return immediate response to avoid timeout"""
    try:
        from datetime import timedelta
        from models import AIConversation
        username = current_user.username
        user_id = current_user.id
        manual_request = request.args.get('manual', 'false').lower() == 'true'
        user_settings = get_user_ai_settings(username)
        cache_duration_hours = user_settings.get('ai_cache_duration_hours', 4)
        analysis_window_start = user_settings.get('ai_analysis_window_start', '08:00')
        analysis_window_end = user_settings.get('ai_analysis_window_end', '23:59')

        # Always run for manual requests, otherwise check schedule/cache
        if not manual_request:
            if not is_user_analysis_window_active(analysis_window_start, analysis_window_end):
                # Identify most recent cache (expired or not) to show instead of blank
                last_conv = AIConversation.query.filter_by(
                    user_id=user_id, 
                    prompt_type='portfolio_review_workflow',
                    sender='ai'
                ).order_by(AIConversation.created_at.desc()).first()
                if last_conv:
                    try:
                        cached_data = json.loads(last_conv.body)
                        cached_data['cache_info'] = {
                            "status": "expired_window_inactive",
                            "cached_at": last_conv.created_at.isoformat(),
                            "expires_at": (last_conv.created_at + timedelta(hours=cache_duration_hours)).isoformat()
                        }
                        return jsonify(cached_data)
                    except:
                        pass
                return jsonify({
                    "success": False,
                    "message": f"Analysis window: {analysis_window_start} - {analysis_window_end}. Use manual refresh for off-hours analysis.",
                    "status": "outside_window"
                })
            
            if not should_run_ai_analysis(user_id):
                # Identify most recent cache (expired or not) to show instead of blank
                last_conv = AIConversation.query.filter_by(
                    user_id=user_id, 
                    prompt_type='portfolio_review_workflow',
                    sender='ai'
                ).order_by(AIConversation.created_at.desc()).first()
                if last_conv:
                    try:
                        cached_data = json.loads(last_conv.body)
                        cached_data['cache_info'] = {
                            "status": "expired_schedule_blocked",
                            "cached_at": last_conv.created_at.isoformat(),
                            "expires_at": (last_conv.created_at + timedelta(hours=cache_duration_hours)).isoformat()
                        }
                        return jsonify(cached_data)
                    except:
                        pass
                return jsonify({
                    "success": False,
                    "message": f"AI analysis scheduled every {cache_duration_hours} hours. Use manual refresh to run immediately.",
                    "status": "schedule_blocked"
                })
            cache_timestamp = datetime.now() - timedelta(hours=cache_duration_hours)
            cached_result = db.session.query(AIConversation).filter(
                AIConversation.user_id == user_id,
                AIConversation.prompt_type == 'portfolio_review_workflow',
                AIConversation.sender == 'ai',
                AIConversation.created_at > cache_timestamp
            ).order_by(AIConversation.created_at.desc()).first()
            if cached_result:
                try:
                    cached_data = json.loads(cached_result.body)
                    eastern_time = get_eastern_datetime(cached_result.created_at)
                    cached_data['timestamp'] = format_eastern_datetime_ampm(eastern_time)
                    cached_data['status'] = 'cache_hit'
                    if 'analysis' in cached_data and 'generated_at' in cached_data['analysis']:
                        cached_data['analysis']['generated_at'] = format_eastern_datetime_ampm(eastern_time)
                    return jsonify(cached_data)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse cached portfolio review for user {user_id}")

        logger.info(f"=== PORTFOLIO REVIEW WORKFLOW START (SYNC) - User: {username} ===")
        analysis_start_time = get_eastern_now_iso()

        # === STAGE 1: Send portfolio_review_pre to AI ===
        ai_prompts = get_user_ai_prompts(user_id)
        if not ai_prompts or not ai_prompts.portfolio_review_pre:
            raise Exception("No portfolio_review_pre prompt configured for this user.")
        stage1_prompt = ai_prompts.portfolio_review_pre
        stage1_messages = [
            {"role": "user", "content": stage1_prompt}
        ]
        # Send to AI (Stage 1)
        stage1_response, _ = call_ai_with_web_search(
            username=username,
            messages=stage1_messages,
            user_id=user_id,
            prompt_type='portfolio_review',
            symbol=None,
            model=None
        )
        if hasattr(stage1_response, 'choices') and stage1_response.choices:
            stage1_content = stage1_response.choices[0].message.content
        else:
            raise Exception("Invalid AI response format at Stage 1")

        # === STAGE 2: Brave search + coin data + portfolio_review_post ===
        from models import Coin
        coins = Coin.query.filter_by(user_id=user_id, hidden=False).all()
        non_stablecoins = [c for c in coins if not is_stablecoin(c.symbol)]
        coin_data = "\n".join([f"{c.symbol}: {c.amount} (value: ${c.amount * c.current if c.current else 0:.2f})" for c in non_stablecoins])

        if not ai_prompts.portfolio_review_post:
            raise Exception("No portfolio_review_post prompt configured for this user.")
        stage2_prompt = ai_prompts.portfolio_review_post
        stage2_context = f"{stage2_prompt}\n\nUSER COIN DATA:\n{coin_data if coin_data else 'No non-stablecoin holdings.'}"
        stage2_messages = [
            {"role": "system", "content": stage2_context},
            {"role": "user", "content": stage1_content}
        ]
        # Send to AI (Stage 2)
        stage2_response, actual_user_prompt = call_ai_with_web_search(
            username=username,
            messages=stage2_messages,
            user_id=user_id,
            prompt_type='portfolio_review',
            symbol=None,
            model=None
        )
        if hasattr(stage2_response, 'choices') and stage2_response.choices:
            analysis_content = stage2_response.choices[0].message.content
        else:
            raise Exception("Invalid AI response format at Stage 2")

        # === LOGGING ===
        import time
        log_ai_conversation(user_id, "portfolio_review", "user", actual_user_prompt)
        time.sleep(0.1)
        log_ai_conversation(user_id, "portfolio_review", "ai", analysis_content)

        # === RESPONSE ===
        workflow_result = {
            "success": True,
            "timestamp": get_eastern_now().isoformat(),
            "stage1": {
                "status": "completed",
                "description": "Sent portfolio_review_pre to AI"
            },
            "stage2": {
                "status": "completed",
                "description": "Brave search + coin data + portfolio_review_post sent to AI"
            },
            "stage3": {
                "status": "completed",
                "description": "AI generated holistic portfolio review",
                "content": analysis_content
            },
            "analysis": {
                "content": analysis_content,
                "type": "portfolio_review",
                "generated_at": analysis_start_time
            },
            "status": "completed"
        }

        # Store workflow result in AIConversation table for caching
        try:
            now = get_eastern_now()
            ai_conversation = AIConversation(
                user_id=user_id,
                date=now.strftime('%Y-%m-%d'),
                time=now.strftime('%I:%M %p %Z'),
                prompt_type='portfolio_review_workflow',
                sender='ai',
                body=json.dumps(workflow_result),
                created_at=now,
                is_hidden=1
            )
            db.session.add(ai_conversation)
            db.session.commit()
            logger.info(f"Portfolio review workflow cache stored for user {user_id}")
            update_ai_analysis_schedule(user_id)
            logger.info(f"Next analysis scheduled for user {user_id}")
        except Exception as db_error:
            logger.error(f"Failed to store portfolio review cache: {db_error}")

        logger.info(f"=== PORTFOLIO REVIEW WORKFLOW COMPLETE (SYNC) - User: {username} ===")
        return jsonify(workflow_result)

    except Exception as e:
        logger.error(f"Portfolio review workflow error for user {username}: {e}", exc_info=True)
        try:
            db.session.rollback()
        except:
            pass
        return jsonify({
            "success": False,
            "error": str(e),
            "timestamp": get_eastern_now().isoformat(),
            "stage1": {
                "status": "failed",
                "description": f"Portfolio review failed: {str(e)}"
            },
            "stage2": {"status": "skipped", "description": "Skipped due to error"},
            "stage3": {"status": "failed", "description": "Analysis failed"},
            "analysis": None,
            "status": "error"
        }), 500

        


@ai_bp.route('/api/ai/portfolio-review-results', methods=['GET'])
@login_required
def api_portfolio_review_results():
    """Get cached Portfolio Review results without triggering new analysis"""
    try:
        from datetime import timedelta
        username = current_user.username
        user_id = current_user.id
        
        # Get user's AI settings for cache duration
        user_settings = get_user_ai_settings(username)
        cache_duration_hours = user_settings.get('ai_cache_duration_hours', 4)
        
        # Look for recent cached results
        cache_timestamp = datetime.now() - timedelta(hours=cache_duration_hours)
        cached_result = db.session.query(AIConversation).filter(
            AIConversation.user_id == user_id,
            AIConversation.prompt_type == 'portfolio_review_workflow',
            AIConversation.sender == 'ai',
            AIConversation.created_at > cache_timestamp
        ).order_by(AIConversation.created_at.desc()).first()
        
        if cached_result:
            try:
                cached_data = json.loads(cached_result.body)
                # Fix timezone - convert UTC created_at to Eastern time with AM/PM format
                eastern_time = get_eastern_datetime(cached_result.created_at)
                cached_data['timestamp'] = format_eastern_datetime_ampm(eastern_time)
                if 'analysis' in cached_data and 'generated_at' in cached_data['analysis']:
                    cached_data['analysis']['generated_at'] = format_eastern_datetime_ampm(eastern_time)
                if 'cache_info' in cached_data:
                    cached_data['cache_info']['generated_at'] = format_eastern_datetime_ampm(eastern_time)
                    cached_data['cache_info']['expires_at'] = (eastern_time + timedelta(hours=cache_duration_hours)).isoformat()
                
                return jsonify(cached_data)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse cached portfolio review for user {user_id}")
        
        # No cached results found
        return jsonify({
            "success": False,
            "message": "No recent portfolio review found. Click 'Refresh Portfolio Review' to generate new analysis.",
            "cache_info": {"status": "no_cache"}
        })
        
    except Exception as e:
        logger.error(f"Portfolio review results error for user {username}: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "cache_info": {"status": "error"}
        }), 500


@ai_bp.route('/api/ai/copilot-results', methods=['GET'])
@login_required
def api_ai_copilot_results():
    """Consolidate all three workflow results for AI Copilot sidebar with proper formatting"""
    try:
        username = current_user.username
        user_id = current_user.id
        
        # Get recent workflow results from the last 24 hours
        since_timestamp = datetime.now() - timedelta(hours=24)
        
        # Query all three workflow types
        workflow_conversations = db.session.query(AIConversation).filter(
            AIConversation.user_id == user_id,
            AIConversation.prompt_type.in_(['market_analysis_workflow', 'risk_assessment_workflow', 'portfolio_review_workflow']),
            AIConversation.sender == 'ai',
            AIConversation.created_at > since_timestamp,
            AIConversation.is_hidden == 0
        ).order_by(AIConversation.created_at.desc()).all()
        
        copilot_messages = []
        
        # Process each workflow result for copilot display
        for conversation in workflow_conversations:
            try:
                workflow_data = json.loads(conversation.body)
                
                # Extract workflow type and content
                workflow_type = conversation.prompt_type.replace('_workflow', '').replace('_', ' ').title()
                analysis_content = workflow_data.get('analysis', {}).get('content', '')
                
                if analysis_content:
                    # Format as user request followed by AI response
                    user_request = f"Run {workflow_type} using the 3-stage agentic workflow"
                    
                    # Add user message
                    copilot_messages.append({
                        "sender": "user",
                        "body": user_request,
                        "created_at": conversation.created_at.isoformat(),
                        "workflow_type": conversation.prompt_type,
                        "display_type": "workflow_request"
                    })
                    
                    # Add AI response with workflow info
                    ai_response_body = f"🤖 **{workflow_type} Complete** (3-Stage Agentic Workflow)\n\n"
                    
                    # Add stage information
                    if workflow_data.get('stage1', {}).get('status') == 'completed':
                        ai_response_body += "✅ **Stage 1:** " + workflow_data['stage1'].get('description', 'Data gathering completed') + "\n"
                    if workflow_data.get('stage2', {}).get('status') == 'completed':
                        ai_response_body += "✅ **Stage 2:** " + workflow_data['stage2'].get('description', 'Web search completed') + "\n"
                    if workflow_data.get('stage3', {}).get('status') == 'completed':
                        ai_response_body += "✅ **Stage 3:** " + workflow_data['stage3'].get('description', 'Analysis completed') + "\n\n"
                    
                    # Add analysis content (truncated for sidebar)
                    if len(analysis_content) > 500:
                        ai_response_body += analysis_content[:500] + "...\n\n*Click to view full analysis*"
                    else:
                        ai_response_body += analysis_content
                    
                    # Add cache information
                    cache_info = workflow_data.get('cache_info', {})
                    if cache_info.get('expires_at'):
                        expires_at = datetime.fromisoformat(cache_info['expires_at'].replace('Z', '+00:00'))
                        ai_response_body += f"\n\n📅 *Cache expires: {expires_at.strftime('%m/%d %I:%M %p')}*"
                    
                    copilot_messages.append({
                        "sender": "agent",
                        "body": ai_response_body,
                        "created_at": conversation.created_at.isoformat(),
                        "workflow_type": conversation.prompt_type,
                        "display_type": "workflow_response",
                        "full_content": analysis_content,
                        "cache_expires": cache_info.get('expires_at')
                    })
                    
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to parse workflow conversation {conversation.id}: {e}")
                continue
        
        # Sort messages chronologically (oldest first for proper conversation flow)
        copilot_messages.sort(key=lambda x: x['created_at'])
        
        # Add summary statistics
        workflow_stats = {
            "total_workflows": len(workflow_conversations),
            "market_analysis_count": len([c for c in workflow_conversations if c.prompt_type == 'market_analysis_workflow']),
            "risk_assessment_count": len([c for c in workflow_conversations if c.prompt_type == 'risk_assessment_workflow']),
            "portfolio_review_count": len([c for c in workflow_conversations if c.prompt_type == 'portfolio_review_workflow']),
            "time_range": "24 hours",
            "last_updated": get_eastern_now().isoformat()
        }
        
        # --- Add full transaction history for Copilot deep queries ---
        # Use get_comprehensive_crypto_data_for_user with no transaction limit
        try:
            full_crypto_data = get_comprehensive_crypto_data_for_user(user_id, limit_transactions=1000000, days_history=3650)  # 10+ years, all txns
            all_transactions = full_crypto_data.get("recent_transactions", [])
        except Exception as e:
            logger.error(f"Failed to get full transaction history for Copilot: {e}")
            all_transactions = []

        response_data = {
            "success": True,
            "messages": copilot_messages,
            "stats": workflow_stats,
            "timestamp": get_eastern_now().isoformat(),
            "all_transactions": all_transactions  # <-- Full transaction history for Copilot sidebar
        }

        logger.info(f"AI Copilot results compiled for user {username}: {len(copilot_messages)} messages from {len(workflow_conversations)} workflows, {len(all_transactions)} transactions included")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"AI Copilot results error for user {username}: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "messages": [],
            "stats": {},
            "timestamp": get_eastern_now().isoformat()
        }), 500