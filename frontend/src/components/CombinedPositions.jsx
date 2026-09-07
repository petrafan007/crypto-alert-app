import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import WebullPositions from './WebullPositions';
import { normalizeRealPositions } from '../utils/positions.mjs';

export default function CombinedPositions({ user, refreshKey }) {
  const [mode, setMode] = useState('REAL');
  const [result, setResult] = useState({ rows: [], mode: null, loading: true, error: '' });
  const [refresh, setRefresh] = useState(0);
  const requestId = useRef(0);
  const admin = Boolean(user?.is_admin || user?.id === 1);
  useEffect(() => {
    if (!user?.id) return;
    const id = ++requestId.current;
    const controller = new AbortController();
    setResult({ rows: [], mode, loading: true, error: '' });
    const endpoint = mode === 'QUANT' ? '/api/webull/portfolio-algo/positions' : mode === 'TEST' ? '/api/webull/test/positions' : '/api/coin-data-live';
    axios.get(endpoint, { withCredentials: true, signal: controller.signal }).then(({ data }) => {
      if (id !== requestId.current) return;
      if (data?.success === false || !Array.isArray(mode === 'REAL' ? data?.portfolio : data?.positions)) throw new Error(data?.message || 'Positions response was unavailable.');
      setResult({ rows: mode === 'REAL' ? normalizeRealPositions(data.portfolio) : data.positions, mode, loading: false, error: '' });
    }).catch(error => {
      if (controller.signal.aborted || id !== requestId.current) return;
      setResult({ rows: [], mode, loading: false, error: error.response?.data?.message || error.message || 'Unable to load positions.' });
    });
    return () => controller.abort();
  }, [mode, user?.id, refresh, refreshKey]);
  return <section className="order-history-container">
    <div className="positions-mode-toolbar">
      <div className="positions-asset-views" role="group" aria-label="Positions trading mode">
        {[['REAL', 'Real Trading'], ['TEST', 'Webull Test Mode'], ...(admin ? [['QUANT', 'Quantitative Strategy']] : [])].map(([value, label]) => <button type="button" key={value} aria-pressed={mode === value} onClick={() => setMode(value)}>{label}</button>)}
      </div>
      <button type="button" className="btn btn-secondary" onClick={() => setRefresh(n => n + 1)} disabled={result.loading}>Refresh positions</button>
    </div>
    <p>{mode === 'REAL' ? 'Binance.US and imported Webull holdings.' : mode === 'TEST' ? 'Simulated Webull holdings in your test account.' : 'Holdings in the isolated quantitative paper account.'}</p>
    {result.error ? <div role="alert" className="modern-real-warning">{result.error} <button type="button" onClick={() => setRefresh(n => n + 1)}>Retry</button></div>
      : result.loading || result.mode !== mode ? <p role="status">Loading positions…</p>
        : <WebullPositions key={`${user?.id}:${mode}`} positions={result.rows} mode={mode} userId={user?.id} />}
  </section>;
}
