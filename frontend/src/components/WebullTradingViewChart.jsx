import React, { useEffect, useMemo, useRef, useState } from 'react';
import './TradingViewAdvancedChart.css';

const SCRIPT = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';

const DEFAULT_STOCKS = [
  { symbol: 'AAPL', name: 'Apple Inc.', type: 'EQUITY' },
  { symbol: 'NVDA', name: 'NVIDIA Corporation', type: 'EQUITY' },
  { symbol: 'TSLA', name: 'Tesla Inc.', type: 'EQUITY' },
  { symbol: 'MSFT', name: 'Microsoft Corporation', type: 'EQUITY' },
  { symbol: 'AMZN', name: 'Amazon.com Inc.', type: 'EQUITY' },
  { symbol: 'GOOGL', name: 'Alphabet Inc.', type: 'EQUITY' },
  { symbol: 'META', name: 'Meta Platforms Inc.', type: 'EQUITY' },
  { symbol: 'SPY', name: 'SPDR S&P 500 ETF Trust', type: 'ETF' },
  { symbol: 'QQQ', name: 'Invesco QQQ Trust', type: 'ETF' },
  { symbol: 'AMD', name: 'Advanced Micro Devices', type: 'EQUITY' },
];

const DEFAULT_CRYPTO_PAIRS = [
  { symbol: 'BTCUSD', name: 'Bitcoin / USD', base: 'BTC', quote: 'USD' },
  { symbol: 'ETHUSD', name: 'Ethereum / USD', base: 'ETH', quote: 'USD' },
  { symbol: 'SOLUSD', name: 'Solana / USD', base: 'SOL', quote: 'USD' },
  { symbol: 'DOGEUSD', name: 'Dogecoin / USD', base: 'DOGE', quote: 'USD' },
  { symbol: 'LTCUSD', name: 'Litecoin / USD', base: 'LTC', quote: 'USD' },
  { symbol: 'SHIBUSD', name: 'Shiba Inu / USD', base: 'SHIB', quote: 'USD' },
  { symbol: 'AVAXUSD', name: 'Avalanche / USD', base: 'AVAX', quote: 'USD' },
  { symbol: 'BCHUSD', name: 'Bitcoin Cash / USD', base: 'BCH', quote: 'USD' },
  { symbol: 'LINKUSD', name: 'Chainlink / USD', base: 'LINK', quote: 'USD' },
  { symbol: 'UNIUSD', name: 'Uniswap / USD', base: 'UNI', quote: 'USD' },
];

