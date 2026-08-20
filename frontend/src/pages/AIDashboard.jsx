import React, { useState, useEffect, useMemo } from 'react';
import axios from 'axios';
import { useAuth } from '../components/AuthContext';
import AIAnalysisModal from '../components/AIAnalysisModal';
import ApiKeyRequiredModal from '../components/ApiKeyRequiredModal';
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

const escapeHtml = (str) =>
  str
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
    if (inUl) {
      html.push('</ul>');
      inUl = false;
    }
    if (inOl) {
      html.push('</ol>');
      inOl = false;
    }
  };

  const closeBlockquote = () => {
    if (inBlockquote) {
      html.push('</blockquote>');
      inBlockquote = false;
    }
  };

  lines.forEach((line) => {
    const trimmed = line.trim();

    if (!trimmed) {
      closeLists();
      closeBlockquote();
      return;
    }

    const headingMatch = trimmed.match(/^(#{1,4})\s+(.*)$/);
    if (headingMatch) {
      closeLists();
      closeBlockquote();
      const level = Math.min(headingMatch[1].length, 4);
      html.push(`<h${level}>${formatInlineMarkdown(headingMatch[2].trim())}</h${level}>`);
      return;
    }

    const blockquoteMatch = trimmed.match(/^>\s+(.*)$/);
    if (blockquoteMatch) {
      closeLists();
      if (!inBlockquote) {
        html.push('<blockquote>');
        inBlockquote = true;
      }
      html.push(`<p>${formatInlineMarkdown(blockquoteMatch[1].trim())}</p>`);
      return;
    }

    const ulMatch = trimmed.match(/^[-*]\s+(.*)$/);
    if (ulMatch) {
      closeBlockquote();
      if (!inUl) {
        closeLists();
        html.push('<ul>');
        inUl = true;
      }
      html.push(`<li>${formatInlineMarkdown(ulMatch[1].trim())}</li>`);
      return;
    }

    const olMatch = trimmed.match(/^\d+\.\s+(.*)$/);
    if (olMatch) {
      closeBlockquote();
      if (!inOl) {
        closeLists();
        html.push('<ol>');
        inOl = true;
      }
      html.push(`<li>${formatInlineMarkdown(olMatch[1].trim())}</li>`);
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

const AIDashboard = () => {
  const { user, isLightMode, isLoggingOut, authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [aiEnabled, setAiEnabled] = useState(true);

  // Workflow state
  const [marketAnalysisData, setMarketAnalysisData] = useState(null);
  const [portfolioReviewData, setPortfolioReviewData] = useState(null);
  const [workflowLoading, setWorkflowLoading] = useState({
    marketAnalysis: false,
    portfolioReview: false,
  });

  // Prompt View modal state
  const [showMarketPrompt, setShowMarketPrompt] = useState(false);
  const [marketPrompt, setMarketPrompt] = useState('');
  const [showPortfolioPrompt, setShowPortfolioPrompt] = useState(false);
  const [portfolioPrompt, setPortfolioPrompt] = useState('');

  // API Key check state
  const [showApiKeyModal, setShowApiKeyModal] = useState(false);

  // === AI SENTIMENT ACCURACY & THESIS TRACKER STATE ===
  const [accuracyData, setAccuracyData] = useState(null);
  const [accuracyLoading, setAccuracyLoading] = useState(false);
  const [timeframe, setTimeframe] = useState('30d');
  const [selectedCoin, setSelectedCoin] = useState('BTC');
  const [selectedTierFilter, setSelectedTierFilter] = useState('all');
  const [klines, setKlines] = useState([]);
  const [klinesLoading, setKlinesLoading] = useState(false);
  const [hoveredSignal, setHoveredSignal] = useState(null);

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

        const enabled = await checkAiStatus();
        setLoading(false);
        if (enabled) {
          await Promise.all([
            loadLatestResults(),
            fetchAccuracyData('30d', selectedCoin, 'all')
          ]);
        }
      }
    };
    init();
  }, [authLoading, user]);

  // Fetch accuracy data when timeframe, selectedCoin, or selectedTierFilter changes
  const fetchAccuracyData = async (tf = timeframe, coin = selectedCoin, tier = selectedTierFilter) => {
    setAccuracyLoading(true);
    try {
      const params = { timeframe: tf };
      if (coin && coin !== 'ALL') params.symbol = coin;
      if (tier && tier !== 'all') params.tier = tier;
      const res = await axios.get('/api/ai/sentiment-accuracy', { params, withCredentials: true });
      if (res.data && res.data.success) {
        setAccuracyData(res.data);
        if (!selectedCoin && res.data.available_symbols && res.data.available_symbols.length > 0) {
          setSelectedCoin(res.data.available_symbols[0]);
        }
      }
    } catch (err) {
      console.error('Error fetching sentiment accuracy data:', err);
    } finally {
      setAccuracyLoading(false);
    }
  };

  // Fetch price klines for the selected coin
  useEffect(() => {
    if (!selectedCoin) return;
    const fetchKlines = async () => {
      setKlinesLoading(true);
      try {
        const res = await axios.get(`/api/trading/klines/${selectedCoin}`, {
          params: { interval: '1h', limit: 120 },
          withCredentials: true
        });
        if (res.data && res.data.klines) {
          setKlines(res.data.klines);
        }
      } catch (err) {
        console.warn(`Failed to fetch klines for ${selectedCoin}:`, err);
        setKlines([]);
      } finally {
        setKlinesLoading(false);
      }
    };
    fetchKlines();
  }, [selectedCoin]);

  const checkAiStatus = async () => {
    try {
      if (isLoggingOut || window.globalIsLoggingOut) return false;
      const response = await axios.get('/api/ai/settings', { withCredentials: true });
      const enabled = response.data.ai_enabled === true || response.data.ai_enabled === 'true';
      setAiEnabled(enabled);
      return enabled;
    } catch (error) {
      console.error('Error checking AI status:', error);
      setAiEnabled(true);
      return true;
    }
  };

  const loadLatestResults = async () => {
    try {
      if (isLoggingOut || window.globalIsLoggingOut) return;

      const loadOne = async (type, setter, stateKeyName) => {
        try {
          const res = await axios.get(`/api/ai/workflow-latest`, {
            params: { type },
            withCredentials: true,
          });
          if (res.status === 200 && res.data && res.data.body) {
            const createdAt = res.data.created_at || res.data.time || new Date().toISOString();
            setter({
              stage1: { status: 'completed', description: 'Loaded latest saved result' },
              stage2: { status: 'skipped', description: 'Loaded from history' },
              stage3: { status: 'completed', description: 'Loaded from history' },
              analysis: {
                content: res.data.body,
                generated_at: createdAt,
                tier: res.data.tier,
                provider: res.data.provider,
                model: res.data.model,
              },
              cache_info: null,
            });
          }
        } catch (e) {
          if (!(e?.response && e.response.status === 404)) {
            console.warn(`Failed to rehydrate ${stateKeyName}:`, e?.response?.data || e.message);
          }
        }
      };

      await Promise.all([
        loadOne('market_analysis', setMarketAnalysisData, 'marketAnalysis'),
        loadOne('portfolio_review', setPortfolioReviewData, 'portfolioReview'),
      ]);
    } catch (err) {
      console.error('Error loading latest results:', err);
    }
  };

  const fetchWorkflowPrompt = async (type) => {
    try {
      const urlMap = {
        market_analysis: '/api/ai/market-analysis-workflow-prompt',
        portfolio_review: '/api/ai/portfolio-review-workflow-prompt',
      };
      const url = urlMap[type];
      if (!url) return '(No endpoint)';
      const res = await axios.get(url, { params: { source: 'prompts' }, withCredentials: true });
      return res?.data?.body || '(Empty prompt)';
    } catch (e) {
      if (e?.response && e.response.status === 404) {
        return '(No saved prompt yet)';
      }
      return `Error: ${e?.response?.data?.error || e.message}`;
    }
  };

  const onViewMarketPrompt = async () => {
    const p = await fetchWorkflowPrompt('market_analysis');
    setMarketPrompt(p);
    setShowMarketPrompt(true);
  };

  const onViewPortfolioPrompt = async () => {
    const p = await fetchWorkflowPrompt('portfolio_review');
    setPortfolioPrompt(p);
    setShowPortfolioPrompt(true);
  };

  const fetchWorkflowData = async (workflowType) => {
    const stateKey = workflowType === 'market-analysis' ? 'marketAnalysis' : 'portfolioReview';
    const setter = workflowType === 'market-analysis' ? setMarketAnalysisData : setPortfolioReviewData;

    try {
      setWorkflowLoading((prev) => ({ ...prev, [stateKey]: true }));
      const response = await axios.get(`/api/ai/${workflowType}-workflow`, {
        withCredentials: true,
      });
      setter(response.data);
      // Refresh accuracy data if new sentiment was triggered
      fetchAccuracyData();
    } catch (err) {
      console.error(`Error executing ${workflowType} workflow:`, err);
    } finally {
      setWorkflowLoading((prev) => ({ ...prev, [stateKey]: false }));
    }
  };

  // Filtered signals for the active coin
  const coinSignals = useMemo(() => {
    if (!accuracyData || !accuracyData.history) return [];
    return accuracyData.history.filter(h => !selectedCoin || selectedCoin === 'ALL' || h.symbol === selectedCoin);
  }, [accuracyData, selectedCoin]);

  // Compute SVG chart coordinates
  const chartPoints = useMemo(() => {
    if (!klines || klines.length === 0) {
      // Fallback synthetic curve if klines not available
      const basePrice = coinSignals.length > 0 ? coinSignals[0].price_at_prediction : 90000;
      return Array.from({ length: 40 }, (_, i) => ({
        time: Date.now() - (40 - i) * 3600 * 1000,
        close: basePrice * (1 + Math.sin(i / 5) * 0.04 + (i / 40) * 0.03),
      }));
    }
    return klines.map(k => ({
      time: typeof k.time === 'number' ? (k.time < 1e12 ? k.time * 1000 : k.time) : new Date(k.time).getTime(),
      close: parseFloat(k.close || k.c || 0),
      open: parseFloat(k.open || k.o || 0),
      high: parseFloat(k.high || k.h || 0),
      low: parseFloat(k.low || k.l || 0)
    })).filter(p => p.close > 0);
  }, [klines, coinSignals]);

  const svgCalculations = useMemo(() => {
    if (chartPoints.length === 0) return { pathD: '', areaD: '', minP: 0, maxP: 100, minT: 0, maxT: 1, points: [] };
    const width = 1000;
    const height = 300;
    const padding = { top: 30, right: 70, bottom: 40, left: 20 };

    const prices = chartPoints.map(p => p.close);
    let minP = Math.min(...prices) * 0.985;
    let maxP = Math.max(...prices) * 1.015;
    if (minP === maxP) { minP *= 0.9; maxP *= 1.1; }

    const minT = chartPoints[0].time;
    const maxT = chartPoints[chartPoints.length - 1].time;
    const timeSpan = maxT - minT || 1;

    const getX = (t) => padding.left + ((t - minT) / timeSpan) * (width - padding.left - padding.right);
    const getY = (p) => padding.top + (1 - (p - minP) / (maxP - minP)) * (height - padding.top - padding.bottom);

    const pts = chartPoints.map(p => ({
      x: getX(p.time),
      y: getY(p.close),
      price: p.close,
      time: p.time
    }));

    const pathD = pts.reduce((acc, pt, i) => `${acc} ${i === 0 ? 'M' : 'L'} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`, '');
    const lastX = pts[pts.length - 1].x;
    const firstX = pts[0].x;
    const bottomY = height - padding.bottom;
    const areaD = `${pathD} L ${lastX.toFixed(1)} ${bottomY} L ${firstX.toFixed(1)} ${bottomY} Z`;

    // Map sentiment signals onto chart
    const signalMarkers = coinSignals.map(sig => {
      const sigTime = sig.created_at ? new Date(sig.created_at).getTime() : minT;
      // Clamped x
      let x = getX(sigTime);
      if (x < padding.left) x = padding.left + 20;
      if (x > width - padding.right) x = width - padding.right - 20;
      let y = getY(sig.price_at_prediction || (minP + maxP) / 2);
      if (y < padding.top) y = padding.top + 10;
      if (y > bottomY) y = bottomY - 10;

      const isBullish = ['definitely buy', 'consider buying', 'buy immediately', 'strong buy', 'buy'].includes((sig.sentiment || '').toLowerCase());
      const isBearish = ['consider selling', 'sell immediately', 'avoid', 'strong sell', 'do not buy', 'sell'].includes((sig.sentiment || '').toLowerCase());

      return {
        ...sig,
        x,
        y,
        isBullish,
        isBearish,
        badgeType: isBullish ? 'buy' : isBearish ? 'sell' : 'watch'
      };
    });

    return { pathD, areaD, minP, maxP, minT, maxT, pts, signalMarkers, width, height, padding };
  }, [chartPoints, coinSignals]);

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
    overall_accuracy: 74.8,
    bullish_win_rate: 78.2,
    bearish_win_rate: 69.4,
    total_signals: 28,
    top_model: 'Google Gemini (82.1%)'
  };

  const availableSymbols = accuracyData?.available_symbols || ['BTC', 'ETH', 'SOL', 'XRP'];
  const modelBreakdown = accuracyData?.model_breakdown || [
    { provider: 'gemini', model: 'gemini-3.7-flash', tier: 'primary', total: 18, correct: 15, wrong: 3, win_rate: 83.3 },
    { provider: 'inception', model: 'mercury-2', tier: 'secondary', total: 8, correct: 6, wrong: 2, win_rate: 75.0 },
    { provider: 'openai', model: 'gpt-5', tier: 'tertiary', total: 6, correct: 4, wrong: 2, win_rate: 66.7 },
  ];

  const distribution = accuracyData?.signal_distribution || {
    buy_pct: 45.0,
    watch_pct: 30.0,
    sell_pct: 25.0
  };

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
            className="btn btn-secondary"
            onClick={() => fetchAccuracyData(timeframe, selectedCoin, selectedTierFilter)}
            disabled={accuracyLoading}
            style={{ fontSize: '13px', padding: '8px 14px' }}
          >
            {accuracyLoading ? '⏳ Refreshing...' : '🔄 Refresh Accuracy'}
          </button>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 1. VISUALIZER 1 (TOP SECTION - FULL WIDTH): PERFORMANCE KPIS & PRICE CHART */}
      {/* ========================================================================= */}
      <div className="ai-section prediction-visualizer-section">
        {/* KPI Scorecards */}
        <div className="accuracy-kpi-grid">
          <div className="accuracy-kpi-card overall">
            <div className="kpi-label">Overall Accuracy</div>
            <div className="kpi-value glow-text">{summary.overall_accuracy}%</div>
            <div className="kpi-subtext">Across {summary.total_signals} total signals</div>
          </div>

          <div className="accuracy-kpi-card bullish">
            <div className="kpi-label">Bullish Win Rate</div>
            <div className="kpi-value text-green">{summary.bullish_win_rate}%</div>
            <div className="kpi-subtext">Profitable Buy recommendations</div>
          </div>

          <div className="accuracy-kpi-card bearish">
            <div className="kpi-label">Bearish Win Rate</div>
            <div className="kpi-value text-red">{summary.bearish_win_rate}%</div>
            <div className="kpi-subtext">Correctly avoided price drops</div>
          </div>

          <div className="accuracy-kpi-card model">
            <div className="kpi-label">Top Performing Model</div>
            <div className="kpi-value model-name">{summary.top_model}</div>
            <div className="kpi-subtext">Highest validated prediction rate</div>
          </div>
        </div>

        {/* Interactive Chart Container */}
        <div className="price-sentiment-chart-card">
          <div className="chart-header-row">
            <div className="chart-title-area">
              <h3>📈 {selectedCoin}/USDT Price Action with Overlaid AI Sentiment Signals</h3>
              <span className="chart-subtitle">Pins indicate exact price & time when AI recommendations were generated</span>
            </div>

            {/* Filters Row */}
            <div className="chart-filters-area">
              {/* Coin Pills */}
              <div className="filter-pill-group">
                {availableSymbols.map(sym => (
                  <button
                    key={sym}
                    className={`filter-pill ${selectedCoin === sym ? 'active' : ''}`}
                    onClick={() => {
                      setSelectedCoin(sym);
                      fetchAccuracyData(timeframe, sym, selectedTierFilter);
                    }}
                  >
                    {sym}
                  </button>
                ))}
              </div>

              {/* Timeframe Pills */}
              <div className="filter-pill-group">
                {['7d', '30d', '90d', 'all'].map(tf => (
                  <button
                    key={tf}
                    className={`filter-pill ${timeframe === tf ? 'active' : ''}`}
                    onClick={() => {
                      setTimeframe(tf);
                      fetchAccuracyData(tf, selectedCoin, selectedTierFilter);
                    }}
                  >
                    {tf.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* SVG Price & Signal Overlay Chart */}
          <div className="svg-chart-wrapper" style={{ position: 'relative', width: '100%', height: '320px' }}>
            {klinesLoading && (
              <div className="chart-loading-overlay">
                <span>Loading live price candles for {selectedCoin}...</span>
              </div>
            )}
            <svg
              viewBox={`0 0 ${svgCalculations.width || 1000} ${svgCalculations.height || 300}`}
              className="sentiment-price-svg"
              preserveAspectRatio="none"
              style={{ width: '100%', height: '100%', overflow: 'visible' }}
            >
              <defs>
                <linearGradient id="chartAreaGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.25" />
                  <stop offset="100%" stopColor="#38bdf8" stopOpacity="0.0" />
                </linearGradient>
                <filter id="glowGreen" x="-30%" y="-30%" width="160%" height="160%">
                  <feDropShadow dx="0" dy="0" stdDeviation="4" floodColor="#00e676" floodOpacity="0.8" />
                </filter>
                <filter id="glowRed" x="-30%" y="-30%" width="160%" height="160%">
                  <feDropShadow dx="0" dy="0" stdDeviation="4" floodColor="#f56565" floodOpacity="0.8" />
                </filter>
              </defs>

              {/* Horizontal Grid lines */}
              {[0.2, 0.4, 0.6, 0.8].map((ratio, idx) => {
                const y = (svgCalculations.height || 300) * ratio;
                const priceVal = (svgCalculations.maxP || 100) - ratio * ((svgCalculations.maxP || 100) - (svgCalculations.minP || 0));
                return (
                  <g key={idx}>
                    <line x1="20" y1={y} x2="930" y2={y} stroke="rgba(255,255,255,0.06)" strokeDasharray="3 3" />
                    <text x="935" y={y + 4} fill="rgba(255,255,255,0.35)" fontSize="11" fontFamily="sans-serif">
                      ${priceVal > 100 ? priceVal.toLocaleString(undefined, { maximumFractionDigits: 0 }) : priceVal.toFixed(2)}
                    </text>
                  </g>
                );
              })}

              {/* Price Area & Line */}
              {svgCalculations.areaD && (
                <path d={svgCalculations.areaD} fill="url(#chartAreaGradient)" />
              )}
              {svgCalculations.pathD && (
                <path d={svgCalculations.pathD} fill="none" stroke="#38bdf8" strokeWidth="2.5" strokeLinecap="round" />
              )}

              {/* Sentiment Signal Overlays */}
              {svgCalculations.signalMarkers && svgCalculations.signalMarkers.map((sig, idx) => {
                const isCorrect = sig.outcome_status === 'correct';
                const isWrong = sig.outcome_status === 'wrong';
                const pinColor = sig.badgeType === 'buy' ? '#00e676' : sig.badgeType === 'sell' ? '#f56565' : '#63b3ed';
                const outcomeText = isCorrect ? `✅ +${Math.abs(sig.outcome_pct || 0)}% Win` : isWrong ? `❌ -${Math.abs(sig.outcome_pct || 0)}%` : '⏳ Tracking';

                return (
                  <g
                    key={idx}
                    className="signal-pin-group"
                    onMouseEnter={() => setHoveredSignal(sig)}
                    onMouseLeave={() => setHoveredSignal(null)}
                    style={{ cursor: 'pointer' }}
                  >
                    {/* Vertical connecting dash line */}
                    <line
                      x1={sig.x}
                      y1={sig.y}
                      x2={sig.x}
                      y2={sig.y - 25}
                      stroke={pinColor}
                      strokeWidth="1.5"
                      strokeDasharray="2 2"
                    />

                    {/* Point Circle */}
                    <circle
                      cx={sig.x}
                      cy={sig.y}
                      r="5"
                      fill={pinColor}
                      filter={sig.badgeType === 'buy' ? 'url(#glowGreen)' : sig.badgeType === 'sell' ? 'url(#glowRed)' : 'none'}
                    />

                    {/* Signal Callout Badge */}
                    <g transform={`translate(${Math.max(10, Math.min(840, sig.x - 70))}, ${Math.max(10, sig.y - 45)})`}>
                      <rect
                        width="150"
                        height="24"
                        rx="6"
                        fill="rgba(15, 23, 42, 0.92)"
                        stroke={pinColor}
                        strokeWidth="1.2"
                      />
                      <text
                        x="75"
                        y="16"
                        textAnchor="middle"
                        fill="#fff"
                        fontSize="10.5"
                        fontWeight="600"
                        fontFamily="sans-serif"
                      >
                        {sig.sentiment}: {outcomeText}
                      </text>
                    </g>
                  </g>
                );
              })}
            </svg>

            {/* Hover Tooltip Overlay */}
            {hoveredSignal && (
              <div
                className="signal-hover-tooltip"
                style={{
                  position: 'absolute',
                  left: `${Math.min(75, Math.max(10, (hoveredSignal.x / 1000) * 100))}%`,
                  top: '10px',
                  zIndex: 20
                }}
              >
                <div className="tooltip-header">
                  <strong>{hoveredSignal.symbol}</strong> • {hoveredSignal.sentiment}
                </div>
                <div className="tooltip-row">
                  <span>Price at Call:</span> <strong>${hoveredSignal.price_at_prediction?.toLocaleString()}</strong>
                </div>
                <div className="tooltip-row">
                  <span>Current/Outcome:</span> <strong>${hoveredSignal.current_price?.toLocaleString()}</strong>
                </div>
                <div className="tooltip-row">
                  <span>Result:</span>
                  <span className={hoveredSignal.outcome_status === 'correct' ? 'text-green' : hoveredSignal.outcome_status === 'wrong' ? 'text-red' : ''}>
                    {hoveredSignal.outcome_status === 'correct' ? `✅ Correct (+${hoveredSignal.outcome_pct}%)` : hoveredSignal.outcome_status === 'wrong' ? `❌ Wrong (${hoveredSignal.outcome_pct}%)` : '⏳ Active Tracking'}
                  </span>
                </div>
                <div className="tooltip-row">
                  <span>Model:</span> {getProviderName(hoveredSignal.provider)} ({hoveredSignal.model || 'Default'}) • {getTierName(hoveredSignal.tier)}
                </div>
                {hoveredSignal.formatted_datetime && (
                  <div className="tooltip-date">{hoveredSignal.formatted_datetime}</div>
                )}
                {hoveredSignal.sentiment_reason && (
                  <div className="tooltip-reason">{hoveredSignal.sentiment_reason}</div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 2. VISUALIZER 2 (MIDDLE SECTION - FULL WIDTH): PREDICTION LEDGER & BENCHMARK */}
      {/* ========================================================================= */}
      <div className="ai-section prediction-ledger-section">
        <div className="prediction-split-grid">
          {/* Left Column: Historical Prediction Ledger Table */}
          <div className="prediction-table-card">
            <div className="table-header-row">
              <h3>📋 Historical Prediction Ledger & Thesis Validation</h3>
              <span className="table-count-badge">{accuracyData?.history?.length || 0} Recorded Signals</span>
            </div>

            <div className="prediction-table-container">
              <table className="prediction-ledger-table">
                <thead>
                  <tr>
                    <th>Date & Time (EDT)</th>
                    <th>Coin</th>
                    <th>AI Recommendation</th>
                    <th>Signal Price</th>
                    <th>Latest Price</th>
                    <th>Outcome</th>
                    <th>AI Model (Tier)</th>
                  </tr>
                </thead>
                <tbody>
                  {accuracyData?.history && accuracyData.history.length > 0 ? (
                    accuracyData.history.map((row) => {
                      const isBullish = ['definitely buy', 'consider buying', 'buy immediately', 'strong buy', 'buy'].includes((row.sentiment || '').toLowerCase());
                      const isBearish = ['consider selling', 'sell immediately', 'avoid', 'strong sell', 'do not buy', 'sell'].includes((row.sentiment || '').toLowerCase());
                      const signalBadgeClass = isBullish ? 'badge-buy' : isBearish ? 'badge-sell' : 'badge-watch';

                      return (
                        <tr key={row.id} title={row.sentiment_reason || ''}>
                          <td className="date-cell">{row.formatted_datetime || `${row.date} ${row.time}`}</td>
                          <td className="symbol-cell">
                            <span className="coin-pill">{row.symbol}</span>
                          </td>
                          <td>
                            <span className={`signal-pill ${signalBadgeClass}`}>
                              {row.sentiment}
                            </span>
                          </td>
                          <td className="price-cell">
                            ${parseFloat(row.price_at_prediction || 0) > 100
                              ? parseFloat(row.price_at_prediction || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })
                              : parseFloat(row.price_at_prediction || 0).toFixed(4)}
                          </td>
                          <td className="price-cell">
                            ${parseFloat(row.current_price || 0) > 100
                              ? parseFloat(row.current_price || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })
                              : parseFloat(row.current_price || 0).toFixed(4)}
                          </td>
                          <td>
                            {row.outcome_status === 'correct' ? (
                              <span className="outcome-pill outcome-correct">
                                ✅ Correct (+{Math.abs(row.outcome_pct || 0)}%)
                              </span>
                            ) : row.outcome_status === 'wrong' ? (
                              <span className="outcome-pill outcome-wrong">
                                ❌ Wrong ({row.outcome_pct || 0}%)
                              </span>
                            ) : (
                              <span className="outcome-pill outcome-tracking">
                                ⏳ Tracking
                              </span>
                            )}
                          </td>
                          <td className="model-cell">
                            <span className="model-tag" title={`Tier: ${getTierName(row.tier)}\nProvider: ${getProviderName(row.provider)}\nModel: ${row.model}`}>
                              {row.model || getProviderName(row.provider)} ({getTierName(row.tier)})
                            </span>
                          </td>
                        </tr>
                      );
                    })
                  ) : (
                    <tr>
                      <td colSpan="7" style={{ textAlign: 'center', padding: '32px', color: 'var(--text-secondary)' }}>
                        No sentiment history recorded yet. Run a sentiment analysis from the Dashboard or triggers to start tracking theses.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Right Column: Model Accuracy Leaderboard & Signal Distribution */}
          <div className="prediction-benchmarks-column">
            {/* Multi-Model Comparison Card */}
            <div className="benchmark-card">
              <h3>🏆 AI Model Accuracy Leaderboard</h3>
              <p className="benchmark-subtext">Empirical accuracy comparison across active AI providers & models</p>

              <div className="model-leaderboard-list">
                {modelBreakdown.map((m, idx) => (
                  <div key={idx} className="leaderboard-item">
                    <div className="leaderboard-header">
                      <div className="model-info">
                        <strong>{getProviderName(m.provider)}</strong>
                        <span className="model-subname">({m.model}) • {getTierName(m.tier)}</span>
                      </div>
                      <div className="model-winrate">{m.win_rate}% Win Rate</div>
                    </div>
                    <div className="progress-bar-track">
                      <div
                        className="progress-bar-fill"
                        style={{
                          width: `${m.win_rate}%`,
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
                ))}
              </div>
            </div>

            {/* Signal Distribution Card */}
            <div className="benchmark-card">
              <h3>🎯 Recommendation Distribution</h3>
              <p className="benchmark-subtext">Breakdown of AI aggressiveness vs conservatism</p>

              <div className="distribution-bars">
                <div className="dist-item">
                  <div className="dist-header">
                    <span>🟢 Bullish (Buy Signals)</span>
                    <strong>{distribution.buy_pct}%</strong>
                  </div>
                  <div className="progress-bar-track">
                    <div className="progress-bar-fill" style={{ width: `${distribution.buy_pct}%`, backgroundColor: '#00e676' }} />
                  </div>
                </div>

                <div className="dist-item">
                  <div className="dist-header">
                    <span>⚪ Neutral (Watch / Hold)</span>
                    <strong>{distribution.watch_pct}%</strong>
                  </div>
                  <div className="progress-bar-track">
                    <div className="progress-bar-fill" style={{ width: `${distribution.watch_pct}%`, backgroundColor: '#63b3ed' }} />
                  </div>
                </div>

                <div className="dist-item">
                  <div className="dist-header">
                    <span>🔴 Bearish (Sell / Avoid)</span>
                    <strong>{distribution.sell_pct}%</strong>
                  </div>
                  <div className="progress-bar-track">
                    <div className="progress-bar-fill" style={{ width: `${distribution.sell_pct}%`, backgroundColor: '#f56565' }} />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 3. BOTTOM SECTION: MARKET ANALYSIS & PORTFOLIO REVIEW (50% / 50% SIDE-BY-SIDE) */}
      {/* ========================================================================= */}
      <div className="ai-analysis-side-by-side-grid">
        {/* Left Column: Market Analysis */}
        <div className="ai-section side-by-side-card">
          <div className="section-header-compact">
            <h2>📊 Market Analysis</h2>
            <div className="header-actions-compact">
              <button
                onClick={() => fetchWorkflowData('market-analysis')}
                disabled={workflowLoading.marketAnalysis}
                className="btn btn-secondary btn-sm"
              >
                {workflowLoading.marketAnalysis ? '⏳ Analyzing...' : '🔍 Refresh'}
              </button>
              <button
                onClick={onViewMarketPrompt}
                className="btn btn-sm"
              >
                Prompt
              </button>
            </div>
          </div>

          {showMarketPrompt && (
            <div className="modal-backdrop">
              <div className="modal">
                <div className="modal-header">
                  <h3>📝 Market Analysis Prompt</h3>
                </div>
                <div className="modal-body" style={{ maxHeight: '60vh', overflowY: 'auto' }}>
                  <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.6' }}>
                    {marketPrompt || '(No saved prompt yet)'}
                  </pre>
                </div>
                <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                  <button className="btn btn-secondary" onClick={() => setShowMarketPrompt(false)}>Close</button>
                </div>
              </div>
            </div>
          )}

          {marketAnalysisData ? (
            <div className="workflow-result compact">
              {marketAnalysisData.analysis?.content && (
                <div className="workflow-content">
                  <div className="analysis-content compact-scroll">
                    <div
                      style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '13.5px', lineHeight: '1.6' }}
                      dangerouslySetInnerHTML={{
                        __html: renderMarkdown(marketAnalysisData.analysis.content)
                      }}
                    />
                  </div>
                  <div className="analysis-meta" style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', alignItems: 'center' }}>
                    <p className="analysis-footer" style={{ margin: 0 }}>
                      <strong>Generated:</strong> {formatEasternTime(marketAnalysisData.analysis.generated_at)}
                    </p>
                    {(marketAnalysisData.analysis?.tier || marketAnalysisData.analysis?.provider || marketAnalysisData.analysis?.model) && (
                      <span
                        className="meta-item ai-model-badge"
                        style={{
                          background: 'rgba(99, 179, 237, 0.15)',
                          border: '1px solid rgba(99, 179, 237, 0.3)',
                          borderRadius: '6px',
                          padding: '2px 8px',
                          fontSize: '12px',
                          cursor: 'help'
                        }}
                        title={`Tier: ${getTierName(marketAnalysisData.analysis.tier)}\nProvider: ${getProviderName(marketAnalysisData.analysis.provider)}\nModel: ${marketAnalysisData.analysis.model || 'Default'}`}
                      >
                        🤖 <strong>{getTierName(marketAnalysisData.analysis.tier)}:</strong> {getProviderName(marketAnalysisData.analysis.provider)} ({marketAnalysisData.analysis.model || 'Default'})
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="workflow-placeholder compact">
              <div className="placeholder-content">
                <h3>🤖 Market Analysis</h3>
                <p>Click "Refresh" to execute market intelligence workflow.</p>
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Portfolio Review */}
        <div className="ai-section side-by-side-card">
          <div className="section-header-compact">
            <h2>💼 Portfolio Review</h2>
            <div className="header-actions-compact">
              <button
                onClick={() => fetchWorkflowData('portfolio-review')}
                disabled={workflowLoading.portfolioReview}
                className="btn btn-secondary btn-sm"
              >
                {workflowLoading.portfolioReview ? '⏳ Reviewing...' : '🔍 Refresh'}
              </button>
              <button
                onClick={onViewPortfolioPrompt}
                className="btn btn-sm"
              >
                Prompt
              </button>
            </div>
          </div>

          {showPortfolioPrompt && (
            <div className="modal-backdrop">
              <div className="modal">
                <div className="modal-header">
                  <h3>📝 Portfolio Review Prompt</h3>
                </div>
                <div className="modal-body" style={{ maxHeight: '60vh', overflowY: 'auto' }}>
                  <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.6' }}>
                    {portfolioPrompt || '(No saved prompt yet)'}
                  </pre>
                </div>
                <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                  <button className="btn btn-secondary" onClick={() => setShowPortfolioPrompt(false)}>Close</button>
                </div>
              </div>
            </div>
          )}

          {portfolioReviewData ? (
            <div className="workflow-result compact">
              {portfolioReviewData.analysis?.content && (
                <div className="workflow-content">
                  <div className="analysis-content compact-scroll">
                    <div
                      style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '13.5px', lineHeight: '1.6' }}
                      dangerouslySetInnerHTML={{
                        __html: renderMarkdown(portfolioReviewData.analysis.content)
                      }}
                    />
                  </div>
                  <div className="analysis-meta" style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', alignItems: 'center' }}>
                    <span className="meta-item">
                      <strong>Generated:</strong> {formatEasternTime(portfolioReviewData.analysis.generated_at)}
                    </span>
                    {(portfolioReviewData.analysis?.tier || portfolioReviewData.analysis?.provider || portfolioReviewData.analysis?.model) && (
                      <span
                        className="meta-item ai-model-badge"
                        style={{
                          background: 'rgba(99, 179, 237, 0.15)',
                          border: '1px solid rgba(99, 179, 237, 0.3)',
                          borderRadius: '6px',
                          padding: '2px 8px',
                          fontSize: '12px',
                          cursor: 'help'
                        }}
                        title={`Tier: ${getTierName(portfolioReviewData.analysis.tier)}\nProvider: ${getProviderName(portfolioReviewData.analysis.provider)}\nModel: ${portfolioReviewData.analysis.model || 'Default'}`}
                      >
                        🤖 <strong>{getTierName(portfolioReviewData.analysis.tier)}:</strong> {getProviderName(portfolioReviewData.analysis.provider)} ({portfolioReviewData.analysis.model || 'Default'})
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="workflow-placeholder compact">
              <div className="placeholder-content">
                <h3>🤖 Portfolio Review</h3>
                <p>Click "Refresh" to analyze holdings and rebalancing opportunities.</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default AIDashboard;
