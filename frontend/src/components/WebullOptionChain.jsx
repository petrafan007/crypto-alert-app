import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import axios from 'axios';
import SearchablePairSelect from './SearchablePairSelect';
import OptionFocusControls from './OptionFocusControls';
import {
  OPTION_STRATEGIES,
  buildOptionStrategyLegs,
  optionStrategyDefinition,
} from '../utils/optionStrategies';
import {
  OPTION_COLUMNS,
  buildStrategyMetrics,
  formatOptionMetric,
  loadFocusColumns,
  optionMetricTitle,
  saveFocusColumns,
} from '../utils/optionChainColumns';
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

const DUAL_PANE_STRATEGIES = new Set(['SINGLE', 'COVERED_STOCK', 'VERTICAL', 'BUTTERFLY', 'CONDOR', 'CALENDAR', 'DIAGONAL']);

function mergeOptionRows(previousRows = [], incomingRows = []) {
  const previousByStrike = new Map(previousRows.map((row) => [String(row?.strike), row]));
  return incomingRows.map((incomingRow) => {
    const previousRow = previousByStrike.get(String(incomingRow?.strike));
    if (!previousRow) return incomingRow;
    return {
      ...previousRow,
      ...incomingRow,
      call: incomingRow.call ? { ...(previousRow.call || {}), ...incomingRow.call } : incomingRow.call,
      put: incomingRow.put ? { ...(previousRow.put || {}), ...incomingRow.put } : incomingRow.put,
    };
  });
}

function mergeOptionChainData(previous, incoming) {
  if (!previous
    || previous.underlying_symbol !== incoming.underlying_symbol
    || previous.selected_expiration !== incoming.selected_expiration) {
    return incoming;
  }
  return {
    ...previous,
    ...incoming,
    chain: mergeOptionRows(previous.chain, incoming.chain),
    next_chain: mergeOptionRows(previous.next_chain, incoming.next_chain),
  };
}

