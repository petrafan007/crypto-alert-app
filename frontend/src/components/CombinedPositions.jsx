import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import WebullPositions from './WebullPositions';
import { useGlobalMode } from './GlobalModeContext';
import { toWebullTradingMode } from '../utils/globalMode.mjs';
import { normalizeRealPositions } from '../utils/positions.mjs';

export default function CombinedPositions({ user, refreshKey }) {
  const { globalMode } = useGlobalMode();
  const mode = toWebullTradingMode(globalMode); // 'REAL' | 'TEST' | 'QUANT'
  const [result, setResult] = useState({ rows: [], mode: null, loading: true, error: '' });
  const [refresh, setRefresh] = useState(0);
  const requestId = useRef(0);

  useEffect(() => {
    if (!user?.id) return;
    const id = ++requestId.current;
    const controller = new AbortController();
    setResult({ rows: [], mode, loading: true, error: '' });
    const endpoint = mode === 'QUANT'
      ? '/api/webull/portfolio-algo/positions'
      : mode === 'TEST'
        ? '/api/dashboard/paper-portfolio'
        : '/api/coin-data-live';
    axios.get(endpoint, { withCredentials: true, signal: controller.signal }).then(({ data }) => {
      if (id !== requestId.current) return;
      if (mode === 'QUANT') {
        if (data?.success === false || !Array.isArray(data?.positions)) {
          throw new Error(data?.message || 'Positions response was unavailable.');
        }
        setResult({ rows: data.positions, mode, loading: false, error: '' });
      } else {
        if (data?.success === false || !Array.isArray(data?.portfolio)) {
          throw new Error(data?.message || 'Positions response was unavailable.');
        }
        setResult({ rows: normalizeRealPositions(data.portfolio), mode, loading: false, error: '' });
      }
    }).catch(error => {
      if (controller.signal.aborted || id !== requestId.current) return;
      setResult({ rows: [], mode, loading: false, error: error.response?.data?.message || error.message || 'Unable to load positions.' });
    });
    return () => controller.abort();
  }, [mode, user?.id, refresh, refreshKey]);

  return (
    <section className="order-history-container">
      <div className="positions-mode-toolbar">
        <p style={{ margin: 0 }}>
          {mode === 'REAL'
            ? 'Binance.US and imported Webull holdings.'
            : mode === 'TEST'
              ? 'Simulated Paper Trading holdings across Webull Test and Binance.US Paper.'
              : 'Read-only holdings in the isolated Quantitative Strategy Engine account.'}
        </p>
        <button type="button" className="btn btn-secondary" onClick={() => setRefresh(n => n + 1)} disabled={result.loading}>
          Refresh positions
        </button>
      </div>
      {result.error ? (
        <div role="alert" className="modern-real-warning">
          {result.error} <button type="button" onClick={() => setRefresh(n => n + 1)}>Retry</button>
        </div>
      ) : result.loading || result.mode !== mode ? (
        <p role="status">Loading positions…</p>
      ) : (
        <WebullPositions key={`${user?.id}:${mode}`} positions={result.rows} mode={mode} userId={user?.id} />
      )}
    </section>
  );
}
