import React, { useEffect, useMemo } from 'react';
import '../pages/Trading.css';

export const UPSIDE_PRESETS = {
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
    descSell: 'User-defined rungs',
    descBuy: 'User-defined rungs'
  }
};

export const DOWNSIDE_PRESETS = {
  TIGHT: {
    name: 'Tight',
    label: '🛡️ Tight',
    descSell: '3 rungs: -1.5%, -3.0%, -4.5%',
    descBuy: '3 rungs: +1.5%, +3.0%, +4.5%',
    rungsSell: [
      { price_offset_pct: -1.5, percentage_of_total: 33.33 },
      { price_offset_pct: -3.0, percentage_of_total: 33.33 },
      { price_offset_pct: -4.5, percentage_of_total: 33.34 }
    ],
    rungsBuy: [
      { price_offset_pct: 1.5, percentage_of_total: 33.33 },
      { price_offset_pct: 3.0, percentage_of_total: 33.33 },
      { price_offset_pct: 4.5, percentage_of_total: 33.34 }
    ]
  },
  MODERATE: {
    name: 'Moderate',
    label: '🛑 Moderate',
    descSell: '3 rungs: -3%, -5%, -8%',
    descBuy: '3 rungs: +3%, +5%, +8%',
    rungsSell: [
      { price_offset_pct: -3.0, percentage_of_total: 30.0 },
      { price_offset_pct: -5.0, percentage_of_total: 30.0 },
      { price_offset_pct: -8.0, percentage_of_total: 40.0 }
    ],
    rungsBuy: [
      { price_offset_pct: 3.0, percentage_of_total: 30.0 },
      { price_offset_pct: 5.0, percentage_of_total: 30.0 },
      { price_offset_pct: 8.0, percentage_of_total: 40.0 }
    ]
  },
  CUSTOM: {
    name: 'Custom',
    label: '⚙️ Custom',
    descSell: 'User-defined stop rungs',
    descBuy: 'User-defined stop rungs'
  }
};

