import React, { useState, useEffect } from 'react';
import './CancelOrderConfirmModal.css';

export default function CancelOrderConfirmModal({
  isOpen,
  onClose,
  order,
  coin,
  onConfirm,
  loading = false,
  error = null
}) {
  const [twoFactorCode, setTwoFactorCode] = useState('');

  useEffect(() => {
    if (isOpen) {
      setTwoFactorCode('');
    }
  }, [isOpen, order]);

  if (!isOpen || !order) return null;

  const symbol = order.symbol || coin?.symbol || 'Crypto';
  const isAutoBuy = !!order.isAutoBuy || order.trigger_type === 'auto_buy';
  const isAutoSell = !!order.isAutoSell || order.trigger_type === 'auto_sell';
  const isAutoTrigger = isAutoBuy || isAutoSell;

  const side = isAutoBuy ? 'AUTO-BUY' : isAutoSell ? 'AUTO-SELL' : (order.side || 'ORDER').toUpperCase();
  const type = isAutoBuy
    ? 'Volatility Surge Trigger'
    : isAutoSell
    ? 'Volatility Drop Trigger'
    : (order.type || order.order_type || 'LIMIT').replace(/_/g, ' ');

  const quantity = order.quantity || order.origQty || order.amount;
  const price = order.price || order.trigger_price;

  let orderDescription = `${type} ${side}`;
  if (isAutoBuy) {
    const vol = order.volatility_pct || coin?.auto_buy_volatility_pct || coin?.volatility_pct || '—';
    const amt = order.amount || coin?.auto_buy_amount || '—';
    const quote = order.quote_currency || coin?.auto_buy_quote_currency || 'USDT';
    orderDescription = `Auto-Buy Trigger for ${symbol} (+${vol}% surge with $${amt} ${quote})`;
  } else if (isAutoSell) {
    const vol = order.volatility_pct || coin?.auto_sell_volatility_pct || coin?.volatility_pct || '—';
    orderDescription = `Auto-Sell Trigger for ${symbol} (-${vol}% drop)`;
  } else {
    if (quantity) {
      orderDescription += ` of ${quantity} ${symbol}`;
    }
    if (price && Number(price) > 0) {
      orderDescription += ` @ $${Number(price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 6 })}`;
    }
  }

  const handleConfirmClick = async () => {
    await onConfirm(order, twoFactorCode);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !loading) {
      handleConfirmClick();
    }
  };

  return (
    <div className="cancel-confirm-backdrop" onClick={(e) => { if (e.target === e.currentTarget && !loading) onClose(); }}>
      <div className="cancel-confirm-modal" role="dialog" aria-labelledby="cancel-confirm-title">
        <div className="cancel-confirm-header">
          <div className="cancel-confirm-icon-wrap">
            <span className="cancel-warning-icon">⚠️</span>
          </div>
          <div>
            <h3 id="cancel-confirm-title">
              {isAutoBuy ? 'Cancel Auto-Buy Trigger' : isAutoSell ? 'Cancel Auto-Sell Trigger' : 'Cancel Pending Order'}
            </h3>
            <p className="cancel-confirm-subtitle">Confirmation and 2FA required</p>
          </div>
          {!loading && (
            <button className="cancel-confirm-close" onClick={onClose} aria-label="Close">
              ✕
            </button>
          )}
        </div>

        <div className="cancel-confirm-body">
          <p className="cancel-confirm-main-text">
            You are canceling <strong>{orderDescription}</strong>.
          </p>
          <p className="cancel-confirm-question">
            Are you sure you want to do this?
          </p>

          <div className="cancel-order-summary-box">
            <div className="cancel-order-summary-row">
              <span>Asset:</span>
              <strong>{symbol}</strong>
            </div>
            <div className="cancel-order-summary-row">
              <span>Side / Trigger:</span>
              <span className={`badge-pill badge-${side.toLowerCase().replace(/_/g, '-')}`}>{side}</span>
            </div>
            <div className="cancel-order-summary-row">
              <span>Type:</span>
              <span>{type}</span>
            </div>
            {isAutoBuy && (
              <>
                <div className="cancel-order-summary-row">
                  <span>Surge Threshold:</span>
                  <strong>+{order.volatility_pct || coin?.auto_buy_volatility_pct || coin?.volatility_pct}%</strong>
                </div>
                <div className="cancel-order-summary-row">
                  <span>Allocation:</span>
                  <strong>${order.amount || coin?.auto_buy_amount} {order.quote_currency || coin?.auto_buy_quote_currency || 'USDT'}</strong>
                </div>
              </>
            )}
            {isAutoSell && (
              <div className="cancel-order-summary-row">
                <span>Drop Threshold:</span>
                <strong>-{order.volatility_pct || coin?.auto_sell_volatility_pct || coin?.volatility_pct}%</strong>
              </div>
            )}
            {!isAutoTrigger && price && Number(price) > 0 && (
              <div className="cancel-order-summary-row">
                <span>Price:</span>
                <strong>${Number(price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 6 })}</strong>
              </div>
            )}
            {!isAutoTrigger && order.order_id && (
              <div className="cancel-order-summary-row">
                <span>Order ID:</span>
                <span className="order-id-mono">{order.order_id}</span>
              </div>
            )}
          </div>

          <div className="cancel-2fa-input-group">
            <label htmlFor="cancel-totp">Enter 2FA Code to Confirm:</label>
            <input
              id="cancel-totp"
              type="text"
              inputMode="numeric"
              maxLength="6"
              placeholder="000000"
              value={twoFactorCode}
              onChange={(e) => setTwoFactorCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              onKeyDown={handleKeyDown}
              className="cancel-2fa-input"
              autoFocus
              disabled={loading}
            />
          </div>

          {error && (
            <div className="cancel-confirm-error">
              ❌ {error}
            </div>
          )}
        </div>

        <div className="cancel-confirm-footer">
          <button
            type="button"
            className="btn btn-secondary cancel-no-btn"
            onClick={onClose}
            disabled={loading}
          >
            No, Keep {isAutoTrigger ? 'Trigger' : 'Order'}
          </button>
          <button
            type="button"
            className="btn btn-danger cancel-yes-btn"
            onClick={handleConfirmClick}
            disabled={loading}
          >
            {loading ? 'Canceling...' : isAutoTrigger ? 'Yes, Cancel Trigger' : 'Yes, Cancel Order'}
          </button>
        </div>
      </div>
    </div>
  );
}
