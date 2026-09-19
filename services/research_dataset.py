"""Point-in-time archive adapters and immutable, source-separated datasets."""
import gzip
import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from core.extensions import db
from research_data_models import ResearchCapture, ResearchDataset, utcnow
from services.portfolio_strategy_signals import utc, finite, ET, session_bounds

MAX_RECORDS = 100000
MAX_RAW_BYTES = 128*1024*1024
KINDS = {'quote','bar','catalog','quote_batch','contract','option_quote','event_quote','event_book','trade','dominance','forecast','outcome','iv'}


def stamp(value):
    if isinstance(value,str) and value.replace('.','',1).isdigit():value=float(value)
    if isinstance(value,str) and not (value.endswith('Z') or '+' in value[10:] or '-' in value[10:]):
        raise ValueError('Timestamps require an explicit UTC offset.')
    if isinstance(value,bool) or value is None:
        raise ValueError('A measured timestamp is required.')
    result = utc(value)
    if not 1990 <= result.year <= 2100:
        raise ValueError('Timestamp is outside the supported range.')
    return result


def iso(value):
    return utc(value).isoformat()


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def unpack(blob, digest=None):
    raw = gzip.decompress(blob)
    if len(raw)>MAX_RAW_BYTES or digest and hashlib.sha256(raw).hexdigest()!=digest:
        raise ValueError('Dataset/capture size or checksum validation failed.')
    return json.loads(raw)


def records(body):
    from services.webull_service import _webull_records
    return _webull_records(body)


def currency(symbol):
    return next((suffix for suffix in ('USDT','USDC','USD') if symbol.endswith(suffix)), 'USD')


