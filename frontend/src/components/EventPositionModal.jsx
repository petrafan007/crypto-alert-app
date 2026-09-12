import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { cutoffFromSymbol } from '../utils/positions.mjs';
import EventContractMiniChart from './EventContractMiniChart';
import './EventPositionModal.css';

const numeric = (value, fallback = null) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const contractSymbol = (holding) => String(holding?.underlying_symbol || holding?.symbol || '')
  .replace(/\s+(YES|NO)$/i, '')
  .trim()
  .toUpperCase();

const heldOutcome = (holding) => {
  const raw = holding?.event_outcome
    || holding?.purchased_outcome
    || holding?.side
    || holding?.position_side
    || holding?.details?.outcome
    || String(holding?.symbol || '').match(/[\s-](YES|NO)$/i)?.[1];
  const val = String(raw || '').trim().toLowerCase();
  return val === 'no' ? 'no' : 'yes';
};

const providerTime = (value) => {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'number' || /^\d+(\.\d+)?$/.test(String(value))) {
    const raw = Number(value);
    return new Date(raw > 100000000000 ? raw : raw * 1000);
  }
  const text = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    let offset = '-04:00';
    try {
      const probe = new Date(`${text}T12:00:00Z`);
      const tzStr = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', timeZoneName: 'short' }).format(probe);
      if (tzStr.includes('EST')) offset = '-05:00';
    } catch {
      offset = '-04:00';
    }
    const endOfDay = Date.parse(`${text}T23:59:59${offset}`);
    return Number.isFinite(endOfDay) ? new Date(endOfDay) : null;
  }
  const parsed = new Date(text);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

