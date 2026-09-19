"""Isolated replay of the actual paper ledger, not a second accounting engine.

CLI only: the parent worker passes immutable observations and saved settings.
The child uses a new in-memory database and disables all network transports.
Clock/cost patches exist only inside this separate process.
"""
import json
import math
import sys
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from services.research_dataset import stamp,iso
from services.research_history import ResearchMarketData,iv_preview

SCENARIOS=('baseline','double_costs','one_observation_delay','half_reported_depth','one_cent_adverse_book','assignment_and_margin_stress')


def blocked(*args,**kwargs):
    raise RuntimeError('Network access is disabled in historical replay.')


def timeline(dataset,start,end):
    points={};next_scan=start
    for row in sorted(dataset['records'],key=lambda r:r['available_at']):
        now=stamp(row['available_at'])
        if not start<=now<=end:continue
        if row['kind'] in ('quote','option_quote') and now>=next_scan:
            points[now]=True;next_scan=now+timedelta(seconds=300)
        if row['kind'] in ('forecast','outcome','event_quote'):
            points.setdefault(now,False)
    if len(points)>3000:raise ValueError('Replay exceeds 3,000 observed time steps; narrow the evaluation window.')
    if len(points)<2:raise ValueError('Each window requires at least two observed time steps.')
    return sorted(points.items())


