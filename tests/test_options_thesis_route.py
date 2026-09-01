import unittest

from flask import Flask

from routes.market import market_bp


class OptionsThesisRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY="test", LOGIN_DISABLED=True, TESTING=True)
        self.app.register_blueprint(market_bp)
        self.client = self.app.test_client()

    def test_returns_the_complete_canonical_thesis_payload(self):
        response = self.client.post("/api/options/thesis", json={
            "underlying_symbol": "AAPL",
            "baseline_price": 316.85,
            "strike_price": 302.50,
            "entry_premium": 0.05,
            "multiplier": 100,
            "quantity": 2,
            "iv": 0.1501,
            "risk_free_rate": 0.0379,
            "expiration_date": "2026-09-02",
            "starting_dte": 0,
            "option_type": "PUT",
        })

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["thesis"]["underlying_symbol"], "AAPL")
        self.assertEqual(payload["thesis"]["columns"], [{"dte": 0, "date": "2026-09-02"}])
        self.assertEqual(payload["thesis"]["rows"][-1]["underlying_price"], 285.17)
        self.assertAlmostEqual(payload["thesis"]["rows"][-1]["pnl"][0], 3456.0, places=2)


if __name__ == "__main__":
    unittest.main()