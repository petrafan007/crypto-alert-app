import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
    FaKey, FaRobot, FaBell, FaShieldAlt, FaChartLine,
    FaCoins, FaFileInvoiceDollar, FaHome, FaCog,
    FaLock, FaQuestionCircle, FaExclamationTriangle,
    FaThLarge, FaListAlt, FaBolt, FaLayerGroup, FaComments,
    FaListOl
} from 'react-icons/fa';

// Table of Contents structure: grouped categories -> section anchors.
// Keep this in sync with the <Section id="..."> anchors rendered below.
const TOC_GROUPS = [
    {
        title: 'Getting Started',
        items: [
            { id: 'getting-started', label: 'Getting Started' },
            { id: 'access-requirements', label: 'Access Requirements' },
            { id: 'security', label: 'Security & Non-Custodial Architecture' },
        ]
    },
    {
        title: 'Account Setup',
        items: [
            { id: 'api-key-setup', label: 'Binance.US API Key Setup' },
            { id: 'webull-openapi-setup', label: 'Webull OpenAPI Setup & Import' },
            { id: 'ai-provider-setup', label: 'AI Provider Setup' },
            { id: 'telegram-alerts', label: 'Telegram Alerts' },
            { id: 'two-factor-auth', label: 'Two-Factor Authentication (2FA)' },
        ]
    },
    {
        title: 'Dashboard',
        items: [
            { id: 'dashboard-overview', label: 'Dashboard Widgets' },
            { id: 'customize-layout', label: 'Customizing Your Layout' },
        ]
    },
    {
        title: 'Portfolio & Watchlist',
        items: [
            { id: 'portfolio-table', label: 'Portfolio Table' },
            { id: 'watchlist', label: 'Watchlist' },
        ]
    },
    {
        title: 'Automated Protection',
        items: [
            { id: 'auto-buy-sell', label: 'Auto-Buy & Auto-Sell Triggers' },
        ]
    },
    {
        title: 'Trading & Staking',
        items: [
            { id: 'trading-center', label: 'Trading Center' },
            { id: 'staking', label: 'Staking' },
        ]
    },
    {
        title: 'AI Features',
        items: [
            { id: 'ai-analysis', label: 'AI Analysis Page' },
            { id: 'ai-copilot', label: 'AI Copilot Sidebar' },
        ]
    },
    {
        title: 'Reports & Settings',
        items: [
            { id: 'tax-report', label: 'Tax Report' },
            { id: 'other-settings', label: 'Other Settings' },
        ]
    },
    {
        title: 'Help',
        items: [
            { id: 'troubleshooting', label: 'Troubleshooting' },
        ]
    }
];

