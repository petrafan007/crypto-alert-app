import React, { useState, useEffect } from 'react';
import axios from 'axios';
import CryptoIcon from './CryptoIcon';

export const parseOrderData = (order) => {
  const isBuy = (order.side || '').toUpperCase() === 'BUY';
  const rawSymbol = (order.symbol || '').toUpperCase();
  const baseSymbol = rawSymbol.replace(/(USDT|USD|BUSD|USDC)$/, '') || rawSymbol;

  // Determine Quantity
  const rawTotalQty = parseFloat(order.quantity ?? order.orig_qty ?? order.origQty ?? order.amount ?? 0);
  const rawFilledQty = parseFloat(order.filled_quantity ?? order.executed_quantity ?? order.executedQty ?? order.filled_size ?? 0);
  const qty = rawTotalQty > 0 ? rawTotalQty : (rawFilledQty > 0 ? rawFilledQty : 0);

  // Determine Price
  const rawPlacedPrice = parseFloat(order.price ?? order.limit_price ?? 0);
  const rawFilledPrice = parseFloat(order.filled_price ?? order.avg_fill_price ?? order.avg_price ?? order.executed_price ?? order.avg_entry ?? order.price_sold_at ?? 0);
  
  let calcPrice = 0;
  if (order.cummulativeQuoteQty && rawFilledQty > 0) {
    calcPrice = parseFloat(order.cummulativeQuoteQty) / rawFilledQty;
  }

  let price = 0;
  if (rawFilledPrice > 0) {
    price = rawFilledPrice;
  } else if (calcPrice > 0) {
    price = calcPrice;
  } else if (rawPlacedPrice > 0) {
    price = rawPlacedPrice;
  }

  // Determine Total Quote Value
  let total = 0;
  if (order.cummulativeQuoteQty && parseFloat(order.cummulativeQuoteQty) > 0) {
    total = parseFloat(order.cummulativeQuoteQty);
  } else if (price > 0 && qty > 0) {
    total = price * qty;
  }

  // Format Quantity string
  let qtyStr = '--';
  if (qty > 0) {
    if (qty >= 1000) {
      qtyStr = qty.toLocaleString('en-US', { maximumFractionDigits: 2 });
    } else if (qty >= 1) {
      qtyStr = qty.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
    } else {
      qtyStr = Number(qty.toFixed(6)).toString();
    }
  }

  // Format Price string
  let priceStr = '$--';
  if (price > 0) {
    if (price >= 1) {
      priceStr = `$${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    } else {
      priceStr = `$${price.toFixed(4)}`;
    }
  } else if (String(order.order_type || order.type || '').toUpperCase() === 'MARKET') {
    priceStr = '@ MKT';
  }

  // Normalize Status
  const rawStatus = (order.status || 'FILLED').toUpperCase();
  const status = rawStatus === 'OPEN' ? 'NEW' : rawStatus === 'CANCELLED' ? 'CANCELED' : rawStatus;

  return {
    isBuy,
    baseSymbol,
    symbol: rawSymbol || baseSymbol,
    qty,
    qtyStr,
    price,
    priceStr,
    total,
    status,
    rawStatus,
    orderType: (order.order_type || order.type || 'LIMIT').toUpperCase()
  };
};

const getStatusBadgeStyle = (status) => {
  switch (status) {
    case 'FILLED':
      return { background: 'rgba(34, 197, 94, 0.15)', color: '#4ade80', border: '1px solid rgba(34, 197, 94, 0.3)' };
    case 'NEW':
      return { background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', border: '1px solid rgba(56, 189, 248, 0.3)' };
    case 'CANCELED':
      return { background: 'rgba(148, 163, 184, 0.15)', color: '#94a3b8', border: '1px solid rgba(148, 163, 184, 0.3)' };
    case 'PARTIALLY_FILLED':
      return { background: 'rgba(245, 158, 11, 0.15)', color: '#fbbf24', border: '1px solid rgba(245, 158, 11, 0.3)' };
    default:
      return { background: 'rgba(148, 163, 184, 0.15)', color: '#94a3b8', border: '1px solid rgba(148, 163, 184, 0.3)' };
  }
};

const RecentTradesWidget = ({ isLightMode, config, onEdit }) => {
  const [allTrades, setAllTrades] = useState([]);
  const [loading, setLoading] = useState(true);

  const maxOrders = config?.maxOrders !== undefined ? Math.max(0, Math.min(20, config.maxOrders)) : 5;
  const statusFilters = Array.isArray(config?.statusFilters) && config.statusFilters.length > 0
    ? config.statusFilters
    : ['FILLED', 'NEW', 'CANCELED', 'PARTIALLY_FILLED'];

  useEffect(() => {
    let cancelled = false;
    const fetchTrades = async () => {
      try {
        let orderList = [];
        try {
          const res = await axios.get('/api/trading/real-orders?limit=50', { withCredentials: true });
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
          setAllTrades(orderList);
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

  // Filter and parse orders
  const parsedOrders = allTrades.map(order => ({
    raw: order,
    parsed: parseOrderData(order)
  }));

  const filteredOrders = parsedOrders.filter(({ parsed }) => {
    return statusFilters.includes(parsed.status) || statusFilters.includes(parsed.rawStatus);
  });

  const visibleOrders = maxOrders > 0 ? filteredOrders.slice(0, maxOrders) : [];

  return (
    <div className="widget-panel-inner" style={{ padding: '16px', height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: 'var(--text-primary, #fff)', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>📜</span> Recent Order History
        </h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '11px', color: '#94a3b8' }}>
            {maxOrders === 0 ? '0 Orders' : `Latest ${maxOrders}`}
          </span>
          {onEdit && (
            <button
              type="button"
              onClick={onEdit}
              title="Customize order history settings"
              style={{
                background: 'rgba(56, 189, 248, 0.12)',
                border: '1px solid rgba(56, 189, 248, 0.25)',
                color: '#38bdf8',
                cursor: 'pointer',
                padding: '2px 5px',
                fontSize: '11px',
                borderRadius: '4px',
                lineHeight: 1,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.15s ease'
              }}
            >
              ✏️
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: '13px' }}>
          Loading trade history...
        </div>
      ) : maxOrders === 0 ? (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: '13px', gap: '8px' }}>
          <span>Display limit is set to 0 orders.</span>
          {onEdit && (
            <button
              type="button"
              onClick={onEdit}
              style={{
                background: 'rgba(56, 189, 248, 0.15)',
                border: '1px solid #38bdf8',
                color: '#38bdf8',
                padding: '4px 10px',
                borderRadius: '6px',
                fontSize: '12px',
                cursor: 'pointer'
              }}
            >
              ✏️ Customize
            </button>
          )}
        </div>
      ) : visibleOrders.length === 0 ? (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: '13px', gap: '6px', textAlign: 'center', padding: '10px' }}>
          <span>No recent orders found matching selected filters.</span>
          {onEdit && (
            <button
              type="button"
              onClick={onEdit}
              style={{
                background: 'none',
                border: 'none',
                color: '#38bdf8',
                fontSize: '12px',
                cursor: 'pointer',
                textDecoration: 'underline'
              }}
            >
              Adjust Status Filters ✏️
            </button>
          )}
        </div>
      ) : (
        <div className="custom-scrollbar" style={{ flex: 1, overflowY: 'auto', minHeight: 0, display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {visibleOrders.map(({ raw, parsed }, idx) => {
            const badgeStyle = getStatusBadgeStyle(parsed.status);
            return (
              <div
                key={raw.id || raw.order_id || idx}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '6px 10px',
                  borderRadius: '6px',
                  background: parsed.isBuy ? 'rgba(34, 197, 94, 0.05)' : 'rgba(239, 68, 68, 0.05)',
                  border: `1px solid ${parsed.isBuy ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)'}`,
                  fontSize: '12px'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                  <span
                    style={{
                      fontSize: '10px',
                      fontWeight: '700',
                      padding: '2px 5px',
                      borderRadius: '4px',
                      background: parsed.isBuy ? 'rgba(34, 197, 94, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                      color: parsed.isBuy ? '#4ade80' : '#f87171',
                      flexShrink: 0
                    }}
                  >
                    {parsed.isBuy ? 'BUY' : 'SELL'}
                  </span>
                  <CryptoIcon symbol={parsed.baseSymbol} size={16} />
                  <span style={{ fontWeight: '600', color: 'var(--text-primary, #fff)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {parsed.symbol}
                  </span>
                </div>

                <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: '8px' }}>
                  <div style={{ fontWeight: '600', color: 'var(--text-primary, #fff)' }}>
                    {parsed.qtyStr} @ {parsed.priceStr}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '5px', marginTop: '2px' }}>
                    <span
                      style={{
                        fontSize: '9px',
                        fontWeight: '600',
                        padding: '1px 4px',
                        borderRadius: '3px',
                        ...badgeStyle
                      }}
                    >
                      {parsed.status}
                    </span>
                    {parsed.total > 0 && (
                      <span style={{ fontSize: '10px', color: '#94a3b8' }}>
                        (${Number(parsed.total || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })})
                      </span>
                    )}
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
