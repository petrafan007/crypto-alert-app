import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import CryptoIcon from '../components/CryptoIcon';
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

  // Order Placement Form State
  const [orderSide, setOrderSide] = useState('BUY');
  const [orderInstrument, setOrderInstrument] = useState('EQUITY');
  const [orderSymbol, setOrderSymbol] = useState('');
  const [orderType, setOrderType] = useState('LIMIT');
  const [orderPrice, setOrderPrice] = useState('');
  const [orderQuantity, setOrderQuantity] = useState('');
  const [timeInForce, setTimeInForce] = useState('DAY');
  const [tradingSession, setTradingSession] = useState('CORE');
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
      setHoldings((portfolioResponse.data?.portfolio || []).filter((item) => item?.is_external || item?.source === 'webull'));
      setHistory((historyResponse.data?.orders || [])
        .filter((order) => String(order?.source || '').toLowerCase() === 'webull')
        .map(normalizeOrder));
      setOpenOrders((openResponse.data?.orders || []).map(normalizeOrder));
      setSignals(signalsResponse.data?.signals || []);
      setSignalSettings((current) => ({ ...current, ...(signalSettingsResponse.data?.settings || {}) }));

      const discoveredAccounts = previewResponse.data?.accounts || [];
      setAccounts(discoveredAccounts);
      if (discoveredAccounts.length && !selectedAccountId) {
        setSelectedAccountId(discoveredAccounts[0].account_id);
      }

      if (openResponse.data?.success === false) setError(openResponse.data?.message || 'Unable to load Webull open orders.');
    } catch (requestError) {
      setError(requestError.response?.data?.message || 'Unable to load the Webull workspace.');
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const activeAccount = useMemo(() => accounts.find((a) => a.account_id === selectedAccountId) || accounts[0], [accounts, selectedAccountId]);
  const cashBalance = useMemo(() => {
    if (!activeAccount?.balance) return 0;
    const b = activeAccount.balance;
    return Number(b.total_cash_balance ?? b.cash_balance ?? b.settled_cash ?? b.cashBalance ?? 0);
  }, [activeAccount]);
  const netLiquidation = useMemo(() => {
    if (!activeAccount?.balance) return 0;
    const b = activeAccount.balance;
    return Number(b.net_liquidation_value ?? b.netLiquidationValue ?? b.total_market_value ?? 0);
  }, [activeAccount]);

  const cryptoHoldings = useMemo(() => holdings.filter((item) => /crypto|coin|token/i.test(item.instrument_type || '')), [holdings]);
  const securityHoldings = useMemo(() => holdings.filter((item) => !cryptoHoldings.includes(item)), [holdings, cryptoHoldings]);
  const displayOpenOrders = useMemo(() => openOrders.filter((order) => OPEN_STATUSES.has(String(order.status).toUpperCase()) || !order.status), [openOrders]);
  const sortedHistory = useMemo(() => [...history].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''))), [history]);
  const historyPages = Math.max(1, Math.ceil(sortedHistory.length / historyPageSize));
  const paginatedHistory = useMemo(() => sortedHistory.slice((historyPage - 1) * historyPageSize, historyPage * historyPageSize), [sortedHistory, historyPage, historyPageSize]);
  useEffect(() => { if (historyPage > historyPages) setHistoryPage(historyPages); }, [historyPage, historyPages]);
  const analyzableHoldings = useMemo(() => holdings.filter((holding) => ['CRYPTO', 'STOCK', 'EQUITY', 'ETF'].includes(String(holding.instrument_type || '').toUpperCase())), [holdings]);
  useEffect(() => {
    if (!selectedSignalHolding && analyzableHoldings.length) setSelectedSignalHolding(`${analyzableHoldings[0].symbol}|${analyzableHoldings[0].instrument_type}`);
  }, [analyzableHoldings, selectedSignalHolding]);

  // Handle Quick Pick from Holdings
  const handleSelectHolding = (holding) => {
    setOrderSymbol(holding.symbol);
    const isCrypto = /crypto|coin|token/i.test(holding.instrument_type || '');
    setOrderInstrument(isCrypto ? 'CRYPTO' : 'EQUITY');
    if (holding.current_price) {
      setOrderPrice(Number(holding.current_price).toFixed(2));
    }
  };

  // Percentage allocation shortcut
  const handlePercentClick = (pct) => {
    const price = Number(orderPrice) || 1;
    if (orderSide === 'BUY') {
      if (cashBalance > 0 && price > 0) {
        const targetDollars = cashBalance * (pct / 100);
        const qty = orderInstrument === 'CRYPTO' ? (targetDollars / price).toFixed(6) : Math.floor(targetDollars / price);
        setOrderQuantity(String(qty > 0 ? qty : ''));
      }
    } else {
      const match = holdings.find((h) => h.symbol === orderSymbol);
      if (match && Number(match.amount) > 0) {
        const qty = (Number(match.amount) * (pct / 100));
        setOrderQuantity(orderInstrument === 'CRYPTO' ? qty.toFixed(6) : String(Math.floor(qty)));
      }
    }
  };

  // Estimated Total
  const estimatedTotal = useMemo(() => {
    const qty = Number(orderQuantity) || 0;
    const px = Number(orderPrice) || 0;
    return qty * px;
  }, [orderQuantity, orderPrice]);

  // Pre-trade validation & review
  const handleReviewOrder = (e) => {
    e.preventDefault();
    setOrderFeedback({ type: '', message: '' });
    if (!selectedAccountId) {
      setOrderFeedback({ type: 'error', message: 'Please select a Webull account.' });
      return;
    }
    if (!orderSymbol.trim()) {
      setOrderFeedback({ type: 'error', message: 'Please enter an instrument symbol.' });
      return;
    }
    const qty = Number(orderQuantity);
    if (!qty || qty <= 0) {
      setOrderFeedback({ type: 'error', message: 'Please enter a valid positive quantity.' });
      return;
    }
    if (orderType === 'LIMIT') {
      const px = Number(orderPrice);
      if (!px || px <= 0) {
        setOrderFeedback({ type: 'error', message: 'Limit orders require a limit price greater than $0.' });
        return;
      }
    }
    setShowConfirmModal(true);
  };

  // Submit Order to Backend
  const handleConfirmSubmit = async () => {
    setOrderSubmitting(true);
    try {
      const payload = {
        account_id: selectedAccountId,
        symbol: orderSymbol.trim().toUpperCase(),
        instrument_type: orderInstrument,
        side: orderSide,
        order_type: orderType,
        quantity: Number(orderQuantity),
        limit_price: orderType === 'LIMIT' ? Number(orderPrice) : undefined,
        time_in_force: timeInForce,
        support_trading_session: tradingSession,
      };

      const response = await axios.post('/api/webull/orders/place', payload, { withCredentials: true });
      if (response.data?.success) {
        setOrderFeedback({ type: 'success', message: response.data.message || 'Webull order placed successfully!' });
        setShowConfirmModal(false);
        setOrderQuantity('');
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

  // Cancel Open Order
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
        <div className={orderFeedback.type === 'error' ? 'modern-real-warning' : 'modern-real-success'} style={{ marginBottom: '16px', padding: '12px 16px', borderRadius: '8px', background: orderFeedback.type === 'error' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.15)', color: orderFeedback.type === 'error' ? '#ef4444' : '#10b981', border: `1px solid ${orderFeedback.type === 'error' ? 'rgba(239, 68, 68, 0.3)' : 'rgba(16, 185, 129, 0.3)'}` }}>
          {orderFeedback.type === 'error' ? '⚠️' : '✅'} {orderFeedback.message}
        </div>
      )}

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
            {activeTab === 'order' && (
              <div className="order-form-container">
                <div className="trading-asset-card" style={{ padding: '24px', borderRadius: '12px', background: 'var(--card-bg, #1e293b)', border: '1px solid rgba(255,255,255,0.08)', marginBottom: '24px' }}>
                  {/* Account Selector & Buying Power Card */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '16px', marginBottom: '20px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <span style={{ fontWeight: 600, color: 'var(--text-secondary, #94a3b8)' }}>Webull Account:</span>
                      <select
                        value={selectedAccountId}
                        onChange={(e) => setSelectedAccountId(e.target.value)}
                        style={{ padding: '8px 14px', borderRadius: '8px', background: 'var(--input-bg, #0f172a)', color: '#fff', border: '1px solid rgba(255,255,255,0.15)', fontSize: '14px', cursor: 'pointer' }}
                      >
                        {accounts.length ? (
                          accounts.map((acc) => (
                            <option key={acc.account_id} value={acc.account_id}>
                              {acc.account_name || 'Account'} ({acc.account_type || 'Individual'}) - {acc.account_id}
                            </option>
                          ))
                        ) : (
                          <option value="">No Accounts Discovered</option>
                        )}
                      </select>
                    </div>
                    <div style={{ display: 'flex', gap: '20px', alignItems: 'center' }}>
                      <div>
                        <small style={{ color: '#94a3b8', display: 'block' }}>Cash Balance</small>
                        <strong style={{ fontSize: '1.1rem', color: '#38bdf8' }}>${number(cashBalance)}</strong>
                      </div>
                      <div>
                        <small style={{ color: '#94a3b8', display: 'block' }}>Net Liquidation</small>
                        <strong style={{ fontSize: '1.1rem', color: '#a78bfa' }}>${number(netLiquidation)}</strong>
                      </div>
                    </div>
                  </div>

                  {/* Quick Pick Holdings */}
                  {holdings.length > 0 && (
                    <div style={{ marginBottom: '20px' }}>
                      <small style={{ color: '#94a3b8', display: 'block', marginBottom: '8px' }}>Quick Pick from Imported Portfolio:</small>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                        {holdings.slice(0, 10).map((h) => (
                          <button
                            key={h.id}
                            type="button"
                            onClick={() => handleSelectHolding(h)}
                            style={{
                              padding: '6px 12px',
                              borderRadius: '20px',
                              border: orderSymbol === h.symbol ? '1px solid #38bdf8' : '1px solid rgba(255,255,255,0.1)',
                              background: orderSymbol === h.symbol ? 'rgba(56, 189, 248, 0.2)' : 'rgba(255,255,255,0.04)',
                              color: orderSymbol === h.symbol ? '#38bdf8' : '#e2e8f0',
                              fontSize: '12px',
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '6px',
                            }}
                          >
                            <strong>{h.symbol}</strong>
                            {h.current_price && <span>${number(h.current_price)}</span>}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Order Placement Form */}
                  <form onSubmit={handleReviewOrder}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '18px', marginBottom: '20px' }}>
                      {/* Order Side */}
                      <div>
                        <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', color: '#94a3b8' }}>Order Side</label>
                        <div style={{ display: 'flex', borderRadius: '8px', overflow: 'hidden', border: '1px solid rgba(255,255,255,0.15)' }}>
                          <button
                            type="button"
                            onClick={() => setOrderSide('BUY')}
                            style={{
                              flex: 1,
                              padding: '10px',
                              background: orderSide === 'BUY' ? '#10b981' : 'transparent',
                              color: '#fff',
                              border: 'none',
                              fontWeight: 'bold',
                              cursor: 'pointer',
                            }}
                          >
                            BUY
                          </button>
                          <button
                            type="button"
                            onClick={() => setOrderSide('SELL')}
                            style={{
                              flex: 1,
                              padding: '10px',
                              background: orderSide === 'SELL' ? '#ef4444' : 'transparent',
                              color: '#fff',
                              border: 'none',
                              fontWeight: 'bold',
                              cursor: 'pointer',
                            }}
                          >
                            SELL
                          </button>
                        </div>
                      </div>

                      {/* Asset Class */}
                      <div>
                        <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', color: '#94a3b8' }}>Asset Class</label>
                        <select
                          value={orderInstrument}
                          onChange={(e) => setOrderInstrument(e.target.value)}
                          style={{ width: '100%', padding: '10px', borderRadius: '8px', background: 'var(--input-bg, #0f172a)', color: '#fff', border: '1px solid rgba(255,255,255,0.15)', fontSize: '14px' }}
                        >
                          <option value="EQUITY">Stocks & ETFs</option>
                          <option value="CRYPTO">Cryptocurrency</option>
                        </select>
                      </div>

                      {/* Symbol Input */}
                      <div>
                        <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', color: '#94a3b8' }}>Symbol</label>
                        <input
                          type="text"
                          placeholder="e.g. AAPL, NVDA, BTC"
                          value={orderSymbol}
                          onChange={(e) => setOrderSymbol(e.target.value.toUpperCase())}
                          style={{ width: '100%', padding: '10px', borderRadius: '8px', background: 'var(--input-bg, #0f172a)', color: '#fff', border: '1px solid rgba(255,255,255,0.15)', fontSize: '14px', textTransform: 'uppercase' }}
                          required
                        />
                      </div>

                      {/* Order Type */}
                      <div>
                        <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', color: '#94a3b8' }}>Order Type</label>
                        <select
                          value={orderType}
                          onChange={(e) => setOrderType(e.target.value)}
                          style={{ width: '100%', padding: '10px', borderRadius: '8px', background: 'var(--input-bg, #0f172a)', color: '#fff', border: '1px solid rgba(255,255,255,0.15)', fontSize: '14px' }}
                        >
                          <option value="LIMIT">Limit Order</option>
                          <option value="MARKET">Market Order</option>
                        </select>
                      </div>

                      {/* Limit Price */}
                      {orderType === 'LIMIT' && (
                        <div>
                          <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', color: '#94a3b8' }}>Limit Price ($)</label>
                          <input
                            type="number"
                            step="any"
                            placeholder="0.00"
                            value={orderPrice}
                            onChange={(e) => setOrderPrice(e.target.value)}
                            style={{ width: '100%', padding: '10px', borderRadius: '8px', background: 'var(--input-bg, #0f172a)', color: '#fff', border: '1px solid rgba(255,255,255,0.15)', fontSize: '14px' }}
                            required
                          />
                        </div>
                      )}

                      {/* Quantity */}
                      <div>
                        <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', color: '#94a3b8' }}>Quantity ({orderInstrument === 'CRYPTO' ? 'Coins' : 'Shares'})</label>
                        <input
                          type="number"
                          step="any"
                          placeholder="0"
                          value={orderQuantity}
                          onChange={(e) => setOrderQuantity(e.target.value)}
                          style={{ width: '100%', padding: '10px', borderRadius: '8px', background: 'var(--input-bg, #0f172a)', color: '#fff', border: '1px solid rgba(255,255,255,0.15)', fontSize: '14px' }}
                          required
                        />
                      </div>

                      {/* Time in Force */}
                      <div>
                        <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', color: '#94a3b8' }}>Time in Force</label>
                        <select
                          value={timeInForce}
                          onChange={(e) => setTimeInForce(e.target.value)}
                          style={{ width: '100%', padding: '10px', borderRadius: '8px', background: 'var(--input-bg, #0f172a)', color: '#fff', border: '1px solid rgba(255,255,255,0.15)', fontSize: '14px' }}
                        >
                          <option value="DAY">Day Order (DAY)</option>
                          <option value="GTC">Good 'Til Canceled (GTC)</option>
                        </select>
                      </div>

                      {/* Trading Session */}
                      <div>
                        <label style={{ display: 'block', marginBottom: '6px', fontSize: '13px', color: '#94a3b8' }}>Session</label>
                        <select
                          value={tradingSession}
                          onChange={(e) => setTradingSession(e.target.value)}
                          style={{ width: '100%', padding: '10px', borderRadius: '8px', background: 'var(--input-bg, #0f172a)', color: '#fff', border: '1px solid rgba(255,255,255,0.15)', fontSize: '14px' }}
                        >
                          <option value="CORE">Regular Hours (CORE)</option>
                          <option value="ALL">Extended Hours (Pre/Post Market)</option>
                        </select>
                      </div>
                    </div>

                    {/* Percentage Allocation Buttons & Total */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px', marginBottom: '24px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <small style={{ color: '#94a3b8' }}>Amount:</small>
                        {[25, 50, 75, 100].map((pct) => (
                          <button
                            key={pct}
                            type="button"
                            onClick={() => handlePercentClick(pct)}
                            style={{
                              padding: '5px 12px',
                              borderRadius: '6px',
                              background: 'rgba(255,255,255,0.06)',
                              border: '1px solid rgba(255,255,255,0.12)',
                              color: '#fff',
                              fontSize: '12px',
                              cursor: 'pointer',
                            }}
                          >
                            {pct}%
                          </button>
                        ))}
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <small style={{ color: '#94a3b8', display: 'block' }}>Estimated Value:</small>
                        <strong style={{ fontSize: '1.25rem', color: '#f8fafc' }}>
                          {estimatedTotal > 0 ? `$${number(estimatedTotal)}` : orderType === 'MARKET' ? 'Market Price' : '$0.00'}
                        </strong>
                      </div>
                    </div>

                    {/* Review Button */}
                    <button
                      type="submit"
                      className="btn"
                      style={{
                        width: '100%',
                        padding: '14px',
                        fontSize: '1rem',
                        fontWeight: 'bold',
                        borderRadius: '8px',
                        background: orderSide === 'BUY' ? 'linear-gradient(135deg, #10b981 0%, #059669 100%)' : 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)',
                        color: '#fff',
                        border: 'none',
                        cursor: 'pointer',
                        boxShadow: '0 4px 12px rgba(0,0,0,0.25)',
                      }}
                    >
                      Review {orderSide} {orderSymbol || 'Order'}
                    </button>
                  </form>
                </div>

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
                          <strong>{activeAccount?.account_name || 'Individual'} ({selectedAccountId})</strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Action:</span>
                          <strong style={{ color: orderSide === 'BUY' ? '#10b981' : '#ef4444' }}>{orderSide}</strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Symbol &amp; Asset:</span>
                          <strong>{orderSymbol} ({orderInstrument})</strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Order Type:</span>
                          <strong>{orderType} {orderType === 'LIMIT' ? `@ $${number(orderPrice)}` : ''}</strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Quantity:</span>
                          <strong>{number(orderQuantity, orderInstrument === 'CRYPTO' ? 6 : 2)}</strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Estimated Total:</span>
                          <strong style={{ color: '#38bdf8' }}>
                            {estimatedTotal > 0 ? `$${number(estimatedTotal)}` : 'Market'}
                          </strong>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span style={{ color: '#94a3b8' }}>Time in Force / Session:</span>
                          <span>{timeInForce} · {tradingSession === 'CORE' ? 'Regular Hours' : 'Extended Hours'}</span>
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
                            background: orderSide === 'BUY' ? '#10b981' : '#ef4444',
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

                <WebullHoldings holdings={holdings} />
              </div>
            )}

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

            {activeTab === 'history' && (
              <section className="order-history-container">
                <h2>Webull Order History</h2>
                <WebullOrderTable orders={paginatedHistory} emptyText="No Webull order history is available yet." />
                <Pagination page={historyPage} setPage={setHistoryPage} pageSize={historyPageSize} setPageSize={setHistoryPageSize} total={sortedHistory.length} />
              </section>
            )}

            {activeTab === 'trade_chart' && (
              <section className="order-history-container">
                <WebullTradeTimelineChart holdings={holdings} orders={history} isLightMode={isLightMode} />
              </section>
            )}

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
