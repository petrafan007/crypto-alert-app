import React, { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import { createChart } from 'lightweight-charts';
import SearchablePairSelect from './SearchablePairSelect';
import { CHART_RANGES, formatChartTick, getChartRange } from '../utils/chartRanges';
import './TradeTimelineChart.css';

const SIGNAL_STYLES = {
  'hold': { code: 'H' },
  'consider buying': { code: 'CB' },
  'buy immediately': { code: 'BI' },
  'consider selling': { code: 'CS' },
  'sell immediately': { code: 'SI' },
};

const OUTCOME_STYLES = {
  correct: { label: 'Correct', color: '#22c55e' },
  neutral: { label: 'Neutral', color: '#38bdf8' },
  wrong: { label: 'Wrong', color: '#ef4444' },
};

const normalizePair = value => String(value || 'BTCUSDT').toUpperCase().replace(/[^A-Z0-9]/g, '');
const pairAssets = symbol => symbol.endsWith('USDT')
  ? { base: symbol.slice(0, -4), quote: 'USDT' }
  : { base: symbol.endsWith('USD') ? symbol.slice(0, -3) : symbol, quote: symbol.endsWith('USD') ? 'USD' : 'USDT' };
const formatPair = pair => {
  const id = pair?.id || pair?.symbol || String(pair || '');
  const { base, quote } = pairAssets(id);
  const metadata = typeof pair === 'object' && pair ? pair : {};
  return { ...metadata, id, base_currency: metadata.base_currency || base, quote_currency: metadata.quote_currency || quote, display_name: metadata.display_name || `${base}/${quote}` };
};
const formatPrice = value => Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: Number(value) < 1 ? 8 : 2 });
const formatDelta = value => {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '';
  const numeric = Number(value);
  const decimals = Math.abs(numeric) > 0 && Math.abs(numeric) < 0.01 ? 4 : 2;
  const displayed = numeric === 0 ? (0).toFixed(decimals) : numeric.toFixed(decimals);
  return ` (${numeric > 0 ? '+' : ''}${displayed}%)`;
};
const formatEasternTime = value => {
  if (!value) return 'Waiting for the next check';
  const raw = String(value);
  const timestamp = new Date(/[zZ]$|[+-]\d\d:\d\d$/.test(raw) ? raw : `${raw}Z`);
  if (Number.isNaN(timestamp.getTime())) return 'Unknown time';
  return timestamp.toLocaleString('en-US', {
    timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
  });
};

