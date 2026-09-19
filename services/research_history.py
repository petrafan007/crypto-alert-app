"""As-of research data boundary and reproducible daily IV previews."""
from bisect import bisect_right
from collections import defaultdict, Counter
from datetime import timedelta
import time
from services.research_dataset import stamp,iso
from services.portfolio_strategy_signals import finite,utc,ET,fresh_quote
from services.portfolio_iv import atm_pair,collection_window,iv_series,iv_source


class ResearchMarketData:
    def __init__(self,dataset,currency='USD',iv_observations=None):
        self.currency=currency
        self.groups=defaultdict(list)
        self.diagnostics=Counter()
        for row in dataset['records']:
            if row['currency']==currency or row['kind']=='dominance':
                self.groups[(row['kind'],row['module'])].append({**row,'at':stamp(row['available_at']),'event':stamp(row['event_at'])})
        self.times={}
        for key,rows in self.groups.items():
            rows.sort(key=lambda r:r['at']);self.times[key]=[r['at'] for r in rows]
        self.iv_observations=iv_observations or []

    def rows(self,kind,module,now):
        key=(kind,module)
        return self.groups.get(key,[])[:bisect_right(self.times.get(key,[]),utc(now))]

    def latest(self,kind,module,symbol,now,source=None):
        rows=self.rows(kind,module,now)
        for row in reversed(rows):
            if row['symbol']==symbol and (source is None or row['source']==source):return row
        raise ValueError(f'Missing as-of {kind}: {module}/{symbol} ({self.currency}).')

    def quote_row(self,symbol,instrument,now):
        module={'EQUITY':'equities','CRYPTO':'crypto','FUTURES':'futures'}[instrument]
        exact=symbol+self.currency if module=='crypto' and not symbol.endswith(('USD','USDT','USDC')) else symbol
        return self.latest('quote',module,exact,now)

    def quote(self,symbol,instrument,now):
        row=self.quote_row(symbol,instrument,now)
        # Receipt-only feeds are labeled in the dataset/result. An explicitly
        # supplied stale provider timestamp can never fall back to receipt.
        return fresh_quote({'price':row['price'],'as_of':row['event']},now)

    def bars(self,symbol,instrument,now,interval='D',limit=260):
        module={'EQUITY':'equities','CRYPTO':'crypto','FUTURES':'futures'}[instrument]
        exact=symbol+self.currency if module=='crypto' and not symbol.endswith(('USD','USDT','USDC')) else symbol
        interval={'D':'1d','H1':'1h','M1':'1m'}[interval]
        candidates=[r for r in self.rows('bar',module,now) if r['symbol']==exact and r['interval']==interval]
        if not candidates:raise ValueError('No completed as-of '+interval+' candles for '+exact)
        try:source=self.quote_row(symbol,instrument,now)['source']
        except ValueError:source=candidates[-1]['source']
        latest={}
        for row in candidates:
            if row['source']==source and stamp(row['complete_at'])<=utc(now):latest[row['event_at']]=row
        ordered=sorted(latest.values(),key=lambda r:r['event'])[-limit:]
        if not ordered or (utc(now)-stamp(ordered[-1]['complete_at'])).total_seconds()>(7*86400 if interval=='1d' else 7200 if interval=='1h' else 180):raise ValueError('Completed candle history is stale.')
        return [{**r,'time':r['event'].timestamp()} for r in ordered]

    def dominance_ok(self,symbol,now):
        if symbol=='BTC':return True
        rows=self.rows('dominance','crypto',now)
        if not rows or (utc(now)-rows[-1]['event']).total_seconds()>3600:raise ValueError('Current BTC dominance unavailable.')
        source=rows[-1]['source']; days={}
        for r in rows:
            if r['source']==source:days[r['event'].date()]=r['value']
        previous=[days.get(utc(now).date()-timedelta(days=i)) for i in range(1,8)]
        if any(v is None for v in previous):raise ValueError('Seven preceding BTC-dominance days are required.')
        return rows[-1]['value']<=sum(previous)/7

    def future(self,root,now):
        contracts={}
        for r in self.rows('contract','futures',now):
            if r.get('root')==root and r.get('expiration','')>str(utc(now).astimezone(ET).date()):contracts[r['symbol']]=r
        if not contracts:raise ValueError('No observed unexpired futures contract.')
        r=min(contracts.values(),key=lambda r:r['expiration'])
        return r['symbol'],finite(r.get('multiplier'),'contract multiplier',.01),finite(r.get('margin'),'observed initial margin',1)

    def option_chain(self,root,target,now,require_complete=False):
        underlying=self.quote_row(root,'EQUITY',now)
        price=self.quote(root,'EQUITY',now)
        source=underlying['source']; contracts={}; day=utc(now).astimezone(ET).date()
        for row in self.rows('contract','options',now):
            try:
                if row.get('root')!=root or row['source']!=source or row.get('standard') is not True or finite(row.get('multiplier'))!=100:continue
                dte=(utc(row['expiration']).date()-day).days
                if 20<=dte<=65 and row.get('option_type') in ('CALL','PUT'):
                    contracts[row['symbol']]={**row,'strike':finite(row['strike'],'strike',.01)}
            except (ValueError,KeyError,TypeError):continue
        if not contracts:raise ValueError('No observed standard option contracts in the saved DTE window.')
        if require_complete and not self.complete_catalog(root,source,day,now):
            raise ValueError('Complete near-expiry catalog evidence is required for daily IV.')
        expiration=min({r['expiration'] for r in contracts.values()},key=lambda e:(abs((utc(e).date()-day).days-target),e))
        selected=sorted([r for r in contracts.values() if r['expiration']==expiration],key=lambda r:(abs(r['strike']-price),r['symbol']))[:80]
        if require_complete:
            observed=set()
            for batch in self.rows('quote_batch','options',now):
                if batch['symbol']==root and batch['source']==source and 0<=(utc(now)-batch['at']).total_seconds()<=120:
                    observed.update(batch.get('symbols',[]))
            if not {r['symbol'] for r in selected}.issubset(observed):raise ValueError('Incomplete selected-contract quote batch evidence.')
        quoted=[]
        for contract in selected:
            try:
                q=self.latest('option_quote','options',contract['symbol'],now,source)
                bid=finite(q.get('bid'),'option bid',.000001);ask=finite(q.get('ask'),'option ask',bid)
                fresh_quote({'price':ask,'as_of':q['event']},now)
                merged={**contract,**q}
                quoted.append({**{k:v for k,v in merged.items() if k not in ('at','event')},'event':iso(q['event']),
                               'strike':contract['strike'],'expiration':expiration,'bid':bid,'ask':ask,'as_of':iso(q['event'])})
            except ValueError:continue
        return price,quoted,source

    def complete_catalog(self,root,source,day,now):
        chains=defaultdict(dict)
        for row in self.rows('catalog','options',now):
            if row['symbol']==root and row['source']==source and row['at'].astimezone(ET).date()==day and (row.get('start') or '9999')<=str(day+timedelta(days=20)) and (row.get('end') or '')>=str(day+timedelta(days=65)):
                chains[(row.get('cycle_id'),row.get('start'),row.get('end'))][row.get('page')]=row.get('next')
        for chain in chains.values():
            cursor=None;seen=set()
            while cursor in chain and cursor not in seen:
                seen.add(cursor);cursor=chain[cursor]
                if cursor is None:return True
        return False

    def options(self,root,settings,now):
        target=settings['target_dte']; price,quoted,source=self.option_chain(root,target,now)
        current=atm_pair(quoted,price); days={}; conflicts=set()
        candidates=self.iv_observations+self.rows('iv','options',now)
        for r in candidates:
            if r.get('symbol')!=root or r.get('target_dte')!=target or r.get('source')!=source or r.get('methodology')!='ATM_PAIR_V1' or stamp(r['available_at'])>utc(now):continue
            day=stamp(r['event_at']).astimezone(ET).date()
            if day in days and days[day]!=r['value']:conflicts.add(day)
            days[day]=r['value']
        values=[v for day,v in sorted(days.items()) if day not in conflicts and utc(now).astimezone(ET).date()-timedelta(days=370)<=day<=utc(now).astimezone(ET).date()][-252:]
        rank=100*(current-min(values))/(max(values)-min(values)) if len(values)>=252 and max(values)>min(values) else None
        return price,quoted,max(0,min(100,rank)) if rank is not None else None

    def spread_mark(self,details,now):
        quotes=[]
        for side in ('short','long'):
            leg=details[side];row=self.latest('option_quote','options',leg['symbol'],now,leg.get('source'))
            fresh_quote({'price':row.get('ask'),'as_of':row['event']},now)
            quotes.append(row)
        return max(0,finite(quotes[0].get('ask'),'short ask')-finite(quotes[1].get('bid'),'long bid'))


