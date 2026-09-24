import React, { useState, useEffect } from 'react';
import { formatOrderType } from '../utils/orderDisplay';
import TotpCodeInput from './TotpCodeInput';
import './ReplaceOrderConfirmModal.css';

export default function ReplaceOrderConfirmModal({
  isOpen,
  onClose,
  order,
  coin,
  onConfirm,
  loading = false,
  error = null
}) {
  const [twoFactorCode, setTwoFactorCode] = useState('');
  const [localError, setLocalError] = useState('');

  const [newPrice, setNewPrice] = useState('');
  const [newQuantity, setNewQuantity] = useState('');

  useEffect(() => {
    if (isOpen && order) {
      setTwoFactorCode('');
      setLocalError('');

      const price = order.price || order.trigger_price || '';
      const quantity = order.quantity || order.origQty || order.amount || '';

      setNewPrice(price ? String(price) : '');
      setNewQuantity(quantity ? String(quantity) : '');
    }
  }, [isOpen, order]);

  if (!isOpen || !order) return null;

  const symbol = order.symbol || coin?.symbol || 'Crypto';
  const isAutoBuy = !!order.isAutoBuy || order.trigger_type === 'auto_buy';
  const isAutoSell = !!order.isAutoSell || order.trigger_type === 'auto_sell';
  const isAutoTrigger = isAutoBuy || isAutoSell;

  const isLadder = String(order.order_id || '').startsWith('ladder_');
  const isTrailing = String(order.order_id || '').startsWith('trail_');

  const side = isAutoBuy ? 'AUTO-BUY' : isAutoSell ? 'AUTO-SELL' : (order.side || 'ORDER').toUpperCase();
  const type = isAutoBuy
    ? 'Volatility Surge Trigger'
    : isAutoSell
    ? 'Volatility Drop Trigger'
    : formatOrderType(order.type || order.order_type || 'LIMIT');

  const oldQuantity = order.quantity || order.origQty || order.amount;
  const oldPrice = order.price || order.trigger_price;

  let orderDescription = `${type} ${side}`;
  if (oldQuantity) {
    orderDescription += ` of ${oldQuantity} ${symbol}`;
  }
  if (oldPrice && Number(oldPrice) > 0) {
    orderDescription += ` @ $${Number(oldPrice).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 6 })}`;
  }

  const handlePriceChange = (val) => {
    setNewPrice(val);
    setLocalError('');
    if (!val) return;

    const numericVal = parseFloat(val);
    const oldQtyNum = parseFloat(oldQuantity);
    const oldPriceNum = parseFloat(oldPrice);

    if (!isNaN(numericVal) && numericVal > 0 && !isNaN(oldQtyNum) && !isNaN(oldPriceNum)) {
      const totalValue = oldPriceNum * oldQtyNum;
      const calculatedQty = totalValue / numericVal;
      setNewQuantity(Number(calculatedQty.toFixed(8)).toString());
    }
  };

  const handleQuantityChange = (val) => {
    setNewQuantity(val);
    setLocalError('');
    if (!val) return;

    const numericVal = parseFloat(val);
    const oldQtyNum = parseFloat(oldQuantity);
    const oldPriceNum = parseFloat(oldPrice);

    if (!isNaN(numericVal) && numericVal > 0 && !isNaN(oldQtyNum) && !isNaN(oldPriceNum)) {
      const totalValue = oldPriceNum * oldQtyNum;
      const calculatedPrice = totalValue / numericVal;
      setNewPrice(Number(calculatedPrice.toFixed(8)).toString());
    }
  };

  const handleConfirmClick = async () => {
    if (!/^\d{6}$/.test(twoFactorCode)) {
      setLocalError('Enter a valid 6-digit two-factor authentication code.');
      return;
    }

    if (!newPrice || Number(newPrice) <= 0) {
      setLocalError('Please enter a valid new price.');
      return;
    }

    if (!isAutoTrigger && !isTrailing && !isLadder && (!newQuantity || Number(newQuantity) <= 0)) {
      setLocalError('Please enter a valid new quantity.');
      return;
    }

    setLocalError('');
    await onConfirm(order, twoFactorCode, { price: newPrice, quantity: newQuantity });
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !loading) {
      handleConfirmClick();
    }
  };

  return (
    <div className="replace-confirm-backdrop" onClick={(e) => { if (e.target === e.currentTarget && !loading) onClose(); }}>
      <div className="replace-confirm-modal" role="dialog" aria-labelledby="replace-confirm-title">
        <div className="replace-confirm-header">
          <div className="replace-confirm-icon-wrap">
            <span className="replace-warning-icon">🔄</span>
          </div>
          <div>
            <h3 id="replace-confirm-title">
              Replace Pending Order
            </h3>
            <p className="replace-confirm-subtitle">Confirmation and 2FA required</p>
          </div>
          {!loading && (
            <button className="replace-confirm-close" onClick={onClose} aria-label="Close">
              ✕
            </button>
          )}
        </div>

        <div className="replace-confirm-body">
          <p className="replace-confirm-main-text">
            You are replacing <strong>{orderDescription}</strong>.
          </p>
          {coin?.current_price && (
            <p className="replace-current-price" style={{ margin: '0 0 16px 0', fontSize: '13px', color: 'var(--text-secondary, #94a3b8)' }}>
              Current Market Price: <strong>${Number(coin.current_price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 6 })}</strong>
            </p>
          )}

          <div className="replace-order-inputs">
             <div className="replace-input-group">
                <label htmlFor="replace-price">New Price ($)</label>
                <input
                  type="number"
                  id="replace-price"
                  value={newPrice}
                  onChange={(e) => handlePriceChange(e.target.value)}
                  min="0"
                  step="any"
                  disabled={loading}
                  autoComplete="off"
                />
             </div>
             {(!isAutoTrigger && !isTrailing && !isLadder) && (
               <div className="replace-input-group">
                  <label htmlFor="replace-quantity">New Quantity ({symbol})</label>
                  <input
                    type="number"
                    id="replace-quantity"
                    value={newQuantity}
                    onChange={(e) => handleQuantityChange(e.target.value)}
                    min="0"
                    step="any"
                    disabled={loading}
                    autoComplete="off"
                  />
               </div>
             )}
          </div>

          <div className="replace-2fa-input-group">
            <label htmlFor="replace-totp">Enter 2FA Code to Confirm:</label>
            <TotpCodeInput
              id="replace-totp"
              placeholder="000000"
              value={twoFactorCode}
              onChange={(e) => { setTwoFactorCode(e.target.value); setLocalError(''); }}
              onKeyDown={handleKeyDown}
              className="replace-2fa-input"
              autoFocus
              disabled={loading}
            />
          </div>

          {(localError || error) && (
            <div className="replace-confirm-error">
              ❌ {localError || error}
            </div>
          )}
        </div>

        <div className="replace-confirm-footer">
          <button
            type="button"
            className="btn btn-secondary replace-no-btn"
            onClick={onClose}
            disabled={loading}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary replace-yes-btn"
            onClick={handleConfirmClick}
            disabled={loading || !/^\d{6}$/.test(twoFactorCode) || !newPrice}
          >
            {loading ? 'Replacing...' : 'Yes, Replace Order'}
          </button>
        </div>
      </div>
    </div>
  );
}
