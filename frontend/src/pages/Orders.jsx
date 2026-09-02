import React, { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import CancelOrderModal from '../components/CancelOrderModal';
import { formatEasternDateTime as formatEasternDateTimeValue } from '../utils/dateTime';
import './Trading.css';
import './AIDashboard.css';

const formatEasternTime = (isoString) => {
  return isoString ? formatEasternDateTimeValue(isoString) : 'Not available';
};

const getProviderName = (provider) => {
  switch ((provider || '').toLowerCase()) {
    case 'openai': return 'OpenAI';
    case 'gemini': return 'Google Gemini';
    case 'zai': return 'Z.AI';
    case 'perplexity': return 'Perplexity';
    case 'inception': return 'Inception Labs';
    default: return provider || 'AI';
  }
};

const getTierName = (tier) => {
  if (!tier) return 'Primary';
  return tier.charAt(0).toUpperCase() + tier.slice(1).toLowerCase();
};

const escapeHtml = (str) =>
  String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

const formatInlineMarkdown = (text) => {
  let formatted = escapeHtml(text);
  formatted = formatted.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  formatted = formatted.replace(/\*(.+?)\*/g, '<em>$1</em>');
  formatted = formatted.replace(/`(.+?)`/g, '<code>$1</code>');
  formatted = formatted.replace(/\[(.+?)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  formatted = formatted.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
  return formatted;
};

const renderMarkdown = (markdown) => {
  if (!markdown) return '';
  const lines = markdown.split(/\r?\n/);
  const html = [];
  let inUl = false;
  let inOl = false;
  let inBlockquote = false;

  const closeLists = () => {
    if (inUl) { html.push('</ul>'); inUl = false; }
    if (inOl) { html.push('</ol>'); inOl = false; }
  };
  const closeBlockquote = () => {
    if (inBlockquote) { html.push('</blockquote>'); inBlockquote = false; }
  };

  lines.forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) {
      closeLists();
      closeBlockquote();
      return;
    }
    const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      closeLists();
      closeBlockquote();
      const level = headingMatch[1].length;
      html.push(`<h${level}>${formatInlineMarkdown(headingMatch[2])}</h${level}>`);
      return;
    }
    const ulMatch = trimmed.match(/^[-*+]\s+(.*)$/);
    if (ulMatch) {
      closeBlockquote();
      if (inOl) { html.push('</ol>'); inOl = false; }
      if (!inUl) { html.push('<ul>'); inUl = true; }
      html.push(`<li>${formatInlineMarkdown(ulMatch[1])}</li>`);
      return;
    }
    const olMatch = trimmed.match(/^\d+\.\s+(.*)$/);
    if (olMatch) {
      closeBlockquote();
      if (inUl) { html.push('</ul>'); inUl = false; }
      if (!inOl) { html.push('<ol>'); inOl = false; }
      html.push(`<li>${formatInlineMarkdown(olMatch[1])}</li>`);
      return;
    }
    const bqMatch = trimmed.match(/^>\s*(.*)$/);
    if (bqMatch) {
      closeLists();
      if (!inBlockquote) { html.push('<blockquote>'); inBlockquote = true; }
      html.push(`<p>${formatInlineMarkdown(bqMatch[1])}</p>`);
      return;
    }
    closeLists();
    closeBlockquote();
    html.push(`<p>${formatInlineMarkdown(trimmed)}</p>`);
  });

  closeLists();
  closeBlockquote();
  return html.join('');
};

const PAGE_SIZES = [20, 50, 100, 200];
const OPEN_STATUSES = new Set([
  'ACTIVE', 'OPEN', 'NEW', 'WORKING', 'PENDING', 'SUBMITTED',
  'PARTIAL_FILLED', 'PARTIALLY_FILLED', 'PARTIALLY FILLED',
]);
const isWebull = (order) => String(order?.source || order?.origin || '').toLowerCase() === 'webull';
const amount = (value, digits = 6) => Number.isFinite(Number(value)) ? Number(value).toLocaleString(undefined, { maximumFractionDigits: digits }) : '—';
const timestamp = (value) => formatEasternDateTimeValue(value);
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
  fee: order.fee ?? order.commission ?? 0,
  fee_asset: order.fee_asset || order.commission_asset || '',
  status: order.status || order.order_status || '—',
  created_at: order.created_at || order.create_time || order.placed_time || order.place_time || order.filled_time_at || order.time,
  };
};

