"""Jev native HTTP transport. No sentiment, trading, or database dependencies."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import math
import random
import threading
import time

import requests
from services.jev_settings import DEFAULT_ENDPOINT, validate_endpoint


class JevError(Exception):
    def __init__(self, code, latency_ms=0):
        self.code = code
        self.latency_ms = latency_ms
        super().__init__({'auth': 'Vercel rejected the API key.', 'timeout': 'Jev request timed out.',
                         'cooldown': 'Jev is cooling down after repeated failures.',
                         'missing_key': 'Save a Vercel AI Gateway API key first.',
                         'invalid_response': 'Jev returned an invalid or incomplete evaluation.'}.get(code, 'Jev evaluation unavailable.'))


@dataclass
class JevEvaluationResult:
    answers: dict
    raw_response: dict
    model: str
    provider: str
    transport: str
    latency_ms: int
    usage: dict | None
    estimated_cost_usd: Decimal | None
    confidence: dict


def number(value, low=0, high=1):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise JevError('invalid_response')
    return value


def validate_answers(payload, questions):
    try:
        answers = payload['answers']
        for key, question in questions.items():
            answer = answers[key]
            kind = question['type']
            if answer['type'] != kind:
                raise JevError('invalid_response')
            if kind == 'boolean':
                number(answer['probability'])
            else:
                expected = set(question['criteria']) if kind == 'choice' else {str(i) for i in range(len(question['criteria']))}
                probs = answer['probabilities']
                if not isinstance(probs, dict) or set(probs) != expected:
                    raise JevError('invalid_response')
                if abs(sum(number(v) for v in probs.values()) - 1) > 0.02:
                    raise JevError('invalid_response')
                if kind == 'choice' and answer['choice'] not in expected:
                    raise JevError('invalid_response')
                if kind == 'score':
                    number(answer['score'], 0, len(expected)-1)
        return {key: answers[key] for key in questions}
    except (KeyError, TypeError, AttributeError):
        raise JevError('invalid_response') from None


class JevClient:
    _failures = {}
    _lock = threading.Lock()

    def __init__(self, api_key, endpoint=DEFAULT_ENDPOINT, model='typesafe-ai/jev', timeout_seconds=3.0):
        self.key = api_key
        self.endpoint = validate_endpoint(endpoint)
        self.model = model
        self.timeout = timeout_seconds

    def evaluate(self, *, state, questions, model=None, timeout_seconds=None):
        started = time.monotonic()
        latency = lambda: int((time.monotonic()-started)*1000)
        if not self.key:
            raise JevError('missing_key')
        bucket = hashlib.sha256((self.endpoint+self.key).encode()).hexdigest()
        with self._lock:
            count, until = self._failures.get(bucket, (0, 0))
        if until > started:
            raise JevError('cooldown')
        budget = min(15, max(0.25, float(timeout_seconds or self.timeout)))
        deadline = started + budget
        code = 'network'
        for attempt in range(2):
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                code = 'timeout'
                break
            try:
                response = requests.post(self.endpoint,
                    headers={'Authorization': f'Bearer {self.key}', 'Content-Type': 'application/json'},
                    json={'model': model or self.model, 'state': state, 'questions': questions,
                          'providerOptions': {'gateway': {'zeroDataRetention': True}}},
                    timeout=(remaining/2, remaining/2), allow_redirects=False)
                status = response.status_code
                if status == 200:
                    try:
                        payload = response.json()
                        answers = validate_answers(payload, questions)
                        metadata = payload.get('providerMetadata') or {}
                        gateway = metadata.get('gateway') or {}
                        confidence = (metadata.get('typesafe') or {}).get('confidence') or {}
                        if not isinstance(confidence, dict):
                            raise JevError('invalid_response')
                        for value in confidence.values():
                            number(value)
                        cost = Decimal(str(gateway['cost'])) if gateway.get('cost') is not None else None
                        if cost is not None and (not cost.is_finite() or cost < 0):
                            raise JevError('invalid_response')
                        actual_model = payload.get('model', model or self.model)
                        if not isinstance(actual_model, str) or len(actual_model) > 100:
                            raise JevError('invalid_response')
                        usage = payload.get('usage')
                        if usage is not None and not isinstance(usage, dict):
                            raise JevError('invalid_response')
                    except (ValueError, TypeError, AttributeError, InvalidOperation):
                        raise JevError('invalid_response') from None
                    with self._lock:
                        type(self)._failures.pop(bucket, None)
                    return JevEvaluationResult(answers, payload, actual_model, 'typesafe-ai', 'vercel', latency(), usage, cost, confidence)
                code = 'auth' if status in (401, 403) else f'http_{status}'
                if status not in (408, 429, 500, 502, 503, 504):
                    break
            except JevError as exc:
                exc.latency_ms = latency()
                raise
            except requests.Timeout:
                code = 'timeout'
            except requests.RequestException:
                code = 'network'
            if attempt == 0:
                delay = min(0.1 + random.random()*0.1, max(0, deadline-time.monotonic()))
                time.sleep(delay)
        with self._lock:
            # Expire idle buckets to bound process memory; keyed by a digest, not secrets.
            type(self)._failures = {k: v for k, v in type(self)._failures.items() if v[1] > started-300}
            type(self)._failures[bucket] = (count+1, time.monotonic()+(30 if count+1 >= 3 else 0))
        raise JevError(code, latency())
