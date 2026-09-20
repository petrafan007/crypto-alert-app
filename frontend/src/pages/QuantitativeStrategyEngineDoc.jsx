import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../components/AuthContext';
import {
    FaChartBar, FaLayerGroup, FaRobot, FaShieldAlt,
    FaListOl, FaArrowLeft, FaSearch, FaBrain, FaChartLine,
    FaCoins, FaFutbol, FaFileInvoice, FaLock
} from 'react-icons/fa';

const TOC_GROUPS = [
    {
        title: 'Architecture',
        items: [
            { id: 'architecture', label: 'Core Architecture & Data Flow' },
        ]
    },
    {
        title: 'Module Algorithms',
        items: [
            { id: 'equities', label: 'Equities Module' },
            { id: 'options', label: 'Options Module' },
            { id: 'crypto', label: 'Crypto Module' },
            { id: 'futures', label: 'Futures Module' },
            { id: 'events', label: 'Event Contracts Module' },
        ]
    },
    {
        title: 'AI Integration',
        items: [
            { id: 'ai-tiers', label: '3-Tier AI Integration & Failover' },
        ]
    },
    {
        title: 'Administration',
        items: [
            { id: 'safeguards', label: 'Administrative Safeguards' },
            { id: 'logs', label: 'Reviewing Operations (Logs)' },
            { id: 'research', label: 'Collected Data & Portfolio Replay' },
        ]
    },
];