def iv_preview(dataset,target):
    if isinstance(target,bool) or not isinstance(target,int) or not 20<=target<=65:raise ValueError('IV target must be 20–65 whole days.')
    data=ResearchMarketData(dataset); accepted={}; excluded=Counter()
    deadline=time.monotonic()+120
    roots=sorted({r.get('root') for r in dataset['records'] if r['kind']=='contract' and r['module']=='options' and r.get('root')})
    times=sorted({stamp(r['available_at']) for r in dataset['records'] if r['kind']=='option_quote' and collection_window(stamp(r['available_at']))})
    for now in times:
        for root in roots:
            if time.monotonic()>deadline:raise ValueError('IV preview exceeded two minutes; narrow the dataset window.')
            key=(root,now.astimezone(ET).date())
            if key in accepted:continue
            try:
                price,quotes,source=data.option_chain(root,target,now,require_complete=True)
                quotes=[r for r in quotes if r.get('timestamp_basis')=='PROVIDER' and collection_window(r['event'])]
                underlying=data.quote_row(root,'EQUITY',now)
                if underlying.get('timestamp_basis')!='PROVIDER':raise ValueError('Underlying quote time is unverified.')
                value=atm_pair(quotes,price)
                accepted[key]={'kind':'iv','module':'options','symbol':root,'currency':'USD','source':source,
                               'value':value,'event_at':iso(now),'available_at':iso(now),'target_dte':target,
                               'methodology':'ATM_PAIR_V1','iv_units':'DECIMAL','derived_from_quote_evidence':True}
            except (ValueError,KeyError,TypeError) as exc:excluded[str(exc)[:150]]+=1
    return {'methodology':'ATM_PAIR_V1','target_dte':target,'accepted':list(accepted.values()),'exclusions':dict(excluded),
            'sessions':len(accepted),'status':'READY' if accepted else 'INSUFFICIENT_COMPATIBLE_CLOSE_WINDOW_DATA',
            'direct_scalar_iv_rows_not_promoted':sum(r['kind']=='iv' for r in dataset['records'])}


