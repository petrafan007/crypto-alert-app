"""Read-only chronological Event forecast/book sensitivity experiment.

Uploaded provenance is declared, not certified. Never estimates unobserved fills.
"""
import math
from collections import Counter
from datetime import datetime, timezone
from types import SimpleNamespace
from services.event_market_timing import observation_time, quote_freshness
from services.portfolio_calibration import summarize_event_calibration


def stamp(value):
    # Research uploads must identify a real instant, including a timezone.
    if not isinstance(value, str) or not (value.endswith('Z') or '+' in value[10:] or '-' in value[10:]):
        raise ValueError('Research timestamps must include an explicit UTC offset.')
    result = observation_time(value)
    if result is None:
        raise ValueError('Invalid research timestamp.')
    return result


def number(value, low=0, high=1):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a measured number.')
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError('Missing or invalid research numeric value.') from None
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError('Research numeric value outside allowed range.')
    return result


def run_event_validation(payload, config):
    from event_algo import evaluate_market, _market_cutoff
    if not isinstance(payload, dict) or payload.get('schema_version') != 1:
        raise ValueError('Expected schema_version 1.')
    records = payload.get('records')
    if not isinstance(records, list) or not 2 <= len(records) <= 2000 or any(not isinstance(row, dict) for row in records):
        raise ValueError('Provide 2–2000 Event record objects.')
    source = payload.get('source')
    if not isinstance(source, str) or not 3 <= len(source.strip()) <= 500:
        raise ValueError('Describe the observation source in 3–500 characters.')
    split = stamp(payload.get('split_at'))
    clean, symbols = [], set()
    for record in records:
        symbol = record.get('symbol')
        if not isinstance(symbol, str) or not 1 <= len(symbol) <= 160 or symbol in symbols:
            raise ValueError('Provide one forecast per unique exact contract symbol; duplicated forecasts are not independent samples.')
        symbols.add(symbol)
        when, cutoff, resolved = (stamp(record.get(key)) for key in ('decision_at','cutoff_at','resolved_at'))
        if not when < cutoff <= resolved <= datetime.now(timezone.utc) or record.get('outcome') not in ('YES','NO'):
            raise ValueError('Each forecast must precede cutoff and have a later observed YES/NO resolution.')
        probability, confidence = number(record.get('probability_yes')), number(record.get('confidence'))
        market = record.get('market')
        if not isinstance(market, dict) or market.get('symbol') != symbol:
            raise ValueError('Quote evidence must match the exact forecast contract.')
        effective_cutoff = _market_cutoff({**market, 'cutoff_at': cutoff.isoformat()})
        if effective_cutoff != cutoff.replace(tzinfo=None):
            raise ValueError('Declared cutoff conflicts with the contract symbol or quote evidence.')
        # Validate offset-bearing quote timestamps rather than silently assigning UTC.
        for key in ('quote_as_of','quote_retrieved_at','underlying_price_as_of'):
            if market.get(key) is not None:
                stamp(market[key])
        clean.append(dict(record, when=when, cutoff=cutoff, resolved=resolved, probability_yes=probability, confidence=confidence))
    clean.sort(key=lambda row:(row['when'],row['symbol']))
    windows = {}
    for key in ('development','held_out'):
        rows = [row for row in clean if (row['when'] < split) == (key=='development')]
        if not rows:
            raise ValueError('Development and held-out windows each require at least one contract.')
        forecasts, timing = [], Counter()
        paired_lags = []
        scenarios = []
        for row in rows:
            market = row['market']
            quote_status = quote_freshness(market, row['when'])['status']
            timing[quote_status] += 1
            if row.get('independent_quote_at') is not None:
                independent = stamp(row['independent_quote_at'])
                received = stamp(market.get('quote_retrieved_at'))
                paired_lags.append((received-independent).total_seconds())
            forecasts.append(dict(contract=row['symbol'], probability_yes=row['probability_yes'], result=row['outcome'],
                predicted_at=row['when'].isoformat(), cutoff_at=row['cutoff'].isoformat(), resolved_at=row['resolved'].isoformat(),
                verified_outcome=True, yes_bid=market.get('yes_bid') if quote_status == 'FRESH' else None,
                yes_ask=market.get('yes_ask') if quote_status == 'FRESH' else None))
        for name, slip, cost in [('reported_book',0,1),('one_cent_adverse',.01,1),('two_cents_double_fees',.02,2)]:
            pnl = 0.0
            reasons = Counter()
            trades = []
            for row in rows:
                market = {**row['market'], 'cutoff_at':row['cutoff'].isoformat(), 'model_probability_yes':row['probability_yes'], 'model_confidence':row['confidence']}
                if quote_freshness(market, row['when'])['status'] != 'FRESH':
                    reasons['unusable_quote_time'] += 1
                    continue
                for side in ('yes','no'):
                    if market.get(side+'_ask') is not None:
                        market[side+'_ask'] = number(market[side+'_ask'])+slip
                import json
                signal = json.loads(config.signal_config)
                fee = number(signal.get('fee_per_contract', .015))*cost
                signal['fee_per_contract'] = fee
                cfg = SimpleNamespace(risk_config=config.risk_config, signal_config=json.dumps(signal), kill_switch=False)
                decision = evaluate_market(market, cfg, now=row['when'].replace(tzinfo=None))
                if not decision['eligible']:
                    reasons['failed_saved_entry_gates'] += 1
                    continue
                depth = market.get(decision['outcome'].lower()+'_ask_size')
                if depth is None:
                    reasons['unknown_depth_no_assumed_fill'] += 1
                    continue
                if number(depth, 0, 1e9) < 1:
                    reasons['insufficient_depth'] += 1
                    continue
                value = (1 if row['outcome']==decision['outcome'] else 0)-decision['executable_price']-fee
                trades.append({'symbol':row['symbol'],'net_pnl':round(value,8),'entry_at':row['when'].isoformat(),'settled_at':row['resolved'].isoformat()})
                pnl += value
            scenarios.append({'scenario':name,'filled_contracts':len(trades),'net_pnl':round(pnl,8) if trades else None,'exclusions':dict(reasons),'trades':trades})
        windows[key] = {'contracts':len(rows), 'calibration':summarize_event_calibration(forecasts), 'scenarios':scenarios,
                        'quote_time_status':dict(timing), 'paired_independent_timestamps':len(paired_lags),
                        'retrieval_minus_independent_seconds':{'min':min(paired_lags),'max':max(paired_lags),'mean':sum(paired_lags)/len(paired_lags)} if paired_lags else None}
    return {'schema_version':1,'scope':'event_forecast_book_sensitivity','module':'events','source':source.strip(),'source_verified':False,
            'windows':windows,'saved_parameters':{'risk_config':config.risk_config,'signal_config':config.signal_config},
            'assumptions':['All input outcomes and source identities are declared by the uploader; the engine does not independently certify them.',
                'One hypothetical contract per eligible record. Reported depth is required, but top-of-book size is not proof of fill or queue priority.',
                'Scenarios reapply saved signal gates, but are independent contract experiments, not a bankroll simulation; aggregate exposure, correlation, overlapping positions and settlement capital reuse are not modeled.',
                'Timestamp pairing measures submitted observations only. Pairing does not prove independent source identity or establish real exchange freshness.',
                'Held-out means chronological separation only. Prior inspection, selection bias and repeated tuning can invalidate inference.',
                'No live risk expansion, strategy setting change or ledger write follows from this experiment.']}
