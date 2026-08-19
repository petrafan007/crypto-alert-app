import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';

const WINDOWS = [
  { label: '7 Days', hours: 24 * 7 },
  { label: '3 Days', hours: 24 * 3 },
  { label: '1 Day', hours: 24 },
  { label: '12 Hours', hours: 12 },
  { label: '1 Hour', hours: 1 },
];

const PortfolioPerformanceTable = ({ portfolio, isLightMode }) => {
  const [history, setHistory] = useState({});

  const qualifyingCoins = useMemo(() => (
    (portfolio || []).filter((coin) => (
      (coin.symbol || '').toUpperCase() !== 'USDT' &&
      Number(coin.current_value || 0) >= 1
    ))
  ), [portfolio]);

  const symbols = useMemo(() => (
    qualifyingCoins.map((coin) => (coin.symbol || '').toUpperCase()).sort().join(',')
  ), [qualifyingCoins]);

  useEffect(() => {
    let cancelled = false;

    const fetchHistory = async () => {
      if (!symbols) {
        setHistory({});
        return;
      }

      const entries = await Promise.all(qualifyingCoins.map(async (coin) => {
        const symbol = (coin.symbol || '').toUpperCase();
        try {
          const response = await axios.get(`/api/chart_history/${symbol}`);
          return [symbol, response.data?.prices || []];
        } catch (error) {
          console.error(`Failed to load performance history for ${symbol}:`, error);
          return [symbol, []];
        }
      }));

      if (!cancelled) setHistory(Object.fromEntries(entries));
    };

    fetchHistory();
    const interval = window.setInterval(fetchHistory, 60000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [symbols]);

  const getChange = (coin, hours) => {
    const symbol = (coin.symbol || '').toUpperCase();
    const points = history[symbol] || [];
    const currentPrice = Number(coin.current_price || 0);
    if (!currentPrice || points.length === 0) return null;

    const target = Date.now() - hours * 60 * 60 * 1000;
    const baseline = [...points]
      .sort((a, b) => a[0] - b[0])
      .filter((point) => Number(point[0]) <= target)
      .at(-1);
    if (!baseline || Number(baseline[1]) <= 0) return null;

    return ((currentPrice - Number(baseline[1])) / Number(baseline[1])) * 100;
  };

  const formatChange = (change) => {
    if (change === null || !Number.isFinite(change)) return <span className="performance-empty">--</span>;
    const isUp = change >= 0;
    return (
      <span className={isUp ? 'performance-up' : 'performance-down'}>
        {isUp ? '↑' : '↓'} {Math.abs(change).toFixed(2)}%
      </span>
    );
  };

  return (
    <div
      className="dashboard-performance-widget"
      style={{
        background: isLightMode ? '#fff' : '#202a30',
        border: `1px solid ${isLightMode ? '#d9e0e5' : '#344047'}`,
        borderRadius: '12px',
        boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
        padding: '16px',
        minWidth: '420px',
        flex: '1 1 620px',
        overflowX: 'auto',
      }}
    >
      <h3 style={{ margin: '0 0 4px', fontSize: '16px', color: isLightMode ? '#333' : '#fff' }}>
        Portfolio Performance
      </h3>
      <small style={{ color: isLightMode ? '#666' : '#aeb9bf' }}>
        Coins valued at $1.00 or more, excluding USDT
      </small>
      <table className="portfolio-performance-table" style={{ width: '100%', marginTop: '14px' }}>
        <thead>
          <tr>
            <th>Coin</th>
            {WINDOWS.map((window) => <th key={window.label}>{window.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {qualifyingCoins.length === 0 ? (
            <tr><td colSpan={WINDOWS.length + 1}>No qualifying portfolio coins</td></tr>
          ) : qualifyingCoins.map((coin) => (
            <tr key={coin.symbol}>
              <td><strong>{(coin.symbol || '').toUpperCase()}</strong></td>
              {WINDOWS.map((window) => (
                <td key={window.label}>{formatChange(getChange(coin, window.hours))}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default PortfolioPerformanceTable;