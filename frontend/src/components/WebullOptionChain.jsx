import React, { useState, useEffect, useMemo, useRef } from 'react';
import axios from 'axios';
import SearchablePairSelect from './SearchablePairSelect';
import {
  OPTION_STRATEGIES,
  buildOptionStrategyLegs,
  optionStrategyDefinition,
} from '../utils/optionStrategies';
import './WebullOptionChain.css';

const PAYOFF_POINTS = {
  single: '4,48 30,38 56,28 82,18 108,8',
  covered: '4,52 36,40 68,28 108,28',
  valley: '4,8 56,52 108,8',
  ramp: '4,52 42,52 76,12 108,12',
  peak: '4,52 28,52 56,8 84,52 108,52',
  plateau: '4,52 30,12 78,12 108,52',
  collar: '4,46 30,46 78,16 108,16',
  curve: '4,48 30,40 56,18 82,30 108,12',
  ratio: '4,50 36,36 68,18 108,48',
};

function StrategyTooltip({ strategy }) {
  return (
    <div className="strategy-hover-card" role="tooltip">
      <svg viewBox="0 0 112 60" aria-label={`${strategy.label} payoff illustration`}>
        <line x1="4" y1="30" x2="108" y2="30" className="strategy-zero-line" />
        <polyline points={PAYOFF_POINTS[strategy.payoff] || PAYOFF_POINTS.single} className="strategy-payoff-line" />
      </svg>
      <div>
        <strong>{strategy.label}</strong>
        <p>{strategy.description}</p>
        {strategy.usesWidth && <small>Width is the number of listed strike intervals between strategy legs.</small>}
      </div>
    </div>
  );
}