export default function WebullTradingViewChart({
  symbol = 'AAPL',
  instrumentType = 'EQUITY',
  onInstrumentChange,
  holdings = [],
  isLightMode = false,
}) {
  const hostRef = useRef(null);
  const [status, setStatus] = useState('loading');
  const [assetCategory, setAssetCategory] = useState(
    instrumentType === 'CRYPTO' ? 'CRYPTO' : 'TRADITIONAL'
  );
  const [customSearch, setCustomSearch] = useState('');

  // Keep asset category synced if symbol/instrumentType prop changes
  useEffect(() => {
    setAssetCategory(instrumentType === 'CRYPTO' ? 'CRYPTO' : 'TRADITIONAL');
  }, [instrumentType]);

  // Combine user's imported holdings with default lists
  const availableTraditional = useMemo(() => {
    const fromHoldings = holdings
      .filter((h) => !/crypto|coin|token/i.test(h.instrument_type || '') && h.symbol)
      .map((h) => ({
        symbol: h.symbol.toUpperCase(),
        name: h.name || h.symbol,
        type: h.instrument_type || 'EQUITY',
      }));
    const map = new Map();
    [...fromHoldings, ...DEFAULT_STOCKS].forEach((item) => {
      if (!map.has(item.symbol)) map.set(item.symbol, item);
    });
    return Array.from(map.values());
  }, [holdings]);

  const availableCrypto = useMemo(() => {
    const fromHoldings = holdings
      .filter((h) => /crypto|coin|token/i.test(h.instrument_type || '') && h.symbol)
      .map((h) => {
        const clean = h.symbol.toUpperCase();
        const pair = clean.endsWith('USD') ? clean : `${clean}USD`;
        return {
          symbol: pair,
          name: `${clean.replace(/USD$/, '')} / USD`,
          base: clean.replace(/USD$/, ''),
          quote: 'USD',
        };
      });
    const map = new Map();
    [...fromHoldings, ...DEFAULT_CRYPTO_PAIRS].forEach((item) => {
      if (!map.has(item.symbol)) map.set(item.symbol, item);
    });
    return Array.from(map.values());
  }, [holdings]);

  // Resolve TradingView widget symbol
  const tvSymbol = useMemo(() => {
    const clean = String(symbol || 'AAPL').toUpperCase().trim();
    if (assetCategory === 'CRYPTO') {
      const pair = clean.endsWith('USD') ? clean : `${clean}USD`;
      return `COINBASE:${pair}`;
    }
    return clean;
  }, [symbol, assetCategory]);

  const pageUrl = `https://www.tradingview.com/symbols/${tvSymbol.replace(':', '-')}/`;

  // Mount TradingView Widget
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
    attribution.innerHTML = `<a href="${pageUrl}" rel="noopener nofollow" target="_blank"><span class="blue-text">${symbol} Chart</span></a><span class="trademark"> by TradingView</span>`;

    const script = document.createElement('script');
    script.src = SCRIPT;
    script.type = 'text/javascript';
    script.async = true;
    script.text = JSON.stringify({
      autosize: true,
      symbol: tvSymbol,
      interval: 'D',
      timezone: 'exchange',
      theme: isLightMode ? 'light' : 'dark',
      style: '1',
      locale: 'en',
      backgroundColor: isLightMode ? '#ffffff' : '#0b1220',
      gridColor: isLightMode ? 'rgba(46,46,46,.08)' : 'rgba(148,163,184,.12)',
      allow_symbol_change: true,
      hide_top_toolbar: false,
      hide_side_toolbar: false,
      hide_legend: false,
      hide_volume: false,
      withdateranges: true,
      save_image: true,
      show_popup_button: true,
      popup_width: '1400',
      popup_height: '900',
      details: true,
      hotlist: true,
      calendar: true,
      support_host: 'https://www.tradingview.com',
    });

    script.onload = () => active && setStatus('ready');
    script.onerror = () => active && setStatus('error');
    host.append(mount, attribution, script);

    const timeout = window.setTimeout(() => active && setStatus((curr) => (curr === 'ready' ? curr : 'error')), 20000);
    return () => {
      active = false;
      window.clearTimeout(timeout);
      host.replaceChildren();
    };
  }, [tvSymbol, isLightMode, pageUrl, symbol]);

  const handleCategorySwitch = (category) => {
    setAssetCategory(category);
    if (category === 'CRYPTO') {
      const first = availableCrypto[0]?.symbol || 'BTCUSD';
      onInstrumentChange?.({ symbol: first, instrumentType: 'CRYPTO' });
    } else {
      const first = availableTraditional[0]?.symbol || 'AAPL';
      onInstrumentChange?.({ symbol: first, instrumentType: 'EQUITY' });
    }
  };

  const handleSelectInstrument = (e) => {
    const val = e.target.value;
    if (assetCategory === 'CRYPTO') {
      onInstrumentChange?.({ symbol: val, instrumentType: 'CRYPTO' });
    } else {
      onInstrumentChange?.({ symbol: val, instrumentType: 'EQUITY' });
    }
  };

  const handleCustomSearchSubmit = (e) => {
    e.preventDefault();
    const query = customSearch.trim().toUpperCase();
    if (!query) return;
    if (assetCategory === 'CRYPTO') {
      const pair = query.endsWith('USD') ? query : `${query}USD`;
      onInstrumentChange?.({ symbol: pair, instrumentType: 'CRYPTO' });
    } else {
      onInstrumentChange?.({ symbol: query, instrumentType: 'EQUITY' });
    }
    setCustomSearch('');
  };

  return (
    <section className="advanced-trading-chart" aria-label={`${symbol} Webull advanced chart`}>
      <header className="advanced-chart-header" style={{ flexWrap: 'wrap', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
          {/* Asset Category Selector */}
          <div className="advanced-chart-pair-control" style={{ width: 'auto' }}>
            <span className="advanced-chart-control-label">Asset Category</span>
            <div style={{ display: 'flex', width: '380px', maxWidth: '100%', borderRadius: '8px', overflow: 'hidden', border: '1px solid rgba(129, 140, 248, 0.4)' }}>
              <button
                type="button"
                onClick={() => handleCategorySwitch('TRADITIONAL')}
                style={{
                  flex: 1,
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: '8px 12px',
                  background: assetCategory === 'TRADITIONAL' ? '#3b82f6' : 'rgba(15, 23, 42, 0.8)',
                  color: '#fff',
                  border: 'none',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  textAlign: 'center',
                  transition: 'background 0.2s ease',
                }}
              >
                🏛️ Traditional (Stocks &amp; ETFs)
              </button>
              <button
                type="button"
                onClick={() => handleCategorySwitch('CRYPTO')}
                style={{
                  flex: 1,
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: '8px 12px',
                  background: assetCategory === 'CRYPTO' ? '#f59e0b' : 'rgba(15, 23, 42, 0.8)',
                  color: '#fff',
                  border: 'none',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  textAlign: 'center',
                  transition: 'background 0.2s ease',
                }}
              >
                🪙 Cryptocurrency
              </button>
            </div>
          </div>

          {/* Instrument / Pair Dropdown */}
          <div className="advanced-chart-pair-control" style={{ width: 'min(100%, 320px)' }}>
            <span className="advanced-chart-control-label">
              {assetCategory === 'CRYPTO' ? 'Trading Pair for Chart & Orders' : 'Stock / ETF for Chart & Orders'}
            </span>
            <select
              value={symbol}
              onChange={handleSelectInstrument}
              style={{
                width: '100%',
                padding: '9px 12px',
                borderRadius: '8px',
                background: 'var(--input-bg, #0f172a)',
                color: '#fff',
                border: '1px solid rgba(255, 255, 255, 0.2)',
                fontSize: '14px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {assetCategory === 'CRYPTO'
                ? availableCrypto.map((pair) => (
                    <option key={pair.symbol} value={pair.symbol}>
                      {pair.symbol} ({pair.name})
                    </option>
                  ))
                : availableTraditional.map((stk) => (
                    <option key={stk.symbol} value={stk.symbol}>
                      {stk.symbol} - {stk.name}
                    </option>
                  ))}
            </select>
          </div>
        </div>

        {/* Quick Ticker Search Input */}
        <form onSubmit={handleCustomSearchSubmit} style={{ display: 'flex', alignItems: 'flex-end', gap: '8px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <span className="advanced-chart-control-label">Enter Custom Ticker</span>
            <input
              type="text"
              placeholder={assetCategory === 'CRYPTO' ? 'e.g. SOL, DOGE' : 'e.g. AMD, PLTR, DIS'}
              value={customSearch}
              onChange={(e) => setCustomSearch(e.target.value.toUpperCase())}
              style={{
                padding: '8px 12px',
                borderRadius: '8px',
                background: 'var(--input-bg, #0f172a)',
                color: '#fff',
                border: '1px solid rgba(255, 255, 255, 0.2)',
                fontSize: '13px',
                textTransform: 'uppercase',
                width: '160px',
              }}
            />
          </div>
          <button
            type="submit"
            className="btn btn-secondary"
            style={{ padding: '8px 14px', fontSize: '13px', borderRadius: '8px' }}
          >
            Load
          </button>
        </form>
      </header>

      <div className="advanced-chart-capabilities">
        <span>80+ indicators</span>
        <span>100+ drawings</span>
        <span>Native symbol search</span>
        <span>Compare symbols</span>
        <span>Date ranges</span>
        <span>Details, hotlists &amp; calendar</span>
        <span>Image &amp; popup tools</span>
      </div>

      <div className="advanced-chart-widget-shell">
        <div ref={hostRef} className="tradingview-widget-container advanced-chart-widget-host" />
        {status === 'loading' && <div className="advanced-chart-widget-status">Loading TradingView Advanced Chart…</div>}
        {status === 'error' && (
          <div className="advanced-chart-widget-status error">
            <span>TradingView could not load. Check network connection or content blocker.</span>
            <a href={pageUrl} target="_blank" rel="noopener noreferrer">Open on TradingView</a>
          </div>
        )}
      </div>

      <p className="advanced-chart-sync-note">
        The selector above keeps the order ticket and Webull chart synchronized. TradingView&apos;s built-in symbol search remains available for independent market research.
      </p>
    </section>
  );
}
