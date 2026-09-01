import React, { useState, useEffect, useMemo } from 'react';
import { formatOrderSide, formatOrderType } from '../utils/orderDisplay';
import './PercentPriceModal.css';

export const formatCalculatedPrice = (val, decimals = null) => {
  if (!Number.isFinite(val) || val <= 0) return '';
  if (decimals !== null) return val.toFixed(decimals);
  if (val >= 100) return val.toFixed(2);
  if (val >= 1) {
    const d2 = val.toFixed(2);
    if (Math.abs(Number(d2) - val) < 1e-5) return d2;
    const d4 = val.toFixed(4);
    return d4.replace(/(\.\d\d[1-9]*)0+$/, '$1');
  }
  if (val >= 0.01) {
    const d2 = val.toFixed(2);
    if (Math.abs(Number(d2) - val) < 1e-5) return d2;
    const d4 = val.toFixed(4);
    return d4.replace(/(\.\d\d[1-9]*)0+$/, '$1');
  }
  const d8 = val.toFixed(8);
  return d8.replace(/(\.\d\d[1-9]*)0+$/, '$1');
};

export default function PercentPriceModal({
  isOpen,
  onClose,
  onApply,
  orderType = 'STOP_LOSS_LIMIT',
  side = 'SELL',
  targetField = 'stopPrice',
  symbol = '',
  baseAsset = '',
  quoteAsset = 'USDT',
  currentPrice = 0,
  avgEntry = null
}) {
  const hasAvgEntry = avgEntry !== null && avgEntry !== undefined && Number(avgEntry) > 0;
  const numAvgEntry = hasAvgEntry ? Number(avgEntry) : null;
  const numCurrentPrice = Number(currentPrice) > 0 ? Number(currentPrice) : 0;

  // Active anchor tab: 'avg_entry' or 'current_price'
  const [anchorTab, setAnchorTab] = useState(() => {
    if (side === 'SELL' && hasAvgEntry) return 'avg_entry';
    return 'current_price';
  });

  // Main percentage input (whole or decimal number)
  const [percentValue, setPercentValue] = useState('10');

  // OCO specific controls
  const [isSymmetricOco, setIsSymmetricOco] = useState(true);
  const [ocoProfitPercent, setOcoProfitPercent] = useState('10');
  const [ocoStopPercent, setOcoStopPercent] = useState('10');

  // Reset tab when modal opens or symbol/side changes
  useEffect(() => {
    if (!isOpen) return;
    if (side === 'SELL' && hasAvgEntry) {
      setAnchorTab('avg_entry');
    } else {
      setAnchorTab('current_price');
    }
    setPercentValue('10');
    setOcoProfitPercent('10');
    setOcoStopPercent('10');
  }, [isOpen, symbol, side, hasAvgEntry]);

  // Handle ESC key
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // Active reference baseline price
  const anchorPrice = useMemo(() => {
    if (anchorTab === 'avg_entry' && numAvgEntry) {
      return numAvgEntry;
    }
    return numCurrentPrice;
  }, [anchorTab, numAvgEntry, numCurrentPrice]);

  // Unrealized P&L % from Average Entry
  const pnlPercent = useMemo(() => {
    if (!numAvgEntry || !numCurrentPrice) return null;
    return ((numCurrentPrice - numAvgEntry) / numAvgEntry) * 100;
  }, [numAvgEntry, numCurrentPrice]);

  // Dynamic calculations based on Order Type, Side, and Anchor
  const calculatedResult = useMemo(() => {
    const P = Math.abs(parseFloat(percentValue) || 0);
    const P_profit = isSymmetricOco ? P : Math.abs(parseFloat(ocoProfitPercent) || 0);
    const P_stop = isSymmetricOco ? P : Math.abs(parseFloat(ocoStopPercent) || 0);

    let price = '';
    let stopPrice = '';
    let stopLimitPrice = '';
    let warning = null;
    let isValid = true;

    if (!anchorPrice || anchorPrice <= 0) {
      return {
        price: '',
        stopPrice: '',
        stopLimitPrice: '',
        warning: 'Reference price is not available yet. Please enter prices manually.',
        isValid: false
      };
    }

    if (P <= 0 && orderType !== 'OCO') {
      return {
        price: '',
        stopPrice: '',
        stopLimitPrice: '',
        warning: 'Please enter a percentage greater than 0.',
        isValid: false
      };
    }

    // 1. STOP LOSS LIMIT
    if (orderType === 'STOP_LOSS_LIMIT') {
      if (side === 'SELL') {
        const diff = anchorPrice * (P / 100);
        const stop = anchorPrice - diff;
        const limit = stop - (diff * (P / 100)); // fraction of a fraction

        stopPrice = formatCalculatedPrice(stop);
        price = formatCalculatedPrice(limit);

        // Guardrail: In spot selling, Stop Price must be <= Current Market Price
        if (numCurrentPrice > 0 && stop > numCurrentPrice) {
          isValid = false;
          const currentDropPct = numAvgEntry
            ? Math.abs(((numCurrentPrice - numAvgEntry) / numAvgEntry) * 100).toFixed(1)
            : '0';
          warning = `Warning: This coin is currently at $${formatCalculatedPrice(numCurrentPrice)} (already down -${currentDropPct}% from average entry). A stop-loss price ($${stopPrice}) cannot be placed above the current market price. Switch to the "Current Price" tab or increase your percentage.`;
        }
      } else {
        // BUY STOP_LOSS_LIMIT (Breakout Buy)
        const diff = anchorPrice * (P / 100);
        const stop = anchorPrice + diff;
        const limit = stop + (diff * (P / 100));

        stopPrice = formatCalculatedPrice(stop);
        price = formatCalculatedPrice(limit);

        // Breakout trigger must be >= Current Market Price
        if (numCurrentPrice > 0 && stop < numCurrentPrice) {
          isValid = false;
          warning = `Warning: Buy breakout stop price ($${stopPrice}) must be greater than current market price ($${formatCalculatedPrice(numCurrentPrice)}).`;
        }
      }
    }

    // 2. TAKE PROFIT LIMIT
    else if (orderType === 'TAKE_PROFIT_LIMIT') {
      if (side === 'SELL') {
        const diff = anchorPrice * (P / 100);
        const stop = anchorPrice + diff;
        const limit = stop + (diff * (P / 100)); // buffer is P% of the profit delta (diff), added above the stop trigger

        stopPrice = formatCalculatedPrice(stop);
        price = formatCalculatedPrice(limit);

        // Trigger must be >= Current Price
        if (numCurrentPrice > 0 && stop < numCurrentPrice) {
          isValid = false;
          warning = `Warning: Take-profit trigger price ($${stopPrice}) must be greater than current market price ($${formatCalculatedPrice(numCurrentPrice)}).`;
        }
      } else {
        // BUY TAKE_PROFIT_LIMIT (Pullback / Support Buy)
        const diff = anchorPrice * (P / 100);
        const stop = anchorPrice - diff;
        const limit = stop + (diff * (P / 100)); // buffer is P% of the pullback delta (diff), added to the stop trigger

        stopPrice = formatCalculatedPrice(stop);
        price = formatCalculatedPrice(limit);

        if (numCurrentPrice > 0 && stop > numCurrentPrice) {
          isValid = false;
          warning = `Warning: Buy pullback trigger price ($${stopPrice}) must be less than current market price ($${formatCalculatedPrice(numCurrentPrice)}).`;
        }
      }
    }

    // 3. LIMIT & LIMIT MAKER
    else if (orderType === 'LIMIT' || orderType === 'LIMIT_MAKER') {
      if (side === 'SELL') {
        const target = anchorPrice * (1 + P / 100);
        price = formatCalculatedPrice(target);
      } else {
        // BUY Limit (Dip Buy)
        const target = anchorPrice * (1 - P / 100);
        price = formatCalculatedPrice(target);

        if (numCurrentPrice > 0 && target > numCurrentPrice) {
          isValid = false;
          warning = `Warning: Buy limit price ($${price}) is above current market price ($${formatCalculatedPrice(numCurrentPrice)}). Standard dip buys must be below current market price.`;
        }
      }
    }

    // 4. STOP LOSS & TAKE PROFIT (Market Stops)
    else if (orderType === 'STOP_LOSS') {
      const diff = anchorPrice * (P / 100);
      const stop = side === 'SELL' ? anchorPrice - diff : anchorPrice + diff;
      stopPrice = formatCalculatedPrice(stop);

      if (side === 'SELL' && numCurrentPrice > 0 && stop > numCurrentPrice) {
        isValid = false;
        warning = `Warning: Stop price ($${stopPrice}) cannot be set above the current market price ($${formatCalculatedPrice(numCurrentPrice)}).`;
      }
    } else if (orderType === 'TAKE_PROFIT') {
      const diff = anchorPrice * (P / 100);
      const stop = side === 'SELL' ? anchorPrice + diff : anchorPrice - diff;
      stopPrice = formatCalculatedPrice(stop);
    }

    // 5. OCO (One-Cancels-the-Other)
    else if (orderType === 'OCO') {
      if (side === 'SELL') {
        // Limit Price = Take Profit (+P_profit%)
        const targetProfit = anchorPrice * (1 + P_profit / 100);
        // Stop Price = Stop Loss (-P_stop%)
        const stopDiff = anchorPrice * (P_stop / 100);
        const stop = anchorPrice - stopDiff;
        const stopLimit = stop - (stopDiff * (P_stop / 100)); // buffer

        price = formatCalculatedPrice(targetProfit);
        stopPrice = formatCalculatedPrice(stop);
        stopLimitPrice = formatCalculatedPrice(stopLimit);

        // Exchange rule for SELL OCO: Limit Price > Current Price > Stop Price
        if (numCurrentPrice > 0) {
          if (stop >= numCurrentPrice) {
            isValid = false;
            const currentDropPct = numAvgEntry
              ? Math.abs(((numCurrentPrice - numAvgEntry) / numAvgEntry) * 100).toFixed(1)
              : '0';
            warning = `Warning: Stop loss trigger ($${stopPrice}) is above or equal to current price ($${formatCalculatedPrice(numCurrentPrice)}). Coin is down -${currentDropPct}%. Switch to "Current Price" tab or increase stop percentage.`;
          } else if (targetProfit <= numCurrentPrice) {
            isValid = false;
            warning = `Warning: Take-profit limit ($${price}) must be higher than current market price ($${formatCalculatedPrice(numCurrentPrice)}).`;
          }
        }
      } else {
        // BUY OCO: Limit Price (Dip Buy) < Market Price < Stop Price (Breakout)
        const dipTarget = anchorPrice * (1 - P_profit / 100);
        const breakoutDiff = anchorPrice * (P_stop / 100);
        const breakoutStop = anchorPrice + breakoutDiff;
        const breakoutLimit = breakoutStop + (breakoutDiff * (P_stop / 100));

        price = formatCalculatedPrice(dipTarget);
        stopPrice = formatCalculatedPrice(breakoutStop);
        stopLimitPrice = formatCalculatedPrice(breakoutLimit);

        if (numCurrentPrice > 0) {
          if (dipTarget >= numCurrentPrice) {
            isValid = false;
            warning = `Warning: Dip buy limit ($${price}) must be lower than current market price ($${formatCalculatedPrice(numCurrentPrice)}).`;
          } else if (breakoutStop <= numCurrentPrice) {
            isValid = false;
            warning = `Warning: Breakout stop ($${stopPrice}) must be higher than current market price ($${formatCalculatedPrice(numCurrentPrice)}).`;
          }
        }
      }
    }

    return { price, stopPrice, stopLimitPrice, warning, isValid };
  }, [
    anchorPrice,
    percentValue,
    isSymmetricOco,
    ocoProfitPercent,
    ocoStopPercent,
    orderType,
    side,
    numCurrentPrice,
    numAvgEntry
  ]);

  if (!isOpen) return null;

  const handlePresetClick = (val) => {
    setPercentValue(String(val));
    if (isSymmetricOco) {
      setOcoProfitPercent(String(val));
      setOcoStopPercent(String(val));
    }
  };

  const handleApplyClick = () => {
    if (!calculatedResult.isValid) return;
    onApply({
      price: calculatedResult.price,
      stopPrice: calculatedResult.stopPrice,
      stopLimitPrice: calculatedResult.stopLimitPrice
    });
    onClose();
  };

  const PRESETS = [5, 10, 15, 20, 25];

  return (
    <div className="percent-modal-overlay" onClick={onClose}>
      <div
        className="percent-modal-dialog"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {/* Modal Header */}
        <div className="percent-modal-header">
          <div className="percent-modal-title-area">
            <h3 className="percent-modal-title">
              <span className="percent-modal-icon">%</span>
              Price Calculator
            </h3>
            <span className={`percent-modal-badge ${side.toLowerCase()}`}>
              {formatOrderSide(side)} · {formatOrderType(orderType)}
            </span>
          </div>
          <button
            type="button"
            className="percent-modal-close"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Tab Selection */}
        <div className="percent-modal-tabs">
          <button
            type="button"
            className={`percent-tab-btn ${anchorTab === 'avg_entry' ? 'active' : ''}`}
            onClick={() => setAnchorTab('avg_entry')}
            disabled={!hasAvgEntry}
            title={!hasAvgEntry ? 'No Average Entry recorded for this asset' : 'Calculate relative to Average Entry'}
          >
            📊 Average Entry
            {hasAvgEntry && <span className="tab-pill">${formatCalculatedPrice(numAvgEntry)}</span>}
          </button>
          <button
            type="button"
            className={`percent-tab-btn ${anchorTab === 'current_price' ? 'active' : ''}`}
            onClick={() => setAnchorTab('current_price')}
          >
            ⚡ Current Price
            {numCurrentPrice > 0 && <span className="tab-pill">${formatCalculatedPrice(numCurrentPrice)}</span>}
          </button>
        </div>

        {/* Reference Price Card */}
        <div className="percent-reference-card">
          <div className="reference-item">
            <span className="reference-label">Pair</span>
            <span className="reference-val">{baseAsset}/{quoteAsset}</span>
          </div>
          <div className="reference-item">
            <span className="reference-label">Current Market Price</span>
            <span className="reference-val highlight">
              ${formatCalculatedPrice(numCurrentPrice)}
            </span>
          </div>
          {hasAvgEntry ? (
            <div className="reference-item">
              <span className="reference-label">Average Entry</span>
              <span className="reference-val">
                ${formatCalculatedPrice(numAvgEntry)}
                {pnlPercent !== null && (
                  <span className={`pnl-sub-badge ${pnlPercent >= 0 ? 'pos' : 'neg'}`}>
                    ({pnlPercent >= 0 ? '+' : ''}{pnlPercent.toFixed(1)}%)
                  </span>
                )}
              </span>
            </div>
          ) : (
            anchorTab === 'avg_entry' && (
              <div className="reference-item no-entry">
                <span className="reference-label">Average Entry</span>
                <span className="reference-val muted">None recorded</span>
              </div>
            )
          )}
        </div>

        {/* Modal Body: Input & Presets */}
        <div className="percent-modal-body">
          {orderType === 'OCO' && (
            <div className="oco-symmetric-toggle">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={isSymmetricOco}
                  onChange={(e) => setIsSymmetricOco(e.target.checked)}
                />
                <span>Apply symmetric swing (±X% in both directions)</span>
              </label>
            </div>
          )}

          {orderType === 'OCO' && !isSymmetricOco ? (
            <div className="oco-asymmetric-inputs">
              <div className="percent-input-wrapper">
                <label className="percent-label">
                  Take Profit Target (% above {anchorTab === 'avg_entry' ? 'Avg Entry' : 'Market'})
                </label>
                <div className="input-group-styled">
                  <input
                    type="number"
                    step="any"
                    value={ocoProfitPercent}
                    onChange={(e) => setOcoProfitPercent(e.target.value)}
                    placeholder="10"
                    className="percent-number-input"
                  />
                  <span className="input-suffix">%</span>
                </div>
              </div>
              <div className="percent-input-wrapper">
                <label className="percent-label">
                  Stop Loss Drop (% below {anchorTab === 'avg_entry' ? 'Avg Entry' : 'Market'})
                </label>
                <div className="input-group-styled">
                  <input
                    type="number"
                    step="any"
                    value={ocoStopPercent}
                    onChange={(e) => setOcoStopPercent(e.target.value)}
                    placeholder="10"
                    className="percent-number-input"
                  />
                  <span className="input-suffix">%</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="percent-input-wrapper">
              <label className="percent-label">
                {orderType === 'STOP_LOSS_LIMIT' && (side === 'SELL' ? 'Stop Loss Drop (%)' : 'Breakout Surge (%)')}
                {orderType === 'TAKE_PROFIT_LIMIT' && (side === 'SELL' ? 'Take Profit Target (%)' : 'Pullback Buy (%)')}
                {(orderType === 'LIMIT' || orderType === 'LIMIT_MAKER') && (side === 'SELL' ? 'Profit Target (%)' : 'Dip Buy Discount (%)')}
                {orderType === 'OCO' && 'Symmetric Swing (± %)'}
                {!['STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT', 'LIMIT', 'LIMIT_MAKER', 'OCO'].includes(orderType) && 'Percentage (%)'}
              </label>
              <div className="input-group-styled">
                <input
                  type="number"
                  step="any"
                  value={percentValue}
                  onChange={(e) => setPercentValue(e.target.value)}
                  placeholder="10"
                  className="percent-number-input"
                  autoFocus
                />
                <span className="input-suffix">%</span>
              </div>
            </div>
          )}

          {/* Quick Preset Buttons */}
          <div className="percent-presets-row">
            <span className="presets-label">Quick:</span>
            {PRESETS.map((p) => (
              <button
                key={p}
                type="button"
                className={`preset-btn ${percentValue === String(p) ? 'selected' : ''}`}
                onClick={() => handlePresetClick(p)}
              >
                {p}%
              </button>
            ))}
          </div>

          {/* Preview Output Badges */}
          <div className="percent-preview-container">
            <div className="preview-heading">Calculated Prices:</div>
            <div className="preview-grid">
              {calculatedResult.stopPrice && (
                <div className="preview-card">
                  <span className="preview-card-label">Stop Price</span>
                  <span className="preview-card-val">${calculatedResult.stopPrice}</span>
                  <span className="preview-card-sub">Trigger</span>
                </div>
              )}
              {calculatedResult.price && (
                <div className="preview-card highlight">
                  <span className="preview-card-label">Limit Price</span>
                  <span className="preview-card-val">${calculatedResult.price}</span>
                  <span className="preview-card-sub">
                    {orderType === 'STOP_LOSS_LIMIT' || orderType === 'TAKE_PROFIT_LIMIT' ? `Execution (with ${percentValue}% buffer)` : 'Execution'}
                  </span>
                </div>
              )}
              {calculatedResult.stopLimitPrice && (
                <div className="preview-card">
                  <span className="preview-card-label">Stop Limit Price</span>
                  <span className="preview-card-val">${calculatedResult.stopLimitPrice}</span>
                  <span className="preview-card-sub">Stop Execution Cap</span>
                </div>
              )}
            </div>
          </div>

          {/* Warning / Validation Alert */}
          {calculatedResult.warning && (
            <div className="percent-warning-banner">
              <span className="warning-icon">⚠️</span>
              <div className="warning-text">{calculatedResult.warning}</div>
            </div>
          )}
        </div>

        {/* Modal Actions */}
        <div className="percent-modal-footer">
          <button
            type="button"
            className="percent-btn-cancel"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="button"
            className="percent-btn-apply"
            onClick={handleApplyClick}
            disabled={!calculatedResult.isValid}
          >
            Apply to Order
          </button>
        </div>
      </div>
    </div>
  );
}
