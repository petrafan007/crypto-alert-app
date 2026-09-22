import React, { useEffect, useRef, useState } from 'react';
import { money } from '../utils/syntheticOrders.mjs';
import './PaperDepositModal.css';
import { showAppConfirm } from './AppDialog';

export default function PaperDepositModal({ visible, broker, balances = {}, currencies = ['USD'], initialCurrency = 'USD', submitting, error, onClose, onDeposit, onReset }) {
  const [amount, setAmount] = useState('1000');
  const [currency, setCurrency] = useState(initialCurrency);
  const input = useRef(null);
  const modal = useRef(null);
  useEffect(() => {
    if (!visible) return;
    const previous = document.activeElement;
    setAmount('1000'); setCurrency(currencies.includes(initialCurrency) ? initialCurrency : currencies[0]); input.current?.focus();
    return () => previous?.focus?.();
  }, [visible]);
  if (!visible) return null;
  const valid = Number.isFinite(Number(amount)) && Number(amount) > 0 && Number(amount) <= 1e9 && /^\d+(\.\d{1,2})?$/.test(amount);
  return <div className="paper-deposit-backdrop" onKeyDown={e => {
    if (e.key === 'Escape' && !submitting) onClose();
    if (e.key === 'Tab') {
      const nodes = [...modal.current.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled)')];
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    }
  }}>
    <section ref={modal} className="paper-deposit-modal" role="dialog" aria-modal="true" aria-labelledby="paper-deposit-title">
      <h3 id="paper-deposit-title">💰 Deposit Fake Money</h3>
      <p>Add simulated funds to your {broker} Paper Trading account to practice using live market prices.</p>
      {currencies.length > 1 && <label>Paper currency<select aria-label="Paper currency" value={currency} disabled={submitting} onChange={e => setCurrency(e.target.value)}>{currencies.map(c => <option key={c}>{c}</option>)}</select></label>}
      <div className="paper-cash-balance"><span>Current Paper Cash Available</span><strong>{money(balances[currency] ?? 0, currency)}</strong></div>
      <label>Quick Deposit Presets:</label>
      <div className="paper-deposit-presets">{[1000, 5000, 10000].map(value => <button key={value} type="button" disabled={submitting} onClick={() => setAmount(String(value))}>+{money(value, currency)}</button>)}</div>
      <form onSubmit={e => { e.preventDefault(); if (valid && !submitting) onDeposit(Number(amount), currency); }}>
        <label htmlFor="paper-deposit-amount">Or Custom Deposit Amount ({currency}):</label>
        <input id="paper-deposit-amount" ref={input} type="number" min="0.01" max="1000000000" step="0.01" value={amount} disabled={submitting} onChange={e => setAmount(e.target.value)} />
        {error && <p className="paper-deposit-error" role="alert">{error}</p>}
        <div className="paper-deposit-actions">
          <button type="button" className="paper-reset" disabled={submitting} onClick={async () => {
            const confirmed = await showAppConfirm(`Reset the ${broker} paper account to zero, clear simulated holdings, and cancel active paper orders? Live balances are unaffected.`, { title: `Reset ${broker} Paper Account`, confirmLabel: 'Reset Account', cancelLabel: 'Keep Account', tone: 'danger' });
            if (confirmed) onReset();
          }}>🔄 Reset Account</button>
          <button type="button" disabled={submitting} onClick={onClose}>Cancel</button>
          <button type="submit" className="paper-confirm" disabled={!valid || submitting}>{submitting ? 'Processing…' : 'Confirm Deposit'}</button>
        </div>
      </form>
    </section>
  </div>;
}
