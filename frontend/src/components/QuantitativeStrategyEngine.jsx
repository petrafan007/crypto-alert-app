import React, { useState, useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import axios from 'axios';
import './QuantitativeStrategyEngine.css';

const DEFAULT_ALLOCATIONS = {
  equities: 35.0,
  options: 25.0,
  crypto: 20.0,
  futures: 10.0,
  events: 10.0,
};

const DEFAULT_WATCHLISTS = {
  equities: ['SPY', 'QQQ', 'IWM', 'SMH', 'XLK', 'NVDA', 'AAPL', 'MSFT', 'AMZN', 'TSLA'],
  options: ['SPY', 'QQQ', 'IWM', 'NVDA', 'TSLA'],
  crypto: ['BTC', 'ETH', 'SOL'],
  futures: ['MES', 'MNQ', 'MGC', 'MCL'],
  events: ['KXBTC15M', 'KXBTCD', 'KXETH15M', 'KXINXD'],
};

const ASSET_MODULE_DEFS = {
  equities: {
    key: 'equities',
    title: 'Equities & ETFs',
    icon: '📈',
    color: '#3b82f6',
    sliceClass: 'slice-equities',
    strategy: 'Dual-Momentum Rotation & 2-Period RSI',
    targetCagr: '12%–16% CAGR',
    defaultWeight: 35.0,
    paramLabels: [
      { key: 'trend_sma_days', label: '200-Day SMA Filter', defaultVal: 'Active' },
      { key: 'rsi_period', label: 'RSI Period', defaultVal: '2' },
      { key: 'rsi_entry_threshold', label: 'Oversold Pullback', defaultVal: '< 10' },
      { key: 'bollinger_std', label: 'Bollinger Bands', defaultVal: '2.0σ' },
    ],
  },
  options: {
    key: 'options',
    title: 'Options Strategies',
    icon: '⚡',
    color: '#8b5cf6',
    sliceClass: 'slice-options',
    strategy: 'Volatility Risk Premium 45-DTE Credit Spreads',
    targetCagr: '18%–24% CAGR',
    defaultWeight: 25.0,
    paramLabels: [
      { key: 'min_ivr', label: 'Min IV Rank (IVR)', defaultVal: '≥ 40' },
      { key: 'target_delta', label: 'Target Short Delta', defaultVal: '18Δ (~82% POP)' },
      { key: 'target_dte', label: 'Expiration Horizon', defaultVal: '45 DTE' },
      { key: 'profit_target_pct', label: 'Take Profit Rule', defaultVal: '50% Max Profit' },
    ],
  },
  crypto: {
    key: 'crypto',
    title: 'Cryptocurrency Spot',
    icon: '🪙',
    color: '#f59e0b',
    sliceClass: 'slice-crypto',
    strategy: 'Adaptive Donchian Breakout & ATR Stops',
    targetCagr: '20%–35% CAGR',
    defaultWeight: 20.0,
    paramLabels: [
      { key: 'entry_channel_periods', label: 'Donchian Entry', defaultVal: '20 Periods' },
      { key: 'exit_channel_periods', label: 'Donchian Exit', defaultVal: '10 Periods' },
      { key: 'atr_stop_multiplier', label: 'Volatility Trailing Stop', defaultVal: '2.5× ATR' },
      { key: 'regime_filter', label: 'BTC Dominance Alignment', defaultVal: 'Enabled' },
    ],
  },
  futures: {
    key: 'futures',
    title: 'Micro Futures',
    icon: '⏱️',
    color: '#10b981',
    sliceClass: 'slice-futures',
    strategy: 'Opening Range Breakout (ORB) & VWAP Reversion',
    targetCagr: '15%–22% CAGR',
    defaultWeight: 10.0,
    paramLabels: [
      { key: 'opening_range_minutes', label: 'ORB Horizon', defaultVal: '15 Minutes (9:30 ET)' },
      { key: 'max_intraday_loss', label: 'Max Daily Loss Ceiling', defaultVal: '$250.00' },
      { key: 'vwap_filter', label: 'VWAP Reversion Anchor', defaultVal: 'Active' },
      { key: 'contracts', label: 'Micro Indices & Commodities', defaultVal: 'MES, MNQ, MGC' },
    ],
  },
  events: {
    key: 'events',
    title: 'Event Contracts',
    icon: '🎯',
    color: '#ec4899',
    sliceClass: 'slice-events',
    strategy: 'Binary Probability & Velocity Arbitrage',
    targetCagr: '20%–30% CAGR',
    defaultWeight: 10.0,
    paramLabels: [
      { key: 'contract_horizon', label: 'Contract Cadence', defaultVal: '15-Min & Hourly' },
      { key: 'min_confidence', label: 'Min Confidence Floor', defaultVal: '50%' },
      { key: 'min_net_edge', label: 'Min Mathematical Edge', defaultVal: '1.5% Net' },
      { key: 'broker_safety', label: 'Order Execution State', defaultVal: 'Paper / Zero Route' },
    ],
  },
};

const formatCurrency = (val) => {
  const num = Number(val);
  if (!Number.isFinite(num)) return '$50,000.00';
  return `$${num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

export default function QuantitativeStrategyEngine({
  isLightMode,
  user,
  eventStrategyConfig,
  setEventStrategyConfig,
  eventStrategyHealth,
  eventStrategyBusy,
  eventStrategyMessage,
  setEventStrategyMessage,
  saveEventStrategy,
  eventStrategyAction,
  loadEventStrategyLogs,
  loadEventStrategyReport,
  openEventStrategyAIModal,
  updateEventStrategySignal,
  updateEventStrategyDuration,
  EVENT_STRATEGY_DURATIONS,
  formatEasternDateTime,
}) {
  const [config, setConfig] = useState(null);
  const [account, setAccount] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  // Modals state
  const [activeGearModal, setActiveGearModal] = useState(null);
  const [showBankrollResetModal, setShowBankrollResetModal] = useState(false);
  const [resetBankrollAmount, setResetBankrollAmount] = useState(50000);
  const [resettingBankroll, setResettingBankroll] = useState(false);

  // Master Portfolio AI Audit state
  const [showMasterAIModal, setShowMasterAIModal] = useState(false);
  const [masterAIAuditLoading, setMasterAIAuditLoading] = useState(false);
  const [masterAIAuditResult, setMasterAIAuditResult] = useState(null);
  const [masterAIPromptDraft, setMasterAIPromptDraft] = useState('');

  // Watchlist new symbol input state per module
  const [newSymbolInputs, setNewSymbolInputs] = useState({
    equities: '',
    options: '',
    crypto: '',
    futures: '',
    events: '',
  });

  const loadPortfolioData = async () => {
    try {
      setLoading(true);
      const [cfgRes, statusRes] = await Promise.all([
        axios.get('/api/webull/portfolio-algo/config', { withCredentials: true }),
        axios.get('/api/webull/portfolio-algo/status', { withCredentials: true }),
      ]);
      if (cfgRes.data?.success) {
        setConfig(cfgRes.data.config);
        setAccount(cfgRes.data.account);
        setMasterAIPromptDraft(cfgRes.data.config?.master_ai_prompt || '');
      }
    } catch (err) {
      console.error('Failed to load portfolio algo config:', err);
      setMessage(err.response?.data?.message || 'Unable to load Quantitative Strategy Engine.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPortfolioData();
  }, []);

  // Compute allocation metrics
  const allocations = useMemo(() => {
    return config?.allocations || DEFAULT_ALLOCATIONS;
  }, [config?.allocations]);

  const totalAllocation = useMemo(() => {
    return Object.values(allocations).reduce((sum, val) => sum + (Number(val) || 0), 0);
  }, [allocations]);

  const isAllocationValid = Math.abs(totalAllocation - 100.0) <= 0.05;

  const totalBankroll = account?.total_equity || config?.total_bankroll || 50000.0;
  const targetAnnualReturn = config?.target_annual_return || 18.5;

  // Handle allocation slider change
  const handleAllocationChange = (moduleKey, newVal) => {
    const val = Math.max(0, Math.min(100, parseFloat(newVal) || 0));
    setConfig((prev) => ({
      ...prev,
      allocations: {
        ...(prev?.allocations || DEFAULT_ALLOCATIONS),
        [moduleKey]: val,
      },
    }));
  };

  // Watchlist manipulation
  const handleRemoveSymbol = (moduleKey, symbolToRemove) => {
    setConfig((prev) => {
      const currentList = prev?.watchlists?.[moduleKey] || DEFAULT_WATCHLISTS[moduleKey] || [];
      const updated = currentList.filter((s) => s !== symbolToRemove);
      return {
        ...prev,
        watchlists: {
          ...(prev?.watchlists || DEFAULT_WATCHLISTS),
          [moduleKey]: updated,
        },
      };
    });
  };

  const handleAddSymbol = (moduleKey) => {
    const inputVal = (newSymbolInputs[moduleKey] || '').trim().toUpperCase();
    if (!inputVal) return;
    setConfig((prev) => {
      const currentList = prev?.watchlists?.[moduleKey] || DEFAULT_WATCHLISTS[moduleKey] || [];
      if (currentList.includes(inputVal)) return prev;
      return {
        ...prev,
        watchlists: {
          ...(prev?.watchlists || DEFAULT_WATCHLISTS),
          [moduleKey]: [...currentList, inputVal],
        },
      };
    });
    setNewSymbolInputs((prev) => ({ ...prev, [moduleKey]: '' }));
  };

  // Save allocations & watchlists
  const handleSavePortfolioConfig = async () => {
    if (!isAllocationValid) {
      setMessage(`Allocations must sum exactly to 100% (currently ${totalAllocation.toFixed(1)}%).`);
      return;
    }
    setSaving(true);
    setMessage('');
    try {
      const response = await axios.post(
        '/api/webull/portfolio-algo/config',
        {
          total_bankroll: config.total_bankroll,
          target_annual_return: config.target_annual_return,
          allocations: config.allocations,
          watchlists: config.watchlists,
          module_settings: config.module_settings,
          master_ai_prompt: masterAIPromptDraft,
        },
        { withCredentials: true }
      );
      if (response.data?.success) {
        setMessage('Quantitative Strategy Engine parameters saved successfully.');
        await loadPortfolioData();
      }
    } catch (err) {
      setMessage(err.response?.data?.message || 'Failed to save Quantitative Strategy Engine configuration.');
    } finally {
      setSaving(false);
    }
  };

  // Reset paper bankroll
  const handleBankrollResetConfirm = async () => {
    setResettingBankroll(true);
    try {
      const response = await axios.post(
        '/api/webull/portfolio-algo/reset-bankroll',
        { amount: resetBankrollAmount },
        { withCredentials: true }
      );
      if (response.data?.success) {
        setMessage(response.data.message || 'Paper bankroll successfully reset.');
        setShowBankrollResetModal(false);
        await loadPortfolioData();
      }
    } catch (err) {
      setMessage(err.response?.data?.message || 'Failed to reset bankroll.');
    } finally {
      setResettingBankroll(false);
    }
  };

  // Run Master Portfolio AI Audit
  const handleRunMasterAIAudit = async () => {
    setMasterAIAuditLoading(true);
    try {
      const response = await axios.post(
        '/api/webull/portfolio-algo/master-audit',
        { prompt: masterAIPromptDraft },
        { withCredentials: true }
      );
      if (response.data?.success) {
        setMasterAIAuditResult(response.data.audit);
      }
    } catch (err) {
      console.error('Master AI Audit failed:', err);
      setMessage(err.response?.data?.message || 'Failed to execute Master AI Audit.');
    } finally {
      setMasterAIAuditLoading(false);
    }
  };

  if (loading && !config) {
    return (
      <div style={{ padding: '40px 0', textAlign: 'center', color: isLightMode ? '#64748b' : '#94a3b8' }}>
        Loading Quantitative Strategy Engine infrastructure...
      </div>
    );
  }

  return (
    <div className="quant-engine-container">
      {/* MASTER RIBBON */}
      <section className="quant-master-ribbon" aria-label="Quantitative Strategy Engine Master Ribbon">
        <div className="quant-master-ribbon-top">
          <div className="quant-title-area">
            <h2>
              <span>🏛️</span> Quantitative Strategy Engine
            </h2>
            <p>
              Autonomous Multi-Asset Paper Trading & Quantitative Research Framework. Dynamic capital allocation matrix
              with 5 domain-specialist strategy modules, isolated paper ledger, and Chief Investment Officer AI audit.
            </p>
          </div>

          <div className="quant-ribbon-badges">
            <span className="quant-badge-paper">🛡️ Forward Paper Mode</span>
            <span className="quant-badge-isolated">Isolated Paper Ledger</span>
          </div>
        </div>

        {message && (
          <div
            className="settings-message"
            style={{ marginBottom: 16, background: 'rgba(56, 189, 248, 0.15)', borderColor: '#38bdf8' }}
          >
            {message}
          </div>
        )}

        {/* METRICS ROW */}
        <div className="quant-ribbon-metrics">
          {/* Total Bankroll Metric */}
          <div className="quant-metric-card">
            <div className="quant-metric-label">
              <span>Paper Bankroll</span>
              <button
                type="button"
                className="btn-quant-reset-bankroll"
                onClick={() => setShowBankrollResetModal(true)}
                title="Reset isolated quant bankroll to $50,000"
              >
                🔄 Reset
              </button>
            </div>
            <div className="quant-metric-value bankroll">{formatCurrency(totalBankroll)}</div>
            <div className="quant-metric-footer">
              <span>Dedicated Quant Ledger</span>
              <span>Cash: {formatCurrency(account?.cash_balance || totalBankroll)}</span>
            </div>
          </div>

          {/* Target Annual Return Metric */}
          <div className="quant-metric-card">
            <div className="quant-metric-label">
              <span>Target Net Annual Return</span>
              <span style={{ fontSize: '0.75rem', color: '#a855f7', fontWeight: 700 }}>Mandate: 16.5%–21.0%</span>
            </div>
            <div className="quant-metric-value return">
              <span>{targetAnnualReturn.toFixed(1)}%</span>
              <span style={{ fontSize: '0.9rem', fontWeight: 600, color: '#94a3b8' }}>CAGR</span>
            </div>
            <div className="quant-metric-footer">
              <input
                type="range"
                min="10.0"
                max="35.0"
                step="0.5"
                value={targetAnnualReturn}
                onChange={(e) =>
                  setConfig((prev) => ({ ...prev, target_annual_return: parseFloat(e.target.value) || 18.5 }))
                }
                style={{ width: '100%', accentColor: '#a855f7' }}
              />
            </div>
          </div>

          {/* 5-Asset Allocation Summary Metric */}
          <div className="quant-metric-card">
            <div className="quant-metric-label">
              <span>Capital Allocation Status</span>
              <span className={`quant-allocation-sum-badge ${isAllocationValid ? 'valid' : 'invalid'}`}>
                {isAllocationValid ? '100% Compliant' : `${totalAllocation.toFixed(1)}% Sum Check`}
              </span>
            </div>
            <div className="quant-metric-value" style={{ color: isAllocationValid ? '#4ade80' : '#f87171' }}>
              {totalAllocation.toFixed(1)}%
            </div>
            <div className="quant-metric-footer">
              <span>5 Asset Classes Weighted</span>
              <span>{isAllocationValid ? 'Balanced' : 'Adjust Sliders to 100%'}</span>
            </div>
          </div>
        </div>

        {/* 5-SLICE COLOR ALLOCATION BAR */}
        <div className="quant-allocation-section">
          <div className="quant-allocation-header">
            <span className="quant-allocation-title">Strategic Capital Distribution Matrix</span>
            <span style={{ fontSize: '0.78rem', color: '#94a3b8' }}>
              Equities: {allocations.equities}% · Options: {allocations.options}% · Crypto: {allocations.crypto}% · Futures: {allocations.futures}% · Events: {allocations.events}%
            </span>
          </div>

          <div className="quant-multi-bar" role="progressbar" aria-valuenow={totalAllocation} aria-valuemin="0" aria-valuemax="100">
            {Object.keys(ASSET_MODULE_DEFS).map((key) => {
              const def = ASSET_MODULE_DEFS[key];
              const weight = Number(allocations[key]) || 0;
              if (weight <= 0) return null;
              const capVal = totalBankroll * (weight / 100);
              return (
                <div
                  key={key}
                  className={`quant-bar-slice ${def.sliceClass}`}
                  style={{ width: `${(weight / Math.max(1, totalAllocation)) * 100}%` }}
                  title={`${def.title}: ${weight}% (${formatCurrency(capVal)})`}
                >
                  {weight >= 8 ? `${def.title.split(' ')[0]} ${weight}%` : `${weight}%`}
                </div>
              );
            })}
          </div>

          <div className="quant-bar-legend">
            {Object.keys(ASSET_MODULE_DEFS).map((key) => {
              const def = ASSET_MODULE_DEFS[key];
              const weight = Number(allocations[key]) || 0;
              const capVal = totalBankroll * (weight / 100);
              return (
                <div key={key} className="quant-legend-item">
                  <span className="quant-legend-dot" style={{ background: def.color }} />
                  <span>
                    <strong>{def.title}:</strong> {weight}% ({formatCurrency(capVal)})
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* MASTER ACTIONS */}
        <div className="quant-ribbon-actions">
          <button
            type="button"
            className="btn-quant-ai-audit"
            onClick={() => {
              setShowMasterAIModal(true);
              if (!masterAIAuditResult) handleRunMasterAIAudit();
            }}
          >
            <span>🤖</span> Master Portfolio AI Audit
          </button>
          <button
            type="button"
            className="btn-quant-save"
            disabled={saving || !isAllocationValid}
            onClick={handleSavePortfolioConfig}
          >
            {saving ? 'Saving...' : '💾 Save Allocations & Watchlists'}
          </button>
        </div>
      </section>

      {/* 5 ASSET MODULE CARDS GRID */}
      <div className="quant-cards-grid">
        {Object.keys(ASSET_MODULE_DEFS).map((modKey) => {
          const def = ASSET_MODULE_DEFS[modKey];
          const weight = Number(allocations[modKey]) || 0;
          const capVal = totalBankroll * (weight / 100);
          const watchlist = config?.watchlists?.[modKey] || DEFAULT_WATCHLISTS[modKey] || [];

          return (
            <div key={modKey} className="quant-module-card">
              {/* Card Header */}
              <div>
                <div className="quant-card-header">
                  <div className="quant-card-title-group">
                    <span className="quant-card-icon">{def.icon}</span>
                    <h3 className="quant-card-title">{def.title}</h3>
                  </div>
                  <button
                    type="button"
                    className="quant-gear-btn"
                    onClick={() => setActiveGearModal(modKey)}
                    title={`Configure ${def.title} Strategy & Specialist AI`}
                    aria-label={`Configure ${def.title}`}
                  >
                    ⚙️
                  </button>
                </div>

                <div className="quant-card-meta">
                  <span
                    className="quant-alloc-badge"
                    style={{ background: `${def.color}22`, border: `1px solid ${def.color}`, color: def.color }}
                  >
                    {weight}% · {formatCurrency(capVal)}
                  </span>
                  <span className="quant-cagr-badge">{def.targetCagr}</span>
                </div>

                <div className="quant-strategy-name">{def.strategy}</div>

                {/* Weight Slider */}
                <div className="quant-card-slider-group">
                  <div className="quant-card-slider-labels">
                    <span>Allocation Weight</span>
                    <strong>
                      {weight}% ({formatCurrency(capVal)})
                    </strong>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    step="1"
                    value={weight}
                    onChange={(e) => handleAllocationChange(modKey, e.target.value)}
                    className="quant-slider"
                    style={{ accentColor: def.color }}
                  />
                </div>

                {/* Watchlist Chips */}
                <div className="quant-watchlist-area">
                  <div className="quant-watchlist-title">
                    <span>Watchlist ({watchlist.length})</span>
                  </div>
                  <div className="quant-chips-container">
                    {watchlist.map((sym) => (
                      <span key={sym} className="quant-chip">
                        <span>{sym}</span>
                        <button
                          type="button"
                          className="quant-chip-remove"
                          onClick={() => handleRemoveSymbol(modKey, sym)}
                          title={`Remove ${sym}`}
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                  <div className="quant-add-chip-form">
                    <input
                      type="text"
                      placeholder="+ Add ticker"
                      value={newSymbolInputs[modKey] || ''}
                      onChange={(e) => setNewSymbolInputs((prev) => ({ ...prev, [modKey]: e.target.value }))}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          handleAddSymbol(modKey);
                        }
                      }}
                      className="quant-add-chip-input"
                    />
                    <button
                      type="button"
                      className="quant-add-chip-btn"
                      onClick={() => handleAddSymbol(modKey)}
                    >
                      Add
                    </button>
                  </div>
                </div>
              </div>

              {/* Mini Parameter Footers */}
              <div className="quant-card-params">
                {def.paramLabels.map((param) => (
                  <div key={param.key} className="quant-param-item">
                    <span>{param.label}</span>
                    <strong>{param.defaultVal}</strong>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* ========================================================================= */}
      {/* ⚙️ GEAR MODALS                                                           */}
      {/* ========================================================================= */}

      {/* 1. EVENT CONTRACTS GEAR MODAL (100% of existing controls preserved) */}
      {activeGearModal === 'events' && createPortal(
        <div className="quant-modal-overlay" role="dialog" aria-modal="true">
          <div className="quant-modal-dialog" style={{ width: 'min(1100px, 96vw)' }}>
            <div className="quant-modal-header">
              <h3>
                <span>🎯</span> Event Contracts Strategy Engine Configuration &amp; Controls
              </h3>
              <button
                type="button"
                className="quant-modal-close-btn"
                onClick={() => setActiveGearModal(null)}
                aria-label="Close configuration"
              >
                ✕
              </button>
            </div>

            <div className="quant-modal-body">
              {eventStrategyMessage && (
                <div className="settings-message" style={{ marginBottom: 12 }}>
                  {eventStrategyMessage}
                </div>
              )}

              {/* Status grid */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12, marginBottom: 16 }}>
                {[
                  ['worker_status', 'Worker', eventStrategyHealth?.worker_status || eventStrategyConfig?.worker_status || 'STOPPED'],
                  ['last_run', 'Last scan', eventStrategyHealth?.last_run ? formatEasternDateTime(eventStrategyHealth.last_run) : '—'],
                  ['heartbeat_at', 'Last heartbeat', eventStrategyHealth?.heartbeat_at ? formatEasternDateTime(eventStrategyHealth.heartbeat_at) : '—'],
                  ['next_expected_scan', 'Next expected scan', eventStrategyHealth?.next_expected_scan ? formatEasternDateTime(eventStrategyHealth.next_expected_scan) : '—'],
                  ['ai_batch_calls_last_hour', 'AI batches (last hour)', `${eventStrategyHealth?.ai_batch_calls_last_hour ?? 0} / ${eventStrategyHealth?.ai_batch_budget_per_hour ?? 12}`],
                  ['ai_evaluations', 'AI evaluation states', (() => {
                    const evals = eventStrategyHealth?.ai_evaluations;
                    if (!evals || typeof evals !== 'object' || Object.keys(evals).length === 0) {
                      return <span style={{ color: isLightMode ? '#718096' : '#94a3b8', fontStyle: 'italic', fontSize: '0.85rem' }}>No evaluations yet</span>;
                    }
                    const badgeMap = {
                      SUCCESS: { bg: isLightMode ? '#dcfce7' : 'rgba(34, 197, 94, 0.18)', border: '#22c55e', text: isLightMode ? '#15803d' : '#4ade80', label: 'Success' },
                      SKIPPED: { bg: isLightMode ? '#fef3c7' : 'rgba(234, 179, 8, 0.18)', border: '#eab308', text: isLightMode ? '#b45309' : '#fde047', label: 'Skipped' },
                      INVALID: { bg: isLightMode ? '#fee2e2' : 'rgba(239, 68, 68, 0.18)', border: '#ef4444', text: isLightMode ? '#b91c1c' : '#f87171', label: 'Invalid' },
                      FAILED: { bg: isLightMode ? '#fee2e2' : 'rgba(239, 68, 68, 0.18)', border: '#ef4444', text: isLightMode ? '#b91c1c' : '#f87171', label: 'Failed' },
                      PENDING: { bg: isLightMode ? '#e0f2fe' : 'rgba(56, 189, 248, 0.18)', border: '#38bdf8', text: isLightMode ? '#0369a1' : '#7dd3fc', label: 'Pending' },
                    };
                    return (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                        {Object.entries(evals).map(([k, count]) => {
                          const conf = badgeMap[k.toUpperCase()] || {
                            bg: isLightMode ? '#f1f5f9' : 'rgba(148, 163, 184, 0.18)',
                            border: '#94a3b8',
                            text: isLightMode ? '#475569' : '#cbd5e1',
                            label: k.charAt(0) + k.slice(1).toLowerCase(),
                          };
                          return (
                            <span
                              key={k}
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 4,
                                padding: '2px 8px',
                                borderRadius: 6,
                                fontSize: '0.8rem',
                                fontWeight: 600,
                                background: conf.bg,
                                border: `1px solid ${conf.border}`,
                                color: conf.text,
                              }}
                            >
                              <span>{conf.label}:</span>
                              <span>{count}</span>
                            </span>
                          );
                        })}
                      </div>
                    );
                  })()],
                ].map(([cardKey, label, value]) => (
                  <div key={label} style={{ padding: '12px 14px', borderRadius: 8, background: isLightMode ? '#edf2f7' : 'rgba(255,255,255,0.05)', border: '1px solid rgba(148,163,184,0.2)' }}>
                    <div style={{ fontSize: 12, color: isLightMode ? '#718096' : '#94a3b8' }}>{label}</div>
                    <div style={{ marginTop: 4, fontWeight: 600, wordBreak: 'break-word' }}>
                      {cardKey === 'ai_evaluations' ? value : String(value || '—')}
                    </div>
                  </div>
                ))}
              </div>

              {/* Action Buttons */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 18 }}>
                <button type="button" className="settings-save-button" disabled={eventStrategyBusy} onClick={saveEventStrategy}>💾 Save settings</button>
                <button type="button" className="settings-action-button" disabled={eventStrategyBusy || eventStrategyConfig?.enabled} onClick={() => eventStrategyAction('start')}>▶ Start</button>
                <button type="button" className="settings-action-button" disabled={eventStrategyBusy || !eventStrategyConfig?.enabled} onClick={() => eventStrategyAction('stop')}>⏸ Stop</button>
                <button type="button" className="settings-action-button" disabled={eventStrategyBusy} onClick={() => eventStrategyAction('scan')}>🔎 Scan now</button>
                <button type="button" className="settings-action-button" disabled={eventStrategyBusy} onClick={loadEventStrategyLogs}>📜 View logs</button>
                <button type="button" className="settings-action-button" disabled={eventStrategyBusy} onClick={() => loadEventStrategyReport()}>📊 View Report</button>
                <button type="button" className="settings-action-button" disabled={eventStrategyBusy} onClick={openEventStrategyAIModal}>🤖 AI Configuration</button>
                <button type="button" className="settings-danger-button" disabled={eventStrategyBusy || eventStrategyConfig?.kill_switch} onClick={() => eventStrategyAction('kill-switch')}>⛔ Kill switch</button>
              </div>

              {/* Strategy Parameters Form */}
              {eventStrategyConfig && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
                  <div>
                    <h4>Research Scope</h4>
                    <label className="settings-form-group">Symbols (comma separated)
                      <input
                        value={(eventStrategyConfig.symbols || []).join(', ')}
                        onChange={(e) =>
                          setEventStrategyConfig((prev) => ({
                            ...prev,
                            symbols: e.target.value.split(',').map((item) => item.trim().toUpperCase()).filter(Boolean),
                          }))
                        }
                      />
                    </label>
                    <div className="settings-form-group">
                      <label>Durations</label>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                        {(EVENT_STRATEGY_DURATIONS || []).map((duration) => (
                          <label key={duration} style={{ display: 'flex', gap: 5, alignItems: 'center', fontSize: 13 }}>
                            <input
                              type="checkbox"
                              checked={(eventStrategyConfig.durations || []).includes(duration)}
                              onChange={(e) => updateEventStrategyDuration(duration, e.target.checked)}
                            />
                            {duration.replace('_', ' ').toLowerCase()}
                          </label>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div>
                    <h4>Collection &amp; AI Frequency</h4>
                    {[
                      ['snapshot_interval_seconds', 'Snapshot collection interval (seconds)'],
                      ['scan_interval_seconds', 'Worker scan interval (seconds)'],
                      ['ai_batch_interval_seconds', 'Minimum interval between AI batches (seconds)'],
                      ['ai_batch_size', 'Contracts per AI batch'],
                      ['max_ai_calls_per_hour', 'Maximum AI batches per hour'],
                      ['ai_cache_ttl_seconds', 'Prediction cache TTL (seconds)'],
                      ['ai_context_refresh_hours', 'Web/search context refresh (hours)'],
                      ['ai_retry_backoff_seconds', 'Initial AI retry backoff (seconds)'],
                    ].map(([key, label]) => (
                      <label key={key} className="settings-form-group" style={{ display: 'block' }}>{label}
                        <input
                          type="number"
                          min="1"
                          value={eventStrategyConfig.signal_config?.[key] ?? ''}
                          onChange={(e) => updateEventStrategySignal(key, e.target.value)}
                        />
                      </label>
                    ))}
                  </div>

                  <div>
                    <h4>AI Cooldown by Contract Duration</h4>
                    {['FIFTEEN_MINUTES', 'HOURLY', 'DAILY', 'WEEKLY', 'MONTHLY', 'ANNUAL', 'ONE_OFF', 'CUSTOM'].map((duration) => (
                      <label key={duration} className="settings-form-group" style={{ display: 'block' }}>
                        {duration.replace('_', ' ').toLowerCase()} cooldown (seconds)
                        <input
                          type="number"
                          min="30"
                          value={eventStrategyConfig.signal_config?.ai_cooldown_by_duration?.[duration] ?? ''}
                          onChange={(e) =>
                            setEventStrategyConfig((prev) => ({
                              ...prev,
                              signal_config: {
                                ...(prev.signal_config || {}),
                                ai_cooldown_by_duration: {
                                  ...(prev.signal_config?.ai_cooldown_by_duration || {}),
                                  [duration]: e.target.value,
                                },
                              },
                            }))
                          }
                        />
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="quant-modal-footer">
              <button
                type="button"
                className="btn-quant-save"
                onClick={() => {
                  saveEventStrategy();
                  setActiveGearModal(null);
                }}
              >
                Save &amp; Close
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* 2. OTHER 4 MODULE GEAR MODALS (Equities, Options, Crypto, Futures) */}
      {activeGearModal && activeGearModal !== 'events' && createPortal(
        <div className="quant-modal-overlay" role="dialog" aria-modal="true">
          <div className="quant-modal-dialog" style={{ width: 'min(920px, 96vw)' }}>
            <div className="quant-modal-header">
              <h3>
                <span>{ASSET_MODULE_DEFS[activeGearModal]?.icon}</span>{' '}
                {ASSET_MODULE_DEFS[activeGearModal]?.title} Strategy &amp; Specialist AI Configuration
              </h3>
              <button
                type="button"
                className="quant-modal-close-btn"
                onClick={() => setActiveGearModal(null)}
                aria-label="Close configuration"
              >
                ✕
              </button>
            </div>

            <div className="quant-modal-body">
              <div style={{ padding: 14, borderRadius: 10, background: 'rgba(56, 189, 248, 0.1)', border: '1px solid rgba(56, 189, 248, 0.25)' }}>
                <div style={{ fontWeight: 700, fontSize: '0.95rem', color: '#38bdf8', marginBottom: 4 }}>
                  Strategy: {ASSET_MODULE_DEFS[activeGearModal]?.strategy}
                </div>
                <div style={{ fontSize: '0.82rem', color: isLightMode ? '#475569' : '#94a3b8' }}>
                  Target CAGR Range: {ASSET_MODULE_DEFS[activeGearModal]?.targetCagr} · Isolated Capital: {allocations[activeGearModal]}% ({formatCurrency(totalBankroll * (allocations[activeGearModal] / 100))})
                </div>
              </div>

              {/* Module-Specific Tuning Parameters */}
              <div>
                <h4 style={{ margin: '0 0 12px 0', fontSize: '1rem', color: isLightMode ? '#0f172a' : '#f8fafc' }}>
                  Quantitative Execution Parameters
                </h4>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14 }}>
                  {activeGearModal === 'equities' && (
                    <>
                      <label className="settings-form-group">200-Day SMA Filter
                        <select
                          value={config?.module_settings?.equities?.trend_sma_days || 200}
                          onChange={(e) => setConfig((prev) => ({
                            ...prev,
                            module_settings: {
                              ...(prev.module_settings || {}),
                              equities: { ...(prev.module_settings?.equities || {}), trend_sma_days: parseInt(e.target.value) || 200 }
                            }
                          }))}
                        >
                          <option value="200">200-Day SMA (Standard Trend Regime)</option>
                          <option value="150">150-Day SMA (Medium Trend Regime)</option>
                          <option value="100">100-Day SMA (Aggressive Trend Regime)</option>
                        </select>
                      </label>
                      <label className="settings-form-group">RSI Period
                        <input
                          type="number"
                          min="2"
                          max="14"
                          value={config?.module_settings?.equities?.rsi_period || 2}
                          onChange={(e) => setConfig((prev) => ({
                            ...prev,
                            module_settings: {
                              ...(prev.module_settings || {}),
                              equities: { ...(prev.module_settings?.equities || {}), rsi_period: parseInt(e.target.value) || 2 }
                            }
                          }))}
                        />
                      </label>
                      <label className="settings-form-group">RSI Entry Threshold (Oversold)
                        <input
                          type="number"
                          min="5"
                          max="30"
                          value={config?.module_settings?.equities?.rsi_entry_threshold || 10}
                          onChange={(e) => setConfig((prev) => ({
                            ...prev,
                            module_settings: {
                              ...(prev.module_settings || {}),
                              equities: { ...(prev.module_settings?.equities || {}), rsi_entry_threshold: parseInt(e.target.value) || 10 }
                            }
                          }))}
                        />
                      </label>
                      <label className="settings-form-group">Bollinger Band Std Dev
                        <input
                          type="number"
                          step="0.1"
                          min="1.0"
                          max="3.0"
                          value={config?.module_settings?.equities?.bollinger_std || 2.0}
                          onChange={(e) => setConfig((prev) => ({
                            ...prev,
                            module_settings: {
                              ...(prev.module_settings || {}),
                              equities: { ...(prev.module_settings?.equities || {}), bollinger_std: parseFloat(e.target.value) || 2.0 }
                            }
                          }))}
                        />
                      </label>
                    </>
                  )}

                  {activeGearModal === 'options' && (
                    <>
                      <label className="settings-form-group">Minimum IV Rank (IVR)
                        <input
                          type="number"
                          min="20"
                          max="80"
                          value={config?.module_settings?.options?.min_ivr || 40}
                          onChange={(e) => setConfig((prev) => ({
                            ...prev,
                            module_settings: {
                              ...(prev.module_settings || {}),
                              options: { ...(prev.module_settings?.options || {}), min_ivr: parseInt(e.target.value) || 40 }
                            }
                          }))}
                        />
                      </label>
                      <label className="settings-form-group">Target Short Delta
                        <input
                          type="number"
                          min="10"
                          max="35"
                          value={config?.module_settings?.options?.target_delta || 18}
                          onChange={(e) => setConfig((prev) => ({
                            ...prev,
                            module_settings: {
                              ...(prev.module_settings || {}),
                              options: { ...(prev.module_settings?.options || {}), target_delta: parseInt(e.target.value) || 18 }
                            }
                          }))}
                        />
                      </label>
                      <label className="settings-form-group">Target DTE Horizon (Days)
                        <input
                          type="number"
                          min="20"
                          max="60"
                          value={config?.module_settings?.options?.target_dte || 45}
                          onChange={(e) => setConfig((prev) => ({
                            ...prev,
                            module_settings: {
                              ...(prev.module_settings || {}),
                              options: { ...(prev.module_settings?.options || {}), target_dte: parseInt(e.target.value) || 45 }
                            }
                          }))}
                        />
                      </label>
                      <label className="settings-form-group">Profit Target (% of Max Credit)
                        <input
                          type="number"
                          min="25"
                          max="75"
                          value={config?.module_settings?.options?.profit_target_pct || 50}
                          onChange={(e) => setConfig((prev) => ({
                            ...prev,
                            module_settings: {
                              ...(prev.module_settings || {}),
                              options: { ...(prev.module_settings?.options || {}), profit_target_pct: parseInt(e.target.value) || 50 }
                            }
                          }))}
                        />
                      </label>
                    </>
                  )}

                  {activeGearModal === 'crypto' && (
                    <>
                      <label className="settings-form-group">Donchian Entry Channel (Periods)
                        <input
                          type="number"
                          min="10"
                          max="50"
                          value={config?.module_settings?.crypto?.entry_channel_periods || 20}
                          onChange={(e) => setConfig((prev) => ({
                            ...prev,
                            module_settings: {
                              ...(prev.module_settings || {}),
                              crypto: { ...(prev.module_settings?.crypto || {}), entry_channel_periods: parseInt(e.target.value) || 20 }
                            }
                          }))}
                        />
                      </label>
                      <label className="settings-form-group">Donchian Exit Channel (Periods)
                        <input
                          type="number"
                          min="5"
                          max="30"
                          value={config?.module_settings?.crypto?.exit_channel_periods || 10}
                          onChange={(e) => setConfig((prev) => ({
                            ...prev,
                            module_settings: {
                              ...(prev.module_settings || {}),
                              crypto: { ...(prev.module_settings?.crypto || {}), exit_channel_periods: parseInt(e.target.value) || 10 }
                            }
                          }))}
                        />
                      </label>
                      <label className="settings-form-group">ATR Trailing Stop Multiplier
                        <input
                          type="number"
                          step="0.1"
                          min="1.5"
                          max="4.0"
                          value={config?.module_settings?.crypto?.atr_stop_multiplier || 2.5}
                          onChange={(e) => setConfig((prev) => ({
                            ...prev,
                            module_settings: {
                              ...(prev.module_settings || {}),
                              crypto: { ...(prev.module_settings?.crypto || {}), atr_stop_multiplier: parseFloat(e.target.value) || 2.5 }
                            }
                          }))}
                        />
                      </label>
                    </>
                  )}

                  {activeGearModal === 'futures' && (
                    <>
                      <label className="settings-form-group">Opening Range Window (Minutes)
                        <input
                          type="number"
                          min="5"
                          max="60"
                          value={config?.module_settings?.futures?.opening_range_minutes || 15}
                          onChange={(e) => setConfig((prev) => ({
                            ...prev,
                            module_settings: {
                              ...(prev.module_settings || {}),
                              futures: { ...(prev.module_settings?.futures || {}), opening_range_minutes: parseInt(e.target.value) || 15 }
                            }
                          }))}
                        />
                      </label>
                      <label className="settings-form-group">Max Daily Loss Stop ($)
                        <input
                          type="number"
                          min="100"
                          max="1000"
                          step="25"
                          value={config?.module_settings?.futures?.max_intraday_loss || 250.0}
                          onChange={(e) => setConfig((prev) => ({
                            ...prev,
                            module_settings: {
                              ...(prev.module_settings || {}),
                              futures: { ...(prev.module_settings?.futures || {}), max_intraday_loss: parseFloat(e.target.value) || 250.0 }
                            }
                          }))}
                        />
                      </label>
                    </>
                  )}
                </div>
              </div>

              {/* Specialist AI Prompt */}
              <div style={{ marginTop: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <label style={{ fontSize: '12px', fontWeight: 600, color: isLightMode ? '#334155' : '#e2e8f0' }}>
                    🤖 Domain Specialist AI System Prompt
                  </label>
                  <button
                    type="button"
                    onClick={() => {
                      const defaultPrompt = ASSET_MODULE_DEFS[activeGearModal]?.strategy || '';
                      setConfig((prev) => ({
                        ...prev,
                        module_settings: {
                          ...(prev.module_settings || {}),
                          [activeGearModal]: {
                            ...(prev.module_settings?.[activeGearModal] || {}),
                            specialist_prompt: `You are a quantitative ${activeGearModal} specialist analyzing market microstructure and momentum.`,
                          },
                        },
                      }));
                    }}
                    style={{ background: 'none', border: 'none', color: '#38bdf8', fontSize: '11px', cursor: 'pointer', textDecoration: 'underline' }}
                  >
                    ↺ Reset to Default
                  </button>
                </div>
                <textarea
                  rows="4"
                  value={config?.module_settings?.[activeGearModal]?.specialist_prompt || ''}
                  onChange={(e) => setConfig((prev) => ({
                    ...prev,
                    module_settings: {
                      ...(prev.module_settings || {}),
                      [activeGearModal]: {
                        ...(prev.module_settings?.[activeGearModal] || {}),
                        specialist_prompt: e.target.value,
                      },
                    },
                  }))}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: 6,
                    background: isLightMode ? '#ffffff' : '#1e293b',
                    color: isLightMode ? '#0f172a' : '#ffffff',
                    border: '1px solid rgba(148,163,184,0.3)',
                    boxSizing: 'border-box',
                    fontSize: '12px',
                    lineHeight: 1.45,
                  }}
                  placeholder={`Specialist AI prompt for ${ASSET_MODULE_DEFS[activeGearModal]?.title}...`}
                />
              </div>
            </div>

            <div className="quant-modal-footer">
              <button
                type="button"
                className="btn-quant-save"
                onClick={() => {
                  handleSavePortfolioConfig();
                  setActiveGearModal(null);
                }}
              >
                Save &amp; Close
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* 3. MASTER PORTFOLIO AI AUDIT MODAL */}
      {showMasterAIModal && createPortal(
        <div className="quant-modal-overlay" role="dialog" aria-modal="true">
          <div className="quant-modal-dialog" style={{ width: 'min(980px, 96vw)' }}>
            <div className="quant-modal-header">
              <h3>
                <span>🤖</span> Master Portfolio AI Audit (Chief Investment Officer)
              </h3>
              <button
                type="button"
                className="quant-modal-close-btn"
                onClick={() => setShowMasterAIModal(false)}
                aria-label="Close modal"
              >
                ✕
              </button>
            </div>

            <div className="quant-modal-body">
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <label style={{ fontSize: '12px', fontWeight: 600, color: isLightMode ? '#334155' : '#e2e8f0' }}>
                    Chief Investment Officer (CIO) Mandate &amp; System Prompt
                  </label>
                  <button
                    type="button"
                    onClick={() =>
                      setMasterAIPromptDraft(
                        'You are the Quantitative Chief Investment Officer (CIO) and Portfolio Risk Auditor for an autonomous multi-asset trading engine. Your mandate is to evaluate the blended portfolio ($50,000 baseline) across 5 asset classes (Equities & ETFs, Options Strategies, Cryptocurrency Spot, Micro Futures, and Event Contracts). Audit portfolio progress toward the net annual target (16.5%–21.0% CAGR), detect cross-asset correlation spikes, identify whether any asset allocation has drifted beyond target risk weights, and issue strategic capital rebalancing directives.'
                      )
                    }
                    style={{ background: 'none', border: 'none', color: '#38bdf8', fontSize: '11px', cursor: 'pointer', textDecoration: 'underline' }}
                  >
                    ↺ Reset to Default Mandate
                  </button>
                </div>
                <textarea
                  rows="3"
                  value={masterAIPromptDraft}
                  onChange={(e) => setMasterAIPromptDraft(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: 6,
                    background: isLightMode ? '#ffffff' : '#1e293b',
                    color: isLightMode ? '#0f172a' : '#ffffff',
                    border: '1px solid rgba(148,163,184,0.3)',
                    boxSizing: 'border-box',
                    fontSize: '12px',
                    lineHeight: 1.45,
                  }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.82rem', color: '#94a3b8' }}>
                  Audits cross-asset correlation, Sharpe profile, risk budget, and strategic capital rebalancing.
                </span>
                <button
                  type="button"
                  className="btn-quant-ai-audit"
                  disabled={masterAIAuditLoading}
                  onClick={handleRunMasterAIAudit}
                >
                  {masterAIAuditLoading ? 'Analyzing Portfolio...' : '⚡ Run Master AI Audit Now'}
                </button>
              </div>

              {/* Audit Result Display */}
              {masterAIAuditLoading ? (
                <div style={{ padding: '40px 0', textAlign: 'center', color: '#38bdf8' }}>
                  Invoking Chief Investment Officer AI audit matrix across 5 asset modules...
                </div>
              ) : masterAIAuditResult ? (
                <div className="quant-audit-output">
                  {masterAIAuditResult.content}
                </div>
              ) : null}
            </div>

            <div className="quant-modal-footer">
              <button
                type="button"
                className="btn-quant-save"
                onClick={() => setShowMasterAIModal(false)}
              >
                Close Audit
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* 4. BANKROLL RESET MODAL */}
      {showBankrollResetModal && createPortal(
        <div className="quant-modal-overlay" role="dialog" aria-modal="true">
          <div className="quant-modal-dialog" style={{ maxWidth: '520px' }}>
            <div className="quant-modal-header">
              <h3>
                <span>🔄</span> Reset Quantitative Paper Bankroll
              </h3>
              <button
                type="button"
                className="quant-modal-close-btn"
                onClick={() => setShowBankrollResetModal(false)}
                aria-label="Close modal"
              >
                ✕
              </button>
            </div>

            <div className="quant-modal-body">
              <p style={{ fontSize: '0.9rem', lineHeight: 1.5, margin: 0, color: isLightMode ? '#334155' : '#cbd5e1' }}>
                Reset the dedicated Quantitative Strategy Engine paper trading account back to a fresh starting balance.
              </p>

              <div style={{ padding: '12px 14px', borderRadius: 8, background: 'rgba(239, 68, 68, 0.12)', border: '1px solid rgba(239, 68, 68, 0.3)' }}>
                <strong style={{ color: '#f87171', display: 'block', marginBottom: 4, fontSize: '0.85rem' }}>
                  🛡️ Strict Ledger Isolation
                </strong>
                <span style={{ fontSize: '0.8rem', color: isLightMode ? '#7f1d1d' : '#fca5a5' }}>
                  This operation resets <strong>only</strong> the isolated Quantitative Strategy Engine ledger. It will <strong>never</strong> wipe or modify manual Webull Test Mode or Binance paper balances.
                </span>
              </div>

              <label className="settings-form-group" style={{ margin: 0 }}>
                Reset Amount ($ USD)
                <input
                  type="number"
                  min="1000"
                  max="1000000"
                  step="1000"
                  value={resetBankrollAmount}
                  onChange={(e) => setResetBankrollAmount(parseFloat(e.target.value) || 50000)}
                />
              </label>
            </div>

            <div className="quant-modal-footer">
              <button
                type="button"
                style={{
                  background: 'none',
                  border: '1px solid rgba(148,163,184,0.3)',
                  color: isLightMode ? '#64748b' : '#94a3b8',
                  padding: '8px 16px',
                  borderRadius: 8,
                  cursor: 'pointer',
                }}
                onClick={() => setShowBankrollResetModal(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn-quant-reset-bankroll"
                disabled={resettingBankroll}
                onClick={handleBankrollResetConfirm}
                style={{ padding: '8px 18px', fontWeight: 700 }}
              >
                {resettingBankroll ? 'Resetting...' : 'Confirm Reset'}
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}
