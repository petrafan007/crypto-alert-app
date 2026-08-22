import React, { useState, useEffect } from 'react';
import axios from 'axios';
import CryptoIcon from './CryptoIcon';

const TopMoversWidget = ({ isLightMode }) => {
  const [movers, setMovers] = useState({ gainers: [], losers: [] });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetchMovers = async () => {
      try {
        const res = await axios.get('/api/coin-performance', { withCredentials: true });
        const perf = Array.isArray(res.data?.performance) ? res.data.performance : [];

        const validCoins = perf
          .filter(c => c && c.symbol && !['USD', 'USDT', 'USDC', 'USDG', 'DAI'].includes(c.symbol.toUpperCase()))
          .map(c => {
            const rawChange = c.change_1d !== undefined && c.change_1d !== null
              ? c.change_1d
              : (c.change_7d || c.change_3d || 0);
            return {
              symbol: c.symbol.toUpperCase(),
              price: Number(c.price || 0),
              change: Number(rawChange)
            };
          });

        if (validCoins.length > 0) {
          // Sort by change descending
          const sorted = [...validCoins].sort((a, b) => b.change - a.change);
          const positive = sorted.filter(c => c.change > 0);
          const negative = sorted.filter(c => c.change < 0);

          let gainers = [];
          let losers = [];

          if (positive.length > 0) {
            gainers = positive.slice(0, 3);
          } else {
            gainers = sorted.slice(0, Math.min(3, Math.ceil(sorted.length / 2)));
          }

          if (negative.length > 0) {
            // Sort most negative first for display
            losers = [...negative].sort((a, b) => a.change - b.change).slice(0, 3);
          } else if (sorted.length > 1) {
            losers = [...sorted].reverse().slice(0, Math.min(3, Math.floor(sorted.length / 2)));
          }

          if (!cancelled) {
            setMovers({ gainers, losers });
            setLoading(false);
          }
        } else if (!cancelled) {
          setLoading(false);
        }
      } catch (err) {
        console.error('Failed to load top movers:', err);
        if (!cancelled) setLoading(false);
      }
    };

    fetchMovers();
    const interval = setInterval(fetchMovers, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="widget-panel-inner" style={{ padding: '16px', height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: 'var(--text-primary, #fff)', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>🔥</span> Top Gainers & Losers (24h)
        </h3>
        <span style={{ fontSize: '11px', color: '#94a3b8' }}>Live</span>
      </div>

      {loading ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: '13px' }}>
          Loading market momentum...
        </div>
      ) : movers.gainers.length === 0 && movers.losers.length === 0 ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: '13px' }}>
          No market movement data available.
        </div>
      ) : (
        <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', minHeight: 0, overflowY: 'auto' }}>
          {/* Gainers */}
          <div style={{ background: 'rgba(34, 197, 94, 0.06)', border: '1px solid rgba(34, 197, 94, 0.15)', borderRadius: '8px', padding: '8px' }}>
            <div style={{ fontSize: '11px', fontWeight: '700', color: '#4ade80', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              ▲ Top Gainers
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {movers.gainers.map(item => (
                <div key={item.symbol} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '12px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <CryptoIcon symbol={item.symbol} size={16} />
                    <span style={{ fontWeight: '600', color: 'var(--text-primary, #fff)' }}>{item.symbol}</span>
                  </div>
                  <span style={{ color: '#4ade80', fontWeight: '600' }}>
                    +{item.change >= 0 ? item.change.toFixed(2) : 0}%
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Losers */}
          <div style={{ background: 'rgba(239, 68, 68, 0.06)', border: '1px solid rgba(239, 68, 68, 0.15)', borderRadius: '8px', padding: '8px' }}>
            <div style={{ fontSize: '11px', fontWeight: '700', color: '#f87171', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              ▼ Top Losers
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {movers.losers.map(item => (
                <div key={item.symbol} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '12px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <CryptoIcon symbol={item.symbol} size={16} />
                    <span style={{ fontWeight: '600', color: 'var(--text-primary, #fff)' }}>{item.symbol}</span>
                  </div>
                  <span style={{ color: '#f87171', fontWeight: '600' }}>
                    {item.change <= 0 ? item.change.toFixed(2) : `-${item.change.toFixed(2)}`}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default TopMoversWidget;