function StrategyTooltip({ strategy, placement }) {
  return (
    <div className={`strategy-hover-card strategy-tooltip-${placement}`} role="tooltip">
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
  onStrategyChange,
  isLightMode = false,
}) {
  const [symbol, setSymbol] = useState(defaultSymbol || 'AAPL');
  const [chainData, setChainData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshWarning, setRefreshWarning] = useState('');
  const [error, setError] = useState('');
  const [selectedExp, setSelectedExp] = useState('');
  const [viewMode, setViewMode] = useState('both'); // 'both', 'calls', 'puts'
  const [strategy, setStrategy] = useState('SINGLE');
  const [strategyWidth, setStrategyWidth] = useState('auto');
  const [strategyError, setStrategyError] = useState('');
  const [tooltipPlacement, setTooltipPlacement] = useState('above');
  const strategyControlRef = useRef(null);
  const [activeFocus, setActiveFocus] = useState('price');
  const [focusProfiles, setFocusProfiles] = useState(loadFocusColumns);
  const leftHeaderRef = useRef(null);
  const rightHeaderRef = useRef(null);
  const leftPaneRef = useRef(null);
  const rightPaneRef = useRef(null);
  const [leftScrollRatio, setLeftScrollRatio] = useState(1);
  const mirrorScrollLock = useRef(false);
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

  useEffect(() => {
    const nextStrategy = String(selectedContract?.optionStrategy || '').toUpperCase();
    if (nextStrategy && OPTION_STRATEGIES.some((item) => item.value === nextStrategy && !item.disabled)) setStrategy(nextStrategy);
    if (selectedContract?.optionStrategyWidth) setStrategyWidth(String(selectedContract.optionStrategyWidth));
  }, [selectedContract?.optionStrategy, selectedContract?.optionStrategyWidth]);

  const fetchOptionChain = useCallback(async (targetSymbol, targetExpiration = '', { background = false } = {}) => {
    const sym = (targetSymbol || symbol || 'AAPL').toUpperCase().trim();
    if (!sym) return;
    const requestId = ++requestSequence.current;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    if (background) {
      setIsRefreshing(true);
      setRefreshWarning('');
    } else {
      setLoading(true);
      setError('');
      setStrategyError('');
      setRefreshWarning('');
      setIsStale(false);
    }
    if (!background) {
      // Never leave the previous symbol/expiration interactive while a new chain
      // is loading. A successful response must match the request before it is
      // allowed to replace the empty state.
      setChainData(null);
    }
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
        setChainData((previous) => background ? mergeOptionChainData(previous, res.data) : res.data);
        setSelectedExp(res.data.selected_expiration || '');
        setLastUpdatedAt(new Date());
        setIsStale(false);
        setRefreshWarning('');
      } else {
        const message = res.data?.message || 'Unable to load option chain.';
        if (background) setRefreshWarning(message);
        else setError(message);
      }
    } catch (err) {
      if (!isMounted.current || requestId !== requestSequence.current || axios.isCancel(err)) return;
      const msg = err.response?.data?.message || err.message || 'Failed to fetch options chain.';
      if (background) setRefreshWarning(msg);
      else setError(msg);
    } finally {
      if (isMounted.current && requestId === requestSequence.current) {
        setIsRefreshing(false);
        setLoading(false);
      }
    }
  }, [symbol]);

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
  const usesDualPane = DUAL_PANE_STRATEGIES.has(strategy);
  const visibleSingleSide = viewMode === 'puts' ? 'PUT' : 'CALL';
  const selectedColumns = (focusProfiles[activeFocus] || []).map((id) => OPTION_COLUMNS[id]).filter(Boolean);

  const updateStrategyTooltipPlacement = () => {
    const rect = strategyControlRef.current?.getBoundingClientRect();
    setTooltipPlacement(rect && rect.top < 210 ? 'left' : 'above');
  };

  const handleStrategyChange = (nextStrategy) => {
    setStrategy(nextStrategy);
    setStrategyError('');
    if (!DUAL_PANE_STRATEGIES.has(nextStrategy) && viewMode === 'both') setViewMode('calls');
    onStrategyChange?.({ strategy: nextStrategy, width: strategyWidth });
  };

  const handleStrategyWidthChange = (nextWidth) => {
    setStrategyWidth(nextWidth);
    setStrategyError('');
    onStrategyChange?.({ strategy, width: nextWidth });
  };

  const handleFocusProfileChange = (focusId, columns) => {
    const next = { ...focusProfiles, [focusId]: columns };
    setFocusProfiles(next);
    saveFocusColumns(next);
  };

  useEffect(() => {
    if (!usesDualPane) return undefined;
    const frame = window.requestAnimationFrame(() => {
      if (leftHeaderRef.current) leftHeaderRef.current.scrollLeft = leftHeaderRef.current.scrollWidth - leftHeaderRef.current.clientWidth;
      if (rightHeaderRef.current) rightHeaderRef.current.scrollLeft = 0;
      if (leftPaneRef.current) leftPaneRef.current.scrollLeft = leftPaneRef.current.scrollWidth - leftPaneRef.current.clientWidth;
      if (rightPaneRef.current) rightPaneRef.current.scrollLeft = 0;
      setLeftScrollRatio(1);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [usesDualPane, strategy, activeFocus, selectedColumns.length, chainData?.underlying_symbol]);

  const syncMirroredScroll = (sourceSide, source) => {
    if (mirrorScrollLock.current || !source) return;
    const sourceMax = Math.max(0, source.scrollWidth - source.clientWidth);
    const sourceRatio = sourceMax > 0 ? source.scrollLeft / sourceMax : 0;
    const leftRatio = sourceSide === 'left' ? sourceRatio : 1 - sourceRatio;
    const targets = [
      [leftHeaderRef.current, leftRatio],
      [leftPaneRef.current, leftRatio],
      [rightHeaderRef.current, 1 - leftRatio],
      [rightPaneRef.current, 1 - leftRatio],
    ];
    mirrorScrollLock.current = true;
    setLeftScrollRatio(leftRatio);
    targets.forEach(([target, ratio]) => {
      if (!target || target === source) return;
      const targetMax = Math.max(0, target.scrollWidth - target.clientWidth);
      target.scrollLeft = targetMax * ratio;
    });
    window.requestAnimationFrame(() => { mirrorScrollLock.current = false; });
  };

  const setMirroredRatio = (nextLeftRatio) => {
    const leftRatio = Math.max(0, Math.min(1, nextLeftRatio));
    mirrorScrollLock.current = true;
    setLeftScrollRatio(leftRatio);
    if (leftHeaderRef.current) {
      leftHeaderRef.current.scrollLeft = Math.max(0, leftHeaderRef.current.scrollWidth - leftHeaderRef.current.clientWidth) * leftRatio;
    }
    if (leftPaneRef.current) {
      leftPaneRef.current.scrollLeft = Math.max(0, leftPaneRef.current.scrollWidth - leftPaneRef.current.clientWidth) * leftRatio;
    }
    if (rightHeaderRef.current) {
      rightHeaderRef.current.scrollLeft = Math.max(0, rightHeaderRef.current.scrollWidth - rightHeaderRef.current.clientWidth) * (1 - leftRatio);
    }
    if (rightPaneRef.current) {
      rightPaneRef.current.scrollLeft = Math.max(0, rightPaneRef.current.scrollWidth - rightPaneRef.current.clientWidth) * (1 - leftRatio);
    }
    window.requestAnimationFrame(() => { mirrorScrollLock.current = false; });
  };

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
      if (document.visibilityState === 'visible') fetchOptionChain(symbol, selectedExp, { background: true });
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

    const displayedMetrics = buildStrategyMetrics({
      strategy,
      chainRows: chainData.chain,
      nextRows: chainData.next_chain || [],
      row,
      optionType,
      width: strategyWidth,
      expiration: selectedExp,
      expirations: chainData.expirations,
      underlyingPrice,
    });
    if (!displayedMetrics || displayedMetrics.strategy_error) {
      setStrategyError(displayedMetrics?.strategy_error || 'This strategy cannot be built at the selected strike.');
      return;
    }

    let targetPrice = displayedMetrics.ask;
    let side = 'BUY';

    if (priceField === 'bid' && Number.isFinite(Number(displayedMetrics.bid))) {
      targetPrice = displayedMetrics.bid;
      side = 'SELL';
    } else if (priceField === 'ask' && Number.isFinite(Number(displayedMetrics.ask))) {
      targetPrice = displayedMetrics.ask;
      side = 'BUY';
    } else if (Number.isFinite(Number(displayedMetrics.mid))) {
      targetPrice = displayedMetrics.mid;
    } else {
      targetPrice = displayedMetrics.last || displayedMetrics.ask || displayedMetrics.bid || 0;
    }
    targetPrice = Math.abs(Number(targetPrice));

    // A missing quote must never become an invented $1.00 premium. The order
    // ticket stays locked until the user selects a contract with a real price.
    if (!(targetPrice > 0)) return;

    let strategyLegs;
    try {
      strategyLegs = buildOptionStrategyLegs({
        strategy,
        chainRows: chainData.chain,
        nextChainRows: chainData.next_chain || [],
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

  const strategyMetricsFor = (row, optionType) => buildStrategyMetrics({
    strategy,
    chainRows: chainData?.chain || [],
    nextRows: chainData?.next_chain || [],
    row,
    optionType,
    width: strategyWidth,
    expiration: selectedExp,
    expirations: chainData?.expirations || [],
    underlyingPrice,
  });

  const renderMetricCells = (row, optionType, isITM, columns = selectedColumns) => {
    const metrics = strategyMetricsFor(row, optionType);
    const sideClass = optionType === 'CALL' ? 'call' : 'put';
    return columns.map((column) => {
      const tradeable = ['bid', 'ask'].includes(column.id) && metrics && !metrics.strategy_error;
      const title = optionMetricTitle(column.id, metrics);
      return (
        <td
          key={`${optionType}-${row.strike}-${column.id}`}
          className={`${tradeable ? 'tradeable-cell' : 'data-cell'} ${sideClass}-${column.id} ${isITM ? `${sideClass}-itm` : ''}`}
          onClick={tradeable ? () => handleContractClick(row, optionType, column.id) : undefined}
          title={title || (tradeable ? `Select the ${activeStrategy.label} ${column.label.toLowerCase()} for this anchor strike.` : '')}
        >
          {formatOptionMetric(column.id, metrics?.[column.id])}
        </td>
      );
    });
  };

  const strategyStrikeLabel = (row, optionType) => {
    const metrics = strategyMetricsFor(row, optionType);
    const strikes = (metrics?.strategy_legs || [])
      .filter((leg) => leg.instrument_type === 'OPTION')
      .map((leg) => Number(leg.strike_price))
      .filter(Number.isFinite)
      .filter((value, index, values) => values.indexOf(value) === index)
      .sort((a, b) => a - b);
    return (strikes.length ? strikes : [Number(row.strike)])
      .map((value) => Number.isInteger(value) ? value.toFixed(0) : value.toFixed(2))
      .join('/');
  };

  const isSelectedRow = (strike, optionType) => Boolean(
    selectedContract
    && selectedContract.optionType === optionType
    && Number(selectedContract.strike) === Number(strike),
  );

  const renderOptionRows = (optionType, columns) => filteredChain.flatMap((row, index) => {
    const strike = Number(row.strike);
    const isITM = underlyingPrice > 0 && (optionType === 'CALL' ? strike < underlyingPrice : strike > underlyingPrice);
    const nextRow = filteredChain[index + 1];
    const divider = underlyingPrice > 0 && strike <= underlyingPrice && nextRow && Number(nextRow.strike) > underlyingPrice;
    const rows = [(
      <tr className={`matrix-row ${isSelectedRow(strike, optionType) ? 'row-selected' : ''}`} key={`${optionType}-${strike}`}>
        {renderMetricCells(row, optionType, isITM, columns)}
      </tr>
    )];
    if (divider) rows.push(
      <tr className="price-divider-row" key={`${optionType}-${strike}-spot`}>
        <td colSpan={columns.length}><div className="price-divider-line"><span>Spot ${underlyingPrice.toFixed(2)}</span></div></td>
      </tr>,
    );
    return rows;
  });

  const renderStrikeRows = () => filteredChain.flatMap((row, index) => {
    const strike = Number(row.strike);
    const nextRow = filteredChain[index + 1];
    const divider = underlyingPrice > 0 && strike <= underlyingPrice && nextRow && Number(nextRow.strike) > underlyingPrice;
    const callLabel = strategyStrikeLabel(row, 'CALL');
    const putLabel = strategyStrikeLabel(row, 'PUT');
    const label = viewMode === 'calls' ? callLabel : viewMode === 'puts' ? putLabel : callLabel === putLabel ? callLabel : `${callLabel} | ${putLabel}`;
    const rows = [<tr className="matrix-row" key={`strike-${strike}`}><td className="strike-cell text-center" title={callLabel === putLabel ? '' : `Calls ${callLabel}; Puts ${putLabel}`}>{label}</td></tr>];
    if (divider) rows.push(<tr className="price-divider-row" key={`strike-${strike}-spot`}><td><div className="price-divider-line"><span>📍</span></div></td></tr>);
    return rows;
  });

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
            onClick={() => fetchOptionChain(symbol, selectedExp, { background: Boolean(chainData) })}
            disabled={loading || isRefreshing}
            className="btn btn-secondary btn-sm chain-refresh-btn"
            title="Refresh Option Chain"
          >
            {loading || isRefreshing ? '⏳ Refreshing...' : '🔄 Refresh'}
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
              disabled={!usesDualPane}
              title={!usesDualPane ? `${activeStrategy.label} displays one option side at a time.` : ''}
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
        <div className="chain-control-group strategy-control-group" ref={strategyControlRef} onMouseEnter={updateStrategyTooltipPlacement} onFocus={updateStrategyTooltipPlacement}>
          <label htmlFor="option-strategy-select" className="chain-control-label">Strategy:</label>
          <div className="strategy-select-with-help" tabIndex="0">
            <select
              id="option-strategy-select"
              value={strategy}
              onChange={(event) => handleStrategyChange(event.target.value)}
              className="chain-select"
              aria-describedby="option-strategy-hover-help"
            >
              {OPTION_STRATEGIES.map((item) => (
                <option key={item.value} value={item.value} disabled={item.disabled}>
                  {item.label}{item.disabled ? ' — API unavailable' : ''}
                </option>
              ))}
            </select>
            <StrategyTooltip strategy={activeStrategy} placement={tooltipPlacement} />
          </div>
          <span id="option-strategy-hover-help" className="sr-only">Hover or focus the selected strategy to see its payoff illustration and description.</span>
          {activeStrategy.usesWidth && (
            <label className="strategy-width-control">
              <span>Width:</span>
              <select value={strategyWidth} onChange={(event) => handleStrategyWidthChange(event.target.value)} className="chain-select" aria-label="Strategy strike width">
                <option value="auto">Auto</option>
                {Array.from({ length: 10 }, (_, index) => index + 1).map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
          )}
        </div>

        <OptionFocusControls
          activeFocus={activeFocus}
          profiles={focusProfiles}
          onFocusChange={setActiveFocus}
          onProfileChange={handleFocusProfileChange}
        />

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
      {refreshWarning && chainData && <div className="chain-refresh-warning" role="status">⚠️ Latest quote refresh failed: {refreshWarning}. Existing values remain displayed.</div>}

      {/* 4. STRATEGY-AWARE OPTIONS MATRIX TABLE */}
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
        <div className={`chain-table-wrapper ${usesDualPane ? 'dual-pane-chain' : 'single-pane-chain'}`}>
          {filteredChain.length === 0 ? (
            <div className="no-data-cell">No options contracts available for {symbol} on {selectedExp}.</div>
          ) : usesDualPane ? (
            <>
              <div className="option-dual-header-grid">
                <div className="option-pane-header-scroll" ref={leftHeaderRef}>
                  <div className="option-pane-header-content" style={{ width: `${selectedColumns.length * 94}px` }}>
                    <div className="option-side-header call-th">{viewMode === 'puts' ? 'PUTS' : 'CALLS'} · {activeStrategy.label}</div>
                    <div className="option-metric-header-row">
                      {[...selectedColumns].reverse().map((column) => <div key={`left-header-${column.id}`} className="option-metric-header call-th">{column.label}</div>)}
                    </div>
                  </div>
                </div>
                <div className="option-strike-header-pane">
                  <div className="option-side-header strike-th">STRIKE</div>
                  <div className="option-metric-header strike-th">{activeStrategy.usesWidth ? `Width ${strategyWidth}` : 'Anchor'}</div>
                </div>
                <div className="option-pane-header-scroll" ref={rightHeaderRef}>
                  <div className="option-pane-header-content" style={{ width: `${selectedColumns.length * 94}px` }}>
                    <div className="option-side-header put-th">{viewMode === 'calls' ? 'CALLS' : 'PUTS'} · {activeStrategy.label}</div>
                    <div className="option-metric-header-row">
                      {selectedColumns.map((column) => <div key={`right-header-${column.id}`} className="option-metric-header put-th">{column.label}</div>)}
                    </div>
                  </div>
                </div>
              </div>
              <div className="option-dual-body-scroll">
                <div className="option-dual-grid">
                  <div
                    className="option-pane-scroll option-pane-left"
                    ref={leftPaneRef}
                    onScroll={(event) => syncMirroredScroll('left', event.currentTarget)}
                  >
                    <table className="options-matrix-table option-pane-table">
                      <tbody>{renderOptionRows(viewMode === 'puts' ? 'PUT' : 'CALL', [...selectedColumns].reverse())}</tbody>
                    </table>
                  </div>
                  <div className="option-strike-pane">
                    <table className="options-matrix-table strike-pane-table">
                      <tbody>{renderStrikeRows()}</tbody>
                    </table>
                  </div>
                  <div
                    className="option-pane-scroll option-pane-right"
                    ref={rightPaneRef}
                    onScroll={(event) => syncMirroredScroll('right', event.currentTarget)}
                  >
                    <table className="options-matrix-table option-pane-table">
                      <tbody>{renderOptionRows(viewMode === 'calls' ? 'CALL' : 'PUT', selectedColumns)}</tbody>
                    </table>
                  </div>
                </div>
              </div>
              <div className="option-dual-scrollbars" aria-label="Mirrored option columns scroll controls">
                <input className="option-scroll-range option-scroll-range-left" type="range" min="0" max="1000" step="1" value={Math.round(leftScrollRatio * 1000)} onChange={(event) => setMirroredRatio(Number(event.target.value) / 1000)} aria-label="Scroll call-side option columns" />
                <div className="option-scroll-rail-strike-spacer" aria-hidden="true" />
                <input className="option-scroll-range option-scroll-range-right" type="range" min="0" max="1000" step="1" value={Math.round((1 - leftScrollRatio) * 1000)} onChange={(event) => setMirroredRatio(1 - (Number(event.target.value) / 1000))} aria-label="Scroll put-side option columns" />
              </div>
            </>
          ) : (
            <div className="option-single-scroll">
              <table className="options-matrix-table option-single-table">
                <thead>
                  <tr><th className="strike-th">STRIKE</th><th className={visibleSingleSide === 'CALL' ? 'call-th' : 'put-th'} colSpan={selectedColumns.length}>{visibleSingleSide === 'CALL' ? 'CALLS' : 'PUTS'} · {activeStrategy.label}</th></tr>
                  <tr><th className="strike-th">{activeStrategy.usesWidth ? `Width ${strategyWidth}` : 'Anchor'}</th>{selectedColumns.map((column) => <th key={`single-${column.id}`} className={visibleSingleSide === 'CALL' ? 'call-th' : 'put-th'}>{column.label}</th>)}</tr>
                </thead>
                <tbody>
                  {filteredChain.flatMap((row, index) => {
                    const strike = Number(row.strike);
                    const isITM = underlyingPrice > 0 && (visibleSingleSide === 'CALL' ? strike < underlyingPrice : strike > underlyingPrice);
                    const nextRow = filteredChain[index + 1];
                    const divider = underlyingPrice > 0 && strike <= underlyingPrice && nextRow && Number(nextRow.strike) > underlyingPrice;
                    const rows = [(
                      <tr className={`matrix-row ${isSelectedRow(strike, visibleSingleSide) ? 'row-selected' : ''}`} key={`single-${strike}`}>
                        <td className="strike-cell">{strategyStrikeLabel(row, visibleSingleSide)}</td>
                        {renderMetricCells(row, visibleSingleSide, isITM)}
                      </tr>
                    )];
                    if (divider) rows.push(<tr className="price-divider-row" key={`single-${strike}-spot`}><td colSpan={selectedColumns.length + 1}><div className="price-divider-line">Spot ${underlyingPrice.toFixed(2)}</div></td></tr>);
                    return rows;
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
