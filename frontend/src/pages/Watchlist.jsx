import React, { useEffect, useState } from 'react';
import axios from 'axios';
import AddToWatchlist from '../components/AddToWatchlist';
import PriceHistoryPopup from '../components/PriceHistoryPopup';
import { getTradeUrl } from '../utils/exchangeUtils';

export default function Watchlist() {
  const [watchlist, setWatchlist] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showAddModal, setShowAddModal] = useState(false);
  
  // Hover popup state
  const [hoverPopup, setHoverPopup] = useState({
    isVisible: false,
    symbol: null,
    position: { x: 0, y: 0 }
  });
  const hoverTimeoutRef = React.useRef(null);

  const fetchWatchlist = async (isInitialLoad = true) => {
    try {
      if (isInitialLoad) {
        setLoading(true);
      }
      
      const res = await axios.get('/api/watchlist');
      setWatchlist(res.data || []);
      
      if (isInitialLoad) {
        setLoading(false);
      }
    } catch (err) {
      console.error('Watchlist fetch error:', err);
      if (isInitialLoad) {
      setError('Failed to load watchlist data.');
    }
    } finally {
      if (isInitialLoad) {
    setLoading(false);
      }
    }
  };

  useEffect(() => {
    let refreshInterval;
    
    // Initial load - show data immediately
    fetchWatchlist(true);
    
    // Set up background refresh every 60 seconds
    refreshInterval = setInterval(() => {
      fetchWatchlist(false);
    }, 60000);
    
    // Cleanup interval on unmount
    return () => {
      if (refreshInterval) {
        clearInterval(refreshInterval);
      }
    };
  }, []);

  const handleAddToWatchlist = (symbol) => {
    // Refresh the watchlist after adding
    fetchWatchlist();
  };

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
        Loading watchlist...
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
        <h1 style={{ color: '#4fd1c5', margin: 0 }}>Watchlist</h1>
        <button
          onClick={() => setShowAddModal(true)}
          style={{
            background: '#4fd1c5',
            color: '#fff',
            border: 'none',
            padding: '12px 20px',
            borderRadius: 8,
            fontSize: '16px',
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'background 0.2s'
          }}
          onMouseEnter={(e) => e.target.style.background = '#38b2ac'}
          onMouseLeave={(e) => e.target.style.background = '#4fd1c5'}
        >
          + Add Coin
        </button>
      </div>
      
      <div style={{ 
        background: '#232b31', 
        borderRadius: 12,
        overflow: 'auto',
        border: '1px solid #333'
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#1a1f23' }}>
              <th style={{ padding: '12px', textAlign: 'left', borderBottom: '1px solid #333' }}>★</th>
              <th style={{ padding: '12px', textAlign: 'left', borderBottom: '1px solid #333' }}>Symbol</th>
              <th style={{ padding: '12px', textAlign: 'left', borderBottom: '1px solid #333' }}>Down Alert</th>
              <th style={{ padding: '12px', textAlign: 'left', borderBottom: '1px solid #333' }}>Up Alert</th>
              <th style={{ padding: '12px', textAlign: 'left', borderBottom: '1px solid #333' }}>Alert</th>
              <th style={{ padding: '12px', textAlign: 'left', borderBottom: '1px solid #333' }}>Note</th>
              <th style={{ padding: '12px', textAlign: 'left', borderBottom: '1px solid #333' }}>Sentiment</th>
              <th style={{ padding: '12px', textAlign: 'left', borderBottom: '1px solid #333' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {!Array.isArray(watchlist) || watchlist.length === 0 ? (
              <tr>
                <td colSpan="8" style={{ padding: '20px', textAlign: 'center', color: '#666' }}>
                  No watchlist data available. Add some coins to get started!
                </td>
              </tr>
            ) : (
              watchlist.map((item, idx) => (
                <tr key={item.symbol} style={{ borderBottom: '1px solid #333' }}>
                  <td style={{ padding: '12px' }}>{item.favorite ? '★' : '☆'}</td>
                  <td 
                    style={{ 
                      padding: '12px', 
                      fontWeight: 'bold',
                      cursor: 'pointer'
                    }}
                    onMouseEnter={(e) => handleSymbolHover(item.symbol, e)}
                    onMouseLeave={handleSymbolLeave}
                    onClick={() => handleChartClick(item.symbol)}
                    title="Hover for 7-day chart, click to open on Binance"
                  >
                    {item.symbol}
                  </td>
                  <td style={{ padding: '12px' }}>
                    {item.down_val ? `$${item.down_val}` : '—'}
                  </td>
                  <td style={{ padding: '12px' }}>
                    {item.up_val ? `$${item.up_val}` : '—'}
                  </td>
                  <td style={{ padding: '12px' }}>
                    {item.alert_enabled ? '🔔' : '🔕'}
                  </td>
                  <td style={{ padding: '12px' }}>{item.note || '—'}</td>
                  <td style={{ padding: '12px' }}>{item.action || 'Watch'}</td>
                  <td style={{ padding: '12px' }}>
                    <button
                      className="trade-action-btn buy"
                      onClick={() => window.location.href = `/trading?symbol=${item.symbol}USDT`}
                    >
                      Buy
                    </button>
                    <button
                      className="trade-action-btn delete"
                      onClick={async () => {
                        try {
                          await axios.post('/api/watchlist/remove', { symbol: item.symbol });
                          fetchWatchlist(); // Refresh the list
                        } catch (err) {
                          console.error('Remove from watchlist error:', err);
                        }
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {showAddModal && (
        <AddToWatchlist
          onAdd={handleAddToWatchlist}
          onClose={() => setShowAddModal(false)}
        />
      )}

      {/* Price History Popup */}
      <PriceHistoryPopup
        symbol={hoverPopup.symbol}
        isVisible={hoverPopup.isVisible}
        position={hoverPopup.position}
        onClose={handleSymbolLeave}
        onChartClick={handleChartClick}
      />
    </div>
  );
}
