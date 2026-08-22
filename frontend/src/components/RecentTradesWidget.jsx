import React, { useState, useEffect } from 'react';
import axios from 'axios';
import CryptoIcon from './CryptoIcon';

const RecentTradesWidget = ({ isLightMode }) => {
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetchTrades = async () => {
      try {
        let orderList = [];
        try {
          const res = await axios.get('/api/trading/real-orders?limit=10', { withCredentials: true });
          if (Array.isArray(res.data?.orders)) {
            orderList = res.data.orders;
          }
        } catch (e) {
          // Fallback to /api/orders
          const fallbackRes = await axios.get('/api/orders', { withCredentials: true });
          if (Array.isArray(fallbackRes.data?.orders)) {
            orderList = fallbackRes.data.orders;
          }
        }

        if (!cancelled) {
          setTrades(orderList.slice(0, 5));
          setLoading(false);
        }
      } catch (err) {
        console.error('Failed to load recent trades:', err);
        if (!cancelled) setLoading(false);
      }
    };

    fetchTrades();
    const interval = setInterval(fetchTrades, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="widget-panel-inner" style={{ padding: '16px', height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: 'var(--text-primary, #fff)', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>📜</span> Recent Order History
        </h3>
        <span style={{ fontSize: '11px', color: '#94a3b8' }}>Latest 5</span>
      </div>

      {loading ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: '13px' }}>
          Loading trade history...
        </div>
      ) : trades.length === 0 ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: '13px' }}>
          No recent executed orders.
        </div>
      ) : (
        <div className="custom-scrollbar" style={{ flex: 1, overflowY: 'auto', minHeight: 0, display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {trades.map((order, idx) => {
            const isBuy = (order.side || '').toUpperCase() === 'BUY';
            const baseSymbol = (order.symbol || '').replace(/(USDT|USD)$/, '');
            const price = parseFloat(order.price || order.executed_price || 0);
            const qty = parseFloat(order.orig_qty || order.amount || 0);
            const total = price * qty;

            return (
              <div
                key={order.id || order.order_id || idx}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '6px 10px',
                  borderRadius: '6px',
                  background: isBuy ? 'rgba(34, 197, 94, 0.05)' : 'rgba(239, 68, 68, 0.05)',
                  border: `1px solid ${isBuy ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)'}`,
                  fontSize: '12px'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span
                    style={{
                      fontSize: '10px',
                      fontWeight: '700',
                      padding: '2px 5px',
                      borderRadius: '4px',
                      background: isBuy ? 'rgba(34, 197, 94, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                      color: isBuy ? '#4ade80' : '#f87171'
                    }}
                  >
                    {isBuy ? 'BUY' : 'SELL'}
                  </span>
                  <CryptoIcon symbol={baseSymbol} size={16} />
                  <span style={{ fontWeight: '600', color: 'var(--text-primary, #fff)' }}>
                    {order.symbol || baseSymbol}
                  </span>
                </div>

                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontWeight: '600', color: 'var(--text-primary, #fff)' }}>
                    {qty > 0 ? qty.toFixed(4) : '--'} @ ${price > 0 ? price.toFixed(2) : '--'}
                  </div>
                  <div style={{ fontSize: '10px', color: '#94a3b8' }}>
                    {order.status || 'FILLED'} {total > 0 && `($${total.toFixed(2)})`}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default RecentTradesWidget;
