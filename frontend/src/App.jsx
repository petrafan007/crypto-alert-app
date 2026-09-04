import React, { useState, useEffect, useRef } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, Link } from 'react-router-dom';
import { useAuth } from './components/AuthContext';
import axios from 'axios';
import Dashboard from './pages/Dashboard';
import Login from './pages/Login';
import Signup from './pages/Signup';
import Onboarding from './pages/Onboarding';
import Trading from './pages/Trading';
import WebullTrading from './pages/WebullTrading';
import Orders from './pages/Orders';
import Settings from './pages/Settings';
import AICopilotSidebar from './components/AICopilotSidebar';
import Staking from './pages/Staking';
import TaxReportBinance from './pages/TaxReportBinance';
import TaxReportWebull from './pages/TaxReportWebull';
import Help from './pages/Help';
import PrivacyPolicy from './pages/PrivacyPolicy';
import TermsOfService from './pages/TermsOfService';
import AcceptableUse from './pages/AcceptableUse';
import TradingRiskDisclosure from './pages/TradingRiskDisclosure';
import Support from './pages/Support';
import ToastNotifications from './components/ToastNotifications';
import { APP_VERSION } from './version';
import './App.css';
import './theme.css';
import './light-theme.css';
import './theme-variables.css';

// Protected Route component
function ProtectedRoute({ children, isLightMode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      height: '100vh',
      color: isLightMode ? '#2d3748' : '#fff',
      fontSize: '18px'
    }}>
      Loading...
    </div>;
  }

  // Inject theme prop into routed page components
  if (!user) return <Navigate to="/login" />;
  if (user.onboardingRequired) return <Navigate to="/onboarding" replace />;
  return React.cloneElement(children, { isLightMode });
}

