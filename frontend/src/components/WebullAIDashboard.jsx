import React, { useState, useEffect, useMemo } from 'react';
import axios from 'axios';
import { useAuth } from './AuthContext';
import SentimentTimelineChart from './SentimentTimelineChart';
import { DEFAULT_SENTIMENT_CHART_RANGE, getChartRange } from '../utils/chartRanges';
import { formatEasternDateTime } from '../utils/dateTime';
import '../pages/AIDashboard.css';

const formatEasternTime = (isoString) => {
  return isoString ? formatEasternDateTime(isoString) : 'Not available';
};

const getProviderName = (provider) => {
  switch ((provider || '').toLowerCase()) {
    case 'openai': return 'OpenAI';
    case 'gemini': return 'Google Gemini';
    case 'zai': return 'Z.AI';
    case 'perplexity': return 'Perplexity';
    case 'inception': return 'Inception Labs';
    default: return provider || 'AI';
  }
};

const getTierName = (tier) => {
  if (!tier) return 'Primary';
  return tier.charAt(0).toUpperCase() + tier.slice(1).toLowerCase();
};

const escapeHtml = (str) =>
  String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

const formatInlineMarkdown = (text) => {
  let formatted = escapeHtml(text);
  formatted = formatted.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  formatted = formatted.replace(/\*(.+?)\*/g, '<em>$1</em>');
  formatted = formatted.replace(/`(.+?)`/g, '<code>$1</code>');
  formatted = formatted.replace(/\[(.+?)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  formatted = formatted.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
  return formatted;
};

const renderMarkdown = (markdown) => {
  if (!markdown) return '';
  const lines = markdown.split(/\r?\n/);
  const html = [];
  let inUl = false;
  let inOl = false;
  let inBlockquote = false;

  const closeLists = () => {
    if (inUl) { html.push('</ul>'); inUl = false; }
    if (inOl) { html.push('</ol>'); inOl = false; }
  };
  const closeBlockquote = () => {
    if (inBlockquote) { html.push('</blockquote>'); inBlockquote = false; }
  };

  lines.forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) {
      closeLists();
      closeBlockquote();
      return;
    }
    const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      closeLists();
      closeBlockquote();
      const level = headingMatch[1].length;
      html.push(`<h${level}>${formatInlineMarkdown(headingMatch[2])}</h${level}>`);
      return;
    }
    const ulMatch = trimmed.match(/^[-*+]\s+(.*)$/);
    if (ulMatch) {
      closeBlockquote();
      if (inOl) { html.push('</ol>'); inOl = false; }
      if (!inUl) { html.push('<ul>'); inUl = true; }
      html.push(`<li>${formatInlineMarkdown(ulMatch[1])}</li>`);
      return;
    }
    const olMatch = trimmed.match(/^\d+\.\s+(.*)$/);
    if (olMatch) {
      closeBlockquote();
      if (inUl) { html.push('</ul>'); inUl = false; }
      if (!inOl) { html.push('<ol>'); inOl = false; }
      html.push(`<li>${formatInlineMarkdown(olMatch[1])}</li>`);
      return;
    }
    const bqMatch = trimmed.match(/^>\s*(.*)$/);
    if (bqMatch) {
      closeLists();
      if (!inBlockquote) { html.push('<blockquote>'); inBlockquote = true; }
      html.push(`<p>${formatInlineMarkdown(bqMatch[1])}</p>`);
      return;
    }
    closeLists();
    closeBlockquote();
    html.push(`<p>${formatInlineMarkdown(trimmed)}</p>`);
  });

  closeLists();
  closeBlockquote();
  return html.join('');
};

const hasRate = (val) => val !== null && val !== undefined && val !== '' && Number.isFinite(Number(val));
const formatRate = (val) => (hasRate(val) ? `${Number(val).toFixed(1)}%` : '—');

