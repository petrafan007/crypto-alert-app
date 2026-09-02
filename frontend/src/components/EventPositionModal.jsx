import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import { formatEasternDateTime } from '../utils/dateTime';
import './EventPositionModal.css';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend, Filler);

const numeric = (value, fallback = null) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const contractSymbol = (holding) => String(holding?.underlying_symbol || holding?.symbol || '')
  .replace(/\s+(YES|NO)$/i, '')
  .trim()
  .toUpperCase();

const heldOutcome = (holding) => String(
  holding?.event_outcome || String(holding?.symbol || '').match(/\s+(YES|NO)$/i)?.[1] || 'yes',
).toLowerCase();

const providerTime = (value) => {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'number' || /^\d+(\.\d+)?$/.test(String(value))) {
    const raw = Number(value);
    return new Date(raw > 100000000000 ? raw : raw * 1000);
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
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
    ? numeric(record?.filled_quantity, 0)
    : numeric(record?.available_quantity ?? record?.quantity ?? record?.amount, 0);
  const [market, setMarket] = useState(null);
  const [bars, setBars] = useState([]);
  const [availableQuantity, setAvailableQuantity] = useState(storedQuantity);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [chartMessage, setChartMessage] = useState('');
  const [serverOffset, setServerOffset] = useState(0);
  const [cutoffExpired, setCutoffExpired] = useState(false);
  const [side, setSide] = useState(isOpenOrder ? 'BUY' : 'SELL');
  const [outcome, setOutcome] = useState(positionOutcome);
  const [quantity, setQuantity] = useState(storedQuantity > 0 ? String(storedQuantity) : '1');
  const [price, setPrice] = useState('');
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

  useEffect(() => {
    if (!isOpen || !symbol) return undefined;
    let cancelled = false;
    setLoading(true);
    setError('');
    setChartMessage('');
    setMarket(null);
    setBars([]);
    setSide(isOpenOrder ? 'BUY' : 'SELL');
    setOutcome(positionOutcome);
    setAvailableQuantity(storedQuantity);
    setQuantity(storedQuantity > 0 ? String(storedQuantity) : '1');
    setPrice('');
    setValidationError('');
    setCutoffExpired(false);

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
      setMarket(nextMarket);
      setBars(Array.isArray(details.bars) ? details.bars : []);
      setChartMessage(details.chart_message || '');
      if (details.available_quantity !== null && details.available_quantity !== undefined) {
        setAvailableQuantity(numeric(details.available_quantity, storedQuantity));
        setQuantity(String(numeric(details.available_quantity, storedQuantity)));
      }
      const serverTime = providerTime(details.server_time);
      setServerOffset(serverTime ? serverTime.getTime() - Date.now() : 0);
      const suggested = quoteFor(nextMarket, positionOutcome, isOpenOrder ? 'BUY' : 'SELL');
      setPrice(suggested === null ? '' : String(suggested));
    }).catch((requestError) => {
      if (!cancelled) {
        setError(requestError.response?.data?.message || 'Unable to load this Event Contract position.');
      }
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [isOpen, symbol, accountId, positionOutcome, isTestMode, storedQuantity, isOpenOrder]);

  useEffect(() => {
    if (!isOpen || !symbol || !market) return undefined;
    let cancelled = false;
    const refreshQuote = () => axios.get('/api/webull/events/markets', {
      params: { symbol },
      withCredentials: true,
    }).then((response) => {
      if (cancelled) return;
      const nextMarket = response.data?.markets?.[0];
      if (!nextMarket) return;
      setMarket(nextMarket);
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
  }, [isOpen, symbol, market?.symbol, outcome, side]);

  const cutoff = providerTime(
    market?.contract_period_end
    || market?.last_trading_date
    || market?.expected_exp_date
    || market?.latest_exp_date
  );
  const providerStatus = String(market?.tradable_status || '').toUpperCase();
  const effectiveStatus = cutoffExpired ? 'NT' : providerStatus;
  const statusLabel = effectiveStatus === 'OC'
    ? 'Open for trading'
    : effectiveStatus === 'CO'
      ? 'Closing only'
      : effectiveStatus === 'NT'
        ? 'Trading closed / awaiting determination'
        : 'Status unavailable';
  const rules = market?.rules || {};
  const averagePrice = isOpenOrder ? null : numeric(record?.avg_entry ?? record?.cost_price, 0);
  const positionQuantity = isOpenOrder ? availableQuantity : numeric(record?.quantity ?? record?.amount, 0);
  const orderQuantity = numeric(record?.quantity, 0);
  const orderFilledQuantity = numeric(record?.filled_quantity, 0);
  const orderRemainingQuantity = Math.max(0, orderQuantity - orderFilledQuantity);
  const executableBid = quoteFor(market, positionOutcome, 'SELL');
  const estimatedCloseValue = executableBid === null ? null : executableBid * availableQuantity;
  const unrealizedPnl = executableBid === null || averagePrice === null ? null : (executableBid - averagePrice) * positionQuantity;
  const winningPayout = positionQuantity * numeric(rules.settlement_payout, 1);
  const selectedQuote = quoteFor(market, outcome, side);

  const chartData = useMemo(() => ({
    labels: bars.map((bar) => formatEasternDateTime(new Date(Number(bar.time) * 1000).toISOString())),
    datasets: [{
      label: 'Yes contract price',
      data: bars.map((bar) => numeric(bar.close, 0) * 100),
      borderColor: '#14b8a6',
      backgroundColor: 'rgba(20, 184, 166, 0.16)',
      pointRadius: 0,
      pointHoverRadius: 4,
      borderWidth: 2,
      fill: true,
      tension: 0.2,
    }],
  }), [bars]);

  const chartOptions = useMemo(() => ({
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { intersect: false, mode: 'index' },
    plugins: {
      legend: { labels: { color: isLightMode ? '#334155' : '#cbd5e1' } },
      tooltip: { callbacks: { label: (context) => `Yes ${Number(context.parsed.y).toFixed(2)}¢` } },
    },
    scales: {
      x: { ticks: { color: isLightMode ? '#475569' : '#94a3b8', maxTicksLimit: 8 }, grid: { color: isLightMode ? 'rgba(71,85,105,.14)' : 'rgba(148,163,184,.12)' } },
      y: {
        min: 0,
        max: 100,
        ticks: { color: isLightMode ? '#475569' : '#94a3b8', callback: (value) => `${value}¢` },
        grid: { color: isLightMode ? 'rgba(71,85,105,.14)' : 'rgba(148,163,184,.12)' },
      },
    },
  }), [isLightMode]);

  if (!isOpen || !record) return null;

  const chooseOrder = (nextSide, nextOutcome) => {
    const nextQuote = quoteFor(market, nextOutcome, nextSide);
    setSide(nextSide);
    setOutcome(nextOutcome);
    setPrice(nextQuote === null ? '' : String(nextQuote));
    setQuantity(nextSide === 'SELL' ? String(availableQuantity || '') : '1');
    setValidationError('');
  };

  const reviewOrder = () => {
    const orderQuantity = numeric(quantity);
    const orderPrice = numeric(price);
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
    if (orderQuantity === null || orderQuantity <= 0) {
      setValidationError('Enter a contract quantity greater than zero.');
      return;
    }
    if (side === 'SELL' && orderQuantity > availableQuantity + 1e-8) {
      setValidationError(`You can close up to ${quantityText(availableQuantity)} contracts.`);
      return;
    }
    if (!rules.fractionable && !Number.isInteger(orderQuantity)) {
      setValidationError('This Event Contract requires a whole-number quantity.');
      return;
    }
    if (orderPrice === null || !priceMatchesRanges(orderPrice, rules.price_ranges || [])) {
      setValidationError('Enter a limit price that matches Webull’s current price range and tick size.');
      return;
    }
    onReviewOrder?.({
      holding: record,
      market,
      side,
      outcome,
      quantity: orderQuantity,
      price: orderPrice,
    });
  };

  return (
    <div className="event-position-modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose?.()}>
      <section className="event-position-modal" role="dialog" aria-modal="true" aria-labelledby="event-position-title">
        <header className="event-position-modal-header">
          <div>
            <span className="event-position-kicker">{isOpenOrder ? 'Event Contract Open Order' : 'Current Event Contract Position'}</span>
            <h2 id="event-position-title">{market?.name || symbol}</h2>
            <p>{market?.display_condition || market?.yes_condition || 'Contract condition unavailable'}</p>
          </div>
          <button type="button" className="event-position-close" onClick={onClose} aria-label="Close Event Contract position">×</button>
        </header>

        <div className="event-position-modal-body">
          <div className="event-position-status-row">
            <span className={`event-position-status status-${effectiveStatus.toLowerCase() || 'unknown'}`}>{statusLabel}</span>
            <div className="event-position-countdown">
              <span>Trading time remaining</span>
              <EventCountdown cutoff={cutoff} serverOffset={serverOffset} onExpire={() => setCutoffExpired(true)} />
            </div>
          </div>

          {loading && <div className="event-position-loading">Loading current Webull contract facts and chart…</div>}
          {error && <div className="event-position-error">{error}</div>}

          {market && (
            <>
              {isOpenOrder && (
                <div className="event-position-facts-grid event-position-order-summary">
                  <div><span>Open order side</span><strong>{String(record?.side || 'BUY').toUpperCase()}</strong></div>
                  <div><span>Order outcome</span><strong>{positionOutcome.toUpperCase()}</strong></div>
                  <div><span>Order quantity</span><strong>{quantityText(orderQuantity)}</strong></div>
                  <div><span>Filled / remaining</span><strong>{quantityText(orderFilledQuantity)} / {quantityText(orderRemainingQuantity)}</strong></div>
                  <div><span>Order limit</span><strong>{cents(record?.price ?? record?.limit_price)}</strong></div>
                  <div><span>Order status</span><strong>{String(record?.status || 'Working')}</strong></div>
                  <div><span>Available to close</span><strong>{quantityText(availableQuantity)}</strong></div>
                  <div><span>Order submitted</span><strong>{record?.created_at || record?.create_time || record?.placed_time || 'Not provided'}</strong></div>
                </div>
              )}
              <div className="event-position-chart-card">
                <div className="event-position-chart-heading">
                  <div><strong>Yes price history</strong><span>Provider OHLCV · Eastern Time</span></div>
                  <div><span>Buy Yes</span><strong>{cents(market.yes_ask)}</strong><span>Buy No</span><strong>{cents(market.no_ask)}</strong></div>
                </div>
                <div className="event-position-chart">
                  {bars.length ? <Line data={chartData} options={chartOptions} /> : <div className="event-position-chart-empty">{chartMessage || 'No chart history is available for this contract.'}</div>}
                </div>
              </div>

              <div className="event-position-facts-grid">
                <div><span>{isOpenOrder ? 'Order outcome' : 'Held outcome'}</span><strong>{positionOutcome.toUpperCase()}</strong></div>
                <div><span>{isOpenOrder ? 'Live contracts owned' : 'Contracts'}</span><strong>{quantityText(positionQuantity)}</strong></div>
                <div><span>Available to close</span><strong>{quantityText(availableQuantity)}</strong></div>
                <div><span>Average entry</span><strong>{cents(averagePrice)}</strong></div>
                <div><span>Executable bid</span><strong>{cents(executableBid)}</strong></div>
                <div><span>Estimated close value</span><strong>{money(estimatedCloseValue)}</strong></div>
                <div><span>Open P&amp;L at bid</span><strong className={unrealizedPnl > 0 ? 'gain' : unrealizedPnl < 0 ? 'loss' : ''}>{money(unrealizedPnl)}</strong></div>
                <div><span>Winning settlement payout</span><strong>{money(winningPayout)}</strong></div>
                <div><span>Yes bid / ask</span><strong>{cents(market.yes_bid)} / {cents(market.yes_ask)}</strong></div>
                <div><span>No bid / ask</span><strong>{cents(market.no_bid)} / {cents(market.no_ask)}</strong></div>
                <div><span>Volume / open interest</span><strong>{quantityText(market.volume)} / {quantityText(market.open_interest)}</strong></div>
                <div><span>Last trade</span><strong>{market.last_trade_time ? formatEasternDateTime(market.last_trade_time) : '—'}</strong></div>
              </div>

              <div className="event-position-timeline">
                <h3>Timeline and contract facts</h3>
                <div><span>Opens</span><strong>{market.open_date ? formatEasternDateTime(market.open_date) : 'Not provided'}</strong></div>
                <div><span>Trading cutoff</span><strong>{cutoff ? formatEasternDateTime(cutoff.toISOString()) : 'Not provided'}</strong></div>
                <div><span>Expected determination</span><strong>{market.expected_exp_date ? formatEasternDateTime(market.expected_exp_date) : 'Not provided'}</strong></div>
                <div><span>Expected payout</span><strong>{market.payout_date ? formatEasternDateTime(market.payout_date) : 'Not provided'}</strong></div>
                <div><span>Trading hours</span><strong>{rules.trading_hours || market.trading_hours || 'Provider status is authoritative'}</strong></div>
                <div><span>Settlement source</span><strong>{market.settlement_source || 'Not provided by Webull'}</strong></div>
                <div><span>Contract symbol</span><strong>{market.symbol}</strong></div>
              </div>

              <div className="event-position-order-card">
                <h3>{isOpenOrder ? 'Manage this open order' : 'Manage this position'}</h3>
                <div className="event-position-order-actions">
                  {isOpenOrder && (
                    <button
                      type="button"
                      className="cancel-open-order"
                      disabled={cancellingOrderId === record.id}
                      onClick={() => onCancelOrder?.(record)}
                    >
                      {cancellingOrderId === record.id ? 'Cancelling...' : 'Cancel Open Order'}
                    </button>
                  )}
                  <button type="button" className={side === 'BUY' && outcome === 'yes' ? 'active yes' : ''} disabled={effectiveStatus !== 'OC'} onClick={() => chooseOrder('BUY', 'yes')}>Buy Yes {cents(market.yes_ask)}</button>
                  <button type="button" className={side === 'BUY' && outcome === 'no' ? 'active no' : ''} disabled={effectiveStatus !== 'OC'} onClick={() => chooseOrder('BUY', 'no')}>Buy No {cents(market.no_ask)}</button>
                  <button type="button" className={side === 'SELL' ? 'active close-position' : ''} disabled={!['OC', 'CO'].includes(effectiveStatus) || availableQuantity <= 0} onClick={() => chooseOrder('SELL', positionOutcome)}>Close {positionOutcome.toUpperCase()} Position {cents(executableBid)}</button>
                </div>
                <div className="event-position-order-fields">
                  <label>Contracts<input type="number" min="0" step={rules.fractionable ? '0.00001' : '1'} value={quantity} onChange={(event) => { setQuantity(event.target.value); setValidationError(''); }} /></label>
                  <label>Limit price (USD)<input type="number" min="0" max="1" step="0.0001" value={price} onChange={(event) => { setPrice(event.target.value); setValidationError(''); }} /></label>
                  <div><span>Current executable quote</span><strong>{cents(selectedQuote)}</strong></div>
                </div>
                {validationError && <p className="event-position-validation" role="alert">{validationError}</p>}
                <div className="event-position-order-footer">
                  <small>Limit / Day only. Live orders continue through the normal Webull confirmation and security checks.</small>
                  <button type="button" className="event-position-review" disabled={loading || !market || (side === 'BUY' ? effectiveStatus !== 'OC' : !['OC', 'CO'].includes(effectiveStatus))} onClick={reviewOrder}>
                    Review {side === 'SELL' ? 'Close Position' : `Buy ${outcome.toUpperCase()}`} Order
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
