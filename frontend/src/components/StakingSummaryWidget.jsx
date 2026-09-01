import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import './StakingSummaryWidget.css';

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
    navigate('/trading/binance?tab=staking');
  };

  if (loading) {
    return (
      <div className="staking-summary-widget staking-loading-state">
        Loading...
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
    <div className="staking-summary-widget" onClick={handleCardClick}>
      <div className="staking-widget-header">
        <h3>
          <span>💰</span>
          <span>Staking</span>
        </h3>
        <small>Earning Rewards</small>
      </div>
      
      <div className="staking-widget-body">
        {/* Total Staked Value */}
        <div className="staking-total-value-container">
          <div className="staking-total-value">
            ${totalValue.toFixed(2)}
          </div>
          <div className="staking-total-label">
            Total Staked & Pending
          </div>
        </div>

        {/* Stats Row */}
        <div className="staking-stats-row">
          <div className="staking-stat-block">
            <div className="staking-stat-value">
              {activePositions}
            </div>
            <div className="staking-stat-label">
              Active Positions
            </div>
          </div>
          
          <div className="staking-stat-block">
            <div className="staking-stat-value highlight">
              {pendingPositions}
            </div>
            <div className="staking-stat-label">
              Pending
            </div>
            <div className="staking-stat-sublabel">
              ≈${pendingValue.toFixed(2)}
            </div>
          </div>
        </div>

        {/* Average APY */}
        <div className="staking-metric-row">
          <div className="staking-metric-label">
            Average APY
          </div>
          <div className="staking-metric-value">
            {avgApyPercent > 0 ? `${avgApyPercent.toFixed(2)}%` : '—'}
          </div>
        </div>

        {/* Today's Rewards */}
        {todaysRewards > 0 && (
          <div className="staking-metric-row">
            <div className="staking-metric-label">
              Today's Rewards
            </div>
            <div className="staking-metric-value">
              +${todaysRewards.toFixed(2)}
            </div>
          </div>
        )}

        <div className="staking-click-hint">
          Click to view details
        </div>
      </div>
    </div>
  );
}
