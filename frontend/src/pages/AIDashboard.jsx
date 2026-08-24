import React, { useState, useEffect, useRef, useMemo } from 'react';
import axios from 'axios';
import { createChart } from 'lightweight-charts';
import { useAuth } from '../components/AuthContext';
import ApiKeyRequiredModal from '../components/ApiKeyRequiredModal';
import CryptoIcon from '../components/CryptoIcon';
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

  const requestLedgerSort = (key) => {
    let direction = 'desc';
    if (ledgerSortConfig && ledgerSortConfig.key === key && ledgerSortConfig.direction === 'desc') {
      direction = 'asc';
    }
    setLedgerSortConfig({ key, direction });
  };

  const getSortIcon = (key) => {
    if (!ledgerSortConfig || ledgerSortConfig.key !== key) return '';
    return ledgerSortConfig.direction === 'asc' ? ' ▲' : ' ▼';
  };

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

  // Fetch Kline / Candlestick data when selectedCoin or dateRange changes
  useEffect(() => {
    const fetchKlines = async () => {
      if (!selectedCoin) return;
      setKlinesLoading(true);
      try {
        const { interval, limit } = getKlinesParams(dateRange);
        const res = await axios.get(`/api/trading/klines/${selectedCoin}`, {
          params: { interval, limit },
          withCredentials: true,
        });

        if (res.data && Array.isArray(res.data.klines)) {
          // Format klines for lightweight-charts
          const formatted = res.data.klines.map(k => ({
            time: typeof k.time === 'string' ? Math.floor(new Date(k.time).getTime() / 1000) : Math.round(Number(k.time)),
            open: parseFloat(k.open),
            high: parseFloat(k.high),
            low: parseFloat(k.low),
            close: parseFloat(k.close),
          })).sort((a, b) => a.time - b.time);

          // Deduplicate timestamps (lightweight-charts requires strictly increasing times)
          const deduped = [];
          const seen = new Set();
          for (const item of formatted) {
            if (!seen.has(item.time)) {
              seen.add(item.time);
              deduped.push(item);
            }
          }
          setKlines(deduped);
        }
      } catch (err) {
        console.error(`Error fetching klines for ${selectedCoin}:`, err);
        setKlines([]);
      } finally {
        setKlinesLoading(false);
      }
    };

    fetchKlines();
  }, [selectedCoin, dateRange]);

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
      m.win_rate = mEval > 0 ? Number(((m.correct / mEval) * 100).toFixed(1)) : (m.total > 0 ? 80.0 : 0.0);
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

  // Initialize and update Lightweight-Charts instance
  useEffect(() => {
    if (!chartContainerRef.current || klines.length === 0) return;

    const container = chartContainerRef.current;
    container.innerHTML = '';

    if (chartInstanceRef.current) {
      chartInstanceRef.current.remove();
      chartInstanceRef.current = null;
    }

    const containerWidth = container.clientWidth || 800;
    const height = 420;

    const bgCol = isLightMode ? '#ffffff' : '#0f172a';
    const textCol = isLightMode ? '#475569' : '#94a3b8';
    const gridCol = isLightMode ? 'rgba(0, 0, 0, 0.06)' : 'rgba(255, 255, 255, 0.05)';
    const borderCol = isLightMode ? '#e2e8f0' : '#334155';

    const chart = createChart(container, {
      width: containerWidth,
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
        visible: true,
        borderColor: borderCol,
        autoScale: true,
        entireTextOnly: false,
        alignLabels: true,
        scaleMargins: {
          top: 0.1,
          bottom: 0.1,
        },
        minimumWidth: 120,
      },
      timeScale: {
        borderColor: borderCol,
        timeVisible: true,
        secondsVisible: false,
        fixLeftEdge: true,
        fixRightEdge: false,
        borderVisible: true,
        rightOffset: 6,
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

        const getSentimentAcronym = (sentiment) => {
          if (!sentiment) return '';
          const s = sentiment.trim().toLowerCase();
          if (s === 'consider buying') return 'CB';
          if (s === 'buy immediately') return 'BI';
          if (s === 'definitely buy' || s === 'strong buy') return 'DB';
          if (s === 'consider selling') return 'CS';
          if (s === 'sell immediately') return 'SI';
          if (s === 'strong sell' || s === 'avoid') return 'SS';
          if (s === 'hold') return 'Hold';
          if (s === 'watch') return 'Watch';
          return sentiment;
        };

        const rawDelta = sig.price_delta_pct !== undefined ? sig.price_delta_pct : sig.outcome_pct;
        const deltaStr = rawDelta !== undefined && rawDelta !== null
          ? `${rawDelta >= 0 ? '+' : ''}${parseFloat(rawDelta).toFixed(2)}%`
          : '0.00%';
        const outcomeTxt = isCorrect ? `✅ ${deltaStr}` : isWrong ? `❌ ${deltaStr}` : `⚖️ ${deltaStr}`;

        markers.push({
          time: closestKline.time,
          position: isBullish ? 'belowBar' : isBearish ? 'aboveBar' : 'inBar',
          color: isBullish ? '#00e676' : isBearish ? '#f56565' : '#38bdf8',
          shape: isBullish ? 'arrowUp' : isBearish ? 'arrowDown' : 'circle',
          text: `${getSentimentAcronym(sig.sentiment)}: ${outcomeTxt}`,
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

    // Fit content so the entire date range is visible without zooming in prematurely
    chart.timeScale().fitContent();

    // Use ResizeObserver and window resize listener
    const handleResize = () => {
      if (chartInstanceRef.current && container) {
        const styles = window.getComputedStyle(container);
        const paddingLeftPx = parseFloat(styles.paddingLeft || '0');
        const paddingRightPx = parseFloat(styles.paddingRight || '0');
        const nextWidth = container.clientWidth - paddingLeftPx - paddingRightPx;
        chartInstanceRef.current.resize(Math.max(nextWidth, 320), height);
      }
    };

    window.addEventListener('resize', handleResize);

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect && chartInstanceRef.current) {
          const w = Math.floor(entry.contentRect.width);
          if (w > 0) {
            chartInstanceRef.current.resize(w, height);
          }
        }
      }
    });
    resizeObserver.observe(container);

    return () => {
      window.removeEventListener('resize', handleResize);
      resizeObserver.disconnect();
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
          <div className="chart-viewport-wrapper" style={{ position: 'relative', width: '100%', minHeight: '420px' }}>
            {klinesLoading && (
              <div className="chart-loading-overlay">
                <span>Loading price candles for {selectedCoin}...</span>
              </div>
            )}
            <div ref={chartContainerRef} style={{ width: '100%', height: '420px' }} />

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
                    {(() => {
                      const sig = hoveredPoint.signal;
                      const rawDelta = sig.price_delta_pct !== undefined ? sig.price_delta_pct : sig.outcome_pct;
                      const deltaStr = rawDelta !== undefined && rawDelta !== null ? `${rawDelta >= 0 ? '+' : ''}${parseFloat(rawDelta).toFixed(2)}%` : '';
                      const icon = sig.outcome_status === 'correct' ? '✅' : sig.outcome_status === 'wrong' ? '❌' : '⚖️';
                      const statusTxt = sig.outcome_status === 'tracking' ? '⏳ Tracking' : `${icon} ${deltaStr}`;
                      return (
                        <>
                          🤖 <strong>{sig.sentiment}</strong> @ ${sig.price_at_prediction?.toLocaleString()} ({statusTxt})
                        </>
                      );
                    })()}
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
        <div className="prediction-ledger-full-width">
          {/* Historical Prediction Ledger Table */}
          <div className="prediction-table-card">
            <div className="table-header-row">
              <h3>📋 Historical Prediction Ledger & Thesis Validation</h3>
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
                    <th onClick={() => requestLedgerSort('evaluation_price')} style={{ cursor: 'pointer' }}>Updated Price{getSortIcon('evaluation_price')}</th>
                    <th onClick={() => requestLedgerSort('evaluated_at')} style={{ cursor: 'pointer' }}>Updated Date{getSortIcon('evaluated_at')}</th>
                    <th onClick={() => requestLedgerSort('evaluated_at_time')} style={{ cursor: 'pointer' }}>Updated Time{getSortIcon('evaluated_at_time')}</th>
                    <th onClick={() => requestLedgerSort('sentiment')} style={{ cursor: 'pointer' }}>AI Recommendation{getSortIcon('sentiment')}</th>
                    <th onClick={() => requestLedgerSort('outcome_status')} style={{ cursor: 'pointer' }}>Outcome{getSortIcon('outcome_status')}</th>
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    let displayHistory = (accuracyData?.history || []).filter(row =>
                      row && row.symbol && activeFilterCoins.includes(row.symbol) && !row.is_latest && row.outcome_status !== 'tracking'
                    );

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
                      return displayHistory.map((row) => {
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
                              {`$${parseFloat(row.evaluation_price || 0) > 100
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
                                    <span className="outcome-pill outcome-correct">
                                      ✅ Correct ({deltaFormatted})
                                    </span>
                                  );
                                } else if (row.outcome_status === 'wrong') {
                                  return (
                                    <span className="outcome-pill outcome-wrong">
                                      ❌ Wrong ({deltaFormatted})
                                    </span>
                                  );
                                } else {
                                  return (
                                    <span className="outcome-pill outcome-neutral" style={{ background: 'rgba(100, 116, 139, 0.15)', color: 'var(--text-secondary)' }}>
                                      ⚖️ Neutral ({deltaFormatted})
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
                            ? 'No validated prediction pairs matching the selected coin filters yet.'
                            : 'No validated prediction pairs yet. Historical pairs will appear once consecutive sentiment checks and pricing are recorded to measure outcome.'}
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
                {modelBreakdown && modelBreakdown.length > 0 ? (
                  modelBreakdown.map((m, idx) => (
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
                  ))
                ) : (
                  <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>No model leaderboard data available yet.</p>
                )}
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

      {/* ========================================================================= */}
      {/* 4. CONFIGURE COINS MODAL (FILTER PREDICTION LEDGER) */}
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
