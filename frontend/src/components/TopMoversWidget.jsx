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
        const [portfolioRes, watchlistRes] = await Promise.allSettled([
          axios.get('/api/coin-data-live', { withCredentials: true }),
          axios.get('/api/watchlist-live', { withCredentials: true })
        ]);

        const allCoins = [];
        const seen = new Set();

        if (portfolioRes.status === 'fulfilled' && portfolioRes.value.data?.coins) {
          portfolioRes.value.data.coins.forEach(c => {
            if (c.symbol && !seen.has(c.symbol.toUpperCase())) {
              seen.add(c.symbol.toUpperCase());
              allCoins.push({
                symbol: c.symbol.toUpperCase(),
                price: parseFloat(c.current || c.current_price || 0),
                change: parseFloat(c.percent_change_24h || c.change_24h || 0)
              });
            }
          });
        }

        if (watchlistRes.status === 'fulfilled' && Array.isArray(watchlistRes.value.data?.watchlist)) {
          watchlistRes.value.data.watchlist.forEach(w => {
            if (w.symbol && !seen.has(w.symbol.toUpperCase())) {
              seen.add(w.symbol.toUpperCase());
              allCoins.push({
                symbol: w.symbol.toUpperCase(),
                price: parseFloat(w.current_price || w.price || 0),
                change: parseFloat(w.percent_change_24h || w.change_24h || 0)
              });
            }
          });
        }

        // Filter valid coins
        const validCoins = allCoins.filter(c => c.price > 0 && !['USD', 'USDT', 'USDC'].includes(c.symbol));
        
        const sorted = [...validCoins].sort((a, b) => b.change - a.change);
        const gainers = sorted.slice(0, 3);
        const losers = [...validCoins].sort((a, b) => a.change - b.change).slice(0, 3);

        if (!cancelled) {
          setMovers({ gainers, losers });
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
