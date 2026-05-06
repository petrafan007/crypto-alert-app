import React, { useState } from 'react';
import axios from 'axios';

export default function AddToWatchlist({ onAdd, onClose }) {
  const [symbol, setSymbol] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!symbol.trim()) return;

    setLoading(true);
    setError('');

    try {
      const response = await axios.post('/api/watchlist/add', {
        symbol: symbol.trim().toUpperCase()
      });

      if (response.data.success) {
        onAdd(symbol.trim().toUpperCase());
        setSymbol('');
        onClose();
      } else {
        setError(response.data.error || 'Failed to add to watchlist');
      }
    } catch (err) {
      console.error('Add to watchlist error:', err);
      setError('Failed to add to watchlist. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0, 0, 0, 0.5)',
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      zIndex: 1000
    }}>
      <div style={{
        background: '#232b31',
        padding: '24px',
        borderRadius: 12,
        border: '1px solid #333',
        minWidth: '300px',
        maxWidth: '400px'
      }}>
        <h3 style={{ color: '#4fd1c5', margin: '0 0 16px 0' }}>
          Add to Watchlist
        </h3>
        
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 16 }}>
            <label style={{
              display: 'block',
              marginBottom: 8,
              color: '#fff',
              fontWeight: 500
            }}>
              Symbol (e.g., BTC, ETH)
            </label>
            <input
              type="text"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              placeholder="Enter coin symbol"
              style={{
                width: '100%',
                padding: '12px 16px',
                borderRadius: 8,
                border: '1px solid #444',
                background: '#1a1f23',
                color: '#fff',
                fontSize: '16px',
                boxSizing: 'border-box'
              }}
              autoFocus
            />
          </div>

          {error && (
            <div style={{
              color: '#f56565',
              marginBottom: 16,
              padding: '8px 12px',
              background: 'rgba(245, 101, 101, 0.1)',
              borderRadius: 6,
              border: '1px solid rgba(245, 101, 101, 0.3)'
            }}>
              {error}
            </div>
          )}

          <div style={{ display: 'flex', gap: 12 }}>
            <button
              type="submit"
              disabled={loading || !symbol.trim()}
              style={{
                flex: 1,
                padding: '12px 16px',
                borderRadius: 8,
                border: 'none',
                background: loading ? '#666' : '#4fd1c5',
                color: '#fff',
                fontSize: '16px',
                fontWeight: 600,
                cursor: loading ? 'not-allowed' : 'pointer',
                transition: 'background 0.2s'
              }}
            >
              {loading ? 'Adding...' : 'Add to Watchlist'}
            </button>
            <button
              type="button"
              onClick={onClose}
              style={{
                padding: '12px 16px',
                borderRadius: 8,
                border: '1px solid #666',
                background: 'transparent',
                color: '#fff',
                fontSize: '16px',
                cursor: 'pointer',
                transition: 'background 0.2s'
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
} 