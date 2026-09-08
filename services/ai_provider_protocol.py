"""Gemini wire format and safe, structured errors shared by AI integrations.

References: ai.google.dev/gemini-api/docs/generate-content/thinking and
docs.ollama.com/api/errors. Never put provider credentials in error messages.
"""
import re
from urllib.parse import quote

import requests

from services.portfolio_audit_context import CompletionText


def safe_provider_error(value, secrets=()):
    detail = str(value)
    for secret in secrets:
        if secret:
            detail = detail.replace(str(secret), '[redacted]')
    detail = re.sub(r'(?i)([?&]key=|x-goog-api-key[\s\"\x27:=]+|Bearer\s+)[^\s&\"\x27]+', r'\1[redacted]', detail)
    return detail[:1200]


class AIProviderHTTPError(RuntimeError):
    def __init__(self, provider, response, secrets=()):
        self.status_code = response.status_code
        self.response = response
        super().__init__(safe_provider_error(
            f'{provider} HTTP {self.status_code}: {response.text or "No error body"}', secrets))


def gemini_generation_config(model, max_tokens, reasoning_level):
    config = {'maxOutputTokens': max(1, int(max_tokens))}
    level = str(reasoning_level or 'medium').lower().replace('_', ' ').strip()
    level = {'light': 'low', 'extra high': 'high', 'max': 'high'}.get(level, level)
    if level not in ('low', 'medium', 'high'):
        level = 'medium'
    name = str(model).lower().removeprefix('models/')
    if re.match(r'gemini-[3-9](?:[.-]|$)', name):
        # Gemini 3 Pro supports low/high; Flash also supports medium.
        if 'pro' in name and level == 'medium':
            level = 'high'
        config['thinkingConfig'] = {'thinkingLevel': level}
    elif '2.5' in name or 'thinking' in name:
        config['thinkingConfig'] = {'thinkingBudget': {'low': 1024, 'medium': 2048, 'high': 4096}[level]}
    return config


def call_gemini_chat(api_key, model, messages, max_tokens, timeout, reasoning_level=None):
    if not api_key:
        raise ValueError('Gemini API key not configured')
    model = str(model or '').strip().removeprefix('models/')
    if not model:
        raise ValueError('Gemini model is required')
    payload = {'contents': [], 'generationConfig': gemini_generation_config(model, max_tokens, reasoning_level)}
    systems = []
    for message in messages:
        role, content = message.get('role'), message.get('content', '')
        if role == 'system':
            systems.append({'text': content})
        elif role in ('user', 'assistant'):
            payload['contents'].append({'role': 'model' if role == 'assistant' else 'user', 'parts': [{'text': content}]})
    if systems:
        payload['systemInstruction'] = {'parts': systems}
    response = requests.post(
        f'https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe="")}:generateContent',
        headers={'x-goog-api-key': api_key, 'Content-Type': 'application/json'},
        json=payload, timeout=(10, timeout),
    )
    try:
        if response.status_code != 200:
            raise AIProviderHTTPError('Gemini', response, (api_key,))
        result = response.json()
        candidates = result.get('candidates') or []
        if not candidates:
            reason = (result.get('promptFeedback') or {}).get('blockReason', 'no candidates')
            raise ValueError(f'Gemini returned no answer ({reason})')
        candidate = candidates[0]
        content = ''.join(p.get('text', '') for p in (candidate.get('content') or {}).get('parts', []) if not p.get('thought'))
        return CompletionText(content, candidate.get('finishReason'), final_answer=bool(content.strip()))
    finally:
        response.close()
