import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { moduleStatusLabel } from '../utils/portfolioModules.mjs';
import { Line } from 'react-chartjs-2';
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend } from 'chart.js';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend);
const money = (n) => Number(n ?? 0).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
const metric = (n, suffix = '') => n == null ? 'Awaiting history' : `${Number(n).toFixed(2)}${suffix}`;
const date = (s) => s ? new Date(s).toLocaleString('en-US', { timeZone: 'America/New_York' }) + ' ET' : 'Not yet';

export default function QuantitativeTelemetry({ onAccount }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = async (signal) => {
    try {
      const { data } = await axios.get('/api/webull/portfolio-algo/status', { signal });
      setStatus(data);
      onAccount(data.account);
      setError('');
    } catch (err) {
      if (!axios.isCancel(err)) setError(err.response?.data?.message || 'Telemetry could not be refreshed.');
    }
  };
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    const timer = setInterval(() => load(controller.signal), 15000);
    return () => { clearInterval(timer); controller.abort(); };
  }, [onAccount]);
  const control = async (action) => {
    setBusy(true);
    try {
      await axios.post('/api/webull/portfolio-algo/control', { action });
      await load();
    } catch (err) {
      setError(err.response?.data?.message || 'Worker control failed.');
    } finally { setBusy(false); }
  };
  const curve = status?.equity_curve || [];
  const performance = status?.performance || {};
  return <section className="quant-master-ribbon quant-telemetry" aria-label="Paper execution and performance">
    <h3>Paper execution &amp; performance</h3>
    <div className="quant-ribbon-actions">
      <strong role="status">{status?.worker_status || 'Loading…'}</strong>
      <button className="btn-quant-save" disabled={busy || !status || status.enabled || status.kill_switch} onClick={() => control('start')}>Start paper engine</button>
      <button className="btn-quant-save" disabled={busy || !status?.enabled} onClick={() => control('stop')}>Stop &amp; freeze</button>
      <button className="btn-quant-save" disabled={busy || !status?.enabled} onClick={() => control('scan')}>Scan now</button>
      <button className="btn-quant-reset-bankroll" disabled={busy || !status} onClick={() => control('kill')}>Kill switch</button>
      {status?.kill_switch && <button className="btn-quant-save" disabled={busy} onClick={() => control('acknowledge')}>Acknowledge pause</button>}
    </div>
    <p>Saved settings govern execution. Five-minute scans · Heartbeat: {date(status?.heartbeat_at)} · Paper run {status?.generation || '—'}</p>
    {error && <p role="alert">{error}</p>}
    {status?.pause_reason && <p className="quant-risk-notice" role="alert">{status.pause_reason}</p>}
    {status?.modules?.error && <p role="alert">{status.modules.error}</p>}
    <div className="quant-performance-grid">
      {[
        ['Cash available', money(status?.account?.cash_balance)], ['Realized P&L', money(status?.account?.realized_pnl)],
        ['Unrealized P&L', money(status?.account?.unrealized_pnl)], ['Annualized return', metric(performance.annualized_return_pct, '%')],
        ['Sharpe', metric(performance.sharpe)], ['Sortino', metric(performance.sortino)],
        ['Win rate', metric(performance.win_rate_pct, '%')], ['Maximum drawdown', metric(performance.max_drawdown_pct, '%')],
      ].map(([label, value]) => <div key={label}><small>{label}</small><strong>{value}</strong></div>)}
    </div>
    <p>Returns include simulated fees and slippage. Annualization needs 30 elapsed days; ratios need 30 daily returns. Return targets are research objectives.</p>
    {curve.length > 1 ? <div className="quant-equity-chart"><Line data={{
      labels: curve.map(p => date(p.time)), datasets: [{ label: 'Paper equity', data: curve.map(p => p.equity), borderColor: '#38bdf8', pointRadius: 0, borderWidth: 2 },
        { label: 'Cash', data: curve.map(p => p.cash), borderColor: '#a78bfa', pointRadius: 0, borderWidth: 1 }],
    }} options={{ responsive: true, maintainAspectRatio: false, animation: false, scales: { x: { ticks: { maxTicksLimit: 6 } } } }} /></div> : <p>The equity curve begins when the paper engine starts.</p>}
    <h4>Module health</h4>
    <div className="quant-module-health">{['equities', 'options', 'crypto', 'futures', 'events'].map(module => <details key={module}>
      <summary>{module.toUpperCase()} · {moduleStatusLabel(status?.modules?.[module]?.status)}</summary>
      <p>{status?.modules?.[module]?.evaluated || 0} symbols evaluated · {status?.modules?.[module]?.entries || 0} new paper entries</p>
      {(status?.modules?.[module]?.messages || []).map((message, index) => <p key={index}>{message}</p>)}
      {!status?.modules?.[module]?.messages?.length && <p>{status?.modules?.[module]?.status === 'DISABLED' ? 'New entries are disabled. Saved watchlists and history are retained; existing positions are managed while the engine runs.' : 'Readiness reflects the last scan. Ready does not guarantee an entry or future data access.'}</p>}
    </details>)}</div>
    <h4>Open positions</h4>
    <div className="quant-table-scroll"><table><thead><tr><th>Module / symbol</th><th>Side</th><th>Quantity</th><th>Entry / mark</th><th>Reserved capital</th><th>Unrealized P&amp;L</th><th>Stop / target</th><th>Marked</th></tr></thead>
      <tbody>{(status?.positions || []).map(p => <tr key={p.id}>
        <td>{p.module}<br /><strong>{p.symbol}</strong>{p.details?.outcome && ` (${p.details.outcome})`}{p.details?.expiration && <small> Exp. {p.details.expiration} · {p.details.short?.strike}/{p.details.long?.strike} {p.details.short?.option_type}</small>}</td>
        <td>{p.side}</td><td>{p.quantity}</td><td>{money(p.average_cost)} / {money(p.mark)}</td><td>{money(p.collateral)}</td><td>{money(p.unrealized_pnl)}</td>
        <td>{p.stop == null ? '—' : money(p.stop)} / {p.target == null ? '—' : money(p.target)}</td><td>{date(p.marked_at)}</td>
      </tr>)}{!status?.positions?.length && <tr><td colSpan="8">No open paper positions in this run.</td></tr>}</tbody></table></div>
    <h4>Capital allocation &amp; rebalancing</h4>
    <p>Disabled modules reserve unused allocation as cash. Reallocate explicitly to change the weights. Exposure above target by more than 3 percentage points is trimmed on a fresh quote. Underweight capital remains available for qualified entries.</p>
    <div className="quant-table-scroll"><table><thead><tr><th>Module</th><th>Target</th><th>Deployed capital</th><th>Drift</th><th>Available</th><th>Signal</th></tr></thead><tbody>
      {(status?.rebalance || []).map(r => <tr key={r.module}><td>{r.module}</td><td>{metric(r.target_pct, '%')}</td><td>{metric(r.actual_pct, '%')}</td><td>{metric(r.drift_pct, ' pp')}</td><td>{money(r.available_capital)}</td><td>{r.signal.replaceAll('_', ' ')}</td></tr>)}
    </tbody></table></div>
  </section>;
}