export default function SentimentTimelineChart({ signals = [], range, onRangeChange, availableSymbols = [], isLightMode = false }) {
  const hostRef = useRef(null);
  const markerGroupsRef = useRef(new Map());
  const [markerBadges, setMarkerBadges] = useState([]);
  const [selectedPair, setSelectedPair] = useState('BTCUSDT');
  const [tradingPairs, setTradingPairs] = useState(() => availableSymbols.map(symbol => formatPair(`${symbol}USDT`)));
  const [prices, setPrices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [hoveredSignals, setHoveredSignals] = useState(null);
  const normalizedPair = normalizePair(selectedPair);
  const { base, quote } = pairAssets(normalizedPair);
  const rangeConfig = getChartRange(range);

  useEffect(() => {
    axios.get('/api/trading-pairs', { withCredentials: true }).then(response => {
      if (Array.isArray(response.data?.pairs) && response.data.pairs.length) {
        setTradingPairs(response.data.pairs.map(formatPair));
      }
    }).catch(errorValue => console.error('Unable to load Sentiment Chart pairs:', errorValue));
  }, []);

  useEffect(() => {
    if (!tradingPairs.length && availableSymbols.length) {
      setTradingPairs(availableSymbols.map(symbol => formatPair(`${symbol}USDT`)));
    }
  }, [availableSymbols, tradingPairs.length]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setHoveredSignals(null);
    axios.get(`/api/trading/klines/${normalizedPair}`, {
      params: { interval: rangeConfig.interval, limit: rangeConfig.limit },
      signal: controller.signal,
      withCredentials: true,
    }).then(response => {
      const nextPrices = (response.data?.klines || []).map(point => ({
        time: Math.floor(Number(point.time)), value: Number(point.close),
      })).filter(point => Number.isFinite(point.time) && Number.isFinite(point.value))
        .sort((a, b) => a.time - b.time);
      setPrices(nextPrices);
      setLoading(false);
    }).catch(errorValue => {
      if (errorValue.code === 'ERR_CANCELED' || errorValue.name === 'CanceledError') return;
      setPrices([]);
      setError(errorValue.response?.data?.error || errorValue.message || 'Unable to load sentiment price history.');
      setLoading(false);
    });
    return () => controller.abort();
  }, [normalizedPair, rangeConfig.interval, rangeConfig.limit]);

  const chartData = useMemo(() => {
    const groups = new Map();
    const lineByTime = new Map(prices.map(point => [String(point.time), point]));
    signals.filter(signal => (
      signal.symbol === base
      && (signal.source_type || 'portfolio') === 'portfolio'
      && OUTCOME_STYLES[signal.outcome_status]
    ))
      .forEach(signal => {
        const style = SIGNAL_STYLES[String(signal.sentiment || '').trim().toLowerCase()];
        const outcomeStyle = OUTCOME_STYLES[signal.outcome_status];
        const originalSignalTime = Number(signal.created_timestamp || Math.floor(new Date(signal.created_at).getTime() / 1000));
        const evaluationTime = Number(signal.evaluated_timestamp || Math.floor(new Date(signal.evaluated_at).getTime() / 1000));
        const evaluationPrice = Number(signal.evaluation_price);
        if (!style || !outcomeStyle || !Number.isFinite(originalSignalTime) || !Number.isFinite(evaluationTime) || evaluationPrice <= 0 || !prices.length) return;
        const candle = prices.reduce((closest, point) => Math.abs(point.time - evaluationTime) < Math.abs(closest.time - evaluationTime) ? point : closest, prices[0]);
        if (!candle || Math.abs(candle.time - evaluationTime) > rangeConfig.intervalSeconds * 2) return;
        const key = String(evaluationTime);
        lineByTime.set(key, { time: evaluationTime, value: evaluationPrice });
        if (!groups.has(key)) groups.set(key, { time: evaluationTime, price: evaluationPrice, signals: [] });
        groups.get(key).signals.push({ ...signal, style, outcomeStyle, originalSignalTime, evaluationTime });
      });

    const markers = [];
    groups.forEach(group => {
      const signal = group.signals[0];
      markers.push({
        time: group.time,
        position: 'inBar',
        shape: 'circle',
        color: signal.outcomeStyle.color,
        size: 1.5,
        text: `${signal.outcomeStyle.label}${formatDelta(signal.price_delta_pct ?? signal.outcome_pct)}`,
        id: String(signal.id),
      });
    });
    return {
      groups,
      lineData: Array.from(lineByTime.values()).sort((a, b) => a.time - b.time),
      markers: markers.sort((a, b) => a.time - b.time),
    };
  }, [base, prices, rangeConfig.intervalSeconds, signals]);

  useEffect(() => {
    if (!hostRef.current || !prices.length) return undefined;
    const dark = !isLightMode;
    const chart = createChart(hostRef.current, {
      width: Math.max(320, Math.floor(hostRef.current.getBoundingClientRect().width)), height: 610,
      layout: { background: { color: dark ? '#0b1220' : '#ffffff' }, textColor: dark ? '#cbd5e1' : '#334155' },
      grid: { vertLines: { color: dark ? '#17213a' : '#e2e8f0' }, horzLines: { color: dark ? '#17213a' : '#e2e8f0' } },
      rightPriceScale: { visible: true, minimumWidth: 84, borderColor: dark ? '#334155' : '#cbd5e1', scaleMargins: { top: .1, bottom: .1 } },
      leftPriceScale: { visible: false },
      timeScale: { borderColor: dark ? '#334155' : '#cbd5e1', timeVisible: range === '1d', secondsVisible: false, tickMarkFormatter: time => formatChartTick(time, range) },
      crosshair: { mode: 1 },
    });
    const series = chart.addLineSeries({ color: '#38bdf8', lineWidth: 2, priceLineVisible: true, lastValueVisible: true });
    series.setData(chartData.lineData);
    series.setMarkers(chartData.markers);
    chart.timeScale().fitContent();
    markerGroupsRef.current = chartData.groups;

    const updateMarkerBadges = () => {
      const host = hostRef.current;
      if (!host) return;
      const badges = chartData.markers.flatMap(marker => {
        const group = chartData.groups.get(String(marker.time));
        const signal = group?.signals?.[0];
        const x = chart.timeScale().timeToCoordinate(marker.time);
        const y = group ? series.priceToCoordinate(group.price) : null;
        if (!signal || x === null || y === null || x < 0 || y < 0 || x > host.clientWidth || y > host.clientHeight) return [];
        return [{
          id: marker.id,
          code: signal.style.code,
          color: signal.outcomeStyle.color,
          left: host.offsetLeft + x,
          top: host.offsetTop + y,
        }];
      });
      setMarkerBadges(badges);
    };

    const hover = param => {
      if (!param?.time || !param.point) return setHoveredSignals(null);
      const group = markerGroupsRef.current.get(String(param.time));
      if (!group?.signals?.length) return setHoveredSignals(null);
      const lineY = series.priceToCoordinate(group.price);
      if (lineY === null || Math.abs(param.point.y - lineY) > 30) return setHoveredSignals(null);
      const host = hostRef.current;
      const tooltipWidth = 370;
      const tooltipHeight = Math.min(480, 135 + group.signals.length * 170);
      const rightCandidate = host.offsetLeft + param.point.x + 18;
      const left = rightCandidate + tooltipWidth <= host.parentElement.clientWidth ? rightCandidate : host.offsetLeft + param.point.x - tooltipWidth - 18;
      setHoveredSignals({
        ...group,
        left: Math.max(10, Math.min(left, host.parentElement.clientWidth - tooltipWidth - 10)),
        top: Math.max(10, Math.min(host.offsetTop + param.point.y - 30, host.parentElement.clientHeight - tooltipHeight - 10)),
      });
    };
    chart.subscribeCrosshairMove(hover);
    const resizeChart = () => {
      chart.resize(Math.max(320, Math.floor(hostRef.current?.getBoundingClientRect().width || 0)), 610);
      window.requestAnimationFrame(updateMarkerBadges);
    };
    const observer = new ResizeObserver(() => window.requestAnimationFrame(resizeChart));
    observer.observe(hostRef.current);
    chart.timeScale().subscribeVisibleTimeRangeChange(updateMarkerBadges);
    window.requestAnimationFrame(() => { resizeChart(); updateMarkerBadges(); });
    return () => {
      observer.disconnect();
      chart.timeScale().unsubscribeVisibleTimeRangeChange(updateMarkerBadges);
      chart.unsubscribeCrosshairMove(hover);
      chart.remove();
    };
  }, [chartData, isLightMode, prices, range]);

  return (
    <section className="trade-timeline-card sentiment-timeline-card">
      <header className="trade-timeline-header">
        <div><h2>Sentiment Chart</h2><p>{base}/{quote} price history with concise AI sentiment signals. Hover a dot for the full thesis and outcome.</p></div>
        <div className="trade-timeline-controls">
          <label className="trade-timeline-pair-select"><span>Coin Pair</span><SearchablePairSelect value={normalizedPair} onChange={setSelectedPair} tradingPairs={tradingPairs} placeholder="Search trading pairs…" /></label>
          <label className="trade-timeline-range-control" title="Changing this range saves it as your default"><span>Range</span><select value={range} onChange={event => onRangeChange(event.target.value)} aria-label="Sentiment Chart date range">{CHART_RANGES.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select><small>Changes save as your default</small></label>
        </div>
      </header>
      <div className="sentiment-chart-legend">
        {Object.entries(OUTCOME_STYLES).map(([status, style]) => <span key={status}><i style={{ background: style.color }} />{style.label}</span>)}
        <span>Markers show completed fixed-horizon outcomes; preserved legacy grades use next-check evaluation</span>
      </div>
      <div className="trade-timeline-chart-shell">
        <div className="trade-timeline-chart-frame"><div ref={hostRef} className="trade-timeline-chart" /></div>
        <div className="sentiment-marker-badge-layer" aria-hidden="true">
          {markerBadges.map(marker => <span key={marker.id} className="sentiment-marker-badge" style={{ left: marker.left, top: marker.top, background: marker.color }}>{marker.code}</span>)}
        </div>
        {hoveredSignals && <div className="sentiment-marker-tooltip" style={{ left: hoveredSignals.left, top: hoveredSignals.top }} role="tooltip">
          <strong>{base}/{quote} AI Sentiment</strong>
          <div className="sentiment-marker-tooltip-list">{hoveredSignals.signals.map(signal => <article key={signal.id}>
            <header><span>{signal.style.code} · {signal.sentiment}</span><b>{formatDelta(signal.price_delta_pct ?? signal.outcome_pct).trim()}</b></header>
            <div className="sentiment-tooltip-outcome">Outcome: <i style={{ background: signal.outcomeStyle.color }} /><b>{signal.outcomeStyle.label}</b></div>
            <time>Original sentiment: {formatEasternTime(new Date(signal.originalSignalTime * 1000).toISOString())}</time>
            <p>{signal.sentiment_reason || 'No thesis explanation was recorded.'}</p>
            <div className="sentiment-comparison">
              <small>Signal price: {formatPrice(signal.price_at_prediction)} {quote}</small>
              <small>{signal.evaluation_method === 'fixed_horizon' ? 'Horizon evaluation' : 'Legacy next check'}: {signal.evaluation_price ? `${formatPrice(signal.evaluation_price)} ${quote} · ${formatEasternTime(signal.evaluated_at)}` : 'Tracking'}</small>
              {Number.isFinite(Number(signal.evaluation_hours)) && <small>Evaluation interval: {Number(signal.evaluation_hours).toFixed(2)} hours</small>}
              <small>Method: {signal.evaluation_method === 'fixed_horizon' ? `Fixed ${Number(signal.forecast_horizon_hours).toFixed(0)}h forecast horizon` : 'Legacy next-check evaluation'}</small>
              {signal.style.code === 'H' && signal.steady_threshold_pct != null && <small>
                Hold rules: Correct within ±{Number(signal.steady_threshold_pct).toFixed(2)}%; Wrong at ±{Number(signal.upside_wrong_threshold_pct).toFixed(2)}% or farther; moves strictly between those boundaries are Neutral
              </small>}
              {signal.correct_threshold_pct != null && signal.wrong_threshold_pct != null && <small>
                {signal.threshold_setting || signal.sentiment} rules: Correct {signal.style.code === 'CS' || signal.style.code === 'SI' ? 'at or below -' : 'at or above +'}{Number(signal.correct_threshold_pct).toFixed(2)}%; Wrong {signal.style.code === 'CS' || signal.style.code === 'SI' ? 'at or above +' : 'at or below -'}{Number(signal.wrong_threshold_pct).toFixed(2)}%
              </small>}
              <small>Result: {(signal.outcome_status || 'tracking').replace(/^./, character => character.toUpperCase())}{formatDelta(signal.price_delta_pct ?? signal.outcome_pct)}</small>
            </div>
            <small className="sentiment-outcome-reason">{signal.outcome_reason || 'Waiting for the fixed forecast horizon.'}</small>
          </article>)}</div>
        </div>}
        {loading && <div className="trade-timeline-status">Loading {base}/{quote} sentiment history…</div>}
        {error && <div className="trade-timeline-status error">{error}</div>}
        {!loading && !error && !chartData.markers.length && <div className="trade-timeline-empty">No completed portfolio sentiment grades were recorded for {base} in this range.</div>}
      </div>
    </section>
  );
}
