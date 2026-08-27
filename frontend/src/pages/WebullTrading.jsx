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
  return <div className="order-history-pagination"><div className="order-history-pagination-info">Showing {total ? (page - 1) * pageSize + 1 : 0}–{Math.min(page * pageSize, total)} of {total} orders</div><div className="order-history-pagination-controls"><label className="order-page-size-label">Rows <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }}>{PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}</select></label><button type="button" className="pagination-btn" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={page === 1}>‹ Prev</button><span className="order-page-indicator">Page {page} of {pages}</span><button type="button" className="pagination-btn" onClick={() => setPage((current) => Math.min(pages, current + 1))} disabled={page === pages}>Next ›</button></div></div>;
}

function WebullOrderTable({ orders, emptyText }) {
  if (!orders.length) return <div className="empty-state"><p>{emptyText}</p></div>;
  return (
    <div className="table-container trading-table">
      <div className="order-table-scroll">
        <table>
          <thead><tr><th>Date / Time</th><th>Symbol</th><th>Side</th><th>Type</th><th>Quantity</th><th>Price</th><th>Filled</th><th>Status</th><th>Source</th></tr></thead>
          <tbody>{orders.map((order) => (
            <tr key={order.id}>
              <td>{formatDate(order.created_at)}</td><td>{order.symbol}</td><td>{order.side}</td><td>{order.order_type}</td>
              <td>{number(order.quantity, 6)}</td><td>{order.price ? `$${number(order.price, 4)}` : 'Market'}</td>
              <td>{number(order.filled_quantity, 6)}</td><td>{order.status}</td>
              <td><span className="badge" style={{ background: 'rgba(96, 165, 250, .16)', color: '#60a5fa' }}>Webull · Read-only</span></td>
            </tr>
          ))}</tbody>
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [historyPage, setHistoryPage] = useState(1);
  const [historyPageSize, setHistoryPageSize] = useState(50);

  const load = async () => {
    setLoading(true); setError('');
    try {
      const [portfolioResponse, historyResponse, openResponse] = await Promise.all([
        axios.get('/api/coin-data-live', { withCredentials: true }),
        axios.get('/api/trading/real-orders?limit=all', { withCredentials: true }),
        axios.get('/api/webull/open-orders', { withCredentials: true }),
      ]);
      setHoldings((portfolioResponse.data?.portfolio || []).filter((item) => item?.is_external || item?.source === 'webull'));
      setHistory((historyResponse.data?.orders || [])
        .filter((order) => String(order?.source || '').toLowerCase() === 'webull')
        .map(normalizeOrder));
      setOpenOrders((openResponse.data?.orders || []).map(normalizeOrder));
      if (openResponse.data?.success === false) setError(openResponse.data?.message || 'Unable to load Webull open orders.');
    } catch (requestError) {
      setError(requestError.response?.data?.message || 'Unable to load the Webull workspace.');
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);
  const cryptoHoldings = useMemo(() => holdings.filter((item) => /crypto|coin|token/i.test(item.instrument_type || '')), [holdings]);
  const securityHoldings = useMemo(() => holdings.filter((item) => !cryptoHoldings.includes(item)), [holdings, cryptoHoldings]);
  const displayOpenOrders = useMemo(() => openOrders.filter((order) => OPEN_STATUSES.has(String(order.status).toUpperCase()) || !order.status), [openOrders]);
  const sortedHistory = useMemo(() => [...history].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''))), [history]);
  const historyPages = Math.max(1, Math.ceil(sortedHistory.length / historyPageSize));
  const paginatedHistory = useMemo(() => sortedHistory.slice((historyPage - 1) * historyPageSize, historyPage * historyPageSize), [sortedHistory, historyPage, historyPageSize]);
  useEffect(() => { if (historyPage > historyPages) setHistoryPage(historyPages); }, [historyPage, historyPages]);

  return (
    <div className="trading-page" style={{ padding: '20px', maxWidth: '1500px', margin: '0 auto' }}>
      <div className="trading-header" style={{ marginBottom: '18px' }}>
        <div><h1 style={{ fontSize: '2rem', margin: 0 }}>📈 Webull Trading</h1><p style={{ margin: '6px 0 0', color: '#94a3b8' }}>All Webull information is read-only. Order placement, changes, and cancellations stay in Webull.</p></div>
        <button type="button" className="btn btn-secondary" onClick={load}>🔄 Refresh Webull</button>
      </div>
      {error && <div className="modern-real-warning" style={{ marginBottom: '16px' }}>⚠️ {error}</div>}
      <div className="trading-tabs">
        <button className={`tab-button ${activeTab === 'order' ? 'active' : ''}`} onClick={() => setActiveTab('order')}>📝 <span className="tab-text">Place Order</span></button>
        <button className={`tab-button ${activeTab === 'open_orders' ? 'active' : ''}`} onClick={() => setActiveTab('open_orders')}>⏳ <span className="tab-text">Open Orders</span>{displayOpenOrders.length > 0 && <span className="tab-badge">{displayOpenOrders.length}</span>}</button>
        <button className={`tab-button ${activeTab === 'history' ? 'active' : ''}`} onClick={() => setActiveTab('history')}>📜 <span className="tab-text">Order History</span></button>
        <button className={`tab-button ${activeTab === 'trade_chart' ? 'active' : ''}`} onClick={() => setActiveTab('trade_chart')}>📈 <span className="tab-text">Trade Chart</span></button>
        <button className={`tab-button ${activeTab === 'ai_analysis' ? 'active' : ''}`} onClick={() => setActiveTab('ai_analysis')}>🤖 <span className="tab-text">AI Analysis</span></button>
      </div>
      <div className="trading-content">
        {loading ? <div className="empty-state"><p>Loading Webull data…</p></div> : <>
          {activeTab === 'order' && <div className="order-form-container"><div className="empty-state"><h2>Webull order placement is read-only</h2><p>Use Webull to place, amend, or cancel orders. Your imported Webull positions remain visible here and on the Dashboard.</p></div><WebullHoldings holdings={holdings} /></div>}
          {activeTab === 'open_orders' && <section className="order-history-container"><h2>Webull Open Orders</h2><WebullOrderTable orders={displayOpenOrders} emptyText="No Webull open orders found." /></section>}
          {activeTab === 'history' && <section className="order-history-container"><h2>Webull Order History</h2><WebullOrderTable orders={paginatedHistory} emptyText="No Webull order history is available yet." /><Pagination page={historyPage} setPage={setHistoryPage} pageSize={historyPageSize} setPageSize={setHistoryPageSize} total={sortedHistory.length} /></section>}
          {activeTab === 'trade_chart' && <section className="order-history-container"><WebullTradeTimelineChart holdings={holdings} orders={history} isLightMode={isLightMode} /></section>}
          {activeTab === 'ai_analysis' && <section className="order-history-container"><h2>Webull AI Analysis</h2><div className="empty-state"><p>Webull crypto will use the existing crypto analysis framework after its market-data mapping is enabled. Equities, ETFs, and options intentionally remain unanalysed until their dedicated prompts and data inputs are available.</p></div><div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '12px' }}><div className="trading-asset-card"><strong>Crypto</strong><span>{cryptoHoldings.length} imported holding(s) · shared crypto prompt family pending market mapping</span></div><div className="trading-asset-card"><strong>Stocks / ETFs / options</strong><span>{securityHoldings.length} imported holding(s) · dedicated analysis family not yet enabled</span></div></div></section>}
        </>}
      </div>
    </div>
  );
}