def scenario_run(dataset,config,points,name,iv):
    from flask import Flask
    from core.extensions import db
    from services import portfolio_engine as e
    import portfolio_algo_models as m
    import event_algo_models as em
    from models import Notification
    from services.portfolio_strategy_signals import performance,ET,MODULES,TYPES
    from services.portfolio_event_execution import validate_entry
    from services.portfolio_execution_math import costs as base_costs,fill_price as base_price,entry_quantity as base_quantity
    from services.event_market_timing import quote_freshness
    app=Flask('historical-replay');app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://',TESTING=True)
    db.init_app(app)
    data=ResearchMarketData(dataset,config.get('currency','USD'),iv)
    fee_factor=2 if name=='double_costs' else 1
    slip_factor=2 if name=='double_costs' else 1
    counters=Counter();module_errors={module:Counter() for module in MODULES};pending={};depth_cap=None
    class Clock(datetime):
        current=points[0][0].replace(tzinfo=None)
        @classmethod
        def utcnow(cls):return cls.current
    def costs(module,price,quantity):return base_costs(module,price,quantity,fee_factor)
    def fill(module,price,side,closing=False):
        if name=='one_cent_adverse_book' and module in ('options','events'):
            buy=(side=='LONG')!=closing
            return max(0,price+(.01 if buy else -.01))
        return base_price(module,price,side,closing,slip_factor)
    def quantity(*args,**kwargs):
        result=base_quantity(*args,**kwargs,cost_multiplier=fee_factor)
        return min(result,depth_cap) if depth_cap is not None else result
    def mark_event(user_id,details,now):
        row=data.latest('event_quote','events',details['contract_symbol'],now)
        if (stamp(now)-row['event']).total_seconds()>30:raise ValueError('Stale Event mark.')
        value=row.get(details['outcome'].lower()+'_bid')
        if value is None:raise ValueError('Missing Event bid.')
        return float(value),None
    original_enter=e.enter_lot
    def enter(cfg,acc,state,module,symbol,signal,price,now,**kwargs):
        nonlocal depth_cap
        key=(module,symbol)
        if name=='one_observation_delay':
            prior=pending.pop(key,None)
            if prior is None:
                pending[key]=now;counters['delayed_entry_queued']+=1;return None
            if now<=prior:return None
        details=kwargs.get('details') or {};depth_cap=None
        try:
            if module=='options':
                values=[details['short'].get('bid_size'),details['long'].get('ask_size')]
                if any(v is None for v in values):raise ValueError('No reported two-leg option depth.')
                depth_cap=math.floor(min(float(v) for v in values))
                if name=='one_cent_adverse_book':
                    if price<=.01:raise ValueError('Adverse spread credit is nonpositive.')
                    kwargs['margin']=(details['width']-(price-.01))*100
                    signal={**signal,'target':(price-.01)*(1-config['settings']['options']['profit_target_pct']/100)}
            elif module=='events':
                if details.get('selected_ask_size') is None:raise ValueError('No reported selected-side Event depth.')
                depth_cap=math.floor(float(details['selected_ask_size']))
                if name=='one_cent_adverse_book' and price>=.99:raise ValueError('Adverse Event price is outside (0,1).')
            else:
                q=data.quote_row(symbol,TYPES[module],now)
                size=q.get('bid_size' if signal.get('side')=='SHORT' else 'ask_size')
                if size is not None:depth_cap=float(size) if module=='crypto' else math.floor(float(size))
                else:counters['entries_with_unknown_depth']+=1
            if depth_cap is not None:
                if name=='half_reported_depth':depth_cap=depth_cap/2 if module=='crypto' else math.floor(depth_cap/2)
                if depth_cap<=0:raise ValueError('Reported depth cannot fund a fill.')
            if module=='futures' and name=='assignment_and_margin_stress' and kwargs.get('margin'):
                kwargs['margin']*=2
            return original_enter(cfg,acc,state,module,symbol,signal,price,now,**kwargs)
        except ValueError as exc:
            counters[str(exc)]+=1
            if kwargs.get('rejections') is not None:kwargs['rejections'].append(str(exc))
            return None
        finally:depth_cap=None
    with app.app_context(),ExitStack() as stack:
        tables=[m.PortfolioStrategyConfig,m.PortfolioStrategyAccount,m.PortfolioEngineState,m.PortfolioStrategyPosition,m.PortfolioStrategyLot,m.PortfolioStrategyOrder,m.PortfolioEquitySnapshot,m.PortfolioEngineLog,m.PortfolioMarketObservation,
                em.EventStrategyConfig,em.EventMarketSnapshot,em.EventContractOutcome,Notification]
        db.metadata.create_all(db.engine,tables=[model.__table__ for model in tables])
        cfg,acc,state=e.ensure_portfolio(1)
        cfg.total_bankroll=config['bankroll'];cfg.target_annual_return=config['target'];cfg.enabled=True;cfg.worker_status='RUNNING'
        cfg.module_settings_json=json.dumps(config['settings']);cfg.allocations_json=json.dumps(config['allocations']);cfg.watchlists_json=json.dumps(config['watchlists'])
        acc.initial_balance=acc.cash_balance=acc.total_equity=config['bankroll'];acc.reset_at=Clock.current
        event_cfg=em.EventStrategyConfig(user_id=1,name='Replay',enabled=True,mode='PAPER',risk_config=json.dumps(config['event']['risk']),signal_config=json.dumps(config['event']['signal']))
        db.session.add(event_cfg);db.session.commit()
        for attribute,value in (('datetime',Clock),('costs',costs),('fill_price',fill),('entry_quantity',quantity),('enter_lot',enter),('mark_event',mark_event),('_record_portfolio_log',lambda *a,**k:None)):
            stack.enter_context(patch.object(e,attribute,value))
        curves=[];seen_forecasts=set();seen_outcomes=set()
        for moment,scan in points:
            Clock.current=moment.replace(tzinfo=None);now=Clock.current
            cfg,acc,state=e.locked(1)
            # Settlement only becomes usable when the result was observed.
            for row in data.rows('outcome','events',now):
                key=(row['symbol'],row.get('config_id'))
                peers=[r for r in data.rows('outcome','events',now) if r['symbol']==row['symbol'] and r.get('config_id')==row.get('config_id')]
                if len({r['outcome'] for r in peers})!=1:
                    counters['conflicting_outcomes']+=1
                    module_errors['events']['Conflicting observed resolutions; prior accounting retained, validation incomplete.']+=1
                    continue
                if key in seen_outcomes:continue
                seen_outcomes.add(key)
                for lot in e.current_lots(1,state):
                    details=e.loads(lot.details_json,{})
                    if lot.module=='events' and details.get('contract_symbol')==row['symbol'] and details.get('origin_config_id')==row.get('config_id'):
                        if stamp(details['cutoff_at'])!=stamp(row['cutoff_at']):
                            module_errors['events']['Settlement cutoff does not match the purchased contract.']+=1
                            continue
                        e.close_lot(acc,lot,1 if details['outcome']==row['outcome'] else 0,'SETTLEMENT',now)
            # Mark held Events from observed bids; never turn an absent quote
            # into a settlement. All modules share the same cash and risk state.
            for lot in e.current_lots(1,state):
                details=e.loads(lot.details_json,{})
                if lot.module=='events':
                    try:
                        q=data.latest('event_quote','events',details['contract_symbol'],now)
                        if (moment-q['event']).total_seconds()>30:raise ValueError('Stale Event mark.')
                        value=q.get(details['outcome'].lower()+'_bid')
                        if value is None:raise ValueError('Missing Event bid.')
                        e.mark_position(db.session.get(e.Position,lot.position_id),lot,float(value))
                    except ValueError as exc:module_errors['events'][str(exc)]+=1
                if lot.module=='options' and name=='assignment_and_margin_stress':
                    try:
                        pos=db.session.get(e.Position,lot.position_id)
                        underlying=data.quote(pos.symbol,'EQUITY',now);short=details['short']
                        itm=underlying<short['strike'] if short['option_type']=='PUT' else underlying>short['strike']
                        if itm:e.close_lot(acc,lot,details['width'],'ASSUMED_ASSIGNMENT_MAX_SPREAD_LOSS',now);counters['assignment_stress_closes']+=1
                    except ValueError as exc:module_errors['options'][str(exc)]+=1
            e.balances(acc,state,1);e.check_circuit(cfg,acc,state);db.session.commit()
            if scan:
                report=e.run_scan(1,force=True,provider=data)
                if not report.get('success'):raise ValueError('Replay scan failed: '+report.get('message','unknown'))
                for module,entry in report.get('modules',{}).items():
                    if module=='events':continue  # The replay's observed Event handoff runs below.
                    for message in entry.get('messages',[]):module_errors[module][message]+=1
                    counters[module+'_evaluated']+=entry.get('evaluated',0)
                for key,queued_at in list(pending.items()):
                    if key[0]!='events' and queued_at<now:
                        pending.pop(key);counters['delayed_entry_failed_revalidation']+=1
            cfg,acc,state=e.locked(1)
            if config['settings']['events']['enabled']:
                for row in data.rows('forecast','events',now):
                    origin=config['event'].get('config_id')
                    if origin is not None and row.get('config_id') is not None and row['config_id']!=origin:continue
                    key=(row['symbol'],row.get('decision_id'),row['available_at'])
                    if (key in seen_forecasts and ('events',row['symbol']) not in pending) or (moment-row['at']).total_seconds()>120:continue
                    seen_forecasts.add(key)
                    if state.kill_switch:continue
                    try:
                        q=data.latest('event_quote','events',row['symbol'],now)
                        market={**row.get('market',{}),**{k:v for k,v in q.items() if k.startswith(('yes_','no_'))},'symbol':row['symbol'],
                                'cutoff_at':row['cutoff_at'],'quote_as_of':iso(q['event']) if q.get('timestamp_basis')=='PROVIDER' else None,
                                'quote_retrieved_at':iso(q['at']),'quote_time_basis':'PROVIDER_QUOTE' if q.get('timestamp_basis')=='PROVIDER' else 'RETRIEVAL_ONLY'}
                        decision=SimpleNamespace(created_at=row['event'].replace(tzinfo=None),contract_symbol=row['symbol'],probability_yes=row['probability_yes'],confidence=row['confidence'],outcome=row.get('outcome'))
                        if decision.outcome not in ('YES','NO'):
                            from event_algo import evaluate_market
                            decision.outcome=evaluate_market({**market,'model_probability_yes':row['probability_yes'],'model_confidence':row['confidence']},event_cfg,now=now)['outcome']
                        status,reason,assessment=validate_entry(decision,market,event_cfg,config['settings']['events'],config['watchlists']['events'],now)
                        if status:raise ValueError(reason)
                        if name=='one_cent_adverse_book' and assessment['net_edge']-.01<config['settings']['events']['min_net_edge']:raise ValueError('Adverse Event quote fails net edge.')
                        details={'contract_symbol':row['symbol'],'outcome':assessment['outcome'],'event_config_id':event_cfg.id,
                                 'origin_config_id':row.get('config_id'),'cutoff_at':row['cutoff_at'],'selected_ask_size':market.get(assessment['outcome'].lower()+'_ask_size')}
                        enter(cfg,acc,state,'events',row['symbol'],{'enter':True,'side':'LONG','reason':'Archived forecast revalidated'},assessment['executable_price'],now,details=details,key='events:'+row['symbol'])
                        counters['events_evaluated']+=1
                        e.balances(acc,state,1);e.check_circuit(cfg,acc,state)
                    except (ValueError,KeyError) as exc:module_errors['events'][str(exc)[:180]]+=1
            e.balances(acc,state,1)
            lots=e.current_lots(1,state,False)
            pnl={module:sum(l.realized_pnl if l.closed_at else db.session.get(e.Position,l.position_id).unrealized_pnl-l.entry_fee for l in lots if l.module==module) for module in MODULES}
            exposure={module:sum(l.collateral for l in lots if not l.closed_at and l.module==module) for module in MODULES}
            curves.append({'time':moment,'equity':acc.total_equity,'cash':acc.cash_balance,'module_pnl':pnl,'module_reserved_capital':exposure})
            e.snapshot(cfg,acc,state,now)
            db.session.commit()
        lots=e.current_lots(1,state,False);closed=[l for l in lots if l.closed_at];opened=[l for l in lots if not l.closed_at]
        metrics=performance(curves,acc.initial_balance,[l.realized_pnl for l in closed])
        days=(points[-1][0]-points[0][0]).total_seconds()/86400
        result={'scenario':name,'starting_equity':acc.initial_balance,'ending_equity':acc.total_equity,'cash':acc.cash_balance,
                'period_return_pct':(acc.total_equity/acc.initial_balance-1)*100,**metrics,'entries':len(lots),'open_positions':len(opened),
                'circuit_paused':state.kill_switch,'module_errors':{m:dict(v) for m,v in module_errors.items()},'decisions':dict(counters),
                'target_equity':acc.initial_balance*(1+config['target']/100)**(days/365),'observation_days':days,
                'module_correlations':e.measured_correlations(1,state.generation),
                'maximum_reserved_capital':max(sum(r['module_reserved_capital'].values()) for r in curves),
                'trades':[{'module':l.module,'symbol':db.session.get(e.Position,l.position_id).symbol,'opened_at':iso(l.opened_at),'closed_at':iso(l.closed_at) if l.closed_at else None,'net_pnl':l.realized_pnl if l.closed_at else None,'entry_fee':l.entry_fee,'collateral':l.collateral} for l in lots],
                'equity_curve':[{**r,'time':iso(r['time'])} for r in curves],
                'coverage':{m:('DISABLED' if not config['settings'][m]['enabled'] else 'DATA_LIMITED' if module_errors[m] else 'OBSERVED' if counters[m+'_evaluated'] or any(l.module==m for l in lots) else 'NO_EVALUABLE_OBSERVATIONS') for m in MODULES}}
        result['status']='DATA_LIMITED' if any(v in ('DATA_LIMITED','NO_EVALUABLE_OBSERVATIONS') for v in result['coverage'].values()) else 'COMPUTED'
        db.session.remove();db.engine.dispose()
        return result


