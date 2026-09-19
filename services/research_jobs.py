"""Durable, bounded research jobs; computation never occupies a web worker."""
import gzip
import hashlib
import json
import os
import subprocess
import sys
import threading
from datetime import timedelta
from pathlib import Path
from core.extensions import db
from research_data_models import ResearchJob as Job,ResearchDataset as Dataset,ResearchCollectionConfig as Config,utcnow
from services.research_dataset import encoded,unpack,stamp,iso,get_dataset,build_archive,save_dataset,canonical


def reserve_storage(user_id,size):
    from services.research_archive import settings
    cfg=Config.query.filter_by(user_id=user_id).populate_existing().with_for_update().first()
    if cfg is None:
        cfg=Config(user_id=user_id,enabled=False,stored_bytes=0,settings_json='{}');db.session.add(cfg)
    if cfg.stored_bytes+size>settings(cfg)['storage_mb']*1048576:raise ValueError('Research storage capacity reached; existing history is retained.')
    cfg.stored_bytes+=size


def saved_config(user_id):
    from services.portfolio_engine import settings_for,loads
    from portfolio_algo_models import PortfolioStrategyConfig,DEFAULT_QUANT_WATCHLISTS
    from event_algo_models import EventStrategyConfig
    cfg=PortfolioStrategyConfig.query.filter_by(user_id=user_id).first()
    if cfg is None:raise ValueError('Save portfolio settings first.')
    event=EventStrategyConfig.query.filter_by(user_id=user_id).order_by(EventStrategyConfig.id).first()
    return {'settings':{m:{k:v for k,v in values.items() if not k.endswith('prompt')} for m,values in settings_for(cfg).items()},
            'watchlists':loads(cfg.watchlists_json,DEFAULT_QUANT_WATCHLISTS),'allocations':json.loads(cfg.allocations_json),
            'bankroll':cfg.total_bankroll,'target':cfg.target_annual_return,'currency':'USD',
            'event':{'risk':json.loads(event.risk_config) if event else {},'signal':json.loads(event.signal_config) if event else {},'config_id':event.id if event else None}}


def enqueue(user_id,kind,request):
    if kind not in ('build','daily_iv','replay','iv_preview','iv_apply'):raise ValueError('Unknown research job.')
    if not isinstance(request,dict):raise ValueError('Research request must be an object.')
    config=saved_config(user_id)
    if kind in ('build','daily_iv'):
        start,end=stamp(request.get('start')),stamp(request.get('end'))
        if not start<end or end-start>timedelta(days=370):raise ValueError('Select an archive range of up to 370 days.')
        clean={'start':iso(start),'end':iso(end)}
    else:
        row=Dataset.query.with_entities(Dataset.id,Dataset.sha256).filter_by(user_id=user_id,id=request.get('dataset_id')).first()
        if row is None:raise ValueError('Dataset not found for this administrator.')
        clean={'dataset_id':row.id,'sha256':row.sha256}
        if kind=='replay':
            times=[stamp(request.get(k)) for k in ('start','split','end')]
            if not times[0]<times[1]<times[2]:raise ValueError('Require start < chronological split < end.')
            clean.update(zip(('start','split','end'),map(iso,times)))
        if kind=='iv_apply' and request.get('sha256')!=row.sha256:raise ValueError('Preview this dataset before applying daily IV.')
    from services.event_runtime import job_slot
    with job_slot(user_id,'research-enqueue'):
        if Job.query.filter(Job.user_id==user_id,Job.status.in_(('QUEUED','RUNNING'))).count()>=2:raise ValueError('Two research jobs are already queued/running; wait for completion.')
        row=Job(user_id=user_id,kind=kind,request_json=json.dumps({'request':clean,'config':config}))
        reserve_storage(user_id,len(row.request_json.encode()))
        db.session.add(row);db.session.commit()
        return job_dict(row)


def job_dict(row,result=False):
    value={'id':row.id,'kind':row.kind,'status':row.status,'created_at':iso(row.created_at),'started_at':iso(row.started_at) if row.started_at else None,
           'completed_at':iso(row.completed_at) if row.completed_at else None,'message':row.message}
    if result and row.result_gzip:value['result']=unpack(row.result_gzip)
    return value


