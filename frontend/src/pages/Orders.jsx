import React, { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import './Trading.css';

const PAGE_SIZES = [20, 50, 100, 200];
const OPEN_STATUSES = new Set(['ACTIVE', 'OPEN', 'NEW', 'WORKING', 'PENDING', 'PARTIALLY_FILLED', 'PARTIALLY FILLED']);
const isWebull = (order) => String(order?.source || order?.origin || '').toLowerCase() === 'webull';
const amount = (value, digits = 6) => Number.isFinite(Number(value)) ? Number(value).toLocaleString(undefined, { maximumFractionDigits: digits }) : '—';
const timestamp = (value) => { const date = new Date(value); return value && !Number.isNaN(date.getTime()) ? date.toLocaleString() : '—'; };
const normalize = (order, source) => {
  const automationOrigin = String(order?.origin || order?.trigger_type || '').toLowerCase();
  const origin = ['auto_buy', 'auto_sell'].includes(automationOrigin) ? automationOrigin : order?.origin;
  return {
  ...order,
  source,
  origin,
  id: order.id || order.order_id || order.orderId || `${source}-${order.symbol || order.ticker || 'unknown'}-${order.created_at || order.create_time || order.filled_time_at || ''}`,
  symbol: String(order.symbol || order.ticker || '—').toUpperCase(),
  side: order.side || '—',
  order_type: order.order_type || order.type || '—',
  quantity: order.quantity ?? order.total_quantity ?? order.order_quantity,
  filled_quantity: order.filled_quantity ?? order.executed_quantity ?? order.filled_qty,
  price: order.price ?? order.limit_price ?? order.order_price,
  status: order.status || order.order_status || '—',
  created_at: order.created_at || order.create_time || order.placed_time || order.place_time || order.filled_time_at || order.time,
  };
};

const isAutomation = (order) => Boolean(order?.is_auto_trigger)
  || ['auto_buy', 'auto_sell'].includes(String(order?.trigger_type || order?.origin || order?.source || '').toLowerCase());
const webullAccountId = (order) => String(order?.webull_account_id || order?._webull_account_id || '').trim();
const orderSource = (order) => (isAutomation(order) ? 'automation' : (isWebull(order) ? 'webull' : 'binance'));
const instrumentCategory = (order) => {
  if (isAutomation(order)) return 'automation';
  if (!isWebull(order)) return 'crypto';
  const hint = String(order?.instrument_type || order?.asset_class || order?.security_type || '').toUpperCase();
  if (hint.includes('CRYPTO') || hint.includes('COIN') || hint.includes('TOKEN')) return 'crypto';
  if (hint.includes('OPTION')) return 'option';
  if (hint.includes('FUTURE')) return 'future';
  if (hint.includes('ETF') || hint.includes('STOCK') || hint.includes('EQUITY') || hint.includes('SECURITY')) return 'equity';
  return 'other';
};
const accountLabel = (account) => {
  const name = account?.account_label || account?.account_name || 'Webull account';
  const masked = account?.account_id_masked || (account?.account_id ? `••••${String(account.account_id).slice(-4)}` : '');
  return masked ? `${name} (${masked})` : name;
};

const displaySide = (side) => String(side || '—').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
const displayType = (type) => String(type || '—').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());

function SourceBadge({ order }) {
  const webull = isWebull(order);
  const automated = String(order?.origin || order?.source || '').toLowerCase();
  const automationLabel = automated === 'auto_sell' ? 'Auto-Sell' : automated === 'auto_buy' ? 'Auto-Buy' : null;
  return <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 4 }}>
    <span className="badge" style={{ background: webull ? 'rgba(96, 165, 250, .16)' : 'rgba(251, 191, 36, .16)', color: webull ? '#2563eb' : '#a16207' }}>{webull ? 'Webull' : 'Binance.US'}</span>
    {automationLabel && <span className="badge" style={{ background: automated === 'auto_sell' ? 'rgba(248, 113, 113, .16)' : 'rgba(74, 222, 128, .16)', color: automated === 'auto_sell' ? '#dc2626' : '#15803d' }}>{automationLabel}</span>}
  </span>;
}

function AccountCell({ order, webullAccounts }) {
  const account = webullAccounts.find((candidate) => String(candidate.account_id) === webullAccountId(order));
  const label = isAutomation(order)
    ? 'Crypto Alert App trigger'
    : isWebull(order) ? (account ? accountLabel(account) : order.webull_account_type || 'Webull account') : 'Binance.US';
  return <div className="combined-order-account"><SourceBadge order={order} /><span>{label}</span></div>;
}

