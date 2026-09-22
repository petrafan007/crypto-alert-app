import React, { useEffect, useMemo } from 'react';
import '../pages/Trading.css';

const PRESETS = {
  CONSERVATIVE: {
    name: 'Conservative',
    label: '🛡️ Conservative',
    descSell: '3 rungs: +2%, +4%, +6%',
    descBuy: '3 rungs: -2%, -4%, -6%',
    rungsSell: [
      { price_offset_pct: 2.0, percentage_of_total: 33.33 },
      { price_offset_pct: 4.0, percentage_of_total: 33.33 },
      { price_offset_pct: 6.0, percentage_of_total: 33.34 }
    ],
    rungsBuy: [
      { price_offset_pct: -2.0, percentage_of_total: 33.33 },
      { price_offset_pct: -4.0, percentage_of_total: 33.33 },
      { price_offset_pct: -6.0, percentage_of_total: 33.34 }
    ]
  },
  AGGRESSIVE: {
    name: 'Aggressive',
    label: '🚀 Aggressive',
    descSell: '4 rungs: +5%, +10%, +15%, +20%',
    descBuy: '4 rungs: -5%, -10%, -15%, -20%',
    rungsSell: [
      { price_offset_pct: 5.0, percentage_of_total: 25.0 },
      { price_offset_pct: 10.0, percentage_of_total: 25.0 },
      { price_offset_pct: 15.0, percentage_of_total: 25.0 },
      { price_offset_pct: 20.0, percentage_of_total: 25.0 }
    ],
    rungsBuy: [
      { price_offset_pct: -5.0, percentage_of_total: 25.0 },
      { price_offset_pct: -10.0, percentage_of_total: 25.0 },
      { price_offset_pct: -15.0, percentage_of_total: 25.0 },
      { price_offset_pct: -20.0, percentage_of_total: 25.0 }
    ]
  },
  CUSTOM: {
    name: 'Custom',
    label: '⚙️ Custom',
    descSell: 'Configure custom rungs & sizes',
    descBuy: 'Configure custom rungs & sizes'
  }
};

export const defaultLadderState = {
  preset: 'CONSERVATIVE',
  mode: 'PERCENTAGE',
  rungs: [
    { price_offset_pct: 2.0, percentage_of_total: 33.33, target_price: '' },
    { price_offset_pct: 4.0, percentage_of_total: 33.33, target_price: '' },
    { price_offset_pct: 6.0, percentage_of_total: 33.34, target_price: '' }
  ],
  hasStopLoss: false,
  stopLossType: 'PERCENT', // 'PERCENT' or 'PRICE'
  stopLossOffsetPct: '5.0',
  stopLossTriggerPrice: '',
  stopLossAction: 'MARKET_SELL_ALL' // 'MARKET_SELL_ALL' or 'CANCEL_REMAINING'
};

