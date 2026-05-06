import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';

export default function PrivacyPolicy({ isLightMode }) {
    useEffect(() => {
        window.scrollTo(0, 0);
    }, []);

    const textColor = isLightMode ? '#212529' : '#e0e0e0';
    const bgColor = isLightMode ? '#f8f9fa' : '#16213e';
    const cardBg = isLightMode ? '#ffffff' : '#1a1a2e';
    const borderColor = isLightMode ? '#dee2e6' : '#2d3748';

    const Section = ({ title, children }) => (
        <div style={{ marginBottom: '28px' }}>
            <h2 style={{ color: textColor, fontSize: '1.3rem', marginBottom: '12px' }}>{title}</h2>
            <div style={{ color: textColor, lineHeight: '1.7', fontSize: '15px' }}>{children}</div>
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
            <div style={{
                backgroundColor: cardBg,
                borderRadius: '12px',
                padding: '32px',
                border: `1px solid ${borderColor}`
            }}>
                <h1 style={{ color: textColor, marginBottom: '8px' }}>Privacy Policy</h1>
                <p style={{ color: textColor, opacity: 0.7, marginBottom: '32px' }}>
                    Last Updated: January 19, 2026
                </p>

                <Section title="1. Introduction">
                    <p>
                        Crypto Alert App ("we," "our," or "us") is committed to protecting your privacy.
                        This Privacy Policy explains how we collect, use, disclose, and safeguard your
                        information when you use our cryptocurrency portfolio management application.
                    </p>
                </Section>

                <Section title="2. Information We Collect">
                    <p><strong>Account Information:</strong> Email address, username, and password (hashed).</p>
                    <p style={{ marginTop: '8px' }}><strong>API Credentials:</strong> Your Binance.US API keys (encrypted at rest) to enable portfolio sync and trading features.</p>
                    <p style={{ marginTop: '8px' }}><strong>Usage Data:</strong> Information about how you interact with the application, including pages visited and features used.</p>
                    <p style={{ marginTop: '8px' }}><strong>Technical Data:</strong> IP address, browser type, and device information for security and debugging purposes.</p>
                </Section>

                <Section title="3. How We Use Your Information">
                    <ul style={{ paddingLeft: '20px', margin: 0 }}>
                        <li>To provide portfolio tracking, trading, and staking services</li>
                        <li>To send price alerts via Telegram (if configured)</li>
                        <li>To generate AI-powered market analysis (if enabled)</li>
                        <li>To generate tax reports for your cryptocurrency transactions</li>
                        <li>To improve and optimize our application</li>
                        <li>To respond to your support requests</li>
                    </ul>
                </Section>

                <Section title="4. Data Storage and Security">
                    <p>
                        We implement industry-standard security measures to protect your data. API credentials
                        are encrypted using AES-256 encryption. We do not store your Binance.US login credentials,
                        only API keys with limited permissions. All data is stored on secure servers.
                    </p>
                </Section>

                <Section title="5. Third-Party Services">
                    <p>We integrate with the following third-party services:</p>
                    <ul style={{ paddingLeft: '20px', marginTop: '8px' }}>
                        <li><strong>Binance.US:</strong> For portfolio data, trading, and staking</li>
                        <li><strong>Telegram:</strong> For sending price alerts (optional)</li>
                        <li><strong>AI Providers (OpenAI, etc.):</strong> For market analysis (optional)</li>
                    </ul>
                    <p style={{ marginTop: '12px' }}>
                        Each of these services has their own privacy policies that govern how they handle your data.
                    </p>
                </Section>

                <Section title="6. Data Retention">
                    <p>
                        We retain your account data as long as your account remains active. You may request
                        deletion of your account and associated data at any time by contacting support.
                    </p>
                </Section>

                <Section title="7. Your Rights">
                    <p>You have the right to:</p>
                    <ul style={{ paddingLeft: '20px', marginTop: '8px' }}>
                        <li>Access your personal data</li>
                        <li>Request correction of inaccurate data</li>
                        <li>Request deletion of your data</li>
                        <li>Revoke API key access at any time via Binance.US</li>
                    </ul>
                </Section>

                <Section title="8. No Custody of Assets">
                    <p>
                        <strong>Important:</strong> Crypto Alert App is a non-custodial application. We never
                        have access to your cryptocurrency assets. All trading and staking operations are
                        executed directly through your Binance.US account via their API. You maintain full
                        custody and control of your assets at all times.
                    </p>
                </Section>

                <Section title="9. Changes to This Policy">
                    <p>
                        We may update this Privacy Policy from time to time. We will notify you of any changes
                        by updating the "Last Updated" date at the top of this page.
                    </p>
                </Section>

                <Section title="10. Contact Us">
                    <p>
                        If you have questions about this Privacy Policy, please contact us at{' '}
                        <Link to="/support" style={{ color: '#4da6ff' }}>our Support page</Link>.
                    </p>
                </Section>
            </div>
        </div>
    );
}
