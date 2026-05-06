import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';

export default function AcceptableUse({ isLightMode }) {
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
                <h1 style={{ color: textColor, marginBottom: '8px' }}>Acceptable Use Policy</h1>
                <p style={{ color: textColor, opacity: 0.7, marginBottom: '32px' }}>
                    Last Updated: January 19, 2026
                </p>

                <Section title="1. Purpose">
                    <p>
                        This Acceptable Use Policy outlines the rules and guidelines for using Crypto Alert App.
                        By using our Service, you agree to comply with this policy.
                    </p>
                </Section>

                <Section title="2. Permitted Uses">
                    <p>You may use Crypto Alert App to:</p>
                    <ul style={{ paddingLeft: '20px', marginTop: '8px' }}>
                        <li>Track your personal cryptocurrency portfolio</li>
                        <li>Execute trades on your own Binance.US account</li>
                        <li>Manage staking positions for your own assets</li>
                        <li>Receive price alerts for cryptocurrencies you own or monitor</li>
                        <li>Generate tax reports for your personal cryptocurrency transactions</li>
                        <li>Access AI-powered market analysis for informational purposes</li>
                    </ul>
                </Section>

                <Section title="3. Prohibited Activities">
                    <p>You agree NOT to use the Service to:</p>
                    <ul style={{ paddingLeft: '20px', marginTop: '8px' }}>
                        <li>Manage accounts or assets belonging to other individuals without authorization</li>
                        <li>Engage in market manipulation, pump-and-dump schemes, or other fraudulent activities</li>
                        <li>Violate any applicable laws, regulations, or Binance.US terms of service</li>
                        <li>Attempt to gain unauthorized access to other users' accounts or data</li>
                        <li>Use automated scripts or bots to abuse the Service or APIs</li>
                        <li>Reverse engineer, decompile, or attempt to extract source code</li>
                        <li>Circumvent security measures or rate limits</li>
                        <li>Transmit malware, viruses, or malicious code</li>
                        <li>Use the Service for money laundering or financing illegal activities</li>
                        <li>Resell or redistribute the Service without authorization</li>
                    </ul>
                </Section>

                <Section title="4. API Usage">
                    <p>When using API integrations, you must:</p>
                    <ul style={{ paddingLeft: '20px', marginTop: '8px' }}>
                        <li>Only use API keys that you have personally generated</li>
                        <li>Never enable withdrawal permissions on API keys used with this Service</li>
                        <li>Respect Binance.US API rate limits</li>
                        <li>Immediately revoke API access if you suspect unauthorized use</li>
                    </ul>
                </Section>

                <Section title="5. Account Security">
                    <p>You are responsible for:</p>
                    <ul style={{ paddingLeft: '20px', marginTop: '8px' }}>
                        <li>Using a strong, unique password for your account</li>
                        <li>Enabling two-factor authentication when available</li>
                        <li>Not sharing your account credentials with anyone</li>
                        <li>Reporting any suspected unauthorized access immediately</li>
                    </ul>
                </Section>

                <Section title="6. Content Guidelines">
                    <p>
                        When using support or communication features, you agree not to send content that is:
                    </p>
                    <ul style={{ paddingLeft: '20px', marginTop: '8px' }}>
                        <li>Abusive, threatening, or harassing</li>
                        <li>Defamatory or invasive of privacy</li>
                        <li>Obscene or inappropriate</li>
                        <li>Spam or unsolicited advertising</li>
                    </ul>
                </Section>

                <Section title="7. Compliance with Laws">
                    <p>
                        You are solely responsible for ensuring that your use of the Service complies with
                        all applicable laws and regulations in your jurisdiction, including but not limited to:
                    </p>
                    <ul style={{ paddingLeft: '20px', marginTop: '8px' }}>
                        <li>Securities and financial regulations</li>
                        <li>Tax reporting requirements</li>
                        <li>Anti-money laundering (AML) laws</li>
                        <li>Know Your Customer (KYC) regulations</li>
                    </ul>
                </Section>

                <Section title="8. Enforcement">
                    <p>
                        We reserve the right to investigate and take appropriate action against anyone who
                        violates this policy, including:
                    </p>
                    <ul style={{ paddingLeft: '20px', marginTop: '8px' }}>
                        <li>Warning the user</li>
                        <li>Suspending or terminating the user's account</li>
                        <li>Reporting violations to law enforcement</li>
                        <li>Taking legal action</li>
                    </ul>
                </Section>

                <Section title="9. Reporting Violations">
                    <p>
                        If you become aware of any violations of this policy, please report them to us via{' '}
                        <Link to="/support" style={{ color: '#4da6ff' }}>our Support page</Link>.
                    </p>
                </Section>

                <Section title="10. Changes to This Policy">
                    <p>
                        We may update this Acceptable Use Policy at any time. Continued use of the Service
                        after changes are posted constitutes acceptance of the updated policy.
                    </p>
                </Section>
            </div>
        </div>
    );
}
