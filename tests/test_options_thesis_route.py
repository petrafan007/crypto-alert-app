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

    def test_far_otm_payload_uses_market_derived_iv_and_adaptive_spot_range(self):
        response = self.client.post("/api/options/thesis", json={
            "underlying_symbol": "AAPL",
            "baseline_price": 316.85,
            "strike_price": 235.00,
            "entry_premium": 0.04,
            "market_premium": 0.04,
            "multiplier": 100,
            "quantity": 2,
            "iv": 0,
            "risk_free_rate": 0.0379,
            "expiration_date": "2026-10-02",
            "starting_dte": 32,
            "option_type": "PUT",
            "action": "BUY",
        })

        self.assertEqual(response.status_code, 200)
        thesis = response.get_json()["thesis"]
        self.assertEqual(thesis["scenario_range_percent"], 0.30)
        self.assertEqual(thesis["rows"][0]["percent_change"], 0.30)
        self.assertEqual(thesis["rows"][-1]["percent_change"], -0.30)
        iv_assumption = next(item for item in thesis["assumptions"] if item["label"] == "Implied volatility")
        self.assertGreater(iv_assumption["value"], 0.30)
        self.assertEqual(iv_assumption["note"], "Derived from the current market mark")


if __name__ == "__main__":
    unittest.main()