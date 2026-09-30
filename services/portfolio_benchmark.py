"""Read-only, timestamp-matched paper benchmark from retained Webull SPY daily bars."""
from functools import lru_cache
from datetime import datetime, timedelta
from sqlalchemy import inspect

from core.extensions import db
from research_data_models import ResearchCapture
from services.research_dataset import adapt, stamp


@lru_cache(maxsize=128)
def _spy_bars(capture_id):
    capture = db.session.get(ResearchCapture, capture_id)
    if capture is None:
        return ()
    return tuple(sorted((row for row in adapt(capture)
                         if row.get('kind') == 'bar' and row.get('module') == 'equities'
                         and row.get('symbol') == 'SPY' and row.get('interval') == '1d'),
                        key=lambda row: row['complete_at']))


def passive_spy(user_id, initial, run_start, as_of):
    if not inspect(db.engine).has_table(ResearchCapture.__tablename__):
        return {'status': 'UNAVAILABLE', 'reason': 'Research archive is not installed.'}
    capture = ResearchCapture.query.filter(
        ResearchCapture.user_id == user_id, ResearchCapture.lane == 'options', ResearchCapture.source == 'WEBULL_PRODUCTION',
        ResearchCapture.kind == 'stock_bars', ResearchCapture.symbol == 'SPY',
        ResearchCapture.received_at >= datetime.utcnow() - timedelta(days=7)).order_by(
            ResearchCapture.id.desc()).first()
    if capture is None:
        return {'status': 'UNAVAILABLE', 'reason': 'No recent SPY daily-bar capture.'}
    try:
        matched = [row for row in _spy_bars(capture.id)
                   if stamp(row['complete_at']) >= stamp(run_start)
                   and stamp(row['complete_at']) <= stamp(as_of)]
        if len(matched) < 2:
            return {'status': 'UNAVAILABLE', 'reason': 'Fewer than two SPY closes overlap the paper run.'}
        first, last = matched[0], matched[-1]
        change = float(last['close']) / float(first['close']) - 1
        return {'status': 'MEASURED', 'symbol': 'SPY',
                'first_close_at': first['complete_at'], 'last_close_at': last['complete_at'],
                'completed_sessions': len(matched), 'price_return_pct': round(change * 100, 4),
                'hypothetical_equity_usd': round(initial * (1 + change), 2),
                'cash_return_pct': 0,
                'basis': 'Webull completed, forward-adjusted daily SPY closes; excludes dividends, fees and cash interest. First eligible close follows the paper start.'}
    except (ValueError, TypeError, KeyError) as exc:
        return {'status': 'UNAVAILABLE', 'reason': 'SPY bar evidence invalid: ' + str(exc)[:120]}
