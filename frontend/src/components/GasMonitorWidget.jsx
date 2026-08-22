import React, { useState } from 'react';

const GasMonitorWidget = ({ isLightMode }) => {
  const gasData = [
    { network: 'Bitcoin (BTC)', metric: '14 sat/vB', speed: 'Fast', speedColor: '#4ade80', level: 'Low Traffic' },
    { network: 'Ethereum (ETH)', metric: '18 Gwei', speed: 'Normal', speedColor: '#38bdf8', level: 'Optimal' },
    { network: 'Solana (SOL)', metric: '< 0.0001 SOL', speed: 'Instant', speedColor: '#4ade80', level: 'High Throughput' }
  ];

  return (
    <div className="widget-panel-inner" style={{ padding: '16px', height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: 'var(--text-primary, #fff)', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>⛽</span> Network Gas & Fees
        </h3>
        <span style={{ fontSize: '11px', color: '#4ade80', fontWeight: '600' }}>Normal</span>
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px', minHeight: 0, justifyContent: 'center' }}>
        {gasData.map(item => (
          <div
            key={item.network}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '8px 12px',
              borderRadius: '8px',
              background: 'rgba(255, 255, 255, 0.04)',
              fontSize: '12px'
            }}
          >
            <div>
              <div style={{ fontWeight: '600', color: 'var(--text-primary, #fff)' }}>{item.network}</div>
              <div style={{ fontSize: '10px', color: '#94a3b8' }}>{item.level}</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontWeight: '700', color: item.speedColor }}>{item.metric}</div>
              <div style={{ fontSize: '10px', color: '#94a3b8' }}>{item.speed}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default GasMonitorWidget;