def process_one():
    # A killed process leaves a durable, visible failure instead of a spinner.
    for stale in Job.query.filter(Job.status=='RUNNING',Job.started_at<utcnow()-timedelta(minutes=6)).all():
        stale.status='FAILED';stale.completed_at=utcnow();stale.message='Worker interrupted or six-minute deadline exceeded; submit a new job.'
    db.session.commit()
    row=Job.query.filter_by(status='QUEUED').order_by(Job.id).with_for_update(skip_locked=True).first()
    if row is None:return False
    row.status='RUNNING';row.started_at=utcnow();job_id=row.id;user_id=row.user_id;kind=row.kind;value=json.loads(row.request_json)
    request,config=value['request'],value['config'];db.session.commit()
    try:
        from credentials import User
        from event_algo import is_event_strategy_admin
        if not is_event_strategy_admin(db.session.get(User,user_id)):raise ValueError('Administrator access is no longer available.')
        if kind in ('build','daily_iv'):
            data=build_archive(user_id,request['start'],request['end']);dataset=save_dataset(user_id,data)
            result={'dataset_id':dataset.id,'sha256':dataset.sha256,'quality':data['quality']}
            if kind=='daily_iv':
                from services.research_history import apply_iv
                result['daily_iv']=apply_iv(user_id,dataset.id,dataset.sha256,config['settings']['options']['target_dte'])
        else:
            dataset,data=get_dataset(user_id,request['dataset_id'])
            if dataset.sha256!=request['sha256']:raise ValueError('Dataset changed after job submission.')
            target=config['settings']['options']['target_dte']
            if kind=='iv_preview':
                from services.research_history import iv_preview
                result={**iv_preview(data,target),'dataset_id':dataset.id,'sha256':dataset.sha256}
            elif kind=='iv_apply':
                from services.research_history import apply_iv
                result=apply_iv(user_id,dataset.id,dataset.sha256,target)
            else:
                db.session.commit()
                # No shell, no production app import, bounded input/time/output.
                child=subprocess.run([sys.executable,'-m','services.research_replay'],input=encoded({'dataset':data,'config':config,'request':request}),
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=240,cwd=str(Path(__file__).resolve().parent.parent),
                    env={k:v for k,v in {**os.environ,'PYTHONWARNINGS':'ignore::DeprecationWarning','OPENBLAS_NUM_THREADS':'1'}.items() if k in ('PATH','LANG','LC_ALL','TZ','PYTHONWARNINGS','OPENBLAS_NUM_THREADS')})
                if len(child.stdout)>64*1048576:raise ValueError('Replay output exceeds 64 MiB; narrow the window.')
                try:reply=json.loads(child.stdout)
                except (ValueError,UnicodeError):raise ValueError('Replay process failed to return a valid result.') from None
                if child.returncode or not reply.get('success'):raise ValueError(reply.get('message','Replay process failed.'))
                result=reply['result']
                result['dataset_id']=dataset.id;result['dataset_sha256']=dataset.sha256
        row=db.session.get(Job,job_id,populate_existing=True)
        if row.status!='RUNNING':return True
        summary={k:result[k] for k in ('scope','dataset_id','dataset_sha256','quality','status','sessions','inserted','already_present') if k in result}
        if 'windows' in result:
            summary['windows']={name:{'start':window['start'],'end':window['end'],'steps':window['steps'],
                'scenarios':[{k:s[k] for k in ('scenario','status','coverage','entries','open_positions','period_return_pct','max_drawdown_pct','circuit_paused')} for s in window['scenarios']]} for name,window in result['windows'].items()}
            summary['saved_config_sha256']=hashlib.sha256(encoded(config)).hexdigest()
        row.summary_json=json.dumps(summary)
        blob=gzip.compress(encoded(result));reserve_storage(user_id,len(blob)+len(row.summary_json.encode()))
        row.result_gzip=blob;row.status='COMPLETED';row.completed_at=utcnow();row.message='Research computation completed; inspect coverage before interpreting performance.'
        db.session.commit()
    except Exception as exc:
        db.session.rollback();row=db.session.get(Job,job_id,populate_existing=True)
        if row.status=='RUNNING':
            row.status='FAILED';row.completed_at=utcnow();row.message=('Four-minute replay deadline exceeded; narrow the window.' if isinstance(exc,subprocess.TimeoutExpired) else str(exc)[:500])
            db.session.commit()
    return True


