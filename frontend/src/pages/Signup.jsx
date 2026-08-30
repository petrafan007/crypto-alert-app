import React, { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../components/AuthContext';
import LegalModal from '../components/LegalModal';
import { TRADING_RISK_CONTENT } from './TradingRiskDisclosure';
import { APP_VERSION } from '../version';
import './Onboarding.css';
import './Signup.css';

export default function Signup({ isLightMode, toggleTheme }) {
  const [form, setForm] = useState({ username: '', email: '', password: '', confirm: '', accepted: false });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [activeModal, setActiveModal] = useState(null); // 'terms' | 'privacy' | 'acceptable' | 'risk' | null
  const navigate = useNavigate();
  const { checkAuthStatus } = useAuth();

  const rules = useMemo(() => ({
    length: form.password.length >= 12,
    upper: /[A-Z]/.test(form.password),
    lower: /[a-z]/.test(form.password),
    number: /\d/.test(form.password),
    special: /[^A-Za-z0-9]/.test(form.password),
    match: Boolean(form.password) && form.password === form.confirm,
  }), [form.password, form.confirm]);

  const valid = Object.values(rules).every(Boolean) && form.username.trim().length >= 3 && /\S+@\S+\.\S+/.test(form.email) && form.accepted;

  const update = (field, value) => setForm(prev => ({ ...prev, [field]: value }));

  const submit = async event => {
    event.preventDefault();
    setError('');
    if (!valid) {
      setError('Complete every required field and password requirement.');
      return;
    }
    setLoading(true);
    try {
      const { data } = await axios.post('/register', {
        username: form.username.trim(),
        email: form.email.trim(),
        password: form.password,
        accepted_terms: form.accepted
      }, {
        withCredentials: true
      });
      await checkAuthStatus();
      navigate(data.redirect || '/onboarding', { replace: true });
    } catch (err) {
      setError(err.response?.data?.error || 'Registration failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const linkStyle = {
    color: 'var(--accent-primary, #4da6ff)',
    background: 'none',
    border: 'none',
    padding: 0,
    font: 'inherit',
    cursor: 'pointer',
    textDecoration: 'underline',
    display: 'inline'
  };

  return (
    <div className="signup-page">
      <header className="ob-header">
        <svg className="ob-brand-icon" viewBox="0 0 32 32">
          <circle cx="16" cy="16" r="13" fill="none" stroke="currentColor" strokeWidth="2.4"/>
          <path d="M8 21l5-5 4 3 7-8M20 11h4v4" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"/>
        </svg>
        <span>
          <strong>Crypto &amp; Securities Dashboard</strong>
          <small>CSDapp.online</small>
        </span>
        <button className="ob-theme" onClick={toggleTheme} type="button">
          <span>{isLightMode ? '☀' : '☾'}</span>{isLightMode ? 'Light' : 'Dark'}
        </button>
      </header>

      <main className="signup-main">
        <section className="signup-card">
          <div className="signup-heading">
            <small>Step 1 of 6</small>
            <h1>Create your account</h1>
            <p>Start with secure sign-in credentials. Setup progress will be saved after your account is created.</p>
          </div>

          {error && <div className="ob-notice error">{error}</div>}

          <form
            onSubmit={submit}
            inert={activeModal ? '' : undefined}
            style={activeModal ? { visibility: 'hidden' } : {}}
          >
            <div className="ob-grid">
              <label className="ob-field">
                <span>Username</span>
                <input
                  value={form.username}
                  onChange={e => update('username', e.target.value)}
                  autoComplete="username"
                  required
                />
                <small>Between 3 and 80 characters.</small>
              </label>

              <label className="ob-field">
                <span>Email address</span>
                <input
                  type="email"
                  value={form.email}
                  onChange={e => update('email', e.target.value)}
                  autoComplete="email"
                  required
                />
                <small>Used for recovery and security notices.</small>
              </label>

              <label className="ob-field">
                <span>Password</span>
                <input
                  type="password"
                  value={form.password}
                  onChange={e => update('password', e.target.value)}
                  autoComplete="new-password"
                  required
                />
              </label>

              <label className="ob-field">
                <span>Confirm password</span>
                <input
                  type="password"
                  value={form.confirm}
                  onChange={e => update('confirm', e.target.value)}
                  autoComplete="new-password"
                  required
                />
              </label>
            </div>

            <div className="signup-rules">
              {[
                ['length', 'At least 12 characters'],
                ['upper', 'One uppercase letter'],
                ['lower', 'One lowercase letter'],
                ['number', 'One number'],
                ['special', 'One special character'],
                ['match', 'Passwords match']
              ].map(([key, label]) => (
                <span className={rules[key] ? 'met' : ''} key={key}>
                  {rules[key] ? '✓' : '○'} {label}
                </span>
              ))}
            </div>

            <label className="signup-accept">
              <input
                type="checkbox"
                checked={form.accepted}
                onChange={e => update('accepted', e.target.checked)}
              />
              <span>
                I agree to the{' '}
                <button type="button" style={linkStyle} onClick={() => setActiveModal('terms')}>
                  Terms of Service
                </button>
                ,{' '}
                <button type="button" style={linkStyle} onClick={() => setActiveModal('privacy')}>
                  Privacy Policy
                </button>
                ,{' '}
                <button type="button" style={linkStyle} onClick={() => setActiveModal('acceptable')}>
                  Acceptable Use Policy
                </button>
                , and{' '}
                <button type="button" style={linkStyle} onClick={() => setActiveModal('risk')}>
                  trading-risk disclosures
                </button>
                .
              </span>
            </label>

            <div className="signup-actions">
              <Link to="/login">Sign in instead</Link>
              <button className="ob-button primary" disabled={loading || !valid}>
                {loading ? 'Creating Account…' : 'Create Account & Continue'}
              </button>
            </div>
          </form>
        </section>

        <footer style={{
          marginTop: '32px',
          textAlign: 'center',
          color: 'var(--text-tertiary, #888)',
          fontSize: '13px',
          paddingBottom: '24px'
        }}>
          Crypto &amp; Securities Dashboard version {APP_VERSION}. © 2026 Cavallaro Services. All rights reserved.
        </footer>
      </main>

      {/* Terms of Service Modal */}
      <LegalModal
        isOpen={activeModal === 'terms'}
        onClose={() => setActiveModal(null)}
        title="Terms of Service"
      >
        <p style={{ opacity: 0.7, marginBottom: '20px' }}>Last Updated: January 19, 2026</p>
        <h3 style={{ fontSize: '1.2rem', marginBottom: '8px', color: 'var(--accent-primary, #4da6ff)' }}>1. Acceptance of Terms</h3>
        <p>By accessing or using Crypto &amp; Securities Dashboard ("the Service"), you agree to be bound by these Terms of Service. If you do not agree to these terms, do not use the Service.</p>

        <h3 style={{ fontSize: '1.2rem', margin: '20px 0 8px', color: 'var(--accent-primary, #4da6ff)' }}>2. Description of Service</h3>
        <p>Crypto &amp; Securities Dashboard is a non-custodial cryptocurrency and securities portfolio management tool that integrates with Binance.US and Webull via API. The Service provides portfolio tracking, trading execution, staking management, price alerts, AI-powered analysis, and tax reporting features.</p>

        <h3 style={{ fontSize: '1.2rem', margin: '20px 0 8px', color: 'var(--accent-primary, #4da6ff)' }}>3. User Responsibilities</h3>
        <ul style={{ paddingLeft: '20px' }}>
          <li>Maintaining the confidentiality of your account credentials</li>
          <li>All activities that occur under your account</li>
          <li>Ensuring your API keys have appropriate permissions (never enable withdrawal permissions)</li>
          <li>Complying with applicable exchange terms of service and regulations</li>
          <li>Reporting all cryptocurrency and securities transactions to relevant tax authorities</li>
          <li>Making informed trading and investment decisions</li>
        </ul>

        <h3 style={{ fontSize: '1.2rem', margin: '20px 0 8px', color: 'var(--accent-primary, #4da6ff)' }}>4. Non-Custodial Nature</h3>
        <p><strong>The Service is entirely non-custodial.</strong> We never hold, control, or have access to your cryptocurrency or securities assets. All transactions are executed via third-party exchange APIs using credentials you provide. You maintain full custody of your assets at all times.</p>

        <h3 style={{ fontSize: '1.2rem', margin: '20px 0 8px', color: 'var(--accent-primary, #4da6ff)' }}>5. No Financial Advice</h3>
        <p><strong>The Service does not provide financial, investment, tax, or legal advice.</strong> All information, including AI-generated analysis and automated sentiment signals, is for informational and educational purposes only. You should consult qualified professionals before making any financial decisions.</p>

        <h3 style={{ fontSize: '1.2rem', margin: '20px 0 8px', color: 'var(--accent-primary, #4da6ff)' }}>6. Disclaimer of Warranties &amp; Limitation of Liability</h3>
        <p>THE SERVICE IS PROVIDED "AS IS" WITHOUT WARRANTIES OF ANY KIND. IN NO EVENT SHALL CRYPTO &amp; SECURITIES DASHBOARD, ITS OWNERS, OR OPERATORS BE LIABLE FOR DIRECT, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL DAMAGES, TRADING LOSSES, OR API OUTAGES.</p>
      </LegalModal>

      {/* Privacy Policy Modal */}
      <LegalModal
        isOpen={activeModal === 'privacy'}
        onClose={() => setActiveModal(null)}
        title="Privacy Policy"
      >
        <p style={{ opacity: 0.7, marginBottom: '20px' }}>Last Updated: January 19, 2026</p>
        <h3 style={{ fontSize: '1.2rem', marginBottom: '8px', color: 'var(--accent-primary, #4da6ff)' }}>1. Information We Collect</h3>
        <ul style={{ paddingLeft: '20px' }}>
          <li><strong>Account Information:</strong> Username, email address, and securely hashed passwords.</li>
          <li><strong>API Credentials:</strong> Exchange API keys and secrets encrypted at rest using AES-256 encryption. We never see or store your raw secrets unencrypted.</li>
          <li><strong>Usage &amp; Diagnostic Data:</strong> Interaction logs and error traces for debugging and performance optimization.</li>
        </ul>

        <h3 style={{ fontSize: '1.2rem', margin: '20px 0 8px', color: 'var(--accent-primary, #4da6ff)' }}>2. How We Use Information</h3>
        <p>We use your information exclusively to provide portfolio synchronization, execute approved trading actions, send automated alerts, and generate local AI market analysis.</p>

        <h3 style={{ fontSize: '1.2rem', margin: '20px 0 8px', color: 'var(--accent-primary, #4da6ff)' }}>3. Non-Custodial Asset Privacy</h3>
        <p>Crypto &amp; Securities Dashboard never accesses, holds, or transfers user funds. All operations execute strictly within the sandbox boundaries of your personal exchange accounts.</p>

        <h3 style={{ fontSize: '1.2rem', margin: '20px 0 8px', color: 'var(--accent-primary, #4da6ff)' }}>4. Third-Party Integrations</h3>
        <p>Direct API connections are established with Binance.US and Webull based solely on user-provided keys. Price alerts and notifications are routed through Telegram Bot APIs only if explicitly configured.</p>
      </LegalModal>

      {/* Acceptable Use Policy Modal */}
      <LegalModal
        isOpen={activeModal === 'acceptable'}
        onClose={() => setActiveModal(null)}
        title="Acceptable Use Policy"
      >
        <p style={{ opacity: 0.7, marginBottom: '20px' }}>Last Updated: January 19, 2026</p>
        <h3 style={{ fontSize: '1.2rem', marginBottom: '8px', color: 'var(--accent-primary, #4da6ff)' }}>1. Permitted Uses</h3>
        <p>You may use the Service to track personal multi-asset portfolios, execute automated or manual trades on verified accounts, monitor market indicators, and generate analytical reports.</p>

        <h3 style={{ fontSize: '1.2rem', margin: '20px 0 8px', color: 'var(--accent-primary, #4da6ff)' }}>2. Prohibited Activities</h3>
        <ul style={{ paddingLeft: '20px' }}>
          <li>Attempting unauthorized access to system resources or other user profiles</li>
          <li>Engaging in unlawful market manipulation, spoofing, or fraudulent trading practices</li>
          <li>Providing API keys with withdrawal permissions enabled</li>
          <li>Interfering with server infrastructure or abusing third-party rate limits</li>
          <li>Using the platform for unauthorized commercial redistribution or money laundering</li>
        </ul>

        <h3 style={{ fontSize: '1.2rem', margin: '20px 0 8px', color: 'var(--accent-primary, #4da6ff)' }}>3. Account &amp; Credential Security</h3>
        <p>Users must maintain unique, strong credentials and are encouraged to configure two-factor authentication (TOTP) to protect application access.</p>
      </LegalModal>

      {/* Trading Risk Disclosures Modal */}
      <LegalModal
        isOpen={activeModal === 'risk'}
        onClose={() => setActiveModal(null)}
        title={TRADING_RISK_CONTENT.title}
      >
        <p style={{ opacity: 0.7, marginBottom: '20px' }}>Last Updated: {TRADING_RISK_CONTENT.lastUpdated}</p>
        {TRADING_RISK_CONTENT.sections.map((sec, idx) => (
          <div key={idx} style={{ marginBottom: '18px' }}>
            <h3 style={{ fontSize: '1.15rem', marginBottom: '6px', color: 'var(--accent-primary, #4da6ff)' }}>
              {sec.title}
            </h3>
            <p style={{ margin: 0 }}>{sec.content}</p>
          </div>
        ))}
      </LegalModal>
    </div>
  );
}
