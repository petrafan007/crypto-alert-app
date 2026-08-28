import React, { useState, useEffect, useMemo } from 'react';
import axios from 'axios';
import { useAuth } from '../components/AuthContext';
import ApiKeyRequiredModal from '../components/ApiKeyRequiredModal';
import CryptoIcon from '../components/CryptoIcon';
import SentimentTimelineChart from '../components/SentimentTimelineChart';
import { DEFAULT_SENTIMENT_CHART_RANGE, getChartRange } from '../utils/chartRanges';
import './AIDashboard.css';

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
    const month = getPart('month');
    const day = getPart('day');
    const year = getPart('year');
    const hour = getPart('hour');
    const minute = getPart('minute');
    const dayPeriod = getPart('dayPeriod');
    const timeZoneName = getPart('timeZoneName') || 'EDT';
    return `${month}-${day}-${year} at ${hour}:${minute} ${dayPeriod} ${timeZoneName}`;
  } catch (error) {
    console.error('Error formatting timestamp:', error);
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

const AIDashboard = () => {
  const { user, isLightMode, isLoggingOut, authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [aiEnabled, setAiEnabled] = useState(true);

  // API Key check state
  const [showApiKeyModal, setShowApiKeyModal] = useState(false);

  // === AI SENTIMENT ACCURACY & THESIS TRACKER STATE ===
  const [accuracyData, setAccuracyData] = useState(null);
  const [accuracyLoading, setAccuracyLoading] = useState(false);
  const [dateRange, setDateRange] = useState(DEFAULT_SENTIMENT_CHART_RANGE);

  // Coin filter state - stores explicitly excluded symbols so any newly added portfolio coins default to INCLUDED (checked)
  const [showCoinFilterModal, setShowCoinFilterModal] = useState(false);
  const [showLedgerCoinDropdown, setShowLedgerCoinDropdown] = useState(false);
  const [ledgerCoinSearch, setLedgerCoinSearch] = useState('');
  const [excludedFilterCoins, setExcludedFilterCoins] = useState(() => {
    try {
      const saved = localStorage.getItem('sentiment_table_excluded_coins');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) return parsed;
      }
    } catch (e) {}
    return [];
  });
  const [tempFilterCoins, setTempFilterCoins] = useState([]);

  // Close ledger coin filter dropdown on outside click
  useEffect(() => {
    if (!showLedgerCoinDropdown) return;
    const handleOutsideClick = (e) => {
      if (!e.target.closest('.ledger-coin-filter-dropdown') && !e.target.closest('.ledger-coin-filter-toggle-btn')) {
        setShowLedgerCoinDropdown(false);
      }
    };
    document.addEventListener('click', handleOutsideClick);
    return () => document.removeEventListener('click', handleOutsideClick);
  }, [showLedgerCoinDropdown]);

  // Ledger sort state (non-persisted, defaults to updated Date & Time descending on reload)
  const [ledgerSortConfig, setLedgerSortConfig] = useState(null);
  const [ledgerPage, setLedgerPage] = useState(1);
  const [ledgerPageSize, setLedgerPageSize] = useState(20);

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

  useEffect(() => {
    const init = async () => {
      if (!authLoading && user) {
        try {
          const permResponse = await axios.get('/api/check-trade-permission', { withCredentials: true });
          if (!permResponse.data.has_api_key) {
            setShowApiKeyModal(true);
            setLoading(false);
            return;
          }
        } catch (err) {
          console.error('Failed to check API key status:', err);
        }

        const { enabled, preferredRange } = await checkAiStatus();
        setLoading(false);
        if (enabled) {
          await fetchAccuracyData(preferredRange);
        }
      }
    };
    init();
  }, [authLoading, user]);

  const fetchAccuracyData = async (tf = dateRange) => {
    setAccuracyLoading(true);
    try {
      // Fetch full history across all coins (no symbol filter on global accuracy fetch)
      const res = await axios.get('/api/ai/sentiment-accuracy', {
        params: { timeframe: tf },
        withCredentials: true
      });
      if (res.data && res.data.success) {
        setAccuracyData(res.data);
      }
    } catch (err) {
      console.error('Error fetching sentiment accuracy data:', err);
    } finally {
      setAccuracyLoading(false);
    }
  };

  // Compute per-coin historical accuracy for hover tooltips
  const coinAccuracyMap = useMemo(() => {
    const map = {};
    (accuracyData?.history || []).forEach((row) => {
      const sym = row.symbol;
      if (!sym) return;
      if (!map[sym]) {
        map[sym] = { total: 0, correct: 0, wrong: 0, active: 0 };
      }
      map[sym].total += 1;
      if (row.outcome_status === 'correct') {
        map[sym].correct += 1;
      } else if (row.outcome_status === 'wrong') {
        map[sym].wrong += 1;
      } else {
        map[sym].active += 1;
      }
    });

    const resultMap = {};
    Object.keys(map).forEach((sym) => {
      const s = map[sym];
      const evaluated = s.correct + s.wrong;
      const rate = evaluated > 0 ? ((s.correct / evaluated) * 100).toFixed(1) : (s.correct > 0 ? '100.0' : '0.0');
      resultMap[sym] = {
        ...s,
        evaluated,
        accuracyRate: rate,
        tooltip: evaluated > 0
          ? `${sym} Historical Accuracy: ${rate}% (${s.correct} Correct, ${s.wrong} Wrong across ${s.total} calls)`
          : `${sym} Accuracy: Active Tracking (${s.active} calls)`,
      };
    });
    return resultMap;
  }, [accuracyData]);

  // Compute available coins with source types for filtering and badges
  const availableCoinFilters = useMemo(() => {
    const map = new Map();
    (accuracyData?.history || []).forEach((row) => {
      if (row.symbol && !map.has(row.symbol)) {
        map.set(row.symbol, {
          symbol: row.symbol,
          source_type: row.source_type || 'portfolio',
        });
      }
    });
    (accuracyData?.available_symbols || []).forEach((sym) => {
      if (sym && !map.has(sym)) {
        map.set(sym, {
          symbol: sym,
          source_type: 'portfolio',
        });
      }
    });
    return Array.from(map.values()).sort((a, b) => a.symbol.localeCompare(b.symbol));
  }, [accuracyData]);

  const activeFilterCoins = useMemo(() => {
    const excludedSet = new Set(excludedFilterCoins);
    return availableCoinFilters.map(c => c.symbol).filter(sym => !excludedSet.has(sym));
  }, [availableCoinFilters, excludedFilterCoins]);

  const completedLedgerRows = useMemo(() => (
    (accuracyData?.history || []).filter(row =>
      row && row.symbol && activeFilterCoins.includes(row.symbol) && !row.is_latest && row.outcome_status !== 'tracking'
    )
  ), [accuracyData, activeFilterCoins]);

  const ledgerPageCount = Math.max(1, Math.ceil(completedLedgerRows.length / ledgerPageSize));

  useEffect(() => {
    setLedgerPage(previous => Math.min(previous, ledgerPageCount));
  }, [ledgerPageCount]);

  useEffect(() => {
    setLedgerPage(1);
  }, [activeFilterCoins, ledgerPageSize]);

  // Dynamic recommendation and multi-model breakdowns
  const { recommendationBreakdown, modelBreakdown } = useMemo(() => {
    if (!accuracyData) {
      return { recommendationBreakdown: [], modelBreakdown: [] };
    }

    const availableFilterList = availableCoinFilters || [];
    const isFiltering = excludedFilterCoins.length > 0;

    // If not actively filtering coins, default to server-aggregated breakdowns
    if (!isFiltering) {
      return {
        recommendationBreakdown: accuracyData.recommendation_breakdown || [],
        modelBreakdown: accuracyData.model_breakdown || []
      };
    }

    const filteredHistory = (accuracyData.history || []).filter(row => row && row.symbol && activeFilterCoins.includes(row.symbol));

    const recStats = {};
    const modStats = {};

    filteredHistory.forEach(row => {
      if (!row) return;
      // Recommendation Breakdown
      const recKey = row.sentiment || 'Unknown';
      if (!recStats[recKey]) {
        recStats[recKey] = { sentiment: recKey, total: 0, correct: 0, wrong: 0, neutral: 0 };
      }
      recStats[recKey].total += 1;
      if (row.outcome_status === 'correct') recStats[recKey].correct += 1;
      else if (row.outcome_status === 'wrong') recStats[recKey].wrong += 1;
      else if (row.outcome_status === 'neutral') recStats[recKey].neutral += 1;
      
      // Model Breakdown
      const modelKey = row.model || 'Default Model';
      if (!modStats[modelKey]) {
        modStats[modelKey] = {
          model: modelKey,
          provider: row.provider || 'AI',
          tier: row.tier || 'primary',
          total: 0,
          correct: 0,
          wrong: 0,
          neutral: 0
        };
      }
      modStats[modelKey].total += 1;
      if (row.outcome_status === 'correct') modStats[modelKey].correct += 1;
      else if (row.outcome_status === 'wrong') modStats[modelKey].wrong += 1;
      else if (row.outcome_status === 'neutral') modStats[modelKey].neutral += 1;
    });

    const recBreakdown = Object.values(recStats).map(r => {
      const rEval = r.correct + r.wrong;
      r.win_rate = rEval > 0 ? Number(((r.correct / rEval) * 100).toFixed(1)) : (r.correct > 0 ? 100.0 : 0.0);
      return r;
    }).sort((a, b) => b.total - a.total);

    const modBreakdown = Object.values(modStats).map(m => {
      const mEval = m.correct + m.wrong;
      m.win_rate = mEval > 0 ? Number(((m.correct / mEval) * 100).toFixed(1)) : null;
      return m;
    }).sort((a, b) => b.win_rate - a.win_rate);

    return {
      recommendationBreakdown: recBreakdown.length > 0 ? recBreakdown : (accuracyData.recommendation_breakdown || []),
      modelBreakdown: modBreakdown.length > 0 ? modBreakdown : (accuracyData.model_breakdown || [])
    };
  }, [accuracyData, activeFilterCoins, excludedFilterCoins, availableCoinFilters]);

  const handleOpenCoinFilterModal = () => {
    setTempFilterCoins([...activeFilterCoins]);
    setShowCoinFilterModal(true);
  };

  const handleToggleFilterCoin = (symbol) => {
    setTempFilterCoins(prev =>
      prev.includes(symbol) ? prev.filter(s => s !== symbol) : [...prev, symbol]
    );
  };

  const handleSelectAllFilterCoins = () => {
    setTempFilterCoins(availableCoinFilters.map(c => c.symbol));
  };

  const handleDeselectAllFilterCoins = () => {
    setTempFilterCoins([]);
  };

  const handleApplyCoinFilter = () => {
    const selectedSet = new Set(tempFilterCoins);
    const newExcluded = availableCoinFilters.map(c => c.symbol).filter(sym => !selectedSet.has(sym));
    setExcludedFilterCoins(newExcluded);
    try {
      localStorage.setItem('sentiment_table_excluded_coins', JSON.stringify(newExcluded));
    } catch (e) {
      console.warn('Failed to save excluded coin filter to localStorage:', e);
    }
    setShowCoinFilterModal(false);
  };

  const handleToggleSingleCoinInFilter = (symbol) => {
    setExcludedFilterCoins(prev => {
      const next = prev.includes(symbol) ? prev.filter(s => s !== symbol) : [...prev, symbol];
      try {
        localStorage.setItem('sentiment_table_excluded_coins', JSON.stringify(next));
      } catch (e) {}
      return next;
    });
  };

  const handleSelectAllInDropdown = () => {
    setExcludedFilterCoins([]);
    try {
      localStorage.setItem('sentiment_table_excluded_coins', JSON.stringify([]));
    } catch (e) {}
  };

  const handleDeselectAllInDropdown = () => {
    const all = availableCoinFilters.map(c => c.symbol);
    setExcludedFilterCoins(all);
    try {
      localStorage.setItem('sentiment_table_excluded_coins', JSON.stringify(all));
    } catch (e) {}
  };

  const checkAiStatus = async () => {
    try {
      if (isLoggingOut || window.globalIsLoggingOut) {
        return { enabled: false, preferredRange: DEFAULT_SENTIMENT_CHART_RANGE };
      }
      const response = await axios.get('/api/ai/settings', { withCredentials: true });
      const enabled = response.data.ai_enabled === true || response.data.ai_enabled === 'true';
      const preferredRange = getChartRange(
        response.data.sentiment_chart_default_range,
        DEFAULT_SENTIMENT_CHART_RANGE,
      ).value;
      setAiEnabled(enabled);
      setDateRange(preferredRange);
      return { enabled, preferredRange };
    } catch (error) {
      console.error('Error checking AI status:', error);
      setAiEnabled(true);
      setDateRange(DEFAULT_SENTIMENT_CHART_RANGE);
      return { enabled: true, preferredRange: DEFAULT_SENTIMENT_CHART_RANGE };
    }
  };

  const handleSentimentRangeChange = async (nextRange) => {
    const normalizedRange = getChartRange(nextRange, DEFAULT_SENTIMENT_CHART_RANGE).value;
    setDateRange(normalizedRange);
    fetchAccuracyData(normalizedRange);
    try {
      await axios.post('/api/ai/settings', {
        sentiment_chart_default_range: normalizedRange,
      }, { withCredentials: true });
    } catch (error) {
      console.error('Unable to save the Sentiment Chart default range:', error);
    }
  };

  if (loading) {
    return (
      <div className="ai-dashboard">
        <div className="ai-loading">
          <div className="ai-loading-spinner"></div>
          <p>Loading AI Prediction & Thesis Dashboard...</p>
        </div>
      </div>
    );
  }

  if (!aiEnabled) {
    return (
      <div className="ai-dashboard">
        <div className="ai-error">
          <div className="modal-backdrop" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div className="modal" style={{ display: 'block', position: 'relative', width: 'auto', maxWidth: '500px', backgroundColor: '#2d3748', border: '1px solid #4a5568' }}>
              <div className="modal-header">
                <h3>⚠️ AI Integration Required</h3>
              </div>
              <div className="modal-body">
                <p>You need to add your AI integration information in settings to use the AI Analysis features.</p>
              </div>
              <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                <button className="btn btn-primary" onClick={() => window.location.href = '/'}>
                  Return to Dashboard
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const summary = accuracyData?.summary || {
    overall_accuracy: null,
    bullish_win_rate: null,
    bearish_win_rate: null,
    total_signals: 0,
    evaluated_signals: 0,
    top_model: 'Not enough validated data'
  };

  const hasRate = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  const formatRate = value => hasRate(value) ? `${Number(value).toFixed(1)}%` : '—';

  const availableSymbols = accuracyData?.available_symbols || ['BTC', 'ETH', 'ONT', 'SOL', 'XRP'];

  return (
    <div className="ai-dashboard">
      <ApiKeyRequiredModal
        show={showApiKeyModal}
        onClose={() => setShowApiKeyModal(false)}
        isLightMode={isLightMode}
      />

      {/* Header */}
      <div className="ai-header">
        <div>
          <h1>🤖 AI Sentiment Prediction & Thesis Engine</h1>
          <p style={{ color: 'var(--text-secondary)', margin: '4px 0 0 0', fontSize: '14px' }}>
            Empirical accuracy tracking and multi-model thesis validation across portfolio holdings & watchlist
          </p>
        </div>
        <div className="ai-header-controls">
          <button
            className="btn btn-secondary configure-coins-btn"
            onClick={handleOpenCoinFilterModal}
            title="Configure which coins are displayed"
            style={{ fontSize: '13px', padding: '8px 14px', marginRight: '8px' }}
          >
            ⚙️ Configure Coins {excludedFilterCoins.length > 0 ? `(${activeFilterCoins.length}/${availableCoinFilters.length})` : ''}
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => fetchAccuracyData(dateRange)}
            disabled={accuracyLoading}
            style={{ fontSize: '13px', padding: '8px 14px' }}
          >
            {accuracyLoading ? '⏳ Refreshing...' : '🔄 Refresh Accuracy'}
          </button>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 1. VISUALIZER 1 (TOP SECTION - FULL WIDTH): PERFORMANCE KPIS & REAL CHART */}
      {/* ========================================================================= */}
      <div className="ai-section prediction-visualizer-section">
        {/* KPI Scorecards */}
        <div className="accuracy-kpi-grid">
          <div className="accuracy-kpi-card overall">
            <div className="kpi-label">Overall Accuracy</div>
            <div className="kpi-value glow-text">{formatRate(summary.overall_accuracy)}</div>
            <div className="kpi-subtext">{summary.correct_count || 0} Correct / {summary.evaluated_signals || 0} decisive of {summary.total_signals} fixed-horizon signals; neutral/tracking excluded</div>
          </div>

          <div className="accuracy-kpi-card bullish">
            <div className="kpi-label">Bullish Win Rate</div>
            <div className="kpi-value text-green">{formatRate(summary.bullish_win_rate)}</div>
            <div className="kpi-subtext">{summary.bullish_correct_count || 0} Correct / {summary.bullish_count || 0} decisive Buy theses</div>
          </div>

          <div className="accuracy-kpi-card bearish">
            <div className="kpi-label">Bearish Win Rate</div>
            <div className="kpi-value text-red">{formatRate(summary.bearish_win_rate)}</div>
            <div className="kpi-subtext">{summary.bearish_correct_count || 0} Correct / {summary.bearish_count || 0} decisive Sell/Watch theses</div>
          </div>

          <div className="accuracy-kpi-card model">
            <div className="kpi-label">Top Performing Model</div>
            <div className="kpi-value model-name">{summary.top_model}</div>
            <div className="kpi-subtext">Highest validated prediction rate</div>
          </div>
        </div>

        <SentimentTimelineChart
          signals={accuracyData?.history || []}
          range={dateRange}
          onRangeChange={handleSentimentRangeChange}
          availableSymbols={availableSymbols}
          isLightMode={isLightMode}
        />
      </div>

      {/* ========================================================================= */}
      {/* 2. VISUALIZER 2 (MIDDLE SECTION - FULL WIDTH): PREDICTION LEDGER & BENCHMARKS */}
      {/* ========================================================================= */}
      <div className="ai-section prediction-ledger-section">
        <div className="prediction-ledger-full-width">
          {/* Historical Prediction Ledger Table */}
          <div className="prediction-table-card">
            <div className="table-header-row">
              <h3>📋 Historical Prediction Ledger</h3>
              <div className="ledger-pagination-controls" aria-label="Historical Prediction Ledger pagination">
                <label>
                  Rows
                  <select value={ledgerPageSize} onChange={(event) => setLedgerPageSize(Number(event.target.value))}>
                    {[20, 50, 100, 200].map(size => <option key={size} value={size}>{size}</option>)}
                  </select>
                </label>
                <span>{completedLedgerRows.length ? `${(ledgerPage - 1) * ledgerPageSize + 1}–${Math.min(ledgerPage * ledgerPageSize, completedLedgerRows.length)} of ${completedLedgerRows.length}` : '0 records'}</span>
                <button type="button" onClick={() => setLedgerPage(page => Math.max(1, page - 1))} disabled={ledgerPage <= 1}>‹</button>
                <span>Page {ledgerPage} / {ledgerPageCount}</span>
                <button type="button" onClick={() => setLedgerPage(page => Math.min(ledgerPageCount, page + 1))} disabled={ledgerPage >= ledgerPageCount}>›</button>
              </div>
            </div>

            <div className="prediction-table-container">
              <table className="prediction-ledger-table">
                <thead>
                  <tr>
                    <th style={{ textAlign: 'center', position: 'relative' }}>
                      <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', justifyContent: 'center' }}>
                        <span onClick={() => requestLedgerSort('symbol')} style={{ cursor: 'pointer' }}>
                          Coin{getSortIcon('symbol')}
                        </span>
                        <button
                          type="button"
                          className="ledger-coin-filter-toggle-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            setShowLedgerCoinDropdown(prev => !prev);
                          }}
                          title="Filter coins displayed in ledger"
                          style={{
                            background: excludedFilterCoins.length > 0 ? '#0284c7' : 'rgba(56, 189, 248, 0.15)',
                            border: '1px solid rgba(56, 189, 248, 0.35)',
                            color: excludedFilterCoins.length > 0 ? '#fff' : '#38bdf8',
                            borderRadius: '4px',
                            padding: '2px 6px',
                            fontSize: '11px',
                            cursor: 'pointer',
                            lineHeight: 1
                          }}
                        >
                          ⚙️
                        </button>
                      </div>
                      {showLedgerCoinDropdown && (
                        <div
                          className="ledger-coin-filter-dropdown"
                          onClick={(e) => e.stopPropagation()}
                          style={{
                            position: 'absolute',
                            top: 'calc(100% + 4px)',
                            left: '0',
                            zIndex: 1000,
                            backgroundColor: isLightMode ? '#ffffff' : '#1e293b',
                            border: '1px solid var(--border-color, #334155)',
                            borderRadius: '8px',
                            padding: '12px',
                            boxShadow: '0 10px 30px rgba(0,0,0,0.5)',
                            minWidth: '220px',
                            maxWidth: '280px',
                            textAlign: 'left',
                            color: 'var(--text-primary, #fff)'
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                            <span style={{ fontSize: '12px', fontWeight: 'bold' }}>Filter Coins ({activeFilterCoins.length}/{availableCoinFilters.length})</span>
                            <button
                              type="button"
                              onClick={() => setShowLedgerCoinDropdown(false)}
                              style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: '14px' }}
                            >
                              ✕
                            </button>
                          </div>
                          <div style={{ display: 'flex', gap: '6px', marginBottom: '8px' }}>
                            <button
                              type="button"
                              className="btn btn-secondary"
                              onClick={handleSelectAllInDropdown}
                              style={{ fontSize: '11px', padding: '3px 8px', flex: 1 }}
                            >
                              Select All
                            </button>
                            <button
                              type="button"
                              className="btn btn-secondary"
                              onClick={handleDeselectAllInDropdown}
                              style={{ fontSize: '11px', padding: '3px 8px', flex: 1 }}
                            >
                              Select None
                            </button>
                          </div>
                          <input
                            type="text"
                            placeholder="Search coins..."
                            value={ledgerCoinSearch}
                            onChange={(e) => setLedgerCoinSearch(e.target.value)}
                            style={{
                              width: '100%',
                              padding: '4px 8px',
                              fontSize: '12px',
                              borderRadius: '4px',
                              border: '1px solid var(--border-color, #334155)',
                              background: isLightMode ? '#f8fafc' : '#0f172a',
                              color: 'var(--text-primary, #fff)',
                              marginBottom: '8px',
                              boxSizing: 'border-box'
                            }}
                          />
                          <div className="custom-scrollbar" style={{ maxHeight: '180px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            {availableCoinFilters
                              .filter(c => !ledgerCoinSearch || c.symbol.toLowerCase().includes(ledgerCoinSearch.toLowerCase()))
                              .map(coin => {
                                const isChecked = activeFilterCoins.includes(coin.symbol);
                                return (
                                  <label
                                    key={coin.symbol}
                                    style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', cursor: 'pointer', padding: '2px 4px', borderRadius: '4px' }}
                                  >
                                    <input
                                      type="checkbox"
                                      checked={isChecked}
                                      onChange={() => handleToggleSingleCoinInFilter(coin.symbol)}
                                      style={{ cursor: 'pointer' }}
                                    />
                                    <CryptoIcon symbol={coin.symbol} size={14} />
                                    <span style={{ fontWeight: 600 }}>{coin.symbol}</span>
                                    <span style={{ fontSize: '10px', opacity: 0.6 }}>({coin.source_type === 'portfolio' ? 'P' : 'W'})</span>
                                  </label>
                                );
                              })}
                          </div>
                        </div>
                      )}
                    </th>
                    <th onClick={() => requestLedgerSort('price_at_prediction')} style={{ cursor: 'pointer' }}>Signal Price{getSortIcon('price_at_prediction')}</th>
                    <th onClick={() => requestLedgerSort('created_at')} style={{ cursor: 'pointer' }}>Signal Date{getSortIcon('created_at')}</th>
                    <th onClick={() => requestLedgerSort('created_at_time')} style={{ cursor: 'pointer' }}>Signal Time{getSortIcon('created_at_time')}</th>
                    <th onClick={() => requestLedgerSort('evaluation_price')} style={{ cursor: 'pointer' }}>Evaluation Price{getSortIcon('evaluation_price')}</th>
                    <th onClick={() => requestLedgerSort('evaluated_at')} style={{ cursor: 'pointer' }}>Evaluation Date{getSortIcon('evaluated_at')}</th>
                    <th onClick={() => requestLedgerSort('evaluated_at_time')} style={{ cursor: 'pointer' }}>Evaluation Time{getSortIcon('evaluated_at_time')}</th>
                    <th onClick={() => requestLedgerSort('sentiment')} style={{ cursor: 'pointer' }}>AI Recommendation{getSortIcon('sentiment')}</th>
                    <th onClick={() => requestLedgerSort('outcome_status')} style={{ cursor: 'pointer' }}>Outcome{getSortIcon('outcome_status')}</th>
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    let displayHistory = [...completedLedgerRows];

                    if (ledgerSortConfig && displayHistory.length > 0) {
                      displayHistory = [...displayHistory].sort((a, b) => {
                        if (!a || !b) return 0;
                        let valA = a[ledgerSortConfig.key];
                        let valB = b[ledgerSortConfig.key];
                        
                        if (['evaluation_price', 'price_at_prediction'].includes(ledgerSortConfig.key)) {
                          valA = parseFloat(valA || 0);
                          valB = parseFloat(valB || 0);
                        } else if (['created_at', 'evaluated_at', 'created_at_time', 'evaluated_at_time'].includes(ledgerSortConfig.key)) {
                          const keyToUse = ledgerSortConfig.key.replace('_time', '');
                          valA = new Date(a[keyToUse] || 0).getTime();
                          valB = new Date(b[keyToUse] || 0).getTime();
                        } else if (['sentiment', 'outcome_status', 'symbol'].includes(ledgerSortConfig.key)) {
                          valA = (valA || '').toString().toLowerCase();
                          valB = (valB || '').toString().toLowerCase();
                        }

                        if (valA < valB) return ledgerSortConfig.direction === 'asc' ? -1 : 1;
                        if (valA > valB) return ledgerSortConfig.direction === 'asc' ? 1 : -1;
                        return 0;
                      });
                    } else if (displayHistory.length > 0) {
                      // Default sort: strictly by updated Date & Time descending
                      displayHistory = [...displayHistory].sort((a, b) => {
                        const timeA = new Date(a.evaluated_at || a.created_at || 0).getTime();
                        const timeB = new Date(b.evaluated_at || b.created_at || 0).getTime();
                        return timeB - timeA;
                      });
                    }

                    if (displayHistory && displayHistory.length > 0) {
                      const pageRows = displayHistory.slice((ledgerPage - 1) * ledgerPageSize, ledgerPage * ledgerPageSize);
                      return pageRows.map((row) => {
                        if (!row) return null;
                        const isBullish = ['definitely buy', 'consider buying', 'buy immediately', 'strong buy', 'buy'].includes((row.sentiment || '').toLowerCase());
                        const isBearish = ['consider selling', 'sell immediately', 'avoid', 'strong sell', 'do not buy', 'sell'].includes((row.sentiment || '').toLowerCase());
                        const signalBadgeClass = isBullish ? 'badge-buy' : isBearish ? 'badge-sell' : 'badge-watch';
                        const coinStat = coinAccuracyMap?.[row.symbol] || { tooltip: `${row.symbol} Accuracy: Tracking` };

                        return (
                          <tr key={row.id}>
                            <td className="symbol-cell" style={{ textAlign: 'center' }}>
                              <div className="coin-cell-content" title={coinStat.tooltip} style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', justifyContent: 'center' }}>
                                <CryptoIcon symbol={row.symbol} size={18} />
                                <span className="coin-pill">
                                  {row.symbol}
                                </span>
                                <span
                                  className={`source-badge ${row.source_type === 'portfolio' ? 'source-p' : 'source-w'}`}
                                  title={row.source_type === 'portfolio' ? 'Portfolio Asset' : 'Watchlist Asset'}
                                >
                                  {row.source_type === 'portfolio' ? 'P' : 'W'}
                                </span>
                              </div>
                            </td>
                            <td className="price-cell">
                              ${parseFloat(row.price_at_prediction || 0) > 100
                                ? parseFloat(row.price_at_prediction || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })
                                : parseFloat(row.price_at_prediction || 0).toFixed(4)}
                            </td>
                            <td className="date-cell">{row.date || '—'}</td>
                            <td className="time-cell">{row.time || '—'}</td>
                            <td className="price-cell">
                              {row.evaluation_price == null ? '—' : `$${parseFloat(row.evaluation_price || 0) > 100
                                ? parseFloat(row.evaluation_price || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })
                                : parseFloat(row.evaluation_price || 0).toFixed(4)}`}
                            </td>
                            <td className="date-cell" style={{ color: 'var(--text-primary)' }}>{row.eval_date || '—'}</td>
                            <td className="time-cell" style={{ color: 'var(--text-primary)' }}>{row.eval_time || '—'}</td>
                            <td>
                              <span className={`signal-pill ${signalBadgeClass}`} title={row.sentiment_reason || ''}>
                                {row.sentiment || '—'}
                              </span>
                            </td>
                            <td>
                              {(() => {
                                const rawDelta = row.price_delta_pct !== undefined ? row.price_delta_pct : row.outcome_pct;
                                const deltaFormatted = rawDelta !== undefined && rawDelta !== null
                                  ? `${rawDelta >= 0 ? '+' : ''}${parseFloat(rawDelta).toFixed(2)}%`
                                  : '0.00%';

                                if (row.outcome_status === 'correct') {
                                  return (
                                    <span className="outcome-pill outcome-correct" title={row.outcome_reason || ''}>
                                      ✅ Correct ({deltaFormatted})
                                    </span>
                                  );
                                } else if (row.outcome_status === 'wrong') {
                                  return (
                                    <span className="outcome-pill outcome-wrong" title={row.outcome_reason || ''}>
                                      ❌ Wrong ({deltaFormatted})
                                    </span>
                                  );
                                } else if (row.outcome_status === 'neutral') {
                                  return (
                                    <span className="outcome-pill outcome-neutral" title={row.outcome_reason || ''} style={{ background: 'rgba(100, 116, 139, 0.15)', color: 'var(--text-secondary)' }}>
                                      ⚖️ Neutral ({deltaFormatted})
                                    </span>
                                  );
                                } else {
                                  return (
                                    <span className="outcome-pill outcome-neutral" title={row.outcome_reason || ''}>
                                      — Not Scored
                                    </span>
                                  );
                                }
                              })()}
                            </td>
                          </tr>
                        );
                      });
                    }

                    return (
                      <tr>
                        <td colSpan="9" style={{ textAlign: 'center', padding: '32px', color: 'var(--text-secondary)' }}>
                          {accuracyData?.history?.length > 0
                            ? 'No completed sentiment outcomes match the selected coin filters yet.'
                            : 'No completed sentiment outcomes yet. New predictions appear after their fixed forecast horizons are reached.'}
                        </td>
                      </tr>
                    );
                  })()}
                </tbody>
              </table>
            </div>
            </div>
          </div>
        </div>

        {/* Right Column: Signal Recommendation Accuracy & Model Comparison */}
        <div className="benchmark-split-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginTop: '20px' }}>
            {/* Recommendation Type Breakdown */}
            <div className="benchmark-card">
              <h3>🎯 Recommendation Type Accuracy</h3>
              <p className="benchmark-subtext">Empirical win rate by exact recommendation signal</p>

              <div className="distribution-bars">
                {recommendationBreakdown && recommendationBreakdown.length > 0 ? (
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
                  <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>No recommendations recorded yet.</p>
                )}
              </div>
            </div>

            {/* AI Model Performance Leaderboard */}
            <div className="benchmark-card">
              <h3>🏆 AI Model Accuracy Leaderboard</h3>
              <p className="benchmark-subtext">Accuracy comparison across active AI providers</p>

              <div className="model-leaderboard-list">
                {modelBreakdown && modelBreakdown.length > 0 ? (
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

      {/* ========================================================================= */}
      {/* 3. CONFIGURE COINS MODAL (FILTER PREDICTION LEDGER) */}
      {/* ========================================================================= */}
      {showCoinFilterModal && (
        <div className="modal-overlay" onClick={() => setShowCoinFilterModal(false)}>
          <div className="modal-content coin-filter-modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>⚙️ Configure Visible Coins in Ledger</h3>
              <button
                className="modal-close"
                onClick={() => setShowCoinFilterModal(false)}
                title="Close"
              >
                ×
              </button>
            </div>

            <div className="modal-body">
              <p style={{ color: 'var(--text-secondary, #94a3b8)', fontSize: '13.5px', margin: '0 0 14px 0', lineHeight: '1.5' }}>
                Select which portfolio and watchlist coins appear in the Historical Prediction Ledger table.
              </p>

              {availableCoinFilters.length === 0 ? (
                <p style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: '20px' }}>
                  No coins found in sentiment history.
                </p>
              ) : (
                <>
                  <div className="select-all-container" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', paddingBottom: '10px', borderBottom: '1px solid var(--border-color, #334155)' }}>
                    <label className="select-all-label" style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontWeight: 600, fontSize: '13px', color: 'var(--text-primary, #f8fafc)' }}>
                      <input
                        type="checkbox"
                        checked={tempFilterCoins.length === availableCoinFilters.length && availableCoinFilters.length > 0}
                        onChange={(e) => e.target.checked ? handleSelectAllFilterCoins() : handleDeselectAllFilterCoins()}
                      />
                      Select All ({tempFilterCoins.length}/{availableCoinFilters.length})
                    </label>
                    <div style={{ display: 'flex', gap: '6px' }}>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={handleSelectAllFilterCoins}
                        style={{ fontSize: '11px', padding: '4px 8px' }}
                      >
                        All
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={handleDeselectAllFilterCoins}
                        style={{ fontSize: '11px', padding: '4px 8px' }}
                      >
                        None
                      </button>
                    </div>
                  </div>

                  <div className="coin-filter-grid">
                    {availableCoinFilters.map(coin => {
                      const isChecked = tempFilterCoins.includes(coin.symbol);
                      return (
                        <label
                          key={coin.symbol}
                          className={`coin-filter-item ${isChecked ? 'selected' : ''}`}
                          style={{ cursor: 'pointer' }}
                        >
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => handleToggleFilterCoin(coin.symbol)}
                          />
                          <CryptoIcon symbol={coin.symbol} size={16} />
                          <span className="coin-symbol-title">{coin.symbol}</span>
                          <span className={`source-badge ${coin.source_type === 'portfolio' ? 'source-p' : 'source-w'}`}>
                            {coin.source_type === 'portfolio' ? 'P' : 'W'}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </>
              )}
            </div>

            <div className="modal-actions" style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', padding: '16px 20px', borderTop: '1px solid var(--border-color, #334155)' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setShowCoinFilterModal(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleApplyCoinFilter}
                disabled={tempFilterCoins.length === 0}
              >
                Apply Filters ({tempFilterCoins.length})
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AIDashboard;
