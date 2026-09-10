import unittest
from datetime import datetime
from unittest.mock import patch

import pytz
from flask import Flask, jsonify
from flask_login import LoginManager, UserMixin

from services.ai_scheduler import _get_analysis_window_bounds
from services.scheduler_tasks import _workflow_response_result, run_due_ai_workflows_for_user


class FakeUser(UserMixin):
    def __init__(self):
        self.id = 7
        self.username = 'scheduler-user'


class AIWorkflowSchedulerTests(unittest.TestCase):
    def test_analysis_window_accepts_saved_hour_and_minute_strings(self):
        now = pytz.timezone('US/Eastern').localize(datetime(2026, 9, 9, 12, 0))

        start, end = _get_analysis_window_bounds({
            'ai_analysis_window_start': '07:30',
            'ai_analysis_window_end': '23:30',
        }, now)

        self.assertEqual((start.hour, start.minute), (7, 30))
        self.assertEqual((end.hour, end.minute), (23, 30))

    def test_analysis_window_rejects_out_of_range_saved_times(self):
        now = pytz.timezone('US/Eastern').localize(datetime(2026, 9, 9, 12, 0))

        start, end = _get_analysis_window_bounds({
            'ai_analysis_window_start': '99:90',
            'ai_analysis_window_end': 'invalid',
        }, now)

        self.assertEqual((start.hour, start.minute), (9, 0))
        self.assertEqual((end.hour, end.minute), (21, 0))

    def test_workflow_response_requires_http_and_payload_success(self):
        app = Flask(__name__)
        with app.app_context():
            success = _workflow_response_result(jsonify({'success': True}))
            failure = _workflow_response_result((jsonify({'success': False, 'error': 'provider failed'}), 500))

        self.assertEqual(success, (True, {'success': True}, 200))
        self.assertEqual(failure, (False, {'error': 'provider failed', 'success': False}, 500))

    @patch('services.ai_scheduler.update_ai_analysis_schedule')
    @patch('services.ai_scheduler.should_run_ai_analysis', return_value=True)
    @patch('services.ai_service.is_user_analysis_window_active', return_value=True)
    @patch('services.analysis_service.get_user_ai_settings', return_value={})
    @patch('services.analysis_service.is_ai_enabled', return_value=True)
    @patch('routes.ai.api_portfolio_review_workflow')
    @patch('routes.ai.api_market_analysis_workflow')
    def test_due_scheduler_runs_both_reports_then_advances_once(
        self, market_view, portfolio_view, _enabled, _settings, _window, _due, update_schedule,
    ):
        app = Flask(__name__)
        app.config.update(SECRET_KEY='test', TESTING=True)
        LoginManager(app)
        with app.app_context():
            market_view.side_effect = lambda: jsonify({'success': True})
            portfolio_view.side_effect = lambda: jsonify({'success': True})
            result = run_due_ai_workflows_for_user(app, FakeUser())

        self.assertEqual(result['status'], 'completed')
        market_view.assert_called_once_with()
        portfolio_view.assert_called_once_with()
        update_schedule.assert_called_once_with(7)


if __name__ == '__main__':
    unittest.main()
