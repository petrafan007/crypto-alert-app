import React, { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import SearchablePairSelect from './SearchablePairSelect';
import TransactionModal from './TransactionModal';
import './TradingViewAdvancedChart.css';

const TRADINGVIEW_WIDGET_SCRIPT = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
const TRADINGVIEW_EXCHANGE = 'BINANCEUS';

const normalizeTradingPair = (value) => String(value || 'BTCUSDT')
  .toUpperCase()
  .replace(/[^A-Z0-9]/g, '');

const toTradingViewSymbol = (value) => `${TRADINGVIEW_EXCHANGE}:${normalizeTradingPair(value)}`;

const getBaseAndQuote = (symbol) => {
  const normalized = normalizeTradingPair(symbol);
  if (normalized.endsWith('USDT')) {
    return { baseAsset: normalized.slice(0, -4), quoteAsset: 'USDT' };
  }
  if (normalized.endsWith('USD')) {
    return { baseAsset: normalized.slice(0, -3), quoteAsset: 'USD' };
  }
  return { baseAsset: normalized, quoteAsset: 'USD' };
};

const normalizeTrade = (trade, index, baseAsset) => {
  const rawDate = trade?.filled_at || trade?.updated_at || trade?.created_at || trade?.time;
  const numericTime = Number(rawDate);
  const parsedTime = Number.isFinite(numericTime) && numericTime > 0
    ? (numericTime > 1e11 ? Math.floor(numericTime / 1000) : Math.floor(numericTime))
    : Math.floor(new Date(rawDate).getTime() / 1000);
  const type = String(trade?.type || trade?.side || '').toUpperCase();
  const status = String(trade?.status || '').toUpperCase();
  const amount = Number(
    trade?.filled_quantity ?? trade?.executed_qty ?? trade?.executedQty ?? trade?.amount ?? trade?.quantity ?? 0
  );
  const price = Number(trade?.filled_price ?? trade?.avg_fill_price ?? trade?.price ?? 0);

  if (
    !Number.isFinite(parsedTime) ||
    parsedTime <= 0 ||
    !['BUY', 'SELL'].includes(type) ||
    !['FILLED', 'COMPLETED'].includes(status) ||
    !Number.isFinite(amount) ||
    amount <= 0 ||
    !Number.isFinite(price) ||
    price <= 0
  ) {
    return null;
  }

  return {
    ...trade,
    id: trade?.id || `${parsedTime}-${type}-${price}-${amount}-${index}`,
    time: parsedTime,
    type,
    status,
    asset: trade?.asset || baseAsset,
    amount,
    price,
  };
};

const formatAmount = (value) => Number(value || 0).toLocaleString(undefined, {
  minimumFractionDigits: 0,
  maximumFractionDigits: 8,
});

const formatPrice = (value, quoteAsset) => {
  const number = Number(value || 0);
  const formatted = number.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: number > 0 && number < 1 ? 8 : 2,
  });
  return quoteAsset === 'USD' ? `$${formatted}` : `${formatted} ${quoteAsset}`;
};