export default function WebullOptionChain({
  defaultSymbol = 'AAPL',
  availableTraditional = [],
  availableStocks = [],
  selectedContract = null,
  onSelectOptionContract,
  onSymbolChange,
  isLightMode = false,
}) {
  const [symbol, setSymbol] = useState(defaultSymbol || 'AAPL');
  const [chainData, setChainData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedExp, setSelectedExp] = useState('');
  const [viewMode, setViewMode] = useState('both'); // 'both', 'calls', 'puts'
  const [strategy, setStrategy] = useState('SINGLE');
  const [strategyWidth, setStrategyWidth] = useState('auto');
  const [strategyError, setStrategyError] = useState('');
  const [strikeRange, setStrikeRange] = useState('20'); // '10', '20', 'all'
  const isMounted = useRef(true);
  const requestSequence = useRef(0);
  const activeRequest = useRef(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null);
  const [isStale, setIsStale] = useState(false);
  const [bodyIsLight, setBodyIsLight] = useState(() =>
    typeof document !== 'undefined' ? document.body.classList.contains('light-mode') : isLightMode
  );

  useEffect(() => {
    if (typeof MutationObserver === 'undefined' || typeof document === 'undefined') return;
    const observer = new MutationObserver(() => {
      setBodyIsLight(document.body.classList.contains('light-mode'));
    });
    observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  const activeLightMode = Boolean(isLightMode || bodyIsLight);

  useEffect(() => {
    isMounted.current = true;
    return () => {
      isMounted.current = false;
      activeRequest.current?.abort();
    };
  }, []);

  // Trading pairs list for traditional mode (SearchablePairSelect)
  const tradingPairs = useMemo(() => {
    if (availableTraditional && availableTraditional.length > 0) {
      return availableTraditional;
    }
    const list = availableStocks && availableStocks.length > 0 ? availableStocks : ['AAPL', 'NVDA', 'SPY', 'TSLA', 'MSFT', 'AMZN', 'GOOGL', 'META', 'QQQ', 'AMD'];
    return list.map((sym) => ({
      id: sym.toUpperCase(),
      symbol: sym.toUpperCase(),
      name: sym.toUpperCase(),
      display_name: sym.toUpperCase(),
      type: 'EQUITY',
    }));
  }, [availableTraditional, availableStocks]);

  // Synchronize when defaultSymbol prop changes from parent
  useEffect(() => {
    if (defaultSymbol && defaultSymbol !== symbol) {
      setSymbol(defaultSymbol);
    }
  }, [defaultSymbol]);

  const fetchOptionChain = async (targetSymbol, targetExpiration = '') => {
    const sym = (targetSymbol || symbol || 'AAPL').toUpperCase().trim();
    if (!sym) return;
    const requestId = ++requestSequence.current;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setLoading(true);
    setError('');
    setStrategyError('');
    setIsStale(false);
    // Never leave the previous symbol/expiration interactive while a new chain
    // is loading. A successful response must match the request before it is
    // allowed to replace the empty state.
    setChainData(null);
    try {
      const res = await axios.get('/api/webull/options/chain', {
        params: {
          symbol: sym,
          expiration: targetExpiration || undefined,
        },
        withCredentials: true,
        signal: controller.signal,
      });
      if (!isMounted.current || requestId !== requestSequence.current) return;
      if (res.data && res.data.success) {
        const responseSymbol = String(res.data.underlying_symbol || '').toUpperCase();
        const responseExpiration = String(res.data.selected_expiration || '');
        if (responseSymbol !== sym || (targetExpiration && responseExpiration !== targetExpiration)) {
          throw new Error('The option-chain response did not match the requested symbol and expiration. Refresh before selecting a contract.');
        }
        setChainData(res.data);
        setSelectedExp(res.data.selected_expiration || '');
        setLastUpdatedAt(new Date());
      } else {
        setError(res.data?.message || 'Unable to load option chain.');
      }
    } catch (err) {
      if (!isMounted.current || requestId !== requestSequence.current || axios.isCancel(err)) return;
      const msg = err.response?.data?.message || err.message || 'Failed to fetch options chain.';
      setError(msg);
    } finally {
      if (isMounted.current && requestId === requestSequence.current) setLoading(false);
    }
  };

  useEffect(() => {
    fetchOptionChain(symbol, '');
  }, [symbol]);

  const handleSelectExpiration = (expDate) => {
    setSelectedExp(expDate);
    setChainData(null);
    fetchOptionChain(symbol, expDate);
  };

  const handleSelectSymbol = (newSym) => {
    const clean = (newSym || '').toUpperCase().trim();
    if (!clean) return;
    setSymbol(clean);
    onSymbolChange?.(clean);
  };

  const underlyingPrice = chainData?.underlying_price || 0.0;
  const changePct = chainData?.underlying_change_pct || 0.0;
  const isPositive = changePct >= 0;
  const marketStatus = chainData?.market_status || 'CLOSED';
  const activeStrategy = optionStrategyDefinition(strategy);

  useEffect(() => {
    const staleAfterMs = marketStatus === 'OPEN' ? 30000 : 120000;
    const timer = window.setInterval(() => {
      setIsStale(Boolean(lastUpdatedAt && Date.now() - lastUpdatedAt.getTime() > staleAfterMs));
    }, 5000);
    return () => window.clearInterval(timer);
  }, [lastUpdatedAt, marketStatus]);

  useEffect(() => {
    if (!chainData || !selectedExp) return undefined;
    const refreshMs = marketStatus === 'OPEN' ? 15000 : 60000;
    const refresh = () => {
      if (document.visibilityState === 'visible') fetchOptionChain(symbol, selectedExp);
    };
    const interval = window.setInterval(refresh, refreshMs);
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [chainData?.underlying_symbol, selectedExp, marketStatus, symbol]);

  // Filter strikes based on strikeRange around underlying price
  const filteredChain = useMemo(() => {
    const rawRows = chainData?.chain || [];
    if (!rawRows.length || strikeRange === 'all' || underlyingPrice <= 0) {
      return rawRows;
    }

    const n = Number(strikeRange) || 20;
    // Find index of strike closest to underlying price
    let closestIdx = 0;
    let minDiff = Infinity;
    rawRows.forEach((r, idx) => {
      const diff = Math.abs(r.strike - underlyingPrice);
      if (diff < minDiff) {
        minDiff = diff;
        closestIdx = idx;
      }
    });

    const startIdx = Math.max(0, closestIdx - n);
    const endIdx = Math.min(rawRows.length, closestIdx + n + 1);
    return rawRows.slice(startIdx, endIdx);
  }, [chainData?.chain, strikeRange, underlyingPrice]);

  const handleContractClick = (row, optionType, priceField) => {
    if (loading || isStale || !chainData || chainData.underlying_symbol !== symbol || chainData.selected_expiration !== selectedExp) {
      setStrategyError('This option chain is refreshing or stale. Wait for the current symbol and expiration to finish loading.');
      return;
    }
    const contract = optionType === 'CALL' ? row.call : row.put;
    if (!contract || !onSelectOptionContract) return;

    let targetPrice = contract.ask;
    let side = 'BUY';

    if (priceField === 'bid' && contract.bid > 0) {
      targetPrice = contract.bid;
      side = 'SELL';
    } else if (priceField === 'ask' && contract.ask > 0) {
      targetPrice = contract.ask;
      side = 'BUY';
    } else if (contract.mid > 0) {
      targetPrice = contract.mid;
    } else {
      targetPrice = contract.last || contract.ask || contract.bid || 0;
    }

    // A missing quote must never become an invented $1.00 premium. The order
    // ticket stays locked until the user selects a contract with a real price.
    if (!(targetPrice > 0)) return;

    let strategyLegs;
    try {
      strategyLegs = buildOptionStrategyLegs({
        strategy,
        chainRows: chainData.chain,
        anchorStrike: row.strike,
        optionType,
        side,
        width: strategyWidth === 'auto' ? 1 : strategyWidth,
        expiration: selectedExp,
        expirations: chainData.expirations,
      });
      setStrategyError('');
    } catch (buildError) {
      setStrategyError(buildError.message);
      return;
    }

    onSelectOptionContract({
      symbol: chainData?.underlying_symbol || symbol,
      optionType,
      strike: row.strike,
      expiration: selectedExp,
      price: targetPrice.toFixed(2),
      side,
      contractSymbol: contract.contract_symbol,
      openInterest: contract.open_interest,
      volume: contract.volume,
      impliedVolatility: contract.implied_volatility,
      optionStrategy: strategy,
      strategyWidth,
      strategyLegs,
    });
  };

  return (
    <div className={`webull-option-chain-container ${activeLightMode ? 'light-mode' : ''}`}>
      {/* 1. TOP HEADER: SEARCHABLE STOCK SELECTOR, LIVE QUOTE & REFRESH */}
      <div className="chain-top-bar">
        <div className="underlying-selector-section">
          <div className="chain-live-search-wrapper">
            <span className="chain-control-label">Underlying Stock / ETF:</span>
            <SearchablePairSelect
              value={symbol}
              onChange={handleSelectSymbol}
              tradingPairs={tradingPairs}
              mode="traditional"
              placeholder="Search stock or ETF (e.g. AAPL, NVDA, SPY)..."
              className="chain-searchable-select"
            />
          </div>

          <div className="underlying-info-block">
            <div className="underlying-quote-meta">
              <span className="underlying-price">
                ${underlyingPrice > 0 ? underlyingPrice.toFixed(2) : '—'}
              </span>
              <span className={`underlying-change ${isPositive ? 'positive' : 'negative'}`}>
                {isPositive ? '+' : ''}{changePct.toFixed(2)}%
              </span>
              <span className={`market-session-pill ${marketStatus === 'OPEN' ? 'session-open' : 'session-closed'}`}>
                {marketStatus === 'OPEN' ? '🟢 Market Open' : '🌙 Market Closed (Closing Quotes)'}
              </span>
              <span className={`chain-freshness-pill ${isStale ? 'stale' : ''}`}>
                {isStale ? '⚠️ Stale — refreshing' : lastUpdatedAt ? `Fresh · ${lastUpdatedAt.toLocaleTimeString('en-US', { timeZone: 'America/New_York' })} ET` : 'Loading freshness…'}
              </span>
            </div>
          </div>
        </div>

        <div className="chain-actions-section">
          <button
            type="button"
            onClick={() => fetchOptionChain(symbol, selectedExp)}
            disabled={loading}
            className="btn btn-secondary btn-sm chain-refresh-btn"
            title="Refresh Option Chain"
          >
            {loading ? '⏳ Refreshing...' : '🔄 Refresh'}
          </button>
        </div>
      </div>

      {/* 2. CONTROLS BAR: EXPIRATION DROPDOWN, VIEW MODE TOGGLE & STRIKE FILTER */}
      <div className="chain-filters-bar">
        {/* Expiration Dropdown Selector */}
        <div className="chain-control-group chain-exp-group">
          <label htmlFor="chain-exp-select" className="chain-control-label">
            📅 Expiration Date:
          </label>
          <select
            id="chain-exp-select"
            className="chain-select chain-exp-select"
            value={selectedExp}
            onChange={(e) => handleSelectExpiration(e.target.value)}
            disabled={loading || !chainData?.expirations?.length}
          >
            {(!chainData?.expirations || chainData.expirations.length === 0) ? (
              <option value="">No expirations loaded</option>
            ) : (
              chainData.expirations.map((exp) => (
                <option key={exp.date} value={exp.date}>
                  {exp.formatted || exp.date} {exp.dte !== null ? `(${exp.dte} DTE)` : ''}
                </option>
              ))
            )}
          </select>
        </div>

        {/* View Mode Toggle: All (Calls & Puts) | Calls Only | Puts Only */}
        <div className="chain-control-group">
          <span className="chain-control-label">Display:</span>
          <div className="view-mode-toggle">
            <button
              type="button"
              className={`mode-btn ${viewMode === 'both' ? 'active' : ''}`}
              onClick={() => setViewMode('both')}
            >
              All (Calls &amp; Puts)
            </button>
            <button
              type="button"
              className={`mode-btn calls-btn ${viewMode === 'calls' ? 'active' : ''}`}
              onClick={() => setViewMode('calls')}
            >
              Calls Only
            </button>
            <button
              type="button"
              className={`mode-btn puts-btn ${viewMode === 'puts' ? 'active' : ''}`}
              onClick={() => setViewMode('puts')}
            >
              Puts Only
            </button>
          </div>
        </div>

        {/* Strategy Selector — hover/focus reveals compact visual guidance. */}
        <div className="chain-control-group strategy-control-group">
          <label htmlFor="option-strategy-select" className="chain-control-label">Strategy:</label>
          <div className="strategy-select-with-help" tabIndex="0">
            <select
              id="option-strategy-select"
              value={strategy}
              onChange={(event) => {
                setStrategy(event.target.value);
                setStrategyError('');
              }}
              className="chain-select"
              aria-describedby="option-strategy-hover-help"
            >
              {OPTION_STRATEGIES.map((item) => (
                <option key={item.value} value={item.value} disabled={item.disabled}>
                  {item.label}{item.disabled ? ' — API unavailable' : ''}
                </option>
              ))}
            </select>
            <StrategyTooltip strategy={activeStrategy} />
          </div>
          <span id="option-strategy-hover-help" className="sr-only">Hover or focus the selected strategy to see its payoff illustration and description.</span>
          {activeStrategy.usesWidth && (
            <label className="strategy-width-control">
              <span>Width:</span>
              <select value={strategyWidth} onChange={(event) => setStrategyWidth(event.target.value)} className="chain-select" aria-label="Strategy strike width">
                <option value="auto">Auto</option>
                {Array.from({ length: 10 }, (_, index) => index + 1).map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
          )}
        </div>

        {/* Strikes Range Selector */}
        <div className="chain-control-group strike-filter-control">
          <label htmlFor="strike-range-select" className="chain-control-label">Strikes:</label>
          <select
            id="strike-range-select"
            value={strikeRange}
            onChange={(e) => setStrikeRange(e.target.value)}
            className="chain-select"
          >
            <option value="10">Near the Money (±10 strikes)</option>
            <option value="20">Near the Money (±20 strikes)</option>
            <option value="all">All Available Strikes</option>
          </select>
        </div>
      </div>

      {/* Active Contract Alert / Summary */}
      {selectedContract && selectedContract.symbol === symbol && (
        <div className="selected-contract-banner">
          <span>🎯 Active Selection:</span>
          <strong>
            {selectedContract.symbol} {selectedContract.expiration} ${parseFloat(selectedContract.strike || 0).toFixed(2)} {selectedContract.optionType}
          </strong>
          <span className="badge-side">{selectedContract.side} @ ${selectedContract.price}</span>
          <span className="badge-strategy">{optionStrategyDefinition(selectedContract.optionStrategy || strategy).label}</span>
        </div>
      )}

      {strategyError && <div className="chain-error-box" role="alert">⚠️ {strategyError}</div>}

      {/* 4. STRADDLE OPTIONS MATRIX TABLE */}
      {error ? (
        <div className="chain-error-box">
          ⚠️ {error}
        </div>
      ) : loading && !chainData ? (
        <div className="chain-loading-box">
          <div className="chain-spinner" />
          <p>Loading {symbol} real-time options book...</p>
        </div>
      ) : (
        <div className="chain-table-wrapper">
          <table className="options-matrix-table">
            <thead>
              <tr>
                {/* Calls Headers */}
                {(viewMode === 'both' || viewMode === 'calls') && (
                  <>
                    <th className="call-th text-left">IV</th>
                    <th className="call-th text-right">OI</th>
                    <th className="call-th text-right">Vol</th>
                    <th className="call-th text-right">Last</th>
                    <th className="call-th call-bid-col text-right">Bid</th>
                    <th className="call-th call-ask-col text-right">Ask</th>
                  </>
                )}

                {/* Strike Header */}
                <th className="strike-th text-center">STRIKE</th>

                {/* Puts Headers */}
                {(viewMode === 'both' || viewMode === 'puts') && (
                  <>
                    <th className="put-th put-bid-col text-left">Bid</th>
                    <th className="put-th put-ask-col text-left">Ask</th>
                    <th className="put-th text-left">Last</th>
                    <th className="put-th text-left">Vol</th>
                    <th className="put-th text-left">OI</th>
                    <th className="put-th text-right">IV</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {filteredChain.length === 0 ? (
                <tr>
                  <td colSpan={viewMode === 'both' ? 13 : 7} className="no-data-cell">
                    No options contracts available for {symbol} on {selectedExp}.
                  </td>
                </tr>
              ) : (
                filteredChain.map((row, idx) => {
                  const call = row.call;
                  const put = row.put;
                  const strike = row.strike;

                  // ITM logic: Call is ITM when strike < underlyingPrice; Put is ITM when strike > underlyingPrice
                  const isCallITM = underlyingPrice > 0 && strike < underlyingPrice;
                  const isPutITM = underlyingPrice > 0 && strike > underlyingPrice;

                  // Insert Divider marker right around current underlying price
                  const nextRow = filteredChain[idx + 1];
                  const isPriceBetween =
                    underlyingPrice > 0 &&
                    strike <= underlyingPrice &&
                    nextRow &&
                    nextRow.strike > underlyingPrice;

                  const isCallSelected =
                    selectedContract &&
                    selectedContract.optionType === 'CALL' &&
                    Number(selectedContract.strike) === Number(strike);

                  const isPutSelected =
                    selectedContract &&
                    selectedContract.optionType === 'PUT' &&
                    Number(selectedContract.strike) === Number(strike);

                  return (
                    <React.Fragment key={strike}>
                      <tr className={`matrix-row ${isCallSelected || isPutSelected ? 'row-selected' : ''}`}>
                        {/* Calls Side */}
                        {(viewMode === 'both' || viewMode === 'calls') && (
                          <>
                            <td className={`data-cell text-left ${isCallITM ? 'call-itm' : ''}`}>
                              {call ? `${call.implied_volatility}%` : '—'}
                            </td>
                            <td className={`data-cell text-right ${isCallITM ? 'call-itm' : ''}`}>
                              {call && call.open_interest ? call.open_interest.toLocaleString() : '—'}
                            </td>
                            <td className={`data-cell text-right ${isCallITM ? 'call-itm' : ''}`}>
                              {call && call.volume ? call.volume.toLocaleString() : '—'}
                            </td>
                            <td className={`data-cell text-right ${isCallITM ? 'call-itm' : ''}`}>
                              ${call && call.last ? call.last.toFixed(2) : '—'}
                            </td>
                            <td
                              className={`tradeable-cell call-bid text-right ${isCallITM ? 'call-itm' : ''}`}
                              onClick={() => handleContractClick(row, 'CALL', 'bid')}
                              title={call ? `Select this Call bid to sell an exact owned contract @ $${call.bid.toFixed(2)}` : ''}
                            >
                              ${call && call.bid ? call.bid.toFixed(2) : '0.00'}
                            </td>
                            <td
                              className={`tradeable-cell call-ask text-right ${isCallITM ? 'call-itm' : ''}`}
                              onClick={() => handleContractClick(row, 'CALL', 'ask')}
                              title={call ? `Select this Call ask to buy @ $${call.ask.toFixed(2)}` : ''}
                            >
                              ${call && call.ask ? call.ask.toFixed(2) : '0.00'}
                            </td>
                          </>
                        )}

                        {/* Center Strike */}
                        <td className="strike-cell text-center">
                          <span className="strike-number">${strike.toFixed(2)}</span>
                        </td>

                        {/* Puts Side */}
                        {(viewMode === 'both' || viewMode === 'puts') && (
                          <>
                            <td
                              className={`tradeable-cell put-bid text-left ${isPutITM ? 'put-itm' : ''}`}
                              onClick={() => handleContractClick(row, 'PUT', 'bid')}
                              title={put ? `Select this Put bid to sell an exact owned contract @ $${put.bid.toFixed(2)}` : ''}
                            >
                              ${put && put.bid ? put.bid.toFixed(2) : '0.00'}
                            </td>
                            <td
                              className={`tradeable-cell put-ask text-left ${isPutITM ? 'put-itm' : ''}`}
                              onClick={() => handleContractClick(row, 'PUT', 'ask')}
                              title={put ? `Select this Put ask to buy @ $${put.ask.toFixed(2)}` : ''}
                            >
                              ${put && put.ask ? put.ask.toFixed(2) : '0.00'}
                            </td>
                            <td className={`data-cell text-left ${isPutITM ? 'put-itm' : ''}`}>
                              ${put && put.last ? put.last.toFixed(2) : '—'}
                            </td>
                            <td className={`data-cell text-left ${isPutITM ? 'put-itm' : ''}`}>
                              {put && put.volume ? put.volume.toLocaleString() : '—'}
                            </td>
                            <td className={`data-cell text-left ${isPutITM ? 'put-itm' : ''}`}>
                              {put && put.open_interest ? put.open_interest.toLocaleString() : '—'}
                            </td>
                            <td className={`data-cell text-right ${isPutITM ? 'put-itm' : ''}`}>
                              {put ? `${put.implied_volatility}%` : '—'}
                            </td>
                          </>
                        )}
                      </tr>

                      {/* Stock Price Line Divider */}
                      {isPriceBetween && (
                        <tr className="price-divider-row">
                          <td colSpan={viewMode === 'both' ? 13 : 7} className="price-divider-cell">
                            <div className="price-divider-line">
                              <span>📍 Spot Price: ${underlyingPrice.toFixed(2)}</span>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
