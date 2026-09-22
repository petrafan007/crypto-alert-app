import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';

const formatNumber = (num, minDigits = 2, maxDigits = 4) => {
  if (num === null || num === undefined || isNaN(num)) return '—';
  const val = Number(num);
  return val.toLocaleString(undefined, {
    minimumFractionDigits: minDigits,
    maximumFractionDigits: val >= 1 ? minDigits : maxDigits
  });
};

const SyntheticOrdersWidget = ({ isLightMode }) => {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [brokerFilter, setBrokerFilter] = useState('all'); // 'all' | 'binance' | 'webull'

  const loadData = async () => {
    try {
      setLoading(true);
      const [trailingRes, ladderRes] = await Promise.allSettled([
        axios.get('/api/trading/trailing-orders?broker=all', { withCredentials: true }),
        axios.get('/api/trading/ladder-orders?broker=all', { withCredentials: true })
      ]);

      const combined = [];

      if (ladderRes.status === 'fulfilled' && ladderRes.value.data?.success) {
        (ladderRes.value.data.ladder_orders || [])
          .filter(o => ['ACTIVE', 'PARTIALLY_FILLED'].includes(o.status))
          .forEach(lo => combined.push({ ...lo, orderKind: 'BRACKET' }));
      }

      if (trailingRes.status === 'fulfilled' && trailingRes.value.data?.success) {
        (trailingRes.value.data.trailing_orders || [])
          .filter(o => o.status === 'ACTIVE')
          .forEach(to => combined.push({ ...to, orderKind: 'TRAILING', total_quantity: to.quantity }));
      }

      combined.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
      setOrders(combined);
    } catch (err) {
      console.error('Failed to load synthetic orders widget data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const timer = setInterval(loadData, 15000); // 15s refresh
    return () => clearInterval(timer);
  }, []);

  const filtered = orders.filter(o => {
    if (brokerFilter === 'all') return true;
    return (o.broker || '').toLowerCase() === brokerFilter;
  });

  return (
    <div className="widget-panel-inner" style={{ padding: '16px', height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '16px' }}>⚡</span>
          <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: 'var(--text-primary, #fff)' }}>
            Synthetic Orders
          </h3>
          {orders.length > 0 && (
            <span style={{
              fontSize: '11px',
              fontWeight: '700',
              padding: '2px 7px',
              borderRadius: '10px',
              background: 'rgba(56, 189, 248, 0.2)',
              color: '#38bdf8'
            }}>
              {orders.length} Active
            </span>
          )}
        </div>

        {/* Broker Filter Pills */}
        <div style={{ display: 'flex', gap: '4px' }}>
          {[
            { id: 'all', label: `All (${orders.length})` },
            { id: 'binance', label: 'Binance' },
            { id: 'webull', label: 'Webull' }
          ].map(b => (
            <button
              key={b.id}
              type="button"
              className={`order-type-btn ${brokerFilter === b.id ? 'active' : ''}`}
              style={{ padding: '2px 8px', fontSize: '11px' }}
              onClick={() => setBrokerFilter(b.id)}
            >
              {b.label}
            </button>
          ))}
        </div>
      </div>

      {/* Orders List Container */}
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {loading && orders.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '20px', color: '#94a3b8', fontSize: '12px' }}>
            ⏳ Loading synthetic orders...
          </div>
        ) : filtered.length === 0 ? (
          <div style={{
            textAlign: 'center',
            padding: '24px 16px',
            color: '#94a3b8',
            fontSize: '12px',
            background: 'rgba(255,255,255,0.02)',
            borderRadius: '8px',
            border: '1px dashed rgba(255,255,255,0.08)'
          }}>
            <p style={{ margin: '0 0 8px 0', fontSize: '13px', color: '#cbd5e1' }}>No active synthetic orders</p>
            <p style={{ margin: 0, fontSize: '11px' }}>
              Create a <strong>Synthetic Order (Trailing & Ladder)</strong> from Binance or Webull Trading to automate smart execution.
            </p>
          </div>
        ) : (
          filtered.map(order => {
            const isSell = order.side === 'SELL';
            const isWebull = (order.broker || '').toLowerCase() === 'webull';
            const isTrailing = order.orderKind === 'TRAILING';
            const progressPct = order.rungs_total > 0
              ? Math.round(((order.rungs_filled || 0) / order.rungs_total) * 100)
              : 0;
            const nextRung = (order.rungs || []).find(r => r.status === 'PENDING');

            return (
              <div
                key={`${order.orderKind}_${order.id}`}
                style={{
                  background: 'rgba(15, 23, 42, 0.5)',
                  border: '1px solid rgba(56, 189, 248, 0.2)',
                  borderRadius: '8px',
                  padding: '10px 12px',
                  position: 'relative'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{
                      fontSize: '10px',
                      fontWeight: '700',
                      padding: '1px 6px',
                      borderRadius: '10px',
                      background: isWebull ? 'rgba(59, 130, 246, 0.2)' : 'rgba(245, 158, 11, 0.2)',
                      color: isWebull ? '#60a5fa' : '#fbbf24'
                    }}>
                      {isWebull ? 'Webull' : 'Binance'}
                    </span>
                    <strong style={{ color: '#fff', fontSize: '13px' }}>{order.symbol}</strong>
                    <span style={{
                      fontSize: '10px',
                      fontWeight: '700',
                      padding: '1px 5px',
                      borderRadius: '4px',
                      background: isSell ? 'rgba(239, 68, 68, 0.15)' : 'rgba(34, 197, 94, 0.15)',
                      color: isSell ? '#f87171' : '#4ade80'
                    }}>
                      {order.side}
                    </span>
                    <span style={{
                      fontSize: '9.5px',
                      fontWeight: '700',
                      padding: '1px 5px',
                      borderRadius: '4px',
                      background: 'rgba(56, 189, 248, 0.15)',
                      color: '#38bdf8'
                    }}>
                      {isTrailing ? '🎯 Trailing' : '⚡ Smart Bracket'}
                    </span>
                  </div>

                  <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                    {isTrailing ? (
                      `Trail ${order.trail_value}${order.trail_type === 'AMOUNT' ? '$' : '%'}`
                    ) : (
                      `${order.rungs_filled || 0}/${order.rungs_total || 0} rungs (${progressPct}%)`
                    )}
                  </span>
                </div>

                {/* Progress bar */}
                <div style={{ width: '100%', height: '4px', background: 'rgba(0,0,0,0.5)', borderRadius: '2px', overflow: 'hidden', marginBottom: '6px' }}>
                  <div style={{
                    width: `${isTrailing ? 100 : progressPct}%`,
                    height: '100%',
                    background: isTrailing ? 'linear-gradient(90deg, #6366f1, #38bdf8)' : isSell ? '#38bdf8' : '#10b981'
                  }} />
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: '#cbd5e1' }}>
                  <span>
                    {isTrailing ? (
                      <>Stop: <strong style={{ color: '#f87171' }}>${formatNumber(order.current_stop_price)}</strong></>
                    ) : (
                      <>Next Target: <strong style={{ color: '#fff' }}>{nextRung ? `$${formatNumber(nextRung.target_price)}` : '—'}</strong></>
                    )}
                  </span>
                  <span>
                    Qty: <strong style={{ color: '#fff' }}>{formatNumber(order.total_quantity, 2, 6)}</strong>
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Footer navigation */}
      <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.06)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Link to="/orders?tab=synthetic_orders" style={{ fontSize: '11px', color: '#38bdf8', textDecoration: 'none' }}>
          View all synthetic orders →
        </Link>
        <span style={{ fontSize: '10px', color: '#64748b' }}>
          Auto-updates every 15s
        </span>
      </div>
    </div>
  );
};

export default SyntheticOrdersWidget;
