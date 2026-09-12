import React from 'react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught an unhandled error:', error, errorInfo);
  }

  handleReload = () => {
    this.setState({ hasError: false, error: null });
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: '40px 20px',
          margin: '30px auto',
          maxWidth: '600px',
          textAlign: 'center',
          background: 'rgba(239, 68, 68, 0.08)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          borderRadius: '12px',
          color: '#f8fafc',
        }}>
          <div style={{ fontSize: '2.5rem', marginBottom: '16px' }}>⚠️</div>
          <h3 style={{ margin: '0 0 8px 0', fontSize: '1.25rem', color: '#f87171' }}>
            {this.props.fallbackTitle || 'Unable to display this view'}
          </h3>
          <p style={{ color: '#94a3b8', fontSize: '0.9rem', marginBottom: '20px', lineHeight: 1.5 }}>
            {this.props.fallbackMessage || 'An unexpected display error occurred. Please reload to restore live data.'}
          </p>
          <button
            type="button"
            onClick={this.handleReload}
            style={{
              padding: '10px 20px',
              borderRadius: '8px',
              background: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
              color: '#ffffff',
              border: 'none',
              fontWeight: 600,
              cursor: 'pointer',
              fontSize: '0.95rem',
            }}
          >
            🔄 Reload View
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
