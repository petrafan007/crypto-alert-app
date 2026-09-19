import React, { useEffect, useState } from 'react';
import axios from 'axios';

const endpoint = '/api/webull/portfolio-algo/research-data';
const date = value => value ? new Date(value).toLocaleString() : 'Not yet';
const fields = [
  ['options_seconds', 'Options interval (seconds)', 300, 3600],
  ['events_seconds', 'Events interval (seconds)', 60, 3600],
  ['crypto_seconds', 'Crypto interval (seconds)', 30, 3600],
  ['futures_seconds', 'Futures interval (seconds)', 60, 3600],
  ['options_contracts', 'Options per underlying per cycle', 80, 400],
  ['event_contracts', 'Event contracts per cycle', 1, 20],
  ['storage_mb', 'Archive capacity (MiB)', 100, 102400],
];

export default function ResearchDataCollection() {
  const [collection, setCollection] = useState(null);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [cursor, setCursor] = useState(0);
  const [exported, setExported] = useState(false);
  const load = async signal => {
    try {
      const { data } = await axios.get(endpoint, { signal, timeout: 15000 });
      setCollection(data.collection);
      setDraft(old => old || data.collection.settings);
      setError('');
    } catch (err) {
      if (!axios.isCancel(err)) setError(err.response?.data?.message || err.message);
    }
  };
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    const timer = setInterval(() => load(controller.signal), 30000);
    return () => { clearInterval(timer); controller.abort(); };
  }, []);
  const save = async changes => {
    setBusy(true); setError('');
    try {
      const { data } = await axios.post(endpoint, changes, { timeout: 15000 });
      setCollection(data.collection); setDraft(data.collection.settings);
    } catch (err) {
      setError(err.response?.data?.message || err.message);
    } finally { setBusy(false); }
  };
  const download = async () => {
    setBusy(true); setError('');
    try {
      const { data } = await axios.get(`${endpoint}/export`, { params: { after: cursor, limit: 100 }, timeout: 30000 });
      const url = URL.createObjectURL(new Blob([JSON.stringify(data)], { type: 'application/json' }));
      const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `research_archive_after_${cursor}.json`; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setCursor(data.last_id); setExported(data.next_cursor === null);
    } catch (err) { setError(err.response?.data?.message || err.message); }
    finally { setBusy(false); }
  };
  return <section className="quant-validation" aria-label="Market research data collection">
    <h3>Market research data archive</h3>
    <p>Collect options quotes, IV and Greeks through existing Webull access; Event books and trades where available; public Binance.US books, trades and candles. Saved engine watchlists select the instruments. Collection runs independently of paper trading and AI.</p>
    <p>No subscription is purchased or activated. Unavailable access is reported and retried with a cooldown. Future paid sources can remain separate in the archive. New collection cannot recover past options quotes or order books.</p>
    {error && <p role="alert">{error}</p>}
    {collection && <>
      <p><strong>{collection.enabled ? 'Collection enabled' : 'Collection paused'}</strong> · {(collection.stored_bytes / 1048576).toFixed(2)} / {collection.settings.storage_mb} MiB stored. Capacity includes archived payloads, metadata, normalized datasets and research results; database overhead is additional. At capacity, new writes pause and history is retained.</p>
      <button type="button" disabled={busy} onClick={() => save({ enabled: !collection.enabled })}>{collection.enabled ? 'Pause collection' : 'Start collection'}</button>
      <details><summary>Collection settings</summary>
        <form onSubmit={event => { event.preventDefault(); save(Object.fromEntries(fields.map(([key]) => [key, Number(draft[key])]))); }}>
          <div className="quant-performance-grid">{fields.map(([key, label, min, max]) => <label key={key}>{label}<input aria-label={label} type="number" min={min} max={max} step="1" required value={draft?.[key] ?? ''} onChange={event => setDraft({ ...draft, [key]: event.target.value })} /></label>)}</div>
          <button disabled={busy} type="submit">Save collection settings</button>
        </form>
      </details>
      {['options', 'events', 'crypto', 'futures'].map(lane => {
        const row = collection.lanes.find(item => item.lane === lane);
        return <div key={lane}>
          <h4>{lane.charAt(0).toUpperCase() + lane.slice(1)} · {collection.enabled ? row?.status || 'Waiting for worker' : 'Paused'}</h4>
          <p>{row?.batches || 0} archived batches · Latest capture: {date(row?.latest_at)} · Worker heartbeat: {date(row?.heartbeat_at)}</p>
          {row?.details?.waiting && <p>{row.details.waiting}</p>}
          {row?.details?.message && <p>{row.details.message}</p>}
          {Object.entries(row?.details?.cooldowns || {}).map(([kind, reason]) => <p key={kind}>{kind}: {reason.status.replaceAll('_', ' ')} · Retry after {date(reason.retry_at * 1000)}</p>)}
          <details><summary>Last cycle coverage and diagnostics</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(row?.details || {}, null, 2)}</pre></details>
        </div>;
      })}
      <p>Polling records samples, not a complete tick feed or guaranteed execution. Original provider timestamps and retrieval times are retained separately. Use the collected-data workbench below to normalize observations, preview daily IV and run portfolio replay.</p>
      <button type="button" disabled={busy} onClick={download}>{exported ? 'Download newer batches' : cursor ? 'Download next archive page' : 'Download first archive page'}</button>
      {cursor > 0 && <button type="button" disabled={busy} onClick={() => { setCursor(0); setExported(false); }}>Restart export</button>}
      <p>Each download contains up to 100 batches / 8 MiB of uncompressed payloads. Keep every page for a full export.</p>
    </>}
  </section>;
}
