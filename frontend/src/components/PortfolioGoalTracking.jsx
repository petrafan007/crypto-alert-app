import React from 'react';
import { Line } from 'react-chartjs-2';
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend } from 'chart.js';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend);
const number = (value, suffix = '') => value == null || !Number.isFinite(Number(value)) ? 'Unavailable' : `${Number(value).toFixed(2)}${suffix}`;
const money = value => value == null ? 'Unavailable' : Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
const timestamp = value => value ? new Date(value).toLocaleString('en-US', { timeZone: 'America/New_York' }) + ' ET' : 'Unavailable';
const gridStyle = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, margin: '12px 0' };
const tableStyle = { width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 };

export default function PortfolioGoalTracking({ goal, showChart = true }) {
  if (!goal) return <section aria-label="Paper return goal"><h4>Paper return goal</h4><p>Goal tracking is not available in this saved report. Generate a new report to capture calculated progress; historical reports are unchanged.</p></section>;
  const coverage = goal.observations || {};
  const curve = goal.curve || [];
  return <section aria-label="Paper return goal" style={{ border: '1px solid rgba(148,163,184,.25)', borderRadius: 10, padding: 16, margin: '18px 0' }}>
    <h4 style={{ marginTop: 0 }}>PAPER · {number(goal.target_annual_return_pct, '%')} annual research goal</h4>
    <p>Run started {timestamp(goal.started_at)} · Valuation {timestamp(goal.as_of)} · {number(goal.elapsed_days)} elapsed days</p>
    <div style={gridStyle}>
      {[
        ['Observed equity', money(goal.current_equity)], ['Compounded target equity', money(goal.target_equity)],
        ['Actual minus target', `${money(goal.target_gap_usd)} (${number(goal.target_gap_pct, '%')})`],
        ['Observed total return', number(goal.total_return_pct, '%')],
        ['Annualized return (descriptive)', goal.annualized_return_pct == null ? `Awaiting ${goal.annualization_min_days || 30} elapsed days` : number(goal.annualized_return_pct, '%')],
        ['Annualized minus target', goal.cagr_gap_pct_points == null ? 'Awaiting annualization' : number(goal.cagr_gap_pct_points, ' pp')],
        ['Capital utilization (marked)', number(goal.capital_utilization_pct, '%')],
        ['Reserved capital', money(goal.reserved_capital_usd)],
      ].map(([label, value]) => <div key={label} style={{ padding: 10, background: 'rgba(148,163,184,.08)', borderRadius: 6 }}><small style={{ display: 'block' }}>{label}</small><strong>{value}</strong></div>)}
    </div>
    <p>{goal.target_note}</p>
    <p>{goal.annualization_note}</p>
    {showChart && curve.length > 1 && <div style={{ height: 230 }}><Line data={{
      datasets: [
        { label: 'Observed paper equity (connecting observed points)', data: curve.map(point => ({ x: Date.parse(point.time), y: point.equity })), borderColor: '#38bdf8', pointRadius: 0, borderWidth: 2 },
        { label: `${number(goal.target_annual_return_pct, '%')} compounded target`, data: curve.map(point => ({ x: Date.parse(point.time), y: point.target_equity })), borderColor: '#f59e0b', borderDash: [6, 4], pointRadius: 0, borderWidth: 2 },
      ],
    }} options={{ responsive: true, maintainAspectRatio: false, animation: false,
      scales: { x: { type: 'linear', ticks: { maxTicksLimit: 5, callback: value => new Date(value).toLocaleDateString() } } },
      plugins: { tooltip: { callbacks: { title: items => timestamp(items[0]?.parsed.x) } } },
    }} /></div>}
    <h5>Rolling observed returns</h5>
    <div style={{ overflowX: 'auto' }}><table style={tableStyle}><thead><tr><th>Window</th><th>Observed return</th><th>Target over same interval</th><th>Coverage / availability</th></tr></thead><tbody>
      {[30, 90, 365].map(days => {
        const item = goal.rolling_returns?.[String(days)] || {};
        return <tr key={days}><td>{days} days</td><td>{number(item.return_pct, '%')}</td><td>{number(item.target_return_pct, '%')}</td><td>{item.reason || `${number(item.actual_elapsed_days)} actual days; ${item.missing_calendar_days ?? '—'} missing snapshot days`}</td></tr>;
      })}
    </tbody></table></div>
    <p>Rolling returns use an observed valuation at or up to 24 hours before the window boundary; no price interpolation. Gaps can conceal intraperiod risk.</p>
    <details><summary>Module return contributions</summary>
      <p>{goal.contribution_basis}</p>
      <table style={tableStyle}><thead><tr><th>Module</th><th>Net P&amp;L</th><th>Portfolio return contribution</th></tr></thead><tbody>
        {(goal.module_contributions || []).map(item => <tr key={item.module}><td>{item.module}</td><td>{money(item.net_pnl)}</td><td>{number(item.contribution_pct_points, ' pp')}</td></tr>)}
        {Math.abs(goal.unattributed_pnl_usd || 0) >= 0.005 && <tr><td>Unattributed — accounting review required</td><td>{money(goal.unattributed_pnl_usd)}</td><td>—</td></tr>}
      </tbody></table>
    </details>
    <details><summary>Observation coverage: {coverage.observed_calendar_days ?? 0} / {coverage.expected_calendar_days ?? 0} UTC days · {coverage.missing_calendar_days ?? 0} missing</summary>
      <p>{coverage.snapshot_count ?? 0} snapshots. {coverage.coverage_note}</p>
      {!!coverage.invalid_snapshot_count && <p role="alert">{coverage.invalid_snapshot_count} invalid snapshots excluded.</p>}
      {(coverage.gap_ranges || []).map(item => <p key={item.start}>{item.start} through {item.end}: {item.days} missing snapshot day(s)</p>)}
    </details>
  </section>;
}
