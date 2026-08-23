import React, { useState, useEffect } from 'react';
import axios from 'axios';
import CryptoIcon from './CryptoIcon';

const TopMoversWidget = ({ isLightMode, config, onEdit, ownedSymbols }) => {
  const [movers, setMovers] = useState({ gainers: [], losers: [] });
  const [loading, setLoading] = useState(true);
  const count = config?.count || 10;
  const owned = ownedSymbols || new Set();

  useEffect(() => {
    let cancelled = false;
    const fetchMovers = async () => {
      try {
        const res = await axios.get('/api/market-movers', { withCredentials: true });
        const all = Array.isArray(res.data?.movers) ? res.data.movers : [];

        const validCoins = all
          .filter(c => c && c.symbol)
          .map(c => ({
            symbol: c.symbol.toUpperCase(),
            price: Number(c.price || 0),
            change: Number(c.change || 0),
            quote: c.quote_currency || 'USDT'
          }));

        if (validCoins.length > 0) {
          const sorted = [...validCoins].sort((a, b) => b.change - a.change);
          const gainers = sorted.filter(c => c.change > 0).slice(0, count);
          const losers = [...sorted].filter(c => c.change < 0).sort((a, b) => a.change - b.change).slice(0, count);

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
  }, [count]);

  const renderRow = (item, color) => {
    const isOwned = owned.has(item.symbol);
    return (
      <div
        key={item.symbol}
        title={isOwned ? 'You own this coin' : undefined}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          fontSize: '12px',
          padding: isOwned ? '2px 6px' : '2px 0',
          borderRadius: '5px',
          backgroundColor: isOwned ? (isLightMode ? 'rgba(56, 189, 248, 0.16)' : 'rgba(56, 189, 248, 0.14)') : 'transparent',
          border: isOwned ? '1px solid rgba(56, 189, 248, 0.4)' : '1px solid transparent'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <CryptoIcon symbol={item.symbol} size={16} />
          <span style={{ fontWeight: '600', color: 'var(--text-primary, #fff)' }}>{item.symbol}</span>
          {isOwned && <span style={{ fontSize: '9px', fontWeight: '700', color: '#38bdf8' }}>★</span>}
        </div>
        <span style={{ color, fontWeight: '600' }}>
          {item.change >= 0 ? '+' : ''}{item.change.toFixed(2)}%
        </span>
      </div>
    );
  };

  return (
    <div className="widget-panel-inner" style={{ padding: '12px', height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
        <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: 'var(--text-primary, #fff)', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>🔥</span> Top Gainers & Losers (24h)
        </h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '11px', color: '#94a3b8' }}>Live · All Binance.US Coins</span>
          {onEdit && (
            <button
              onClick={onEdit}
              title="Customize Top Gainers & Losers"
              style={{
                background: 'rgba(255,255,255,0.08)',
                border: '1px solid rgba(255,255,255,0.15)',
                borderRadius: '6px',
                color: 'var(--text-secondary, #94a3b8)',
                cursor: 'pointer',
                fontSize: '12px',
                padding: '3px 6px',
                lineHeight: 1
              }}
            >
              ✏️
            </button>
          )}
        </div>
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
        <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', minHeight: 0 }}>
          {/* Gainers */}
          <div style={{ background: 'rgba(34, 197, 94, 0.06)', border: '1px solid rgba(34, 197, 94, 0.15)', borderRadius: '8px', padding: '6px', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div style={{ fontSize: '11px', fontWeight: '700', color: '#4ade80', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              ▲ Top Gainers
            </div>
            <div className="custom-scrollbar" style={{ display: 'flex', flexDirection: 'column', gap: '3px', flex: 1, minHeight: 0, overflowY: 'auto' }}>
              {movers.gainers.map(item => renderRow(item, '#4ade80'))}
            </div>
          </div>

          {/* Losers */}
          <div style={{ background: 'rgba(239, 68, 68, 0.06)', border: '1px solid rgba(239, 68, 68, 0.15)', borderRadius: '8px', padding: '6px', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <div style={{ fontSize: '11px', fontWeight: '700', color: '#f87171', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              ▼ Top Losers
            </div>
            <div className="custom-scrollbar" style={{ display: 'flex', flexDirection: 'column', gap: '3px', flex: 1, minHeight: 0, overflowY: 'auto' }}>
              {movers.losers.map(item => renderRow(item, '#f87171'))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default TopMoversWidget;
