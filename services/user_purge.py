"""Remove every row that belongs to one user, across all tables.

Tables are discovered from the live database schema at run time: every
table with a ``user_id`` column, child tables reached only through a foreign
key (for example ladder rungs), and rows keyed by username. New tables are
covered automatically, so account deletion can no longer leave orphaned data
behind.

Nothing is deleted unless ``purge_user`` is called with the user's exact
username as confirmation. ``purge_plan`` only counts.
"""
import logging
from graphlib import TopologicalSorter

from sqlalchemy import inspect, text

from core.extensions import db

logger = logging.getLogger(__name__)

# Rows keyed by username instead of user_id.
USERNAME_KEYED = (('provider_request_states', 'owner'),)


def _schema():
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    columns = {table: {c['name'] for c in inspector.get_columns(table)} for table in tables}
    foreign_keys = {table: inspector.get_foreign_keys(table) for table in tables}
    return tables, columns, foreign_keys


def _delete_order(tables, columns, foreign_keys):
    """User-owned tables ordered so children are deleted before their parents."""
    owned = {t for t in tables if 'user_id' in columns[t] and t != 'users'}
    # Children without user_id that hang off an owned parent, e.g. ladder_rungs.
    children = {}
    for table in tables:
        if table in owned or table == 'users':
            continue
        for fk in foreign_keys[table]:
            if fk.get('referred_table') in owned and fk.get('constrained_columns'):
                children[table] = (fk['constrained_columns'][0], fk['referred_table'], (fk.get('referred_columns') or ['id'])[0])
    graph = {t: set() for t in owned | set(children)}
    for table in graph:
        for fk in foreign_keys[table]:
            parent = fk.get('referred_table')
            if parent in graph and parent != table:
                # The parent may only go after this child.
                graph[parent].add(table)
    return list(TopologicalSorter(graph).static_order()), owned, children


def _statements(user_id, username):
    tables, columns, foreign_keys = _schema()
    order, owned, children = _delete_order(tables, columns, foreign_keys)
    for table in order:
        if table in children:
            column, parent, parent_column = children[table]
            yield table, (f'"{table}" WHERE "{column}" IN (SELECT "{parent_column}" FROM "{parent}" WHERE user_id = :user_id)')
        else:
            yield table, f'"{table}" WHERE user_id = :user_id'
    for table, column in USERNAME_KEYED:
        if table in columns and column in columns[table] and username:
            yield table, f'"{table}" WHERE "{column}" = :username'


def purge_plan(user_id):
    """Count what ``purge_user`` would remove, without changing anything."""
    from credentials import User
    user = db.session.get(User, user_id)
    username = user.username if user else None
    counts = {}
    with db.engine.connect() as connection:
        for table, clause in _statements(user_id, username):
            count = connection.execute(text(f'SELECT count(*) FROM {clause}'),
                                       {'user_id': user_id, 'username': username}).scalar()
            if count:
                counts[table] = counts.get(table, 0) + count
    return {'user_id': user_id, 'username': username, 'user_exists': user is not None, 'rows': counts,
            'total_rows': sum(counts.values())}


def purge_user(user_id, *, confirm_username):
    """Delete the user and every row they own in one transaction.

    ``confirm_username`` must equal the user's username exactly.
    """
    from credentials import User
    user = db.session.get(User, user_id)
    if user is None:
        raise ValueError(f'User {user_id} does not exist.')
    if confirm_username != user.username:
        raise ValueError('Confirmation does not match the username; nothing was deleted.')
    username = user.username
    db.session.rollback()
    removed = {}
    with db.engine.begin() as connection:
        for table, clause in _statements(user_id, username):
            result = connection.execute(text(f'DELETE FROM {clause}'), {'user_id': user_id, 'username': username})
            if result.rowcount:
                removed[table] = removed.get(table, 0) + result.rowcount
        connection.execute(text('DELETE FROM users WHERE id = :user_id'), {'user_id': user_id})
    db.session.expire_all()
    logger.warning('Purged user %s (id %s): %s rows across %s tables.', username, user_id,
                   sum(removed.values()), len(removed))
    return {'user_id': user_id, 'username': username, 'rows': removed, 'total_rows': sum(removed.values())}


def orphan_report():
    """Rows whose user_id no longer exists (left by older account deletions). Read-only."""
    tables, columns, _ = _schema()
    report = {}
    with db.engine.connect() as connection:
        for table in tables:
            if table == 'users' or 'user_id' not in columns[table]:
                continue
            rows = connection.execute(text(
                f'SELECT user_id, count(*) FROM "{table}" WHERE user_id IS NOT NULL '
                f'AND user_id NOT IN (SELECT id FROM users) GROUP BY user_id')).all()
            for user_id, count in rows:
                report.setdefault(int(user_id), {})[table] = count
    return report


def purge_orphans(user_id):
    """Delete leftover rows for a user ID that no longer exists in users."""
    from credentials import User
    if db.session.get(User, user_id) is not None:
        raise ValueError(f'User {user_id} still exists; use purge_user instead.')
    removed = {}
    with db.engine.begin() as connection:
        for table, clause in _statements(user_id, None):
            result = connection.execute(text(f'DELETE FROM {clause}'), {'user_id': user_id, 'username': None})
            if result.rowcount:
                removed[table] = removed.get(table, 0) + result.rowcount
    return {'user_id': user_id, 'rows': removed, 'total_rows': sum(removed.values())}
