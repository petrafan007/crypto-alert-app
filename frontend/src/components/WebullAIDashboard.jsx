import React, { useState, useEffect, useMemo } from 'react';
import axios from 'axios';
import { useAuth } from './AuthContext';
import SentimentTimelineChart from './SentimentTimelineChart';
import { DEFAULT_SENTIMENT_CHART_RANGE, getChartRange } from '../utils/chartRanges';
import '../pages/AIDashboard.css';

const formatEasternTime = (isoString) => {
  if (!isoString) return 'Not available';
  try {
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return String(isoString);
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZoneName: 'short'
    });
    const parts = formatter.formatToParts(date);
    const getPart = (type) => parts.find(p => p.type === type)?.value || '';
    return `${getPart('month')}-${getPart('day')}-${getPart('year')} at ${getPart('hour')}:${getPart('minute')} ${getPart('dayPeriod')} ${getPart('timeZoneName') || 'EDT'}`;
  } catch (error) {
    return 'Invalid date';
  }
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

const formatRate = (rate) => (rate !== null && rate !== undefined ? `${rate}%` : '—');
const hasRate = (rate) => rate !== null && rate !== undefined;

export default function WebullAIDashboard({ isLightMode = false }) {
  const { user, loading: authLoading } = useAuth();

  // Range and filter state
  const [dateRange, setDateRange] = useState('30d');
  const [chartRange, setChartRange] = useState(DEFAULT_SENTIMENT_CHART_RANGE);
  const [accuracyData, setAccuracyData] = useState(null);
  const [accuracyLoading, setAccuracyLoading] = useState(false);

  // Available Webull holdings & watchlist
  const [webullHoldings, setWebullHoldings] = useState([]);
  const [selectedHoldingId, setSelectedHoldingId] = useState('');
  const [analyzingHolding, setAnalyzingHolding] = useState(false);
  const [analyzeNotice, setAnalyzeNotice] = useState('');
  const [activeThesis, setActiveThesis] = useState(null);

  // Filter and modal state
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

  // Webull AI signal settings
  const [signalSettings, setSignalSettings] = useState({
    webull_ai_scheduling_enabled: false,
    webull_crypto_sentiment_frequency_hours: 6,
    webull_equity_sentiment_frequency_hours: 24,
    webull_crypto_sentiment_horizon_hours: 24,
    webull_equity_sentiment_horizon_hours: 24,
  });
  const [savingSettings, setSavingSettings] = useState(false);

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

  const loadWebullHoldings = async () => {
    try {
      const res = await axios.get('/api/coin-data-live', { withCredentials: true });
      const portfolio = res.data?.portfolio || [];
      const webullItems = portfolio.filter(item => item.source === 'webull' || item.is_external);
      setWebullHoldings(webullItems);
      if (webullItems.length > 0 && !selectedHoldingId) {
        setSelectedHoldingId(String(webullItems[0].id));
      }
    } catch (e) {
      console.error('Failed to load Webull holdings for AI Analysis:', e);
    }
  };

  const loadSignalSettings = async () => {
    try {
      const res = await axios.get('/api/webull/ai-settings', { withCredentials: true });
      if (res.data?.settings) {
        setSignalSettings(res.data.settings);
      }
    } catch (e) {
      console.error('Failed to load Webull AI settings:', e);
    }
  };

  useEffect(() => {
    if (!authLoading && user) {
      fetchAccuracyData(dateRange);
      loadWebullHoldings();
      loadSignalSettings();
    }
  }, [authLoading, user]);

  const handleSaveSettings = async (e) => {
    e?.preventDefault();
    setSavingSettings(true);
    try {
      const res = await axios.put('/api/webull/ai-settings', signalSettings, { withCredentials: true });
      if (res.data?.settings) {
        setSignalSettings(res.data.settings);
        setAnalyzeNotice('AI Signal scheduling settings updated.');
        setTimeout(() => setAnalyzeNotice(''), 4000);
      }
    } catch (e) {
      setAnalyzeNotice(e.response?.data?.message || 'Failed to save settings.');
    } finally {
      setSavingSettings(false);
    }
  };

  const handleRunAnalysis = async () => {
    if (!selectedHoldingId) return;
    setAnalyzingHolding(true);
    setAnalyzeNotice('');
    try {
      const selectedItem = webullHoldings.find(h => String(h.id) === String(selectedHoldingId));
      const payload = {
        holding_id: selectedHoldingId,
        symbol: selectedItem?.symbol,
        instrument_type: selectedItem?.asset_type || selectedItem?.instrument_type,
      };
      const res = await axios.post('/api/webull/ai-analysis', payload, { withCredentials: true });
      if (res.data?.success && res.data?.signal) {
        setActiveThesis({
          signal: res.data.signal,
          market: res.data.market,
          symbol: selectedItem?.symbol || res.data.signal.symbol,
        });
        setAnalyzeNotice('Generated fresh thesis and recorded research signal in ledger.');
        fetchAccuracyData(dateRange);
      } else {
        setAnalyzeNotice(res.data?.message || 'Unable to generate analysis.');
      }
    } catch (e) {
      setAnalyzeNotice(e.response?.data?.message || e.message || 'Analysis failed.');
    } finally {
      setAnalyzingHolding(false);
    }
  };

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
      list = list.filter(row => (row.symbol || '').toUpperCase() === selectedLedgerCoin.toUpperCase());
    }
    if (activeLedgerCoins.length > 0) {
      const allowed = new Set(activeLedgerCoins.map(s => s.toUpperCase()));
      list = list.filter(row => allowed.has((row.symbol || '').toUpperCase()));
    }

    if (ledgerSortConfig) {
      list = [...list].sort((a, b) => {
        let valA = a[ledgerSortConfig.key];
        let valB = b[ledgerSortConfig.key];
        if (['evaluation_price', 'price_at_prediction', 'outcome_pct'].includes(ledgerSortConfig.key)) {
          valA = parseFloat(valA || 0);
          valB = parseFloat(valB || 0);
        } else if (['created_at', 'evaluated_at'].includes(ledgerSortConfig.key)) {
          valA = new Date(a[ledgerSortConfig.key] || 0).getTime();
          valB = new Date(b[ledgerSortConfig.key] || 0).getTime();
        } else {
          valA = (valA || '').toString().toLowerCase();
          valB = (valB || '').toString().toLowerCase();
        }
        if (valA < valB) return ledgerSortConfig.direction === 'asc' ? -1 : 1;
        if (valA > valB) return ledgerSortConfig.direction === 'asc' ? 1 : -1;
        return 0;
      });
    } else {
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
    <div className="ai-dashboard" style={{ padding: '24px 0', minHeight: 'auto', background: 'transparent' }}>
      {/* Header */}
      <div className="ai-header">
        <div>
          <h1>🤖 Webull AI Sentiment Prediction & Thesis Engine</h1>
          <p style={{ margin: '4px 0 0', color: 'var(--text-secondary, #94a3b8)', fontSize: '14px' }}>
            Empirical accuracy tracking and multi-model thesis validation across Webull portfolio holdings & watchlist
          </p>
        </div>
        <div className="ai-header-controls">
          <div className="range-selector">
            {['1d', '3d', '7d', '14d', '30d', '90d', '180d', '365d', '730d'].map((range) => (
              <button
                key={range}
                className={`range-btn ${dateRange === range ? 'active' : ''}`}
                onClick={() => {
                  setDateRange(range);
                  fetchAccuracyData(range);
                }}
              >
                {range}
              </button>
            ))}
          </div>
          <button
            onClick={() => {
              setTempFilterCoins(activeLedgerCoins.length > 0 ? [...activeLedgerCoins] : [...availableSymbols]);
              setShowCoinFilterModal(true);
            }}
            className="btn btn-secondary btn-sm"
          >
            ⚙️ Configure Assets {activeLedgerCoins.length > 0 && `(${activeLedgerCoins.length})`}
          </button>
          <button
            onClick={() => fetchAccuracyData(dateRange)}
            disabled={accuracyLoading}
            className="btn btn-primary btn-sm"
          >
            {accuracyLoading ? '⏳ Refreshing...' : '🔄 Refresh Accuracy'}
          </button>
        </div>
      </div>

      {analyzeNotice && (
        <div className="modern-real-warning" style={{ marginBottom: 20, background: 'rgba(56, 189, 248, 0.1)', borderColor: '#38bdf8', color: '#38bdf8' }}>
          💡 {analyzeNotice}
        </div>
      )}

      {/* ========================================================================= */}
      {/* 1. VISUALIZER 1: PERFORMANCE KPIS & SENTIMENT TIMELINE CHART */}
      {/* ========================================================================= */}
      <div className="prediction-visualizer-section">
        <div className="accuracy-kpi-grid">
          <div className="accuracy-kpi-card overall">
            <span className="kpi-label">🎯 Webull Overall Accuracy</span>
            <div className="kpi-value glow-text">
              {formatRate(summary.overall_accuracy)}
            </div>
            <span className="kpi-subtext">
              {summary.correct_count ?? 0} Correct / {summary.evaluated_signals ?? 0} Evaluated Calls
            </span>
          </div>

          <div className="accuracy-kpi-card bullish">
            <span className="kpi-label">🚀 Bullish Win Rate</span>
            <div className="kpi-value text-green">
              {formatRate(summary.bullish_win_rate)}
            </div>
            <span className="kpi-subtext">
              {summary.bullish_correct_count ?? 0} Correct / {summary.bullish_count ?? 0} Decisive
            </span>
          </div>

          <div className="accuracy-kpi-card bearish">
            <span className="kpi-label">🔻 Bearish Win Rate</span>
            <div className="kpi-value text-red">
              {formatRate(summary.bearish_win_rate)}
            </div>
            <span className="kpi-subtext">
              {summary.bearish_correct_count ?? 0} Correct / {summary.bearish_count ?? 0} Decisive
            </span>
          </div>

          <div className="accuracy-kpi-card model">
            <span className="kpi-label">🏆 Top Performing Model</span>
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
      {/* 2. ON-DEMAND AI SENTIMENT PREDICTION & THESIS ENGINE */}
      {/* ========================================================================= */}
      <div className="ai-section" style={{ marginBottom: 24, padding: 24, background: 'var(--card-bg, #1e293b)', borderRadius: 12, border: '1px solid var(--card-border, #334155)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16, marginBottom: 18 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: '1.25rem', color: '#38bdf8' }}>⚡ Run Webull AI Analysis & Generate Thesis</h2>
            <p style={{ margin: '4px 0 0', color: 'var(--text-secondary, #94a3b8)', fontSize: '13px' }}>
              Select any Webull position (Stock, ETF, Crypto, or Option) to execute multi-stage AI sentiment analysis with real-time news grounding.
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <select
              value={selectedHoldingId}
              onChange={(e) => setSelectedHoldingId(e.target.value)}
              style={{ padding: '8px 12px', background: '#0b0f19', color: '#fff', border: '1px solid #334155', borderRadius: 6, minWidth: 220 }}
            >
              {webullHoldings.length === 0 ? (
                <option value="">No imported Webull holdings</option>
              ) : (
                webullHoldings.map((holding) => (
                  <option key={holding.id} value={holding.id}>
                    {holding.symbol} — {holding.asset_type || holding.instrument_type || 'Equity'} ({holding.amount} @ ${Number(holding.avg_entry || holding.current_price || 0).toFixed(2)})
                  </option>
                ))
              )}
            </select>

            <button
              type="button"
              className="btn btn-primary"
              disabled={analyzingHolding || !selectedHoldingId}
              onClick={handleRunAnalysis}
              style={{ minWidth: 160 }}
            >
              {analyzingHolding ? '⏳ Analyzing Holding...' : '🚀 Generate Thesis'}
            </button>
          </div>
        </div>

        {/* Active Thesis Result Card */}
        {activeThesis && activeThesis.signal && (
          <div className="workflow-result" style={{ background: '#0b0f19', border: '1px solid #38bdf8', borderRadius: 8, padding: 20, marginTop: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 16, borderBottom: '1px solid #1e293b', paddingBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontSize: '1.4rem', fontWeight: 'bold', color: '#f8fafc' }}>{activeThesis.symbol}</span>
                <span className={`signal-pill ${['buy immediately', 'consider buying'].includes(activeThesis.signal.recommendation.toLowerCase()) ? 'badge-buy' : ['sell immediately', 'consider selling'].includes(activeThesis.signal.recommendation.toLowerCase()) ? 'badge-sell' : 'badge-watch'}`}>
                  {activeThesis.signal.recommendation}
                </span>
                <span style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>
                  Entry: ${Number(activeThesis.signal.entry_price || 0).toFixed(4)}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <span className="meta-item ai-model-badge" style={{ background: 'rgba(99, 179, 237, 0.15)', border: '1px solid rgba(99, 179, 237, 0.3)', borderRadius: 6, padding: '2px 8px', fontSize: '12px' }}>
                  🤖 {getProviderName(activeThesis.signal.ai_provider)} ({activeThesis.signal.provider_model || 'Default'}) • {getTierName(activeThesis.signal.ai_tier)}
                </span>
                <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                  Horizon: {activeThesis.signal.forecast_horizon_hours}h
                </span>
              </div>
            </div>

            <div
              style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.6', color: '#e2e8f0' }}
              dangerouslySetInnerHTML={{ __html: renderMarkdown(activeThesis.signal.reason) }}
            />
          </div>
        )}
      </div>

      {/* ========================================================================= */}
      {/* 3. VISUALIZER 2: PREDICTION LEDGER & BENCHMARKS */}
      {/* ========================================================================= */}
      <div className="prediction-ledger-section">
        <div className="prediction-ledger-header">
          <div>
            <h2>📜 Webull Historical Prediction Ledger</h2>
            <p className="prediction-ledger-subtext">
              Immutable record of all AI signals recorded for Webull assets, evaluated strictly against connector market quotes.
            </p>
          </div>

          <div className="ledger-controls">
            <label className="coin-filter-label">Asset: </label>
            <select
              value={selectedLedgerCoin}
              onChange={(e) => {
                setSelectedLedgerCoin(e.target.value);
                setLedgerPage(1);
              }}
              className="ledger-coin-select"
            >
              <option value="all">All Webull Assets</option>
              {availableSymbols.map((sym) => (
                <option key={sym} value={sym}>{sym}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Prediction Table Card */}
        <div className="prediction-table-card">
          <div className="table-responsive">
            <table className="prediction-table">
              <thead>
                <tr>
                  <th onClick={() => requestLedgerSort('symbol')} style={{ cursor: 'pointer' }}>Asset {getSortIcon('symbol')}</th>
                  <th onClick={() => requestLedgerSort('price_at_prediction')} style={{ cursor: 'pointer' }}>Initial Price {getSortIcon('price_at_prediction')}</th>
                  <th onClick={() => requestLedgerSort('created_at')} style={{ cursor: 'pointer' }}>Prediction Date {getSortIcon('created_at')}</th>
                  <th>Horizon</th>
                  <th onClick={() => requestLedgerSort('evaluation_price')} style={{ cursor: 'pointer' }}>Eval Price {getSortIcon('evaluation_price')}</th>
                  <th onClick={() => requestLedgerSort('evaluated_at')} style={{ cursor: 'pointer' }}>Eval Date {getSortIcon('evaluated_at')}</th>
                  <th onClick={() => requestLedgerSort('sentiment')} style={{ cursor: 'pointer' }}>Signal {getSortIcon('sentiment')}</th>
                  <th onClick={() => requestLedgerSort('outcome_status')} style={{ cursor: 'pointer' }}>Outcome {getSortIcon('outcome_status')}</th>
                  <th>Thesis</th>
                </tr>
              </thead>
              <tbody>
                {paginatedRows.length === 0 ? (
                  <tr>
                    <td colSpan="9" style={{ textAlign: 'center', padding: '36px', color: 'var(--text-secondary)' }}>
                      No Webull sentiment predictions recorded for this timeframe yet. Use the "Generate Thesis" engine above to analyze an asset.
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
                        <td className="symbol-cell" style={{ textAlign: 'center' }}>
                          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                            <span className="coin-pill">{row.symbol}</span>
                            <span className="source-badge source-p" style={{ fontSize: '10px', background: '#38bdf8', color: '#000', fontWeight: 'bold' }}>
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
                        <td>
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

          {/* Pagination Controls */}
          {filteredHistory.length > 0 && (
            <div className="pagination-bar" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', borderTop: '1px solid var(--border-color, #2d3748)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Rows per page:</span>
                <select
                  value={ledgerPageSize}
                  onChange={(e) => {
                    setLedgerPageSize(Number(e.target.value));
                    setLedgerPage(1);
                  }}
                  style={{ background: '#0b0f19', color: '#fff', border: '1px solid #334155', borderRadius: 4, padding: '2px 6px' }}
                >
                  {[20, 50, 100, 200].map(sz => <option key={sz} value={sz}>{sz}</option>)}
                </select>
                <span style={{ fontSize: '13px', color: 'var(--text-secondary)', marginLeft: 12 }}>
                  Showing {Math.min((ledgerPage - 1) * ledgerPageSize + 1, filteredHistory.length)}–{Math.min(ledgerPage * ledgerPageSize, filteredHistory.length)} of {filteredHistory.length}
                </span>
              </div>

              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={ledgerPage <= 1}
                  onClick={() => setLedgerPage(p => Math.max(1, p - 1))}
                >
                  ◀ Prev
                </button>
                <span style={{ display: 'flex', alignItems: 'center', fontSize: '13px', padding: '0 8px' }}>
                  {ledgerPage} / {totalPages}
                </span>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={ledgerPage >= totalPages}
                  onClick={() => setLedgerPage(p => Math.min(totalPages, p + 1))}
                >
                  Next ▶
                </button>
              </div>
            </div>
          )}
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
      {/* 4. SCHEDULED AI ANALYSIS SETTINGS CARD */}
      {/* ========================================================================= */}
      <div className="ai-section" style={{ marginTop: 24, padding: 20, background: 'var(--card-bg, #1e293b)', borderRadius: 12, border: '1px solid var(--card-border, #334155)' }}>
        <h3 style={{ margin: '0 0 8px', fontSize: '1.1rem', color: '#f8fafc' }}>⏱️ Scheduled Webull AI Research Automation</h3>
        <p style={{ color: 'var(--text-secondary, #94a3b8)', fontSize: '13px', margin: '0 0 16px' }}>
          Optionally enable automated periodic background signals for Webull holdings. When enabled, signals are stored in the ledger and graded at their target evaluation date.
        </p>

        <form onSubmit={handleSaveSettings} style={{ display: 'flex', flexWrap: 'wrap', gap: 20, alignItems: 'flex-end' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: '14px' }}>
            <input
              type="checkbox"
              checked={signalSettings.webull_ai_scheduling_enabled}
              onChange={(e) => setSignalSettings({ ...signalSettings, webull_ai_scheduling_enabled: e.target.checked })}
            />
            <span>Enable Scheduled Webull AI Signals</span>
          </label>

          <label style={{ fontSize: '13px', display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span>Crypto Cadence (hours):</span>
            <input
              type="number"
              min="1"
              max="168"
              value={signalSettings.webull_crypto_sentiment_frequency_hours}
              onChange={(e) => setSignalSettings({ ...signalSettings, webull_crypto_sentiment_frequency_hours: Number(e.target.value) })}
              style={{ width: 100, padding: '4px 8px', background: '#0b0f19', color: '#fff', border: '1px solid #334155', borderRadius: 4 }}
            />
          </label>

          <label style={{ fontSize: '13px', display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span>Equity Cadence (hours):</span>
            <input
              type="number"
              min="1"
              max="168"
              value={signalSettings.webull_equity_sentiment_frequency_hours}
              onChange={(e) => setSignalSettings({ ...signalSettings, webull_equity_sentiment_frequency_hours: Number(e.target.value) })}
              style={{ width: 100, padding: '4px 8px', background: '#0b0f19', color: '#fff', border: '1px solid #334155', borderRadius: 4 }}
            />
          </label>

          <button
            type="submit"
            className="btn btn-secondary btn-sm"
            disabled={savingSettings}
            style={{ height: 32 }}
          >
            {savingSettings ? 'Saving...' : 'Save Schedule Settings'}
          </button>
        </form>
      </div>

      {/* ========================================================================= */}
      {/* 5. THESIS DETAIL MODAL */}
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
      {/* 6. CONFIGURE ASSETS MODAL */}
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
