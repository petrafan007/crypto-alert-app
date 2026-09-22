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

const SyntheticOrdersTable = ({
  defaultBroker = 'all',
  showBrokerFilter = true,
  onOrderCancelled
}) => {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [brokerFilter, setBrokerFilter] = useState(defaultBroker);
  const [statusFilter, setStatusFilter] = useState('ALL'); // 'ALL' | 'ACTIVE' | 'COMPLETED' | 'CANCELLED'
  const [typeFilter, setTypeFilter] = useState('ALL'); // 'ALL' | 'BRACKET' | 'LADDER' | 'TRAILING'
  const [expandedOrders, setExpandedOrders] = useState(new Set());
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

      // Fetch both ladder/smart orders and standalone trailing orders
      const [ladderRes, trailingRes] = await Promise.allSettled([
        axios.get('/api/trading/ladder-orders', { params, withCredentials: true }),
        axios.get('/api/trading/trailing-orders', { params, withCredentials: true })
      ]);

      const unified = [];

      if (ladderRes.status === 'fulfilled' && ladderRes.value.data?.success) {
        (ladderRes.value.data.ladder_orders || []).forEach(lo => {
          unified.push({
            ...lo,
            orderKind: lo.strategy_type === 'SYNTHETIC' || lo.upside_mode || lo.downside_mode ? 'BRACKET' : 'LADDER',
            cancelEndpoint: `/api/trading/ladder-orders/${lo.id}/cancel`
          });
        });
      }

      if (trailingRes.status === 'fulfilled' && trailingRes.value.data?.success) {
        (trailingRes.value.data.trailing_orders || []).forEach(to => {
          unified.push({
            ...to,
            orderKind: 'TRAILING',
            total_quantity: to.quantity,
            total_budget_usd: to.quantity * (to.current_stop_price || 0),
            cancelEndpoint: `/api/trading/trailing-orders/${to.id}/cancel`
          });
        });
      }

      // Sort by creation date desc
      unified.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
      setOrders(unified);
    } catch (err) {
      console.error('Failed to load synthetic orders:', err);
      setActionError(err.response?.data?.error || err.message || 'Failed to load synthetic orders');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadOrders();
  }, [brokerFilter]);

  const toggleExpand = (id) => {
    setExpandedOrders(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleCancelOrder = async (order) => {
    const isBracket = order.orderKind === 'BRACKET' || order.orderKind === 'LADDER';
    const msg = isBracket
      ? `Are you sure you want to cancel synthetic order #${order.id}? Any remaining unfilled rungs will be cancelled.`
      : `Are you sure you want to cancel trailing order #${order.id}?`;

    if (!window.confirm(msg)) return;

    try {
      setCancellingId(order.id);
      setActionError('');
      setActionSuccess('');
      const res = await axios.post(order.cancelEndpoint, {}, { withCredentials: true });
      if (res.data?.success) {
        setActionSuccess(`Order #${order.id} cancelled successfully.`);
        if (onOrderCancelled) onOrderCancelled(order.id);
        loadOrders();
      } else {
        setActionError(res.data?.error || 'Cancellation failed.');
      }
    } catch (err) {
      console.error('Cancellation error:', err);
      setActionError(err.response?.data?.error || err.message || 'Failed to cancel order');
    } finally {
      setCancellingId(null);
    }
  };

  // Filtered orders
  const filteredOrders = orders.filter(o => {
    if (statusFilter === 'ACTIVE' && !['ACTIVE', 'PARTIALLY_FILLED'].includes(o.status)) return false;
    if (statusFilter === 'COMPLETED' && o.status !== 'COMPLETED') return false;
    if (statusFilter === 'CANCELLED' && !['CANCELLED', 'STOPPED_OUT', 'FAILED'].includes(o.status)) return false;
    if (typeFilter !== 'ALL' && o.orderKind !== typeFilter) return false;
    return true;
  });

  return (
    <div className="synthetic-orders-table-container">
      {/* Notifications */}
      {actionSuccess && (
        <div style={{
          padding: '8px 12px',
          borderRadius: '6px',
          background: 'rgba(16, 185, 129, 0.15)',
          border: '1px solid rgba(16, 185, 129, 0.3)',
          color: '#34d399',
          fontSize: '12px',
          marginBottom: '12px'
        }}>
          ✅ {actionSuccess}
        </div>
      )}
      {actionError && (
        <div style={{
          padding: '8px 12px',
          borderRadius: '6px',
          background: 'rgba(239, 68, 68, 0.15)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          color: '#f87171',
          fontSize: '12px',
          marginBottom: '12px'
        }}>
          ⚠️ {actionError}
        </div>
      )}

      {/* Filters Bar */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '14px',
        flexWrap: 'wrap',
        gap: '10px'
      }}>
        {/* Left: Broker & Type Filters */}
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
          {showBrokerFilter && (
            <div style={{ display: 'flex', gap: '4px', background: 'rgba(0,0,0,0.25)', padding: '2px', borderRadius: '6px' }}>
              {[
                { id: 'all', label: 'All Brokers' },
                { id: 'binance', label: 'Binance.US' },
                { id: 'webull', label: 'Webull' }
              ].map(b => (
                <button
                  key={b.id}
                  type="button"
                  onClick={() => setBrokerFilter(b.id)}
                  className={`order-type-btn ${brokerFilter === b.id ? 'active' : ''}`}
                  style={{ padding: '3px 8px', fontSize: '11px' }}
                >
                  {b.label}
                </button>
              ))}
            </div>
          )}

          <div style={{ display: 'flex', gap: '4px', background: 'rgba(0,0,0,0.25)', padding: '2px', borderRadius: '6px' }}>
            {[
              { id: 'ALL', label: 'All Strategies' },
              { id: 'BRACKET', label: '⚡ Smart Bracket' },
              { id: 'LADDER', label: '🪜 Ladder' },
              { id: 'TRAILING', label: '🎯 Trailing' }
            ].map(tf => (
              <button
                key={tf.id}
                type="button"
                onClick={() => setTypeFilter(tf.id)}
                className={`order-type-btn ${typeFilter === tf.id ? 'active' : ''}`}
                style={{ padding: '3px 8px', fontSize: '11px' }}
              >
                {tf.label}
              </button>
            ))}
          </div>
        </div>

        {/* Right: Status Filters & Refresh */}
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          {['ALL', 'ACTIVE', 'COMPLETED', 'CANCELLED'].map(s => (
            <button
              key={s}
              type="button"
              onClick={() => setStatusFilter(s)}
              className={`order-type-btn ${statusFilter === s ? 'active' : ''}`}
              style={{ padding: '3px 8px', fontSize: '11px' }}
            >
              {s}
            </button>
          ))}
          <button
            type="button"
            onClick={loadOrders}
            disabled={loading}
            className="order-type-btn"
            style={{ padding: '3px 8px', fontSize: '11px' }}
            title="Refresh Orders"
          >
            {loading ? '⏳' : '🔄'}
          </button>
        </div>
      </div>

      {/* Main Table */}
      {filteredOrders.length === 0 ? (
        <div style={{
          padding: '36px',
          textAlign: 'center',
          background: 'rgba(30, 41, 59, 0.4)',
          borderRadius: '8px',
          border: '1px solid rgba(255, 255, 255, 0.05)',
          color: '#94a3b8'
        }}>
          {loading ? 'Loading synthetic orders…' : 'No synthetic or smart orders found.'}
        </div>
      ) : (
        <div style={{ overflowX: 'auto', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.08)' }}>
          <table className="order-history-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
            <thead>
              <tr style={{ background: 'rgba(15, 23, 42, 0.8)', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                <th style={{ padding: '10px 12px', textAlign: 'left' }}>Order / Broker</th>
                <th style={{ padding: '10px 12px', textAlign: 'left' }}>Asset / Side</th>
                <th style={{ padding: '10px 12px', textAlign: 'left' }}>Strategy Configuration</th>
                <th style={{ padding: '10px 12px', textAlign: 'left' }}>Execution Progress</th>
                <th style={{ padding: '10px 12px', textAlign: 'center' }}>Status</th>
                <th style={{ padding: '10px 12px', textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredOrders.map(order => {
                const isExpanded = expandedOrders.has(order.id);
                const isSell = order.side === 'SELL';
                const isWebull = (order.broker || '').toLowerCase() === 'webull';
                const rungs = order.rungs || [];
                const tpRungs = rungs.filter(r => r.rung_type !== 'STOP_LOSS');
                const slRungs = rungs.filter(r => r.rung_type === 'STOP_LOSS');

                return (
                  <React.Fragment key={`${order.orderKind}_${order.id}`}>
                    <tr style={{
                      borderBottom: '1px solid rgba(255,255,255,0.05)',
                      background: isExpanded ? 'rgba(30, 41, 59, 0.5)' : 'transparent',
                      transition: 'background 0.2s'
                    }}>
                      {/* 1. Broker & Kind */}
                      <td style={{ padding: '10px 12px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{ fontSize: '15px' }}>
                            {order.orderKind === 'BRACKET' ? '⚡' : order.orderKind === 'TRAILING' ? '🎯' : '🪜'}
                          </span>
                          <div>
                            <div style={{ fontWeight: '700', color: '#fff', fontSize: '12px' }}>
                              #{order.id} {order.orderKind === 'BRACKET' ? 'Smart Bracket' : order.orderKind === 'TRAILING' ? 'Trailing Stop' : 'Ladder'}
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginTop: '2px' }}>
                              <span style={{
                                fontSize: '9.5px',
                                fontWeight: '700',
                                padding: '1px 5px',
                                borderRadius: '4px',
                                background: isWebull ? 'rgba(56, 189, 248, 0.2)' : 'rgba(234, 179, 8, 0.2)',
                                color: isWebull ? '#38bdf8' : '#eab308'
                              }}>
                                {isWebull ? 'Webull' : 'Binance.US'}
                              </span>
                              {order.instrument_type && order.instrument_type !== 'CRYPTO' && (
                                <span style={{ fontSize: '9.5px', color: '#94a3b8' }}>
                                  ({order.instrument_type})
                                </span>
                              )}
                              {order.test_mode && (
                                <span style={{ fontSize: '9px', padding: '1px 4px', borderRadius: '3px', background: 'rgba(168, 85, 247, 0.2)', color: '#c084fc' }}>
                                  TEST
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      </td>

                      {/* 2. Asset & Side */}
                      <td style={{ padding: '10px 12px' }}>
                        <div style={{ fontWeight: '700', fontSize: '13px', color: '#e2e8f0' }}>
                          {order.symbol}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '2px' }}>
                          <span style={{
                            fontSize: '10px',
                            fontWeight: '700',
                            padding: '1px 6px',
                            borderRadius: '4px',
                            background: isSell ? 'rgba(239, 68, 68, 0.2)' : 'rgba(16, 185, 129, 0.2)',
                            color: isSell ? '#f87171' : '#34d399'
                          }}>
                            {order.side}
                          </span>
                          <span style={{ fontSize: '11px', color: '#cbd5e1' }}>
                            {formatNumber(order.total_quantity, 2, 6)}
                          </span>
                        </div>
                      </td>

                      {/* 3. Strategy Configuration */}
                      <td style={{ padding: '10px 12px' }}>
                        {order.orderKind === 'TRAILING' ? (
                          <div>
                            <div style={{ color: '#38bdf8', fontWeight: '600' }}>
                              Trailing {order.trail_value}{order.trail_type === 'AMOUNT' ? '$' : '%'}
                            </div>
                            {order.activation_price && (
                              <div style={{ fontSize: '10px', color: '#94a3b8' }}>
                                Act: ${formatNumber(order.activation_price)}
                              </div>
                            )}
                          </div>
                        ) : (
                          <div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                              <span style={{ fontSize: '10px', color: '#34d399', fontWeight: '700' }}>🟢 UP:</span>
                              <span style={{ color: '#e2e8f0', fontSize: '11px' }}>
                                {order.upside_mode === 'TRAILING'
                                  ? `Trailing (+${order.upside_trail_value || 2}%)`
                                  : order.upside_mode === 'SINGLE'
                                  ? `Target $${formatNumber(order.upside_target_price)}`
                                  : `Ladder (${tpRungs.length} rungs)`}
                              </span>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginTop: '2px' }}>
                              <span style={{ fontSize: '10px', color: '#f87171', fontWeight: '700' }}>🔴 DOWN:</span>
                              <span style={{ color: '#94a3b8', fontSize: '11px' }}>
                                {order.downside_mode === 'TRAILING'
                                  ? `Trailing Stop (-${order.downside_trail_value || 3}%)`
                                  : order.downside_mode === 'LADDER'
                                  ? `Stop Ladder (${slRungs.length} rungs)`
                                  : order.downside_mode === 'SINGLE' || order.has_stop_loss
                                  ? `Floor Stop $${formatNumber(order.downside_target_price || order.stop_loss_trigger_price)}`
                                  : 'None'}
                              </span>
                            </div>
                          </div>
                        )}
                      </td>

                      {/* 4. Execution Progress */}
                      <td style={{ padding: '10px 12px', minWidth: '160px' }}>
                        {order.orderKind === 'TRAILING' ? (
                          <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '3px' }}>
                              <span style={{ color: '#94a3b8' }}>Dynamic Stop:</span>
                              <strong style={{ color: '#f87171' }}>${formatNumber(order.current_stop_price)}</strong>
                            </div>
                            {order.highest_price && (
                              <div style={{ fontSize: '10px', color: '#94a3b8' }}>
                                Peak Watermark: ${formatNumber(order.highest_price)}
                              </div>
                            )}
                          </div>
                        ) : (
                          <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '3px' }}>
                              <span style={{ color: '#94a3b8' }}>Rungs:</span>
                              <strong style={{ color: order.rungs_filled >= order.rungs_total && order.rungs_total > 0 ? '#34d399' : '#38bdf8' }}>
                                {order.rungs_filled || 0} / {order.rungs_total || rungs.length} filled
                              </strong>
                            </div>
                            <div style={{ width: '100%', height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px', overflow: 'hidden' }}>
                              <div style={{
                                width: `${order.rungs_total > 0 ? Math.min(100, ((order.rungs_filled || 0) / order.rungs_total) * 100) : 0}%`,
                                height: '100%',
                                background: 'linear-gradient(90deg, #38bdf8 0%, #34d399 100%)',
                                borderRadius: '3px',
                                transition: 'width 0.3s'
                              }} />
                            </div>
                          </div>
                        )}
                      </td>

                      {/* 5. Status Badge */}
                      <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                        <span style={{
                          padding: '3px 8px',
                          borderRadius: '12px',
                          fontSize: '10.5px',
                          fontWeight: '700',
                          textTransform: 'uppercase',
                          background: order.status === 'COMPLETED'
                            ? 'rgba(16, 185, 129, 0.2)'
                            : order.status === 'ACTIVE'
                            ? 'rgba(56, 189, 248, 0.2)'
                            : order.status === 'PARTIALLY_FILLED'
                            ? 'rgba(234, 179, 8, 0.2)'
                            : order.status === 'STOPPED_OUT'
                            ? 'rgba(239, 68, 68, 0.25)'
                            : 'rgba(148, 163, 184, 0.2)',
                          color: order.status === 'COMPLETED'
                            ? '#34d399'
                            : order.status === 'ACTIVE'
                            ? '#38bdf8'
                            : order.status === 'PARTIALLY_FILLED'
                            ? '#eab308'
                            : order.status === 'STOPPED_OUT'
                            ? '#f87171'
                            : '#94a3b8'
                        }}>
                          {order.status}
                        </span>
                      </td>

                      {/* 6. Actions */}
                      <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '6px' }}>
                          {rungs.length > 0 && (
                            <button
                              type="button"
                              onClick={() => toggleExpand(order.id)}
                              style={{
                                padding: '3px 8px',
                                borderRadius: '4px',
                                background: 'rgba(255,255,255,0.06)',
                                border: '1px solid rgba(255,255,255,0.15)',
                                color: '#cbd5e1',
                                fontSize: '11px',
                                cursor: 'pointer'
                              }}
                            >
                              {isExpanded ? 'Hide ▲' : 'Rungs ▼'}
                            </button>
                          )}
                          {['ACTIVE', 'PARTIALLY_FILLED'].includes(order.status) && (
                            <button
                              type="button"
                              onClick={() => handleCancelOrder(order)}
                              disabled={cancellingId === order.id}
                              style={{
                                padding: '3px 8px',
                                borderRadius: '4px',
                                background: 'rgba(239, 68, 68, 0.2)',
                                border: '1px solid rgba(239, 68, 68, 0.4)',
                                color: '#f87171',
                                fontSize: '11px',
                                cursor: 'pointer'
                              }}
                            >
                              {cancellingId === order.id ? 'Cancelling…' : 'Cancel'}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>

                    {/* Collapsible Drawer for Rungs Details */}
                    {isExpanded && rungs.length > 0 && (
                      <tr>
                        <td colSpan={6} style={{ padding: '12px 16px', background: 'rgba(15, 23, 42, 0.6)' }}>
                          <div style={{ fontSize: '11px', fontWeight: '700', color: '#94a3b8', marginBottom: '8px' }}>
                            Child Execution Rungs ({rungs.length})
                          </div>
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '8px' }}>
                            {rungs.map(rung => {
                              const isStop = rung.rung_type === 'STOP_LOSS';
                              return (
                                <div
                                  key={rung.id || rung.rung_number}
                                  style={{
                                    padding: '8px 10px',
                                    borderRadius: '6px',
                                    background: isStop ? 'rgba(239, 68, 68, 0.08)' : 'rgba(16, 185, 129, 0.08)',
                                    border: `1px solid ${isStop ? 'rgba(239, 68, 68, 0.25)' : 'rgba(16, 185, 129, 0.25)'}`,
                                    display: 'flex',
                                    justifyContent: 'space-between',
                                    alignItems: 'center'
                                  }}
                                >
                                  <div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                      <span style={{ fontSize: '10px', fontWeight: '700', color: isStop ? '#f87171' : '#34d399' }}>
                                        {isStop ? '🛑 STOP' : '🟢 PROFIT'} #{rung.rung_number}
                                      </span>
                                      <span style={{ fontSize: '11px', fontWeight: '700', color: '#fff' }}>
                                        ${formatNumber(rung.target_price)}
                                      </span>
                                      <span style={{ fontSize: '10px', color: isStop ? '#f87171' : '#34d399' }}>
                                        ({rung.price_offset_pct > 0 ? `+${rung.price_offset_pct}` : rung.price_offset_pct}%)
                                      </span>
                                    </div>
                                    <div style={{ fontSize: '10px', color: '#94a3b8', marginTop: '2px' }}>
                                      {formatNumber(rung.quantity, 2, 6)} ({rung.percentage_of_total}%) | Val: ${formatNumber(rung.estimated_usd)}
                                    </div>
                                  </div>
                                  <span style={{
                                    fontSize: '9.5px',
                                    fontWeight: '700',
                                    padding: '1px 5px',
                                    borderRadius: '4px',
                                    background: rung.status === 'FILLED' ? 'rgba(16, 185, 129, 0.25)' : 'rgba(148, 163, 184, 0.15)',
                                    color: rung.status === 'FILLED' ? '#34d399' : '#94a3b8'
                                  }}>
                                    {rung.status}
                                  </span>
                                </div>
                              );
                            })}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default SyntheticOrdersTable;
