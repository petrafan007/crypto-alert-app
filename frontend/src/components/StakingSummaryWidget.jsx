import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';

const toNumber = (value, fallback = 0) => {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
};

const normalizeSummaryPayload = (payload) => {
  if (!payload) {
    return {
      totalStakedValue: 0,
      totalValue: 0,
      activePositions: 0,
      pendingPositions: 0,
      todayRewards: 0,
      avgApy: 0,
      activeValue: 0,
      pendingValue: 0
    };
  }

  const summary = payload.summary || {};

  return {
    totalStakedValue: toNumber(summary.totalUsd ?? payload.totalStakedValue ?? payload.totalValue ?? 0),
    totalValue: toNumber(summary.totalUsd ?? payload.totalValue ?? payload.totalStakedValue ?? 0),
    activePositions: toNumber(summary.activeCount ?? payload.activePositions ?? payload.totalActivePositions ?? 0),
    pendingPositions: toNumber(summary.pendingCount ?? payload.pendingPositions ?? payload.pendingCount ?? 0),
    todayRewards: toNumber(payload.todayRewards ?? payload.todaysRewards ?? 0),
    avgApy: toNumber(summary.avgApy ?? payload.avgApy ?? payload.averageAPY ?? 0),
    activeValue: toNumber(summary.activeUsd ?? payload.activeValue ?? 0),
    pendingValue: toNumber(summary.pendingUsd ?? payload.pendingValue ?? payload.pendingUsd ?? 0)
  };
};

const consumePrefetchedSummary = () => {
  if (typeof window !== 'undefined' && window.__STAKING_SUMMARY__) {
    const snapshot = window.__STAKING_SUMMARY__;
    delete window.__STAKING_SUMMARY__;
    return snapshot;
  }
  return null;
};

