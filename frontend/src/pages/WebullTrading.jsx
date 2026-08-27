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
      const [portfolioResponse, historyResponse, openResponse, signalsResponse, signalSettingsResponse] = await Promise.all([
        axios.get('/api/coin-data-live', { withCredentials: true }),
        axios.get('/api/trading/real-orders?limit=all', { withCredentials: true }),
        axios.get('/api/webull/open-orders', { withCredentials: true }),
        axios.get('/api/webull/ai-signals?limit=50', { withCredentials: true }),
        axios.get('/api/webull/ai-settings', { withCredentials: true }),
      ]);
      setHoldings((portfolioResponse.data?.portfolio || []).filter((item) => item?.is_external || item?.source === 'webull'));
      setHistory((historyResponse.data?.orders || [])
        .filter((order) => String(order?.source || '').toLowerCase() === 'webull')
        .map(normalizeOrder));
      setOpenOrders((openResponse.data?.orders || []).map(normalizeOrder));
      setSignals(signalsResponse.data?.signals || []);
      setSignalSettings((current) => ({ ...current, ...(signalSettingsResponse.data?.settings || {}) }));
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
          {activeTab === 'ai_analysis' && <section className="order-history-container"><h2>Webull AI Analysis</h2><p style={{ color: 'var(--text-secondary, #94a3b8)', marginTop: 0 }}>Stored research signals use distinct crypto and equity/ETF prompt paths, are graded at their saved forecast horizon, and never submit a Webull order. Options remain unavailable until contract-level mapping is added.</p><div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'end', margin: '18px 0' }}><label style={{ display: 'grid', gap: 6, minWidth: 240 }}><span>Imported holding</span><select value={selectedSignalHolding} onChange={(event) => setSelectedSignalHolding(event.target.value)}>{analyzableHoldings.map((holding) => <option key={`${holding.id}-${holding.instrument_type}`} value={`${holding.symbol}|${holding.instrument_type}`}>{holding.symbol} · {holding.instrument_type}</option>)}</select></label><button type="button" className="btn btn-primary" disabled={!selectedSignalHolding || signalBusy} onClick={createSignal}>{signalBusy ? 'Creating…' : 'Create Stored Signal'}</button></div>{signalMessage && <div className="modern-real-warning" style={{ marginBottom: 16 }}>{signalMessage}</div>}<div className="trading-asset-card" style={{ marginBottom: 18 }}><strong>Optional scheduled signals</strong><div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'end', marginTop: 12 }}><label style={{ display: 'flex', gap: 8, alignItems: 'center' }}><input type="checkbox" checked={!!signalSettings.webull_ai_scheduling_enabled} onChange={(event) => setSignalSettings((current) => ({ ...current, webull_ai_scheduling_enabled: event.target.checked }))} /> Enable scheduled read-only signals</label>{[['webull_crypto_sentiment_frequency_hours', 'Crypto cadence (hours)'], ['webull_crypto_sentiment_horizon_hours', 'Crypto forecast (hours)'], ['webull_equity_sentiment_frequency_hours', 'Equity / ETF cadence (hours)'], ['webull_equity_sentiment_horizon_hours', 'Equity / ETF forecast (hours)']].map(([key, label]) => <label key={key} style={{ display: 'grid', gap: 6 }}><span>{label}</span><input type="number" min="1" max="720" value={signalSettings[key]} onChange={(event) => setSignalSettings((current) => ({ ...current, [key]: event.target.value }))} style={{ width: 150 }} /></label>)}<button type="button" className="btn btn-secondary" disabled={signalBusy} onClick={saveSignalSettings}>Save schedule</button></div></div><WebullSignalTable signals={signals} /></section>}
        </>}
      </div>
    </div>
  );
}

function WebullSignalTable({ signals }) {
  if (!signals.length) return <div className="empty-state"><p>No stored Webull signals yet. Current signals remain tracking until their saved evaluation time.</p></div>;
  const outcomeColor = { correct: '#22c55e', neutral: '#38bdf8', wrong: '#ef4444', tracking: '#fbbf24' };
  return <div className="table-container trading-table"><div className="order-table-scroll"><table><thead><tr><th>Created</th><th>Symbol</th><th>Asset Class</th><th>Signal</th><th>Forecast</th><th>Outcome</th><th>Origin</th></tr></thead><tbody>{signals.map((signal) => <tr key={signal.id}><td>{formatDate(signal.created_at)}</td><td>{signal.symbol}</td><td>{signal.instrument_type}</td><td><strong>{signal.recommendation}</strong><br /><small>{signal.reason}</small></td><td>{signal.forecast_horizon_hours}h · target {formatDate(signal.target_evaluation_at)}</td><td style={{ color: outcomeColor[signal.outcome_status] || 'inherit' }}>{signal.outcome_status || 'tracking'}{signal.outcome_pct != null ? ` (${Number(signal.outcome_pct).toFixed(2)}%)` : ''}</td><td>{signal.origin}</td></tr>)}</tbody></table></div></div>;
}

function WebullHoldings({ holdings, compact = false }) {
  if (!holdings.length) return <div className="empty-state"><p>No imported Webull holdings. Import a Webull portfolio snapshot in Settings first.</p></div>;
  return <div className="table-container trading-table" style={{ marginTop: compact ? 12 : 20 }}><div className="order-table-scroll"><table><thead><tr><th>Symbol</th><th>Type</th><th>Quantity</th><th>Last Price</th><th>Value</th><th>Unrealized P&amp;L</th><th>Source</th></tr></thead><tbody>{holdings.map((holding) => { const isOption = String(holding.instrument_type || '').toUpperCase() === 'OPTION'; const optionLabel = [holding.underlying_symbol, holding.option_expiration, holding.option_strike != null ? `$${holding.option_strike}` : '', holding.option_type].filter(Boolean).join(' · '); return <tr key={holding.id}><td style={{ display: 'flex', alignItems: 'center', gap: 8 }}><CryptoIcon symbol={holding.symbol} size={22} /><span>{holding.symbol}{isOption && optionLabel && <small style={{ display: 'block', color: 'var(--text-secondary, #94a3b8)' }}>{optionLabel}</small>}</span></td><td>{holding.instrument_type || 'Security'}{isOption && !holding.instrument_id && <small style={{ display: 'block', color: '#fbbf24' }}>Contract resolution needed</small>}</td><td>{number(holding.amount, 6)}</td><td>{holding.current_price ? `$${number(holding.current_price, 4)}` : '—'}</td><td>{holding.current_value != null ? `$${number(holding.current_value)}` : '—'}</td><td style={{ color: Number(holding.webull_unrealized_pnl) >= 0 ? '#4ade80' : '#f87171' }}>{holding.webull_unrealized_pnl == null ? '—' : `$${number(holding.webull_unrealized_pnl)}`}</td><td><span className="badge" style={{ background: 'rgba(96, 165, 250, .16)', color: '#60a5fa' }}>Webull</span></td></tr>; })}</tbody></table></div></div>;
}
