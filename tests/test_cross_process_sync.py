"""Locks and cache invalidation across real operating-system processes (audit F29, F30, F38).

The lock test needs a disposable PostgreSQL database, because advisory locks
are a PostgreSQL feature. It runs only when CSD_TEST_POSTGRES_URL is set, for
example:

    createdb -h /var/run/postgresql -p 5433 csd_lock_test
    CSD_TEST_POSTGRES_URL='postgresql:///csd_lock_test?host=/var/run/postgresql&port=5433' \\
        python -m unittest tests.test_cross_process_sync
    dropdb -h /var/run/postgresql -p 5433 csd_lock_test

It never touches the application's own database. The cache test needs no
database and always runs.
"""
import multiprocessing as mp
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

POSTGRES_URL = os.environ.get('CSD_TEST_POSTGRES_URL')


def _app(url):
    from flask import Flask
    from core.extensions import db
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI=url, TESTING=True)
    db.init_app(app)
    return app


def _hold_lock(url, user_id, held, release, result):
    from services.sync_locks import user_sync_lock
    with _app(url).app_context():
        with user_sync_lock('webull-snapshot', user_id) as locked:
            result.put(('holder', locked))
            held.set()
            release.wait(30)


def _try_lock(url, user_id, timeout, result):
    from services.sync_locks import user_sync_lock
    with _app(url).app_context():
        with user_sync_lock('webull-snapshot', user_id, timeout=timeout) as locked:
            result.put(('other', user_id, locked))


def _cache_worker(state_dir, commands, replies):
    """A separate process with its own in-memory Webull cache."""
    os.environ['CSD_SHARED_STATE_DIR'] = state_dir
    from services import webull_service as ws
    calls = {'count': 0}

    def reply(*_args, **_kwargs):
        calls['count'] += 1
        response = Mock(status_code=200)
        response.json.return_value = {'data': [{'order_id': f'read-{calls["count"]}', 'symbol': 'AAPL'}]}
        return response
    with patch.object(ws, '_rate_limited_order_request', side_effect=reply):
        while True:
            command = commands.get(timeout=30)
            if command == 'read':
                replies.put([order['order_id'] for order in ws.get_webull_open_orders('k', 's', 'production', 't', account_id='A')])
            elif command == 'clear':
                ws.clear_webull_order_cache()
                replies.put('cleared')
            else:
                return


class CrossProcessCacheTests(unittest.TestCase):
    def test_clearing_in_one_process_invalidates_another_process_cache(self):
        context = mp.get_context('spawn')
        with tempfile.TemporaryDirectory() as state_dir:
            web = (context.Queue(), context.Queue())
            worker = (context.Queue(), context.Queue())
            processes = [context.Process(target=_cache_worker, args=(state_dir, *queues)) for queues in (web, worker)]
            for process in processes:
                process.start()
            try:
                ask = lambda queues, command: (queues[0].put(command), queues[1].get(timeout=30))[1]
                self.assertEqual(ask(worker, 'read'), ['read-1'])
                self.assertEqual(ask(worker, 'read'), ['read-1'], 'served from the worker process cache')
                self.assertEqual(ask(web, 'clear'), 'cleared')          # e.g. a cancellation handled by a web worker
                self.assertEqual(ask(worker, 'read'), ['read-2'], 'the worker process read Webull again')
            finally:
                for queues in (web, worker):
                    queues[0].put('stop')
                for process in processes:
                    process.join(30)


@unittest.skipUnless(POSTGRES_URL, 'set CSD_TEST_POSTGRES_URL to a disposable PostgreSQL database')
class CrossProcessLockTests(unittest.TestCase):
    def test_one_snapshot_refresh_per_user_across_processes(self):
        context = mp.get_context('spawn')
        held, release, result = context.Event(), context.Event(), context.Queue()
        holder = context.Process(target=_hold_lock, args=(POSTGRES_URL, 7, held, release, result))
        holder.start()
        try:
            self.assertTrue(held.wait(30))
            self.assertEqual(result.get(timeout=30), ('holder', True))
            for user_id in (7, 8):
                other = context.Process(target=_try_lock, args=(POSTGRES_URL, user_id, 1.0, result))
                other.start(); other.join(30)
                self.assertEqual(result.get(timeout=30), ('other', user_id, user_id != 7),
                                 'the same user waits and gives up; another user is not blocked')
            release.set()
            holder.join(30)
            after = context.Process(target=_try_lock, args=(POSTGRES_URL, 7, 1.0, result))
            after.start(); after.join(30)
            self.assertEqual(result.get(timeout=30), ('other', 7, True), 'free again once released')
        finally:
            release.set()
            holder.join(30)

    def test_a_waiting_refresh_runs_when_the_first_finishes(self):
        context = mp.get_context('spawn')
        held, release, result = context.Event(), context.Event(), context.Queue()
        holder = context.Process(target=_hold_lock, args=(POSTGRES_URL, 9, held, release, result))
        holder.start()
        self.assertTrue(held.wait(30)); result.get(timeout=30)
        waiter = context.Process(target=_try_lock, args=(POSTGRES_URL, 9, 20.0, result))
        waiter.start()
        release.set()
        waiter.join(30); holder.join(30)
        self.assertEqual(result.get(timeout=30), ('other', 9, True))


if __name__ == '__main__':
    unittest.main()
