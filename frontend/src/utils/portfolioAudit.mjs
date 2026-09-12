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

  // Archived evidence describes the report timestamp, not today's engine.
  // Narrative text and successful report generation cannot establish health.
  const reportStatus = String(audit.status || '').toUpperCase();
  const workerStatus = String(evidence.worker_status || '').toUpperCase();
  const moduleStates = Object.values(evidence.modules || {})
    .filter((item) => item && item.enabled !== false && item.status !== 'DISABLED')
    .map((item) => String(item.status || '').toUpperCase());
  const isCircuitPaused = evidence.kill_switch === true ||
    evidence.risk_controls?.new_entries_paused === true ||
    ['MONITORING_ONLY', 'CIRCUIT_PAUSED', 'KILLED'].includes(workerStatus);
  const isWarmingUp = moduleStates.includes('WARMING_UP');
  const isMarketClosed = moduleStates.includes('MARKET_CLOSED');
  const operationalFailure = ['DEGRADED', 'STALLED', 'STALE', 'ERROR'].includes(workerStatus) ||
    moduleStates.some((status) => ['DATA_LIMITED', 'SUBSCRIPTION_REQUIRED', 'ERROR', 'STALE', 'STALLED'].includes(status));
  const knownReadyStates = ['READY', 'SCANNED', 'NO_SIGNAL', 'WARMING_UP', 'MARKET_CLOSED'];

  let healthStatus = 'idle';
  let healthLabel = '⚪ Engine Health Unverified';
  let isOperatingProperly = false;
  let statusExplanation = 'This report does not contain sufficient structured evidence to establish engine health. Check current telemetry.';

  if (reportStatus === 'PENDING') {
    healthStatus = 'pending';
    healthLabel = '🔵 Generating Report…';
    statusExplanation = 'The audit is still being generated. Engine health has not been established by this report.';
  } else if (['FAILED', 'UNAVAILABLE', 'ERROR'].includes(reportStatus)) {
    healthStatus = 'degraded';
    healthLabel = '🟡 Report Unavailable';
    statusExplanation = 'Report generation failed or was unavailable. Review its diagnostics and current engine telemetry.';
  } else if (isCircuitPaused) {
    healthStatus = 'paused';
    healthLabel = '🟠 Entries Paused (Risk Circuit Active)';
    statusExplanation = 'The saved evidence records a risk pause on new entries. Check current controls before taking action.';
  } else if (failedCount > 0 || reportStatus === 'PARTIAL' || operationalFailure) {
    healthStatus = 'degraded';
    healthLabel = '🟡 Attention Needed';
    statusExplanation = 'The saved evidence records operational limitations or incomplete specialist assessments that require inspection.';
  } else if (evidence.enabled === false || workerStatus === 'STOPPED') {
    healthLabel = '⚪ Engine Stopped';
    statusExplanation = 'The engine was stopped at the time of this report.';
  } else if (reportStatus === 'SUCCESS' && workerStatus === 'RUNNING' &&
             moduleStates.length > 0 && moduleStates.every((status) => knownReadyStates.includes(status))) {
    healthStatus = 'healthy';
    healthLabel = isWarmingUp ? '🟢 Operating Properly (Collecting History)' :
      isMarketClosed ? '🟢 Operating Properly (Market Closed)' : '🟢 Operating Properly (Healthy)';
    isOperatingProperly = true;
    statusExplanation = 'At the report timestamp, structured worker and module evidence indicated the engine was operating properly. This does not validate strategy profitability or establish current health.';
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
    recommendations.push('Review the recorded pause reason and current risk controls before considering new entries.');
  }
  if (isMarketClosed) {
    recommendations.push('Regular market hours are closed. Prepare watchlists and verify capital allocation for the upcoming trading session.');
  }
  if (recommendations.length === 0) {
    recommendations.push('Compare this report’s timestamped evidence with current worker telemetry and review any recorded limitations.');
  }

  return {
    healthStatus,
    healthLabel,
    headline: audit.headline ? cleanHumanText(audit.headline) : (reportStatus === 'SUCCESS' ? 'Report Generation Complete' : 'Report Status: ' + (reportStatus || 'Unknown')),
    statusExplanation,
    isOperatingProperly,
    modules,
    recommendations,
  };
}