export const defaultLadderState = {
  strategyType: 'SYNTHETIC',
  // Upside Strategy
  upsideMode: 'LADDER', // 'SINGLE' | 'LADDER' | 'TRAILING'
  upsidePreset: 'CONSERVATIVE', // 'CONSERVATIVE' | 'AGGRESSIVE' | 'CUSTOM'
  upsideTargetPrice: '',
  upsideOffsetPct: '5.0',
  upsideTrailValue: '2.0',
  upsideTrailType: 'PERCENT', // 'PERCENT' | 'AMOUNT'
  upsideActivationPrice: '',
  upsideRungs: [
    { price_offset_pct: 2.0, percentage_of_total: 33.33, target_price: '' },
    { price_offset_pct: 4.0, percentage_of_total: 33.33, target_price: '' },
    { price_offset_pct: 6.0, percentage_of_total: 33.34, target_price: '' }
  ],

  // Downside Strategy
  hasDownsideProtection: true,
  downsideMode: 'LADDER', // 'SINGLE' | 'LADDER' | 'TRAILING'
  downsidePreset: 'MODERATE', // 'TIGHT' | 'MODERATE' | 'CUSTOM'
  downsideTargetPrice: '',
  downsideOffsetPct: '5.0',
  downsideTrailValue: '3.0',
  downsideTrailType: 'PERCENT', // 'PERCENT' | 'AMOUNT'
  downsideActivationPrice: '',
  downsideStopAction: 'MARKET_SELL_ALL', // 'MARKET_SELL_ALL' | 'CANCEL_REMAINING'
  downsideRungs: [
    { price_offset_pct: -3.0, percentage_of_total: 30.0, target_price: '' },
    { price_offset_pct: -5.0, percentage_of_total: 30.0, target_price: '' },
    { price_offset_pct: -8.0, percentage_of_total: 40.0, target_price: '' }
  ],

  // Legacy mappings for backwards compatibility
  preset: 'CONSERVATIVE',
  rungs: [
    { price_offset_pct: 2.0, percentage_of_total: 33.33, target_price: '' },
    { price_offset_pct: 4.0, percentage_of_total: 33.33, target_price: '' },
    { price_offset_pct: 6.0, percentage_of_total: 33.34, target_price: '' }
  ],
  hasStopLoss: true,
  stopLossType: 'PERCENT',
  stopLossOffsetPct: '5.0',
  stopLossTriggerPrice: '',
  stopLossAction: 'MARKET_SELL_ALL'
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

  // Active configurations with safe fallbacks
  const upsideMode = ladderConfig.upsideMode || 'LADDER';
  const downsideMode = ladderConfig.downsideMode || (ladderConfig.hasStopLoss ? 'SINGLE' : 'LADDER');
  const hasDownside = ladderConfig.hasDownsideProtection !== undefined ? ladderConfig.hasDownsideProtection : (ladderConfig.hasStopLoss || true);

  const upsideRungs = ladderConfig.upsideRungs || ladderConfig.rungs || defaultLadderState.upsideRungs;
  const downsideRungs = ladderConfig.downsideRungs || defaultLadderState.downsideRungs;

  // Update helper
  const updateConfig = (patch) => {
    const next = { ...ladderConfig, ...patch };
    // Synchronize legacy fields for backwards compatibility
    if (patch.upsideRungs) next.rungs = patch.upsideRungs;
    if (patch.upsidePreset) next.preset = patch.upsidePreset;
    if (patch.hasDownsideProtection !== undefined) next.hasStopLoss = patch.hasDownsideProtection;
    if (patch.downsideTargetPrice !== undefined) next.stopLossTriggerPrice = patch.downsideTargetPrice;
    if (patch.downsideOffsetPct !== undefined) next.stopLossOffsetPct = patch.downsideOffsetPct;
    if (patch.downsideStopAction !== undefined) next.stopLossAction = patch.downsideStopAction;
    onChange(next);
  };

  // Recompute target prices when price changes
  useEffect(() => {
    if (price <= 0) return;

    let modified = false;
    let newUpsideRungs = upsideRungs;
    let newDownsideRungs = downsideRungs;

    if (ladderConfig.upsidePreset !== 'CUSTOM') {
      const p = UPSIDE_PRESETS[ladderConfig.upsidePreset] || UPSIDE_PRESETS.CONSERVATIVE;
      const tpl = isSell ? p.rungsSell : p.rungsBuy;
      newUpsideRungs = upsideRungs.map((r, i) => {
        const off = tpl[i]?.price_offset_pct ?? r.price_offset_pct;
        const tgt = (price * (1 + off / 100)).toFixed(price >= 1 ? 2 : 6);
        return { ...r, price_offset_pct: off, target_price: tgt };
      });
      modified = true;
    }

    if (ladderConfig.downsidePreset !== 'CUSTOM') {
      const p = DOWNSIDE_PRESETS[ladderConfig.downsidePreset] || DOWNSIDE_PRESETS.MODERATE;
      const tpl = isSell ? p.rungsSell : p.rungsBuy;
      newDownsideRungs = downsideRungs.map((r, i) => {
        const off = tpl[i]?.price_offset_pct ?? r.price_offset_pct;
        const tgt = (price * (1 + off / 100)).toFixed(price >= 1 ? 2 : 6);
        return { ...r, price_offset_pct: off, target_price: tgt };
      });
      modified = true;
    }

    let upTarget = ladderConfig.upsideTargetPrice;
    if (!upTarget || ladderConfig.upsideMode === 'SINGLE') {
      const off = parseFloat(ladderConfig.upsideOffsetPct || 5.0);
      upTarget = (isSell ? price * (1 + off / 100) : price * (1 - off / 100)).toFixed(price >= 1 ? 2 : 6);
      modified = true;
    }

    let downTarget = ladderConfig.downsideTargetPrice;
    if (!downTarget || ladderConfig.downsideMode === 'SINGLE') {
      const off = parseFloat(ladderConfig.downsideOffsetPct || 5.0);
      downTarget = (isSell ? price * (1 - off / 100) : price * (1 + off / 100)).toFixed(price >= 1 ? 2 : 6);
      modified = true;
    }

    if (modified) {
      updateConfig({
        upsideRungs: newUpsideRungs,
        downsideRungs: newDownsideRungs,
        upsideTargetPrice: upTarget,
        downsideTargetPrice: downTarget
      });
    }
  }, [price, side]);

  // Apply Upside Preset
  const applyUpsidePreset = (key) => {
    if (key === 'CUSTOM') {
      updateConfig({ upsidePreset: 'CUSTOM' });
      return;
    }
    const preset = UPSIDE_PRESETS[key];
    if (!preset) return;
    const tpl = isSell ? preset.rungsSell : preset.rungsBuy;
    const updated = tpl.map(r => ({
      price_offset_pct: r.price_offset_pct,
      percentage_of_total: r.percentage_of_total,
      target_price: price > 0 ? (price * (1 + r.price_offset_pct / 100)).toFixed(price >= 1 ? 2 : 6) : ''
    }));
    updateConfig({
      upsidePreset: key,
      upsideRungs: updated
    });
  };

  // Apply Downside Preset
  const applyDownsidePreset = (key) => {
    if (key === 'CUSTOM') {
      updateConfig({ downsidePreset: 'CUSTOM' });
      return;
    }
    const preset = DOWNSIDE_PRESETS[key];
    if (!preset) return;
    const tpl = isSell ? preset.rungsSell : preset.rungsBuy;
    const updated = tpl.map(r => ({
      price_offset_pct: r.price_offset_pct,
      percentage_of_total: r.percentage_of_total,
      target_price: price > 0 ? (price * (1 + r.price_offset_pct / 100)).toFixed(price >= 1 ? 2 : 6) : ''
    }));
    updateConfig({
      downsidePreset: key,
      downsideRungs: updated
    });
  };

  // Handle Upside Rung Changes
  const handleUpsideRungChange = (index, field, value) => {
    const updated = [...upsideRungs];
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
    updateConfig({ upsidePreset: 'CUSTOM', upsideRungs: updated });
  };

  const handleAddUpsideRung = () => {
    if (upsideRungs.length >= 10) return;
    const last = upsideRungs[upsideRungs.length - 1];
    const nextOffset = last ? (isSell ? last.price_offset_pct + 2.5 : last.price_offset_pct - 2.5) : (isSell ? 2.5 : -2.5);
    const nextPrice = price > 0 ? (price * (1 + nextOffset / 100)).toFixed(price >= 1 ? 2 : 6) : '';
    const updated = [...upsideRungs, { price_offset_pct: nextOffset, percentage_of_total: 10, target_price: nextPrice }];
    updateConfig({ upsidePreset: 'CUSTOM', upsideRungs: updated });
  };

  const handleRemoveUpsideRung = (index) => {
    if (upsideRungs.length <= 1) return;
    updateConfig({ upsidePreset: 'CUSTOM', upsideRungs: upsideRungs.filter((_, i) => i !== index) });
  };

  const handleEvenlyDistributeUpside = () => {
    const count = upsideRungs.length;
    if (count === 0) return;
    const pctEach = Number((100 / count).toFixed(2));
    const updated = upsideRungs.map((r, i) => ({
      ...r,
      percentage_of_total: i === count - 1 ? Number((100 - pctEach * (count - 1)).toFixed(2)) : pctEach
    }));
    updateConfig({ upsidePreset: 'CUSTOM', upsideRungs: updated });
  };

  // Handle Downside Rung Changes
  const handleDownsideRungChange = (index, field, value) => {
    const updated = [...downsideRungs];
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
    updateConfig({ downsidePreset: 'CUSTOM', downsideRungs: updated });
  };

  const handleAddDownsideRung = () => {
    if (downsideRungs.length >= 10) return;
    const last = downsideRungs[downsideRungs.length - 1];
    const nextOffset = last ? (isSell ? last.price_offset_pct - 2.5 : last.price_offset_pct + 2.5) : (isSell ? -2.5 : 2.5);
    const nextPrice = price > 0 ? (price * (1 + nextOffset / 100)).toFixed(price >= 1 ? 2 : 6) : '';
    const updated = [...downsideRungs, { price_offset_pct: nextOffset, percentage_of_total: 10, target_price: nextPrice }];
    updateConfig({ downsidePreset: 'CUSTOM', downsideRungs: updated });
  };

  const handleRemoveDownsideRung = (index) => {
    if (downsideRungs.length <= 1) return;
    updateConfig({ downsidePreset: 'CUSTOM', downsideRungs: downsideRungs.filter((_, i) => i !== index) });
  };

  const handleEvenlyDistributeDownside = () => {
    const count = downsideRungs.length;
    if (count === 0) return;
    const pctEach = Number((100 / count).toFixed(2));
    const updated = downsideRungs.map((r, i) => ({
      ...r,
      percentage_of_total: i === count - 1 ? Number((100 - pctEach * (count - 1)).toFixed(2)) : pctEach
    }));
    updateConfig({ downsidePreset: 'CUSTOM', downsideRungs: updated });
  };

  // Stepped preview calculations for Upside
  const calculatedUpsideTiers = useMemo(() => {
    let cumulativeQty = 0;
    let cumulativeUsd = 0;
    return upsideRungs.map((r, idx) => {
      const pct = parseFloat(r.percentage_of_total) || 0;
      const rungQty = totalQty > 0 ? (totalQty * (pct / 100)) : 0;
      let tgt = parseFloat(r.target_price) || 0;
      if (tgt <= 0 && price > 0) {
        tgt = price * (1 + (parseFloat(r.price_offset_pct) || 0) / 100);
      }
      const estUsd = rungQty * tgt;
      cumulativeQty += rungQty;
      cumulativeUsd += estUsd;
      return {
        rungNumber: idx + 1,
        offsetPct: parseFloat(r.price_offset_pct) || 0,
        targetPrice: tgt,
        percentageOfTotal: pct,
        quantity: rungQty,
        estimatedUsd: estUsd,
        cumulativeQty,
        cumulativeUsd
      };
    });
  }, [upsideRungs, totalQty, price]);

  // Stepped preview calculations for Downside
  const calculatedDownsideTiers = useMemo(() => {
    let cumulativeQty = 0;
    let cumulativeUsd = 0;
    return downsideRungs.map((r, idx) => {
      const pct = parseFloat(r.percentage_of_total) || 0;
      const rungQty = totalQty > 0 ? (totalQty * (pct / 100)) : 0;
      let tgt = parseFloat(r.target_price) || 0;
      if (tgt <= 0 && price > 0) {
        tgt = price * (1 + (parseFloat(r.price_offset_pct) || 0) / 100);
      }
      const estUsd = rungQty * tgt;
      cumulativeQty += rungQty;
      cumulativeUsd += estUsd;
      return {
        rungNumber: idx + 1,
        offsetPct: parseFloat(r.price_offset_pct) || 0,
        targetPrice: tgt,
        percentageOfTotal: pct,
        quantity: rungQty,
        estimatedUsd: estUsd,
        cumulativeQty,
        cumulativeUsd
      };
    });
  }, [downsideRungs, totalQty, price]);

  return (
    <div className="ladder-order-config-container" style={{ width: '100%', marginTop: '6px' }}>
      <div className="ladder-strategy-split-container">
        {/* ============================================================== */}
        {/* 🟢 COLUMN 1: UPSIDE STRATEGY (TAKE PROFIT)                     */}
        {/* ============================================================== */}
        <div style={{
          background: 'rgba(16, 185, 129, 0.04)',
          border: '1px solid rgba(16, 185, 129, 0.25)',
          borderRadius: '10px',
          padding: '14px',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px'
        }}>
          {/* Header & Tagline */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <label className="order-field-label" style={{ margin: 0, color: '#34d399', fontWeight: '700', letterSpacing: '0.05em' }}>
              <span>🟢 UPSIDE STRATEGY (TAKE PROFIT)</span>
            </label>
            <span style={{ fontSize: '11px', color: '#94a3b8' }}>
              {isSell ? 'Exit into strength' : 'Dip entry'}
            </span>
          </div>

          {/* Mode Selector Buttons */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '6px' }}>
            {[
              { id: 'SINGLE', label: 'Mode A', title: 'Single Target (100% Exit)' },
              { id: 'LADDER', label: 'Mode B', title: 'Multi-Rung Ladder' },
              { id: 'TRAILING', label: 'Mode C', title: 'Trailing Stop' }
            ].map(m => (
              <button
                key={m.id}
                type="button"
                onClick={() => updateConfig({ upsideMode: m.id })}
                className={`order-type-btn ${upsideMode === m.id ? 'active' : ''}`}
                style={{
                  padding: '8px 4px',
                  fontSize: '11px',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '2px',
                  borderColor: upsideMode === m.id ? '#34d399' : undefined
                }}
                title={m.title}
              >
                <strong style={{ color: upsideMode === m.id ? '#34d399' : '#e2e8f0' }}>{m.label}</strong>
                <span style={{ fontSize: '9.5px', color: '#94a3b8', whiteSpace: 'nowrap' }}>{m.title.split(' ')[0]} {m.title.split(' ')[1]}</span>
              </button>
            ))}
          </div>

          {/* Mode Title & Market Price */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '4px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
            <span style={{ fontWeight: '600', fontSize: '12px', color: '#34d399', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span>📈</span> {upsideMode === 'SINGLE' ? 'Mode A (Single Target 100%)' : upsideMode === 'TRAILING' ? 'Mode C (Trailing Take-Profit)' : 'Mode B (Multi-Rung Ladder)'}
            </span>
            {price > 0 && (
              <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                Market Price: <strong style={{ color: '#fff' }}>${price.toLocaleString()}</strong>
              </span>
            )}
          </div>

          {/* MODE A: Single Target */}
          {upsideMode === 'SINGLE' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label className="order-field-label">Target Exit Price ({quoteAsset})</label>
                <input
                  type="number"
                  step="any"
                  className="order-styled-input"
                  value={ladderConfig.upsideTargetPrice || ''}
                  placeholder="Target Price"
                  onChange={(e) => {
                    const val = e.target.value;
                    const pFloat = parseFloat(val) || 0;
                    const off = price > 0 && pFloat > 0 ? (((pFloat - price) / price) * 100).toFixed(2) : ladderConfig.upsideOffsetPct;
                    updateConfig({ upsideTargetPrice: val, upsideOffsetPct: off });
                  }}
                />
                <div style={{ display: 'flex', gap: '6px', marginTop: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '11px', color: '#94a3b8' }}>Quick +%:</span>
                  {[2, 5, 10, 15, 20].map(pct => (
                    <button
                      key={pct}
                      type="button"
                      onClick={() => {
                        const tgt = price > 0 ? (price * (1 + pct / 100)).toFixed(price >= 1 ? 2 : 6) : '';
                        updateConfig({ upsideOffsetPct: String(pct), upsideTargetPrice: tgt });
                      }}
                      style={{
                        padding: '2px 7px',
                        borderRadius: '4px',
                        background: 'rgba(255,255,255,0.06)',
                        border: '1px solid rgba(255,255,255,0.15)',
                        color: '#34d399',
                        fontSize: '11px',
                        cursor: 'pointer'
                      }}
                    >
                      +{pct}%
                    </button>
                  ))}
                </div>
              </div>

              <div style={{
                background: 'rgba(15, 23, 42, 0.6)',
                borderRadius: '8px',
                padding: '12px',
                border: '1px solid rgba(255, 255, 255, 0.05)',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'center'
              }}>
                <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '4px' }}>Single Exit Execution Summary</div>
                <div style={{ fontSize: '13px', fontWeight: '700', color: '#34d399' }}>
                  100% Position ({totalQty > 0 ? totalQty.toLocaleString() : '—'} {baseAsset})
                </div>
                <div style={{ fontSize: '11px', color: '#cbd5e1', marginTop: '4px' }}>
                  Est. Proceeds: <strong style={{ color: '#fff' }}>${(totalQty * (parseFloat(ladderConfig.upsideTargetPrice) || price)).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
                </div>
              </div>
            </div>
          )}

          {/* MODE C: Trailing Take-Profit */}
          {upsideMode === 'TRAILING' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '8px' }}>
                  <div>
                    <label className="order-field-label">Trail Distance Offset</label>
                    <div style={{ display: 'flex', gap: '4px' }}>
                      <input
                        type="number"
                        step="any"
                        min="0.1"
                        className="order-styled-input"
                        value={ladderConfig.upsideTrailValue || '2.0'}
                        onChange={(e) => updateConfig({ upsideTrailValue: e.target.value })}
                        placeholder="2.0"
                      />
                      <button
                        type="button"
                        onClick={() => updateConfig({ upsideTrailType: ladderConfig.upsideTrailType === 'AMOUNT' ? 'PERCENT' : 'AMOUNT' })}
                        className="order-type-btn active"
                        style={{ padding: '0 8px', fontSize: '11px' }}
                      >
                        {ladderConfig.upsideTrailType === 'AMOUNT' ? '$' : '%'}
                      </button>
                    </div>
                  </div>

                  <div>
                    <label className="order-field-label">Activation Hurdle (Opt.)</label>
                    <input
                      type="number"
                      step="any"
                      className="order-styled-input"
                      value={ladderConfig.upsideActivationPrice || ''}
                      onChange={(e) => updateConfig({ upsideActivationPrice: e.target.value })}
                      placeholder="Optional Price"
                    />
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '6px', marginTop: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '11px', color: '#94a3b8' }}>Presets:</span>
                  {[1.5, 2.0, 3.0, 5.0].map(p => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => updateConfig({ upsideTrailValue: String(p), upsideTrailType: 'PERCENT' })}
                      style={{
                        padding: '2px 7px',
                        borderRadius: '4px',
                        background: 'rgba(255,255,255,0.06)',
                        border: '1px solid rgba(255,255,255,0.15)',
                        color: '#34d399',
                        fontSize: '11px',
                        cursor: 'pointer'
                      }}
                    >
                      {p}%
                    </button>
                  ))}
                </div>
              </div>

              <div style={{
                background: 'rgba(15, 23, 42, 0.6)',
                borderRadius: '8px',
                padding: '12px',
                border: '1px solid rgba(255, 255, 255, 0.05)',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'center'
              }}>
                <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '4px' }}>Trailing Take-Profit Engine</div>
                <div style={{ fontSize: '12px', color: '#e2e8f0', lineHeight: 1.4 }}>
                  Ratchets the peak high watermark upwards as price climbs. Once price pulls back by <strong style={{ color: '#34d399' }}>{ladderConfig.upsideTrailValue || '2.0'}{ladderConfig.upsideTrailType === 'AMOUNT' ? '$' : '%'}</strong> from its highest peak, an automated market sell triggers.
                </div>
              </div>
            </div>
          )}

          {/* MODE B: Multi-Rung Ladder */}
          {upsideMode === 'LADDER' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {/* Presets Bar */}
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                {Object.keys(UPSIDE_PRESETS).map(key => (
                  <button
                    key={key}
                    type="button"
                    className={`order-type-btn ${ladderConfig.upsidePreset === key ? 'active' : ''}`}
                    style={{ padding: '6px 12px', fontSize: '11px' }}
                    onClick={() => applyUpsidePreset(key)}
                  >
                    {UPSIDE_PRESETS[key].label}
                  </button>
                ))}
              </div>

              {/* Rungs Table */}
              <div style={{
                background: 'rgba(15, 23, 42, 0.6)',
                borderRadius: '8px',
                padding: '10px 12px',
                border: '1px solid rgba(255, 255, 255, 0.05)'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <span style={{ fontSize: '12px', fontWeight: '700', color: '#cbd5e1' }}>
                    📋 Profit Rungs ({upsideRungs.length})
                  </span>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <button
                      type="button"
                      onClick={handleEvenlyDistributeUpside}
                      style={{
                        padding: '2px 8px',
                        borderRadius: '4px',
                        background: 'rgba(255,255,255,0.06)',
                        border: '1px solid rgba(255,255,255,0.15)',
                        color: '#cbd5e1',
                        fontSize: '11px',
                        cursor: 'pointer'
                      }}
                    >
                      ⚖️ Split Evenly
                    </button>
                    <button
                      type="button"
                      onClick={handleAddUpsideRung}
                      disabled={upsideRungs.length >= 10}
                      style={{
                        padding: '2px 8px',
                        borderRadius: '4px',
                        background: 'rgba(16, 185, 129, 0.2)',
                        border: '1px solid rgba(16, 185, 129, 0.4)',
                        color: '#34d399',
                        fontSize: '11px',
                        cursor: 'pointer'
                      }}
                    >
                      + Add Rung
                    </button>
                  </div>
                </div>

                {/* Table Header */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: '28px 1.3fr 1fr 1fr 24px',
                  gap: '6px',
                  padding: '4px 0',
                  fontSize: '10px',
                  fontWeight: '700',
                  color: '#94a3b8',
                  borderBottom: '1px solid rgba(255,255,255,0.08)'
                }}>
                  <span>Tier</span>
                  <span>Target ({quoteAsset})</span>
                  <span>Dist %</span>
                  <span>Alloc %</span>
                  <span></span>
                </div>

                {/* Table Rows */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '6px' }}>
                  {upsideRungs.map((rung, index) => (
                    <div
                      key={index}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '28px 1.3fr 1fr 1fr 24px',
                        gap: '6px',
                        alignItems: 'center'
                      }}
                    >
                      <span style={{ fontSize: '11px', fontWeight: '700', color: '#94a3b8', textAlign: 'center' }}>
                        #{index + 1}
                      </span>
                      <input
                        type="number"
                        step="any"
                        className="order-styled-input"
                        style={{ padding: '4px 6px', fontSize: '11px' }}
                        value={rung.target_price || ''}
                        placeholder="Target"
                        onChange={(e) => handleUpsideRungChange(index, 'target_price', e.target.value)}
                      />
                      <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                        <input
                          type="number"
                          step="any"
                          className="order-styled-input"
                          style={{ padding: '4px 6px', fontSize: '11px', color: '#34d399', fontWeight: '600' }}
                          value={rung.price_offset_pct}
                          onChange={(e) => handleUpsideRungChange(index, 'price_offset_pct', e.target.value)}
                        />
                        <span style={{ position: 'absolute', right: '6px', fontSize: '10px', color: '#94a3b8', pointerEvents: 'none' }}>%</span>
                      </div>
                      <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                        <input
                          type="number"
                          step="any"
                          min="1"
                          max="100"
                          className="order-styled-input"
                          style={{ padding: '4px 6px', fontSize: '11px' }}
                          value={rung.percentage_of_total}
                          onChange={(e) => handleUpsideRungChange(index, 'percentage_of_total', e.target.value)}
                        />
                        <span style={{ position: 'absolute', right: '6px', fontSize: '10px', color: '#94a3b8', pointerEvents: 'none' }}>%</span>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleRemoveUpsideRung(index)}
                        disabled={upsideRungs.length <= 1}
                        style={{
                          background: 'transparent',
                          border: 'none',
                          color: upsideRungs.length <= 1 ? '#475569' : '#f87171',
                          cursor: upsideRungs.length <= 1 ? 'not-allowed' : 'pointer',
                          fontSize: '12px'
                        }}
                        title="Remove rung"
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              </div>

              {/* Stepped Execution Preview Bar */}
              <div style={{
                background: 'rgba(15, 23, 42, 0.6)',
                borderRadius: '8px',
                padding: '10px 12px',
                border: '1px solid rgba(56, 189, 248, 0.25)'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <span style={{ fontSize: '12px', fontWeight: '700', color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span>📊</span> Stepped Execution Preview
                  </span>
                  <span style={{ fontSize: '10.5px', color: '#94a3b8' }}>
                    Alloc: <strong style={{ color: Math.abs(upsideRungs.reduce((a, b) => a + (parseFloat(b.percentage_of_total) || 0), 0) - 100) < 0.5 ? '#34d399' : '#f87171' }}>
                      {upsideRungs.reduce((a, b) => a + (parseFloat(b.percentage_of_total) || 0), 0).toFixed(1)}% / 100%
                    </strong>
                  </span>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {calculatedUpsideTiers.map(tier => {
                    const prog = totalQty > 0 ? Math.min(100, (tier.cumulativeQty / totalQty) * 100) : (tier.rungNumber / calculatedUpsideTiers.length) * 100;
                    return (
                      <div
                        key={tier.rungNumber}
                        style={{
                          background: 'rgba(30, 41, 59, 0.6)',
                          borderRadius: '6px',
                          padding: '6px 8px',
                          border: '1px solid rgba(255, 255, 255, 0.05)',
                          position: 'relative',
                          overflow: 'hidden'
                        }}
                      >
                        <div
                          style={{
                            position: 'absolute',
                            left: 0,
                            top: 0,
                            bottom: 0,
                            width: `${prog}%`,
                            background: 'linear-gradient(90deg, rgba(16, 185, 129, 0.15) 0%, rgba(16, 185, 129, 0.3) 100%)',
                            borderRight: '2px solid #34d399',
                            pointerEvents: 'none'
                          }}
                        />
                        <div style={{ position: 'relative', zIndex: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <div>
                            <span style={{ fontSize: '11px', fontWeight: '700', color: '#38bdf8', marginRight: '6px' }}>
                              #{tier.rungNumber}
                            </span>
                            <span style={{ fontSize: '11.5px', fontWeight: '700', color: '#fff' }}>
                              ${tier.targetPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </span>
                            <span style={{ fontSize: '10.5px', color: '#34d399', marginLeft: '6px', fontWeight: '600' }}>
                              (+{tier.offsetPct}%)
                            </span>
                          </div>
                          <div style={{ textAlign: 'right' }}>
                            <div style={{ fontSize: '11px', fontWeight: '600', color: '#e2e8f0' }}>
                              {tier.quantity > 0 ? tier.quantity.toLocaleString(undefined, { maximumFractionDigits: 4 }) : '—'} {baseAsset} ({tier.percentageOfTotal}%)
                            </div>
                            <div style={{ fontSize: '9.5px', color: '#94a3b8' }}>
                              Val: ${tier.estimatedUsd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} | Cum: ${tier.cumulativeUsd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ============================================================== */}
        {/* 🔴 COLUMN 2: DOWNSIDE STRATEGY (STOP LOSS)                     */}
        {/* ============================================================== */}
        <div style={{
          background: 'rgba(239, 68, 68, 0.04)',
          border: '1px solid rgba(239, 68, 68, 0.25)',
          borderRadius: '10px',
          padding: '14px',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px'
        }}>
          {/* Header & Status (MATCHING TYPOGRAPHY TO UPSIDE) */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <label
              className="order-field-label"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                cursor: 'pointer',
                margin: 0,
                color: hasDownside ? '#f87171' : '#cbd5e1',
                fontWeight: '700',
                letterSpacing: '0.05em'
              }}
            >
              <input
                type="checkbox"
                checked={hasDownside}
                onChange={(e) => updateConfig({ hasDownsideProtection: e.target.checked })}
                style={{ width: '15px', height: '15px', accentColor: '#f87171', cursor: 'pointer' }}
              />
              <span>🔴 DOWNSIDE STRATEGY (STOP LOSS)</span>
            </label>
            <span style={{ fontSize: '11px', fontWeight: '600', color: hasDownside ? '#f87171' : '#64748b' }}>
              {hasDownside ? 'Active' : 'Disabled (Off)'}
            </span>
          </div>

          {/* Mode Selector Buttons */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: '6px',
            opacity: hasDownside ? 1 : 0.38,
            pointerEvents: hasDownside ? 'auto' : 'none'
          }}>
            {[
              { id: 'SINGLE', label: 'Mode A', title: 'Single Stop (100% Exit)' },
              { id: 'LADDER', label: 'Mode B', title: 'Staged Stop Ladder' },
              { id: 'TRAILING', label: 'Mode C', title: 'Trailing Stop' }
            ].map(m => (
              <button
                key={m.id}
                type="button"
                onClick={() => updateConfig({ downsideMode: m.id })}
                className={`order-type-btn ${downsideMode === m.id ? 'active' : ''}`}
                style={{
                  padding: '8px 4px',
                  fontSize: '11px',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '2px',
                  borderColor: downsideMode === m.id ? '#f87171' : undefined
                }}
                title={m.title}
              >
                <strong style={{ color: downsideMode === m.id ? '#f87171' : '#e2e8f0' }}>{m.label}</strong>
                <span style={{ fontSize: '9.5px', color: '#94a3b8', whiteSpace: 'nowrap' }}>{m.title.split(' ')[0]} {m.title.split(' ')[1]}</span>
              </button>
            ))}
          </div>

          {/* Downside Mode Content */}
          {hasDownside ? (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '4px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                <span style={{ fontWeight: '600', fontSize: '12px', color: '#f87171', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span>🛡️</span> {downsideMode === 'SINGLE' ? 'Mode A (Single Stop Floor)' : downsideMode === 'TRAILING' ? 'Mode C (Trailing Stop Loss)' : 'Mode B (Staged Stop Ladder)'}
                </span>
                <span style={{ fontSize: '11px', color: '#fca5a5' }}>
                  Protects position on drop
                </span>
              </div>

              {/* MODE A: Single Stop Floor */}
              {downsideMode === 'SINGLE' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div>
                    <label className="order-field-label">Stop-Loss Trigger Price ({quoteAsset})</label>
                    <input
                      type="number"
                      step="any"
                      className="order-styled-input"
                      style={{ color: '#f87171', fontWeight: '700' }}
                      value={ladderConfig.downsideTargetPrice || ''}
                      placeholder="Stop Price"
                      onChange={(e) => {
                        const val = e.target.value;
                        const pFloat = parseFloat(val) || 0;
                        const off = price > 0 && pFloat > 0 ? (((price - pFloat) / price) * 100).toFixed(2) : ladderConfig.downsideOffsetPct;
                        updateConfig({ downsideTargetPrice: val, downsideOffsetPct: off });
                      }}
                    />
                    <div style={{ display: 'flex', gap: '6px', marginTop: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '11px', color: '#94a3b8' }}>Quick -%:</span>
                      {[2, 3, 5, 8, 10].map(pct => (
                        <button
                          key={pct}
                          type="button"
                          onClick={() => {
                            const tgt = price > 0 ? (price * (1 - pct / 100)).toFixed(price >= 1 ? 2 : 6) : '';
                            updateConfig({ downsideOffsetPct: String(pct), downsideTargetPrice: tgt });
                          }}
                          style={{
                            padding: '2px 7px',
                            borderRadius: '4px',
                            background: 'rgba(255,255,255,0.06)',
                            border: '1px solid rgba(255,255,255,0.15)',
                            color: '#f87171',
                            fontSize: '11px',
                            cursor: 'pointer'
                          }}
                        >
                          -{pct}%
                        </button>
                      ))}
                    </div>
                  </div>

                  <div style={{
                    background: 'rgba(15, 23, 42, 0.6)',
                    borderRadius: '8px',
                    padding: '12px',
                    border: '1px solid rgba(255, 255, 255, 0.05)',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center'
                  }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '4px' }}>Stop-Loss Action When Triggered</div>
                    <div style={{ display: 'flex', gap: '6px' }}>
                      <button
                        type="button"
                        className={`order-type-btn ${ladderConfig.downsideStopAction === 'MARKET_SELL_ALL' ? 'active' : ''}`}
                        style={{ flex: 1, padding: '6px 8px', fontSize: '11px' }}
                        onClick={() => updateConfig({ downsideStopAction: 'MARKET_SELL_ALL' })}
                      >
                        🚨 Market Liquidate
                      </button>
                      <button
                        type="button"
                        className={`order-type-btn ${ladderConfig.downsideStopAction === 'CANCEL_REMAINING' ? 'active' : ''}`}
                        style={{ flex: 1, padding: '6px 8px', fontSize: '11px' }}
                        onClick={() => updateConfig({ downsideStopAction: 'CANCEL_REMAINING' })}
                      >
                        🛑 Cancel Open Only
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* MODE C: Trailing Stop Loss */}
              {downsideMode === 'TRAILING' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '8px' }}>
                      <div>
                        <label className="order-field-label">Trailing Stop Distance</label>
                        <div style={{ display: 'flex', gap: '4px' }}>
                          <input
                            type="number"
                            step="any"
                            min="0.1"
                            className="order-styled-input"
                            value={ladderConfig.downsideTrailValue || '3.0'}
                            onChange={(e) => updateConfig({ downsideTrailValue: e.target.value })}
                            placeholder="3.0"
                          />
                          <button
                            type="button"
                            onClick={() => updateConfig({ downsideTrailType: ladderConfig.downsideTrailType === 'AMOUNT' ? 'PERCENT' : 'AMOUNT' })}
                            className="order-type-btn active"
                            style={{ padding: '0 8px', fontSize: '11px' }}
                          >
                            {ladderConfig.downsideTrailType === 'AMOUNT' ? '$' : '%'}
                          </button>
                        </div>
                      </div>

                      <div>
                        <label className="order-field-label">Activation Price (Opt.)</label>
                        <input
                          type="number"
                          step="any"
                          className="order-styled-input"
                          value={ladderConfig.downsideActivationPrice || ''}
                          onChange={(e) => updateConfig({ downsideActivationPrice: e.target.value })}
                          placeholder="Optional Hurdle"
                        />
                      </div>
                    </div>

                    <div style={{ display: 'flex', gap: '6px', marginTop: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '11px', color: '#94a3b8' }}>Presets:</span>
                      {[2.0, 3.0, 5.0, 8.0].map(p => (
                        <button
                          key={p}
                          type="button"
                          onClick={() => updateConfig({ downsideTrailValue: String(p), downsideTrailType: 'PERCENT' })}
                          style={{
                            padding: '2px 7px',
                            borderRadius: '4px',
                            background: 'rgba(255,255,255,0.06)',
                            border: '1px solid rgba(255,255,255,0.15)',
                            color: '#f87171',
                            fontSize: '11px',
                            cursor: 'pointer'
                          }}
                        >
                          {p}%
                        </button>
                      ))}
                    </div>
                  </div>

                  <div style={{
                    background: 'rgba(15, 23, 42, 0.6)',
                    borderRadius: '8px',
                    padding: '12px',
                    border: '1px solid rgba(255, 255, 255, 0.05)',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center'
                  }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '4px' }}>Trailing Stop Loss Engine</div>
                    <div style={{ fontSize: '12px', color: '#e2e8f0', lineHeight: 1.4 }}>
                      As the asset gains value, the stop-loss price ratchets upward dynamically, staying <strong style={{ color: '#f87171' }}>{ladderConfig.downsideTrailValue || '3.0'}{ladderConfig.downsideTrailType === 'AMOUNT' ? '$' : '%'}</strong> behind market highs to protect accrued profits.
                    </div>
                  </div>
                </div>
              )}

              {/* MODE B: Staged Stop Ladder */}
              {downsideMode === 'LADDER' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {/* Presets Bar */}
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    {Object.keys(DOWNSIDE_PRESETS).map(key => (
                      <button
                        key={key}
                        type="button"
                        className={`order-type-btn ${ladderConfig.downsidePreset === key ? 'active' : ''}`}
                        style={{ padding: '6px 12px', fontSize: '11px', borderColor: ladderConfig.downsidePreset === key ? '#f87171' : undefined }}
                        onClick={() => applyDownsidePreset(key)}
                      >
                        {DOWNSIDE_PRESETS[key].label}
                      </button>
                    ))}
                  </div>

                  {/* Stop Rungs Table */}
                  <div style={{
                    background: 'rgba(15, 23, 42, 0.6)',
                    borderRadius: '8px',
                    padding: '10px 12px',
                    border: '1px solid rgba(255, 255, 255, 0.05)'
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                      <span style={{ fontSize: '12px', fontWeight: '700', color: '#cbd5e1' }}>
                        📋 Stop Rungs ({downsideRungs.length})
                      </span>
                      <div style={{ display: 'flex', gap: '6px' }}>
                        <button
                          type="button"
                          onClick={handleEvenlyDistributeDownside}
                          style={{
                            padding: '2px 8px',
                            borderRadius: '4px',
                            background: 'rgba(255,255,255,0.06)',
                            border: '1px solid rgba(255,255,255,0.15)',
                            color: '#cbd5e1',
                            fontSize: '11px',
                            cursor: 'pointer'
                          }}
                        >
                          ⚖️ Split Evenly
                        </button>
                        <button
                          type="button"
                          onClick={handleAddDownsideRung}
                          disabled={downsideRungs.length >= 10}
                          style={{
                            padding: '2px 8px',
                            borderRadius: '4px',
                            background: 'rgba(239, 68, 68, 0.2)',
                            border: '1px solid rgba(239, 68, 68, 0.4)',
                            color: '#f87171',
                            fontSize: '11px',
                            cursor: 'pointer'
                          }}
                        >
                          + Add Stop Rung
                        </button>
                      </div>
                    </div>

                    {/* Table Header */}
                    <div style={{
                      display: 'grid',
                      gridTemplateColumns: '28px 1.3fr 1fr 1fr 24px',
                      gap: '6px',
                      padding: '4px 0',
                      fontSize: '10px',
                      fontWeight: '700',
                      color: '#94a3b8',
                      borderBottom: '1px solid rgba(255,255,255,0.08)'
                    }}>
                      <span>Tier</span>
                      <span>Stop ({quoteAsset})</span>
                      <span>Drop %</span>
                      <span>Alloc %</span>
                      <span></span>
                    </div>

                    {/* Table Rows */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '6px' }}>
                      {downsideRungs.map((rung, index) => (
                        <div
                          key={index}
                          style={{
                            display: 'grid',
                            gridTemplateColumns: '28px 1.3fr 1fr 1fr 24px',
                            gap: '6px',
                            alignItems: 'center'
                          }}
                        >
                          <span style={{ fontSize: '11px', fontWeight: '700', color: '#94a3b8', textAlign: 'center' }}>
                            #{index + 1}
                          </span>
                          <input
                            type="number"
                            step="any"
                            className="order-styled-input"
                            style={{ padding: '4px 6px', fontSize: '11px', color: '#f87171', fontWeight: '600' }}
                            value={rung.target_price || ''}
                            placeholder="Stop Px"
                            onChange={(e) => handleDownsideRungChange(index, 'target_price', e.target.value)}
                          />
                          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                            <input
                              type="number"
                              step="any"
                              className="order-styled-input"
                              style={{ padding: '4px 6px', fontSize: '11px', color: '#f87171', fontWeight: '600' }}
                              value={rung.price_offset_pct}
                              onChange={(e) => handleDownsideRungChange(index, 'price_offset_pct', e.target.value)}
                            />
                            <span style={{ position: 'absolute', right: '6px', fontSize: '10px', color: '#94a3b8', pointerEvents: 'none' }}>%</span>
                          </div>
                          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                            <input
                              type="number"
                              step="any"
                              min="1"
                              max="100"
                              className="order-styled-input"
                              style={{ padding: '4px 6px', fontSize: '11px' }}
                              value={rung.percentage_of_total}
                              onChange={(e) => handleDownsideRungChange(index, 'percentage_of_total', e.target.value)}
                            />
                            <span style={{ position: 'absolute', right: '6px', fontSize: '10px', color: '#94a3b8', pointerEvents: 'none' }}>%</span>
                          </div>
                          <button
                            type="button"
                            onClick={() => handleRemoveDownsideRung(index)}
                            disabled={downsideRungs.length <= 1}
                            style={{
                              background: 'transparent',
                              border: 'none',
                              color: downsideRungs.length <= 1 ? '#475569' : '#f87171',
                              cursor: downsideRungs.length <= 1 ? 'not-allowed' : 'pointer',
                              fontSize: '12px'
                            }}
                            title="Remove rung"
                          >
                            ✕
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Downside Stop Preview */}
                  <div style={{
                    background: 'rgba(15, 23, 42, 0.6)',
                    borderRadius: '8px',
                    padding: '10px 12px',
                    border: '1px solid rgba(239, 68, 68, 0.3)'
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                      <span style={{ fontSize: '12px', fontWeight: '700', color: '#f87171', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span>📉</span> Downside Stop Preview
                      </span>
                      <span style={{ fontSize: '10.5px', color: '#94a3b8' }}>
                        Alloc: <strong style={{ color: Math.abs(downsideRungs.reduce((a, b) => a + (parseFloat(b.percentage_of_total) || 0), 0) - 100) < 0.5 ? '#34d399' : '#f87171' }}>
                          {downsideRungs.reduce((a, b) => a + (parseFloat(b.percentage_of_total) || 0), 0).toFixed(1)}% / 100%
                        </strong>
                      </span>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      {calculatedDownsideTiers.map(tier => {
                        const prog = totalQty > 0 ? Math.min(100, (tier.cumulativeQty / totalQty) * 100) : (tier.rungNumber / calculatedDownsideTiers.length) * 100;
                        return (
                          <div
                            key={tier.rungNumber}
                            style={{
                              background: 'rgba(30, 41, 59, 0.6)',
                              borderRadius: '6px',
                              padding: '6px 8px',
                              border: '1px solid rgba(255, 255, 255, 0.05)',
                              position: 'relative',
                              overflow: 'hidden'
                            }}
                          >
                            <div
                              style={{
                                position: 'absolute',
                                left: 0,
                                top: 0,
                                bottom: 0,
                                width: `${prog}%`,
                                background: 'linear-gradient(90deg, rgba(239, 68, 68, 0.15) 0%, rgba(239, 68, 68, 0.3) 100%)',
                                borderRight: '2px solid #f87171',
                                pointerEvents: 'none'
                              }}
                            />
                            <div style={{ position: 'relative', zIndex: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <div>
                                <span style={{ fontSize: '11px', fontWeight: '700', color: '#f87171', marginRight: '6px' }}>
                                  #{tier.rungNumber}
                                </span>
                                <span style={{ fontSize: '11.5px', fontWeight: '700', color: '#fff' }}>
                                  ${tier.targetPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                </span>
                                <span style={{ fontSize: '10.5px', color: '#f87171', marginLeft: '6px', fontWeight: '600' }}>
                                  ({tier.offsetPct}%)
                                </span>
                              </div>
                              <div style={{ textAlign: 'right' }}>
                                <div style={{ fontSize: '11px', fontWeight: '600', color: '#e2e8f0' }}>
                                  {tier.quantity > 0 ? tier.quantity.toLocaleString(undefined, { maximumFractionDigits: 4 }) : '—'} {baseAsset} ({tier.percentageOfTotal}%)
                                </div>
                                <div style={{ fontSize: '9.5px', color: '#94a3b8' }}>
                                  Cut: ${tier.estimatedUsd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} | Cum: ${tier.cumulativeUsd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div style={{
              background: 'rgba(15, 23, 42, 0.45)',
              border: '1px dashed rgba(239, 68, 68, 0.25)',
              borderRadius: '8px',
              padding: '24px 16px',
              textAlign: 'center',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              color: '#94a3b8',
              minHeight: '200px'
            }}>
              <span style={{ fontSize: '24px' }}>🛡️</span>
              <strong style={{ color: '#cbd5e1', fontSize: '13px' }}>Capital Protection Inactive</strong>
              <span style={{ fontSize: '11.5px', maxWidth: '300px', lineHeight: 1.4 }}>
                Enable Stop-Loss to guard your position with a single stop floor, multi-staged stop ladder, or dynamic trailing stop.
              </span>
              <button
                type="button"
                onClick={() => updateConfig({ hasDownsideProtection: true })}
                style={{
                  marginTop: '8px',
                  padding: '6px 14px',
                  borderRadius: '6px',
                  background: 'rgba(239, 68, 68, 0.15)',
                  border: '1px solid rgba(239, 68, 68, 0.4)',
                  color: '#f87171',
                  fontSize: '11.5px',
                  fontWeight: '600',
                  cursor: 'pointer'
                }}
              >
                🛡️ Enable Downside Strategy
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default LadderOrderConfig;
