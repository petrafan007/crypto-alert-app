import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';

const QuickTradeWidget = ({ isLightMode, portfolio = [], accountScope = 'binance' }) => {
  const navigate = useNavigate();
  const [exchangeMode, setExchangeMode] = useState(accountScope === 'webull' ? 'webull' : 'binance');

  // Keep mode in sync when accountScope prop changes explicitly
  React.useEffect(() => {
    if (accountScope === 'webull') setExchangeMode('webull');
    else if (accountScope === 'binance') setExchangeMode('binance');
  }, [accountScope]);

  const defaultCryptoList = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE', 'ONT'];
  const defaultStockList = ['AAPL', 'NVDA', 'TSLA', 'SPY', 'QQQ', 'AMZN', 'MSFT'];

  // Dynamically extract user's portfolio tickers
  const availableCoins = React.useMemo(() => {
    const portfolioCrypto = portfolio
      .filter((p) => !p.is_external && p.source !== 'webull')
      .map((p) => String(p.symbol || '').toUpperCase())
      .filter(Boolean);
    return Array.from(new Set([...portfolioCrypto, ...defaultCryptoList])).slice(0, 10);
  }, [portfolio]);

  const availableStocks = React.useMemo(() => {
    const portfolioStocks = portfolio
      .filter((p) => p.is_external || p.source === 'webull')
      .map((p) => String(p.symbol || '').toUpperCase())
      .filter(Boolean);
    return Array.from(new Set([...portfolioStocks, ...defaultStockList])).slice(0, 10);
  }, [portfolio]);

  const isWebull = exchangeMode === 'webull';
  const symbols = isWebull ? availableStocks : availableCoins;
  const [selectedSymbol, setSelectedSymbol] = useState(isWebull ? (availableStocks[0] || 'AAPL') : 'BTC');
  const [side, setSide] = useState('BUY');
  const [amountPct, setAmountPct] = useState(25);

  // Switch default symbol when toggling exchange mode
  const handleExchangeChange = (mode) => {
    setExchangeMode(mode);
    setSelectedSymbol(mode === 'webull' ? (availableStocks[0] || 'AAPL') : (availableCoins[0] || 'BTC'));
  };

  const handleGoToTrade = () => {
    if (isWebull) {
      navigate(`/trading/webull?symbol=${encodeURIComponent(selectedSymbol)}&side=${side}`);
    } else {
      navigate('/trading', {
        state: {
          tradePrefill: {
            symbol: `${selectedSymbol}USDT`,
            side: side === 'SELL' ? 'SELL' : 'BUY',
            baseCoin: selectedSymbol
          }
        }
      });
    }
  };

  return (
    <div className="widget-panel-inner" style={{ padding: '16px', height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
        <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: 'var(--text-primary, #fff)', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>⚡</span> Quick Trade Terminal
        </h3>
        {accountScope === 'all' ? (
          <div style={{ display: 'flex', gap: '2px', background: 'rgba(0,0,0,0.3)', padding: '2px', borderRadius: '6px' }}>
            <button
              type="button"
              onClick={() => handleExchangeChange('binance')}
              style={{
                padding: '2px 6px',
                borderRadius: '4px',
                border: 'none',
                background: !isWebull ? '#f3ba2f' : 'transparent',
                color: !isWebull ? '#000' : '#94a3b8',
                fontSize: '10px',
                fontWeight: 700,
                cursor: 'pointer'
              }}
            >
              Binance
            </button>
            <button
              type="button"
              onClick={() => handleExchangeChange('webull')}
              style={{
                padding: '2px 6px',
                borderRadius: '4px',
                border: 'none',
                background: isWebull ? '#38bdf8' : 'transparent',
                color: isWebull ? '#000' : '#94a3b8',
                fontSize: '10px',
                fontWeight: 700,
                cursor: 'pointer'
              }}
            >
              Webull
            </button>
          </div>
        ) : (
          <span style={{ fontSize: '11px', color: isWebull ? '#38bdf8' : '#f3ba2f', fontWeight: '600' }}>
            {isWebull ? 'Webull' : 'Binance.US'}
          </span>
        )}
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
            Buy {selectedSymbol}
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
            Sell {selectedSymbol}
          </button>
        </div>

        {/* Symbol Selector */}
        <div style={{ display: 'flex', gap: '4px', overflowX: 'auto', paddingBottom: '4px' }}>
          {symbols.map(s => (
            <button
              key={s}
              type="button"
              onClick={() => setSelectedSymbol(s)}
              style={{
                padding: '4px 8px',
                borderRadius: '6px',
                border: selectedSymbol === s ? (isWebull ? '1px solid #38bdf8' : '1px solid #f3ba2f') : '1px solid rgba(255,255,255,0.08)',
                background: selectedSymbol === s ? (isWebull ? 'rgba(56, 189, 248, 0.18)' : 'rgba(243, 186, 47, 0.18)') : 'rgba(255,255,255,0.04)',
                color: selectedSymbol === s ? (isWebull ? '#38bdf8' : '#f3ba2f') : '#94a3b8',
                fontSize: '12px',
                fontWeight: '600',
                cursor: 'pointer',
                whiteSpace: 'nowrap'
              }}
            >
              {s}
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
          {isWebull ? `Open ${selectedSymbol} in Webull Trading` : `Open ${selectedSymbol}/USDT Terminal`}
        </button>
      </div>
    </div>
  );
};

export default QuickTradeWidget;
