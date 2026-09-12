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
    'Use only code-calculated goal_tracking annualization and correlations when present; a null metric '
    'means unavailable, not zero. No sample-count threshold automatically implements or validates stress tests. '
    'An indicator omitted from the report is NOT evidence that its provider data are missing. '
    'MARKET_CLOSED with zero evaluations means the session gate skipped the scan; it does not mean '
    'missing price history or a broken feed. READY proves the evaluated symbols passed data collection '
    'and indicator calculation for that scan only; it is not proof of timely decision consumption or successful '
    'execution. Event readiness must be supported by fresh observed decisions, quotes and handoff outcomes. '
    'Use signal_checks to explain unqualified entries; do not infer a failed '
    'dominance gate from a generic strategy name. NOT_DUE Event positions are ordinary unexpired '
    'holdings, not stuck settlements, and two positions occupy two slots. Use exchange_session times '
    'rather than guessing the local trading session from UTC. allocation_preference is an internal '
    'relative weight, never actual exposure. Per-module realized P&L belongs to that named module. '
    'Do not invent flags, controls, data-import jobs, provider outages or new risk violations. Do not '
    'claim a long-term annual target has failed on a one-day sample. A supplied target-path shortfall is a '
    'descriptive difference at that timestamp, not proof of strategy failure. Follow operational_summary '
    'as the authoritative explanation of each module; specialist prose is not a source of new facts. '
    'The implemented portfolio circuit pauses new entries at a 10% loss of starting bankroll; '
    'do not claim it is missing or suggest adding it. This floor differs from historical peak-to-trough '
    'maximum drawdown. Do not attribute maximum drawdown to current holdings or a single trade without '
    'a supplied attribution. Drift is actual_pct minus target_pct. Open Event market value is '
    'collateral plus unrealized P&L, not original collateral. Use supplied formatted monetary facts '
    'rather than inventing notional exposure. Do not recommend relaxing confidence, edge, dominance '
    'or warm-up requirements just to generate trades, especially with one daily return sample. '
    'Do not propose adding controls or calculators that strategy_rules/risk_controls say are already implemented. '
    'Do not introduce unrelated Binance accounts, tokenized equities, OCO orders, manual trade tickets or '
    'claims of live execution. Suggestions must relate to implemented rules and recorded limitations. '
    'The numeric goal_tracking.target_annual_return_pct is authoritative over legacy ranges in custom prompts. '
    'Use the supplied target equity, dollar/percentage gap, CAGR percentage-point gap, rolling returns, '
    'capital utilization and module contributions without inventing missing values. Label all results PAPER '
    'and give the run period, as-of timestamp and observation gaps. The target path is hypothetical, not an '
    'investable benchmark or measured cash opportunity cost. Thirty elapsed days is only the annualization '
    'display threshold, not validation, statistical confidence, or evidence of attainable future CAGR. '
    'Report SUCCESS means report generation completed, not that the strategy, data feeds or workers are healthy. '
    'Separate recorded facts, inferred explanations, missing evidence and proposed experiments. '
    'Only claim historical replay, cost/latency sensitivity, stress scenarios or calibration were performed '
    'when their timestamped results and coverage are supplied. Never turn an engineering unit-test pass '
    'into a claim of investment performance. Treat any validation result as scoped to its supplied data, '
    'assumptions and module coverage, never proof of portfolio-wide goal attainment.'
)

DEFAULT_AUDIT_GUIDANCE = (
    'Evaluate progress toward the configured annual research target using goal_tracking, not a legacy '
    'target range. Explain the measured target-equity gap now and the annualized percentage-point gap '
    'only when available. Identify each enabled module’s net contribution, capital utilization and '
    'operational blockers. Distinguish a successful report from healthy workers and a validated strategy. '
    'Organize recommendations into recorded defects to fix, missing evidence to collect, and controlled '
    'strategy experiments with out-of-sample evaluation and realistic costs, latency and missed fills. '
    'Explain exactly what has and has not been tested; do not invent stress-test or calibration results. '
    'Do not relax freshness, risk, confidence or signal gates merely to force more trades.'
)

MASTER_SCOPE = (
    'Begin with ## 1. Executive Summary and one or two narrative paragraphs before any table. '
    'CRITICAL TONE AND VOCABULARY: Write in clear, human-friendly, plain English for an executive or active trader; '
    'do not write like a dense academic research paper. In Section 1 Executive Summary, strictly avoid using raw internal '
    'slugs or code variable names such as warming_up, available_capacity, market_closed, no_signal, or data_limited; '
    'translate them into plain language (e.g. "calibrating indicator history", "available buying power / capital headroom", '
    '"regular market session is closed", "no qualifying setups"). '
    'The Executive Summary must state clearly: (1) what the engine is doing right now and its current operational state, '
    '(2) whether the engine is working properly or has operational defects, and (3) actionable recommendations to improve '
    'or repair the quantitative strategy engine. '
    'Then cover measured goal progress, recorded performance, module operation and blockers, capital/risk, '
    'evidence limitations, and prioritized engineering/strategy observations. Aim for 900–1800 words. '
    'Explain why the engine did or did not trade, rather than prescribing unconditional investment.'
)
MODULE_SCOPE = (
    'Review only this module and its supplied positions. Explain readiness, actual activity, '
    'entry/exit blockers, data limitations, net contribution when supplied and concrete next checks. '
    'Do not infer portfolio-wide performance from this module. Aim for 400–700 words.'
)


def audit_prompt_policy():
    """Expose every shared system instruction alongside the editable prompts."""
    return {'engine_purpose': ENGINE_PURPOSE, 'evidence_rules': EVIDENCE_RULES,
            'default_guidance': DEFAULT_AUDIT_GUIDANCE,
            'master_scope': MASTER_SCOPE, 'module_scope': MODULE_SCOPE}

STRATEGY_RULES = {
    'equities': 'US regular sessions only. Completed daily trend SMA, positive 63-session momentum and SPY relative strength; oversold RSI and lower Bollinger pullback. Exits: RSI recovery, trend failure or ATR stop.',
    'options': 'Standard defined-risk credit spreads, 20–65 DTE closest to configured target, short absolute delta near target, executable two-sided legs, IV Rank above minimum. IV Rank needs 252 observed daily ATM IV values with a non-flat range. Exits: profit target, spread stop or seven DTE. No invented IV history.',
    'crypto': '24/7 completed-hour Donchian breakouts with ATR trailing stops. ETH/SOL also require measured Bitcoin dominance at or below the preceding seven-day average. BTC does not require that filter.',
    'futures': 'Opt-in micro futures opening-range breakout with volume/VWAP confirmation, actual contract metadata, margin reserves, session exits and daily risk ceiling.',
    'events': 'Fresh eligible Event-worker decisions, configured confidence/net edge after fees, selected-side executable books and pre-cutoff entries. Use the saved Event risk policy in structured evidence for position, fee-inclusive exposure, contract, rolling-hour, Eastern-day and realized high-water drawdown limits; do not substitute historical hard-coded limits. Open stakes and fees reserve loss allowance. Supplied ask depth caps quantity; missing depth is unknown. Mark at purchased-side bid; settle only on explicit provider evidence. Unresolved expired positions remain open and occupy capacity.',
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


def audit_system_prompt(custom, module=None, guidance=None):
    return '\n\n'.join((custom or '', ENGINE_PURPOSE,
                        DEFAULT_AUDIT_GUIDANCE if guidance is None else guidance,
                        EVIDENCE_RULES, MODULE_SCOPE if module else MASTER_SCOPE))
