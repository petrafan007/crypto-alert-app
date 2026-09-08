import React, { useEffect, useState } from 'react';
import { portfolioAuditProgress } from '../utils/portfolioAudit.mjs';

const names = { equities: 'Equities', crypto: 'Crypto', options: 'Options', events: 'Event contracts', futures: 'Futures' };
const duration = seconds => `${Math.floor(Math.max(0, seconds) / 60)}m ${Math.floor(Math.max(0, seconds) % 60)}s`;

export default function PortfolioAuditProgress({ audit, isLightMode }) {
  const [now, setNow] = useState(Date.now());
  const pending = !audit || audit.status === 'PENDING';
  useEffect(() => {
    if (!pending) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [pending]);
  const progress = portfolioAuditProgress(audit);
  const completed = progress.completed_modules || [];
  const modules = progress.modules || [];
  const failed = progress.failed_modules || [];
  const percent = Math.max(0, Math.min(pending ? 99 : 100, Number(progress.percent) || 0));
  const stages = { queued: 'Waiting to start', preparing: 'Collecting portfolio evidence', module: `${names[progress.current_module] || 'Specialist'} assessment`, master: 'Master CIO synthesis', finalizing: 'Validating and saving the report', complete: failed.length ? 'Report finished with module limitations' : 'Report complete', failed: 'Report stopped — see diagnostics' };
  const stage = stages[progress.stage] || 'Preparing audit';
  const start = Date.parse(audit?.created_at || audit?.timestamp);
  const elapsed = pending && Number.isFinite(start) ? (now - start) / 1000 : progress.elapsed_seconds;
  const retryTime = Date.parse(progress.retry_at);
  const retrySeconds = Number.isFinite(retryTime) ? Math.max(0, Math.ceil((retryTime - now) / 1000)) : 0;
  const attemptEvents = (audit?.evidence?.provider_attempts || []).filter(entry => ['failed', 'retrying'].includes(entry.event));
  const warning = failed.length > 0 || progress.stage === 'failed';
  const color = warning ? (isLightMode ? '#92400e' : '#fbbf24') : (isLightMode ? '#0369a1' : '#7dd3fc');
  return <section aria-label="AI audit progress" style={{ margin: '12px 24px 0', padding: '12px 16px', borderRadius: 8, border: `1px solid ${warning ? '#f59e0b' : '#38bdf8'}`, color, background: isLightMode ? '#f0f9ff' : 'rgba(56,189,248,0.09)', flexShrink: 0 }}>
    <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 8, fontWeight: 600 }}>
      <span>{pending ? 'Live audit' : 'Audit'}{audit?.id ? ` #${audit.id}` : ''}: {stage}</span>
      <span>{pending ? 'Approximately ' : ''}{percent}%</span>
    </div>
    <div role="progressbar" aria-label="Approximate audit completion" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-valuetext={`${percent}% — ${stage}`} style={{ height: 10, borderRadius: 10, background: isLightMode ? '#cbd5e1' : '#334155', margin: '10px 0', overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${percent}%`, background: warning ? '#f59e0b' : '#0ea5e9', transition: 'width 0.4s ease' }} />
    </div>
    <div style={{ fontSize: 13, display: 'flex', flexWrap: 'wrap', gap: '4px 16px' }}>
      <span>{completed.length} / {modules.length || '—'} enabled specialists finished{failed.length ? ` (${failed.length} unavailable)` : ''}</span>
      {elapsed != null && <span>Elapsed: {duration(elapsed)}</span>}
      {progress.model && <span>{progress.tier}: {progress.provider} / {progress.model}</span>}
    </div>
    <p role="status" style={{ fontSize: 12, margin: '6px 0 0' }}>
      {progress.event === 'retrying' ? `Retrying this provider${retrySeconds ? ` in ${retrySeconds}s` : ' shortly'}. ` : progress.event === 'queued' ? 'Waiting for the provider request slot. ' : progress.event === 'spacing' ? `Pacing the next prompt${retrySeconds ? ` (${retrySeconds}s)` : ''}. ` : ''}
      {pending ? 'Percentage reflects completed stages; generation time and retries vary. The master report follows all enabled specialists.' : 'Saved progress stays with this report.'}
    </p>
    {attemptEvents.length > 0 && <details style={{ marginTop: 8, fontSize: 12 }}>
      <summary>Provider retries and fallback reasons ({attemptEvents.length})</summary>
      <div style={{ maxHeight: 140, overflow: 'auto', overflowWrap: 'anywhere' }}>
        {attemptEvents.map((entry, index) => <p key={index} style={{ margin: '8px 0' }}>{entry.module ? names[entry.module] || entry.module : 'Master'} · {entry.tier} · {entry.model} · {entry.event}: {entry.error}</p>)}
      </div>
    </details>}
  </section>;
}
