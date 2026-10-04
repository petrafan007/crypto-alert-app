"""Shared purpose, evidence semantics and completion checks for paper audits."""
from services.prompt_catalog import default_prompt, prompt_for
import re

AUDIT_END = '<!-- AUDIT_COMPLETE -->'
AUDIT_TOKEN_LIMITS = {'portfolio_module_audit': 8192, 'portfolio_audit': 16384, 'portfolio_strategy_review': 4096}

ENGINE_PURPOSE = default_prompt('audit.engine_purpose')

EVIDENCE_RULES = default_prompt('audit.evidence_rules')

DEFAULT_AUDIT_GUIDANCE = default_prompt('audit.default_audit_guidance')

MASTER_SCOPE = default_prompt('audit.master_scope')
MODULE_SCOPE = default_prompt('audit.module_scope')


def audit_prompt_policy(user_id=None):
    """Expose every shared system instruction alongside the editable prompts."""
    return {name: prompt_for(user_id, 'audit.' + key) for name, key in
            [('engine_purpose', 'engine_purpose'), ('evidence_rules', 'evidence_rules'),
             ('default_guidance', 'default_audit_guidance'), ('master_scope', 'master_scope'), ('module_scope', 'module_scope')]}

STRATEGY_RULES = {
    'equities': 'US regular sessions only. Completed 63-session trend and SPY relative strength rank the two leading watchlist symbols. Independent oversold RSI/lower-band pullback may also qualify in a positive long trend. Exits: RSI recovery, trend failure or ATR stop.',
    'options': 'Defined-risk 20–65 DTE credit spreads use fresh two-sided legs. During IV warm-up, completed underlying history, realized volatility and current ATM IV support a separately labeled paper regime. Thirty verified IV sessions permit a short percentile; 252 permit annual IV rank. Exits: profit target, spread stop or seven DTE. No invented IV history.',
    'crypto': '24/7 completed-hour Donchian breakouts with ATR trailing stops. ETH/SOL also require measured Bitcoin dominance at or below the preceding seven-day average. BTC does not require that filter.',
    'futures': 'Opt-in micro futures opening-range breakout with volume/VWAP confirmation, actual contract metadata, margin reserves and session exits. Daily P&L is measured, not an entry stop.',
    'events': 'Fresh eligible Event-worker decisions, configured confidence/net edge after fees, selected-side executable books and pre-cutoff entries. Saved per-trade dollars, open dollars, positions and contract count limit paper exposure. Rolling-hour, Eastern-day P&L and realized high-water drawdown remain measured facts, not entry stops. Supplied ask depth caps quantity; missing depth is unknown. Mark at purchased-side bid; settle only on explicit provider evidence. Unresolved expired positions remain open and occupy capacity.',
}


class CompletionText(str):
    """String-compatible provider text retaining termination metadata."""
    def __new__(cls, text, finish_reason=None, final_answer=True):
        obj = super().__new__(cls, text or '')
        obj.finish_reason = finish_reason
        obj.final_answer = final_answer
        return obj


class IncompleteAuditError(ValueError):
    def __init__(self, message, partial_text=''):
        super().__init__(message)
        self.partial_text = str(partial_text)


def complete_audit_text(value):
    text = str(value or '').strip()
    reason = str(getattr(value, 'finish_reason', '') or '').lower()
    if reason in ('length', 'max_tokens', 'max_output_tokens', 'model_length', 'content_filter', 'safety', 'recitation'):
        raise IncompleteAuditError(f'Audit provider ended with {reason}; incomplete output rejected.', text)
    if not getattr(value, 'final_answer', True) or not text.endswith(AUDIT_END):
        raise IncompleteAuditError('Audit final answer is missing its completion marker; incomplete output rejected.', text)
    text = text[:-len(AUDIT_END)].rstrip()
    if not text or text.count('```') % 2:
        raise IncompleteAuditError('Audit is empty or has an unfinished code block.', text)
    return text


def check_drawdown_claim(text, evidence):
    """Reject the observed percentage/fraction regression before saving success."""
    actual = evidence.get('performance', {}).get('max_drawdown_pct')
    if actual is None:
        return
    for line in text.splitlines():
        if re.search(r'(?:max(?:imum)?[\s-]*drawdown|observed[\s-]*drawdown)', line, re.I):
            # Inspect the value immediately after the metric label, not a later
            # recommendation or a separate risk limit on the same line.
            match = re.search(r'(?:max(?:imum)?[\s-]*drawdown|observed[\s-]*drawdown)[^\d\n]{0,35}(\d+(?:\.\d+)?)\s*%', line, re.I)
            if match and abs(float(match[1])-actual) > 0.011:
                raise IncompleteAuditError('Audit drawdown claim contradicts the recorded percentage.', text)
    if evidence.get('risk_controls', {}).get('portfolio_circuit_implemented'):
        if re.search(r'(?:does not enforce|lacks|no)\s+(?:a\s+)?(?:stop.loss|drawdown guard|drawdown circuit)[^\n.]{0,45}portfolio', text, re.I):
            raise IncompleteAuditError('Audit incorrectly claims the implemented portfolio risk circuit is absent.', text)


def audit_system_prompt(custom, module=None, guidance=None, user_id=None):
    policy = audit_prompt_policy(user_id)
    return '\n\n'.join((custom or '', policy['engine_purpose'],
                        policy['default_guidance'] if guidance is None else guidance,
                        policy['evidence_rules'], policy['module_scope' if module else 'master_scope']))
