"""Keep portfolio value history useful without letting it grow forever.

The portfolio loop records a value every minute per account series. Charts
over a month or more only need hourly or daily points, so older rows are
thinned to the last value of each hour (7-90 days old) and of each day
(older than 90 days), per user and per series. The latest week is kept in
full. The first and last point of every series are never removed.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from core.extensions import db

logger = logging.getLogger(__name__)

FULL_RESOLUTION_DAYS = 7
HOURLY_RESOLUTION_DAYS = 90
INDEX_NAME = 'ix_portfolio_value_history_user_source_ts'

_THIN_SQL = """
DELETE FROM portfolio_value_history AS p
USING (
    SELECT id,
           row_number() OVER (PARTITION BY user_id, COALESCE(source, 'all'), date_trunc(:bucket, "timestamp")
                              ORDER BY "timestamp" DESC, id DESC) AS rank_in_bucket,
           row_number() OVER (PARTITION BY user_id, COALESCE(source, 'all') ORDER BY "timestamp" ASC, id ASC) AS rank_in_series
    FROM portfolio_value_history
    WHERE "timestamp" IS NOT NULL AND "timestamp" < :newer_than AND "timestamp" >= :older_than
) AS ranked
WHERE p.id = ranked.id AND ranked.rank_in_bucket > 1
  AND NOT (ranked.rank_in_series = 1 AND :older_than = :epoch)
"""


def ensure_history_index():
    """Index the chart query (user, series, time) without blocking writes."""
    if db.engine.dialect.name != 'postgresql':
        return False
    with db.engine.connect() as connection:
        exists = connection.execute(text('SELECT 1 FROM pg_indexes WHERE indexname = :name'),
                                    {'name': INDEX_NAME}).scalar()
    if exists:
        return False
    with db.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        connection.execute(text(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} '
            'ON portfolio_value_history (user_id, source, "timestamp")'))
    logger.info('Created index %s', INDEX_NAME)
    return True


def thin_portfolio_value_history(now=None):
    """Thin old history in place; returns the number of rows removed."""
    if db.engine.dialect.name != 'postgresql':
        return 0
    now = now or datetime.utcnow()
    epoch = datetime(1970, 1, 1)
    full_cutoff = now - timedelta(days=FULL_RESOLUTION_DAYS)
    hourly_cutoff = now - timedelta(days=HOURLY_RESOLUTION_DAYS)
    removed = 0
    with db.engine.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        removed += connection.execute(text(_THIN_SQL), {
            'bucket': 'hour', 'newer_than': full_cutoff, 'older_than': hourly_cutoff, 'epoch': epoch}).rowcount
        removed += connection.execute(text(_THIN_SQL), {
            'bucket': 'day', 'newer_than': hourly_cutoff, 'older_than': epoch, 'epoch': epoch}).rowcount
    if removed:
        with db.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
            connection.execute(text('VACUUM (ANALYZE) portfolio_value_history'))
        logger.info('Thinned portfolio value history: removed %s superseded points', removed)
    return removed
