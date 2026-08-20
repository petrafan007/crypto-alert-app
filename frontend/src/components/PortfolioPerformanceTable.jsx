import React, { useEffect, useState } from 'react';
import axios from 'axios';

const WINDOW_KEYS = [
  { label: '7D', key: 'change_7d' },
  { label: '3D', key: 'change_3d' },
  { label: '1D', key: 'change_1d' },
  { label: '12H', key: 'change_12h' },
  { label: '1H', key: 'change_1h' },
];

const PortfolioPerformanceTable = () => {
  const [performanceData, setPerformanceData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    const fetchPerformance = async () => {
      try {
        const response = await axios.get('/api/coin-performance', { withCredentials: true });
        if (!response.data?.success || !Array.isArray(response.data.performance)) {
          throw new Error('Invalid coin performance response');
        }
        if (!cancelled) {
          setPerformanceData(response.data.performance);
          setError('');
        }
      } catch (fetchError) {
        console.error('Failed to load coin performance:', fetchError);
        if (!cancelled) setError('Performance data unavailable');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchPerformance();
    const interval = window.setInterval(fetchPerformance, 60000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  const formatChange = (change) => {
    const numericChange = Number(change);
    if (change === null || change === undefined || !Number.isFinite(numericChange)) {
      return <span className="performance-empty">--</span>;
    }
    const isUp = numericChange >= 0;
    return (
      <span className={isUp ? 'performance-up' : 'performance-down'}>
        {isUp ? '↑' : '↓'} {Math.abs(numericChange).toFixed(2)}%
      </span>
    );
  };

  return (
    <div className="dashboard-performance-widget">
      <div className="performance-widget-header">
        <h3>
          <span>📊</span>
          <span>Coin Performance</span>
        </h3>
        <small>Holdings worth at least $1, excluding stablecoins</small>
      </div>

      <div className="performance-table-scroll" aria-live="polite">
        <table className="portfolio-performance-table">
          <thead>
            <tr>
              <th>Coin</th>
              {WINDOW_KEYS.map((w) => (
                <th key={w.label}>{w.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && performanceData.length === 0 ? (
              <tr>
                <td className="performance-message" colSpan={WINDOW_KEYS.length + 1}>
                  Loading performance...
                </td>
              </tr>
            ) : error && performanceData.length === 0 ? (
              <tr>
                <td className="performance-message performance-error" colSpan={WINDOW_KEYS.length + 1}>
                  {error}
                </td>
              </tr>
            ) : performanceData.length === 0 ? (
              <tr>
                <td className="performance-message" colSpan={WINDOW_KEYS.length + 1}>
                  No qualifying coins
                </td>
              </tr>
            ) : (
              performanceData.map((item) => (
                <tr key={item.symbol}>
                  <td className="performance-symbol">{item.symbol}</td>
                  {WINDOW_KEYS.map((w) => (
                    <td key={w.label}>
                      {formatChange(item[w.key])}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default PortfolioPerformanceTable;