def adapt(capture):
    """Never use receipt time as an invented exchange quote timestamp."""
    body = unpack(capture.payload_gzip,capture.sha256)
    meta = json.loads(capture.metadata_json)
    params = meta.get('parameters',{})
    received = utc(capture.received_at)
    source, kind = capture.source, capture.kind
    base = {'source':source,'available_at':iso(received),'capture_id':capture.id,'capture_sha256':capture.sha256}
    def item(row_kind,module,symbol,event_at=None,**fields):
        event = stamp(event_at) if event_at is not None else received
        return {**base,'kind':row_kind,'module':module,'symbol':symbol,'currency':currency(symbol),
                'event_at':iso(event),'timestamp_basis':'PROVIDER' if event_at is not None else 'RECEIPT_ONLY',**fields}
    if kind in ('stock_quotes','webull_crypto_quotes','futures_quotes'):
        module={'stock_quotes':'equities','webull_crypto_quotes':'crypto','futures_quotes':'futures'}[kind]
        for r in records(body):
            yield item('quote',module,r['symbol'],r.get('quote_time',r.get('timestamp')),
                       price=r.get('price',r.get('last_price')),bid=r.get('bid'),ask=r.get('ask'),
                       bid_size=r.get('bid_size'),ask_size=r.get('ask_size'))
    elif kind=='option_catalog':
        from services.research_collection import next_cursor
        yield item('catalog','options',capture.symbol,cycle_id=meta.get('cycle_id',str(capture.id)),
                   start=params.get('start_date'),end=params.get('end_date'),page=params.get('pagination_key'),next=next_cursor(body,'pagination_key'))
        for r in records(body):
            yield item('contract','options',r['symbol'],root=r.get('underlying_symbol'),
                       expiration=str(r.get('expiration_date',''))[:10],strike=r.get('strike_price'),
                       option_type={'C':'CALL','P':'PUT'}.get(r.get('option_type'),r.get('option_type')),
                       multiplier=r.get('multiplier'),standard=r.get('def_type')=='STANDARD',
                       catalog_complete=not (isinstance(body,dict) and body.get('pagination_key')) and len(records(body))<1000,
                       catalog_start=params.get('start_date'),catalog_end=params.get('end_date'))
    elif kind=='option_quotes':
        from services.webull_service import _normalise_option_snapshot_record
        yield item('quote_batch','options',capture.symbol,cycle_id=meta.get('cycle_id'),symbols=str(params.get('symbols') or '').split(','))
        for r in records(body):
            q=_normalise_option_snapshot_record(r)
            yield item('option_quote','options',r['symbol'],r.get('quote_time',r.get('timestamp')),
                       **{k:q.get(k) for k in ('bid','ask','bid_size','ask_size','implied_volatility','delta','gamma','theta','vega','rho','volume','open_interest')},iv_units='DECIMAL')
    elif kind=='event_catalog':
        from event_algo import _market_cutoff
        for r in records(body):
            cutoff=_market_cutoff(r)
            if cutoff:
                yield item('contract','events',r['symbol'],cutoff_at=iso(cutoff),provider_metadata=r)
    elif kind=='event_quotes':
        for r in records(body):
            yield item('event_quote','events',r['symbol'],r.get('quote_time',r.get('timestamp')),
                       **{k:r.get(k) for k in ('yes_bid','yes_ask','no_bid','no_ask','yes_bid_size','yes_ask_size','no_bid_size','no_ask_size','volume','open_interest')})
    elif kind=='event_depth':
        if isinstance(body,dict) and body.get('symbol'):
            yield item('event_book','events',body['symbol'],body.get('quote_time'),
                       **{key:body.get(key,[]) for key in ('yes_bids','no_bids','yes_asks','no_asks')})
    elif kind=='independent_event_depth':
        book=body.get('orderbook_fp')
        if not isinstance(book,dict):raise ValueError('Unknown independent order book schema.')
        yield item('event_book','events',capture.symbol,
                   yes_bids=[{'price':r[0],'size':r[1]} for r in book.get('yes_dollars',[])],
                   no_bids=[{'price':r[0],'size':r[1]} for r in book.get('no_dollars',[])],
                   book_basis='REPORTED_BINARY_BIDS_ONLY')
    elif kind in ('crypto_trades','event_trades'):
        rows=body if isinstance(body,list) else body.get('result',[])
        for r in rows:
            if kind=='crypto_trades':
                yield item('trade','crypto',capture.symbol,r.get('T'),trade_id=str(r['a']),price=r['p'],size=r['q'])
            else:
                yield item('trade','events',body['symbol'],r.get('time'),trade_id=str(r['trade_id']),yes_price=r.get('yes_price'),no_price=r.get('no_price'),size=r.get('volume'))
    elif kind=='crypto_depth':
        if isinstance(body,dict) and body.get('bids') and body.get('asks'):
            bid,ask=map(float,(body['bids'][0][0],body['asks'][0][0]))
            yield item('quote','crypto',capture.symbol,price=(bid+ask)/2,bid=bid,ask=ask,
                       bid_size=body['bids'][0][1],ask_size=body['asks'][0][1],book_update_id=body.get('lastUpdateId'),
                       bids=body['bids'],asks=body['asks'],price_basis='BOOK_MIDPOINT')
    elif kind in ('crypto_bars','stock_bars','webull_crypto_bars','futures_bars'):
        interval=params.get('interval') or {'D':'1d','M60':'1h','M1':'1m'}.get(params.get('timespan'))
        module='equities' if kind=='stock_bars' else 'futures' if kind=='futures_bars' else 'crypto'
        if interval not in ('1m','1h','1d'):
            raise ValueError('Unknown candle interval.')
        raw_bars=body if kind=='crypto_bars' else [b for r in records(body) for b in (r['result'] if isinstance(r.get('result'),list) else [r])]
        for r in raw_bars:
            if isinstance(r,list):
                fields=dict(zip(('open','high','low','close','volume'),r[1:6])); opened=stamp(r[0]); closed=stamp(r[6])+timedelta(milliseconds=1)
            else:
                from services.webull_service import _normalise_webull_bar
                fields=_normalise_webull_bar(r,strict_ohlc=True)
                if fields is None: continue
                opened=stamp(fields.pop('time'))
                if interval=='1d' and module=='equities':
                    bounds=session_bounds(opened.date() if opened.hour==0 else opened.astimezone(ET).date())
                    if not bounds: continue
                    closed=bounds[1]
                else: closed=opened+timedelta(seconds={'1m':60,'1h':3600,'1d':86400}[interval])
            if closed<=received:
                yield item('bar',module,capture.symbol,opened,**fields,interval=interval,complete_at=iso(closed))
    elif kind=='dominance':
        r=body['data']
        yield item('dominance','crypto','BTC_DOMINANCE',r['updated_at'],value=r['market_cap_percentage']['btc'])
    elif kind=='futures_catalog':
        from services.webull_service import _normalise_futures_catalog_record
        for r in records(body):
            q=_normalise_futures_catalog_record(r)
            yield item('contract','futures',q['symbol'],root=q.get('product_code') or capture.symbol,
                       expiration=str(q.get('expiration_date') or '')[:10],multiplier=q.get('contract_multiplier'),margin=q.get('initial_margin'))


