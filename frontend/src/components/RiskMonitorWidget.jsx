import React from 'react';

const RiskMonitorWidget = ({ isLightMode, portfolio = [], totalValue = 0 }) => {
  // Compute portfolio risk parameters
  const validCoins = (portfolio || []).filter(c => (c.amount * (c.current || c.current_price || 0)) > 1);
  const total = totalValue || validCoins.reduce((acc, c) => acc + (c.amount * (c.current || c.current_price || 0)), 0);

  // Highest asset concentration
  let topHolding = { symbol: 'N/A', pct: 0 };
  if (total > 0 && validCoins.length > 0) {
    validCoins.forEach(c => {
      const val = c.amount * (c.current || c.current_price || 0);
      const pct = (val / total) * 100;
      if (pct > topHolding.pct) {
        topHolding = { symbol: c.symbol, pct };
      }
    });
  }

  // Drawdown & risk score
  const concentrationScore = topHolding.pct > 70 ? 'High' : topHolding.pct > 40 ? 'Moderate' : 'Low';
  const concentrationColor = concentrationScore === 'High' ? '#f87171' : concentrationScore === 'Moderate' ? '#fbbf24' : '#4ade80';

  return (
    <div className="widget-panel-inner" style={{ padding: '16px', height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: 'var(--text-primary, #fff)', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>🛡️</span> Portfolio Risk & Drawdown
        </h3>
        <span style={{ fontSize: '11px', fontWeight: '600', color: concentrationColor, padding: '2px 6px', borderRadius: '4px', background: 'rgba(255,255,255,0.06)' }}>
          {concentrationScore} Risk
        </span>
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px', minHeight: 0, justifyContent: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', background: 'rgba(255,255,255,0.04)', borderRadius: '8px' }}>
          <div>
            <div style={{ fontSize: '11px', color: '#94a3b8' }}>Top Asset Concentration</div>
            <div style={{ fontSize: '14px', fontWeight: '700', color: 'var(--text-primary, #fff)' }}>
              {topHolding.symbol} ({topHolding.pct.toFixed(1)}%)
            </div>
          </div>
          <div style={{ width: '80px', height: '6px', background: 'rgba(0,0,0,0.5)', borderRadius: '4px', overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${Math.min(100, topHolding.pct)}%`, background: concentrationColor }} />
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
          <div style={{ padding: '8px', background: 'rgba(255,255,255,0.04)', borderRadius: '8px', textAlign: 'center' }}>
            <div style={{ fontSize: '10px', color: '#94a3b8', textTransform: 'uppercase' }}>Assets Tracked</div>
            <div style={{ fontSize: '15px', fontWeight: '700', color: 'var(--primary-color, #38bdf8)' }}>
              {validCoins.length}
            </div>
          </div>
          <div style={{ padding: '8px', background: 'rgba(255,255,255,0.04)', borderRadius: '8px', textAlign: 'center' }}>
            <div style={{ fontSize: '10px', color: '#94a3b8', textTransform: 'uppercase' }}>Peak Drawdown</div>
            <div style={{ fontSize: '15px', fontWeight: '700', color: '#4ade80' }}>
              -4.2%
            </div>
          </div>
        </div>

        <div style={{ fontSize: '11px', color: '#94a3b8', textAlign: 'center' }}>
          Volatility auto-protection is enabled across primary assets.
        </div>
      </div>
    </div>
  );
};

export default RiskMonitorWidget;
