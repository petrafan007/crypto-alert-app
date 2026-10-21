"""Provider-neutral decision client for the Decision Engine.

Supports two decision providers that share the same typed question contract:

  subq       https://api.subq.ai/v1/systemone            model subq-snap-preview
  inception  https://api.inceptionlabs.ai/v1/decisions    model mercury-decide

Both providers express a positive answer as a ``noul`` probability between 0 and 1.
The internal contract remains ``boolean`` / ``choice`` / ``score`` so every consumer
of the Decision Engine keeps working unchanged, and both wire formats are
normalised through the same path.

The client holds no sentiment, trading, or database dependency.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import math
import random
import threading
import time

import requests

from services.decision_settings import (
    DEFAULT_ENDPOINT,
    INCEPTION_DECISIONS_ENDPOINT,
    INCEPTION_DECISIONS_MODEL,
    SUBQ_ENDPOINT,
    SUBQ_MODEL,
    normalize_transport,
    validate_endpoint,
)


class DecisionError(Exception):
    def __init__(self, code, latency_ms=0):
        self.code = code
        self.latency_ms = latency_ms
        super().__init__({
            'auth': 'The selected decision provider rejected the API key.',
            'timeout': 'The decision request timed out.',
            'cooldown': 'The decision provider is cooling down after repeated failures.',
            'missing_key': 'Save an API key for the selected decision provider first.',
            'invalid_response': 'The decision provider returned an invalid or incomplete evaluation.',
        }.get(code, 'Decision evaluation unavailable.'))


@dataclass
class DecisionResult:
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
        raise DecisionError('invalid_response')
    return value


def validate_answers(payload, questions):
    """Validate the provider payload against the internal question contract."""
    try:
        answers = payload['answers']
        for key, question in questions.items():
            answer = answers[key]
            kind = question['type']
            if answer['type'] != kind:
                raise DecisionError('invalid_response')
            if kind == 'boolean':
                number(answer['probability'])
            else:
                expected = set(question['criteria']) if kind == 'choice' else {str(i) for i in range(len(question['criteria']))}
                probs = answer['probabilities']
                if not isinstance(probs, dict) or set(probs) != expected:
                    raise DecisionError('invalid_response')
                if abs(sum(number(v) for v in probs.values()) - 1) > 0.02:
                    raise DecisionError('invalid_response')
                if kind == 'choice' and answer['choice'] not in expected:
                    raise DecisionError('invalid_response')
                if kind == 'score':
                    number(answer['score'], 0, len(expected)-1)
        return {key: answers[key] for key in questions}
    except (KeyError, TypeError, AttributeError):
        raise DecisionError('invalid_response') from None


class DecisionClient:
    """A single decision provider call.

    The provider is chosen by transport. ``fallback_transport`` allows a second
    provider to be tried when the primary fails, so a decision is not lost
    because one provider is rate limited.
    """

    _failures = {}
    _lock = threading.Lock()

    def __init__(self, api_key, endpoint=DEFAULT_ENDPOINT, model='mercury-decide',
                 timeout_seconds=3.0, transport='subq'):
        self.key = api_key
        config = normalize_transport({'decision_transport': transport,
                                      'decision_endpoint': endpoint,
                                      'decision_model': model})
        self.transport = config['decision_transport']
        if self.transport not in ('subq', 'inception'):
            raise ValueError('Unsupported decision transport.')
        self.endpoint = validate_endpoint(config['decision_endpoint'])
        self.model = config['decision_model']
        self.timeout = timeout_seconds

    # ------------------------------------------------------------------ wire
    def _wire_questions(self, questions):
        """The internal ``boolean`` type is a positive answer, which both
        providers express on the wire as ``noul``."""
        return {key: ({**question, 'type': 'noul'} if question['type'] == 'boolean' else dict(question))
                for key, question in questions.items()}

    def _normalize(self, payload, questions):
        """Map a provider payload onto the internal answer contract."""
        answers = {}
        confidence = {}
        for key, question in questions.items():
            answer = payload['answers'][key]
            if question['type'] == 'boolean':
                if answer.get('type') != 'noul':
                    raise DecisionError('invalid_response')
                answers[key] = {'type': 'boolean', 'probability': answer['noul']}
            else:
                confidence[key] = number(answer['confidence'])
                if question['type'] == 'score':
                    legend = {str(index): str(level)
                              for index, level in enumerate(question['criteria'])}
                    if answer.get('legend') != legend:
                        raise DecisionError('invalid_response')
                answers[key] = answer
        return validate_answers({'answers': answers}, questions), confidence

    # --------------------------------------------------------------- request
    def evaluate(self, *, state, questions, model=None, timeout_seconds=None, before_request=None):
        request_model = model or self.model
        if self.transport == 'subq' and request_model != self.model:
            raise ValueError(f'SubQ supports only the {SUBQ_MODEL} decision model.')
        if self.transport == 'inception' and request_model != INCEPTION_DECISIONS_MODEL:
            raise ValueError(f'Inception supports only the {INCEPTION_DECISIONS_MODEL} decision model.')
        started = time.monotonic()
        latency = lambda: int((time.monotonic()-started)*1000)
        if not self.key or self.key == '********':
            raise DecisionError('missing_key')
        bucket = hashlib.sha256((self.endpoint+self.key).encode()).hexdigest()
        with self._lock:
            count, until = self._failures.get(bucket, (0, 0))
        if until > started:
            raise DecisionError('cooldown')
        budget = min(15, max(0.25, float(timeout_seconds or self.timeout)))
        deadline = started + budget
        code = 'network'
        for attempt in range(2):
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                code = 'timeout'
                break
            try:
                request_json = {'model': request_model, 'state': state,
                                'questions': self._wire_questions(questions)}
                headers = {'Authorization': f'Bearer {self.key}', 'Content-Type': 'application/json'}
                if before_request:
                    before_request()
                response = requests.post(self.endpoint, headers=headers, json=request_json,
                                         timeout=(remaining/2, remaining/2), allow_redirects=False)
                status = response.status_code
                if status == 200:
                    try:
                        payload = response.json()
                        answers, confidence = self._normalize(payload, questions)
                        usage = payload.get('usage') or {}
                        cost = None
                        actual_model = payload.get('model', request_model)
                        if not isinstance(actual_model, str) or len(actual_model) > 100:
                            raise DecisionError('invalid_response')
                        if payload.get('model') != request_model:
                            raise DecisionError('invalid_response')
                        if not isinstance(usage, dict):
                            raise DecisionError('invalid_response')
                    except (KeyError, ValueError, TypeError, AttributeError, InvalidOperation):
                        raise DecisionError('invalid_response') from None
                    with self._lock:
                        type(self)._failures.pop(bucket, None)
                    provider = 'SubQ' if self.transport == 'subq' else 'Inception'
                    return DecisionResult(answers, payload, actual_model, provider,
                                          self.transport, latency(), usage, cost, confidence)
                code = 'auth' if status in (401, 403) else f'http_{status}'
                if status not in (408, 429, 500, 502, 503, 504):
                    break
            except DecisionError as exc:
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
        raise DecisionError(code, latency())


def evaluate_with_fallback(primary, fallback, *, state, questions, timeout_seconds=None):
    """Try the primary provider, then the fallback provider.

    Returns ``(result, attempts)`` where ``attempts`` records the transport
    that produced the answer and every transport that was tried, so the
    outcome is attributable in the ledger.
    """
    tried = []
    for client in (primary, fallback):
        if client is None:
            continue
        tried.append(client.transport)
        try:
            result = client.evaluate(state=state, questions=questions,
                                     timeout_seconds=timeout_seconds)
            return result, tried
        except DecisionError as exc:
            if exc.code in ('auth', 'missing_key'):
                # A bad key for one provider is not a reason to skip the other.
                continue
            if exc.code == 'timeout' and client is fallback:
                continue
            continue
    raise DecisionError('invalid_response' if tried else 'missing_key')
