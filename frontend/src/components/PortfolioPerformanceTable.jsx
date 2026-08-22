import React, { useEffect, useState } from 'react';
import axios from 'axios';
import CryptoIcon from './CryptoIcon';

const WINDOW_KEYS = [
  { label: '7D', key: 'change_7d' },
  { label: '3D', key: 'change_3d' },
  { label: '1D', key: 'change_1d' },
  { label: '12H', key: 'change_12h' },
  { label: '1H', key: 'change_1h' },
];

const GenericCoinIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0, display: 'inline-block', verticalAlign: 'middle' }}>
    <circle cx="12" cy="12" r="10" fill="url(#coin_gold_grad)" stroke="#EAB308" strokeWidth="1.5" />
    <path d="M12 6v12M9 8.5h4.5a2 2 0 0 1 0 4H9h5a2 2 0 0 1 0 4H9" stroke="#FFF" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    <defs>
      <linearGradient id="coin_gold_grad" x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
        <stop stopColor="#F59E0B" />
        <stop offset="1" stopColor="#D97706" />
      </linearGradient>
    </defs>
  </svg>
);

const PortfolioPerformanceTable = ({ hiddenCoins = [] }) => {
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

  const visibleData = performanceData.filter(
    (item) => !hiddenCoins.includes(item.symbol)
  );

  return (
    <div className="dashboard-performance-widget widget-panel-inner">
      <div className="performance-widget-header" style={{ marginBottom: '12px' }}>
        <h3 className="chart-title" style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: 0 }}>
          <GenericCoinIcon size={20} />
          <span>Coin Performance</span>
        </h3>
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
            ) : visibleData.length === 0 ? (
              <tr>
                <td className="performance-message" colSpan={WINDOW_KEYS.length + 1}>
                  {performanceData.length > 0 ? 'All coins hidden in filter' : 'No qualifying coins'}
                </td>
              </tr>
            ) : (
              visibleData.map((item) => (
                <tr key={item.symbol}>
                  <td className="performance-symbol">
                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
                      <CryptoIcon symbol={item.symbol} size={18} />
                      <span style={{ fontWeight: '600' }}>{item.symbol}</span>
                    </div>
                  </td>
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
