import React, { useEffect, useMemo, useState, useRef } from 'react';
import axios from 'axios';
import CryptoIcon, { WebullLogo } from '../components/CryptoIcon';
import { FaToggleOn, FaToggleOff } from 'react-icons/fa';
import WebullTradingViewChart, { DEFAULT_STOCKS } from '../components/WebullTradingViewChart';
import WebullTradeTimelineChart from '../components/WebullTradeTimelineChart';
import TwoFactorModal from '../components/TwoFactorModal';
import CancelOrderModal from '../components/CancelOrderModal';
import PercentPriceModal from '../components/PercentPriceModal';
import WebullAIDashboard from '../components/WebullAIDashboard';
import WebullOptionChain from '../components/WebullOptionChain';
import OptionsPayoffChart from '../components/OptionsPayoffChart';
import { differenceInEasternCalendarDays, formatEasternDate, formatEasternDateTime, formatEasternTime } from '../utils/dateTime';
import { optionStrategyDefinition } from '../utils/optionStrategies';
import {
  formatComboRole,
  formatOrderSide,
  formatOrderStatus,
  formatOrderType,
  formatTimeInForce,
} from '../utils/orderDisplay';
import './Trading.css';

const OPEN_STATUSES = new Set(['OPEN', 'NEW', 'WORKING', 'PENDING', 'PARTIALLY_FILLED', 'PARTIALLY FILLED']);
const PAGE_SIZES = [20, 50, 100, 200];
const orderTypeLabel = (value) => formatOrderType(value, 'Order');
const orderIsPaper = (order) => Boolean(
  order?.is_paper
  || String(order?.account_id || '') === 'TEST_PAPER_ACCOUNT'
  || String(order?.id || order?.order_id || '').startsWith('SIM_')
);

const number = (value, digits = 2) => {
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
    : '—';
};

const eventMoney = (value) => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '—';
  const digits = Math.abs(parsed * 100 - Math.round(parsed * 100)) > 1e-8 ? 4 : 2;
  return `$${parsed.toFixed(digits)}`;
};

const eventPriceRangeLabel = (ranges = []) => ranges.length
  ? ranges.map((range) => `${eventMoney(range.start)}–${eventMoney(range.end)} (tick ${eventMoney(range.step)})`).join(', ')
  : 'Unavailable';

const eventConditionLabel = (market) => {
  const condition = String(market?.display_condition || market?.yes_condition || '').trim();
  if (!condition) return 'Condition details unavailable';
  return /^(yes\b|threshold:)/i.test(condition) ? condition : `YES if ${condition}`;
};

const eventPriceMatchesRanges = (price, ranges = []) => {
  const numericPrice = Number(price);
  if (!Number.isFinite(numericPrice)) return false;
  return ranges.some((range) => {
    const start = Number(range.start);
    const end = Number(range.end);
    const step = Number(range.step);
    if (![start, end, step].every(Number.isFinite) || step <= 0 || numericPrice < start || numericPrice > end) return false;
    const ticks = (numericPrice - start) / step;
    return Math.abs(ticks - Math.round(ticks)) <= 1e-6;
  });
};

const formatDate = formatEasternDateTime;

const optionLegsFromRecord = (record = {}) => {
  if (Array.isArray(record.legs)) return record.legs;
  if (Array.isArray(record.option_legs)) return record.option_legs;
  if (Array.isArray(record.combo_orders)) return record.combo_orders;
  if (typeof record.combo_orders === 'string' && record.combo_orders.trim()) {
    try {
      const parsed = JSON.parse(record.combo_orders);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
};

const optionContractDetails = (record = {}) => {
  const rawSymbol = String(record.symbol || record.ticker || '').trim().toUpperCase();
  const parsed = rawSymbol.match(/^([A-Z][A-Z0-9.]*)\s+(\d{4}-\d{2}-\d{2})\s+\$?([\d.]+)\s+(CALL|PUT)$/);
  const optionLegs = optionLegsFromRecord(record).filter((leg) => String(leg.instrument_type || 'OPTION').toUpperCase() === 'OPTION');
  const unique = (values) => [...new Set(values.filter((value) => value !== undefined && value !== null && String(value).trim() !== '').map(String))];
  const expirations = unique(optionLegs.map((leg) => leg.option_expire_date || leg.option_expiration || leg.expiration_date));
  const strikes = unique(optionLegs.map((leg) => leg.strike_price ?? leg.option_strike));
  const optionTypes = unique(optionLegs.map((leg) => String(leg.option_type || '').toUpperCase()));
  const isOption = String(record.instrument_type || '').toUpperCase() === 'OPTION' || Boolean(parsed) || optionLegs.length > 0;
  const strike = record.option_strike ?? record.strike_price ?? parsed?.[3] ?? null;
  return {
    isOption,
    symbol: String(record.underlying_symbol || parsed?.[1] || rawSymbol || '—').toUpperCase(),
    expiration: expirations.length ? expirations.join(' / ') : String(record.option_expiration || record.option_expire_date || record.expiration_date || parsed?.[2] || '').slice(0, 10),
    strike,
    strikeLabel: strikes.length ? strikes.map((value) => `$${number(value, 2)}`).join(' / ') : strike != null ? `$${number(strike, 2)}` : '—',
    optionType: optionTypes.length ? optionTypes.join(' / ') : String(record.option_type || parsed?.[4] || '').toUpperCase(),
  };
};

const normalizeOrder = (order) => ({
  ...order,
  id: order.id || order.order_id || order.orderId || `${order.symbol}-${order.created_at || order.create_time || ''}`,
  symbol: String(order.symbol || order.ticker || '—').toUpperCase(),
  side: order.side || '—',
  order_type: order.order_type || order.type || '—',
  quantity: order.quantity ?? order.total_quantity ?? order.order_quantity,
  filled_quantity: order.filled_quantity ?? order.executed_quantity ?? order.filled_qty,
  price: order.price ?? order.limit_price ?? order.order_price,
  status: order.status || order.order_status || '—',
  created_at: order.created_at || order.create_time || order.placed_time || order.place_time || order.filled_time_at || order.update_time,
});

function Pagination({ page, setPage, pageSize, setPageSize, total }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="order-history-pagination">
      <div className="order-history-pagination-info">
        Showing {total ? (page - 1) * pageSize + 1 : 0}–{Math.min(page * pageSize, total)} of {total} orders
      </div>
      <div className="order-history-pagination-controls">
        <label className="order-page-size-label">
          Rows{' '}
          <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }}>
            {PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}
          </select>
        </label>
        <button type="button" className="pagination-btn" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={page === 1}>
          ‹ Prev
        </button>
        <span className="order-page-indicator">Page {page} of {pages}</span>
        <button type="button" className="pagination-btn" onClick={() => setPage((current) => Math.min(pages, current + 1))} disabled={page === pages}>
          Next ›
        </button>
      </div>
    </div>
  );
}

function WebullOrderTable({ orders, emptyText, onCancelOrder, cancellingId, optionClosePnlByOrder = null }) {
  if (!orders.length) return <div className="empty-state"><p>{emptyText}</p></div>;
  const showOptionColumns = orders.some((order) => optionContractDetails(order).isOption);
  const showClosePnlColumn = showOptionColumns && optionClosePnlByOrder !== null;
  return (
    <div className="table-container trading-table">
      <div className="order-table-scroll">
        <table>
          <thead>
            <tr>
              <th>Date</th><th>Time (ET)</th><th style={{ textAlign: 'center' }}>Symbol</th>
              {showOptionColumns && <><th>Expiration</th><th>Strike</th><th>Call / Put</th></>}
              <th>Side</th><th>Type</th><th>Quantity</th><th>Price</th><th>Filled</th>
              {showClosePnlColumn && <th title="Estimated before fees from the filled basis and current executable close quote.">Close-Now P&amp;L</th>}
              <th>Status</th><th>Source</th>
              {onCancelOrder && <th>Action</th>}
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => {
              const option = optionContractDetails(order);
              const closePnl = optionClosePnlByOrder?.[order.id];
              return <tr key={order.id}>
                <td>{formatEasternDate(order.created_at)}</td>
                <td>{formatEasternTime(order.created_at)}</td>
                <td style={{ textAlign: 'center' }}>{option.symbol}</td>
                {showOptionColumns && <>
                  <td>{option.isOption ? option.expiration || '—' : '—'}</td>
                  <td>{option.isOption ? option.strikeLabel : '—'}</td>
                  <td>{option.isOption ? formatOrderType(option.optionType, option.optionType || '—') : '—'}</td>
                </>}
                <td>{formatOrderSide(order.side)}</td>
                <td>{formatOrderType(order.order_type)}</td>
                <td>{number(order.quantity, 6)}</td>
                <td>{order.price ? `$${number(order.price, 4)}` : 'Market'}</td>
                <td>{number(order.filled_quantity, 6)}</td>
                {showClosePnlColumn && (
                  <td>
                    {!option.isOption ? '—' : closePnl?.status === 'loading' ? (
                      <span className="option-close-pnl-muted">Refreshing…</span>
                    ) : closePnl?.status === 'not_filled' ? (
                      <span className="option-close-pnl-muted" title="P&amp;L requires an actual fill price and filled quantity.">Not filled</span>
                    ) : closePnl?.status === 'available' ? (
                      <span className={closePnl.pnl >= 0 ? 'option-close-pnl-positive' : 'option-close-pnl-negative'}>
                        {closePnl.pnl >= 0 ? '+' : '-'}${number(Math.abs(closePnl.pnl), 2)}
                        <small>@ {closePnl.closeSide} ${number(closePnl.closePrice, 4)}</small>
                      </span>
                    ) : (
                      <span className="option-close-pnl-muted" title={closePnl?.message || 'A current executable quote is unavailable.'}>Unavailable</span>
                    )}
                  </td>
                )}
                <td>{formatOrderStatus(order.status)}</td>
                <td><span className="badge" style={{ background: 'rgba(96, 165, 250, .16)', color: '#60a5fa' }}>Webull</span></td>
                {onCancelOrder && (
                  <td>
                    <button
                      type="button"
                      className="btn btn-sm btn-danger"
                      style={{ padding: '3px 8px', fontSize: '11px', backgroundColor: '#ef4444', borderColor: '#ef4444', color: '#fff', borderRadius: '4px', cursor: 'pointer' }}
                      disabled={cancellingId === order.id}
                      onClick={() => onCancelOrder(order)}
                    >
                      {cancellingId === order.id ? 'Cancelling...' : 'Cancel'}
                    </button>
                  </td>
                )}
              </tr>;
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const isCryptoAccount = (acc) => {
  if (!acc) return false;
  const identity = [
    acc.account_class,
    acc.account_type,
    acc.account_sub_type,
    acc.account_label,
    acc.account_name,
  ].filter(Boolean).join(' ').toLowerCase();
  return identity.includes('crypto');
};

const isIndividualCashAccount = (acc) => {
  if (!acc || isCryptoAccount(acc)) return false;
  const identity = [
    acc.account_class,
    acc.account_type,
    acc.account_label,
    acc.account_name,
  ].filter(Boolean).join(' ').toLowerCase();
  return identity.includes('individual') && identity.includes('cash');
};

const preferredEquityAccount = (accounts) => (
  accounts.find(isIndividualCashAccount)
  || accounts.find((account) => !isCryptoAccount(account))
  || null
);

const holdingMatchesSymbol = (holding, symbol) => {
  const holdingSymbol = String(holding?.symbol || '').toUpperCase();
  const holdingUnderlying = String(holding?.underlying_symbol || '').toUpperCase();
  const cleanSymbol = String(symbol || '').toUpperCase();
  return holdingSymbol === cleanSymbol
    || holdingUnderlying === cleanSymbol
    || holdingSymbol.replace(/\s+(YES|NO)$/, '') === cleanSymbol
    || holdingSymbol === cleanSymbol.replace(/USD$/, '');
};

const holdingForAccount = (holdings, symbol, accountId) => (
  holdings.find((holding) => String(holding?.account_id || '') === String(accountId || '') && holdingMatchesSymbol(holding, symbol))
);

const normalizedWebullInstrumentType = (value) => {
  const type = String(value || '').trim().toUpperCase();
  if (['CRYPTO', 'COIN', 'TOKEN'].includes(type)) return 'CRYPTO';
  if (['OPTION', 'OPTIONS'].includes(type)) return 'OPTION';
  if (['FUTURE', 'FUTURES'].includes(type)) return 'FUTURES';
  if (['EVENT', 'EVENT_CONTRACT'].includes(type)) return 'EVENT';
  return 'EQUITY';
};

const QUANTITY_EPSILON = 1e-8;
const OPTION_CONTRACT_MULTIPLIER = 100;
const OPTION_STRIKE_EPSILON = 0.0001;

const formatQuantityForTicket = (value, precision = 6) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return '';
  return numeric.toFixed(precision).replace(/\.?0+$/, '');
};

const isFractionalQuantity = (value) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) && Math.abs(numeric - Math.round(numeric)) > QUANTITY_EPSILON;
};

const nonNegativeNumber = (value) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric >= 0 ? numeric : 0;
};

const optionOrderValue = (quantity, premium) => {
  const total = nonNegativeNumber(quantity) * nonNegativeNumber(premium) * OPTION_CONTRACT_MULTIPLIER;
  return Number.isFinite(total) ? total : 0;
};

const optionOrderValueText = (quantity, premium) => optionOrderValue(quantity, premium).toFixed(2);

const normalizedOptionExpiry = (value) => String(value || '').trim().slice(0, 10);

const holdingMatchesOptionContract = (holding, { accountId, underlyingSymbol, optionType, optionStrike, optionExpiration }) => {
  if (String(holding?.instrument_type || '').trim().toUpperCase() !== 'OPTION') return false;
  if (String(holding?.account_id || '') !== String(accountId || '')) return false;
  if (String(holding?.underlying_symbol || holding?.symbol || '').trim().toUpperCase() !== String(underlyingSymbol || '').trim().toUpperCase()) return false;
  if (String(holding?.option_type || '').trim().toUpperCase() !== String(optionType || '').trim().toUpperCase()) return false;
  if (normalizedOptionExpiry(holding?.option_expiration) !== normalizedOptionExpiry(optionExpiration)) return false;
  const holdingStrike = Number(holding?.option_strike);
  const selectedStrike = Number(optionStrike);
  return Number.isFinite(holdingStrike)
    && Number.isFinite(selectedStrike)
    && Math.abs(holdingStrike - selectedStrike) <= OPTION_STRIKE_EPSILON;
};

