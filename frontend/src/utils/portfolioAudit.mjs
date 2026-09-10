export const AUDIT_SLUG_MAP = {
  warming_up: 'Calibrating indicators & collecting history',
  available_capacity: 'Available buying power & capital headroom',
  market_closed: 'U.S. regular market closed (session inactive)',
  circuit_paused: 'Trading paused by portfolio risk circuit',
  no_signal: 'Market scanned; no qualifying trade setups',
  data_limited: 'Market quote feed temporarily delayed or incomplete',
  ready: 'Active & evaluating market data',
  scanned: 'Active & evaluating market data',
  active: 'Actively running',
  disabled: 'Strategy module disabled',
  neutral: 'Neutral market conditions',
  cash_preserved: 'Capital preserved in cash',
  high_volatility: 'High market volatility detected',
  low_liquidity: 'Low liquidity / wide spread',
  loss_limit_reached: 'Daily loss limit reached',
  drawdown_limit: 'Drawdown threshold reached',
  rate_limited: 'API rate limit cooldown active',
  idle: 'Standing by for scheduled evaluation cycle',
  success: 'Completed successfully',
  partial: 'Completed with some module limitations',
  pending: 'Audit queued / generating report',
};

export function humanizeAuditSlug(slug) {
  if (!slug) return '';
  const key = String(slug).toLowerCase().trim();
  if (AUDIT_SLUG_MAP[key]) return AUDIT_SLUG_MAP[key];
  return key
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function cleanHumanText(text) {
  if (!text || typeof text !== 'string') return '';
  let cleaned = text;
  for (const [slug, human] of Object.entries(AUDIT_SLUG_MAP)) {
    const slugPattern = new RegExp(`(?<![a-zA-Z0-9_-])\`?${slug}\`?(?![a-zA-Z0-9_-])`, 'gi');
    cleaned = cleaned.replace(slugPattern, human);
  }
  return cleaned;
}

export function normalizePortfolioAudit(audit) {
  if (!audit) return null;
  const warnings = (audit.validation_warnings || []).map((warning) => `> **Report limitation:** ${cleanHumanText(warning)}\n\n`).join('');
  return {
    ...audit,
    created_at: audit.timestamp || audit.created_at,
    content_markdown: warnings + ([audit.content, audit.content_markdown, audit.summary].find((value) => typeof value === 'string' && value.trim()) ||
      (audit.status === 'PENDING' ? 'Audit queued. Waiting for the completed report.' : 'This archived report contains no text. Generate a fresh report to collect current evidence.')),
    evidence: audit.evidence || {},
  };
}

export function selectPortfolioAudit(audits, id) {
  if (!Array.isArray(audits) || !audits.length) return null;
  return audits.find((audit) => String(audit.id) === String(id)) || audits[0] || null;
}

export function auditOutcomeMessage(audit) {
  if (audit?.status === 'SUCCESS') return 'Portfolio AI audit completed.';
  if (audit?.status === 'PARTIAL') return 'Portfolio report completed with module limitations. Review the report and module errors.';
  if (audit?.status === 'PENDING') return 'Audit queued. This window updates automatically; you can close it and return later.';
  return cleanHumanText(audit?.content_markdown) || 'The audit did not complete. Review its saved diagnostics.';
}

export function portfolioAuditProgress(audit) {
  if (audit?.progress) return audit.progress;
  const evidence = audit?.evidence || {};
  const modules = Object.keys(evidence.specialist_mandates || {});
  const failed = modules.filter((module) => Object.hasOwn(evidence.module_audit_errors || {}, module));
  const completed = modules.filter((module) => evidence.module_audits?.[module] || failed.includes(module));
  const finished = ['SUCCESS', 'PARTIAL'].includes(audit?.status);
  return {
    percent: finished ? 100 : modules.length ? Math.round(5 + 80 * completed.length / modules.length) : 0,
    stage: finished ? 'complete' : audit?.status && audit.status !== 'PENDING' ? 'failed' : !modules.length ? 'queued' : completed.length === modules.length ? 'master' : 'module',
    modules,
    completed_modules: completed,
    failed_modules: failed,
    current_module: modules.find((module) => !completed.includes(module)),
  };
}

export function buildExecutiveSummary(audit) {
  if (!audit) {
    return {
      healthStatus: 'idle',
      healthLabel: '⚪ No Report Available',
      headline: 'No quantitative strategy audit is currently selected.',
      statusExplanation: 'Generate an AI audit report to evaluate operational health and strategy performance.',
      isOperatingProperly: false,
      modules: [],
      recommendations: ['Click "Generate Fresh Report Now" to run a complete audit across all modules.'],
    };
  }

  const evidence = audit.evidence || {};
  const specialistMandates = evidence.specialist_mandates || {};
  const moduleAudits = evidence.module_audits || {};
  const moduleErrors = evidence.module_audit_errors || {};
  const moduleNames = Object.keys(specialistMandates);
  const failedCount = Object.keys(moduleErrors).length;

  const rawMarkdown = [audit.content, audit.content_markdown, audit.summary].find((val) => typeof val === 'string' && val.trim()) || '';
  const cleanedMarkdown = cleanHumanText(rawMarkdown);

  let healthStatus = 'healthy';
  let healthLabel = '🟢 Operating Properly (Healthy)';
  let isOperatingProperly = true;

  const textLower = cleanedMarkdown.toLowerCase();
  const isCircuitPaused = textLower.includes('circuit paused') || textLower.includes('risk circuit') || textLower.includes('trading paused');
  const isWarmingUp = textLower.includes('calibrating indicators') || textLower.includes('warming up');
  const isMarketClosed = textLower.includes('market closed') || textLower.includes('session inactive');

  if (audit.status === 'PENDING') {
    healthStatus = 'pending';
    healthLabel = '🔵 Generating Report…';
    isOperatingProperly = true;
  } else if (failedCount > 0 || audit.status === 'PARTIAL') {
    healthStatus = 'degraded';
    healthLabel = `🟡 Attention Needed (${failedCount} module issue${failedCount === 1 ? '' : 's'})`;
    isOperatingProperly = false;
  } else if (isCircuitPaused) {
    healthStatus = 'paused';
    healthLabel = '🟠 Trading Paused (Risk Circuit Active)';
    isOperatingProperly = false;
  } else if (isWarmingUp) {
    healthStatus = 'healthy';
    healthLabel = '🟢 Operating Properly (Calibrating)';
    isOperatingProperly = true;
  } else if (isMarketClosed) {
    healthStatus = 'healthy';
    healthLabel = '🟢 Operating Properly (Market Closed)';
    isOperatingProperly = true;
  }

  let statusExplanation = '';
  if (audit.status === 'PENDING') {
    statusExplanation = 'The quantitative audit is currently running. Specialist modules are inspecting portfolio performance, market signals, and risk limits.';
  } else if (isCircuitPaused) {
    statusExplanation = 'The strategy engine is operating with active risk protections: trading is temporarily paused by a portfolio risk circuit or daily drawdown guardrail to preserve capital.';
  } else if (failedCount > 0) {
    statusExplanation = `The engine is partially running, but ${failedCount} specialist module${failedCount === 1 ? ' encountered an error and requires' : 's encountered errors and require'} inspection. Other strategy components continue to function normally.`;
  } else if (isMarketClosed) {
    statusExplanation = 'The strategy engine is healthy and standing by for the next regular market session. Account balances, risk parameters, and watchlists are ready for market open.';
  } else if (isWarmingUp) {
    statusExplanation = 'The engine is operating properly, calibrating technical indicators and ingesting real-time price history before issuing automated trade setups.';
  } else {
    statusExplanation = 'The quantitative strategy engine is operating properly with no system faults. Strategy modules are actively evaluating market conditions and scanning watchlists for qualifying trade setups adhering to risk boundaries.';
  }

  const modules = moduleNames.map((modName) => {
    const error = moduleErrors[modName];
    const modAudit = moduleAudits[modName];
    const mandate = specialistMandates[modName] || {};
    let status = 'ready';
    let humanStatus = 'Active & evaluating market data';

    if (error) {
      status = 'error';
      humanStatus = cleanHumanText(error);
    } else if (modAudit) {
      const summaryText = typeof modAudit === 'string' ? modAudit : (modAudit.summary || modAudit.status || 'Active');
      humanStatus = cleanHumanText(summaryText);
    }

    return {
      name: modName,
      label: mandate.title || modName.replace(/_/g, ' ').toUpperCase(),
      status,
      humanStatus,
      error: error ? cleanHumanText(error) : null,
    };
  });

  const recommendations = [];
  if (failedCount > 0) {
    for (const [mod, err] of Object.entries(moduleErrors)) {
      recommendations.push(`Repair ${mod.toUpperCase()}: ${cleanHumanText(err)}. Verify market data feeds and API permissions.`);
    }
  }
  if (isCircuitPaused) {
    recommendations.push('Review portfolio risk circuit thresholds in Strategy Settings. If market conditions have stabilized, evaluate lifting circuit pauses.');
  }
  if (isMarketClosed) {
    recommendations.push('Regular market hours are closed. Prepare watchlists and verify capital allocation for the upcoming trading session.');
  }
  if (recommendations.length === 0) {
    recommendations.push('The engine is running smoothly. Continue monitoring execution fills and review open positions periodically in Webull Trading.');
    recommendations.push('Ensure sufficient buying power is allocated under Strategy Settings to capitalize on emerging algorithmic setups.');
  }

  return {
    healthStatus,
    healthLabel,
    headline: audit.headline ? cleanHumanText(audit.headline) : (audit.status === 'SUCCESS' ? 'Audit Complete: Engine Healthy' : 'Audit Complete: Limitations Noted'),
    statusExplanation,
    isOperatingProperly,
    modules,
    recommendations,
  };
}
