import React from 'react';

export default function LegalModal({ isOpen, onClose, title, children }) {
  if (!isOpen) return null;

  return (
    <div
      className="ob-modal-backdrop legal-modal-backdrop"
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.82)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 2147483647,
        padding: '20px',
        backdropFilter: 'blur(6px)'
      }}
      onClick={onClose}
    >
      <div
        className="legal-modal-container"
        style={{
          backgroundColor: 'var(--card-bg, #1a1f23)',
          color: 'var(--text-primary, #e0e0e0)',
          borderRadius: '16px',
          border: '1px solid var(--border-color, #333)',
          width: '100%',
          maxWidth: '850px',
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 20px 40px rgba(0,0,0,0.5)',
          overflow: 'hidden'
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '20px 28px',
            borderBottom: '1px solid var(--border-color, #333)',
            backgroundColor: 'var(--bg-quaternary, #232b31)'
          }}
        >
          <h2 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 600, color: 'var(--text-primary, #fff)' }}>
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            style={{
              background: 'transparent',
              border: 'none',
              fontSize: '24px',
              fontWeight: 'bold',
              color: 'var(--text-secondary, #aaa)',
              cursor: 'pointer',
              lineHeight: 1,
              padding: '4px 8px',
              borderRadius: '6px'
            }}
            onMouseEnter={(e) => e.target.style.color = '#fff'}
            onMouseLeave={(e) => e.target.style.color = 'var(--text-secondary, #aaa)'}
          >
            &times;
          </button>
        </div>

        <div
          style={{
            padding: '24px 28px',
            overflowY: 'auto',
            flex: 1,
            lineHeight: 1.7,
            fontSize: '15px'
          }}
        >
          {children}
        </div>

        <div
          style={{
            padding: '16px 28px',
            borderTop: '1px solid var(--border-color, #333)',
            display: 'flex',
            justifyContent: 'flex-end',
            backgroundColor: 'var(--bg-quaternary, #232b31)'
          }}
        >
          <button
            type="button"
            className="ob-button primary"
            onClick={onClose}
            style={{
              padding: '8px 24px',
              cursor: 'pointer',
              borderRadius: '8px',
              fontWeight: 600
            }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
