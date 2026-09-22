import React, { useState, useEffect } from 'react';
import axios from 'axios';
import CryptoIcon, { BinanceLogo, WebullLogo } from './CryptoIcon';
import '../pages/Trading.css';

const formatNumber = (num, minDigits = 2, maxDigits = 4) => {
  if (num === null || num === undefined || isNaN(num)) return '—';
  const val = Number(num);
  return val.toLocaleString(undefined, {
    minimumFractionDigits: minDigits,
    maximumFractionDigits: val >= 1 ? minDigits : maxDigits
  });
};

const LadderOrdersTable = ({
  defaultBroker = 'all',
  showBrokerFilter = true,
  onOrderCancelled
}) => {
  const [ladderOrders, setLadderOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [brokerFilter, setBrokerFilter] = useState(defaultBroker);
  const [statusFilter, setStatusFilter] = useState('ALL'); // 'ALL' | 'ACTIVE' | 'COMPLETED' | 'CANCELLED'
  const [expandedOrders, setExpandedOrders] = useState(new Set());
  const [cancellingId, setCancellingId] = useState(null);
  const [actionError, setActionError] = useState('');
  const [actionSuccess, setActionSuccess] = useState('');

  const loadLadderOrders = async () => {
    try {
      setLoading(true);
      setActionError('');
      const params = {};
      if (brokerFilter && brokerFilter !== 'all') {
        params.broker = brokerFilter;
      }
      const res = await axios.get('/api/trading/ladder-orders', {
        params,
        withCredentials: true
      });
      if (res.data?.success) {
        setLadderOrders(res.data.ladder_orders || []);
      }
    } catch (err) {
      console.error('Failed to load ladder orders:', err);
      setActionError(err.response?.data?.error || err.message || 'Failed to load ladder orders');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLadderOrders();
  }, [brokerFilter]);

  const toggleExpand = (id) => {
    setExpandedOrders(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleCancelLadder = async (orderId) => {
    if (!window.confirm('Are you sure you want to cancel this synthetic Ladder Order? All remaining unfilled rungs will be cancelled.')) {
      return;
    }
    try {
      setCancellingId(orderId);
      setActionError('');
      setActionSuccess('');
      const res = await axios.post(`/api/trading/ladder-orders/${orderId}/cancel`, {}, { withCredentials: true });
      if (res.data?.success) {
        setActionSuccess(`Ladder order #${orderId} cancelled successfully.`);
        if (onOrderCancelled) onOrderCancelled(orderId);
        loadLadderOrders();
      } else {
        setActionError(res.data?.error || 'Failed to cancel ladder order');
      }
    } catch (err) {
      setActionError(err.response?.data?.error || err.message || 'Failed to cancel ladder order');
    } finally {
      setCancellingId(null);
    }
  };

  // Filter display orders
  const displayOrders = ladderOrders.filter(order => {
    if (statusFilter === 'ACTIVE') return order.status === 'ACTIVE';
    if (statusFilter === 'COMPLETED') return order.status === 'COMPLETED';
    if (statusFilter === 'CANCELLED') return ['CANCELLED', 'STOP_LOSS_TRIGGERED'].includes(order.status);
    return true;
  });

  return (
    <div className="ladder-orders-table-wrapper" style={{ width: '100%' }}>
      {/* Action alerts */}
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

      {/* Header Controls Bar */}
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
        {/* Broker filter pills */}
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

        {/* Status Filter & Refresh */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{ display: 'flex', gap: '4px' }}>
            {[
              { id: 'ALL', label: 'All' },
              { id: 'ACTIVE', label: 'Active' },
              { id: 'COMPLETED', label: 'Filled' },
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
            onClick={loadLadderOrders}
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

      {/* Table Container */}
      <div className="table-container" style={{ overflowX: 'auto' }}>
        <table className="trading-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={{ width: '32px' }}></th>
              <th>Broker</th>
              <th>Symbol</th>
              <th>Side</th>
              <th>Preset</th>
              <th>Progress</th>
              <th>Next Target</th>
              <th>Total Qty</th>
              <th>Stop-Loss</th>
              <th>Status</th>
              <th>Created</th>
              <th style={{ textAlign: 'center' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {displayOrders.length === 0 ? (
              <tr>
                <td colSpan="12" style={{ textAlign: 'center', padding: '36px', color: '#94a3b8' }}>
                  {loading ? 'Loading ladder orders...' : 'No ladder orders found matching the current filters.'}
                </td>
              </tr>
            ) : (
              displayOrders.map(order => {
                const isExpanded = expandedOrders.has(order.id);
                const isSell = order.side === 'SELL';
                const progressPct = order.rungs_total > 0
                  ? Math.round((order.rungs_filled / order.rungs_total) * 100)
                  : 0;

                // Find next pending rung
                const nextRung = (order.rungs || []).find(r => r.status === 'PENDING');

                return (
                  <React.Fragment key={order.id}>
                    <tr style={{
                      borderBottom: isExpanded ? 'none' : '1px solid rgba(255,255,255,0.06)',
                      background: isExpanded ? 'rgba(255,255,255,0.02)' : 'transparent'
                    }}>
                      {/* Expand Button */}
                      <td style={{ textAlign: 'center', padding: '8px 4px' }}>
                        <button
                          type="button"
                          onClick={() => toggleExpand(order.id)}
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: '#94a3b8',
                            cursor: 'pointer',
                            fontSize: '12px',
                            padding: '2px 4px'
                          }}
                          title={isExpanded ? 'Collapse rungs' : 'Expand rungs detail'}
                        >
                          {isExpanded ? '▼' : '▶'}
                        </button>
                      </td>

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
                          background: isSell ? 'rgba(56, 189, 248, 0.15)' : 'rgba(34, 197, 94, 0.15)',
                          color: isSell ? '#38bdf8' : '#4ade80'
                        }}>
                          {isSell ? 'SCALE-OUT (SELL)' : 'SCALE-IN (BUY)'}
                        </span>
                      </td>

                      {/* Preset */}
                      <td style={{ fontSize: '12px', color: '#cbd5e1' }}>
                        {order.preset_name || 'Custom'}
                      </td>

                      {/* Progress Bar & Text */}
                      <td style={{ minWidth: '130px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px', fontSize: '11px' }}>
                          <span style={{ fontWeight: '700', color: '#f8fafc' }}>
                            {order.rungs_filled} of {order.rungs_total} filled
                          </span>
                          <span style={{ color: '#94a3b8' }}>{progressPct}%</span>
                        </div>
                        <div style={{ width: '100%', height: '6px', background: 'rgba(0,0,0,0.5)', borderRadius: '3px', overflow: 'hidden' }}>
                          <div style={{
                            width: `${progressPct}%`,
                            height: '100%',
                            background: progressPct === 100 ? '#4ade80' : isSell ? '#38bdf8' : '#10b981',
                            transition: 'width 0.3s ease'
                          }} />
                        </div>
                      </td>

                      {/* Next Target */}
                      <td style={{ fontSize: '12px' }}>
                        {nextRung ? (
                          <span style={{ fontWeight: '700', color: '#f8fafc' }}>
                            ${formatNumber(nextRung.target_price)}
                            <span style={{ fontSize: '10px', color: nextRung.price_offset_pct >= 0 ? '#34d399' : '#f87171', marginLeft: '4px' }}>
                              ({nextRung.price_offset_pct >= 0 ? '+' : ''}{nextRung.price_offset_pct}%)
                            </span>
                          </span>
                        ) : (
                          <span style={{ color: '#94a3b8' }}>—</span>
                        )}
                      </td>

                      {/* Total Qty */}
                      <td style={{ fontSize: '12px', fontWeight: '600', color: '#cbd5e1' }}>
                        {formatNumber(order.total_quantity, 4, 6)}
                      </td>

                      {/* Stop-Loss */}
                      <td style={{ fontSize: '11px' }}>
                        {order.has_stop_loss && order.stop_loss_trigger_price ? (
                          <span style={{ color: '#f87171', fontWeight: '600' }}>
                            ${formatNumber(order.stop_loss_trigger_price)}
                          </span>
                        ) : (
                          <span style={{ color: '#64748b' }}>None</span>
                        )}
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
                            order.status === 'COMPLETED' ? 'rgba(56, 189, 248, 0.15)' :
                            order.status === 'STOP_LOSS_TRIGGERED' ? 'rgba(239, 68, 68, 0.15)' :
                            'rgba(148, 163, 184, 0.15)',
                          color:
                            order.status === 'ACTIVE' ? '#4ade80' :
                            order.status === 'COMPLETED' ? '#38bdf8' :
                            order.status === 'STOP_LOSS_TRIGGERED' ? '#f87171' :
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
                            onClick={() => handleCancelLadder(order.id)}
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

                    {/* EXPANDED RUNGS DRAWER */}
                    {isExpanded && (
                      <tr style={{ background: 'rgba(15, 23, 42, 0.6)' }}>
                        <td colSpan="12" style={{ padding: '12px 18px' }}>
                          <div style={{ fontSize: '12px', fontWeight: '700', color: '#38bdf8', marginBottom: '8px' }}>
                            🪜 Detailed Rung Progression for Ladder #{order.id}:
                          </div>
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '8px' }}>
                            {(order.rungs || []).map(rung => {
                              const isFilled = rung.status === 'FILLED';
                              const isPending = rung.status === 'PENDING';
                              return (
                                <div
                                  key={rung.id || rung.rung_number}
                                  style={{
                                    background: isFilled ? 'rgba(34, 197, 94, 0.08)' : 'rgba(255, 255, 255, 0.03)',
                                    border: `1px solid ${isFilled ? 'rgba(34, 197, 94, 0.3)' : isPending ? 'rgba(56, 189, 248, 0.3)' : 'rgba(255, 255, 255, 0.08)'}`,
                                    borderRadius: '6px',
                                    padding: '8px 10px',
                                    fontSize: '11px'
                                  }}
                                >
                                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                                    <strong style={{ color: '#fff' }}>Rung #{rung.rung_number}</strong>
                                    <span style={{
                                      fontWeight: '700',
                                      color: isFilled ? '#4ade80' : isPending ? '#38bdf8' : '#94a3b8'
                                    }}>
                                      {rung.status}
                                    </span>
                                  </div>
                                  <div style={{ color: '#cbd5e1' }}>
                                    Target: <strong>${formatNumber(rung.target_price)}</strong> ({rung.price_offset_pct >= 0 ? '+' : ''}{rung.price_offset_pct}%)
                                  </div>
                                  <div style={{ color: '#94a3b8' }}>
                                    Qty: {formatNumber(rung.quantity, 4, 6)} ({rung.percentage_of_total}%)
                                  </div>
                                  {isFilled && rung.executed_price && (
                                    <div style={{ color: '#4ade80', marginTop: '4px', fontSize: '10px' }}>
                                      Filled at ${formatNumber(rung.executed_price)}
                                    </div>
                                  )}
                                  {rung.error_message && (
                                    <div style={{ color: '#f87171', marginTop: '4px', fontSize: '10px' }}>
                                      {rung.error_message}
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default LadderOrdersTable;
