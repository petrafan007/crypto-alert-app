import React, { useEffect, useRef, useState, useMemo, useCallback } from 'react';
import { createChart } from 'lightweight-charts';
import axios from 'axios';
import { FiRefreshCw, FiMaximize2, FiActivity, FiTrendingUp, FiTrendingDown } from 'react-icons/fi';
import './TradingViewAdvancedChart.css';

const TIMEFRAMES = [
  { label: '1m', value: '1m' },
  { label: '5m', value: '5m' },
  { label: '15m', value: '15m' },
  { label: '1h', value: '1h' },
  { label: '1D', value: '1d' },
];

export default function WebullFuturesLightweightChart({
  symbol = 'MES',
  product = null,
  contract = null,
  accounts = [],
  selectedAccountId,
  onAccountChange,
  defaultAccountId,
  onSetDefaultAccount,
  savingDefaultAccount = false,
  allowDefaultAccount = true,
  isLightMode = false,
}) {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);

  const [timeframe, setTimeframe] = useState('1h');
  const [bars, setBars] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hoveredCandle, setHoveredCandle] = useState(null);
  const [dataSource, setDataSource] = useState('');

  // Resolved clean symbol
  const cleanSymbol = useMemo(() => {
    const raw = String(contract?.symbol || product?.product_code || symbol || 'MES').trim().toUpperCase();
    return raw.replace(/[^A-Z0-9]/g, '');
  }, [contract, product, symbol]);

  const productName = product?.name || `${cleanSymbol} Futures`;
  const exchange = product?.exchange || 'CME';

  // Fetch futures bars from backend
  const fetchBars = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get('/api/webull/futures/bars', {
        params: {
          symbol: cleanSymbol,
          interval: timeframe,
          limit: 200,
        },
        withCredentials: true,
      });
      if (res.data?.success && Array.isArray(res.data?.bars) && res.data.bars.length > 0) {
        setBars(res.data.bars);
        setDataSource(res.data.source === 'webull' ? 'Webull Market Data' : 'Continuous Futures Feed');
      } else {
        setError(res.data?.message || 'No chart data returned for this contract.');
      }
    } catch (err) {
      console.error('Failed to fetch futures bars:', err);
      setError(err.response?.data?.message || 'Failed to load futures market data.');
    } finally {
      setLoading(false);
    }
  }, [cleanSymbol, timeframe]);

  // Refetch on symbol or timeframe change
  useEffect(() => {
    fetchBars();
  }, [fetchBars]);

  // Derived stats from latest bars
  const stats = useMemo(() => {
    if (!bars || bars.length === 0) return null;
    const latest = bars[bars.length - 1];
    const prev = bars.length > 1 ? bars[bars.length - 2] : latest;
    const change = latest.close - prev.close;
    const changePct = prev.close > 0 ? (change / prev.close) * 100 : 0;
    return {
      lastPrice: latest.close,
      change,
      changePct,
      high: latest.high,
      low: latest.low,
      volume: latest.volume,
    };
  }, [bars]);

  // Active display OHLCV: hovered bar or latest bar
  const activeCandle = hoveredCandle || (bars.length > 0 ? bars[bars.length - 1] : null);

  // Initialize and update lightweight-chart
  useEffect(() => {
    const container = chartContainerRef.current;
    if (!container) return undefined;

    // Clean up prior chart
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    }

    const width = container.clientWidth || 800;
    const height = Math.max(container.clientHeight || 560, 480);

    const chart = createChart(container, {
      width,
      height,
      layout: {
        background: { color: isLightMode ? '#ffffff' : '#0b1220' },
        textColor: isLightMode ? '#475569' : '#94a3b8',
        fontSize: 12,
        fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
      },
      grid: {
        vertLines: { color: isLightMode ? 'rgba(226, 232, 240, 0.8)' : 'rgba(51, 65, 85, 0.4)' },
        horzLines: { color: isLightMode ? 'rgba(226, 232, 240, 0.8)' : 'rgba(51, 65, 85, 0.4)' },
      },
      crosshair: {
        mode: 1,
        vertLine: {
          color: '#6366f1',
          width: 1,
          style: 3,
          labelBackgroundColor: '#4f46e5',
        },
        horzLine: {
          color: '#6366f1',
          width: 1,
          style: 3,
          labelBackgroundColor: '#4f46e5',
        },
      },
      rightPriceScale: {
        borderColor: isLightMode ? '#cbd5e1' : 'rgba(51, 65, 85, 0.7)',
        scaleMargins: { top: 0.1, bottom: 0.2 },
        autoScale: true,
      },
      timeScale: {
        borderColor: isLightMode ? '#cbd5e1' : 'rgba(51, 65, 85, 0.7)',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    });

    const volumeSeries = chart.addHistogramSeries({
      color: '#6366f1',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
      scaleMargins: { top: 0.82, bottom: 0 },
    });

    // Populate chart data
    if (bars && bars.length > 0) {
      const candleData = bars
        .map((b) => ({
          time: Number(b.time),
          open: Number(b.open),
          high: Number(b.high),
          low: Number(b.low),
          close: Number(b.close),
        }))
        .sort((a, b) => a.time - b.time);

      const volumeData = bars
        .map((b) => ({
          time: Number(b.time),
          value: Number(b.volume || 0),
          color: b.close >= b.open ? 'rgba(34, 197, 94, 0.45)' : 'rgba(239, 68, 68, 0.45)',
        }))
        .sort((a, b) => a.time - b.time);

      candleSeries.setData(candleData);
      volumeSeries.setData(volumeData);
      chart.timeScale().fitContent();
    }

    // Crosshair move handler to update OHLCV legend
    chart.subscribeCrosshairMove((param) => {
      if (!param || !param.time || !param.seriesPrices) {
        setHoveredCandle(null);
        return;
      }
      const candlePrice = param.seriesPrices.get(candleSeries);
      const volPrice = param.seriesPrices.get(volumeSeries);
      if (candlePrice) {
        setHoveredCandle({
          time: param.time,
          open: candlePrice.open,
          high: candlePrice.high,
          low: candlePrice.low,
          close: candlePrice.close,
          volume: volPrice || 0,
        });
      } else {
        setHoveredCandle(null);
      }
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    // Resize observer for responsive layout
    const ro = new ResizeObserver((entries) => {
      if (!entries || !entries[0] || !chartRef.current) return;
      const cr = entries[0].contentRect;
      chartRef.current.applyOptions({
        width: Math.max(cr.width, 320),
        height: Math.max(cr.height, 400),
      });
    });
    ro.observe(container);

    return () => {
      ro.disconnect();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [bars, isLightMode]);

  const handleFitContent = () => {
    if (chartRef.current) {
      chartRef.current.timeScale().fitContent();
    }
  };

  return (
    <section className="advanced-trading-chart" aria-label={`${cleanSymbol} Futures open-source chart`}>
      {/* 1. Header with Account Selector & Contract Highlights */}
      <header className="advanced-chart-header" style={{ flexWrap: 'wrap', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap', width: '100%' }}>
          {/* Webull Account Selector */}
          {accounts.length > 0 && (
            <div className="advanced-chart-pair-control" style={{ width: 'min(100%, 300px)' }}>
              <span className="advanced-chart-control-label">Webull Futures Account</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {allowDefaultAccount && (
                  <button
                    type="button"
                    onClick={() => onSetDefaultAccount?.(selectedAccountId)}
                    disabled={!selectedAccountId || savingDefaultAccount || selectedAccountId === defaultAccountId}
                    aria-label={selectedAccountId === defaultAccountId ? 'Selected account is default' : 'Set as default'}
                    aria-pressed={selectedAccountId === defaultAccountId}
                    title={selectedAccountId === defaultAccountId ? 'Default Webull account' : 'Make this the default Webull account'}
                    style={{
                      flex: '0 0 38px',
                      height: '38px',
                      borderRadius: '8px',
                      border: isLightMode ? '1px solid #cbd5e1' : '1px solid rgba(129, 140, 248, 0.4)',
                      background: isLightMode ? '#ffffff' : '#0f172a',
                      color: selectedAccountId === defaultAccountId ? '#f59e0b' : (isLightMode ? '#64748b' : '#94a3b8'),
                      fontSize: '22px',
                      lineHeight: 1,
                      cursor: selectedAccountId === defaultAccountId || savingDefaultAccount ? 'default' : 'pointer',
                    }}
                  >
                    {savingDefaultAccount ? '…' : selectedAccountId === defaultAccountId ? '★' : '☆'}
                  </button>
                )}
                <select
                  value={selectedAccountId}
                  onChange={(e) => onAccountChange?.(e.target.value)}
                  aria-label="Select Webull Account"
                  style={{
                    flex: 1,
                    minWidth: 0,
                    padding: '9px 12px',
                    borderRadius: '8px',
                    background: isLightMode ? '#ffffff' : '#0f172a',
                    color: isLightMode ? '#0f172a' : '#f8fafc',
                    border: isLightMode ? '1px solid #cbd5e1' : '1px solid rgba(129, 140, 248, 0.4)',
                    fontSize: '13px',
                    fontWeight: 600,
                  }}
                >
                  {accounts.map((acc) => (
                    <option key={acc.account_id} value={acc.account_id}>
                      {acc.account_name || acc.account_label || acc.account_id} ({acc.account_type || 'Margin'})
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {/* Product Badge */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: '220px' }}>
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: '40px',
                height: '40px',
                borderRadius: '10px',
                background: 'linear-gradient(135deg, #4f46e5, #06b6d4)',
                color: '#ffffff',
                fontWeight: 800,
                fontSize: '14px',
                boxShadow: '0 4px 12px rgba(79, 70, 229, 0.35)',
              }}
            >
              <FiActivity size={20} />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontWeight: 800, fontSize: '17px', color: isLightMode ? '#0f172a' : '#ffffff' }}>
                  {cleanSymbol}
                </span>
                <span
                  style={{
                    fontSize: '11px',
                    fontWeight: 700,
                    padding: '2px 8px',
                    borderRadius: '6px',
                    background: 'rgba(99, 102, 241, 0.15)',
                    color: '#818cf8',
                    border: '1px solid rgba(99, 102, 241, 0.3)',
                  }}
                >
                  {exchange}
                </span>
              </div>
              <div style={{ fontSize: '12px', color: isLightMode ? '#64748b' : '#94a3b8' }}>
                {productName}
              </div>
            </div>
          </div>

          {/* Timeframe & Action Controls */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginLeft: 'auto', flexWrap: 'wrap' }}>
            <div
              style={{
                display: 'inline-flex',
                padding: '3px',
                borderRadius: '8px',
                background: isLightMode ? '#f1f5f9' : '#0f172a',
                border: isLightMode ? '1px solid #cbd5e1' : '1px solid rgba(51, 65, 85, 0.6)',
              }}
            >
              {TIMEFRAMES.map((tf) => {
                const isActive = timeframe === tf.value;
                return (
                  <button
                    key={tf.value}
                    type="button"
                    onClick={() => setTimeframe(tf.value)}
                    style={{
                      padding: '5px 12px',
                      borderRadius: '6px',
                      fontSize: '12px',
                      fontWeight: isActive ? 700 : 500,
                      background: isActive ? (isLightMode ? '#ffffff' : '#6366f1') : 'transparent',
                      color: isActive ? (isLightMode ? '#4f46e5' : '#ffffff') : (isLightMode ? '#64748b' : '#94a3b8'),
                      border: 'none',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                      boxShadow: isActive ? '0 2px 6px rgba(0, 0, 0, 0.15)' : 'none',
                    }}
                  >
                    {tf.label}
                  </button>
                );
              })}
            </div>

            <button
              type="button"
              onClick={handleFitContent}
              title="Reset Zoom / Fit Content"
              aria-label="Fit Chart Content"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: '36px',
                height: '36px',
                borderRadius: '8px',
                background: isLightMode ? '#f1f5f9' : '#0f172a',
                border: isLightMode ? '1px solid #cbd5e1' : '1px solid rgba(51, 65, 85, 0.6)',
                color: isLightMode ? '#475569' : '#94a3b8',
                cursor: 'pointer',
              }}
            >
              <FiMaximize2 size={16} />
            </button>

            <button
              type="button"
              onClick={fetchBars}
              disabled={loading}
              title="Refresh Market Bars"
              aria-label="Refresh Market Bars"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: '36px',
                height: '36px',
                borderRadius: '8px',
                background: isLightMode ? '#f1f5f9' : '#0f172a',
                border: isLightMode ? '1px solid #cbd5e1' : '1px solid rgba(51, 65, 85, 0.6)',
                color: isLightMode ? '#475569' : '#94a3b8',
                cursor: loading ? 'default' : 'pointer',
              }}
            >
              <FiRefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>
      </header>

      {/* 2. OHLCV Metrics & Live Banner */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '16px',
          padding: '10px 20px',
          borderBottom: isLightMode ? '1px solid #e2e8f0' : '1px solid rgba(51, 65, 85, 0.5)',
          background: isLightMode ? '#f8fafc' : 'rgba(15, 23, 42, 0.6)',
          fontSize: '13px',
          flexWrap: 'wrap',
        }}
      >
        {/* Left: Latest Price & Change */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          {stats ? (
            <>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
                <span style={{ fontSize: '20px', fontWeight: 800, color: isLightMode ? '#0f172a' : '#f8fafc' }}>
                  ${stats.lastPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '4px',
                    fontWeight: 700,
                    fontSize: '12px',
                    color: stats.change >= 0 ? '#22c55e' : '#ef4444',
                  }}
                >
                  {stats.change >= 0 ? <FiTrendingUp size={14} /> : <FiTrendingDown size={14} />}
                  {stats.change >= 0 ? '+' : ''}{stats.change.toFixed(2)} ({stats.changePct >= 0 ? '+' : ''}{stats.changePct.toFixed(2)}%)
                </span>
              </div>
            </>
          ) : (
            <span style={{ color: '#94a3b8' }}>Loading quotes…</span>
          )}
        </div>

        {/* Center: Hovered Candle OHLCV Display */}
        {activeCandle && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              fontFamily: 'monospace',
              fontSize: '12px',
              color: isLightMode ? '#475569' : '#94a3b8',
            }}
          >
            <span>O: <strong style={{ color: isLightMode ? '#0f172a' : '#e2e8f0' }}>{activeCandle.open?.toFixed(2)}</strong></span>
            <span>H: <strong style={{ color: '#22c55e' }}>{activeCandle.high?.toFixed(2)}</strong></span>
            <span>L: <strong style={{ color: '#ef4444' }}>{activeCandle.low?.toFixed(2)}</strong></span>
            <span>C: <strong style={{ color: isLightMode ? '#0f172a' : '#e2e8f0' }}>{activeCandle.close?.toFixed(2)}</strong></span>
            {activeCandle.volume > 0 && (
              <span>Vol: <strong style={{ color: '#818cf8' }}>{Math.round(activeCandle.volume).toLocaleString()}</strong></span>
            )}
          </div>
        )}

        {/* Right: Data Source Badge */}
        {dataSource && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span
              style={{
                fontSize: '11px',
                fontWeight: 600,
                color: isLightMode ? '#64748b' : '#64748b',
                background: isLightMode ? '#e2e8f0' : 'rgba(51, 65, 85, 0.4)',
                padding: '2px 8px',
                borderRadius: '4px',
              }}
            >
              {dataSource}
            </span>
          </div>
        )}
      </div>

      {/* 3. Open-Source Lightweight Chart Area */}
      <div
        style={{
          position: 'relative',
          width: '100%',
          height: '560px',
          minHeight: '480px',
          background: isLightMode ? '#ffffff' : '#0b1220',
        }}
      >
        {loading && bars.length === 0 && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '12px',
              background: isLightMode ? 'rgba(255, 255, 255, 0.85)' : 'rgba(11, 18, 32, 0.85)',
              zIndex: 3,
            }}
          >
            <FiRefreshCw size={32} className="animate-spin" style={{ color: '#6366f1' }} />
            <span style={{ fontWeight: 600, color: isLightMode ? '#475569' : '#94a3b8' }}>
              Loading {cleanSymbol} futures chart…
            </span>
          </div>
        )}

        {error && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '12px',
              padding: '20px',
              background: isLightMode ? 'rgba(254, 242, 242, 0.95)' : 'rgba(69, 10, 10, 0.92)',
              color: '#ef4444',
              zIndex: 4,
              textAlign: 'center',
            }}
          >
            <span style={{ fontWeight: 700, fontSize: '15px' }}>{error}</span>
            <button
              type="button"
              onClick={fetchBars}
              style={{
                padding: '8px 16px',
                borderRadius: '8px',
                background: '#ef4444',
                color: '#ffffff',
                border: 'none',
                fontWeight: 700,
                cursor: 'pointer',
              }}
            >
              Retry
            </button>
          </div>
        )}

        <div
          ref={chartContainerRef}
          style={{ width: '100%', height: '100%', outline: 'none' }}
        />
      </div>

      {/* 4. Footer Note */}
      <footer
        className="advanced-chart-sync-note"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 16px',
          fontSize: '12px',
        }}
      >
        <span>
          Native open-source candlestick chart backed by live CME & continuous futures data.
        </span>
        <span style={{ color: '#6366f1', fontWeight: 600 }}>
          Trading active for {cleanSymbol}
        </span>
      </footer>
    </section>
  );
}
