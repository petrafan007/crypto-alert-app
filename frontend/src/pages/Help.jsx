import React from 'react';
import { Link } from 'react-router-dom';
import {
    FaKey, FaRobot, FaBell, FaShieldAlt, FaChartLine,
    FaCoins, FaFileInvoiceDollar, FaHome, FaCog,
    FaLock, FaQuestionCircle, FaExclamationTriangle
} from 'react-icons/fa';

export default function Help({ isLightMode }) {
    const textColor = isLightMode ? '#212529' : '#e0e0e0';
    const bgColor = isLightMode ? '#f8f9fa' : '#16213e';
    const cardBg = isLightMode ? '#ffffff' : '#1a1a2e';
    const borderColor = isLightMode ? '#dee2e6' : '#2d3748';
    const accentColor = '#4da6ff';

    const Section = ({ icon, title, children }) => (
        <div style={{
            backgroundColor: cardBg,
            borderRadius: '12px',
            padding: '24px',
            marginBottom: '20px',
            border: `1px solid ${borderColor}`
        }}>
            <h2 style={{
                color: accentColor,
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                marginBottom: '16px',
                fontSize: '1.3rem'
            }}>
                {icon} {title}
            </h2>
            <div style={{ color: textColor }}>{children}</div>
        </div>
    );

    const Tip = ({ children }) => (
        <div style={{
            backgroundColor: isLightMode ? '#e7f1ff' : '#1e3a5f',
            padding: '12px 16px',
            borderRadius: '8px',
            marginTop: '12px',
            fontSize: '14px'
        }}>
            <strong style={{ color: accentColor }}>💡 Tip:</strong> {children}
        </div>
    );

    const Warning = ({ children }) => (
        <div style={{
            backgroundColor: isLightMode ? '#fff3cd' : '#5c4b00',
            padding: '12px 16px',
            borderRadius: '8px',
            marginTop: '12px',
            fontSize: '14px',
            borderLeft: '4px solid #ffc107'
        }}>
            <strong style={{ color: isLightMode ? '#856404' : '#ffc107' }}>⚠️ Important:</strong> {children}
        </div>
    );

    return (
        <div style={{
            padding: '20px',
            maxWidth: '900px',
            margin: '0 auto',
            backgroundColor: bgColor,
            minHeight: '100vh'
        }}>
            <h1 style={{ color: textColor, marginBottom: '32px', display: 'flex', alignItems: 'center', gap: '12px' }}>
                <FaQuestionCircle style={{ color: accentColor }} /> Help & Documentation
            </h1>

            {/* Getting Started */}
            <Section icon={<FaHome />} title="Getting Started">
                <p style={{ marginBottom: '16px' }}>
                    Welcome to Crypto Alert App! This dashboard helps you manage your cryptocurrency portfolio,
                    execute trades, stake assets, and get AI-powered market analysis.
                </p>

                <h3 style={{ color: textColor, marginTop: '20px', marginBottom: '12px' }}>Quick Start Steps:</h3>
                <ol style={{ paddingLeft: '20px', lineHeight: '1.8' }}>
                    <li><strong>Set up your Binance.US API key</strong> in Settings (required for most features)</li>
                    <li><strong>Configure alerts</strong> via Telegram for price notifications</li>
                    <li><strong>Enable AI integration</strong> for market analysis (optional)</li>
                    <li><strong>Explore the dashboard</strong> to view your portfolio</li>
                </ol>
            </Section>

            {/* Access Requirements */}
            <Section icon={<FaLock />} title="Access Requirements">
                <p style={{ marginBottom: '16px' }}>
                    Different pages require different levels of API key configuration:
                </p>

                <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '12px' }}>
                    <thead>
                        <tr style={{ borderBottom: `2px solid ${borderColor}` }}>
                            <th style={{ textAlign: 'left', padding: '12px', color: accentColor }}>Page</th>
                            <th style={{ textAlign: 'left', padding: '12px', color: accentColor }}>Requires</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr style={{ borderBottom: `1px solid ${borderColor}` }}>
                            <td style={{ padding: '12px' }}>Dashboard, Settings, Tax Report, Help</td>
                            <td style={{ padding: '12px' }}>No API key needed</td>
                        </tr>
                        <tr style={{ borderBottom: `1px solid ${borderColor}` }}>
                            <td style={{ padding: '12px' }}>AI Analysis</td>
                            <td style={{ padding: '12px' }}>Valid Binance.US API key</td>
                        </tr>
                        <tr style={{ borderBottom: `1px solid ${borderColor}` }}>
                            <td style={{ padding: '12px' }}>Trading, Staking</td>
                            <td style={{ padding: '12px' }}>Valid API key + "Enable Spot Trading" permission</td>
                        </tr>
                    </tbody>
                </table>

                <Warning>
                    If you see a modal saying "API Key Required" or "Trading Permission Required",
                    follow the instructions to configure your API key in Settings.
                </Warning>
            </Section>

            {/* Binance API Key Setup */}
            <Section icon={<FaKey />} title="Binance.US API Key Setup">
                <p style={{ marginBottom: '16px' }}>
                    To use portfolio sync, trading, and staking features, you need to connect your Binance.US account.
                </p>

                <h3 style={{ color: textColor, marginTop: '20px', marginBottom: '12px' }}>Steps to create an API key:</h3>
                <ol style={{ paddingLeft: '20px', lineHeight: '1.8' }}>
                    <li>Log into your <a href="https://www.binance.us" target="_blank" rel="noopener noreferrer" style={{ color: accentColor }}>Binance.US</a> account</li>
                    <li>Navigate to <strong>Profile → API Management</strong></li>
                    <li>Create a new API key with a label (e.g., "Crypto Alert App")</li>
                    <li>Enable these permissions:
                        <ul style={{ marginTop: '8px', paddingLeft: '20px' }}>
                            <li><strong>Enable Reading</strong> - Required for portfolio sync</li>
                            <li><strong>Enable Spot Trading</strong> - Required for Trading and Staking pages</li>
                        </ul>
                    </li>
                    <li>Copy the API Key and Secret</li>
                    <li>Paste them into Settings and click "Test Binance Connection"</li>
                </ol>

                <Warning>
                    Never share your API Secret. For security, do NOT enable withdrawal permissions.
                </Warning>
            </Section>

            {/* How the Site Works */}
            <Section icon={<FaChartLine />} title="How the Site Works">
                <h3 style={{ color: textColor, marginBottom: '12px' }}>Dashboard</h3>
                <p style={{ marginBottom: '16px' }}>
                    Your main portfolio view showing all coins, current prices, gains/losses, and total value.
                    The dashboard auto-syncs with Binance.US when your API key is configured.
                </p>

                <h3 style={{ color: textColor, marginBottom: '12px' }}>Trading</h3>
                <p style={{ marginBottom: '16px' }}>
                    Execute spot trades directly from the app. Features include:
                </p>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px' }}>
                    <li>Market, Limit, Stop-Limit, and OCO orders</li>
                    <li>Real-time price charts</li>
                    <li>Order history and open orders management</li>
                    <li>Test Mode for paper trading (no real trades)</li>
                    <li>Optional 2FA for trade confirmation</li>
                </ul>

                <h3 style={{ color: textColor, marginBottom: '12px' }}>Staking</h3>
                <p style={{ marginBottom: '16px' }}>
                    Stake your crypto assets to earn rewards. View available staking options,
                    current staked balances, and rewards history.
                </p>

                <h3 style={{ color: textColor, marginBottom: '12px' }}>AI Analysis</h3>
                <p style={{ marginBottom: '16px' }}>
                    Get AI-powered analysis including:
                </p>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px' }}>
                    <li><strong>Market Analysis</strong> - Current market trends and opportunities</li>
                    <li><strong>Risk Assessment</strong> - Portfolio risk evaluation</li>
                    <li><strong>Portfolio Review</strong> - Personalized recommendations</li>
                </ul>

                <h3 style={{ color: textColor, marginBottom: '12px' }}>Tax Report</h3>
                <p>
                    Generate tax reports for your crypto transactions. Supports FIFO, LIFO, and HIFO
                    cost basis methods.
                </p>
            </Section>

            {/* AI Integration */}
            <Section icon={<FaRobot />} title="AI Integration Setup">
                <p style={{ marginBottom: '16px' }}>
                    Enable AI-powered market analysis by configuring an AI provider in Settings.
                </p>

                <h3 style={{ color: textColor, marginTop: '20px', marginBottom: '12px' }}>Supported Providers:</h3>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px' }}>
                    <li><strong>OpenAI</strong> - GPT-4o, GPT-4o-mini</li>
                    <li><strong>Z.AI (Zhipu)</strong> - GLM-4 Flash</li>
                    <li><strong>Anthropic</strong> - Claude models</li>
                    <li><strong>Google</strong> - Gemini models</li>
                </ul>

                <Tip>
                    The AI runs periodic analysis during your configured "analysis window" hours.
                    You can also manually trigger analysis from the AI Analysis page.
                </Tip>
            </Section>

            {/* Telegram Alerts */}
            <Section icon={<FaBell />} title="Telegram Alerts">
                <p style={{ marginBottom: '16px' }}>
                    Get instant price alerts and notifications via Telegram.
                </p>

                <ol style={{ paddingLeft: '20px', lineHeight: '1.8' }}>
                    <li>Create a bot with <a href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer" style={{ color: accentColor }}>@BotFather</a> on Telegram</li>
                    <li>Copy your Bot Token</li>
                    <li>Message your bot to start a conversation</li>
                    <li>Get your Chat ID from <a href="https://t.me/userinfobot" target="_blank" rel="noopener noreferrer" style={{ color: accentColor }}>@userinfobot</a></li>
                    <li>Enter both in Settings and test the connection</li>
                </ol>
            </Section>

            {/* Two-Factor Authentication */}
            <Section icon={<FaShieldAlt />} title="Two-Factor Authentication (2FA)">
                <p style={{ marginBottom: '16px' }}>
                    Add an extra layer of security to your trading operations with TOTP-based 2FA.
                </p>

                <ol style={{ paddingLeft: '20px', lineHeight: '1.8' }}>
                    <li>Enable 2FA in Settings and scan the QR code with an authenticator app</li>
                    <li>Verify by entering the 6-digit code</li>
                    <li>When "Require 2FA for Trading" is enabled, you'll need to confirm trades with a code</li>
                </ol>

                <Tip>
                    Store your recovery codes securely in case you lose access to your authenticator.
                </Tip>
            </Section>

            {/* Troubleshooting */}
            <Section icon={<FaExclamationTriangle />} title="Troubleshooting">
                <h3 style={{ color: textColor, marginBottom: '12px' }}>"API Key Required" Modal</h3>
                <p style={{ marginBottom: '16px' }}>
                    This appears when you try to access AI Analysis, Trading, or Staking without a configured API key.
                    Go to <Link to="/settings" style={{ color: accentColor }}>Settings</Link> and add your Binance.US credentials.
                </p>

                <h3 style={{ color: textColor, marginBottom: '12px' }}>"Trading Permission Required" Modal</h3>
                <p style={{ marginBottom: '16px' }}>
                    This appears when your API key doesn't have "Enable Spot Trading" permission.
                    Log into Binance.US, edit your API key, and enable this permission.
                </p>

                <h3 style={{ color: textColor, marginBottom: '12px' }}>Connection Test Failed</h3>
                <p>
                    Double-check that you copied the API Key and Secret correctly.
                    Make sure "Enable Reading" permission is enabled on your key.
                </p>
            </Section>

            <div style={{ textAlign: 'center', padding: '20px', color: textColor, opacity: 0.6 }}>
                <p>Need more help? Check the GitHub repository or contact support.</p>
            </div>
        </div>
    );
}
