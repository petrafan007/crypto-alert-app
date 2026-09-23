import React, { useEffect, useState } from 'react';
import axios from 'axios';

const pct = value => value == null ? '—' : `${(value * 100).toFixed(1)}%`;
export default function JevTelemetry({ useCase, refreshKey = 0 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    const load = () => axios.get('/api/jev/telemetry', { params: useCase ? { use_case: useCase } : {}, signal: controller.signal })
      .then(({ data }) => { setData(data); setError(''); })
      .catch(err => { if (!axios.isCancel(err)) setError('Jev activity could not be loaded.'); });
    load();
    const timer = setInterval(load, 30000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [useCase, refreshKey]);
  return <div aria-label="Jev research activity">
    {error && <p role="alert">{error}</p>}
    {data && <>
      <p>Last 30 days · {data.sample_count} observations (up to {data.sample_limit}) · {data.pending_count} pending</p>
      <p>Latency p50 / p95: {data.p50_ms ?? '—'} / {data.p95_ms ?? '—'} ms · Fallback: {pct(data.fallback_rate)} · Errors: {pct(data.error_rate)}</p>
      <p>Reported cost: {data.reported_cost_usd == null ? 'Unavailable' : `$${data.reported_cost_usd.toFixed(6)}`} ({data.cost_reported_count} evaluations with cost)</p>
      {data.last_success && <p>Last success: {new Date(data.last_success).toLocaleString()}</p>}
      {data.last_safe_error && <p>Last error: {data.last_safe_error}</p>}
      <details><summary>Recent evaluations and calibration</summary>
        {!data.recent.length && <p>No evaluations yet. Enable shadow mode in AI Providers &amp; Models to begin collecting observations.</p>}
        <div style={{ overflowX: 'auto' }}><table className="table">
          <thead><tr><th>Asset / time</th><th>Result</th><th>Answers</th><th>Action</th><th>Future return</th></tr></thead>
          <tbody>{data.recent.map(row => <tr key={row.id}>
            <td>{row.symbol} · {row.market_source}<br />{new Date(row.decision_time).toLocaleString()}</td>
            <td>{row.status}<br />{row.result_state || row.error_message_safe}<br />{row.latency_ms ?? '—'} ms</td>
            <td>{Object.entries(row.answers).map(([key, answer]) => <div key={key}>{key.replaceAll('_', ' ')}: {answer.type === 'boolean' ? pct(answer.probability) : answer.type === 'score' ? `${(answer.score + 1).toFixed(1)}/5` : answer.choice}</div>)}</td>
            <td>{row.action_taken}<br />{row.baseline?.baseline_action ? `Baseline: ${row.baseline.baseline_action}` : ''}</td>
            <td>{row.outcome_return_pct == null ? 'Unscored' : `${row.outcome_return_pct.toFixed(2)}%`}</td>
          </tr>)}</tbody>
        </table></div>
        {Object.entries(data.calibration).map(([cohort, group]) => <div key={cohort}>
          <strong>{cohort}</strong> · {group.sample_count} graded observations
          {Object.entries(group.questions).map(([question, values]) => <p key={question}>{question}: Brier {values.brier.toFixed(4)} ({values.count} observations)</p>)}
        </div>)}
        {!Object.keys(data.calibration).length && <p>Calibration awaits outcomes at the configured forecast horizons.</p>}
        <p>{data.limitations}</p>
      </details>
    </>}
  </div>;
}
