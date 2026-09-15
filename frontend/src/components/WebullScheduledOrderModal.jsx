import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import TotpCodeInput from './TotpCodeInput';
import './WebullScheduledOrderModal.css';

export default function WebullScheduledOrderModal({
  isOpen,
  onClose,
  orderData,
  require2fa = false,
  onSuccess,
}) {
  const [maxPrice, setMaxPrice] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [nextOpenText, setNextOpenText] = useState('Next trading day at 9:30 AM ET');
  const [loading, setLoading] = useState(false);
  const [loadingSchedule, setLoadingSchedule] = useState(false);
  const [error, setError] = useState('');
  const totpInputRef = useRef(null);

  useEffect(() => {
    if (!isOpen) {
      setError('');
      setTotpCode('');
      setLoading(false);
      return;
    }

    // Default price ceiling: +3% buffer above current quote (editable by user)
    const refPx = parseFloat(orderData?.reference_price || 0);
    if (refPx > 0) {
      setMaxPrice((refPx * 1.03).toFixed(2));
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
        // Fallback to generic message
        setNextOpenText('Next trading day at 9:30 AM ET');
      })
      .finally(() => {
        setLoadingSchedule(false);
      });

    // Focus 2FA if required
    if (require2fa) {
      setTimeout(() => {
        totpInputRef.current?.focus();
      }, 80);
    }
  }, [isOpen, orderData, require2fa]);

  if (!isOpen || !orderData) return null;

  const isCashAmount = orderData.entrust_type === 'AMOUNT';
  const displayQty = isCashAmount
    ? `$${parseFloat(orderData.total_cash_amount || 0).toFixed(2)} USD`
    : `${orderData.quantity} shares`;

  const estimatedValue = isCashAmount
    ? parseFloat(orderData.total_cash_amount || 0)
    : (parseFloat(orderData.quantity || 0) * parseFloat(orderData.reference_price || 0));

  const handleSubmit = async (e) => {
    e?.preventDefault();
    setError('');

    if (require2fa && (!totpCode || totpCode.trim().length !== 6)) {
      setError('Please enter your 6-digit two-factor authentication code.');
      return;
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
        entrust_type: orderData.entrust_type || 'QTY',
        quantity: isCashAmount ? null : parseFloat(orderData.quantity),
        total_cash_amount: isCashAmount ? parseFloat(orderData.total_cash_amount) : null,
        reference_price: orderData.reference_price ? parseFloat(orderData.reference_price) : null,
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

        <form onSubmit={handleSubmit}>
          <div className="scheduled-order-body">
            <div className="scheduled-order-prompt-box">
              <span className="scheduled-order-prompt-icon" aria-hidden="true">💡</span>
              <div>
                <strong>Would you like to time your buy for the next trading day at 9:30 AM?</strong>
                <div style={{ marginTop: '4px', opacity: 0.9 }}>
                  Webull requires whole shares during extended/overnight sessions. We can safely hold this fractional order in queue and route it to Webull right as regular hours open.
                </div>
              </div>
            </div>

            <div className="scheduled-order-summary-card">
              <div className="scheduled-order-row">
                <span className="scheduled-order-label">Target Asset</span>
                <span className="scheduled-order-val">
                  <span className="scheduled-order-symbol-tag">{orderData.symbol}</span>
                  {orderData.reference_price ? ` ($${parseFloat(orderData.reference_price).toFixed(2)})` : ''}
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

              <div className="scheduled-order-row">
                <span className="scheduled-order-label">Order Size</span>
                <span className="scheduled-order-val" style={{ color: '#60a5fa' }}>{displayQty}</span>
              </div>

              {estimatedValue > 0 && (
                <div className="scheduled-order-row">
                  <span className="scheduled-order-label">Estimated Value</span>
                  <span className="scheduled-order-val">${estimatedValue.toFixed(2)} USD</span>
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

            <div className="scheduled-order-field-group">
              <label className="scheduled-order-field-label" htmlFor="scheduledPriceCeiling">
                <span>Maximum Purchase Price Ceiling ($ USD)</span>
                <span className="scheduled-order-field-badge">+3% Default Buffer</span>
              </label>
              <div className="scheduled-order-input-wrapper">
                <span className="scheduled-order-currency-prefix">$</span>
                <input
                  id="scheduledPriceCeiling"
                  type="number"
                  step="0.01"
                  min="0.01"
                  className="scheduled-order-input"
                  value={maxPrice}
                  onChange={(e) => setMaxPrice(e.target.value)}
                  placeholder="0.00"
                />
              </div>
              <p className="scheduled-order-field-hint">
                <strong>Price Protection:</strong> If the market opens at 9:30 AM above this ceiling price, the order will safely abort without buying to protect you against sudden gap-ups.
              </p>
            </div>

            {require2fa && (
              <div className="scheduled-order-field-group">
                <label className="scheduled-order-field-label" htmlFor="scheduledTotpCode">
                  Two-Factor Authentication Code
                </label>
                <TotpCodeInput
                  id="scheduledTotpCode"
                  ref={totpInputRef}
                  className="scheduled-order-totp-input"
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value)}
                  placeholder="000000"
                  autoFocus
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
