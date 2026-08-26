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
                    Welcome to Crypto Alert App! This is a non-custodial cryptocurrency portfolio management and
                    trading platform for Binance.US. It covers real-time portfolio tracking, one-click trading of
                    any Binance.US-listed coin, staking, automated crash/surge protection, and AI-powered market
                    analysis — all self-hosted, so your API keys and data never leave your own server.
                </p>

                <SubHeading>Quick Start Steps:</SubHeading>
                <ol style={{ paddingLeft: '20px', lineHeight: '1.8' }}>
                    <li><strong>Set up your Binance.US API key</strong> in Settings (required for portfolio sync, trading, and staking)</li>
                    <li><strong>Configure alerts</strong> via Telegram and/or browser notifications for price and trade updates</li>
                    <li><strong>Enable AI integration</strong> for sentiment analysis and the AI Copilot (optional)</li>
                    <li><strong>Explore your Dashboard</strong> — add coins to your Portfolio and Watchlist, then customize the widget layout</li>
                    <li><strong>Set up alerts and triggers</strong> — price alerts, Auto-Buy/Auto-Sell volatility triggers, per your risk tolerance</li>
                </ol>

                <Tip>
                    First time in the app? A one-time onboarding walkthrough highlights the main navigation areas.
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
                            <td style={{ padding: '12px' }}>AI Analysis, AI Copilot Sidebar</td>
                            <td style={{ padding: '12px' }}>Valid Binance.US API key</td>
                        </tr>
                        <tr style={{ borderBottom: `1px solid ${borderColor}` }}>
                            <td style={{ padding: '12px' }}>Trading, Staking, Auto-Buy/Auto-Sell</td>
                            <td style={{ padding: '12px' }}>Valid API key + "Enable Spot Trading" permission</td>
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
                    This app never takes custody of your funds — all trades execute directly on your Binance.US
                    account using your own API key.
                </p>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.8' }}>
                    <li><strong>Local AES-256 Encryption at Rest</strong> — your Binance.US API key/secret and any AI provider keys are encrypted before being stored in the database.</li>
                    <li><strong>Self-Hosted Privacy</strong> — since you run this app on your own server, your keys, trades, and portfolio data stay completely under your control.</li>
                    <li><strong>Credential Encryption Key rotation</strong> (admin account only) — available in Settings for rotating the underlying encryption key.</li>
                    <li><strong>App-level 2FA</strong> — an additional authentication layer for trade execution, separate from your Binance.US account 2FA (see <a href="#two-factor-auth" style={{ color: accentColor }}>Two-Factor Authentication</a>).</li>
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
                    <li>Create a new API key with a label (e.g., "Crypto Alert App")</li>
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
                    Authenticator, Bitwarden, Authy, etc.). This is <strong>separate</strong> from your Binance.US
                    account's own 2FA — it protects this app itself, so anyone with access to your browser session
                    or login credentials still can't log in or place trades without your authenticator code.
                </p>

                <ol style={{ paddingLeft: '20px', lineHeight: '1.8' }}>
                    <li>Enable 2FA in Settings and scan the QR code with an authenticator app</li>
                    <li>Verify by entering the 6-digit code</li>
                    <li>When 2FA is enabled on your profile, you will be prompted for your 6-digit code upon logging in</li>
                    <li>When "Require 2FA for Trading" is enabled, you will also need to confirm each order, dust conversion, and Cancel Auto-Buy/Auto-Sell Trigger action with a code</li>
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
                    <li><strong>Allocations Donut</strong> — breakdown of your holdings by asset weight</li>
                    <li><strong>Portfolio Trend Chart</strong> — net worth over 1D, 7D, 30D, 1Y, and All-time</li>
                    <li><strong>Fear & Greed Index</strong> — overall market sentiment gauge</li>
                    <li><strong>CBBI Bull Run Index</strong> — Bull Run Peak Confidence metric</li>
                    <li><strong>Total Portfolio Value</strong> — live USD/USDT valuation card</li>
                    <li><strong>Staking Yield Overview</strong> — quick summary of staking APY and rewards</li>
                    <li><strong>7-Day Performance Tickers</strong> — multi-interval % change per coin</li>
                    <li><strong>Top Gainers & Losers</strong> — 24h momentum across every coin Binance.US lists (not just your holdings). Click any coin in the list to jump straight to its chart on the Trading page. An editable ✏️ button lets you set how many coins to show per side, and coins you own are highlighted with a ★ badge</li>
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
                    unhidden). Each row supports a full set of actions:
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
                    pair with the Sell side selected — it does not sell USDT, it sells ETH for USDT.
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
                    <li><strong>Auto-Sell</strong> fires if the price drops by more than Volatility % within the configured Volatility Hours window (default 24h, adjustable in Settings → Portfolio Table Settings)</li>
                    <li><strong>Auto-Buy</strong> fires if the price surges by more than Volatility % within that same window</li>
                </ul>
                <Example>
                    If XRP is at $3.00 and you set Volatility % to 5, enabling Auto-Sell arms a trigger around
                    $2.85 (a 5% drop) and enabling Auto-Buy arms a trigger around $3.15 (a 5% surge). Editing the
                    Volatility % field afterward immediately recalculates and updates both the live trigger price
                    shown in Open Orders and the actual threshold the background monitor uses.
                </Example>

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
                    The Trading Center lets you execute spot trades for <strong>any</strong> coin Binance.US lists —
                    54+ USD pairs and 200+ USDT pairs. USD and USDT are simply the two settlement currencies you can
                    quote against; they are not the only things you can buy or sell.
                </p>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.9' }}>
                    <li><strong>Two searchable symbol tools</strong> — use the app's Binance.US pair selector to keep the chart, order ticket, balances, and personal history synchronized; TradingView's built-in search is also available for independent market research</li>
                    <li><strong>TradingView Advanced Chart</strong> — candlesticks and other chart styles, 80+ indicators, 100+ drawing tools, comparisons, configurable price scales, date ranges, details, hotlists, economic calendar, image export, and a full-size popup</li>
                    <li><strong>Moving averages & oscillators</strong> — Moving Average, RSI, MACD, Stochastic, ATR, Bollinger Bands, and Volume are available from TradingView's built-in <em>Indicators</em> menu, replacing the former controls below the chart</li>
                    <li><strong>Trade Chart tab</strong> — pair-aware Binance.US buys and sells appear as uncluttered up/down arrows over a price line, with exact time, price, amount, and value available on hover. Search any supported pair and choose a range from 1D through ALL; the default is 1 Month.</li>
                    <li><strong>Order types</strong> — Market, Limit, Stop-Loss, Stop-Loss-Limit, Take-Profit, Take-Profit-Limit, OCO (One-Cancels-the-Other), and Limit Maker (availability depends on the selected pair)</li>
                    <li><strong>Order Placement panel</strong> — MAX balance button, quote-quantity 2-way sync, a percentage slider (0/25/50/75/100%), and an order summary with estimated fees</li>
                    <li><strong>Open Orders tab</strong> — all pending real exchange orders plus any active Auto-Buy/Auto-Sell triggers</li>
                    <li><strong>Order History tab</strong> — paginated (20 rows/page) history of filled and cancelled orders, filterable by pair</li>
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
                    A dedicated page for deeper, on-demand AI intelligence beyond the per-coin sentiment badges:
                </p>
                <ul style={{ paddingLeft: '20px', marginBottom: '16px', lineHeight: '1.9' }}>
                    <li><strong>Market Analysis</strong> — current market trends and opportunities, grounded in live web search</li>
                    <li><strong>Portfolio Review</strong> — comprehensive risk assessment, allocation breakdown, and recommendations</li>
                    <li><strong>Sentiment Chart</strong> — a pair-aware price line showing only completed sentiment grades. Green Correct, blue Neutral, and red Wrong markers display the precise move to the next same-coin check; tracking signals remain hidden. Hover tooltips preserve the original H/CB/BI/CS/SI recommendation and show its outcome directly above the signal timestamp. New users default to 3 Days, the selector supports 1D through ALL, and each selection is saved as that user's default.</li>
                    <li><strong>Historical Prediction Ledger</strong> — every past sentiment call is compared with the next sentiment check for the same coin and source. The ledger shows both check prices and timestamps, supports interactive coin filtering, and sorts by next-check date/time descending by default.</li>
                    <li><strong>Sentiment Variable Settings</strong> — directional recommendations have independent Correct and Wrong percentage boundaries; Wrong may be 0.00%. Hold instead defines a configurable steady range around 0%, and becomes Wrong once price reaches the Consider Buying or Consider Selling Correct boundary. Exact boundaries are decisive and intermediate moves are Neutral.</li>
                    <li><strong>Automatic Coin Inclusion</strong> — newly added portfolio coins are automatically checked off and included by default in all charts, list views, and thesis evaluations</li>
                    <li><strong>AI Model Leaderboard</strong> — empirical accuracy comparison across whichever AI providers/models you've used</li>
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
                    <li><strong>Portfolio Table Settings</strong> — set the Volatility Hours window used by Auto-Buy/Auto-Sell threshold checks</li>
                    <li><strong>Sync Coins</strong> — force an immediate balance sync with Binance.US</li>
                    <li><strong>Run Sentiment Analysis Now</strong> — trigger a full AI sentiment pass on demand</li>
                    <li><strong>Include Beta</strong> — opt in to beta releases when upgrading</li>
                    <li><strong>Upgrade App</strong> — pull and apply the latest released version</li>
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
