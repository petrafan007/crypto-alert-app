import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import TotpCodeInput from './TotpCodeInput';
import './WebullScheduledOrderModal.css';

const DEFAULT_BUFFER_PCT = 3.00;

export default function WebullScheduledOrderModal({
  isOpen,
  onClose,
  orderData,
  require2fa = false,
  onSuccess,
}) {
  const [orderMode, setOrderMode] = useState('QTY'); // 'QTY' or 'AMOUNT'
  const [quantity, setQuantity] = useState('');
  const [totalCashAmount, setTotalCashAmount] = useState('');
  const [bufferPercent, setBufferPercent] = useState('3.00');
  const [maxPrice, setMaxPrice] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [nextOpenText, setNextOpenText] = useState('Next trading day at 9:30 AM ET');
  const [loading, setLoading] = useState(false);
  const [loadingSchedule, setLoadingSchedule] = useState(false);
  const [error, setError] = useState('');
  const totpInputRef = useRef(null);

  useEffect(() => {
    if (!isOpen || !orderData) {
      setError('');
      setTotpCode('');
      setLoading(false);
      return;
    }

    const refPx = parseFloat(orderData.reference_price || 0);
    const initialCash = parseFloat(orderData.total_cash_amount || 0);
    const initialQty = parseFloat(orderData.quantity || 0);

    // Prefer cash amount mode if order was triggered via total cash / quote value and no raw quantity
    const isCashMode = orderData.entrust_type === 'AMOUNT' || (initialCash > 0 && initialQty <= 0);
    setOrderMode(isCashMode ? 'AMOUNT' : 'QTY');

    if (initialCash > 0) {
      setTotalCashAmount(initialCash.toFixed(2));
    } else if (initialQty > 0 && refPx > 0) {
      setTotalCashAmount((initialQty * refPx).toFixed(2));
    } else {
      setTotalCashAmount('');
    }

    if (initialQty > 0) {
      setQuantity(String(initialQty));
    } else if (initialCash > 0 && refPx > 0) {
      setQuantity((initialCash / refPx).toFixed(5));
    } else {
      setQuantity('');
    }

    // Default +3.00% price ceiling buffer
    setBufferPercent(DEFAULT_BUFFER_PCT.toFixed(2));
    if (refPx > 0) {
      setMaxPrice((refPx * (1 + DEFAULT_BUFFER_PCT / 100)).toFixed(2));
    } else {
      setMaxPrice('');
    }

    setLoadingSchedule(true);
    axios
      .get('/api/webull/scheduled-orders/next-open', { withCredentials: true })
      .then((res) => {
        if (res.data?.success && res.data?.target_execution_time_et) {
          setNextOpenText(res.data.target_execution_time_et);
        }
      })
      .catch(() => {
        setNextOpenText('Next trading day at 9:30 AM ET');
      })
      .finally(() => {
        setLoadingSchedule(false);
      });

    if (require2fa) {
      setTimeout(() => {
        totpInputRef.current?.focus();
        totpInputRef.current?.select?.();
      }, 100);
    }
  }, [isOpen, orderData, require2fa]);

  if (!isOpen || !orderData) return null;

  const refPriceNum = parseFloat(orderData.reference_price || 0);
  const qtyNum = parseFloat(quantity || 0);
  const cashNum = parseFloat(totalCashAmount || 0);

  // Buffer % change handler: calculates new price ceiling
  const handleBufferSelect = (pct) => {
    const formatted = Number(pct).toFixed(2);
    setBufferPercent(formatted);
    if (refPriceNum > 0) {
      setMaxPrice((refPriceNum * (1 + pct / 100)).toFixed(2));
    }
  };

  const handleBufferInputChange = (val) => {
    let clean = val.replace(/[^0-9.]/g, '');
    const parts = clean.split('.');
    if (parts.length > 2) {
      clean = parts[0] + '.' + parts.slice(1).join('');
    }
    if (parts.length === 2 && parts[1].length > 2) {
      clean = parts[0] + '.' + parts[1].slice(0, 2);
    }
    setBufferPercent(clean);
    const pct = parseFloat(clean);
    if (!isNaN(pct) && refPriceNum > 0) {
      setMaxPrice((refPriceNum * (1 + pct / 100)).toFixed(2));
    }
  };

  const handleBufferBlur = () => {
    const num = parseFloat(bufferPercent);
    if (isNaN(num) || num < 0) {
      setBufferPercent(DEFAULT_BUFFER_PCT.toFixed(2));
      if (refPriceNum > 0) {
        setMaxPrice((refPriceNum * (1 + DEFAULT_BUFFER_PCT / 100)).toFixed(2));
      }
    } else {
      setBufferPercent(num.toFixed(2));
    }
  };

  // Ceiling price change handler: updates buffer percentage in sync
  const handleMaxPriceChange = (val) => {
    let clean = val.replace(/[^0-9.]/g, '');
    const parts = clean.split('.');
    if (parts.length > 2) clean = parts[0] + '.' + parts.slice(1).join('');
    if (parts.length === 2 && parts[1].length > 2) clean = parts[0] + '.' + parts[1].slice(0, 2);
    setMaxPrice(clean);
    const px = parseFloat(clean);
    if (!isNaN(px) && refPriceNum > 0 && px > 0) {
      const computedPct = ((px - refPriceNum) / refPriceNum) * 100;
      setBufferPercent(computedPct >= 0 ? computedPct.toFixed(2) : '0.00');
    }
  };

  const handlePasteTotp = async () => {
    try {
      if (navigator.clipboard?.readText) {
        const text = await navigator.clipboard.readText();
        const clean = text.replace(/\D/g, '').slice(0, 6);
        if (clean) {
          setTotpCode(clean);
          return;
        }
      }
    } catch {
      // clipboard access not permitted
    }
    totpInputRef.current?.focus?.();
    totpInputRef.current?.select?.();
  };

  const handleModeChange = (mode) => {
    setOrderMode(mode);
    setError('');
    if (mode === 'AMOUNT' && (!cashNum || cashNum <= 0) && qtyNum > 0 && refPriceNum > 0) {
      setTotalCashAmount((qtyNum * refPriceNum).toFixed(2));
    } else if (mode === 'QTY' && (!qtyNum || qtyNum <= 0) && cashNum > 0 && refPriceNum > 0) {
      setQuantity((cashNum / refPriceNum).toFixed(5));
    }
  };

  const handleCashChange = (val) => {
    const clean = val.replace(/[^0-9.]/g, '');
    setTotalCashAmount(clean);
    const num = parseFloat(clean);
    if (num > 0 && refPriceNum > 0) {
      setQuantity((num / refPriceNum).toFixed(5));
    }
  };

  const handleQuantityChange = (val) => {
    const clean = val.replace(/[^0-9.]/g, '');
    setQuantity(clean);
    const num = parseFloat(clean);
    if (num > 0 && refPriceNum > 0) {
      setTotalCashAmount((num * refPriceNum).toFixed(2));
    }
  };

  const isCashAmount = orderMode === 'AMOUNT';
  const displayQty = isCashAmount
    ? `$${cashNum.toFixed(2)} USD`
    : `${qtyNum > 0 ? qtyNum : (orderData.quantity || '0')} shares`;

  const estimatedValue = isCashAmount
    ? cashNum
    : (qtyNum > 0 && refPriceNum > 0 ? qtyNum * refPriceNum : 0);

  const ceilingNum = parseFloat(maxPrice || 0);
  const maxEstimatedValue = isCashAmount
    ? cashNum
    : (qtyNum > 0 && ceilingNum > 0 ? qtyNum * ceilingNum : 0);

  const handleSubmit = async (e) => {
    e?.preventDefault();
    setError('');

    if (require2fa && (!totpCode || totpCode.trim().length !== 6)) {
      setError('Please enter your 6-digit two-factor authentication code.');
      return;
    }

    if (isCashAmount) {
      if (isNaN(cashNum) || cashNum < 5.0) {
        setError('Total order value must be at least $5.00 for dollar-based fractional orders.');
        return;
      }
    } else {
      if (isNaN(qtyNum) || qtyNum <= 0) {
        setError('Please enter a valid share quantity greater than zero.');
        return;
      }
    }

    const ceilingValue = maxPrice.trim() ? parseFloat(maxPrice) : null;
    if (ceilingValue !== null && (isNaN(ceilingValue) || ceilingValue <= 0)) {
      setError('Please enter a valid price ceiling greater than $0.00.');
      return;
    }

    setLoading(true);
    try {
      const payload = {
        account_id: orderData.account_id,
        account_name: orderData.account_name,
        symbol: orderData.symbol,
        instrument_type: 'EQUITY',
        side: 'BUY',
        entrust_type: isCashAmount ? 'AMOUNT' : 'QTY',
        quantity: isCashAmount ? null : qtyNum,
        total_cash_amount: isCashAmount ? cashNum : null,
        reference_price: refPriceNum > 0 ? refPriceNum : null,
        max_price: ceilingValue,
        two_factor_code: require2fa ? totpCode.trim() : undefined,
      };

      const res = await axios.post('/api/webull/scheduled-orders', payload, { withCredentials: true });
      if (res.data?.success) {
        if (onSuccess) {
          onSuccess(res.data.order || res.data);
        }
        onClose();
      } else {
        setError(res.data?.message || 'Failed to schedule order.');
      }
    } catch (err) {
      const msg = err.response?.data?.message || err.message || 'An error occurred while scheduling your order.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="scheduled-order-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="scheduled-order-modal" onClick={(e) => e.stopPropagation()}>
        <div className="scheduled-order-header">
          <div className="scheduled-order-title-wrap">
            <div className="scheduled-order-icon" aria-hidden="true">⏰</div>
            <div>
              <h3>Schedule Market Open Buy</h3>
              <p className="scheduled-order-subtitle">Automated 9:30 AM ET CORE execution</p>
            </div>
          </div>
          <button
            type="button"
            className="scheduled-order-close"
            onClick={onClose}
            aria-label="Close"
          >
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit} className="scheduled-order-form" autoComplete="on">
          <div className="scheduled-order-body">
            <div className="scheduled-order-prompt-box">
              <span className="scheduled-order-prompt-icon" aria-hidden="true">💡</span>
              <div>
                <strong>Would you like to time your buy for the next trading day at 9:30 AM?</strong>
                <div style={{ marginTop: '4px', opacity: 0.9 }}>
                  Webull requires whole shares during extended/overnight sessions. We can safely hold this order in queue and route it to Webull right as regular hours open.
                </div>
              </div>
            </div>

            {/* Mode Switcher */}
            <div className="scheduled-order-tabs">
              <button
                type="button"
                className={`scheduled-order-tab ${orderMode === 'AMOUNT' ? 'active' : ''}`}
                onClick={() => handleModeChange('AMOUNT')}
              >
                💵 Order by Dollar Value ($ USD)
              </button>
              <button
                type="button"
                className={`scheduled-order-tab ${orderMode === 'QTY' ? 'active' : ''}`}
                onClick={() => handleModeChange('QTY')}
              >
                📊 Order by Share Quantity (QTY)
              </button>
            </div>

            <div className="scheduled-order-summary-card">
              <div className="scheduled-order-row">
                <span className="scheduled-order-label">Target Asset</span>
                <span className="scheduled-order-val">
                  <span className="scheduled-order-symbol-tag">{orderData.symbol}</span>
                  {refPriceNum > 0 ? ` ($${refPriceNum.toFixed(2)} / share)` : ''}
                </span>
              </div>

              <div className="scheduled-order-row">
                <span className="scheduled-order-label">Execution Time</span>
                <span className="scheduled-order-val scheduled-order-time-tag">
                  {loadingSchedule ? 'Checking calendar...' : nextOpenText}
                </span>
              </div>

              <div className="scheduled-order-row">
                <span className="scheduled-order-label">Order Type / Session</span>
                <span className="scheduled-order-val">Market Buy (CORE Session)</span>
              </div>

              {isCashAmount ? (
                <div className="scheduled-order-row">
                  <span className="scheduled-order-label">Estimated Shares</span>
                  <span className="scheduled-order-val" style={{ color: '#60a5fa' }}>
                    ~{refPriceNum > 0 && cashNum > 0 ? (cashNum / refPriceNum).toFixed(5) : '0'} shares
                  </span>
                </div>
              ) : (
                <div className="scheduled-order-row">
                  <span className="scheduled-order-label">Estimated Value</span>
                  <span className="scheduled-order-val" style={{ color: '#60a5fa' }}>
                    ${estimatedValue.toFixed(2)} USD
                    {ceilingNum > 0 && (
                      <span style={{ fontSize: '11px', color: '#9ca3af', marginLeft: '4px' }}>
                        (Max: ${maxEstimatedValue.toFixed(2)})
                      </span>
                    )}
                  </span>
                </div>
              )}

              {orderData.account_name && (
                <div className="scheduled-order-row">
                  <span className="scheduled-order-label">Webull Account</span>
                  <span className="scheduled-order-val" style={{ fontSize: '12px', color: '#9ca3af' }}>
                    {orderData.account_name}
                  </span>
                </div>
              )}
            </div>

            {/* Editable Order Size */}
            {isCashAmount ? (
              <div className="scheduled-order-field-group">
                <label className="scheduled-order-field-label" htmlFor="scheduledCashAmount">
                  <span>Order Value ($ USD)</span>
                  <span className="scheduled-order-field-badge">Min $5.00</span>
                </label>
                <div className="scheduled-order-input-wrapper">
                  <span className="scheduled-order-currency-prefix">$</span>
                  <input
                    id="scheduledCashAmount"
                    type="number"
                    step="0.01"
                    min="5.00"
                    className="scheduled-order-input"
                    value={totalCashAmount}
                    onChange={(e) => handleCashChange(e.target.value)}
                    placeholder="0.00"
                    required
                  />
                </div>
                <p className="scheduled-order-field-hint">
                  Specify the exact dollar budget to spend on {orderData.symbol} at market open.
                </p>
              </div>
            ) : (
              <div className="scheduled-order-field-group">
                <label className="scheduled-order-field-label" htmlFor="scheduledQuantity">
                  <span>Share Quantity</span>
                  <span className="scheduled-order-field-badge">Up to 5 Decimals</span>
                </label>
                <input
                  id="scheduledQuantity"
                  type="number"
                  step="0.00001"
                  min="0.00001"
                  className="scheduled-order-input scheduled-order-input-no-prefix"
                  value={quantity}
                  onChange={(e) => handleQuantityChange(e.target.value)}
                  placeholder="0.00"
                  required
                />
                <p className="scheduled-order-field-hint">
                  Specify the exact fractional or whole shares of {orderData.symbol} to purchase.
                </p>
              </div>
            )}

            {/* Price Protection Buffer & Price Ceiling */}
            <div className="scheduled-order-field-group">
              <label className="scheduled-order-field-label" htmlFor="scheduledPriceCeiling">
                <span>Maximum Purchase Price Ceiling ($ USD)</span>
                <span className="scheduled-order-field-badge">+{bufferPercent}% Buffer</span>
              </label>

              {/* Quick % Buffer Chips */}
              <div className="scheduled-order-chips">
                <span className="scheduled-order-chips-label">Quick Buffer:</span>
                {[1, 2, 3, 5, 10].map((pct) => (
                  <button
                    key={pct}
                    type="button"
                    className={`scheduled-order-chip ${parseFloat(bufferPercent) === pct ? 'active' : ''}`}
                    onClick={() => handleBufferSelect(pct)}
                  >
                    +{pct}% {pct === 3 ? '(Default)' : ''}
                  </button>
                ))}
              </div>

              <div className="scheduled-order-buffer-row">
                <div className="scheduled-order-input-wrapper scheduled-order-flex-1">
                  <span className="scheduled-order-currency-prefix">$</span>
                  <input
                    id="scheduledPriceCeiling"
                    type="number"
                    step="0.01"
                    min="0.01"
                    className="scheduled-order-input"
                    value={maxPrice}
                    onChange={(e) => handleMaxPriceChange(e.target.value)}
                    placeholder="0.00"
                  />
                </div>
                <div className="scheduled-order-pct-input-wrap">
                  <span className="scheduled-order-pct-label">+</span>
                  <input
                    id="scheduledBufferPct"
                    type="text"
                    inputMode="decimal"
                    className="scheduled-order-pct-input"
                    value={bufferPercent}
                    onChange={(e) => handleBufferInputChange(e.target.value)}
                    onBlur={handleBufferBlur}
                    placeholder="3.00"
                    title="Buffer percentage above reference price"
                  />
                  <span className="scheduled-order-pct-suffix">%</span>
                </div>
              </div>

              {/* Protection Explanation Callout */}
              <div className="scheduled-order-protection-callout">
                <div className="scheduled-order-protection-badge">
                  🛡️ Purchase Allowed Up to: ${maxPrice || '0.00'} / share (+{bufferPercent}%)
                </div>
                <div className="scheduled-order-protection-text">
                  {isCashAmount ? (
                    <>
                      If <strong>{orderData.symbol}</strong> opens at 9:30 AM between <strong>${refPriceNum.toFixed(2)}</strong> and <strong>${maxPrice || '0.00'}</strong> (+{bufferPercent}%), your <strong>${cashNum.toFixed(2)}</strong> buy will execute at open. It will <strong>NOT</strong> cancel for minor movements (such as +$0.01). It will only safely abort if the opening price spikes above <strong>${maxPrice || '0.00'}</strong>.
                    </>
                  ) : (
                    <>
                      If <strong>{orderData.symbol}</strong> opens at 9:30 AM between <strong>${refPriceNum.toFixed(2)}</strong> and <strong>${maxPrice || '0.00'}</strong> (+{bufferPercent}%), your order for <strong>{qtyNum || orderData.quantity} shares</strong> will execute at open (up to <strong>${maxEstimatedValue.toFixed(2)}</strong>). It will <strong>NOT</strong> cancel for minor movements (such as +$0.01). It will only safely abort if the opening price spikes above <strong>${maxPrice || '0.00'}</strong>.
                    </>
                  )}
                </div>
              </div>
            </div>

            {require2fa && (
              <div className="scheduled-order-field-group">
                <div className="scheduled-order-field-label-row">
                  <label className="scheduled-order-field-label" htmlFor="scheduledTotpCode">
                    Two-Factor Authentication Code
                  </label>
                  <button
                    type="button"
                    className="scheduled-order-paste-btn"
                    onClick={handlePasteTotp}
                    title="Paste 6-digit TOTP code from clipboard"
                  >
                    📋 Paste Code
                  </button>
                </div>
                <TotpCodeInput
                  id="scheduledTotpCode"
                  name="totp"
                  ref={totpInputRef}
                  className="scheduled-order-totp-input"
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value)}
                  placeholder="000000"
                />
                <p className="scheduled-order-field-hint">
                  Enter your 6-digit TOTP code to authorize this scheduled execution.
                </p>
              </div>
            )}

            {error && (
              <div className="scheduled-order-error" role="alert">
                <span>⚠️</span>
                <span>{error}</span>
              </div>
            )}
          </div>

          <div className="scheduled-order-footer">
            <button
              type="button"
              className="scheduled-order-btn-cancel"
              onClick={onClose}
              disabled={loading}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="scheduled-order-btn-submit"
              disabled={loading}
            >
              {loading ? 'Scheduling...' : '⏰ Schedule Buy for 9:30 AM'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
