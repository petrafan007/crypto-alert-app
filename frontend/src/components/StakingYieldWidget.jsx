import React, { useState, useEffect } from 'react';
import axios from 'axios';
import CryptoIcon from './CryptoIcon';

const StakingYieldWidget = ({ isLightMode }) => {
  const [stakingData, setStakingData] = useState({
    totalStakedUsd: 0,
    estimatedDailyUsd: 0,
    estimatedMonthlyUsd: 0,
    estimatedYearlyUsd: 0,
    avgApr: 4.8,
    assets: []
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetchStaking = async () => {
      try {
        const res = await axios.get('/api/staking-balances', { withCredentials: true });
        if (res.data?.success && Array.isArray(res.data.positions)) {
          let total = 0;
          const assets = res.data.positions.map(p => {
            const usd = parseFloat(p.usd_value || p.total_usd || 0);
            total += usd;
            return {
              asset: p.asset || p.symbol,
              amount: parseFloat(p.amount || 0),
              apr: parseFloat(p.apr || p.annual_yield_pct || 5.0),
              usdValue: usd
            };
          });

          const avgApr = assets.length > 0 ? assets.reduce((acc, curr) => acc + curr.apr, 0) / assets.length : 4.8;
          const yearly = (total * (avgApr / 100));
          const monthly = yearly / 12;
          const daily = yearly / 365;

          if (!cancelled) {
            setStakingData({
              totalStakedUsd: total,
              estimatedDailyUsd: daily,
              estimatedMonthlyUsd: monthly,
              estimatedYearlyUsd: yearly,
              avgApr: avgApr,
              assets: assets
            });
            setLoading(false);
          }
        }
      } catch (err) {
        console.error('Failed to load staking yield:', err);
        if (!cancelled) setLoading(false);
      }
    };

    fetchStaking();
    const interval = setInterval(fetchStaking, 60000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="widget-panel-inner" style={{ padding: '16px', height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: 'var(--text-primary, #fff)', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>🌾</span> Staking Yield & Rewards
        </h3>
        <span style={{ fontSize: '11px', color: '#f59e0b', fontWeight: '600' }}>
          ~{stakingData.avgApr.toFixed(1)}% Avg APR
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px', marginBottom: '12px' }}>
        <div style={{ background: 'rgba(255, 255, 255, 0.04)', borderRadius: '8px', padding: '8px', textAlign: 'center' }}>
          <div style={{ fontSize: '10px', color: '#94a3b8', textTransform: 'uppercase' }}>Daily</div>
          <div style={{ fontSize: '13px', fontWeight: '700', color: '#4ade80' }}>
            ${stakingData.estimatedDailyUsd.toFixed(2)}
          </div>
        </div>
        <div style={{ background: 'rgba(255, 255, 255, 0.04)', borderRadius: '8px', padding: '8px', textAlign: 'center' }}>
          <div style={{ fontSize: '10px', color: '#94a3b8', textTransform: 'uppercase' }}>Monthly</div>
          <div style={{ fontSize: '13px', fontWeight: '700', color: '#4ade80' }}>
            ${stakingData.estimatedMonthlyUsd.toFixed(2)}
          </div>
        </div>
        <div style={{ background: 'rgba(255, 255, 255, 0.04)', borderRadius: '8px', padding: '8px', textAlign: 'center' }}>
          <div style={{ fontSize: '10px', color: '#94a3b8', textTransform: 'uppercase' }}>Yearly</div>
          <div style={{ fontSize: '13px', fontWeight: '700', color: '#38bdf8' }}>
            ${stakingData.estimatedYearlyUsd.toFixed(2)}
          </div>
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {stakingData.assets.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#94a3b8', fontSize: '12px', padding: '12px 0' }}>
            No active Binance.US staking positions.
          </div>
        ) : (
          stakingData.assets.map(a => (
            <div key={a.asset} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '12px', padding: '4px 8px', borderRadius: '6px', background: 'rgba(0,0,0,0.2)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <CryptoIcon symbol={a.asset} size={16} />
                <span style={{ fontWeight: '600', color: 'var(--text-primary, #fff)' }}>{a.asset}</span>
              </div>
              <div style={{ textAlign: 'right' }}>
                <span style={{ color: '#f59e0b', fontWeight: '600' }}>{a.apr.toFixed(1)}% APR</span>
                <span style={{ color: '#94a3b8', fontSize: '11px', marginLeft: '6px' }}>(${a.usdValue.toFixed(2)})</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default StakingYieldWidget;
