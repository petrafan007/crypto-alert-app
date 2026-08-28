import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import CryptoIcon from '../components/CryptoIcon';
import WebullTradingViewChart from '../components/WebullTradingViewChart';
import WebullTradeTimelineChart from '../components/WebullTradeTimelineChart';
import './Trading.css';

const OPEN_STATUSES = new Set(['OPEN', 'NEW', 'WORKING', 'PENDING', 'PARTIALLY_FILLED', 'PARTIALLY FILLED']);
const PAGE_SIZES = [20, 50, 100, 200];

const number = (value, digits = 2) => {
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
    : '—';
};

const formatDate = (value) => {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
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

function WebullOrderTable({ orders, emptyText, onCancelOrder, cancellingId }) {
  if (!orders.length) return <div className="empty-state"><p>{emptyText}</p></div>;
  return (
    <div className="table-container trading-table">
      <div className="order-table-scroll">
        <table>
          <thead>
            <tr>
              <th>Date / Time</th><th>Symbol</th><th>Side</th><th>Type</th><th>Quantity</th><th>Price</th><th>Filled</th><th>Status</th><th>Source</th>
              {onCancelOrder && <th>Action</th>}
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr key={order.id}>
                <td>{formatDate(order.created_at)}</td>
                <td>{order.symbol}</td>
                <td>{order.side}</td>
                <td>{order.order_type}</td>
                <td>{number(order.quantity, 6)}</td>
                <td>{order.price ? `$${number(order.price, 4)}` : 'Market'}</td>
                <td>{number(order.filled_quantity, 6)}</td>
                <td>{order.status}</td>
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
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function WebullTrading({ isLightMode = false }) {
  const [activeTab, setActiveTab] = useState('order');
  const [holdings, setHoldings] = useState([]);
  const [history, setHistory] = useState([]);
  const [openOrders, setOpenOrders] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [selectedAccountId, setSelectedAccountId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [cancellingOrderId, setCancellingOrderId] = useState(null);

  // Selected Instrument & Chart state
  const [selectedSymbol, setSelectedSymbol] = useState('AAPL');
  const [selectedInstrumentType, setSelectedInstrumentType] = useState('EQUITY');
  const [livePrice, setLivePrice] = useState(0);

  // Order Placement Form State (mirroring Binance.US Trading)
  const [orderForm, setOrderForm] = useState({
    side: 'BUY',
    type: 'LIMIT',
    quantity: '',
    quoteQuantity: '',
    price: '',
    timeInForce: 'DAY',
    tradingSession: 'CORE',
  });
  const [balancePercentage, setBalancePercentage] = useState(0);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [orderSubmitting, setOrderSubmitting] = useState(false);
  const [orderFeedback, setOrderFeedback] = useState({ type: '', message: '' });

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

  const load = async () => {
    setLoading(true); setError('');
    try {
      const [portfolioResponse, historyResponse, openResponse, signalsResponse, signalSettingsResponse, previewResponse] = await Promise.all([
        axios.get('/api/coin-data-live', { withCredentials: true }),
        axios.get('/api/trading/real-orders?limit=all', { withCredentials: true }),
        axios.get('/api/webull/open-orders', { withCredentials: true }),
        axios.get('/api/webull/ai-signals?limit=50', { withCredentials: true }),
        axios.get('/api/webull/ai-settings', { withCredentials: true }),
        axios.get('/api/webull/portfolio-preview', { withCredentials: true }).catch(() => ({ data: { accounts: [] } })),
      ]);
      const importedHoldings = (portfolioResponse.data?.portfolio || []).filter((item) => item?.is_external || item?.source === 'webull');
      setHoldings(importedHoldings);
      setHistory((historyResponse.data?.orders || [])
        .filter((order) => String(order?.source || '').toLowerCase() === 'webull')
        .map(normalizeOrder));
      setOpenOrders((openResponse.data?.orders || []).map(normalizeOrder));
      setSignals(signalsResponse.data?.signals || []);
      setSignalSettings((current) => ({ ...current, ...(signalSettingsResponse.data?.settings || {}) }));

      let discoveredAccounts = previewResponse.data?.accounts || [];
      if (!discoveredAccounts.length) {
        try {
          const accRes = await axios.get('/api/webull/accounts', { withCredentials: true });
          discoveredAccounts = accRes.data?.accounts || [];
        } catch (e) {}
      }
      setAccounts(discoveredAccounts);
      if (discoveredAccounts.length && !selectedAccountId) {
        setSelectedAccountId(discoveredAccounts[0].account_id);
      }

      // If holdings exist and selectedSymbol is default, pick the first holding
      if (importedHoldings.length > 0 && selectedSymbol === 'AAPL') {
        const first = importedHoldings[0];
        setSelectedSymbol(first.symbol);
        const isCrypto = /crypto|coin|token/i.test(first.instrument_type || '');
        setSelectedInstrumentType(isCrypto ? 'CRYPTO' : 'EQUITY');
        if (first.current_price) {
          setLivePrice(Number(first.current_price));
          setOrderForm((prev) => ({ ...prev, price: Number(first.current_price).toFixed(2) }));
        }
      }

      if (openResponse.data?.success === false) setError(openResponse.data?.message || 'Unable to load Webull open orders.');
    } catch (requestError) {
      setError(requestError.response?.data?.message || 'Unable to load the Webull workspace.');
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  // Sync active account and cash balance
  const activeAccount = useMemo(() => accounts.find((a) => a.account_id === selectedAccountId) || accounts[0], [accounts, selectedAccountId]);
  const cashBalance = useMemo(() => {
    if (!activeAccount?.balance) return 0;
    const b = activeAccount.balance;
    return Number(b.total_cash_balance ?? b.cash_balance ?? b.settled_cash ?? b.cashBalance ?? 0);
  }, [activeAccount]);

  // Holding for the currently selected symbol
  const currentHolding = useMemo(() => {
    const clean = selectedSymbol.toUpperCase();
    return holdings.find((h) => h.symbol.toUpperCase() === clean || h.symbol.toUpperCase() === clean.replace(/USD$/, ''));
  }, [holdings, selectedSymbol]);

  const heldQuantity = useMemo(() => Number(currentHolding?.amount || 0), [currentHolding]);
  const heldValue = useMemo(() => Number(currentHolding?.current_value || (heldQuantity * livePrice) || 0), [currentHolding, heldQuantity, livePrice]);

  // Update live price and limit price when symbol or holdings change
  useEffect(() => {
    if (currentHolding?.current_price) {
      const px = Number(currentHolding.current_price);
      setLivePrice(px);
      setOrderForm((prev) => (prev.price ? prev : { ...prev, price: px.toFixed(2) }));
    } else {
      // Fetch latest market bar for quote
      const cleanSymbol = selectedInstrumentType === 'CRYPTO' && !selectedSymbol.endsWith('USD') ? `${selectedSymbol}USD` : selectedSymbol;
      axios.get(`/api/webull/market-bars?symbol=${cleanSymbol}&instrument_type=${selectedInstrumentType}&limit=1`, { withCredentials: true })
        .then((res) => {
          const bars = res.data?.bars || [];
          if (bars.length > 0 && bars[bars.length - 1]?.close) {
            const px = Number(bars[bars.length - 1].close);
            setLivePrice(px);
            setOrderForm((prev) => (prev.price ? prev : { ...prev, price: px.toFixed(2) }));
          }
        })
        .catch(() => {});
    }
  }, [selectedSymbol, selectedInstrumentType, currentHolding]);

  // Handlers for Instrument change from Top TradingView Chart
  const handleInstrumentChange = ({ symbol, instrumentType }) => {
    setSelectedSymbol(symbol);
    setSelectedInstrumentType(instrumentType);
    setBalancePercentage(0);
    setOrderForm((prev) => ({
      ...prev,
      quantity: '',
      quoteQuantity: '',
      price: '',
    }));
  };

  // Dual Input Quantity / Value calculations
  const effectivePrice = useMemo(() => {
    if (orderForm.type === 'LIMIT' && Number(orderForm.price) > 0) {
      return Number(orderForm.price);
    }
    return livePrice > 0 ? livePrice : (Number(orderForm.price) || 1);
  }, [orderForm.type, orderForm.price, livePrice]);

  const handleBaseQuantityChange = (val) => {
    const qty = val.replace(/[^0-9.]/g, '');
    const numQty = parseFloat(qty) || 0;
    const computedVal = numQty > 0 && effectivePrice > 0 ? (numQty * effectivePrice).toFixed(2) : '';
    setOrderForm((prev) => ({ ...prev, quantity: qty, quoteQuantity: computedVal }));
  };

  const handleQuoteQuantityChange = (val) => {
    const quoteVal = val.replace(/[^0-9.]/g, '');
    const numQuote = parseFloat(quoteVal) || 0;
    const computedQty = numQuote > 0 && effectivePrice > 0
      ? (selectedInstrumentType === 'CRYPTO' ? (numQuote / effectivePrice).toFixed(6) : String(Math.floor(numQuote / effectivePrice)))
      : '';
    setOrderForm((prev) => ({ ...prev, quoteQuantity: quoteVal, quantity: computedQty }));
  };

  const handlePriceChange = (val) => {
    const px = val.replace(/[^0-9.]/g, '');
    setOrderForm((prev) => {
      const numQty = parseFloat(prev.quantity) || 0;
      const numPx = parseFloat(px) || 0;
      const computedQuote = numQty > 0 && numPx > 0 ? (numQty * numPx).toFixed(2) : prev.quoteQuantity;
      return { ...prev, price: px, quoteQuantity: computedQuote };
    });
  };

  // Slider change handler
  const handleSliderChange = (pct) => {
    setBalancePercentage(pct);
    if (pct === 0) {
      setOrderForm((prev) => ({ ...prev, quantity: '', quoteQuantity: '' }));
      return;
    }
    if (orderForm.side === 'BUY') {
      if (cashBalance > 0 && effectivePrice > 0) {
        const targetDollars = cashBalance * (pct / 100);
        const qty = selectedInstrumentType === 'CRYPTO'
          ? (targetDollars / effectivePrice).toFixed(6)
          : String(Math.floor(targetDollars / effectivePrice));
        setOrderForm((prev) => ({
          ...prev,
          quantity: qty,
          quoteQuantity: targetDollars.toFixed(2),
        }));
      }
    } else {
      if (heldQuantity > 0) {
        const targetQty = (heldQuantity * (pct / 100));
        const formattedQty = selectedInstrumentType === 'CRYPTO' ? targetQty.toFixed(6) : String(Math.floor(targetQty));
        const computedVal = (parseFloat(formattedQty) * effectivePrice).toFixed(2);
        setOrderForm((prev) => ({
          ...prev,
          quantity: formattedQty,
          quoteQuantity: computedVal,
        }));
      }
    }
  };

  const orderTotal = useMemo(() => {
    const qty = parseFloat(orderForm.quantity) || 0;
    return qty * effectivePrice;
  }, [orderForm.quantity, effectivePrice]);

  // Pre-trade submit handler
  const handleOrderSubmit = (e) => {
    e.preventDefault();
    setOrderFeedback({ type: '', message: '' });
    if (!selectedAccountId) {
      setOrderFeedback({ type: 'error', message: 'Please select a Webull account.' });
      return;
    }
    if (!selectedSymbol.trim()) {
      setOrderFeedback({ type: 'error', message: 'Please select an instrument.' });
      return;
    }
    const qty = parseFloat(orderForm.quantity);
    if (!qty || qty <= 0) {
      setOrderFeedback({ type: 'error', message: 'Please enter a valid order quantity.' });
      return;
    }
    if (orderForm.type === 'LIMIT') {
      const px = parseFloat(orderForm.price);
      if (!px || px <= 0) {
        setOrderFeedback({ type: 'error', message: 'Limit orders require a limit price greater than $0.' });
        return;
      }
    }
    setShowConfirmModal(true);
  };

  // Transmit order to Webull OpenAPI
  const handleConfirmSubmit = async () => {
    setOrderSubmitting(true);
    try {
      const payload = {
        account_id: selectedAccountId,
        symbol: selectedSymbol.trim().toUpperCase(),
        instrument_type: selectedInstrumentType,
        side: orderForm.side,
        order_type: orderForm.type,
        quantity: Number(orderForm.quantity),
        limit_price: orderForm.type === 'LIMIT' ? Number(orderForm.price) : undefined,
        time_in_force: orderForm.timeInForce,
        support_trading_session: orderForm.tradingSession,
      };

      const response = await axios.post('/api/webull/orders/place', payload, { withCredentials: true });
      if (response.data?.success) {
        setOrderFeedback({ type: 'success', message: response.data.message || 'Webull order placed successfully!' });
        setShowConfirmModal(false);
        setOrderForm((prev) => ({ ...prev, quantity: '', quoteQuantity: '' }));
        setBalancePercentage(0);
        await load();
      } else {
        setOrderFeedback({ type: 'error', message: response.data?.message || 'Failed to place Webull order.' });
        setShowConfirmModal(false);
      }
    } catch (err) {
      setOrderFeedback({
        type: 'error',
        message: err.response?.data?.message || err.message || 'Webull order placement failed.',
      });
      setShowConfirmModal(false);
    } finally {
      setOrderSubmitting(false);
    }
  };

  // Open Orders cancellation
  const handleCancelOpenOrder = async (order) => {
    if (!window.confirm(`Are you sure you want to cancel the open Webull order for ${order.symbol}?`)) {
      return;
    }
    setCancellingOrderId(order.id);
    try {
      const response = await axios.post('/api/webull/orders/cancel', {
        account_id: order._webull_account_id || selectedAccountId,
        order_id: order.id,
        client_order_id: order.client_order_id,
      }, { withCredentials: true });
      if (response.data?.success) {
        setOrderFeedback({ type: 'success', message: response.data.message || 'Order cancelled successfully.' });
        await load();
      } else {
        setOrderFeedback({ type: 'error', message: response.data?.message || 'Unable to cancel order.' });
      }
    } catch (err) {
      setOrderFeedback({
        type: 'error',
        message: err.response?.data?.message || 'Order cancellation failed.',
      });
    } finally {
      setCancellingOrderId(null);
    }
  };

  const displayOpenOrders = useMemo(() => openOrders.filter((order) => OPEN_STATUSES.has(String(order.status).toUpperCase()) || !order.status), [openOrders]);
  const sortedHistory = useMemo(() => [...history].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''))), [history]);
  const historyPages = Math.max(1, Math.ceil(sortedHistory.length / historyPageSize));
  const paginatedHistory = useMemo(() => sortedHistory.slice((historyPage - 1) * historyPageSize, historyPage * historyPageSize), [sortedHistory, historyPage, historyPageSize]);
  useEffect(() => { if (historyPage > historyPages) setHistoryPage(historyPages); }, [historyPage, historyPages]);
  const analyzableHoldings = useMemo(() => holdings.filter((holding) => ['CRYPTO', 'STOCK', 'EQUITY', 'ETF'].includes(String(holding.instrument_type || '').toUpperCase())), [holdings]);
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
      <div className="trading-header" style={{ marginBottom: '18px' }}>
        <div>
          <h1 style={{ fontSize: '2rem', margin: 0 }}>📈 Webull Trading</h1>
          <p style={{ margin: '6px 0 0', color: '#94a3b8' }}>
            Execute orders, manage open positions, and review signals via Webull OpenAPI.
          </p>
        </div>
        <button type="button" className="btn btn-secondary" onClick={load}>🔄 Refresh Webull</button>
      </div>

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
        <button className={`tab-button ${activeTab === 'ai_analysis' ? 'active' : ''}`} onClick={() => setActiveTab('ai_analysis')}>
          🤖 <span className="tab-text">AI Analysis</span>
        </button>
      </div>

      <div className="trading-content">
        {loading ? (
          <div className="empty-state"><p>Loading Webull data…</p></div>
        ) : (
          <>
            {/* PLACE ORDER TAB */}
            {activeTab === 'order' && (
              <div className="order-form-container">
                {/* 1. Full-Width TradingView Advanced Chart with Category & Instrument Selector */}
                <WebullTradingViewChart
                  symbol={selectedSymbol}
                  instrumentType={selectedInstrumentType}
                  onInstrumentChange={handleInstrumentChange}
                  holdings={holdings}
                  isLightMode={isLightMode}
                />

                {/* 2. Redesigned Order Placement Header Cards (matching Binance.US) */}
                <div className="trading-order-header-cards">
                  {/* Selected Asset Available Card */}
                  <div className="trading-asset-card">
                    <CryptoIcon symbol={selectedSymbol} size={32} />
                    <div className="trading-asset-card-details">
                      <span className="trading-asset-card-label">{selectedSymbol} Available</span>
                      <span className="trading-asset-card-value">
                        {number(heldQuantity, selectedInstrumentType === 'CRYPTO' ? 6 : 2)}{' '}
                        <small>{selectedInstrumentType === 'CRYPTO' ? selectedSymbol.replace(/USD$/, '') : 'Shares'}</small>
                      </span>
                      {heldValue > 0 && (
                        <span className="trading-asset-card-sub">
                          ≈ ${number(heldValue)} USD
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Cash / Buying Power Card with Webull Account Selector */}
                  <div className="trading-asset-card">
                    <CryptoIcon symbol="USD" size={32} />
                    <div className="trading-asset-card-details" style={{ width: '100%' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px', gap: '8px' }}>
                        <span className="trading-asset-card-label">USD Cash Available</span>
                        {accounts.length > 0 && (
                          <select
                            value={selectedAccountId}
                            onChange={(e) => setSelectedAccountId(e.target.value)}
                            aria-label="Select Webull Account"
                            style={{
                              padding: '4px 8px',
                              borderRadius: '6px',
                              background: isLightMode ? '#ffffff' : '#0f172a',
                              color: isLightMode ? '#0f172a' : '#f8fafc',
                              border: isLightMode ? '1px solid #cbd5e1' : '1px solid rgba(148, 163, 184, 0.35)',
                              fontSize: '12px',
                              fontWeight: '600',
                              cursor: 'pointer',
                              maxWidth: '220px',
                            }}
                          >
                            {accounts.map((acc) => {
                              const label = acc.account_label || acc.account_name || acc.account_type || 'Account';
                              const numDisplay = acc.account_number || acc.account_id_masked || (acc.account_id ? `••••${String(acc.account_id).slice(-4)}` : '');
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
                        )}
                      </div>
                      <span className="trading-asset-card-value">
                        ${number(cashBalance)} <small>USD</small>
                      </span>
                      <span className="trading-asset-card-sub">
                        {activeAccount?.account_label || activeAccount?.account_name || 'Webull Account'}{' '}
                        ({activeAccount?.account_number || activeAccount?.account_id_masked || (selectedAccountId ? `••••${String(selectedAccountId).slice(-4)}` : '')}) · Ready to trade
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
                <form onSubmit={handleOrderSubmit} className="trading-order-panel">
                  {/* Row 1: Order Side & Order Types */}
                  <div className="order-control-row">
                    <div className="order-control-group side-group">
                      <label className="order-field-label">Order Side</label>
                      <div className="order-side-segmented">
                        <button
                          type="button"
                          className={`order-side-btn buy-side ${orderForm.side === 'BUY' ? 'active' : ''}`}
                          onClick={() => {
                            setOrderForm((prev) => ({ ...prev, side: 'BUY' }));
                            setBalancePercentage(0);
                          }}
                        >
                          📈 Buy
                        </button>
                        <button
                          type="button"
                          className={`order-side-btn sell-side ${orderForm.side === 'SELL' ? 'active' : ''}`}
                          onClick={() => {
                            setOrderForm((prev) => ({ ...prev, side: 'SELL' }));
                            setBalancePercentage(0);
                          }}
                        >
                          📉 Sell
                        </button>
                      </div>
                    </div>

                    <div className="order-control-group type-group">
                      <label className="order-field-label">Order Types</label>
                      <div className="order-type-segmented">
                        <button
                          type="button"
                          className={`order-type-btn ${orderForm.type === 'LIMIT' ? 'active' : ''}`}
                          onClick={() => setOrderForm((prev) => ({ ...prev, type: 'LIMIT' }))}
                        >
                          Limit
                        </button>
                        <button
                          type="button"
                          className={`order-type-btn ${orderForm.type === 'MARKET' ? 'active' : ''}`}
                          onClick={() => setOrderForm((prev) => ({ ...prev, type: 'MARKET' }))}
                        >
                          Market
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Row 2: Quantity and Quote Value Inputs */}
                  <div className="order-inputs-row">
                    <div className="order-input-group">
                      <label className="order-field-label" htmlFor="quantity">
                        Quantity ({selectedSymbol})
                      </label>
                      <div className="order-input-wrapper">
                        <input
                          id="quantity"
                          type="text"
                          inputMode="decimal"
                          value={orderForm.quantity}
                          onChange={(e) => handleBaseQuantityChange(e.target.value)}
                          placeholder="0.0000"
                          className="order-styled-input"
                          required
                          autoComplete="off"
                        />
                        <button
                          type="button"
                          className="input-max-btn"
                          onClick={() => handleSliderChange(100)}
                          title="Use 100% Available Balance"
                        >
                          MAX
                        </button>
                      </div>
                    </div>

                    <div className="order-input-group">
                      <label className="order-field-label" htmlFor="quoteQuantity">
                        Order Value ($ USD)
                      </label>
                      <div className="order-input-wrapper">
                        <input
                          id="quoteQuantity"
                          type="text"
                          inputMode="decimal"
                          value={orderForm.quoteQuantity}
                          onChange={(e) => handleQuoteQuantityChange(e.target.value)}
                          placeholder="$0.00"
                          className="order-styled-input"
                          autoComplete="off"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Limit Price Input (when LIMIT order type) */}
                  {orderForm.type === 'LIMIT' && (
                    <div className="order-inputs-row">
                      <div className="order-input-group" style={{ width: '100%' }}>
                        <label className="order-field-label" htmlFor="price">
                          Limit Price ($ USD)
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
                            required
                          />
                        </div>
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
                      >
                        <option value="DAY">Day Order (DAY)</option>
                        <option value="GTC">Good &apos;Til Canceled (GTC)</option>
                      </select>
                    </div>
                    <div className="order-input-group">
                      <label className="order-field-label">Trading Session</label>
                      <select
                        value={orderForm.tradingSession}
                        onChange={(e) => setOrderForm((prev) => ({ ...prev, tradingSession: e.target.value }))}
                        className="order-styled-input"
                        style={{ cursor: 'pointer' }}
                      >
                        <option value="CORE">Regular Hours (CORE: 9:30 AM - 4:00 PM ET)</option>
                        <option value="ALL">Extended Hours (ALL: Pre &amp; Post Market)</option>
                      </select>
                    </div>
                  </div>

                  {/* Row 3: Use Balance Slider Section */}
                  <div className="order-slider-section">
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
                        >
                          {pct}%
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Row 4: Order Summary Card */}
                  <div className="order-summary-card">
                    <div className="order-summary-row">
                      <span>Order Total:</span>
                      <strong>${number(orderTotal)} USD</strong>
                    </div>
                    <div className="order-summary-row">
                      <span>Estimated Cash Impact:</span>
                      <span style={{ color: orderForm.side === 'BUY' ? '#ef4444' : '#10b981', fontWeight: 600 }}>
                        {orderForm.side === 'BUY' ? `-$${number(orderTotal)}` : `+$${number(orderTotal)}`}
                      </span>
                    </div>
                  </div>

                  {/* Row 5: Action Button */}
                  <div className="order-submit-row">
                    <button
                      type="submit"
                      className={`order-submit-btn ${orderForm.side === 'BUY' ? 'buy-action' : 'sell-action'}`}
                      disabled={orderSubmitting}
                    >
                      {orderSubmitting ? 'Placing Order…' : `Place ${orderForm.side === 'BUY' ? 'Buy' : 'Sell'} Order`}
                    </button>
                  </div>
                </form>

                {/* Pre-Trade Confirmation Modal */}
                {showConfirmModal && (
                  <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }}>
                    <div style={{ background: 'var(--card-bg, #1e293b)', borderRadius: '14px', padding: '28px', maxWidth: '480px', width: '100%', border: '1px solid rgba(255,255,255,0.15)', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.5)' }}>
                      <h3 style={{ margin: '0 0 16px', fontSize: '1.4rem' }}>Confirm Webull Order</h3>
                      <p style={{ color: '#94a3b8', fontSize: '0.9rem', marginBottom: '20px' }}>
                        Please review the details below. This will transmit an active order to Webull OpenAPI.
                      </p>
                      <div style={{ background: 'rgba(0,0,0,0.25)', padding: '16px', borderRadius: '8px', marginBottom: '20px', display: 'grid', gap: '10px', fontSize: '0.95rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Account:</span>
                          <strong>{activeAccount?.account_label || activeAccount?.account_name || 'Webull Account'} ({activeAccount?.account_number || activeAccount?.account_id_masked || selectedAccountId})</strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Action:</span>
                          <strong style={{ color: orderForm.side === 'BUY' ? '#10b981' : '#ef4444' }}>{orderForm.side}</strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Symbol &amp; Asset:</span>
                          <strong>{selectedSymbol} ({selectedInstrumentType})</strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Order Type:</span>
                          <strong>{orderForm.type} {orderForm.type === 'LIMIT' ? `@ $${number(orderForm.price)}` : ''}</strong>
                        </div>
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
                          <span>{orderForm.timeInForce} · {orderForm.tradingSession === 'CORE' ? 'Regular Hours' : 'Extended Hours'}</span>
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
                          onClick={handleConfirmSubmit}
                        >
                          {orderSubmitting ? 'Submitting…' : 'Confirm Order'}
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* Holdings Table Below */}
                <WebullHoldings holdings={holdings} />
              </div>
            )}

            {/* OPEN ORDERS TAB */}
            {activeTab === 'open_orders' && (
              <section className="order-history-container">
                <h2>Webull Open Orders</h2>
                <WebullOrderTable
                  orders={displayOpenOrders}
                  emptyText="No Webull open orders found."
                  onCancelOrder={handleCancelOpenOrder}
                  cancellingId={cancellingOrderId}
                />
              </section>
            )}

            {/* ORDER HISTORY TAB */}
            {activeTab === 'history' && (
              <section className="order-history-container">
                <h2>Webull Order History</h2>
                <WebullOrderTable orders={paginatedHistory} emptyText="No Webull order history is available yet." />
                <Pagination page={historyPage} setPage={setHistoryPage} pageSize={historyPageSize} setPageSize={setHistoryPageSize} total={sortedHistory.length} />
              </section>
            )}

            {/* TRADE CHART TAB */}
            {activeTab === 'trade_chart' && (
              <section className="order-history-container">
                <WebullTradeTimelineChart holdings={holdings} orders={history} isLightMode={isLightMode} />
              </section>
            )}

            {/* AI ANALYSIS TAB */}
            {activeTab === 'ai_analysis' && (
              <section className="order-history-container">
                <h2>Webull AI Analysis</h2>
                <p style={{ color: 'var(--text-secondary, #94a3b8)', marginTop: 0 }}>
                  Stored research signals use distinct crypto and equity/ETF prompt paths, are graded at their saved forecast horizon, and never submit a Webull order. Options remain unavailable until contract-level mapping is added.
                </p>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'end', margin: '18px 0' }}>
                  <label style={{ display: 'grid', gap: 6, minWidth: 240 }}>
                    <span>Imported holding</span>
                    <select value={selectedSignalHolding} onChange={(event) => setSelectedSignalHolding(event.target.value)}>
                      {analyzableHoldings.map((holding) => (
                        <option key={`${holding.id}-${holding.instrument_type}`} value={`${holding.symbol}|${holding.instrument_type}`}>
                          {holding.symbol} · {holding.instrument_type}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button type="button" className="btn btn-primary" disabled={!selectedSignalHolding || signalBusy} onClick={createSignal}>
                    {signalBusy ? 'Creating…' : 'Create Stored Signal'}
                  </button>
                </div>
                {signalMessage && <div className="modern-real-warning" style={{ marginBottom: 16 }}>{signalMessage}</div>}
                <div className="trading-asset-card" style={{ marginBottom: 18 }}>
                  <strong>Optional scheduled signals</strong>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'end', marginTop: 12 }}>
                    <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <input
                        type="checkbox"
                        checked={!!signalSettings.webull_ai_scheduling_enabled}
                        onChange={(event) => setSignalSettings((current) => ({ ...current, webull_ai_scheduling_enabled: event.target.checked }))}
                      />{' '}
                      Enable scheduled read-only signals
                    </label>
                    {[
                      ['webull_crypto_sentiment_frequency_hours', 'Crypto cadence (hours)'],
                      ['webull_crypto_sentiment_horizon_hours', 'Crypto forecast (hours)'],
                      ['webull_equity_sentiment_frequency_hours', 'Equity / ETF cadence (hours)'],
                      ['webull_equity_sentiment_horizon_hours', 'Equity / ETF forecast (hours)'],
                    ].map(([key, label]) => (
                      <label key={key} style={{ display: 'grid', gap: 6 }}>
                        <span>{label}</span>
                        <input
                          type="number"
                          min="1"
                          max="720"
                          value={signalSettings[key]}
                          onChange={(event) => setSignalSettings((current) => ({ ...current, [key]: event.target.value }))}
                          style={{ width: 150 }}
                        />
                      </label>
                    ))}
                    <button type="button" className="btn btn-secondary" disabled={signalBusy} onClick={saveSignalSettings}>
                      Save schedule
                    </button>
                  </div>
                </div>
                <WebullSignalTable signals={signals} />
              </section>
            )}
          </>
        )}
      </div>
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
              <th>Created</th><th>Symbol</th><th>Asset Class</th><th>Signal</th><th>Forecast</th><th>Outcome</th><th>Origin</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((signal) => (
              <tr key={signal.id}>
                <td>{formatDate(signal.created_at)}</td>
                <td>{signal.symbol}</td>
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

function WebullHoldings({ holdings, compact = false }) {
  if (!holdings.length) return <div className="empty-state"><p>No imported Webull holdings. Import a Webull portfolio snapshot in Settings first.</p></div>;
  return (
    <div className="table-container trading-table" style={{ marginTop: compact ? 12 : 20 }}>
      <div className="order-table-scroll">
        <table>
          <thead>
            <tr>
              <th>Symbol</th><th>Type</th><th>Quantity</th><th>Last Price</th><th>Value</th><th>Unrealized P&amp;L</th><th>Source</th>
            </tr>
          </thead>
          <tbody>
            {holdings.map((holding) => {
              const isOption = String(holding.instrument_type || '').toUpperCase() === 'OPTION';
              const optionLabel = [holding.underlying_symbol, holding.option_expiration, holding.option_strike != null ? `$${holding.option_strike}` : '', holding.option_type].filter(Boolean).join(' · ');
              return (
                <tr key={holding.id}>
                  <td style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <CryptoIcon symbol={holding.symbol} size={22} />
                    <span>
                      {holding.symbol}
                      {isOption && optionLabel && <small style={{ display: 'block', color: 'var(--text-secondary, #94a3b8)' }}>{optionLabel}</small>}
                    </span>
                  </td>
                  <td>
                    {holding.instrument_type || 'Security'}
                    {isOption && !holding.instrument_id && <small style={{ display: 'block', color: '#fbbf24' }}>Contract resolution needed</small>}
                  </td>
                  <td>{number(holding.amount, 6)}</td>
                  <td>{holding.current_price ? `$${number(holding.current_price, 4)}` : '—'}</td>
                  <td>{holding.current_value != null ? `$${number(holding.current_value)}` : '—'}</td>
                  <td style={{ color: Number(holding.webull_unrealized_pnl) >= 0 ? '#4ade80' : '#f87171' }}>
                    {holding.webull_unrealized_pnl == null ? '—' : `$${number(holding.webull_unrealized_pnl)}`}
                  </td>
                  <td><span className="badge" style={{ background: 'rgba(96, 165, 250, .16)', color: '#60a5fa' }}>Webull</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
