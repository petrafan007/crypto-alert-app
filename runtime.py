"""Explicit database initialization and singleton background-worker entry points."""
import argparse
import signal
import threading

from sqlalchemy import text

WORKER_LOCK = 2892005010


def run_worker(app, stop=None):
    from core.extensions import db
    from services.scheduler_tasks import start_background_jobs
    stop = stop or threading.Event()
    with app.app_context():
        # A session-level lock lives on this dedicated connection, not the ORM pool.
        with db.engine.connect() as connection:
            if not connection.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': WORKER_LOCK}).scalar():
                raise RuntimeError('Another background scheduler already owns this database.')
            connection.commit()
            try:
                jobs = start_background_jobs(app)
                if not jobs:
                    raise RuntimeError('Background scheduler did not start any jobs.')
                app.logger.info('Singleton background scheduler started.')
                while not stop.is_set():
                    from services.provider_resilience import write, identity
                    threads = [{'name': name, 'alive': thread.is_alive()} for name, thread in jobs.items()]
                    if not all(thread['alive'] for thread in threads):
                        raise RuntimeError('A supervised background job stopped.')
                    write(identity('scheduler-heartbeat'), '__system__', 'scheduler', 'heartbeat', {'threads': threads}, 35)
                    if stop.wait(10):
                        break
                    # Lost DB connections terminate the process; systemd restarts and reacquires.
                    connection.execute(text('SELECT 1'))
                    connection.commit()
            finally:
                connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': WORKER_LOCK})
                connection.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['init-db', 'worker'])
    args = parser.parse_args()
    from main import app
    if args.command == 'init-db':
        from database import init_db
        init_db(app)
        # Verify the new release schema explicitly; legacy initializer logs some errors.
        from core.extensions import db
        with app.app_context(), db.engine.connect() as connection:
            connection.execute(text('SELECT telegram_notifications_enabled FROM user_settings LIMIT 0'))
            connection.execute(text('SELECT key FROM provider_request_states LIMIT 0'))
    else:
        stop = threading.Event()
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: stop.set())
        run_worker(app, stop)


if __name__ == '__main__':
    main()
