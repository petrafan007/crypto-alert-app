import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import './Trading.css';

const PAGE_SIZES = [20, 50, 100, 200];
const OPEN_STATUSES = new Set(['OPEN', 'NEW', 'WORKING', 'PENDING', 'PARTIALLY_FILLED', 'PARTIALLY FILLED']);
const isWebull = (order) => String(order?.source || order?.origin || '').toLowerCase() === 'webull';
const amount = (value, digits = 6) => Number.isFinite(Number(value)) ? Number(value).toLocaleString(undefined, { maximumFractionDigits: digits }) : '—';
const timestamp = (value) => { const date = new Date(value); return value && !Number.isNaN(date.getTime()) ? date.toLocaleString() : '—'; };
const normalize = (order, source) => ({
  ...order,
  source,
  id: order.id || order.order_id || order.orderId || `${source}-${order.symbol || order.ticker || 'unknown'}-${order.created_at || order.create_time || order.filled_time_at || ''}`,
  symbol: String(order.symbol || order.ticker || '—').toUpperCase(),
  side: order.side || '—',
  order_type: order.order_type || order.type || '—',
  quantity: order.quantity ?? order.total_quantity ?? order.order_quantity,
  filled_quantity: order.filled_quantity ?? order.executed_quantity ?? order.filled_qty,
  price: order.price ?? order.limit_price ?? order.order_price,
  status: order.status || order.order_status || '—',
  created_at: order.created_at || order.create_time || order.placed_time || order.place_time || order.filled_time_at || order.time,
});

const displaySide = (side) => String(side || '—').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
const displayType = (type) => String(type || '—').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());

function SourceBadge({ order }) {
  const webull = isWebull(order);
  return <span className="badge" style={{ background: webull ? 'rgba(96, 165, 250, .16)' : 'rgba(251, 191, 36, .16)', color: webull ? '#2563eb' : '#a16207' }}>{webull ? 'Webull' : 'Binance.US'}</span>;
}

