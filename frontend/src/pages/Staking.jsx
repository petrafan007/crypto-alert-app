import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useSearchParams } from 'react-router-dom';
import './Staking.css';
import TradePermissionModal from '../components/TradePermissionModal';
import ApiKeyRequiredModal from '../components/ApiKeyRequiredModal';

export default function Staking({ isLightMode }) {
  const [searchParams] = useSearchParams();
  const [stakingAssets, setStakingAssets] = useState([]);
  const [stakedCoins, setStakedCoins] = useState([]);
  const [stakingHistory, setStakingHistory] = useState([]);
  const [rewards, setRewards] = useState([]);
  const [pendingPositions, setPendingPositions] = useState([]);
  const [pendingTransactions, setPendingTransactions] = useState([]);
  const [balanceSummary, setBalanceSummary] = useState({
    activeCount: 0,
    pendingCount: 0,
    activeUsd: 0,
    pendingUsd: 0,
    totalUsd: 0
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showStakeModal, setShowStakeModal] = useState(false);
  const [showUnstakeModal, setShowUnstakeModal] = useState(false);
  const [selectedAsset, setSelectedAsset] = useState(null);
  const [selectedStakedCoin, setSelectedStakedCoin] = useState(null);
  const [stakeAmount, setStakeAmount] = useState('');
  const [unstakeAmount, setUnstakeAmount] = useState('');
  const [autoRestake, setAutoRestake] = useState(false);
  const [totalStakedValue, setTotalStakedValue] = useState(0);
  const [totalRewardsEarned, setTotalRewardsEarned] = useState(0);
  const [portfolioMap, setPortfolioMap] = useState({});
  const [realtimeBalance, setRealtimeBalance] = useState(null);
  const [fetchingBalance, setFetchingBalance] = useState(false);
  const [settings, setSettings] = useState({ require_2fa: false, totp_enabled: false });
  const [twoFactorCode, setTwoFactorCode] = useState('');
  const [twoFactorError, setTwoFactorError] = useState('');
  const [verifying2FA, setVerifying2FA] = useState(false);
  const [showTwoFactorInput, setShowTwoFactorInput] = useState(true);

  // Permission Check States
  const [showApiKeyModal, setShowApiKeyModal] = useState(false);
  const [showPermissionModal, setShowPermissionModal] = useState(false);

  useEffect(() => {
    // Check trade permission first
    const checkPermission = async () => {
      try {
        const response = await axios.get('/api/check-trade-permission', { withCredentials: true });
        if (!response.data.has_api_key) {
          // No API key configured
          setShowApiKeyModal(true);
        } else if (!response.data.has_permission) {
          // Has API key but no trading permission
          setShowPermissionModal(true);
        }
      } catch (err) {
        console.error('Failed to check trade permission:', err);
      }
    };
    checkPermission();

    fetchStakingData();
    fetchSettings();
  }, []);

  // Auto-open stake modal if coin parameter is present
  useEffect(() => {
    const coinParam = searchParams.get('coin');
    if (coinParam && stakingAssets.length > 0 && !showStakeModal) {
      const asset = stakingAssets.find(a => a.stakingAsset === coinParam);
      if (asset) {
        handleStakeClick(asset);
      }
    }
  }, [searchParams, stakingAssets]);

  const fetchSettings = async () => {
    try {
      const response = await axios.get('/api/trading/settings', { withCredentials: true });
      if (response.data) {
        setSettings(response.data);
        setShowTwoFactorInput(!!(response.data.require_2fa && response.data.totp_enabled));
      }
    } catch (err) {
      console.error('Failed to fetch settings:', err);
    }
  };

  const fetchStakingData = async () => {
    try {
      setLoading(true);
      setError('');

      // Step 1: Fetch staking asset information from Binance.US
      console.log('Fetching staking assets from Binance.US...');
      const assetsResponse = await axios.get('/api/staking/assets', { withCredentials: true });
      console.log('Staking assets response:', assetsResponse.data);

      const allStakingAssets = assetsResponse.data || [];

      // Create a set of stakeable symbols for quick lookup
      const stakeableSymbols = new Set(allStakingAssets.map(a => a.stakingAsset));
      console.log('Stakeable symbols:', Array.from(stakeableSymbols));

      // Step 2: Fetch user's local portfolio from database
      console.log('Fetching portfolio from database...');
      const portfolioResponse = await axios.get('/api/coin-data', { withCredentials: true });

      if (!portfolioResponse.data || !portfolioResponse.data.portfolio) {
        throw new Error('Failed to fetch portfolio data');
      }

      const portfolioCoins = portfolioResponse.data.portfolio || [];
      console.log('Portfolio coins:', portfolioCoins.length);

      // Step 3: Filter portfolio to coins that are stakeable, not hidden, and >= $1 USDT
      const eligibleCoins = portfolioCoins.filter(coin =>
        stakeableSymbols.has(coin.symbol) &&
        !coin.hidden &&
        coin.current_value >= 1
      );

      console.log('Eligible coins for staking:', eligibleCoins.map(c => `${c.symbol} ($${c.current_value.toFixed(2)})`));

      // Step 4: Create portfolio map for quick lookup (using symbol as key)
      const portMap = {};
      eligibleCoins.forEach(coin => {
        portMap[coin.symbol] = {
          symbol: coin.symbol,
          balance: coin.amount,
          value: coin.current_value,
          price: coin.current_price
        };
      });
      setPortfolioMap(portMap);

      // Step 5: Filter staking assets to only show eligible coins
      const filteredAssets = allStakingAssets.filter(asset =>
        portMap[asset.stakingAsset] !== undefined
      );

      console.log('Filtered stakeable assets:', filteredAssets.map(a => a.stakingAsset));
      setStakingAssets(filteredAssets);

      // Step 6: Fetch current staking balances
      const balanceResponse = await axios.get('/api/staking/balance', { withCredentials: true });
      console.log('Staking balance response:', balanceResponse.data);
      const balanceData = balanceResponse.data || {};
      const balances = balanceData.balances || [];
      const activeFromApi = balanceData.activePositions || balances;
      const pendingFromApi = balanceData.pendingPositions || [];

      setStakedCoins(activeFromApi);
      setPendingPositions(pendingFromApi);
      setPendingTransactions(balanceData.pendingTransactions || []);

      const summary = balanceData.summary || {};
      setBalanceSummary({
        activeCount: summary.activeCount ?? activeFromApi.length,
        pendingCount: summary.pendingCount ?? pendingFromApi.length,
        activeUsd: summary.activeUsd ?? 0,
        pendingUsd: summary.pendingUsd ?? 0,
        totalUsd: summary.totalUsd ?? balanceData.totalStakedValue ?? 0
      });
      setTotalStakedValue(summary.totalUsd ?? balanceData.totalStakedValue ?? 0);

      // Step 7: Fetch staking history
      const historyResponse = await axios.get('/api/staking/history', { withCredentials: true });
      setStakingHistory(historyResponse.data || []);

      // Step 8: Fetch rewards
      const rewardsResponse = await axios.get('/api/staking/rewards', { withCredentials: true });
      setRewards(rewardsResponse.data || []);

      // Calculate total rewards earned
      const totalRewards = (rewardsResponse.data || []).reduce((sum, r) => sum + (r.usdValue || 0), 0);
      setTotalRewardsEarned(totalRewards);

      setLoading(false);
    } catch (err) {
      console.error('Failed to fetch staking data:', err);
      console.error('Error details:', err.response?.data || err.message);
      setError(err.response?.data?.error || err.message || 'Failed to load staking data. Please refresh the page.');
      setLoading(false);
      setStakingAssets([]); // Ensure it's set to empty array on error
    }
  };

  const fetchRealtimeBalance = async (symbol) => {
    try {
      setFetchingBalance(true);
      console.log(`Fetching real-time balance for ${symbol}...`);

      // Use portfolio balance we already have from fetchStakingData
      const portfolioCoin = portfolioMap[symbol];
      if (!portfolioCoin) {
        console.warn(`No portfolio data found for ${symbol}`);
        setRealtimeBalance({ symbol, tradable: 0, reservedByOrders: 0 });
        setFetchingBalance(false);
        return;
      }

      const portfolioAmount = parseFloat(portfolioCoin.balance || 0);
      const portfolioPrice = parseFloat(portfolioCoin.price || 0);

      // Fetch pending orders to determine reserved quantity for this asset (SELL orders reserve base asset)
      let reservedByOrders = 0;
      try {
        const po = await axios.get('/api/pending-orders', { withCredentials: true });
        const pending = po.data && po.data.pending_orders ? po.data.pending_orders : [];
        // Sum quantities for SELL orders matching this asset
        pending.forEach(o => {
          try {
            const orderAsset = (o.asset || '').toUpperCase();
            const side = (o.side || '').toUpperCase();
            const qty = parseFloat(o.quantity || 0);
            if (orderAsset === symbol.toUpperCase() && side === 'SELL' && qty > 0) {
              reservedByOrders += qty;
            }
          } catch (e) {
            // ignore parse errors per-order
          }
        });
      } catch (err) {
        console.warn('Failed to fetch pending orders for reserved calculation:', err);
      }

      // tradable = portfolio amount - reservedByOrders (cannot be negative)
      const tradable = Math.max(0, portfolioAmount - reservedByOrders);

      console.log(`Balance calculation for ${symbol}:`, {
        portfolioAmount,
        reservedByOrders,
        tradable,
        price: portfolioPrice,
        value: tradable * portfolioPrice
      });

      setRealtimeBalance({
        symbol,
        amount: portfolioAmount,
        reservedByOrders,
        tradable,
        price: portfolioPrice,
        value: tradable * portfolioPrice
      });
      setFetchingBalance(false);
    } catch (err) {
      console.error(`Failed to fetch real-time balance for ${symbol}:`, err);
      setFetchingBalance(false);
    }
  };

  const handleStakeClick = async (asset) => {
    setSelectedAsset(asset);
    setStakeAmount('');
    setAutoRestake(false);
    setRealtimeBalance(null);
    setTwoFactorCode('');
    setTwoFactorError('');
    setShowTwoFactorInput(!!(settings.require_2fa && settings.totp_enabled));
    setShowStakeModal(true);

    // Fetch real-time balance from Binance API
    await fetchRealtimeBalance(asset.stakingAsset);
  };

  const handleUnstakeClick = (stakedCoin) => {
    setSelectedStakedCoin(stakedCoin);
    setUnstakeAmount('');
    setTwoFactorCode('');
    setTwoFactorError('');
    setShowTwoFactorInput(!!(settings.require_2fa && settings.totp_enabled));
    setShowUnstakeModal(true);
  };

  const handleStakeSubmit = async () => {
    if (!selectedAsset || !stakeAmount || parseFloat(stakeAmount) <= 0) {
      setError('Please enter a valid amount');
      return;
    }
    // determine max tradable amount
    const maxTradable = realtimeBalance && realtimeBalance.tradable !== undefined
      ? realtimeBalance.tradable
      : (portfolioMap[selectedAsset.stakingAsset] ? parseFloat(portfolioMap[selectedAsset.stakingAsset].balance || 0) : 0);

    if (parseFloat(stakeAmount) > maxTradable) {
      setError(`You may only stake up to ${maxTradable} ${selectedAsset.stakingAsset} (tradable amount).`);
      return;
    }

    // Verify 2FA code
    if (!twoFactorCode || twoFactorCode.length !== 6) {
      setTwoFactorError('Please enter a valid 6-digit code');
      return;
    }

    setVerifying2FA(true);
    setTwoFactorError('');

    try {
      // Verify 2FA code
      const verifyResponse = await axios.post('/api/trading/2fa/verify', { code: twoFactorCode }, { withCredentials: true });

      if (!verifyResponse.data.success) {
        setTwoFactorError(verifyResponse.data.error || 'Verification failed');
        setVerifying2FA(false);
        return;
      }

      const token = verifyResponse.data.token;

      // Submit stake with token
      await submitStake(token);

    } catch (err) {
      setTwoFactorError(err.response?.data?.error || 'Verification failed');
      setVerifying2FA(false);
    }
  };

  const submitStake = async (twofaToken) => {
    try {
      const payload = {
        stakingAsset: selectedAsset.stakingAsset,
        amount: parseFloat(stakeAmount),
        autoRestake: autoRestake
      };

      if (twofaToken) {
        payload.twofa_token = twofaToken;
      }

      const response = await axios.post('/api/staking/stake', payload, { withCredentials: true });

      if (response.data.success) {
        setShowStakeModal(false);
        setShowTwoFactorInput(!!(settings.require_2fa && settings.totp_enabled));
        setTwoFactorCode('');
        setVerifying2FA(false);
        setError('');
        alert(`Successfully staked ${payload.amount} ${payload.stakingAsset}`);
        fetchStakingData(); // Refresh data
      } else {
        setError(response.data.error || 'Staking failed');
        setVerifying2FA(false);
      }
    } catch (err) {
      console.error('Staking error:', err);
      const errorMsg = err.response?.data?.error || 'Failed to stake asset';
      setError(errorMsg);
      setVerifying2FA(false);

      // Check if 2FA is required (backend might request it)
      if (err.response?.data?.requires_2fa) {
        setShowTwoFactorInput(true);
      } else {
        alert(errorMsg);
      }
    }
  };

  const handleUnstakeSubmit = async () => {
    if (!selectedStakedCoin || !unstakeAmount || parseFloat(unstakeAmount) <= 0) {
      setError('Please enter a valid amount');
      return;
    }

    // Verify 2FA code
    if (settings.require_2fa && settings.totp_enabled) {
      if (!twoFactorCode || twoFactorCode.length !== 6) {
        setTwoFactorError('Please enter a valid 6-digit code');
        return;
      }

      setVerifying2FA(true);
      setTwoFactorError('');

      try {
        // Verify 2FA code
        const verifyResponse = await axios.post('/api/trading/2fa/verify', { code: twoFactorCode }, { withCredentials: true });

        if (!verifyResponse.data.success) {
          setTwoFactorError(verifyResponse.data.error || 'Verification failed');
          setVerifying2FA(false);
          return;
        }

        const token = verifyResponse.data.token;

        // Submit unstake with token
        await submitUnstake(token);

      } catch (err) {
        setTwoFactorError(err.response?.data?.error || 'Verification failed');
        setVerifying2FA(false);
      }
    } else {
      await submitUnstake();
    }
  };

  const submitUnstake = async (twofaToken) => {
    try {
      const payload = {
        stakedCoinId: selectedStakedCoin.id,
        amount: parseFloat(unstakeAmount)
      };

      if (twofaToken) {
        payload.twofa_token = twofaToken;
      }

      const response = await axios.post('/api/staking/unstake', payload, { withCredentials: true });

      if (response.data.success) {
        setShowUnstakeModal(false);
        setTwoFactorCode('');
        setVerifying2FA(false);
        setError('');
        alert(response.data.message);
        fetchStakingData(); // Refresh data
      } else {
        setError(response.data.error || 'Unstaking failed');
        setVerifying2FA(false);
      }
    } catch (err) {
      console.error('Unstaking error:', err);
      const errorMsg = err.response?.data?.error || 'Failed to unstake asset';
      setError(errorMsg);
      setVerifying2FA(false);

      if (err.response?.data?.requires_2fa) {
        setShowTwoFactorInput(true);
      } else {
        alert(errorMsg);
      }
    }
  };

  const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleString();
  };

  const formatStatusLabel = (status) => {
    if (!status) return 'Unknown';
    return status
      .toString()
      .replace(/_/g, ' ')
      .toLowerCase()
      .replace(/\b\w/g, (char) => char.toUpperCase());
  };

  const formatUsd = (value) => {
    if (value === undefined || value === null || Number.isNaN(Number(value))) {
      return '$0.00';
    }
    return `$${Number(value).toFixed(2)}`;
  };

  const formatUnstakingPeriod = (hours) => {
    if (!hours) return 'N/A';
    const days = Math.floor(hours / 24);
    return `${days} day${days !== 1 ? 's' : ''}`;
  };

  if (loading) {
    return (
      <div className={`staking-container ${isLightMode ? 'light' : 'dark'}`}>
        <div className="loading-message">Loading staking data...</div>
      </div>
    );
  }

  return (
    <div className={`staking-container ${isLightMode ? 'light' : 'dark'}`}>
      {/* API Key Required Modal */}
      <ApiKeyRequiredModal
        show={showApiKeyModal}
        onClose={() => setShowApiKeyModal(false)}
        isLightMode={isLightMode}
      />
      {/* Trade Permission Modal */}
      <TradePermissionModal
        show={showPermissionModal}
        onClose={() => setShowPermissionModal(false)}
        pageName="staking"
        isLightMode={isLightMode}
      />
      <h1 className="staking-title">💰 Staking</h1>

      {error && (
        <div className="error-message">
          {error}
          <button onClick={() => setError('')} className="close-error">×</button>
        </div>
      )}

      {/* Staking Overview */}
      <div className="staking-overview">
        <div className="overview-card">
          <div className="overview-label">Total Staked Value</div>
          <div className="overview-value">{formatUsd(totalStakedValue)}</div>
          <div className="overview-subtext">
            Includes active, bonding, and unstaking balances
          </div>
        </div>
        <div className="overview-card">
          <div className="overview-label">Total Rewards Earned (All Time)</div>
          <div className="overview-value">{formatUsd(totalRewardsEarned)}</div>
        </div>
        <div className="overview-card">
          <div className="overview-label">Pending Positions</div>
          <div className="overview-value">{balanceSummary.pendingCount ?? pendingPositions.length}</div>
          <div className="overview-subtext">
            {formatUsd(balanceSummary.pendingUsd ?? 0)} pending on Binance.US
          </div>
        </div>
        <div className="overview-card">
          <div className="overview-label">Active Positions</div>
          <div className="overview-value">{balanceSummary.activeCount ?? stakedCoins.length}</div>
          <div className="overview-subtext">
            {formatUsd(balanceSummary.activeUsd ?? 0)} currently staked
          </div>
        </div>
      </div>

      {/* Available Assets to Stake */}
      <div className="staking-section">
        <h2 className="section-title">Available Assets to Stake</h2>
        {loading ? (
          <div style={{
            padding: '40px',
            textAlign: 'center',
            backgroundColor: 'var(--card-bg, #2a2a2a)',
            borderRadius: '12px',
            marginBottom: '20px'
          }}>
            <h3 style={{ marginBottom: '16px', fontSize: '20px' }}>📊 Loading Staking Assets...</h3>
            <p style={{ color: '#888', marginBottom: '12px' }}>
              Fetching available staking options from Binance.US
            </p>
          </div>
        ) : stakingAssets.length === 0 ? (
          <div style={{
            padding: '40px',
            textAlign: 'center',
            backgroundColor: 'var(--card-bg, #2a2a2a)',
            borderRadius: '12px',
            marginBottom: '20px'
          }}>
            <h3 style={{ marginBottom: '16px', fontSize: '20px' }}>ℹ️ No Stakeable Assets Found</h3>
            <p style={{ color: '#888', marginBottom: '12px' }}>
              You don't have any coins eligible for staking.
            </p>
            <p style={{ color: '#666', fontSize: '14px' }}>
              To stake, you need coins worth at least $1 USDT that are supported by Binance.US staking.
            </p>
          </div>
        ) : (
          <div className="assets-grid">
            {stakingAssets.map((asset, index) => (
              <div key={index} className="asset-card">
                <div className="asset-symbol">{asset.stakingAsset}</div>
                <div className="asset-details">
                  <div className="asset-apy">APY: <span className="apy-value">{(asset.apy * 100).toFixed(2)}%</span></div>
                  <div className="asset-info">Min: {asset.minStakingLimit}</div>
                  <div className="asset-info">Unstake: {formatUnstakingPeriod(asset.unstakingPeriod)}</div>
                </div>
                <button
                  className="btn-stake"
                  onClick={() => handleStakeClick(asset)}
                >
                  Stake
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Pending Staking Positions */}
      <div className="staking-section">
        <h2 className="section-title">Pending Staking Positions</h2>
        {pendingPositions.length === 0 ? (
          pendingTransactions.length > 0 ? (
            <div className="pending-activity-card">
              <h3>Pending Activity</h3>
              <ul className="pending-activity-list">
                {pendingTransactions.map((txn, index) => (
                  <li key={txn.tranId || `${txn.asset}-${index}`}>
                    <div className="pending-activity-row">
                      <div>
                        <strong>{txn.asset}</strong> · {formatStatusLabel(txn.status)}
                      </div>
                      <div>
                        {parseFloat(txn.amount || 0).toFixed(8)} {txn.asset} ({formatUsd(txn.currentValue)})
                      </div>
                    </div>
                    {txn.initiatedTime && (
                      <div className="pending-activity-time">{formatDate(txn.initiatedTime)}</div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="no-data">No pending staking positions.</p>
          )
        ) : (
          <>
            <div className="staking-table-container">
              <table className="staking-table">
                <thead>
                  <tr>
                    <th>Asset</th>
                    <th>Amount</th>
                    <th>Value</th>
                    <th>Status</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {pendingPositions.map((position, index) => {
                    const amount = position.stakingAmount !== undefined && position.stakingAmount !== null
                      ? parseFloat(position.stakingAmount).toFixed(8)
                      : '-';
                    const value = position.currentValue !== undefined && position.currentValue !== null
                      ? formatUsd(position.currentValue)
                      : '$0.00';
                    const statusKeyRaw = (position.status || position.statusCategory || 'pending').toString().toLowerCase();
                    const statusKey = statusKeyRaw.replace(/\s+/g, '-');
                    const statusLabel = position.statusLabel || formatStatusLabel(position.status || position.statusCategory);
                    return (
                      <tr key={position.id || position.tranId || `pending-${index}`}>
                        <td>{position.asset || position.binanceData?.asset || '—'}</td>
                        <td>{amount} {position.asset || ''}</td>
                        <td>{value}</td>
                        <td>
                          <span className={`status-badge status-${statusKey}`}>
                            {statusLabel}
                          </span>
                        </td>
                        <td>
                          {position.type ? `${position.type.charAt(0).toUpperCase()}${position.type.slice(1)}` : (position.detail || 'Stake')}
                          {position.initiatedTime && (
                            <span style={{ display: 'block', fontSize: '12px', color: '#999', marginTop: '4px' }}>
                              {formatDate(position.initiatedTime)}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {pendingTransactions.length > 0 && (
              <div className="pending-activity-card">
                <h3>Pending Activity</h3>
                <ul className="pending-activity-list">
                  {pendingTransactions.map((txn, index) => (
                    <li key={txn.tranId || `${txn.asset}-${index}`}>
                      <div className="pending-activity-row">
                        <div>
                          <strong>{txn.asset}</strong> · {formatStatusLabel(txn.status)}
                        </div>
                        <div>
                          {parseFloat(txn.amount || 0).toFixed(8)} {txn.asset} ({formatUsd(txn.currentValue)})
                        </div>
                      </div>
                      {txn.initiatedTime && (
                        <div className="pending-activity-time">{formatDate(txn.initiatedTime)}</div>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>

      {/* Active Staking Positions */}
      <div className="staking-section">
        <div className="section-header">
          <div className="pending-indicator">
            Pending Positions: <span>{balanceSummary.pendingCount ?? pendingPositions.length}</span>
          </div>
          <h2 className="section-title">Active Staking Positions</h2>
        </div>
        {stakedCoins.length === 0 ? (
          <p className="no-data">No active staking positions.</p>
        ) : (
          <div className="staking-table-container">
            <table className="staking-table">
              <thead>
                <tr>
                  <th>Asset</th>
                  <th>Staked</th>
                  <th>Value</th>
                  <th>APY</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {stakedCoins.map((coin, index) => {
                  const amount = coin.amount !== undefined && coin.amount !== null
                    ? parseFloat(coin.amount).toFixed(8)
                    : coin.stakingAmount !== undefined && coin.stakingAmount !== null
                      ? parseFloat(coin.stakingAmount).toFixed(8)
                      : '0.00000000';
                  const value = coin.currentValue !== undefined && coin.currentValue !== null
                    ? formatUsd(coin.currentValue)
                    : '$0.00';
                  const apyDisplay = coin.apy !== undefined && coin.apy !== null
                    ? `${(Number(coin.apy) * 100).toFixed(2)}%`
                    : '—';
                  const statusKeyRaw = (coin.status || coin.statusCategory || 'active').toString().toLowerCase();
                  const statusKey = statusKeyRaw.replace(/\s+/g, '-');
                  const statusLabel = coin.statusLabel || formatStatusLabel(coin.status || coin.statusCategory);
                  const isActive = (coin.status || coin.statusCategory) === 'active';
                  const availableAt = coin.unstakeAvailableAt || coin.localUnstakeAvailableAt;

                  return (
                    <tr key={coin.id || coin.positionId || `${coin.asset}-${index}`}>
                      <td>{coin.asset}</td>
                      <td>{amount} {coin.asset}</td>
                      <td>{value}</td>
                      <td className="apy-cell">{apyDisplay}</td>
                      <td>
                        <span className={`status-badge status-${statusKey}`}>
                          {statusLabel}
                        </span>
                      </td>
                      <td>
                        {(statusKey === 'active' || statusKey === 'staked' || coin.can_redeem) &&
                          statusKey !== 'unstaking' &&
                          statusKey !== 'redeeming' &&
                          statusKey !== 'unbonding' ? (
                          <button
                            className="btn-unstake"
                            onClick={() => handleUnstakeClick(coin)}
                          >
                            Unstake
                          </button>
                        ) : (
                          <button className="btn-unstake disabled" disabled>
                            {statusKey === 'unstaking' || statusKey === 'redeeming' || statusKey === 'unbonding' ? 'Unstaking' : 'Locked'}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Transaction History */}
      <div className="staking-section">
        <h2 className="section-title">Transaction History</h2>
        {stakingHistory.length === 0 ? (
          <p className="no-data">No staking history.</p>
        ) : (
          <div className="history-table-container">
            <table className="history-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Type</th>
                  <th>Amount</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {stakingHistory.map((transaction, index) => {
                  const typeKey = (transaction.type || 'unknown').toLowerCase();
                  const typeLabel = typeKey === 'stake'
                    ? 'Stake'
                    : typeKey === 'unstake'
                      ? 'Unstake'
                      : formatStatusLabel(typeKey);
                  const statusKey = (transaction.status || 'unknown').toLowerCase().replace(/\s+/g, '-');
                  const statusLabel = formatStatusLabel(transaction.status);
                  const amountDisplay = transaction.amount !== undefined && transaction.amount !== null
                    ? parseFloat(transaction.amount).toFixed(8)
                    : '0.00000000';

                  return (
                    <tr key={index}>
                      <td>{formatDate(transaction.initiatedTime)}</td>
                      <td>
                        <span className={`type-badge type-${typeKey}`}>
                          {typeLabel}
                        </span>
                      </td>
                      <td>{amountDisplay} {transaction.asset}</td>
                      <td>
                        <span className={`status-badge status-${statusKey}`}>
                          {statusLabel}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Stake Modal */}
      {showStakeModal && selectedAsset && (
        <div className="modal-overlay" onClick={() => setShowStakeModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Stake {selectedAsset.stakingAsset}</h3>
              <button className="modal-close" onClick={() => setShowStakeModal(false)}>×</button>
            </div>
            <div className="modal-body">
              {/* Real-time Balance Display from Binance API */}
              {fetchingBalance ? (
                <div className="available-balance-info">
                  <h4>💰 Checking Available Balance...</h4>
                  <div className="balance-details">
                    <div style={{ color: '#888', fontSize: '14px' }}>
                      Fetching real-time balance from Binance...
                    </div>
                  </div>
                </div>
              ) : realtimeBalance ? (
                <div className="available-balance-info">
                  <h4>💰 Available to Stake (Binance):</h4>
                  <div className="balance-details">
                    <div className="balance-amount">
                      {realtimeBalance.tradable.toFixed(8)} {selectedAsset.stakingAsset}
                    </div>
                    <div className="balance-value">
                      ≈ ${(realtimeBalance.tradable * realtimeBalance.price).toFixed(2)} USDT
                    </div>
                  </div>
                  <div style={{ fontSize: '12px', color: '#888', marginTop: '8px' }}>
                    Real-time data from Binance.US
                  </div>
                  {realtimeBalance.reservedByOrders > 0 && (
                    <div style={{ marginTop: '8px', color: '#ffcc00', fontSize: '13px' }}>
                      Note: Your entire {selectedAsset.stakingAsset} balance is not available to stake due to an open order.
                    </div>
                  )}
                </div>
              ) : portfolioMap[selectedAsset.stakingAsset] ? (
                <div className="available-balance-info">
                  <h4>💰 Portfolio Balance:</h4>
                  <div className="balance-details">
                    <div className="balance-amount">
                      {portfolioMap[selectedAsset.stakingAsset].balance} {selectedAsset.stakingAsset}
                    </div>
                    <div className="balance-value">
                      ≈ ${portfolioMap[selectedAsset.stakingAsset].value?.toFixed(2)} USDT
                    </div>
                  </div>
                  <div style={{ fontSize: '12px', color: '#888', marginTop: '8px' }}>
                    Loading real-time balance...
                  </div>
                </div>
              ) : null}

              <div className="modal-info">
                <div className="info-row">
                  <span>Amount to Stake:</span>
                </div>
                <input
                  type="number"
                  className="stake-input"
                  value={stakeAmount}
                  onChange={(e) => setStakeAmount(e.target.value)}
                  placeholder={`Min: ${selectedAsset.minStakingLimit}`}
                  step="0.00000001"
                />
              </div>

              <div className="auto-restake-option">
                <label>
                  <input
                    type="checkbox"
                    checked={autoRestake}
                    onChange={(e) => setAutoRestake(e.target.checked)}
                  />
                  <span>Auto-restake rewards</span>
                </label>
              </div>

              <div className="estimated-returns">
                <h4>📊 Estimated Annual Return:</h4>
                <div className="returns-detail">
                  <div>APR: {(selectedAsset.apr * 100).toFixed(2)}% → ${(parseFloat(stakeAmount || 0) * selectedAsset.apr).toFixed(2)}/year</div>
                  <div>APY: {(selectedAsset.apy * 100).toFixed(2)}% (with auto-restake)</div>
                </div>
              </div>

              <div className="warning-message">
                ⚠️ Unstaking Period: {formatUnstakingPeriod(selectedAsset.unstakingPeriod)}
              </div>

              <div className="min-max-info">
                Min Stake: {selectedAsset.minStakingLimit} {selectedAsset.stakingAsset} |
                Max: {selectedAsset.maxStakingLimit} {selectedAsset.stakingAsset}
              </div>

              {/* 2FA Input Section */}
              {showTwoFactorInput && (
                <div className="two-factor-section" style={{
                  marginTop: '20px',
                  padding: '15px',
                  background: 'rgba(33, 150, 243, 0.1)',
                  borderRadius: '8px',
                  border: '1px solid rgba(33, 150, 243, 0.3)'
                }}>
                  <h4 style={{ marginBottom: '10px', fontSize: '16px' }}>🔐 Two-Factor Authentication</h4>
                  <p style={{ fontSize: '13px', color: '#aaa', marginBottom: '10px' }}>
                    Enter your 6-digit authentication code:
                  </p>
                  <input
                    type="text"
                    inputMode="numeric"
                    pattern="[0-9]*"
                    maxLength="6"
                    value={twoFactorCode}
                    onChange={(e) => {
                      const value = e.target.value.replace(/\D/g, '').slice(0, 6);
                      setTwoFactorCode(value);
                      setTwoFactorError('');
                    }}
                    placeholder="000000"
                    className="stake-input"
                    style={{
                      textAlign: 'center',
                      fontSize: '24px',
                      letterSpacing: '8px',
                      fontWeight: 'bold',
                      marginBottom: '10px'
                    }}
                    autoFocus={false}
                    disabled={verifying2FA}
                  />
                  <p style={{ fontSize: '12px', color: '#888' }}>
                    Enter the code from your authenticator app (e.g., Bitwarden, Google Authenticator)
                  </p>
                  {twoFactorError && (
                    <div style={{
                      marginTop: '10px',
                      padding: '10px',
                      background: 'rgba(244, 67, 54, 0.1)',
                      border: '1px solid rgba(244, 67, 54, 0.3)',
                      borderRadius: '4px',
                      color: '#f44336',
                      fontSize: '13px'
                    }}>
                      ❌ {twoFactorError}
                    </div>
                  )}
                </div>
              )}
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => {
                setShowStakeModal(false);
                setTwoFactorCode('');
                setTwoFactorError('');
                setShowTwoFactorInput(!!(settings.require_2fa && settings.totp_enabled));
              }}>Cancel</button>
              <button
                className="btn btn-primary"
                onClick={handleStakeSubmit}
                disabled={verifying2FA || (showTwoFactorInput && twoFactorCode.length !== 6)}
              >
                {verifying2FA ? '⏳ Verifying...' : '✓ Verify & Stake'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Unstake Modal */}
      {showUnstakeModal && selectedStakedCoin && (
        <div className="modal-overlay" onClick={() => setShowUnstakeModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Unstake {selectedStakedCoin.asset}</h3>
              <button className="modal-close" onClick={() => setShowUnstakeModal(false)}>×</button>
            </div>
            <div className="modal-body">
              <div className="modal-info">
                <div className="info-row">
                  <span>Currently Staked: {selectedStakedCoin.stakingAmount.toFixed(8)} {selectedStakedCoin.asset}</span>
                </div>
                <div className="info-row">
                  <span>Amount to Unstake:</span>
                </div>
                <input
                  type="number"
                  className="stake-input"
                  value={unstakeAmount}
                  onChange={(e) => setUnstakeAmount(e.target.value)}
                  placeholder="0.00000000"
                  step="0.00000001"
                  max={selectedStakedCoin.stakingAmount}
                />
                <button
                  className="btn-max"
                  onClick={() => setUnstakeAmount(selectedStakedCoin.stakingAmount.toString())}
                >
                  Max
                </button>
              </div>

              <div className="warning-message">
                ⚠️ Important:<br />
                • Unstaking takes time to process<br />
                • No rewards earned during unstaking<br />
                • Funds will return to spot wallet
              </div>

              <div className="unstake-summary">
                You will receive:<br />
                <strong>{parseFloat(unstakeAmount || 0).toFixed(8)} {selectedStakedCoin.asset}</strong>
                {' '}(~${(parseFloat(unstakeAmount || 0) * selectedStakedCoin.currentPrice).toFixed(2)})
              </div>

              {/* 2FA Input Section */}
              {showTwoFactorInput && (
                <div className="two-factor-section" style={{
                  marginTop: '20px',
                  padding: '15px',
                  background: 'rgba(244, 67, 54, 0.1)',
                  borderRadius: '8px',
                  border: '1px solid rgba(244, 67, 54, 0.3)'
                }}>
                  <h4 style={{ marginBottom: '10px', fontSize: '16px' }}>🔐 Two-Factor Authentication</h4>
                  <p style={{ fontSize: '13px', color: '#aaa', marginBottom: '10px' }}>
                    Enter your 6-digit authentication code:
                  </p>
                  <input
                    type="text"
                    inputMode="numeric"
                    pattern="[0-9]*"
                    maxLength="6"
                    value={twoFactorCode}
                    onChange={(e) => {
                      const value = e.target.value.replace(/\D/g, '').slice(0, 6);
                      setTwoFactorCode(value);
                    }}
                    placeholder="000000"
                    style={{
                      width: '100%',
                      padding: '12px',
                      fontSize: '20px',
                      textAlign: 'center',
                      letterSpacing: '5px',
                      background: 'rgba(0,0,0,0.2)',
                      border: '1px solid #444',
                      borderRadius: '4px',
                      color: 'white'
                    }}
                  />
                  {twoFactorError && (
                    <div style={{ color: '#f44336', fontSize: '13px', marginTop: '10px', textAlign: 'center' }}>
                      {twoFactorError}
                    </div>
                  )}
                </div>
              )}
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" disabled={verifying2FA} onClick={() => setShowUnstakeModal(false)}>Cancel</button>
              <button
                className="btn btn-danger"
                onClick={handleUnstakeSubmit}
                disabled={verifying2FA || (showTwoFactorInput && twoFactorCode.length !== 6)}
              >
                {verifying2FA ? 'Verifying...' : 'Confirm Unstake'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
