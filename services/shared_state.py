"""Small pieces of state shared by every process of one installation.

The web service runs several worker processes and the background scheduler
runs in another. In-memory caches are private to each of them, so clearing a
cache in one process used to leave older copies alive in the others. These
helpers keep two kinds of shared state in files under the instance directory:

* revisions: a counter per named cache. Clearing a cache bumps its revision;
  every process compares the revision it cached under with the current one.
* snapshots: a small JSON value with the time it was observed. A write is kept
  only if it was observed later than what is already stored, so a slow, older
  read can never replace a newer one.

Nothing here is a source of truth. A missing or unreadable file only means
"no shared state", and callers then read from the provider again.
"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

from log import logger

_LOCK = threading.Lock()


_TEST_DIR = None


def _running_tests():
    # `python -m unittest` and pytest set these; a test run must never read or
    # write the shared state of the installation it happens to run in.
    return 'unittest' in str(sys.argv[0] if sys.argv else '') or 'pytest' in sys.modules


def state_dir():
    global _TEST_DIR
    configured = os.environ.get('CSD_SHARED_STATE_DIR')
    if configured:
        path = Path(configured)
    elif _running_tests():
        if _TEST_DIR is None:
            _TEST_DIR = tempfile.mkdtemp(prefix='csd-shared-state-test-')
        path = Path(_TEST_DIR)
    else:
        path = Path(__file__).resolve().parents[1] / 'instance' / 'shared-state'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _file(kind, name):
    safe = ''.join(char if char.isalnum() or char in '-_.' else '_' for char in str(name))
    return state_dir() / f'{kind}-{safe}.json'


def _read(path):
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning('Ignoring unreadable shared state %s: %s', path.name, exc)
        return None


def _write(path, value):
    # Write a sibling file and rename it over the old one, so a reader never
    # sees a half-written file.
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def revision(name):
    """The current revision of a named cache, as an opaque string."""
    try:
        value = _read(_file('revision', name))
        return str(value.get('revision')) if isinstance(value, dict) else '0'
    except OSError:
        return '0'


def bump_revision(name):
    """Invalidate a named cache in every process."""
    token = f'{time.time_ns()}-{os.getpid()}'
    try:
        with _LOCK:
            _write(_file('revision', name), {'revision': token})
    except OSError as exc:
        logger.warning('Could not record shared cache invalidation for %s: %s', name, exc)
    return token


def store_snapshot(name, value, observed_at):
    """Keep `value` unless a snapshot observed later is already stored."""
    path = _file('snapshot', name)
    try:
        with _LOCK:
            current = _read(path)
            if isinstance(current, dict) and float(current.get('observed_at') or 0) > float(observed_at):
                return False
            _write(path, {'observed_at': float(observed_at), 'value': value})
            return True
    except OSError as exc:
        logger.warning('Could not store shared snapshot %s: %s', name, exc)
        return False


def load_snapshot(name, max_age):
    """Return (value, observed_at) if a snapshot newer than `max_age` seconds exists."""
    try:
        current = _read(_file('snapshot', name))
    except OSError:
        return None, None
    if not isinstance(current, dict):
        return None, None
    observed_at = float(current.get('observed_at') or 0)
    if time.time() - observed_at >= max_age:
        return None, None
    return current.get('value'), observed_at


def discard_snapshot(name):
    try:
        _file('snapshot', name).unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning('Could not discard shared snapshot %s: %s', name, exc)
