import React, { useEffect, useMemo, useRef, useState } from 'react';
import SearchablePairSelect from './SearchablePairSelect';
import './TradingViewAdvancedChart.css';

const SCRIPT = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
const EXCHANGE = 'BINANCEUS';
const normalize = value => String(value || 'BTCUSDT').toUpperCase().replace(/[^A-Z0-9]/g, '');
const assets = symbol => symbol.endsWith('USDT')
  ? { base: symbol.slice(0, -4), quote: 'USDT' }
  : { base: symbol.endsWith('USD') ? symbol.slice(0, -3) : symbol, quote: symbol.endsWith('USD') ? 'USD' : 'USDT' };

export default function TradingViewAdvancedChart({
  symbol = 'BTCUSDT', onSymbolChange, tradingPairs = [], watchlistPairs = [],
  filterCoin = null, onResetFilter = null, totalPairsCount = 0, isLightMode = false,
}) {
  const hostRef = useRef(null);
  const [status, setStatus] = useState('loading');
  const pair = normalize(symbol);
  const { base, quote } = assets(pair);
  const tvSymbol = `${EXCHANGE}:${pair}`;
  const pageUrl = `https://www.tradingview.com/symbols/${pair}/?exchange=${EXCHANGE}`;
  const watchlist = useMemo(() => Array.from(new Set([pair, ...watchlistPairs.map(item => normalize(typeof item === 'string' ? item : item?.id || item?.symbol))]))
    .filter(Boolean).slice(0, 50).map(item => `${EXCHANGE}:${item}`), [pair, watchlistPairs]);
  const watchlistKey = watchlist.join('|');

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;
    let active = true;
    setStatus('loading');
    host.replaceChildren();
    const mount = document.createElement('div');
    mount.className = 'tradingview-widget-container__widget';
    const attribution = document.createElement('div');
    attribution.className = 'tradingview-widget-copyright';
    attribution.innerHTML = `<a href="${pageUrl}" rel="noopener nofollow" target="_blank"><span class="blue-text">${base}/${quote} chart</span></a><span class="trademark"> by TradingView</span>`;
    const script = document.createElement('script');
    script.src = SCRIPT;
    script.type = 'text/javascript';
    script.async = true;
    script.text = JSON.stringify({
      autosize: true, symbol: tvSymbol, interval: 'D', timezone: 'exchange',
      theme: isLightMode ? 'light' : 'dark', style: '1', locale: 'en',
      backgroundColor: isLightMode ? '#ffffff' : '#0b1220',
      gridColor: isLightMode ? 'rgba(46,46,46,.08)' : 'rgba(148,163,184,.12)',
      allow_symbol_change: true, hide_top_toolbar: false, hide_side_toolbar: false,
      hide_legend: false, hide_volume: false, withdateranges: true, save_image: true,
      show_popup_button: true, popup_width: '1400', popup_height: '900', details: true,
      hotlist: true, calendar: true, watchlist, compareSymbols: [], studies: [],
      support_host: 'https://www.tradingview.com',
    });
    script.onload = () => active && setStatus('ready');
    script.onerror = () => active && setStatus('error');
    host.append(mount, attribution, script);
    const timeout = window.setTimeout(() => active && setStatus(current => current === 'ready' ? current : 'error'), 20000);
    return () => { active = false; window.clearTimeout(timeout); host.replaceChildren(); };
  }, [base, isLightMode, pageUrl, quote, tvSymbol, watchlistKey]);

  return (
    <section className="advanced-trading-chart" aria-label={`${base}/${quote} advanced chart`}>
      <header className="advanced-chart-header">
        <div className="advanced-chart-pair-control">
          <span className="advanced-chart-control-label">Trading pair for chart and orders</span>
          {onSymbolChange && tradingPairs.length ? <SearchablePairSelect value={pair} onChange={onSymbolChange} tradingPairs={tradingPairs} placeholder="Search Binance.US pairs…" /> : <strong>{base} / {quote}</strong>}
        </div>
        {filterCoin && onResetFilter && <button type="button" className="advanced-chart-reset-filter" onClick={onResetFilter}>Show All Pairs {totalPairsCount ? `(${totalPairsCount})` : ''}</button>}
      </header>
      <div className="advanced-chart-capabilities"><span>80+ indicators</span><span>100+ drawings</span><span>Native symbol search</span><span>Compare symbols</span><span>Date ranges</span><span>Details, hotlists &amp; calendar</span><span>Image &amp; popup tools</span></div>
      <div className="advanced-chart-widget-shell">
        <div ref={hostRef} className="tradingview-widget-container advanced-chart-widget-host" />
        {status === 'loading' && <div className="advanced-chart-widget-status">Loading TradingView Advanced Chart…</div>}
        {status === 'error' && <div className="advanced-chart-widget-status error"><span>TradingView could not load. Check the network connection or browser content-blocking settings.</span><a href={pageUrl} target="_blank" rel="noopener noreferrer">Open this chart on TradingView</a></div>}
      </div>
      <p className="advanced-chart-sync-note">The selector above keeps the order ticket and Binance.US chart synchronized. TradingView's built-in symbol search remains available for independent market research.</p>
    </section>
  );
}
