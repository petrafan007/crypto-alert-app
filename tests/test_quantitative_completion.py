"""v3.3 research integrity, exact-window audit and durable runtime regressions."""
import json
import os
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch, Mock
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from flask import Flask
from sqlalchemy.schema import CreateSchema
from core.extensions import db
from event_algo_models import EventStrategyConfig as Config, EventStrategyRun as Run, EventStrategyLog as Log, EventStrategyDecision as Decision, EventStrategyAIEvaluation as Evaluation, EventMarketSnapshot as Snapshot, EventStrategyReport as Report
from credentials import User, UserSetting
from portfolio_algo_models import PortfolioStrategyConfig as PortfolioConfig, PortfolioEngineState as State, PortfolioMarketObservation as Observation
from services.provider_resilience import ProviderState, AIRequestDeferred, AuditCancelled
from services.event_audit import gather, deterministic_report, cited_interpretation
from services.event_runtime import budget, event_request_guard
from services.portfolio_iv import atm_pair, collection_window, iv_source


class QuantitativeCompletionTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        uri = os.environ.get('QUANT_COMPLETION_TEST_DATABASE_URI', 'sqlite://')
        schema = 'completion_'+uuid4().hex
        self.app.config.update(SQLALCHEMY_DATABASE_URI=uri, TESTING=True)
        if uri.startswith('postgresql'):
            self.app.config['SQLALCHEMY_ENGINE_OPTIONS']={'connect_args':{'options':'-csearch_path='+schema+' -cstatement_timeout=10000'}}
        db.init_app(self.app)
        self.ctx=self.app.app_context();self.ctx.push()
        if uri.startswith('postgresql'):
            with db.engine.begin() as con: con.execute(CreateSchema(schema))
        db.metadata.create_all(db.engine,tables=[m.__table__ for m in (User,UserSetting,Config,Run,Log,Decision,Evaluation,Snapshot,Report,PortfolioConfig,State,ProviderState,Observation)])
        self.config=Config(user_id=1,name='Test',enabled=True,worker_status='RUNNING')
        db.session.add(self.config);db.session.commit()
        self.now=datetime.utcnow()
        from services.event_runtime import _memory
        _memory.clear()

    def tearDown(self):
        db.session.remove();db.engine.dispose();self.ctx.pop()

    def test_exact_window_counts_exceed_samples_and_isolate_configuration(self):
        for idx in range(260):
            db.session.add(Log(user_id=1,config_id=self.config.id,level='ERROR' if idx==0 else 'INFO',event_type='TEST',message='Evidence',created_at=self.now-timedelta(minutes=1)))
        for idx in range(120):
            db.session.add(Decision(user_id=1,config_id=self.config.id,contract_symbol=str(idx),action='NO_TRADE',eligible=False,reason_codes='["EDGE"]',created_at=self.now-timedelta(minutes=1)))
        for user,config,when in [(2,self.config.id,self.now),(1,999,self.now),(1,self.config.id,self.now-timedelta(hours=7)),(1,self.config.id,self.now+timedelta(hours=1))]:
            db.session.add(Log(user_id=user,config_id=config,level='ERROR',event_type='OUTSIDE',message='Never included',created_at=when))
        db.session.add(Run(user_id=1,config_id=self.config.id,scanned_count=130,error_count=1,status='COMPLETED',heartbeat_at=self.now))
        db.session.commit()
        result=gather(1,self.config,6)
        self.assertEqual(result['metrics']['total_logs'],260)
        self.assertEqual(result['metrics']['log_error_count'],1)
        self.assertEqual(result['metrics']['error_count'],1)
        self.assertEqual(result['metrics']['scan_error_count'],1)
        self.assertEqual(result['metrics']['decisions_count'],120)
        self.assertEqual(result['sampling']['decisions']['supplied'],100)
        self.assertTrue(result['sampling']['decisions']['truncated'])
        self.assertEqual(len(result['recent_errors']),1)
        self.assertEqual(result['metrics']['scanned_contracts'],130)

    def test_empty_window_never_imports_old_history_or_certifies_health(self):
        db.session.add(Run(user_id=1,config_id=self.config.id,started_at=self.now-timedelta(days=1),scanned_count=100))
        db.session.commit()
        result=gather(1,self.config,2)
        self.assertEqual(result['metrics']['scans_count'],0)
        report=deterministic_report(result)
        self.assertNotEqual(report['status'],'HEALTHY')
        self.assertNotIn('6-hour',report['content_markdown'])
        self.assertNotIn('valid bid/ask spreads',report['content_markdown'])

    def test_unknown_timestamps_are_counted_and_model_cannot_supply_facts(self):
        db.session.add(Snapshot(user_id=1,config_id=self.config.id,contract_symbol='TEST',raw_json='{}'))
        db.session.commit()
        data=gather(1,self.config,6)
        self.assertEqual(data['metrics']['quote_status_at_retrieval'],{'UNKNOWN':1})
        with self.assertRaises(ValueError): cited_interpretation('{"complete":true,"observations":[{"text":"great","evidence_refs":["log:999"]}]}',data)
        with self.assertRaises(ValueError): cited_interpretation('{"observations":[]}',data)
        text=cited_interpretation('{"complete":true,"observations":[{"text":"# Fake table | 9000","evidence_refs":["metrics"]}]}',data)
        self.assertIn('unverified suggestions',text)
        self.assertNotIn('# Fake',text)

    def test_controls_and_deadline_guard_uses_fresh_saved_values(self):
        guard=event_request_guard(1,self.config.id,seconds=100)
        guard()
        self.config.enabled=False;db.session.commit()
        with self.assertRaises(AuditCancelled):guard()
        expired=event_request_guard(1,self.config.id,seconds=-1)
        with self.assertRaises(AuditCancelled):expired()

    def test_report_persists_facts_and_rejects_late_model_output(self):
        from event_algo import generate_event_strategy_report
        db.session.add(User(id=1,username='audit-test',pwd_hash='unused'))
        db.session.commit()
        with patch('services.ai_service.is_ai_enabled', return_value=False):
            report = generate_event_strategy_report(1,self.config,hours=2)
        self.assertEqual(report.status,'ATTENTION_REQUIRED')
        self.assertEqual(json.loads(report.metrics_json)['audit_evidence_version'],2)
        self.assertEqual(Log.query.filter_by(event_type='REPORT_COMPLETED').count(),1)
        def stop_and_respond(**kwargs):
            self.config.enabled=False
            db.session.commit()
            return SimpleNamespace(text='{"complete":true,"observations":[]}'), ''
        with patch('services.ai_service.is_ai_enabled',return_value=True), patch('event_algo.get_event_strategy_ai_tiers_and_keys',return_value=([],{})), patch('services.ai_service.call_ai_with_web_search',side_effect=stop_and_respond):
            with self.assertRaises(AuditCancelled):generate_event_strategy_report(1,self.config,hours=2)
        self.assertEqual(Report.query.count(),1)

    def test_budget_counts_attempts_and_expires_without_process_reset(self):
        budget(1,2,reserve=True);budget(1,2,reserve=True)
        with self.assertRaises(AIRequestDeferred):budget(1,2,reserve=True)
        self.assertEqual(budget(1)['calls'],2)
        self.assertEqual(budget(2)['calls'],0)
        with patch('services.event_runtime.time.time',return_value=__import__('time').time()+3601):
            self.assertEqual(budget(1)['calls'],0)

    @unittest.skipUnless(os.environ.get('QUANT_COMPLETION_TEST_DATABASE_URI','').startswith('postgresql'),'PostgreSQL concurrency')
    def test_two_connections_cannot_spend_same_last_request(self):
        barrier=Barrier(2)
        def consume(_):
            with self.app.app_context():
                barrier.wait(timeout=5)
                try: budget(1,1,reserve=True);return True
                except AIRequestDeferred:return False
        with ThreadPoolExecutor(max_workers=2) as pool: result=list(pool.map(consume,[1,2]))
        self.assertEqual(sum(result),1)
        self.assertEqual(budget(1)['calls'],1)

    def test_portfolio_watchlist_controls_provider_series_and_missing_is_explicit(self):
        from services.event_universe import collection_targets,matches_series
        db.session.add(PortfolioConfig(user_id=1,watchlists_json='{"events":["KXINXD","KXBTC15M","MISSING"]}'));db.session.commit()
        with patch('services.webull_service.get_webull_event_categories',return_value=[{'category_code':'CRYPTO'},{'category_code':'FINANCIALS'}]),patch('services.webull_service.get_webull_event_series',side_effect=[[{'series_symbol':'KXBTC15M'}],[{'series_symbol':'KXINXD'}]]):
            targets,missing=collection_targets(1,self.config,('','','',''))
        self.assertEqual({row[0] for row in targets},{'KXINXD','KXBTC15M'})
        self.assertEqual(missing,['MISSING'])
        self.assertFalse(matches_series({'symbol':'KXOTHER-TEST'},'KXINXD'))
        self.assertTrue(matches_series({'symbol':'KXINXD-TEST'},'KXINXD'))

    def test_iv_pairs_and_early_close_sampling_are_consistent(self):
        quotes=[{'strike':100,'option_type':'CALL','implied_volatility':.2}, {'strike':100,'option_type':'PUT','implied_volatility':.4}, {'strike':101,'option_type':'CALL','implied_volatility':8}]
        self.assertAlmostEqual(atm_pair(quotes,100.5),.3)
        with self.assertRaises(ValueError):atm_pair(quotes[2:],101)
        self.assertNotEqual(iv_source(30),iv_source(45))
        self.assertTrue(collection_window(datetime(2026,11,27,17,50,tzinfo=timezone.utc)))
        self.assertFalse(collection_window(datetime(2026,11,27,18,1,tzinfo=timezone.utc)))
        self.assertFalse(collection_window(datetime(2026,11,28,17,50,tzinfo=timezone.utc)))

    def test_daily_iv_freeze_and_old_methodology_exclusion(self):
        from services.portfolio_strategy_data import PortfolioMarketData
        from services.portfolio_iv import iv_series
        data=object.__new__(PortfolioMarketData);data.user_id=1
        data.observe('IV:SPY',.2,self.now,source='WEBULL_OPTION_QUOTES')
        data.observe(iv_series('SPY',30),.3,self.now,source=iv_source(30),preserve_daily=True)
        rows=data.observe(iv_series('SPY',30),.8,self.now,source=iv_source(30),preserve_daily=True)
        self.assertEqual(rows[0].value,.3)
        self.assertEqual(data.observation_history('IV:SPY','WEBULL_OPTION_QUOTES',self.now.date())[0].value,.2)
        self.assertEqual(data.observation_history('IV:SPY',iv_source(45),self.now.date()),[])

    def test_module_correlation_does_not_invent_zero_for_missing_module(self):
        from services.portfolio_engine import measured_correlations
        rows=[SimpleNamespace(created_at=self.now+timedelta(days=i),modules_json=json.dumps({'equities':i*i,'crypto':i*i*2})) for i in range(35)]
        with patch('services.portfolio_engine.daily_snapshots',return_value=rows):result=measured_correlations(1,1)
        pair=next(row for row in result if row['a']=='equities' and row['b']=='crypto')
        self.assertAlmostEqual(pair['pearson_r'],1)
        self.assertEqual(pair['basis'],'DAILY_MODULE_DOLLAR_PNL_CHANGES')
        self.assertTrue(all(row['daily_samples']==0 for row in result if 'options' in (row['a'],row['b'])))