def validate_row(row):
    if not isinstance(row,dict) or row.get('kind') not in KINDS or row.get('module') not in ('equities','options','crypto','futures','events'):
        raise ValueError('Unknown record kind/module.')
    for key,limit in (('source',120),('symbol',160),('currency',10)):
        if not isinstance(row.get(key),str) or not 1<=len(row[key])<=limit:
            raise ValueError('Missing bounded source/symbol/currency.')
    when,available=stamp(row.get('event_at')),stamp(row.get('available_at'))
    if available>datetime.now(timezone.utc)+timedelta(seconds=5) or when>available+timedelta(seconds=5):
        raise ValueError('Future observation or event after availability.')
    row={**row,'event_at':iso(when),'available_at':iso(available)}
    if row.get('kind') in ('quote','option_quote','event_quote','event_book'):
        if row.get('timestamp_basis') not in (None,'PROVIDER','RECEIPT_ONLY','UNSPECIFIED'):raise ValueError('Unknown quote timestamp basis.')
        row.setdefault('timestamp_basis','UNSPECIFIED')
    kind=row['kind']
    if kind=='bar':
        if row.get('interval') not in ('1m','1h','1d'):raise ValueError('Unknown interval.')
        for key in ('open','high','low','close','volume'):row[key]=finite(row.get(key),key,0 if key=='volume' else .00000001)
        if row['low']>min(row['open'],row['close']) or row['high']<max(row['open'],row['close']) or row['low']>row['high']:
            raise ValueError('Invalid OHLC.')
        complete=stamp(row.get('complete_at'))
        minimum=when+timedelta(seconds={'1m':60,'1h':3600,'1d':86400}[row['interval']])
        if row['module']=='equities' and row['interval']=='1d':
            bounds=session_bounds(when.date() if when.hour==0 else when.astimezone(ET).date())
            if not bounds:raise ValueError('Non-session equity bar.')
            minimum=bounds[1]
        if not minimum<=complete<=available:raise ValueError('Unfinished or prematurely available candle.')
        row['complete_at']=iso(complete)
    if kind=='quote':row['price']=finite(row.get('price'),'price',.00000001)
    for key in ('bid','ask','bid_size','ask_size','yes_bid','yes_ask','no_bid','no_ask','yes_bid_size','yes_ask_size','no_bid_size','no_ask_size'):
        if row.get(key) is not None:row[key]=finite(row[key],key,0,1 if key in ('yes_bid','yes_ask','no_bid','no_ask') else 1e12)
    for bid,ask in (('bid','ask'),('yes_bid','yes_ask'),('no_bid','no_ask')):
        if row.get(bid) is not None and row.get(ask) is not None and row[bid]>row[ask]:raise ValueError('Crossed quote.')
    if kind=='option_quote':
        if row.get('iv_units')!='DECIMAL':raise ValueError('Option IV must declare DECIMAL units.')
        if row.get('implied_volatility') is not None:row['implied_volatility']=finite(row['implied_volatility'],'IV',.000001,9.99999)
        for key in ('delta','gamma','theta','vega','rho'):
            if row.get(key) is not None:row[key]=finite(row[key],key,-1e6,1e6)
    if kind=='dominance':row['value']=finite(row.get('value'),'dominance',.01,100)
    if kind=='forecast':
        for key in ('probability_yes','confidence'):row[key]=finite(row.get(key),key,0,1)
        if not when<stamp(row.get('cutoff_at')):raise ValueError('Forecast after cutoff.')
    if kind=='outcome':
        if row.get('outcome') not in ('YES','NO') or not stamp(row.get('cutoff_at'))<=when:raise ValueError('Invalid outcome or settlement time.')
    if kind=='iv':
        from services.portfolio_iv import collection_window
        row['value']=finite(row.get('value'),'IV',.000001,9.99999)
        if row.get('methodology')!='ATM_PAIR_V1' or row.get('iv_units')!='DECIMAL':raise ValueError('Separate or unknown IV methodology.')
        if not isinstance(row.get('target_dte'),int) or not 20<=row['target_dte']<=65:raise ValueError('Invalid IV DTE target.')
        if not collection_window(when):raise ValueError('Daily IV must be observed in the actual session close window.')
    if kind=='contract' and row['module'] in ('options','futures'):
        try:datetime.strptime(row['expiration'],'%Y-%m-%d')
        except (ValueError,TypeError,KeyError):raise ValueError('Contract requires expiration YYYY-MM-DD.') from None
        row['multiplier']=finite(row.get('multiplier'),'contract multiplier',.01)
        if row['module']=='options':
            row['strike']=finite(row.get('strike'),'option strike',.000001)
            if row.get('option_type') not in ('CALL','PUT') or not isinstance(row.get('standard'),bool):raise ValueError('Options require CALL/PUT and an explicit standard flag.')
        elif row.get('margin') is not None:row['margin']=finite(row['margin'],'initial margin',1)
    if kind=='event_book':
        for key in ('yes_bids','no_bids','yes_asks','no_asks'):
            levels=row.get(key,[])
            if not isinstance(levels,list) or len(levels)>1000:raise ValueError('Invalid Event book depth.')
            if any(not isinstance(level,dict) or 'price' not in level or 'size' not in level for level in levels):raise ValueError('Book levels require price and size.')
            row[key]=[{'price':finite(level['price'],'book price',0,1),'size':finite(level['size'],'book size',0)} for level in levels]
    return row