function OrderTable({ orders, open, onCancelOrder, cancellingId }) {
  if (!orders.length) return <div className="empty-state"><p>No {open ? 'open' : 'historical'} orders for the selected accounts.</p></div>;
  return (
    <div className="table-container trading-table">
      <div className="order-table-scroll">
        <table>
          <thead>
            <tr>
              <th>Date / Time</th><th>Account</th><th>Symbol</th><th>Side</th><th>Type</th><th>Quantity</th><th>Price</th><th>Filled</th><th>Status</th>
              {open && <th>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr key={`${order.source}-${order.id}`}>
                <td>{timestamp(order.created_at)}</td>
                <td><SourceBadge order={order} /></td>
                <td>{order.symbol}</td>
                <td>{displaySide(order.side)}</td>
                <td>{displayType(order.order_type)}</td>
                <td>{amount(order.quantity)}</td>
                <td>{Number(order.price) > 0 ? `$${amount(order.price, 4)}` : 'Market'}</td>
                <td>{amount(order.filled_quantity)}</td>
                <td>{order.status}</td>
                {open && (
                  <td>
                    <button
                      type="button"
                      className="btn btn-sm btn-danger"
                      style={{ padding: '3px 8px', fontSize: '11px', backgroundColor: '#ef4444', borderColor: '#ef4444', color: '#fff', borderRadius: '4px', cursor: 'pointer' }}
                      disabled={cancellingId === order.id}
                      onClick={() => onCancelOrder?.(order)}
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

function Pagination({ page, setPage, pageSize, setPageSize, total }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return <div className="order-history-pagination"><div className="order-history-pagination-info">Showing {total ? (page - 1) * pageSize + 1 : 0}–{Math.min(page * pageSize, total)} of {total} orders</div><div className="order-history-pagination-controls"><label className="order-page-size-label">Rows <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }}>{PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}</select></label><button type="button" className="pagination-btn" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={page === 1}>‹ Prev</button><span className="order-page-indicator">Page {page} of {pages}</span><button type="button" className="pagination-btn" onClick={() => setPage((current) => Math.min(pages, current + 1))} disabled={page === pages}>Next ›</button></div></div>;
}

export default function Orders() {
  const [activeTab, setActiveTab] = useState('open');
  const [history, setHistory] = useState([]);
  const [openOrders, setOpenOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');
  const [cancellingId, setCancellingId] = useState(null);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyPageSize, setHistoryPageSize] = useState(50);

  const load = async () => {
    setLoading(true); setNotice('');
    try {
      const [historyResponse, binanceOpenResponse, webullOpenResponse] = await Promise.all([
        axios.get('/api/trading/real-orders?limit=all', { withCredentials: true }),
        axios.get('/api/pending-orders', { withCredentials: true }),
        axios.get('/api/webull/open-orders', { withCredentials: true }),
      ]);
      const allHistory = (historyResponse.data?.orders || []).map((order) => normalize(order, isWebull(order) ? 'webull' : 'binance'));
      setHistory(allHistory);
      const binanceOpen = (binanceOpenResponse.data?.pending_orders || binanceOpenResponse.data?.orders || []).map((order) => normalize(order, 'binance'));
      const binanceFromHistory = allHistory.filter((order) => !isWebull(order) && OPEN_STATUSES.has(String(order.status).toUpperCase()));
      const webullOpen = (webullOpenResponse.data?.orders || []).map((order) => normalize(order, 'webull'));
      const uniqueOpenOrders = new Map();
      [...binanceOpen, ...binanceFromHistory, ...webullOpen].forEach((order) => uniqueOpenOrders.set(`${order.source}-${order.id}`, order));
      setOpenOrders([...uniqueOpenOrders.values()]);
      if (webullOpenResponse.data?.success === false) setNotice(webullOpenResponse.data?.message || 'Webull open orders could not be refreshed.');
    } catch (error) {
      setNotice(error.response?.data?.message || 'Unable to load combined orders.');
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);
  const activeOpenOrders = useMemo(() => openOrders.filter((order) => OPEN_STATUSES.has(String(order.status).toUpperCase()) || !order.status || order.status === '—'), [openOrders]);
  const sortedHistory = useMemo(() => [...history].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''))), [history]);
  const historyPages = Math.max(1, Math.ceil(sortedHistory.length / historyPageSize));
  const paginatedHistory = useMemo(() => sortedHistory.slice((historyPage - 1) * historyPageSize, historyPage * historyPageSize), [sortedHistory, historyPage, historyPageSize]);
  useEffect(() => { if (historyPage > historyPages) setHistoryPage(historyPages); }, [historyPage, historyPages]);

  const handleCancelOrder = async (order) => {
    if (!window.confirm(`Are you sure you want to cancel the open ${order.source === 'webull' ? 'Webull' : 'Binance.US'} order for ${order.symbol}?`)) {
      return;
    }
    setCancellingId(order.id);
    try {
      if (order.source === 'webull') {
        const resp = await axios.post('/api/webull/orders/cancel', {
          account_id: order._webull_account_id,
          order_id: order.id,
          client_order_id: order.client_order_id,
        }, { withCredentials: true });
        if (resp.data?.success) {
          setNotice(resp.data.message || 'Webull order cancelled.');
          await load();
        } else {
          setNotice(resp.data?.message || 'Failed to cancel Webull order.');
        }
      } else {
        const resp = await axios.post(`/api/trading/cancel-order/${order.id}`, { symbol: order.symbol }, { withCredentials: true });
        if (resp.data?.success) {
          setNotice('Binance.US order cancelled.');
          await load();
        } else {
          setNotice(resp.data?.error || 'Failed to cancel Binance.US order.');
        }
      }
    } catch (err) {
      setNotice(err.response?.data?.message || err.response?.data?.error || 'Failed to cancel order.');
    } finally {
      setCancellingId(null);
    }
  };

  return (
    <div className="trading-page" style={{ padding: '20px', maxWidth: '1500px', margin: '0 auto' }}>
      <div className="trading-header" style={{ marginBottom: 18 }}>
        <div>
          <h1 style={{ fontSize: '2rem', margin: 0 }}>📋 Orders</h1>
          <p style={{ margin: '6px 0 0', color: 'var(--text-secondary, #94a3b8)' }}>
            Open orders and history across Binance.US and Webull.
          </p>
        </div>
        <button type="button" className="btn btn-secondary" onClick={load}>🔄 Refresh</button>
      </div>
      {notice && <div className="modern-real-warning" style={{ marginBottom: 16 }}>⚠️ {notice}</div>}
      <div className="trading-tabs">
        <button className={`tab-button ${activeTab === 'open' ? 'active' : ''}`} onClick={() => setActiveTab('open')}>
          ⏳ <span className="tab-text">Open Orders</span>{activeOpenOrders.length > 0 && <span className="tab-badge">{activeOpenOrders.length}</span>}
        </button>
        <button className={`tab-button ${activeTab === 'history' ? 'active' : ''}`} onClick={() => setActiveTab('history')}>
          📜 <span className="tab-text">Order History</span>
        </button>
      </div>
      <div className="trading-content">
        <section className="order-history-container">
          {loading ? (
            <div className="empty-state"><p>Loading combined orders…</p></div>
          ) : activeTab === 'open' ? (
            <>
              <h2>All Open Orders</h2>
              <OrderTable orders={activeOpenOrders} open onCancelOrder={handleCancelOrder} cancellingId={cancellingId} />
            </>
          ) : (
            <>
              <h2>All Order History</h2>
              <OrderTable orders={paginatedHistory} />
              <Pagination page={historyPage} setPage={setHistoryPage} pageSize={historyPageSize} setPageSize={setHistoryPageSize} total={sortedHistory.length} />
            </>
          )}
        </section>
      </div>
    </div>
  );
}