export default function WebullAIDashboard({ isLightMode = false }) {
  const { user, authLoading } = useAuth();

  // Accuracy state
  const [accuracyData, setAccuracyData] = useState(null);
  const [accuracyLoading, setAccuracyLoading] = useState(false);
  const [dateRange, setDateRange] = useState(DEFAULT_SENTIMENT_CHART_RANGE);
  const [chartRange, setChartRange] = useState(DEFAULT_SENTIMENT_CHART_RANGE);

  // Asset filtering
  const [selectedLedgerCoin, setSelectedLedgerCoin] = useState('all');
  const [showCoinFilterModal, setShowCoinFilterModal] = useState(false);
  const [activeLedgerCoins, setActiveLedgerCoins] = useState(() => {
    try {
      const saved = localStorage.getItem('webull_dashboard_active_ledger_coins');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) return parsed;
      }
    } catch (e) {}
    return [];
  });
  const [tempFilterCoins, setTempFilterCoins] = useState([]);

  // Thesis detail modal
  const [selectedThesisModal, setSelectedThesisModal] = useState(null);

  // Ledger sorting & pagination
  const [ledgerSortConfig, setLedgerSortConfig] = useState(null);
  const [ledgerPage, setLedgerPage] = useState(1);
  const [ledgerPageSize, setLedgerPageSize] = useState(20);

  const fetchAccuracyData = async (tf = dateRange) => {
    setAccuracyLoading(true);
    try {
      const res = await axios.get('/api/webull/ai-accuracy', {
        params: { timeframe: tf },
        withCredentials: true
      });
      if (res.data && res.data.success) {
        setAccuracyData(res.data);
      }
    } catch (err) {
      console.error('Error fetching Webull sentiment accuracy data:', err);
    } finally {
      setAccuracyLoading(false);
    }
  };

  useEffect(() => {
    if (!authLoading && user) {
      fetchAccuracyData(dateRange);
    }
  }, [authLoading, user]);

  const requestLedgerSort = (key) => {
    let direction = 'desc';
    if (ledgerSortConfig && ledgerSortConfig.key === key && ledgerSortConfig.direction === 'desc') {
      direction = 'asc';
    }
    setLedgerSortConfig({ key, direction });
    setLedgerPage(1);
  };

  const getSortIcon = (key) => {
    if (!ledgerSortConfig || ledgerSortConfig.key !== key) return '';
    return ledgerSortConfig.direction === 'asc' ? ' ▲' : ' ▼';
  };

  const summary = accuracyData?.summary || {};
  const recommendationBreakdown = accuracyData?.recommendation_breakdown || [];
  const modelBreakdown = accuracyData?.model_breakdown || [];
  const availableSymbols = accuracyData?.available_symbols || [];

  // Filtered and sorted history
  const filteredHistory = useMemo(() => {
    let list = accuracyData?.history || [];
    if (selectedLedgerCoin !== 'all') {
      list = list.filter(row => row.symbol === selectedLedgerCoin);
    }
    if (activeLedgerCoins.length > 0) {
      list = list.filter(row => activeLedgerCoins.includes(row.symbol));
    }

    if (ledgerSortConfig && list.length > 0) {
      list = [...list].sort((a, b) => {
        let valA = a[ledgerSortConfig.key];
        let valB = b[ledgerSortConfig.key];

        if (['price_at_prediction', 'evaluation_price', 'forecast_horizon_hours', 'outcome_pct'].includes(ledgerSortConfig.key)) {
          valA = parseFloat(valA || 0);
          valB = parseFloat(valB || 0);
        } else if (['created_at', 'evaluated_at'].includes(ledgerSortConfig.key)) {
          valA = new Date(valA || 0).getTime();
          valB = new Date(valB || 0).getTime();
        } else {
          valA = String(valA || '').toLowerCase();
          valB = String(valB || '').toLowerCase();
        }

        if (valA < valB) return ledgerSortConfig.direction === 'asc' ? -1 : 1;
        if (valA > valB) return ledgerSortConfig.direction === 'asc' ? 1 : -1;
        return 0;
      });
    } else if (list.length > 0) {
      list = [...list].sort((a, b) => {
        const timeA = new Date(a.evaluated_at || a.created_at || 0).getTime();
        const timeB = new Date(b.evaluated_at || b.created_at || 0).getTime();
        return timeB - timeA;
      });
    }
    return list;
  }, [accuracyData?.history, selectedLedgerCoin, activeLedgerCoins, ledgerSortConfig]);

  const paginatedRows = useMemo(() => {
    const start = (ledgerPage - 1) * ledgerPageSize;
    return filteredHistory.slice(start, start + ledgerPageSize);
  }, [filteredHistory, ledgerPage, ledgerPageSize]);

  const totalPages = Math.ceil(filteredHistory.length / ledgerPageSize) || 1;

  return (
    <div className="ai-dashboard" style={{ padding: '16px 0', minHeight: 'auto', background: 'transparent' }}>
      {/* Header */}
      <div className="ai-header">
        <div>
          <h1>🤖 Webull AI Sentiment Prediction & Thesis Engine</h1>
          <p style={{ margin: '4px 0 0', color: 'var(--text-secondary, #94a3b8)', fontSize: '14px' }}>
            Empirical accuracy tracking and multi-model thesis validation across Webull portfolio holdings & watchlist
          </p>
        </div>
        <div className="ai-header-controls">
          <button
            onClick={() => {
              setTempFilterCoins(activeLedgerCoins.length > 0 ? [...activeLedgerCoins] : [...availableSymbols]);
              setShowCoinFilterModal(true);
            }}
            className="btn btn-secondary configure-coins-btn"
            style={{ fontSize: '13px', padding: '8px 14px', marginRight: '8px' }}
          >
            ⚙️ Configure Assets {activeLedgerCoins.length > 0 ? `(${activeLedgerCoins.length}/${availableSymbols.length})` : ''}
          </button>
          <button
            onClick={() => fetchAccuracyData(dateRange)}
            disabled={accuracyLoading}
            className="btn btn-secondary"
            style={{ fontSize: '13px', padding: '8px 14px' }}
          >
            {accuracyLoading ? '⏳ Refreshing...' : '🔄 Refresh Accuracy'}
          </button>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 1. VISUALIZER 1: PERFORMANCE KPIS & SENTIMENT TIMELINE CHART */}
      {/* ========================================================================= */}
      <div className="ai-section prediction-visualizer-section">
        {/* KPI Scorecards */}
        <div className="accuracy-kpi-grid">
          <div className="accuracy-kpi-card overall">
            <span className="kpi-label">Overall Accuracy</span>
            <div className="kpi-value glow-text">
              {formatRate(summary.overall_accuracy)}
            </div>
            <span className="kpi-subtext">
              {summary.correct_count ?? 0} Correct / {summary.evaluated_signals ?? 0} Evaluated Calls
            </span>
          </div>

          <div className="accuracy-kpi-card bullish">
            <span className="kpi-label">Bullish Win Rate</span>
            <div className="kpi-value text-green">
              {formatRate(summary.bullish_win_rate)}
            </div>
            <span className="kpi-subtext">
              {summary.bullish_correct_count ?? 0} Correct / {summary.bullish_count ?? 0} Decisive
            </span>
          </div>

          <div className="accuracy-kpi-card bearish">
            <span className="kpi-label">Bearish Win Rate</span>
            <div className="kpi-value text-red">
              {formatRate(summary.bearish_win_rate)}
            </div>
            <span className="kpi-subtext">
              {summary.bearish_correct_count ?? 0} Correct / {summary.bearish_count ?? 0} Decisive
            </span>
          </div>

          <div className="accuracy-kpi-card model">
            <span className="kpi-label">Top Performing Model</span>
            <div className="kpi-value" style={{ fontSize: '18px', color: '#c084fc', marginTop: '6px' }}>
              {summary.top_model || 'Not enough validated data'}
            </div>
            <span className="kpi-subtext">
              {summary.total_signals ?? 0} Total Stored Forecasts ({summary.tracking_count ?? 0} tracking)
            </span>
          </div>
        </div>

        {/* Sentiment Timeline Chart */}
        <SentimentTimelineChart
          signals={accuracyData?.history || []}
          range={chartRange}
          onRangeChange={setChartRange}
          availableSymbols={availableSymbols}
          isLightMode={isLightMode}
        />
      </div>

      {/* ========================================================================= */}
      {/* 2. VISUALIZER 2: HISTORICAL PREDICTION LEDGER & BENCHMARKS */}
      {/* ========================================================================= */}
      <div className="ai-section prediction-ledger-section">
        <div className="prediction-ledger-full-width">
          {/* Historical Prediction Ledger Table Card */}
          <div className="prediction-table-card">
            <div className="table-header-row">
              <h3>📋 Webull Historical Prediction Ledger</h3>
              <div className="ledger-pagination-controls" aria-label="Webull Historical Prediction Ledger pagination">
                <label>
                  Rows
                  <select
                    value={ledgerPageSize}
                    onChange={(event) => {
                      setLedgerPageSize(Number(event.target.value));
                      setLedgerPage(1);
                    }}
                  >
                    {[20, 50, 100, 200].map((size) => (
                      <option key={size} value={size}>
                        {size}
                      </option>
                    ))}
                  </select>
                </label>
                <span>
                  {filteredHistory.length
                    ? `${(ledgerPage - 1) * ledgerPageSize + 1}–${Math.min(ledgerPage * ledgerPageSize, filteredHistory.length)} of ${filteredHistory.length}`
                    : '0 records'}
                </span>
                <button
                  type="button"
                  onClick={() => setLedgerPage((page) => Math.max(1, page - 1))}
                  disabled={ledgerPage <= 1}
                >
                  ‹
                </button>
                <span>
                  Page {ledgerPage} / {totalPages}
                </span>
                <button
                  type="button"
                  onClick={() => setLedgerPage((page) => Math.min(totalPages, page + 1))}
                  disabled={ledgerPage >= totalPages}
                >
                  ›
                </button>
              </div>
            </div>

            <div className="prediction-table-container">
              <table className="prediction-ledger-table">
                <thead>
                  <tr>
                    <th onClick={() => requestLedgerSort('symbol')} style={{ cursor: 'pointer' }}>
                      Asset {getSortIcon('symbol')}
                    </th>
                    <th onClick={() => requestLedgerSort('price_at_prediction')} style={{ cursor: 'pointer' }}>
                      Signal Price {getSortIcon('price_at_prediction')}
                    </th>
                    <th onClick={() => requestLedgerSort('created_at')} style={{ cursor: 'pointer' }}>
                      Signal Date {getSortIcon('created_at')}
                    </th>
                    <th>Horizon</th>
                    <th onClick={() => requestLedgerSort('evaluation_price')} style={{ cursor: 'pointer' }}>
                      Eval Price {getSortIcon('evaluation_price')}
                    </th>
                    <th onClick={() => requestLedgerSort('evaluated_at')} style={{ cursor: 'pointer' }}>
                      Eval Date {getSortIcon('evaluated_at')}
                    </th>
                    <th onClick={() => requestLedgerSort('sentiment')} style={{ cursor: 'pointer' }}>
                      AI Recommendation {getSortIcon('sentiment')}
                    </th>
                    <th onClick={() => requestLedgerSort('outcome_status')} style={{ cursor: 'pointer' }}>
                      Outcome {getSortIcon('outcome_status')}
                    </th>
                    <th style={{ textAlign: 'center' }}>Thesis</th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedRows.length === 0 ? (
                    <tr>
                      <td colSpan="9" style={{ textAlign: 'center', padding: '36px', color: 'var(--text-secondary)' }}>
                        {accuracyData?.history?.length > 0
                          ? 'No Webull sentiment predictions match the selected filters.'
                          : 'No Webull sentiment predictions recorded yet. Signals are created automatically based on your sentiment schedule.'}
                      </td>
                    </tr>
                  ) : (
                    paginatedRows.map((row) => {
                      const isBullish = ['buy immediately', 'consider buying', 'buy', 'strong buy'].includes((row.sentiment || '').toLowerCase());
                      const isBearish = ['sell immediately', 'consider selling', 'sell', 'strong sell'].includes((row.sentiment || '').toLowerCase());
                      const signalBadgeClass = isBullish ? 'badge-buy' : isBearish ? 'badge-sell' : 'badge-watch';

                      const rawDelta = row.outcome_pct ?? row.price_delta_pct;
                      const deltaFormatted = rawDelta !== undefined && rawDelta !== null
                        ? `${rawDelta >= 0 ? '+' : ''}${parseFloat(rawDelta).toFixed(2)}%`
                        : '0.00%';

                      return (
                        <tr key={row.id}>
                          <td className="symbol-cell">
                            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                              <span className="coin-pill">{row.symbol}</span>
                              <span
                                className="source-badge source-p"
                                style={{ fontSize: '10px', background: '#38bdf8', color: '#000', fontWeight: 'bold' }}
                              >
                                {row.instrument_type || 'EQUITY'}
                              </span>
                            </div>
                          </td>
                          <td className="price-cell">
                            ${parseFloat(row.price_at_prediction || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                          </td>
                          <td className="date-cell">{row.date || '—'} {row.time || ''}</td>
                          <td>{row.forecast_horizon_hours ? `${row.forecast_horizon_hours}h` : '24h'}</td>
                          <td className="price-cell">
                            {row.evaluation_price !== null && row.evaluation_price !== undefined
                              ? `$${parseFloat(row.evaluation_price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`
                              : '—'}
                          </td>
                          <td className="date-cell">{row.eval_date ? `${row.eval_date} ${row.eval_time || ''}` : 'Tracking'}</td>
                          <td>
                            <span className={`signal-pill ${signalBadgeClass}`}>
                              {row.sentiment || '—'}
                            </span>
                          </td>
                          <td>
                            {row.outcome_status === 'correct' ? (
                              <span className="outcome-pill outcome-correct" title={row.outcome_reason || ''}>
                                ✅ Correct ({deltaFormatted})
                              </span>
                            ) : row.outcome_status === 'wrong' ? (
                              <span className="outcome-pill outcome-wrong" title={row.outcome_reason || ''}>
                                ❌ Wrong ({deltaFormatted})
                              </span>
                            ) : row.outcome_status === 'neutral' ? (
                              <span className="outcome-pill outcome-neutral" style={{ background: 'rgba(100, 116, 139, 0.15)', color: 'var(--text-secondary)' }} title={row.outcome_reason || ''}>
                                ⚖️ Neutral ({deltaFormatted})
                              </span>
                            ) : (
                              <span className="outcome-pill outcome-neutral" style={{ color: '#38bdf8' }} title={row.outcome_reason || 'Waiting for evaluation horizon'}>
                                ⏳ Tracking
                              </span>
                            )}
                          </td>
                          <td style={{ textAlign: 'center' }}>
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              style={{ padding: '2px 8px', fontSize: '12px' }}
                              onClick={() => setSelectedThesisModal(row)}
                            >
                              Thesis
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Benchmarks Split Grid: Recommendation Accuracy & Model Leaderboard */}
        <div className="benchmark-split-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginTop: 24 }}>
          {/* Recommendation Breakdown */}
          <div className="benchmark-card">
            <h3>🎯 Recommendation Type Accuracy</h3>
            <p className="benchmark-subtext">Empirical win rate across Webull signals</p>

            <div className="distribution-bars">
              {recommendationBreakdown.length > 0 ? (
                recommendationBreakdown.map((rec, idx) => {
                  const isBullish = ['Definitely Buy', 'Consider Buying', 'Buy Immediately', 'Strong Buy', 'Buy'].includes(rec.sentiment);
                  const isBearish = ['Consider Selling', 'Sell Immediately', 'Avoid', 'Strong Sell', 'Do Not Buy', 'Sell'].includes(rec.sentiment);
                  const barCol = isBullish ? '#00e676' : isBearish ? '#f56565' : '#38bdf8';

                  return (
                    <div key={idx} className="dist-item">
                      <div className="dist-header">
                        <span>{rec.sentiment} ({rec.total} calls)</span>
                        <strong>{formatRate(rec.win_rate)} Win Rate</strong>
                      </div>
                      <div className="progress-bar-track">
                        <div className="progress-bar-fill" style={{ width: `${hasRate(rec.win_rate) ? rec.win_rate : 0}%`, backgroundColor: barCol }} />
                      </div>
                      <div className="leaderboard-counts">
                        <span>{rec.correct} Correct</span>
                        <span>{rec.wrong} Inaccurate</span>
                        <span>{rec.neutral} Neutral</span>
                      </div>
                    </div>
                  );
                })
              ) : (
                <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>No Webull recommendations recorded yet.</p>
              )}
            </div>
          </div>

          {/* AI Model Leaderboard */}
          <div className="benchmark-card">
            <h3>🏆 AI Model Accuracy Leaderboard</h3>
            <p className="benchmark-subtext">Accuracy comparison on Webull market predictions</p>

            <div className="model-leaderboard-list">
              {modelBreakdown.length > 0 ? (
                modelBreakdown.map((m, idx) => (
                  <div key={idx} className="leaderboard-item">
                    <div className="leaderboard-header">
                      <div className="model-info">
                        <strong>{getProviderName(m.provider)}</strong>
                        <span className="model-subname">({m.model}) • {getTierName(m.tier)}</span>
                      </div>
                      <div className="model-winrate">{formatRate(m.win_rate)} Win Rate</div>
                    </div>
                    <div className="progress-bar-track">
                      <div
                        className="progress-bar-fill"
                        style={{
                          width: `${hasRate(m.win_rate) ? m.win_rate : 0}%`,
                          backgroundColor: idx === 0 ? '#00e676' : idx === 1 ? '#38bdf8' : '#a855f7'
                        }}
                      />
                    </div>
                    <div className="leaderboard-counts">
                      <span>{m.correct} Correct Calls</span>
                      <span>{m.wrong} Inaccurate Calls</span>
                      <span>{m.total} Total</span>
                    </div>
                  </div>
                ))
              ) : (
                <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>No model leaderboard data available yet.</p>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 3. THESIS DETAIL MODAL */}
      {/* ========================================================================= */}
      {selectedThesisModal && (
        <div className="modal-backdrop" onClick={() => setSelectedThesisModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 750, width: '90%' }}>
            <div className="modal-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3 style={{ margin: 0, fontSize: '1.3rem' }}>
                  📊 {selectedThesisModal.symbol} Research Thesis
                </h3>
                <p style={{ margin: '4px 0 0', fontSize: '12px', color: 'var(--text-secondary)' }}>
                  Recorded on {selectedThesisModal.formatted_datetime || selectedThesisModal.date} at ${parseFloat(selectedThesisModal.price_at_prediction || 0).toFixed(4)}
                </p>
              </div>
              <span className={`signal-pill ${['buy immediately', 'consider buying'].includes((selectedThesisModal.sentiment || '').toLowerCase()) ? 'badge-buy' : ['sell immediately', 'consider selling'].includes((selectedThesisModal.sentiment || '').toLowerCase()) ? 'badge-sell' : 'badge-watch'}`}>
                {selectedThesisModal.sentiment}
              </span>
            </div>

            <div className="modal-body" style={{ maxHeight: '60vh', overflowY: 'auto', padding: 20 }}>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16, padding: '8px 12px', background: 'rgba(15, 23, 42, 0.6)', borderRadius: 6, border: '1px solid #334155' }}>
                <span style={{ fontSize: '12px' }}><strong>Provider:</strong> {getProviderName(selectedThesisModal.provider)}</span>
                <span style={{ fontSize: '12px' }}><strong>Model:</strong> {selectedThesisModal.model || 'Default'}</span>
                <span style={{ fontSize: '12px' }}><strong>Horizon:</strong> {selectedThesisModal.forecast_horizon_hours || 24}h</span>
                <span style={{ fontSize: '12px' }}><strong>Outcome:</strong> {selectedThesisModal.outcome_status} ({selectedThesisModal.outcome_pct ? `${selectedThesisModal.outcome_pct >= 0 ? '+' : ''}${selectedThesisModal.outcome_pct}%` : 'Tracking'})</span>
              </div>

              <div
                style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.6', color: '#e2e8f0' }}
                dangerouslySetInnerHTML={{ __html: renderMarkdown(selectedThesisModal.sentiment_reason) }}
              />

              {selectedThesisModal.market_context && (
                <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid #334155' }}>
                  <h4 style={{ margin: '0 0 8px', fontSize: '13px', color: 'var(--text-secondary)' }}>Market Data Snapshot:</h4>
                  <pre style={{ fontSize: '12px', background: '#0b0f19', padding: 10, borderRadius: 4, whiteSpace: 'pre-wrap', color: '#94a3b8' }}>
                    {selectedThesisModal.market_context}
                  </pre>
                </div>
              )}
            </div>

            <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', padding: '12px 20px' }}>
              <button className="btn btn-secondary" onClick={() => setSelectedThesisModal(null)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* 4. CONFIGURE ASSETS MODAL */}
      {/* ========================================================================= */}
      {showCoinFilterModal && (
        <div className="modal-backdrop" onClick={() => setShowCoinFilterModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 500 }}>
            <div className="modal-header">
              <h3>⚙️ Configure Webull Ledger Assets</h3>
            </div>
            <div className="modal-body" style={{ maxHeight: '50vh', overflowY: 'auto', padding: 20 }}>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: 12 }}>
                Select the Webull symbols you want visible in the prediction ledger and chart:
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))', gap: 8 }}>
                {availableSymbols.map((sym) => {
                  const isChecked = tempFilterCoins.includes(sym);
                  return (
                    <label key={sym} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '13px', cursor: 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => {
                          setTempFilterCoins(prev => isChecked ? prev.filter(s => s !== sym) : [...prev, sym]);
                        }}
                      />
                      <span>{sym}</span>
                    </label>
                  );
                })}
              </div>
            </div>
            <div className="modal-footer" style={{ display: 'flex', justifyContent: 'space-between', padding: '12px 20px' }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setTempFilterCoins([...availableSymbols])}
              >
                Select All
              </button>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn btn-secondary" onClick={() => setShowCoinFilterModal(false)}>Cancel</button>
                <button
                  className="btn btn-primary"
                  onClick={() => {
                    const toSave = tempFilterCoins.length === availableSymbols.length ? [] : tempFilterCoins;
                    setActiveLedgerCoins(toSave);
                    localStorage.setItem('webull_dashboard_active_ledger_coins', JSON.stringify(toSave));
                    setShowCoinFilterModal(false);
                  }}
                >
                  Apply Filters
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