def run_replay(dataset,config,request):
    start,split,end=(stamp(request[key]) for key in ('start','split','end'))
    if not start<split<end:raise ValueError('Require start < chronological split < end.')
    iv=iv_preview(dataset,config['settings']['options']['target_dte'])['accepted']
    windows={}
    for name,left,right in (('development',start,split-timedelta(microseconds=1)),('held_out',split,end)):
        points=timeline(dataset,left,right)
        windows[name]={'start':iso(points[0][0]),'end':iso(points[-1][0]),'steps':len(points),
                       'scenarios':[scenario_run(dataset,config,points,s,iv) for s in SCENARIOS]}
    return {'scope':'shared_capital_portfolio_replay','schema_version':2,'windows':windows,'saved_config':config,
            'source_quality':dataset['quality'],'provenance':dataset['provenance'],
            'assumptions':['Runs the actual paper ledger in a separate, network-disabled process and in-memory database.',
                           'All modules share cash, allocation, position sizing, fees, rebalancing, Event exposure and circuit controls; each window/scenario starts independently.',
                           'Only observations already available at each step are visible. Collected backfills do not become historical point-in-time observations.',
                           'Spot/derivative scans use observed times at least 300 seconds apart; Event evidence supplies additional steps. Unobserved prices, queues, cancellations and fills cannot be recovered.',
                           'Reported size caps entries. Half-depth is a partial-fill sensitivity, not an estimated fill probability; unknown option/Event depth never produces a research fill.',
                           'Assignment stress closes an observed ITM spread at maximum defined-spread loss; it is an adverse assumption, not physical share-delivery accounting. Futures margin doubles in that scenario.',
                           'USD and stablecoin denominations are not silently combined. Missing currency-compatible feeds remain data limitations.',
                           'Open positions remain marked rather than forcibly liquidated at a fabricated price. Missing/stale marks and pending outcomes limit reported performance.',
                           'Chronological separation cannot certify an untouched holdout; source provenance is preserved but not independently certified.']}


if __name__=='__main__':
    # No production Flask app, credentials, providers or scheduler is started.
    import socket
    import requests
    import resource
    try:
        resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
        resource.setrlimit(resource.RLIMIT_CPU,(230,235))
        value=json.load(sys.stdin)
        with patch('socket.socket.connect',blocked),patch('socket.create_connection',blocked),patch('requests.sessions.Session.request',blocked):
            result=run_replay(value['dataset'],value['config'],value['request'])
        print(json.dumps({'success':True,'result':result},allow_nan=False))
    except Exception as exc:
        print(json.dumps({'success':False,'message':str(exc)[:500],'error_type':type(exc).__name__}))
        sys.exit(1)
