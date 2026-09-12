import React from 'react';
import { createPortal } from 'react-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import PortfolioAuditProgress from './PortfolioAuditProgress';
import PortfolioGoalTracking from './PortfolioGoalTracking';
import PortfolioEventCalibration from './PortfolioEventCalibration';
import {
  buildExecutiveSummary,
  cleanHumanText,
  humanizeAuditSlug,
} from '../utils/portfolioAudit.mjs';

function formatEasternDateTime(timestamp) {
  if (!timestamp) return '—';
  try {
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return String(timestamp);
    return date.toLocaleString('en-US', {
      timeZone: 'America/New_York',
      month: 'numeric',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    }) + ' ET';
  } catch {
    return String(timestamp);
  }
}

const getHeadlineCalloutStyle = (status, isLight) => {
  const norm = String(status || '').toUpperCase();
  if (norm === 'ATTENTION_REQUIRED' || norm === 'WARN' || norm === 'WARNING') {
    return {
      bg: isLight ? '#fffbeb' : 'rgba(245, 158, 11, 0.1)',
      border: '1px solid rgba(245, 158, 11, 0.35)',
      color: isLight ? '#92400e' : '#fcd34d',
      icon: '⚠️',
    };
  }
  if (norm === 'DEGRADED') {
    return {
      bg: isLight ? '#fff7ed' : 'rgba(249, 115, 22, 0.1)',
      border: '1px solid rgba(249, 115, 22, 0.35)',
      color: isLight ? '#9a3412' : '#fdba74',
      icon: '⚡',
    };
  }
  if (norm === 'ERROR' || norm === 'CRITICAL' || norm === 'FAILED') {
    return {
      bg: isLight ? '#fef2f2' : 'rgba(239, 68, 68, 0.1)',
      border: '1px solid rgba(239, 68, 68, 0.35)',
      color: isLight ? '#991b1b' : '#fca5a5',
      icon: '🚨',
    };
  }
  return {
    bg: isLight ? '#f0fdf4' : 'rgba(34, 197, 94, 0.1)',
    border: '1px solid rgba(34, 197, 94, 0.35)',
    color: isLight ? '#166534' : '#86efac',
    icon: '✨',
  };
};