export default function Help({ isLightMode }) {
    const textColor = isLightMode ? '#212529' : '#e0e0e0';
    const bgColor = isLightMode ? '#f8f9fa' : '#16213e';
    const cardBg = isLightMode ? '#ffffff' : '#1a1a2e';
    const borderColor = isLightMode ? '#dee2e6' : '#2d3748';
    const accentColor = '#4da6ff';
    const [activeId, setActiveId] = useState(TOC_GROUPS[0].items[0].id);

    // Highlight the TOC entry matching whichever section is currently in view.
    useEffect(() => {
        const ids = TOC_GROUPS.flatMap(g => g.items.map(i => i.id));
        const elements = ids.map(id => document.getElementById(id)).filter(Boolean);
        if (elements.length === 0) return undefined;

        const observer = new IntersectionObserver((entries) => {
            const visible = entries.filter(e => e.isIntersecting);
            if (visible.length > 0) {
                visible.sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
                setActiveId(visible[0].target.id);
            }
        }, { rootMargin: '-100px 0px -70% 0px', threshold: 0 });

        elements.forEach(el => observer.observe(el));
        return () => observer.disconnect();
    }, []);

    const Section = ({ id, icon, title, children }) => (
        <div id={id} style={{
            backgroundColor: cardBg,
            borderRadius: '12px',
            padding: '24px',
            marginBottom: '20px',
            border: `1px solid ${borderColor}`,
            scrollMarginTop: '16px'
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
            <a href="#toc" style={{ display: 'inline-block', marginTop: '16px', fontSize: '12px', color: accentColor, opacity: 0.8, textDecoration: 'none' }}>
                ↑ Back to Table of Contents
            </a>
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

    const Example = ({ children }) => (
        <div style={{
            backgroundColor: isLightMode ? '#eafaf1' : '#0f3324',
            padding: '12px 16px',
            borderRadius: '8px',
            marginTop: '12px',
            fontSize: '14px',
            borderLeft: '4px solid #2ecc71'
        }}>
            <strong style={{ color: '#2ecc71' }}>🧭 Example:</strong> {children}
        </div>
    );

    const SubHeading = ({ children }) => (
        <h3 style={{ color: textColor, marginTop: '20px', marginBottom: '12px' }}>{children}</h3>
    );

    return (
        <div style={{
            padding: '20px',
            maxWidth: '980px',
            margin: '0 auto',
            backgroundColor: bgColor,
            minHeight: '100vh'
        }}>
            <h1 style={{ color: textColor, marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '12px' }}>
                <FaQuestionCircle style={{ color: accentColor }} /> Help & Documentation
            </h1>

            {/* Table of Contents */}
            <div id="toc" style={{
                backgroundColor: cardBg,
                borderRadius: '12px',
                padding: '24px',
                marginBottom: '20px',
                border: `1px solid ${borderColor}`,
                scrollMarginTop: '16px'
            }}>
                <h2 style={{ color: accentColor, marginBottom: '16px', fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <FaListOl /> Table of Contents
                </h2>
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                    gap: '20px'
                }}>
                    {TOC_GROUPS.map(group => (
                        <div key={group.title}>
                            <div style={{ color: textColor, opacity: 0.7, fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px', fontWeight: 'bold' }}>
                                {group.title}
                            </div>
                            <ul style={{ listStyle: 'none', padding: 0, margin: 0, lineHeight: '1.9' }}>
                                {group.items.map(item => (
                                    <li key={item.id}>
                                        <a
                                            href={`#${item.id}`}
                                            style={{
                                                color: activeId === item.id ? accentColor : textColor,
                                                fontWeight: activeId === item.id ? 'bold' : 'normal',
                                                textDecoration: 'none',
                                                fontSize: '14px'
                                            }}
                                        >
                                            {activeId === item.id ? '▸ ' : ''}{item.label}
                                        </a>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    ))}
                </div>
            </div>

            {/* Getting Started */}
            <Section id="getting-started" icon={<FaHome />} title="Getting Started">
                <p style={{ marginBottom: '16px' }}>
                    Welcome to Crypto &amp; Securities Dashboard! This is a non-custodial crypto and securities portfolio
                    management and trading platform for Binance.US and Webull. It covers real-time portfolio tracking,
                    exchange-aware trading, staking, automated Binance.US crash/surge protection, and AI-powered market
                    analysis — all self-hosted, so your credentials and data never leave your own server.
                </p>

                <SubHeading>Quick Start Steps:</SubHeading>
                <ol style={{ paddingLeft: '20px', lineHeight: '1.8' }}>
                    <li><strong>Set up your Binance.US API key</strong> in Settings for crypto portfolio sync, trading, staking, and app automation</li>
                    <li><strong>Optionally connect Webull OpenAPI</strong> in Settings, choose the accounts to include, preview them, and import their read-only portfolio snapshots</li>
                    <li><strong>Configure alerts</strong> via Telegram and/or browser notifications for price and trade updates</li>
                    <li><strong>Enable AI integration</strong> for sentiment analysis and the AI Copilot (optional)</li>
                    <li><strong>Explore your Dashboard</strong> — add coins to your Portfolio and Watchlist, then customize the widget layout</li>
                    <li><strong>Set up alerts and triggers</strong> — price alerts, Auto-Buy/Auto-Sell volatility triggers, per your risk tolerance</li>
                </ol>

                <Tip>
                    New accounts use a resumable, theme-aware setup flow for security, at least one required exchange connection, optional AI/search providers, Telegram testing, and a final review before Dashboard access.
                    You can always come back here for a full reference.
                </Tip>
            </Section>

            {/* Access Requirements */}
            <Section id="access-requirements" icon={<FaLock />} title="Access Requirements">
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
                            <td style={{ padding: '12px' }}>Binance.US Trading, Staking, Auto-Buy/Auto-Sell</td>
                            <td style={{ padding: '12px' }}>Valid Binance.US API key with the needed reading/trading permission</td>
                        </tr>
                        <tr style={{ borderBottom: `1px solid ${borderColor}` }}>
                            <td style={{ padding: '12px' }}>Webull Portfolio, Webull Trading, Webull Orders</td>
                            <td style={{ padding: '12px' }}>Verified Webull OpenAPI connection, enabled account, and imported portfolio snapshot</td>
                        </tr>
                        <tr style={{ borderBottom: `1px solid ${borderColor}` }}>
                            <td style={{ padding: '12px' }}>AI Analysis, AI Copilot Sidebar</td>
                            <td style={{ padding: '12px' }}>Configured AI provider; exchange data is limited to your connected/imported accounts</td>
                        </tr>
                    </tbody>
                </table>

                <Warning>
                    If you see a modal saying "API Key Required" or "Trading Permission Required",
                    follow the instructions to configure your API key in Settings.
                </Warning>
            </Section>

            {/* Security */}
            <Section id="security" icon={<FaShieldAlt />} title="Security & Non-Custodial Architecture">
                <p style={{ marginBottom: '16px' }}>
                    This app never takes custody of your funds — Binance.US and Webull orders execute directly with
                    the selected account at the owning provider.
                </p>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.8' }}>
                    <li><strong>Local AES-256 Encryption at Rest</strong> — your Binance.US API key/secret, Webull App Key/App Secret and access token, and AI provider keys are encrypted before being stored in the database.</li>
                    <li><strong>Self-Hosted Privacy</strong> — since you run this app on your own server, your keys, trades, and portfolio data stay completely under your control.</li>
                    <li><strong>Credential Encryption Key rotation</strong> (admin account only) — available in Settings for rotating the underlying encryption key.</li>
                    <li><strong>App-level 2FA</strong> — an additional authentication layer for Binance.US and Webull trade execution, separate from each provider's own authentication (see <a href="#two-factor-auth" style={{ color: accentColor }}>Two-Factor Authentication</a>).</li>
                </ul>
                <Warning>
                    Never enable withdrawal permissions on the API key you give this app. Only "Enable Reading" and
                    "Enable Spot Trading" are required.
                </Warning>
            </Section>

            {/* Binance API Key Setup */}
            <Section id="api-key-setup" icon={<FaKey />} title="Binance.US API Key Setup">
                <p style={{ marginBottom: '16px' }}>
                    To use portfolio sync, trading, staking, and Auto-Buy/Auto-Sell, you need to connect your
                    Binance.US account. A single API Key and Secret is used for all of these features.
                </p>

                <SubHeading>Steps to create an API key:</SubHeading>
                <ol style={{ paddingLeft: '20px', lineHeight: '1.8' }}>
                    <li>Log into your <a href="https://www.binance.us" target="_blank" rel="noopener noreferrer" style={{ color: accentColor }}>Binance.US</a> account</li>
                    <li>Navigate to <strong>Profile → API Management</strong></li>
                    <li>Create a new API key with a label (e.g., "Crypto &amp; Securities Dashboard")</li>
                    <li>Enable these permissions:
                        <ul style={{ marginTop: '8px', paddingLeft: '20px' }}>
                            <li><strong>Enable Reading</strong> - Required for portfolio sync and price tracking</li>
                            <li><strong>Enable Spot Trading</strong> - Required for Trading, Staking, and Auto-Buy/Auto-Sell</li>
                        </ul>
                    </li>
                    <li>Copy the API Key and Secret</li>
                    <li>Paste them into Settings and click "Test Binance Connection"</li>
                </ol>

                <Warning>
                    Never share your API Secret. For security, do NOT enable withdrawal permissions.
                </Warning>
            </Section>

            {/* Webull OpenAPI Setup */}
            <Section id="webull-openapi-setup" icon={<FaChartLine />} title="Webull OpenAPI Setup & Import">
                <p style={{ marginBottom: '16px' }}>
                    Connect Webull only through your personal Webull Trading API application in <Link to="/settings" style={{ color: accentColor }}>Settings</Link>.
                    The connection is account-scoped: it never substitutes Binance.US data, exposes a raw account number in the browser, or enables every discovered Webull account automatically.
                </p>

                <SubHeading>Before you begin</SubHeading>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.8' }}>
                    <li>Have the <strong>Webull App Key</strong> and <strong>App Secret</strong> issued for the environment you intend to use.</li>
                    <li>Choose <strong>Production</strong> only for your live Webull account or <strong>Sandbox</strong> only for a Webull test account. Credentials cannot be used across environments.</li>
                    <li>Enable app-level trading 2FA before submitting or cancelling live Webull orders if you want the app's six-digit confirmation safeguard.</li>
                </ul>

                <SubHeading>Connect and verify Webull</SubHeading>
                <ol style={{ paddingLeft: '20px', lineHeight: '1.8' }}>
                    <li>Open <Link to="/settings" style={{ color: accentColor }}>Settings</Link> and find <strong>Webull OpenAPI Connection</strong>.</li>
                    <li>Select the environment that issued the credentials, enter the App Key and App Secret, then save Settings. Both are encrypted at rest and are not sent back to the browser.</li>
                    <li>Select <strong>Connect and Verify in Webull</strong>. If Webull immediately reports an active token, continue to account selection below.</li>
                    <li>If verification is pending, open the newest notification in the Webull app at <strong>Menu → Messages → OpenAPI Notifications</strong>, select <strong>Check Now</strong>, and approve the SMS code.</li>
                    <li>Return to Settings and select <strong>Check Webull Verification</strong> within five minutes. A successful status is shown as active for the selected environment.</li>
                </ol>

                <Tip>
                    Verification confirms API access only. It does not import balances or positions and does not place an order.
                    If you change the credentials or environment, the stored Webull token is cleared and must be verified again.
                </Tip>

                <SubHeading>Choose accounts and import your portfolio</SubHeading>
                <ol style={{ paddingLeft: '20px', lineHeight: '1.8' }}>
                    <li>Under <strong>Connected Webull Accounts</strong>, use <strong>Refresh Accounts</strong> if needed. Account names, masked IDs, and types are displayed without exposing the full account number.</li>
                    <li>Check only the accounts you want available in Webull Trading. Unchecked accounts are excluded from Webull navigation and account-scoped actions.</li>
                    <li>Select <strong>Load Read-Only Portfolio Preview</strong> to inspect the enabled accounts' balances and open positions. This preview does not save or merge anything.</li>
                    <li>Select <strong>Import into Unified Portfolio</strong> to persist the selected accounts' current snapshots. The Dashboard then includes them as separate Webull source/account rows; same-symbol holdings are never merged with Binance.US.</li>
                </ol>

                <SubHeading>Navigate and set your default account</SubHeading>
                <p style={{ marginBottom: '16px' }}>
                    Choose <strong>Trading → Webull</strong> to open the dedicated Webull workspace. Use the <strong>Webull Account</strong>
                    selector above the chart to switch only among enabled accounts. Select the outlined star immediately to the left of the selector to make the current account your default; a filled gold star identifies the saved default account. That account opens automatically when you choose Webull Trading without a direct asset link. A Portfolio, Watchlist, or stock-mover action keeps the asset's owning account and instrument type instead of falling back to Binance.US or a different Webull account.
                </p>

                <SubHeading>Place and manage Webull orders safely</SubHeading>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.8' }}>
                    <li>Webull Trading supports the enabled account's equities/ETFs, crypto, imported option contracts, futures, and Event Contracts. The ticket shows the selected account, available position, buying power, and current quote before confirmation.</li>
                    <li>For an equity or ETF, choose <strong>Only Regular Hours</strong>, <strong>Including Extended Hours</strong>, or <strong>Overnight Hours Only</strong>. Fractional stock/ETF orders are Market-only during Regular Hours, must be more than zero and no more than one share, and have a $5 minimum. Extended and Overnight sessions require whole shares.</li>
                    <li>For an Event Contract, choose a live Webull category, optionally filter by <strong>Duration / Frequency</strong>, and search contracts currently open for a new position using words from the title, condition, event, series, or symbol. Frequency choices load directly from Webull's lightweight Series catalog, and a search loads matching Series without waiting for every market in the category. <strong>15 minutes</strong> is derived only for Webull series that explicitly identify that cadence, and <strong>Intraday</strong> combines those series with Webull's Hourly frequency. Common forms such as <strong>Bitcoin fifteen minutes</strong>, <strong>BTC 15 min</strong>, and <strong>bitcoin 15m</strong> are treated consistently. Future and non-tradable contracts are excluded. The selected-contract brief explains what YES and NO mean, identifies fixed-target versus reference-price direction contracts, expresses allowed order prices in cents, and shows the contract cutoff and $1/$0 settlement. Catalog warnings remain with discovery status instead of replacing live bid/ask information.</li>
                    <li>Current Event Contract positions provide an Open Position action with a live countdown, Yes/No quotes, position value and P&amp;L, provider price history, contract timeline, and Buy Yes, Buy No, or Close Position controls. A closing-only contract can be sold only for the exact Yes/No position and quantity currently held; a non-tradable contract remains viewable but cannot be traded.</li>
                    <li>Use the pre-trade review to verify provider, masked account, symbol/contract, side, quantity, price, order type, time in force, and trading session. With app trading 2FA enabled, entering the six-digit code is required before a live order is sent.</li>
                    <li>Use <strong>Open Orders</strong> or the top-level <strong>Orders</strong> page to review Webull orders. Cancelling a Webull order uses the app's theme-aware confirmation modal, identifies the exact provider/account/order, and requires the six-digit code when 2FA is enabled.</li>
                    <li>Webull tables, charts, selectors, and confirmation/cancellation dialogs translate provider codes into readable labels such as <strong>Stop Loss Limit</strong> and <strong>Limit on Open (LOO)</strong>. The unchanged API code is still used behind the scenes.</li>
                    <li><strong>Test Mode is fully isolated:</strong> holdings, Open Orders, Order History, Trade Chart markers, and Combo Orders show simulated paper data only. Turning Test Mode off clears those paper records from the workspace and restores only live Webull records. Conditional and auction paper orders remain Working until their trigger or auction can occur. AI Analysis is hidden in Test Mode because simulated orders do not need brokerage signal analysis.</li>
                </ul>

                <Warning>
                    Webull positions, orders, quotes, and buying power remain provider- and account-scoped. A Webull row can never submit a Binance.US order, and Binance.US app Auto-Buy/Auto-Sell triggers do not control Webull holdings.
                </Warning>
            </Section>

            {/* AI Provider Setup */}
            <Section id="ai-provider-setup" icon={<FaRobot />} title="AI Provider Setup">
                <p style={{ marginBottom: '16px' }}>
                    Enable AI-powered sentiment analysis, market analysis, and the AI Copilot by configuring one or
                    more AI providers in Settings.
                </p>

                <SubHeading>Supported Providers:</SubHeading>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px' }}>
                    <li><strong>OpenAI</strong> - GPT-4o, o1, o3-mini and other reasoning models</li>
                    <li><strong>Google Gemini</strong> - multiple Gemini models with a Low/Medium/High reasoning effort selector</li>
                    <li><strong>Z.AI (Zhipu)</strong> - GLM-4.x and GLM-5 family models, including a free flash tier</li>
                    <li><strong>Perplexity</strong> - Sonar models with built-in web search</li>
                </ul>

                <SubHeading>Primary, Secondary & Tertiary Integrations</SubHeading>
                <p style={{ marginBottom: '16px' }}>
                    Settings lets you configure up to three independent AI provider slots. If the Primary provider's
                    call fails or is rate-limited, the app automatically retries with the Secondary, then the
                    Tertiary provider, so a single outage doesn't stop your sentiment analysis or Copilot chats.
                </p>

                <SubHeading>Live Web-Grounded Analysis</SubHeading>
                <p style={{ marginBottom: '16px' }}>
                    Sentiment and market analysis are grounded with real-time web search (Brave Search, with an
                    automatic DuckDuckGo fallback) so recommendations reflect current news, not just historical price data.
                </p>

                <SubHeading>Custom AI Prompts</SubHeading>
                <p style={{ marginBottom: '16px' }}>
                    Settings exposes editable prompt templates for each AI workflow — Coin Analysis, Market Analysis,
                    Portfolio Review, Portfolio Sentiment, Watchlist Sentiment, and the AI Copilot — so you can tune
                    tone, risk appetite, or focus areas to your preference.
                </p>

                <Tip>
                    Sentiment analysis runs automatically on a schedule (configurable per portfolio/watchlist), or you
                    can trigger it instantly with "Run Sentiment Analysis Now" in Settings, or per-coin with the 🔄
                    refresh icon in the Portfolio/Watchlist tables.
                </Tip>
            </Section>

            {/* Telegram Alerts */}
            <Section id="telegram-alerts" icon={<FaBell />} title="Telegram Alerts">
                <p style={{ marginBottom: '16px' }}>
                    Get instant price alerts, trade confirmations, and Auto-Buy/Auto-Sell execution notifications via Telegram.
                </p>

                <ol style={{ paddingLeft: '20px', lineHeight: '1.8' }}>
                    <li>Create a bot with <a href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer" style={{ color: accentColor }}>@BotFather</a> on Telegram</li>
                    <li>Copy your Bot Token</li>
                    <li>Message your bot to start a conversation</li>
                    <li>Get your Chat ID from <a href="https://t.me/userinfobot" target="_blank" rel="noopener noreferrer" style={{ color: accentColor }}>@userinfobot</a></li>
                    <li>Enter both in Settings and test the connection</li>
                </ol>

                <Tip>
                    Browser toast notifications (top-right pop-ups) can be toggled independently in Settings and work
                    without any Telegram setup.
                </Tip>
            </Section>

            {/* Two-Factor Authentication */}
            <Section id="two-factor-auth" icon={<FaShieldAlt />} title="Two-Factor Authentication (2FA)">
                <p style={{ marginBottom: '16px' }}>
                    Add an extra layer of security to account login and trade execution with TOTP-based 2FA (compatible with Google
                    Authenticator, Bitwarden, Authy, etc.). This is <strong>separate</strong> from your Binance.US and Webull
                    account authentication — it protects this app itself, so anyone with access to your browser session
                    or login credentials still can't log in or place trades without your authenticator code.
                </p>

                <ol style={{ paddingLeft: '20px', lineHeight: '1.8' }}>
                    <li>Enable 2FA in Settings and scan the QR code with an authenticator app</li>
                    <li>Verify by entering the 6-digit code</li>
                    <li>When 2FA is enabled on your profile, you will be prompted for your 6-digit code upon logging in</li>
                    <li>When "Require 2FA for Trading" is enabled, you will also need to confirm Binance.US and live Webull order placement, protected order cancellation, dust conversion, and Cancel Auto-Buy/Auto-Sell Trigger actions with a code</li>
                    <li>Webull simulated paper orders use the paper-order review confirmation without requiring an authenticator code; this exception never applies to live Webull orders</li>
                </ol>

                <Tip>
                    Store your recovery codes securely in case you lose access to your authenticator.
                </Tip>
            </Section>

            {/* Dashboard Overview */}
            <Section id="dashboard-overview" icon={<FaThLarge />} title="Dashboard Widgets">
                <p style={{ marginBottom: '16px' }}>
                    The Dashboard is a customizable grid of widgets giving you an at-a-glance view of your portfolio
                    and the market. Available widgets include:
                </p>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.9' }}>
                    <li><strong>Allocations Donut</strong> — breakdown of your holdings by asset weight, with the total value plus tracked dollar and percentage P&amp;L centered in the donut</li>
                    <li><strong>Portfolio Trend Chart</strong> — net worth history with a ✏️ range selector. Choose which quick range buttons you want displayed: 1H, 4H, 12H, 24H, 2D–7D, 14D, 30D, 60D, 90D, 1Y, 2Y, 3Y, and All-time.</li>
                    <li><strong>Fear & Greed Index</strong> — overall market sentiment gauge</li>
                    <li><strong>CBBI Bull Run Index</strong> — Bull Run Peak Confidence metric</li>
                    <li><strong>Total Portfolio Value</strong> — live USD/USDT valuation card</li>
                    <li><strong>Staking Yield Overview</strong> — quick summary of staking APY and rewards</li>
                    <li><strong>7-Day Performance Tickers</strong> — multi-interval % change per coin</li>
                    <li><strong>Top Gainers & Losers</strong> — 24h momentum across every coin Binance.US lists (not just your holdings). Click any coin in the list to jump straight to its local Trading chart. An editable ✏️ button lets you set 3–50 coins per side, and coins you own are highlighted with a ★ badge</li>
                    <li><strong>Recent Order History</strong> — live feed of your most recent filled trades</li>
                    <li><strong>AI Copilot Market Pulse</strong> — macro sentiment score and catalyst summary</li>
                    <li><strong>Staking Yield & Rewards Tracker</strong> — projected daily/monthly/yearly yield</li>
                    <li><strong>Portfolio Risk & Drawdown Monitor</strong> — ATH drawdown and concentration risk</li>
                    <li><strong>Quick Trade Mini-Terminal</strong> — fast buy/sell launcher from the Dashboard</li>
                    <li><strong>Network Gas & Fee Monitor</strong> — live network fees for BTC, ETH, and SOL</li>
                </ul>
            </Section>

            {/* Customize Layout */}
            <Section id="customize-layout" icon={<FaLayerGroup />} title="Customizing Your Layout">
                <p style={{ marginBottom: '16px' }}>
                    Click <strong>Customize Layout</strong> in the Dashboard header to enter edit mode:
                </p>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.9' }}>
                    <li><strong>Drag (⠿)</strong> to reorder or reposition any widget freely on the grid</li>
                    <li><strong>Resize</strong> using the corner/edge handles to make a widget wider or taller</li>
                    <li><strong>Hide (✕)</strong> any widget you don't want to see</li>
                    <li><strong>+ Add / Restore Panels</strong> — bring back hidden widgets; new panels are placed in the first open grid slot at full default size</li>
                    <li><strong>↩ Undo</strong> — step back through up to 5 recent layout changes</li>
                    <li><strong>💾 Save / ✕ Cancel</strong> — commit your layout changes, or roll back to how it looked before you entered edit mode</li>
                </ul>
                <Tip>
                    Your layout is saved locally to your browser, with a "Reset Default" option available if you want
                    to start over.
                </Tip>
            </Section>

            {/* Portfolio Table */}
            <Section id="portfolio-table" icon={<FaListAlt />} title="Portfolio Table">
                <p style={{ marginBottom: '16px' }}>
                    The Portfolio table lists every coin you hold on Binance.US worth at least $1.00 (or manually
                    unhidden). It can also display imported Webull positions, marked with a bull source icon; hover it to identify Webull. Binance.US rows use the Binance icon. The icon immediately after the source identifies crypto versus traditional assets.
                    Webull rows never expose Binance.US controls for trading, alerts, sentiment, news, staking, notes, or hiding; their actions route only to the selected Webull workspace and account. Each Binance.US row supports a full set of Binance.US actions:
                </p>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.9' }}>
                    <li><strong>Buy / Sell</strong> — trade <em>any coin in the row</em> against USD or USDT (Binance.US's two settlement/quote currencies); selecting "Buy with USDT" means using your USDT balance to purchase that coin, not buying USDT itself</li>
                    <li><strong>Stake 🪙</strong> — jump straight to staking that asset (if supported)</li>
                    <li><strong>Hide 👁️</strong> — manually hide a coin from the table regardless of its value</li>
                    <li><strong>Notes ✏️</strong> — attach a free-text note to any coin</li>
                    <li><strong>Alert Bell 🔔</strong> — set Price Up/Down alert thresholds; auto-saves when you click away (blur) or press Enter</li>
                    <li><strong>Volatility %</strong> — the percentage move used by Auto-Buy/Auto-Sell triggers (see next section)</li>
                    <li><strong>Sentiment badge</strong> — AI recommendation (Strong Buy, Buy, Hold, Consider Selling, Sell) with a 🔄 button for an instant per-coin refresh and a hover tooltip explaining the AI's reasoning</li>
                    <li><strong>Double-click the Sentiment cell</strong> to toggle AI sentiment tracking on or off for that specific coin — useful if you don't want every coin analyzed. Disabled coins show a muted "🚫 Not Tracked" label; double-click again to re-enable</li>
                    <li><strong>News 📰</strong> — hover for the latest cached AI-generated news summary for that coin</li>
                    <li><strong>Sparkline hover</strong> — hover the price to see a 7-day mini price chart</li>
                    <li><strong>Column sorting & customization</strong> — click column headers to sort, or use the gear icon to show/hide/reorder columns</li>
                </ul>
                <Example>
                    Clicking "Sell" → "USDT" on your ETH row opens the Trading Center pre-filtered to the ETH/USDT
                    pair with the Sell side selected — it does not sell USDT, it sells ETH for USDT. Webull orders retain
                    a Webull origin badge in Order History and never open Binance.US trading; Webull cancellation stays scoped to its owning Webull account.
                </Example>
            </Section>

            {/* Watchlist */}
            <Section id="watchlist" icon={<FaCoins />} title="Watchlist">
                <p style={{ marginBottom: '16px' }}>
                    The Watchlist lets you track coins you don't currently own, so you can monitor them for future
                    buy opportunities.
                </p>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.9' }}>
                    <li><strong>Adding a coin</strong> instantly runs a one-time AI sentiment check for it</li>
                    <li><strong>Watchlist sentiment</strong> uses its own 4-tier scale: Avoid, Watch, Consider Buying, Definitely Buy</li>
                    <li><strong>Double-click the Sentiment cell</strong> to disable or re-enable AI sentiment tracking for that coin, same as in the Portfolio table</li>
                    <li><strong>Buy</strong> — purchase the coin against USD or USDT directly from the Watchlist row</li>
                    <li><strong>Delete</strong> — remove a coin you're no longer tracking</li>
                    <li>Watchlist coins also support <strong>Volatility %</strong> and <strong>Auto-Buy triggers</strong>, just like Portfolio coins</li>
                </ul>
            </Section>

            {/* Auto-Buy / Auto-Sell */}
            <Section id="auto-buy-sell" icon={<FaBolt />} title="Auto-Buy & Auto-Sell Triggers">
                <p style={{ marginBottom: '16px' }}>
                    Auto-Buy and Auto-Sell are autonomous, background-monitored triggers that protect against sudden
                    drops or automatically capture sudden surges, without you needing to watch the market.
                </p>

                <SubHeading>How the trigger price is calculated</SubHeading>
                <p style={{ marginBottom: '16px' }}>
                    Each coin has a <strong>Volatility %</strong> field on the Portfolio/Watchlist table. Combined with
                    the current price, this determines the trigger point:
                </p>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.9' }}>
                    <li><strong>Auto-Sell</strong> begins confirmation if the price drops by more than Volatility % within the configured Volatility Hours window (default 24h, adjustable in Settings → Portfolio Table &amp; Execution Safety Settings)</li>
                    <li><strong>Auto-Buy</strong> begins confirmation if the price surges by more than Volatility % within that same window</li>
                </ul>
                <Example>
                    If XRP is at $3.00 and you set Volatility % to 5, enabling Auto-Sell arms a trigger around
                    $2.85 (a 5% drop) and enabling Auto-Buy arms a trigger around $3.15 (a 5% surge). Editing the
                    Volatility % field afterward immediately recalculates and updates both the live trigger price
                    shown in Open Orders and the actual threshold the background monitor uses.
                </Example>

                <SubHeading>Confirmation against temporary swings</SubHeading>
                <p style={{ marginBottom: '16px' }}>
                    <strong>Automated Trigger Confirmation Window (Minutes)</strong> is shared by Auto-Buy and Auto-Sell and defaults to 15 minutes. The threshold must remain met for the complete window before the app submits an order. If any background check finds that the price has recovered across the threshold, that trigger's timer is cleared and it must qualify again from the beginning. This prevents a brief, volatile spike or dip from immediately executing a trade.
                </p>

                <SubHeading>Setting it up</SubHeading>
                <ol style={{ paddingLeft: '20px', lineHeight: '1.8' }}>
                    <li>Set a Volatility % for the coin on the Portfolio or Watchlist table</li>
                    <li>Click the row's trade menu and choose <strong>Trigger Auto-Sell</strong> or <strong>Trigger Auto-Buy</strong></li>
                    <li>Choose the settlement currency (USD or USDT) and, for Auto-Buy, the dollar amount to allocate</li>
                    <li>Confirm — the coin now shows an active indicator (⚡ Auto-Sell / 🚀 Auto-Buy)</li>
                </ol>

                <SubHeading>Balance protection</SubHeading>
                <p style={{ marginBottom: '16px' }}>
                    Auto-Buy validates your live free balance and reserves funds already committed to other active
                    Auto-Buy triggers, so you can never allocate more than what's actually uncommitted (with a $1.00
                    minimum order floor). Auto-Sell automatically cancels any conflicting open orders (limit/stop-loss)
                    on that coin right before executing, so it can unlock and sell 100% of your balance.
                </p>

                <SubHeading>Viewing and cancelling triggers</SubHeading>
                <p style={{ marginBottom: '16px' }}>
                    Active triggers appear alongside your real exchange orders in the Trading Center's <strong>Open
                    Orders</strong> tab, showing the live calculated trigger price. Once a trigger fires and places a
                    real order, it also appears in <strong>Order History</strong> at its actual executed price. To
                    cancel a trigger, click "Cancel" on the Portfolio/Watchlist row (or from Open Orders) — a
                    confirmation modal shows the current trigger details and, if 2FA is enabled, requires your code.
                </p>
            </Section>

            {/* Trading Center */}
            <Section id="trading-center" icon={<FaChartLine />} title="Trading Center">
                <p style={{ marginBottom: '16px' }}>
                    Use the <strong>Trading</strong> menu to choose a dedicated exchange workspace. <strong>Binance.US Trading</strong> lets you execute spot trades for <strong>any</strong> coin Binance.US lists —
                    54+ USD pairs and 200+ USDT pairs. USD and USDT are simply the two settlement currencies you can
                    quote against; they are not the only things you can buy or sell.
                </p>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.9' }}>
                    <li><strong>Exchange-specific workspaces</strong> — Binance.US Trading is isolated to Binance.US balances, pairs, and orders. Webull Trading uses the selected account’s imported positions and buying power for execution. Its Max and percentage controls preserve fractional stock/ETF quantities during Regular Hours; Webull fractional stock/ETF orders must be Market orders in the Regular Hours session, while Extended and Overnight sessions require whole shares. Stock/ETF, crypto, and single-leg option tickets apply their own supported order types and time-in-force rules; option orders retain the exact imported contract terms. Valid Webull orders and cancellations use the six-digit 2FA confirmation flow for their owning account.</li>
                    <li><strong>Combined Orders</strong> — the top-level Orders destination combines Binance.US, Webull, and active app automation orders while preserving source and account labels. Filter either tab by source, account, symbol, product type, status, or time range without making another exchange request. Cancelling an open order uses the native theme-aware modal, identifies the exact provider/account/order or trigger, and requires your six-digit 2FA code.</li>
                    <li><strong>Two searchable symbol tools</strong> — use the app's Binance.US pair selector to keep the chart, order ticket, balances, and personal history synchronized; TradingView's built-in search is also available for independent market research</li>
                    <li><strong>TradingView Advanced Chart</strong> — candlesticks and other chart styles, 80+ indicators, 100+ drawing tools, comparisons, configurable price scales, date ranges, details, hotlists, economic calendar, image export, and a full-size popup</li>
                    <li><strong>Moving averages & oscillators</strong> — Moving Average, RSI, MACD, Stochastic, ATR, Bollinger Bands, and Volume are available from TradingView's built-in <em>Indicators</em> menu, replacing the former controls below the chart</li>
                    <li><strong>Trade Chart tabs</strong> — Binance.US pairs show pair-aware buys and sells as uncluttered up/down arrows over a price line, with exact time, price, amount, and value on hover. The Webull Trade Chart provides the same read-only history for imported Webull equities, ETFs, crypto, and contract-mapped options, overlaid only with that instrument's completed Webull orders. Option charts and quotes use the contract ID, never the underlying stock. The option panel shows the available contract details, price/IV, and Greeks; unavailable OPRA data is clearly identified. Choose a holding and a range from 1D through ALL; the default is 1 Month.</li>
                    <li><strong>AI Analysis tab</strong> — the former global AI Analysis destination now lives inside Binance.US Trading. It retains the existing crypto sentiment, ledger, and AI workflow features.</li>
                    <li><strong>Order types</strong> — Market, Limit, Stop-Loss, Stop-Loss-Limit, Take-Profit, Take-Profit-Limit, OCO (One-Cancels-the-Other), and Limit Maker (availability depends on the selected pair)</li>
                    <li><strong>Order Placement panel</strong> — MAX balance button, quote-quantity 2-way sync, a percentage slider (0/25/50/75/100%), and an order summary with estimated fees</li>
                    <li><strong>Open Orders tab</strong> — all pending real exchange orders plus any active Auto-Buy/Auto-Sell triggers</li>
                    <li><strong>Order History tabs</strong> — Binance.US, Webull, and combined Orders histories are paginated at 50 rows by default. Choose 20, 50, 100, or 200 rows per page. The Binance.US Origin badge distinguishes manual orders, Auto-Sell/Auto-Buy execution, and a manual order canceled by Auto-Sell to release its balance.</li>
                    <li><strong>Convert Dust</strong> — sweep small leftover balances into a supported asset in one action</li>
                </ul>
                <Tip>
                    A Test Mode is available for practicing order placement without executing real trades.
                </Tip>
            </Section>

            {/* Staking */}
            <Section id="staking" icon={<FaCoins />} title="Staking">
                <p style={{ marginBottom: '16px' }}>
                    Manage Binance.US staking positions for supported proof-of-stake assets directly in the app.
                </p>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.9' }}>
                    <li><strong>Real-Time APY Synchronization</strong> — reward rates and estimated APY/APR percentages are pulled directly in real time from live Binance.US staking endpoints</li>
                    <li><strong>One-click Stake / Unstake</strong> — deposit into or redeem from a staking position</li>
                    <li><strong>Daily Reward Tracking</strong> — today's rewards, average APY, actively staked amount, and pending releases</li>
                </ul>
            </Section>

            {/* AI Analysis */}
            <Section id="ai-analysis" icon={<FaRobot />} title="AI Analysis Page">
                <p style={{ marginBottom: '16px' }}>
                    AI Analysis is available as a tab within <strong>Binance.US Trading</strong>, providing deeper, on-demand crypto intelligence beyond the per-coin sentiment badges. In live Webull mode, its AI tab keeps product types separate: imported Webull crypto and stocks/ETFs can create stored, read-only signals with their own prompt family, saved forecast horizon, and later graded outcome. The Webull AI tab is hidden in Test Mode. Equity/ETF signals and grading wait for regular U.S. market hours rather than relying on a stale closing price. Optional scheduled Webull signals are off by default and use that same lifecycle. They never place an order. Webull options now have contract-safe charts and quote data, but remain unavailable to AI until an options-specific prompt and risk model are added; the Webull Trade Chart does not enable or infer an AI recommendation.
                </p>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.9' }}>
                    <li><strong>Market Analysis</strong> — current market trends and opportunities, grounded in live web search</li>
                    <li><strong>Portfolio Review</strong> — comprehensive risk assessment, allocation breakdown, and recommendations</li>
                    <li><strong>Sentiment Chart</strong> — a pair-aware price line showing only completed sentiment grades. Green Correct, blue Neutral, and red Wrong circles contain the original H/CB/BI/CS/SI recommendation being graded; tracking signals remain hidden. Hover tooltips preserve the original sentiment timestamp and evaluation detail. New users default to 3 Days, the selector supports 1D through ALL, and each selection is saved as that user's default.</li>
                    <li><strong>Historical Prediction Ledger</strong> — sentiment calls are graded at their configured fixed forecast horizon, independent of scheduled or manual refreshes. The ledger shows signal and evaluation prices and timestamps, supports coin filtering and sorting, and paginates 20 rows by default with 20, 50, 100, and 200-row options.</li>
                    <li><strong>Sentiment Variable Settings</strong> — directional recommendations have independent Correct and Wrong percentage boundaries; directional Wrong may be 0.00%. Hold uses a configurable Steady Range (±%) and one symmetric Wrong Threshold (±%) that must be greater than Steady. Hold is Correct inside Steady, Wrong at or beyond its Wrong threshold, and Neutral strictly between those boundaries.</li>
                    <li><strong>Automatic Coin Inclusion</strong> — newly added portfolio coins are automatically checked off and included by default in all charts, list views, and thesis evaluations</li>
                    <li><strong>AI Model Leaderboard</strong> — empirical accuracy comparison across whichever AI providers/models you've used</li>
                    <li><strong>NewsAPI grounding</strong> — when a News API key is configured, AI workflows that request current news include fresh NewsAPI articles alongside supplemental market web-search context.</li>
                </ul>
            </Section>

            {/* AI Copilot */}
            <Section id="ai-copilot" icon={<FaComments />} title="AI Copilot Sidebar">
                <p style={{ marginBottom: '16px' }}>
                    The AI Copilot is a context-aware chat assistant available from a sidebar on most pages.
                </p>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.9' }}>
                    <li>Automatically injects your active portfolio holdings, pending orders, and recent sentiment signals into its context, so answers are tailored to your actual account</li>
                    <li>Full conversation history is saved; you can archive or delete individual messages instantly</li>
                    <li>Ask it things like "Should I be worried about my SOL position?" or "What's driving the market today?"</li>
                </ul>
            </Section>

            {/* Tax Report */}
            <Section id="tax-report" icon={<FaFileInvoiceDollar />} title="Tax Report">
                <p style={{ marginBottom: '16px' }}>
                    Generate capital gains/losses summaries for your crypto activity.
                </p>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.9' }}>
                    <li><strong>Cost basis method</strong> — choose FIFO, LIFO, or HIFO in Settings → Tax Configuration</li>
                    <li><strong>Tax-year filtering</strong> — generate annual reports scoped to a specific tax year (e.g. 2026, 2025, 2024...) or all time</li>
                    <li><strong>Short-Term vs. Long-Term Capital Gains</strong> — automatically calculates holding periods and breaks down short-term vs. long-term gains</li>
                    <li><strong>Unified transaction ledger</strong> — every buy, sell, deposit, withdrawal, staking reward, and fee formatted in Eastern Time</li>
                    <li><strong>CSV & Excel export</strong> — download filtered annual tax summaries and transaction logs for your tax records</li>
                </ul>
            </Section>

            {/* Other Settings */}
            <Section id="other-settings" icon={<FaCog />} title="Other Settings">
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.9' }}>
                    <li><strong>Portfolio Table &amp; Execution Safety Settings</strong> — set the Volatility Hours comparison window and the 1–1,440 minute Automated Trigger Confirmation Window used by both Auto-Buy and Auto-Sell. The default confirmation window is 15 minutes and a price recovery resets a pending timer.</li>
                    <li><strong>Sync Coins</strong> — force an immediate balance sync with Binance.US</li>
                    <li><strong>Webull OpenAPI Connection</strong> — securely save your App Key and App Secret, then select <strong>Connect and Verify in Webull</strong>. For Production accounts with Webull OpenAPI 2FA, approve the SMS code in Webull’s Menu → Messages → OpenAPI Notifications and select <strong>Check Webull Verification</strong> within five minutes. The resulting access token is encrypted, never shown in the browser, is bound to its environment, and is cleared if its credentials or environment change. Verification alone neither imports positions nor sends orders; import selected accounts before using their Webull workspace.</li>
                    <li><strong>Connected Webull Accounts</strong> — after verification, Settings discovers and lists your associated Webull accounts using masked labels and account types only. Choose the account(s) to include; account IDs, tokens, and signing material never reach the browser.</li>
                    <li><strong>Webull Portfolio Preview</strong> — when connected Webull accounts are selected, load a live, read-only preview of those accounts’ balances and open positions. The preview does not merge or persist data until you explicitly import it; it never alters existing Binance.US dashboard data.</li>
                    <li><strong>Webull setup instructions</strong> — see <a href="#webull-openapi-setup" style={{ color: accentColor }}>Webull OpenAPI Setup &amp; Import</a> above for the complete verification, account-selection, import, default-account, and order-safety workflow.</li>
                    <li><strong>Run Sentiment Analysis Now</strong> — trigger a full AI sentiment pass on demand</li>
                    <li><strong>Include Beta</strong> — opt in to beta releases when upgrading</li>
                    <li><strong>AI Integrations Enabled</strong> — toggle all configured AI integrations from the Settings header. API keys, Telegram credentials, and the News API key are masked on screen; every configured provider has a consistent <strong>Test API Connection</strong> button.</li>
                    <li><strong>Upgrade App</strong> — queries GitHub live for the latest eligible published release, shows that exact tag for confirmation, then rechecks GitHub immediately before installing it. Beta releases are included only when Include Beta is enabled.</li>
                    <li><strong>Delete Account</strong> — permanently removes your credentials, 2FA, settings, and tax data (export your tax report first!)</li>
                </ul>
            </Section>

            {/* Troubleshooting */}
            <Section id="troubleshooting" icon={<FaExclamationTriangle />} title="Troubleshooting">
                <SubHeading>"API Key Required" Modal</SubHeading>
                <p style={{ marginBottom: '16px' }}>
                    This appears when you try to access AI Analysis, Trading, or Staking without a configured API key.
                    Go to <Link to="/settings" style={{ color: accentColor }}>Settings</Link> and add your Binance.US credentials.
                </p>

                <SubHeading>"Trading Permission Required" Modal</SubHeading>
                <p style={{ marginBottom: '16px' }}>
                    This appears when your API key doesn't have "Enable Spot Trading" permission.
                    Log into Binance.US, edit your API key, and enable this permission.
                </p>

                <SubHeading>Connection Test Failed</SubHeading>
                <p style={{ marginBottom: '16px' }}>
                    Double-check that you copied the API Key and Secret correctly.
                    Make sure "Enable Reading" permission is enabled on your key.
                </p>

                <SubHeading>Webull verification is pending or no Webull accounts appear</SubHeading>
                <p style={{ marginBottom: '16px' }}>
                    Confirm that the selected Production or Sandbox environment matches the App Key and App Secret. For a pending
                    Production verification, approve the newest request in Webull at <strong>Menu → Messages → OpenAPI Notifications</strong>
                    and then select <strong>Check Webull Verification</strong> in Settings within five minutes. Once active, use
                    <strong>Refresh Accounts</strong>, enable at least one account, load the read-only preview, and import the selected
                    portfolio snapshot before opening Webull Trading.
                </p>

                <SubHeading>Webull order validation error</SubHeading>
                <p style={{ marginBottom: '16px' }}>
                    Confirm that the selected Webull account owns the position for a sell, that the order uses an allowed
                    instrument/order type/session combination, and that the quantity follows the session rules. Fractional stock/ETF
                    orders are Market-only in Only Regular Hours; Extended and Overnight orders require whole shares. Review the
                    pre-trade details and complete the app's six-digit 2FA confirmation when trading 2FA is enabled.
                </p>

                <SubHeading>Auto-Buy "Cannot allocate" Error</SubHeading>
                <p style={{ marginBottom: '16px' }}>
                    This means the amount you tried to allocate exceeds your uncommitted free balance for that quote
                    currency, after accounting for other active Auto-Buy triggers. Lower the amount or free up balance.
                </p>

                <SubHeading>Order Rejected for Price</SubHeading>
                <p>
                    Binance.US enforces price collar limits on Limit/Stop orders (generally within a band around the
                    current market price). If your order is rejected, adjust the price closer to the live market price.
                </p>
            </Section>

            <div style={{ textAlign: 'center', padding: '20px', color: textColor, opacity: 0.6 }}>
                <p>Need more help? Visit the <Link to="/support" style={{ color: accentColor }}>Support</Link> page or check the GitHub repository.</p>
            </div>
        </div>
    );
}
