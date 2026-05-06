import React, { useEffect, useState } from 'react';
import axios from 'axios';
import PriceHistoryPopup from '../components/PriceHistoryPopup';
import ValidationPopup from '../components/ValidationPopup';
import { getTradeUrl } from '../utils/exchangeUtils';

const TABLE_HEADER_GROUP_STYLE = {
  display: 'table-header-group'
};

const TABLE_HEADER_ROW_STYLE = {
  display: 'table-row',
  background: '#1a1f23'
};

const BASE_HEADER_CELL_STYLE = {
  padding: '12px',
  textAlign: 'left',
  borderBottom: '1px solid #333',
  display: 'table-cell'
};

const ACCENT_HEADER_CELL_STYLE = {
  ...BASE_HEADER_CELL_STYLE,
  color: '#4fd1c5'
};

const BODY_CELL_STYLE = {
  padding: '12px',
  display: 'table-cell'
};

export default function Portfolio() {
  const [portfolio, setPortfolio] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [pendingOrders, setPendingOrders] = useState([]);
  
  // Hover popup state
  const [hoverPopup, setHoverPopup] = useState({
    isVisible: false,
    symbol: null,
    position: { x: 0, y: 0 }
  });
  const hoverTimeoutRef = React.useRef(null);

  // Validation popup state
  const [showValidation, setShowValidation] = useState(false);
  
  // Pending order tooltip state
  const [orderTooltip, setOrderTooltip] = useState({
    isVisible: false,
    text: '',
    position: { x: 0, y: 0 }
  });

  useEffect(() => {
    // Fetch portfolio data
    async function fetchPortfolio() {
      try {
        const res = await axios.get('/api/coin-data-live');
        // Only filter out coins if they have a hidden property set to true
        const allCoins = res.data.portfolio || [];
        const visibleCoins = allCoins.filter(coin => !coin.hidden);
        setPortfolio(visibleCoins);
      } catch (err) {
        console.error('Portfolio fetch error:', err);
        setError('Failed to load portfolio data.');
      }
      setLoading(false);
    }
    
    // Fetch pending orders from Binance
    async function fetchPendingOrders() {
      try {
        const res = await axios.get('/api/pending-orders');
        setPendingOrders(res.data.pending_orders || []);
      } catch (err) {
        console.error('Pending orders fetch error:', err);
        // Don't show error to user, just log it
      }
    }
    
    // Fetch immediately
    fetchPortfolio();
    fetchPendingOrders();
    
    // Set up 60-second interval for live updates
    const updateInterval = setInterval(() => {
      fetchPortfolio();
      fetchPendingOrders();
    }, 60000); // 60 seconds
    
    // Cleanup interval on unmount
    return () => {
      clearInterval(updateInterval);
    };
  }, []);

  // Hover popup functions
  const handleSymbolHover = (symbol, event) => {
    // Clear any existing timeout
    if (hoverTimeoutRef.current) {
      clearTimeout(hoverTimeoutRef.current);
    }
    
    // Only update if symbol changed or popup is not visible
    if (hoverPopup.symbol !== symbol || !hoverPopup.isVisible) {
      const rect = event.currentTarget.getBoundingClientRect();
      setHoverPopup({
        isVisible: true,
        symbol: symbol,
        position: {
          x: rect.left + rect.width / 2 - 150, // Center above symbol (popup width is ~300px)
          y: rect.top - 250 // Position above symbol
        }
      });
    }
  };

  const handleSymbolLeave = () => {
    // Add a small delay before closing to prevent flickering when moving between elements
    hoverTimeoutRef.current = setTimeout(() => {
      setHoverPopup({
        isVisible: false,
        symbol: null,
        position: { x: 0, y: 0 }
      });
    }, 100);
  };

  const handleChartClick = (symbol) => {
    // Open the exchange in a new tab
    window.open(getTradeUrl(symbol), '_blank');
  };

  // Check if a coin has pending orders
  const getPendingOrdersForCoin = (symbol) => {
    if (!pendingOrders || !Array.isArray(pendingOrders)) return [];
    return pendingOrders.filter(order => order.asset === symbol);
  };

  // Generate tooltip text for pending orders
  const generateOrderTooltipText = (orders) => {
    if (orders.length === 0) return '';
    
    if (orders.length === 1) {
      const order = orders[0];
      const orderTypeName = order.type === 'STOP_LOSS_LIMIT' ? 'stop limit' : 'limit';
      return `There is a current pending ${orderTypeName} for this coin when it ${order.direction} ${order.trigger_price.toFixed(4)} USDT`;
    } else {
      // Multiple orders (OCO or multiple separate orders)
      const orderTexts = orders.map(order => {
        const orderTypeName = order.type === 'STOP_LOSS_LIMIT' ? 'stop limit' : 'limit';
        return `${order.direction} ${order.trigger_price.toFixed(4)} USDT`;
      });
      return `There is a current pending order for this coin when it ${orderTexts.join(' or ')}`;
    }
  };

  // Handle hover on row for pending order tooltip
  const handleRowHover = (coin, event) => {
    const orders = getPendingOrdersForCoin(coin.symbol);
    if (orders.length > 0) {
      const rect = event.currentTarget.getBoundingClientRect();
      setOrderTooltip({
        isVisible: true,
        text: generateOrderTooltipText(orders),
        position: {
          x: event.clientX,
          y: rect.top - 60
        }
      });
    }
  };

  const handleRowLeave = () => {
    setOrderTooltip({
      isVisible: false,
      text: '',
      position: { x: 0, y: 0 }
    });
  };

  // Sync portfolio with exchange
  const syncPortfolio = async () => {
    try {
      setLoading(true);
      await axios.post('/api/sync-portfolio');
      // Refresh portfolio data after sync using live endpoint
      const res = await axios.get('/api/coin-data-live');
      setPortfolio(res.data.portfolio || []);
    } catch (err) {
      console.error('Portfolio sync error:', err);
      setError('Failed to sync portfolio');
    }
    setLoading(false);
  };

  if (loading) {
    return (
      <div style={{ 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center', 
        height: '50vh',
        color: '#fff',
        fontSize: '18px'
      }}>
        Loading portfolio...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ 
        padding: '24px',
        color: '#f56565',
        textAlign: 'center',
        background: 'rgba(245, 101, 101, 0.1)',
        borderRadius: 8,
        border: '1px solid rgba(245, 101, 101, 0.3)'
      }}>
        {error}
      </div>
    );
  }

  return (
    <div style={{ color: '#fff' }}>
      <div style={{ 
        display: 'flex', 
        justifyContent: 'space-between', 
        alignItems: 'center', 
        marginBottom: 24 
      }}>
        <h1 style={{ color: '#4fd1c5', margin: 0 }}>Portfolio</h1>
        <button
          onClick={() => setShowValidation(true)}
          style={{
            background: '#4fd1c5',
            color: '#1a1f23',
            border: 'none',
            padding: '12px 20px',
            borderRadius: '8px',
            fontWeight: '600',
            cursor: 'pointer',
            fontSize: '0.95rem',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            transition: 'all 0.2s ease'
          }}
          onMouseOver={(e) => e.target.style.background = '#38b2ac'}
          onMouseOut={(e) => e.target.style.background = '#4fd1c5'}
        >
          🛡️ Failsafe Validation
        </button>
      </div>
      
      <div 
        className="table-container portfolio-table"
        style={{ 
          background: '#232b31', 
          borderRadius: 12,
          overflow: 'auto',
          border: '1px solid #333'
        }}
      >
        <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'auto', display: 'table' }}>
          <thead style={TABLE_HEADER_GROUP_STYLE}>
            <tr style={TABLE_HEADER_ROW_STYLE}>
              <th style={BASE_HEADER_CELL_STYLE}>Symbol</th>
              <th style={ACCENT_HEADER_CELL_STYLE}>Amount</th>
              <th style={ACCENT_HEADER_CELL_STYLE}>Initial Price</th>
              <th style={ACCENT_HEADER_CELL_STYLE}>Current Price</th>
              <th style={ACCENT_HEADER_CELL_STYLE}>Current Value</th>
              <th style={ACCENT_HEADER_CELL_STYLE}>% Change</th>
              <th style={BASE_HEADER_CELL_STYLE}>Purchase Date</th>
            </tr>
          </thead>
          <tbody>
            {!Array.isArray(portfolio) || portfolio.length === 0 ? (
              <tr>
                <td 
                  colSpan="7" 
                  style={{ 
                    ...BODY_CELL_STYLE, 
                    padding: '20px', 
                    textAlign: 'center', 
                    color: '#666' 
                  }}
                >
                  No portfolio data available
                </td>
              </tr>
            ) : (
              portfolio.map((coin, idx) => {
                const hasPendingOrders = getPendingOrdersForCoin(coin.symbol).length > 0;
                return (
                  <tr 
                    key={coin.symbol} 
                    style={{ 
                      borderBottom: '1px solid #333',
                      backgroundColor: hasPendingOrders ? '#3d3d1a' : 'transparent',
                      position: 'relative'
                    }}
                    onMouseEnter={(e) => handleRowHover(coin, e)}
                    onMouseLeave={handleRowLeave}
                  >
                    <td 
                      style={{ 
                        ...BODY_CELL_STYLE,
                        fontWeight: 'bold',
                        cursor: 'pointer'
                      }}
                      onMouseEnter={(e) => {
                        handleSymbolHover(coin.symbol, e);
                        handleRowLeave(); // Hide order tooltip when hovering over symbol
                      }}
                      onMouseLeave={handleSymbolLeave}
                      onClick={() => handleChartClick(coin.symbol)}
                      title="Hover for 7-day chart, click to open on Binance"
                    >
                      {coin.symbol}
                    </td>
                    <td style={BODY_CELL_STYLE}>{coin.amount ? coin.amount.toFixed(4) : '—'}</td>
                    <td style={BODY_CELL_STYLE}>
                      {coin.avg_entry ? `$${coin.avg_entry.toFixed(4)}` : '—'}
                    </td>
                    <td style={BODY_CELL_STYLE}>
                      {coin.current_price ? `$${coin.current_price.toFixed(4)}` : '—'}
                    </td>
                    <td style={BODY_CELL_STYLE}>
                      {coin.current_value ? `$${coin.current_value.toFixed(2)}` : '—'}
                    </td>
                    <td style={BODY_CELL_STYLE}>
                      {coin.pct_change !== undefined ? (
                        <span style={{ color: coin.pct_change >= 0 ? '#48bb78' : '#f56565' }}>
                          {coin.pct_change >= 0 ? '+' : ''}{coin.pct_change.toFixed(2)}%
                        </span>
                      ) : '—'}
                    </td>
                    <td style={BODY_CELL_STYLE}>{coin.purchase_date ? coin.purchase_date.split(' ')[0] : '—'}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Price History Popup */}
      <PriceHistoryPopup
        symbol={hoverPopup.symbol}
        isVisible={hoverPopup.isVisible}
        position={hoverPopup.position}
        onClose={handleSymbolLeave}
        onChartClick={handleChartClick}
      />

      {/* Pending Order Tooltip */}
      {orderTooltip.isVisible && (
        <div
          style={{
            position: 'fixed',
            left: `${orderTooltip.position.x}px`,
            top: `${orderTooltip.position.y}px`,
            background: 'rgba(255, 255, 0, 0.95)',
            color: '#000',
            padding: '8px 12px',
            borderRadius: '6px',
            fontSize: '13px',
            fontWeight: '500',
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            zIndex: 10000,
            maxWidth: '300px',
            pointerEvents: 'none',
            border: '2px solid #ffd700'
          }}
        >
          {orderTooltip.text}
        </div>
      )}

      {/* Validation Popup */}
      <ValidationPopup
        isVisible={showValidation}
        onClose={() => setShowValidation(false)}
        onSync={syncPortfolio}
      />
    </div>
  );
}
