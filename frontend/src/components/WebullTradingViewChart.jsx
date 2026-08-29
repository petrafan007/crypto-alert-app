import React, { useEffect, useMemo, useRef, useState } from 'react';
import SearchablePairSelect from './SearchablePairSelect';
import './TradingViewAdvancedChart.css';

const SCRIPT = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';

export const DEFAULT_STOCKS = [
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
  accounts = [],
  selectedAccountId,
  onAccountChange,
  defaultAccountId,
  onSetDefaultAccount,
  savingDefaultAccount = false,
  holdings = [],
  isLightMode = false,
}) {
  const hostRef = useRef(null);
  const [status, setStatus] = useState('loading');
  const isCrypto = instrumentType === 'CRYPTO';
  const isOption = instrumentType === 'OPTION';
  const isFutures = instrumentType === 'FUTURES';

  // Combine user's imported holdings with default lists
  const availableTraditional = useMemo(() => {
    const fromHoldings = holdings
      .filter((h) => !/crypto|coin|token/i.test(h.instrument_type || '') && !['OPTION', 'FUTURES'].includes(String(h.instrument_type || '').toUpperCase()) && h.symbol)
      .map((h) => ({
        id: h.symbol.toUpperCase(),
        symbol: h.symbol.toUpperCase(),
        name: h.name || h.symbol,
        display_name: `${h.symbol.toUpperCase()} — ${h.name || 'Holding'}`,
        type: h.instrument_type || 'EQUITY',
        isHolding: true,
      }));
    const map = new Map();
    fromHoldings.forEach((item) => map.set(item.symbol, item));
    DEFAULT_STOCKS.forEach((item) => {
      if (!map.has(item.symbol)) {
        map.set(item.symbol, {
          id: item.symbol,
          symbol: item.symbol,
          name: item.name,
          display_name: `${item.symbol} — ${item.name}`,
          type: item.type,
        });
      }
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
          id: pair,
          symbol: pair,
          name: `${clean.replace(/USD$/, '')} / USD`,
          display_name: `${pair} (${clean.replace(/USD$/, '')} / USD)`,
          base: clean.replace(/USD$/, ''),
          quote: 'USD',
          quote_currency: 'USD',
          isHolding: true,
        };
      });
    const map = new Map();
    fromHoldings.forEach((item) => map.set(item.symbol, item));
    DEFAULT_CRYPTO_PAIRS.forEach((item) => {
      if (!map.has(item.symbol)) {
        map.set(item.symbol, {
          id: item.symbol,
          symbol: item.symbol,
          name: item.name,
          display_name: `${item.symbol} (${item.name})`,
          base: item.base,
          quote: item.quote,
          quote_currency: item.quote,
        });
      }
    });
    return Array.from(map.values());
  }, [holdings]);

  // Resolve TradingView widget symbol
  const tvSymbol = useMemo(() => {
    const clean = String(symbol || '').toUpperCase().trim();
    if (isFutures && !clean) return '';
    const resolved = clean || 'AAPL';
    if (isCrypto) {
      const pair = resolved.endsWith('USD') ? resolved : `${resolved}USD`;
      return `COINBASE:${pair}`;
    }
    return resolved;
  }, [symbol, isCrypto, isFutures]);

  const pageUrl = tvSymbol
    ? `https://www.tradingview.com/symbols/${tvSymbol.replace(':', '-')}/`
    : 'https://www.tradingview.com/markets/futures/';

  // Mount TradingView Widget
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;
    let active = true;
    setStatus('loading');
    host.replaceChildren();
    if (!tvSymbol) {
      setStatus('ready');
      return () => { active = false; host.replaceChildren(); };
    }

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

  return (
    <section className="advanced-trading-chart" aria-label={`${symbol} Webull advanced chart`}>
      <header className="advanced-chart-header" style={{ flexWrap: 'wrap', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap', width: '100%' }}>
          {/* Webull Account Selector */}
          {accounts.length > 0 && (
            <div className="advanced-chart-pair-control" style={{ width: 'min(100%, 300px)' }}>
              <span className="advanced-chart-control-label">Webull Account</span>
              <select
                value={selectedAccountId}
                onChange={(e) => onAccountChange?.(e.target.value)}
                aria-label="Select Webull Account"
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '8px',
                  background: isLightMode ? '#ffffff' : '#0f172a',
                  color: isLightMode ? '#0f172a' : '#f8fafc',
                  border: isLightMode ? '1px solid #cbd5e1' : '1px solid rgba(129, 140, 248, 0.4)',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                {accounts.map((acc) => {
                  const label = acc.account_label || acc.account_name || acc.account_type || 'Account';
                  const numDisplay = acc.account_id_masked || (acc.account_id ? `••••${String(acc.account_id).slice(-4)}` : '');
                  return (
                    <option
                      key={acc.account_id}
                      value={acc.account_id}
                      style={{
                        background: isLightMode ? '#ffffff' : '#0f172a',
                        color: isLightMode ? '#0f172a' : '#f8fafc',
                      }}
                    >
                      {label} ({numDisplay})
                    </option>
                  );
                })}
              </select>
              <button
                type="button"
                onClick={() => onSetDefaultAccount?.()}
                disabled={!selectedAccountId || savingDefaultAccount || selectedAccountId === defaultAccountId}
                style={{
                  marginTop: '7px', padding: 0, border: 'none', background: 'transparent',
                  color: selectedAccountId === defaultAccountId ? (isLightMode ? '#475569' : '#94a3b8') : '#38bdf8',
                  fontSize: '12px', fontWeight: 600,
                  cursor: selectedAccountId === defaultAccountId || savingDefaultAccount ? 'default' : 'pointer',
                }}
              >
                {savingDefaultAccount ? 'Saving default…' : selectedAccountId === defaultAccountId ? 'Default trading account' : 'Make selected account my default'}
              </button>
            </div>
          )}

          {/* Unified Searchable Instrument / Pair Selector */}
          <div className="advanced-chart-pair-control" style={{ width: 'min(100%, 340px)' }}>
            <span className="advanced-chart-control-label">
              {isCrypto ? 'Cryptocurrency Pair for Chart & Orders' : isOption ? 'Option Underlying Chart' : isFutures ? 'Webull Futures Contract' : 'Stock / ETF for Chart & Orders'}
            </span>
            {isOption || isFutures ? (
              <div className="order-styled-input" aria-label={isFutures ? 'Selected Webull futures contract' : 'Selected option underlying'} style={{ padding: '10px 12px', color: isLightMode ? '#0f172a' : '#e2e8f0' }}>
                {symbol || 'Choose a contract below'} · {isFutures ? 'selected futures contract' : 'selected option contract'}
              </div>
            ) : (
              <SearchablePairSelect
                value={symbol}
                onChange={(nextSym) => {
                  onInstrumentChange?.({
                    symbol: nextSym,
                    instrumentType: isCrypto ? 'CRYPTO' : 'EQUITY',
                  });
                }}
                tradingPairs={isCrypto ? availableCrypto : availableTraditional}
                mode={isCrypto ? 'crypto' : 'traditional'}
                placeholder={isCrypto ? 'Search crypto pairs (e.g. BTC, ETH, SOL)...' : 'Search stocks & ETFs (e.g. AAPL, NVDA, SPY)...'}
              />
            )}
          </div>
        </div>
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
        {!tvSymbol && <div className="advanced-chart-widget-status">Select an exact Webull futures contract below to load its chart.</div>}
        {tvSymbol && status === 'loading' && <div className="advanced-chart-widget-status">Loading TradingView Advanced Chart…</div>}
        {status === 'error' && (
          <div className="advanced-chart-widget-status error">
            <span>TradingView could not load. Check network connection or content blocker.</span>
            <a href={pageUrl} target="_blank" rel="noopener noreferrer">Open on TradingView</a>
          </div>
        )}
      </div>

      <p className="advanced-chart-sync-note">
        {isOption
          ? 'The chart shows the option underlying. The imported holding and its strike, expiration, and call/put terms remain locked into the option ticket below.'
          : isFutures
            ? 'Choose a Webull futures contract in the ticket below. The selected contract stays locked into the order ticket while TradingView remains available for market research.'
          : 'The selector above keeps the order ticket and Webull chart synchronized. TradingView\'s built-in symbol search remains available for independent market research.'}
      </p>
    </section>
  );
}
