import unittest
import json
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

from portfolio_algo_models import (
    DEFAULT_ALLOCATIONS,
    DEFAULT_MODULE_SETTINGS,
    DEFAULT_QUANT_WATCHLISTS,
    PortfolioStrategyConfig,
    PortfolioStrategyAccount,
    PortfolioStrategyPosition,
    PortfolioStrategyOrder,
)
from routes.portfolio_algo import reset_portfolio_bankroll


class PortfolioAlgoTests(unittest.TestCase):
    def test_default_allocations_sum_to_100(self):
        total = sum(DEFAULT_ALLOCATIONS.values())
        self.assertAlmostEqual(total, 100.0, places=2)
        self.assertEqual(DEFAULT_ALLOCATIONS["equities"], 35.0)
        self.assertEqual(DEFAULT_ALLOCATIONS["options"], 25.0)
        self.assertEqual(DEFAULT_ALLOCATIONS["crypto"], 20.0)
        self.assertEqual(DEFAULT_ALLOCATIONS["futures"], 10.0)
        self.assertEqual(DEFAULT_ALLOCATIONS["events"], 10.0)

    def test_default_watchlists_structure(self):
        self.assertIn("equities", DEFAULT_QUANT_WATCHLISTS)
        self.assertIn("options", DEFAULT_QUANT_WATCHLISTS)
        self.assertIn("crypto", DEFAULT_QUANT_WATCHLISTS)
        self.assertIn("futures", DEFAULT_QUANT_WATCHLISTS)
        self.assertIn("events", DEFAULT_QUANT_WATCHLISTS)

        # Ensure top-tier assets exist
        self.assertIn("SPY", DEFAULT_QUANT_WATCHLISTS["equities"])
        self.assertIn("QQQ", DEFAULT_QUANT_WATCHLISTS["equities"])
        self.assertIn("NVDA", DEFAULT_QUANT_WATCHLISTS["equities"])
        self.assertIn("BTC", DEFAULT_QUANT_WATCHLISTS["crypto"])
        self.assertIn("ETH", DEFAULT_QUANT_WATCHLISTS["crypto"])
        self.assertIn("MES", DEFAULT_QUANT_WATCHLISTS["futures"])
        self.assertIn("KXBTC15M", DEFAULT_QUANT_WATCHLISTS["events"])

    def test_default_module_settings(self):
        for key in ("equities", "options", "crypto", "futures", "events"):
            self.assertIn(key, DEFAULT_MODULE_SETTINGS)
            self.assertIn("strategy", DEFAULT_MODULE_SETTINGS[key])
            self.assertIn("target_cagr_range", DEFAULT_MODULE_SETTINGS[key])

    @patch("routes.portfolio_algo.PortfolioStrategyAccount")
    @patch("routes.portfolio_algo.PortfolioStrategyConfig")
    @patch("routes.portfolio_algo.PortfolioStrategyPosition")
    @patch("routes.portfolio_algo.PortfolioStrategyOrder")
    @patch("routes.portfolio_algo.db")
    def test_reset_portfolio_bankroll(self, mock_db, mock_order, mock_pos, mock_cfg_model, mock_acc_model):
        mock_acc = SimpleNamespace(
            initial_balance=10000.0,
            cash_balance=8500.0,
            total_equity=8500.0,
            reset_at=None,
            updated_at=None,
        )
        mock_acc_model.query.filter_by.return_value.first.return_value = mock_acc

        mock_cfg = SimpleNamespace(
            total_bankroll=10000.0,
            updated_at=None,
        )
        mock_cfg_model.query.filter_by.return_value.first.return_value = mock_cfg

        result = reset_portfolio_bankroll(user_id=1, amount=50000.0)

        self.assertEqual(result["initial_balance"], 50000.0)
        self.assertEqual(result["cash_balance"], 50000.0)
        self.assertEqual(result["total_equity"], 50000.0)
        self.assertEqual(mock_acc.cash_balance, 50000.0)
        self.assertEqual(mock_cfg.total_bankroll, 50000.0)
        mock_pos.query.filter_by.return_value.delete.assert_called_once()
        mock_order.query.filter_by.return_value.delete.assert_called_once()
        mock_db.session.commit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
