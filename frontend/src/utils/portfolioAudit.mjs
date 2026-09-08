export function normalizePortfolioAudit(audit) {
  const warnings = (audit.validation_warnings || []).map(warning => `> **Report limitation:** ${warning}\n\n`).join('');
  return {
    ...audit,
    created_at: audit.timestamp || audit.created_at,
    content_markdown: warnings + ([audit.content, audit.content_markdown, audit.summary].find(value => typeof value === 'string' && value.trim()) ||
      (audit.status === 'PENDING' ? 'Audit queued. Waiting for the completed report.' : 'This archived report contains no text. Generate a fresh report to collect current evidence.')),
    evidence: audit.evidence || {},
  };
}

export function selectPortfolioAudit(audits, id) {
  return audits.find(audit => String(audit.id) === String(id)) || audits[0] || null;
}

export function auditOutcomeMessage(audit) {
  if (audit?.status === 'SUCCESS') return 'Portfolio AI audit completed.';
  if (audit?.status === 'PARTIAL') return 'Portfolio report completed with module limitations. Review the report and module errors.';
  if (audit?.status === 'PENDING') return 'Audit queued. This window updates automatically; you can close it and return later.';
  return audit?.content_markdown || 'The audit did not complete. Review its saved diagnostics.';
}

export function portfolioAuditProgress(audit) {
  if (audit?.progress) return audit.progress;
  // Read older/in-flight releases using their saved enabled-specialist evidence.
  const evidence = audit?.evidence || {};
  const modules = Object.keys(evidence.specialist_mandates || {});
  const failed = modules.filter(module => Object.hasOwn(evidence.module_audit_errors || {}, module));
  const completed = modules.filter(module => evidence.module_audits?.[module] || failed.includes(module));
  const finished = ['SUCCESS', 'PARTIAL'].includes(audit?.status);
  return {
    percent: finished ? 100 : modules.length ? Math.round(5 + 80 * completed.length / modules.length) : 0,
    stage: finished ? 'complete' : audit?.status && audit.status !== 'PENDING' ? 'failed' : !modules.length ? 'queued' : completed.length === modules.length ? 'master' : 'module',
    modules, completed_modules: completed, failed_modules: failed,
    current_module: modules.find(module => !completed.includes(module)),
  };
}
