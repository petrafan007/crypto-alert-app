"""Research archive authorization, integrity, limits and transport regressions."""
import gzip
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4
from flask import Flask, g
from flask_login import LoginManager
from sqlalchemy.schema import CreateSchema
from core.extensions import db
from research_data_models import ResearchCollectionConfig as Config, ResearchCollectionState as State, ResearchCapture as Capture, utcnow
from services import research_archive as archive
from services.research_collection import Collector, collect_once, rotated, next_cursor
from portfolio_algo_models import PortfolioStrategyConfig as Portfolio


class ResearchCollectionTests(unittest.TestCase):
    def setUp(self):
        uri = os.environ.get('QUANT_RESEARCH_TEST_DATABASE_URI','sqlite://')
        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY='test', TESTING=True, SQLALCHEMY_DATABASE_URI=uri)
        schema = 'research_'+uuid4().hex
        if uri.startswith('postgresql'):
            self.app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'connect_args':{'options':'-csearch_path='+schema+' -cstatement_timeout=10000'}}
        db.init_app(self.app)
        self.ctx = self.app.app_context(); self.ctx.push()
        if uri.startswith('postgresql'):
            with db.engine.begin() as con: con.execute(CreateSchema(schema))
        db.metadata.create_all(db.engine,tables=[m.__table__ for m in (Config, State, Capture, Portfolio)])
        archive.configure(1,{'enabled':True})
        self.now=utcnow()

    def tearDown(self):
        db.session.remove(); db.engine.dispose(); self.ctx.pop()

    def save(self, payload=None, user=1):
        return archive.save_capture(user,'crypto','BINANCE_US_PUBLIC','crypto_depth','BTCUSDT',payload or {'bids':[['1','2']]},self.now)

    def test_roundtrip_retains_provider_time_and_redacts_credentials(self):
        self.save({'quote_time':123, 'nested':{'access_token':'private','secret':'private','price':'0.40'}, 'bids':[['0.39','20']]})
        data=archive.export_page(1)['records'][0]
        self.assertEqual(data['payload'],{'quote_time':123,'nested':{'price':'0.40'},'bids':[['0.39','20']]})
        self.assertNotEqual(data['received_at'],123)
        self.assertTrue(data['sha256'])
        self.assertEqual(archive.status(1)['stored_bytes'],Capture.query.one().compressed_bytes+2)

    def test_export_is_user_scoped_and_cursor_complete(self):
        archive.configure(2,{'enabled':True})
        first=self.save(); self.save(user=2); last=self.save({'last':True})
        page=archive.export_page(1,limit=1)
        self.assertEqual([r['id'] for r in page['records']],[first])
        page=archive.export_page(1,after=page['next_cursor'])
        self.assertEqual([r['id'] for r in page['records']],[last])
        self.assertIsNone(page['next_cursor'])

    def test_corruption_rejected(self):
        self.save(); row=Capture.query.one(); row.payload_gzip=gzip.compress(b'{}'); db.session.commit()
        with self.assertRaisesRegex(ValueError,'checksum'): archive.export_page(1)

    def test_pause_rejects_late_result(self):
        archive.configure(1,{'enabled':False})
        with self.assertRaises(archive.CollectionPaused): self.save()
        self.assertEqual(Capture.query.count(),0)

    def test_cap_preserves_history_and_rejects_next_write(self):
        self.save()
        cfg=db.session.get(Config,1); cfg.stored_bytes=100*1024*1024-1; cfg.settings_json='{"storage_mb":100}'; db.session.commit()
        with self.assertRaisesRegex(archive.CollectionPaused,'storage'): self.save({'new':True})
        self.assertEqual(Capture.query.count(),1)
        self.assertEqual(db.session.get(Config,1).stored_bytes,100*1024*1024-1)

    def test_settings_and_payload_limits(self):
        for value in ({'enabled':'yes'},{'storage_mb':True},{'crypto_seconds':0},{'paid':True}):
            with self.assertRaises(ValueError): archive.configure(1,value)
        with self.assertRaises(ValueError): self.save({'data':'x'*(4*1024*1024)})
        with self.assertRaises(ValueError): self.save({'price':float('nan')})
        self.assertEqual(Capture.query.count(),0)

    def test_public_transport_is_credential_free_and_archived(self):
        c=Collector(1,'crypto',archive.DEFAULTS,{})
        response=Mock(status_code=200); response.json.return_value={'bids':[],'asks':[],'lastUpdateId':7}
        with patch('requests.get',return_value=response) as get, patch('event_algo._webull_connection_for_user') as creds:
            c.fetch('crypto_depth','BTCUSDT',{'symbol':'BTCUSDT','limit':1000})
        creds.assert_not_called(); self.assertNotIn('headers',get.call_args.kwargs)
        self.assertEqual(get.call_args.args[0],'https://api.binance.us/api/v3/depth')
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        self.assertEqual(Capture.query.one().source,'BINANCE_US_PUBLIC')

    def test_pause_during_transport_discards_response(self):
        c=Collector(1,'crypto',archive.DEFAULTS,{})
        def paused(*args,**kwargs):
            archive.configure(1,{'enabled':False})
            response=Mock(status_code=200); response.json.return_value={'bids':[]}; return response
        with patch('requests.get',side_effect=paused),self.assertRaises(archive.CollectionPaused):
            c.fetch('crypto_depth','BTCUSDT',{})
        self.assertEqual(Capture.query.count(),0)

    def test_access_denial_cools_endpoint_without_purchasing(self):
        c=Collector(1,'events',archive.DEFAULTS,{})
        creds=SimpleNamespace(webull_app_key='key',webull_app_secret='secret',webull_access_token='token')
        with patch('event_algo._webull_connection_for_user',return_value=(creds,'production')),patch('services.webull_service._webull_request',side_effect=ValueError('403 subscription required')) as request:
            c.fetch('event_depth','A',{}); c.fetch('event_depth','B',{})
        self.assertEqual(request.call_count,1)
        self.assertEqual(request.call_args.args[3],'GET')
        self.assertEqual(c.details['cooldowns']['event_depth']['status'],'ACCESS_REQUIRED')
        self.assertNotIn('secret',json.dumps(c.details))

    def test_missing_symbol_does_not_block_other_symbols(self):
        c=Collector(1,'crypto',archive.DEFAULTS,{})
        response=Mock(status_code=200); response.json.return_value={'bids':[]}
        with patch('requests.get',side_effect=[ValueError('invalid symbol'),response]) as request:
            c.fetch('crypto_depth','BAD',{}); c.fetch('crypto_depth','BTCUSDT',{})
        self.assertEqual(request.call_count,2); self.assertEqual(Capture.query.count(),1)

    def test_rotation_and_nested_pagination(self):
        self.assertEqual(rotated(['a','b','c'],2,2),(['c','a'],1))
        self.assertEqual(next_cursor({'data':{'pagination_key':'next'}},'pagination_key'),'next')

    def test_events_preserve_book_sides_and_use_singular_symbol(self):
        c=Collector(1,'events',archive.DEFAULTS,{})
        future=self.now+timedelta(hours=1)
        def fetch(kind,symbol,params):
            if kind=='event_catalog': return {'data':[{'symbol':'TEST-live','status':'LISTING','cutoff_at':future.isoformat()}, {'symbol':'TEST-old','status':'DELISTING','cutoff_at':self.now.isoformat()}]}
            return {'yes_bids':[['0.4','2']], 'no_bids':[['0.6','1']]}
        with patch.object(c,'fetch',side_effect=fetch) as request:
            c.events_lane({'events':['TEST']})
        calls=[call.args for call in request.call_args_list if call.args[0]=='event_depth']
        self.assertEqual(calls,[('event_depth','TEST-live',{'symbol':'TEST-live','category':'US_EVENT','depth':10})])

    def test_options_archive_unknown_timestamps_without_fabrication(self):
        c=Collector(1,'options',archive.DEFAULTS,{})
        exp=str((self.now+timedelta(days=30)).date())
        contract={'symbol':'SPY_TEST','underlying_symbol':'SPY','def_type':'STANDARD','multiplier':100,'expiration_date':exp,'strike_price':100,'option_type':'CALL'}
        def fetch(kind,symbol,params):
            if kind=='option_catalog': return {'data':[contract],'pagination_key':'more'}
            if kind=='stock_quotes': return [{'price':100}]
            return [{'symbol':'SPY_TEST','iv':0.3}]
        with patch('services.portfolio_strategy_signals.in_session',return_value=True),patch.object(c,'fetch',side_effect=fetch) as request:
            c.options_lane({'options':['SPY']},{'options':{'target_dte':30}})
        self.assertFalse(c.details['coverage']['SPY']['near_catalog_complete'])
        self.assertTrue(any(call.args[0]=='option_quotes' for call in request.call_args_list))

    def test_off_session_wait_and_previous_error_cleared(self):
        details={'off_session_date':str(self.now.date()),'waiting':'old','message':'old','cooldowns':{'old':{'retry_at':0}}}
        c=Collector(1,'options',archive.DEFAULTS,details)
        self.assertNotIn('message',details); self.assertFalse(details['cooldowns'])
        with patch('services.portfolio_strategy_signals.in_session',return_value=False),patch.object(c,'fetch') as request:
            c.options_lane({},{}); request.assert_not_called()
        self.assertIn('closed',details['waiting'])

    def test_worker_honors_saved_cadence(self):
        db.session.add(Portfolio(user_id=1)); db.session.commit()
        with patch('services.event_runtime.job_slot',return_value=nullcontext()),patch.object(Collector,'crypto_lane') as lane:
            collect_once(1,'crypto'); collect_once(1,'crypto')
        self.assertEqual(lane.call_count,1)
        self.assertEqual(State.query.one().status,'RECORDING')

    def test_routes_require_admin_and_exports_cannot_select_other_user(self):
        from routes.portfolio_algo import portfolio_algo_bp
        manager=LoginManager(self.app)
        @manager.user_loader
        def user(value): return SimpleNamespace(id=int(value),is_authenticated=True,is_active=True,is_anonymous=False)
        @self.app.before_request
        def clear(): g.pop('_login_user',None)
        self.app.register_blueprint(portfolio_algo_bp)
        client=self.app.test_client(); path='/api/webull/portfolio-algo/research-data'
        self.assertEqual(client.get(path).status_code,401)
        with client.session_transaction() as session: session['_user_id']='1'
        with patch('routes.portfolio_algo.is_event_strategy_admin',return_value=False): self.assertEqual(client.get(path).status_code,403)
        archive.configure(2,{'enabled':True}); self.save(user=2)
        with patch('routes.portfolio_algo.is_event_strategy_admin',return_value=True):
            result=client.get(path+'/export?user_id=2')
            self.assertEqual(result.status_code,200); self.assertEqual(result.json['records'],[])
            self.assertEqual(client.get(path+'/export?limit=101').status_code,400)

    def test_postgres_cap_atomic_across_collectors(self):
        if db.engine.dialect.name!='postgresql': self.skipTest('PostgreSQL locking test')
        payload={'same':'payload'}
        raw=json.dumps(payload,sort_keys=True,separators=(',',':')).encode()
        size=len(gzip.compress(raw,mtime=0))+2
        cfg=db.session.get(Config,1); cfg.settings_json='{"storage_mb":100}'; cfg.stored_bytes=100*1024*1024-size; db.session.commit()
        def insert():
            with self.app.app_context():
                try: self.save(payload); return 'saved'
                except archive.CollectionPaused: return 'paused'
                finally: db.session.remove()
        with ThreadPoolExecutor(max_workers=2) as pool: result=list(pool.map(lambda _:insert(),range(2)))
        self.assertCountEqual(result,['saved','paused']); self.assertEqual(Capture.query.count(),1)


if __name__=='__main__': unittest.main()