def audit_summary(user_id):
    """Bounded, timestamped research evidence without loading dataset payloads."""
    from sqlalchemy import inspect
    if not inspect(db.engine).has_table(Job.__tablename__):
        return {'status':'UNAVAILABLE','reason':'Research migration is not installed.'}
    jobs=Job.query.with_entities(Job.id,Job.kind,Job.status,Job.created_at,Job.completed_at,Job.summary_json,Job.message).filter(Job.user_id==user_id).order_by(Job.id.desc()).limit(10).all()
    datasets=Dataset.query.with_entities(Dataset.id,Dataset.created_at,Dataset.sha256,Dataset.summary_json).filter(Dataset.user_id==user_id).order_by(Dataset.id.desc()).limit(5).all()
    return {'status':'RECORDED','jobs_supplied':len(jobs),'job_limit':10,'dataset_limit':5,
            'datasets':[{'id':r.id,'created_at':iso(r.created_at),'sha256':r.sha256,'quality':json.loads(r.summary_json)} for r in datasets],
            'jobs':[{'id':r.id,'kind':r.kind,'status':r.status,'created_at':iso(r.created_at),'completed_at':iso(r.completed_at) if r.completed_at else None,
                     'summary':json.loads(r.summary_json) if r.summary_json else None,'message':r.message} for r in jobs],
            'interpretation':'Computation completion is not empirical validation. Saved settings and data windows differ from the live paper run. Missing module coverage, unknown timestamps and unobserved history remain limitations.'}


def import_preview(payload):
    if not isinstance(payload,dict) or payload.get('schema_version')!=2 or not isinstance(payload.get('records'),list):raise ValueError('Import requires schema_version 2 and records.')
    declaration=payload.get('source')
    if not isinstance(declaration,str) or not 3<=len(declaration)<=500:raise ValueError('Describe the data provider, permissions and adjustment conventions in source (3–500 characters).')
    data=canonical(payload['records'],{'origin':'IMPORTED','declaration':declaration,'source_verified':False})
    return data,hashlib.sha256(encoded(data)).hexdigest()


def research_job_loop(app,stop_event=None):
    stop=stop_event or threading.Event()
    while not stop.is_set():
        with app.app_context():
            try:
                schedule_daily_iv()
                process_one()
            except Exception as exc:
                db.session.rollback();app.logger.warning('Research job worker unavailable: %s',type(exc).__name__)
            finally:db.session.remove()
        stop.wait(3)


_last_daily_check=0


def schedule_daily_iv():
    """Once per observed session; absence of data is not an importable IV day."""
    import time
    from services.portfolio_strategy_signals import ET,session_bounds,utc
    from research_data_models import ResearchCapture
    from credentials import User
    from event_algo import is_event_strategy_admin
    global _last_daily_check
    if time.monotonic()-_last_daily_check<60:return
    _last_daily_check=time.monotonic()
    now=utc(utcnow());bounds=session_bounds(now.astimezone(ET).date())
    if not bounds or not bounds[1]+timedelta(minutes=5)<=now<=bounds[1]+timedelta(hours=4):return
    left,right=bounds[1]-timedelta(minutes=20),bounds[1]
    for cfg in Config.query.filter_by(enabled=True).all():
        if not is_event_strategy_admin(db.session.get(User,cfg.user_id)):continue
        if Job.query.filter(Job.user_id==cfg.user_id,Job.kind=='daily_iv',Job.created_at>=right.replace(tzinfo=None)).first():continue
        if not ResearchCapture.query.filter(ResearchCapture.user_id==cfg.user_id,ResearchCapture.kind=='option_quotes',ResearchCapture.received_at>=left.replace(tzinfo=None),ResearchCapture.received_at<right.replace(tzinfo=None)).first():continue
        try:enqueue(cfg.user_id,'daily_iv',{'start':iso(left),'end':iso(right)})
        except ValueError:continue
