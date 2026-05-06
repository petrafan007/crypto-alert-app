import React from 'react';
import { useNavigate } from 'react-router-dom';
import { FaExclamationTriangle, FaTimes } from 'react-icons/fa';

const TradePermissionModal = ({ show, onClose, pageName = 'trading', isLightMode }) => {
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

    // Custom message based on page
    const getMessage = () => {
        if (pageName === 'staking') {
            return "Your Binance API key does not allow for staking.";
        }
        return "Your Binance API key does not currently allow trading.";
    };

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
                    <h2 style={{ margin: 0, color: '#f0ad4e', fontSize: '1.3rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <FaExclamationTriangle /> {pageName === 'staking' ? 'Staking' : 'Trading'} Permission Required
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
                        {getMessage()}
                    </p>
                    <div style={{
                        backgroundColor: isLightMode ? '#fff3cd' : '#5c4b00',
                        padding: '12px',
                        borderRadius: '8px'
                    }}>
                        <strong style={{ color: isLightMode ? '#856404' : '#ffc107' }}>How to fix:</strong>
                        <ol style={{ color: textColor, margin: '8px 0 0 0', paddingLeft: '20px', fontSize: '14px' }}>
                            <li>Go to your Binance.US account</li>
                            <li>Navigate to API Management</li>
                            <li>Edit your API key and enable "Enable Spot Trading"</li>
                            <li>Return here and refresh the page</li>
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

export default TradePermissionModal;
