import React, { useState, useEffect } from 'react';
import './TwoFactorModal.css';

export default function TwoFactorModal({ isVisible, onClose, onVerify, orderDetails }) {
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // Reset state when modal visibility changes
  useEffect(() => {
    if (isVisible) {
      setCode('');
      setError('');
      setLoading(false);
    }
  }, [isVisible]);

  const formatQuantity = (value) => {
    const numeric = parseFloat(value);
    if (Number.isFinite(numeric)) {
      return numeric.toString().replace(/\\.0+$/, '');
    }
    return value;
  };

  const formatPrice = (value) => {
    const numeric = parseFloat(value);
    if (!Number.isFinite(numeric) || numeric === 0) {
      return 'the market price';
    }
    if (numeric >= 1) {
      return `${numeric.toFixed(2)} USDT`;
    }
    return `${numeric.toFixed(4)} USDT`;
  };

  const getOrderExplanation = (details) => {
    if (!details) return '';

    const side = (details.side || 'BUY').toUpperCase();
    const type = (details.type || 'MARKET').toUpperCase();
    const symbol = details.symbol || '';
    const baseAsset = symbol.replace(/USDT$/i, '').replace(/USD$/i, '') || symbol;
    const qtyText = formatQuantity(details.quantity) || 'the specified amount of';
    const priceText = formatPrice(details.price);
    const stopPriceText = formatPrice(details.stopPrice);
    const stopLimitPriceText = formatPrice(details.stopLimitPrice);

    // Handle staking operations
    if (side === 'STAKE' && type === 'STAKING') {
      return `This will stake ${qtyText} ${baseAsset} on Binance.US. Your staked assets will earn rewards and can be unstaked at any time (subject to unstaking periods).`;
    }

    const actionVerb = side === 'SELL' ? 'sell' : 'buy';
    const directionUp = 'rises to or above';
    const directionDown = 'drops to or below';

    const builds = {
      MARKET: () =>
        `This market order will ${actionVerb} approximately ${qtyText} ${baseAsset} immediately at the best available price.`,
      LIMIT: () =>
        `This limit order will ${actionVerb} ${qtyText} ${baseAsset} at ${priceText}. It will only fill at this price or better.`,
      STOP_LOSS: () =>
        `If the last price ${directionDown} ${stopPriceText}, a market order will ${actionVerb} ${qtyText} ${baseAsset}.`,
      STOP_LOSS_LIMIT: () =>
        `If the last price ${directionDown} ${stopPriceText}, a limit order will ${actionVerb} ${qtyText} ${baseAsset} at ${priceText}.`,
      TAKE_PROFIT: () =>
        `If the last price ${side === 'SELL' ? directionUp : directionDown} ${stopPriceText}, a market order will ${actionVerb} ${qtyText} ${baseAsset}.`,
      TAKE_PROFIT_LIMIT: () =>
        `If the last price ${side === 'SELL' ? directionUp : directionDown} ${stopPriceText}, a limit order will ${actionVerb} ${qtyText} ${baseAsset} at ${priceText}.`,
      LIMIT_MAKER: () =>
        `This post-only limit order will ${actionVerb} ${qtyText} ${baseAsset} at ${priceText}. If it would match immediately as a taker order, Binance.US will cancel it.`,
      OCO: () =>
        `This OCO (One-Cancels-Other) order combines two orders that work together: ` +
        `(1) A LIMIT order to ${actionVerb} ${qtyText} ${baseAsset} if the price reaches ${priceText}, OR ` +
        `(2) A STOP-LIMIT order that triggers if the price ${side === 'SELL' ? directionDown : directionUp} ${stopPriceText}, then places a ${actionVerb} order at ${stopLimitPriceText}. ` +
        `Whichever condition is met FIRST will execute, and the other order is automatically cancelled.`
    };

    const builder = builds[type];
    return builder ? builder() : `This order will ${actionVerb} ${qtyText} ${baseAsset} when its trigger conditions are met.`;
  };

  const explanation = getOrderExplanation(orderDetails);

  if (!isVisible) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (code.length !== 6 || !/^\d+$/.test(code)) {
      setError('Please enter a valid 6-digit code');
      return;
    }

    setLoading(true);
    setError('');

    try {
      await onVerify(code);
      setLoading(false);
    } catch (err) {
      setError(err.message || 'Verification failed');
      setLoading(false);
    }
  };

  const handleCodeChange = (e) => {
    const value = e.target.value.replace(/\D/g, '').slice(0, 6);
    setCode(value);
    setError('');
  };

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget && !loading) {
      onClose();
    }
  };

  return (
    <div className="two-factor-modal-backdrop" onClick={handleBackdropClick}>
      <div className="two-factor-modal">
        <div className="two-factor-modal-header">
          <h3>🔐 Two-Factor Authentication</h3>
          {!loading && (
            <button
              className="two-factor-close"
              onClick={onClose}
              aria-label="Close"
            >
              ×
            </button>
          )}
        </div>

        <div className="two-factor-modal-content">
          {orderDetails && (
            <div className="order-summary">
              <h4>Order Summary:</h4>
              <div className="order-detail-row">
                <span className="label">Action:</span>
                <span className={`value ${orderDetails.side.toLowerCase()}`}>
                  {orderDetails.side} {orderDetails.symbol}
                </span>
              </div>
              <div className="order-detail-row">
                <span className="label">Type:</span>
                <span className="value">{orderDetails.type}</span>
              </div>
              <div className="order-detail-row">
                <span className="label">Quantity:</span>
                <span className="value">{orderDetails.quantity}</span>
              </div>
              {orderDetails.price && orderDetails.price > 0 && (
                <div className="order-detail-row">
                  <span className="label">Price:</span>
                  <span className="value">${orderDetails.price}</span>
                </div>
              )}
              {orderDetails.estimatedValue && (
                <div className="order-detail-row total">
                  <span className="label">Est. Value:</span>
                  <span className="value">${orderDetails.estimatedValue}</span>
                </div>
              )}
            </div>
          )}

          {explanation && (
            <div className="order-explanation">
              {explanation}
            </div>
          )}

          <form onSubmit={handleSubmit} className="two-factor-form">
            <div className="form-group">
              <label htmlFor="twoFactorCode">
                Enter your 6-digit authentication code:
              </label>
              <input
                id="twoFactorCode"
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                maxLength="6"
                value={code}
                onChange={handleCodeChange}
                placeholder="000000"
                className="two-factor-input"
                autoFocus
                disabled={loading}
                autoComplete="off"
              />
              <p className="help-text">
                Enter the code from your authenticator app (e.g., Bitwarden, Google Authenticator)
              </p>
            </div>

            {error && (
              <div className="error-message">
                ❌ {error}
              </div>
            )}

            <div className="two-factor-actions">
              <button
                type="button"
                onClick={onClose}
                className="btn btn-secondary"
                disabled={loading}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={loading || code.length !== 6}
              >
                {loading ? '⏳ Verifying...' : '✓ Verify & Submit Order'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
