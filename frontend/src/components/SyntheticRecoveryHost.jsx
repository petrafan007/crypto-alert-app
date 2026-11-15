import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { number, orderKey } from '../utils/syntheticOrders.mjs';
import TotpCodeInput from './TotpCodeInput';
import './SyntheticOrders.css';

export const openSyntheticRecovery = order => window.dispatchEvent(new CustomEvent('app:synthetic-recovery', { detail: order }));
const initialLegs = order => {
  if (order.conditional_spec) return order.conditional_phase === 'EXIT' ? order.conditional_spec.legs.slice(1) : order.conditional_spec.legs;
  const price = Number(order.last_price || order.upside_target_price || order.current_stop_price || 1);
  return [
    { side: order.side, order_type: 'LIMIT', price: order.side === 'BUY' ? (order.downside_target_price || price * 0.98) : (order.upside_target_price || price * 1.02) },
    { side: order.side, order_type: 'STOP_LOSS', stop_price: order.side === 'BUY' ? (order.upside_target_price || price * 1.02) : (order.downside_target_price || price * 0.98) },
  ];
};

export default function SyntheticRecoveryHost({ userId }) {
  const [order, setOrder] = useState(null), [step, setStep] = useState('choose');
  const [type, setType] = useState('SAME'), [session, setSession] = useState('ALL');
  const [cap, setCap] = useState('1'), [legs, setLegs] = useState([]), [code, setCode] = useState('');
  const [trail, setTrail] = useState('2'), [rungs, setRungs] = useState([{ target_price: '', pct_of_total: 50 }, { target_price: '', pct_of_total: 50 }]);
  const [edits, setEdits] = useState({}), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const seen = useRef(new Set()), initialized = useRef(false), dialog = useRef(null);
  useEffect(() => {
    seen.current = new Set(); initialized.current = false;
    let stopped = false, running = false;
    const poll = async () => {
      if (running) return;
      running = true;
      try {
        const results = await Promise.all(['ladder', 'trailing'].map(name => axios.get(`/api/trading/${name}-orders`, { withCredentials: true })));
        if (stopped) return;
        const failures = results.flatMap((r, i) => (r.data[`${i ? 'trailing' : 'ladder'}_orders`] || []).map(o => ({ ...o, parentKind: i ? 'TRAILING' : 'LADDER' }))).filter(o => o.recovery_available);
        failures.forEach(o => {
          const key = orderKey(o), storageKey = `synthetic-failure:${userId}:${key}`;
          let previous = false;
          try { previous = localStorage.getItem(storageKey) === 'seen'; } catch { /* Storage can be unavailable. */ }
          if (initialized.current && !seen.current.has(key) && !previous) {
            window.dispatchEvent(new CustomEvent('app:new-toast', { detail: {
              id: `synthetic-${key}`, category: 'warning', symbol: o.symbol,
              message: `${o.status_label}. ${o.monitoring_error || o.error_message || 'Execution stopped.'} Click to review your choices. This is also saved in Order History.`,
              onClick: () => openSyntheticRecovery(o),
            } }));
          }
          seen.current.add(key);
          try { localStorage.setItem(storageKey, 'seen'); } catch { /* Optional deduplication. */ }
        });
        initialized.current = true;
      } catch { /* Order history remains the durable recovery path; retry polling. */ }
      finally { running = false; }
    };
    poll(); const timer = setInterval(poll, 5000);
    return () => { stopped = true; clearInterval(timer); };
  }, [userId]);
  useEffect(() => {
    const open = async event => {
      const candidate = event.detail;
      setError(''); setStep('choose'); setCode(''); setType('SAME'); setBusy(true); setOrder(candidate);
      try {
        const resource = candidate.parentKind === 'TRAILING' ? 'trailing' : 'ladder';
        const result = await axios.get(`/api/trading/${resource}-orders`, { withCredentials: true });
        const fresh = (result.data[`${resource}_orders`] || []).find(o => o.id === candidate.id);
        if (!fresh) throw new Error('Strategy no longer available. Refresh Order History.');
        setOrder({ ...fresh, parentKind: candidate.parentKind });
        setLegs(initialLegs(fresh)); setSession(fresh.trading_session || 'CORE'); setCap(String(fresh.limit_cap_pct || 1));
        setEdits(Object.fromEntries(['upside_target_price', 'downside_target_price', 'upside_trail_value', 'downside_trail_value', 'trail_value'].filter(k => fresh[k] != null).map(k => [k, fresh[k]])));
      } catch (err) { setError(err.response?.data?.error || err.message); }
      finally { setBusy(false); }
    };
    window.addEventListener('app:synthetic-recovery', open);
    return () => window.removeEventListener('app:synthetic-recovery', open);
  }, []);
  useEffect(() => {
    if (!order) return;
    const previous = document.activeElement;
    dialog.current?.focus();
    const keyboard = event => {
      if (event.key === 'Escape' && !busy) setOrder(null);
      if (event.key !== 'Tab') return;
      const nodes = dialog.current?.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), [href]');
      if (!nodes?.length) return;
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', keyboard);
    return () => { document.removeEventListener('keydown', keyboard); previous?.focus?.(); };
  }, [Boolean(order), busy]);
  if (!order) return null;
  const changeType = next => {
    setType(next);
    if (next === 'SAME') return;
    const base = Number(order.last_price || order.upside_target_price || order.current_stop_price || 1);
    const entry = { side: order.side, order_type: 'LIMIT', price: base };
    const opposite = order.side === 'BUY' ? 'SELL' : 'BUY';
    const exits = [{ side: opposite, order_type: 'LIMIT', price: base * (opposite === 'SELL' ? 1.02 : 0.98) }, { side: opposite, order_type: 'STOP_LOSS', stop_price: base * (opposite === 'SELL' ? 0.98 : 1.02) }];
    setLegs(next === 'OCO' ? initialLegs({ ...order, conditional_spec: null }) : next === 'OTO' ? [entry, exits[0]] : next === 'OTOCO' ? [entry, ...exits] : next === 'STOP' ? [{ ...entry, order_type: 'STOP_LOSS', stop_price: base }] : [entry]);
  };
  const submit = async action => {
    setBusy(true); setError('');
    try {
      const result = await axios.post(`/api/trading/synthetic-orders/${order.parentKind}/${order.id}/recover`, {
        action, two_factor_code: code, strategy_type: type,
        trading_session: session, limit_cap_pct: Number(cap), legs, edits, trail_value: Number(trail), rungs,
      }, { withCredentials: true });
      if (!result.data.success) throw new Error(result.data.error);
      window.dispatchEvent(new CustomEvent('app:new-toast', { detail: { category: 'success', message: result.data.replacement_id ? `Replacement strategy #${result.data.replacement_id} created for the unfilled remainder.` : 'The remaining strategy stays cancelled.' } }));
      window.dispatchEvent(new Event('app:synthetic-updated'));
      setOrder(null);
    } catch (err) { setError(err.response?.data?.error || err.message); }
    finally { setBusy(false); }
  };
  return <div className="synthetic-recovery-backdrop"><div ref={dialog} tabIndex={-1} className="synthetic-recovery-modal" role="dialog" aria-modal="true" aria-labelledby="synthetic-recovery-title">
    <button className="synthetic-recovery-close" aria-label="Close recovery" disabled={busy} onClick={() => setOrder(null)}>×</button>
    <h2 id="synthetic-recovery-title">{step === 'replace' ? 'Replace / Retry' : 'Review synthetic order'}</h2>
    <p><strong>{order.symbol} · {order.side} · {order.test_mode ? 'Paper' : 'Live'} · {order.account_id}</strong></p>
    <p>{order.status_label || order.status}: {order.monitoring_error || order.error_message}</p>
    <p>Confirmed filled: <strong>{number(order.filled_quantity || 0)}</strong> · Unfilled remainder: <strong>{number(order.remaining_quantity)}</strong>. Filled trades cannot be undone here.</p>
    {error && <p role="alert" className="synthetic-warning">{error}</p>}
    {!order.recovery_available ? <p>{order.recovery_action ? `Recovery decision already saved: ${order.recovery_action.replaceAll('_', ' ')}${order.replacement_id ? ` · replacement #${order.replacement_id}` : ''}.` : 'Recovery is unavailable until the broker confirms a final failed execution with an unfilled remainder.'}</p> : step === 'choose' ? <div className="synthetic-recovery-choices">
      <button disabled={busy} onClick={() => setStep('replace')}>A. Replace / Retry</button>
      <button disabled={busy} onClick={() => setStep('regular')}>B. Use Regular Hours</button>
      <button disabled={busy} onClick={() => submit('KEEP_CANCELLED')}>C. Keep Cancelled</button>
    </div> : <>
      {step === 'replace' && <>
        <label>Order type<select aria-label="Order type" value={type} onChange={e => changeType(e.target.value)}><option value="SAME">Current strategy</option>{order.broker === 'webull' && order.instrument_type !== 'CRYPTO' && ['OCO', 'OTO', 'OTOCO', 'LIMIT', 'STOP', 'TRAILING', 'LADDER'].map(t => <option key={t}>{t}</option>)}</select></label>
        <label>Trading session<select aria-label="Trading session" value={session} onChange={e => setSession(e.target.value)}><option value="CORE">Regular Hours</option>{order.broker === 'webull' && order.instrument_type !== 'CRYPTO' && <option value="ALL">Regular + Extended Hours</option>}</select></label>
        {session === 'ALL' && <label>Extended-hours price cap (%)<input type="number" min="0.1" max="5" step="0.1" value={cap} onChange={e => setCap(e.target.value)} /></label>}
        {type === 'TRAILING' ? <label>Trailing distance (%)<input type="number" min="0.01" max="99" step="any" value={trail} onChange={e => setTrail(e.target.value)} /></label> : type === 'LADDER' ? <><p>Set upside targets above the current price. Allocations must total 100%; extended-hours steps must allocate whole shares.</p>{rungs.map((r,i) => <fieldset key={i}><legend>Step {i + 1}</legend><label>Target price<input type="number" min="0.0001" step="any" value={r.target_price} onChange={e => setRungs(prev => prev.map((x,j) => j === i ? { ...x, target_price: e.target.value } : x))} /></label><label>Allocation (%)<input type="number" min="0.01" max="100" step="any" value={r.pct_of_total} onChange={e => setRungs(prev => prev.map((x,j) => j === i ? { ...x, pct_of_total: e.target.value } : x))} /></label></fieldset>)}</> : type === 'SAME' ? order.conditional_spec ? <p>Uses the existing leg prices shown below. Choose OCO, OTO, OTOCO, Limit or Stop above to edit the legs.</p> : Object.entries(edits).map(([key, value]) => <label key={key}>{key.replaceAll('_', ' ')}<input type="number" min="0.0001" step="any" value={value} onChange={e => setEdits(prev => ({ ...prev, [key]: e.target.value }))} /></label>) : legs.map((leg, i) => <fieldset key={i}><legend>Leg {i + 1} · {leg.side}</legend>
          <label>Type<select value={leg.order_type} onChange={e => setLegs(prev => prev.map((l, j) => j === i ? { ...l, order_type: e.target.value } : l))}>{['LIMIT', 'STOP_LOSS', 'STOP_LOSS_LIMIT'].map(t => <option key={t}>{t}</option>)}</select></label>
          {(leg.order_type === 'LIMIT' || leg.order_type === 'STOP_LOSS_LIMIT') && <label>Limit price<input required type="number" min="0.0001" step="any" value={leg.price || ''} onChange={e => setLegs(prev => prev.map((l,j) => j === i ? { ...l, price: e.target.value } : l))} /></label>}
          {leg.order_type !== 'LIMIT' && <label>Stop price<input required type="number" min="0.0001" step="any" value={leg.stop_price || ''} onChange={e => setLegs(prev => prev.map((l,j) => j === i ? { ...l, stop_price: e.target.value } : l))} /></label>}
        </fieldset>)}
      </>}
      {order.conditional_spec && type === 'SAME' && <ul>{initialLegs(order).map((leg,i) => <li key={i}>{leg.side} {leg.order_type} · limit {leg.price || '—'} · stop {leg.stop_price || '—'}</li>)}</ul>}
      <p>{step === 'regular' ? 'Creates a new strategy for the unfilled remainder during regular market hours (9:30 AM–4:00 PM ET on trading days).' : 'Creates a new strategy for the unfilled remainder in the selected session.'} Conditions already met may trigger as soon as monitoring resumes. The old attempt stays in history.</p>
      <p>Plain stops and legacy strategies send Market orders in regular hours and capped Limit orders in extended hours. Entered Limit and Stop Limit prices are preserved. Unfilled live limit children time out after 5 minutes; a fill is never guaranteed. OTO exits activate only after the entry settles, sized to confirmed fills. A partially filled entry may leave a position awaiting confirmation before exits activate.</p>
      {type === 'SAME' && !order.conditional_spec && <p>Existing ladder allocation percentages and trailing watermarks are retained over the remaining quantity.</p>}
      {!order.test_mode && <label>Authenticator code<TotpCodeInput value={code} onChange={e => setCode(e.target.value)} /></label>}
      <div className="synthetic-actions"><button disabled={busy} onClick={() => setStep('choose')}>Back</button><button disabled={busy || (!order.test_mode && code.length !== 6)} onClick={() => submit(step === 'regular' ? 'REGULAR' : 'REPLACE')}>{busy ? 'Saving…' : 'Confirm and submit'}</button></div>
    </>}
    <p className="synthetic-muted">Closing this dialog leaves the stopped strategy unchanged.</p>
  </div></div>;
}
