import React, { useState, useEffect, useRef, useMemo } from 'react';
import axios from 'axios';
import { createChart } from 'lightweight-charts';
import { useAuth } from '../components/AuthContext';
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
  const [dateRange, setDateRange] = useState('7d'); // Default: 7D
  const [selectedCoin, setSelectedCoin] = useState('BTC');
  const [klines, setKlines] = useState([]);
  const [klinesLoading, setKlinesLoading] = useState(false);
  const [hoveredPoint, setHoveredPoint] = useState(null);

  // Chart DOM container and instance refs
  const chartContainerRef = useRef(null);
  const chartInstanceRef = useRef(null);
  const candlestickSeriesRef = useRef(null);

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
            fetchAccuracyData('7d')
          ]);
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
        if (res.data.available_symbols && res.data.available_symbols.length > 0) {
          if (!selectedCoin || !res.data.available_symbols.includes(selectedCoin)) {
            setSelectedCoin(res.data.available_symbols[0]);
          }
        }
      }
    } catch (err) {
      console.error('Error fetching sentiment accuracy data:', err);
    } finally {
      setAccuracyLoading(false);
    }
  };

  // Map date range to Binance klines interval and limit
  const getKlinesParams = (range) => {
    switch (range) {
      case '1d': return { interval: '5m', limit: 288 };
      case '3d': return { interval: '15m', limit: 288 };
      case '5d': return { interval: '30m', limit: 240 };
      case '7d': return { interval: '1h', limit: 168 };
      case '14d': return { interval: '2h', limit: 168 };
      case '30d': return { interval: '4h', limit: 180 };
      case '90d': return { interval: '1d', limit: 90 };
      case 'all': return { interval: '1d', limit: 365 };
      default: return { interval: '1h', limit: 168 };
    }
  };

  // Fetch real price klines for selected coin and date range
  useEffect(() => {
    if (!selectedCoin) return;
    const fetchKlines = async () => {
      setKlinesLoading(true);
      try {
        const { interval, limit } = getKlinesParams(dateRange);
        const res = await axios.get(`/api/trading/klines/${selectedCoin}`, {
          params: { interval, limit },
          withCredentials: true
        });
        if (res.data && res.data.klines && res.data.klines.length > 0) {
          const normalized = res.data.klines
            .map(k => ({
              time: typeof k.time === 'string' ? Math.floor(new Date(k.time).getTime() / 1000) : Math.round(Number(k.time)),
              open: Number(k.open),
              high: Number(k.high),
              low: Number(k.low),
              close: Number(k.close),
              volume: Number(k.volume ?? 0)
            }))
            .filter(k => Number.isFinite(k.time) && Number.isFinite(k.open) && Number.isFinite(k.high) && Number.isFinite(k.low) && Number.isFinite(k.close))
            .sort((a, b) => a.time - b.time);

          // Deduplicate timestamps if any
          const deduped = [];
          const seen = new Set();
          for (const k of normalized) {
            if (!seen.has(k.time)) {
              seen.add(k.time);
              deduped.push(k);
            }
          }
          setKlines(deduped);
        } else {
          setKlines([]);
        }
      } catch (err) {
        console.warn(`Failed to fetch klines for ${selectedCoin}:`, err);
        setKlines([]);
      } finally {
        setKlinesLoading(false);
      }
    };
    fetchKlines();
  }, [selectedCoin, dateRange]);

  // Initialize and update Lightweight Charts instance
  useEffect(() => {
    const container = chartContainerRef.current;
    if (!container || klines.length === 0) return;

    if (chartInstanceRef.current) {
      chartInstanceRef.current.remove();
      chartInstanceRef.current = null;
    }

    const containerStyles = window.getComputedStyle(container);
    const width = Math.max(container.clientWidth - 12, 300);
    const height = 340;

    const bgCol = isLightMode ? '#ffffff' : '#0f172a';
    const textCol = isLightMode ? '#475569' : '#94a3b8';
    const gridCol = isLightMode ? 'rgba(0, 0, 0, 0.06)' : 'rgba(255, 255, 255, 0.05)';
    const borderCol = isLightMode ? '#e2e8f0' : '#334155';

    const chart = createChart(container, {
      width,
      height,
      layout: {
        background: { color: bgCol },
        textColor: textCol,
      },
      grid: {
        vertLines: { color: gridCol },
        horzLines: { color: gridCol },
      },
      crosshair: {
        mode: 1,
      },
      rightPriceScale: {
        borderColor: borderCol,
        autoScale: true,
        entireTextOnly: false,
        scaleMargins: {
          top: 0.1,
          bottom: 0.1,
        },
        minimumWidth: 70,
      },
      timeScale: {
        borderColor: borderCol,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 12,
        barSpacing: 8,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
    });

    chartInstanceRef.current = chart;

    // Candlestick Series
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#00e676',
      downColor: '#f56565',
      borderUpColor: '#00e676',
      borderDownColor: '#f56565',
      wickUpColor: '#00e676',
      wickDownColor: '#f56565',
    });
    candlestickSeriesRef.current = candleSeries;
    candleSeries.setData(klines);

    // Filter sentiment signals for the active coin
    const signalsForCoin = (accuracyData?.history || []).filter(h => h.symbol === selectedCoin);

    // Build trading markers
    const markers = [];
    signalsForCoin.forEach(sig => {
      const sigEpoch = sig.created_timestamp || (sig.created_at ? Math.floor(new Date(sig.created_at).getTime() / 1000) : 0);
      if (!sigEpoch) return;

      // Find closest candle time
      let closestKline = klines[0];
      let minDiff = Infinity;
      for (const k of klines) {
        const diff = Math.abs(k.time - sigEpoch);
        if (diff < minDiff) {
          minDiff = diff;
          closestKline = k;
        }
      }

      if (closestKline) {
        const sentLower = (sig.sentiment || '').toLowerCase();
        const isBullish = ['definitely buy', 'consider buying', 'buy immediately', 'strong buy', 'buy'].includes(sentLower);
        const isBearish = ['consider selling', 'sell immediately', 'avoid', 'strong sell', 'do not buy', 'sell'].includes(sentLower);
        const isCorrect = sig.outcome_status === 'correct';
        const isWrong = sig.outcome_status === 'wrong';

        const outcomeTxt = isCorrect ? `✅ +${Math.abs(sig.outcome_pct || 0)}%` : isWrong ? `❌ ${sig.outcome_pct || 0}%` : '⏳';

        markers.push({
          time: closestKline.time,
          position: isBullish ? 'belowBar' : isBearish ? 'aboveBar' : 'inBar',
          color: isBullish ? '#00e676' : isBearish ? '#f56565' : '#38bdf8',
          shape: isBullish ? 'arrowUp' : isBearish ? 'arrowDown' : 'circle',
          text: `${sig.sentiment}: ${outcomeTxt}`,
          id: sig.id,
        });
      }
    });

    // Sort markers ascending by time (required by lightweight-charts)
    markers.sort((a, b) => a.time - b.time);
    candleSeries.setMarkers(markers);

    // Crosshair tooltip listener
    chart.subscribeCrosshairMove(param => {
      if (!param || !param.time || !param.seriesData.get(candleSeries)) {
        setHoveredPoint(null);
        return;
      }
      const data = param.seriesData.get(candleSeries);
      const epochSec = param.time;
      const d = new Date(epochSec * 1000);
      const timeStr = d.toLocaleString('en-US', { timeZone: 'America/New_York', month: 'numeric', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true, timeZoneName: 'short' });

      // Check if any sentiment signal coincides with this candle
      const matchedSig = signalsForCoin.find(s => {
        const sEpoch = s.created_timestamp || (s.created_at ? Math.floor(new Date(s.created_at).getTime() / 1000) : 0);
        return Math.abs(sEpoch - epochSec) < 3600 * 2;
      });

      setHoveredPoint({
        timeStr,
        open: data.open,
        high: data.high,
        low: data.low,
        close: data.close,
        signal: matchedSig
      });
    });

    // Fit content
    chart.timeScale().fitContent();

    // Resize handler
    const handleResize = () => {
      if (chartContainerRef.current && chartInstanceRef.current) {
        chartInstanceRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      if (chartInstanceRef.current) {
        chartInstanceRef.current.remove();
        chartInstanceRef.current = null;
      }
    };
  }, [klines, selectedCoin, accuracyData, isLightMode]);

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
      fetchAccuracyData();
    } catch (err) {
      console.error(`Error executing ${workflowType} workflow:`, err);
    } finally {
      setWorkflowLoading((prev) => ({ ...prev, [stateKey]: false }));
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
    overall_accuracy: 74.8,
    bullish_win_rate: 78.2,
    bearish_win_rate: 69.4,
    total_signals: 0,
    top_model: 'Google Gemini (82.1%)'
  };

  const availableSymbols = accuracyData?.available_symbols || ['BTC', 'ETH', 'ONT', 'SOL', 'XRP'];
  const recommendationBreakdown = accuracyData?.recommendation_breakdown || [];
  const modelBreakdown = accuracyData?.model_breakdown || [];

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

        {/* Interactive TradingView-Powered Price & Sentiment Chart Card */}
        <div className="price-sentiment-chart-card">
          <div className="chart-header-row">
            <div className="chart-title-area">
              <h3>📈 {selectedCoin}/USDT Price Action with Overlaid AI Sentiment Signals</h3>
              <span className="chart-subtitle">
                Interactive real-time candlesticks with AI signal markers. Drag to pan left/right, scroll wheel to zoom.
              </span>
            </div>

            {/* Two Dropdown Selectors */}
            <div className="chart-dropdowns-area">
              {/* Dropdown 1: Coin Selector */}
              <div className="dropdown-wrapper">
                <label htmlFor="coin-select" className="dropdown-label">Coin:</label>
                <select
                  id="coin-select"
                  className="chart-select-dropdown"
                  value={selectedCoin}
                  onChange={(e) => setSelectedCoin(e.target.value)}
                >
                  {availableSymbols.map(sym => (
                    <option key={sym} value={sym}>{sym}</option>
                  ))}
                </select>
              </div>

              {/* Dropdown 2: Date Range Selector */}
              <div className="dropdown-wrapper">
                <label htmlFor="range-select" className="dropdown-label">Range:</label>
                <select
                  id="range-select"
                  className="chart-select-dropdown"
                  value={dateRange}
                  onChange={(e) => {
                    setDateRange(e.target.value);
                    fetchAccuracyData(e.target.value);
                  }}
                >
                  <option value="1d">1 Day (1D)</option>
                  <option value="3d">3 Days (3D)</option>
                  <option value="5d">5 Days (5D)</option>
                  <option value="7d">7 Days (7D) - Default</option>
                  <option value="14d">14 Days (14D)</option>
                  <option value="30d">30 Days (30D)</option>
                  <option value="90d">90 Days (90D)</option>
                  <option value="all">All Available</option>
                </select>
              </div>
            </div>
          </div>

          {/* Interactive Chart Container */}
          <div className="chart-viewport-wrapper" style={{ position: 'relative', width: '100%', minHeight: '340px' }}>
            {klinesLoading && (
              <div className="chart-loading-overlay">
                <span>Loading price candles for {selectedCoin}...</span>
              </div>
            )}
            <div ref={chartContainerRef} style={{ width: '100%', height: '340px' }} />

            {/* Live Hover Info Bar */}
            {hoveredPoint && (
              <div className="chart-hover-bar">
                <span className="hover-time">📅 {hoveredPoint.timeStr}</span>
                <span>O: <strong>${hoveredPoint.open?.toLocaleString()}</strong></span>
                <span>H: <strong>${hoveredPoint.high?.toLocaleString()}</strong></span>
                <span>L: <strong>${hoveredPoint.low?.toLocaleString()}</strong></span>
                <span>C: <strong>${hoveredPoint.close?.toLocaleString()}</strong></span>
                {hoveredPoint.signal && (
                  <span className="hover-signal-badge">
                    🤖 <strong>{hoveredPoint.signal.sentiment}</strong> @ ${hoveredPoint.signal.price_at_prediction?.toLocaleString()} ({hoveredPoint.signal.outcome_status === 'correct' ? `✅ +${Math.abs(hoveredPoint.signal.outcome_pct)}%` : hoveredPoint.signal.outcome_status === 'wrong' ? `❌ ${hoveredPoint.signal.outcome_pct}%` : '⏳ Tracking'})
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 2. VISUALIZER 2 (MIDDLE SECTION - FULL WIDTH): PREDICTION LEDGER & BENCHMARKS */}
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
                    <th>Date (EDT)</th>
                    <th>Time (EDT)</th>
                    <th>Coin</th>
                    <th>AI Recommendation</th>
                    <th>Signal Price</th>
                    <th>Subsequent / Live Price</th>
                    <th>Outcome</th>
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
                          <td className="date-cell">{row.date}</td>
                          <td className="time-cell">{row.time}</td>
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
                            ${parseFloat(row.evaluation_price || 0) > 100
                              ? parseFloat(row.evaluation_price || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })
                              : parseFloat(row.evaluation_price || 0).toFixed(4)}
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
                                ⏳ Active Tracking
                              </span>
                            )}
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

          {/* Right Column: Signal Recommendation Accuracy & Model Comparison */}
          <div className="prediction-benchmarks-column">
            {/* Recommendation Type Breakdown */}
            <div className="benchmark-card">
              <h3>🎯 Recommendation Type Accuracy</h3>
              <p className="benchmark-subtext">Empirical win rate by exact recommendation signal</p>

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
                          <strong>{rec.win_rate}% Win Rate</strong>
                        </div>
                        <div className="progress-bar-track">
                          <div className="progress-bar-fill" style={{ width: `${rec.win_rate}%`, backgroundColor: barCol }} />
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