export default function App() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const isDashboard = location.pathname === '/';
  const isOnboarding = location.pathname === '/onboarding' || location.pathname === '/signup';
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState('');
  const [showUnhideModal, setShowUnhideModal] = useState(false);
  const [hiddenCoins, setHiddenCoins] = useState([]);
  const [selectedHiddenCoins, setSelectedHiddenCoins] = useState([]);
  const [selectAllHidden, setSelectAllHidden] = useState(false);
  const [showTradingMenu, setShowTradingMenu] = useState(false);
  const tradingMenuRef = useRef(null);
  const [showTaxMenu, setShowTaxMenu] = useState(false);
  const taxMenuRef = useRef(null);
  const [isLightMode, setIsLightMode] = useState(() => {
    const stored = localStorage.getItem('theme');
    return stored ? stored === 'light' : false;
  });

  function handleLogout() {
    logout();
    // Don't navigate here - let AuthContext handle the redirect
  }

  // Theme toggle functionality
  const toggleTheme = () => {
    setIsLightMode(prev => {
      const next = !prev;
      localStorage.setItem('theme', next ? 'light' : 'dark');
      return next;
    });
  };

  // Apply theme class to body
  useEffect(() => {
    document.body.classList.add('theme-transition');
    const timeout = setTimeout(() => document.body.classList.remove('theme-transition'), 400);
    if (isLightMode) {
      document.body.classList.add('light-mode');
      document.body.classList.remove('dark-mode');
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      document.body.classList.add('dark-mode');
      document.body.classList.remove('light-mode');
      document.documentElement.setAttribute('data-theme', 'dark');
    }
    return () => clearTimeout(timeout);
  }, [isLightMode]);

  // Keep the exchange menu open while moving from its trigger into the
  // popover. Dismiss only from an intentional outside click or Escape.
  useEffect(() => {
    if (!showTradingMenu && !showTaxMenu) return undefined;
    const dismiss = (event) => {
      const insideTrading = tradingMenuRef.current?.contains(event.target);
      const insideTax = taxMenuRef.current?.contains(event.target);
      if (!insideTrading && !insideTax) {
        setShowTradingMenu(false);
        setShowTaxMenu(false);
      }
    };
    const dismissOnEscape = (event) => {
      if (event.key === 'Escape') {
        setShowTradingMenu(false);
        setShowTaxMenu(false);
      }
    };
    document.addEventListener('mousedown', dismiss);
    document.addEventListener('keydown', dismissOnEscape);
    return () => {
      document.removeEventListener('mousedown', dismiss);
      document.removeEventListener('keydown', dismissOnEscape);
    };
  }, [showTradingMenu, showTaxMenu]);



  // Unhide Assets functionality
  const handleUnhideCoins = async () => {
    try {
      const response = await axios.get('/api/hidden-coins', { withCredentials: true });
      setHiddenCoins((response.data || []).filter(coin => coin?.id && String(coin.symbol || '').trim()));
      setShowUnhideModal(true);
    } catch (err) {
      console.error('Failed to fetch hidden assets:', err);
      setMessage('Failed to load hidden assets');
      setMessageType('error');
    }
  };

  const handleSelectAllHidden = () => {
    if (selectAllHidden) {
      setSelectedHiddenCoins([]);
      setSelectAllHidden(false);
    } else {
      setSelectedHiddenCoins(hiddenCoins.map(coin => coin.id));
      setSelectAllHidden(true);
    }
  };

  const handleSelectHiddenCoin = (coinId) => {
    setSelectedHiddenCoins(prev =>
      prev.includes(coinId)
        ? prev.filter(id => id !== coinId)
        : [...prev, coinId]
    );
  };

  const handleUnhideSelected = async () => {
    if (selectedHiddenCoins.length === 0) {
      setMessage('Please select assets to unhide');
      setMessageType('error');
      return;
    }

    try {
      const response = await axios.post('/api/unhide-all', {
        coin_ids: selectedHiddenCoins
      }, { withCredentials: true });

      if (response.data.success) {
        setMessage('Assets unhidden successfully!');
        setMessageType('success');
        setShowUnhideModal(false);
        setSelectedHiddenCoins([]);
        setSelectAllHidden(false);
        // Refresh the page to show updated data
        window.location.reload();
      } else {
        setMessage(response.data.error || 'Failed to unhide assets');
        setMessageType('error');
      }
    } catch (err) {
      console.error('Unhide assets error:', err);
      setMessage('Failed to unhide assets');
      setMessageType('error');
    }
  };

  return (
    <div className="app-container">
      {/* Message Display */}
      {message && (
        <div className={`message ${messageType}`}>
          {message}
        </div>
      )}

      {/* Navigation */}
      <nav className="nav-container" style={isOnboarding ? { display: 'none' } : undefined}>
        <div className="nav-content" style={{ flexDirection: 'column' }}>
          {user && (
            <div className="nav-links" style={{ width: '100%', justifyContent: 'center' }}>
              {isDashboard ? (
                <div id="navbar-customize-portal" style={{ display: 'inline-flex', alignItems: 'center' }}></div>
              ) : (
                <Link to="/" className="nav-link">
                  📊 Dashboard
                </Link>
              )}
              <div ref={tradingMenuRef} className="nav-menu">
                <button
                  type="button"
                  className="nav-link"
                  aria-haspopup="menu"
                  aria-expanded={showTradingMenu}
                  onClick={() => setShowTradingMenu((shown) => !shown)}
                >
                  📈 Trading ▾
                </button>
                {showTradingMenu && (
                  <div className="nav-menu-popover" role="menu">
                    <Link to="/trading/binance" state={{ resetTradingPair: true }} role="menuitem" onClick={() => setShowTradingMenu(false)}>Binance.US</Link>
                    <Link to="/trading/webull" role="menuitem" onClick={() => setShowTradingMenu(false)}>Webull</Link>
                  </div>
                )}
              </div>
              <Link to="/orders" className="nav-link">
                📋 Orders
              </Link>
              <Link to="/settings" className="nav-link">
                ⚙️ Settings
              </Link>

              <div ref={taxMenuRef} className="nav-menu">
                <button
                  type="button"
                  className="nav-link"
                  aria-haspopup="menu"
                  aria-expanded={showTaxMenu}
                  onClick={() => setShowTaxMenu((shown) => !shown)}
                >
                  📄 Tax Report ▾
                </button>
                {showTaxMenu && (
                  <div className="nav-menu-popover" role="menu">
                    <Link to="/tax-report-binance" role="menuitem" onClick={() => setShowTaxMenu(false)}>Binance.US</Link>
                    <Link to="/tax-report-webull" role="menuitem" onClick={() => setShowTaxMenu(false)}>Webull</Link>
                  </div>
                )}
              </div>

              <button
                onClick={handleUnhideCoins}
                className="nav-link"
              >
                🚫 Unhide Assets
              </button>

              <Link to="/help" className="nav-link">
                ❓ Help
              </Link>

              {/* New theme toggle switch */}
              <button onClick={toggleTheme} className={`theme-switch ${isLightMode ? 'light' : 'dark'}`} aria-label="Toggle theme">
                <span className="track">
                  <span className="thumb" />
                  <span className="icon sun">☀️</span>
                  <span className="icon moon">🌙</span>
                </span>
              </button>

              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginLeft: '12px', padding: '6px 16px 6px 6px', backgroundColor: 'rgba(30, 35, 45, 0.6)', borderRadius: '30px', border: '1px solid rgba(255,255,255,0.1)', flexShrink: 0 }}>
                <div style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '50%',
                  background: 'linear-gradient(135deg, #a855f7, #7e22ce)',
                  color: 'white',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontWeight: 'bold',
                  fontSize: '16px',
                  boxShadow: '0 0 10px rgba(168, 85, 247, 0.5)',
                  flexShrink: 0
                }}>
                  {user.username ? user.username.charAt(0).toUpperCase() : '?'}
                </div>
                <span style={{ fontSize: '14px', color: '#e2e8f0', whiteSpace: 'nowrap' }}>
                  Signed in as <strong style={{ color: 'white', fontWeight: 'bold' }}>{user.username}</strong>
                </span>
              </div>

              <button
                onClick={handleLogout}
                className="nav-link"
              >
                Logout
              </button>
            </div>
          )}
          <div className="brand-logo" aria-label="Crypto & Securities Dashboard">
            <svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" className="brand-icon" aria-hidden="true">
              <circle cx="16" cy="16" r="13" stroke="url(#brand-logo-gradient)" strokeWidth="2.5"/>
              <path d="M8 21L13 16L17 19L24 11" stroke="url(#brand-logo-gradient)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M20 11H24V15" stroke="#00F2FE" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M10 24V21M16 24V19M22 24V15" stroke="#4FACFE" strokeWidth="2.25" strokeLinecap="round"/>
              <defs>
                <linearGradient id="brand-logo-gradient" x1="5" y1="4" x2="27" y2="28" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#00F2FE"/>
                  <stop offset="1" stopColor="#4FACFE"/>
                </linearGradient>
              </defs>
            </svg>
            <span className="brand-logo-wordmark">Crypto &amp; Securities Dashboard</span>
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <div className={isOnboarding ? '' : 'main-content'}>
        <React.Suspense fallback={
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
            <div className="spinner-border text-primary" role="status">
              <span className="visually-hidden">Loading...</span>
            </div>
          </div>
        }>
          <Routes>
            <Route path="/login" element={user ? <Navigate to="/" /> : <Login />} />
            <Route path="/signup" element={user ? <Navigate to="/" /> : <Signup isLightMode={isLightMode} toggleTheme={toggleTheme} />} />
            <Route path="/onboarding" element={user ? (user.onboardingRequired ? <Onboarding isLightMode={isLightMode} toggleTheme={toggleTheme} /> : <Navigate to="/" replace />) : <Navigate to="/login" replace />} />
            <Route path="/" element={
              <ProtectedRoute isLightMode={isLightMode}>
                <Dashboard />
              </ProtectedRoute>
            } />
            <Route path="/trading" element={
              <ProtectedRoute isLightMode={isLightMode}>
                <Trading />
              </ProtectedRoute>
            } />
            <Route path="/trading/binance" element={
              <ProtectedRoute isLightMode={isLightMode}>
                <Trading />
              </ProtectedRoute>
            } />
            <Route path="/trading/webull" element={
              <ProtectedRoute isLightMode={isLightMode}>
                <WebullTrading />
              </ProtectedRoute>
            } />
            <Route path="/webull-trading" element={
              <ProtectedRoute isLightMode={isLightMode}>
                <WebullTrading />
              </ProtectedRoute>
            } />
            <Route path="/orders" element={
              <ProtectedRoute isLightMode={isLightMode}>
                <Orders />
              </ProtectedRoute>
            } />
            <Route path="/ai-analysis" element={
              <Navigate to="/trading/binance?tab=ai-analysis" replace />
            } />
            <Route path="/settings" element={
              <ProtectedRoute isLightMode={isLightMode}>
                <Settings />
              </ProtectedRoute>
            } />
            <Route path="/staking" element={
              <ProtectedRoute isLightMode={isLightMode}>
                <Staking />
              </ProtectedRoute>
            } />

            <Route path="/tax-report" element={
              <ProtectedRoute isLightMode={isLightMode}>
                <TaxReportBinance />
              </ProtectedRoute>
            } />
            <Route path="/tax-report-binance" element={
              <ProtectedRoute isLightMode={isLightMode}>
                <TaxReportBinance />
              </ProtectedRoute>
            } />
            <Route path="/tax-report-webull" element={
              <ProtectedRoute isLightMode={isLightMode}>
                <TaxReportWebull />
              </ProtectedRoute>
            } />
            <Route path="/help" element={
              <ProtectedRoute isLightMode={isLightMode}>
                <Help isLightMode={isLightMode} />
              </ProtectedRoute>
            } />
            <Route path="/privacy" element={<PrivacyPolicy isLightMode={isLightMode} />} />
            <Route path="/terms" element={<TermsOfService isLightMode={isLightMode} />} />
            <Route path="/acceptable-use" element={<AcceptableUse isLightMode={isLightMode} />} />
            <Route path="/risk-disclosure" element={<TradingRiskDisclosure isLightMode={isLightMode} />} />
            <Route path="/support" element={<Support isLightMode={isLightMode} />} />
          </Routes>
        </React.Suspense>
      </div>

      {/* Unhide Assets Modal */}
      {showUnhideModal && (
        <div className="modal-overlay">
          <div className="modal-content" style={{ maxWidth: '520px' }}>
            <div className="modal-header">
              <h3>Unhide Assets</h3>
              <button
                onClick={() => setShowUnhideModal(false)}
                className="modal-close"
              >
                ×
              </button>
            </div>

            <div className="modal-body">
              {hiddenCoins.length === 0 ? (
                <p className="no-data">No hidden assets found.</p>
              ) : (
                <>
                  <div className="select-all-container">
                    <label className="select-all-label">
                      <input
                        type="checkbox"
                        checked={selectAllHidden}
                        onChange={handleSelectAllHidden}
                      />
                      Select All
                    </label>
                  </div>

                  <div className="hidden-coins-list">
                    {hiddenCoins.map(coin => (
                      <div
                        key={coin.id}
                        className="hidden-coin-item"
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '12px',
                          padding: '8px 12px',
                          borderBottom: '1px solid rgba(255, 255, 255, 0.07)'
                        }}
                      >
                        {/* Checkbox */}
                        <input
                          type="checkbox"
                          checked={selectedHiddenCoins.includes(coin.id)}
                          onChange={() => handleSelectHiddenCoin(coin.id)}
                        />

                        {/* Column 1: Asset Symbol & ETF Identity */}
                        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', minWidth: '80px' }}>
                          <span className="coin-symbol" style={{ fontWeight: '700', fontSize: '0.95rem' }}>
                            {coin.symbol}
                          </span>
                          {coin.is_etf && (
                            <span
                              className="etf-badge"
                              title="Exchange Traded Fund (ETF)"
                              style={{
                                fontSize: '0.68rem',
                                padding: '1px 5px',
                                borderRadius: '4px',
                                background: 'rgba(56, 189, 248, 0.22)',
                                color: '#38bdf8',
                                fontWeight: '700',
                                border: '1px solid rgba(56, 189, 248, 0.4)',
                                letterSpacing: '0.04em'
                              }}
                            >
                              ETF
                            </span>
                          )}
                        </div>

                        {/* Column 2: Exchange / Source Badge */}
                        <div style={{ display: 'inline-flex', alignItems: 'center' }}>
                          {coin.source_label && (
                            <span
                              className="coin-source-badge"
                              style={{
                                fontSize: '0.75rem',
                                padding: '2px 8px',
                                borderRadius: '4px',
                                background: coin.source === 'webull' ? 'rgba(56, 189, 248, 0.18)' : 'rgba(234, 179, 8, 0.18)',
                                color: coin.source === 'webull' ? '#38bdf8' : '#eab308',
                                fontWeight: '600'
                              }}
                            >
                              {coin.source_label}
                            </span>
                          )}
                        </div>

                        {/* Column 3: Asset / Account Type Blue Pill */}
                        <div style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center' }}>
                          <span
                            className="webull-account-pill"
                            title={coin.source === 'binance' ? 'Binance Cryptocurrency' : `Webull ${coin.webull_account_type || 'Account'}`}
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              padding: '2px 8px',
                              borderRadius: '9999px',
                              fontSize: '0.72rem',
                              fontWeight: 600,
                              letterSpacing: '0.02em',
                              whiteSpace: 'nowrap',
                              background: isLightMode ? '#000000' : '#2563eb',
                              color: isLightMode ? '#facc15' : '#ffffff',
                              border: isLightMode ? '1px solid #1f2937' : '1px solid #3b82f6',
                            }}
                          >
                            {coin.source === 'binance' ? 'Crypto' : (coin.webull_account_type || (coin.instrument_type === 'CASH' ? 'USD Cash' : 'Webull'))}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="modal-actions">
                    <button
                      onClick={() => setShowUnhideModal(false)}
                      className="btn btn-secondary"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleUnhideSelected}
                      disabled={selectedHiddenCoins.length === 0}
                      className={`btn ${selectedHiddenCoins.length === 0 ? 'btn-disabled' : 'btn-primary'}`}
                    >
                      Unhide Selected ({selectedHiddenCoins.length})
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* AI Copilot Sidebar */}
      {!isOnboarding && <AICopilotSidebar />}

      {/* Footer with Legal Links */}
      <footer style={{
        display: isOnboarding ? 'none' : undefined,
        textAlign: 'center',
        padding: '20px',
        borderTop: `1px solid ${isLightMode ? '#dee2e6' : '#2d3748'}`,
        marginTop: '40px',
        backgroundColor: isLightMode ? '#f8f9fa' : '#0f0f23'
      }}>
        <div style={{
          display: 'flex',
          justifyContent: 'center',
          gap: '24px',
          flexWrap: 'wrap',
          marginBottom: '12px'
        }}>
          <Link to="/privacy" style={{ color: '#4da6ff', textDecoration: 'none', fontSize: '14px' }}>
            Privacy Policy
          </Link>
          <Link to="/terms" style={{ color: '#4da6ff', textDecoration: 'none', fontSize: '14px' }}>
            Terms of Service
          </Link>
          <Link to="/acceptable-use" style={{ color: '#4da6ff', textDecoration: 'none', fontSize: '14px' }}>
            Acceptable Use
          </Link>
          <Link to="/risk-disclosure" style={{ color: '#4da6ff', textDecoration: 'none', fontSize: '14px' }}>
            Trading Risk Disclosures
          </Link>
          <Link to="/support" style={{ color: '#4da6ff', textDecoration: 'none', fontSize: '14px' }}>
            Support
          </Link>
        </div>
        <p style={{
          color: isLightMode ? '#6c757d' : '#adb5bd',
          fontSize: '12px',
          margin: 0
        }}>
          Crypto &amp; Securities Dashboard version {APP_VERSION}. © 2026 Cavallaro Services, LLC. All rights reserved.
        </p>
      </footer>

      {/* Global Toast Notifications */}
      <ToastNotifications isLightMode={isLightMode} />
    </div>
  );
}
