import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';

const QuickTradeWidget = ({ isLightMode, portfolio = [] }) => {
  const navigate = useNavigate();
  const [selectedCoin, setSelectedCoin] = useState('BTC');
  const [side, setSide] = useState('BUY');
  const [amountPct, setAmountPct] = useState(25);

  const availableCoins = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE', 'ONT'];

  const handleGoToTrade = () => {
    navigate('/trading', {
      state: {
        tradePrefill: {
          symbol: `${selectedCoin}USDT`,
          side: side === 'SELL' ? 'SELL' : 'BUY',
          baseCoin: selectedCoin
        }
      }
    });
  };

  return (
    <div className="widget-panel-inner" style={{ padding: '16px', height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: 'var(--text-primary, #fff)', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>⚡</span> Quick Trade Terminal
        </h3>
        <span style={{ fontSize: '11px', color: '#38bdf8', fontWeight: '600' }}>Instant</span>
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px', minHeight: 0, justifyContent: 'center' }}>
        {/* Buy / Sell Tabs */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px', background: 'rgba(0,0,0,0.3)', padding: '3px', borderRadius: '8px' }}>
          <button
            type="button"
            onClick={() => setSide('BUY')}
            style={{
              padding: '6px',
              borderRadius: '6px',
              border: 'none',
              background: side === 'BUY' ? '#22c55e' : 'transparent',
              color: '#fff',
              fontWeight: '700',
              fontSize: '12px',
              cursor: 'pointer'
            }}
          >
            Buy {selectedCoin}
          </button>
          <button
            type="button"
            onClick={() => setSide('SELL')}
            style={{
              padding: '6px',
              borderRadius: '6px',
              border: 'none',
              background: side === 'SELL' ? '#ef4444' : 'transparent',
              color: '#fff',
              fontWeight: '700',
              fontSize: '12px',
              cursor: 'pointer'
            }}
          >
            Sell {selectedCoin}
          </button>
        </div>

        {/* Coin Selector */}
        <div style={{ display: 'flex', gap: '4px', overflowX: 'auto', paddingBottom: '4px' }}>
          {availableCoins.map(c => (
            <button
              key={c}
              type="button"
              onClick={() => setSelectedCoin(c)}
              style={{
                padding: '4px 8px',
                borderRadius: '6px',
                border: selectedCoin === c ? '1px solid #38bdf8' : '1px solid rgba(255,255,255,0.08)',
                background: selectedCoin === c ? 'rgba(56, 189, 248, 0.15)' : 'rgba(255,255,255,0.04)',
                color: selectedCoin === c ? '#38bdf8' : '#94a3b8',
                fontSize: '12px',
                fontWeight: '600',
                cursor: 'pointer'
              }}
            >
              {c}
            </button>
          ))}
        </div>

        {/* Quick Percentage Buttons */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '4px' }}>
          {[25, 50, 75, 100].map(pct => (
            <button
              key={pct}
              type="button"
              onClick={() => setAmountPct(pct)}
              style={{
                padding: '4px',
                borderRadius: '4px',
                border: amountPct === pct ? '1px solid #38bdf8' : '1px solid rgba(255,255,255,0.06)',
                background: amountPct === pct ? 'rgba(56, 189, 248, 0.2)' : 'rgba(255,255,255,0.03)',
                color: amountPct === pct ? '#38bdf8' : '#94a3b8',
                fontSize: '11px',
                fontWeight: '600',
                cursor: 'pointer'
              }}
            >
              {pct}%
            </button>
          ))}
        </div>

        {/* Launch Button */}
        <button
          type="button"
          onClick={handleGoToTrade}
          style={{
            marginTop: 'auto',
            padding: '8px',
            borderRadius: '6px',
            border: 'none',
            background: side === 'BUY' ? 'linear-gradient(135deg, #22c55e, #16a34a)' : 'linear-gradient(135deg, #ef4444, #dc2626)',
            color: '#fff',
            fontWeight: '700',
            fontSize: '13px',
            cursor: 'pointer',
            boxShadow: '0 2px 8px rgba(0,0,0,0.3)'
          }}
        >
          Open {selectedCoin}/USDT Terminal
        </button>
      </div>
    </div>
  );
};

export default QuickTradeWidget;