function OrderTable({ orders, open, onCancelOrder, cancellingId, webullAccounts }) {
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
                <td><AccountCell order={order} webullAccounts={webullAccounts} /></td>
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
  const [historyLoading, setHistoryLoading] = useState(false);
  const [webullOpenLoading, setWebullOpenLoading] = useState(false);
  const [webullOpenProgress, setWebullOpenProgress] = useState({ complete: 0, total: 0 });
  const [webullAccounts, setWebullAccounts] = useState([]);
  const [filters, setFilters] = useState({
    source: 'all', account: 'all', symbol: '', product: 'all', status: 'all', timeRange: 'all',
  });
  const openOrdersRequestId = useRef(0);

  const replaceOpenOrdersForSource = (source, orders) => {
    setOpenOrders((previous) => {
      const combined = new Map();
      [...previous.filter((order) => order.source !== source), ...orders]
        .forEach((order) => combined.set(`${order.source}-${order.id}`, order));
      return [...combined.values()];
    });
  };

  const loadOpenOrders = async () => {
    const requestId = ++openOrdersRequestId.current;
    setWebullOpenLoading(true);
    setWebullOpenProgress({ complete: 0, total: 0 });
    replaceOpenOrdersForSource('webull', []);

    // Webull limits order reads globally, so its all-accounts endpoint used to
    // withhold every result until the final account completed. Request known
    // accounts individually and render each result immediately instead.
    (async () => {
      try {
        const accountsResponse = await axios.get('/api/webull/accounts', { withCredentials: true });
        if (requestId !== openOrdersRequestId.current) return;
        const enabled = accountsResponse.data?.enabled_account_ids || [];
        const enabledAccounts = (accountsResponse.data?.accounts || [])
          .filter((account) => !enabled.length || enabled.includes(account.account_id))
        setWebullAccounts(enabledAccounts);
        const accountIds = enabledAccounts
          .map((account) => account.account_id)
          .filter(Boolean);
        setWebullOpenProgress({ complete: 0, total: accountIds.length });
        if (!accountIds.length) return;

        const ordersByAccount = new Map();
        let completed = 0;
        await Promise.all(accountIds.map(async (accountId) => {
          try {
            const response = await axios.get(`/api/webull/open-orders?account_id=${encodeURIComponent(accountId)}`, { withCredentials: true });
            if (requestId !== openOrdersRequestId.current) return;
            if (response.data?.success === false) throw new Error(response.data?.message || 'Webull open orders could not be refreshed.');
            ordersByAccount.set(accountId, (response.data?.orders || []).map((order) => normalize(order, 'webull')));
            replaceOpenOrdersForSource('webull', [...ordersByAccount.values()].flat());
          } catch (error) {
            if (requestId === openOrdersRequestId.current) {
              setNotice(error.response?.data?.message || error.message || 'Some Webull open orders could not be refreshed.');
            }
          } finally {
            completed += 1;
            if (requestId === openOrdersRequestId.current) {
              setWebullOpenProgress({ complete: completed, total: accountIds.length });
            }
          }
        }));
      } catch (error) {
        if (requestId === openOrdersRequestId.current) {
          setNotice(error.response?.data?.message || 'Webull open orders could not be refreshed.');
        }
      } finally {
        if (requestId === openOrdersRequestId.current) setWebullOpenLoading(false);
      }
    })();

    try {
      // This endpoint merges Binance.US-native open orders with this app's
      // active Auto-Buy / Auto-Sell trigger records.  The generic pending
      // endpoint only returns orders already submitted to Binance.US.
      const binanceOpenResponse = await axios.get('/api/trading/open-orders', { withCredentials: true });
      if (requestId !== openOrdersRequestId.current) return;
      const binanceOpen = (binanceOpenResponse.data?.orders || binanceOpenResponse.data?.pending_orders || []).map((order) => normalize(order, 'binance'));
      replaceOpenOrdersForSource('binance', binanceOpen);
    } catch (error) {
      if (requestId === openOrdersRequestId.current) {
        setNotice(error.response?.data?.message || 'Unable to load Binance.US open orders.');
      }
    }
  };

  const loadHistory = async () => {
    setHistoryLoading(true);
    try {
      const historyResponse = await axios.get('/api/trading/real-orders?limit=100', { withCredentials: true });
      const allHistory = (historyResponse.data?.orders || []).map((order) => {
        const source = String(order?.source || '').toLowerCase();
        return normalize(order, ['auto_buy', 'auto_sell'].includes(source) ? source : (isWebull(order) ? 'webull' : 'binance'));
      });
      setHistory(allHistory);
      const binanceFromHistory = allHistory.filter((order) => !isWebull(order) && OPEN_STATUSES.has(String(order.status).toUpperCase()));
      if (binanceFromHistory.length) {
        setOpenOrders((prev) => {
          const map = new Map();
          [...prev, ...binanceFromHistory].forEach((o) => map.set(`${o.source}-${o.id}`, o));
          return [...map.values()];
        });
      }
    } catch (error) {
      // Background history loading errors non-blocking
    } finally {
      setHistoryLoading(false);
    }
  };

  const load = async () => {
    setLoading(true);
    setNotice('');
    await loadOpenOrders();
    setLoading(false);
  };

  useEffect(() => { load(); }, []);
  const activeOpenOrders = useMemo(() => openOrders.filter((order) => OPEN_STATUSES.has(String(order.status).toUpperCase()) || !order.status || order.status === '—'), [openOrders]);
  const filterableOrders = useMemo(() => [...activeOpenOrders, ...history], [activeOpenOrders, history]);
  const statusOptions = useMemo(() => [...new Set(filterableOrders.map((order) => String(order.status || 'Unknown').toUpperCase()))].sort(), [filterableOrders]);
  const matchesFilters = (order) => {
    if (filters.source !== 'all' && orderSource(order) !== filters.source) return false;
    if (filters.account === 'binance' && isWebull(order)) return false;
    if (filters.account !== 'all' && filters.account !== 'binance' && webullAccountId(order) !== filters.account) return false;
    if (filters.symbol && !String(order.symbol || '').toUpperCase().includes(filters.symbol.trim().toUpperCase())) return false;
    if (filters.product !== 'all' && instrumentCategory(order) !== filters.product) return false;
    if (filters.status !== 'all' && String(order.status || 'Unknown').toUpperCase() !== filters.status) return false;
    if (filters.timeRange !== 'all') {
      const createdAt = new Date(order.created_at);
      const days = Number(filters.timeRange);
      if (Number.isNaN(createdAt.getTime()) || createdAt.getTime() < Date.now() - days * 24 * 60 * 60 * 1000) return false;
    }
    return true;
  };
  const filteredOpenOrders = useMemo(() => activeOpenOrders
    .filter(matchesFilters)
    .sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''))), [activeOpenOrders, filters, webullAccounts]);
  const sortedHistory = useMemo(() => history.filter(matchesFilters).sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''))), [history, filters, webullAccounts]);
  const historyPages = Math.max(1, Math.ceil(sortedHistory.length / historyPageSize));
  const paginatedHistory = useMemo(() => sortedHistory.slice((historyPage - 1) * historyPageSize, historyPage * historyPageSize), [sortedHistory, historyPage, historyPageSize]);
  useEffect(() => { if (historyPage > historyPages) setHistoryPage(historyPages); }, [historyPage, historyPages]);
  useEffect(() => { setHistoryPage(1); }, [filters]);

  const setFilter = (name, value) => setFilters((current) => ({ ...current, [name]: value }));
  const resetFilters = () => setFilters({ source: 'all', account: 'all', symbol: '', product: 'all', status: 'all', timeRange: 'all' });

  const selectTab = (tab) => {
    setActiveTab(tab);
    // Full order history is an exchange-wide scan (one Binance request per
    // relevant trading pair plus Webull account history). Do not make the
    // initial Combined Orders view wait for that nonessential work.
    if (tab === 'history' && !history.length && !historyLoading) loadHistory();
  };

  const handleCancelOrder = async (order) => {
    const isAutoTrigger = Boolean(order.is_auto_trigger) || ['auto_buy', 'auto_sell'].includes(String(order.trigger_type || order.origin || '').toLowerCase());
    const cancellationTarget = isAutoTrigger
      ? `${String(order.trigger_type || order.origin).replace('_', '-')} trigger`
      : `${order.source === 'webull' ? 'Webull' : 'Binance.US'} order`;
    if (!window.confirm(`Are you sure you want to cancel the open ${cancellationTarget} for ${order.symbol}?`)) {
      return;
    }
    setCancellingId(order.id);
    try {
      if (isAutoTrigger) {
        const triggerType = String(order.trigger_type || order.origin || '').toLowerCase();
        const response = await axios.post(
          triggerType === 'auto_buy' ? '/api/portfolio/trigger-auto-buy' : '/api/portfolio/trigger-auto-sell',
          {
            symbol: order.base_symbol || order.symbol,
            table_type: order.table_type || 'portfolio',
            enabled: false,
          },
          { withCredentials: true },
        );
        if (response.data?.success) {
          setNotice(`${triggerType === 'auto_buy' ? 'Auto-Buy' : 'Auto-Sell'} disabled.`);
          await load();
        } else {
          setNotice(response.data?.error || 'Failed to disable the automated trigger.');
        }
      } else if (order.source === 'webull') {
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
        <button className={`tab-button ${activeTab === 'open' ? 'active' : ''}`} onClick={() => selectTab('open')}>
          ⏳ <span className="tab-text">Open Orders</span>{filteredOpenOrders.length > 0 && <span className="tab-badge">{filteredOpenOrders.length}</span>}
        </button>
        <button className={`tab-button ${activeTab === 'history' ? 'active' : ''}`} onClick={() => selectTab('history')}>
          📜 <span className="tab-text">Order History</span>
        </button>
      </div>
      <div className="trading-content">
        <section className="order-history-container">
          <div className="combined-order-filters" aria-label="Combined order filters">
            <label>Source<select value={filters.source} onChange={(event) => setFilter('source', event.target.value)}><option value="all">All sources</option><option value="binance">Binance.US</option><option value="webull">Webull</option><option value="automation">Auto-Buy / Auto-Sell</option></select></label>
            <label>Account<select value={filters.account} onChange={(event) => setFilter('account', event.target.value)}><option value="all">All accounts</option><option value="binance">Binance.US</option>{webullAccounts.map((account) => <option key={account.account_id} value={account.account_id}>{accountLabel(account)}</option>)}</select></label>
            <label>Symbol<input type="search" value={filters.symbol} onChange={(event) => setFilter('symbol', event.target.value)} placeholder="BTC, TSLA…" /></label>
            <label>Product<select value={filters.product} onChange={(event) => setFilter('product', event.target.value)}><option value="all">All products</option><option value="crypto">Crypto</option><option value="equity">Stock / ETF</option><option value="option">Options</option><option value="future">Futures</option><option value="automation">Automation</option><option value="other">Other</option></select></label>
            <label>Status<select value={filters.status} onChange={(event) => setFilter('status', event.target.value)}><option value="all">All statuses</option>{statusOptions.map((status) => <option key={status} value={status}>{displayType(status)}</option>)}</select></label>
            <label>Time range<select value={filters.timeRange} onChange={(event) => setFilter('timeRange', event.target.value)}><option value="all">All time</option><option value="1">Past 24 hours</option><option value="7">Past 7 days</option><option value="30">Past 30 days</option><option value="90">Past 90 days</option></select></label>
            <button type="button" className="btn btn-secondary combined-order-filter-reset" onClick={resetFilters}>Reset filters</button>
          </div>
          {loading ? (
            <div className="empty-state"><p>Loading combined orders…</p></div>
          ) : activeTab === 'open' ? (
            <>
              <h2>All Open Orders</h2>
              {webullOpenLoading && <p className="order-refresh-status" role="status">Refreshing Webull open orders{webullOpenProgress.total ? ` (${webullOpenProgress.complete}/${webullOpenProgress.total} accounts)…` : '…'}</p>}
              <OrderTable orders={filteredOpenOrders} open onCancelOrder={handleCancelOrder} cancellingId={cancellingId} webullAccounts={webullAccounts} />
            </>
          ) : historyLoading && !sortedHistory.length ? (
            <div className="empty-state"><p>Loading order history…</p></div>
          ) : (
            <>
              <h2>All Order History</h2>
              <OrderTable orders={paginatedHistory} webullAccounts={webullAccounts} />
              <Pagination page={historyPage} setPage={setHistoryPage} pageSize={historyPageSize} setPageSize={setHistoryPageSize} total={sortedHistory.length} />
            </>
          )}
        </section>
      </div>
    </div>
  );
}
