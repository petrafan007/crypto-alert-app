import React, { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import { createChart } from 'lightweight-charts';
import { CHART_RANGES, DEFAULT_CHART_RANGE, formatChartTick } from '../utils/chartRanges';
import './TradeTimelineChart.css';

const WEBULL_RANGES = {
  '1d': { interval: 'M5', limit: 288, intervalSeconds: 300 },
  '3d': { interval: 'M15', limit: 288, intervalSeconds: 900 },
  '5d': { interval: 'M30', limit: 240, intervalSeconds: 1800 },
  '7d': { interval: 'H1', limit: 168, intervalSeconds: 3600 },
  '14d': { interval: 'H1', limit: 336, intervalSeconds: 3600 },
  '30d': { interval: 'H1', limit: 720, intervalSeconds: 3600 },
  '90d': { interval: 'H4', limit: 540, intervalSeconds: 14400 },
  '180d': { interval: 'D', limit: 180, intervalSeconds: 86400 },
  '365d': { interval: 'D', limit: 365, intervalSeconds: 86400 },
  '730d': { interval: 'D', limit: 730, intervalSeconds: 86400 },
  all: { interval: 'W', limit: 1000, intervalSeconds: 604800 },
};

const CHARTABLE_TYPES = new Set(['CRYPTO', 'STOCK', 'EQUITY', 'ETF', 'OPTION']);
const toTimestamp = (value) => {
  const numeric = Number(value);
  if (Number.isFinite(numeric) && numeric > 0) return Math.floor(numeric > 1e11 ? numeric / 1000 : numeric);
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? Math.floor(parsed / 1000) : null;
};
const number = (value, digits = 2) => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: digits });
const displayType = (holding) => String(holding?.instrument_type || 'Security').replace(/_/g, ' ');
const isChartable = (holding) => CHARTABLE_TYPES.has(String(holding?.instrument_type || '').toUpperCase());

const normalizeOrder = (order, index) => {
  const side = String(order?.side || order?.action || '').toUpperCase();
  const status = String(order?.status || order?.order_status || '').toUpperCase();
  const time = toTimestamp(order?.filled_at || order?.filled_time_at || order?.updated_at || order?.created_at || order?.create_time || order?.placed_time || order?.place_time);
  const quantity = Number(order?.filled_quantity ?? order?.executed_quantity ?? order?.filled_qty ?? order?.total_quantity ?? order?.order_quantity ?? order?.quantity ?? 0);
  const price = Number(order?.filled_price ?? order?.average_filled_price ?? order?.avg_fill_price ?? order?.avg_price ?? order?.price ?? order?.limit_price ?? 0);
  if (!time || !['BUY', 'SELL', 'SHORT'].includes(side) || !['FILLED', 'COMPLETED', 'EXECUTED'].includes(status) || quantity <= 0 || price <= 0) return null;
  const markerSide = side === 'SHORT' ? 'SELL' : side;
  return { ...order, id: order.id || order.order_id || order.orderId || `${time}-${side}-${index}`, side: markerSide, actionSide: side, time, quantity, price };
};

