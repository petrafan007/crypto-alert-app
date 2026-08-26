import React, { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import { createChart } from 'lightweight-charts';
import SearchablePairSelect from './SearchablePairSelect';
import TransactionModal from './TransactionModal';
import { CHART_RANGES, DEFAULT_CHART_RANGE, formatChartTick, getChartRange } from '../utils/chartRanges';
import './TradeTimelineChart.css';

const normalizePair = value => String(value || 'BTCUSDT').toUpperCase().replace(/[^A-Z0-9]/g, '');

const pairAssets = symbol => {
  if (symbol.endsWith('USDT')) return { base: symbol.slice(0, -4), quote: 'USDT' };
  if (symbol.endsWith('USD')) return { base: symbol.slice(0, -3), quote: 'USD' };
  return { base: symbol, quote: 'USDT' };
};

const normalizeTrade = (trade, index, base) => {
  const rawTime = trade.filled_at || trade.updated_at || trade.created_at || trade.time;
  const numeric = Number(rawTime);
  const time = Number.isFinite(numeric) && numeric > 0
    ? Math.floor(numeric > 1e11 ? numeric / 1000 : numeric)
    : Math.floor(new Date(rawTime).getTime() / 1000);
  const type = String(trade.side || trade.type || '').toUpperCase();
  const status = String(trade.status || '').toUpperCase();
  const amount = Number(trade.filled_quantity ?? trade.executed_qty ?? trade.executedQty ?? trade.quantity ?? 0);
  const price = Number(trade.filled_price ?? trade.avg_fill_price ?? trade.price ?? 0);
  if (!Number.isFinite(time) || !['BUY', 'SELL'].includes(type) || !['FILLED', 'COMPLETED'].includes(status) || amount <= 0 || price <= 0) return null;
  return { ...trade, id: trade.id || `${time}-${type}-${index}`, time, type, amount, price, asset: base };
};

const fmt = (value, digits = 2) => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: digits });