const LadderOrderConfig = ({
  side = 'SELL',
  currentPrice = 0,
  totalQuantity = '',
  baseAsset = 'ASSET',
  quoteAsset = 'USD',
  ladderConfig = defaultLadderState,
  onChange
}) => {
  const isSell = side === 'SELL';
  const price = parseFloat(currentPrice) || 0;
  const totalQty = parseFloat(totalQuantity) || 0;

  // Sync preset if side changes or initial load
  const applyPreset = (presetKey) => {
    if (presetKey === 'CUSTOM') {
      onChange({
        ...ladderConfig,
        preset: 'CUSTOM'
      });
      return;
    }
    const preset = PRESETS[presetKey];
    if (!preset) return;
    const templateRungs = isSell ? preset.rungsSell : preset.rungsBuy;
    const updatedRungs = templateRungs.map(r => ({
      price_offset_pct: r.price_offset_pct,
      percentage_of_total: r.percentage_of_total,
      target_price: price > 0 ? (price * (1 + r.price_offset_pct / 100)).toFixed(price >= 1 ? 2 : 6) : ''
    }));

    onChange({
      ...ladderConfig,
      preset: presetKey,
      rungs: updatedRungs
    });
  };

  // Recompute target prices when currentPrice changes if in percentage mode
  useEffect(() => {
    if (price > 0 && ladderConfig.preset !== 'CUSTOM') {
      const preset = PRESETS[ladderConfig.preset] || PRESETS.CONSERVATIVE;
      const templateRungs = isSell ? preset.rungsSell : preset.rungsBuy;
      const updatedRungs = ladderConfig.rungs.map((r, idx) => {
        const offset = templateRungs[idx]?.price_offset_pct ?? r.price_offset_pct;
        const calcPrice = price * (1 + offset / 100);
        return {
          ...r,
          price_offset_pct: offset,
          target_price: calcPrice.toFixed(price >= 1 ? 2 : 6)
        };
      });
      onChange({
        ...ladderConfig,
        rungs: updatedRungs
      });
    }
  }, [price, side]);

  const handleRungChange = (index, field, value) => {
    const updated = [...ladderConfig.rungs];
    const rung = { ...updated[index], [field]: value };

    if (field === 'price_offset_pct' && price > 0) {
      const offset = parseFloat(value) || 0;
      rung.target_price = (price * (1 + offset / 100)).toFixed(price >= 1 ? 2 : 6);
    } else if (field === 'target_price' && price > 0) {
      const tgt = parseFloat(value) || 0;
      if (tgt > 0) {
        rung.price_offset_pct = Number((((tgt - price) / price) * 100).toFixed(2));
      }
    }

    updated[index] = rung;
    onChange({
      ...ladderConfig,
      preset: 'CUSTOM',
      rungs: updated
    });
  };

  const handleAddRung = () => {
    if (ladderConfig.rungs.length >= 10) return;
    const lastRung = ladderConfig.rungs[ladderConfig.rungs.length - 1];
    const nextOffset = lastRung ? (isSell ? lastRung.price_offset_pct + 3 : lastRung.price_offset_pct - 3) : (isSell ? 3 : -3);
    const nextPrice = price > 0 ? (price * (1 + nextOffset / 100)).toFixed(price >= 1 ? 2 : 6) : '';
    const updated = [
      ...ladderConfig.rungs,
      {
        price_offset_pct: nextOffset,
        percentage_of_total: 10,
        target_price: nextPrice
      }
    ];
    onChange({
      ...ladderConfig,
      preset: 'CUSTOM',
      rungs: updated
    });
  };

  const handleRemoveRung = (index) => {
    if (ladderConfig.rungs.length <= 2) return;
    const updated = ladderConfig.rungs.filter((_, idx) => idx !== index);
    onChange({
      ...ladderConfig,
      preset: 'CUSTOM',
      rungs: updated
    });
  };

  // Evenly distribute quantities
  const handleEvenlyDistribute = () => {
    const count = ladderConfig.rungs.length;
    if (count === 0) return;
    const pctEach = Number((100 / count).toFixed(2));
    const updated = ladderConfig.rungs.map((r, i) => ({
      ...r,
      percentage_of_total: i === count - 1 ? Number((100 - pctEach * (count - 1)).toFixed(2)) : pctEach
    }));
    onChange({
      ...ladderConfig,
      preset: 'CUSTOM',
      rungs: updated
    });
  };

  // Compute calculated tiers for visual preview
  const calculatedTiers = useMemo(() => {
    let cumulativeQty = 0;
    let cumulativeUsd = 0;

    return ladderConfig.rungs.map((r, idx) => {
      const pct = parseFloat(r.percentage_of_total) || 0;
      const rungQty = totalQty > 0 ? (totalQty * (pct / 100)) : 0;
      let targetPrice = parseFloat(r.target_price) || 0;
      if (targetPrice <= 0 && price > 0) {
        targetPrice = price * (1 + (parseFloat(r.price_offset_pct) || 0) / 100);
      }
      const estUsd = rungQty * targetPrice;
      cumulativeQty += rungQty;
      cumulativeUsd += estUsd;

      return {
        rungNumber: idx + 1,
        offsetPct: parseFloat(r.price_offset_pct) || 0,
        targetPrice,
        percentageOfTotal: pct,
        quantity: rungQty,
        estimatedUsd: estUsd,
        cumulativeQty,
        cumulativeUsd
      };
    });
  }, [ladderConfig.rungs, totalQty, price]);

  const totalPctAssigned = ladderConfig.rungs.reduce((acc, r) => acc + (parseFloat(r.percentage_of_total) || 0), 0);
  const isTotalPctValid = Math.abs(totalPctAssigned - 100) < 0.5;

  // Calculate Stop Loss Price preview
  const calculatedStopPrice = useMemo(() => {
    if (!ladderConfig.hasStopLoss) return null;
    if (ladderConfig.stopLossType === 'PRICE') {
      return parseFloat(ladderConfig.stopLossTriggerPrice) || 0;
    }
    const offset = parseFloat(ladderConfig.stopLossOffsetPct) || 0;
    if (price > 0 && offset > 0) {
      return isSell ? price * (1 - offset / 100) : price * (1 + offset / 100);
    }
    return null;
  }, [ladderConfig.hasStopLoss, ladderConfig.stopLossType, ladderConfig.stopLossOffsetPct, ladderConfig.stopLossTriggerPrice, price, isSell]);

  return (
    <div className="ladder-order-config-container" style={{ width: '100%', marginTop: '6px' }}>
      {/* PRESETS SELECTION */}
      <div style={{ marginBottom: '14px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <label className="order-field-label" style={{ marginBottom: 0 }}>
            Ladder Preset ({isSell ? 'Scale-Out' : 'Scale-In'})
          </label>
          <span style={{ fontSize: '11px', color: '#94a3b8' }}>
            {isSell ? 'Take profits incrementally as price rises' : 'Accumulate incrementally as price dips'}
          </span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
          {Object.keys(PRESETS).map((key) => {
            const p = PRESETS[key];
            const isActive = ladderConfig.preset === key;
            return (
              <button
                key={key}
                type="button"
                className={`order-type-btn ${isActive ? 'active' : ''}`}
                style={{
                  padding: '10px 8px',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '3px',
                  textAlign: 'center',
                  borderColor: isActive ? '#38bdf8' : 'rgba(255,255,255,0.12)'
                }}
                onClick={() => applyPreset(key)}
              >
                <span style={{ fontWeight: '600', fontSize: '13px' }}>{p.label}</span>
                <span style={{ fontSize: '10px', color: isActive ? '#e0f2fe' : '#94a3b8', lineHeight: '1.2' }}>
                  {isSell ? p.descSell : p.descBuy}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* RUNGS EDITOR TABLE */}
      <div style={{
        background: 'rgba(15, 23, 42, 0.5)',
        border: '1px solid rgba(255,255,255,0.1)',
        borderRadius: '8px',
        padding: '12px',
        marginBottom: '14px'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '13px', fontWeight: '700', color: '#f8fafc' }}>
              🎯 Ladder Rungs ({ladderConfig.rungs.length})
            </span>
            <span style={{
              fontSize: '11px',
              padding: '2px 6px',
              borderRadius: '4px',
              background: isTotalPctValid ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)',
              color: isTotalPctValid ? '#4ade80' : '#f87171',
              fontWeight: '600'
            }}>
              Total: {totalPctAssigned.toFixed(1)}% / 100%
            </span>
          </div>

          <div style={{ display: 'flex', gap: '6px' }}>
            <button
              type="button"
              onClick={handleEvenlyDistribute}
              style={{
                background: 'rgba(255,255,255,0.06)',
                border: '1px solid rgba(255,255,255,0.15)',
                color: '#cbd5e1',
                padding: '3px 8px',
                borderRadius: '4px',
                fontSize: '11px',
                cursor: 'pointer'
              }}
              title="Split total quantity equally among all rungs"
            >
              ⚖️ Split Evenly
            </button>
            <button
              type="button"
              onClick={handleAddRung}
              disabled={ladderConfig.rungs.length >= 10}
              style={{
                background: 'rgba(56, 189, 248, 0.15)',
                border: '1px solid rgba(56, 189, 248, 0.3)',
                color: '#38bdf8',
                padding: '3px 8px',
                borderRadius: '4px',
                fontSize: '11px',
                cursor: ladderConfig.rungs.length >= 10 ? 'not-allowed' : 'pointer'
              }}
            >
              ➕ Add Rung
            </button>
          </div>
        </div>

        {/* Rungs Header */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '40px 1.2fr 1fr 1fr 30px',
          gap: '8px',
          padding: '4px 6px',
          fontSize: '11px',
          fontWeight: '600',
          color: '#94a3b8',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
          marginBottom: '6px'
        }}>
          <span>Tier</span>
          <span>Target Price ({quoteAsset})</span>
          <span>Distance %</span>
          <span>Alloc %</span>
          <span></span>
        </div>

        {/* Rungs Rows */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '220px', overflowY: 'auto' }}>
          {ladderConfig.rungs.map((rung, index) => {
            const isNegative = rung.price_offset_pct < 0;
            return (
              <div
                key={index}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '40px 1.2fr 1fr 1fr 30px',
                  gap: '8px',
                  alignItems: 'center',
                  background: 'rgba(255,255,255,0.02)',
                  padding: '4px 6px',
                  borderRadius: '6px',
                  border: '1px solid rgba(255,255,255,0.04)'
                }}
              >
                <span style={{ fontSize: '11px', fontWeight: '700', color: '#cbd5e1' }}>
                  #{index + 1}
                </span>

                <input
                  type="number"
                  step="any"
                  className="order-styled-input"
                  style={{ padding: '6px 8px', fontSize: '12px' }}
                  value={rung.target_price || ''}
                  placeholder="Target Price"
                  onChange={(e) => handleRungChange(index, 'target_price', e.target.value)}
                />

                <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                  <input
                    type="number"
                    step="any"
                    className="order-styled-input"
                    style={{
                      padding: '6px 8px',
                      fontSize: '12px',
                      color: isNegative ? '#f87171' : '#34d399',
                      fontWeight: '600'
                    }}
                    value={rung.price_offset_pct}
                    onChange={(e) => handleRungChange(index, 'price_offset_pct', e.target.value)}
                  />
                  <span style={{ position: 'absolute', right: '8px', fontSize: '11px', color: '#94a3b8', pointerEvents: 'none' }}>%</span>
                </div>

                <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                  <input
                    type="number"
                    step="any"
                    min="1"
                    max="100"
                    className="order-styled-input"
                    style={{ padding: '6px 8px', fontSize: '12px' }}
                    value={rung.percentage_of_total}
                    onChange={(e) => handleRungChange(index, 'percentage_of_total', e.target.value)}
                  />
                  <span style={{ position: 'absolute', right: '8px', fontSize: '11px', color: '#94a3b8', pointerEvents: 'none' }}>%</span>
                </div>

                <button
                  type="button"
                  onClick={() => handleRemoveRung(index)}
                  disabled={ladderConfig.rungs.length <= 2}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: ladderConfig.rungs.length <= 2 ? '#475569' : '#f87171',
                    cursor: ladderConfig.rungs.length <= 2 ? 'not-allowed' : 'pointer',
                    fontSize: '14px',
                    padding: '2px'
                  }}
                  title="Remove rung"
                >
                  ✕
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* STEPPED VISUAL PREVIEW BAR */}
      <div style={{
        background: 'rgba(30, 41, 59, 0.7)',
        border: '1px solid rgba(56, 189, 248, 0.25)',
        borderRadius: '8px',
        padding: '12px',
        marginBottom: '14px'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <span style={{ fontSize: '12px', fontWeight: '700', color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span>📊</span> Stepped Ladder Execution Preview
          </span>
          {price > 0 && (
            <span style={{ fontSize: '11px', color: '#94a3b8' }}>
              Base: <strong style={{ color: '#fff' }}>${price.toLocaleString()}</strong>
            </span>
          )}
        </div>

        {/* Stepped Bars */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {calculatedTiers.map((tier) => {
            const isGain = tier.offsetPct >= 0;
            const progressPct = totalQty > 0 ? Math.min(100, (tier.cumulativeQty / totalQty) * 100) : tier.rungNumber * (100 / calculatedTiers.length);

            return (
              <div
                key={tier.rungNumber}
                style={{
                  background: 'rgba(15, 23, 42, 0.6)',
                  borderRadius: '6px',
                  padding: '8px 10px',
                  border: '1px solid rgba(255, 255, 255, 0.05)',
                  position: 'relative',
                  overflow: 'hidden'
                }}
              >
                {/* Background progress fill */}
                <div
                  style={{
                    position: 'absolute',
                    top: 0,
                    bottom: 0,
                    left: 0,
                    width: `${progressPct}%`,
                    background: isSell ? 'rgba(56, 189, 248, 0.08)' : 'rgba(34, 197, 94, 0.08)',
                    zIndex: 0,
                    pointerEvents: 'none'
                  }}
                />

                <div style={{ position: 'relative', zIndex: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '4px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{
                      display: 'inline-block',
                      width: '20px',
                      height: '20px',
                      borderRadius: '50%',
                      background: isSell ? 'rgba(56, 189, 248, 0.2)' : 'rgba(34, 197, 94, 0.2)',
                      color: isSell ? '#38bdf8' : '#4ade80',
                      fontSize: '11px',
                      fontWeight: '700',
                      textAlign: 'center',
                      lineHeight: '20px'
                    }}>
                      {tier.rungNumber}
                    </span>
                    <div>
                      <span style={{ fontWeight: '700', fontSize: '13px', color: '#fff' }}>
                        ${tier.targetPrice > 0 ? tier.targetPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: tier.targetPrice >= 1 ? 2 : 6 }) : '—'}
                      </span>
                      <span style={{
                        marginLeft: '6px',
                        fontSize: '11px',
                        fontWeight: '600',
                        color: isGain ? '#34d399' : '#f87171'
                      }}>
                        ({isGain ? '+' : ''}{tier.offsetPct}%)
                      </span>
                    </div>
                  </div>

                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: '12px', fontWeight: '600', color: '#e2e8f0' }}>
                      {tier.quantity > 0 ? tier.quantity.toLocaleString(undefined, { maximumFractionDigits: 6 }) : '—'} {baseAsset}
                      <span style={{ color: '#94a3b8', fontSize: '11px', marginLeft: '4px' }}>({tier.percentageOfTotal}%)</span>
                    </div>
                    <div style={{ fontSize: '10px', color: '#94a3b8' }}>
                      Tier Value: ${tier.estimatedUsd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {quoteAsset} | Cum: ${tier.cumulativeUsd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* DOWNSIDE STOP-LOSS SAFETY NET */}
      <div style={{
        background: ladderConfig.hasStopLoss ? 'rgba(239, 68, 68, 0.08)' : 'rgba(255,255,255,0.02)',
        border: `1px solid ${ladderConfig.hasStopLoss ? 'rgba(239, 68, 68, 0.3)' : 'rgba(255,255,255,0.08)'}`,
        borderRadius: '8px',
        padding: '12px',
        marginBottom: '10px'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', margin: 0 }}>
            <input
              type="checkbox"
              checked={ladderConfig.hasStopLoss}
              onChange={(e) => onChange({ ...ladderConfig, hasStopLoss: e.target.checked })}
              style={{ width: '16px', height: '16px', accentColor: '#f87171' }}
            />
            <span style={{ fontWeight: '700', fontSize: '13px', color: ladderConfig.hasStopLoss ? '#f87171' : '#cbd5e1' }}>
              🛡️ Downside Stop-Loss Safety Net
            </span>
          </label>
          <span style={{ fontSize: '11px', color: '#94a3b8' }}>
            {ladderConfig.hasStopLoss ? 'Active' : 'Optional safety hedge'}
          </span>
        </div>

        {ladderConfig.hasStopLoss && (
          <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '8px' }}>
              <div>
                <label className="order-field-label" style={{ fontSize: '11px' }}>
                  Stop Trigger Distance ({isSell ? 'Drop below' : 'Surge above'})
                </label>
                <div style={{ display: 'flex', gap: '6px' }}>
                  <div style={{ position: 'relative', flex: 1 }}>
                    <input
                      type="number"
                      step="any"
                      min="0.1"
                      className="order-styled-input"
                      value={ladderConfig.stopLossOffsetPct}
                      onChange={(e) => onChange({ ...ladderConfig, stopLossOffsetPct: e.target.value })}
                      placeholder="5.0"
                    />
                    <span style={{ position: 'absolute', right: '8px', top: '8px', fontSize: '11px', color: '#94a3b8' }}>%</span>
                  </div>
                  <div style={{ display: 'flex', gap: '3px' }}>
                    {[3, 5, 8, 10].map(p => (
                      <button
                        key={p}
                        type="button"
                        onClick={() => onChange({ ...ladderConfig, stopLossOffsetPct: String(p) })}
                        style={{
                          padding: '2px 6px',
                          borderRadius: '4px',
                          background: 'rgba(255,255,255,0.06)',
                          border: '1px solid rgba(255,255,255,0.15)',
                          color: '#cbd5e1',
                          fontSize: '11px',
                          cursor: 'pointer'
                        }}
                      >
                        {p}%
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div>
                <label className="order-field-label" style={{ fontSize: '11px' }}>
                  Stop Trigger Price ({quoteAsset})
                </label>
                <input
                  type="text"
                  readOnly
                  className="order-styled-input"
                  style={{ background: 'rgba(0,0,0,0.3)', color: '#f87171', fontWeight: '700' }}
                  value={calculatedStopPrice ? `$${calculatedStopPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: calculatedStopPrice >= 1 ? 2 : 6 })}` : '—'}
                />
              </div>
            </div>

            <div>
              <label className="order-field-label" style={{ fontSize: '11px' }}>
                Stop-Loss Action When Triggered
              </label>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  type="button"
                  className={`order-type-btn ${ladderConfig.stopLossAction === 'MARKET_SELL_ALL' ? 'active' : ''}`}
                  style={{ flex: 1, padding: '6px 8px', fontSize: '11px' }}
                  onClick={() => onChange({ ...ladderConfig, stopLossAction: 'MARKET_SELL_ALL' })}
                >
                  🚨 Market {isSell ? 'Sell' : 'Close'} Remaining Position
                </button>
                <button
                  type="button"
                  className={`order-type-btn ${ladderConfig.stopLossAction === 'CANCEL_REMAINING' ? 'active' : ''}`}
                  style={{ flex: 1, padding: '6px 8px', fontSize: '11px' }}
                  onClick={() => onChange({ ...ladderConfig, stopLossAction: 'CANCEL_REMAINING' })}
                >
                  🛑 Cancel Remaining Rungs Only
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default LadderOrderConfig;