export default function WebullTrading({ isLightMode = false }) {
  const [activeTab, setActiveTab] = useState('order');
  const [holdings, setHoldings] = useState([]);
  const [history, setHistory] = useState([]);
  const [openOrders, setOpenOrders] = useState([]);
  const [optionClosePnlByOrder, setOptionClosePnlByOrder] = useState({});
  const [accounts, setAccounts] = useState([]);
  const [selectedAccountId, setSelectedAccountId] = useState('');
  const [defaultAccountId, setDefaultAccountId] = useState('');
  const [savingDefaultAccount, setSavingDefaultAccount] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [cancellingOrderId, setCancellingOrderId] = useState(null);
  const [cancelModal, setCancelModal] = useState({ isVisible: false, order: null, error: '', loading: false });

  // Webull Test Mode (Paper Trading) state
  const [isTestMode, setIsTestMode] = useState(false);
  const modeHoldings = useMemo(
    () => holdings.filter((holding) => orderIsPaper(holding) === isTestMode),
    [holdings, isTestMode]
  );
  const [paperSummary, setPaperSummary] = useState(null);
  const [showDepositModal, setShowDepositModal] = useState(false);
  const [depositAmount, setDepositAmount] = useState('1000');
  const [depositSubmitting, setDepositSubmitting] = useState(false);
  const orderTicketRef = useRef(null);
  const [ticketFlash, setTicketFlash] = useState(false);

  // Selected Instrument & Chart state
  const [selectedSymbol, setSelectedSymbol] = useState('AAPL');
  const [selectedInstrumentType, setSelectedInstrumentType] = useState('EQUITY');
  const [selectedSecurityType, setSelectedSecurityType] = useState('EQUITY');
  const assetSymbolMemoryRef = useRef({
    EQUITY: 'AAPL',
    OPTION: 'AAPL',
    CRYPTO: 'BTCUSD',
    FUTURES: '',
    EVENT: '',
  });
  const [selectedOptionHoldingId, setSelectedOptionHoldingId] = useState('');
  const [futuresCatalog, setFuturesCatalog] = useState({ classes: [], products: [] });
  const [futuresContracts, setFuturesContracts] = useState([]);
  const [futuresContractInput, setFuturesContractInput] = useState('');
  const [selectedFuturesContract, setSelectedFuturesContract] = useState(null);
  const [futuresLoading, setFuturesLoading] = useState(false);
  const [futuresMessage, setFuturesMessage] = useState('');
  const [livePrice, setLivePrice] = useState(0);
  const [optionUnderlyingPrice, setOptionUnderlyingPrice] = useState(0);
  const [chartStrikeRequest, setChartStrikeRequest] = useState(null);

  // Event Contracts State (Binary Outcome Contracts)
  const [eventCategories, setEventCategories] = useState([]);
  const [selectedEventCategory, setSelectedEventCategory] = useState('');
  const [eventMarkets, setEventMarkets] = useState([]);
  const [selectedEventMarket, setSelectedEventMarket] = useState(null);
  const [eventMarketQuery, setEventMarketQuery] = useState('');
  const [eventMarketMenuOpen, setEventMarketMenuOpen] = useState(false);
  const [eventTotalMatches, setEventTotalMatches] = useState(0);
  const [eventLoading, setEventLoading] = useState(false);
  const [eventCatalogLoading, setEventCatalogLoading] = useState(false);
  const [eventMessage, setEventMessage] = useState('');
  const eventMarketRequestRef = useRef(0);
  const eventMarketSelectorRef = useRef(null);
  const eventAutoPriceRef = useRef(true);

  // Helper to detect cash-based Webull accounts (Individual Cash, Roth IRA, Rollover IRA)
  const isCashBasedAccount = (account) => {
    if (!account) return false;
    const label = `${account.account_label || ''} ${account.account_name || ''} ${account.account_type || ''} ${account.account_class || ''}`.toLowerCase();
    if (label.includes('crypto')) return false;
    return (
      label.includes('cash') ||
      label.includes('ira') ||
      label.includes('roth') ||
      label.includes('rollover')
    );
  };

  // Determine smart default trading session based on US Eastern time (ET)
  const getDefaultTradingSession = () => {
    try {
      const now = new Date();
      const etString = now.toLocaleString('en-US', { timeZone: 'America/New_York' });
      const etDate = new Date(etString);
      const day = etDate.getDay(); // 0 = Sun, 1 = Mon, ..., 6 = Sat
      const hour = etDate.getHours();
      const minute = etDate.getMinutes();
      const timeInMinutes = hour * 60 + minute;

      // Webull regular market hours: 9:30 AM to 4:00 PM Eastern, Monday - Friday
      const isWeekday = day >= 1 && day <= 5;
      const isMarketOpen = isWeekday && timeInMinutes >= (9 * 60 + 30) && timeInMinutes < (16 * 60);
      // After-hours: 4:00 PM to 8:00 PM Eastern, Monday - Friday
      const isAfterHours = isWeekday && timeInMinutes >= (16 * 60) && timeInMinutes < (20 * 60);
      // Pre-market: 4:00 AM to 9:30 AM Eastern, Monday - Friday
      const isPreMarket = isWeekday && timeInMinutes >= (4 * 60) && timeInMinutes < (9 * 60 + 30);

      if (isMarketOpen) {
        return 'CORE'; // Only Regular Hours
      }
      if (isAfterHours || isPreMarket) {
        return 'ALL'; // Including Extended Hours
      }
      // Overnight: 8:00 PM to 4:00 AM Eastern or weekends
      return 'NIGHT'; // Overnight Hours Only
    } catch (e) {
      return 'CORE';
    }
  };

  // Order Placement Form State (mirroring Binance.US Trading)
  const [orderForm, setOrderForm] = useState({
    side: 'BUY',
    type: 'LIMIT',
    quantity: '',
    quoteQuantity: '',
    price: '',
    stopPrice: '',
    timeInForce: 'DAY',
    tradingSession: getDefaultTradingSession(),
    optionType: 'CALL',
    optionStrike: '',
    optionExpiration: '',
    optionStrategy: 'SINGLE',
    optionStrategyWidth: 'auto',
    optionStrategyLegs: [],
    trailingType: 'AMOUNT',
    trailingStopStep: '',
    // Webull Stock Orders API extensions
    entrustType: 'QTY', // 'QTY' | 'AMOUNT'
    totalCashAmount: '',
    isAlgoEnabled: false,
    algoType: 'TWAP', // 'TWAP' | 'VWAP' | 'POV'
    algoStartTime: '10:00:00',
    algoEndTime: '15:30:00',
    maxTargetPercent: '10',
    targetVolPercent: '10',
    isBracketEnabled: false,
    bracketTakeProfitPrice: '',
    bracketStopLossPrice: '',
    bracketStopLossLimitPrice: '',
    // Event Contracts extension
    eventOutcome: 'yes', // 'yes' | 'no'
  });

  // Combo Orders Form State (OTO / OCO / OTOCO)
  const [comboForm, setComboForm] = useState({
    comboType: 'OTOCO',
    symbol: 'AAPL',
    legs: [
      { id: '1', role: 'MASTER', side: 'BUY', order_type: 'LIMIT', price: '', stopPrice: '', quantity: '1', timeInForce: 'DAY', session: 'CORE' },
      { id: '2', role: 'OTOCO', side: 'SELL', order_type: 'LIMIT', price: '', stopPrice: '', quantity: '1', timeInForce: 'DAY', session: 'CORE' },
      { id: '3', role: 'OTOCO', side: 'SELL', order_type: 'STOP_LOSS', price: '', stopPrice: '', quantity: '1', timeInForce: 'DAY', session: 'CORE' },
    ],
  });

  const availableOrderTypes = useMemo(() => {
    const commonLimit = { value: 'LIMIT', label: 'Limit', description: 'Execute at the specified limit price or better' };
    const stopLoss = { value: 'STOP_LOSS', label: 'Stop Loss', description: 'Trigger a market order when the stop price is reached' };
    const stopLossLimit = { value: 'STOP_LOSS_LIMIT', label: 'Stop Loss Limit', description: 'Trigger a limit order when the stop price is reached' };
    // Event Contracts support strictly LIMIT orders only per Webull API docs
    if (selectedInstrumentType === 'EVENT') {
      return [commonLimit];
    }
    // A buy stop-loss becomes an unbounded market order at the trigger, so it
    // cannot satisfy the ticket's cash-coverage guarantee. Buy options use a
    // limit (or stop-limit) with a defined maximum premium instead.
    if (selectedInstrumentType === 'OPTION') {
      return orderForm.side === 'BUY' ? [commonLimit, stopLossLimit] : [commonLimit, stopLoss, stopLossLimit];
    }
    if (selectedInstrumentType === 'CRYPTO') {
      return [
        { value: 'MARKET', label: 'Market', description: 'Execute immediately at the best available price' },
        commonLimit,
        stopLossLimit,
      ];
    }
    if (selectedInstrumentType === 'FUTURES') {
      return [
        { value: 'MARKET', label: 'Market', description: 'Execute immediately at the best available price' },
        commonLimit,
        stopLoss,
        stopLossLimit,
        { value: 'TRAILING_STOP_LOSS', label: 'Trailing Stop', description: 'Trail the market by a dollar amount or percentage' },
      ];
    }
    // Stock / Equity orders support all Webull Stock API types
    return [
      commonLimit,
      { value: 'MARKET', label: 'Market', description: 'Execute immediately at the best available price' },
      stopLoss,
      stopLossLimit,
      { value: 'TRAILING_STOP_LOSS', label: 'Trailing Stop', description: 'Stop price trails the market price by a set amount or percentage (DAY only)' },
      { value: 'MARKET_ON_OPEN', label: formatOrderType('MARKET_ON_OPEN'), description: 'Execute at the opening auction price' },
      { value: 'MARKET_ON_CLOSE', label: formatOrderType('MARKET_ON_CLOSE'), description: 'Execute at the closing auction price' },
      { value: 'LIMIT_ON_OPEN', label: formatOrderType('LIMIT_ON_OPEN'), description: 'Limit order executed at the market-open auction' },
    ];
  }, [selectedInstrumentType, orderForm.side]);

  // Reset to LIMIT if current type is unsupported for current asset class
  useEffect(() => {
    if (!availableOrderTypes.some((t) => t.value === orderForm.type)) {
      setOrderForm((prev) => ({ ...prev, type: 'LIMIT', stopPrice: '' }));
    }
  }, [availableOrderTypes, orderForm.type]);

  useEffect(() => {
    if (selectedInstrumentType === 'EVENT' && orderForm.timeInForce !== 'DAY') {
      setOrderForm((prev) => ({ ...prev, timeInForce: 'DAY' }));
    } else if (selectedInstrumentType === 'OPTION' && orderForm.side === 'SELL' && orderForm.timeInForce !== 'DAY') {
      setOrderForm((prev) => ({ ...prev, timeInForce: 'DAY' }));
    } else if (selectedInstrumentType !== 'CRYPTO' && orderForm.timeInForce === 'IOC') {
      setOrderForm((prev) => ({ ...prev, timeInForce: 'DAY' }));
    } else if (['TRAILING_STOP_LOSS', 'MARKET_ON_OPEN', 'MARKET_ON_CLOSE', 'LIMIT_ON_OPEN'].includes(orderForm.type) && orderForm.timeInForce !== 'DAY') {
      setOrderForm((prev) => ({ ...prev, timeInForce: 'DAY' }));
    }
  }, [selectedInstrumentType, orderForm.side, orderForm.timeInForce, orderForm.type]);
  const [balancePercentage, setBalancePercentage] = useState(0);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [orderSubmitting, setOrderSubmitting] = useState(false);
  const [orderFeedback, setOrderFeedback] = useState({ type: '', message: '' });
  const [orderValidationError, setOrderValidationError] = useState('');

  // Percent Price Calculator Modal State
  const [percentModal, setPercentModal] = useState({
    isOpen: false,
    targetField: 'price'
  });

  const userChangedSessionRef = React.useRef(false);

  const handleOpenPercentModal = (targetField = 'price') => {
    setPercentModal({
      isOpen: true,
      targetField
    });
  };

  const handleApplyPercentPrices = ({ price, stopPrice }) => {
    setOrderForm((prev) => {
      const next = { ...prev };
      if (price !== undefined && price !== '') {
        next.price = price;
      }
      if (stopPrice !== undefined && stopPrice !== '') {
        next.stopPrice = stopPrice;
      }
      return next;
    });
    setOrderValidationError('');
  };

  // 2FA State
  const [require2fa, setRequire2fa] = useState(false);
  const [twoFactorModal, setTwoFactorModal] = useState({ isVisible: false, orderData: null });

  // History & Signal State
  const [historyPage, setHistoryPage] = useState(1);
  const [historyPageSize, setHistoryPageSize] = useState(50);
  const [signals, setSignals] = useState([]);
  const [signalSettings, setSignalSettings] = useState({
    webull_ai_scheduling_enabled: false,
    webull_crypto_sentiment_frequency_hours: 24,
    webull_equity_sentiment_frequency_hours: 24,
    webull_crypto_sentiment_horizon_hours: 24,
    webull_equity_sentiment_horizon_hours: 24,
  });
  const [selectedSignalHolding, setSelectedSignalHolding] = useState('');
  const [signalBusy, setSignalBusy] = useState(false);
  const [signalMessage, setSignalMessage] = useState('');

  const [historyLoading, setHistoryLoading] = useState(false);

  const loadHistory = async (targetAccId, paperMode = isTestMode) => {
    if (paperMode) {
      setHistoryLoading(true);
      try {
        const resp = await axios.get('/api/webull/test/orders', { withCredentials: true });
        setHistory((resp.data?.orders || []).map(normalizeOrder));
      } catch (e) {
        // non-blocking
      } finally {
        setHistoryLoading(false);
      }
      return;
    }
    const accId = targetAccId || selectedAccountId;
    setHistoryLoading(true);
    try {
      const resp = await axios.get(
        `/api/trading/real-orders?account_scope=webull&history_source=database&limit=100${accId ? `&account_id=${accId}` : ''}`,
        { withCredentials: true }
      );
      // account_scope=webull + history_source=database already scopes results to
      // Webull-sourced persisted rows; no additional client-side filter needed.
      setHistory((resp.data?.orders || []).map(normalizeOrder));
    } catch (e) {
      // non-blocking
    } finally {
      setHistoryLoading(false);
    }
  };

  const loadOpenOrders = async (targetAccId, paperMode = isTestMode) => {
    if (paperMode) {
      try {
        const res = await axios.get('/api/webull/test/orders', { withCredentials: true });
        const working = (res.data?.orders || []).filter((o) => o.status === 'Working' || o.status === 'Open').map(normalizeOrder);
        setOpenOrders(working);
      } catch (e) {
        // non-blocking
      }
      return;
    }
    const accId = targetAccId || selectedAccountId;
    try {
      const res = await axios.get(
        `/api/webull/open-orders${accId ? `?account_id=${accId}` : ''}`,
        { withCredentials: true }
      );
      setOpenOrders((res.data?.orders || []).map(normalizeOrder));
      if (res.data?.success === false) {
        setError(res.data?.message || 'Unable to load Webull open orders.');
      }
    } catch (e) {
      setError(e.response?.data?.message || 'Unable to load Webull open orders.');
    }
  };

  const loadPaperTradingData = async () => {
    try {
      const [sumRes, posRes, ordRes] = await Promise.all([
        axios.get('/api/webull/test/account-summary', { withCredentials: true }),
        axios.get('/api/webull/test/positions', { withCredentials: true }),
        axios.get('/api/webull/test/orders', { withCredentials: true }),
      ]);
      if (sumRes.data?.success) {
        setPaperSummary(sumRes.data.summary);
      }
      if (posRes.data?.success) {
        setHoldings(posRes.data.positions || []);
      }
      if (ordRes.data?.success) {
        setHistory((ordRes.data.orders || []).map(normalizeOrder));
        const working = (ordRes.data.orders || []).filter((o) => o.status === 'Working' || o.status === 'Open').map(normalizeOrder);
        setOpenOrders(working);
      }
    } catch (e) {
      console.error('Failed to load paper trading data:', e);
    }
  };

  const handleToggleTestMode = async (enabled) => {
    try {
      await axios.post('/api/webull/test/toggle', { enabled }, { withCredentials: true });
      setIsTestMode(enabled);
      setHoldings([]);
      setHistory([]);
      setOpenOrders([]);
      if (enabled) {
        setSelectedAccountId('TEST_PAPER_ACCOUNT');
        await loadPaperTradingData();
        setOrderFeedback({ type: 'success', message: 'Switched to Webull Test Mode (Paper Trading with live real pricing).' });
      } else {
        setPaperSummary(null);
        await load(false);
        setOrderFeedback({ type: 'success', message: 'Switched to Webull Live Trading Mode.' });
      }
    } catch (err) {
      console.error('Failed to toggle test mode:', err);
      setOrderFeedback({ type: 'error', message: 'Failed to update test mode setting.' });
    }
  };

  const handleDepositFakeMoney = async () => {
    const amt = parseFloat(depositAmount);
    if (!amt || amt <= 0) return;
    setDepositSubmitting(true);
    try {
      const res = await axios.post('/api/webull/test/deposit', { amount: amt, reset: false }, { withCredentials: true });
      if (res.data?.success) {
        setShowDepositModal(false);
        setDepositAmount('1000');
        await loadPaperTradingData();
        setOrderFeedback({ type: 'success', message: res.data.message || `Deposited $${amt.toLocaleString()} fake money!` });
      }
    } catch (err) {
      setOrderFeedback({ type: 'error', message: err.response?.data?.message || 'Deposit failed.' });
    } finally {
      setDepositSubmitting(false);
    }
  };

  const handleResetPaperAccount = async () => {
    if (!window.confirm('Reset your Webull Paper Trading account to $0.00, clear all simulated positions, and cancel every active simulated order?')) return;
    setDepositSubmitting(true);
    try {
      const res = await axios.post('/api/webull/test/deposit', { amount: 0, reset: true }, { withCredentials: true });
      if (res.data?.success) {
        setShowDepositModal(false);
        await loadPaperTradingData();
        setOrderFeedback({ type: 'success', message: res.data?.message || 'Webull paper account reset to $0.00; positions cleared and active simulated orders cancelled.' });
      }
    } catch (err) {
      setOrderFeedback({ type: 'error', message: err.response?.data?.message || 'Reset failed.' });
    } finally {
      setDepositSubmitting(false);
    }
  };

  const load = async (forcedTestMode = null) => {
    setLoading(true); setError('');
    try {
      // 1. Fetch lightweight core data needed for trading UI (accounts & portfolio holdings & 2FA setting)
      const [portfolioResponse, accRes, signalSettingsResponse, tradingSettingsRes, testStatusRes] = await Promise.all([
        axios.get('/api/coin-data-live', { withCredentials: true }),
        axios.get('/api/webull/accounts', { withCredentials: true }),
        axios.get('/api/webull/ai-settings', { withCredentials: true }),
        axios.get('/api/trading/settings', { withCredentials: true }).catch(() => ({ data: {} })),
        axios.get('/api/webull/test/status', { withCredentials: true }).catch(() => ({ data: {} })),
      ]);
      const testModeActive = forcedTestMode == null
        ? Boolean(testStatusRes?.data?.enabled)
        : Boolean(forcedTestMode);
      setIsTestMode(testModeActive);
      if (tradingSettingsRes.data?.settings?.require_2fa) {
        setRequire2fa(true);
      }
      const importedHoldings = (portfolioResponse.data?.portfolio || []).filter(
        (item) => item?.is_external || item?.source === 'webull'
      );
      setSignalSettings((current) => ({ ...current, ...(signalSettingsResponse.data?.settings || {}) }));

      const discoveredAccounts = accRes.data?.accounts || [];
      const enabledIds = accRes.data?.enabled_account_ids;
      const filteredAccounts = (enabledIds && enabledIds.length > 0)
        ? discoveredAccounts.filter((a) => enabledIds.includes(a.account_id))
        : discoveredAccounts.filter((a) => a.is_enabled !== false);
      setAccounts(filteredAccounts);
      const savedDefaultAccountId = String(accRes.data?.default_account_id || '');
      setDefaultAccountId(savedDefaultAccountId);

      if (testModeActive) {
        setSelectedAccountId('TEST_PAPER_ACCOUNT');
        await loadPaperTradingData();
        setLoading(false);
        axios.get('/api/webull/ai-signals?limit=50', { withCredentials: true })
          .then((res) => setSignals(res.data?.signals || []))
          .catch(() => {});
        return;
      }

      setHoldings(importedHoldings);

      const urlParams = new URLSearchParams(window.location.search);
      const urlSymbol = urlParams.get('symbol')?.toUpperCase()?.trim();
      const urlSide = urlParams.get('side')?.toUpperCase()?.trim();
      const urlAccountId = urlParams.get('account_id')?.trim();
      const urlInstrumentType = urlParams.get('instrument_type')?.toUpperCase()?.trim();
      const urlAccountPreference = urlParams.get('account_preference')?.toLowerCase()?.trim();
      const requestedInstrumentType = ['CRYPTO', 'EQUITY', 'OPTION', 'FUTURES', 'EVENT'].includes(urlInstrumentType) ? urlInstrumentType : null;
      const urlHoldingId = urlParams.get('holding_id')?.trim();
      const deepLinkedHolding = urlHoldingId
        ? importedHoldings.find((holding) => String(holding?.id || '') === urlHoldingId)
        : null;

      // Determine which account should be active on load:
      // 1. If an explicit account_id is in the URL, select that account.
      // 2. Otherwise if a symbol was provided, infer account by asset class.
      // 3. Otherwise use the user's saved default, then prefer an equity/cash
      //    account so a new user does not unexpectedly land in crypto.
      let activeAcc = null;

      if (urlAccountId) {
        // Priority 1: explicit account_id from navigation
        activeAcc = filteredAccounts.find((a) => a.account_id === urlAccountId) || null;
      }

      // A portfolio row can identify a precise option contract.  Prefer that
      // ownership/account context over a same-symbol lookup so an option is
      // never coerced into its underlying equity ticket.
      if (!activeAcc && deepLinkedHolding?.account_id) {
        activeAcc = filteredAccounts.find((a) => a.account_id === deepLinkedHolding.account_id) || null;
      }

      // Stock-mover navigation explicitly targets the user's individual cash
      // account, rather than whichever Webull account happened to be selected
      // in a prior session.
      if (!activeAcc && requestedInstrumentType === 'EQUITY' && urlAccountPreference === 'individual_cash') {
        activeAcc = preferredEquityAccount(filteredAccounts);
      }

      if (!activeAcc && urlSymbol) {
        // Priority 2: find the account that holds this symbol directly
        const matchedHoldingByAcc = importedHoldings.find((h) => h.symbol === urlSymbol && h.account_id);
        if (matchedHoldingByAcc?.account_id) {
          activeAcc = filteredAccounts.find((a) => a.account_id === matchedHoldingByAcc.account_id) || null;
        }
        // Priority 2b: infer by asset class (crypto symbol → crypto acct, else equity)
        if (!activeAcc) {
          const isRequestedCrypto = requestedInstrumentType === 'CRYPTO' || (
            requestedInstrumentType !== 'EQUITY' && (urlSymbol.endsWith('USD') || /crypto|coin|token/i.test(
              importedHoldings.find((h) => h.symbol === urlSymbol)?.instrument_type || ''
            ))
          );
          if (isRequestedCrypto) {
            activeAcc = filteredAccounts.find((a) => isCryptoAccount(a)) || null;
          } else {
            activeAcc = preferredEquityAccount(filteredAccounts);
          }
        }
      }

      // Priority 3: saved default, then previously-selected or a safe fallback.
      if (!activeAcc) {
        activeAcc = filteredAccounts.find((a) => a.account_id === savedDefaultAccountId)
          || filteredAccounts.find((a) => a.account_id === selectedAccountId)
          || preferredEquityAccount(filteredAccounts)
          || filteredAccounts[0]
          || null;
      }

      if (activeAcc) {
        const isCrypto = isCryptoAccount(activeAcc);
        const matchedHolding = deepLinkedHolding
          || (urlSymbol ? holdingForAccount(importedHoldings, urlSymbol, activeAcc.account_id) : null);
        const requestedTypeAllowedForAccount = !requestedInstrumentType
          || (isCrypto ? requestedInstrumentType === 'CRYPTO' : requestedInstrumentType !== 'CRYPTO');
        const nextInstrumentType = requestedTypeAllowedForAccount && requestedInstrumentType
          || (matchedHolding ? normalizedWebullInstrumentType(matchedHolding.instrument_type) : (isCrypto ? 'CRYPTO' : 'EQUITY'));
        setSelectedAccountId(activeAcc.account_id);
        setSelectedInstrumentType(nextInstrumentType);
        setSelectedSecurityType(
          nextInstrumentType === 'EQUITY' && String(matchedHolding?.instrument_type || '').toUpperCase() === 'ETF'
            ? 'ETF'
            : nextInstrumentType
        );
        setSelectedOptionHoldingId(nextInstrumentType === 'OPTION' && matchedHolding?.id ? String(matchedHolding.id) : '');

        if (urlSymbol) {
          const ticketSymbol = nextInstrumentType === 'OPTION'
            ? (matchedHolding?.underlying_symbol || urlSymbol)
            : urlSymbol;
          setSelectedSymbol(ticketSymbol);
          if (nextInstrumentType === 'FUTURES') {
            setFuturesContractInput(urlSymbol);
            setSelectedFuturesContract(matchedHolding ? {
              symbol: urlSymbol,
              name: matchedHolding.name || urlSymbol,
              expiration_date: matchedHolding.expiration_date,
            } : null);
          }
          if (matchedHolding?.current_price) setLivePrice(Number(matchedHolding.current_price));
          setOrderForm((prev) => ({
            ...prev,
            side: urlSide && ['BUY', 'SELL'].includes(urlSide) ? urlSide : prev.side,
            type: nextInstrumentType === 'OPTION' ? 'LIMIT' : prev.type,
            price: matchedHolding?.current_price ? Number(matchedHolding.current_price).toFixed(2) : prev.price,
            optionType: nextInstrumentType === 'OPTION' ? (matchedHolding?.option_type || prev.optionType) : prev.optionType,
            optionStrike: nextInstrumentType === 'OPTION' && matchedHolding?.option_strike != null ? String(matchedHolding.option_strike) : prev.optionStrike,
            optionExpiration: nextInstrumentType === 'OPTION' ? (matchedHolding?.option_expiration || prev.optionExpiration) : prev.optionExpiration,
            quantity: nextInstrumentType === 'OPTION' && urlSide === 'SELL' && matchedHolding?.amount ? String(matchedHolding.amount) : prev.quantity,
          }));
        } else if (isCrypto && (selectedSymbol === 'AAPL' || !selectedSymbol.endsWith('USD'))) {
          const firstCrypto = importedHoldings.find((h) => String(h.account_id || '') === activeAcc.account_id && /crypto|coin|token/i.test(h.instrument_type || ''));
          setSelectedSymbol(firstCrypto ? firstCrypto.symbol : 'BTCUSD');
          if (firstCrypto?.current_price) {
            setLivePrice(Number(firstCrypto.current_price));
            setOrderForm((prev) => ({ ...prev, price: Number(firstCrypto.current_price).toFixed(2) }));
          }
        } else if (!isCrypto && (selectedSymbol === 'BTCUSD' || selectedSymbol.endsWith('USD'))) {
          const firstStock = importedHoldings.find((h) => String(h.account_id || '') === activeAcc.account_id
            && !/crypto|coin|token/i.test(h.instrument_type || '')
            && !['OPTION', 'FUTURES', 'EVENT'].includes(String(h.instrument_type || '').toUpperCase()));
          setSelectedSymbol(firstStock ? firstStock.symbol : 'AAPL');
          if (firstStock?.current_price) {
            setLivePrice(Number(firstStock.current_price));
            setOrderForm((prev) => ({ ...prev, price: Number(firstStock.current_price).toFixed(2) }));
          }
        }
      }

      // UNBLOCK UI IMMEDIATELY: Trading page, chart, and order form render instantly!
      setLoading(false);

      // 2. Fetch active account open orders in background
      if (activeAcc?.account_id) {
        loadOpenOrders(activeAcc.account_id, false);
      }

      // 3. Fetch background AI signals
      axios.get('/api/webull/ai-signals?limit=50', { withCredentials: true })
        .then((res) => setSignals(res.data?.signals || []))
        .catch(() => {});
    } catch (requestError) {
      setError(requestError.response?.data?.message || 'Unable to load the Webull workspace.');
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  // Fetch history when history or chart tab is activated
  useEffect(() => {
    if (['history', 'trade_chart'].includes(activeTab) && !history.length && !historyLoading) {
      loadHistory(undefined, isTestMode);
    }
  }, [activeTab, isTestMode]);

  // Refetch open orders when account changes
  useEffect(() => {
    if (selectedAccountId) {
      loadOpenOrders(selectedAccountId, isTestMode);
    }
  }, [selectedAccountId, isTestMode]);

  // Sync active account and cash balance
  const activeAccount = useMemo(() => {
    if (isTestMode) {
      return {
        account_id: 'TEST_PAPER_ACCOUNT',
        account_id_masked: '••••SIM',
        account_label: 'Webull Paper Account',
        account_name: 'Webull Paper Account',
        account_type: 'CASH',
        account_class: 'PAPER_TRADING',
        is_paper: true,
        balance: {
          total_cash_balance: paperSummary?.cash_balance ?? 0,
          cash_balance: paperSummary?.cash_balance ?? 0,
          settled_cash: paperSummary?.cash_balance ?? 0,
          net_liquidation: paperSummary?.net_liquidation ?? 0,
          buying_power: paperSummary?.buying_power ?? 0,
        },
        net_liquidation: paperSummary?.net_liquidation ?? 0,
        buying_power: paperSummary?.buying_power ?? 0,
        cash_balance: paperSummary?.cash_balance ?? 0,
        total_market_value: paperSummary?.total_market_value ?? 0,
        unrealized_profit_loss: paperSummary?.unrealized_profit_loss ?? 0,
        unrealized_profit_loss_rate: paperSummary?.unrealized_profit_loss_rate ?? 0,
      };
    }
    return accounts.find((a) => a.account_id === selectedAccountId) || accounts[0];
  }, [isTestMode, paperSummary, accounts, selectedAccountId]);

  const activeAccountIsCrypto = isCryptoAccount(activeAccount);
  const assetClassDisabled = (assetClass) => {
    if (isTestMode) return false;
    if (!activeAccount) return false;
    return activeAccountIsCrypto ? assetClass !== 'CRYPTO' : assetClass === 'CRYPTO';
  };

  const displayAccounts = useMemo(() => {
    if (isTestMode) {
      return [
        {
          account_id: 'TEST_PAPER_ACCOUNT',
          account_id_masked: '••••SIM',
          account_label: 'Webull Paper Account',
          account_name: 'Webull Paper Account',
          account_type: 'CASH',
          account_class: 'PAPER_TRADING',
          is_paper: true,
        },
      ];
    }
    return accounts;
  }, [isTestMode, accounts]);

  const resetFuturesSelection = () => {
    setFuturesContracts([]);
    setFuturesContractInput('');
    setSelectedFuturesContract(null);
    setFuturesMessage('');
  };

  const DEFAULT_FUTURES_PRODUCTS = [
    { product_code: 'ES', symbol: 'ES', name: 'E-mini S&P 500 Futures', exchange: 'CME' },
    { product_code: 'NQ', symbol: 'NQ', name: 'E-mini Nasdaq-100 Futures', exchange: 'CME' },
    { product_code: 'YM', symbol: 'YM', name: 'E-mini Dow Jones Futures', exchange: 'CBOT' },
    { product_code: 'RTY', symbol: 'RTY', name: 'E-mini Russell 2000 Futures', exchange: 'CME' },
    { product_code: 'MES', symbol: 'MES', name: 'Micro E-mini S&P 500 Futures', exchange: 'CME' },
    { product_code: 'MNQ', symbol: 'MNQ', name: 'Micro E-mini Nasdaq-100 Futures', exchange: 'CME' },
    { product_code: 'CL', symbol: 'CL', name: 'Crude Oil Futures', exchange: 'NYMEX' },
    { product_code: 'GC', symbol: 'GC', name: 'Gold Futures', exchange: 'COMEX' },
    { product_code: 'SI', symbol: 'SI', name: 'Silver Futures', exchange: 'COMEX' },
    { product_code: 'BTC', symbol: 'BTC', name: 'Bitcoin Futures', exchange: 'CME' },
  ];

  const handleAssetClassChange = (nextType) => {
    if (assetClassDisabled(nextType)) return;
    userChangedSessionRef.current = false;
    assetSymbolMemoryRef.current[selectedInstrumentType] = selectedSymbol;
    const equityHolding = modeHoldings.find((holding) => String(holding.account_id || '') === String(selectedAccountId)
      && !/crypto|coin|token/i.test(holding.instrument_type || '')
      && !['OPTION', 'FUTURES', 'EVENT'].includes(String(holding.instrument_type || '').toUpperCase()));
    const cryptoHolding = modeHoldings.find((holding) => String(holding.account_id || '') === String(selectedAccountId)
      && /crypto|coin|token/i.test(holding.instrument_type || ''));
    const defaultSymbols = {
      EQUITY: equityHolding?.symbol || 'AAPL',
      OPTION: assetSymbolMemoryRef.current.EQUITY || equityHolding?.symbol || 'AAPL',
      CRYPTO: cryptoHolding?.symbol || 'BTCUSD',
      FUTURES: selectedFuturesContract?.symbol || '',
      EVENT: selectedEventMarket?.symbol || '',
    };
    const nextSymbol = assetSymbolMemoryRef.current[nextType] || defaultSymbols[nextType] || '';
    setSelectedInstrumentType(nextType);
    setSelectedSecurityType(nextType === 'EQUITY' ? 'EQUITY' : nextType);
    setSelectedSymbol(nextSymbol);
    setSelectedOptionHoldingId('');
    setBalancePercentage(0);
    setOrderValidationError('');
    setLivePrice(0);
    setOrderForm((prev) => ({
      ...prev,
      type: nextType === 'EVENT' ? 'LIMIT' : (nextType === 'OPTION' ? 'LIMIT' : 'MARKET'),
      quantity: '',
      quoteQuantity: '',
      price: nextType === 'EVENT' ? String(eventQuoteFor(selectedEventMarket, 'yes', 'BUY') ?? '') : '',
      stopPrice: '',
      trailingStopStep: '',
      timeInForce: 'DAY',
      entrustType: 'QTY',
      eventOutcome: 'yes',
    }));
  };

  // Automatically default session for cash-based accounts when instrument or account changes
  useEffect(() => {
    if (selectedInstrumentType === 'EQUITY' && isCashBasedAccount(activeAccount) && !userChangedSessionRef.current) {
      const defaultSession = getDefaultTradingSession();
      setOrderForm((prev) => (prev.tradingSession === defaultSession ? prev : { ...prev, tradingSession: defaultSession }));
    }
  }, [selectedInstrumentType, activeAccount]);
  const cashBalance = useMemo(() => {
    if (isTestMode) {
      return Number(paperSummary?.buying_power ?? paperSummary?.available_cash ?? paperSummary?.cash_balance ?? 0);
    }
    if (!activeAccount?.balance) return 0;
    const b = activeAccount.balance;
    return nonNegativeNumber(b.total_cash_balance ?? b.cash_balance ?? b.settled_cash ?? b.cashBalance ?? 0);
  }, [isTestMode, paperSummary, activeAccount]);

  const loadFuturesCatalog = async () => {
    setFuturesLoading(true);
    setFuturesMessage('');
    try {
      const response = await axios.get('/api/webull/futures/catalog', { withCredentials: true });
      const products = response.data?.products?.length ? response.data.products : DEFAULT_FUTURES_PRODUCTS;
      setFuturesCatalog({
        classes: response.data?.classes || [],
        products: products,
      });
    } catch (requestError) {
      setFuturesCatalog((prev) => ({
        classes: prev.classes || [],
        products: prev.products?.length ? prev.products : DEFAULT_FUTURES_PRODUCTS,
      }));
    } finally {
      setFuturesLoading(false);
    }
  };

  const lookupFuturesContracts = async () => {
    const requestedSymbol = futuresContractInput.trim().toUpperCase();
    if (!requestedSymbol) {
      setFuturesMessage('Enter an exact futures contract code, for example ESZ5.');
      return;
    }
    setFuturesLoading(true);
    setFuturesMessage('');
    try {
      const response = await axios.get('/api/webull/futures/contracts', {
        params: { symbol: requestedSymbol },
        withCredentials: true,
      });
      const contracts = response.data?.contracts || [];
      setFuturesContracts(contracts);
      if (!contracts.length) setFuturesMessage(`No tradable Webull futures contract was returned for ${requestedSymbol}.`);
      if (contracts.length === 1) {
        const contract = contracts[0];
        setSelectedFuturesContract(contract);
        setSelectedSymbol(contract.symbol || requestedSymbol);
        setLivePrice(0);
        setOrderForm((prev) => ({ ...prev, type: 'MARKET', quantity: '', quoteQuantity: '', price: '', stopPrice: '', trailingStopStep: '' }));
      }
    } catch (requestError) {
      setFuturesContracts([]);
      setSelectedFuturesContract(null);
      setFuturesMessage(requestError.response?.data?.message || 'Unable to look up the Webull futures contract.');
    } finally {
      setFuturesLoading(false);
    }
  };

  const selectFuturesContract = (contract) => {
    const contractSymbol = String(contract?.symbol || '').trim().toUpperCase();
    if (!contractSymbol) return;
    setSelectedFuturesContract(contract);
    setFuturesContractInput(contractSymbol);
    setSelectedSymbol(contractSymbol);
    setLivePrice(0);
    setBalancePercentage(0);
    setOrderValidationError('');
    setOrderForm((prev) => ({ ...prev, type: 'MARKET', quantity: '', quoteQuantity: '', price: '', stopPrice: '', trailingStopStep: '' }));
  };

  useEffect(() => {
    if (selectedInstrumentType === 'FUTURES' && !activeAccountIsCrypto && !futuresCatalog.products.length && !futuresLoading) {
      loadFuturesCatalog();
    }
  }, [selectedInstrumentType, activeAccountIsCrypto]);

  // Event Contract Helpers
  const eventQuoteFor = (market, outcome = orderForm.eventOutcome, side = orderForm.side) => {
    if (!market) return null;
    const cleanOutcome = String(outcome || 'yes').toLowerCase();
    const cleanSide = String(side || 'BUY').toUpperCase();
    const field = `${cleanOutcome}_${cleanSide === 'SELL' ? 'bid' : 'ask'}`;
    const value = Number(market[field]);
    return Number.isFinite(value) && value >= 0 ? value : null;
  };

  useEffect(() => {
    assetSymbolMemoryRef.current[selectedInstrumentType] = selectedSymbol;
  }, [selectedInstrumentType, selectedSymbol]);

  const applyEventMarket = (market, { resetPrice = true } = {}) => {
    if (!market?.symbol) return;
    const suggestedPrice = eventQuoteFor(market);
    setSelectedEventMarket(market);
    assetSymbolMemoryRef.current.EVENT = market.symbol;
    setSelectedSymbol(market.symbol);
    setEventMarketMenuOpen(false);
    eventAutoPriceRef.current = resetPrice;
    setOrderValidationError('');
    setOrderForm((prev) => ({
      ...prev,
      price: resetPrice && suggestedPrice != null ? String(suggestedPrice) : prev.price,
      quoteQuantity: resetPrice && suggestedPrice != null && Number(prev.quantity) > 0
        ? (Number(prev.quantity) * suggestedPrice).toFixed(2)
        : prev.quoteQuantity,
    }));
  };

  const loadEventMarkets = async ({ category = selectedEventCategory, query = eventMarketQuery } = {}) => {
    if (!category) return;
    const requestId = ++eventMarketRequestRef.current;
    setEventLoading(true);
    setEventMessage('');
    try {
      const response = await axios.get('/api/webull/events/markets', {
        params: { category, query: query.trim(), limit: query.trim() ? 50 : 10 },
        withCredentials: true,
      });
      if (requestId !== eventMarketRequestRef.current) return;
      const mkts = response.data?.markets || [];
      setEventMarkets(mkts);
      setEventTotalMatches(Number(response.data?.total_matches || mkts.length));
      setEventCatalogLoading(Boolean(response.data?.loading));
      setEventMessage(response.data?.message || '');
    } catch (err) {
      if (requestId !== eventMarketRequestRef.current) return;
      setEventMarkets([]);
      setEventTotalMatches(0);
      setEventCatalogLoading(false);
      setEventMessage(err.response?.data?.message || 'Unable to load Webull Event Contract markets.');
    } finally {
      if (requestId === eventMarketRequestRef.current) setEventLoading(false);
    }
  };

  const loadEventCategoriesAndMarkets = async () => {
    setEventLoading(true);
    setEventMessage('');
    try {
      const response = await axios.get('/api/webull/events/categories', { withCredentials: true });
      const categories = response.data?.categories || [];
      setEventCategories(categories);
      if (!categories.length) throw new Error('Webull returned no Event Contract categories.');
      const initialCategory = categories[0].category_code || categories[0].category_id;
      setSelectedEventCategory(initialCategory);
      setEventMarketQuery('');
      setEventMarkets([]);
      setEventTotalMatches(0);
      setEventCatalogLoading(true);
    } catch (err) {
      setEventMessage(err.response?.data?.message || err.message || 'Unable to load Webull Event Contract categories.');
    } finally {
      setEventLoading(false);
    }
  };

  const handleEventCategoryChange = (categoryCode) => {
    // Invalidate any slower response from the previous category before the
    // next request begins, and clear every selection-dependent ticket value.
    eventMarketRequestRef.current += 1;
    setSelectedEventCategory(categoryCode);
    setEventMarketQuery('');
    setEventMarkets([]);
    setEventTotalMatches(0);
    setEventMessage('');
    setEventLoading(true);
    setEventCatalogLoading(true);
    setSelectedEventMarket(null);
    assetSymbolMemoryRef.current.EVENT = '';
    setSelectedSymbol('');
    setEventMarketMenuOpen(true);
    setOrderForm((prev) => ({ ...prev, price: '', quantity: '', quoteQuantity: '' }));
  };

  const chooseEventOutcome = (outcome) => {
    const suggestedPrice = eventQuoteFor(selectedEventMarket, outcome, orderForm.side);
    eventAutoPriceRef.current = true;
    setOrderForm((prev) => ({
      ...prev,
      eventOutcome: outcome,
      price: suggestedPrice != null ? String(suggestedPrice) : '',
      quoteQuantity: suggestedPrice != null && Number(prev.quantity) > 0
        ? (Number(prev.quantity) * suggestedPrice).toFixed(2)
        : '',
    }));
    setOrderValidationError('');
  };

  useEffect(() => {
    if (selectedInstrumentType === 'EVENT' && !eventCategories.length && !eventLoading) {
      loadEventCategoriesAndMarkets();
    }
  }, [selectedInstrumentType]);

  useEffect(() => {
    if (selectedInstrumentType !== 'EVENT' || !selectedEventCategory) return undefined;
    const timer = window.setTimeout(() => {
      loadEventMarkets({ category: selectedEventCategory, query: eventMarketQuery });
    }, eventMarketQuery.trim() ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [selectedInstrumentType, selectedEventCategory, eventMarketQuery]);

  useEffect(() => {
    if (selectedInstrumentType !== 'EVENT' || !selectedEventCategory || !eventCatalogLoading) return undefined;
    const interval = window.setInterval(() => {
      loadEventMarkets({ category: selectedEventCategory, query: eventMarketQuery });
    }, 5000);
    return () => window.clearInterval(interval);
  }, [selectedInstrumentType, selectedEventCategory, eventMarketQuery, eventCatalogLoading]);

  useEffect(() => {
    if (selectedInstrumentType !== 'EVENT' || !selectedEventMarket?.symbol) return undefined;
    let cancelled = false;
    const refreshQuote = async () => {
      try {
        const response = await axios.get('/api/webull/events/markets', {
          params: { symbol: selectedEventMarket.symbol },
          withCredentials: true,
        });
        const market = response.data?.markets?.[0];
        if (!market || cancelled) return;
        setSelectedEventMarket(market);
        setEventMarkets((current) => current.map((item) => (item.symbol === market.symbol ? market : item)));
        if (eventAutoPriceRef.current) {
          setOrderForm((prev) => {
            const suggestedPrice = eventQuoteFor(market, prev.eventOutcome, prev.side);
            return suggestedPrice == null ? prev : {
              ...prev,
              price: String(suggestedPrice),
              quoteQuantity: Number(prev.quantity) > 0
                ? (Number(prev.quantity) * suggestedPrice).toFixed(2)
                : prev.quoteQuantity,
            };
          });
        }
      } catch (err) {
        if (!cancelled) setEventMessage(err.response?.data?.message || 'Live Event Contract pricing is temporarily unavailable.');
      }
    };
    refreshQuote();
    const interval = window.setInterval(refreshQuote, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [selectedInstrumentType, selectedEventMarket?.symbol]);

  useEffect(() => {
    const closeMenu = (event) => {
      if (eventMarketSelectorRef.current && !eventMarketSelectorRef.current.contains(event.target)) {
        setEventMarketMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', closeMenu);
    return () => document.removeEventListener('mousedown', closeMenu);
  }, []);

  // An option sale may only close the exact held contract: account,
  // underlying, expiration, strike, and call/put all have to match.
  const currentHolding = useMemo(() => {
    if (selectedInstrumentType === 'OPTION') {
      const matchingOptions = modeHoldings.filter((holding) => holdingMatchesOptionContract(holding, {
        accountId: selectedAccountId,
        underlyingSymbol: selectedSymbol,
        optionType: orderForm.optionType,
        optionStrike: orderForm.optionStrike,
        optionExpiration: orderForm.optionExpiration,
      }));
      return matchingOptions.find((holding) => String(holding?.id || '') === selectedOptionHoldingId)
        || matchingOptions[0]
        || null;
    }
    if (selectedInstrumentType === 'EVENT') {
      return modeHoldings.find((holding) => String(holding?.account_id || '') === String(selectedAccountId || '')
        && String(holding?.instrument_type || '').toUpperCase() === 'EVENT'
        && holdingMatchesSymbol(holding, selectedSymbol)
        && String(holding?.event_outcome || '').toLowerCase() === String(orderForm.eventOutcome || '').toLowerCase()) || null;
    }
    return holdingForAccount(modeHoldings, selectedSymbol, selectedAccountId);
  }, [modeHoldings, selectedSymbol, selectedAccountId, selectedInstrumentType, selectedOptionHoldingId, orderForm.optionType, orderForm.optionStrike, orderForm.optionExpiration, orderForm.eventOutcome]);

  const currentHoldingIsShort = useMemo(
    () => String(currentHolding?.position_side || currentHolding?.side || '').toUpperCase() === 'SHORT',
    [currentHolding]
  );
  const heldQuantity = useMemo(
    () => nonNegativeNumber(currentHolding?.available_quantity ?? currentHolding?.amount),
    [currentHolding]
  );
  const heldValue = useMemo(
    () => Math.abs(Number(currentHolding?.current_value ?? (heldQuantity * livePrice)) || 0),
    [currentHolding, heldQuantity, livePrice]
  );

  // A current snapshot is the trade-ticket source of truth. Stored holdings
  // provide a fast initial fallback while the signed Webull quote arrives.
  useEffect(() => {
    if (selectedInstrumentType === 'EVENT') {
      setLivePrice(0);
      return undefined;
    }
    let active = true;
    const fallbackPrice = Number(currentHolding?.current_price || 0);
    if (fallbackPrice > 0) setLivePrice(fallbackPrice);
    const loadSnapshot = async () => {
      try {
        if (selectedInstrumentType === 'OPTION' && !currentHolding?.id) return;
        if (selectedInstrumentType === 'FUTURES' && !selectedFuturesContract?.symbol) return;
        if (!['EQUITY', 'CRYPTO', 'OPTION', 'FUTURES'].includes(selectedInstrumentType)) return;
        const response = selectedInstrumentType === 'OPTION'
          ? await axios.get('/api/webull/option-market-data', {
            params: { holding_id: currentHolding.id },
            withCredentials: true,
          })
          : selectedInstrumentType === 'FUTURES'
            ? await axios.get('/api/webull/futures/market-data', {
              params: { symbol: selectedSymbol },
              withCredentials: true,
            })
          : await axios.get('/api/webull/market-snapshot', {
            params: {
              symbol: selectedSymbol,
              instrument_type: selectedInstrumentType === 'EQUITY' ? selectedSecurityType : selectedInstrumentType,
            },
            withCredentials: true,
          });
        const price = Number(selectedInstrumentType === 'OPTION'
          ? response.data?.quote?.last_price
          : selectedInstrumentType === 'FUTURES'
            ? response.data?.quote?.price
          : response.data?.snapshot?.price || 0);
        if (active && price > 0) {
          setLivePrice(price);
          setOrderForm((prev) => (prev.price ? prev : { ...prev, price: price.toFixed(price >= 1 ? 2 : 4) }));
        }
      } catch {
        // Retain the imported price if the user's OpenAPI quote entitlement is unavailable.
      }
    };
    loadSnapshot();
    const timer = window.setInterval(loadSnapshot, 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, [selectedSymbol, selectedInstrumentType, selectedSecurityType, currentHolding, selectedFuturesContract]);

  // Handlers for Instrument change from Top TradingView Chart
  const handleInstrumentChange = ({ symbol: nextSymbol, instrumentType: nextType, securityType }) => {
    if (assetClassDisabled(nextType)) return;
    userChangedSessionRef.current = false;
    setSelectedSymbol(nextSymbol);
    setSelectedInstrumentType(nextType);
    setSelectedSecurityType(nextType === 'EQUITY' ? (securityType === 'ETF' ? 'ETF' : 'EQUITY') : nextType);
    setSelectedOptionHoldingId('');
    setBalancePercentage(0);
    setOrderValidationError('');
    setOrderForm((prev) => ({
      ...prev,
      symbol: nextSymbol,
      quantity: '',
      quoteQuantity: '',
      price: '',
      stopPrice: '',
      trailingStopStep: '',
      ...(nextType === 'EQUITY' && isCashBasedAccount(activeAccount) ? { tradingSession: getDefaultTradingSession() } : {})
    }));
  };

  const handleAccountChange = (newAccountId) => {
    userChangedSessionRef.current = false;
    assetSymbolMemoryRef.current[selectedInstrumentType] = selectedSymbol;
    setSelectedAccountId(newAccountId);
    setSelectedOptionHoldingId('');
    resetFuturesSelection();
    setBalancePercentage(0);
    setOrderValidationError('');
    const targetAcc = accounts.find((a) => a.account_id === newAccountId);
    const isCrypto = isCryptoAccount(targetAcc);
    if (isCrypto) {
      const topCryptoHolding = modeHoldings.find((h) => String(h.account_id || '') === String(newAccountId) && /crypto|coin|token/i.test(h.instrument_type || ''));
      const nextSym = assetSymbolMemoryRef.current.CRYPTO || topCryptoHolding?.symbol || 'BTCUSD';
      setSelectedInstrumentType('CRYPTO');
      setSelectedSecurityType('CRYPTO');
      assetSymbolMemoryRef.current.CRYPTO = nextSym;
      setSelectedSymbol(nextSym);
      setOrderForm((prev) => ({ ...prev, symbol: nextSym, quantity: '', quoteQuantity: '' }));
    } else {
      const topEquityHolding = modeHoldings.find((h) => String(h.account_id || '') === String(newAccountId)
        && !/crypto|coin|token/i.test(h.instrument_type || '')
        && !['OPTION', 'FUTURES', 'EVENT'].includes(String(h.instrument_type || '').toUpperCase()));
      const nextSym = assetSymbolMemoryRef.current.EQUITY || topEquityHolding?.symbol || 'AAPL';
      setSelectedInstrumentType('EQUITY');
      setSelectedSecurityType('EQUITY');
      assetSymbolMemoryRef.current.EQUITY = nextSym;
      setSelectedSymbol(nextSym);
      const shouldDefaultSession = isCashBasedAccount(targetAcc);
      setOrderForm((prev) => ({
        ...prev,
        symbol: nextSym,
        quantity: '',
        quoteQuantity: '',
        ...(shouldDefaultSession ? { tradingSession: getDefaultTradingSession() } : {})
      }));
    }
  };

  const saveDefaultAccount = async (accountId = selectedAccountId) => {
    const cleanAccountId = String(accountId || '');
    if (!cleanAccountId || savingDefaultAccount || isTestMode) return;
    setSavingDefaultAccount(true);
    try {
      const response = await axios.put('/api/webull/default-account', { account_id: cleanAccountId }, { withCredentials: true });
      setDefaultAccountId(String(response.data?.default_account_id || cleanAccountId));
      setOrderFeedback({ type: 'success', message: 'Webull default trading account saved.' });
    } catch (requestError) {
      setOrderFeedback({ type: 'error', message: requestError.response?.data?.message || 'Unable to save the default Webull account.' });
    } finally {
      setSavingDefaultAccount(false);
    }
  };

  useEffect(() => {
    if (isTestMode && activeTab === 'ai_analysis') setActiveTab('order');
  }, [activeTab, isTestMode]);

  // Dual Input Quantity / Value calculations
  const effectivePrice = useMemo(() => {
    const limitPrice = Number(orderForm.price);
    const stopPrice = Number(orderForm.stopPrice);
    const currentPrice = Number(livePrice);
    if (['LIMIT', 'STOP_LOSS_LIMIT'].includes(orderForm.type) && Number.isFinite(limitPrice) && limitPrice > 0) {
      return limitPrice;
    }
    if (orderForm.type === 'STOP_LOSS' && Number.isFinite(stopPrice) && stopPrice > 0) {
      return stopPrice;
    }
    return Number.isFinite(currentPrice) && currentPrice > 0 ? currentPrice : 0;
  }, [orderForm.type, orderForm.price, orderForm.stopPrice, livePrice]);

  const fractionalEquityAllowed = selectedInstrumentType === 'EQUITY' && orderForm.tradingSession === 'CORE';
  const fractionalQuantityAllowed = selectedInstrumentType === 'CRYPTO'
    || fractionalEquityAllowed
    || (selectedInstrumentType === 'EVENT' && Boolean(selectedEventMarket?.rules?.fractionable));

  const handleBaseQuantityChange = (val) => {
    const qty = val.replace(/[^0-9.]/g, '');
    const numQty = parseFloat(qty) || 0;
    const mult = selectedInstrumentType === 'OPTION' ? OPTION_CONTRACT_MULTIPLIER : 1;
    const computedVal = numQty > 0 && effectivePrice > 0
      ? (numQty * effectivePrice * mult).toFixed(2)
      : selectedInstrumentType === 'OPTION' ? '0.00' : '';
    setOrderValidationError('');
    setOrderForm((prev) => ({ ...prev, quantity: qty, quoteQuantity: computedVal }));
  };

  const handleQuoteQuantityChange = (val) => {
    const quoteVal = val.replace(/[^0-9.]/g, '');
    const numQuote = parseFloat(quoteVal) || 0;
    const mult = selectedInstrumentType === 'OPTION' ? OPTION_CONTRACT_MULTIPLIER : 1;
    const unitCost = effectivePrice * mult;
    const rawQuantity = numQuote > 0 && unitCost > 0 ? numQuote / unitCost : 0;
    const wholeQuantity = Math.floor(rawQuantity);
    const computedQty = fractionalQuantityAllowed
      ? formatQuantityForTicket(rawQuantity, 6)
        : wholeQuantity > 0 ? String(wholeQuantity) : '';
    setOrderValidationError('');
    if (selectedInstrumentType === 'EQUITY' && !fractionalEquityAllowed && rawQuantity > 0 && wholeQuantity < 1) {
      setOrderValidationError('Extended and Overnight stock/ETF sessions require whole shares. Select Only Regular Hours (CORE) to use a fractional quantity.');
    }
    setOrderForm((prev) => ({
      ...prev,
      quoteQuantity: selectedInstrumentType === 'OPTION'
        ? optionOrderValueText(computedQty, effectivePrice)
        : quoteVal,
      quantity: computedQty,
    }));
  };

  const handlePriceChange = (val) => {
    const px = val.replace(/[^0-9.]/g, '');
    if (selectedInstrumentType === 'EVENT') eventAutoPriceRef.current = false;
    setOrderForm((prev) => {
      const numQty = parseFloat(prev.quantity) || 0;
      const numPx = parseFloat(px) || 0;
      const mult = selectedInstrumentType === 'OPTION' ? OPTION_CONTRACT_MULTIPLIER : 1;
      const computedQuote = numQty > 0 && numPx > 0
        ? (numQty * numPx * mult).toFixed(2)
        : selectedInstrumentType === 'OPTION' ? '0.00' : prev.quoteQuantity;
      return { ...prev, price: px, quoteQuantity: computedQuote };
    });
    setOrderValidationError('');
  };

  const handleStopPriceChange = (val) => {
    const spx = val.replace(/[^0-9.]/g, '');
    setOrderValidationError('');
    setOrderForm((prev) => ({
      ...prev,
      stopPrice: spx,
      quoteQuantity: selectedInstrumentType === 'OPTION'
        ? optionOrderValueText(prev.quantity, spx)
        : prev.quoteQuantity,
    }));
  };

  // Slider change handler
  const handleSliderChange = (pct) => {
    setBalancePercentage(pct);
    setOrderValidationError('');
    if (pct === 0) {
      setOrderForm((prev) => ({ ...prev, quantity: '', quoteQuantity: '' }));
      return;
    }
    if (orderForm.side === 'BUY') {
      if (cashBalance > 0 && effectivePrice > 0) {
        const targetDollars = cashBalance * (pct / 100);
        const mult = selectedInstrumentType === 'OPTION' ? OPTION_CONTRACT_MULTIPLIER : 1;
        const unitCost = effectivePrice * mult;
        const rawQuantity = targetDollars / unitCost;
        const wholeQuantity = Math.floor(rawQuantity);
        const qty = fractionalQuantityAllowed
          ? formatQuantityForTicket(rawQuantity, 6)
            : wholeQuantity > 0 ? String(wholeQuantity) : '';
        if (selectedInstrumentType === 'EQUITY' && !fractionalEquityAllowed && rawQuantity > 0 && wholeQuantity < 1) {
          setOrderValidationError('Extended and Overnight stock/ETF sessions require whole shares. Select Only Regular Hours (CORE) to use a fractional quantity.');
        }
        setOrderForm((prev) => ({
          ...prev,
          quantity: qty,
          quoteQuantity: selectedInstrumentType === 'OPTION'
            ? optionOrderValueText(qty, effectivePrice)
            : targetDollars.toFixed(2),
        }));
      }
    } else {
      if (heldQuantity > 0) {
        const targetQty = (heldQuantity * (pct / 100));
        const wholeQuantity = Math.floor(targetQty);
        const formattedQty = fractionalQuantityAllowed
          ? formatQuantityForTicket(targetQty, 6)
            : wholeQuantity > 0 ? String(wholeQuantity) : '';
        if (selectedInstrumentType === 'EQUITY' && !fractionalEquityAllowed && targetQty > 0 && wholeQuantity < 1) {
          setOrderValidationError('Extended and Overnight stock/ETF sessions require whole shares. Select Only Regular Hours (CORE) to sell this fractional position.');
        }
        const mult = selectedInstrumentType === 'OPTION' ? OPTION_CONTRACT_MULTIPLIER : 1;
        const computedVal = selectedInstrumentType === 'OPTION'
          ? optionOrderValueText(formattedQty, effectivePrice)
          : (parseFloat(formattedQty) * effectivePrice * mult).toFixed(2);
        setOrderForm((prev) => ({
          ...prev,
          quantity: formattedQty,
          quoteQuantity: computedVal,
        }));
      } else {
        setOrderValidationError(`No ${selectedSymbol} is available to sell in the selected Webull account.`);
      }
    }
  };

  const orderTotal = useMemo(() => {
    if (selectedInstrumentType === 'EQUITY' && orderForm.entrustType === 'AMOUNT') {
      const cashVal = parseFloat(orderForm.totalCashAmount) || 0;
      return Number.isFinite(cashVal) && cashVal >= 0 ? cashVal : 0;
    }
    const qty = parseFloat(orderForm.quantity) || 0;
    const mult = selectedInstrumentType === 'OPTION' ? OPTION_CONTRACT_MULTIPLIER : 1;
    const total = qty * effectivePrice * mult;
    return Number.isFinite(total) && total >= 0 ? total : 0;
  }, [orderForm.quantity, orderForm.totalCashAmount, orderForm.entrustType, effectivePrice, selectedInstrumentType]);

  const optionContractSelected = selectedInstrumentType === 'OPTION'
    && Boolean(normalizedOptionExpiry(orderForm.optionExpiration))
    && Number(orderForm.optionStrike) > 0
    && effectivePrice > 0;
  const optionIsSingle = String(orderForm.optionStrategy || 'SINGLE').toUpperCase() === 'SINGLE';
  const optionUnitCost = optionContractSelected ? optionOrderValue(1, effectivePrice) : 0;
  const optionBuyEnabled = optionContractSelected && (!optionIsSingle || cashBalance + QUANTITY_EPSILON >= optionUnitCost);
  const optionSellEnabled = optionContractSelected && (!optionIsSingle || heldQuantity >= 1 - QUANTITY_EPSILON);
  const optionOrderControlsDisabled = selectedInstrumentType === 'OPTION'
    && (orderForm.side === 'BUY' ? !optionBuyEnabled : !optionSellEnabled);
  const optionExecutionMessage = !optionContractSelected
    ? 'Choose a priced contract from the options chain to enable an order.'
    : orderForm.side === 'BUY' && !optionBuyEnabled
      ? `This contract costs $${number(optionUnitCost)} per contract. Available USD is $${number(cashBalance)}.`
      : orderForm.side === 'SELL' && !optionSellEnabled
        ? 'Sell is available only for an exact option contract currently owned in this Webull account.'
        : '';
  const futuresContractSelected = selectedInstrumentType === 'FUTURES'
    && Boolean(selectedFuturesContract?.symbol)
    && String(selectedFuturesContract.symbol).toUpperCase() === String(selectedSymbol || '').toUpperCase();
  const futuresOrderControlsDisabled = selectedInstrumentType === 'FUTURES' && !futuresContractSelected;
  const eventRules = selectedEventMarket?.rules || {};
  const eventTradableStatus = String(selectedEventMarket?.tradable_status || eventRules.tradable_status || '').toUpperCase();
  const eventBuyEnabled = selectedInstrumentType !== 'EVENT' || (Boolean(selectedEventMarket?.symbol) && eventTradableStatus === 'OC');
  const eventSellEnabled = selectedInstrumentType !== 'EVENT' || (
    Boolean(selectedEventMarket?.symbol)
    && ['OC', 'CO'].includes(eventTradableStatus)
    && heldQuantity > QUANTITY_EPSILON
  );
  const eventCurrentSideEnabled = orderForm.side === 'SELL' ? eventSellEnabled : eventBuyEnabled;
  const eventOrderControlsDisabled = selectedInstrumentType === 'EVENT' && !eventCurrentSideEnabled;
  const ticketOrderControlsDisabled = optionOrderControlsDisabled || futuresOrderControlsDisabled || eventOrderControlsDisabled;
  const futuresExecutionMessage = selectedInstrumentType === 'FUTURES' && !futuresContractSelected
    ? 'Load and select an exact Webull futures contract before placing an order. Futures margin and trading eligibility are verified by Webull.'
    : '';
  const eventExecutionMessage = selectedInstrumentType === 'EVENT' && !selectedEventMarket?.symbol
    ? 'Choose a Webull Event Contract market before placing an order.'
    : selectedInstrumentType === 'EVENT' && !eventCurrentSideEnabled
      ? orderForm.side === 'BUY' && eventTradableStatus === 'CO'
        ? 'Webull currently marks this contract Liquidate Only. New positions are closed, but an owned position may be sold.'
        : orderForm.side === 'SELL' && ['OC', 'CO'].includes(eventTradableStatus) && heldQuantity <= QUANTITY_EPSILON
          ? 'Sell to Close is available only for the exact Yes/No Event Contract position currently owned in this account.'
        : 'Webull currently marks this Event Contract as not tradable.'
      : '';
  const eventSelectedQuote = eventQuoteFor(selectedEventMarket, orderForm.eventOutcome, orderForm.side);
  const eventSettlementPayout = Number(eventRules.settlement_payout);
  const eventQuantity = Number(orderForm.quantity);
  const eventLimitPrice = Number(orderForm.price);
  const eventPotentialProfitEach = Number.isFinite(eventSettlementPayout) && Number.isFinite(eventLimitPrice)
    ? Math.max(0, eventSettlementPayout - eventLimitPrice)
    : null;
  const eventGrossWinningPayout = Number.isFinite(eventSettlementPayout) && Number.isFinite(eventQuantity)
    ? eventSettlementPayout * eventQuantity
    : null;
  const eventPotentialProfitTotal = eventPotentialProfitEach != null && Number.isFinite(eventQuantity)
    ? eventPotentialProfitEach * eventQuantity
    : null;
  const eventStatusLabel = eventTradableStatus === 'OC'
    ? 'Open for trading'
    : eventTradableStatus === 'CO'
      ? 'Liquidate only'
      : eventTradableStatus === 'NT'
        ? 'Not tradable'
        : 'Status unavailable';

  useEffect(() => {
    if (selectedInstrumentType !== 'OPTION') return;
    if (orderForm.side === 'SELL' && !optionSellEnabled && optionBuyEnabled) {
      setOrderForm((prev) => ({ ...prev, side: 'BUY' }));
    } else if (orderForm.side === 'BUY' && !optionBuyEnabled && optionSellEnabled) {
      setOrderForm((prev) => ({ ...prev, side: 'SELL', timeInForce: 'DAY' }));
    }
  }, [selectedInstrumentType, orderForm.side, optionBuyEnabled, optionSellEnabled]);

  const activeAccountLabel = () => {
    const name = activeAccount?.account_label || activeAccount?.account_name || 'Webull Account';
    const masked = activeAccount?.account_id_masked || (selectedAccountId ? `••••${String(selectedAccountId).slice(-4)}` : '');
    return masked ? `${name} (${masked})` : name;
  };

  const assetClassButtonStyle = (assetClass, activeBackground) => ({
    padding: '5px 12px',
    borderRadius: '6px',
    border: 'none',
    background: selectedInstrumentType === assetClass ? activeBackground : 'transparent',
    color: '#fff',
    fontSize: '12px',
    fontWeight: 700,
    cursor: assetClassDisabled(assetClass) ? 'not-allowed' : 'pointer',
    opacity: assetClassDisabled(assetClass) ? 0.38 : 1,
    filter: assetClassDisabled(assetClass) ? 'grayscale(1)' : 'none',
  });

  const webullTwoFactorOrderDetails = () => ({
    provider: 'Webull',
    accountLabel: activeAccountLabel(),
    symbol: selectedSymbol,
    instrumentType: selectedInstrumentType === 'EQUITY' ? selectedSecurityType : selectedInstrumentType,
    side: orderForm.side,
    type: orderForm.type,
    quantity: orderForm.quantity,
    price: ['LIMIT', 'STOP_LOSS_LIMIT'].includes(orderForm.type) || selectedInstrumentType === 'EVENT' ? orderForm.price : undefined,
    stopPrice: ['STOP_LOSS', 'STOP_LOSS_LIMIT'].includes(orderForm.type) ? orderForm.stopPrice : undefined,
    estimatedValue: orderTotal > 0 ? orderTotal.toFixed(2) : undefined,
    timeInForce: orderForm.timeInForce,
    tradingSession: selectedInstrumentType === 'EQUITY' ? orderForm.tradingSession : 'CORE',
    optionType: selectedInstrumentType === 'OPTION' ? orderForm.optionType : undefined,
    optionStrike: selectedInstrumentType === 'OPTION' ? orderForm.optionStrike : undefined,
    optionExpiration: selectedInstrumentType === 'OPTION' ? orderForm.optionExpiration : undefined,
    trailingType: orderForm.type === 'TRAILING_STOP_LOSS' ? orderForm.trailingType : undefined,
    trailingStopStep: orderForm.type === 'TRAILING_STOP_LOSS' ? orderForm.trailingStopStep : undefined,
    bracketTakeProfitPrice: orderForm.isBracketEnabled ? orderForm.bracketTakeProfitPrice : undefined,
    bracketStopLossPrice: orderForm.isBracketEnabled ? orderForm.bracketStopLossPrice : undefined,
    bracketStopLossLimitPrice: orderForm.isBracketEnabled ? orderForm.bracketStopLossLimitPrice : undefined,
    eventOutcome: selectedInstrumentType === 'EVENT' ? orderForm.eventOutcome : undefined,
    currency: 'USD',
  });

  const rejectOrder = (message) => {
    setOrderValidationError(message);
    setOrderFeedback({ type: 'error', message });
  };

  // Pre-trade submit handler
  const handleOrderSubmit = (e) => {
    e.preventDefault();
    setOrderFeedback({ type: '', message: '' });
    setOrderValidationError('');
    if (!selectedAccountId) {
      rejectOrder('Please select a Webull account.');
      return;
    }
    if (!selectedSymbol.trim()) {
      rejectOrder('Please select an instrument.');
      return;
    }

    const isCashAmountMode = selectedInstrumentType === 'EQUITY' && orderForm.entrustType === 'AMOUNT';
    const qty = parseFloat(orderForm.quantity);
    const cashAmt = parseFloat(orderForm.totalCashAmount);

    if (isCashAmountMode) {
      if (!cashAmt || cashAmt < 5) {
        rejectOrder('Please enter a total cash amount of at least $5.00 for dollar-based orders.');
        return;
      }
    } else {
      if (!qty || qty <= 0) {
        rejectOrder('Please enter a valid order quantity. Use Max or enter a quantity greater than zero.');
        return;
      }
    }

    if (selectedInstrumentType === 'EVENT') {
      if (!selectedEventMarket?.symbol) {
        rejectOrder('Choose a Webull Event Contract market before placing an order.');
        return;
      }
      if (!eventRules.fractionable && !Number.isInteger(qty)) {
        rejectOrder('This Event Contract market requires a whole number of contracts.');
        return;
      }
      const eventMaxQuantity = Number(eventRules.max_quantity);
      if (Number.isFinite(eventMaxQuantity) && qty > eventMaxQuantity) {
        rejectOrder(`Maximum quantity for this Event Contract is ${number(eventMaxQuantity, eventRules.fractionable ? 5 : 0)} contracts.`);
        return;
      }
      const px = parseFloat(orderForm.price);
      if (!px || !eventPriceMatchesRanges(px, eventRules.price_ranges || [])) {
        rejectOrder(`Event Contract limit price must match a current Webull price range and tick: ${eventPriceRangeLabel(eventRules.price_ranges)}.`);
        return;
      }
      if (!['yes', 'no'].includes(String(orderForm.eventOutcome || '').toLowerCase())) {
        rejectOrder('Please select an outcome (YES or NO) for the event contract.');
        return;
      }
    }
    if (selectedInstrumentType === 'OPTION') {
      if (!optionContractSelected) {
        rejectOrder('Choose a priced option contract from the options chain before placing an order.');
        return;
      }
      if (!Number.isInteger(qty)) {
        rejectOrder('Webull option orders require a whole number of contracts.');
        return;
      }
      if (optionIsSingle && orderForm.side === 'SELL' && !optionSellEnabled) {
        rejectOrder('You can sell only an exact call or put contract currently owned in the selected Webull account.');
        return;
      }
      if (optionIsSingle && orderForm.side === 'BUY') {
        if (!optionBuyEnabled) {
          rejectOrder(`Insufficient USD to purchase one contract. This contract costs $${number(optionUnitCost)} and available USD is $${number(cashBalance)}.`);
          return;
        }
        if (orderTotal > cashBalance + QUANTITY_EPSILON) {
          rejectOrder(`Insufficient USD for ${qty} option contract${qty === 1 ? '' : 's'}. Estimated premium is $${number(orderTotal)} and available USD is $${number(cashBalance)}.`);
          return;
        }
      }
    }
    if (selectedInstrumentType === 'FUTURES') {
      if (!futuresContractSelected) {
        rejectOrder('Load and select an exact Webull futures contract before placing an order.');
        return;
      }
      if (!Number.isInteger(qty)) {
        rejectOrder('Webull futures orders require a whole number of contracts.');
        return;
      }
      if (!['DAY', 'GTC'].includes(orderForm.timeInForce)) {
        rejectOrder('Webull futures orders support Day or Good \'Til Canceled time in force.');
        return;
      }
    }
    if (['FUTURES', 'EQUITY'].includes(selectedInstrumentType) && orderForm.type === 'TRAILING_STOP_LOSS') {
      if (!['AMOUNT', 'PERCENTAGE'].includes(orderForm.trailingType) || Number(orderForm.trailingStopStep) <= 0) {
        rejectOrder('Trailing stops require a positive trail amount or percentage.');
        return;
      }
    }
    if (!['FUTURES', 'EVENT'].includes(selectedInstrumentType) && !(selectedInstrumentType === 'OPTION' && !optionIsSingle) && orderForm.side === 'SELL' && !isCashAmountMode && qty > heldQuantity + QUANTITY_EPSILON) {
      rejectOrder(`You can sell up to ${formatQuantityForTicket(heldQuantity, 6) || '0'} ${selectedSymbol} from ${activeAccountLabel()}.`);
      return;
    }
    if (isTestMode && orderForm.side === 'BUY_TO_CLOSE' && qty > heldQuantity + QUANTITY_EPSILON) {
      rejectOrder(`You can cover up to ${formatQuantityForTicket(heldQuantity, 6) || '0'} short units of ${selectedSymbol}.`);
      return;
    }
    if (selectedInstrumentType === 'EQUITY' && !isCashAmountMode && isFractionalQuantity(qty)) {
      if (orderForm.tradingSession !== 'CORE') {
        rejectOrder('Fractional stock and ETF orders are available only during Regular Hours. Select Only Regular Hours (CORE) or use a whole-share quantity.');
        return;
      }
      if (orderForm.type !== 'MARKET') {
        rejectOrder('Webull supports fractional stock and ETF orders as Market orders during Regular Hours. Select Market or use a whole-share quantity for this order type.');
        return;
      }
      if (orderTotal < 5) {
        rejectOrder('Webull requires a fractional stock or ETF order value of at least $5.00.');
        return;
      }
    }
    if (selectedInstrumentType === 'EQUITY' && orderForm.isAlgoEnabled) {
      if (!['MARKET', 'LIMIT'].includes(orderForm.type)) {
        rejectOrder('Algorithmic orders support Market and Limit orders only.');
        return;
      }
      if (orderForm.tradingSession !== 'CORE') {
        rejectOrder('Algorithmic orders run only during Regular Trading Hours (CORE).');
        return;
      }
      if (!orderForm.algoStartTime || !orderForm.algoEndTime) {
        rejectOrder('Algorithmic orders require start and end times in HH:mm:ss format.');
        return;
      }
    }
    if (selectedInstrumentType === 'EQUITY' && orderForm.isBracketEnabled) {
      if (!orderForm.bracketTakeProfitPrice && !orderForm.bracketStopLossPrice) {
        rejectOrder('Please enter at least a take-profit or stop-loss trigger price for the bracket.');
        return;
      }
    }
    if (selectedInstrumentType === 'OPTION') {
      if (!optionIsSingle && (!Array.isArray(orderForm.optionStrategyLegs) || orderForm.optionStrategyLegs.length < 2)) {
        rejectOrder('Select a strategy anchor from the current option chain so every strategy leg can be constructed.');
        return;
      }
      if (['LIMIT', 'STOP_LOSS_LIMIT'].includes(orderForm.type)) {
        const px = parseFloat(orderForm.price);
        if (!px || px <= 0) {
          rejectOrder('Options orders require a limit price greater than $0.');
          return;
        }
      }
      if (!orderForm.optionExpiration) {
        rejectOrder('Please specify an option expiration date.');
        return;
      }
      if (!orderForm.optionStrike || parseFloat(orderForm.optionStrike) <= 0) {
        rejectOrder('Please specify an option strike price.');
        return;
      }
      if (['STOP_LOSS', 'STOP_LOSS_LIMIT'].includes(orderForm.type)) {
        const spx = parseFloat(orderForm.stopPrice);
        if (!spx || spx <= 0) {
          rejectOrder('Options stop orders require a trigger price greater than $0.');
          return;
        }
      }
    } else {
      if (['LIMIT', 'STOP_LOSS_LIMIT', 'LIMIT_ON_OPEN'].includes(orderForm.type)) {
        const px = parseFloat(orderForm.price);
        if (!px || px <= 0) {
          rejectOrder('Limit orders require a limit price greater than $0.');
          return;
        }
      }
      if (['STOP_LOSS', 'STOP_LOSS_LIMIT'].includes(orderForm.type)) {
        const spx = parseFloat(orderForm.stopPrice);
        if (!spx || spx <= 0) {
          rejectOrder('Stop orders require a stop trigger price greater than $0.');
          return;
        }
      }
    }
    // Simulated Webull orders are isolated in the paper engine and never reach
    // the live OpenAPI order path, so trading 2FA is reserved for live orders.
    if (require2fa && !isTestMode) {
      setTwoFactorModal({ isVisible: true, orderData: webullTwoFactorOrderDetails() });
    } else {
      setShowConfirmModal(true);
    }
  };

  // Transmit order to Webull OpenAPI
  const handleConfirmSubmit = async (tokenOverride) => {
    setOrderSubmitting(true);
    try {
      const isCashAmountMode = selectedInstrumentType === 'EQUITY' && orderForm.entrustType === 'AMOUNT';
      const payload = {
        test_mode: isTestMode,
        account_id: selectedAccountId,
        symbol: selectedSymbol.trim().toUpperCase(),
        instrument_type: selectedInstrumentType === 'EQUITY' ? selectedSecurityType : selectedInstrumentType,
        option_type: selectedInstrumentType === 'OPTION' ? orderForm.optionType : undefined,
        side: orderForm.side,
        order_type: selectedInstrumentType === 'EVENT' ? 'LIMIT' : orderForm.type,
        quantity: isCashAmountMode ? undefined : Number(orderForm.quantity),
        entrust_type: selectedInstrumentType === 'EQUITY' ? orderForm.entrustType : 'QTY',
        total_cash_amount: isCashAmountMode ? Number(orderForm.totalCashAmount) : undefined,
        limit_price: ['LIMIT', 'STOP_LOSS_LIMIT', 'LIMIT_ON_OPEN'].includes(orderForm.type) || selectedInstrumentType === 'EVENT' ? Number(orderForm.price) : undefined,
        stop_price: ['STOP_LOSS', 'STOP_LOSS_LIMIT'].includes(orderForm.type) ? Number(orderForm.stopPrice) : undefined,
        trailing_type: ['FUTURES', 'EQUITY'].includes(selectedInstrumentType) && orderForm.type === 'TRAILING_STOP_LOSS' ? orderForm.trailingType : undefined,
        trailing_stop_step: ['FUTURES', 'EQUITY'].includes(selectedInstrumentType) && orderForm.type === 'TRAILING_STOP_LOSS' ? Number(orderForm.trailingStopStep) : undefined,
        time_in_force: selectedInstrumentType === 'EVENT' ? 'DAY' : (['TRAILING_STOP_LOSS', 'MARKET_ON_OPEN', 'MARKET_ON_CLOSE', 'LIMIT_ON_OPEN'].includes(orderForm.type) ? 'DAY' : orderForm.timeInForce),
        support_trading_session: ['CRYPTO', 'OPTION', 'FUTURES', 'EVENT'].includes(selectedInstrumentType) ? 'CORE' : orderForm.tradingSession,
        event_outcome: selectedInstrumentType === 'EVENT' ? (orderForm.eventOutcome || 'yes').toLowerCase() : undefined,
        option_underlying_symbol: selectedInstrumentType === 'OPTION' ? selectedSymbol.trim().toUpperCase() : undefined,
        option_strike: selectedInstrumentType === 'OPTION' ? Number(orderForm.optionStrike) : undefined,
        option_expiration: selectedInstrumentType === 'OPTION' ? orderForm.optionExpiration : undefined,
        option_strategy: selectedInstrumentType === 'OPTION' ? orderForm.optionStrategy : undefined,
        option_strategy_width: selectedInstrumentType === 'OPTION' ? orderForm.optionStrategyWidth : undefined,
        option_legs: selectedInstrumentType === 'OPTION' ? orderForm.optionStrategyLegs : undefined,
        algo_type: (selectedInstrumentType === 'EQUITY' && orderForm.isAlgoEnabled) ? orderForm.algoType : undefined,
        algo_start_time: (selectedInstrumentType === 'EQUITY' && orderForm.isAlgoEnabled) ? orderForm.algoStartTime : undefined,
        algo_end_time: (selectedInstrumentType === 'EQUITY' && orderForm.isAlgoEnabled) ? orderForm.algoEndTime : undefined,
        max_target_percent: (selectedInstrumentType === 'EQUITY' && orderForm.isAlgoEnabled && ['TWAP', 'VWAP'].includes(orderForm.algoType)) ? Number(orderForm.maxTargetPercent) : undefined,
        target_vol_percent: (selectedInstrumentType === 'EQUITY' && orderForm.isAlgoEnabled && orderForm.algoType === 'POV') ? Number(orderForm.targetVolPercent) : undefined,
        bracket_take_profit_price: (selectedInstrumentType === 'EQUITY' && orderForm.isBracketEnabled && orderForm.bracketTakeProfitPrice) ? Number(orderForm.bracketTakeProfitPrice) : undefined,
        bracket_stop_loss_price: (selectedInstrumentType === 'EQUITY' && orderForm.isBracketEnabled && orderForm.bracketStopLossPrice) ? Number(orderForm.bracketStopLossPrice) : undefined,
        bracket_stop_loss_limit_price: (selectedInstrumentType === 'EQUITY' && orderForm.isBracketEnabled && orderForm.bracketStopLossLimitPrice) ? Number(orderForm.bracketStopLossLimitPrice) : undefined,
        ...(tokenOverride ? { twofa_token: tokenOverride } : {}),
      };

      const response = await axios.post('/api/webull/orders/place', payload, { withCredentials: true });
      if (response.data?.success) {
        setOrderFeedback({ type: 'success', message: response.data.message || 'Order placed successfully!' });
        setShowConfirmModal(false);
        setOrderForm((prev) => ({
          ...prev,
          quantity: '',
          quoteQuantity: '',
          totalCashAmount: '',
          price: '',
          stopPrice: '',
          trailingStopStep: '',
          bracketTakeProfitPrice: '',
          bracketStopLossPrice: '',
          bracketStopLossLimitPrice: '',
        }));
        if (isTestMode) {
          loadPaperTradingData();
        } else {
          loadOpenOrders(selectedAccountId);
        }
        loadHistory(selectedAccountId);
      } else {
        setOrderFeedback({ type: 'error', message: response.data.message || 'Order placement failed.' });
      }
    } catch (err) {
      if (err.response?.data?.requires_2fa) {
        setShowConfirmModal(false);
        setTwoFactorModal({ isVisible: true, orderData: webullTwoFactorOrderDetails() });
      } else {
        setOrderFeedback({ type: 'error', message: err.response?.data?.message || err.message || 'Failed to place order.' });
      }
    } finally {
      setOrderSubmitting(false);
    }
  };

  const handleComboSubmit = async () => {
    if (!selectedAccountId) {
      setOrderFeedback({ type: 'error', message: 'Please select a Webull account.' });
      return;
    }
    const sym = (comboForm.symbol || '').trim().toUpperCase();
    if (!sym) {
      setOrderFeedback({ type: 'error', message: 'Please enter a stock symbol for the combo order.' });
      return;
    }
    for (let i = 0; i < comboForm.legs.length; i++) {
      const leg = comboForm.legs[i];
      const lqty = parseFloat(leg.quantity);
      if (!lqty || lqty <= 0) {
        setOrderFeedback({ type: 'error', message: `Leg #${i + 1} (${formatComboRole(leg.role)}) requires a positive quantity.` });
        return;
      }
      if (['LIMIT', 'STOP_LOSS_LIMIT', 'LIMIT_ON_OPEN'].includes(leg.order_type)) {
        const lpx = parseFloat(leg.price);
        if (!lpx || lpx <= 0) {
          setOrderFeedback({ type: 'error', message: `Leg #${i + 1} (${formatComboRole(leg.role)}) requires a valid limit price.` });
          return;
        }
      }
      if (['STOP_LOSS', 'STOP_LOSS_LIMIT'].includes(leg.order_type)) {
        const lspx = parseFloat(leg.stopPrice);
        if (!lspx || lspx <= 0) {
          setOrderFeedback({ type: 'error', message: `Leg #${i + 1} (${formatComboRole(leg.role)}) requires a valid stop price.` });
          return;
        }
      }
    }

    setOrderSubmitting(true);
    try {
      const payload = {
        test_mode: isTestMode,
        account_id: selectedAccountId,
        combo_type: comboForm.comboType,
        combo_orders: comboForm.legs.map((leg) => ({
          symbol: sym,
          side: leg.side,
          order_type: leg.order_type,
          combo_type: leg.role,
          quantity: Number(leg.quantity),
          limit_price: ['LIMIT', 'STOP_LOSS_LIMIT', 'LIMIT_ON_OPEN'].includes(leg.order_type) ? Number(leg.price) : undefined,
          stop_price: ['STOP_LOSS', 'STOP_LOSS_LIMIT'].includes(leg.order_type) ? Number(leg.stopPrice) : undefined,
          time_in_force: leg.timeInForce || 'DAY',
          support_trading_session: leg.session || 'CORE',
          entrust_type: 'QTY',
        })),
      };
      const response = await axios.post('/api/webull/orders/place', payload, { withCredentials: true });
      if (response.data?.success) {
        setOrderFeedback({ type: 'success', message: response.data.message || 'Webull combo order submitted successfully!' });
        if (isTestMode) {
          loadPaperTradingData();
          loadOpenOrders('TEST_PAPER_ACCOUNT');
        } else {
          loadOpenOrders(selectedAccountId);
        }
        loadHistory(selectedAccountId);
        setActiveTab('open_orders');
      } else {
        setOrderFeedback({ type: 'error', message: response.data?.message || 'Failed to submit combo order.' });
      }
    } catch (err) {
      setOrderFeedback({ type: 'error', message: err.response?.data?.message || err.message || 'Webull combo order failed.' });
    } finally {
      setOrderSubmitting(false);
    }
  };

  const handleTwoFactorVerify = async (code) => {
    const res = await axios.post('/api/trading/2fa/verify', { code }, { withCredentials: true });
    if (res.data?.success && res.data?.token) {
      setTwoFactorModal({ isVisible: false, orderData: null });
      await handleConfirmSubmit(res.data.token);
    } else {
      throw new Error(res.data?.error || 'Invalid 2FA code');
    }
  };

  const openCancelModalForOrder = (order) => {
    const accountId = String(order._webull_account_id || order.webull_account_id || selectedAccountId || '');
    const account = accounts.find((candidate) => String(candidate.account_id) === accountId) || activeAccount;
    const accountName = account?.account_label || account?.account_name || account?.account_type || 'Webull account';
    const accountMask = account?.account_id_masked || (account?.account_id ? `••••${String(account.account_id).slice(-4)}` : '');
    setCancelModal({
      isVisible: true,
      order: {
        ...order,
        cancel_provider: 'Webull',
        cancel_account_label: accountMask ? `${accountName} (${accountMask})` : accountName,
      },
      error: '',
      loading: false,
    });
  };

  const closeCancelModal = () => {
    if (!cancelModal.loading) setCancelModal({ isVisible: false, order: null, error: '', loading: false });
  };

  // Webull cancellations use the same theme-aware 2FA confirmation modal as
  // Binance.US. The backend independently verifies the entered code.
  const handleCancelOpenOrder = async (twoFactorCode) => {
    const order = cancelModal.order;
    if (!order) return;
    setCancelModal((current) => ({ ...current, loading: true, error: '' }));
    setCancellingOrderId(order.id);
    try {
      const response = await axios.post('/api/webull/orders/cancel', {
        account_id: order._webull_account_id || order.webull_account_id || selectedAccountId,
        order_id: order.id,
        client_order_id: order.client_order_id,
        two_factor_code: twoFactorCode,
      }, { withCredentials: true });
      if (response.data?.success) {
        setOrderFeedback({ type: 'success', message: response.data.message || 'Order cancelled successfully.' });
        setCancelModal({ isVisible: false, order: null, error: '', loading: false });
        loadOpenOrders(selectedAccountId);
      } else {
        setCancelModal((current) => ({ ...current, loading: false, error: response.data?.message || 'Unable to cancel order.' }));
      }
    } catch (err) {
      setCancelModal((current) => ({
        ...current,
        loading: false,
        error: err.response?.data?.message || err.response?.data?.error || 'Order cancellation failed.',
      }));
    } finally {
      setCancellingOrderId(null);
    }
  };

  const handleSelectHolding = (holding) => {
    if (!holding) return;
    const isOption = String(holding.instrument_type || '').toUpperCase() === 'OPTION';
    const isFutures = ['FUTURE', 'FUTURES'].includes(String(holding.instrument_type || '').toUpperCase());
    const isEvent = String(holding.instrument_type || '').toUpperCase() === 'EVENT';
    const isCrypto = /crypto|coin|token/i.test(holding.instrument_type || '');
    const isShortPosition = String(holding.position_side || holding.side || '').toUpperCase() === 'SHORT';

    if (holding.account_id) setSelectedAccountId(String(holding.account_id));
    const targetSymbol = isOption || isEvent
      ? (holding.underlying_symbol || String(holding.symbol || '').replace(/\s+(YES|NO)$/i, ''))
      : holding.symbol;
    setSelectedSymbol(targetSymbol);
    assetSymbolMemoryRef.current[isOption ? 'OPTION' : isFutures ? 'FUTURES' : isEvent ? 'EVENT' : isCrypto ? 'CRYPTO' : 'EQUITY'] = targetSymbol;
    setSelectedOptionHoldingId(isOption ? String(holding.id || '') : '');

    const rawQty = holding.available_quantity ?? holding.quantity ?? holding.amount;
    const holdingQuantity = nonNegativeNumber(rawQty);
    const rawPx = holding.current_price ?? holding.last_price ?? holding.cost_price;
    const holdingPrice = nonNegativeNumber(rawPx);

    if (holdingPrice > 0) {
      setLivePrice(holdingPrice);
    }

    if (isOption) {
      setSelectedInstrumentType('OPTION');
      setSelectedSecurityType('OPTION');
      const optStrike = holding.option_strike ? String(holding.option_strike) : '';
      const optExp = holding.option_expiration || '';
      const optType = holding.option_type || 'CALL';
      const formattedQty = holdingQuantity > 0 ? String(holdingQuantity) : '1';
      const formattedPx = holdingPrice > 0 ? String(holdingPrice) : '';
      setOrderForm((prev) => ({
        ...prev,
        side: isShortPosition && isTestMode ? 'BUY_TO_CLOSE' : 'SELL',
        type: 'LIMIT',
        optionType: optType,
        optionStrike: optStrike,
        optionExpiration: optExp,
        price: formattedPx,
        quantity: formattedQty,
        quoteQuantity: optionOrderValueText(formattedQty, formattedPx),
        stopPrice: '',
        trailingStopStep: '',
      }));
    } else if (isFutures) {
      const contractSymbol = String(holding.symbol || '').toUpperCase();
      setSelectedInstrumentType('FUTURES');
      setSelectedSecurityType('FUTURES');
      setSelectedFuturesContract({
        symbol: contractSymbol,
        name: holding.name || contractSymbol,
        expiration_date: holding.expiration_date,
      });
      setFuturesContractInput(contractSymbol);
      const formattedQty = holdingQuantity > 0 ? String(holdingQuantity) : '1';
      setOrderForm((prev) => ({
        ...prev,
        side: 'SELL',
        type: 'MARKET',
        price: '',
        stopPrice: '',
        trailingStopStep: '',
        quantity: formattedQty,
        quoteQuantity: '',
      }));
    } else if (isEvent) {
      setSelectedInstrumentType('EVENT');
      setSelectedSecurityType('EVENT');
      const outcome = String(holding.event_outcome || String(holding.symbol || '').match(/\s+(YES|NO)$/i)?.[1] || 'yes').toLowerCase();
      const formattedQty = holdingQuantity > 0 ? String(holdingQuantity) : '1';
      const formattedPx = holdingPrice > 0 ? String(holdingPrice) : '';
      setOrderForm((prev) => ({
        ...prev,
        side: 'SELL',
        type: 'LIMIT',
        price: formattedPx,
        quantity: formattedQty,
        eventOutcome: outcome,
        quoteQuantity: formattedPx ? (Number(formattedQty) * Number(formattedPx)).toFixed(2) : '',
        stopPrice: '',
        trailingStopStep: '',
      }));
      axios.get('/api/webull/events/markets', {
        params: { symbol: targetSymbol },
        withCredentials: true,
      }).then((response) => {
        const market = response.data?.markets?.[0];
        if (!market) return;
        setSelectedEventMarket(market);
        setSelectedEventCategory(market.category_code || market.category_id || selectedEventCategory);
        setEventMarkets((current) => current.some((item) => item.symbol === market.symbol) ? current : [market, ...current]);
        const bid = eventQuoteFor(market, outcome, 'SELL');
        if (bid != null) {
          setOrderForm((prev) => ({
            ...prev,
            price: String(bid),
            quoteQuantity: Number(prev.quantity) > 0 ? (Number(prev.quantity) * bid).toFixed(2) : '',
          }));
        }
      }).catch(() => setEventMessage('Unable to refresh the selected Event Contract position quote.'));
    } else {
      setSelectedInstrumentType(isCrypto ? 'CRYPTO' : 'EQUITY');
      setSelectedSecurityType(isCrypto ? 'CRYPTO' : (String(holding.instrument_type || '').toUpperCase() === 'ETF' ? 'ETF' : 'EQUITY'));
      const formattedQty = holdingQuantity > 0 ? String(holdingQuantity) : '';
      const formattedPx = holdingPrice > 0 ? (holdingPrice >= 1 ? holdingPrice.toFixed(2) : holdingPrice.toFixed(4)) : '';
      const estTotal = (holdingQuantity > 0 && holdingPrice > 0) ? (holdingQuantity * holdingPrice).toFixed(2) : '';
      setOrderForm((prev) => ({
        ...prev,
        side: isShortPosition && isTestMode ? 'BUY_TO_CLOSE' : 'SELL',
        type: isCrypto ? 'MARKET' : 'LIMIT',
        price: formattedPx,
        quantity: formattedQty,
        quoteQuantity: estTotal,
        stopPrice: '',
        trailingStopStep: '',
      }));
    }

    setBalancePercentage(100);
    setOrderValidationError('');
    setActiveTab('order');

    // Trigger visual accent pulse and smoothly scroll directly to the Order Ticket panel
    setTicketFlash(true);
    setTimeout(() => setTicketFlash(false), 1800);
    setTimeout(() => {
      if (orderTicketRef.current) {
        orderTicketRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
      } else {
        const el = document.getElementById('webull-order-ticket-section') || document.querySelector('.trading-order-panel');
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      }
    }, 60);
  };

  const modeOpenOrders = useMemo(
    () => openOrders.filter((order) => orderIsPaper(order) === isTestMode),
    [openOrders, isTestMode]
  );
  const modeHistory = useMemo(
    () => history.filter((order) => orderIsPaper(order) === isTestMode),
    [history, isTestMode]
  );
  const displayOpenOrders = useMemo(() => modeOpenOrders.filter((order) => OPEN_STATUSES.has(String(order.status).toUpperCase()) || !order.status), [modeOpenOrders]);

  useEffect(() => {
    if (activeTab !== 'open_orders' || !selectedAccountId) return undefined;
    const refresh = () => loadOpenOrders(selectedAccountId, isTestMode);
    refresh();
    const timer = window.setInterval(refresh, 30000);
    return () => window.clearInterval(timer);
  }, [activeTab, selectedAccountId, isTestMode]);

  useEffect(() => {
    if (activeTab !== 'open_orders') return undefined;
    let cancelled = false;
    const optionOrders = displayOpenOrders.filter((order) => optionContractDetails(order).isOption);

    const refreshClosePnl = async () => {
      const pending = {};
      const filledOrders = [];
      optionOrders.forEach((order) => {
        const filledQuantity = Number(order.filled_quantity || 0);
        if (filledQuantity <= 0) pending[order.id] = { status: 'not_filled' };
        else {
          const option = optionContractDetails(order);
          const optionType = String(option.optionType || '').toUpperCase();
          const hasSingleContractIdentity = Boolean(
            option.symbol && /^\d{4}-\d{2}-\d{2}$/.test(option.expiration)
            && Number.isFinite(Number(option.strike)) && ['CALL', 'PUT'].includes(optionType)
          );
          if (!hasSingleContractIdentity) {
            pending[order.id] = { status: 'unavailable', message: 'A single filled option contract identity is required.' };
          } else {
            pending[order.id] = { status: 'loading' };
            filledOrders.push(order);
          }
        }
      });
      if (!cancelled) setOptionClosePnlByOrder(pending);
      if (!filledOrders.length) return;

      const groups = new Map();
      filledOrders.forEach((order) => {
        const option = optionContractDetails(order);
        const key = `${option.symbol}|${option.expiration}`;
        if (!groups.has(key)) groups.set(key, { symbol: option.symbol, expiration: option.expiration, orders: [] });
        groups.get(key).orders.push({ order, option });
      });

      const results = { ...pending };
      await Promise.all([...groups.values()].map(async (group) => {
        try {
          const response = await axios.get('/api/webull/options/chain', {
            params: { symbol: group.symbol, expiration: group.expiration },
            withCredentials: true,
          });
          const chain = response.data?.chain || [];
          group.orders.forEach(({ order, option }) => {
            const strikeRow = chain.find((row) => Math.abs(Number(row.strike) - Number(option.strike)) <= OPTION_STRIKE_EPSILON);
            const quote = strikeRow?.[String(option.optionType).toUpperCase() === 'PUT' ? 'put' : 'call'];
            const side = String(order.side || '').toUpperCase();
            const isLong = ['BUY', 'BUY_TO_OPEN'].includes(side);
            const closeSide = isLong ? 'bid' : 'ask';
            const closePrice = Number(quote?.[closeSide]);
            const entryPrice = Number(
              order.avg_fill_price ?? order.average_fill_price ?? order.filled_price
              ?? order.avg_price ?? order.average_price
            );
            const filledQuantity = Number(order.filled_quantity || 0);
            if (!(closePrice >= 0) || !(entryPrice >= 0) || filledQuantity <= 0) {
              results[order.id] = { status: 'unavailable', message: 'A filled basis or executable close quote is unavailable.' };
              return;
            }
            const pnl = (isLong ? closePrice - entryPrice : entryPrice - closePrice) * filledQuantity * 100;
            results[order.id] = { status: 'available', pnl, closePrice, closeSide };
          });
        } catch (requestError) {
          group.orders.forEach(({ order }) => {
            results[order.id] = {
              status: 'unavailable',
              message: requestError.response?.data?.message || 'Unable to refresh the option close quote.',
            };
          });
        }
      }));
      if (!cancelled) setOptionClosePnlByOrder(results);
    };

    refreshClosePnl();
    const timer = window.setInterval(refreshClosePnl, 30000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeTab, displayOpenOrders]);
  const sortedHistory = useMemo(() => [...modeHistory].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''))), [modeHistory]);
  const historyPages = Math.max(1, Math.ceil(sortedHistory.length / historyPageSize));
  const paginatedHistory = useMemo(() => sortedHistory.slice((historyPage - 1) * historyPageSize, historyPage * historyPageSize), [sortedHistory, historyPage, historyPageSize]);
  useEffect(() => { if (historyPage > historyPages) setHistoryPage(historyPages); }, [historyPage, historyPages]);
  const analyzableHoldings = useMemo(() => modeHoldings.filter((holding) => ['CRYPTO', 'STOCK', 'EQUITY', 'ETF', 'OPTION', 'FUTURES'].includes(String(holding.instrument_type || '').toUpperCase())), [modeHoldings]);
  const availableStockSymbols = useMemo(() => {
    const stocks = modeHoldings
      .filter((h) => !/crypto|coin|token/i.test(h.instrument_type || '') && !['OPTION', 'FUTURES', 'EVENT'].includes(String(h.instrument_type || '').toUpperCase()))
      .map((h) => (h.underlying_symbol || h.symbol || '').toUpperCase().trim())
      .filter(Boolean);
    return Array.from(new Set(['AAPL', 'NVDA', 'SPY', 'TSLA', 'AMD', 'MSFT', ...stocks]));
  }, [modeHoldings]);

  const availableTraditional = useMemo(() => {
    const fromHoldings = modeHoldings
      .filter((h) => !/crypto|coin|token/i.test(h.instrument_type || '') && !['OPTION', 'FUTURES', 'EVENT'].includes(String(h.instrument_type || '').toUpperCase()) && h.symbol)
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
    (DEFAULT_STOCKS || []).forEach((item) => {
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
  }, [modeHoldings]);

  const handleSelectOptionContract = (contractData) => {
    if (contractData.symbol && contractData.symbol !== selectedSymbol) {
      setSelectedSymbol(contractData.symbol);
    }
    setSelectedOptionHoldingId('');
    const premium = nonNegativeNumber(contractData.price);
    if (Number(contractData.underlyingPrice) > 0) {
      setOptionUnderlyingPrice(Number(contractData.underlyingPrice));
    }
    if (premium > 0) {
      setLivePrice(premium);
    }
    setOrderForm((prev) => {
      const quantity = prev.quantity && Number(prev.quantity) > 0 ? prev.quantity : '1';
      return {
        ...prev,
        optionType: contractData.optionType || 'CALL',
        optionStrike: String(contractData.strike || ''),
        optionExpiration: contractData.expiration || '',
        optionStrategy: contractData.optionStrategy || 'SINGLE',
        optionStrategyWidth: contractData.strategyWidth || 'auto',
        optionStrategyLegs: contractData.strategyLegs || [],
        price: premium > 0 ? String(contractData.price) : '',
        side: contractData.side || 'BUY',
        quantity,
        quoteQuantity: optionOrderValueText(quantity, premium),
        stopPrice: '',
      };
    });
    setOrderValidationError('');
  };

  const handlePayoffChartStrikeSelect = (strike) => {
    const requestedStrike = Number(strike);
    if (!(requestedStrike > 0)) return;
    setChartStrikeRequest((previous) => ({
      id: (previous?.id || 0) + 1,
      strike: requestedStrike,
    }));
  };

  const handleTicketSideChange = (nextSide) => {
    const eventSuggestedPrice = selectedInstrumentType === 'EVENT'
      ? eventQuoteFor(selectedEventMarket, orderForm.eventOutcome, nextSide)
      : null;
    if (selectedInstrumentType === 'EVENT') eventAutoPriceRef.current = true;
    setOrderForm((prev) => {
      const shouldReverseOptionLegs = (
        selectedInstrumentType === 'OPTION'
        && prev.side !== nextSide
        && Array.isArray(prev.optionStrategyLegs)
        && prev.optionStrategyLegs.length > 0
      );
      return {
        ...prev,
        side: nextSide,
        price: selectedInstrumentType === 'EVENT'
          ? (eventSuggestedPrice != null ? String(eventSuggestedPrice) : '')
          : prev.price,
        quoteQuantity: selectedInstrumentType === 'EVENT' && eventSuggestedPrice != null && Number(prev.quantity) > 0
          ? (Number(prev.quantity) * eventSuggestedPrice).toFixed(2)
          : prev.quoteQuantity,
        timeInForce: selectedInstrumentType === 'OPTION' && nextSide === 'SELL' ? 'DAY' : prev.timeInForce,
        optionStrategyLegs: shouldReverseOptionLegs
          ? prev.optionStrategyLegs.map((leg) => ({ ...leg, side: String(leg.side).toUpperCase() === 'BUY' ? 'SELL' : 'BUY' }))
          : prev.optionStrategyLegs,
      };
    });
    setBalancePercentage(0);
    setOrderValidationError('');
  };
  useEffect(() => {
    if (!selectedSignalHolding && analyzableHoldings.length) setSelectedSignalHolding(`${analyzableHoldings[0].symbol}|${analyzableHoldings[0].instrument_type}`);
  }, [analyzableHoldings, selectedSignalHolding]);

  const createSignal = async () => {
    const [symbol, instrument_type] = selectedSignalHolding.split('|');
    if (!symbol) return;
    setSignalBusy(true); setSignalMessage('');
    try {
      const response = await axios.post('/api/webull/ai-analysis', { symbol, instrument_type }, { withCredentials: true });
      setSignals((current) => [response.data.signal, ...current]);
      setSignalMessage(response.data.message || 'Stored a new read-only signal.');
    } catch (requestError) {
      setSignalMessage(requestError.response?.data?.message || 'Unable to create the Webull signal.');
    } finally { setSignalBusy(false); }
  };

  const saveSignalSettings = async () => {
    setSignalBusy(true); setSignalMessage('');
    try {
      const response = await axios.put('/api/webull/ai-settings', signalSettings, { withCredentials: true });
      setSignalSettings((current) => ({ ...current, ...(response.data?.settings || {}) }));
      setSignalMessage('Webull AI schedule settings saved. Scheduling is opt-in and remains read-only.');
    } catch (requestError) {
      setSignalMessage(requestError.response?.data?.message || 'Unable to save Webull AI settings.');
    } finally { setSignalBusy(false); }
  };

  return (
    <div className="trading-page" style={{ padding: '20px', maxWidth: '1500px', margin: '0 auto' }}>
      <div className="trading-header" style={{ marginBottom: '18px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
        <div>
          <h1 style={{ fontSize: '2rem', margin: 0, display: 'flex', alignItems: 'center', gap: '10px' }}>
            <WebullLogo size={32} /> Webull Trading
          </h1>
          <p style={{ margin: '6px 0 0', color: '#94a3b8' }}>
            {isTestMode
              ? 'Webull Paper Trading Mode — practice trading across all assets with simulated funds & real-time live quotes.'
              : 'Execute orders, manage open positions, and review signals via Webull OpenAPI.'}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
          {isTestMode && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setShowDepositModal(true)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
                color: '#ffffff',
                border: 'none',
                padding: '8px 16px',
                borderRadius: '8px',
                fontWeight: 600,
                cursor: 'pointer',
                boxShadow: '0 2px 8px rgba(16, 185, 129, 0.4)'
              }}
            >
              💰 Deposit Fake Money
            </button>
          )}
          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              cursor: 'pointer',
              color: isLightMode ? '#2d3748' : '#e2e8f0',
              userSelect: 'none',
              margin: 0,
              fontSize: '0.95rem',
              fontWeight: 600
            }}
            title="Toggle Webull Test Mode (Paper Trading with live quotes)"
          >
            <input
              type="checkbox"
              checked={isTestMode}
              onChange={(e) => handleToggleTestMode(e.target.checked)}
              style={{ position: 'absolute', opacity: 0, pointerEvents: 'none' }}
            />
            {isTestMode ? <FaToggleOn size={30} color="#4fd1c5" /> : <FaToggleOff size={30} color="#6c757d" />}
            Test Mode
          </label>
        </div>
      </div>

      {isTestMode && (
        <div
          style={{
            marginBottom: '16px',
            padding: '12px 18px',
            borderRadius: '8px',
            background: 'rgba(79, 209, 197, 0.12)',
            border: '1px solid rgba(79, 209, 197, 0.35)',
            color: '#4fd1c5',
            display: 'flex',
            alignItems: 'center',
            gap: '12px'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontWeight: 600 }}>
            <span style={{ fontSize: '1.2rem' }}>🧪</span>
            <span>
              TEST MODE ACTIVE — Simulated Webull Paper Account (${number(cashBalance)} USD available cash). Trades fill against real live market quotes with zero financial risk.
            </span>
          </div>
        </div>
      )}

      {error && <div className="modern-real-warning" style={{ marginBottom: '16px' }}>⚠️ {error}</div>}
      {orderFeedback.message && (
        <div
          className={orderFeedback.type === 'error' ? 'modern-real-warning' : 'modern-real-success'}
          style={{
            marginBottom: '16px',
            padding: '12px 16px',
            borderRadius: '8px',
            background: orderFeedback.type === 'error' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.15)',
            color: orderFeedback.type === 'error' ? '#ef4444' : '#10b981',
            border: `1px solid ${orderFeedback.type === 'error' ? 'rgba(239, 68, 68, 0.3)' : 'rgba(16, 185, 129, 0.3)'}`,
          }}
        >
          {orderFeedback.type === 'error' ? '⚠️' : '✅'} {orderFeedback.message}
        </div>
      )}

      {/* Navigation Tabs */}
      <div className="trading-tabs">
        <button className={`tab-button ${activeTab === 'order' ? 'active' : ''}`} onClick={() => setActiveTab('order')}>
          📝 <span className="tab-text">Place Order</span>
        </button>
        <button className={`tab-button ${activeTab === 'combo' ? 'active' : ''}`} onClick={() => setActiveTab('combo')}>
          🔗 <span className="tab-text">Combo Orders (OTO/OCO)</span>
        </button>
        <button className={`tab-button ${activeTab === 'open_orders' ? 'active' : ''}`} onClick={() => setActiveTab('open_orders')}>
          ⏳ <span className="tab-text">Open Orders</span>
          {displayOpenOrders.length > 0 && <span className="tab-badge">{displayOpenOrders.length}</span>}
        </button>
        <button className={`tab-button ${activeTab === 'history' ? 'active' : ''}`} onClick={() => setActiveTab('history')}>
          📜 <span className="tab-text">Order History</span>
        </button>
        <button className={`tab-button ${activeTab === 'trade_chart' ? 'active' : ''}`} onClick={() => setActiveTab('trade_chart')}>
          📈 <span className="tab-text">Trade Chart</span>
        </button>
        {!isTestMode && (
          <button className={`tab-button ${activeTab === 'ai_analysis' ? 'active' : ''}`} onClick={() => setActiveTab('ai_analysis')}>
            🤖 <span className="tab-text">AI Analysis</span>
          </button>
        )}
      </div>

      <div className="trading-content">
        {loading ? (
          <div className="empty-state"><p>Loading Webull data…</p></div>
        ) : (
          <>
            {/* PLACE ORDER TAB */}
            {activeTab === 'order' && (
              <div className="order-form-container">
                {/* 1. Full-Width TradingView Advanced Chart with Webull Account & Instrument Selector */}
                <WebullTradingViewChart
                  symbol={selectedSymbol}
                  instrumentType={selectedInstrumentType}
                  onInstrumentChange={handleInstrumentChange}
                  accounts={displayAccounts}
                  selectedAccountId={isTestMode ? 'TEST_PAPER_ACCOUNT' : selectedAccountId}
                  onAccountChange={handleAccountChange}
                  defaultAccountId={defaultAccountId}
                  onSetDefaultAccount={saveDefaultAccount}
                  savingDefaultAccount={savingDefaultAccount}
                  allowDefaultAccount={!isTestMode}
                  holdings={modeHoldings}
                  isLightMode={isLightMode}
                  accountOnly={selectedInstrumentType === 'EVENT'}
                />

                {/* 2. Order Ticket Container (with scroll ref and highlight pulse) */}
                <div
                  id="webull-order-ticket-section"
                  ref={orderTicketRef}
                  style={{
                    scrollMarginTop: '80px',
                    transition: 'box-shadow 0.4s ease, border-color 0.4s ease',
                    borderRadius: '16px',
                    padding: '8px',
                    margin: '-8px',
                    ...(ticketFlash
                      ? {
                          boxShadow: '0 0 35px rgba(56, 189, 248, 0.75)',
                          border: '2px solid #38bdf8',
                        }
                      : { border: '2px solid transparent' }),
                  }}
                >
                  {/* Redesigned Order Placement Header Cards (matching Binance.US) */}
                  <div className="trading-order-header-cards">
                  {/* Selected Asset Available Card */}
                  <div className="trading-asset-card">
                    <CryptoIcon symbol={selectedSymbol} size={32} />
                    <div className="trading-asset-card-details">
                      <span className="trading-asset-card-label">{selectedSymbol} Available</span>
                      <span className="trading-asset-card-value">
                        {number(heldQuantity, selectedInstrumentType === 'CRYPTO' ? 6 : 2)}{' '}
                        <small>{selectedInstrumentType === 'CRYPTO' ? selectedSymbol.replace(/USD$/, '') : ['OPTION', 'FUTURES', 'EVENT'].includes(selectedInstrumentType) ? 'Contracts' : 'Shares'}</small>
                      </span>
                      {heldValue > 0 && (
                        <span className="trading-asset-card-sub">
                          ≈ ${number(heldValue)} USD
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Cash / Buying Power Card */}
                  <div className="trading-asset-card">
                    <CryptoIcon symbol="USD" size={32} />
                    <div className="trading-asset-card-details" style={{ width: '100%' }}>
                      <span className="trading-asset-card-label">USD Cash Available</span>
                      <span className="trading-asset-card-value">
                        ${number(cashBalance)} <small>USD</small>
                      </span>
                      <span className="trading-asset-card-sub">
                        {activeAccount?.account_label || activeAccount?.account_name || 'Webull Account'}{' '}
                        ({activeAccount?.account_id_masked || (selectedAccountId ? `••••${String(selectedAccountId).slice(-4)}` : '')}) · Ready to trade
                      </span>
                    </div>
                  </div>

                  {/* Real-time Price Card */}
                  <div className="trading-asset-card trading-price-card">
                    <div className="trading-price-header">
                      <span className="trading-asset-card-label">Real-time Price</span>
                      <span className="live-pulse-dot" />
                    </div>
                    <div className="trading-asset-card-value price-highlight">
                      {livePrice > 0 ? `$${number(livePrice, livePrice >= 1 ? 2 : 4)}` : 'Market Price'}{' '}
                      <small>USD</small>
                    </div>
                    <span className="trading-asset-card-sub">Instant Market Rate</span>
                  </div>
                </div>

                {/* 3. Redesigned Modern Order Panel (matching Binance.US) */}
                <form onSubmit={handleOrderSubmit} className="trading-order-panel" noValidate>
                  {/* Asset Class Switcher — asset lanes follow the selected Webull account. */}
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap', marginBottom: '14px' }}>
                    <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-secondary, #94a3b8)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                      Asset Class:
                    </span>
                    <div style={{ display: 'inline-flex', background: 'rgba(0,0,0,0.35)', padding: '3px', borderRadius: '8px', gap: '4px' }}>
                      <button
                        type="button"
                        onClick={() => handleAssetClassChange('EQUITY')}
                        disabled={assetClassDisabled('EQUITY')}
                        title={assetClassDisabled('EQUITY') ? 'Stocks & ETFs are unavailable in a Crypto Webull account.' : 'Trade stocks and ETFs'}
                        style={assetClassButtonStyle('EQUITY', 'linear-gradient(135deg, #3b82f6, #2563eb)')}
                      >
                        🏛️ Equities &amp; ETFs
                      </button>
                      <button
                        type="button"
                        onClick={() => handleAssetClassChange('CRYPTO')}
                        disabled={assetClassDisabled('CRYPTO')}
                        title={assetClassDisabled('CRYPTO') ? 'Crypto is available only in a Crypto Webull account.' : 'Trade Webull crypto'}
                        style={assetClassButtonStyle('CRYPTO', 'linear-gradient(135deg, #f59e0b, #d97706)')}
                      >
                        🪙 Crypto
                      </button>
                      <button
                        type="button"
                        onClick={() => handleAssetClassChange('OPTION')}
                        disabled={assetClassDisabled('OPTION')}
                        title={assetClassDisabled('OPTION') ? 'Options are unavailable in a Crypto Webull account.' : 'Trade calls and puts'}
                        style={assetClassButtonStyle('OPTION', 'linear-gradient(135deg, #8b5cf6, #7c3aed)')}
                      >
                        ⚡ Options (Calls &amp; Puts)
                      </button>
                      <button
                        type="button"
                        onClick={() => handleAssetClassChange('FUTURES')}
                        disabled={assetClassDisabled('FUTURES')}
                        title={assetClassDisabled('FUTURES') ? 'Futures are unavailable in a Crypto Webull account.' : 'Trade Webull futures'}
                        style={assetClassButtonStyle('FUTURES', 'linear-gradient(135deg, #0f766e, #0d9488)')}
                      >
                        🏁 Futures
                      </button>
                      <button
                        type="button"
                        onClick={() => handleAssetClassChange('EVENT')}
                        disabled={assetClassDisabled('EVENT')}
                        title={assetClassDisabled('EVENT') ? 'Event Contracts are unavailable in a Crypto Webull account.' : 'Trade Webull binary event contracts'}
                        style={assetClassButtonStyle('EVENT', 'linear-gradient(135deg, #ec4899, #db2777)')}
                      >
                        🎯 Event Contracts
                      </button>
                    </div>
                  </div>

                  {selectedInstrumentType === 'FUTURES' && (
                    <div style={{ background: 'rgba(13, 148, 136, 0.12)', border: '1px solid rgba(45, 212, 191, 0.36)', borderRadius: '8px', padding: '14px', marginBottom: '14px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', alignItems: 'center', flexWrap: 'wrap', marginBottom: '8px' }}>
                        <span style={{ fontSize: '13px', fontWeight: 700, color: '#5eead4' }}>🏁 Webull Futures Contract Setup</span>
                        <button type="button" className="btn btn-sm btn-secondary" onClick={loadFuturesCatalog} disabled={futuresLoading}>
                          {futuresLoading ? 'Loading…' : 'Refresh products'}
                        </button>
                      </div>
                      <p style={{ margin: '0 0 12px', color: '#99f6e4', fontSize: '12px', lineHeight: 1.45 }}>
                        Enter an exact Webull futures contract code (for example, ESZ5), then select the returned contract. Orders use whole contracts only; Webull verifies futures permission and margin before accepting the order.
                      </p>
                      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(180px, 1fr) auto', gap: '8px', alignItems: 'end' }}>
                        <div>
                          <label className="order-field-label" htmlFor="futuresContract">Futures Contract Code</label>
                          <input
                            id="futuresContract"
                            type="text"
                            value={futuresContractInput}
                            onChange={(event) => {
                              setFuturesContractInput(event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''));
                              setSelectedFuturesContract(null);
                              setFuturesContracts([]);
                              setFuturesMessage('');
                            }}
                            placeholder="e.g. ESZ5"
                            className="order-styled-input"
                            autoComplete="off"
                          />
                        </div>
                        <button type="button" className="btn btn-primary" onClick={lookupFuturesContracts} disabled={futuresLoading || !futuresContractInput.trim()}>
                          Find Contract
                        </button>
                      </div>
                      {futuresCatalog.products.length > 0 && (
                        <div style={{ marginTop: '10px' }}>
                          <label className="order-field-label" htmlFor="futuresProduct">Webull Product Codes</label>
                          <select
                            id="futuresProduct"
                            className="order-styled-input"
                            value=""
                            onChange={(event) => {
                              const code = event.target.value;
                              if (code) setFuturesContractInput(code);
                            }}
                          >
                            <option value="">Choose a product code as a starting point…</option>
                            {futuresCatalog.products.map((product, index) => {
                              const code = product.product_code || product.symbol;
                              return code ? <option key={`${code}-${index}`} value={code}>{code} — {product.name || 'Webull futures product'}</option> : null;
                            })}
                          </select>
                        </div>
                      )}
                      {futuresContracts.length > 1 && (
                        <div style={{ marginTop: '12px', display: 'grid', gap: '6px' }}>
                          <span className="order-field-label">Matching Webull Contracts</span>
                          {futuresContracts.map((contract, index) => (
                            <button
                              key={`${contract.symbol || contract.product_code}-${index}`}
                              type="button"
                              onClick={() => selectFuturesContract(contract)}
                              style={{ textAlign: 'left', padding: '9px 11px', borderRadius: '6px', border: `1px solid ${selectedFuturesContract?.symbol === contract.symbol ? '#2dd4bf' : 'rgba(94,234,212,.24)'}`, background: selectedFuturesContract?.symbol === contract.symbol ? 'rgba(13,148,136,.25)' : 'rgba(0,0,0,.2)', color: '#e2e8f0', cursor: 'pointer' }}
                            >
                              <strong>{contract.symbol || contract.product_code}</strong> · {contract.name || 'Webull futures contract'}{contract.expiration_date ? ` · expires ${contract.expiration_date}` : ''}
                            </button>
                          ))}
                        </div>
                      )}
                      {selectedFuturesContract && (
                        <div style={{ marginTop: '12px', padding: '9px 11px', borderRadius: '6px', background: 'rgba(0,0,0,.24)', color: '#ccfbf1', fontSize: '12px', lineHeight: 1.55 }}>
                          <strong>{selectedFuturesContract.symbol}</strong> · {selectedFuturesContract.name || 'Selected Webull futures contract'}
                          {selectedFuturesContract.exchange ? ` · ${selectedFuturesContract.exchange}` : ''}
                          {selectedFuturesContract.expiration_date ? ` · expires ${selectedFuturesContract.expiration_date}` : ''}
                          {selectedFuturesContract.contract_multiplier ? ` · multiplier ${selectedFuturesContract.contract_multiplier}` : ''}
                          {selectedFuturesContract.tick_size ? ` · tick ${selectedFuturesContract.tick_size}` : ''}
                        </div>
                      )}
                      {futuresMessage && <p className="option-ticket-status" role="status">⚠️ {futuresMessage}</p>}
                    </div>
                  )}

                  {/* Webull Event Contract Setup (When EVENT selected) */}
                  {selectedInstrumentType === 'EVENT' && (
                    <div className="event-contract-card">
                      <div className="event-contract-card-header">
                        <span className="event-contract-card-title">
                          🎯 Webull Event Contract Setup
                        </span>
                        <span className={`event-market-status status-${eventTradableStatus.toLowerCase() || 'unknown'}`}>
                          {eventStatusLabel}
                        </span>
                      </div>

                      <div className="event-contract-selector-grid">
                        <div>
                          <label className="order-field-label">Event Category</label>
                          <select
                            value={selectedEventCategory}
                            onChange={(e) => handleEventCategoryChange(e.target.value)}
                            className="order-styled-input"
                            disabled={eventLoading && !eventCategories.length}
                          >
                            {eventCategories.map((cat) => (
                              <option key={cat.category_id || cat.category_code} value={cat.category_code || cat.category_id}>
                                {cat.name}
                              </option>
                            ))}
                          </select>
                        </div>

                        <div className="event-market-combobox" ref={eventMarketSelectorRef}>
                          <label className="order-field-label" htmlFor="event-market-search">Select Event Market</label>
                          <div className="event-market-search-row">
                            <input
                              id="event-market-search"
                              type="search"
                              value={eventMarketQuery}
                              onChange={(event) => {
                                setEventMarketQuery(event.target.value);
                                setEventMarketMenuOpen(true);
                              }}
                              onFocus={() => setEventMarketMenuOpen(true)}
                              placeholder="Search every contract by title or symbol"
                              className="order-styled-input event-market-search-input"
                              autoComplete="off"
                              role="combobox"
                              aria-expanded={eventMarketMenuOpen}
                              aria-controls="event-market-results"
                            />
                            <button
                              type="button"
                              className="event-market-menu-toggle"
                              onClick={() => setEventMarketMenuOpen((open) => !open)}
                              aria-label="Show Event Contract markets"
                            >
                              ▾
                            </button>
                          </div>
                          {eventMarketMenuOpen && (
                            <div className="event-market-results" id="event-market-results" role="listbox">
                              <div className="event-market-results-heading">
                                <span>{eventMarketQuery.trim() ? `${eventTotalMatches} matching contracts` : 'Top 10 trending contracts'}</span>
                                {(eventLoading || eventCatalogLoading) && (
                                  <span>{eventLoading ? 'Refreshing…' : 'Loading catalog…'}</span>
                                )}
                              </div>
                              {!eventLoading && !eventMarkets.length && (
                                <div className="event-market-empty">
                                  {eventCatalogLoading
                                    ? 'Loading available Webull contracts…'
                                    : 'No available Webull contracts match this category and search.'}
                                </div>
                              )}
                              {eventMarkets.map((market) => (
                                <button
                                  key={market.symbol}
                                  type="button"
                                  role="option"
                                  aria-selected={market.symbol === selectedEventMarket?.symbol}
                                  className={`event-market-result ${market.symbol === selectedEventMarket?.symbol ? 'selected' : ''}`}
                                  onClick={() => applyEventMarket(market)}
                                >
                                  <span className="event-market-result-copy">
                                    <strong>{market.name}</strong>
                                    <span className="event-market-condition">{eventConditionLabel(market)}</span>
                                    <small className="event-market-symbol">{market.symbol}</small>
                                  </span>
                                  <span className="event-market-result-prices">
                                    <span>Yes {eventMoney(market.yes_ask)}</span>
                                    <span>No {eventMoney(market.no_ask)}</span>
                                    <small>Vol {number(market.volume, 0)}</small>
                                  </span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>

                      {selectedEventMarket && (
                        <div className="selected-event-market" aria-live="polite">
                          <div>
                            <strong>{selectedEventMarket.name}</strong>
                            <span>{selectedEventMarket.symbol}</span>
                            <p>{eventConditionLabel(selectedEventMarket)}</p>
                          </div>
                          <div className="selected-event-market-stats">
                            <span>Volume <strong>{number(selectedEventMarket.volume, 0)}</strong></span>
                            <span>Open interest <strong>{number(selectedEventMarket.open_interest, 0)}</strong></span>
                            <span>Last trade <strong>{formatDate(selectedEventMarket.last_trade_time)}</strong></span>
                          </div>
                        </div>
                      )}

                      <div className="event-outcome-section">
                        <label className="order-field-label">Contract Outcome</label>
                        <div className="event-outcome-grid">
                          <button
                            type="button"
                            onClick={() => chooseEventOutcome('yes')}
                            className={`event-outcome-button yes ${orderForm.eventOutcome === 'yes' ? 'selected' : ''}`}
                            disabled={!selectedEventMarket}
                          >
                            <strong>👍 YES · {orderForm.side === 'SELL' ? 'Sell' : 'Buy'} {eventMoney(eventQuoteFor(selectedEventMarket, 'yes', orderForm.side))}</strong>
                            <span>Bid {eventMoney(selectedEventMarket?.yes_bid)} · Ask {eventMoney(selectedEventMarket?.yes_ask)}</span>
                            <small>Available size {number(orderForm.side === 'SELL' ? selectedEventMarket?.yes_bid_size : selectedEventMarket?.yes_ask_size, 0)}</small>
                          </button>

                          <button
                            type="button"
                            onClick={() => chooseEventOutcome('no')}
                            className={`event-outcome-button no ${orderForm.eventOutcome === 'no' ? 'selected' : ''}`}
                            disabled={!selectedEventMarket}
                          >
                            <strong>👎 NO · {orderForm.side === 'SELL' ? 'Sell' : 'Buy'} {eventMoney(eventQuoteFor(selectedEventMarket, 'no', orderForm.side))}</strong>
                            <span>Bid {eventMoney(selectedEventMarket?.no_bid)} · Ask {eventMoney(selectedEventMarket?.no_ask)}</span>
                            <small>Available size {number(orderForm.side === 'SELL' ? selectedEventMarket?.no_bid_size : selectedEventMarket?.no_ask_size, 0)}</small>
                          </button>
                        </div>
                      </div>

                      <div className="event-rules-grid">
                        <div>
                          <span>Order Type</span>
                          <strong>{eventRules.order_types?.map((rule) => `${rule.order_type} (${(rule.time_in_force || []).join('/')})`).join(', ') || 'Unavailable'}</strong>
                        </div>
                        <div>
                          <span>Price Range</span>
                          <strong>{eventPriceRangeLabel(eventRules.price_ranges)}</strong>
                        </div>
                        <div>
                          <span>Win Payout</span>
                          <strong>{Number.isFinite(eventSettlementPayout) ? `${eventMoney(eventSettlementPayout)} per correct contract` : 'Unavailable'}</strong>
                        </div>
                        <div>
                          <span>Max Quantity</span>
                          <strong>{eventRules.max_quantity ? `${number(eventRules.max_quantity, 0)} contracts` : 'Unavailable'}</strong>
                        </div>
                        <div>
                          <span>Quantity Type</span>
                          <strong>{eventRules.fractionable ? 'Fractional contracts supported' : 'Whole contracts only'}</strong>
                        </div>
                        <div>
                          <span>Trading Hours</span>
                          <strong>{eventRules.trading_hours || 'Unavailable'}</strong>
                        </div>
                      </div>

                      <div className="event-payout-summary" aria-live="polite">
                        <span>
                          Current {String(orderForm.eventOutcome || '').toUpperCase()} {orderForm.side === 'SELL' ? 'bid' : 'ask'}:
                          <strong>{eventMoney(eventSelectedQuote)}</strong>
                        </span>
                        <span>
                          Profit per correct contract at your limit:
                          <strong>{eventPotentialProfitEach != null ? eventMoney(eventPotentialProfitEach) : '—'}</strong>
                        </span>
                        <span>
                          Gross winning payout for {Number.isFinite(eventQuantity) && eventQuantity > 0 ? number(eventQuantity, eventRules.fractionable ? 5 : 0) : '—'}:
                          <strong>{eventGrossWinningPayout != null ? eventMoney(eventGrossWinningPayout) : '—'}</strong>
                        </span>
                        <span>
                          Potential profit before fees:
                          <strong>{eventPotentialProfitTotal != null ? eventMoney(eventPotentialProfitTotal) : '—'}</strong>
                        </span>
                      </div>

                      {eventMessage && <p className="option-ticket-status" role="status">⚠️ {eventMessage}</p>}
                    </div>
                  )}

                  {/* Options Chain & Live Order Book (When OPTION selected) - Positioned Right Below Asset Class Switcher */}
                  {selectedInstrumentType === 'OPTION' && (
                    <WebullOptionChain
                      defaultSymbol={selectedSymbol}
                      availableTraditional={availableTraditional}
                      selectedContract={{
                        symbol: selectedSymbol,
                        optionType: orderForm.optionType,
                        strike: orderForm.optionStrike,
                        expiration: orderForm.optionExpiration,
                        price: orderForm.price,
                        side: orderForm.side,
                        optionStrategy: orderForm.optionStrategy,
                        optionStrategyWidth: orderForm.optionStrategyWidth,
                      }}
                      onSelectOptionContract={handleSelectOptionContract}
                      onUnderlyingPriceChange={setOptionUnderlyingPrice}
                      chartStrikeRequest={chartStrikeRequest}
                      onChartStrikeRequestHandled={(requestId) => {
                        setChartStrikeRequest((previous) => (
                          previous?.id === requestId ? null : previous
                        ));
                      }}
                      onSymbolChange={(newSym) => {
                        setOptionUnderlyingPrice(0);
                        setSelectedSymbol(newSym);
                      }}
                      onStrategyChange={({ strategy, width }) => {
                        setOrderForm((previous) => ({
                          ...previous,
                          optionStrategy: strategy,
                          optionStrategyWidth: width,
                          optionStrategyLegs: [],
                          optionStrike: '',
                          optionExpiration: '',
                          price: '',
                        }));
                      }}
                      isLightMode={isLightMode}
                    />
                  )}
                  



                  {/* Options Contract Setup (When OPTION selected) */}
                  {selectedInstrumentType === 'OPTION' && (
                    <div style={{ background: 'rgba(139, 92, 246, 0.12)', border: '1px solid rgba(139, 92, 246, 0.35)', borderRadius: '8px', padding: '14px', marginBottom: '14px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                        <span style={{ fontSize: '13px', fontWeight: 700, color: '#c4b5fd', display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <span>🎯</span> Option Contract Setup ({selectedSymbol})
                        </span>
                        <span style={{ fontSize: '11px', color: '#a78bfa', background: 'rgba(139, 92, 246, 0.25)', padding: '3px 8px', borderRadius: '12px', fontWeight: 600 }}>
                          {optionStrategyDefinition(orderForm.optionStrategy).label} · {orderForm.optionStrategyLegs?.length || 1} leg{(orderForm.optionStrategyLegs?.length || 1) === 1 ? '' : 's'}
                        </span>
                      </div>

                      {orderForm.optionStrike && orderForm.optionExpiration ? (
                        <div style={{ background: 'rgba(0, 0, 0, 0.3)', border: '1px solid rgba(139, 92, 246, 0.35)', borderRadius: '6px', padding: '8px 12px', marginBottom: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                          <span style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc' }}>
                            {selectedSymbol} {orderForm.optionExpiration} ${parseFloat(orderForm.optionStrike || 0).toFixed(2)} {orderForm.optionType}
                          </span>
                          <span style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 700, background: 'rgba(56, 189, 248, 0.15)', padding: '2px 8px', borderRadius: '10px' }}>
                            {orderForm.side} @ ${orderForm.price || '0.00'}
                          </span>
                        </div>
                      ) : (
                        <p style={{ margin: '0 0 10px', fontSize: '12px', color: '#94a3b8' }}>
                          💡 Tip: Click any <strong>Bid</strong> or <strong>Ask</strong> in the Options Chain above to instantly load contract terms and prices.
                        </p>
                      )}
                      <p style={{ margin: '0 0 12px', fontSize: '12px', color: '#c4b5fd', lineHeight: 1.45 }}>
                        These values reflect the contract selected above. Buy is enabled only when available USD covers one contract; Sell is enabled only for the exact owned call or put in this Webull account.
                      </p>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '12px' }}>
                        <div>
                          <label className="order-field-label">Option Type</label>
                          <div
                            className="order-styled-input"
                            role="status"
                            aria-label="Selected option type"
                            style={{ fontWeight: 700, color: '#fff' }}
                          >
                            {orderForm.optionType || '—'}
                          </div>
                        </div>
                        <div>
                          <label className="order-field-label">Strike Price ($)</label>
                          <input
                            type="text"
                            inputMode="decimal"
                            value={orderForm.optionStrike}
                            readOnly
                            aria-readonly="true"
                            className="order-styled-input"
                          />
                        </div>
                        <div>
                          <label className="order-field-label">Expiration Date</label>
                          <input
                            type="date"
                            value={orderForm.optionExpiration}
                            readOnly
                            aria-readonly="true"
                            className="order-styled-input"
                          />
                        </div>
                      </div>

                      {/* Real-time Breakeven & Risk Safeguards */}
                      {Number(orderForm.optionStrike) > 0 && Number(orderForm.price) > 0 && (
                        <div style={{ marginTop: '12px', display: 'flex', gap: '16px', flexWrap: 'wrap', fontSize: '12px', color: '#e2e8f0', background: 'rgba(0,0,0,0.25)', padding: '8px 12px', borderRadius: '6px' }}>
                          <div>
                            <span style={{ color: '#94a3b8' }}>Breakeven Price: </span>
                            <strong style={{ color: '#38bdf8' }}>
                              ${(orderForm.optionType === 'CALL'
                                ? Number(orderForm.optionStrike) + Number(orderForm.price)
                                : Number(orderForm.optionStrike) - Number(orderForm.price)).toFixed(2)}
                            </strong>
                          </div>
                          <div>
                            <span style={{ color: '#94a3b8' }}>Maximum Risk: </span>
                            <strong style={{ color: '#f87171' }}>
                              ${((Number(orderForm.quantity) || 1) * Number(orderForm.price) * 100).toFixed(2)} (Total Premium)
                            </strong>
                          </div>
                          <div>
                            <span style={{ color: '#94a3b8' }}>Est. Total Premium: </span>
                            <strong style={{ color: '#4ade80' }}>
                              ${((Number(orderForm.quantity) || 1) * Number(orderForm.price) * 100).toFixed(2)}
                            </strong>
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Row 1: Order Side & Order Types (Stacked with Order Types underneath Order Side) */}
                  <div className="order-control-row">
                    <div className="order-control-group side-group">
                      <label className="order-field-label">Order Side</label>
                      <div className={`order-side-segmented ${selectedInstrumentType === 'EQUITY' ? (isTestMode && currentHoldingIsShort ? 'four-cols' : 'three-cols') : ''}`}>
                        <button
                          type="button"
                          className={`order-side-btn buy-side ${orderForm.side === 'BUY' ? 'active' : ''}`}
                          onClick={() => handleTicketSideChange('BUY')}
                          disabled={(selectedInstrumentType === 'EVENT' ? !eventBuyEnabled : ticketOrderControlsDisabled) || assetClassDisabled(selectedInstrumentType)}
                          title={selectedInstrumentType === 'OPTION' && !optionBuyEnabled ? optionExecutionMessage || 'A priced option contract and enough USD for one contract are required to buy.' : futuresOrderControlsDisabled ? futuresExecutionMessage : selectedInstrumentType === 'EVENT' ? 'Buy to open event contract' : 'Buy this instrument'}
                        >
                          📈 Buy {selectedInstrumentType === 'EVENT' ? '(To Open)' : ''}
                        </button>
                        <button
                          type="button"
                          className={`order-side-btn sell-side ${orderForm.side === 'SELL' ? 'active' : ''}`}
                          onClick={() => handleTicketSideChange('SELL')}
                          disabled={(selectedInstrumentType === 'EVENT' ? !eventSellEnabled : ticketOrderControlsDisabled) || assetClassDisabled(selectedInstrumentType)}
                          title={selectedInstrumentType === 'OPTION' && !optionSellEnabled ? 'Sell is available only for an exact option contract currently owned in this Webull account.' : futuresOrderControlsDisabled ? futuresExecutionMessage : selectedInstrumentType === 'EVENT' ? 'Sell to close event contract' : 'Sell this instrument'}
                        >
                          📉 Sell {selectedInstrumentType === 'EVENT' ? '(To Close)' : ''}
                        </button>
                        {selectedInstrumentType === 'EQUITY' && isTestMode && currentHoldingIsShort && (
                          <button
                            type="button"
                            className={`order-side-btn cover-side ${orderForm.side === 'BUY_TO_CLOSE' ? 'active' : ''}`}
                            onClick={() => {
                              setOrderForm((prev) => ({ ...prev, side: 'BUY_TO_CLOSE', entrustType: 'QTY' }));
                              setBalancePercentage(0);
                              setOrderValidationError('');
                            }}
                            disabled={ticketOrderControlsDisabled || heldQuantity <= 0}
                            title={`Buy up to ${formatQuantityForTicket(heldQuantity, 6) || '0'} units to close this simulated short position`}
                          >
                            ↩ Cover
                          </button>
                        )}
                        {selectedInstrumentType === 'EQUITY' && (
                          <button
                            type="button"
                            className={`order-side-btn short-side ${orderForm.side === 'SHORT' ? 'active' : ''}`}
                            onClick={() => {
                              setOrderForm((prev) => ({ ...prev, side: 'SHORT' }));
                              setBalancePercentage(0);
                              setOrderValidationError('');
                            }}
                            disabled={ticketOrderControlsDisabled || assetClassDisabled('EQUITY')}
                            title="Sell short this equity (Webull margin account required)"
                          >
                            🔻 Short
                          </button>
                        )}
                      </div>
                    </div>

                    <div className="order-control-group type-group">
                      <label className="order-field-label">Order Types</label>
                      <div className="order-type-segmented">
                        {availableOrderTypes.map((t) => (
                          <button
                            key={t.value}
                            type="button"
                            className={`order-type-btn ${orderForm.type === t.value ? 'active' : ''}`}
                            onClick={() => {
                              setOrderForm((prev) => ({ ...prev, type: t.value }));
                              setOrderValidationError('');
                            }}
                            title={t.description}
                            disabled={ticketOrderControlsDisabled || selectedInstrumentType === 'EVENT'}
                          >
                            {t.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>

                  {selectedInstrumentType === 'OPTION' && optionExecutionMessage && (
                    <p className="option-ticket-status" role="status">⚠️ {optionExecutionMessage}</p>
                  )}
                  {futuresExecutionMessage && (
                    <p className="option-ticket-status" role="status">⚠️ {futuresExecutionMessage}</p>
                  )}
                  {eventExecutionMessage && (
                    <p className="option-ticket-status" role="status">⚠️ {eventExecutionMessage}</p>
                  )}

                  {/* Webull Entrust Type Switcher (Equities only) */}
                  {selectedInstrumentType === 'EQUITY' && (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
                      <span style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8' }}>Order Entry Mode:</span>
                      <div className="webull-entrust-segmented">
                        <button
                          type="button"
                          className={`webull-entrust-btn ${orderForm.entrustType === 'QTY' ? 'active' : ''}`}
                          onClick={() => {
                            setOrderForm((prev) => ({ ...prev, entrustType: 'QTY' }));
                            setOrderValidationError('');
                          }}
                        >
                          By Shares (QTY)
                        </button>
                        <button
                          type="button"
                          className={`webull-entrust-btn ${orderForm.entrustType === 'AMOUNT' ? 'active' : ''}`}
                          onClick={() => {
                            setOrderForm((prev) => ({
                              ...prev,
                              entrustType: 'AMOUNT',
                              totalCashAmount: prev.totalCashAmount || (prev.quoteQuantity && Number(prev.quoteQuantity) >= 5 ? prev.quoteQuantity : '25.00'),
                            }));
                            setOrderValidationError('');
                          }}
                        >
                          By Cash Amount ($ AMOUNT)
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Cash Amount Input if in AMOUNT entrust mode for Equities */}
                  {selectedInstrumentType === 'EQUITY' && orderForm.entrustType === 'AMOUNT' ? (
                    <div className="order-inputs-row">
                      <div className="order-input-group" style={{ width: '100%' }}>
                        <label className="order-field-label" htmlFor="totalCashAmount">
                          Total Cash Amount ($ USD)
                        </label>
                        <div className="order-input-wrapper">
                          <input
                            id="totalCashAmount"
                            type="text"
                            inputMode="decimal"
                            value={orderForm.totalCashAmount}
                            onChange={(e) => {
                              const val = e.target.value.replace(/[^0-9.]/g, '');
                              setOrderForm((prev) => ({
                                ...prev,
                                totalCashAmount: val,
                                quantity: effectivePrice > 0 && Number(val) > 0 ? (Number(val) / effectivePrice).toFixed(4) : prev.quantity,
                              }));
                              setOrderValidationError('');
                            }}
                            placeholder="e.g. 25.00 (min $5.00)"
                            className="order-styled-input"
                            disabled={ticketOrderControlsDisabled}
                            autoComplete="off"
                          />
                        </div>
                        <small className="order-field-help" style={{ color: '#94a3b8', fontSize: '11px', marginTop: '4px' }}>
                          Webull cash fractional order (minimum $5.00).
                          {effectivePrice > 0 && Number(orderForm.totalCashAmount) > 0 && (
                            <span style={{ color: '#38bdf8', marginLeft: '6px' }}>
                              ≈ {(Number(orderForm.totalCashAmount) / effectivePrice).toFixed(4)} shares @ ${number(effectivePrice)}
                            </span>
                          )}
                        </small>
                      </div>
                    </div>
                  ) : (
                    /* Row 2: Quantity and Quote Value Inputs */
                    <div className="order-inputs-row">
                      <div className="order-input-group">
                        <label className="order-field-label" htmlFor="quantity">
                          {selectedInstrumentType === 'OPTION'
                            ? 'Contracts (100 shares each)'
                            : selectedInstrumentType === 'EVENT'
                              ? `Contracts${Number.isFinite(Number(eventRules.max_quantity)) ? ` (Max ${number(eventRules.max_quantity, eventRules.fractionable ? 5 : 0)})` : ''}`
                              : selectedInstrumentType === 'FUTURES'
                                ? 'Contracts'
                                : `Quantity (${selectedSymbol})`}
                        </label>
                        <div className="order-input-wrapper">
                          <input
                            id="quantity"
                            type="text"
                            inputMode="decimal"
                            value={orderForm.quantity}
                            onChange={(e) => handleBaseQuantityChange(e.target.value)}
                            placeholder={['OPTION', 'FUTURES', 'EVENT'].includes(selectedInstrumentType) ? '1' : '0.0000'}
                            className="order-styled-input"
                            disabled={ticketOrderControlsDisabled}
                            aria-label={selectedInstrumentType === 'OPTION' ? `Option strategy contracts, current value ${orderForm.quantity || 'empty'}` : `Order quantity for ${selectedSymbol}`}
                            aria-invalid={Boolean(orderValidationError)}
                            aria-describedby={orderValidationError ? 'webull-order-validation' : undefined}
                            autoComplete="off"
                          />
                          {selectedInstrumentType !== 'FUTURES' && <button
                            type="button"
                            className="input-max-btn"
                            onClick={() => handleSliderChange(100)}
                            title="Use 100% Available Balance"
                            disabled={ticketOrderControlsDisabled}
                          >
                            MAX
                          </button>}
                        </div>
                        {orderValidationError && (
                          <p
                            id="webull-order-validation"
                            role="alert"
                            style={{ color: '#fca5a5', fontSize: '12px', fontWeight: 600, lineHeight: 1.4, margin: '7px 0 0' }}
                          >
                            ⚠️ {orderValidationError}
                          </p>
                        )}
                      </div>

                      {selectedInstrumentType === 'FUTURES' ? (
                        <div className="order-input-group">
                          <label className="order-field-label">Margin &amp; Notional</label>
                          <div className="order-styled-input" style={{ padding: '10px 12px', color: '#94a3b8' }}>
                            Calculated by Webull for the selected contract
                          </div>
                        </div>
                      ) : (
                        <div className="order-input-group">
                          <label className="order-field-label" htmlFor="quoteQuantity">
                            Order Value ($ USD)
                          </label>
                          <div className="order-input-wrapper">
                            <input
                              id="quoteQuantity"
                              type="text"
                              inputMode="decimal"
                              value={selectedInstrumentType === 'OPTION' ? optionOrderValueText(orderForm.quantity, effectivePrice) : orderForm.quoteQuantity}
                              onChange={(e) => handleQuoteQuantityChange(e.target.value)}
                              placeholder="$0.00"
                              className="order-styled-input"
                              disabled={ticketOrderControlsDisabled}
                              readOnly={selectedInstrumentType === 'OPTION'}
                              aria-label={selectedInstrumentType === 'OPTION' ? `Calculated option order value, ${optionOrderValueText(orderForm.quantity, effectivePrice)} US dollars` : 'Order value in US dollars'}
                              autoComplete="off"
                            />
                            <button
                              type="button"
                              className="input-percent-btn"
                              onClick={() => {
                                const nextPct = balancePercentage === 25 ? 50 : balancePercentage === 50 ? 75 : balancePercentage === 75 ? 100 : 25;
                                handleSliderChange(nextPct);
                              }}
                              title="Step allocation: 25%, 50%, 75%, 100%"
                              disabled={ticketOrderControlsDisabled}
                            >
                              %
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Conditional Price Inputs based on order type */}
                  {orderForm.type === 'STOP_LOSS' && (
                    <div className="order-inputs-row">
                      <div className="order-input-group" style={{ width: '100%' }}>
                        <label className="order-field-label" htmlFor="stopPrice">
                          Stop Price ($ USD)
                        </label>
                        <div className="order-input-wrapper">
                          <input
                            id="stopPrice"
                            type="text"
                            inputMode="decimal"
                            value={orderForm.stopPrice}
                            onChange={(e) => handleStopPriceChange(e.target.value)}
                            placeholder="0.00"
                            className="order-styled-input"
                            disabled={ticketOrderControlsDisabled}
                            required
                          />
                          <button
                            type="button"
                            className="input-percent-btn"
                            onClick={() => handleOpenPercentModal('stopPrice')}
                            title="Calculate stop price from percentage"
                            disabled={ticketOrderControlsDisabled}
                          >
                            %
                          </button>
                        </div>
                        <small className="order-field-help" style={{ color: '#94a3b8', fontSize: '11px', marginTop: '4px' }}>
                          Trigger price: once reached, a market order is placed to execute immediately.
                        </small>
                      </div>
                    </div>
                  )}

                  {orderForm.type === 'STOP_LOSS_LIMIT' && (
                    <div className="order-inputs-row">
                      <div className="order-input-group">
                        <label className="order-field-label" htmlFor="stopPrice">
                          Stop Trigger Price ($ USD)
                        </label>
                        <div className="order-input-wrapper">
                          <input
                            id="stopPrice"
                            type="text"
                            inputMode="decimal"
                            value={orderForm.stopPrice}
                            onChange={(e) => handleStopPriceChange(e.target.value)}
                            placeholder="0.00"
                            className="order-styled-input"
                            disabled={ticketOrderControlsDisabled}
                            required
                          />
                          <button
                            type="button"
                            className="input-percent-btn"
                            onClick={() => handleOpenPercentModal('stopPrice')}
                            title="Calculate stop trigger & limit execution prices from percentage"
                            disabled={ticketOrderControlsDisabled}
                          >
                            %
                          </button>
                        </div>
                        <small className="order-field-help" style={{ color: '#94a3b8', fontSize: '11px', marginTop: '4px' }}>
                          Price that triggers the limit order
                        </small>
                      </div>

                      <div className="order-input-group">
                        <label className="order-field-label" htmlFor="price">
                          Limit Execution Price ($ USD)
                        </label>
                        <div className="order-input-wrapper">
                          <input
                            id="price"
                            type="text"
                            inputMode="decimal"
                            value={orderForm.price}
                            onChange={(e) => handlePriceChange(e.target.value)}
                            placeholder="0.00"
                            className="order-styled-input"
                            disabled={ticketOrderControlsDisabled}
                            required
                          />
                        </div>
                        <small className="order-field-help" style={{ color: '#94a3b8', fontSize: '11px', marginTop: '4px' }}>
                          Maximum purchase or minimum sale price
                        </small>
                      </div>
                    </div>
                  )}

                  {['FUTURES', 'EQUITY'].includes(selectedInstrumentType) && orderForm.type === 'TRAILING_STOP_LOSS' && (
                    <div className="order-inputs-row">
                      <div className="order-input-group">
                        <label className="order-field-label">Trail Type</label>
                        <select
                          value={orderForm.trailingType}
                          onChange={(event) => setOrderForm((prev) => ({ ...prev, trailingType: event.target.value }))}
                          className="order-styled-input"
                          disabled={ticketOrderControlsDisabled}
                        >
                          <option value="AMOUNT">Dollar amount ($)</option>
                          <option value="PERCENTAGE">Percentage (%)</option>
                        </select>
                      </div>
                      <div className="order-input-group">
                        <label className="order-field-label" htmlFor="trailingStopStep">Trail {orderForm.trailingType === 'PERCENTAGE' ? 'Percentage' : 'Amount'} {orderForm.trailingType === 'PERCENTAGE' ? '(%)' : '($ USD)'}</label>
                        <input
                          id="trailingStopStep"
                          type="text"
                          inputMode="decimal"
                          value={orderForm.trailingStopStep}
                          onChange={(event) => setOrderForm((prev) => ({ ...prev, trailingStopStep: event.target.value.replace(/[^0-9.]/g, '') }))}
                          placeholder={orderForm.trailingType === 'PERCENTAGE' ? 'e.g. 1.00' : 'e.g. 5.00'}
                          className="order-styled-input"
                          disabled={ticketOrderControlsDisabled}
                        />
                      </div>
                    </div>
                  )}

                  {['LIMIT', 'LIMIT_ON_OPEN'].includes(orderForm.type) && (
                    <div className="order-inputs-row">
                      <div className="order-input-group" style={{ width: '100%' }}>
                        <label className="order-field-label" htmlFor="price">
                          {selectedInstrumentType === 'EVENT' ? 'Event Contract Limit Price ($ USD)' : 'Limit Price ($ USD)'}
                        </label>
                        <div className="order-input-wrapper">
                          <input
                            id="price"
                            type="text"
                            inputMode="decimal"
                            value={orderForm.price}
                            onChange={(e) => handlePriceChange(e.target.value)}
                            placeholder={selectedInstrumentType === 'EVENT' ? 'Select a market quote' : '0.00'}
                            className="order-styled-input"
                            disabled={ticketOrderControlsDisabled}
                            required
                          />
                          {selectedInstrumentType !== 'EVENT' && (
                            <button
                              type="button"
                              className="input-percent-btn"
                              onClick={() => handleOpenPercentModal('price')}
                              title="Calculate limit price from percentage"
                              disabled={ticketOrderControlsDisabled}
                            >
                              %
                            </button>
                          )}
                        </div>
                        {selectedInstrumentType === 'EVENT' && (
                          <small className="order-field-help" style={{ color: '#94a3b8', fontSize: '11px', marginTop: '4px' }}>
                            Current Webull range: {eventPriceRangeLabel(eventRules.price_ranges)}. Winning settlement: {eventMoney(eventSettlementPayout)}. Implied win probability: {Math.round((Number(orderForm.price) || 0) * 100)}%.
                          </small>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Execution Settings: Time in Force & Trading Session */}
                  <div className="order-inputs-row" style={{ marginTop: '12px' }}>
                    <div className="order-input-group">
                      <label className="order-field-label">Time In Force</label>
                      <select
                        value={orderForm.timeInForce}
                        onChange={(e) => setOrderForm((prev) => ({ ...prev, timeInForce: e.target.value }))}
                        className="order-styled-input"
                        style={{ cursor: 'pointer' }}
                        disabled={ticketOrderControlsDisabled || selectedInstrumentType === 'EVENT'}
                      >
                        <option value="DAY">Day Order (DAY)</option>
                        {!(selectedInstrumentType === 'OPTION' && orderForm.side === 'SELL') && selectedInstrumentType !== 'EVENT' && !['TRAILING_STOP_LOSS', 'MARKET_ON_OPEN', 'MARKET_ON_CLOSE', 'LIMIT_ON_OPEN'].includes(orderForm.type) && <option value="GTC">Good &apos;Til Canceled (GTC)</option>}
                        {selectedInstrumentType === 'CRYPTO' && <option value="IOC">Immediate or Cancel (IOC)</option>}
                      </select>
                    </div>
                    {selectedInstrumentType === 'EQUITY' && (
                      <div className="order-input-group">
                        <label className="order-field-label">Trading Session</label>
                        <select
                          value={orderForm.tradingSession}
                          onChange={(e) => {
                            userChangedSessionRef.current = true;
                            setOrderForm((prev) => ({ ...prev, tradingSession: e.target.value }));
                            setOrderValidationError('');
                          }}
                          className="order-styled-input"
                          style={{ cursor: 'pointer' }}
                        >
                          <option value="CORE">Only Regular Hours (CORE: 9:30 AM - 4:00 PM ET)</option>
                          <option value="ALL">Including Extended Hours (ALL: 4:00 AM - 8:00 PM ET)</option>
                          <option value="NIGHT">Overnight Hours Only (NIGHT: 8:00 PM - 4:00 AM ET)</option>
                        </select>
                      </div>
                    )}
                  </div>

                  {selectedInstrumentType === 'EQUITY' && (
                    <p style={{ margin: '0 0 12px', color: '#94a3b8', fontSize: '12px', lineHeight: 1.45 }}>
                      Fractional stock and ETF quantities are available only for <strong style={{ color: '#e2e8f0' }}>Only Regular Hours (CORE)</strong> and Webull Market orders. Extended and Overnight sessions require whole shares.
                    </p>
                  )}

                  {/* Bracket Order Configuration (Take-Profit / Stop-Loss for Stocks) */}
                  {selectedInstrumentType === 'EQUITY' && (
                    <div className="webull-stock-feature-card webull-bracket-box">
                      <div className="webull-feature-toggle-row">
                        <label className="webull-feature-title" style={{ color: '#34d399', cursor: 'pointer' }}>
                          <input
                            type="checkbox"
                            checked={orderForm.isBracketEnabled}
                            onChange={(e) => setOrderForm((prev) => ({ ...prev, isBracketEnabled: e.target.checked }))}
                            style={{ cursor: 'pointer', accentColor: '#10b981' }}
                          />
                          <span>🎯 Attach Take-Profit / Stop-Loss (Bracket)</span>
                        </label>
                        <span style={{ fontSize: '11px', color: '#6ee7b7', background: 'rgba(16, 185, 129, 0.2)', padding: '2px 8px', borderRadius: '10px' }}>
                          Automated Exits
                        </span>
                      </div>
                      {orderForm.isBracketEnabled && (
                        <div style={{ marginTop: '10px' }}>
                          <p style={{ margin: '0 0 10px', fontSize: '12px', color: '#94a3b8', lineHeight: 1.4 }}>
                            When the primary stock order executes, Webull automatically deploys linked exit legs.
                          </p>
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '10px' }}>
                            <div>
                              <label className="order-field-label">Take-Profit Price ($)</label>
                              <input
                                type="text"
                                inputMode="decimal"
                                value={orderForm.bracketTakeProfitPrice}
                                onChange={(e) => setOrderForm((prev) => ({ ...prev, bracketTakeProfitPrice: e.target.value.replace(/[^0-9.]/g, '') }))}
                                placeholder="e.g. 195.00"
                                className="order-styled-input"
                              />
                            </div>
                            <div>
                              <label className="order-field-label">Stop-Loss Trigger ($)</label>
                              <input
                                type="text"
                                inputMode="decimal"
                                value={orderForm.bracketStopLossPrice}
                                onChange={(e) => setOrderForm((prev) => ({ ...prev, bracketStopLossPrice: e.target.value.replace(/[^0-9.]/g, '') }))}
                                placeholder="e.g. 170.00"
                                className="order-styled-input"
                              />
                            </div>
                            <div>
                              <label className="order-field-label">Stop Limit Price ($ opt)</label>
                              <input
                                type="text"
                                inputMode="decimal"
                                value={orderForm.bracketStopLossLimitPrice}
                                onChange={(e) => setOrderForm((prev) => ({ ...prev, bracketStopLossLimitPrice: e.target.value.replace(/[^0-9.]/g, '') }))}
                                placeholder="e.g. 168.00"
                                className="order-styled-input"
                              />
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Institutional Algorithmic Trading (TWAP / VWAP / POV for Stocks) */}
                  {selectedInstrumentType === 'EQUITY' && ['MARKET', 'LIMIT'].includes(orderForm.type) && orderForm.tradingSession === 'CORE' && (
                    <div className="webull-stock-feature-card webull-algo-box">
                      <div className="webull-feature-toggle-row">
                        <label className="webull-feature-title" style={{ color: '#38bdf8', cursor: 'pointer' }}>
                          <input
                            type="checkbox"
                            checked={orderForm.isAlgoEnabled}
                            onChange={(e) => setOrderForm((prev) => ({ ...prev, isAlgoEnabled: e.target.checked }))}
                            style={{ cursor: 'pointer', accentColor: '#0284c7' }}
                          />
                          <span>⚡ Algorithmic Execution (TWAP / VWAP / POV)</span>
                        </label>
                        <span style={{ fontSize: '11px', color: '#7dd3fc', background: 'rgba(2, 132, 199, 0.2)', padding: '2px 8px', borderRadius: '10px' }}>
                          Regular Hours (CORE)
                        </span>
                      </div>
                      {orderForm.isAlgoEnabled && (
                        <div style={{ marginTop: '10px' }}>
                          <p style={{ margin: '0 0 10px', fontSize: '12px', color: '#94a3b8', lineHeight: 1.4 }}>
                            Institutional execution to slice orders over time and minimize slippage.
                          </p>
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '10px' }}>
                            <div>
                              <label className="order-field-label">Algorithm Type</label>
                              <select
                                value={orderForm.algoType}
                                onChange={(e) => setOrderForm((prev) => ({ ...prev, algoType: e.target.value }))}
                                className="order-styled-input"
                              >
                                <option value="TWAP">TWAP (Time-Weighted)</option>
                                <option value="VWAP">VWAP (Volume-Weighted)</option>
                                <option value="POV">POV (% of Volume)</option>
                              </select>
                            </div>
                            <div>
                              <label className="order-field-label">Start Time (ET)</label>
                              <input
                                type="text"
                                value={orderForm.algoStartTime}
                                onChange={(e) => setOrderForm((prev) => ({ ...prev, algoStartTime: e.target.value }))}
                                placeholder="HH:mm:ss"
                                className="order-styled-input"
                              />
                            </div>
                            <div>
                              <label className="order-field-label">End Time (ET)</label>
                              <input
                                type="text"
                                value={orderForm.algoEndTime}
                                onChange={(e) => setOrderForm((prev) => ({ ...prev, algoEndTime: e.target.value }))}
                                placeholder="HH:mm:ss"
                                className="order-styled-input"
                              />
                            </div>
                            {['TWAP', 'VWAP'].includes(orderForm.algoType) && (
                              <div>
                                <label className="order-field-label">Max Target % (1-20)</label>
                                <input
                                  type="number"
                                  min="1"
                                  max="20"
                                  value={orderForm.maxTargetPercent}
                                  onChange={(e) => setOrderForm((prev) => ({ ...prev, maxTargetPercent: e.target.value }))}
                                  className="order-styled-input"
                                />
                              </div>
                            )}
                            {orderForm.algoType === 'POV' && (
                              <div>
                                <label className="order-field-label">Target Volume % (1-20)</label>
                                <input
                                  type="number"
                                  min="1"
                                  max="20"
                                  value={orderForm.targetVolPercent}
                                  onChange={(e) => setOrderForm((prev) => ({ ...prev, targetVolPercent: e.target.value }))}
                                  className="order-styled-input"
                                />
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Row 3: Use Balance Slider Section */}
                  {selectedInstrumentType !== 'FUTURES' && <div className="order-slider-section">
                    <div className="order-slider-header">
                      <span className="order-field-label">Use Balance: {balancePercentage}%</span>
                      {balancePercentage > 0 && (
                        <span className="order-slider-amount">
                          ({orderForm.side === 'SELL'
                            ? `${((heldQuantity * balancePercentage) / 100).toFixed(selectedInstrumentType === 'CRYPTO' ? 6 : 2)} ${selectedSymbol}`
                            : `$${((cashBalance * balancePercentage) / 100).toFixed(2)} USD`})
                        </span>
                      )}
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="100"
                      step="1"
                      value={balancePercentage}
                      onChange={(e) => handleSliderChange(parseInt(e.target.value, 10))}
                      className="modern-balance-slider"
                      disabled={ticketOrderControlsDisabled}
                      style={{
                        background: `linear-gradient(to right, ${orderForm.side === 'BUY' ? '#10b981' : '#ef4444'} ${balancePercentage}%, rgba(255, 255, 255, 0.1) ${balancePercentage}%)`,
                      }}
                    />
                    <div className="slider-pills-row">
                      {[0, 25, 50, 75, 100].map((pct) => (
                        <button
                          key={pct}
                          type="button"
                          className={`slider-pct-pill ${balancePercentage === pct ? 'active' : ''}`}
                          onClick={() => handleSliderChange(pct)}
                          disabled={ticketOrderControlsDisabled}
                        >
                          {pct}%
                        </button>
                      ))}
                    </div>
                  </div>}

                  {/* Row 4: Order Summary Card */}
                  <div className="order-summary-card">
                    <div className="order-summary-row">
                      <span>Order Total:</span>
                      <strong>{selectedInstrumentType === 'FUTURES' ? 'Webull calculates margin' : `$${number(orderTotal)} USD`}</strong>
                    </div>
                    <div className="order-summary-row">
                      <span>Estimated Cash Impact:</span>
                      <span style={{ color: ['BUY', 'BUY_TO_CLOSE'].includes(orderForm.side) ? '#ef4444' : '#10b981', fontWeight: 600 }}>
                        {selectedInstrumentType === 'FUTURES'
                          ? 'Verified by Webull at order acceptance'
                          : ['BUY', 'BUY_TO_CLOSE'].includes(orderForm.side) ? `-$${number(orderTotal)}` : `+$${number(orderTotal)}`}
                      </span>
                    </div>
                  </div>

                  {/* Options Payoff Chart Preview */}
                  {selectedInstrumentType === 'OPTION' && orderForm.optionStrike && orderForm.optionExpiration && (
                    <div style={{ marginTop: '20px', marginBottom: '20px' }}>
                      <OptionsPayoffChart
                        underlyingSymbol={selectedSymbol}
                        baselinePrice={Number(optionUnderlyingPrice || orderForm.optionStrike)}
                        strikePrice={Number(orderForm.optionStrike)}
                        entryPremium={Number(orderForm.price || 0)}
                        multiplier={100}
                        quantity={Number(orderForm.quantity || 0)}
                        iv={0.1501}
                        riskFreeRate={0.0379}
                        expirationDate={orderForm.optionExpiration}
                        startingDTE={differenceInEasternCalendarDays(orderForm.optionExpiration)}
                        optionType={orderForm.optionType}
                        action={orderForm.side}
                        onStrikeSelect={handlePayoffChartStrikeSelect}
                      />
                    </div>
                  )}

                  {/* Row 5: Action Button (Binance parity) */}
                  <div className="order-submit-row">
                    <button
                      type="submit"
                      className={`modern-submit-button ${orderForm.side.toLowerCase()}`}
                      disabled={orderSubmitting || ticketOrderControlsDisabled || assetClassDisabled(selectedInstrumentType)}
                    >
                      {orderSubmitting ? (
                        <span>⏳ Processing Order...</span>
                      ) : isTestMode ? (
                        <span>
                          🧪 Place Simulated {orderTypeLabel(orderForm.type)} {orderForm.side === 'BUY' ? (selectedInstrumentType === 'EVENT' ? 'Buy to Open' : 'Buy') : orderForm.side === 'BUY_TO_CLOSE' ? 'Cover' : orderForm.side === 'SHORT' ? 'Short' : (selectedInstrumentType === 'EVENT' ? 'Sell to Close' : 'Sell')} Order (Paper)
                        </span>
                      ) : (
                        <span>
                          ⚡ Place Real {orderTypeLabel(orderForm.type)} {orderForm.side === 'BUY' ? (selectedInstrumentType === 'EVENT' ? 'Buy to Open' : 'Buy') : orderForm.side === 'BUY_TO_CLOSE' ? 'Cover' : orderForm.side === 'SHORT' ? 'Short' : (selectedInstrumentType === 'EVENT' ? 'Sell to Close' : 'Sell')} Order
                        </span>
                      )}
                    </button>
                  </div>

                  {/* Row 6: Warning in Real / Test Trading Mode */}
                  {isTestMode ? (
                    <div className="modern-real-warning" style={{ marginTop: '12px', background: 'rgba(79, 209, 197, 0.15)', borderColor: 'rgba(79, 209, 197, 0.35)', color: '#4fd1c5' }}>
                      🧪 <strong>TEST MODE ACTIVE:</strong> You are paper trading with simulated cash (${number(cashBalance)} USD available). Option fills obey regular U.S. options market hours, and no real orders are sent to Webull.
                    </div>
                  ) : (
                    <div className="modern-real-warning" style={{ marginTop: '12px' }}>
                      ⚠️ <strong>WARNING:</strong> You are in REAL TRADING MODE. This will execute an actual live order on Webull OpenAPI.
                    </div>
                  )}
                </form>
                </div>

                {/* Pre-Trade Confirmation Modal */}
                {showConfirmModal && (
                  <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }}>
                    <div style={{ background: 'var(--card-bg, #1e293b)', borderRadius: '14px', padding: '28px', maxWidth: '480px', width: '100%', border: '1px solid rgba(255,255,255,0.15)', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.5)' }}>
                      <h3 style={{ margin: '0 0 16px', fontSize: '1.4rem' }}>
                        {isTestMode ? '🧪 Confirm Simulated Order' : 'Confirm Webull Order'}
                      </h3>
                      <p style={{ color: '#94a3b8', fontSize: '0.9rem', marginBottom: '20px' }}>
                        {isTestMode
                          ? 'Please review the simulated trade details below. This will be submitted to the isolated Paper Trading engine under the applicable market-hours rules.'
                          : 'Please review the details below. This will transmit an active order to Webull OpenAPI.'}
                      </p>
                      <div style={{ background: 'rgba(0,0,0,0.25)', padding: '16px', borderRadius: '8px', marginBottom: '20px', display: 'grid', gap: '10px', fontSize: '0.95rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Account:</span>
                          <strong>{activeAccount?.account_label || activeAccount?.account_name || 'Webull Account'} ({activeAccount?.account_id_masked || selectedAccountId})</strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Action:</span>
                          <strong style={{ color: orderForm.side === 'BUY' ? '#10b981' : '#ef4444' }}>{formatOrderSide(orderForm.side)}</strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Symbol &amp; Asset:</span>
                          <strong>{selectedSymbol} ({selectedInstrumentType === 'EQUITY' ? selectedSecurityType : selectedInstrumentType})</strong>
                        </div>
                        {selectedInstrumentType === 'OPTION' && (
                          <>
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                              <span style={{ color: '#94a3b8' }}>Strategy:</span>
                              <strong style={{ color: '#c4b5fd' }}>{optionStrategyDefinition(orderForm.optionStrategy).label}</strong>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                              <span style={{ color: '#94a3b8' }}>Option Contract:</span>
                              <strong style={{ color: '#c4b5fd' }}>
                                {selectedSymbol} {orderForm.optionType} ${orderForm.optionStrike} Exp: {orderForm.optionExpiration}
                              </strong>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                              <span style={{ color: '#94a3b8' }}>Multiplier:</span>
                              <span>100 Shares / Contract</span>
                            </div>
                            {optionIsSingle && Number(orderForm.optionStrike) > 0 && Number(orderForm.price) > 0 && (
                              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                <span style={{ color: '#94a3b8' }}>Breakeven Price:</span>
                                <strong style={{ color: '#38bdf8' }}>
                                  ${(orderForm.optionType === 'CALL'
                                    ? Number(orderForm.optionStrike) + Number(orderForm.price)
                                    : Number(orderForm.optionStrike) - Number(orderForm.price)).toFixed(2)}
                                </strong>
                              </div>
                            )}
                            {!optionIsSingle && orderForm.optionStrategyLegs?.length > 0 && (
                              <div style={{ display: 'grid', gap: 4 }}>
                                <span style={{ color: '#94a3b8' }}>Strategy Legs:</span>
                                {orderForm.optionStrategyLegs.map((leg, index) => (
                                  <small key={`${leg.instrument_type}-${leg.option_expire_date || ''}-${leg.strike_price || ''}-${index}`} style={{ color: '#cbd5e1' }}>
                                    {index + 1}. {formatOrderSide(leg.side)} {leg.quantity} × {leg.instrument_type === 'EQUITY' ? `${selectedSymbol} shares` : `${selectedSymbol} ${leg.option_expire_date} $${leg.strike_price} ${leg.option_type}`}
                                  </small>
                                ))}
                              </div>
                            )}
                          </>
                        )}
                        {selectedInstrumentType === 'EVENT' && (
                          <>
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                              <span style={{ color: '#94a3b8' }}>Contract Outcome:</span>
                              <strong style={{ color: String(orderForm.eventOutcome || '').toLowerCase() === 'yes' ? '#4ade80' : '#f87171' }}>
                                {String(orderForm.eventOutcome || '').toUpperCase() === 'YES' ? '👍 YES (Event Occurs)' : '👎 NO (Event Does Not Occur)'}
                              </strong>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                              <span style={{ color: '#94a3b8' }}>Settlement Value:</span>
                              <span style={{ color: '#e2e8f0' }}>{eventMoney(eventSettlementPayout)} on win / $0.00 on loss</span>
                            </div>
                          </>
                        )}
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Order Type:</span>
                          <strong>
                            {formatOrderType(orderForm.type)}
                            {orderForm.type === 'LIMIT' && ` @ $${number(orderForm.price)}`}
                            {orderForm.type === 'STOP_LOSS' && ` (Stop Trigger: $${number(orderForm.stopPrice)})`}
                            {orderForm.type === 'STOP_LOSS_LIMIT' && ` (Stop: $${number(orderForm.stopPrice)}, Limit: $${number(orderForm.price)})`}
                          </strong>
                        </div>
                        {orderForm.type === 'TRAILING_STOP_LOSS' && (
                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span style={{ color: '#94a3b8' }}>Trailing Stop:</span>
                            <strong>
                              {orderForm.trailingType === 'PERCENTAGE'
                                ? `${number(orderForm.trailingStopStep)}%`
                                : `$${number(orderForm.trailingStopStep)} USD`}
                            </strong>
                          </div>
                        )}
                        {selectedInstrumentType === 'EQUITY' && orderForm.isBracketEnabled && (
                          <>
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                              <span style={{ color: '#94a3b8' }}>Attached Bracket:</span>
                              <strong>Enabled</strong>
                            </div>
                            {orderForm.bracketTakeProfitPrice && (
                              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                <span style={{ color: '#94a3b8' }}>Take Profit:</span>
                                <strong>${number(orderForm.bracketTakeProfitPrice)}</strong>
                              </div>
                            )}
                            {orderForm.bracketStopLossPrice && (
                              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                <span style={{ color: '#94a3b8' }}>Stop Loss Trigger:</span>
                                <strong>${number(orderForm.bracketStopLossPrice)}</strong>
                              </div>
                            )}
                            {orderForm.bracketStopLossLimitPrice && (
                              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                <span style={{ color: '#94a3b8' }}>Stop Loss Limit:</span>
                                <strong>${number(orderForm.bracketStopLossLimitPrice)}</strong>
                              </div>
                            )}
                          </>
                        )}
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Quantity:</span>
                          <strong>{number(orderForm.quantity, selectedInstrumentType === 'CRYPTO' ? 6 : 2)}</strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Estimated Total:</span>
                          <strong style={{ color: '#38bdf8' }}>
                            {orderTotal > 0 ? `$${number(orderTotal)}` : 'Market Price'}
                          </strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Time in Force / Session:</span>
                          <span>{formatTimeInForce(orderForm.timeInForce)} · {selectedInstrumentType === 'OPTION' ? 'Regular Options Session' : orderForm.tradingSession === 'CORE' ? 'Regular Hours' : orderForm.tradingSession === 'NIGHT' ? 'Overnight Hours Only' : 'Including Extended Hours'}</span>
                        </div>
                      </div>

                      <div style={{ display: 'flex', gap: '12px' }}>
                        <button
                          type="button"
                          className="btn btn-secondary"
                          style={{ flex: 1, padding: '12px' }}
                          disabled={orderSubmitting}
                          onClick={() => setShowConfirmModal(false)}
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          className="btn btn-primary"
                          style={{
                            flex: 1,
                            padding: '12px',
                            background: orderForm.side === 'BUY' ? '#10b981' : '#ef4444',
                            border: 'none',
                            fontWeight: 'bold',
                          }}
                          disabled={orderSubmitting}
                          onClick={() => handleConfirmSubmit()}
                        >
                          {orderSubmitting ? 'Submitting…' : 'Confirm Order'}
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* Holdings Table Below */}
                <WebullHoldings holdings={modeHoldings} onSelectHolding={handleSelectHolding} isTestMode={isTestMode} />
              </div>
            )}

            {/* COMBO ORDERS (OTO / OCO / OTOCO) BUILDER TAB */}
            {activeTab === 'combo' && (
              <div className="order-form-container">
                <div className="combo-builder-card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
                    <div>
                      <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        🔗 Webull Multi-Leg Combo Order Builder
                      </h2>
                      <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#94a3b8' }}>
                        Place native Webull conditional combo orders (OTO, OCO, OTOCO) across linked stock execution legs.
                      </p>
                    </div>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      {['OTOCO', 'OTO', 'OCO'].map((type) => (
                        <button
                          key={type}
                          type="button"
                          className={`btn ${comboForm.comboType === type ? 'btn-primary' : 'btn-secondary'}`}
                          style={{
                            padding: '6px 14px',
                            fontSize: '12px',
                            fontWeight: 700,
                            borderRadius: '6px',
                            background: comboForm.comboType === type ? '#3b82f6' : 'rgba(255,255,255,0.05)',
                            borderColor: comboForm.comboType === type ? '#3b82f6' : '#334155',
                          }}
                          onClick={() => {
                            if (type === 'OTO') {
                              setComboForm((prev) => ({
                                ...prev,
                                comboType: 'OTO',
                                legs: [
                                  { id: '1', role: 'MASTER', side: 'BUY', order_type: 'LIMIT', price: '', stopPrice: '', quantity: '1', timeInForce: 'DAY', session: 'CORE' },
                                  { id: '2', role: 'OTO', side: 'SELL', order_type: 'LIMIT', price: '', stopPrice: '', quantity: '1', timeInForce: 'DAY', session: 'CORE' },
                                ],
                              }));
                            } else if (type === 'OCO') {
                              setComboForm((prev) => ({
                                ...prev,
                                comboType: 'OCO',
                                legs: [
                                  { id: '1', role: 'OCO', side: 'SELL', order_type: 'LIMIT', price: '', stopPrice: '', quantity: '1', timeInForce: 'DAY', session: 'CORE' },
                                  { id: '2', role: 'OCO', side: 'SELL', order_type: 'STOP_LOSS', price: '', stopPrice: '', quantity: '1', timeInForce: 'DAY', session: 'CORE' },
                                ],
                              }));
                            } else {
                              setComboForm((prev) => ({
                                ...prev,
                                comboType: 'OTOCO',
                                legs: [
                                  { id: '1', role: 'MASTER', side: 'BUY', order_type: 'LIMIT', price: '', stopPrice: '', quantity: '1', timeInForce: 'DAY', session: 'CORE' },
                                  { id: '2', role: 'OTOCO', side: 'SELL', order_type: 'LIMIT', price: '', stopPrice: '', quantity: '1', timeInForce: 'DAY', session: 'CORE' },
                                  { id: '3', role: 'OTOCO', side: 'SELL', order_type: 'STOP_LOSS', price: '', stopPrice: '', quantity: '1', timeInForce: 'DAY', session: 'CORE' },
                                ],
                              }));
                            }
                          }}
                        >
                          {formatOrderType(type)}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Stock Symbol Input */}
                  <div style={{ marginBottom: '16px', maxWidth: '300px' }}>
                    <label className="order-field-label">Stock Symbol</label>
                    <input
                      type="text"
                      value={comboForm.symbol}
                      onChange={(e) => setComboForm((prev) => ({ ...prev, symbol: e.target.value.toUpperCase() }))}
                      placeholder="e.g. AAPL, NVDA, TSLA"
                      className="order-styled-input"
                      style={{ fontWeight: 700 }}
                    />
                  </div>

                  {/* Legs List */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '20px' }}>
                    {comboForm.legs.map((leg, idx) => (
                      <div key={leg.id} className="combo-leg-card">
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                          <span className={`combo-leg-badge ${leg.role === 'MASTER' ? 'master' : 'dependent'}`}>
                            Leg #{idx + 1} · {formatComboRole(leg.role)}
                          </span>
                          <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                            {leg.role === 'MASTER' ? 'Primary Trigger Order' : leg.role === 'OTOCO' ? 'Bracket Sub-Order (One-Cancels-Other)' : 'Dependent Triggered Order'}
                          </span>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '12px' }}>
                          <div>
                            <label className="order-field-label">Side</label>
                            <select
                              value={leg.side}
                              onChange={(e) => {
                                const val = e.target.value;
                                setComboForm((prev) => ({
                                  ...prev,
                                  legs: prev.legs.map((l, i) => i === idx ? { ...l, side: val } : l),
                                }));
                              }}
                              className="order-styled-input"
                            >
                              <option value="BUY">{formatOrderSide('BUY')}</option>
                              <option value="SELL">{formatOrderSide('SELL')}</option>
                              <option value="SHORT">{formatOrderSide('SHORT')}</option>
                            </select>
                          </div>

                          <div>
                            <label className="order-field-label">Order Type</label>
                            <select
                              value={leg.order_type}
                              onChange={(e) => {
                                const val = e.target.value;
                                setComboForm((prev) => ({
                                  ...prev,
                                  legs: prev.legs.map((l, i) => i === idx ? { ...l, order_type: val } : l),
                                }));
                              }}
                              className="order-styled-input"
                            >
                              <option value="LIMIT">{formatOrderType('LIMIT')}</option>
                              <option value="MARKET">{formatOrderType('MARKET')}</option>
                              <option value="STOP_LOSS">{formatOrderType('STOP_LOSS')}</option>
                              <option value="STOP_LOSS_LIMIT">{formatOrderType('STOP_LOSS_LIMIT')}</option>
                            </select>
                          </div>

                          <div>
                            <label className="order-field-label">Quantity</label>
                            <input
                              type="text"
                              inputMode="decimal"
                              value={leg.quantity}
                              onChange={(e) => {
                                const val = e.target.value.replace(/[^0-9.]/g, '');
                                setComboForm((prev) => ({
                                  ...prev,
                                  legs: prev.legs.map((l, i) => i === idx ? { ...l, quantity: val } : l),
                                }));
                              }}
                              placeholder="Quantity"
                              className="order-styled-input"
                            />
                          </div>

                          {['LIMIT', 'STOP_LOSS_LIMIT'].includes(leg.order_type) && (
                            <div>
                              <label className="order-field-label">Limit Price ($)</label>
                              <input
                                type="text"
                                inputMode="decimal"
                                value={leg.price}
                                onChange={(e) => {
                                  const val = e.target.value.replace(/[^0-9.]/g, '');
                                  setComboForm((prev) => ({
                                    ...prev,
                                    legs: prev.legs.map((l, i) => i === idx ? { ...l, price: val } : l),
                                  }));
                                }}
                                placeholder="0.00"
                                className="order-styled-input"
                              />
                            </div>
                          )}

                          {['STOP_LOSS', 'STOP_LOSS_LIMIT'].includes(leg.order_type) && (
                            <div>
                              <label className="order-field-label">Stop Price ($)</label>
                              <input
                                type="text"
                                inputMode="decimal"
                                value={leg.stopPrice}
                                onChange={(e) => {
                                  const val = e.target.value.replace(/[^0-9.]/g, '');
                                  setComboForm((prev) => ({
                                    ...prev,
                                    legs: prev.legs.map((l, i) => i === idx ? { ...l, stopPrice: val } : l),
                                  }));
                                }}
                                placeholder="0.00"
                                className="order-styled-input"
                              />
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>

                  <button
                    type="button"
                    className="btn btn-primary"
                    style={{
                      width: '100%',
                      padding: '14px',
                      fontSize: '1rem',
                      fontWeight: 700,
                      background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
                      border: 'none',
                      borderRadius: '8px',
                      cursor: 'pointer',
                    }}
                    disabled={orderSubmitting}
                    onClick={handleComboSubmit}
                  >
                    {orderSubmitting ? 'Submitting Combo Order…' : `Submit Webull ${formatOrderType(comboForm.comboType)} Order`}
                  </button>
                </div>
              </div>
            )}

            {/* OPEN ORDERS TAB */}
            {activeTab === 'open_orders' && (
              <section className="order-history-container">
                <h2>Webull Open Orders</h2>
                <WebullOrderTable
                  orders={displayOpenOrders}
                  emptyText="No Webull open orders found."
                  onCancelOrder={openCancelModalForOrder}
                  cancellingId={cancellingOrderId}
                  optionClosePnlByOrder={optionClosePnlByOrder}
                />
              </section>
            )}

            {/* ORDER HISTORY TAB */}
            {activeTab === 'history' && (
              <section className="order-history-container">
                <h2>Webull Order History</h2>
                {historyLoading && !sortedHistory.length ? (
                  <div className="empty-state"><p>Loading Webull order history…</p></div>
                ) : (
                  <>
                    <WebullOrderTable orders={paginatedHistory} emptyText="No Webull order history is available yet." />
                    <Pagination page={historyPage} setPage={setHistoryPage} pageSize={historyPageSize} setPageSize={setHistoryPageSize} total={sortedHistory.length} />
                  </>
                )}
              </section>
            )}

            {/* TRADE CHART TAB */}
            {activeTab === 'trade_chart' && (
              <section className="order-history-container">
                <WebullTradeTimelineChart holdings={modeHoldings} orders={modeHistory} isLightMode={isLightMode} isTestMode={isTestMode} />
              </section>
            )}

            {/* AI ANALYSIS TAB */}
            {!isTestMode && activeTab === 'ai_analysis' && (
              <WebullAIDashboard isLightMode={isLightMode} />
            )}
          </>
        )}
      </div>
      <TwoFactorModal
        isVisible={twoFactorModal.isVisible}
        onClose={() => setTwoFactorModal({ isVisible: false, orderData: null })}
        onVerify={handleTwoFactorVerify}
        orderDetails={twoFactorModal.orderData}
      />
      <CancelOrderModal
        isVisible={cancelModal.isVisible}
        onClose={closeCancelModal}
        onConfirm={handleCancelOpenOrder}
        order={cancelModal.order}
        loading={cancelModal.loading}
        error={cancelModal.error}
        requiresTwoFactor={!isTestMode}
      />

      <PercentPriceModal
        isOpen={percentModal.isOpen}
        onClose={() => setPercentModal((prev) => ({ ...prev, isOpen: false }))}
        onApply={handleApplyPercentPrices}
        orderType={orderForm.type}
        side={orderForm.side}
        targetField={percentModal.targetField}
        symbol={selectedSymbol}
        baseAsset={selectedSymbol}
        quoteAsset="USD"
        currentPrice={livePrice}
        avgEntry={Number(currentHolding?.avg_entry || currentHolding?.cost_price || 0) > 0 ? Number(currentHolding?.avg_entry || currentHolding?.cost_price) : null}
      />

      {/* Paper Deposit Modal */}
      {showDepositModal && (
        <div className="modal-overlay" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999, padding: '20px' }}>
          <div className="modal-content" style={{ background: 'var(--card-bg, #1e293b)', border: '1px solid rgba(79, 209, 197, 0.4)', borderRadius: '16px', maxWidth: '460px', width: '100%', padding: '28px', boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.6)' }}>
            <h3 style={{ margin: '0 0 10px', fontSize: '1.4rem', display: 'flex', alignItems: 'center', gap: '8px', color: '#4fd1c5' }}>
              💰 Deposit Fake Money
            </h3>
            <p style={{ color: '#94a3b8', fontSize: '0.9rem', marginBottom: '20px', lineHeight: 1.5 }}>
              Add simulated funds to your Webull Paper Trading account to practice trades across stocks, ETFs, crypto, options, and futures using real-time market pricing.
            </p>

            <div style={{ marginBottom: '20px', padding: '14px 18px', background: 'rgba(15, 23, 42, 0.6)', borderRadius: '10px', border: '1px solid rgba(255, 255, 255, 0.1)' }}>
              <div style={{ fontSize: '0.85rem', color: '#94a3b8', marginBottom: '4px' }}>Current Paper Cash Available</div>
              <div style={{ fontSize: '1.6rem', fontWeight: 800, color: '#10b981' }}>
                ${number(cashBalance)} <small style={{ fontSize: '0.9rem', color: '#94a3b8', fontWeight: 500 }}>USD</small>
              </div>
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.88rem', color: '#cbd5e1', fontWeight: 600 }}>
                Quick Deposit Presets:
              </label>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px', marginBottom: '14px' }}>
                {[1000, 5000, 10000].map((amt) => (
                  <button
                    key={amt}
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setDepositAmount(String(amt))}
                    style={{ fontWeight: 600, padding: '10px 8px', fontSize: '0.95rem' }}
                  >
                    +${amt.toLocaleString()}
                  </button>
                ))}
              </div>

              <label style={{ display: 'block', marginBottom: '6px', fontSize: '0.85rem', color: '#94a3b8' }}>
                Or Custom Deposit Amount ($ USD):
              </label>
              <input
                type="number"
                min="1"
                step="any"
                value={depositAmount}
                onChange={(e) => setDepositAmount(e.target.value)}
                placeholder="e.g. 1000"
                style={{
                  width: '100%',
                  padding: '12px 14px',
                  borderRadius: '8px',
                  border: '1px solid rgba(79, 209, 197, 0.4)',
                  background: 'rgba(15, 23, 42, 0.9)',
                  color: '#ffffff',
                  fontSize: '1.1rem',
                  fontWeight: 600,
                  boxSizing: 'border-box'
                }}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '24px', gap: '10px', flexWrap: 'wrap' }}>
              <button
                type="button"
                className="btn btn-outline-danger"
                onClick={handleResetPaperAccount}
                title="Reset cash to $0.00, clear simulated positions, and cancel active simulated orders"
                style={{
                  fontSize: '0.85rem',
                  padding: '8px 12px',
                  borderColor: '#ef4444',
                  color: '#ef4444',
                  background: 'transparent',
                  cursor: 'pointer'
                }}
              >
                🔄 Reset Account
              </button>
              <div style={{ display: 'flex', gap: '10px' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowDepositModal(false)}
                  style={{ padding: '8px 16px' }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn-success"
                  disabled={depositSubmitting || !depositAmount || Number(depositAmount) <= 0}
                  onClick={handleDepositFakeMoney}
                  style={{
                    background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
                    border: 'none',
                    fontWeight: 600,
                    padding: '8px 18px',
                    color: '#fff',
                    borderRadius: '6px',
                    cursor: 'pointer'
                  }}
                >
                  {depositSubmitting ? 'Depositing...' : 'Confirm Deposit'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function WebullSignalTable({ signals }) {
  if (!signals.length) return <div className="empty-state"><p>No stored Webull signals yet. Current signals remain tracking until their saved evaluation time.</p></div>;
  const outcomeColor = { correct: '#22c55e', neutral: '#38bdf8', wrong: '#ef4444', tracking: '#fbbf24' };
  return (
    <div className="table-container trading-table">
      <div className="order-table-scroll">
        <table>
          <thead>
            <tr>
              <th>Created</th><th style={{ textAlign: 'center' }}>Symbol</th><th>Asset Class</th><th>Signal</th><th>Forecast</th><th>Outcome</th><th>Origin</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((signal) => (
              <tr key={signal.id}>
                <td>{formatDate(signal.created_at)}</td>
                <td style={{ textAlign: 'center' }}>{signal.symbol}</td>
                <td>{signal.instrument_type}</td>
                <td><strong>{signal.recommendation}</strong><br /><small>{signal.reason}</small></td>
                <td>{signal.forecast_horizon_hours}h · target {formatDate(signal.target_evaluation_at)}</td>
                <td style={{ color: outcomeColor[signal.outcome_status] || 'inherit' }}>
                  {signal.outcome_status || 'tracking'}
                  {signal.outcome_pct != null ? ` (${Number(signal.outcome_pct).toFixed(2)}%)` : ''}
                </td>
                <td>{signal.origin}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function WebullHoldings({ holdings, compact = false, onSelectHolding, isTestMode = false }) {
  if (!holdings.length) {
    return (
      <div className="empty-state">
        <p>
          {isTestMode
            ? 'No simulated holdings yet. Place a test order above to build your paper portfolio!'
            : 'No imported Webull holdings. Import a Webull portfolio snapshot in Settings first.'}
        </p>
      </div>
    );
  }
  const showOptionColumns = holdings.some((holding) => optionContractDetails(holding).isOption);
  return (
    <div className="table-container trading-table" style={{ marginTop: compact ? 12 : 20 }}>
      <div className="order-table-scroll">
        <table>
          <thead>
            <tr>
              <th style={{ textAlign: 'center' }}>Symbol</th>
              {showOptionColumns && <><th>Expiration</th><th>Strike</th><th>Call / Put</th></>}
              <th>Asset Class</th><th>Position</th><th>Quantity</th><th>Available</th><th>Last Price</th><th>Value</th><th>Unrealized P&amp;L</th><th style={{ textAlign: 'center' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {holdings.map((holding) => {
              const option = optionContractDetails(holding);
              const isOption = option.isOption;
              return (
                <tr
                  key={holding.id}
                  onClick={() => onSelectHolding?.(holding)}
                  style={{ cursor: onSelectHolding ? 'pointer' : 'default' }}
                  title={onSelectHolding ? `Click to load ${isOption ? `${option.symbol} ${option.expiration} $${option.strike} ${option.optionType}` : option.symbol} into the order terminal` : undefined}
                >
                  <td style={{ textAlign: 'center' }}>
                    <div style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8, textAlign: 'left' }}>
                      <CryptoIcon symbol={option.symbol} size={22} />
                      <span>
                        {option.symbol}
                        {(holding.is_paper || isTestMode) && (
                          <span className="badge" style={{ background: 'rgba(79, 209, 197, 0.2)', color: '#4fd1c5', border: '1px solid rgba(79, 209, 197, 0.4)', marginLeft: 6, fontSize: '0.7rem', fontWeight: 700 }}>
                            PAPER
                          </span>
                        )}
                      </span>
                    </div>
                  </td>
                  {showOptionColumns && <>
                    <td>{isOption ? option.expiration || '—' : '—'}</td>
                    <td>{isOption ? option.strikeLabel : '—'}</td>
                    <td>{isOption ? option.optionType || '—' : '—'}</td>
                  </>}
                  <td>
                    {holding.instrument_type || 'Security'}
                    {isOption && !holding.instrument_id && !holding.is_paper && <small style={{ display: 'block', color: '#fbbf24' }}>Contract resolution needed</small>}
                  </td>
                  <td>{String(holding.position_side || holding.side || 'LONG').toUpperCase() === 'SHORT' ? 'Short' : 'Long'}</td>
                  <td>{number(holding.quantity ?? holding.amount, 6)}</td>
                  <td>{number(holding.available_quantity ?? holding.quantity ?? holding.amount, 6)}</td>
                  <td>{(holding.current_price ?? holding.last_price) ? `$${number(holding.current_price ?? holding.last_price, 4)}` : '—'}</td>
                  <td>{(holding.current_value ?? holding.market_value) != null ? `$${number(holding.current_value ?? holding.market_value)}` : '—'}</td>
                  <td style={{ color: Number(holding.webull_unrealized_pnl ?? holding.unrealized_profit_loss) >= 0 ? '#4ade80' : '#f87171' }}>
                    {(holding.webull_unrealized_pnl ?? holding.unrealized_profit_loss) == null ? '—' : `$${number(holding.webull_unrealized_pnl ?? holding.unrealized_profit_loss)}`}
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <button
                      type="button"
                      className="badge"
                      style={{
                        background: 'rgba(56, 189, 248, .18)',
                        border: '1px solid rgba(56, 189, 248, .35)',
                        color: '#38bdf8',
                        cursor: 'pointer',
                        padding: '5px 14px',
                        fontWeight: 700,
                        borderRadius: '6px',
                        fontSize: '0.82rem',
                        transition: 'all 0.2s ease',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = 'rgba(56, 189, 248, .35)';
                        e.currentTarget.style.color = '#ffffff';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'rgba(56, 189, 248, .18)';
                        e.currentTarget.style.color = '#38bdf8';
                      }}
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectHolding?.(holding);
                      }}
                      title={`Load ${isOption ? `${option.symbol} ${option.expiration} $${option.strike} ${option.optionType}` : option.symbol} into trade ticket`}
                    >
                      Trade
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
