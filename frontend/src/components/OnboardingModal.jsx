import React from 'react';
import { useNavigate } from 'react-router-dom';
import { FaKey, FaRobot, FaBell, FaShieldAlt, FaQuestionCircle, FaTimes } from 'react-icons/fa';

const OnboardingModal = ({ show, onClose, isLightMode }) => {
    const navigate = useNavigate();

    const handleHelp = () => {
        onClose();
        navigate('/help');
    };

    if (!show) return null;

    const textColor = isLightMode ? '#212529' : '#e0e0e0';
    const bgColor = isLightMode ? '#ffffff' : '#16213e';
    const accentColor = '#4da6ff';

    const FeatureRow = ({ icon, title, description }) => (
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', marginBottom: '16px' }}>
            <div style={{ color: accentColor, fontSize: '20px', marginTop: '2px' }}>{icon}</div>
            <div>
                <strong style={{ color: textColor }}>{title}</strong>
                <p style={{ color: isLightMode ? '#6c757d' : '#adb5bd', margin: '4px 0 0 0', fontSize: '14px' }}>
                    {description}
                </p>
            </div>
        </div>
    );

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
                maxWidth: '600px',
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
                    <h2 style={{ margin: 0, color: textColor, fontSize: '1.4rem' }}>
                        🎉 Welcome to Crypto Alert App!
                    </h2>
                    <button onClick={onClose} style={{
                        background: 'none',
                        border: 'none',
                        color: textColor,
                        fontSize: '20px',
                        cursor: 'pointer'
                    }}><FaTimes /></button>
                </div>

                {/* Body */}
                <div style={{ padding: '24px' }}>
                    <p style={{ color: textColor, marginBottom: '24px' }}>
                        Here's a quick overview of the settings you can configure:
                    </p>

                    <FeatureRow
                        icon={<FaKey />}
                        title="Binance.US API Keys"
                        description="Connect your Binance.US account for portfolio sync, trading, and staking. Make sure to enable 'Enable Reading' and 'Enable Spot Trading' permissions."
                    />

                    <FeatureRow
                        icon={<FaRobot />}
                        title="AI Integration"
                        description="Enable AI-powered market analysis, sentiment tracking, and portfolio recommendations using OpenAI, Z.AI, or other providers."
                    />

                    <FeatureRow
                        icon={<FaBell />}
                        title="Telegram Alerts"
                        description="Set up Telegram notifications to receive instant price alerts directly to your phone."
                    />

                    <FeatureRow
                        icon={<FaShieldAlt />}
                        title="Two-Factor Authentication"
                        description="Add an extra layer of security to your trading operations with TOTP-based 2FA."
                    />

                    <div style={{
                        backgroundColor: isLightMode ? '#e7f1ff' : '#1e3a5f',
                        padding: '16px',
                        borderRadius: '8px',
                        marginTop: '16px'
                    }}>
                        <strong style={{ color: accentColor }}>💡 Pro Tip:</strong>
                        <p style={{ color: textColor, margin: '8px 0 0 0', fontSize: '14px' }}>
                            For the full Trading and Staking experience, make sure your Binance.US API key has <strong>"Enable Spot Trading"</strong> permission enabled.
                        </p>
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
                    <button onClick={handleHelp} style={{
                        padding: '10px 20px',
                        border: '1px solid #4da6ff',
                        borderRadius: '6px',
                        backgroundColor: 'transparent',
                        color: '#4da6ff',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px'
                    }}>
                        <FaQuestionCircle /> Help
                    </button>
                    <button onClick={onClose} style={{
                        padding: '10px 24px',
                        border: 'none',
                        borderRadius: '6px',
                        backgroundColor: '#4da6ff',
                        color: 'white',
                        cursor: 'pointer',
                        fontWeight: 600
                    }}>
                        Okay, Got It!
                    </button>
                </div>
            </div>
        </div>
    );
};

export default OnboardingModal;
