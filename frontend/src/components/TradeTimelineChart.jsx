import React, { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import { createChart } from 'lightweight-charts';
import SearchablePairSelect from './SearchablePairSelect';
import TransactionModal from './TransactionModal';
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
  const [modal, setModal] = useState({ isOpen: false, transactions: [], type: 'BUY', dateStr: '' });
  const normalized = normalizePair(symbol);
  const { base, quote } = pairAssets(normalized);

  useEffect(() => {
    const controller = new AbortController();
    setStatus('loading');
    setError('');
    Promise.all([
      axios.get(`/api/trading/klines/${normalized}`, { params: { interval: '1d', limit: 1000 }, signal: controller.signal, withCredentials: true }),
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
  }, [base, normalized]);

  const chartData = useMemo(() => {
    const byDay = new Map();
    trades.forEach(trade => {
      const candle = prices.reduce((closest, point) => Math.abs(point.time - trade.time) < Math.abs(closest.time - trade.time) ? point : closest, prices[0]);
      if (!candle || Math.abs(candle.time - trade.time) > 172800) return;
      const key = String(candle.time);
      if (!byDay.has(key)) byDay.set(key, { time: candle.time, trades: [] });
      byDay.get(key).trades.push(trade);
    });
    const markers = [];
    byDay.forEach(group => {
      ['BUY', 'SELL'].forEach(type => {
        const items = group.trades.filter(t => t.type === type);
        if (!items.length) return;
        const amount = items.reduce((sum, trade) => sum + trade.amount, 0);
        const value = items.reduce((sum, trade) => sum + trade.amount * trade.price, 0);
        const average = value / amount;
        markers.push({
          time: group.time,
          position: type === 'BUY' ? 'belowBar' : 'aboveBar',
          color: type === 'BUY' ? '#22c55e' : '#ef4444',
          shape: type === 'BUY' ? 'arrowUp' : 'arrowDown',
          text: `${type} ${fmt(amount, 8)} ${base} @ ${fmt(average, average < 1 ? 8 : 2)} · ${fmt(value, 2)} ${quote}`,
        });
      });
    });
    return { markers: markers.sort((a, b) => a.time - b.time), groups: byDay };
  }, [base, prices, quote, trades]);

  useEffect(() => {
    if (!hostRef.current || !prices.length) return undefined;
    const dark = !isLightMode;
    const chart = createChart(hostRef.current, {
      width: hostRef.current.clientWidth, height: 610,
      layout: { background: { color: dark ? '#0b1220' : '#ffffff' }, textColor: dark ? '#cbd5e1' : '#334155' },
      grid: { vertLines: { color: dark ? '#17213a' : '#e2e8f0' }, horzLines: { color: dark ? '#17213a' : '#e2e8f0' } },
      rightPriceScale: { visible: true, borderColor: dark ? '#334155' : '#cbd5e1' },
      leftPriceScale: { visible: false },
      timeScale: { borderColor: dark ? '#334155' : '#cbd5e1', timeVisible: false, tickMarkFormatter: time => {
        const date = new Date(Number(time) * 1000);
        return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', timeZone: 'UTC' });
      } },
      crosshair: { mode: 1 },
    });
    const series = chart.addLineSeries({ color: '#38bdf8', lineWidth: 2, priceLineVisible: true });
    series.setData(prices);
    series.setMarkers(chartData.markers);
    chart.timeScale().fitContent();
    markerGroupsRef.current = chartData.groups;
    const click = param => {
      if (!param.time) return;
      const group = markerGroupsRef.current.get(String(param.time));
      if (!group?.trades?.length) return;
      const dateStr = new Date(group.time * 1000).toLocaleDateString('en-US', { timeZone: 'UTC', year: 'numeric', month: 'long', day: 'numeric' });
      setModal({ isOpen: true, transactions: group.trades, type: group.trades[0].type, dateStr });
    };
    chart.subscribeClick(click);
    const observer = new ResizeObserver(entries => chart.applyOptions({ width: entries[0].contentRect.width }));
    observer.observe(hostRef.current);
    chartRef.current = chart;
    seriesRef.current = series;
    return () => { observer.disconnect(); chart.unsubscribeClick(click); chart.remove(); chartRef.current = null; seriesRef.current = null; };
  }, [chartData, isLightMode, prices]);

  return (
    <section className="trade-timeline-card">
      <header className="trade-timeline-header">
        <div><h2>My {base}/{quote} Trade Chart</h2><p>Daily price history with exact-pair purchases and sales. Click an arrow for exact execution times and details.</p></div>
        <SearchablePairSelect value={normalized} onChange={onSymbolChange} tradingPairs={tradingPairs} placeholder="Search trading pairs…" />
      </header>
      <div className="trade-timeline-legend"><span className="buy">↑ Purchase</span><span className="sell">↓ Sale</span><span>Y-axis: {quote} price</span><span>X-axis: year and month</span></div>
      <div className="trade-timeline-chart-shell">
        <div ref={hostRef} className="trade-timeline-chart" />
        {status === 'loading' && <div className="trade-timeline-status">Loading {base}/{quote} price and trade history…</div>}
        {status === 'error' && <div className="trade-timeline-status error">{error}</div>}
        {status === 'ready' && !trades.length && <div className="trade-timeline-empty">No completed {base}/{quote} purchases or sales were found. The price line remains available.</div>}
      </div>
      <TransactionModal isOpen={modal.isOpen} onClose={() => setModal(prev => ({ ...prev, isOpen: false }))} transactions={modal.transactions} type={modal.type} dateStr={modal.dateStr} quoteAsset={quote} />
    </section>
  );
}
