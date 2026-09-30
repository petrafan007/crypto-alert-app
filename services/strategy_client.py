"""Bounded, paper-only client for the separately managed strategy source service."""
import hashlib
import json
import os
import socket
from datetime import datetime, timezone

SOCKET = '/run/crypto-quant-strategy/strategy.sock'
MAX_REPLY = 256 * 1024


class StrategyUnavailable(ValueError):
    pass


def request(operation, *, module=None, **payload):
    path = os.getenv('QUANT_STRATEGY_SOCKET', SOCKET)
    value = {'schema': 1, 'op': operation, **({'module': module} if module else {}), **payload}
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'
    if len(raw) > 256 * 1024:
        raise StrategyUnavailable('Strategy request exceeds 256 KiB.')
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(path)
            connection.sendall(raw)
            chunks = bytearray()
            while not chunks.endswith(b'\n'):
                part = connection.recv(4096)
                if not part or len(chunks) + len(part) > MAX_REPLY:
                    raise StrategyUnavailable('Strategy service returned an incomplete or oversized response.')
                chunks.extend(part)
        reply = json.loads(chunks)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise StrategyUnavailable('Strategy service is unavailable: ' + type(exc).__name__) from exc
    if reply.get('schema') != 1 or 'error' in reply or not isinstance(reply.get('result'), dict):
        raise StrategyUnavailable(str(reply.get('error', 'Invalid strategy response.'))[:300])
    return reply['result']


def evaluate(user_id, module, symbol, features, now):
    if module not in ('equities', 'options', 'crypto', 'events'):
        raise ValueError('Unknown strategy module.')
    if not isinstance(user_id, int) or user_id < 1 or not isinstance(symbol, str) or not 1 <= len(symbol) <= 160:
        raise ValueError('Invalid strategy scope.')
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    as_of = now.isoformat()
    snapshot = {'user_id': user_id, 'module': module, 'symbol': symbol,
                'as_of': as_of, 'features': features}
    sha = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    result = request('evaluate', module=module, user_id=user_id, symbol=symbol,
                     as_of=as_of, features=features, snapshot_sha256=sha)
    if (result.get('module') != module or result.get('snapshot_sha256') != sha or
            type(result.get('enter')) is not bool or
            result.get('action') != ('ENTER' if result['enter'] else 'NO_TRADE') or
            not isinstance(result.get('strategy_version'), str) or
            not isinstance(result.get('code_sha256'), str) or len(result['code_sha256']) != 64):
        raise StrategyUnavailable('Strategy service response failed scope or schema checks.')
    return result
