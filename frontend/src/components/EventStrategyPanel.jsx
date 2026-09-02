import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import './EventStrategyPanel.css';

const DURATIONS = [
  ['FIFTEEN_MINUTES', '15-minute'],
  ['HOURLY', 'Hourly'],
  ['DAILY', 'Daily'],
];

const formatPercent = (value) => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : '—';

export default function EventStrategyPanel({ isPaperMode }) {
  const [status, setStatus] = useState(null);
  const [config, setConfig] = useState(null);
  const [decisions, setDecisions] = useState([]);
  const [symbols, setSymbols] = useState('BTC, ETH');
  const [durations, setDurations] = useState(['FIFTEEN_MINUTES', 'HOURLY']);
  const [minEdge, setMinEdge] = useState('0.03');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const load = async () => {
    try {
      const [statusResponse, decisionsResponse] = await Promise.all([
        axios.get('/api/webull/event-algo/status'),
        axios.get('/api/webull/event-algo/decisions?limit=8'),
      ]);
      const nextConfig = statusResponse.data?.config;
      setStatus(statusResponse.data);
      setConfig(nextConfig);
      if (nextConfig) {
        setSymbols((nextConfig.symbols || []).join(', '));
        setDurations(nextConfig.durations || []);
        setMinEdge(String(nextConfig.signal_config?.min_net_edge ?? 0.03));
      }
      setDecisions(decisionsResponse.data?.decisions || []);
    } catch (error) {
      setMessage(error.response?.data?.message || 'Event strategy status is unavailable.');
    }
  };

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 30000);
    return () => window.clearInterval(timer);
  }, []);

  const request = async (path, body = {}) => {
    setBusy(true);
    setMessage('');
    try {
      const response = await axios.post(path, body);
      setMessage(response.data?.message || 'Updated.');
      await load();
    } catch (error) {
      setMessage(error.response?.data?.message || 'The Event strategy request failed.');
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    setMessage('');
    try {
      await axios.put('/api/webull/event-algo/config', {
        symbols: symbols.split(',').map((value) => value.trim()).filter(Boolean),
        durations,
        signal_config: { min_net_edge: Number(minEdge) },
      });
      setMessage('Paper research settings saved.');
      await load();
    } catch (error) {
      setMessage(error.response?.data?.message || 'Unable to save paper research settings.');
    } finally {
      setBusy(false);
    }
  };

  const lastRun = status?.last_run;
  const running = config?.enabled && !config?.kill_switch;
  const recentNoTrade = useMemo(() => decisions.filter((item) => !item.eligible).length, [decisions]);

  return (
    <section className="event-strategy-panel" aria-label="Webull Event Contract algorithmic paper strategy">
      <div className="event-strategy-panel-header">
        <div>
          <h3>📊 Event Contract Strategy Engine</h3>
          <p>Forward-paper research for Webull Bitcoin and Ethereum predictions.</p>
        </div>
        <span className="event-strategy-mode-badge">PAPER · SIGNALS ONLY</span>
      </div>

      {!isPaperMode && (
        <div className="event-strategy-warning" role="alert">Enable Webull paper/test mode before starting the strategy engine.</div>
      )}
      <div className="event-strategy-safety-note">v2.77 never submits live orders or changes your Webull account. Every scan records data and a decision trace for later validation.</div>

      <div className="event-strategy-stat-grid">
        <div><span>Worker</span><strong>{running ? (config.worker_status || 'RUNNING') : (config?.worker_status || 'STOPPED')}</strong></div>
        <div><span>Last scan</span><strong>{lastRun?.finished_at ? new Date(lastRun.finished_at).toLocaleString() : 'Not run yet'}</strong></div>
        <div><span>Scanned</span><strong>{lastRun?.scanned_count ?? 0}</strong></div>
        <div><span>NO_TRADE decisions</span><strong>{lastRun?.no_trade_count ?? recentNoTrade}</strong></div>
      </div>

      <div className="event-strategy-controls">
        <label>Symbols<input value={symbols} onChange={(event) => setSymbols(event.target.value)} disabled={!isPaperMode || busy} aria-label="Event strategy symbols" /></label>
        <label>Minimum net edge<input value={minEdge} onChange={(event) => setMinEdge(event.target.value)} disabled={!isPaperMode || busy} inputMode="decimal" aria-label="Minimum net edge" /></label>
        <div className="event-strategy-duration-list" role="group" aria-label="Event strategy durations">
          <span>Durations</span>
          {DURATIONS.map(([value, label]) => (
            <label key={value}><input type="checkbox" checked={durations.includes(value)} onChange={() => setDurations((previous) => previous.includes(value) ? previous.filter((item) => item !== value) : [...previous, value])} disabled={!isPaperMode || busy} />{label}</label>
          ))}
        </div>
      </div>

      <div className="event-strategy-actions">
        <button type="button" onClick={save} disabled={!isPaperMode || busy}>Save research settings</button>
        <button type="button" onClick={() => request('/api/webull/event-algo/scan', { refresh: true })} disabled={!isPaperMode || busy}>Scan now</button>
        <button type="button" onClick={() => request('/api/webull/event-algo/start')} disabled={!isPaperMode || busy || config?.kill_switch}>Start paper worker</button>
        <button type="button" onClick={() => request('/api/webull/event-algo/stop')} disabled={busy}>Stop</button>
        <button type="button" className="danger" onClick={() => request('/api/webull/event-algo/kill-switch')} disabled={busy}>Kill switch</button>
      </div>

      {config?.kill_switch && <div className="event-strategy-warning" role="alert">Kill switch active. New strategy entries are disabled until the configuration is reviewed.</div>}
      {message && <p className="event-strategy-message" role="status">{message}</p>}

      <div className="event-strategy-decisions">
        <div className="event-strategy-decisions-heading"><strong>Recent decision trace</strong><span>{decisions.length} recorded</span></div>
        {!decisions.length ? <p>No paper decisions recorded yet. Scan the configured markets to begin collecting evidence.</p> : decisions.slice(0, 5).map((decision) => (
          <div className="event-strategy-decision" key={decision.id}>
            <strong>{decision.contract_symbol}</strong>
            <span className={decision.eligible ? 'qualified' : 'no-trade'}>{decision.action}</span>
            <span>Edge {formatPercent(decision.net_edge)} · Confidence {formatPercent(decision.confidence)}</span>
            <small>{(decision.reason_codes || []).join(', ') || 'Qualified paper signal'}</small>
          </div>
        ))}
      </div>
    </section>
  );
}
