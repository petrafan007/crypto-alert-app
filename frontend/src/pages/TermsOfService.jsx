import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';

export default function TermsOfService({ isLightMode }) {
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
                <h1 style={{ color: textColor, marginBottom: '8px' }}>Terms of Service</h1>
                <p style={{ color: textColor, opacity: 0.7, marginBottom: '32px' }}>
                    Last Updated: January 19, 2026
                </p>

                <Section title="1. Acceptance of Terms">
                    <p>
                        By accessing or using Crypto Alert App ("the Service"), you agree to be bound by these
                        Terms of Service. If you do not agree to these terms, do not use the Service.
                    </p>
                </Section>

                <Section title="2. Description of Service">
                    <p>
                        Crypto Alert App is a non-custodial cryptocurrency portfolio management tool that
                        integrates with Binance.US via API. The Service provides portfolio tracking, trading
                        execution, staking management, price alerts, AI-powered analysis, and tax reporting
                        features.
                    </p>
                </Section>

                <Section title="3. User Responsibilities">
                    <p>You are solely responsible for:</p>
                    <ul style={{ paddingLeft: '20px', marginTop: '8px' }}>
                        <li>Maintaining the confidentiality of your account credentials</li>
                        <li>All activities that occur under your account</li>
                        <li>Ensuring your API keys have appropriate permissions</li>
                        <li>Complying with Binance.US terms of service</li>
                        <li>Reporting all cryptocurrency transactions to relevant tax authorities</li>
                        <li>Making informed trading and investment decisions</li>
                    </ul>
                </Section>

                <Section title="4. Non-Custodial Nature">
                    <p>
                        <strong>The Service is entirely non-custodial.</strong> We never hold, control, or have
                        access to your cryptocurrency assets. All transactions are executed via the Binance.US
                        API using credentials you provide. You maintain full custody of your assets at all times.
                    </p>
                </Section>

                <Section title="5. No Financial Advice">
                    <p>
                        <strong>The Service does not provide financial, investment, tax, or legal advice.</strong>{' '}
                        All information, including AI-generated analysis, is for informational purposes only.
                        You should consult qualified professionals before making any financial decisions.
                        Past performance is not indicative of future results.
                    </p>
                </Section>

                <Section title="6. Disclaimer of Warranties">
                    <p>
                        THE SERVICE IS PROVIDED "AS IS" AND "AS AVAILABLE" WITHOUT WARRANTIES OF ANY KIND,
                        EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO IMPLIED WARRANTIES OF
                        MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT.
                    </p>
                    <p style={{ marginTop: '12px' }}>
                        We do not warrant that the Service will be uninterrupted, error-free, or secure.
                        We do not guarantee the accuracy of any data, prices, or analysis provided.
                    </p>
                </Section>

                <Section title="7. Limitation of Liability">
                    <p>
                        <strong>TO THE MAXIMUM EXTENT PERMITTED BY LAW, IN NO EVENT SHALL CRYPTO ALERT APP,
                            ITS OWNERS, OPERATORS, AFFILIATES, OR EMPLOYEES BE LIABLE FOR ANY:</strong>
                    </p>
                    <ul style={{ paddingLeft: '20px', marginTop: '8px' }}>
                        <li>Direct, indirect, incidental, special, consequential, or punitive damages</li>
                        <li>Loss of profits, revenue, data, or goodwill</li>
                        <li>Trading losses or missed opportunities</li>
                        <li>Losses resulting from unauthorized access to your account</li>
                        <li>Losses resulting from API errors or Binance.US outages</li>
                        <li>Losses resulting from reliance on AI-generated analysis</li>
                        <li>Tax penalties or interest resulting from incorrect reporting</li>
                    </ul>
                    <p style={{ marginTop: '12px' }}>
                        This limitation applies regardless of the legal theory under which damages are sought
                        and even if we have been advised of the possibility of such damages.
                    </p>
                </Section>

                <Section title="8. Indemnification">
                    <p>
                        You agree to indemnify, defend, and hold harmless Crypto Alert App and its owners,
                        operators, affiliates, and employees from any claims, damages, losses, or expenses
                        (including reasonable attorneys' fees) arising from your use of the Service or
                        violation of these Terms.
                    </p>
                </Section>

                <Section title="9. Risk Acknowledgment">
                    <p>
                        <strong>CRYPTOCURRENCY TRADING INVOLVES SUBSTANTIAL RISK OF LOSS.</strong> By using
                        this Service, you acknowledge that:
                    </p>
                    <ul style={{ paddingLeft: '20px', marginTop: '8px' }}>
                        <li>Cryptocurrency markets are highly volatile</li>
                        <li>You may lose some or all of your invested capital</li>
                        <li>You are solely responsible for your trading decisions</li>
                        <li>Historical performance does not guarantee future results</li>
                        <li>AI analysis may be inaccurate or outdated</li>
                    </ul>
                </Section>

                <Section title="10. Termination">
                    <p>
                        We reserve the right to suspend or terminate your access to the Service at any time,
                        for any reason, without notice. You may terminate your account at any time by
                        deleting your account or contacting support.
                    </p>
                </Section>

                <Section title="11. Governing Law">
                    <p>
                        These Terms shall be governed by and construed in accordance with the laws of the
                        United States. Any disputes arising from these Terms or your use of the Service
                        shall be resolved through binding arbitration.
                    </p>
                </Section>

                <Section title="12. Changes to Terms">
                    <p>
                        We may modify these Terms at any time. Continued use of the Service after changes
                        are posted constitutes acceptance of the modified Terms.
                    </p>
                </Section>

                <Section title="13. Contact">
                    <p>
                        For questions about these Terms, please contact us at{' '}
                        <Link to="/support" style={{ color: '#4da6ff' }}>our Support page</Link>.
                    </p>
                </Section>
            </div>
        </div>
    );
}