def canonical(rows, provenance, exclusions=None):
    unique={}; duplicates=0
    deadline=time.monotonic()+180
    for raw in rows:
        if time.monotonic()>deadline:raise ValueError('Normalization exceeded three minutes; narrow the window.')
        row=validate_row(raw)
        # Keep conflicting revisions, but retain the earliest known availability
        # for genuinely identical observations. Never backdate a later revision.
        identity={k:v for k,v in row.items() if k not in ('available_at','capture_id','capture_sha256')}
        if row.get('timestamp_basis')=='RECEIPT_ONLY' or row['kind'] in ('contract','catalog','quote_batch'):identity['available_at']=row['available_at']
        key=hashlib.sha256(encoded(identity)).hexdigest()
        if key in unique:
            duplicates+=1
            if row['available_at']<unique[key]['available_at']:unique[key]=row
        else:unique[key]=row
        if len(unique)>MAX_RECORDS:raise ValueError('Dataset exceeds 100,000 records; narrow the date window.')
    clean=sorted(unique.values(),key=lambda r:(r['available_at'],r['kind'],r['symbol'],r['event_at']))
    if not clean:raise ValueError('No usable observations in this selection.')
    return {'schema_version':2,'records':clean,'provenance':provenance,
            'quality':{'accepted':len(clean),'duplicates_removed':duplicates,'excluded':dict(exclusions or {}),
                       'counts':dict(Counter(r['module']+':'+r['kind'] for r in clean)),
                       'currencies':sorted({r['currency'] for r in clean}),
                       'independent_books':compare_books(clean),
                       'unknown_exchange_timestamps':sum(r['kind'] in ('quote','option_quote','event_quote','event_book') and r.get('timestamp_basis')!='PROVIDER' for r in clean),
                       'stale_quotes_at_receipt':sum(r['kind'] in ('quote','option_quote','event_quote','event_book') and (stamp(r['available_at'])-stamp(r['event_at'])).total_seconds()>(30 if r['module']=='events' else 120) for r in clean),
                       'first_available_at':clean[0]['available_at'],'last_available_at':clean[-1]['available_at']}}


