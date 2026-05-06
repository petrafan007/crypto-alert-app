import React from 'react';
import './OrderFeedbackModal.css';

export default function OrderFeedbackModal({ isVisible, onClose, message, type = "success" }) {
  if (!isVisible) return null;

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  const getIcon = () => {
    switch (type) {
      case 'success':
        return '✅';
      case 'error':
        return '❌';
      case 'warning':
        return '⚠️';
      default:
        return 'ℹ️';
    }
  };

  const getTitle = () => {
    switch (type) {
      case 'success':
        return 'Order Successful';
      case 'error':
        return 'Order Failed';
      case 'warning':
        return 'Warning';
      default:
        return 'Information';
    }
  };

  return (
    <div className="order-feedback-modal-backdrop" onClick={handleBackdropClick}>
      <div className={`order-feedback-modal ${type}`}>
        <div className="order-feedback-modal-header">
          <div className="order-feedback-icon">{getIcon()}</div>
          <h3>{getTitle()}</h3>
        </div>
        
        <div className="order-feedback-modal-content">
          <div className="order-feedback-message">
            {message}
          </div>
        </div>
        
        <div className="order-feedback-modal-footer">
          <button 
            className="btn btn-primary"
            onClick={onClose}
          >
            OK
          </button>
        </div>
      </div>
    </div>
  );
}
