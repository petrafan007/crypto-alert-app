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
  const [trailingOrders, setTrailingOrders] = useState([]);
  const [ladderOrders, setLadderOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeSubTab, setActiveSubTab] = useState('all'); // 'all' | 'ladder' | 'trailing'

  const loadData = async () => {
    try {
      setLoading(true);
      const [trailingRes, ladderRes] = await Promise.allSettled([
        axios.get('/api/trading/trailing-orders?broker=all', { withCredentials: true }),
        axios.get('/api/trading/ladder-orders?broker=all', { withCredentials: true })
      ]);

      if (trailingRes.status === 'fulfilled' && trailingRes.value.data?.success) {
        setTrailingOrders((trailingRes.value.data.trailing_orders || []).filter(o => o.status === 'ACTIVE'));
      }
      if (ladderRes.status === 'fulfilled' && ladderRes.value.data?.success) {
        setLadderOrders((ladderRes.value.data.ladder_orders || []).filter(o => o.status === 'ACTIVE'));
      }
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

  const totalActive = trailingOrders.length + ladderOrders.length;

  return (
    <div className="widget-panel-inner" style={{ padding: '16px', height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '16px' }}>🪜</span>
          <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: 'var(--text-primary, #fff)' }}>
            Synthetic & Ladder Orders
          </h3>
          {totalActive > 0 && (
            <span style={{
              fontSize: '11px',
              fontWeight: '700',
              padding: '2px 7px',
              borderRadius: '10px',
              background: 'rgba(56, 189, 248, 0.2)',
              color: '#38bdf8'
            }}>
              {totalActive} Active
            </span>
          )}
        </div>

        {/* Sub-tabs */}
        <div style={{ display: 'flex', gap: '4px' }}>
          <button
            type="button"
            className={`order-type-btn ${activeSubTab === 'all' ? 'active' : ''}`}
            style={{ padding: '2px 8px', fontSize: '11px' }}
            onClick={() => setActiveSubTab('all')}
          >
            All ({totalActive})
          </button>
          <button
            type="button"
            className={`order-type-btn ${activeSubTab === 'ladder' ? 'active' : ''}`}
            style={{ padding: '2px 8px', fontSize: '11px' }}
            onClick={() => setActiveSubTab('ladder')}
          >
            Ladders ({ladderOrders.length})
          </button>
          <button
            type="button"
            className={`order-type-btn ${activeSubTab === 'trailing' ? 'active' : ''}`}
            style={{ padding: '2px 8px', fontSize: '11px' }}
            onClick={() => setActiveSubTab('trailing')}
          >
            Trailing ({trailingOrders.length})
          </button>
        </div>
      </div>

      {/* Orders List Container */}
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {loading && totalActive === 0 ? (
          <div style={{ textAlign: 'center', padding: '20px', color: '#94a3b8', fontSize: '12px' }}>
            ⏳ Loading synthetic orders...
          </div>
        ) : totalActive === 0 ? (
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
              Create a <strong>Ladder Order</strong> or <strong>Trailing Stop</strong> from Binance or Webull Trading to automate staged execution.
            </p>
          </div>
        ) : (
          <>
            {/* Ladder Orders */}
            {(activeSubTab === 'all' || activeSubTab === 'ladder') && ladderOrders.map(order => {
              const isSell = order.side === 'SELL';
              const progressPct = order.rungs_total > 0
                ? Math.round((order.rungs_filled / order.rungs_total) * 100)
                : 0;
              const nextRung = (order.rungs || []).find(r => r.status === 'PENDING');

              return (
                <div
                  key={`ladder_${order.id}`}
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
                        background: order.broker === 'webull' ? 'rgba(59, 130, 246, 0.2)' : 'rgba(245, 158, 11, 0.2)',
                        color: order.broker === 'webull' ? '#60a5fa' : '#fbbf24'
                      }}>
                        {order.broker === 'webull' ? 'Webull' : 'Binance'}
                      </span>
                      <strong style={{ color: '#fff', fontSize: '13px' }}>{order.symbol}</strong>
                      <span style={{
                        fontSize: '10px',
                        fontWeight: '700',
                        padding: '1px 5px',
                        borderRadius: '4px',
                        background: isSell ? 'rgba(56, 189, 248, 0.15)' : 'rgba(34, 197, 94, 0.15)',
                        color: isSell ? '#38bdf8' : '#4ade80'
                      }}>
                        {isSell ? '🪜 Scale-Out' : '🪜 Scale-In'}
                      </span>
                    </div>

                    <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                      {order.rungs_filled}/{order.rungs_total} rungs ({progressPct}%)
                    </span>
                  </div>

                  {/* Progress bar */}
                  <div style={{ width: '100%', height: '4px', background: 'rgba(0,0,0,0.5)', borderRadius: '2px', overflow: 'hidden', marginBottom: '6px' }}>
                    <div style={{ width: `${progressPct}%`, height: '100%', background: isSell ? '#38bdf8' : '#10b981' }} />
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: '#cbd5e1' }}>
                    <span>
                      Next target: <strong style={{ color: '#fff' }}>{nextRung ? `$${formatNumber(nextRung.target_price)}` : '—'}</strong>
                    </span>
                    {order.has_stop_loss && order.stop_loss_trigger_price && (
                      <span style={{ color: '#f87171' }}>
                        Stop: <strong>${formatNumber(order.stop_loss_trigger_price)}</strong>
                      </span>
                    )}
                  </div>
                </div>
              );
            })}

            {/* Trailing Orders */}
            {(activeSubTab === 'all' || activeSubTab === 'trailing') && trailingOrders.map(order => {
              const isSell = order.side === 'SELL';
              const trailText = order.trail_type === 'PERCENT' ? `${order.trail_value}%` : `$${order.trail_value}`;

              return (
                <div
                  key={`trailing_${order.id}`}
                  style={{
                    background: 'rgba(15, 23, 42, 0.5)',
                    border: '1px solid rgba(168, 85, 247, 0.2)',
                    borderRadius: '8px',
                    padding: '10px 12px'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span style={{
                        fontSize: '10px',
                        fontWeight: '700',
                        padding: '1px 6px',
                        borderRadius: '10px',
                        background: order.broker === 'webull' ? 'rgba(59, 130, 246, 0.2)' : 'rgba(245, 158, 11, 0.2)',
                        color: order.broker === 'webull' ? '#60a5fa' : '#fbbf24'
                      }}>
                        {order.broker === 'webull' ? 'Webull' : 'Binance'}
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
                        🎯 Trailing {order.side}
                      </span>
                    </div>

                    <span style={{ fontSize: '11px', color: '#c084fc', fontWeight: '600' }}>
                      Trail {trailText}
                    </span>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: '#cbd5e1' }}>
                    <span>
                      Trigger: <strong style={{ color: isSell ? '#f87171' : '#34d399' }}>
                        {order.current_stop_price ? `$${formatNumber(order.current_stop_price)}` : 'Tracking peak...'}
                      </strong>
                    </span>
                    <span>
                      Qty: {formatNumber(order.quantity, 4, 6)}
                    </span>
                  </div>
                </div>
              );
            })}
          </>
        )}
      </div>

      {/* Footer link to Orders */}
      <div style={{ marginTop: '8px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.06)', textAlign: 'right' }}>
        <Link to="/orders?tab=ladder_orders" style={{ fontSize: '11px', color: '#38bdf8', textDecoration: 'none', fontWeight: '600' }}>
          Manage Orders in Central Hub →
        </Link>
      </div>
    </div>
  );
};

export default SyntheticOrdersWidget;
