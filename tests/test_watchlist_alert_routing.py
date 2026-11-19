"""Watchlist alert edits route by row id, not provider label (v4.19.7).

Since v4.19.6 a generic watchlist row for a stock reports source='webull'
(its provider identity, needed by the pending-order matcher) while living
in the generic `watchlist` table with a plain numeric id. The
/api/set-watch-alert endpoint keyed its Webull branch off
`source == 'webull'` as well as the 'webull-watchlist-' id prefix, so an
alert edit for such a row was looked up in webull_watchlist_items, missed,
and 404'd — the dashboard reverted the user's value (Joseph's ANT alerts,
Nov 19 2026: his 89/100 edits never persisted; 70/83 from Nov 17 stayed).
These tests pin the routing: prefixed ids -> Webull table only; plain
numeric ids -> the generic row, whatever provider label the row carries.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from core.extensions import db
from models import WatchlistCoin, WebullWatchlistItem


class SetWatchAlertRoutingTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://',
                               SECRET_KEY='test', TESTING=True)
        db.init_app(self.app)
        self.ctx = self.app.app_context()
        self.ctx.push()
        for model in (WatchlistCoin, WebullWatchlistItem):
            model.__table__.create(db.engine, checkfirst=True)
        self.ant = WatchlistCoin(user_id=1, symbol='ANT', asset_type='stock',
                                 down_alert=70.0, up_alert=83.0, alert_enabled=True)
        self.btc = WatchlistCoin(user_id=1, symbol='BTC', asset_type='crypto',
                                 down_alert=60000.0, up_alert=67500.0, alert_enabled=True)
        self.other_ant = WatchlistCoin(user_id=2, symbol='ANT', asset_type='stock',
                                       down_alert=1.0, up_alert=2.0, alert_enabled=True)
        db.session.add_all([self.ant, self.btc, self.other_ant])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()

    def _post(self, body, user_id=1):
        from routes import system
        user = SimpleNamespace(id=user_id)
        with self.app.test_request_context(method='POST', json=body), \
                patch.object(system, 'current_user', user):
            result = system.set_watch_alert.__wrapped__()
        return result[1] if isinstance(result, tuple) else 200

    # -- the bug: generic stock row carrying the Webull provider label ----
    def test_generic_stock_row_up_alert_persists_with_webull_source(self):
        status = self._post({'id': self.ant.id, 'source': 'webull', 'symbol': 'ANT',
                             'direction': 'up', 'value': 100})
        self.assertEqual(status, 200)
        db.session.refresh(self.ant)
        self.assertEqual(self.ant.up_alert, 100.0)
        self.assertEqual(WebullWatchlistItem.query.count(), 0)

    def test_generic_stock_row_down_alert_persists_with_webull_source(self):
        status = self._post({'id': self.ant.id, 'source': 'webull', 'symbol': 'ANT',
                             'direction': 'down', 'value': 89})
        self.assertEqual(status, 200)
        db.session.refresh(self.ant)
        self.assertEqual(self.ant.down_alert, 89.0)

    def test_generic_stock_row_alert_enabled_toggle_persists(self):
        status = self._post({'id': self.ant.id, 'source': 'webull', 'symbol': 'ANT',
                             'alert_enabled': False})
        self.assertEqual(status, 200)
        db.session.refresh(self.ant)
        self.assertFalse(self.ant.alert_enabled)

    def test_generic_stock_row_clear_alert_persists(self):
        status = self._post({'id': self.ant.id, 'source': 'webull', 'symbol': 'ANT',
                             'direction': 'up', 'value': ''})
        self.assertEqual(status, 200)
        db.session.refresh(self.ant)
        self.assertIsNone(self.ant.up_alert)

    # -- unchanged paths ----------------------------------------------------
    def test_generic_crypto_row_alert_edit_still_persists(self):
        status = self._post({'id': self.btc.id, 'source': 'binance', 'symbol': 'BTC',
                             'direction': 'up', 'value': 70000})
        self.assertEqual(status, 200)
        db.session.refresh(self.btc)
        self.assertEqual(self.btc.up_alert, 70000.0)

    def test_prefixed_webull_item_still_routes_to_webull_table(self):
        item = WebullWatchlistItem(user_id=1, symbol='ANT', instrument_type='EQUITY')
        db.session.add(item)
        db.session.commit()
        status = self._post({'id': f'webull-watchlist-{item.id}', 'source': 'webull',
                             'symbol': 'ANT', 'direction': 'up', 'value': 123})
        self.assertEqual(status, 200)
        db.session.refresh(item)
        db.session.refresh(self.ant)
        self.assertEqual(item.up_alert, 123.0)
        self.assertEqual(self.ant.up_alert, 83.0)

    def test_prefixed_id_for_missing_webull_item_404s_and_touches_nothing(self):
        status = self._post({'id': 'webull-watchlist-999999', 'source': 'webull',
                             'symbol': 'ANT', 'direction': 'up', 'value': 100})
        self.assertEqual(status, 404)
        db.session.refresh(self.ant)
        self.assertEqual(self.ant.up_alert, 83.0)

    def test_cannot_edit_another_users_row_by_id(self):
        status = self._post({'id': self.other_ant.id, 'source': 'webull',
                             'symbol': 'ZZZ', 'direction': 'up', 'value': 100},
                            user_id=1)
        self.assertEqual(status, 404)
        db.session.refresh(self.other_ant)
        self.assertEqual(self.other_ant.up_alert, 2.0)


if __name__ == '__main__':
    unittest.main()
