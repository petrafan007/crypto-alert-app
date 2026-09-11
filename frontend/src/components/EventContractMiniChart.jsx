import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import axios from 'axios';
import { formatEasternTime } from '../utils/dateTime';
import './EventContractMiniChart.css';

const TIMEFRAME_CONFIGS = {
  '1m': { interval: '1m', limit: 15, label: '1m', description: 'Past 15 minutes in 1m increments' },
  '15m': { interval: '15m', limit: 4, label: '15m', description: 'Past 1 hour in 15m increments' },
  '1h': { interval: '1h', limit: 6, label: '1h', description: 'Past 6 hours in 1h increments' },
  '4h': { interval: '4h', limit: 6, label: '4h', description: 'Last 24 hours in 4h increments' },
};

const detectDefaultTimeframe = (market, duration) => {
  const durationStr = String(duration || market?.series_frequency || '').toUpperCase();
  const name = String(market?.name || '').toLowerCase();
  
  if (durationStr === 'FIFTEEN_MINUTES' || /\b15\s*(?:m|min|minute)/i.test(name)) {
    return '15m';
  }
  if (durationStr === 'HOURLY' || /\b(?:1\s*h|1\s*hour|hourly)\b/i.test(name)) {
    return '1h';
  }
  if (durationStr === 'DAILY' || /\b(?:1\s*d|daily)\b/i.test(name)) {
    return '4h';
  }
  return '15m';
};

const formatPrice = (val) => {
  if (val == null || !Number.isFinite(val)) return '—';
  if (val >= 1000) {
    return `$${val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  if (val >= 1) {
    return `$${val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
  }
  return `$${val.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 6 })}`;
};

const formatAxisPrice = (val, priceRange) => {
  if (val == null || !Number.isFinite(val)) return '';
  if (val >= 10000) {
    if (priceRange != null && priceRange < 15) {
      return `$${val.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`;
    }
    return `$${Math.round(val).toLocaleString('en-US')}`;
  }
  if (val >= 1000) {
    if (priceRange != null && priceRange < 5) {
      return `$${val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    return `$${Math.round(val).toLocaleString('en-US')}`;
  }
  if (val >= 1) {
    return `$${val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  return `$${val.toLocaleString('en-US', { minimumFractionDigits: 3, maximumFractionDigits: 4 })}`;
};

const formatXAxisTime = (timestamp, timeframe) => {
  if (!timestamp) return '';
  const d = new Date(timestamp);
  if (isNaN(d.getTime())) return '';

  try {
    if (timeframe === '4h') {
      const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/New_York',
        month: 'numeric',
        day: 'numeric',
        hour: 'numeric',
        hour12: true,
      }).formatToParts(d);
      const m = parts.find((p) => p.type === 'month')?.value || '';
      const day = parts.find((p) => p.type === 'day')?.value || '';
      const h = parts.find((p) => p.type === 'hour')?.value || '';
      const dp = parts.find((p) => p.type === 'dayPeriod')?.value || '';
      return `${m}/${day} ${h} ${dp}`;
    }
    return new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    }).format(d);
  } catch (e) {
    return d.toLocaleTimeString();
  }
};

