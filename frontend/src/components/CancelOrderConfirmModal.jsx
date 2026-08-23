import React, { useState } from 'react';
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
  const [needs2FA, setNeeds2FA] = useState(false);

  if (!isOpen || !order) return null;

  const symbol = order.symbol || coin?.symbol || 'Crypto';
  const side = (order.side || 'ORDER').toUpperCase();
  const type = (order.type || order.order_type || 'LIMIT').replace(/_/g, ' ');
  const quantity = order.quantity || order.origQty || order.amount;
  const price = order.price || order.trigger_price;

  let orderDescription = `${type} ${side}`;
  if (quantity) {
    orderDescription += ` of ${quantity} ${symbol}`;
  }
  if (price && Number(price) > 0) {
    orderDescription += ` @ $${Number(price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 6 })}`;
  }

  const handleConfirmClick = async () => {
    try {
      const result = await onConfirm(order, twoFactorCode);
      if (result?.requires_2fa) {
        setNeeds2FA(true);
      }
    } catch (err) {
      if (err?.response?.data?.requires_2fa) {
        setNeeds2FA(true);
      }
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
            <h3 id="cancel-confirm-title">Cancel Pending Order</h3>
            <p className="cancel-confirm-subtitle">Confirmation required</p>
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
              <span>Side:</span>
              <span className={`badge-pill badge-${side.toLowerCase()}`}>{side}</span>
            </div>
            <div className="cancel-order-summary-row">
              <span>Type:</span>
              <span>{type}</span>
            </div>
            {price && Number(price) > 0 && (
              <div className="cancel-order-summary-row">
                <span>Price:</span>
                <strong>${Number(price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 6 })}</strong>
              </div>
            )}
            {order.order_id && (
              <div className="cancel-order-summary-row">
                <span>Order ID:</span>
                <span className="order-id-mono">{order.order_id}</span>
              </div>
            )}
          </div>

          {needs2FA && (
            <div className="cancel-2fa-input-group">
              <label htmlFor="cancel-totp">Enter 2FA Code to Confirm:</label>
              <input
                id="cancel-totp"
                type="text"
                maxLength="6"
                placeholder="000000"
                value={twoFactorCode}
                onChange={(e) => setTwoFactorCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                className="cancel-2fa-input"
                autoFocus
              />
            </div>
          )}

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
            No, Keep Order
          </button>
          <button
            type="button"
            className="btn btn-danger cancel-yes-btn"
            onClick={handleConfirmClick}
            disabled={loading || (needs2FA && twoFactorCode.length !== 6)}
          >
            {loading ? 'Canceling...' : 'Yes, Cancel Order'}
          </button>
        </div>
      </div>
    </div>
  );
}