export default function QuantitativeStrategyEngineDoc({ isLightMode }) {
    const { user } = useAuth();
    const navigate = useNavigate();
    const isAdmin = Boolean(user?.is_admin || user?.id === 1);

    const textColor = isLightMode ? '#212529' : '#e0e0e0';
    const bgColor = isLightMode ? '#f8f9fa' : '#16213e';
    const cardBg = isLightMode ? '#ffffff' : '#1a1a2e';
    const borderColor = isLightMode ? '#dee2e6' : '#2d3748';
    const accentColor = '#4da6ff';
    const [activeId, setActiveId] = useState(TOC_GROUPS[0].items[0].id);

    // Redirect non-admins immediately
    useEffect(() => {
        if (user && !isAdmin) {
            navigate('/help', { replace: true });
        }
    }, [user, isAdmin, navigate]);

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

    if (!isAdmin) return null;

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

    const Note = ({ children }) => (
        <div style={{
            backgroundColor: isLightMode ? '#eafaf1' : '#0f3324',
            padding: '12px 16px',
            borderRadius: '8px',
            marginTop: '12px',
            fontSize: '14px',
            borderLeft: '4px solid #2ecc71'
        }}>
            <strong style={{ color: '#2ecc71' }}>🔬 Technical Note:</strong> {children}
        </div>
    );

    const SubHeading = ({ children }) => (
        <h3 style={{ color: textColor, marginTop: '20px', marginBottom: '12px' }}>{children}</h3>
    );

    const SettingTag = ({ children }) => (
        <code style={{
            backgroundColor: isLightMode ? '#e9ecef' : '#2d3748',
            color: isLightMode ? '#495057' : '#81e6d9',
            padding: '1px 6px',
            borderRadius: '4px',
            fontSize: '13px',
            fontFamily: 'monospace'
        }}>
            {children}
        </code>
    );

    return (
        <div style={{
            padding: '20px',
            maxWidth: '980px',
            margin: '0 auto',
            backgroundColor: bgColor,
            minHeight: '100vh'
        }}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
                <Link
                    to="/help"
                    style={{ color: accentColor, textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '14px' }}
                >
                    <FaArrowLeft /> Back to Help
                </Link>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
                <h1 style={{ color: textColor, display: 'flex', alignItems: 'center', gap: '12px', margin: 0 }}>
                    <FaChartBar style={{ color: accentColor }} /> Quantitative Strategy Engine
                </h1>
            </div>
            <div style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                backgroundColor: isLightMode ? '#fff3cd' : '#5c4b00',
                color: isLightMode ? '#856404' : '#ffc107',
                border: `1px solid ${isLightMode ? '#ffc107' : '#856404'}`,
                borderRadius: '6px',
                padding: '4px 10px',
                fontSize: '12px',
                fontWeight: 'bold',
                marginBottom: '24px'
            }}>
                <FaLock style={{ fontSize: '10px' }} /> Administrator Documentation
            </div>
            <p style={{ color: textColor, marginBottom: '28px', lineHeight: '1.7', opacity: 0.85 }}>
                The Quantitative Strategy Engine is a paper-ledger simulation system for testing and validating multi-asset
                trading algorithms. This guide covers the end-to-end pipeline, module algorithm mechanics, the 3-Tier AI
                integration cascade, and the administrative safeguards built into the engine.
            </p>

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

            {/* Section 1: Core Architecture */}
            <Section id="architecture" icon={<FaLayerGroup />} title="Core Architecture & Data Flow">
                <p style={{ marginBottom: '16px', lineHeight: '1.7' }}>
                    The engine operates on a continuous background pipeline, not in real-time alongside front-end requests.
                    This ensures uninterrupted market monitoring. The full pipeline executes in this sequence:
                </p>
                <ol style={{ paddingLeft: '24px', lineHeight: '2.2', marginBottom: '16px' }}>
                    <li>
                        <strong>Market Data Ingestion</strong> — The background worker (<SettingTag>run_scan</SettingTag> in
                        <SettingTag>services/portfolio_engine.py</SettingTag>) checks for work every 15 seconds and
                        normally scans the portfolio every five minutes. A separate Event consumer checks fresh
                        decisions every 15 seconds. Session, freshness and risk gates still apply.
                    </li>
                    <li>
                        <strong>Algorithmic Signal Evaluation</strong> — Ingested data is passed through purely deterministic,
                        math-driven algorithms in <SettingTag>services/portfolio_strategy_signals.py</SettingTag>.
                        Entry and exit gates are deterministic. Event probabilities come from the separate AI forecast worker.
                    </li>
                    <li>
                        <strong>Paper Ledger Execution</strong> — When an algorithm fires an entry or exit signal, the engine
                        updates positions on the paper ledger, records P&L, and subtracts estimated slippage and commissions.
                        Both opens and closes are written to the <SettingTag>PortfolioEngineLog</SettingTag> table.
                    </li>
                    <li>
                        <strong>AI Audit Cascade</strong> — On the master daily/weekly market-close schedule, or on manual request,
                        the engine takes a portfolio snapshot and initiates the AI evaluation cascade:
                        <ul style={{ marginTop: '8px', paddingLeft: '20px', lineHeight: '2' }}>
                            <li><strong>Localized Module Agents</strong> — each active module (Equities, Options, Crypto, Futures, Events) gets its own isolated AI agent call using its <SettingTag>auditor_prompt</SettingTag> and module-scoped evidence.</li>
                            <li><strong>Master CIO Synthesis</strong> — once all module agents respond, the Master CIO receives their outputs plus overarching metrics (total equity, cash allocation, cross-module correlations) to generate the final portfolio report.</li>
                        </ul>
                    </li>
                    <li>
                        <strong>System Logging</strong> — Every scan cycle, executed lot, and AI step is written to the
                        <SettingTag>PortfolioEngineLog</SettingTag> table and appears in the <strong>View Logs</strong> modal.
                    </li>
                </ol>
                <Note>
                    The engine uses <SettingTag>lease_token</SettingTag> and <SettingTag>lease_until</SettingTag> database fields to prevent duplicate
                    execution across gunicorn workers. Only the worker that successfully acquires the lease proceeds.
                </Note>
            </Section>

            {/* Section 2: Equities */}
            <Section id="equities" icon={<FaChartLine />} title="Equities Module">
                <p style={{ marginBottom: '12px', lineHeight: '1.7' }}>
                    <strong>Strategy:</strong> Trend-following mean-reversion with relative momentum filtering.
                </p>
                <p style={{ marginBottom: '16px', lineHeight: '1.7' }}>
                    The module buys when a stock is above its long-term SMA and showing positive relative momentum
                    against its benchmark, but has temporarily pulled back to an oversold RSI reading and touched
                    the lower Bollinger Band. It exits when price breaks below the SMA or RSI becomes overbought.
                </p>
                <SubHeading>Key Settings</SubHeading>
                <ul style={{ paddingLeft: '20px', lineHeight: '2.2' }}>
                    <li><SettingTag>trend_sma_days</SettingTag> — the N-day Simple Moving Average used as the primary trend filter.</li>
                    <li><SettingTag>rsi_period</SettingTag> — the RSI look-back period (default: 2-period for sensitivity).</li>
                    <li><SettingTag>rsi_entry_threshold</SettingTag> — RSI must be <em>below</em> this value to signal an entry.</li>
                    <li><SettingTag>bollinger_std</SettingTag> — the standard deviation multiplier for the lower band entry trigger.</li>
                </ul>
                <Note>
                    Requires at least <code>max(trend_sma_days, 64, rsi_period + 1)</code> completed daily bars
                    and 64 benchmark bars before signaling. The benchmark is used to compute 63-session relative momentum.
                </Note>
            </Section>

            {/* Section 3: Options */}
            <Section id="options" icon={<FaFileInvoice />} title="Options Module">
                <p style={{ marginBottom: '12px', lineHeight: '1.7' }}>
                    <strong>Strategy:</strong> Defined-risk OTM credit spread premium collection.
                </p>
                <p style={{ marginBottom: '16px', lineHeight: '1.7' }}>
                    The module scans live option chains for short legs at a target delta and paired long legs that
                    create a defined-risk spread. It only enters when Implied Volatility Rank (IVR) exceeds a minimum
                    threshold, ensuring premium is elevated. Contracts must have 20–65 days to expiration.
                </p>
                <SubHeading>Key Settings</SubHeading>
                <ul style={{ paddingLeft: '20px', lineHeight: '2.2' }}>
                    <li><SettingTag>target_delta</SettingTag> — the absolute delta of the short leg (e.g., 16 = 0.16 delta).</li>
                    <li><SettingTag>target_dte</SettingTag> — ideal days-to-expiration; the engine selects the spread closest to this target.</li>
                    <li><SettingTag>min_ivr</SettingTag> — minimum IV Rank required to enter a new spread position.</li>
                </ul>
                <Note>
                    The engine selects the best spread by jointly minimizing: <em>|DTE - target_dte|</em>,
                    <em>|delta - target_delta|</em>, and spread width. Only quoted contracts with provider-supplied
                    Greeks are eligible; contracts with a missing or TBD condition are excluded.
                    IV rank also requires 252 compatible measured daily ATM observations with a non-flat range.
                </Note>
            </Section>

            {/* Section 4: Crypto */}
            <Section id="crypto" icon={<FaCoins />} title="Crypto Module">
                <p style={{ marginBottom: '12px', lineHeight: '1.7' }}>
                    <strong>Strategy:</strong> Donchian Channel breakout with Bitcoin dominance regime filter.
                </p>
                <p style={{ marginBottom: '16px', lineHeight: '1.7' }}>
                    The module enters a long position when the live price breaks above the highest high of the entry
                    channel and Bitcoin dominance confirms a risk-on regime. It exits when price breaks below the
                    lowest low of the exit channel. An ATR-based trailing stop is calculated on entry.
                </p>
                <SubHeading>Key Settings</SubHeading>
                <ul style={{ paddingLeft: '20px', lineHeight: '2.2' }}>
                    <li><SettingTag>entry_channel_periods</SettingTag> — look-back period in hourly bars for the breakout high.</li>
                    <li><SettingTag>exit_channel_periods</SettingTag> — look-back period for the exit low channel.</li>
                    <li><SettingTag>atr_stop_multiplier</SettingTag> — stop loss is set at <em>entry_price - (multiplier × ATR)</em>.</li>
                </ul>
                <Note>
                    The engine compares the live quote against <em>prior completed bars only</em>, never against the
                    forming candle's own high. This avoids false breakouts from intrabar wicks.
                </Note>
            </Section>

            {/* Section 5: Futures */}
            <Section id="futures" icon={<FaFutbol />} title="Futures Module">
                <p style={{ marginBottom: '12px', lineHeight: '1.7' }}>
                    <strong>Strategy:</strong> Opening Range Breakout (ORB) with VWAP directional confirmation.
                </p>
                <p style={{ marginBottom: '16px', lineHeight: '1.7' }}>
                    The module identifies the high and low of the opening range (e.g., the first 15 minutes of the
                    US cash session). It enters long if price breaks above the range <em>and</em> is above the
                    session VWAP, or short if price breaks below the range and is below VWAP. Entries are blocked
                    within the final 15 minutes of the session; positions are exited in the final 5 minutes.
                </p>
                <SubHeading>Key Settings</SubHeading>
                <ul style={{ paddingLeft: '20px', lineHeight: '2.2' }}>
                    <li><SettingTag>opening_range_minutes</SettingTag> — duration of the opening range in minutes.</li>
                </ul>
                <Warning>
                    Every individual 1-minute candle within the opening range is required. If the range window
                    contains any gaps, the engine will not signal — ensuring VWAP accuracy.
                </Warning>
            </Section>

            {/* Section 6: Events */}
            <Section id="events" icon={<FaSearch />} title="Event Contracts Module">
                <p style={{ marginBottom: '12px', lineHeight: '1.7' }}>
                    <strong>Strategy:</strong> Compare archived model probabilities with fresh executable binary-contract prices.
                </p>
                <p style={{ marginBottom: '16px', lineHeight: '1.7' }}>
                    The independent Event consumer revalidates forecast age, cutoff, confidence, net edge after fees,
                    spread and saved risk limits before entering the shared paper ledger. Missing or stale evidence
                    blocks entry. Expired positions remain open until an explicit provider settlement is observed.
                </p>
                <SubHeading>Key Settings</SubHeading>
                <ul style={{ paddingLeft: '20px', lineHeight: '2.2' }}>
                    <li><SettingTag>min_confidence</SettingTag> — required forecast confidence.</li>
                    <li><SettingTag>min_net_edge</SettingTag> — required modeled edge after fees and uncertainty allowance.</li>
                </ul>
            </Section>

            {/* Section 7: AI Tiers */}
            <Section id="ai-tiers" icon={<FaBrain />} title="3-Tier AI Integration & Failover">
                <p style={{ marginBottom: '16px', lineHeight: '1.7' }}>
                    The engine supports retries and fallback for autonomous reporting by routing AI calls through
                    a 3-Tier failover system configured in <strong>Master AI Configuration</strong>.
                </p>
                <SubHeading>Configuring the Tiers</SubHeading>
                <ul style={{ paddingLeft: '20px', lineHeight: '2.2', marginBottom: '16px' }}>
                    <li><strong>Primary</strong> — your configured first provider and model.</li>
                    <li><strong>Secondary</strong> — your configured backup.</li>
                    <li><strong>Tertiary</strong> — your final configured fallback, including an available local model if selected.</li>
                </ul>
                <SubHeading>Failover Execution Logic</SubHeading>
                <p style={{ lineHeight: '1.7' }}>
                    When the master audit schedule triggers, or you request a manual audit:
                </p>
                <ol style={{ paddingLeft: '24px', lineHeight: '2.2' }}>
                    <li>For each active module, the engine calls the <strong>Primary</strong> localized AI agent.</li>
                    <li>If the call fails (timeout, rate limit, model error), it automatically falls over to <strong>Secondary</strong>, then <strong>Tertiary</strong>.</li>
                    <li>After all module audits complete, the same 3-tier failover applies to the <strong>Master CIO</strong> synthesis call.</li>
                    <li>Each module's agent uses its own custom <SettingTag>auditor_prompt</SettingTag> from Module Settings and receives only isolated, module-scoped evidence — never the full portfolio payload.</li>
                </ol>
                <Note>
                    Module audits run <em>sequentially</em> to preserve the sequential evidence chain. The Master CIO
                    receives all module responses embedded in the <SettingTag>module_audits</SettingTag> evidence field
                    before synthesizing its final report.
                </Note>
            </Section>

            {/* Section 8: Safeguards */}
            <Section id="safeguards" icon={<FaShieldAlt />} title="Administrative Safeguards">
                <p style={{ marginBottom: '16px', lineHeight: '1.7' }}>
                    The engine runs autonomously, but several layers of protection prevent catastrophic runaway behavior.
                </p>
                <SubHeading>Global Circuit Breaker</SubHeading>
                <p style={{ lineHeight: '1.7', marginBottom: '12px' }}>
                    The system monitors <strong>Total Portfolio Equity</strong> after every scan. If simulated equity
                    falls to <strong>90% of the starting bankroll or below</strong>, the engine pauses new entries.
                    Existing positions can still be monitored and exited. Review the pause in the dashboard;
                    an explicit Stop separately freezes execution.
                </p>
                <SubHeading>Stall Detection via Lease Tokens</SubHeading>
                <p style={{ lineHeight: '1.7', marginBottom: '12px' }}>
                    Background workers write a <SettingTag>lease_token</SettingTag> and <SettingTag>lease_until</SettingTag>
                    timestamp to the database before each scan. If a gunicorn worker process stalls or crashes, the lease
                    expires after <strong>five minutes without renewal</strong>, allowing the scheduler to reclaim it safely.
                </p>
                <SubHeading>Position Sizing & Allocation Enforcement</SubHeading>
                <p style={{ lineHeight: '1.7', marginBottom: '12px' }}>
                    Entry sizing respects the module's available budget and shared cash. Market moves and retained
                    positions can put actual weights above targets; an allocation target is not a guarantee of exact exposure.
                </p>
                <Warning>
                    The portfolio circuit uses the starting bankroll. Reported peak-to-trough drawdown and the
                    Event module's separate daily risk controls have different baselines.
                </Warning>
            </Section>

            {/* Section 9: Logs */}
            <Section id="logs" icon={<FaRobot />} title="Reviewing Operations (View Logs)">
                <p style={{ marginBottom: '16px', lineHeight: '1.7' }}>
                    All significant engine activity is written to the <SettingTag>PortfolioEngineLog</SettingTag> database
                    table and viewable from the <strong>View Logs</strong> button on the Quant Strategy dashboard.
                </p>
                <SubHeading>Log Event Types</SubHeading>
                <ul style={{ paddingLeft: '20px', lineHeight: '2.4' }}>
                    <li><SettingTag>SCAN_START</SettingTag> / <SettingTag>SCAN_COMPLETE</SettingTag> — identifies actual portfolio scans and their recorded results.</li>
                    <li><SettingTag>POSITION_OPENED</SettingTag> — logs the module, instrument, entry price, and signal reason (e.g., <em>Donchian breakout with measured dominance regime</em>).</li>
                    <li><SettingTag>POSITION_CLOSED</SettingTag> — logs the instrument, exit price, and closing reason (e.g., stop-loss hit or exit signal triggered).</li>
                    <li><SettingTag>AUDIT_START</SettingTag> — signals the beginning of a full autonomous AI audit cascade.</li>
                    <li><SettingTag>AUDIT_MODULE</SettingTag> — one entry per module as each localized AI agent is invoked.</li>
                    <li><SettingTag>AUDIT_MASTER</SettingTag> — confirms the Master CIO synthesis call has been dispatched.</li>
                    <li><SettingTag>AUDIT_COMPLETE</SettingTag> — confirms the Master CIO report was generated successfully.</li>
                </ul>
                <Tip>
                    Logs persist across restarts. An empty view may reflect filters, a new paper run or no recorded
                    activity; check the saved worker state and timestamps before drawing conclusions.
                </Tip>
                <p>Event health uses the last completed scan while a new scan runs. Cached forecasts and completed
                    AI batches publish immediately with refreshed quotes. Degraded status still indicates missing
                    or failed evidence in an enabled module; a running scan alone does not establish a fault.
                    Quote refreshes never extend a forecast's lifetime or bypass entry and risk controls.</p>
                <p>Before requesting AI, the engine checks the saved entry window, market status, quote timing,
                    usable bid/ask sides, spread and reported liquidity. Excluded contracts retain an observation
                    and an explanation that AI was not required. Closed or out-of-window contracts do not create
                    a data fault merely because their books or forecasts are unavailable. Eligible contracts still
                    require valid evidence. Model requests contain at most two contracts with explicit JSON
                    instructions, and incomplete or invalid answers cannot authorize an entry.</p>
            </Section>

            <Section id="research" icon={<FaChartLine />} title="Collected Data & Portfolio Replay (v3.5.0)">
                <p>Enable the market research archive in quantitative telemetry to collect available options, stock,
                    crypto, futures and Event observations using public feeds and existing access. Collection adds
                    no data subscription and submits no trade or AI request.</p>
                <ol style={{ paddingLeft: '24px', lineHeight: '2.2' }}>
                    <li>Build a dataset from a receipt-time window, starting with 20–60 minutes. View its job result and select the saved dataset.</li>
                    <li>Preview daily IV to see compatible sessions and exclusions. Append measured self-collected days without replacing history; a post-close job also attempts this automatically.</li>
                    <li>Choose a chronological split and run the shared-capital portfolio replay. Six scenarios exercise costs, delayed entries, reduced depth and derivative stress.</li>
                    <li>Inspect module coverage and download the full evidence. Optional historical imports require a preview and explicit save; no purchase is made.</li>
                </ol>
                <Note>Jobs continue after you close the page. Completed computation does not establish profitable
                    trading. Missing history, unverified exchange timestamps and pending outcomes remain visible.
                    Public Event books permit receipt-time comparisons, not a guarantee of broker fills.</Note>
            </Section>

            <div style={{ textAlign: 'center', padding: '20px', color: textColor, opacity: 0.6 }}>
                <p>Need technical support? Visit the <Link to="/support" style={{ color: accentColor }}>Support</Link> page.</p>
            </div>
        </div>
    );
}