export default function TradeTimelineChart({ symbol, onSymbolChange, tradingPairs = [], isLightMode = false }) {
  const hostRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const markerGroupsRef = useRef(new Map());
  const [prices, setPrices] = useState([]);
  const [trades, setTrades] = useState([]);
  const [status, setStatus] = useState('loading');
  const [error, setError] = useState('');
  const [range, setRange] = useState(DEFAULT_CHART_RANGE);
  const [hoveredTrades, setHoveredTrades] = useState(null);
  const [modal, setModal] = useState({ isOpen: false, transactions: [], type: 'BUY', dateStr: '' });
  const normalized = normalizePair(symbol);
  const { base, quote } = pairAssets(normalized);
  const rangeConfig = getChartRange(range);

  useEffect(() => {
    const controller = new AbortController();
    setStatus('loading');
    setError('');
    setHoveredTrades(null);
    Promise.all([
      axios.get(`/api/trading/klines/${normalized}`, { params: { interval: rangeConfig.interval, limit: rangeConfig.limit }, signal: controller.signal, withCredentials: true }),
      axios.get('/api/trading/real-orders', { params: { limit: 'all', symbol: normalized }, signal: controller.signal, withCredentials: true }),
    ]).then(([market, orders]) => {
      const line = (market.data?.klines || []).map(k => ({ time: Math.floor(Number(k.time)), value: Number(k.close) }))
        .filter(k => Number.isFinite(k.time) && Number.isFinite(k.value)).sort((a, b) => a.time - b.time);
      const fills = (orders.data?.orders || []).map((order, index) => normalizeTrade(order, index, base)).filter(Boolean).sort((a, b) => a.time - b.time);
      setPrices(line);
      setTrades(fills);
      setStatus('ready');
    }).catch(err => {
      if (err.code === 'ERR_CANCELED' || err.name === 'CanceledError') return;
      setError(err.response?.data?.error || err.message || 'Unable to load chart data.');
      setStatus('error');
    });
    return () => controller.abort();
  }, [base, normalized, rangeConfig.interval, rangeConfig.limit]);

  const chartData = useMemo(() => {
    const byDay = new Map();
    trades.forEach(trade => {
      const candle = prices.reduce((closest, point) => Math.abs(point.time - trade.time) < Math.abs(closest.time - trade.time) ? point : closest, prices[0]);
      if (!candle || Math.abs(candle.time - trade.time) > rangeConfig.intervalSeconds * 2) return;
      const key = String(candle.time);
      if (!byDay.has(key)) byDay.set(key, { time: candle.time, price: candle.value, trades: [] });
      byDay.get(key).trades.push(trade);
    });
    const markers = [];
    byDay.forEach(group => {
      ['BUY', 'SELL'].forEach(type => {
        const items = group.trades.filter(t => t.type === type);
        if (!items.length) return;
        markers.push({
          time: group.time,
          position: type === 'BUY' ? 'belowBar' : 'aboveBar',
          color: type === 'BUY' ? '#22c55e' : '#ef4444',
          shape: type === 'BUY' ? 'arrowUp' : 'arrowDown',
          size: 2,
        });
      });
    });
    return { markers: markers.sort((a, b) => a.time - b.time), groups: byDay };
  }, [prices, rangeConfig.intervalSeconds, trades]);

  useEffect(() => {
    if (!hostRef.current || !prices.length) return undefined;
    const dark = !isLightMode;
    const chart = createChart(hostRef.current, {
      width: Math.max(320, Math.floor(hostRef.current.getBoundingClientRect().width)), height: 610,
      layout: { background: { color: dark ? '#0b1220' : '#ffffff' }, textColor: dark ? '#cbd5e1' : '#334155' },
      grid: { vertLines: { color: dark ? '#17213a' : '#e2e8f0' }, horzLines: { color: dark ? '#17213a' : '#e2e8f0' } },
      rightPriceScale: { visible: true, minimumWidth: 84, borderColor: dark ? '#334155' : '#cbd5e1', scaleMargins: { top: 0.1, bottom: 0.1 } },
      leftPriceScale: { visible: false },
      timeScale: { borderColor: dark ? '#334155' : '#cbd5e1', timeVisible: range === '1d', secondsVisible: false, tickMarkFormatter: time => formatChartTick(time, range) },
      crosshair: { mode: 1 },
    });
    const series = chart.addLineSeries({ color: '#38bdf8', lineWidth: 2, priceLineVisible: true, lastValueVisible: true });
    series.setData(prices);
    series.setMarkers(chartData.markers);
    chart.timeScale().fitContent();
    markerGroupsRef.current = chartData.groups;
    const resolveMarker = param => {
      if (!param?.time || !param.point) return null;
      const group = markerGroupsRef.current.get(String(param.time));
      if (!group?.trades?.length) return null;
      const lineY = series.priceToCoordinate(group.price);
      if (lineY === null || Math.abs(param.point.y - lineY) > 72 || Math.abs(param.point.y - lineY) < 5) return null;
      const type = param.point.y > lineY ? 'BUY' : 'SELL';
      const transactions = group.trades.filter(trade => trade.type === type);
      if (!transactions.length) return null;
      return { group, type, transactions };
    };
    const hover = param => {
      const marker = resolveMarker(param);
      if (!marker) {
        setHoveredTrades(null);
        return;
      }
      const host = hostRef.current;
      const tooltipWidth = 350;
      const tooltipHeight = Math.min(300, 112 + marker.transactions.length * 42);
      const rightCandidate = host.offsetLeft + param.point.x + 18;
      const left = rightCandidate + tooltipWidth <= host.parentElement.clientWidth
        ? rightCandidate
        : host.offsetLeft + param.point.x - tooltipWidth - 18;
      setHoveredTrades({
        ...marker,
        left: Math.max(10, Math.min(left, host.parentElement.clientWidth - tooltipWidth - 10)),
        top: Math.max(10, Math.min(host.offsetTop + param.point.y - 30, host.parentElement.clientHeight - tooltipHeight - 10)),
      });
    };
    const click = param => {
      const marker = resolveMarker(param);
      if (!marker) return;
      const { group, type, transactions } = marker;
      const dateStr = new Date(group.time * 1000).toLocaleDateString('en-US', { timeZone: 'UTC', year: 'numeric', month: 'long', day: 'numeric' });
      setModal({ isOpen: true, transactions, type, dateStr });
    };
    chart.subscribeCrosshairMove(hover);
    chart.subscribeClick(click);
    const resizeChart = () => {
      const width = Math.max(320, Math.floor(hostRef.current?.getBoundingClientRect().width || 0));
      chart.resize(width, 610);
    };
    const observer = new ResizeObserver(() => window.requestAnimationFrame(resizeChart));
    observer.observe(hostRef.current);
    window.requestAnimationFrame(resizeChart);
    chartRef.current = chart;
    seriesRef.current = series;
    return () => { observer.disconnect(); chart.unsubscribeCrosshairMove(hover); chart.unsubscribeClick(click); chart.remove(); chartRef.current = null; seriesRef.current = null; };
  }, [chartData, isLightMode, prices, range]);

  return (
    <section className="trade-timeline-card">
      <header className="trade-timeline-header">
        <div><h2>My {base}/{quote} Trade Chart</h2><p>Price history with exact-pair purchases and sales. Click an arrow for exact execution times and details.</p></div>
        <div className="trade-timeline-controls">
          <div className="trade-timeline-pair-select">
            <SearchablePairSelect value={normalized} onChange={onSymbolChange} tradingPairs={tradingPairs} placeholder="Search trading pairs…" />
          </div>
          <label className="trade-timeline-range-control">
            <span>Range</span>
            <select value={range} onChange={event => setRange(event.target.value)} aria-label="Trade Chart date range">
              {CHART_RANGES.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
        </div>
      </header>
      <div className="trade-timeline-legend"><span className="buy">↑ Purchase</span><span className="sell">↓ Sale</span><span>Y-axis: {quote} price</span><span>X-axis: date and time</span></div>
      <div className="trade-timeline-chart-shell">
        <div className="trade-timeline-chart-frame">
          <div ref={hostRef} className="trade-timeline-chart" />
        </div>
        {hoveredTrades && (
          <div className={`trade-marker-tooltip ${hoveredTrades.type.toLowerCase()}`} style={{ left: hoveredTrades.left, top: hoveredTrades.top }} role="tooltip">
            <strong>{hoveredTrades.type === 'BUY' ? '↑ Purchase' : '↓ Sale'} · {base}/{quote}</strong>
            <time>{new Date(hoveredTrades.group.time * 1000).toLocaleDateString('en-US', { timeZone: 'UTC', year: 'numeric', month: 'long', day: 'numeric' })}</time>
            <div className="trade-marker-tooltip-list">
              {hoveredTrades.transactions.map(trade => (
                <div className="trade-marker-tooltip-row" key={trade.id}>
                  <span>{new Date(trade.time * 1000).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })}</span>
                  <span>{fmt(trade.amount, 8)} {base} @ {fmt(trade.price, trade.price < 1 ? 8 : 2)} {quote}</span>
                  <b>{fmt(trade.amount * trade.price, 2)} {quote}</b>
                </div>
              ))}
            </div>
            <small>Click the arrow for full transaction details.</small>
          </div>
        )}
        {status === 'loading' && <div className="trade-timeline-status">Loading {base}/{quote} price and trade history…</div>}
        {status === 'error' && <div className="trade-timeline-status error">{error}</div>}
        {status === 'ready' && !trades.length && <div className="trade-timeline-empty">No completed {base}/{quote} purchases or sales were found. The price line remains available.</div>}
      </div>
      <TransactionModal isOpen={modal.isOpen} onClose={() => setModal(prev => ({ ...prev, isOpen: false }))} transactions={modal.transactions} type={modal.type} dateStr={modal.dateStr} quoteAsset={quote} />
    </section>
  );
}