export default function WebullTradeTimelineChart({ holdings = [], orders = [], isLightMode = false, isTestMode = false }) {
  const hostRef = useRef(null);
  const markerGroupsRef = useRef(new Map());
  const [selectedId, setSelectedId] = useState('');
  const [range, setRange] = useState(DEFAULT_CHART_RANGE);
  const [bars, setBars] = useState([]);
  const [status, setStatus] = useState('idle');
  const [error, setError] = useState('');
  const [hoveredTrades, setHoveredTrades] = useState(null);
  const [optionMarketData, setOptionMarketData] = useState(null);
  const [optionMarketMessage, setOptionMarketMessage] = useState('');
  const chartConfig = WEBULL_RANGES[range] || WEBULL_RANGES[DEFAULT_CHART_RANGE];
  const chartableHolding = useMemo(() => holdings.find(isChartable), [holdings]);
  const selectedHolding = useMemo(
    () => holdings.find((holding) => String(holding.id) === selectedId) || chartableHolding || holdings[0] || null,
    [chartableHolding, holdings, selectedId],
  );
  const selectedIsChartable = isChartable(selectedHolding);
  const symbol = String(selectedHolding?.symbol || '').toUpperCase();
  const instrumentType = String(selectedHolding?.instrument_type || '').toUpperCase();
  const isOption = instrumentType === 'OPTION';

  useEffect(() => {
    const selectionStillExists = holdings.some((holding) => String(holding.id) === selectedId);
    if ((!selectedId || !selectionStillExists) && chartableHolding?.id) setSelectedId(String(chartableHolding.id));
  }, [chartableHolding, holdings, selectedId]);

  useEffect(() => {
    if (!selectedHolding || !selectedIsChartable) {
      setBars([]); setStatus('idle'); setError(''); setHoveredTrades(null);
      return undefined;
    }
    const controller = new AbortController();
    setStatus('loading'); setError(''); setHoveredTrades(null);
    axios.get('/api/webull/market-bars', {
      params: { holding_id: selectedHolding.id, interval: chartConfig.interval, limit: chartConfig.limit },
      withCredentials: true, signal: controller.signal,
    }).then((response) => {
      const normalized = (response.data?.bars || []).map((bar) => ({ time: toTimestamp(bar.time), value: Number(bar.close) }))
        .filter((bar) => bar.time && Number.isFinite(bar.value) && bar.value > 0)
        .sort((a, b) => a.time - b.time);
      setBars(normalized); setStatus('ready');
    }).catch((requestError) => {
      if (requestError.code === 'ERR_CANCELED' || requestError.name === 'CanceledError') return;
      setError(requestError.response?.data?.message || 'Unable to load Webull market data.'); setStatus('error');
    });
    return () => controller.abort();
  }, [chartConfig.interval, chartConfig.limit, instrumentType, selectedHolding, selectedIsChartable, symbol]);

  useEffect(() => {
    if (!selectedHolding || !isOption) {
      setOptionMarketData(null); setOptionMarketMessage('');
      return undefined;
    }
    const controller = new AbortController();
    setOptionMarketData(null); setOptionMarketMessage('Loading option contract details…');
    axios.get('/api/webull/option-market-data', { params: { holding_id: selectedHolding.id }, withCredentials: true, signal: controller.signal })
      .then((response) => {
        setOptionMarketData(response.data || null);
        setOptionMarketMessage(response.data?.message || '');
      }).catch((requestError) => {
        if (requestError.code === 'ERR_CANCELED' || requestError.name === 'CanceledError') return;
        setOptionMarketData(null); setOptionMarketMessage(requestError.response?.data?.message || 'Unable to load option contract details.');
      });
    return () => controller.abort();
  }, [isOption, selectedHolding]);

  const fills = useMemo(() => (orders || [])
    .filter((order) => String(order?.symbol || order?.ticker || '').toUpperCase() === symbol)
    .map(normalizeOrder).filter(Boolean).sort((a, b) => a.time - b.time), [orders, symbol]);

  const chartData = useMemo(() => {
    const groups = new Map();
    fills.forEach((fill) => {
      const closest = bars.reduce((best, bar) => (!best || Math.abs(bar.time - fill.time) < Math.abs(best.time - fill.time) ? bar : best), null);
      if (!closest || Math.abs(closest.time - fill.time) > chartConfig.intervalSeconds * 3) return;
      const key = String(closest.time);
      if (!groups.has(key)) groups.set(key, { time: closest.time, price: closest.value, trades: [] });
      groups.get(key).trades.push(fill);
    });
    const markers = [];
    groups.forEach((group) => ['BUY', 'SELL'].forEach((side) => {
      if (!group.trades.some((trade) => trade.side === side)) return;
      markers.push({ time: group.time, position: side === 'BUY' ? 'belowBar' : 'aboveBar', color: side === 'BUY' ? '#22c55e' : '#ef4444', shape: side === 'BUY' ? 'arrowUp' : 'arrowDown', size: 2 });
    }));
    return { groups, markers: markers.sort((a, b) => a.time - b.time) };
  }, [bars, chartConfig.intervalSeconds, fills]);

  useEffect(() => {
    if (!hostRef.current || !bars.length) return undefined;
    const dark = !isLightMode;
    const chart = createChart(hostRef.current, {
      width: Math.max(320, Math.floor(hostRef.current.getBoundingClientRect().width)), height: 610,
      layout: { background: { color: dark ? '#0b1220' : '#ffffff' }, textColor: dark ? '#cbd5e1' : '#334155' },
      grid: { vertLines: { color: dark ? '#17213a' : '#e2e8f0' }, horzLines: { color: dark ? '#17213a' : '#e2e8f0' } },
      rightPriceScale: { visible: true, minimumWidth: 84, borderColor: dark ? '#334155' : '#cbd5e1', scaleMargins: { top: 0.1, bottom: 0.1 } },
      leftPriceScale: { visible: false },
      timeScale: { borderColor: dark ? '#334155' : '#cbd5e1', timeVisible: range === '1d', secondsVisible: false, tickMarkFormatter: (time) => formatChartTick(time, range) },
      crosshair: { mode: 1 },
    });
    const series = chart.addLineSeries({ color: '#38bdf8', lineWidth: 2, priceLineVisible: true, lastValueVisible: true });
    series.setData(bars); series.setMarkers(chartData.markers); chart.timeScale().fitContent(); markerGroupsRef.current = chartData.groups;
    const resolveMarker = (param) => {
      if (!param?.time || !param.point) return null;
      const group = markerGroupsRef.current.get(String(param.time));
      if (!group?.trades?.length) return null;
      const lineY = series.priceToCoordinate(group.price);
      if (lineY === null || Math.abs(param.point.y - lineY) > 72 || Math.abs(param.point.y - lineY) < 5) return null;
      const side = param.point.y > lineY ? 'BUY' : 'SELL';
      const trades = group.trades.filter((trade) => trade.side === side);
      return trades.length ? { group, side, trades } : null;
    };
    const onMove = (param) => {
      const marker = resolveMarker(param);
      if (!marker) { setHoveredTrades(null); return; }
      const host = hostRef.current; const tooltipWidth = 350; const tooltipHeight = Math.min(300, 112 + marker.trades.length * 42);
      const candidate = host.offsetLeft + param.point.x + 18;
      const left = candidate + tooltipWidth <= host.parentElement.clientWidth ? candidate : host.offsetLeft + param.point.x - tooltipWidth - 18;
      setHoveredTrades({ ...marker, left: Math.max(10, Math.min(left, host.parentElement.clientWidth - tooltipWidth - 10)), top: Math.max(10, Math.min(host.offsetTop + param.point.y - 30, host.parentElement.clientHeight - tooltipHeight - 10)) });
    };
    chart.subscribeCrosshairMove(onMove);
    const resize = () => chart.resize(Math.max(320, Math.floor(hostRef.current?.getBoundingClientRect().width || 0)), 610);
    const observer = new ResizeObserver(() => window.requestAnimationFrame(resize)); observer.observe(hostRef.current); window.requestAnimationFrame(resize);
    return () => { observer.disconnect(); chart.unsubscribeCrosshairMove(onMove); chart.remove(); };
  }, [bars, chartData, isLightMode, range]);

  if (!holdings.length) return <div className="empty-state"><p>{isTestMode ? 'No simulated paper holdings are available for the Trade Chart yet.' : 'No imported Webull holdings. Import a Webull portfolio snapshot in Settings first.'}</p></div>;
  const currency = String(selectedHolding?.currency || 'USD').toUpperCase();
  return <section className="trade-timeline-card webull-trade-chart">
    <header className="trade-timeline-header">
      <div><h2>My {symbol} Webull Trade Chart</h2><p>{isTestMode ? 'Paper-only price history markers; live Webull transactions are hidden.' : 'Live-account Webull price history; simulated paper transactions are hidden.'}</p></div>
      <div className="trade-timeline-controls">
        <label className="trade-timeline-pair-select"><span>Webull Holding</span><select value={selectedId || String(selectedHolding?.id || '')} onChange={(event) => setSelectedId(event.target.value)} aria-label="Webull holding">
          {holdings.map((holding) => <option key={holding.id} value={String(holding.id)}>{holding.symbol} · {displayType(holding)}{isChartable(holding) ? '' : ' — chart unavailable'}</option>)}
        </select></label>
        <label className="trade-timeline-range-control"><span>Range</span><select value={range} onChange={(event) => setRange(event.target.value)} aria-label="Webull Trade Chart date range">{CHART_RANGES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
      </div>
    </header>
    {!selectedIsChartable ? <div className="empty-state webull-chart-notice"><h3>{symbol} chart unavailable</h3><p>This Webull instrument type does not have a supported chart.</p></div> : <>
      {isOption && <OptionContractDetails marketData={optionMarketData} message={optionMarketMessage} currency={currency} />}
      <div className="trade-timeline-legend"><span className="buy">↑ Purchase</span><span className="sell">↓ Sale</span><span>Y-axis: {currency} price</span><span>X-axis: date and time</span><span>Webull · read-only</span></div>
      <div className="trade-timeline-chart-shell"><div className="trade-timeline-chart-frame"><div ref={hostRef} className="trade-timeline-chart" /></div>
        {hoveredTrades && <div className={`trade-marker-tooltip ${hoveredTrades.side.toLowerCase()}`} style={{ left: hoveredTrades.left, top: hoveredTrades.top }} role="tooltip"><strong>{hoveredTrades.side === 'BUY' ? '↑ Purchase' : '↓ Sale / Short'} · {symbol}</strong><time>{new Date(hoveredTrades.group.time * 1000).toLocaleDateString('en-US', { timeZone: 'UTC', year: 'numeric', month: 'long', day: 'numeric' })}</time><div className="trade-marker-tooltip-list">{hoveredTrades.trades.map((trade) => <div className="trade-marker-tooltip-row" key={trade.id}><span>{new Date(trade.time * 1000).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })}</span><span>{trade.actionSide === 'SHORT' ? 'SHORT · ' : ''}{number(trade.quantity, 8)} {symbol} @ {number(trade.price, trade.price < 1 ? 8 : 2)} {currency}</span><b>{number(trade.quantity * trade.price, 2)} {currency}</b></div>)}</div></div>}
        {status === 'loading' && <div className="trade-timeline-status">Loading {symbol} price and Webull trade history…</div>}
        {status === 'error' && <div className="trade-timeline-status error">{error}</div>}
        {status === 'ready' && !fills.length && <div className="trade-timeline-empty">No completed Webull purchases or sales were found. The price line remains available.</div>}
      </div>
    </>}
  </section>;
}

function OptionContractDetails({ marketData, message, currency }) {
  const contract = marketData?.contract;
  const quote = marketData?.quote;
  const decimal = (value, digits = 4) => Number.isFinite(Number(value)) ? Number(value).toLocaleString(undefined, { maximumFractionDigits: digits }) : '—';
  return <div className="webull-option-details" aria-live="polite">
    {contract ? <><strong>{contract.label}</strong><span>Contract ID: {contract.instrument_id}</span><span>Multiplier: {decimal(contract.multiplier, 0)}</span></> : <strong>Option contract details</strong>}
    {quote ? <><span>Last: {decimal(quote.last_price)} {currency}</span><span>Bid / Ask: {decimal(quote.bid)} / {decimal(quote.ask)}</span><span>IV: {Number.isFinite(Number(quote.implied_volatility)) ? `${(Number(quote.implied_volatility) * 100).toFixed(2)}%` : '—'}</span><span>Δ {decimal(quote.delta)} · Γ {decimal(quote.gamma)} · Θ {decimal(quote.theta)} · Vega {decimal(quote.vega)}</span></> : <span>{message || 'Option quote unavailable.'}</span>}
  </div>;
}