function WebullHoldings({ holdings, compact = false }) {
  if (!holdings.length) return <div className="empty-state"><p>No imported Webull holdings. Import a Webull portfolio snapshot in Settings first.</p></div>;
  return <div className="table-container trading-table" style={{ marginTop: compact ? 12 : 20 }}><div className="order-table-scroll"><table><thead><tr><th>Symbol</th><th>Type</th><th>Quantity</th><th>Last Price</th><th>Value</th><th>Unrealized P&amp;L</th><th>Source</th></tr></thead><tbody>{holdings.map((holding) => <tr key={holding.id}><td style={{ display: 'flex', alignItems: 'center', gap: 8 }}><CryptoIcon symbol={holding.symbol} size={22} />{holding.symbol}</td><td>{holding.instrument_type || 'Security'}</td><td>{number(holding.amount, 6)}</td><td>{holding.current_price ? `$${number(holding.current_price, 4)}` : '—'}</td><td>{holding.current_value != null ? `$${number(holding.current_value)}` : '—'}</td><td style={{ color: Number(holding.webull_unrealized_pnl) >= 0 ? '#4ade80' : '#f87171' }}>{holding.webull_unrealized_pnl == null ? '—' : `$${number(holding.webull_unrealized_pnl)}`}</td><td><span className="badge" style={{ background: 'rgba(96, 165, 250, .16)', color: '#60a5fa' }}>Webull</span></td></tr>)}</tbody></table></div></div>;
}
