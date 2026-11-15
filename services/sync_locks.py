"""Per-user, cross-process locks for background synchronisation.

The web service, its post-transaction threads and the background worker can
all synchronise the same user's data at once. A lock here is held from the
provider read until the database commit, so two syncs of the same kind for the
same user never interleave.
"""
import hashlib
import threading
import time
from contextlib import contextmanager

from sqlalchemy import text

from core.extensions import db

_LOCAL_LOCKS = {}
_LOCAL_LOCKS_GUARD = threading.Lock()


def _local_lock(name):
    with _LOCAL_LOCKS_GUARD:
        return _LOCAL_LOCKS.setdefault(name, threading.Lock())


@contextmanager
def user_sync_lock(kind, user_id, timeout=0.0):
    """Yield True while holding the lock, or False if it was not free within `timeout` seconds.

    On databases without advisory locks (the SQLite test suite) only the
    in-process lock applies.
    """
    name = f'{kind}:{user_id}'
    key = int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], 'big', signed=True)
    local = _local_lock(name)
    acquired = local.acquire(timeout=timeout) if timeout > 0 else local.acquire(blocking=False)
    if not acquired:
        yield False
        return
    try:
        if db.engine.dialect.name != 'postgresql':
            yield True
            return
        deadline = time.monotonic() + timeout
        with db.engine.connect() as connection:
            locked = bool(connection.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': key}).scalar())
            while not locked and time.monotonic() < deadline:
                time.sleep(0.5)
                locked = bool(connection.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': key}).scalar())
            try:
                yield locked
            finally:
                if locked:
                    connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': key})
                connection.commit()
    finally:
        local.release()
