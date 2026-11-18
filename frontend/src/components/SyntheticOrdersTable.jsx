import { openSyntheticRecovery } from './SyntheticRecoveryHost';
import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import CancelOrderModal from './CancelOrderModal';
import { orderKey, strategyKind, number, money, timestamp, trailLabel, matchesStatus, quoteCurrency } from '../utils/syntheticOrders.mjs';
import './SyntheticOrders.css';

const labels = { BRACKET: 'Smart bracket', LADDER: 'Ladder', TRAILING: 'Trailing stop', SINGLE: 'Single target' };
const sideLabel = (order, prefix) => prefix === 'upside' ? (order.side === 'BUY' ? 'Breakout' : 'Take profit') : (order.side === 'BUY' ? 'Buy the Dip' : 'Downside protection');
const budgetOf = order => Number(order.quote_budget) > 0 ? Number(order.quote_budget) : null;

// One section per side of a ladder or bracket, each with its own numbered steps.
function StepSections({ order, currency }) {
  const budget = budgetOf(order);
  return <div className="synthetic-step-sections">{['upside', 'downside'].map(prefix => {
    const mode = order[`${prefix}_mode`] || (prefix === 'upside' ? 'LADDER' : 'NONE');
    if (mode === 'NONE') return null;
    const rungs = (order.rungs || []).filter(r => (r.rung_type || 'TAKE_PROFIT') === (prefix === 'upside' ? 'TAKE_PROFIT' : 'STOP_LOSS'));
    const summary = mode === 'TRAILING' ? `Trailing ${trailLabel(order[`${prefix}_trail_value`], order[`${prefix}_trail_type`], currency)} · stop ${money(order[`${prefix}_current_stop_price`], currency)}`
      : mode === 'SINGLE' ? `Single trigger ${prefix === 'upside' ? '≥' : '≤'} ${money(order[`${prefix}_target_price`] ?? order.stop_loss_trigger_price, currency)}` : `${rungs.length} steps`;
    return <section key={prefix} className={`synthetic-step-section synthetic-step-section-${prefix}`}>
      <h4>{sideLabel(order, prefix)} <small>{summary}</small></h4>
      {mode === 'LADDER' && <div className="synthetic-step-grid">{rungs.map((rung, index) => <div key={rung.id || rung.rung_number} className="synthetic-step">
        <strong>Step {index + 1} · {rung.status.replaceAll('_', ' ')}</strong>
        <small>Trigger: {money(rung.target_price, currency)} ({Number(rung.price_offset_pct).toFixed(2)}%)</small>
        {budget
          ? <><small>Budget share: {money(budget * rung.percentage_of_total / 100, currency)} ({Number(rung.percentage_of_total).toFixed(2)}%)</small><small>Buys: {number(rung.quantity)} {order.symbol?.replace(/(USDT|USDC|USD)$/, '')}</small></>
          : <><small>Allocation: {number(rung.quantity)} ({Number(rung.percentage_of_total).toFixed(2)}%)</small><small>Estimated value: {money(rung.estimated_usd, currency)}</small></>}
        {rung.error_message && <small className="synthetic-warning">{rung.error_message}</small>}
      </div>)}</div>}
    </section>;
  })}</div>;
}
const canCancel = status => ['ACTIVE', 'PARTIALLY_FILLED', 'SUBMITTED', 'TRIGGERED', 'FAILED', 'NEEDS_REVIEW'].includes(status);
function Strategy({ order }) {
  const currency = quoteCurrency(order);
  if (order.parentKind === 'TRAILING') return <div>
    <strong>Trail {trailLabel(order.trail_value, order.trail_type, currency)}</strong>
    <small>{order.is_activated ? 'Activated' : 'Waiting for activation'}{order.activation_price ? ` · ${money(order.activation_price, currency)}` : ''}</small>
    <small>Stop: {money(order.current_stop_price, currency)}</small>
    <small>{order.side === 'BUY' ? 'Trough' : 'Peak'}: {money(order.side === 'BUY' ? order.lowest_price : order.highest_price, currency)}</small>
  </div>;
  return <div className="synthetic-strategy">
    {['upside', 'downside'].map(prefix => {
      const mode = order[`${prefix}_mode`] || (prefix === 'upside' ? 'LADDER' : 'NONE');
      const kind = prefix === 'upside' ? 'TAKE_PROFIT' : 'STOP_LOSS';
      const rungs = (order.rungs || []).filter(r => (r.rung_type || 'TAKE_PROFIT') === kind);
      const watermark = prefix === 'upside' ? order.upside_highest_price : order.downside_lowest_price;
      const activation = order[`${prefix}_activation_price`];
      const active = !activation || (order.side === 'SELL' ? watermark >= activation : watermark <= activation);
      return <div key={prefix}>
        <strong>{prefix === 'upside' ? (order.side === 'BUY' ? 'Breakout entry' : 'Profit target') : (order.side === 'BUY' ? 'Buy the dip' : 'Downside protection')}: </strong>
        {mode === 'NONE' ? 'Off' : mode === 'SINGLE' ? money(order[`${prefix}_target_price`], currency) : mode === 'LADDER' ? `${rungs.length} steps` : `Trail ${trailLabel(order[`${prefix}_trail_value`], order[`${prefix}_trail_type`], currency)}`}
        {mode === 'TRAILING' && <><small>{active ? 'Activated' : 'Waiting for activation'}{activation ? ` · ${money(activation, currency)}` : ''}</small>
          <small>Stop: {money(order[`${prefix}_current_stop_price`], currency)} · {order.side === 'BUY' ? 'Trough' : 'Peak'}: {money(watermark, currency)}</small></>}
        {prefix === 'downside' && mode === 'SINGLE' && <small>{order.stop_loss_action === 'CANCEL_REMAINING' ? 'Cancel remaining strategy only' : `${order.trading_session === 'ALL' ? 'Market in regular hours; capped Limit in extended hours:' : 'Market:'} ${order.side.toLowerCase()} remaining quantity`}</small>}
      </div>;
    })}
  </div>;
}