/** Format a Date or ISO string as M/D/YYYY, h:mm A in Eastern time, without seconds or TZ label. */
const fmtEastern = (value) => {
  if (!value) return 'Not provided';
  const d = value instanceof Date ? value : providerTime(value);
  if (!d || Number.isNaN(d.getTime())) return 'Not provided';
  return d.toLocaleString('en-US', {
    timeZone: 'America/New_York',
    month: 'numeric',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
};

/**
 * Detect if a date value is a bare UTC midnight that was parsed from a date-only string
 * (e.g. "2026-09-11") and would therefore show as 8:00 PM EDT the prior evening.
 * In that case we should prefer the contract cutoff time instead.
 */
const isDateOnlyMidnight = (value) => {
  if (!value) return false;
  const text = String(value).trim();
  // A bare YYYY-MM-DD date or a UTC midnight ISO
  return /^\d{4}-\d{2}-\d{2}$/.test(text) || /T00:00:00(\.0+)?(Z|[+-]00:00)$/.test(text);
};

const formatCountdown = (milliseconds) => {
  const safe = Math.max(0, Math.floor(milliseconds));
  const minutes = Math.floor(safe / 60000);
  const seconds = Math.floor((safe % 60000) / 1000);
  const millis = safe % 1000;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    + `.${String(millis).padStart(3, '0')}`;
};

const cents = (value) => {
  const parsed = numeric(value);
  if (parsed === null) return '—';
  const amount = parsed * 100;
  return `${amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}¢`;
};

const money = (value, digits = 2) => {
  const parsed = numeric(value);
  return parsed === null ? '—' : `$${parsed.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
};

const quantityText = (value) => {
  const parsed = numeric(value);
  return parsed === null ? '—' : parsed.toLocaleString(undefined, { maximumFractionDigits: 5 });
};

const quoteFor = (market, outcome, side) => {
  const key = `${String(outcome || 'yes').toLowerCase()}_${side === 'SELL' ? 'bid' : 'ask'}`;
  const value = numeric(market?.[key]);
  return value !== null && value > 0 ? value : null;
};

const priceMatchesRanges = (price, ranges = []) => {
  const value = numeric(price);
  if (value === null) return false;
  return ranges.some((range) => {
    const start = numeric(range.start);
    const end = numeric(range.end);
    const step = numeric(range.step);
    if ([start, end, step].some((item) => item === null) || step <= 0 || value < start || value > end) return false;
    return Math.abs(((value - start) / step) - Math.round((value - start) / step)) <= 1e-6;
  });
};

function EventCountdown({ cutoff, serverOffset, onExpire }) {
  const [clock, setClock] = useState(Date.now());
  useEffect(() => {
    const interval = window.setInterval(() => setClock(Date.now()), 33);
    return () => window.clearInterval(interval);
  }, []);
  const remaining = cutoff ? cutoff.getTime() - (clock + serverOffset) : null;
  useEffect(() => {
    if (remaining !== null && remaining <= 0) onExpire?.();
  }, [remaining, onExpire]);
  return <strong>{remaining === null ? 'Unavailable' : formatCountdown(remaining)}</strong>;
}

export default function EventPositionModal({
  isOpen,
  holding,
  openOrder = null,
  initialMarket = null,
  isTestMode = false,
  isLightMode = false,
  onClose,
  onReviewOrder,
  onCancelOrder,
  cancellingOrderId,
}) {
  const record = openOrder || holding;
  const isOpenOrder = Boolean(openOrder);
  const symbol = contractSymbol(record);
  const positionOutcome = heldOutcome(record);
  const accountId = String(record?.account_id || record?._webull_account_id || record?.webull_account_id || '');
  const storedQuantity = isOpenOrder
    ? numeric(record?.quantity, 0)
    : numeric(record?.available_quantity ?? record?.quantity ?? record?.amount, 0);
  const storedPrice = isOpenOrder
    ? (record?.price || record?.limit_price ? String(record.price || record.limit_price) : '')
    : '';
  const initialSide = isOpenOrder
    ? (String(record?.side || '').toUpperCase().includes('SELL') ? 'SELL' : 'BUY')
    : 'SELL';

  const [market, setMarket] = useState(() => initialMarket || record?.market || null);
  const loadedSymbolRef = useRef(symbol);
  const [availableQuantity, setAvailableQuantity] = useState(storedQuantity);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [serverOffset, setServerOffset] = useState(0);
  const [cutoffExpired, setCutoffExpired] = useState(false);
  const [side, setSide] = useState(initialSide);
  const [outcome, setOutcome] = useState(positionOutcome);
  const [quantity, setQuantity] = useState(storedQuantity > 0 ? String(storedQuantity) : '1');
  const [price, setPrice] = useState(storedPrice);
  const [validationError, setValidationError] = useState('');

  useEffect(() => {
    if (!isOpen) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') onClose?.();
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [isOpen, onClose]);

  // Synchronize initialMarket when supplied externally
  useEffect(() => {
    if (initialMarket && (!market || market.symbol !== initialMarket.symbol)) {
      setMarket(initialMarket);
      loadedSymbolRef.current = initialMarket.symbol;
    }
  }, [initialMarket]);

  // Reset or initialize state only when symbol actually changes to a different contract
  useEffect(() => {
    if (symbol && loadedSymbolRef.current !== symbol) {
      loadedSymbolRef.current = symbol;
      setMarket(initialMarket?.symbol === symbol ? initialMarket : null);
      setCutoffExpired(false);
    }
  }, [symbol, initialMarket]);

  // Synchronize form side, outcome, quantity, and price when order/position changes
  useEffect(() => {
    if (!isOpen) return;
    setSide(initialSide);
    setOutcome(positionOutcome);
    setAvailableQuantity(storedQuantity);
    setQuantity(storedQuantity > 0 ? String(storedQuantity) : '1');
    if (storedPrice) {
      setPrice(storedPrice);
    } else {
      const suggested = quoteFor(market || initialMarket, positionOutcome, isOpenOrder ? initialSide : 'SELL');
      if (suggested !== null) {
        setPrice(String(suggested));
      }
    }
    setValidationError('');
  }, [isOpen, isOpenOrder, positionOutcome, initialSide, storedQuantity, storedPrice]);

  // Fetch contract position facts and bars without cancelling on quantity or fill state changes
  useEffect(() => {
    if (!isOpen || !symbol) return undefined;
    let cancelled = false;

    if (!market || market.symbol !== symbol) {
      setLoading(true);
    }
    setError('');

    axios.get('/api/webull/events/position', {
      params: {
        symbol,
        account_id: accountId,
        event_outcome: positionOutcome,
        timespan: 'M1',
        count: 240,
        test_mode: isTestMode ? '1' : '0',
      },
      withCredentials: true,
    }).then((response) => {
      if (cancelled) return;
      const details = response.data || {};
      const nextMarket = details.market || null;
      if (nextMarket) {
        setMarket((prev) => ({ ...(prev || {}), ...nextMarket }));
      }
      if (!isOpenOrder && details.available_quantity !== null && details.available_quantity !== undefined) {
        setAvailableQuantity(numeric(details.available_quantity, storedQuantity));
      }
      const serverTime = providerTime(details.server_time);
      setServerOffset(serverTime ? serverTime.getTime() - Date.now() : 0);
      if (!storedPrice) {
        const suggested = quoteFor(nextMarket, positionOutcome, isOpenOrder ? initialSide : 'SELL');
        if (suggested !== null) {
          setPrice((current) => (!current ? String(suggested) : current));
        }
      }
    }).catch((requestError) => {
      if (!cancelled && !market) {
        setError(requestError.response?.data?.message || 'Unable to load this Event Contract position.');
      }
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });

    return () => { cancelled = true; };
  }, [isOpen, symbol, accountId, positionOutcome, isTestMode]);

  useEffect(() => {
    if (!isOpen || !symbol) return undefined;
    let cancelled = false;
    const refreshQuote = () => axios.get('/api/webull/events/markets', {
      params: { symbol },
      withCredentials: true,
    }).then((response) => {
      if (cancelled) return;
      const nextMarket = response.data?.markets?.[0];
      if (!nextMarket) return;
      setMarket((prev) => ({ ...(prev || {}), ...nextMarket }));
      setPrice((current) => {
        const previousSuggested = quoteFor(market, outcome, side);
        const nextSuggested = quoteFor(nextMarket, outcome, side);
        return nextSuggested !== null && (!current || Number(current) === previousSuggested)
          ? String(nextSuggested)
          : current;
      });
    }).catch(() => {});
    const interval = window.setInterval(refreshQuote, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [isOpen, symbol, outcome, side]);

  const [clock, setClock] = useState(Date.now());
  useEffect(() => {
    if (!isOpen) return undefined;
    const timer = window.setInterval(() => setClock(Date.now()), 100);
    return () => window.clearInterval(timer);
  }, [isOpen]);

  const symbolCutoff = cutoffFromSymbol(market?.symbol || symbol);
  const cutoff = symbolCutoff ? new Date(symbolCutoff) : providerTime(
    market?.contract_period_end
    || market?.cutoff_at
    || market?.last_trading_date
    || market?.expected_exp_date
    || market?.latest_exp_date
  );

  const isCutoffPassed = cutoff ? cutoff.getTime() <= (clock + serverOffset) : false;
  const isExpired = cutoffExpired || isCutoffPassed;

  const fallbackMarket = useMemo(() => {
    if (!symbol) return null;
    const base = symbol.replace(/^KX/, '').replace(/15M.*|1H.*|DAILY.*/i, '').trim().toUpperCase();
    return {
      symbol,
      name: symbol,
      underlying_symbol: base ? `${base}USDT` : symbol,
      display_condition: `${symbol} Event Contract`,
      cutoff_at: symbolCutoff ? new Date(symbolCutoff).toISOString() : null,
      tradable_status: isExpired ? 'CLOSED' : 'OC',
    };
  }, [symbol, symbolCutoff, isExpired]);

  const activeMarket = market || fallbackMarket;

  // Resolve Opens using contract_period_start, falling back to open_date (only if non-midnight UTC)
  const opensDate = useMemo(() => {
    const periodStart = activeMarket?.contract_period_start;
    if (periodStart) return providerTime(periodStart);
    if (activeMarket?.open_date && !isDateOnlyMidnight(activeMarket.open_date)) return providerTime(activeMarket.open_date);
    return null;
  }, [activeMarket?.contract_period_start, activeMarket?.open_date]);

  // Expected determination: use contract_period_end/cutoff if the provider's expected_exp_date is bare UTC midnight
  const expectedDetermination = useMemo(() => {
    const exp = activeMarket?.expected_exp_date;
    if (exp && !isDateOnlyMidnight(exp)) return providerTime(exp);
    // Fall back to cutoff (contract period end), which we already computed
    return cutoff;
  }, [activeMarket?.expected_exp_date, cutoff]);

  // Expected payout: use payout_date if non-midnight, else fall back to cutoff
  const expectedPayout = useMemo(() => {
    const pd = activeMarket?.payout_date;
    if (pd && !isDateOnlyMidnight(pd)) return providerTime(pd);
    return cutoff;
  }, [activeMarket?.payout_date, cutoff]);

  const providerStatus = String(activeMarket?.tradable_status || '').toUpperCase();
  const effectiveStatus = isExpired
    ? 'CLOSED'
    : (['OC', 'CO'].includes(providerStatus)
        ? providerStatus
        : (isCutoffPassed ? 'CLOSED' : (providerStatus ? 'CLOSED' : 'OC')));
  const statusLabel = isExpired
    ? 'Closed'
    : (effectiveStatus === 'OC'
      ? 'Open for trading'
      : effectiveStatus === 'CO'
        ? 'Closing only'
        : 'Closed');
  const rules = activeMarket?.rules || {};
  const averagePrice = isOpenOrder ? null : numeric(record?.avg_entry ?? record?.cost_price, 0);
  const positionQuantity = isOpenOrder ? availableQuantity : numeric(record?.quantity ?? record?.amount, 0);
  const orderQuantity = numeric(record?.quantity, 0);
  const orderFilledQuantity = numeric(record?.filled_quantity, 0);
  const orderRemainingQuantity = Math.max(0, orderQuantity - orderFilledQuantity);
  const executableBid = quoteFor(activeMarket, positionOutcome, 'SELL');
  const estimatedCloseValue = executableBid === null ? null : executableBid * availableQuantity;
  const unrealizedPnl = executableBid === null || averagePrice === null ? null : (executableBid - averagePrice) * positionQuantity;
  const winningPayout = positionQuantity * numeric(rules.settlement_payout, 1);
  const selectedQuote = quoteFor(activeMarket, outcome, side);

  // Derive the underlying crypto symbol for the mini chart (e.g. "KXBTC15M-..." → "BTCUSDT")
  const underlyingChartSymbol = useMemo(() => {
    const ms = activeMarket?.underlying_symbol || activeMarket?.underlying_name || symbol;
    const base = String(ms || '').replace(/^KX/, '').replace(/15M.*|1H.*|DAILY.*/i, '').trim().toUpperCase();
    if (!base) return null;
    // If it looks like a crypto base (BTC, ETH, SOL, etc.) add USDT for Binance kline lookup
    return /^[A-Z]{2,6}$/.test(base) ? `${base}USDT` : base;
  }, [activeMarket?.underlying_symbol, activeMarket?.underlying_name, symbol]);

  // Best guess at live underlying price from market reference data
  const liveUnderlyingPrice = numeric(activeMarket?.reference_price ?? activeMarket?.target_value, 0);

  if (!isOpen || !record) return null;

  const chooseOrder = (nextSide, nextOutcome) => {
    const nextQuote = quoteFor(activeMarket, nextOutcome, nextSide);
    setSide(nextSide);
    setOutcome(nextOutcome);
    setPrice(nextQuote === null ? '' : String(nextQuote));
    setQuantity(nextSide === 'SELL' ? String(availableQuantity || '') : '1');
    setValidationError('');
  };

  const reviewOrder = () => {
    const orderQty = numeric(quantity);
    const orderPx = numeric(price);
    if (!market?.symbol) {
      setValidationError('Live contract details must load before an order can be reviewed.');
      return;
    }
    if (side === 'BUY' && effectiveStatus !== 'OC') {
      setValidationError('This contract is not open for new positions.');
      return;
    }
    if (side === 'SELL' && !['OC', 'CO'].includes(effectiveStatus)) {
      setValidationError('This position can no longer be closed because trading has ended.');
      return;
    }
    if (orderQty === null || orderQty <= 0) {
      setValidationError('Enter a contract quantity greater than zero.');
      return;
    }
    if (!isOpenOrder && side === 'SELL' && orderQty > availableQuantity + 1e-8) {
      setValidationError(`You can close up to ${quantityText(availableQuantity)} contracts.`);
      return;
    }
    if (!rules.fractionable && !Number.isInteger(orderQty)) {
      setValidationError('This Event Contract requires a whole-number quantity.');
      return;
    }
    if (orderPx === null || !priceMatchesRanges(orderPx, rules.price_ranges || [])) {
      setValidationError('Enter a limit price that matches Webull\u2019s current price range and tick size.');
      return;
    }
    onReviewOrder?.({
      holding: record,
      market,
      side,
      outcome,
      quantity: orderQty,
      price: orderPx,
      replacing_order_id: isOpenOrder ? (record?.id || record?.order_id) : undefined,
    });
  };

  return (
    <div className="event-position-modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose?.()}>
      <section className="event-position-modal" role="dialog" aria-modal="true" aria-labelledby="event-position-title">
        <header className="event-position-modal-header">
          <div className="event-position-header-top-row">
            <span className="event-position-kicker">{isOpenOrder ? 'Event Contract Open Order' : 'Current Event Contract Position'}</span>
            <div className="event-position-header-countdown">
              <span className="countdown-label">Trading time remaining</span>
              <EventCountdown cutoff={cutoff} serverOffset={serverOffset} onExpire={() => setCutoffExpired(true)} />
            </div>
            <button type="button" className="event-position-close" onClick={onClose} aria-label="Close Event Contract position">×</button>
          </div>

          <div className="event-position-title-row">
            <h2 id="event-position-title">{activeMarket?.name || symbol}</h2>
            <span className={`event-position-status status-${effectiveStatus.toLowerCase() || 'unknown'}`}>{statusLabel}</span>
          </div>

          <div className="event-position-header-sub">
            <p className="event-position-condition">{activeMarket?.display_condition || activeMarket?.yes_condition || `${symbol} Event Contract`}</p>
            {activeMarket?.symbol && (
              <div className="event-position-header-meta">
                {activeMarket?.target_value != null && (
                  <span className="event-position-target-badge">Target Price: <strong>{activeMarket?.reference_price != null ? `$${Number(activeMarket.reference_price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'}</strong></span>
                )}
                <span className="event-position-symbol-badge">{activeMarket.symbol}</span>
              </div>
            )}
          </div>
        </header>

        <div className="event-position-modal-body">
          {loading && !market && <div className="event-position-loading">Loading current Webull contract facts and chart…</div>}
          {error && <div className="event-position-error">{error}</div>}

          {activeMarket && (
            <>
              {/* Compact 5x2 Facts Grid */}
              <div className="event-position-facts-grid">
                {isOpenOrder ? (
                  <>
                    <div><span>Open order side</span><strong>{String(record?.side || 'BUY').toUpperCase()}</strong></div>
                    <div><span>Order outcome</span><strong>{positionOutcome.toUpperCase()}</strong></div>
                    <div><span>Order quantity</span><strong>{quantityText(orderQuantity)}</strong></div>
                    <div><span>Filled / remaining</span><strong>{quantityText(orderFilledQuantity)} / {quantityText(orderRemainingQuantity)}</strong></div>
                    <div><span>Order limit</span><strong>{cents(record?.price ?? record?.limit_price)}</strong></div>
                    <div><span>Order status</span><strong>{String(record?.status || 'Working')}</strong></div>
                    <div><span>Available to close</span><strong>{quantityText(availableQuantity)}</strong></div>
                    <div><span>Yes bid / ask</span><strong>{cents(activeMarket.yes_bid)} / {cents(activeMarket.yes_ask)}</strong></div>
                    <div><span>No bid / ask</span><strong>{cents(activeMarket.no_bid)} / {cents(activeMarket.no_ask)}</strong></div>
                    <div><span>Volume / open int</span><strong>{quantityText(activeMarket.volume)} / {quantityText(activeMarket.open_interest)}</strong></div>
                  </>
                ) : (
                  <>
                    <div><span>Held outcome</span><strong>{positionOutcome.toUpperCase()}</strong></div>
                    <div><span>Contracts</span><strong>{quantityText(positionQuantity)}</strong></div>
                    <div><span>Available to close</span><strong>{quantityText(availableQuantity)}</strong></div>
                    <div><span>Average entry</span><strong>{cents(averagePrice)}</strong></div>
                    <div><span>Executable bid</span><strong>{cents(executableBid)}</strong></div>
                    <div><span>Estimated close value</span><strong>{money(estimatedCloseValue)}</strong></div>
                    <div><span>Open P&amp;L at bid</span><strong className={unrealizedPnl > 0 ? 'gain' : unrealizedPnl < 0 ? 'loss' : ''}>{money(unrealizedPnl)}</strong></div>
                    <div><span>Winning payout</span><strong>{money(winningPayout)}</strong></div>
                    <div><span>Yes bid / ask</span><strong>{cents(activeMarket.yes_bid)} / {cents(activeMarket.yes_ask)}</strong></div>
                    <div><span>No bid / ask</span><strong>{cents(activeMarket.no_bid)} / {cents(activeMarket.no_ask)}</strong></div>
                  </>
                )}
              </div>

              {/* Two-Column Main Content: Left Column (Chart + Timeline), Right Column (Action Card) */}
              <div className="event-position-main-columns">
                <div className="event-position-col-left">
                  {underlyingChartSymbol && (
                    <div className="event-position-chart-card">
                      <EventContractMiniChart
                        symbol={underlyingChartSymbol}
                        market={activeMarket}
                        duration={activeMarket?.series_frequency}
                        isLightMode={isLightMode}
                        livePrice={liveUnderlyingPrice}
                      />
                    </div>
                  )}

                  <div className="event-position-timeline">
                    <h3>Timeline &amp; Settlement</h3>
                    <div className="event-position-timeline-grid">
                      <div><span>Opens</span><strong>{fmtEastern(opensDate)}</strong></div>
                      <div><span>Trading cutoff</span><strong>{cutoff ? fmtEastern(cutoff) : 'Not provided'}</strong></div>
                      <div><span>Expected determination</span><strong>{fmtEastern(expectedDetermination)}</strong></div>
                      <div><span>Expected payout</span><strong>{fmtEastern(expectedPayout)}</strong></div>
                    </div>
                  </div>
                </div>

                <div className="event-position-col-right">
                  <div className={`event-position-order-card ${isExpired ? 'is-expired' : ''}`}>
                    <h3>{isOpenOrder ? 'Replace this open order' : 'Manage this position'}</h3>
                    <div className="event-position-order-actions">
                      {isOpenOrder && (
                        <button
                          type="button"
                          className="cancel-open-order"
                          disabled={isExpired || cancellingOrderId === record.id}
                          onClick={() => onCancelOrder?.(record)}
                        >
                          {cancellingOrderId === record.id ? 'Cancelling...' : 'Cancel Open Order'}
                        </button>
                      )}
                      <button type="button" className={side === 'BUY' && outcome === 'yes' ? 'active yes' : ''} disabled={isExpired || effectiveStatus !== 'OC'} onClick={() => chooseOrder('BUY', 'yes')}>Buy Yes {activeMarket?.yes_ask ? cents(activeMarket.yes_ask) : ''}</button>
                      <button type="button" className={side === 'BUY' && outcome === 'no' ? 'active no' : ''} disabled={isExpired || effectiveStatus !== 'OC'} onClick={() => chooseOrder('BUY', 'no')}>Buy No {activeMarket?.no_ask ? cents(activeMarket.no_ask) : ''}</button>
                      <button type="button" className={side === 'SELL' ? 'active close-position' : ''} disabled={isExpired || !['OC', 'CO'].includes(effectiveStatus) || (!isOpenOrder && availableQuantity <= 0)} onClick={() => chooseOrder('SELL', positionOutcome)}>Close {positionOutcome.toUpperCase()} Position {executableBid ? cents(executableBid) : ''}</button>
                    </div>
                    <div className="event-position-order-fields">
                      <label>Contracts<input type="number" min="0" step={rules.fractionable ? '0.00001' : '1'} value={quantity} disabled={isExpired} onChange={(event) => { setQuantity(event.target.value); setValidationError(''); }} /></label>
                      <label>Limit price (USD)<input type="number" min="0" max="1" step="0.0001" value={price} disabled={isExpired} onChange={(event) => { setPrice(event.target.value); setValidationError(''); }} /></label>
                      <div className="event-position-quote-box"><span>Current quote</span><strong>{cents(selectedQuote)}</strong></div>
                    </div>
                    {validationError && <p className="event-position-validation" role="alert">{validationError}</p>}
                    <div className="event-position-order-footer">
                      <small>
                        {isExpired
                          ? 'Trading cutoff has passed. This contract is closed and awaiting settlement determination.'
                          : (isOpenOrder ? `Submitting will cancel open order #${record?.id || record?.order_id} and submit this updated order.` : 'Limit / Day only. Live orders continue through the normal Webull confirmation and security checks.')
                        }
                      </small>
                      {isExpired ? (
                        <button
                          type="button"
                          className="event-position-review expired-close-btn"
                          onClick={onClose}
                          aria-label="Close modal"
                        >
                          Close
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="event-position-review"
                          disabled={!activeMarket || (side === 'BUY' ? effectiveStatus !== 'OC' : !['OC', 'CO'].includes(effectiveStatus))}
                          onClick={reviewOrder}
                        >
                          {isOpenOrder ? 'Review & Replace Order' : `Review ${side === 'SELL' ? 'Close Position' : `Buy ${outcome.toUpperCase()}`} Order`}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