export default function StakingSummaryWidget() {
  const initialPrefetch = consumePrefetchedSummary();
  const [stakingData, setStakingData] = useState(() => normalizeSummaryPayload(initialPrefetch));
  const [loading, setLoading] = useState(() => !initialPrefetch);
  const navigate = useNavigate();

  useEffect(() => {
    fetchStakingData();
  }, []);

  const fetchStakingData = async () => {
    try {
      const response = await axios.get(`/api/staking/balance?ts=${Date.now()}`, {
        withCredentials: true
      });
      const normalized = normalizeSummaryPayload(response.data);
      setStakingData(normalized);
      setLoading(false);
    } catch (err) {
      console.error('Failed to fetch staking summary:', err);
      if (!stakingData) {
        const fallback = normalizeSummaryPayload(initialPrefetch);
        if (!initialPrefetch) {
          try {
            const summaryResp = await axios.post('/api/staking/dashboard-view', {}, { withCredentials: true });
            setStakingData(normalizeSummaryPayload(summaryResp.data));
            setLoading(false);
            return;
          } catch (innerErr) {
            console.error('Fallback staking summary request failed:', innerErr);
          }
        }
        setStakingData(fallback);
      }
      setLoading(false);
    }
  };

  const handleCardClick = () => {
    navigate('/staking');
  };

  if (loading) {
    return (
      <div style={{
        background: 'var(--card-bg, #ffffff)',
        borderRadius: '12px',
        boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
        padding: '16px',
        minWidth: '280px',
        maxWidth: '320px',
        border: '1px solid var(--border-color, #e0e0e0)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        transition: 'transform 0.2s, box-shadow 0.2s'
      }}>
        <div style={{ fontSize: '14px', color: 'var(--text-secondary, #666666)' }}>
          Loading...
        </div>
      </div>
    );
  }

  const totalValue = toNumber(stakingData?.totalValue ?? stakingData?.totalStakedValue ?? 0);
  const activePositionsRaw = toNumber(stakingData?.activePositions ?? stakingData?.totalActivePositions ?? 0);
  const pendingPositionsRaw = toNumber(stakingData?.pendingPositions ?? stakingData?.pendingCount ?? 0);
  const todaysRewards = toNumber(stakingData?.todayRewards ?? stakingData?.todaysRewards ?? 0);
  const avgApyPercent = toNumber(stakingData?.avgApy ?? stakingData?.averageAPY ?? 0);
  const pendingValue = toNumber(stakingData?.pendingValue ?? stakingData?.pendingUsd ?? 0);
  const activePositions = Math.max(0, Math.round(activePositionsRaw));
  const pendingPositions = Math.max(0, Math.round(pendingPositionsRaw));

  return (
    <div 
      onClick={handleCardClick}
      style={{
        background: 'var(--card-bg, #ffffff)',
        borderRadius: '12px',
        boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
        padding: '16px',
        minWidth: '280px',
        maxWidth: '320px',
        border: '1px solid var(--border-color, #e0e0e0)',
        display: 'flex',
        flexDirection: 'column',
        cursor: 'pointer',
        transition: 'transform 0.2s, box-shadow 0.2s'
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = 'translateY(-4px)';
        e.currentTarget.style.boxShadow = '0 4px 16px rgba(0, 0, 0, 0.15)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = 'translateY(0)';
        e.currentTarget.style.boxShadow = '0 2px 8px rgba(0, 0, 0, 0.1)';
      }}
    >
      <div style={{ marginBottom: '16px', textAlign: 'center' }}>
        <h3 style={{
          margin: '0 0 4px 0',
          fontSize: '16px',
          fontWeight: '600',
          color: 'var(--text-primary, #333333)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '8px'
        }}>
          <span>💰</span>
          <span>Staking</span>
        </h3>
        <small style={{
          fontSize: '12px',
          color: 'var(--text-secondary, #666666)',
          display: 'block'
        }}>
          Earning Rewards
        </small>
      </div>
      
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
        flex: 1
      }}>
        {/* Total Staked Value */}
        <div style={{ textAlign: 'center' }}>
          <div style={{
            fontSize: '28px',
            fontWeight: 'bold',
            color: 'var(--primary-color, #2196F3)',
            marginBottom: '4px'
          }}>
            ${totalValue.toFixed(2)}
          </div>
          <div style={{
            fontSize: '11px',
            color: 'var(--text-secondary, #666666)',
            opacity: '0.8'
          }}>
            Total Staked & Pending
          </div>
        </div>

        {/* Stats Row */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '8px',
          paddingTop: '12px',
          borderTop: '1px solid var(--border-color, #e0e0e0)'
        }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{
              fontSize: '18px',
              fontWeight: '600',
              color: 'var(--text-primary, #333333)'
            }}>
              {activePositions}
            </div>
            <div style={{
              fontSize: '10px',
              color: 'var(--text-secondary, #666666)',
              marginTop: '2px'
            }}>
              Active Positions
            </div>
          </div>
          
          <div style={{ textAlign: 'center' }}>
            <div style={{
              fontSize: '18px',
              fontWeight: '600',
              color: '#2196F3'
            }}>
              {pendingPositions}
            </div>
            <div style={{
              fontSize: '10px',
              color: 'var(--text-secondary, #666666)',
              marginTop: '2px'
            }}>
              Pending
            </div>
            <div style={{
              fontSize: '10px',
              color: 'var(--text-secondary, #999999)'
            }}>
              ≈${pendingValue.toFixed(2)}
            </div>
          </div>
        </div>

        {/* Average APY */}
        <div style={{
          textAlign: 'center',
          paddingTop: '8px',
          borderTop: '1px solid var(--border-color, #e0e0e0)'
        }}>
          <div style={{
            fontSize: '12px',
            color: 'var(--text-secondary, #666666)'
          }}>
            Average APY
          </div>
          <div style={{
            fontSize: '16px',
            fontWeight: '600',
            color: '#4CAF50',
            marginTop: '4px'
          }}>
            {avgApyPercent > 0 ? `${avgApyPercent.toFixed(2)}%` : '—'}
          </div>
        </div>

        {/* Today's Rewards */}
        {todaysRewards > 0 && (
          <div style={{
            textAlign: 'center',
            paddingTop: '8px',
            borderTop: '1px solid var(--border-color, #e0e0e0)'
          }}>
            <div style={{
              fontSize: '12px',
              color: 'var(--text-secondary, #666666)'
            }}>
              Today's Rewards
            </div>
            <div style={{
              fontSize: '16px',
              fontWeight: '600',
              color: '#4CAF50',
              marginTop: '4px'
            }}>
              +${todaysRewards.toFixed(2)}
            </div>
          </div>
        )}

        {/* Click instruction */}
        <div style={{
          fontSize: '10px',
          color: 'var(--text-secondary, #666666)',
          textAlign: 'center',
          opacity: '0.6',
          marginTop: '4px'
        }}>
          Click to view details
        </div>
      </div>
    </div>
  );
}
