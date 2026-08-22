import React, { useState, useEffect } from 'react';
import axios from 'axios';

const AIPulseWidget = ({ isLightMode, onOpenCopilot }) => {
  const [pulse, setPulse] = useState({
    sentiment: 'Bullish',
    score: 72,
    summary: 'Strong macro accumulation across majors with heavy volume supporting key resistance levels.',
    catalysts: ['Bitcoin ETF net inflows accelerating', 'Ethereum staking APR holding steady at 3.4%', 'Layer 1 trading volume up +12% week-over-week']
  });

  return (
    <div className="widget-panel-inner" style={{ padding: '16px', height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
        <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: 'var(--text-primary, #fff)', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>🤖</span> AI Copilot Market Pulse
        </h3>
        <span
          style={{
            fontSize: '11px',
            fontWeight: '700',
            padding: '2px 8px',
            borderRadius: '12px',
            background: 'rgba(56, 189, 248, 0.15)',
            color: '#38bdf8',
            border: '1px solid rgba(56, 189, 248, 0.3)'
          }}
        >
          AI Active
        </span>
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px', minHeight: 0, overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(255, 255, 255, 0.04)', padding: '8px 12px', borderRadius: '8px' }}>
          <div>
            <div style={{ fontSize: '11px', color: '#94a3b8' }}>Overall Market Bias</div>
            <div style={{ fontSize: '15px', fontWeight: '700', color: '#4ade80' }}>
              🟢 {pulse.sentiment} ({pulse.score}/100)
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '11px', color: '#94a3b8' }}>Confidence</div>
            <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary, #fff)' }}>High (88%)</div>
          </div>
        </div>

        <p style={{ margin: 0, fontSize: '12px', color: '#cbd5e1', lineHeight: '1.4' }}>
          {pulse.summary}
        </p>

        <div style={{ marginTop: 'auto', paddingTop: '4px' }}>
          <div style={{ fontSize: '11px', fontWeight: '600', color: '#94a3b8', marginBottom: '4px' }}>Key AI Catalysts:</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            {pulse.catalysts.map((cat, i) => (
              <div key={i} style={{ fontSize: '11px', color: '#94a3b8', display: 'flex', alignItems: 'flex-start', gap: '4px' }}>
                <span style={{ color: '#38bdf8' }}>•</span>
                <span>{cat}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export default AIPulseWidget;
