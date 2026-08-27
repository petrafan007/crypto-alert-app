import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { FaDollarSign } from 'react-icons/fa';

const TopStockMoversWidget = ({ isLightMode, config, onEdit, ownedSymbols, onStockClick }) => {
  const [movers, setMovers] = useState({ gainers: [], losers: [] });
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState('');
  const count = config?.count || 10;
  const owned = ownedSymbols || new Set();

  useEffect(() => {
    let cancelled = false;
    const fetchStockMovers = async () => {
      try {
        const res = await axios.get('/api/webull/stock-movers', { withCredentials: true });
        if (cancelled) return;

        if (res.data?.success) {
          const rawGainers = Array.isArray(res.data?.gainers) ? res.data.gainers : [];
          const rawLosers = Array.isArray(res.data?.losers) ? res.data.losers : [];

          const formatItems = (list) =>
            list
              .filter(item => item && item.symbol)
              .map(item => ({
                symbol: String(item.symbol).toUpperCase(),
                name: item.name || '',
                price: Number(item.price || 0),
                change: Number(item.change || 0),
                currency: item.currency || 'USD',
              }));

          const sortedGainers = formatItems(rawGainers)
            .sort((a, b) => b.change - a.change)
            .slice(0, count);

          const sortedLosers = formatItems(rawLosers)
            .sort((a, b) => a.change - b.change)
            .slice(0, count);

          setMovers({ gainers: sortedGainers, losers: sortedLosers });
          setErrorMessage('');
          setLoading(false);
        } else {
          setErrorMessage(res.data?.message || 'Unable to load U.S. stock movers.');
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          const msg = err.response?.data?.message || err.message || 'Connect Webull to view U.S. stock movers.';
          setErrorMessage(msg);
          setLoading(false);
        }
      }
    };

    fetchStockMovers();
    const interval = setInterval(fetchStockMovers, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [count]);

  const renderRow = (item, color) => {
    const isOwned = owned.has(item.symbol);
    const titleText = `${item.name ? `${item.name} (${item.symbol})` : item.symbol}${item.price > 0 ? ` · $${item.price.toFixed(2)}` : ''}${isOwned ? ' · You own this stock' : ''}`;

    return (
      <div
        key={item.symbol}
        className="top-mover-row"
        title={titleText}
        onClick={onStockClick ? () => onStockClick(item.symbol) : undefined}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          fontSize: '12px',
          padding: isOwned ? '2px 6px' : '2px 0',
          borderRadius: '5px',
          cursor: onStockClick ? 'pointer' : 'default',
          backgroundColor: isOwned ? (isLightMode ? 'rgba(56, 189, 248, 0.16)' : 'rgba(56, 189, 248, 0.14)') : 'transparent',
          border: isOwned ? '1px solid rgba(56, 189, 248, 0.4)' : '1px solid transparent'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', minWidth: 0 }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', color: 'var(--text-secondary, #94a3b8)', fontSize: '0.8rem', flexShrink: 0 }}>
            <FaDollarSign />
          </span>
          <span style={{ fontWeight: '600', color: 'var(--text-primary, #fff)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {item.symbol}
          </span>
          {isOwned && <span style={{ fontSize: '9px', fontWeight: '700', color: '#38bdf8', flexShrink: 0 }}>★</span>}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
          {item.price > 0 && (
            <span style={{ fontSize: '11px', color: 'var(--text-secondary, #94a3b8)' }}>
              ${item.price.toFixed(2)}
            </span>
          )}
          <span style={{ color, fontWeight: '600' }}>
            {item.change >= 0 ? '+' : ''}{item.change.toFixed(2)}%
          </span>
        </div>
      </div>
    );
  };

  return (
    <div className="widget-panel-inner" style={{ padding: '12px', height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
        <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: 'var(--text-primary, #fff)', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>📈</span> Top Stock Gainers & Losers (24h)
        </h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '11px', color: '#94a3b8' }}>Live · U.S. Stocks</span>
          {onEdit && (
            <button
              onClick={onEdit}
              title="Customize Top Stock Gainers & Losers"
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
          Loading stock momentum...
        </div>
      ) : errorMessage ? (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: '13px', textAlign: 'center', padding: '10px', gap: '6px' }}>
          <span>{errorMessage}</span>
          <span style={{ fontSize: '11px', color: 'var(--accent-primary, #38bdf8)' }}>Connect Webull in Settings &gt; Exchange Setup</span>
        </div>
      ) : movers.gainers.length === 0 && movers.losers.length === 0 ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: '13px' }}>
          No stock market movement data available.
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

export default TopStockMoversWidget;
