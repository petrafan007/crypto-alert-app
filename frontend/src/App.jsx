import React, { useState, useEffect, useRef } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, Link } from 'react-router-dom';
import { useAuth } from './components/AuthContext';
import axios from 'axios';
import Dashboard from './pages/Dashboard';
import Login from './pages/Login';
import Signup from './pages/Signup';
import Trading from './pages/Trading';
import WebullTrading from './pages/WebullTrading';
import Orders from './pages/Orders';
import Settings from './pages/Settings';
import AICopilotSidebar from './components/AICopilotSidebar';
import Staking from './pages/Staking';
import TaxReport from './pages/TaxReport';
import Help from './pages/Help';
import PrivacyPolicy from './pages/PrivacyPolicy';
import TermsOfService from './pages/TermsOfService';
import AcceptableUse from './pages/AcceptableUse';
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
  return user ? React.cloneElement(children, { isLightMode }) : <Navigate to="/login" />;
}

export default function App() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const isDashboard = location.pathname === '/';
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState('');
  const [showUnhideModal, setShowUnhideModal] = useState(false);
  const [hiddenCoins, setHiddenCoins] = useState([]);
  const [selectedHiddenCoins, setSelectedHiddenCoins] = useState([]);
  const [selectAllHidden, setSelectAllHidden] = useState(false);
  const [showTradingMenu, setShowTradingMenu] = useState(false);
  const tradingMenuRef = useRef(null);
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
    if (!showTradingMenu) return undefined;
    const dismiss = (event) => {
      if (tradingMenuRef.current && !tradingMenuRef.current.contains(event.target)) {
        setShowTradingMenu(false);
      }
    };
    const dismissOnEscape = (event) => {
      if (event.key === 'Escape') setShowTradingMenu(false);
    };
    document.addEventListener('mousedown', dismiss);
    document.addEventListener('keydown', dismissOnEscape);
    return () => {
      document.removeEventListener('mousedown', dismiss);
      document.removeEventListener('keydown', dismissOnEscape);
    };
  }, [showTradingMenu]);



  // Unhide Coins functionality
  const handleUnhideCoins = async () => {
    try {
      const response = await axios.get('/api/hidden-coins', { withCredentials: true });
      setHiddenCoins((response.data || []).filter(coin => coin?.id && String(coin.symbol || '').trim()));
      setShowUnhideModal(true);
    } catch (err) {
      console.error('Failed to fetch hidden coins:', err);
      setMessage('Failed to load hidden coins');
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
      setMessage('Please select coins to unhide');
      setMessageType('error');
      return;
    }

    try {
      const response = await axios.post('/api/unhide-all', {
        coin_ids: selectedHiddenCoins
      }, { withCredentials: true });

      if (response.data.success) {
        setMessage('Coins unhidden successfully!');
        setMessageType('success');
        setShowUnhideModal(false);
        setSelectedHiddenCoins([]);
        setSelectAllHidden(false);
        // Refresh the page to show updated data
        window.location.reload();
      } else {
        setMessage(response.data.error || 'Failed to unhide coins');
        setMessageType('error');
      }
    } catch (err) {
      console.error('Unhide coins error:', err);
      setMessage('Failed to unhide coins');
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
      <nav className="nav-container">
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
              <Link to="/staking" className="nav-link">
                💰 Staking
              </Link>
              <Link to="/settings" className="nav-link">
                ⚙️ Settings
              </Link>

              <Link to="/tax-report" className="nav-link">
                📄 Tax Report
              </Link>

              <button
                onClick={handleUnhideCoins}
                className="nav-link"
              >
                🚫 Unhide Coins
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

              <button
                onClick={handleLogout}
                className="nav-link"
              >
                Logout
              </button>
            </div>
          )}
          <div className="brand-logo">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className="brand-icon">
              <path d="M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="url(#logo-grad)" strokeWidth="2" strokeLinecap="round"/>
              <path d="M12 7V12L15 15" stroke="url(#logo-grad)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M12 2L12 4" stroke="#4FACFE" strokeWidth="2" strokeLinecap="round"/>
              <path d="M12 20L12 22" stroke="#00F2FE" strokeWidth="2" strokeLinecap="round"/>
              <path d="M22 12L20 12" stroke="#4FACFE" strokeWidth="2" strokeLinecap="round"/>
              <path d="M4 12L2 12" stroke="#00F2FE" strokeWidth="2" strokeLinecap="round"/>
              <defs>
                <linearGradient id="logo-grad" x1="3" y1="3" x2="21" y2="21" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#00F2FE"/>
                  <stop offset="1" stopColor="#4FACFE"/>
                </linearGradient>
              </defs>
            </svg>
            <span>Crypto Alert App</span>
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <div className="main-content">
        <React.Suspense fallback={
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
            <div className="spinner-border text-primary" role="status">
              <span className="visually-hidden">Loading...</span>
            </div>
          </div>
        }>
          <Routes>
            <Route path="/login" element={user ? <Navigate to="/" /> : <Login />} />
            <Route path="/signup" element={user ? <Navigate to="/" /> : <Signup />} />
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
                <TaxReport />
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
            <Route path="/support" element={<Support isLightMode={isLightMode} />} />
          </Routes>
        </React.Suspense>
      </div>

      {/* Unhide Coins Modal */}
      {showUnhideModal && (
        <div className="modal-overlay">
          <div className="modal-content">
            <div className="modal-header">
              <h3>Unhide Coins</h3>
              <button
                onClick={() => setShowUnhideModal(false)}
                className="modal-close"
              >
                ×
              </button>
            </div>

            <div className="modal-body">
              {hiddenCoins.length === 0 ? (
                <p className="no-data">No hidden coins found.</p>
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
                      <div key={coin.id} className="hidden-coin-item">
                        <input
                          type="checkbox"
                          checked={selectedHiddenCoins.includes(coin.id)}
                          onChange={() => handleSelectHiddenCoin(coin.id)}
                        />
                        <span className="coin-symbol">{coin.symbol}</span>
                        <span className="coin-name">{coin.name || ''}</span>
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
      <AICopilotSidebar />

      {/* Footer with Legal Links */}
      <footer style={{
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
          <Link to="/support" style={{ color: '#4da6ff', textDecoration: 'none', fontSize: '14px' }}>
            Support
          </Link>
        </div>
        <p style={{
          color: isLightMode ? '#6c757d' : '#adb5bd',
          fontSize: '12px',
          margin: 0
        }}>
          Crypto Alert App version {APP_VERSION}. © 2026 Cavallaro Services. All rights reserved.
        </p>
      </footer>

      {/* Global Toast Notifications */}
      <ToastNotifications isLightMode={isLightMode} />
    </div>
  );
}
