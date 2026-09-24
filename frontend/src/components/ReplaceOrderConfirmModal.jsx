import React from 'react';
import WebullTrading from '../pages/WebullTrading';
import Trading from '../pages/Trading';
import './ReplaceOrderConfirmModal.css';

export default function ReplaceOrderConfirmModal({
  isOpen,
  onClose,
  order,
  coin,
  onConfirm
}) {
  if (!isOpen || !order) return null;

  const isWebull = coin?.is_external || coin?.source === 'webull';

  const handleEmbeddedSuccess = () => {
    if (onConfirm) onConfirm();
  };

  return (
    <div className="replace-confirm-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="replace-confirm-modal replace-confirm-modal-wide" role="dialog" aria-labelledby="replace-confirm-title">
        <div className="replace-confirm-header" style={{ padding: '16px 20px', borderBottom: '1px solid var(--border-color, #334155)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div className="replace-confirm-icon-wrap" style={{ width: '36px', height: '36px' }}>
              <span className="replace-warning-icon" style={{ fontSize: '1.2rem' }}>🔄</span>
            </div>
            <div>
              <h3 id="replace-confirm-title" style={{ margin: 0, fontSize: '1.25rem', color: 'var(--text-primary, #f8fafc)' }}>
                Replace Pending Order
              </h3>
              <p style={{ margin: 0, fontSize: '0.85rem', color: '#94a3b8' }}>Advanced Order Replacement</p>
            </div>
          </div>
          <button className="replace-confirm-close" onClick={onClose} aria-label="Close" style={{ background: 'transparent', border: 'none', color: '#94a3b8', fontSize: '1.5rem', cursor: 'pointer' }}>
            ✕
          </button>
        </div>

        <div className="replace-confirm-body" style={{ padding: 0, maxHeight: '85vh', overflowY: 'auto', overflowX: 'hidden' }}>
          {isWebull ? (
            <WebullTrading 
              isEmbeddedReplaceMode={true} 
              embeddedOrder={order} 
              embeddedCoin={coin} 
              onEmbeddedClose={onClose} 
              onEmbeddedSuccess={handleEmbeddedSuccess} 
            />
          ) : (
            <Trading 
              isEmbeddedReplaceMode={true} 
              embeddedOrder={order} 
              embeddedCoin={coin} 
              onEmbeddedClose={onClose} 
              onEmbeddedSuccess={handleEmbeddedSuccess} 
            />
          )}
        </div>
      </div>
    </div>
  );
}