def compare_books(rows):
    """Descriptive receipt-time pairing; never an exchange-latency estimate."""
    from bisect import bisect_left
    from statistics import median
    independent={}
    for row in rows:
        if row['kind']=='event_book' and row['source']=='KALSHI_PUBLIC':
            independent.setdefault(row['symbol'],[]).append((stamp(row['available_at']).timestamp(),row))
    indexes={symbol:([r[0] for r in values],values) for symbol,values in independent.items()}
    pairs=[];sides=Counter();used=set()
    for row in rows:
        if row['kind']!='event_book' or row['source']!='WEBULL_PRODUCTION' or row['symbol'] not in indexes:continue
        times,values=indexes[row['symbol']];at=stamp(row['available_at']).timestamp();index=bisect_left(times,at)
        candidates=[values[i] for i in (index-1,index) if 0<=i<len(values)]
        matched=min(candidates,key=lambda r:abs(r[0]-at))
        key=(row['symbol'],matched[0])
        if abs(matched[0]-at)>5 or key in used:continue
        used.add(key);differences=[]
        for side in ('yes_bids','no_bids'):
            left,right=row.get(side,[]),matched[1].get(side,[])
            if not left or not right:sides['missing_reported_side']+=1;continue
            a,b=max(left,key=lambda r:r['price']),max(right,key=lambda r:r['price'])
            differences.append(abs(a['price']-b['price']))
            sides['compared_sides']+=1
            sides['same_best_bid']+=abs(a['price']-b['price'])<1e-8
            sides['different_best_bid_size']+=abs(a['size']-b['size'])>1e-8
        pairs.append((abs(matched[0]-at),differences))
    differences=[d for _,values in pairs for d in values]
    return {'paired_books':len(pairs),'independent_books':sum(len(v) for v in independent.values()),**dict(sides),
            'median_receipt_gap_seconds':median([p[0] for p in pairs]) if pairs else None,
            'median_absolute_bid_difference_usd':median(differences) if differences else None,
            'basis':'Exact ticker, one-to-one receipts within five seconds. No exchange timestamp, latency, broker depth equivalence or fill guarantee is inferred.'}


def build_archive(user_id,start,end):
    start,end=stamp(start),stamp(end)
    if not start<end or (end-start).days>370:raise ValueError('Choose an archive window of at most 370 days.')
    query=ResearchCapture.query.filter(ResearchCapture.user_id==user_id,ResearchCapture.received_at>=start.replace(tzinfo=None),ResearchCapture.received_at<end.replace(tzinfo=None)).order_by(ResearchCapture.id)
    hashes=[];excluded=Counter()
    def read_rows():
        total=0
        for capture in query.yield_per(25):
            total+=capture.raw_bytes
            if total>MAX_RAW_BYTES or len(hashes)>=20000:raise ValueError('Archive window exceeds 128 MiB / 20,000 batches; narrow the dates.')
            hashes.append([capture.id,capture.sha256])
            try:
                for raw in adapt(capture):
                    try:yield validate_row(raw)
                    except (ValueError,TypeError,KeyError) as exc:excluded[str(exc)[:120]]+=1
            except (KeyError,TypeError):excluded['Malformed '+capture.kind]+=1
        for row in event_evidence(user_id,start,end):
            try:yield validate_row(row)
            except (ValueError,TypeError,KeyError) as exc:excluded['Event evidence: '+str(exc)[:100]]+=1
    return canonical(read_rows(),{'origin':'LOCAL_ARCHIVE','captures':hashes,'start':iso(start),'end':iso(end),'source_verified':False},excluded)


