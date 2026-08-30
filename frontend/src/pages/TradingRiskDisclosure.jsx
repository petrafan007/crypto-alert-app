import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';

export const TRADING_RISK_CONTENT = {
    title: 'Trading Risk Disclosures',
    lastUpdated: 'August 30, 2026',
    sections: [
        {
            title: '1. General Investment and Trading Risks',
            content: 'Trading and investing in cryptocurrencies, digital assets, equities, ETFs, and options involve substantial risk of loss and are not suitable for every investor. The valuation of digital assets and equities can fluctuate significantly, potentially resulting in the loss of your entire invested principal within a short period.'
        },
        {
            title: '2. Cryptocurrency and Digital Asset Volatility',
            content: 'Cryptocurrency markets operate 24 hours a day, 7 days a week, and are subject to extreme volatility driven by market sentiment, regulatory actions, technical protocol exploits, network congestion, and macroeconomic events. Unlike traditional equity exchanges, cryptocurrency markets typically do not have circuit breakers or mandatory trading halts.'
        },
        {
            title: '3. Options and Derivatives Risk',
            content: 'Trading equity and index options involves complex risks and may result in rapid and total loss of capital. Derivative contracts are subject to time decay (theta decay), sharp changes in implied volatility, and leverage risks that can magnify losses beyond anticipated ranges.'
        },
        {
            title: '4. Execution, Liquidity, and Slippage Risks',
            content: 'Market orders or automated stop-loss and limit orders are subject to market slippage, exchange matching engine latency, and spread widening during periods of high volatility or thin liquidity. Executed prices may diverge materially from the last quoted market price or expected trigger price.'
        },
        {
            title: '5. Exchange and API Third-Party Dependencies',
            content: 'Crypto & Securities Dashboard is a non-custodial software interface that interacts with third-party exchanges (including Binance.US and Webull) via customer-provided API credentials. The application is not responsible for exchange downtime, API rate limiting, network outages, execution failures, or exchange-side account restrictions.'
        },
        {
            title: '6. AI-Assisted Market Analysis Disclaimer',
            content: 'Automated signals, sentiment scores, AI Copilot responses, and technical indicators are generated for informational and educational purposes only. They do not constitute financial, investment, legal, or tax advice. You are solely responsible for conducting your own independent due diligence before placing any trade.'
        },
        {
            title: '7. Non-Custodial Architecture & User Responsibility',
            content: 'The Service does not hold, custody, or manage user funds. You maintain sole custody of your assets and private keys across linked exchange accounts. You are solely responsible for securing your account credentials, safeguarding API keys, and managing trading risk.'
        }
    ]
};

export default function TradingRiskDisclosure({ isLightMode }) {
    useEffect(() => {
        window.scrollTo(0, 0);
    }, []);

    const textColor = isLightMode ? '#212529' : '#e0e0e0';
    const bgColor = isLightMode ? '#f8f9fa' : '#16213e';
    const cardBg = isLightMode ? '#ffffff' : '#1a1a2e';
    const borderColor = isLightMode ? '#dee2e6' : '#2d3748';

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
                <h1 style={{ color: textColor, marginBottom: '8px' }}>{TRADING_RISK_CONTENT.title}</h1>
                <p style={{ color: textColor, opacity: 0.7, marginBottom: '32px' }}>
                    Last Updated: {TRADING_RISK_CONTENT.lastUpdated}
                </p>

                {TRADING_RISK_CONTENT.sections.map((section, idx) => (
                    <div key={idx} style={{ marginBottom: '28px' }}>
                        <h2 style={{ color: textColor, fontSize: '1.3rem', marginBottom: '12px' }}>{section.title}</h2>
                        <div style={{ color: textColor, lineHeight: '1.7', fontSize: '15px' }}>
                            <p>{section.content}</p>
                        </div>
                    </div>
                ))}

                <div style={{ marginTop: '32px', borderTop: `1px solid ${borderColor}`, paddingTop: '20px' }}>
                    <p style={{ color: textColor, fontSize: '14px' }}>
                        For additional questions or inquiries regarding these disclosures, please visit{' '}
                        <Link to="/support" style={{ color: '#4da6ff' }}>our Support page</Link>.
                    </p>
                </div>
            </div>
        </div>
    );
}