export default function EventContractMiniChart({
  symbol,
  market,
  duration,
  isLightMode = false,
  livePrice = 0,
}) {
  const cleanSymbol = useMemo(() => {
    if (!symbol) return '';
    return String(symbol).replace(/USD$|USDT$/, '').toUpperCase();
  }, [symbol]);

  const [timeframe, setTimeframe] = useState(() => detectDefaultTimeframe(market, duration));
  const [candles, setCandles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [hoverData, setHoverData] = useState(null);
  const [chartMode, setChartMode] = useState('area'); // 'area' or 'candle'
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });

  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const pollTimerRef = useRef(null);
  const abortControllerRef = useRef(null);

  // Observe container dimensions for responsive canvas sizing
  useEffect(() => {
    const el = canvasRef.current?.parentElement;
    if (!el) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          setContainerSize({ width: Math.round(width), height: Math.round(height) });
        }
      }
    });

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Sync default timeframe when market or contract duration changes
  useEffect(() => {
    const nextDefault = detectDefaultTimeframe(market, duration);
    setTimeframe(nextDefault);
  }, [market?.symbol, market?.name, market?.series_frequency, duration]);

  // Fetch Kline / Candlestick data
  const fetchKlines = useCallback(async (isPolling = false) => {
    if (!cleanSymbol) return;
    const config = TIMEFRAME_CONFIGS[timeframe] || TIMEFRAME_CONFIGS['15m'];

    if (!isPolling) {
      setLoading(true);
      setError(null);
    }

    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response = await axios.get(`/api/trading/klines/${cleanSymbol}`, {
        params: {
          interval: config.interval,
          limit: config.limit,
        },
        withCredentials: true,
        signal: controller.signal,
      });

      if (response.data?.success && Array.isArray(response.data?.klines)) {
        const rawKlines = response.data.klines;
        const mapped = rawKlines.map((k) => ({
          time: Number(k.time) * 1000,
          open: Number(k.open),
          high: Number(k.high),
          low: Number(k.low),
          close: Number(k.close),
          volume: Number(k.volume || 0),
        })).filter((k) => Number.isFinite(k.close) && k.close > 0);

        setCandles(mapped);
        setError(null);
      } else if (!isPolling) {
        setError('No price history available');
      }
    } catch (err) {
      if (!axios.isCancel(err) && !isPolling) {
        setError('Price feed currently unavailable');
      }
    } finally {
      if (!isPolling) {
        setLoading(false);
      }
    }
  }, [cleanSymbol, timeframe]);

  // Trigger fetch and recurring poll
  useEffect(() => {
    fetchKlines(false);

    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
    }
    pollTimerRef.current = setInterval(() => {
      fetchKlines(true);
    }, 4000);

    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
      }
      abortControllerRef.current?.abort();
    };
  }, [fetchKlines]);

  // Incorporate external livePrice when provided
  const displayCandles = useMemo(() => {
    if (!candles.length) return [];
    if (!livePrice || livePrice <= 0) return candles;

    const copy = [...candles];
    const last = copy[copy.length - 1];
    if (last) {
      copy[copy.length - 1] = {
        ...last,
        close: livePrice,
        high: Math.max(last.high, livePrice),
        low: Math.min(last.low, livePrice),
      };
    }
    return copy;
  }, [candles, livePrice]);

  // Derived price metrics
  const currentPrice = useMemo(() => {
    if (hoverData?.price != null) return hoverData.price;
    if (livePrice > 0) return livePrice;
    if (displayCandles.length > 0) {
      return displayCandles[displayCandles.length - 1].close;
    }
    return 0;
  }, [hoverData, livePrice, displayCandles]);

  const startPrice = useMemo(() => {
    if (displayCandles.length > 0) {
      return displayCandles[0].open || displayCandles[0].close;
    }
    return 0;
  }, [displayCandles]);

  const priceChange = useMemo(() => {
    if (!currentPrice || !startPrice) return { amount: 0, percent: 0, isPositive: true };
    const diff = currentPrice - startPrice;
    const pct = (diff / startPrice) * 100;
    return {
      amount: diff,
      percent: pct,
      isPositive: diff >= 0,
    };
  }, [currentPrice, startPrice]);

  // Canvas Rendering
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;

    if (width <= 0 || height <= 0) return;

    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, width, height);

    if (displayCandles.length < 2) {
      return;
    }

    // Chart margins: Left padding leaves ample room for Y-axis price labels
    const padLeft = 54;
    const padRight = 10;
    const padTop = 14;
    const padBottom = 22;
    const drawWidth = Math.max(10, width - padLeft - padRight);
    const drawHeight = Math.max(10, height - padTop - padBottom);

    // Calculate min and max price
    let minPrice = Infinity;
    let maxPrice = -Infinity;
    displayCandles.forEach((c) => {
      const low = chartMode === 'candle' ? c.low : c.close;
      const high = chartMode === 'candle' ? c.high : c.close;
      if (low < minPrice) minPrice = low;
      if (high > maxPrice) maxPrice = high;
    });

    if (minPrice === maxPrice) {
      minPrice *= 0.999;
      maxPrice *= 1.001;
    }

    const priceRange = maxPrice - minPrice;
    const getY = (price) => padTop + drawHeight - ((price - minPrice) / priceRange) * drawHeight;
    const getX = (idx) => padLeft + (idx / (displayCandles.length - 1)) * drawWidth;

    // --- 1. Y-Axis Gridlines & Price Labels (on the Left) ---
    const yTickFractions = drawHeight >= 110 ? [0, 0.333, 0.667, 1] : [0, 0.5, 1];
    ctx.save();
    ctx.font = '9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';

    yTickFractions.forEach((fraction) => {
      const y = padTop + drawHeight * (1 - fraction);
      const priceAtTick = minPrice + fraction * priceRange;
      const label = formatAxisPrice(priceAtTick, priceRange);

      // Subtle horizontal gridline
      ctx.save();
      ctx.strokeStyle = isLightMode ? 'rgba(226, 232, 240, 0.8)' : 'rgba(30, 41, 59, 0.7)';
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(padLeft, y);
      ctx.lineTo(width - padRight, y);
      ctx.stroke();
      ctx.restore();

      // Tick mark on Y-axis
      ctx.strokeStyle = isLightMode ? 'rgba(148, 163, 184, 0.6)' : 'rgba(71, 85, 105, 0.6)';
      ctx.beginPath();
      ctx.moveTo(padLeft - 3, y);
      ctx.lineTo(padLeft, y);
      ctx.stroke();

      // Price text on left
      ctx.fillStyle = isLightMode ? '#64748b' : '#94a3b8';
      ctx.fillText(label, padLeft - 6, y);
    });
    ctx.restore();

    // Baseline dashed reference line
    const baseY = getY(startPrice);
    if (baseY >= padTop && baseY <= height - padBottom) {
      ctx.save();
      ctx.strokeStyle = isLightMode ? 'rgba(100, 116, 139, 0.65)' : 'rgba(148, 163, 184, 0.45)';
      ctx.setLineDash([4, 3]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(padLeft, baseY);
      ctx.lineTo(width - padRight, baseY);
      ctx.stroke();
      ctx.restore();
    }

    // --- 2. Chart Series (Area or Candles) ---
    const isUp = priceChange.isPositive;
    const strokeColor = isUp ? '#10b981' : '#f43f5e';
    const topGradient = isUp ? 'rgba(16, 185, 129, 0.28)' : 'rgba(244, 63, 94, 0.28)';
    const bottomGradient = isUp ? 'rgba(16, 185, 129, 0.01)' : 'rgba(244, 63, 94, 0.01)';

    if (chartMode === 'candle') {
      const candleWidth = Math.max(3, Math.min(10, (drawWidth / displayCandles.length) * 0.65));
      displayCandles.forEach((c, i) => {
        const x = getX(i);
        const candleUp = c.close >= c.open;
        const color = candleUp ? '#10b981' : '#f43f5e';

        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, getY(c.high));
        ctx.lineTo(x, getY(c.low));
        ctx.stroke();

        const openY = getY(c.open);
        const closeY = getY(c.close);
        const bodyTop = Math.min(openY, closeY);
        const bodyHeight = Math.max(1.5, Math.abs(openY - closeY));

        ctx.fillStyle = color;
        ctx.fillRect(x - candleWidth / 2, bodyTop, candleWidth, bodyHeight);
      });
    } else {
      // Smooth Area Chart
      const points = displayCandles.map((c, i) => ({ x: getX(i), y: getY(c.close) }));

      // Area fill
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      for (let i = 0; i < points.length - 1; i++) {
        const xc = (points[i].x + points[i + 1].x) / 2;
        const yc = (points[i].y + points[i + 1].y) / 2;
        ctx.quadraticCurveTo(points[i].x, points[i].y, xc, yc);
      }
      ctx.lineTo(points[points.length - 1].x, points[points.length - 1].y);
      ctx.lineTo(points[points.length - 1].x, height - padBottom);
      ctx.lineTo(points[0].x, height - padBottom);
      ctx.closePath();

      const gradient = ctx.createLinearGradient(0, padTop, 0, height - padBottom);
      gradient.addColorStop(0, topGradient);
      gradient.addColorStop(1, bottomGradient);
      ctx.fillStyle = gradient;
      ctx.fill();
      ctx.restore();

      // Line stroke
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      for (let i = 0; i < points.length - 1; i++) {
        const xc = (points[i].x + points[i + 1].x) / 2;
        const yc = (points[i].y + points[i + 1].y) / 2;
        ctx.quadraticCurveTo(points[i].x, points[i].y, xc, yc);
      }
      ctx.lineTo(points[points.length - 1].x, points[points.length - 1].y);
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 2;
      ctx.lineJoin = 'round';
      ctx.stroke();
      ctx.restore();

      // Glowing live point at latest data point
      const lastPoint = points[points.length - 1];
      ctx.save();
      ctx.beginPath();
      ctx.arc(lastPoint.x, lastPoint.y, 4, 0, Math.PI * 2);
      ctx.fillStyle = strokeColor;
      ctx.shadowColor = strokeColor;
      ctx.shadowBlur = 8;
      ctx.fill();

      ctx.beginPath();
      ctx.arc(lastPoint.x, lastPoint.y, 1.8, 0, Math.PI * 2);
      ctx.fillStyle = '#ffffff';
      ctx.fill();
      ctx.restore();
    }

    // --- 3. Axis Border Lines (Y-Axis & X-Axis) ---
    ctx.save();
    ctx.strokeStyle = isLightMode ? 'rgba(203, 213, 225, 0.9)' : 'rgba(71, 85, 105, 0.7)';
    ctx.lineWidth = 1;

    // Vertical Y-Axis border
    ctx.beginPath();
    ctx.moveTo(padLeft, padTop);
    ctx.lineTo(padLeft, height - padBottom);
    ctx.stroke();

    // Horizontal X-Axis border
    ctx.beginPath();
    ctx.moveTo(padLeft, height - padBottom);
    ctx.lineTo(width - padRight, height - padBottom);
    ctx.stroke();
    ctx.restore();

    // --- 4. X-Axis Time Ticks & Labels (along Bottom) ---
    ctx.save();
    ctx.font = '9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace';
    ctx.fillStyle = isLightMode ? '#64748b' : '#94a3b8';
    ctx.textBaseline = 'top';

    const numTimeLabels = Math.min(4, displayCandles.length);
    const tickStep = (displayCandles.length - 1) / Math.max(1, numTimeLabels - 1);
    const selectedIndices = [];
    for (let k = 0; k < numTimeLabels; k++) {
      selectedIndices.push(Math.round(k * tickStep));
    }
    const uniqueTickIndices = [...new Set(selectedIndices)];

    uniqueTickIndices.forEach((idx) => {
      const candle = displayCandles[idx];
      if (!candle) return;
      const x = getX(idx);
      const timeStr = formatXAxisTime(candle.time, timeframe);

      // Tick mark down from X-axis
      ctx.strokeStyle = isLightMode ? 'rgba(148, 163, 184, 0.6)' : 'rgba(71, 85, 105, 0.6)';
      ctx.beginPath();
      ctx.moveTo(x, height - padBottom);
      ctx.lineTo(x, height - padBottom + 3);
      ctx.stroke();

      // Align label: left at start, right at end, center elsewhere
      ctx.textAlign = idx === 0 ? 'left' : (idx === displayCandles.length - 1 ? 'right' : 'center');
      ctx.fillText(timeStr, x, height - padBottom + 5);
    });
    ctx.restore();

    // --- 5. Interactive Crosshair & Hover Highlights ---
    if (hoverData && hoverData.index != null && hoverData.index >= 0 && hoverData.index < displayCandles.length) {
      const hoverIndex = hoverData.index;
      const hx = getX(hoverIndex);
      const hy = getY(displayCandles[hoverIndex].close);

      ctx.save();
      ctx.strokeStyle = isLightMode ? 'rgba(30, 41, 59, 0.5)' : 'rgba(255, 255, 255, 0.5)';
      ctx.setLineDash([2, 2]);
      ctx.lineWidth = 1;

      // Vertical crosshair
      ctx.beginPath();
      ctx.moveTo(hx, padTop);
      ctx.lineTo(hx, height - padBottom);
      ctx.stroke();

      // Horizontal crosshair
      ctx.beginPath();
      ctx.moveTo(padLeft, hy);
      ctx.lineTo(width - padRight, hy);
      ctx.stroke();

      // Point dot
      ctx.beginPath();
      ctx.arc(hx, hy, 3.5, 0, Math.PI * 2);
      ctx.fillStyle = isLightMode ? '#0f172a' : '#ffffff';
      ctx.fill();
      ctx.restore();

      // Highlight badge on Y-axis (Price)
      ctx.save();
      const hoverPriceStr = formatPrice(displayCandles[hoverIndex].close);
      ctx.font = 'bold 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace';
      const textWidth = ctx.measureText(hoverPriceStr).width;
      const pillWidth = textWidth + 8;
      const pillHeight = 15;
      const pillX = Math.max(2, padLeft - pillWidth - 2);
      const pillY = Math.max(padTop - 7, Math.min(height - padBottom - 8, hy - pillHeight / 2));

      ctx.fillStyle = isLightMode ? '#1e293b' : '#38bdf8';
      ctx.beginPath();
      ctx.roundRect ? ctx.roundRect(pillX, pillY, pillWidth, pillHeight, 3) : ctx.rect(pillX, pillY, pillWidth, pillHeight);
      ctx.fill();

      ctx.fillStyle = isLightMode ? '#ffffff' : '#0f172a';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(hoverPriceStr, pillX + pillWidth / 2, pillY + pillHeight / 2);
      ctx.restore();
    }
  }, [displayCandles, chartMode, isLightMode, priceChange.isPositive, startPrice, hoverData, containerSize, timeframe]);

  // Mouse / Touch crosshair events
  const handleMouseMove = (e) => {
    const canvas = canvasRef.current;
    if (!canvas || displayCandles.length < 2) return;
    const rect = canvas.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const xPos = clientX - rect.left;

    const padLeft = 54;
    const padRight = 10;
    const drawWidth = rect.width - padLeft - padRight;
    const clampedX = Math.max(0, Math.min(drawWidth, xPos - padLeft));
    const ratio = clampedX / drawWidth;
    const index = Math.round(ratio * (displayCandles.length - 1));

    if (index >= 0 && index < displayCandles.length) {
      const candle = displayCandles[index];
      setHoverData({
        index,
        price: candle.close,
        time: candle.time,
      });
    }
  };

  const handleMouseLeave = () => {
    setHoverData(null);
  };

  // Safe early exit AFTER hooks
  if (!cleanSymbol) return null;

  return (
    <div
      ref={containerRef}
      className={`event-mini-chart-card ${isLightMode ? 'light-mode' : ''}`}
      aria-label={`Real-time ${cleanSymbol} price mini chart`}
    >
      {/* Chart Header */}
      <div className="event-mini-chart-header">
        <div className="event-mini-chart-price-box">
          <div className="event-mini-chart-symbol-badge">
            <span className="coin-tag">{cleanSymbol}</span>
            <span className="live-pulse" title="Live streaming feed" />
          </div>
          <div className="event-mini-chart-price-info">
            <span className="current-price">{formatPrice(currentPrice)}</span>
            <span
              className={`price-change ${priceChange.isPositive ? 'positive' : 'negative'}`}
            >
              {priceChange.isPositive ? '▲ +' : '▼ '}
              {Math.abs(priceChange.percent).toFixed(2)}%
            </span>
          </div>
        </div>

        {/* Timeframe Selectors */}
        <div className="event-mini-chart-controls">
          <div className="event-mini-chart-timeframes" role="group" aria-label="Chart timeframes">
            {Object.keys(TIMEFRAME_CONFIGS).map((tf) => (
              <button
                key={tf}
                type="button"
                className={`tf-btn ${timeframe === tf ? 'active' : ''}`}
                onClick={() => setTimeframe(tf)}
                title={TIMEFRAME_CONFIGS[tf].description}
                aria-pressed={timeframe === tf}
              >
                {tf}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="chart-mode-toggle"
            onClick={() => setChartMode((prev) => (prev === 'area' ? 'candle' : 'area'))}
            title={`Switch to ${chartMode === 'area' ? 'Candlestick' : 'Area line'} view`}
            aria-label="Toggle chart type"
          >
            {chartMode === 'area' ? '📊' : '📈'}
          </button>
        </div>
      </div>

      {/* Chart Canvas Area */}
      <div
        className="event-mini-chart-body"
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        onTouchMove={handleMouseMove}
        onTouchEnd={handleMouseLeave}
      >
        <canvas ref={canvasRef} className="event-mini-chart-canvas" />

        {loading && displayCandles.length === 0 && (
          <div className="event-mini-chart-overlay">
            <div className="mini-spinner" />
          </div>
        )}

        {error && displayCandles.length === 0 && (
          <div className="event-mini-chart-overlay error">
            <span>{error}</span>
          </div>
        )}

        {/* Hover Readout Bar */}
        {hoverData && (
          <div className="event-mini-chart-hover-bar">
            <span>{formatEasternTime(new Date(hoverData.time))} ET</span>
            <strong>{formatPrice(hoverData.price)}</strong>
          </div>
        )}
      </div>
    </div>
  );
}