const TradingViewAdvancedChart = ({
  symbol = 'BTCUSDT',
  onSymbolChange,
  tradingPairs = [],
  watchlistPairs = [],
  filterCoin = null,
  onResetFilter = null,
  totalPairsCount = 0,
  isLightMode = false,
}) => {
  const widgetContainerRef = useRef(null);
  const [widgetStatus, setWidgetStatus] = useState('loading');
  const [transactions, setTransactions] = useState([]);
  const [tradeHistoryStatus, setTradeHistoryStatus] = useState('loading');
  const [tradeHistoryError, setTradeHistoryError] = useState('');
  const [modalState, setModalState] = useState({
    isOpen: false,
    transactions: [],
    type: '',
    dateStr: '',
  });

  const normalizedSymbol = normalizeTradingPair(symbol);
  const { baseAsset, quoteAsset } = getBaseAndQuote(normalizedSymbol);
  const tradingViewSymbol = toTradingViewSymbol(normalizedSymbol);
  const tradingViewPageUrl = `https://www.tradingview.com/symbols/${normalizedSymbol}/?exchange=${TRADINGVIEW_EXCHANGE}&utm_source=crypto.petrafied.net&utm_medium=widget_new&utm_campaign=advanced-chart`;

  const tradingViewWatchlist = useMemo(() => {
    const pairIds = watchlistPairs
      .map((pair) => (typeof pair === 'string' ? pair : pair?.id || pair?.symbol))
      .filter(Boolean)
      .map(normalizeTradingPair);
    return Array.from(new Set([normalizedSymbol, ...pairIds]))
      .slice(0, 50)
      .map(toTradingViewSymbol);
  }, [normalizedSymbol, watchlistPairs]);

  const watchlistKey = tradingViewWatchlist.join('|');

  useEffect(() => {
    const host = widgetContainerRef.current;
    if (!host) return undefined;

    setWidgetStatus('loading');
    host.replaceChildren();

    const widgetMount = document.createElement('div');
    widgetMount.className = 'tradingview-widget-container__widget';

    const attribution = document.createElement('div');
    attribution.className = 'tradingview-widget-copyright';
    attribution.innerHTML = `<a href="${tradingViewPageUrl}" rel="noopener nofollow" target="_blank"><span class="blue-text">${baseAsset}/${quoteAsset} chart</span></a><span class="trademark"> by TradingView</span>`;

    const script = document.createElement('script');
    script.src = TRADINGVIEW_WIDGET_SCRIPT;
    script.type = 'text/javascript';
    script.async = true;
    let active = true;
    let observedFrame = null;
    let widgetTimeout = null;

    const markWidgetReady = () => {
      if (!active) return;
      setWidgetStatus('ready');
      if (widgetTimeout) window.clearTimeout(widgetTimeout);
    };

    const watchForWidgetFrame = () => {
      const frame = host.querySelector('iframe');
      if (!frame || frame === observedFrame) return;
      observedFrame = frame;
      frame.addEventListener('load', markWidgetReady, { once: true });
    };

    const widgetObserver = new MutationObserver(watchForWidgetFrame);
    widgetObserver.observe(host, { childList: true, subtree: true });
    script.onload = watchForWidgetFrame;
    script.onerror = () => {
      if (active) setWidgetStatus('error');
    };
    script.text = JSON.stringify({
      autosize: true,
      symbol: tradingViewSymbol,
      interval: 'D',
      timezone: 'exchange',
      theme: isLightMode ? 'light' : 'dark',
      style: '1',
      locale: 'en',
      backgroundColor: isLightMode ? '#ffffff' : '#0b1220',
      gridColor: isLightMode ? 'rgba(46, 46, 46, 0.08)' : 'rgba(148, 163, 184, 0.12)',
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
      watchlist: tradingViewWatchlist,
      compareSymbols: [],
      studies: [],
      support_host: 'https://www.tradingview.com',
    });

    host.append(widgetMount, attribution, script);
    widgetTimeout = window.setTimeout(() => {
      if (active) setWidgetStatus('error');
    }, 20000);

    return () => {
      active = false;
      widgetObserver.disconnect();
      if (observedFrame) observedFrame.removeEventListener('load', markWidgetReady);
      if (widgetTimeout) window.clearTimeout(widgetTimeout);
      script.onload = null;
      script.onerror = null;
      host.replaceChildren();
    };
  }, [baseAsset, isLightMode, normalizedSymbol, quoteAsset, tradingViewPageUrl, tradingViewSymbol, watchlistKey]);

  useEffect(() => {
    const controller = new AbortController();
    setTradeHistoryStatus('loading');
    setTradeHistoryError('');

    axios.get('/api/trading/real-orders', {
      withCredentials: true,
      signal: controller.signal,
      params: {
        limit: 'all',
        symbol: normalizedSymbol,
      },
    }).then((response) => {
      if (response.data?.success) {
        const normalized = (response.data.orders || [])
          .map((trade, index) => normalizeTrade(trade, index, baseAsset))
          .filter(Boolean)
          .sort((a, b) => b.time - a.time);
        setTransactions(normalized);
        setTradeHistoryStatus('ready');
      } else {
        throw new Error(response.data?.error || 'Unable to load completed trade history');
      }
    }).catch((error) => {
      if (error.code === 'ERR_CANCELED' || error.name === 'CanceledError') return;
      setTransactions([]);
      setTradeHistoryError(error.response?.data?.error || error.message || 'Unable to load completed trade history');
      setTradeHistoryStatus('error');
    });

    return () => controller.abort();
  }, [baseAsset, normalizedSymbol]);

  const groupedTrades = useMemo(() => {
    const groups = new Map();
    const dateKeyFormatter = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'America/New_York',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
    const dateLabelFormatter = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York',
      weekday: 'short',
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });

    transactions.forEach((trade) => {
      const date = new Date(trade.time * 1000);
      const key = dateKeyFormatter.format(date);
      if (!groups.has(key)) {
        groups.set(key, {
          key,
          label: dateLabelFormatter.format(date),
          latestTime: trade.time,
          trades: [],
        });
      }
      const group = groups.get(key);
      group.latestTime = Math.max(group.latestTime, trade.time);
      group.trades.push(trade);
    });

    return Array.from(groups.values()).sort((a, b) => b.latestTime - a.latestTime);
  }, [transactions]);

  const summary = useMemo(() => transactions.reduce((totals, trade) => {
    const value = trade.amount * trade.price;
    if (trade.type === 'BUY') {
      totals.buyCount += 1;
      totals.buyValue += value;
    } else {
      totals.sellCount += 1;
      totals.sellValue += value;
    }
    return totals;
  }, { buyCount: 0, sellCount: 0, buyValue: 0, sellValue: 0 }), [transactions]);

  const openTradeDetails = (trade, dateStr) => {
    setModalState({
      isOpen: true,
      transactions: [trade],
      type: trade.type,
      dateStr,
    });
  };

  return (
    <section className="advanced-trading-chart" aria-label={`${baseAsset}/${quoteAsset} advanced chart and trade history`}>
      <header className="advanced-chart-header">
        <div className="advanced-chart-pair-control">
          <span className="advanced-chart-control-label">Trading pair for orders and My Trades</span>
          {onSymbolChange && tradingPairs.length > 0 ? (
            <SearchablePairSelect
              value={normalizedSymbol}
              onChange={onSymbolChange}
              tradingPairs={tradingPairs}
              placeholder="Search Binance.US pairs..."
            />
          ) : (
            <strong>{baseAsset} / {quoteAsset}</strong>
          )}
        </div>
        {filterCoin && onResetFilter && (
          <button
            type="button"
            className="advanced-chart-reset-filter"
            onClick={onResetFilter}
            title={`Filtered to ${filterCoin} pairs. Show every available pair.`}
          >
            Show All Pairs {totalPairsCount > 0 ? `(${totalPairsCount})` : ''}
          </button>
        )}
      </header>

      <div className="advanced-chart-capabilities" aria-label="Available TradingView tools">
        <span>80+ indicators</span>
        <span>100+ drawings</span>
        <span>Native symbol search</span>
        <span>Compare symbols</span>
        <span>Date ranges</span>
        <span>Details, hotlists &amp; calendar</span>
        <span>Image &amp; popup tools</span>
      </div>

      <div className="advanced-chart-widget-shell">
        <div
          ref={widgetContainerRef}
          className="tradingview-widget-container advanced-chart-widget-host"
        />
        {widgetStatus === 'loading' && (
          <div className="advanced-chart-widget-status" role="status">Loading TradingView Advanced Chart…</div>
        )}
        {widgetStatus === 'error' && (
          <div className="advanced-chart-widget-status error" role="alert">
            <span>TradingView could not load. Check the network connection or browser content-blocking settings.</span>
            <a href={tradingViewPageUrl} target="_blank" rel="noopener noreferrer">Open this chart on TradingView</a>
          </div>
        )}
      </div>

      <p className="advanced-chart-sync-note">
        The selector above keeps the order ticket, Binance.US chart, and My Trades history synchronized.
        TradingView's built-in symbol search is also enabled for independent market research.
      </p>

      <section className="personal-trades-panel" aria-labelledby="personal-trades-title">
        <div className="personal-trades-header">
          <div>
            <span className="personal-trades-eyebrow">Pair-aware activity</span>
            <h3 id="personal-trades-title">My {baseAsset} Trades</h3>
            <p>Completed Binance.US buys and sells for this exact pair, grouped by their Eastern Time execution date.</p>
          </div>
          {transactions.length > 0 && (
            <div className="personal-trades-summary" aria-label="Trade totals">
              <span className="trade-summary-buy">
                {summary.buyCount} {summary.buyCount === 1 ? 'buy' : 'buys'} · {formatPrice(summary.buyValue, quoteAsset)}
              </span>
              <span className="trade-summary-sell">
                {summary.sellCount} {summary.sellCount === 1 ? 'sell' : 'sells'} · {formatPrice(summary.sellValue, quoteAsset)}
              </span>
            </div>
          )}
        </div>

        {tradeHistoryStatus === 'loading' && (
          <div className="personal-trades-empty" role="status">Loading {baseAsset} trade dates…</div>
        )}
        {tradeHistoryStatus === 'error' && (
          <div className="personal-trades-empty error" role="alert">{tradeHistoryError}</div>
        )}
        {tradeHistoryStatus === 'ready' && groupedTrades.length === 0 && (
          <div className="personal-trades-empty">No completed Binance.US buys or sells were found for {baseAsset}/{quoteAsset}.</div>
        )}

        {groupedTrades.length > 0 && (
          <div className="personal-trades-timeline">
            {groupedTrades.map((group) => (
              <article className="trade-date-group" key={group.key}>
                <div className="trade-date-heading">
                  <time dateTime={group.key}>{group.label}</time>
                  <span>{group.trades.length} {group.trades.length === 1 ? 'trade' : 'trades'}</span>
                </div>
                <div className="trade-date-items">
                  {group.trades.map((trade) => {
                    const timeLabel = new Date(trade.time * 1000).toLocaleTimeString('en-US', {
                      timeZone: 'America/New_York',
                      hour: 'numeric',
                      minute: '2-digit',
                    });
                    return (
                      <button
                        type="button"
                        className={`personal-trade-row ${trade.type.toLowerCase()}`}
                        key={trade.id}
                        onClick={() => openTradeDetails(trade, group.label)}
                        title="Open full transaction details"
                      >
                        <span className="personal-trade-side" aria-label={trade.type}>
                          {trade.type === 'BUY' ? '↑' : '↓'} {trade.type}
                        </span>
                        <time dateTime={new Date(trade.time * 1000).toISOString()}>{timeLabel} ET</time>
                        <span className="personal-trade-amount">{formatAmount(trade.amount)} {baseAsset}</span>
                        <span className="personal-trade-price">@ {formatPrice(trade.price, quoteAsset)}</span>
                        <strong>{formatPrice(trade.amount * trade.price, quoteAsset)}</strong>
                      </button>
                    );
                  })}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <TransactionModal
        isOpen={modalState.isOpen}
        onClose={() => setModalState((previous) => ({ ...previous, isOpen: false }))}
        transactions={modalState.transactions}
        type={modalState.type}
        dateStr={modalState.dateStr}
        quoteAsset={quoteAsset}
      />
    </section>
  );
};

export default TradingViewAdvancedChart;
