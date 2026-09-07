"""Shared purpose, evidence semantics and completion checks for paper audits."""
import re

AUDIT_END = '<!-- AUDIT_COMPLETE -->'
AUDIT_TOKEN_LIMITS = {'portfolio_module_audit': 8192, 'portfolio_audit': 16384}

ENGINE_PURPOSE = (
    'This engine is an isolated, multi-asset PAPER research ledger. Its purpose is to forward-test '
    'deterministic strategies, realistic simulated costs, capital budgets and risk controls before '
    'judging their performance. It does not trade the real account. The annual return target is a '
    'research objective, never a forecast or promise. AI audits explain observed operation and suggest '
    'evidence-based engineering or strategy experiments; they do not execute trades or change settings. '
    'Only configured watchlists and enabled modules are eligible for new entries. Existing disabled-module '
    'positions still count as risk. Do not recommend enabling disabled futures just to fill an allocation. '
    'Allocation percentages are maximum strategy budgets, not mandatory invested weights. Unused cash '
    'is expected while signals, sessions, history or liquidity do not qualify. AVAILABLE_CAPACITY is '
    'not a buy signal. MARKET_CLOSED, DISABLED and WARMING_UP are not provider failures. READY means '
    'a scan evaluated data, not that an entry qualified. DEGRADED can describe one module while others '
    'continue operating. Never recommend bypassing data freshness, settlement or risk limits.'
)

EVIDENCE_RULES = (
    'Use only the supplied timestamped paper evidence. Do not invent current market prices, technical '
    'indicators, news, holdings, performance or correlations. An empty positions list means no open '
    'positions in that scope; historical fills and logs are not current holdings. Specialist prose is '
    'unverified interpretation and cannot override recorded facts. All fields ending _pct, including '
    'max_drawdown_pct, are ALREADY percentages: 0.115836 means 0.115836%, NOT 11.5836%. '
    'Event details.outcome/purchased_outcome is the YES or NO side BOUGHT, not the settlement result. '
    'A purchased NO contract pays $1 per unit if the provider confirms NO, $0 if YES; pending means '
    'unknown. Neither missing bids nor stale/terminal-looking trade prices prove a winner. Event value '
    'is quantity times mark; collateral and fees are separate. Distinguish open position counts, '
    'watchlist symbols evaluated, qualified signals, rejected entries and actual filled entries. '
    'Insufficient daily samples cannot justify numerical stress tests, CAGR or correlations. Do not '
    'introduce unrelated Binance accounts, tokenized equities, OCO orders, manual trade tickets or '
    'claims of live execution. Suggestions must relate to implemented rules and recorded limitations.'
)

STRATEGY_RULES = {
    'equities': 'US regular sessions only. Completed daily trend SMA, positive 63-session momentum and SPY relative strength; oversold RSI and lower Bollinger pullback. Exits: RSI recovery, trend failure or ATR stop.',
    'options': 'Standard defined-risk credit spreads, 20–65 DTE closest to configured target, short absolute delta near target, executable two-sided legs, IV Rank above minimum. IV Rank needs 252 observed daily ATM IV values with a non-flat range. Exits: profit target, spread stop or seven DTE. No invented IV history.',
    'crypto': '24/7 completed-hour Donchian breakouts with ATR trailing stops. ETH/SOL also require measured Bitcoin dominance at or below the preceding seven-day average. BTC does not require that filter.',
    'futures': 'Opt-in micro futures opening-range breakout with volume/VWAP confirmation, actual contract metadata, margin reserves, session exits and daily risk ceiling.',
    'events': 'Fresh eligible Event-worker decisions, configured confidence/net edge after fees, executable asks and pre-cutoff entries. Maximum three simultaneous positions, $50 entry risk and 50 units per lot. Mark at purchased-side bid; settle only on explicit provider evidence. Unresolved expired positions remain open and occupy capacity.',
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


def audit_system_prompt(custom, module=None):
    scope = ('Review only this module and its supplied positions. Explain readiness, actual activity, '
             'entry/exit blockers, data limitations and concrete next checks. Aim for 400–700 words.'
             if module else
             'Begin with ## 1. Executive Summary and one or two narrative paragraphs before any table. '
             'Then cover recorded performance, module operation and blockers, capital/risk, evidence '
             'limitations, and prioritized engineering/strategy observations. Aim for 900–1800 words. '
             'Explain why the engine did or did not trade, rather than prescribing unconditional investment.')
    return '\n\n'.join((custom or '', ENGINE_PURPOSE, EVIDENCE_RULES, scope))