def apply_iv(user_id,dataset_id,digest,target):
    """Append only compatible self-collected daily values; never replace history."""
    from core.extensions import db
    from services.research_dataset import get_dataset
    from portfolio_algo_models import PortfolioMarketObservation as Observation
    from services.event_runtime import job_slot
    row,data=get_dataset(user_id,dataset_id)
    if row.sha256!=digest:raise ValueError('Dataset checksum changed; preview again.')
    if data['provenance'].get('origin')!='LOCAL_ARCHIVE':raise ValueError('Imported provider history remains isolated research data; it cannot relabel the live Webull series.')
    preview=iv_preview(data,target); inserted=existing=conflicts=0
    with job_slot(user_id,'iv-history'):
        for item in preview['accepted']:
            if item['source']!='WEBULL_PRODUCTION':continue
            series=iv_series(item['symbol'],target);day=stamp(item['event_at']).astimezone(ET).date()
            prior=Observation.query.filter_by(user_id=user_id,series=series,day=day).first()
            if prior:
                existing+=1;conflicts+=int(prior.source!=iv_source(target) or abs(prior.value-item['value'])>1e-10)
                continue
            # Savepoints make concurrent live sampling idempotent without
            # rolling back unrelated accepted days or overwriting a winner.
            from sqlalchemy.exc import IntegrityError
            try:
                with db.session.begin_nested():
                    db.session.add(Observation(user_id=user_id,series=series,day=day,value=item['value'],source=iv_source(target),observed_at=stamp(item['event_at']).replace(tzinfo=None)))
                    db.session.flush()
                inserted+=1
            except IntegrityError:existing+=1
        db.session.commit()
    return {**preview,'inserted':inserted,'already_present':existing,'conflicting_existing_retained':conflicts}