export default function SyntheticOrdersTable({ defaultBroker = 'all', showBrokerFilter = true, accountId, testMode, onOrderCancelled, historyMode = false }) {
  const [orders, setOrders] = useState([]);
  const [broker, setBroker] = useState(defaultBroker);
  const [status, setStatus] = useState(historyMode ? 'ALL' : 'ACTIVE');
  const [kind, setKind] = useState('ALL');
  const [mode, setMode] = useState('all');
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState(new Set());
  const [busy, setBusy] = useState(null);
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState([]);
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [updated, setUpdated] = useState(null);
  const [cancelTarget, setCancelTarget] = useState(null);
  const [cancelError, setCancelError] = useState('');
  useEffect(() => { const changed = () => setRefresh(v => v + 1); window.addEventListener('app:synthetic-updated', changed); return () => window.removeEventListener('app:synthetic-updated', changed); }, []);
  useEffect(() => setBroker(defaultBroker), [defaultBroker]);
  useEffect(() => {
    let stopped = false, running = false;
    const controller = new AbortController();
    setOrders([]); setUpdated(null); setLoading(true); setErrors([]);
    const load = async () => {
      if (running || stopped) return;
      running = true;
      const params = {};
      if (broker !== 'all') params.broker = broker;
      if (accountId) params.account_id = accountId;
      if (typeof testMode === 'boolean') params.test_mode = testMode;
      const resources = ['ladder', 'trailing'];
      const results = await Promise.allSettled(resources.map(name => axios.get(`/api/trading/${name}-orders`, { params, withCredentials: true, signal: controller.signal })));
      if (stopped) return;
      const failures = [], successful = [];
      results.forEach((result, index) => {
        const resource = resources[index], parentKind = resource.toUpperCase();
        if (result.status !== 'fulfilled' || !result.value.data?.success) {
          failures.push(`${resource === 'ladder' ? 'Bracket/ladder' : 'Trailing'} orders could not be refreshed. Previously loaded rows may be stale.`);
          return;
        }
        successful.push(parentKind);
      });
      setOrders(previous => {
        const merged = previous.filter(o => !successful.includes(o.parentKind));
        results.forEach((result, index) => {
          const parentKind = resources[index].toUpperCase();
          if (!successful.includes(parentKind)) return;
          (result.value.data[`${resources[index]}_orders`] || []).forEach(o => merged.push({ ...o, parentKind, total_quantity: o.total_quantity ?? o.quantity }));
        });
        return merged.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
      });
      setErrors(failures); setLoading(false); running = false;
      if (!failures.length) setUpdated(new Date().toLocaleTimeString());
    };
    load();
    const timer = setInterval(() => { if (!document.hidden) load(); }, 5000);
    return () => { stopped = true; controller.abort(); clearInterval(timer); };
  }, [broker, accountId, testMode, refresh]);
  const filtered = useMemo(() => orders.filter(o => (!historyMode || !['ACTIVE', 'PARTIALLY_FILLED'].includes(o.status)) && matchesStatus(o, status)
    && (kind === 'ALL' || strategyKind(o) === kind)
    && (mode === 'all' || Boolean(o.test_mode) === (mode === 'paper'))
    && `${o.symbol} ${o.account_id || ''} ${o.instrument_type}`.toLowerCase().includes(search.toLowerCase())), [orders, status, kind, mode, search]);
  const cancel = async (order, twoFactorCode) => {
    setBusy(orderKey(order)); setNotice('');
    try {
      const result = await axios.post(`/api/trading/${order.parentKind === 'LADDER' ? 'ladder' : 'trailing'}-orders/${order.id}/cancel`, { two_factor_code: twoFactorCode }, { withCredentials: true });
      if (!result.data?.success) throw new Error(result.data?.error || 'Cancellation failed.');
      const saved = result.data.ladder_order || result.data.trailing_order;
      setNotice(saved?.status === 'CANCEL_PENDING' ? 'Cancellation requested; awaiting the broker’s final execution state.' : 'Remaining strategy cancelled.');
      setOrders(prev => prev.map(o => orderKey(o) === orderKey(order) ? { ...o, ...saved } : o));
      setCancelTarget(null); setCancelError('');
      onOrderCancelled?.(order.id);
    } catch (error) { setCancelError(error.response?.data?.error || error.message || 'Cancellation failed.'); }
    finally { setBusy(null); }
  };
  return <><div className="synthetic-orders">
    <div className="synthetic-filters">
      {showBrokerFilter && <label>Broker<select aria-label="Broker" value={broker} onChange={e => setBroker(e.target.value)}><option value="all">All brokers</option><option value="binance">Binance.US</option><option value="webull">Webull</option></select></label>}
      <label>Strategy<select aria-label="Strategy" value={kind} onChange={e => setKind(e.target.value)}><option value="ALL">All strategies</option>{Object.entries(labels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label>Status<select aria-label="Status" value={status} onChange={e => setStatus(e.target.value)}>{['ALL', 'ACTIVE', 'COMPLETED', 'CANCELLED', 'FAILED', 'NEEDS_REVIEW'].map(s => <option key={s} value={s}>{s.replaceAll('_', ' ')}</option>)}</select></label>
      {typeof testMode !== 'boolean' && <label>Mode<select aria-label="Mode" value={mode} onChange={e => setMode(e.target.value)}><option value="all">Live and paper</option><option value="live">Live</option><option value="paper">Paper</option></select></label>}
      <label>Search<input aria-label="Search synthetic orders" type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Symbol, asset class or account" /></label>
      <button type="button" onClick={() => setRefresh(v => v + 1)} disabled={loading}>Refresh</button>
    </div>
    <p className="synthetic-muted">Refreshes every 5 seconds{updated ? ` · Last complete refresh ${updated}` : ''}. Triggers are monitored by the server; fills require broker confirmation.</p>
    {errors.map(error => <p key={error} role="alert" className="synthetic-warning">{error}</p>)}
    {notice && <p role="status" className="synthetic-notice">{notice}</p>}
    {loading && !orders.length ? <p role="status">Loading synthetic orders…</p> : !filtered.length ? <p className="synthetic-empty">{errors.length ? 'Order data is unavailable. Retry refresh.' : 'No synthetic orders match these filters.'}</p> :
      <div className="synthetic-scroll"><table><caption className="synthetic-sr-only">Synthetic order strategies and confirmed executions</caption><thead><tr>
        {['Order / account', 'Asset / quantity', 'Strategy and trigger', 'Execution progress', 'Status / monitoring', 'Actions'].map(label => <th key={label} scope="col">{label}</th>)}
      </tr></thead><tbody>{filtered.map(order => {
        const key = orderKey(order), open = expanded.has(key), currency = quoteCurrency(order), verified = order.execution_history_verified !== false;
        const progress = order.total_quantity > 0 ? Math.min(100, 100 * (order.filled_quantity || 0) / order.total_quantity) : 0;
        return <React.Fragment key={key}><tr>
          <td><strong>#{order.id} · {order.conditional_spec ? order.strategy_type : labels[strategyKind(order)]}</strong><small>{order.broker === 'webull' ? 'Webull' : 'Binance.US'} · {order.test_mode ? 'Paper' : 'Live'}{order.environment && order.environment !== 'production' ? ` · ${order.environment}` : ''}</small>
            <small>Account: {order.account_id || 'Binance.US spot'}</small><small>Created: {timestamp(order.created_at)}</small></td>
          <td><strong>{order.symbol}</strong><small>{order.instrument_type} · <span className={`synthetic-side-${order.side.toLowerCase()}`}>{order.side}</span></small><small>{budgetOf(order) ? `Budget: ${money(budgetOf(order), currency)}` : `Total: ${number(order.total_quantity)}`}</small><small>{order.instrument_type === 'CRYPTO' ? '24/7 monitoring' : order.trading_session === 'ALL' ? 'Regular + Extended Hours (4 AM–8 PM ET, trading days)' : 'Regular Hours (9:30 AM–4 PM ET, trading days)'}</small></td>
          <td>{order.conditional_spec ? <><strong>Synthetic {order.strategy_type} · {order.conditional_phase}</strong>{order.conditional_spec.legs.map((leg, i) => <small key={i}>{leg.side} {leg.order_type} · limit {leg.price || '—'} · stop {leg.stop_price || '—'}</small>)}{order.conditional_spec.entry_remainder_cancelled > 0 && <small className="synthetic-warning">Entry partially filled: {number(order.conditional_spec.entry_filled_quantity)}; {number(order.conditional_spec.entry_remainder_cancelled)} cancelled. Exits sized to confirmed entry fills.</small>}</> : <Strategy order={order} />}</td>
          <td>{verified ? budgetOf(order) ? <><strong>{money(budgetOf(order) - (order.budget_remaining ?? budgetOf(order)), currency)} / {money(budgetOf(order), currency)} used</strong><progress max="100" value={Math.min(100, order.budget_used_pct || 0)} aria-label={`Order ${order.id} budget used`} />
            <small>Unused: {money(order.budget_remaining ?? budgetOf(order), currency)}</small><small>Bought: {number(order.filled_quantity || 0)}</small><small>Awaiting broker: {number(order.pending_quantity || 0)}</small>
            {order.rungs?.length > 0 && <small>{order.rungs_filled || 0} of {order.rungs.length} steps filled</small>}</> : <><strong>{number(order.filled_quantity || 0)} / {number(order.total_quantity)} filled</strong><progress max="100" value={progress} aria-label={`Order ${order.id} quantity filled`} />
            <small>Remaining: {number(order.remaining_quantity ?? order.total_quantity)}</small><small>Awaiting broker: {number(order.pending_quantity || 0)}</small>
            {order.rungs?.length > 0 && <small>{order.rungs_filled || 0} of {order.rungs.length} steps filled</small>}</> : <small className="synthetic-warning">Legacy execution totals are unverified. Review broker history before replacing this strategy.</small>}</td>
          <td><button type="button" className={`synthetic-status state-${order.status.toLowerCase()}`} onClick={() => openSyntheticRecovery(order)}>{order.status_label || order.status.replaceAll('_', ' ')}</button><small>Last price: {money(order.last_price, currency)}</small><small>Checked: {timestamp(order.last_checked_at)}</small>
            {(order.monitoring_error || order.error_message) && <small className="synthetic-warning">{order.monitoring_error || order.error_message}</small>}</td>
          <td><div className="synthetic-actions">{order.recovery_available && <button type="button" onClick={() => openSyntheticRecovery(order)}>Review issue</button>}<button type="button" aria-expanded={open} onClick={() => setExpanded(prev => { const next = new Set(prev); next.has(key) ? next.delete(key) : next.add(key); return next; })}>{open ? 'Hide details' : 'Details'}</button>
            {canCancel(order.status) && <button type="button" className="synthetic-cancel" disabled={busy === key} onClick={() => { setCancelTarget(order); setCancelError(''); }}>{busy === key ? 'Cancelling…' : 'Cancel'}</button>}</div></td>
        </tr>{open && <tr><td colSpan="6" className="synthetic-detail">
          <p>Updated: {timestamp(order.updated_at)} · {budgetOf(order) ? `Both sides share one ${money(budgetOf(order), currency)} budget; each side spends at most it at its trigger prices.` : 'Both sides share the total quantity.'} Failed strategies and strategies needing review are paused.</p>
          {!order.conditional_spec && <StepSections order={order} currency={currency} />}
          <strong>{order.test_mode ? 'Paper executions' : 'Broker executions'}</strong>{!order.executions?.length ? <p>No executions recorded{!verified ? ' by the new engine. Review older fills in broker order history.' : '.'}</p> :
            <div className="synthetic-step-grid">{order.executions.map(fill => <div className="synthetic-step" key={fill.id}>
              <strong>{fill.leg.replaceAll('_', ' ')} · {fill.status.replaceAll('_', ' ')}</strong><small>Requested: {number(fill.quantity)} · Filled: {number(fill.filled_quantity)} · Average fill: {money(fill.filled_price, currency)}</small>
              <small>Broker ID: {fill.broker_order_id || 'Awaiting acknowledgement'}</small><small>Client ID: {fill.client_order_id}</small><small>Updated: {timestamp(fill.updated_at)}</small>
              {fill.error_message && <small className="synthetic-warning">{fill.error_message}</small>}
            </div>)}</div>}
        </td></tr>}</React.Fragment>;
      })}</tbody></table></div>}
  </div><CancelOrderModal
    isVisible={Boolean(cancelTarget)}
    onClose={() => { if (!busy) { setCancelTarget(null); setCancelError(''); } }}
    onConfirm={(code) => cancel(cancelTarget, code)}
    order={cancelTarget ? {
      ...cancelTarget,
      is_synthetic_strategy: true,
      cancel_provider: cancelTarget.broker === 'webull' ? 'Webull' : 'Binance.US',
      cancel_account_label: cancelTarget.account_id || (cancelTarget.broker === 'webull' ? 'Webull account' : 'Binance.US spot'),
    } : null}
    loading={Boolean(cancelTarget && busy === orderKey(cancelTarget))}
    error={cancelError}
    requiresTwoFactor={!cancelTarget?.test_mode}
  /></>;
}
