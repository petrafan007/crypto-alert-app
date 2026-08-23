import React, { useState, useEffect } from 'react';
import './TwoFactorModal.css';

export default function CancelOrderModal({
  isVisible,
  onClose,
  onConfirm,
  order,
  loading,
  error,
}) {
  const [code, setCode] = useState('');
  const [localError, setLocalError] = useState('');

  useEffect(() => {
    if (isVisible) {
      setCode('');
      setLocalError('');
    }
  }, [isVisible, order]);

  if (!isVisible) {
    return null;
  }

  const isAutoBuy = order?.is_auto_trigger && order?.trigger_type === 'auto_buy';
  const isAutoSell = order?.is_auto_trigger && order?.trigger_type === 'auto_sell';
  const isAutoTrigger = isAutoBuy || isAutoSell;
  const tradingPair = order?.symbol || 'this trading pair';
  const baseSymbol = order?.base_symbol || tradingPair;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (code.length !== 6 || !/^\d+$/.test(code)) {
      setLocalError('Please enter a valid 6-digit code.');
      return;
    }
    setLocalError('');
    await onConfirm(code);
  };

  const handleBackdropClick = (event) => {
    if (event.target === event.currentTarget && !loading) {
      onClose();
    }
  };

  return (
    <div className="two-factor-modal-backdrop" onClick={handleBackdropClick}>
      <div className="two-factor-modal">
        <div className="two-factor-modal-header">
          <h3>{isAutoBuy ? 'Cancel Auto-Buy Trigger' : isAutoSell ? 'Cancel Auto-Sell Trigger' : 'Cancel Order'}</h3>
          {!loading && (
            <button
              className="two-factor-close"
              onClick={onClose}
              aria-label="Close cancel order modal"
            >
              ×
            </button>
          )}
        </div>

        <div className="two-factor-modal-content">
          <p style={{ marginBottom: '18px', fontSize: '15px', color: '#e2e8f0' }}>
            {isAutoTrigger ? (
              <>
                Enter your 6-digit two-factor authentication code to confirm cancellation of the active <strong>{isAutoBuy ? 'Auto-Buy' : 'Auto-Sell'}</strong> trigger for <strong>{baseSymbol}</strong> {order?.trigger_details ? `(${order.trigger_details})` : ''}.
              </>
            ) : (
              <>
                Enter your 6-digit two-factor authentication code to confirm cancellation of this order for <strong>{tradingPair}</strong>.
              </>
            )}
          </p>

          <form onSubmit={handleSubmit} className="two-factor-form">
            <div className="form-group">
              <label htmlFor="cancelTwoFactorCode">6-digit Code</label>
              <input
                id="cancelTwoFactorCode"
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                maxLength="6"
                value={code}
                onChange={(e) => {
                  const value = e.target.value.replace(/\\D/g, '').slice(0, 6);
                  setCode(value);
                  setLocalError('');
                }}
                placeholder="000000"
                className="two-factor-input"
                autoFocus
                disabled={loading}
              />
            </div>

            {(localError || error) && (
              <div className="error-message">
                ❌ {localError || error}
              </div>
            )}

            <div className="two-factor-actions">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={onClose}
                disabled={loading}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={loading || code.length !== 6}
              >
                {loading ? '⏳ Confirming...' : 'Confirm'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