class EventResearchTests(unittest.TestCase):
    def payload(self):
        rows=[]
        for day in (1,2):
            when=f'2026-09-0{day}T12:00:00Z'
            rows.append(dict(symbol='TEST'+str(day),decision_at=when,cutoff_at=f'2026-09-0{day}T12:15:00Z',resolved_at=f'2026-09-0{day}T12:16:00Z',outcome='YES',probability_yes=.8,confidence=.9,independent_quote_at=when,
                market=dict(symbol='TEST'+str(day),quote_retrieved_at=when,quote_time_basis='RETRIEVAL_ONLY',yes_bid=.39,yes_ask=.4,no_bid=.59,no_ask=.6,yes_ask_size=1,no_ask_size=1)))
        return dict(schema_version=1,module='events',source='Synthetic test observations',split_at='2026-09-02T00:00:00Z',records=rows)

    def test_event_sensitivity_requires_reported_depth_and_discloses_pairing(self):
        from services.event_research_validation import run_event_validation
        data=self.payload()
        result=run_event_validation(data,SimpleNamespace(risk_config='{}',signal_config='{}'))
        window=result['windows']['held_out']
        self.assertFalse(result['source_verified'])
        self.assertEqual(window['paired_independent_timestamps'],1)
        self.assertGreater(window['scenarios'][0]['net_pnl'],window['scenarios'][2]['net_pnl'])
        data['records'][1]['market'].pop('yes_ask_size')
        window=run_event_validation(data,SimpleNamespace(risk_config='{}',signal_config='{}'))['windows']['held_out']
        self.assertIsNone(window['scenarios'][0]['net_pnl'])
        self.assertEqual(window['scenarios'][0]['exclusions']['unknown_depth_no_assumed_fill'],1)

    def test_duplicate_post_cutoff_or_naive_observations_rejected(self):
        from services.event_research_validation import run_event_validation
        for key,value in [('symbol','TEST1'),('decision_at','2026-09-02T12:20:00Z'),('decision_at','2026-09-02T12:00:00')]:
            data=self.payload();data['records'][1][key]=value
            with self.assertRaises(ValueError):run_event_validation(data,SimpleNamespace(risk_config='{}',signal_config='{}'))

    def test_stale_book_cannot_supply_contemporaneous_market_benchmark(self):
        from services.event_research_validation import run_event_validation
        data=self.payload()
        data['records'][1]['market']['quote_retrieved_at']='2026-09-02T11:00:00Z'
        result=run_event_validation(data,SimpleNamespace(risk_config='{}',signal_config='{}'))
        window=result['windows']['held_out']
        self.assertIsNone(window['calibration']['market_brier_score'])
        self.assertIsNone(window['scenarios'][0]['net_pnl'])