const isAutomation = (order) => {
  const automationKinds = [
    order?.trigger_type,
    order?.origin,
    order?.source,
    order?.order_type,
  ].map((value) => String(value || '').toLowerCase());
  return Boolean(order?.is_auto_trigger)
    || automationKinds.some((value) => ['auto_buy', 'auto_sell'].includes(value));
};
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

function AccountCell({ order, webullAccounts }) {
  const account = webullAccounts.find((candidate) => String(candidate.account_id) === webullAccountId(order));
  const label = isWebull(order) ? (account ? accountLabel(account) : order.webull_account_type || 'Webull account') : 'Binance.US';
  return <div className="combined-order-account">{label}</div>;
}

function OrderTable({ orders, open, onCancelOrder, cancellingId, webullAccounts }) {
  if (!orders.length) return <div className="empty-state"><p>No {open ? 'open' : 'historical'} orders for the selected accounts.</p></div>;
  return (
    <div className="table-container trading-table">
      <div className="order-table-scroll">
        <table>
          <thead>
            <tr>
              <th>Date / Time</th><th className="combined-order-account-heading">Account</th><th>Symbol</th><th>Side</th><th>Type</th><th>Quantity</th><th>Price</th><th>Filled</th><th>Fee</th><th>Status</th>
              {open && <th>Est. P&L (if filled)</th>}
              {open && <th>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr key={`${order.source}-${order.id}`}>
                <td>{timestamp(order.created_at)}</td>
                <td className="combined-order-account-cell"><AccountCell order={order} webullAccounts={webullAccounts} /></td>
                <td>{order.symbol}</td>
                <td>{displaySide(order.side)}</td>
                <td>{displayType(order.order_type)}</td>
                <td>{amount(order.quantity)}</td>
                <td>{Number(order.price) > 0 ? `$${amount(order.price, 4)}` : 'Market'}</td>
                <td>{amount(order.filled_quantity)}</td>
                <td>
                  {(() => {
                    const feeVal = Number(order.fee || 0);
                    const asset = order.fee_asset || '';
                    if (feeVal <= 0) return '—';
                    if (!asset || asset === 'USD' || asset === 'USDT') return `$${amount(feeVal, 4)}`;
                    return `${amount(feeVal, 8)} ${asset}`;
                  })()}
                </td>
                <td>{order.status}</td>
                {open && (
                  <td>—</td>
                )}
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
  const [activeTab, setActiveTab] = useState(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const t = params.get('tab');
      if (['open', 'history', 'market_analysis', 'portfolio_review'].includes(t)) {
        return t;
      }
    } catch {}
    return 'open';
  });
  const [marketAnalysisData, setMarketAnalysisData] = useState(null);
  const [portfolioReviewData, setPortfolioReviewData] = useState(null);
  const [marketPrompt, setMarketPrompt] = useState('');
  const [portfolioPrompt, setPortfolioPrompt] = useState('');
  const [showMarketPromptModal, setShowMarketPromptModal] = useState(false);
  const [showPortfolioPromptModal, setShowPortfolioPromptModal] = useState(false);
  const [workflowLoading, setWorkflowLoading] = useState({ marketAnalysis: false, portfolioReview: false });
  const [workflowError, setWorkflowError] = useState({ marketAnalysis: '', portfolioReview: '' });
  const [history, setHistory] = useState([]);
  const [openOrders, setOpenOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');
  const [cancellingId, setCancellingId] = useState(null);
  const [cancelModal, setCancelModal] = useState({ isVisible: false, order: null, error: '', loading: false });
  const [historyPage, setHistoryPage] = useState(1);
  const [historyPageSize, setHistoryPageSize] = useState(50);
  const [historyTotal, setHistoryTotal] = useState(0);
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
      const historyResponse = await axios.get(
        `/api/trading/real-orders?page=${historyPage}&page_size=${historyPageSize}`,
        { withCredentials: true },
      );
      const allHistory = (historyResponse.data?.orders || []).map((order) => {
        const source = String(order?.source || '').toLowerCase();
        return normalize(order, ['auto_buy', 'auto_sell'].includes(source) ? source : (isWebull(order) ? 'webull' : 'binance'));
      });
      setHistory(allHistory);
      setHistoryTotal(Number(historyResponse.data?.total ?? allHistory.length));
    } catch (error) {
      setNotice(error.response?.data?.message || 'Unable to load order history.');
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

  const normalizeWorkflowResult = (data) => {
    if (!data) return null;
    const content = data.analysis?.content || data.body || '';
    const generatedAt = data.analysis?.generated_at || data.created_at || data.time || null;
    const provider = data.analysis?.provider || data.provider || null;
    const model = data.analysis?.model || data.model || null;
    const tier = data.analysis?.tier || data.tier || null;
    if (!content) return null;
    return {
      content,
      generated_at: generatedAt,
      provider,
      model,
      tier,
    };
  };

  const loadLatestWorkflowData = async (targetType = 'all') => {
    if (targetType === 'all' || targetType === 'market-analysis') {
      try {
        const res = await axios.get('/api/ai/workflow-latest?type=market-analysis', { withCredentials: true });
        const normalized = normalizeWorkflowResult(res.data);
        if (normalized) setMarketAnalysisData(normalized);
      } catch (err) {}
    }
    if (targetType === 'all' || targetType === 'portfolio-review') {
      try {
        const res = await axios.get('/api/ai/workflow-latest?type=portfolio-review', { withCredentials: true });
        const normalized = normalizeWorkflowResult(res.data);
        if (normalized) setPortfolioReviewData(normalized);
      } catch (err) {}
    }
  };

  const fetchWorkflowData = async (type) => {
    const isMarket = type === 'market-analysis';
    setWorkflowLoading(prev => ({ ...prev, [isMarket ? 'marketAnalysis' : 'portfolioReview']: true }));
    setWorkflowError(prev => ({ ...prev, [isMarket ? 'marketAnalysis' : 'portfolioReview']: '' }));
    try {
      const res = await axios.get(`/api/ai/${type}-workflow`, {
        params: { refresh: true },
        withCredentials: true
      });
      const normalized = normalizeWorkflowResult(res.data);
      if (normalized) {
        if (isMarket) setMarketAnalysisData(normalized);
        else setPortfolioReviewData(normalized);
      }
    } catch (err) {
      const msg = err.response?.data?.message || err.response?.data?.error || err.message || 'Workflow execution failed.';
      setWorkflowError(prev => ({ ...prev, [isMarket ? 'marketAnalysis' : 'portfolioReview']: msg }));
    } finally {
      setWorkflowLoading(prev => ({ ...prev, [isMarket ? 'marketAnalysis' : 'portfolioReview']: false }));
    }
  };

  const fetchWorkflowPrompt = async (type) => {
    try {
      const res = await axios.get(`/api/ai/${type}-workflow-prompt`, {
        params: { source: 'prompts' },
        withCredentials: true
      });
      const promptText = res.data?.body || res.data?.prompt || '';
      if (promptText) {
        if (type === 'market-analysis') setMarketPrompt(promptText);
        else setPortfolioPrompt(promptText);
      }
      return promptText;
    } catch (e) {
      console.error(`Failed to fetch ${type} prompt:`, e);
      return '';
    }
  };

  const handleOpenMarketPromptModal = async () => {
    await fetchWorkflowPrompt('market-analysis');
    setShowMarketPromptModal(true);
  };

  const handleOpenPortfolioPromptModal = async () => {
    await fetchWorkflowPrompt('portfolio-review');
    setShowPortfolioPromptModal(true);
  };

  useEffect(() => {
    load();
    loadLatestWorkflowData();
    fetchWorkflowPrompt('market-analysis');
    fetchWorkflowPrompt('portfolio-review');
  }, []);
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
  const historyPages = Math.max(1, Math.ceil(historyTotal / historyPageSize));
  const paginatedHistory = sortedHistory;
  useEffect(() => { if (historyPage > historyPages) setHistoryPage(historyPages); }, [historyPage, historyPages]);
  useEffect(() => { setHistoryPage(1); }, [filters]);

  const setFilter = (name, value) => setFilters((current) => ({ ...current, [name]: value }));
  const resetFilters = () => setFilters({ source: 'all', account: 'all', symbol: '', product: 'all', status: 'all', timeRange: 'all' });

  const selectTab = (tab) => {
    setActiveTab(tab);
    try {
      const url = new URL(window.location);
      url.searchParams.set('tab', tab);
      window.history.replaceState({}, '', url);
    } catch {}
    if (tab === 'market_analysis' && !marketAnalysisData) loadLatestWorkflowData('market-analysis');
    if (tab === 'portfolio_review' && !portfolioReviewData) loadLatestWorkflowData('portfolio-review');
  };

  useEffect(() => {
    if (activeTab === 'history') loadHistory();
  }, [activeTab, historyPage, historyPageSize]);

  const openCancelModalForOrder = (order) => {
    const account = webullAccounts.find((candidate) => String(candidate.account_id) === webullAccountId(order));
    setCancelModal({
      isVisible: true,
      order: {
        ...order,
        cancel_provider: isWebull(order) ? 'Webull' : 'Binance.US',
        cancel_account_label: isWebull(order) ? (account ? accountLabel(account) : order.webull_account_type || 'Webull account') : 'Binance.US',
      },
      error: '',
      loading: false,
    });
  };

  const closeCancelModal = () => {
    if (!cancelModal.loading) setCancelModal({ isVisible: false, order: null, error: '', loading: false });
  };

  const handleCancelOrderConfirm = async (twoFactorCode) => {
    const order = cancelModal.order;
    if (!order) return;
    const triggerType = String(order.trigger_type || order.origin || order.order_type || '').toLowerCase();
    const isAutoTrigger = isAutomation(order);
    setCancelModal((current) => ({ ...current, loading: true, error: '' }));
    setCancellingId(order.id);
    try {
      if (isAutoTrigger) {
        const response = await axios.post(
          triggerType === 'auto_buy' ? '/api/portfolio/trigger-auto-buy' : '/api/portfolio/trigger-auto-sell',
          {
            symbol: order.base_symbol || order.symbol,
            table_type: order.table_type || 'portfolio',
            enabled: false,
            two_factor_code: twoFactorCode,
          },
          { withCredentials: true },
        );
        if (response.data?.success) {
          setNotice(`${triggerType === 'auto_buy' ? 'Auto-Buy' : 'Auto-Sell'} disabled.`);
          setCancelModal({ isVisible: false, order: null, error: '', loading: false });
          await load();
        } else {
          setCancelModal((current) => ({ ...current, loading: false, error: response.data?.error || 'Failed to disable the automated trigger.' }));
        }
      } else if (order.source === 'webull') {
        const resp = await axios.post('/api/webull/orders/cancel', {
          account_id: webullAccountId(order),
          order_id: order.id,
          client_order_id: order.client_order_id,
          two_factor_code: twoFactorCode,
        }, { withCredentials: true });
        if (resp.data?.success) {
          setNotice(resp.data.message || 'Webull order cancelled.');
          setCancelModal({ isVisible: false, order: null, error: '', loading: false });
          await load();
        } else {
          setCancelModal((current) => ({ ...current, loading: false, error: resp.data?.message || 'Failed to cancel Webull order.' }));
        }
      } else {
        const resp = await axios.post(`/api/cancel-order/${order.id}`, { symbol: order.symbol, two_factor_code: twoFactorCode }, { withCredentials: true });
        if (resp.data?.success) {
          setNotice('Binance.US order cancelled.');
          setCancelModal({ isVisible: false, order: null, error: '', loading: false });
          await load();
        } else {
          setCancelModal((current) => ({ ...current, loading: false, error: resp.data?.error || 'Failed to cancel Binance.US order.' }));
        }
      }
    } catch (err) {
      setCancelModal((current) => ({
        ...current,
        loading: false,
        error: err.response?.data?.message || err.response?.data?.error || 'Failed to cancel order.',
      }));
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
        <button className={`tab-button ${activeTab === 'market_analysis' ? 'active' : ''}`} onClick={() => selectTab('market_analysis')}>
          📊 <span className="tab-text">Market Analysis</span>
        </button>
        <button className={`tab-button ${activeTab === 'portfolio_review' ? 'active' : ''}`} onClick={() => selectTab('portfolio_review')}>
          💼 <span className="tab-text">Portfolio Review</span>
        </button>
      </div>
      <div className="trading-content">
        {(activeTab === 'open' || activeTab === 'history') && (
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
                <OrderTable orders={filteredOpenOrders} open onCancelOrder={openCancelModalForOrder} cancellingId={cancellingId} webullAccounts={webullAccounts} />
              </>
            ) : historyLoading && !sortedHistory.length ? (
              <div className="empty-state"><p>Loading order history…</p></div>
            ) : (
              <>
                <h2>All Order History</h2>
                <OrderTable orders={paginatedHistory} webullAccounts={webullAccounts} />
                <Pagination page={historyPage} setPage={setHistoryPage} pageSize={historyPageSize} setPageSize={setHistoryPageSize} total={historyTotal} />
              </>
            )}
          </section>
        )}

        {/* MARKET ANALYSIS TAB (FULL WIDTH) */}
        {activeTab === 'market_analysis' && (
          <section className="order-history-container" style={{ width: '100%', padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16, marginBottom: 20 }}>
              <div>
                <h2 style={{ margin: 0, fontSize: '1.5rem', color: '#38bdf8' }}>📊 Universal Market Analysis</h2>
                <p style={{ margin: '4px 0 0', color: 'var(--text-secondary, #94a3b8)', fontSize: '14px' }}>
                  Macro economic intelligence covering traditional securities (S&P 500, Nasdaq, 10Y Yields, Federal Reserve policy) and cryptocurrency markets (Bitcoin dominance, liquidity, market structure).
                </p>
              </div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleOpenMarketPromptModal}
                >
                  📝 View Prompt
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={workflowLoading.marketAnalysis}
                  onClick={() => fetchWorkflowData('market-analysis')}
                >
                  {workflowLoading.marketAnalysis ? '⏳ Analyzing Market...' : '🔄 Refresh Analysis'}
                </button>
              </div>
            </div>

            {workflowError.marketAnalysis && (
              <div className="modern-real-warning" style={{ marginBottom: 16 }}>⚠️ {workflowError.marketAnalysis}</div>
            )}

            {marketAnalysisData ? (
              <div className="workflow-result" style={{ background: '#0b0f19', border: '1px solid #334155', borderRadius: 10, padding: 24 }}>
                <div
                  style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.7', color: '#e2e8f0' }}
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(marketAnalysisData.content) }}
                />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginTop: 24, paddingTop: 16, borderTop: '1px solid #1e293b' }}>
                  <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                    <strong>Generated:</strong> {formatEasternTime(marketAnalysisData.generated_at)}
                  </span>
                  {(marketAnalysisData.tier || marketAnalysisData.provider || marketAnalysisData.model) && (
                    <span className="meta-item ai-model-badge" style={{ background: 'rgba(99, 179, 237, 0.15)', border: '1px solid rgba(99, 179, 237, 0.3)', borderRadius: 6, padding: '3px 10px', fontSize: '12px' }}>
                      🤖 <strong>{getTierName(marketAnalysisData.tier)}:</strong> {getProviderName(marketAnalysisData.provider)} ({marketAnalysisData.model || 'Default'})
                    </span>
                  )}
                </div>
              </div>
            ) : (
              <div className="empty-state" style={{ padding: 48, textAlign: 'center' }}>
                <h3>🤖 No Market Analysis generated yet</h3>
                <p style={{ color: 'var(--text-secondary)', marginBottom: 16 }}>Click "Refresh Analysis" to trigger macro intelligence synthesis across securities and crypto.</p>
                <button type="button" className="btn btn-primary" onClick={() => fetchWorkflowData('market-analysis')}>
                  🚀 Generate Market Analysis
                </button>
              </div>
            )}
          </section>
        )}

        {/* PORTFOLIO REVIEW TAB (FULL WIDTH) */}
        {activeTab === 'portfolio_review' && (
          <section className="order-history-container" style={{ width: '100%', padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16, marginBottom: 20 }}>
              <div>
                <h2 style={{ margin: 0, fontSize: '1.5rem', color: '#38bdf8' }}>💼 Universal Portfolio Review</h2>
                <p style={{ margin: '4px 0 0', color: 'var(--text-secondary, #94a3b8)', fontSize: '14px' }}>
                  Comprehensive multi-asset intelligence evaluating overall asset allocation, sector weights, concentration risks, and tactical rebalancing across all Binance.US and Webull holdings.
                </p>
              </div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleOpenPortfolioPromptModal}
                >
                  📝 View Prompt
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={workflowLoading.portfolioReview}
                  onClick={() => fetchWorkflowData('portfolio-review')}
                >
                  {workflowLoading.portfolioReview ? '⏳ Reviewing Portfolio...' : '🔄 Refresh Review'}
                </button>
              </div>
            </div>

            {workflowError.portfolioReview && (
              <div className="modern-real-warning" style={{ marginBottom: 16 }}>⚠️ {workflowError.portfolioReview}</div>
            )}

            {portfolioReviewData ? (
              <div className="workflow-result" style={{ background: '#0b0f19', border: '1px solid #334155', borderRadius: 10, padding: 24 }}>
                <div
                  style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.7', color: '#e2e8f0' }}
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(portfolioReviewData.content) }}
                />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginTop: 24, paddingTop: 16, borderTop: '1px solid #1e293b' }}>
                  <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                    <strong>Generated:</strong> {formatEasternTime(portfolioReviewData.generated_at)}
                  </span>
                  {(portfolioReviewData.tier || portfolioReviewData.provider || portfolioReviewData.model) && (
                    <span className="meta-item ai-model-badge" style={{ background: 'rgba(99, 179, 237, 0.15)', border: '1px solid rgba(99, 179, 237, 0.3)', borderRadius: 6, padding: '3px 10px', fontSize: '12px' }}>
                      🤖 <strong>{getTierName(portfolioReviewData.tier)}:</strong> {getProviderName(portfolioReviewData.provider)} ({portfolioReviewData.model || 'Default'})
                    </span>
                  )}
                </div>
              </div>
            ) : (
              <div className="empty-state" style={{ padding: 48, textAlign: 'center' }}>
                <h3>🤖 No Portfolio Review generated yet</h3>
                <p style={{ color: 'var(--text-secondary)', marginBottom: 16 }}>Click "Refresh Review" to evaluate your blended Binance + Webull portfolio allocation.</p>
                <button type="button" className="btn btn-primary" onClick={() => fetchWorkflowData('portfolio-review')}>
                  🚀 Generate Portfolio Review
                </button>
              </div>
            )}
          </section>
        )}
      </div>
      <CancelOrderModal
        isVisible={cancelModal.isVisible}
        onClose={closeCancelModal}
        onConfirm={handleCancelOrderConfirm}
        order={cancelModal.order}
        loading={cancelModal.loading}
        error={cancelModal.error}
      />

      {/* Market Analysis Prompt Modal */}
      {showMarketPromptModal && (
        <div className="modal-backdrop" onClick={() => setShowMarketPromptModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 650, width: '90%' }}>
            <div className="modal-header">
              <h3 style={{ margin: 0 }}>📝 Universal Market Analysis Prompt</h3>
            </div>
            <div className="modal-body" style={{ maxHeight: '60vh', overflowY: 'auto', padding: 20 }}>
              <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.6', color: '#cbd5e1' }}>
                {marketPrompt || '(No custom prompt configured, using system default)'}
              </pre>
            </div>
            <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', padding: '12px 20px' }}>
              <button className="btn btn-secondary" onClick={() => setShowMarketPromptModal(false)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {/* Portfolio Review Prompt Modal */}
      {showPortfolioPromptModal && (
        <div className="modal-backdrop" onClick={() => setShowPortfolioPromptModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 650, width: '90%' }}>
            <div className="modal-header">
              <h3 style={{ margin: 0 }}>📝 Universal Portfolio Review Prompt</h3>
            </div>
            <div className="modal-body" style={{ maxHeight: '60vh', overflowY: 'auto', padding: 20 }}>
              <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.6', color: '#cbd5e1' }}>
                {portfolioPrompt || '(No custom prompt configured, using system default)'}
              </pre>
            </div>
            <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', padding: '12px 20px' }}>
              <button className="btn btn-secondary" onClick={() => setShowPortfolioPromptModal(false)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
