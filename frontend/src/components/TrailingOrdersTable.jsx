import React, { useState, useEffect } from 'react';
import axios from 'axios';
import '../pages/Trading.css';

const formatNumber = (num, minDigits = 2, maxDigits = 4) => {
  if (num === null || num === undefined || isNaN(num)) return '—';
  const val = Number(num);
  return val.toLocaleString(undefined, {
    minimumFractionDigits: minDigits,
    maximumFractionDigits: val >= 1 ? minDigits : maxDigits
  });
};

const TrailingOrdersTable = ({
  defaultBroker = 'all',
  showBrokerFilter = true,
  onOrderCancelled
}) => {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [brokerFilter, setBrokerFilter] = useState(defaultBroker);
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [cancellingId, setCancellingId] = useState(null);
  const [actionError, setActionError] = useState('');
  const [actionSuccess, setActionSuccess] = useState('');

  const loadOrders = async () => {
    try {
      setLoading(true);
      setActionError('');
      const params = {};
      if (brokerFilter && brokerFilter !== 'all') {
        params.broker = brokerFilter;
      }
      const res = await axios.get('/api/trading/trailing-orders', {
        params,
        withCredentials: true
      });
      if (res.data?.success) {
        setOrders(res.data.trailing_orders || []);
      }
    } catch (err) {
      console.error('Failed to load trailing orders:', err);
      setActionError(err.response?.data?.error || err.message || 'Failed to load trailing orders');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadOrders();
  }, [brokerFilter]);

  const handleCancelOrder = async (orderId) => {
    if (!window.confirm(`Are you sure you want to cancel Trailing Stop order #${orderId}?`)) {
      return;
    }
    try {
      setCancellingId(orderId);
      setActionError('');
      setActionSuccess('');
      const res = await axios.post(`/api/trading/trailing-orders/${orderId}/cancel`, {}, { withCredentials: true });
      if (res.data?.success) {
        setActionSuccess(`Trailing order #${orderId} cancelled successfully.`);
        if (onOrderCancelled) onOrderCancelled(orderId);
        loadOrders();
      } else {
        setActionError(res.data?.error || 'Failed to cancel trailing order');
      }
    } catch (err) {
      setActionError(err.response?.data?.error || err.message || 'Failed to cancel trailing order');
    } finally {
      setCancellingId(null);
    }
  };

  const displayOrders = orders.filter(order => {
    if (statusFilter === 'ACTIVE') return order.status === 'ACTIVE';
    if (statusFilter === 'TRIGGERED') return order.status === 'TRIGGERED';
    if (statusFilter === 'CANCELLED') return order.status === 'CANCELLED';
    return true;
  });

  return (
    <div className="trailing-orders-table-wrapper" style={{ width: '100%' }}>
      {/* Alerts */}
      {actionSuccess && (
        <div style={{
          background: 'rgba(34, 197, 94, 0.15)',
          border: '1px solid rgba(34, 197, 94, 0.3)',
          color: '#4ade80',
          padding: '8px 12px',
          borderRadius: '6px',
          marginBottom: '12px',
          fontSize: '13px'
        }}>
          ✅ {actionSuccess}
        </div>
      )}
      {actionError && (
        <div style={{
          background: 'rgba(239, 68, 68, 0.15)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          color: '#f87171',
          padding: '8px 12px',
          borderRadius: '6px',
          marginBottom: '12px',
          fontSize: '13px'
        }}>
          ⚠️ {actionError}
        </div>
      )}

      {/* Header controls */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: '10px',
        marginBottom: '14px',
        padding: '10px 14px',
        background: 'rgba(255, 255, 255, 0.03)',
        borderRadius: '8px',
        border: '1px solid rgba(255, 255, 255, 0.06)'
      }}>
        {showBrokerFilter ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ fontSize: '12px', color: '#94a3b8', marginRight: '4px' }}>Broker:</span>
            {[
              { id: 'all', label: 'All Brokers' },
              { id: 'binance', label: 'Binance.US' },
              { id: 'webull', label: 'Webull' }
            ].map(b => (
              <button
                key={b.id}
                type="button"
                className={`order-type-btn ${brokerFilter === b.id ? 'active' : ''}`}
                style={{ padding: '4px 10px', fontSize: '11px', borderRadius: '16px' }}
                onClick={() => setBrokerFilter(b.id)}
              >
                {b.id === 'binance' && <span style={{ marginRight: '4px' }}>🟡</span>}
                {b.id === 'webull' && <span style={{ marginRight: '4px' }}>🔵</span>}
                {b.label}
              </button>
            ))}
          </div>
        ) : <div />}

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{ display: 'flex', gap: '4px' }}>
            {[
              { id: 'ALL', label: 'All' },
              { id: 'ACTIVE', label: 'Active' },
              { id: 'TRIGGERED', label: 'Triggered' },
              { id: 'CANCELLED', label: 'Cancelled' }
            ].map(s => (
              <button
                key={s.id}
                type="button"
                className={`order-type-btn ${statusFilter === s.id ? 'active' : ''}`}
                style={{ padding: '4px 8px', fontSize: '11px' }}
                onClick={() => setStatusFilter(s.id)}
              >
                {s.label}
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={loadOrders}
            disabled={loading}
            style={{
              padding: '5px 12px',
              borderRadius: '6px',
              background: 'rgba(56, 189, 248, 0.15)',
              border: '1px solid rgba(56, 189, 248, 0.3)',
              color: '#38bdf8',
              fontSize: '12px',
              cursor: loading ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '4px'
            }}
          >
            {loading ? '⏳ Updating...' : '🔄 Refresh'}
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="table-container" style={{ overflowX: 'auto' }}>
        <table className="trading-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th>Broker</th>
              <th>Symbol</th>
              <th>Side</th>
              <th>Trail Distance</th>
              <th>Reference Peak/Dip</th>
              <th>Dynamic Trigger</th>
              <th>Quantity</th>
              <th>Status</th>
              <th>Created</th>
              <th style={{ textAlign: 'center' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {displayOrders.length === 0 ? (
              <tr>
                <td colSpan="10" style={{ textAlign: 'center', padding: '36px', color: '#94a3b8' }}>
                  {loading ? 'Loading trailing orders...' : 'No trailing orders found matching the current filters.'}
                </td>
              </tr>
            ) : (
              displayOrders.map(order => {
                const isSell = order.side === 'SELL';
                const refPrice = isSell ? order.reference_high_price : order.reference_low_price;
                const trailText = order.trail_type === 'PERCENT' ? `${order.trail_value}%` : `$${order.trail_value}`;

                return (
                  <tr key={order.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                    {/* Broker */}
                    <td>
                      <span style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        padding: '2px 8px',
                        borderRadius: '12px',
                        fontSize: '11px',
                        fontWeight: '600',
                        background: order.broker === 'webull' ? 'rgba(59, 130, 246, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                        color: order.broker === 'webull' ? '#60a5fa' : '#fbbf24',
                        border: `1px solid ${order.broker === 'webull' ? 'rgba(59, 130, 246, 0.3)' : 'rgba(245, 158, 11, 0.3)'}`
                      }}>
                        {order.broker === 'webull' ? 'Webull' : 'Binance.US'}
                      </span>
                    </td>

                    {/* Symbol */}
                    <td style={{ fontWeight: '700', color: '#fff' }}>
                      {order.symbol}
                    </td>

                    {/* Side */}
                    <td>
                      <span style={{
                        padding: '2px 6px',
                        borderRadius: '4px',
                        fontSize: '11px',
                        fontWeight: '700',
                        background: isSell ? 'rgba(239, 68, 68, 0.15)' : 'rgba(34, 197, 94, 0.15)',
                        color: isSell ? '#f87171' : '#4ade80'
                      }}>
                        {order.side}
                      </span>
                    </td>

                    {/* Trail Distance */}
                    <td style={{ fontSize: '12px', fontWeight: '600', color: '#38bdf8' }}>
                      {trailText}
                    </td>

                    {/* Reference High / Low */}
                    <td style={{ fontSize: '12px', color: '#cbd5e1' }}>
                      {refPrice ? `$${formatNumber(refPrice)}` : 'Tracking...'}
                    </td>

                    {/* Dynamic Trigger */}
                    <td style={{ fontSize: '12px' }}>
                      {order.current_stop_price ? (
                        <strong style={{ color: isSell ? '#f87171' : '#34d399' }}>
                          ${formatNumber(order.current_stop_price)}
                        </strong>
                      ) : (
                        <span style={{ color: '#94a3b8' }}>Tracking peak...</span>
                      )}
                    </td>

                    {/* Quantity */}
                    <td style={{ fontSize: '12px', color: '#cbd5e1' }}>
                      {formatNumber(order.quantity, 4, 6)}
                    </td>

                    {/* Status */}
                    <td>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: '12px',
                        fontSize: '11px',
                        fontWeight: '700',
                        background:
                          order.status === 'ACTIVE' ? 'rgba(34, 197, 94, 0.15)' :
                          order.status === 'TRIGGERED' ? 'rgba(56, 189, 248, 0.15)' :
                          'rgba(148, 163, 184, 0.15)',
                        color:
                          order.status === 'ACTIVE' ? '#4ade80' :
                          order.status === 'TRIGGERED' ? '#38bdf8' :
                          '#94a3b8'
                      }}>
                        {order.status}
                      </span>
                    </td>

                    {/* Created */}
                    <td style={{ fontSize: '11px', color: '#94a3b8', whiteSpace: 'nowrap' }}>
                      {order.created_at ? new Date(order.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—'}
                    </td>

                    {/* Action */}
                    <td style={{ textAlign: 'center' }}>
                      {order.status === 'ACTIVE' ? (
                        <button
                          type="button"
                          onClick={() => handleCancelOrder(order.id)}
                          disabled={cancellingId === order.id}
                          style={{
                            background: 'rgba(239, 68, 68, 0.15)',
                            border: '1px solid rgba(239, 68, 68, 0.3)',
                            color: '#f87171',
                            padding: '4px 10px',
                            borderRadius: '4px',
                            fontSize: '11px',
                            fontWeight: '600',
                            cursor: cancellingId === order.id ? 'not-allowed' : 'pointer'
                          }}
                        >
                          {cancellingId === order.id ? 'Cancelling...' : 'Cancel'}
                        </button>
                      ) : (
                        <span style={{ color: '#475569', fontSize: '11px' }}>—</span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default TrailingOrdersTable;
