import React, { useEffect, useState } from 'react';
import axios from 'axios';
const base = '/api/webull/portfolio-algo/research';
const local = value => { const d = new Date(value); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
const metric = value => value == null ? 'Unavailable' : Number(value).toFixed(2);
function download(data, name) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data)], { type: 'application/json' }));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = name; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function ResearchWorkbench() {
  const [state, setState] = useState({ datasets: [], jobs: [] });
  const [selected, setSelected] = useState('');
  const [start, setStart] = useState(local(Date.now() - 3600000));
  const [end, setEnd] = useState(local(Date.now()));
  const [split, setSplit] = useState(local(Date.now() - 1800000));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [job, setJob] = useState(null);
  const [upload, setUpload] = useState(null);
  const [preview, setPreview] = useState(null);
  const load = async signal => {
    try { const { data } = await axios.get(base, { signal, timeout: 15000 }); setState(data); }
    catch (err) { if (!axios.isCancel(err)) setError(err.response?.data?.message || err.message); }
  };
  useEffect(() => {
    const controller = new AbortController(); load(controller.signal);
    const timer = setInterval(() => load(controller.signal), 5000);
    return () => { controller.abort(); clearInterval(timer); };
  }, []);
  const action = async work => {
    setBusy(true); setError('');
    try { await work(); await load(); }
    catch (err) { setError(err.response?.data?.message || err.message); }
    finally { setBusy(false); }
  };
  const queue = kind => action(async () => {
    const request = kind === 'build' ? { start: new Date(start).toISOString(), end: new Date(end).toISOString() } : {
      dataset_id: Number(selected), sha256: state.datasets.find(d => d.id === Number(selected))?.sha256,
      start: new Date(start).toISOString(), split: new Date(split).toISOString(), end: new Date(end).toISOString(),
    };
    const { data } = await axios.post(`${base}/jobs`, { kind, request }, { timeout: 15000 }); setJob(data.job);
  });
  const inspect = id => action(async () => { const { data } = await axios.get(`${base}/jobs/${id}`, { timeout: 30000 }); setJob(data.job); });
  const select = value => {
    setSelected(value); setJob(null);
    const dataset = state.datasets.find(d => d.id === Number(value));
    if (dataset) {
      const first = new Date(dataset.quality.first_available_at).getTime(); const last = new Date(dataset.quality.last_available_at).getTime();
      setStart(local(first)); setEnd(local(last + 60000)); setSplit(local((first + last) / 2));
    }
  };
  const readFile = event => action(async () => {
    setPreview(null); setUpload(null);
    const file = event.target.files?.[0]; if (!file) return;
    if (file.size > 5 * 1048576) throw new Error('Dataset uploads are limited to 5 MiB.');
    const dataset = JSON.parse(await file.text());
    const { data } = await axios.post(`${base}/import`, { dataset }, { timeout: 30000 });
    setUpload(dataset); setPreview(data.preview);
  });
  const result = job?.result;
  return <section aria-label="Portfolio research workbench" style={{ marginTop: 24 }}>
    <h3>Collected-data research workbench</h3>
    <p>Build a usable dataset directly from your archive, preview consistent daily IV, and replay the portfolio with shared cash and saved risk rules. Jobs run in the background; results and failures remain available after closing this page.</p>
    {error && <p role="alert">{error}</p>}
    <div className="quant-performance-grid">
      <label>Start (your local time)<input type="datetime-local" value={start} onChange={e => setStart(e.target.value)} /></label>
      <label>Chronological split<input type="datetime-local" value={split} onChange={e => setSplit(e.target.value)} /></label>
      <label>End (your local time)<input type="datetime-local" value={end} onChange={e => setEnd(e.target.value)} /></label>
    </div>
    <button disabled={busy || !start || !end} type="button" onClick={() => queue('build')}>Build dataset from collected data</button>
    <p>Builds verify archive checksums, preserve when data became available, and remove identical observations. Backfilled candles remain unavailable before their actual collection time. Oversized selections fail with a smaller-window instruction; they are not silently truncated.</p>
    <label>Saved dataset <select value={selected} onChange={e => select(e.target.value)}>
      <option value="">Select a dataset</option>{state.datasets.map(d => <option key={d.id} value={d.id}>Dataset {d.id} · {d.quality.accepted} observations · {new Date(d.created_at).toLocaleString()}</option>)}
    </select></label>
    {selected && <>
      <p>Coverage: {Object.entries(state.datasets.find(d => d.id === Number(selected))?.quality.counts || {}).map(([key, count]) => `${key}: ${count}`).join(' · ')}</p>
      <p>Independent Event-book pairs within five seconds: {state.datasets.find(d => d.id === Number(selected))?.quality.independent_books?.paired_books ?? 0}. Comparisons and missing timestamp/depth counts are included in the dataset download; receipt timing does not establish exchange latency.</p>
      <button type="button" disabled={busy} onClick={() => queue('iv_preview')}>Preview daily IV history</button>
      <button type="button" disabled={busy || !split} onClick={() => queue('replay')}>Run shared-capital portfolio replay</button>
      <button type="button" disabled={busy} onClick={() => action(async () => { const { data } = await axios.get(`${base}/datasets/${selected}`, { timeout: 30000 }); download(data, `research-dataset-${selected}.json`); })}>Download normalized dataset</button>
    </>}
    <details><summary>Import additional historical data</summary>
      <p>Optional provider data uses the same version 2 observation format. No purchase is required or made. Preview validates timestamps, units, prices and provenance before saving an immutable dataset. Imported data remains source-labeled research evidence; it cannot overwrite live Webull history.</p>
      <input type="file" accept="application/json,.json" onChange={readFile} disabled={busy} aria-label="Historical provider dataset" />
      {preview && <><p>{preview.quality.accepted} accepted observations; {preview.quality.duplicates_removed} duplicates removed. Source identity is declared, not independently certified.</p><button type="button" disabled={busy} onClick={() => action(async () => {
        const { data } = await axios.post(`${base}/import`, { dataset: upload, commit: true, sha256: preview.sha256 }, { timeout: 30000 });
        setPreview(null); setSelected(String(data.preview.dataset_id));
      })}>Save previewed dataset</button></>}
      <button type="button" onClick={() => download({ schema_version: 2, source: 'Describe provider, permissions, IV units and adjustment conventions', records: [] }, 'research-import-template.json')}>Download import template</button>
      <p>Records require kind, module, symbol, source, currency, event_at and available_at. Use explicit UTC offsets. Download a normalized dataset to inspect source adapters; the documentation defines quote, candle, contract, catalog, forecast, outcome and IV fields.</p>
    </details>
    <h4>Research jobs</h4>
    {state.jobs.length === 0 && <p>No jobs submitted yet.</p>}
    {state.jobs.map(row => <p key={row.id}>#{row.id} · {row.kind.replaceAll('_', ' ')} · {row.status} · {new Date(row.created_at).toLocaleString()} <button type="button" disabled={busy} onClick={() => inspect(row.id)}>View result</button>{row.status === 'FAILED' && <> — {row.message}</>}</p>)}
    {job && <div aria-live="polite"><h4>Job #{job.id}: {job.status}</h4><p>{job.message}</p>
      {['QUEUED', 'RUNNING'].includes(job.status) && <p>Use View result when the job list reports completion. Replay has a four-minute computation limit; interrupted jobs become visible failures.</p>}
      {result?.quality && <p>Dataset {result.dataset_id} saved with {result.quality.accepted} observations. Select it above to continue.</p>}
      {result?.methodology && <>
        <p>{result.sessions} compatible close-window observations · {result.status}. Existing history is preserved.</p>
        {Object.entries(result.exclusions || {}).map(([reason, count]) => <p key={reason}>{reason}: {count}</p>)}
        {job.kind === 'iv_preview' && result.sessions > 0 && Number(selected) === result.dataset_id && <button type="button" disabled={busy} onClick={() => queue('iv_apply')}>Append compatible self-collected IV days</button>}
        {result.inserted != null && <p>Inserted: {result.inserted}; already present: {result.already_present}; conflicting existing values retained: {result.conflicting_existing_retained}.</p>}
      </>}
      {result?.scope === 'shared_capital_portfolio_replay' && <>
        <p>Computation is separate from validation: inspect each module's coverage. Missing inputs can yield no trades and a flat cash balance; neither demonstrates a working or profitable strategy.</p>
        {Object.entries(result.windows).map(([name, window]) => <div key={name}><h4>{name.replace('_', ' ')} · {window.steps} observed steps</h4>
          <div className="quant-table-scroll"><table><thead><tr><th>Scenario</th><th>Coverage</th><th>Net return</th><th>Drawdown</th><th>Entries / open</th></tr></thead><tbody>{window.scenarios.map(s => <tr key={s.scenario}><td>{s.scenario.replaceAll('_', ' ')}</td><td>{s.status}</td><td>{metric(s.period_return_pct)}%</td><td>{metric(s.max_drawdown_pct)}%</td><td>{s.entries} / {s.open_positions}</td></tr>)}</tbody></table></div>
          <details><summary>Per-module coverage and exclusions</summary>{window.scenarios.map(s => <div key={s.scenario}><h5>{s.scenario}</h5>{Object.entries(s.coverage).map(([module, status]) => <p key={module}>{module}: {status} {Object.entries(s.module_errors[module] || {}).map(([reason, count]) => `${reason} (${count})`).join('; ')}</p>)}</div>)}</details>
        </div>)}
        <details><summary>Execution assumptions</summary>{result.assumptions.map(text => <p key={text}>{text}</p>)}</details>
      </>}
      {result && <button type="button" onClick={() => download(result, `research-job-${job.id}.json`)}>Download full evidence and results</button>}
    </div>}
  </section>;
}