def event_evidence(user_id,start,end):
    from event_algo_models import EventStrategyDecision as Decision, EventMarketSnapshot as Snapshot, EventContractOutcome as Outcome
    out=[]
    decisions=Decision.query.filter(Decision.user_id==user_id,Decision.created_at>=start.replace(tzinfo=None),Decision.created_at<end.replace(tzinfo=None)).order_by(Decision.created_at,Decision.id).limit(5001).all()
    if len(decisions)>5000:raise ValueError('Too many Event decisions; narrow the date window.')
    for row in decisions:
        snap=db.session.get(Snapshot,row.snapshot_id)
        if not snap or snap.user_id!=user_id or snap.config_id!=row.config_id or not snap.cutoff_at or row.probability_yes is None or row.confidence is None:continue
        if row.created_at>=snap.cutoff_at:continue
        out.append({'kind':'forecast','module':'events','symbol':row.contract_symbol,'source':'ARCHIVED_EVENT_FORECAST',
                    'currency':'USD','event_at':iso(row.created_at),'available_at':iso(row.created_at),
                    'probability_yes':row.probability_yes,'confidence':row.confidence,'cutoff_at':iso(snap.cutoff_at),
                    'decision_id':row.id,'config_id':row.config_id,'outcome':row.outcome,'market':json.loads(snap.raw_json or '{}')})
    outcomes=Outcome.query.filter(Outcome.user_id==user_id,Outcome.observed_at>=start.replace(tzinfo=None),Outcome.observed_at<end.replace(tzinfo=None),Outcome.settlement_status=='RESOLVED').limit(5001).all()
    if len(outcomes)>5000:raise ValueError('Too many Event outcomes; narrow the date window.')
    for row in outcomes:
        if row.outcome in ('YES','NO') and row.settlement_at and row.cutoff_at and row.cutoff_at<=row.settlement_at<=row.observed_at:
            out.append({'kind':'outcome','module':'events','symbol':row.contract_symbol,'source':row.resolved_source or 'UNKNOWN',
                        'currency':'USD','event_at':iso(row.settlement_at),'available_at':iso(row.observed_at),
                        'cutoff_at':iso(row.cutoff_at),'outcome':row.outcome,'outcome_id':row.id,'config_id':row.config_id})
    return out


def save_dataset(user_id,data):
    raw=encoded(data)
    if len(raw)>MAX_RAW_BYTES:raise ValueError('Normalized dataset exceeds 128 MiB.')
    digest=hashlib.sha256(raw).hexdigest()
    from services.event_runtime import job_slot
    from services.research_jobs import reserve_storage
    with job_slot(user_id,'research-dataset'):
        existing=ResearchDataset.query.filter_by(user_id=user_id,sha256=digest).first()
        if existing:return existing
        blob=gzip.compress(raw)
        summary=json.dumps(data['quality'])
        reserve_storage(user_id,len(blob)+len(summary.encode()))
        row=ResearchDataset(user_id=user_id,sha256=digest,payload_gzip=blob,summary_json=summary)
        db.session.add(row);db.session.commit()
        return row


def get_dataset(user_id,dataset_id):
    row=ResearchDataset.query.filter_by(user_id=user_id,id=dataset_id).first()
    if not row:raise ValueError('Dataset not found for this administrator.')
    return row,unpack(row.payload_gzip,row.sha256)
