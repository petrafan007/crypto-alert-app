"""Point-in-time research regressions and actual-ledger replay accounting."""
import copy
import gzip
import hashlib
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch
from flask import Flask,g
from flask_login import LoginManager
from sqlalchemy.schema import CreateSchema
from core.extensions import db
from credentials import User
from research_data_models import ResearchDataset,ResearchJob,ResearchCapture,ResearchCollectionConfig,ResearchCollectionState,utcnow
from portfolio_algo_models import PortfolioStrategyConfig,PortfolioMarketObservation,DEFAULT_MODULE_SETTINGS,DEFAULT_ALLOCATIONS,DEFAULT_QUANT_WATCHLISTS
from event_algo_models import EventMarketSnapshot,EventStrategyDecision,EventContractOutcome,EventStrategyConfig
from services.research_dataset import canonical,validate_row,adapt,encoded,save_dataset,get_dataset,build_archive,stamp
from services.research_history import ResearchMarketData,iv_preview,apply_iv
from services.research_replay import scenario_run,timeline,run_replay
from services.research_jobs import enqueue,process_one,import_preview

NOW=datetime(2025,6,2,14,tzinfo=timezone.utc)


def row(kind,module,symbol,at=NOW,**fields):
    return {'kind':kind,'module':module,'symbol':symbol,'source':'TEST','currency':'USD','event_at':at.isoformat(),
            'available_at':at.isoformat(),'timestamp_basis':'PROVIDER',**fields}


def config(*enabled):
    settings=copy.deepcopy(DEFAULT_MODULE_SETTINGS)
    for key in settings:settings[key]['enabled']=key in enabled
    return {'settings':settings,'allocations':DEFAULT_ALLOCATIONS,'watchlists':copy.deepcopy(DEFAULT_QUANT_WATCHLISTS),
            'bankroll':1000,'target':18.5,'currency':'USD','event':{'risk':{},'signal':{},'config_id':None}}


def crypto_data(prices=(105,108,109,95),symbols=('BTCUSD',)):
    rows=[]
    for symbol in symbols:
        for i in range(200):
            t=NOW-timedelta(hours=201-i)
            rows.append(row('bar','crypto',symbol,t,available_at=(t+timedelta(hours=1)).isoformat(),complete_at=(t+timedelta(hours=1)).isoformat(),interval='1h',open=100,high=101,low=99,close=100,volume=100))
        for i,price in enumerate(prices):
            rows.append(row('quote','crypto',symbol,NOW+timedelta(minutes=5*i),price=price,bid=price-.1,ask=price+.1,ask_size=1000,bid_size=1000))
    return canonical(rows,{'origin':'SYNTHETIC_TEST'})


def option_data():
    at=NOW.replace(hour=19,minute=50);expiry=str((at+timedelta(days=45)).date())
    rows=[row('catalog','options','SPY',at,source='WEBULL_PRODUCTION',start=str(at.date()+timedelta(days=20)),end=str(at.date()+timedelta(days=65)),cycle_id='cycle',page=None,next=None)]
    for kind,strike,symbol in [('PUT',90,'P90'),('PUT',85,'P85'),('CALL',90,'C90')]:
        rows.append(row('contract','options',symbol,at,source='WEBULL_PRODUCTION',root='SPY',expiration=expiry,strike=strike,option_type=kind,multiplier=100,standard=True))
    for i in range(2):
        moment=at+timedelta(minutes=5*i)
        rows.append(row('quote','equities','SPY',moment,source='WEBULL_PRODUCTION',price=100))
        rows.append(row('quote_batch','options','SPY',moment,source='WEBULL_PRODUCTION',cycle_id='cycle',symbols=['P90','P85','C90']))
        for symbol,bid,ask,delta in [('P90',2,2.1,-.18),('P85',.5,.6,-.09),('C90',10,10.2,.8)]:
            rows.append(row('option_quote','options',symbol,moment,source='WEBULL_PRODUCTION',bid=bid,ask=ask,bid_size=2,ask_size=2,implied_volatility=.4,delta=delta,iv_units='DECIMAL'))
    return canonical(rows,{'origin':'LOCAL_ARCHIVE'})


