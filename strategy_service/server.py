"""Credential-free, Unix-socket strategy decision and source-version service.

Run as a dedicated system account with no network or access to app checkouts.
The app owns all market validation, paper fills, exits, settlement and risk.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import resource
import socketserver
import subprocess
import sys
from datetime import datetime, timezone

MODULES = ('equities', 'options', 'crypto', 'events')
SCHEMA = 1
MAX_REQUEST = 256 * 1024
MAX_SOURCE = 16 * 1024
ALLOWED = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Assign,
           ast.If, ast.Compare, ast.Name, ast.Constant, ast.Dict, ast.Subscript,
           ast.BinOp, ast.BoolOp, ast.UnaryOp, ast.Call, ast.List, ast.Tuple,
           ast.Load, ast.Store, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Gt,
           ast.Lt, ast.GtE, ast.LtE, ast.Eq, ast.NotEq, ast.And, ast.Or, ast.Not,
           ast.Is, ast.IsNot, ast.IfExp)
BUILTINS = {'abs': abs, 'min': min, 'max': max, 'round': round, 'float': float,
            'int': int, 'bool': bool}
ROOT = Path(os.environ.get('QUANT_STRATEGY_ROOT', '/var/lib/crypto-quant-strategy'))
SOCKET = os.environ.get('QUANT_STRATEGY_SOCKET', '/run/crypto-quant-strategy/strategy.sock')
BASELINES = Path(__file__).resolve().parent / 'rules'
FAILURES = {module: 0 for module in MODULES}


def digest(source):
    return hashlib.sha256(source.encode('utf-8')).hexdigest()


def validate_source(source):
    if not isinstance(source, str) or not 1 <= len(source.encode()) <= MAX_SOURCE:
        raise ValueError('Strategy source must be 1–16 KiB.')
    tree = ast.parse(source)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError('Exactly one decide(f) function is required.')
    function = tree.body[0]
    if function.name != 'decide' or len(function.args.args) != 1 or function.args.args[0].arg != 'f':
        raise ValueError('Strategy entry point must be decide(f).')
    if function.decorator_list or function.args.defaults or function.args.kwarg or function.args.vararg:
        raise ValueError('Decorators and variable arguments are not permitted.')
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED):
            raise ValueError('Disallowed Python construct: ' + type(node).__name__)
        if isinstance(node, ast.Name) and (node.id.startswith('_') or node.id not in
                {'f', 'c', 'checks', 'direction', 'ready', 'abs', 'min', 'max', 'round', 'float', 'int', 'bool'}):
            raise ValueError('Undeclared signal variable: ' + node.id)
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in BUILTINS):
            raise ValueError('Only bounded arithmetic builtins may be called.')
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)) and len(node.value) > 1000:
            raise ValueError('Strategy string constant is too large.')
    return tree


def evaluate_local(source, features):
    tree = validate_source(source)
    scope = {'__builtins__': BUILTINS}
    exec(compile(tree, '<strategy>', 'exec'), scope)
    result = scope['decide'](features)
    if not isinstance(result, dict) or type(result.get('enter')) is not bool:
        raise ValueError('Strategy must return a decision object with boolean enter.')
    if result.get('setup') is not None and (not isinstance(result['setup'], str) or len(result['setup']) > 80):
        raise ValueError('Invalid setup identifier.')
    if not isinstance(result.get('reason'), str) or len(result['reason']) > 500:
        raise ValueError('Invalid decision reason.')
    return {key: result.get(key) for key in ('enter', 'setup', 'reason')}


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
    resource.setrlimit(resource.RLIMIT_AS, (128 * 1024 * 1024, 128 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))


def sandboxed(source, features):
    payload = json.dumps({'source': source, 'features': features}, allow_nan=False).encode()
    if len(payload) > MAX_REQUEST:
        raise ValueError('Strategy input exceeds 256 KiB.')
    child = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve()), '--eval'],
                           input=payload, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=2, preexec_fn=_limits, env={'PATH': '/usr/bin:/bin'})
    if child.returncode or len(child.stdout) > 4096:
        raise ValueError('Restricted strategy process failed.')
    reply = json.loads(child.stdout)
    if 'error' in reply:
        raise ValueError(str(reply['error'])[:200])
    return reply['result']


def source_path(module, sha):
    return ROOT / 'versions' / module / (sha + '.py')


def active_path(module):
    return ROOT / ('active-' + module + '.json')


def write_atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.new-' + str(os.getpid()))
    try:
        with open(temporary, 'x', encoding='utf-8') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def active(module):
    if module not in MODULES:
        raise ValueError('Unknown strategy module.')
    pointer = active_path(module)
    if not pointer.exists():
        source = (BASELINES / (module + '.py')).read_text()
        validate_source(source)
        sha = digest(source)
        write_atomic(source_path(module, sha), source)
        write_atomic(pointer, json.dumps({'sha256': sha, 'version': '4.5.0-baseline', 'previous': None}))
    meta = json.loads(pointer.read_text())
    source = source_path(module, meta['sha256']).read_text()
    if digest(source) != meta['sha256']:
        raise ValueError('Active strategy checksum mismatch.')
    return meta, source


def handle(request):
    if request.get('schema') != SCHEMA:
        raise ValueError('Unsupported strategy protocol.')
    op = request.get('op')
    if op == 'health':
        return {'status': 'READY', 'modules': {module: active(module)[0] for module in MODULES}}
    module = request.get('module')
    meta, source = active(module)
    if op == 'source':
        return {'module': module, 'source': source, **meta}
    if op == 'version_source':
        sha = request.get('code_sha256')
        if not isinstance(sha, str) or len(sha) != 64:
            raise ValueError('Invalid source checksum.')
        candidate = source_path(module, sha).read_text()
        if digest(candidate) != sha:
            raise ValueError('Version checksum mismatch.')
        return {'module': module, 'source': candidate, 'code_sha256': sha}
    if op == 'evaluate_candidate':
        sha = request.get('candidate_sha256')
        if not isinstance(sha, str) or len(sha) != 64:
            raise ValueError('Invalid candidate checksum.')
        candidate = source_path(module, sha).read_text()
        if digest(candidate) != sha:
            raise ValueError('Candidate source checksum mismatch.')
        features = request.get('features')
        if not isinstance(features, dict):
            raise ValueError('Candidate features must be an object.')
        result = sandboxed(candidate, features)
        return {'module': module, 'candidate_sha256': sha, **result}
    if op == 'evaluate':
        as_of = datetime.fromisoformat(request['as_of'].replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - as_of).total_seconds()
        if not -5 <= age <= 120:
            raise ValueError('Strategy snapshot is stale or from the future.')
        features = request.get('features')
        if not isinstance(features, dict):
            raise ValueError('Strategy features must be an object.')
        try:
            result = sandboxed(source, features)
            FAILURES[module] = 0
        except Exception:
            FAILURES[module] += 1
            if FAILURES[module] >= 3 and meta.get('previous'):
                previous = source_path(module, meta['previous']).read_text()
                if digest(previous) == meta['previous']:
                    write_atomic(active_path(module), json.dumps({
                        'sha256': meta['previous'], 'version': 'automatic-rollback-' + meta['previous'][:12],
                        'previous': None,
                        'rolled_back_at': datetime.now(timezone.utc).isoformat(),
                        'rollback_reason': 'Three consecutive restricted strategy evaluation failures.'}))
                    FAILURES[module] = 0
            raise
        return {'module': module, 'action': 'ENTER' if result['enter'] else 'NO_TRADE',
                'enter': result['enter'], 'setup': result['setup'], 'reason': result['reason'],
                'code_sha256': meta['sha256'], 'strategy_version': meta['version'],
                'snapshot_sha256': request.get('snapshot_sha256')}
    if op == 'propose':
        if request.get('parent_sha256') != meta['sha256']:
            raise ValueError('Active source changed; regenerate candidate against current parent.')
        candidate = request.get('source')
        validate_source(candidate)
        candidate_sha = digest(candidate)
        fixtures = request.get('fixtures')
        if not isinstance(fixtures, list) or not 1 <= len(fixtures) <= 40:
            raise ValueError('1–40 deterministic fixtures are required.')
        validations = []
        for item in fixtures:
            features = item['features']
            first = sandboxed(candidate, features)
            second = sandboxed(candidate, features)
            if first != second:
                raise ValueError('Candidate is nondeterministic on a fixture.')
            validations.append({'input_sha256': digest(json.dumps(features, sort_keys=True)),
                                'decision': first})
        write_atomic(source_path(module, candidate_sha), candidate) if not source_path(module, candidate_sha).exists() else None
        return {'module': module, 'parent_sha256': meta['sha256'],
                'candidate_sha256': candidate_sha, 'validation': validations, 'status': 'VALIDATED'}
    if op == 'activate':
        candidate_sha = request.get('candidate_sha256')
        if not isinstance(candidate_sha, str) or len(candidate_sha) != 64:
            raise ValueError('Invalid candidate checksum.')
        if request.get('parent_sha256') != meta['sha256']:
            raise ValueError('Active source changed before promotion.')
        candidate = source_path(module, candidate_sha).read_text()
        if digest(candidate) != candidate_sha:
            raise ValueError('Candidate checksum mismatch.')
        gates = request.get('gates')
        if not isinstance(gates, dict) or gates.get('observation_sessions', 0) < 30 or gates.get('closed_trades', 0) < 20 or gates.get('risk_breaches') != 0 or gates.get('holdout_fresh') is not True or gates.get('candidate_score', 0) <= gates.get('baseline_score', 0):
            raise ValueError('Outcome, risk or fresh chronological holdout gate did not pass.')
        if request.get('evidence_sha256') is None:
            raise ValueError('Activation requires immutable evidence hash.')
        if meta.get('activated_at', '')[:10] == datetime.now(timezone.utc).date().isoformat():
            raise ValueError('One accepted revision per module per UTC day is permitted.')
        write_atomic(active_path(module), json.dumps({
            'sha256': candidate_sha, 'version': 'revision-' + candidate_sha[:12],
            'previous': meta['sha256'], 'activated_at': datetime.now(timezone.utc).isoformat(),
            'evidence_sha256': request['evidence_sha256']}))
        return {'status': 'ACTIVE', **active(module)[0]}
    if op == 'rollback':
        prior = meta.get('previous')
        if not prior:
            raise ValueError('No previous strategy version.')
        if request.get('expected_sha256') != meta['sha256']:
            raise ValueError('Active source changed before rollback.')
        candidate = source_path(module, prior).read_text()
        if digest(candidate) != prior:
            raise ValueError('Rollback checksum mismatch.')
        write_atomic(active_path(module), json.dumps({'sha256': prior, 'version': 'rollback-' + prior[:12],
                                                       'previous': None,
                                                       'rolled_back_at': datetime.now(timezone.utc).isoformat()}))
        return {'status': 'ROLLED_BACK', **active(module)[0]}
    raise ValueError('Unknown strategy operation.')


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        raw = self.rfile.readline(MAX_REQUEST + 1)
        try:
            if len(raw) > MAX_REQUEST:
                raise ValueError('Strategy request exceeds 256 KiB.')
            reply = {'schema': SCHEMA, 'result': handle(json.loads(raw))}
        except Exception as exc:
            reply = {'schema': SCHEMA, 'error': str(exc)[:300]}
        self.wfile.write(json.dumps(reply, allow_nan=False).encode() + b'\n')


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--eval', action='store_true')
    args = parser.parse_args()
    if args.eval:
        try:
            value = json.loads(sys.stdin.buffer.read(MAX_REQUEST + 1))
            print(json.dumps({'result': evaluate_local(value['source'], value['features'])}))
        except Exception as exc:
            print(json.dumps({'error': str(exc)[:200]}))
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    for module in MODULES:
        active(module)
    path = Path(SOCKET)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with Server(SOCKET, Handler) as server:
        os.chmod(SOCKET, 0o660)
        server.serve_forever()


if __name__ == '__main__':
    main()
