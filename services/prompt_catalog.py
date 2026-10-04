"""UI-managed AI instructions; bundled data supplies visible reset defaults."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
from flask import has_app_context


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).resolve().parent.parent / 'config/ai_prompt_catalog.json').read_text())


def default_prompt(key):
    return deepcopy(catalog()[key]['value'])


def overrides_for(user_id):
    if not user_id or not has_app_context():
        return {}
    from core.extensions import db
    from credentials import UserSetting
    row = db.session.get(UserSetting, user_id)
    values = json.loads(row.ai_prompt_overrides or '{}') if row else {}
    if not isinstance(values, dict):
        raise ValueError('Saved AI prompts are invalid; no provider request was made.')
    # Preserve the former Event report mandate, and expose its effective text
    # through the same editor that subsequent requests actually use.
    if row and row.event_strategy_audit_prompt and 'audit.event_system' not in values:
        values['audit.event_system'] = row.event_strategy_audit_prompt
    return values


def prompt_for(user_id, key, overrides=None):
    values = overrides_for(user_id) if overrides is None else overrides
    return deepcopy(values[key] if key in values else catalog()[key]['value'])


def render_prompt(template, **variables):
    # Replace supported variables only. Evidence is never recursively rendered.
    for key, value in variables.items():
        template = template.replace('{' + key + '}', str(value))
    return template


def validate_overrides(values):
    if not isinstance(values, dict) or len(json.dumps(values)) > 200000:
        raise ValueError('Prompt settings must be an object of at most 200000 characters.')
    for key, value in values.items():
        if key not in catalog():
            raise ValueError('Unknown AI prompt setting.')
        expected = catalog()[key]['value']
        if isinstance(expected, str):
            if not isinstance(value, str) or not value.strip() or len(value) > 24000:
                raise ValueError('Prompt text must contain 1–24000 characters.')
        else:
            if not isinstance(value, dict) or set(value) != set(expected):
                raise ValueError('Evaluation question IDs must match the response contract.')
            for name, question in value.items():
                original = expected[name]
                if not isinstance(question, dict) or set(question) != set(original) or question.get('type') != original['type']:
                    raise ValueError('Evaluation question types must match the response contract.')
                instruction = question['instructions']
                if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 6000:
                    raise ValueError('Evaluation instructions must contain 1–6000 characters.')
                if 'criteria' in original:
                    criteria, baseline = question['criteria'], original['criteria']
                    if isinstance(baseline, dict):
                        valid = isinstance(criteria, dict) and set(criteria) == set(baseline)
                        descriptions = criteria.values() if valid else []
                    else:
                        valid = isinstance(criteria, list) and len(criteria) == len(baseline)
                        descriptions = criteria if valid else []
                    if not valid or any(not isinstance(v, str) or not v.strip() or len(v) > 2000 for v in descriptions):
                        raise ValueError('Evaluation criteria must preserve labels and contain valid descriptions.')
        if key == 'jev.contract_probability':
            if any('{index}' not in q['instructions'] or '{symbol}' not in q['instructions'] for q in value.values()):
                raise ValueError('Contract questions must include {index} and {symbol} to bind each contract.')
        if key == 'audit.completion' and '{marker}' not in value:
            raise ValueError('The audit completion prompt must include {marker}.')
    return values


def save_overrides(row, values):
    validate_overrides(values)
    saved = json.loads(row.ai_prompt_overrides or '{}')
    saved.update(values)
    validate_overrides(saved)
    row.ai_prompt_overrides = json.dumps(saved, ensure_ascii=False)


def view_for(user_id):
    saved = overrides_for(user_id)
    return {key: {**deepcopy(entry), 'value': prompt_for(user_id, key, saved),
                  'default': deepcopy(entry['value'])} for key, entry in catalog().items()}