export default function PortfolioAuditModal({
  isOpen,
  onClose,
  report,
  history = [],
  onSelectReport,
  onGenerateNow,
  generating = false,
  pending = false,
  loading = false,
  error = '',
  onClearError,
  message = '',
  onClearMessage,
  isLightMode = false,
}) {
  if (!isOpen) return null;

  const executiveSummary = buildExecutiveSummary(report);
  const isBusy = generating || pending;

  const healthBadgeStyle = {
    healthy: {
      bg: isLightMode ? 'rgba(34, 197, 94, 0.12)' : 'rgba(34, 197, 94, 0.22)',
      border: '1px solid #22c55e',
      color: isLightMode ? '#15803d' : '#4ade80',
    },
    paused: {
      bg: isLightMode ? 'rgba(249, 115, 22, 0.12)' : 'rgba(249, 115, 22, 0.22)',
      border: '1px solid #f97316',
      color: isLightMode ? '#c2410c' : '#fb923c',
    },
    degraded: {
      bg: isLightMode ? 'rgba(234, 179, 8, 0.12)' : 'rgba(234, 179, 8, 0.22)',
      border: '1px solid #eab308',
      color: isLightMode ? '#a16207' : '#fde047',
    },
    pending: {
      bg: isLightMode ? 'rgba(56, 189, 248, 0.12)' : 'rgba(56, 189, 248, 0.22)',
      border: '1px solid #38bdf8',
      color: isLightMode ? '#0369a1' : '#7dd3fc',
    },
  }[executiveSummary.healthStatus] || {
    bg: 'rgba(148, 163, 184, 0.15)',
    border: '1px solid #94a3b8',
    color: isLightMode ? '#475569' : '#cbd5e1',
  };

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 10000,
        background: 'rgba(0,0,0,0.75)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 20,
      }}
    >
      <div
        style={{
          width: 'min(1060px, 96vw)',
          maxHeight: '90vh',
          overflow: 'hidden',
          borderRadius: 14,
          background: isLightMode ? '#fff' : '#0f172a',
          color: isLightMode ? '#1a202c' : '#e2e8f0',
          border: '1px solid #38bdf8',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)',
        }}
      >
        {/* Modal Header */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '16px 24px',
            borderBottom: '1px solid rgba(148,163,184,0.2)',
          }}
        >
          <div>
            <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 10, fontSize: '1.25rem' }}>
              <span>📊 Quantitative Portfolio AI Audit Report</span>
              {report?.status && (
                <span
                  style={{
                    fontSize: '0.75rem',
                    fontWeight: 700,
                    padding: '3px 10px',
                    borderRadius: 12,
                    background:
                      report.status === 'SUCCESS'
                        ? 'rgba(34, 197, 94, 0.18)'
                        : report.status === 'DEGRADED' || report.status === 'FAILED'
                        ? 'rgba(239, 68, 68, 0.18)'
                        : 'rgba(234, 179, 8, 0.18)',
                    border: `1px solid ${
                      report.status === 'SUCCESS'
                        ? '#22c55e'
                        : report.status === 'DEGRADED' || report.status === 'FAILED'
                        ? '#ef4444'
                        : '#eab308'
                    }`,
                    color:
                      report.status === 'SUCCESS'
                        ? '#4ade80'
                        : report.status === 'DEGRADED' || report.status === 'FAILED'
                        ? '#f87171'
                        : '#fde047',
                  }}
                >
                  {report.status === 'SUCCESS' ? 'REPORT COMPLETE' : report.status}
                </span>
              )}
            </h3>
            <div style={{ fontSize: '0.82rem', color: isLightMode ? '#64748b' : '#94a3b8', marginTop: 4 }}>
              Portfolio and enabled-module assessments. Automatic reports follow the master Off/Daily/Weekly schedule; manual reports remain available.
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close report"
            style={{
              background: 'none',
              border: 'none',
              color: isLightMode ? '#64748b' : '#94a3b8',
              fontSize: 20,
              cursor: 'pointer',
              padding: 4,
            }}
          >
            ✕
          </button>
        </div>

        {/* Sub-bar with Report Selector & Generate Now */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 12,
            padding: '12px 24px',
            background: isLightMode ? '#f8fafc' : 'rgba(255,255,255,0.02)',
            borderBottom: '1px solid rgba(148,163,184,0.15)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: isLightMode ? '#475569' : '#cbd5e1' }}>
              Report History:
            </span>
            {history.length > 0 ? (
              <select
                value={report?.id || ''}
                onChange={(e) => onSelectReport && onSelectReport(e.target.value)}
                style={{
                  padding: '5px 10px',
                  borderRadius: 6,
                  fontSize: '0.82rem',
                  background: isLightMode ? '#fff' : '#1e293b',
                  color: isLightMode ? '#1e293b' : '#f1f5f9',
                  border: '1px solid rgba(148,163,184,0.3)',
                }}
              >
                {history.map((rep) => (
                  <option key={rep.id} value={rep.id}>
                    {formatEasternDateTime(rep.created_at)} ({rep.status || 'Report'})
                  </option>
                ))}
              </select>
            ) : (
              <span style={{ fontSize: '0.82rem', color: isLightMode ? '#64748b' : '#94a3b8' }}>
                No saved reports yet
              </span>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <button
              type="button"
              className="settings-action-button"
              disabled={isBusy}
              onClick={onGenerateNow}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontSize: '0.85rem',
                padding: '6px 14px',
                cursor: isBusy ? 'not-allowed' : 'pointer',
                opacity: isBusy ? 0.7 : 1,
              }}
            >
              {isBusy ? '⚡ Analyzing worker & logs…' : '⚡ Generate Fresh Report Now'}
            </button>
          </div>
        </div>

        {/* Modal Alerts & Progress Banner */}
        {(generating || pending || report?.progress) && (
          <PortfolioAuditProgress
            audit={history.find((rep) => rep.status === 'PENDING') || (generating ? null : report)}
            isLightMode={isLightMode}
          />
        )}
        {error && (
          <div
            style={{
              margin: '12px 24px 0',
              padding: '10px 14px',
              borderRadius: 8,
              background: 'rgba(239, 68, 68, 0.15)',
              border: '1px solid #ef4444',
              color: isLightMode ? '#dc2626' : '#f87171',
              fontSize: '0.88rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 8,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>⚠️</span>
              <span>{error}</span>
            </div>
            {onClearError && (
              <button
                type="button"
                onClick={onClearError}
                style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: '1rem', padding: '0 4px' }}
              >
                ✕
              </button>
            )}
          </div>
        )}
        {message && (
          <div
            style={{
              margin: '12px 24px 0',
              padding: '10px 14px',
              borderRadius: 8,
              background: 'rgba(34, 197, 94, 0.15)',
              border: '1px solid #22c55e',
              color: isLightMode ? '#16a34a' : '#4ade80',
              fontSize: '0.88rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 8,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>✓</span>
              <span>{message}</span>
            </div>
            {onClearMessage && (
              <button
                type="button"
                onClick={onClearMessage}
                style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: '1rem', padding: '0 4px' }}
              >
                ✕
              </button>
            )}
          </div>
        )}

        {/* Scrollable Report Body */}
        <div style={{ overflow: 'auto', padding: '20px 24px', flex: 1 }}>
          {loading ? (
            <div style={{ padding: '40px 0', textAlign: 'center', color: isLightMode ? '#64748b' : '#94a3b8' }}>
              Loading strategy engine report…
            </div>
          ) : !report ? (
            <div style={{ padding: '40px 0', textAlign: 'center' }}>
              <p style={{ fontSize: '1.05rem', color: isLightMode ? '#475569' : '#cbd5e1' }}>
                No audit report has been generated yet.
              </p>
              <p
                style={{
                  fontSize: '0.88rem',
                  color: isLightMode ? '#64748b' : '#94a3b8',
                  maxWidth: 500,
                  margin: '0 auto 20px',
                }}
              >
                Reports evaluate current engine operational health, module conditions, and risk settings. Click below to generate the initial report.
              </p>
              <button
                type="button"
                className="settings-save-button"
                disabled={isBusy}
                onClick={onGenerateNow}
                style={{ cursor: isBusy ? 'not-allowed' : 'pointer', opacity: isBusy ? 0.7 : 1 }}
              >
                {isBusy ? '⚡ Analyzing worker & logs…' : '⚡ Generate Initial Report Now'}
              </button>
            </div>
          ) : (
            <div>
              {/* Top metrics ribbon */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
                  gap: 12,
                  marginBottom: 16,
                }}
              >
                <div
                  style={{
                    padding: '10px 14px',
                    borderRadius: 8,
                    background: isLightMode ? '#f1f5f9' : 'rgba(255,255,255,0.04)',
                    border: '1px solid rgba(148,163,184,0.18)',
                  }}
                >
                  <div style={{ fontSize: 11, color: isLightMode ? '#64748b' : '#94a3b8' }}>Report Created</div>
                  <div style={{ fontWeight: 600, fontSize: '0.88rem', marginTop: 3 }}>
                    {formatEasternDateTime(report.created_at)}
                  </div>
                </div>
                <div
                  style={{
                    padding: '10px 14px',
                    borderRadius: 8,
                    background: isLightMode ? '#f1f5f9' : 'rgba(255,255,255,0.04)',
                    border: '1px solid rgba(148,163,184,0.18)',
                  }}
                >
                  <div style={{ fontSize: 11, color: isLightMode ? '#64748b' : '#94a3b8' }}>Paper Run</div>
                  <div style={{ fontWeight: 600, fontSize: '0.88rem', marginTop: 3 }}>
                    {report.generation == null ? '—' : `#${report.generation}`}
                  </div>
                </div>
                <div
                  style={{
                    padding: '10px 14px',
                    borderRadius: 8,
                    background: isLightMode ? '#f1f5f9' : 'rgba(255,255,255,0.04)',
                    border: '1px solid rgba(148,163,184,0.18)',
                  }}
                >
                  <div style={{ fontSize: 11, color: isLightMode ? '#64748b' : '#94a3b8' }}>Paper Equity</div>
                  <div style={{ fontWeight: 600, fontSize: '0.88rem', marginTop: 3 }}>
                    {report.evidence?.account?.total_equity == null
                      ? '—'
                      : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(
                          report.evidence.account.total_equity,
                        )}
                  </div>
                </div>
                <div
                  style={{
                    padding: '10px 14px',
                    borderRadius: 8,
                    background: isLightMode ? '#f1f5f9' : 'rgba(255,255,255,0.04)',
                    border: '1px solid rgba(148,163,184,0.18)',
                  }}
                >
                  <div style={{ fontSize: 11, color: isLightMode ? '#64748b' : '#94a3b8' }}>Open Positions</div>
                  <div style={{ fontWeight: 600, fontSize: '0.88rem', marginTop: 3 }}>
                    {report.evidence?.open_positions_count ?? '—'}
                  </div>
                </div>
                <div
                  style={{
                    padding: '10px 14px',
                    borderRadius: 8,
                    background: isLightMode ? '#f1f5f9' : 'rgba(255,255,255,0.04)',
                    border: '1px solid rgba(148,163,184,0.18)',
                  }}
                >
                  <div style={{ fontSize: 11, color: isLightMode ? '#64748b' : '#94a3b8' }}>Auditor Model</div>
                  <div style={{ fontWeight: 600, fontSize: '0.88rem', marginTop: 3 }}>
                    {report.model || report.provider || (report.status === 'PENDING' ? 'Awaiting master report' : 'Unavailable')}
                  </div>
                </div>
              </div>

              {/* EXECUTIVE SUMMARY BOX - Placed directly below the top metrics ribbon */}
              <div
                style={{
                  padding: '18px 20px',
                  borderRadius: 10,
                  marginBottom: 20,
                  background: isLightMode ? '#f8fafc' : 'rgba(30, 41, 59, 0.7)',
                  border: isLightMode ? '1px solid #cbd5e1' : '1px solid rgba(56, 189, 248, 0.35)',
                  boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 14 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: '1.25rem' }}>📋</span>
                    <h4 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 700 }}>
                      Executive Summary & Engine Operational Health
                    </h4>
                  </div>
                  <span
                    style={{
                      fontSize: '0.82rem',
                      fontWeight: 700,
                      padding: '4px 12px',
                      borderRadius: 14,
                      background: healthBadgeStyle.bg,
                      border: healthBadgeStyle.border,
                      color: healthBadgeStyle.color,
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 6,
                    }}
                  >
                    {executiveSummary.healthLabel}
                  </span>
                </div>

                {/* Plain English Status Explanation */}
                <div
                  style={{
                    padding: '12px 14px',
                    borderRadius: 8,
                    marginBottom: 14,
                    background: isLightMode ? '#fff' : 'rgba(15, 23, 42, 0.6)',
                    border: isLightMode ? '1px solid #e2e8f0' : '1px solid rgba(148, 163, 184, 0.2)',
                  }}
                >
                  <div style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700, color: isLightMode ? '#64748b' : '#94a3b8', marginBottom: 4 }}>
                    What the Strategy Engine is Doing Right Now:
                  </div>
                  <div style={{ fontSize: '0.92rem', lineHeight: 1.5, color: isLightMode ? '#1e293b' : '#f1f5f9' }}>
                    {executiveSummary.statusExplanation}
                  </div>
                </div>

                {/* Specialist Modules Grid */}
                {executiveSummary.modules.length > 0 && (
                  <div style={{ marginBottom: 14 }}>
                    <div style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700, color: isLightMode ? '#64748b' : '#94a3b8', marginBottom: 8 }}>
                      Strategy Specialist Modules:
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8 }}>
                      {executiveSummary.modules.map((mod) => (
                        <div
                          key={mod.name}
                          style={{
                            padding: '10px 12px',
                            borderRadius: 6,
                            background: isLightMode ? '#fff' : 'rgba(15, 23, 42, 0.45)',
                            border: isLightMode ? '1px solid #e2e8f0' : '1px solid rgba(148, 163, 184, 0.15)',
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                            <strong style={{ fontSize: '0.84rem' }}>{mod.label}</strong>
                            <span
                              style={{
                                fontSize: '0.7rem',
                                fontWeight: 700,
                                padding: '2px 6px',
                                borderRadius: 4,
                                background: mod.status === 'error' ? 'rgba(239, 68, 68, 0.2)' : 'rgba(34, 197, 94, 0.15)',
                                color: mod.status === 'error' ? '#f87171' : '#4ade80',
                              }}
                            >
                              {mod.status === 'error' ? 'ISSUE' : 'OK'}
                            </span>
                          </div>
                          <div style={{ fontSize: '0.8rem', color: isLightMode ? '#475569' : '#cbd5e1' }}>
                            {mod.humanStatus}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Actionable Recommendations to Improve or Repair */}
                {executiveSummary.recommendations.length > 0 && (
                  <div
                    style={{
                      padding: '12px 14px',
                      borderRadius: 8,
                      background: isLightMode ? '#eff6ff' : 'rgba(56, 189, 248, 0.08)',
                      border: isLightMode ? '1px solid #bfdbfe' : '1px solid rgba(56, 189, 248, 0.25)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.82rem', fontWeight: 700, color: isLightMode ? '#1d4ed8' : '#38bdf8', marginBottom: 6 }}>
                      <span>💡</span>
                      <span>Actionable Recommendations to Improve or Repair the Engine:</span>
                    </div>
                    <ul style={{ margin: 0, paddingLeft: 20, fontSize: '0.86rem', lineHeight: 1.5, color: isLightMode ? '#1e293b' : '#e2e8f0' }}>
                      {executiveSummary.recommendations.map((rec, index) => (
                        <li key={index} style={{ marginBottom: 4 }}>
                          {rec}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {/* Goal Tracking & Calibration */}
              <PortfolioGoalTracking goal={report.evidence?.goal_tracking} />
              <PortfolioEventCalibration calibration={report.evidence?.event_calibration} />

              {/* Headline Callout with dynamic alert coloring */}
              {report.headline && (() => {
                const style = getHeadlineCalloutStyle(report.status, isLightMode);
                return (
                  <div
                    style={{
                      padding: '12px 16px',
                      borderRadius: 8,
                      marginBottom: 20,
                      background: style.bg,
                      border: style.border,
                      fontWeight: 600,
                      fontSize: '0.95rem',
                      color: style.color,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                    }}
                  >
                    <span>{style.icon}</span>
                    <span>{cleanHumanText(report.headline)}</span>
                  </div>
                );
              })()}

              {report.evidence?.pause_reason && (
                <p role="status">
                  <strong>Paper execution paused:</strong> {cleanHumanText(report.evidence.pause_reason)}
                </p>
              )}

              {/* Detailed Markdown Report Content */}
              <div className="event-strategy-report-markdown" style={{ lineHeight: 1.65, fontSize: '0.92rem' }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {cleanHumanText(report.content_markdown)}
                </ReactMarkdown>
              </div>

              {/* Collapsible Module Details */}
              {Object.entries(report.evidence?.module_audits || {}).map(([module, content]) => (
                <details key={module} style={{ marginTop: 16 }}>
                  <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
                    {module.toUpperCase()} specialist assessment
                    {report.evidence?.module_audit_errors?.[module] ? ' — unavailable' : ''}
                  </summary>
                  <div style={{ marginTop: 8, paddingLeft: 12 }}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {cleanHumanText(content || report.evidence?.module_audit_errors?.[module] || 'No module assessment was returned.')}
                    </ReactMarkdown>
                  </div>
                </details>
              ))}

              {Object.keys(report.evidence || {}).length > 0 && (
                <details style={{ marginTop: 16 }}>
                  <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Saved portfolio evidence (Technical Diagnostics)</summary>
                  <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: '0.8rem', background: isLightMode ? '#f1f5f9' : 'rgba(0,0,0,0.3)', padding: 12, borderRadius: 6 }}>
                    {JSON.stringify(report.evidence, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
