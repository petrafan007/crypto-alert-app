import React from 'react';
import { useNavigate } from 'react-router-dom';
import { FaKey, FaTimes } from 'react-icons/fa';

const ApiKeyRequiredModal = ({ show, onClose, isLightMode }) => {
    const navigate = useNavigate();

    const handleGoToSettings = () => {
        onClose();
        navigate('/settings');
    };

    const handleGoToDashboard = () => {
        onClose();
        navigate('/');
    };

    if (!show) return null;

    const textColor = isLightMode ? '#212529' : '#e0e0e0';
    const bgColor = isLightMode ? '#ffffff' : '#16213e';

    return (
        <div style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.6)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 9999
        }} onClick={onClose}>
            <div style={{
                backgroundColor: bgColor,
                borderRadius: '12px',
                maxWidth: '500px',
                width: '90%',
                maxHeight: '90vh',
                overflow: 'auto',
                boxShadow: '0 10px 40px rgba(0,0,0,0.4)'
            }} onClick={e => e.stopPropagation()}>
                {/* Header */}
                <div style={{
                    padding: '20px 24px',
                    borderBottom: `1px solid ${isLightMode ? '#dee2e6' : '#2d3748'}`,
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center'
                }}>
                    <h2 style={{ margin: 0, color: '#4da6ff', fontSize: '1.3rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <FaKey /> API Key Required
                    </h2>
                    <button onClick={handleGoToDashboard} style={{
                        background: 'none',
                        border: 'none',
                        color: textColor,
                        fontSize: '20px',
                        cursor: 'pointer'
                    }}><FaTimes /></button>
                </div>

                {/* Body */}
                <div style={{ padding: '24px' }}>
                    <p style={{ color: textColor, marginBottom: '16px', fontSize: '16px' }}>
                        To access this feature, you need to configure your Binance.US API key.
                    </p>
                    <div style={{
                        backgroundColor: isLightMode ? '#e7f1ff' : '#1e3a5f',
                        padding: '16px',
                        borderRadius: '8px'
                    }}>
                        <strong style={{ color: '#4da6ff' }}>How to set up:</strong>
                        <ol style={{ color: textColor, margin: '8px 0 0 0', paddingLeft: '20px', fontSize: '14px' }}>
                            <li>Go to Settings</li>
                            <li>Enter your Binance.US API Key and Secret</li>
                            <li>Click "Test Binance Connection" to verify</li>
                            <li>Return to this page</li>
                        </ol>
                    </div>
                </div>

                {/* Footer */}
                <div style={{
                    padding: '16px 24px',
                    borderTop: `1px solid ${isLightMode ? '#dee2e6' : '#2d3748'}`,
                    display: 'flex',
                    justifyContent: 'flex-end',
                    gap: '12px'
                }}>
                    <button onClick={handleGoToDashboard} style={{
                        padding: '10px 20px',
                        border: `1px solid ${isLightMode ? '#6c757d' : '#555'}`,
                        borderRadius: '6px',
                        backgroundColor: 'transparent',
                        color: textColor,
                        cursor: 'pointer'
                    }}>
                        Go to Dashboard
                    </button>
                    <button onClick={handleGoToSettings} style={{
                        padding: '10px 24px',
                        border: 'none',
                        borderRadius: '6px',
                        backgroundColor: '#4da6ff',
                        color: 'white',
                        cursor: 'pointer',
                        fontWeight: 600
                    }}>
                        Go to Settings
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ApiKeyRequiredModal;
