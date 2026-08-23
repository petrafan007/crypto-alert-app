import React, { useState, useEffect } from 'react';
import './TransactionModal.css';

const TransactionModal = ({ isOpen, onClose, transactions, type, dateStr }) => {
  const [currentIndex, setCurrentIndex] = useState(0);

  useEffect(() => {
    // Reset index when modal opens with new data
    if (isOpen) {
      setCurrentIndex(0);
    }
  }, [isOpen, transactions]);

  if (!isOpen || !transactions || transactions.length === 0) {
    return null;
  }

  const handlePrev = (e) => {
    e.stopPropagation();
    setCurrentIndex((prev) => (prev > 0 ? prev - 1 : transactions.length - 1));
  };

  const handleNext = (e) => {
    e.stopPropagation();
    setCurrentIndex((prev) => (prev < transactions.length - 1 ? prev + 1 : 0));
  };

  const formatCurrency = (val) => {
    return Number(val).toLocaleString(undefined, {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 6
    });
  };

  const currentTx = transactions[currentIndex];
  const txDate = new Date(currentTx.time * 1000).toLocaleString('en-US', { timeZone: 'America/New_York' });
  const txValue = (currentTx.amount * currentTx.price) || 0;

  return (
    <div className="tx-modal-overlay" onClick={onClose}>
      <div className="tx-modal-content" onClick={e => e.stopPropagation()}>
        <button className="tx-modal-close" onClick={onClose}>×</button>
        
        <div className="tx-modal-header">
          <h3 style={{ color: type === 'BUY' ? '#22c55e' : '#ef4444' }}>
            {type === 'BUY' ? 'Purchase Details' : 'Sale Details'}
          </h3>
          <div className="tx-modal-date">{dateStr}</div>
        </div>

        <div className="tx-modal-body">
          {transactions.length > 1 && (
            <button className="tx-modal-nav prev" onClick={handlePrev}>‹</button>
          )}
          
          <div className="tx-modal-details">
            <div className="tx-detail-row">
              <span className="tx-label">Coin:</span>
              <span className="tx-value fw-bold">{currentTx.asset}</span>
            </div>
            <div className="tx-detail-row">
              <span className="tx-label">Date/Time:</span>
              <span className="tx-value">{txDate}</span>
            </div>
            <div className="tx-detail-row">
              <span className="tx-label">Coin Price:</span>
              <span className="tx-value">{formatCurrency(currentTx.price)}</span>
            </div>
            <div className="tx-detail-row">
              <span className="tx-label">Amount:</span>
              <span className="tx-value">{currentTx.amount} {currentTx.asset}</span>
            </div>
            <div className="tx-detail-row">
              <span className="tx-label">Value (USDT):</span>
              <span className="tx-value" style={{ color: type === 'BUY' ? '#22c55e' : '#ef4444', fontWeight: 'bold' }}>
                {formatCurrency(txValue)}
              </span>
            </div>
          </div>

          {transactions.length > 1 && (
            <button className="tx-modal-nav next" onClick={handleNext}>›</button>
          )}
        </div>

        {transactions.length > 1 && (
          <div className="tx-modal-footer">
            Transaction {currentIndex + 1} of {transactions.length}
          </div>
        )}
      </div>
    </div>
  );
};

export default TransactionModal;