class ResearchPureTests(unittest.TestCase):
    def test_calendar_batch_cache_preserves_holidays_early_close_and_dst(self):
        from datetime import date
        from services.portfolio_strategy_signals import session_bounds
        self.assertIsNone(session_bounds(date(2025,7,4)))
        self.assertEqual(session_bounds(date(2025,7,3))[1].hour,17)
        self.assertEqual(session_bounds(date(2025,1,6))[0].hour,14)
        self.assertEqual(session_bounds(date(2025,6,2))[0].hour,13)

    def test_invalid_timestamp_numeric_and_candle_inputs_rejected(self):
        for changes in ({'event_at':'2025-06-02T14:00:00'},{'price':True},{'price':float('nan')},{'bid':101,'ask':99},{'available_at':'2025-06-02T13:00:00Z'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):validate_row(row('quote','equities','SPY',price=100,**changes) if 'price' not in changes else row('quote','equities','SPY',**changes))
        bad=row('bar','crypto','BTCUSD',interval='1h',open=1,high=2,low=1,close=2,volume=1,complete_at=NOW.isoformat())
        with self.assertRaises(ValueError):validate_row(bad)

    def test_duplicate_quotes_keep_first_availability_and_revisions_stay_later(self):
        one=row('quote','equities','SPY',price=100)
        duplicate={**one,'available_at':(NOW+timedelta(seconds=10)).isoformat(),'capture_id':2}
        revision={**duplicate,'price':101}
        data=canonical([duplicate,one,revision],{'origin':'TEST'})
        self.assertEqual(data['quality']['accepted'],2);self.assertEqual(data['quality']['duplicates_removed'],1)
        provider=ResearchMarketData(data)
        self.assertEqual(provider.quote('SPY','EQUITY',NOW+timedelta(seconds=5)),100)
        self.assertEqual(provider.quote('SPY','EQUITY',NOW+timedelta(seconds=11)),101)

    def test_collected_backfill_cannot_be_used_before_receipt(self):
        data=crypto_data()
        for r in data['records']:
            if r['kind']=='bar':r['available_at']=(NOW+timedelta(hours=1)).isoformat()
        provider=ResearchMarketData(data)
        with self.assertRaisesRegex(ValueError,'No completed'):provider.bars('BTC','CRYPTO',NOW,interval='H1')

    def test_currency_and_sources_do_not_silently_mix(self):
        data=canonical([row('quote','crypto','BTCUSDT',currency='USDT',price=100)],{'origin':'TEST'})
        with self.assertRaises(ValueError):ResearchMarketData(data).quote('BTC','CRYPTO',NOW)
        self.assertEqual(ResearchMarketData(data,'USDT').quote('BTC','CRYPTO',NOW),100)

    def test_stale_provider_quote_never_uses_fresh_receipt(self):
        data=canonical([row('quote','equities','SPY',price=100,available_at=(NOW+timedelta(minutes=5)).isoformat())],{'origin':'TEST'})
        with self.assertRaises(ValueError):ResearchMarketData(data).quote('SPY','EQUITY',NOW+timedelta(minutes=5))
        self.assertEqual(data['quality']['stale_quotes_at_receipt'],1)

    def test_archive_adapter_keeps_book_unknown_time_and_exact_currency(self):
        raw=encoded({'bids':[['100','3']],'asks':[['101','2']],'lastUpdateId':9})
        cap=SimpleNamespace(payload_gzip=gzip.compress(raw),sha256=hashlib.sha256(raw).hexdigest(),metadata_json='{}',received_at=NOW,id=1,source='BINANCE_US_PUBLIC',kind='crypto_depth',symbol='BTCUSDT')
        record=list(adapt(cap))[0]
        self.assertEqual(record['timestamp_basis'],'RECEIPT_ONLY');self.assertEqual(record['currency'],'USDT');self.assertEqual(record['price'],100.5)

    def test_independent_books_keep_reported_dollars_and_receipt_pairing(self):
        raw=encoded({'orderbook_fp':{'yes_dollars':[['0.4','12.5']],'no_dollars':[['0.58','9']]}})
        cap=SimpleNamespace(payload_gzip=gzip.compress(raw),sha256=hashlib.sha256(raw).hexdigest(),metadata_json='{}',received_at=NOW+timedelta(seconds=2),id=1,source='KALSHI_PUBLIC',kind='independent_event_depth',symbol='KXBTC15M-TEST')
        independent=list(adapt(cap))[0]
        self.assertEqual(independent['timestamp_basis'],'RECEIPT_ONLY')
        webull=row('event_book','events',cap.symbol,source='WEBULL_PRODUCTION',yes_bids=[{'price':.4,'size':10}],no_bids=[])
        data=canonical([webull,independent],{'origin':'TEST'})
        result=data['quality']['independent_books']
        self.assertEqual(result['paired_books'],1);self.assertEqual(result['same_best_bid'],1)
        self.assertEqual(result['median_receipt_gap_seconds'],2);self.assertEqual(result['missing_reported_side'],1)
        self.assertEqual(result['different_best_bid_size'],1)
        independent['available_at']=(NOW+timedelta(seconds=6)).isoformat()
        self.assertEqual(canonical([webull,independent],{})['quality']['independent_books']['paired_books'],0)

    def test_import_rejects_malformed_or_negative_depth(self):
        for levels in ([{}],[None],[{'price':.4,'size':-1}]):
            with self.assertRaises(ValueError):validate_row(row('event_book','events','EVENT',yes_bids=levels))

    def test_iv_preview_requires_complete_catalog_batches_and_real_close(self):
        data=option_data();preview=iv_preview(data,45)
        self.assertEqual(preview['sessions'],1);self.assertAlmostEqual(preview['accepted'][0]['value'],.4)
        for kind in ('catalog','quote_batch'):
            partial={**data,'records':[r for r in data['records'] if r['kind']!=kind]}
            self.assertEqual(iv_preview(partial,45)['sessions'],0)
        stale=copy.deepcopy(data)
        for r in stale['records']:
            if r['kind']=='option_quote':r['event_at']=NOW.isoformat()
        self.assertEqual(iv_preview(stale,45)['sessions'],0)

    def test_paginated_catalog_requires_unbroken_chain(self):
        data=option_data();catalog=next(r for r in data['records'] if r['kind']=='catalog');catalog['next']='page2'
        provider=ResearchMarketData(data)
        at=NOW.replace(hour=19,minute=55)
        self.assertFalse(provider.complete_catalog('SPY','WEBULL_PRODUCTION',at.date(),at))
        data['records'].append({**catalog,'page':'page2','next':None})
        self.assertTrue(ResearchMarketData(data).complete_catalog('SPY','WEBULL_PRODUCTION',at.date(),at))

    def test_options_rank_uses_252_same_source_method_target_days(self):
        import pandas_market_calendars as calendars
        data=option_data();at=NOW.replace(hour=19,minute=55)
        schedule=calendars.get_calendar('NYSE').schedule(start_date=at.date()-timedelta(days=370),end_date=at.date()-timedelta(days=1)).tail(252)
        self.assertEqual(len(schedule),252)
        history=[row('iv','options','SPY',r.market_close.to_pydatetime()-timedelta(minutes=5),source='WEBULL_PRODUCTION',value=.2+i/1000,target_dte=45,methodology='ATM_PAIR_V1',iv_units='DECIMAL') for i,(_,r) in enumerate(schedule.iterrows())]
        provider=ResearchMarketData(data,iv_observations=history)
        self.assertIsNotNone(provider.options('SPY',{'target_dte':45},at)[2])
        history.pop();self.assertIsNone(provider.options('SPY',{'target_dte':45},at)[2])
        self.assertIsNone(provider.options('SPY',{'target_dte':30},at)[2])

    def test_import_preview_does_not_certify_source_or_accept_unknown_iv_units(self):
        data,digest=import_preview({'schema_version':2,'source':'Provider export with permission','records':[row('quote','equities','SPY',price=100)]})
        self.assertFalse(data['provenance']['source_verified']);self.assertEqual(len(digest),64)
        with self.assertRaises(ValueError):validate_row(row('option_quote','options','TEST',implied_volatility=40,iv_units='PERCENT'))

    def test_actual_crypto_ledger_accounting_and_chronological_reset(self):
        data=crypto_data();cfg=config('crypto');cfg['watchlists']['crypto']=['BTC']
        result=run_replay(data,cfg,{'start':NOW.isoformat(),'split':(NOW+timedelta(minutes=10)).isoformat(),'end':(NOW+timedelta(minutes=16)).isoformat()})
        first=result['windows']['development']['scenarios'][0];last=result['windows']['held_out']['scenarios'][0]
        self.assertEqual(first['entries'],1);self.assertEqual(last['entries'],1)
        self.assertEqual(first['starting_equity'],last['starting_equity'])
        self.assertEqual(last['closed_trades'],1)
        self.assertAlmostEqual(last['ending_equity'],1000+last['trades'][0]['net_pnl'],6)
        self.assertGreaterEqual(min(r['cash'] for r in first['equity_curve']),0)
        delayed=result['windows']['held_out']['scenarios'][2]
        self.assertEqual(delayed['entries'],0)

    def test_shared_capital_multiple_symbols_and_reported_depth(self):
        data=crypto_data(prices=(105,108),symbols=('BTCUSD','TESTUSD'))
        cfg=config('crypto');cfg['watchlists']['crypto']=['BTC','TEST']
        with patch.object(ResearchMarketData,'dominance_ok',return_value=True):
            result=scenario_run(data,cfg,timeline(data,NOW,NOW+timedelta(minutes=6)),'baseline',[])
        self.assertEqual(result['entries'],2)
        self.assertLessEqual(result['maximum_reserved_capital'],1000)
        self.assertGreaterEqual(result['cash'],0)
        for r in data['records']:
            if r['kind']=='quote':r['ask_size']=.002
        limited=scenario_run(data,cfg,timeline(data,NOW,NOW+timedelta(minutes=6)),'half_reported_depth',[])
        self.assertLess(limited['maximum_reserved_capital'],1)

    def test_options_run_actual_spread_margin_and_depth(self):
        data=option_data();cfg=config('options');cfg['bankroll']=100000;cfg['watchlists']['options']=['SPY']
        original=ResearchMarketData.options
        def ready(provider,*args):
            price,quotes,_=original(provider,*args)
            return price,quotes,80  # This test targets ledger accounting, not IV warm-up (tested separately).
        times=timeline(data,NOW.replace(hour=19,minute=50),NOW.replace(hour=19,minute=56))
        with patch.object(ResearchMarketData,'options',ready):
            result=scenario_run(data,cfg,times,'baseline',[])
        self.assertEqual(result['entries'],1)
        self.assertEqual(result['trades'][0]['collateral'],360)
        self.assertAlmostEqual(result['trades'][0]['entry_fee'],1.3)
        self.assertLess(result['ending_equity'],100000)
        for r in data['records']:
            if r['kind']=='option_quote':r['bid_size']=None
        with patch.object(ResearchMarketData,'options',ready):
            result=scenario_run(data,cfg,times,'baseline',[])
        self.assertEqual(result['entries'],0)
        self.assertIn('No reported two-leg option depth.',result['decisions'])

    def test_futures_session_exit_actual_multiplier_and_margin(self):
        at=NOW.replace(hour=19,minute=50);symbol='MESM25'
        rows=[row('contract','futures',symbol,at,root='MES',expiration='2025-06-20',multiplier=5,margin=500)]
        opening=NOW.replace(hour=13,minute=30)
        for i in range(380):
            t=opening+timedelta(minutes=i)
            rows.append(row('bar','futures',symbol,t,available_at=(t+timedelta(minutes=1)).isoformat(),complete_at=(t+timedelta(minutes=1)).isoformat(),interval='1m',open=100,high=101,low=99,close=100,volume=100))
        # Entry before the final 15-minute gate, then session exit at 15:55 ET.
        entry=at-timedelta(minutes=20)
        rows[0]['available_at']=entry.isoformat();rows[0]['event_at']=entry.isoformat()
        for t in (entry,at+timedelta(minutes=5)):rows.append(row('quote','futures',symbol,t,price=105,bid_size=100,ask_size=100))
        data=canonical(rows,{'origin':'TEST'});cfg=config('futures');cfg['bankroll']=100000;cfg['watchlists']['futures']=['MES']
        result=scenario_run(data,cfg,timeline(data,entry,at+timedelta(minutes=6)),'baseline',[])
        self.assertEqual(result['entries'],1);self.assertEqual(result['closed_trades'],1)
        self.assertGreater(result['trades'][0]['collateral'],0)
        self.assertAlmostEqual(result['ending_equity'],100000+result['trades'][0]['net_pnl'],6)

    def test_event_settlement_waits_for_observation_and_releases_cash_once(self):
        symbol='KXBTC15M-TEST';cutoff=NOW+timedelta(minutes=10);observed=cutoff+timedelta(minutes=2)
        market={'symbol':symbol,'series_symbol':'KXBTC15M','volume':500,'open_interest':100,'cutoff_at':cutoff.isoformat()}
        rows=[row('forecast','events',symbol,probability_yes=.8,confidence=.9,outcome='YES',cutoff_at=cutoff.isoformat(),market=market,decision_id=1,config_id=1),
              row('event_quote','events',symbol,yes_bid=.39,yes_ask=.4,no_bid=.60,no_ask=.62,yes_ask_size=100,no_ask_size=100),
              row('outcome','events',symbol,cutoff,available_at=observed.isoformat(),cutoff_at=cutoff.isoformat(),outcome='YES',config_id=1),
              row('event_quote','events',symbol,observed+timedelta(seconds=1),yes_bid=1,yes_ask=1,no_bid=0,no_ask=0)]
        cfg=config('events');cfg['watchlists']['events']=['KXBTC15M']
        data=canonical(rows,{'origin':'TEST'});points=timeline(data,NOW,observed+timedelta(seconds=2))
        result=scenario_run(data,cfg,points,'baseline',[])
        self.assertEqual(result['entries'],1);self.assertEqual(result['closed_trades'],1)
        self.assertEqual(result['trades'][0]['closed_at'],observed.isoformat())
        self.assertAlmostEqual(result['ending_equity'],1000+result['trades'][0]['net_pnl'],6)
        mismatched=copy.deepcopy(rows)
        mismatched[2]['cutoff_at']=(cutoff-timedelta(seconds=1)).isoformat()
        result=scenario_run(canonical(mismatched,{}),cfg,points,'baseline',[])
        self.assertEqual(result['closed_trades'],0)
        self.assertIn('Settlement cutoff does not match the purchased contract.',result['module_errors']['events'])

    def test_child_replay_is_offline_and_returns_valid_json(self):
        data=crypto_data();cfg=config('crypto');cfg['watchlists']['crypto']=['BTC']
        payload={'dataset':data,'config':cfg,'request':{'start':NOW.isoformat(),'split':(NOW+timedelta(minutes=10)).isoformat(),'end':(NOW+timedelta(minutes=16)).isoformat()}}
        result=subprocess.run([sys.executable,'-m','services.research_replay'],input=encoded(payload),capture_output=True,timeout=60,env={**os.environ,'OPENBLAS_NUM_THREADS':'1','PYTHONWARNINGS':'ignore::DeprecationWarning'})
        self.assertEqual(result.returncode,0,result.stdout.decode()[-1000:]+result.stderr.decode()[-1000:])
        self.assertTrue(json.loads(result.stdout)['success'])


class ResearchDatabaseTests(unittest.TestCase):
    def setUp(self):
        uri=os.environ.get('QUANT_WORKBENCH_TEST_DATABASE_URI','sqlite://');schema='workbench_'+uuid4().hex
        self.app=Flask(__name__);self.app.config.update(SECRET_KEY='test',TESTING=True,SQLALCHEMY_DATABASE_URI=uri)
        if uri.startswith('postgresql'):self.app.config['SQLALCHEMY_ENGINE_OPTIONS']={'connect_args':{'options':'-csearch_path='+schema+' -cstatement_timeout=10000'}}
        db.init_app(self.app);self.ctx=self.app.app_context();self.ctx.push()
        if uri.startswith('postgresql'):
            with db.engine.begin() as con:con.execute(CreateSchema(schema))
        db.metadata.create_all(db.engine,tables=[m.__table__ for m in (User,ResearchCollectionConfig,ResearchCollectionState,ResearchCapture,ResearchDataset,ResearchJob,PortfolioStrategyConfig,PortfolioMarketObservation,EventStrategyConfig,EventMarketSnapshot,EventStrategyDecision,EventContractOutcome)])
        db.session.add(User(id=1,username='admin',pwd_hash='test'));db.session.add(PortfolioStrategyConfig(user_id=1));db.session.commit()

    def tearDown(self):
        db.session.remove();db.engine.dispose();self.ctx.pop()

    def test_dataset_idempotent_user_scoped_and_budgeted(self):
        data=crypto_data();one=save_dataset(1,data);again=save_dataset(1,data)
        self.assertEqual(one.id,again.id);self.assertEqual(ResearchDataset.query.count(),1)
        self.assertEqual(db.session.get(ResearchCollectionConfig,1).stored_bytes,len(one.payload_gzip)+len(one.summary_json.encode()))
        with self.assertRaises(ValueError):get_dataset(2,one.id)

    def test_append_iv_is_idempotent_and_preserves_conflicts(self):
        dataset=save_dataset(1,option_data());first=apply_iv(1,dataset.id,dataset.sha256,45)
        self.assertEqual(first['inserted'],1)
        again=apply_iv(1,dataset.id,dataset.sha256,45);self.assertEqual(again['already_present'],1)
        old=PortfolioMarketObservation.query.one();old.value=.9;db.session.commit()
        result=apply_iv(1,dataset.id,dataset.sha256,45)
        self.assertEqual(result['conflicting_existing_retained'],1);self.assertEqual(PortfolioMarketObservation.query.one().value,.9)

    def test_import_cannot_overwrite_live_iv(self):
        data=option_data();data['provenance']['origin']='IMPORTED';dataset=save_dataset(1,data)
        with self.assertRaises(ValueError):apply_iv(1,dataset.id,dataset.sha256,45)
        self.assertEqual(PortfolioMarketObservation.query.count(),0)

    def test_job_limits_and_failure_are_durable(self):
        dataset=save_dataset(1,crypto_data());req={'dataset_id':dataset.id}
        enqueue(1,'iv_preview',req);enqueue(1,'iv_preview',req)
        with self.assertRaises(ValueError):enqueue(1,'iv_preview',req)
        with patch('services.research_history.iv_preview',side_effect=ValueError('Bad fixture')):self.assertTrue(process_one())
        failed=ResearchJob.query.order_by(ResearchJob.id).first();self.assertEqual(failed.status,'FAILED');self.assertEqual(failed.message,'Bad fixture')

    def test_abandoned_job_fails_and_next_queued_job_finishes(self):
        dataset=save_dataset(1,crypto_data());enqueue(1,'iv_preview',{'dataset_id':dataset.id})
        db.session.add(ResearchJob(user_id=1,kind='replay',status='RUNNING',started_at=utcnow()-timedelta(minutes=7),request_json='{}'));db.session.commit()
        process_one()
        self.assertCountEqual([r.status for r in ResearchJob.query.all()],['COMPLETED','FAILED'])

    def test_audit_research_summary_is_bounded_and_user_scoped(self):
        from services.research_jobs import audit_summary
        dataset=save_dataset(1,crypto_data());enqueue(1,'iv_preview',{'dataset_id':dataset.id});process_one()
        summary=audit_summary(1)
        self.assertEqual(summary['jobs'][0]['status'],'COMPLETED')
        self.assertEqual(summary['jobs'][0]['summary']['sessions'],0)
        self.assertEqual(summary['datasets'][0]['id'],dataset.id)
        self.assertNotIn('records',json.dumps(summary));self.assertEqual(audit_summary(2)['jobs'],[])

    def test_live_iv_sampler_preserves_concurrent_archive_insert(self):
        from flask_sqlalchemy.query import Query
        from services.portfolio_strategy_data import PortfolioMarketData
        from services.portfolio_iv import iv_series,iv_source
        series=iv_series('SPY',45);source=iv_source(45)
        observation=PortfolioMarketObservation(user_id=1,series=series,day=NOW.date(),value=.4,source=source,observed_at=NOW.replace(tzinfo=None))
        db.session.add(observation);db.session.commit()
        provider=PortfolioMarketData.__new__(PortfolioMarketData);provider.user_id=1
        with patch.object(Query,'first',return_value=None):
            history=provider.observe(series,.9,NOW,source=source,preserve_daily=True)
        self.assertEqual(len(history),1);self.assertEqual(history[0].value,.4)
        self.assertEqual(PortfolioMarketObservation.query.count(),1)

    def test_routes_enforce_admin_preview_and_ownership(self):
        from routes.portfolio_algo import portfolio_algo_bp
        manager=LoginManager(self.app)
        @manager.user_loader
        def load(value):return db.session.get(User,int(value))
        @self.app.before_request
        def clear():g.pop('_login_user',None)
        self.app.register_blueprint(portfolio_algo_bp);client=self.app.test_client();base='/api/webull/portfolio-algo/research'
        self.assertEqual(client.get(base).status_code,401)
        with client.session_transaction() as session:session['_user_id']='1'
        payload={'schema_version':2,'source':'Permitted test export','records':[row('quote','equities','SPY',price=100)]}
        preview=client.post(base+'/import',json={'dataset':payload}).json['preview']
        self.assertEqual(ResearchDataset.query.count(),0)
        self.assertEqual(client.post(base+'/import',json={'dataset':payload,'commit':True,'sha256':'wrong'}).status_code,400)
        saved=client.post(base+'/import',json={'dataset':payload,'commit':True,'sha256':preview['sha256']})
        self.assertEqual(saved.status_code,200)
        with patch('routes.portfolio_algo.is_event_strategy_admin',return_value=False):self.assertEqual(client.get(base).status_code,403)
        self.assertEqual(client.get(base+'/datasets/999999').status_code,400)


if __name__=='__main__':unittest.main()
