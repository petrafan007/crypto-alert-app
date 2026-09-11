import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import axios from 'axios';
import { formatEasternTime } from '../utils/dateTime';
import './EventContractMiniChart.css';

const TIMEFRAME_CONFIGS = {
  '1m': { interval: '1m', limit: 30, label: '1m', description: 'Minute by minute' },
  '15m': { interval: '1m', limit: 15, label: '15m', description: 'Last 15 minutes' },
  '1h': { interval: '1m', limit: 60, label: '1h', description: '1 Hour' },
  '4h': { interval: '5m', limit: 48, label: '4h', description: '4 Hours' },
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

  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const pollTimerRef = useRef(null);
  const abortControllerRef = useRef(null);

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

    const padTop = 14;
    const padBottom = 16;
    const padLeft = 8;
    const padRight = 8;
    const drawWidth = width - padLeft - padRight;
    const drawHeight = height - padTop - padBottom;

    // Calculate min and max
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

    const isUp = priceChange.isPositive;
    const strokeColor = isUp ? '#10b981' : '#f43f5e';
    const topGradient = isUp ? 'rgba(16, 185, 129, 0.28)' : 'rgba(244, 63, 94, 0.28)';
    const bottomGradient = isUp ? 'rgba(16, 185, 129, 0.01)' : 'rgba(244, 63, 94, 0.01)';

    // Baseline dashed reference line
    const baseY = getY(startPrice);
    ctx.save();
    ctx.strokeStyle = isLightMode ? 'rgba(148, 163, 184, 0.45)' : 'rgba(148, 163, 184, 0.25)';
    ctx.setLineDash([3, 3]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padLeft, baseY);
    ctx.lineTo(width - padRight, baseY);
    ctx.stroke();
    ctx.restore();

    if (chartMode === 'candle') {
      // Candlestick rendering
      const candleWidth = Math.max(2, Math.min(8, (drawWidth / displayCandles.length) * 0.7));
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

      // Glowing dot at latest point
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

    // Crosshair rendering if hovered
    if (hoverData && hoverData.index != null && hoverData.index >= 0 && hoverData.index < displayCandles.length) {
      const hoverIndex = hoverData.index;
      const hx = getX(hoverIndex);
      const hy = getY(displayCandles[hoverIndex].close);

      ctx.save();
      ctx.strokeStyle = isLightMode ? 'rgba(30, 41, 59, 0.4)' : 'rgba(255, 255, 255, 0.4)';
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

      // Hover point dot
      ctx.beginPath();
      ctx.arc(hx, hy, 4, 0, Math.PI * 2);
      ctx.fillStyle = isLightMode ? '#0f172a' : '#ffffff';
      ctx.fill();
      ctx.restore();
    }
  }, [displayCandles, chartMode, isLightMode, priceChange.isPositive, startPrice, hoverData]);

  // Mouse / Touch crosshair events
  const handleMouseMove = (e) => {
    const canvas = canvasRef.current;
    if (!canvas || displayCandles.length < 2) return;
    const rect = canvas.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const xPos = clientX - rect.left;

    const padLeft = 8;
    const padRight = 8;
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
