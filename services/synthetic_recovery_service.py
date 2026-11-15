"""Atomic, idempotent recovery of settled synthetic failures only."""
import json
from core.extensions import db
from core.time_utils import utc_now
from trading_models import LadderOrder, LadderRung, TrailingOrder, SyntheticRecovery
from services import synthetic_execution_service as ex


def recover(user_id, kind, identifier, data):
    model = {'LADDER': LadderOrder, 'TRAILING': TrailingOrder}.get(kind)
    if model is None:
        raise ValueError('Unknown synthetic strategy kind.')
    with ex.parent_lock(kind, identifier) as locked:
        if not locked:
            raise ValueError('This strategy is busy. Refresh before retrying.')
        source = model.query.filter_by(id=identifier, user_id=user_id).populate_existing().first()
        if source is None:
            raise ValueError('Synthetic strategy not found.')
        prior = SyntheticRecovery.query.filter_by(user_id=user_id, parent_kind=kind, parent_id=identifier).first()
        if prior:
            return dict(action=prior.action, replacement_id=prior.replacement_id, replacement_kind=prior.replacement_kind, already_recovered=True)
        if source.status != 'FAILED' or source.engine_version != 2:
            raise ValueError('Only a stopped, verified failure can be recovered.')
        rows = ex.reconcile_executions(source, kind)
        if any(row.status in ex.OPEN_EXECUTIONS for row in rows):
            raise ValueError('Awaiting final broker confirmation. No replacement has been submitted.')
        details = source.to_dict()
        remaining = details['remaining_quantity']
        if remaining <= 1e-10:
            raise ValueError('No unfilled quantity remains. Refresh broker fills.')
        action = data.get('action')
        if action not in {'REPLACE', 'REGULAR', 'KEEP_CANCELLED'}:
            raise ValueError('Choose Replace / Retry, Use Regular Hours, or Keep Cancelled.')
        replacement = None
        replacement_kind = kind
        if action != 'KEEP_CANCELLED':
            session = 'CORE' if action == 'REGULAR' else str(data.get('trading_session', source.trading_session)).upper()
            identity = ex.validate_identity(source.symbol, source.side, source.broker, source.instrument_type, session, source.account_id, source.test_mode)
            session = identity[4]
            ex.require_whole_shares(remaining, session, source.instrument_type)
            ex.check_synthetic_order_capacity(user_id, source.symbol, source.side, remaining, source.broker,
                                              source.test_mode, account_id=source.account_id)
            if action == 'REPLACE' and data.get('strategy_type') in {'TRAILING', 'LADDER'}:
                shared = dict(user_id=user_id, symbol=source.symbol, side=source.side, broker=source.broker,
                    account_id=source.account_id, instrument_type=source.instrument_type, trading_session=session,
                    test_mode=source.test_mode, limit_cap_pct=data.get('limit_cap_pct', source.limit_cap_pct), commit=False)
                if data['strategy_type'] == 'TRAILING':
                    from services.trailing_order_service import create_trailing_order
                    result = create_trailing_order(**shared, quantity=remaining, trail_type='PERCENT', trail_value=data.get('trail_value'))
                    replacement_kind = 'TRAILING'
                    replacement = db.session.get(TrailingOrder, result['id'])
                else:
                    from services.ladder_order_service import create_ladder_order
                    targets = data.get('rungs')
                    if not isinstance(targets, list) or not targets:
                        raise ValueError('Add ladder targets and allocations.')
                    result = create_ladder_order(**shared, total_quantity=remaining, custom_rungs=targets, upside_mode='LADDER')
                    replacement_kind = 'LADDER'
                    replacement = db.session.get(LadderOrder, result['id'])
            elif action == 'REPLACE' and data.get('strategy_type') not in (None, 'SAME'):
                from services.synthetic_conditional_service import create_conditional
                replacement = create_conditional(user_id, dict(
                    symbol=source.symbol, side=(data.get('legs') or [{}])[0].get('side', source.side), broker=source.broker,
                    instrument_type=source.instrument_type, trading_session=session, account_id=source.account_id,
                    test_mode=source.test_mode, total_quantity=remaining, strategy_type=data['strategy_type'],
                    legs=data.get('legs'), limit_cap_pct=data.get('limit_cap_pct', source.limit_cap_pct)), commit=False)
                # Recovery is for the same holding and direction, never an implicit reversal.
                if replacement.side != source.side:
                    raise ValueError('Replacement must retain the failed phase\'s side.')
                replacement_kind = 'LADDER'
            else:
                excluded = {'id', 'created_at', 'updated_at', 'last_checked_at', 'last_price', 'monitoring_error',
                            'error_message', 'triggered_at', 'executed_order_id', 'cancel_requested', 'status'}
                values = {column.name: getattr(source, column.name) for column in model.__table__.columns if column.name not in excluded}
                values.update(status='ACTIVE', cancel_requested=False, trading_session=session,
                              limit_cap_pct=ex.limit_cap(data.get('limit_cap_pct', source.limit_cap_pct), session))
                values['total_quantity' if kind == 'LADDER' else 'quantity'] = remaining
                if kind == 'LADDER':
                    values['rungs_filled'] = 0
                    if source.total_budget_usd:
                        values['total_budget_usd'] = source.total_budget_usd * remaining / source.total_quantity
                    if source.conditional_spec:
                        spec = json.loads(source.conditional_spec)
                        if source.conditional_phase == 'EXIT':
                            spec['legs'] = spec['legs'][1:]
                            values.update(conditional_phase='SINGLE', strategy_type='OCO' if len(spec['legs']) == 2 else 'LIMIT')
                        values['conditional_spec'] = json.dumps(spec)
                if action == 'REPLACE' and not (kind == 'LADDER' and source.conditional_spec):
                    allowed = {'upside_target_price', 'downside_target_price', 'upside_trail_value', 'downside_trail_value'} if kind == 'LADDER' else {'trail_value'}
                    for field, value in (data.get('edits') or {}).items():
                        if field not in allowed:
                            raise ValueError('Unsupported strategy setting.')
                        values[field] = ex.positive(value, field.replace('_', ' '))
                        if 'trail_value' in field:
                            ex.trailing_parameters(value, values.get(field.replace('_value', '_type'), 'PERCENT'))
                    if kind == 'LADDER' and 'downside_target_price' in values:
                        values['stop_loss_trigger_price'] = values['downside_target_price']
                replacement = model(**values)
                db.session.add(replacement)
                db.session.flush()
                if kind == 'LADDER' and not source.conditional_spec:
                    # Restart the reviewed allocation over ONLY the unfilled remainder.
                    rules = ex.quantity_rules(replacement)
                    allocated = {}
                    for rung in source.rungs:
                        group = [r for r in source.rungs if r.rung_type == rung.rung_type]
                        raw = remaining - allocated.get(rung.rung_type, 0) if rung == group[-1] else remaining * rung.percentage_of_total / 100
                        qty = ex.normalize_quantity(raw, rules)
                        allocated[rung.rung_type] = allocated.get(rung.rung_type, 0) + qty
                        ex.require_whole_shares(qty, session, source.instrument_type)
                        ex.positive(qty, 'Replacement rung quantity')
                        db.session.add(LadderRung(ladder_id=replacement.id, rung_number=rung.rung_number,
                            rung_type=rung.rung_type, target_price=(values.get('upside_target_price') if rung.rung_type == 'TAKE_PROFIT' and values.get('upside_mode') == 'SINGLE' else rung.target_price), price_offset_pct=rung.price_offset_pct,
                            quantity=qty, percentage_of_total=rung.percentage_of_total, estimated_usd=qty*rung.target_price, status='PENDING'))
            if not getattr(replacement, 'conditional_spec', None):
                from services.trailing_order_service import calculate_trailing_stop_price
                if replacement_kind == 'TRAILING':
                    watermark = replacement.highest_price if replacement.side == 'SELL' else replacement.lowest_price
                    replacement.current_stop_price = calculate_trailing_stop_price(replacement.side, watermark, replacement.trail_type, replacement.trail_value)
                else:
                    for prefix in ('upside', 'downside'):
                        if getattr(replacement, f'{prefix}_mode') == 'TRAILING':
                            watermark = getattr(replacement, 'upside_highest_price' if prefix == 'upside' else 'downside_lowest_price')
                            setattr(replacement, f'{prefix}_current_stop_price', calculate_trailing_stop_price(replacement.side, watermark, getattr(replacement, f'{prefix}_trail_type'), getattr(replacement, f'{prefix}_trail_value')))
            replacement.updated_at = utc_now(aware=False)
        decision = SyntheticRecovery(user_id=user_id, parent_kind=kind, parent_id=identifier, action=action,
            replacement_kind=replacement_kind if replacement else None, replacement_id=replacement.id if replacement else None)
        db.session.add(decision)
        db.session.commit()
        return dict(action=action, replacement_id=decision.replacement_id, replacement_kind=decision.replacement_kind)
