import React from 'react';
import './ReportModal.css';

export default function ReportModal({ isVisible, onClose, report, title = "Analysis Report" }) {
  if (!isVisible) return null;

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  return (
    <div className="report-modal-backdrop" onClick={handleBackdropClick}>
      <div className="report-modal">
        <div className="report-modal-header">
          <h3>{title}</h3>
          <button 
            className="report-modal-close"
            onClick={onClose}
            aria-label="Close modal"
          >
            ×
          </button>
        </div>
        
        <div className="report-modal-content">
          <div className="report-text">
            {report || 'No report available.'}
          </div>
        </div>
        
        <div className="report-modal-footer">
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
