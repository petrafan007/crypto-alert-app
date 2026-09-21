import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from core.extensions import db
from credentials import User, UserSetting
from event_algo_models import EventStrategyConfig, EventStrategyLog, EventStrategyReport
from models import (
    AICopilotSession,
    AIConversation,
    ExternalSentimentSignal,
    WebullAccountSnapshot,
    WebullHolding,
    WebullOrder,
    WebullTestAccount,
    WebullTestOrder,
    WebullTestPosition,
    WebullWatchlistItem,
)
from portfolio_algo_models import (
    PortfolioAudit,
    PortfolioEngineLog,
    PortfolioEngineState,
    PortfolioStrategyAccount,
    PortfolioStrategyConfig,
)
from services.copilot_context import (
    build_admin_quant_copilot_snapshot,
    build_webull_copilot_snapshot,
    copilot_market_queries,
    copilot_question_scope,
    copilot_context_json,
)
from routes.ai import process_ai_conversation
from trading_models import AllActivity, RealOrder, TestOrder


class CopilotExpandedContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            TESTING=True,
        )
        db.init_app(cls.app)
        cls.context = cls.app.app_context()
        cls.context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        cls.context.pop()

    def setUp(self):
        db.session.rollback()
        for model in (
            AIConversation, AICopilotSession, AllActivity, RealOrder, TestOrder,
            EventStrategyReport, EventStrategyLog, EventStrategyConfig,
            PortfolioAudit, PortfolioEngineLog, PortfolioEngineState,
            PortfolioStrategyAccount, PortfolioStrategyConfig,
            ExternalSentimentSignal, WebullTestOrder, WebullTestPosition,
            WebullTestAccount, WebullOrder, WebullWatchlistItem,
            WebullHolding, WebullAccountSnapshot, UserSetting, User,
        ):
            db.session.query(model).delete()
        db.session.commit()

        self.admin = User(username="admin", email="admin@example.test")
        self.admin.set_password("ValidPassword!234")
        self.member = User(username="member", email="member@example.test")
        self.member.set_password("ValidPassword!234")
        db.session.add_all([self.admin, self.member])
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()

    def test_webull_snapshot_covers_real_test_watchlist_orders_and_signals(self):
        now = datetime.utcnow()
        db.session.add(UserSetting(
            user_id=self.member.id,
            webull_environment="production",
            webull_test_mode_enabled=True,
            webull_default_account_id="REAL-1234",
            webull_enabled_account_ids='["REAL-1234"]',
        ))
        db.session.add(WebullAccountSnapshot(
            user_id=self.member.id,
            account_id="REAL-1234",
            account_name="Primary",
            account_type="Individual Cash",
            total_net_liquidation_value=12345,
            total_cash_balance=2345,
            total_market_value=10000,
            synced_at=now,
        ))
        db.session.add(WebullHolding(
            user_id=self.member.id,
            account_id="REAL-1234",
            symbol="NVDA",
            instrument_type="EQUITY",
            quantity=5,
            last_price=200,
            current_value=1000,
            cost_price=180,
            unrealized_profit_loss=100,
            synced_at=now,
        ))
        db.session.add(WebullWatchlistItem(
            user_id=self.member.id,
            symbol="SPY",
            instrument_type="ETF",
            last_price=650,
            note="Watch support",
        ))
        db.session.add(WebullOrder(
            user_id=self.member.id,
            account_id="REAL-1234",
            provider_order_id="provider-order-1",
            symbol="AAPL",
            instrument_type="EQUITY",
            side="BUY",
            order_type="LIMIT",
            quantity=2,
            price=190,
            status="WORKING",
            created_at=now,
            synced_at=now,
        ))
        db.session.add(ExternalSentimentSignal(
            user_id=self.member.id,
            provider="webull",
            symbol="NVDA",
            instrument_type="EQUITY",
            prompt_family="equity",
            recommendation="Hold",
            reason="Valuation is elevated.",
            entry_price=200,
            forecast_horizon_hours=24,
            target_evaluation_at=now + timedelta(hours=24),
        ))
        db.session.add(WebullTestAccount(user_id=self.member.id, cash_balance=50000))
        db.session.add(WebullTestPosition(
            user_id=self.member.id,
            symbol="TSLA",
            instrument_type="EQUITY",
            quantity=3,
            cost_price=300,
            last_price=310,
            market_value=930,
            unrealized_pnl=30,
        ))
        db.session.add(WebullTestOrder(
            order_id="SIM-1",
            user_id=self.member.id,
            symbol="TSLA",
            instrument_type="EQUITY",
            side="BUY",
            order_type="LIMIT",
            quantity=3,
            limit_price=300,
            status="Filled",
        ))
        db.session.commit()

        snapshot = build_webull_copilot_snapshot(self.member.id)
        self.assertEqual(snapshot["real_mode"]["accounts"][0]["net_liquidation_value"], 12345)
        self.assertEqual(snapshot["real_mode"]["holdings"][0]["symbol"], "NVDA")
        self.assertEqual(snapshot["real_mode"]["watchlist"][0]["symbol"], "SPY")
        self.assertEqual(snapshot["real_mode"]["orders"][0]["status"], "WORKING")
        self.assertEqual(snapshot["real_mode"]["ai_signals"][0]["recommendation"], "Hold")
        self.assertTrue(snapshot["test_mode"]["enabled"])
        self.assertEqual(snapshot["test_mode"]["positions"][0]["symbol"], "TSLA")
        self.assertEqual(snapshot["test_mode"]["orders"][0]["order_id"], "SIM-1")

    def test_quant_context_is_admin_only_and_contains_settings_logs_reports_without_secrets(self):
        now = datetime.utcnow()
        db.session.add(PortfolioStrategyConfig(
            user_id=self.admin.id,
            name="Default Multi-Asset Portfolio",
            master_ai_config=json.dumps({
                "primary": {"provider": "openai", "model": "gpt-test", "api_key": "do-not-leak"},
            }),
        ))
        db.session.add(PortfolioStrategyAccount(user_id=self.admin.id))
        db.session.add(PortfolioEngineState(user_id=self.admin.id))
        db.session.add(PortfolioEngineLog(
            user_id=self.admin.id,
            level="WARNING",
            event_type="DATA_LIMITED",
            message="Options history is warming up.",
            details_json='{"symbol":"SPY"}',
        ))
        db.session.add(PortfolioAudit(
            user_id=self.admin.id,
            generation=1,
            status="SUCCESS",
            content="Quantitative portfolio audit content.",
            evidence_json='{"audit_context_version":3}',
        ))
        event_cfg = EventStrategyConfig(
            user_id=self.admin.id,
            name="Event Contracts",
            enabled=True,
            mode="PAPER",
            worker_status="RUNNING",
            symbols='["BTC"]',
            durations='["FIFTEEN_MINUTES"]',
            risk_config='{"max_position":25}',
            signal_config='{"scan_interval_seconds":60}',
            ai_config='{"primary":{"api_key":"event-secret","provider":"openai","model":"gpt-test"}}',
        )
        db.session.add(event_cfg)
        db.session.flush()
        db.session.add(EventStrategyLog(
            user_id=self.admin.id,
            config_id=event_cfg.id,
            level="INFO",
            event_type="SCAN_COMPLETE",
            message="Event scan completed.",
        ))
        db.session.add(EventStrategyReport(
            user_id=self.admin.id,
            config_id=event_cfg.id,
            period_start=now - timedelta(hours=6),
            period_end=now,
            status="HEALTHY",
            headline="Event engine healthy",
            summary="No operational fault.",
            content_markdown="## Event audit\nAll recorded scans completed.",
            metrics_json='{"scans":6}',
        ))
        db.session.commit()

        self.assertIsNone(build_admin_quant_copilot_snapshot(self.member.id, self.member))

        snapshot = build_admin_quant_copilot_snapshot(
            self.admin.id,
            self.admin,
            "Show the latest quantitative strategy logs and reports.",
        )
        rendered = copilot_context_json(snapshot)
        self.assertEqual(snapshot["authorization"], "ADMINISTRATOR-ONLY CONTEXT")
        self.assertEqual(
            snapshot["quantitative_portfolio_engine"]["logs"][0]["event_type"],
            "DATA_LIMITED",
        )
        self.assertIn(
            "Quantitative portfolio audit content.",
            snapshot["quantitative_portfolio_engine"]["reports"][0]["content"],
        )
        self.assertEqual(
            snapshot["event_contract_strategy_engine"]["logs"][0]["event_type"],
            "SCAN_COMPLETE",
        )
        self.assertIn(
            "All recorded scans completed.",
            snapshot["event_contract_strategy_engine"]["reports"][0]["content_markdown"],
        )
        self.assertNotIn("do-not-leak", rendered)
        self.assertNotIn("event-secret", rendered)
        self.assertIn("[CONFIGURED - VALUE REDACTED]", rendered)

    def test_quant_context_stays_compact_until_the_admin_asks_for_engine_detail(self):
        db.session.add(PortfolioStrategyConfig(
            user_id=self.admin.id,
            name="Default Multi-Asset Portfolio",
        ))
        db.session.add(PortfolioStrategyAccount(user_id=self.admin.id))
        db.session.add(PortfolioEngineState(user_id=self.admin.id))
        db.session.add(PortfolioEngineLog(
            user_id=self.admin.id,
            event_type="COMPACT_CONTEXT_TEST",
            message="Only load this when quantitative detail is relevant.",
        ))
        db.session.commit()

        snapshot = build_admin_quant_copilot_snapshot(
            self.admin.id,
            self.admin,
            "What is the current BTC market price?",
        )

        portfolio = snapshot["quantitative_portfolio_engine"]
        self.assertFalse(snapshot["retrieval_scope"]["detail_requested"])
        self.assertIn("settings", portfolio)
        self.assertIn("report_catalog", portfolio)
        self.assertNotIn("logs", portfolio)
        self.assertNotIn("reports", portfolio)
        self.assertNotIn("current_status", portfolio)

    def test_quant_log_exact_id_search_reaches_beyond_the_recent_window(self):
        db.session.add(PortfolioStrategyConfig(
            user_id=self.admin.id,
            name="Default Multi-Asset Portfolio",
        ))
        db.session.add(PortfolioStrategyAccount(user_id=self.admin.id))
        db.session.add(PortfolioEngineState(user_id=self.admin.id))
        old_log = PortfolioEngineLog(
            user_id=self.admin.id,
            event_type="OLD_ARCHIVE_RECORD",
            message="Exact lookup must find this historical evidence.",
            created_at=datetime.utcnow() - timedelta(days=30),
        )
        db.session.add(old_log)
        db.session.flush()
        old_log_id = old_log.id
        for index in range(110):
            db.session.add(PortfolioEngineLog(
                user_id=self.admin.id,
                event_type="RECENT_RECORD",
                message=f"Recent log {index}",
                created_at=datetime.utcnow() + timedelta(seconds=index),
            ))
        db.session.commit()

        snapshot = build_admin_quant_copilot_snapshot(
            self.admin.id,
            self.admin,
            f"Inspect quant log #{old_log_id}.",
        )
        portfolio = snapshot["quantitative_portfolio_engine"]

        self.assertNotIn(old_log_id, [row["id"] for row in portfolio["logs"]])
        self.assertIn(old_log_id, [row["id"] for row in portfolio["archive_log_matches"]])
        self.assertTrue(portfolio["log_window"]["archive_search_performed"])

    def test_general_market_question_excludes_account_context_and_uses_timeframe(self):
        from services.copilot_context import copilot_market_search, is_general_market_question
        question = "how is it that bitcoin is up almost 10% in the past 10 days even though the fed increase interest rates and inflation is still higher than they want?"
        self.assertTrue(is_general_market_question(question))
        self.assertFalse(is_general_market_question("How does inflation affect my BTC holdings?"))
        self.assertFalse(is_general_market_question("What about that?"))
        with patch("routes.ai.call_ai_with_web_search") as provider, \
             patch("routes.ai.build_webull_copilot_snapshot", side_effect=AssertionError("Account lookup for market question")), \
             patch("routes.ai.build_admin_quant_copilot_snapshot", side_effect=AssertionError("Quant lookup for market question")):
            provider.return_value = (SimpleNamespace(
                text="Market explanation.", tier="primary", provider="test", model="test-model",
            ), "")
            result = process_ai_conversation(self.member.id, question)
        self.assertEqual(result[0], "Market explanation.")
        prompt = provider.call_args.kwargs['messages'][0]['content']
        self.assertIn('GENERAL MARKET QUESTION (BTC)', prompt)
        self.assertNotIn('LIVE USER DATABASE SNAPSHOT', prompt)
        self.assertNotIn('RECENT COMPLETED TRANSACTIONS', prompt)
        query, freshness = copilot_market_search(prompt, 'BTC')
        self.assertIn('inflation', query)
        self.assertIn('past 10 days', query)
        self.assertNotIn('Historical conversation', query)
        self.assertEqual(freshness, 'pm')

        for wording in (
            'Why did Bitcoin surge yesterday?',
            'What is Bitcoin doing today?',
            'Explain Apple earnings',
        ):
            self.assertEqual(copilot_question_scope(wording), 'market')
        self.assertEqual(
            copilot_question_scope('What about that?', ['Why did Bitcoin surge yesterday?']),
            'market',
        )
        queries, freshness = copilot_market_queries(
            'Why did BTC and ETH rise over the past ten days?\n\nCompare inflation too.',
            ['BTC', 'ETH'],
        )
        self.assertEqual(freshness, 'pm')
        self.assertIn('Compare inflation too', queries[0])
        self.assertTrue(any('historical closing price' in query for query in queries))

    def test_focused_crypto_chat_handles_missing_and_numeric_realized_pnl(self):
        trade = AllActivity(
            user_id=self.member.id, date=datetime.now(), type="BUY",
            asset="BTC", amount=0.01, avg_entry=80000, status="FILLED",
            gain_loss=None,
        )
        db.session.add(trade)
        db.session.commit()
        cases = (
            ("BUY", None, "not applicable (purchase; no realized profit/loss)"),
            ("BUY", 0, "not applicable (purchase; no realized profit/loss)"),
            ("SELL", None, "unavailable (not recorded)"),
            ("SELL", 0, "+$0.00"), ("SELL", 12.5, "+$12.50"),
            ("SELL", -4.25, "$-4.25"),
        )
        for side, value, expected in cases:
            with self.subTest(side=side, gain_loss=value):
                trade.type = side
                trade.gain_loss = value
                db.session.commit()
                with patch("routes.ai.call_ai_with_web_search") as provider:
                    provider.return_value = (SimpleNamespace(
                        text="Context received.", tier="primary",
                        provider="test", model="test-model",
                    ), "")
                    result = process_ai_conversation(
                        self.member.id, "Review my bitcoin trades and holdings"
                    )
                self.assertEqual(result[0], "Context received.")
                prompt = provider.call_args.kwargs["messages"][0]["content"]
                self.assertIn(f"Recent Execution: {side}", prompt)
                self.assertIn(f"(Realized PnL: {expected})", prompt)

    def test_copilot_request_injects_quant_context_for_admin_only(self):
        db.session.add(PortfolioStrategyConfig(
            user_id=self.admin.id,
            name="Default Multi-Asset Portfolio",
        ))
        db.session.add(PortfolioStrategyAccount(user_id=self.admin.id))
        db.session.add(PortfolioEngineState(user_id=self.admin.id))
        db.session.add(PortfolioEngineLog(
            user_id=self.admin.id,
            event_type="ROLE_ISOLATION_TEST",
            message="Visible only in administrator context.",
        ))
        db.session.commit()

        captured = []

        def fake_ai_call(**kwargs):
            captured.append(kwargs["messages"][0]["content"])
            return SimpleNamespace(
                text="Context received.",
                tier="primary",
                provider="test",
                model="test-model",
            ), ""

        with patch("routes.ai.call_ai_with_web_search", side_effect=fake_ai_call):
            process_ai_conversation(self.admin.id, "How is the quant engine?")
            process_ai_conversation(self.member.id, "How is the quant engine?")

        self.assertIn("ADMINISTRATOR-ONLY QUANTITATIVE STRATEGY ENGINE CONTEXT", captured[0])
        self.assertIn("ROLE_ISOLATION_TEST", captured[0])
        self.assertNotIn("ADMINISTRATOR-ONLY QUANTITATIVE STRATEGY ENGINE CONTEXT", captured[1])
        self.assertNotIn("ROLE_ISOLATION_TEST", captured[1])
        self.assertIn("WEBULL REAL TRADING MODE + TEST MODE CONTEXT", captured[1])


if __name__ == "__main__":
    unittest.main()
