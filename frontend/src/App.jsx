import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, Link } from 'react-router-dom';
import { useAuth } from './components/AuthContext';
import axios from 'axios';
import Dashboard from './pages/Dashboard';
import Login from './pages/Login';
import Signup from './pages/Signup';
import TradingNew from './pages/TradingNew';
import Settings from './pages/Settings';
import AIDashboard from './pages/AIDashboard';
import AICopilotSidebar from './components/AICopilotSidebar';
import Staking from './pages/Staking';
import TaxReport from './pages/TaxReport';
import Help from './pages/Help';
import PrivacyPolicy from './pages/PrivacyPolicy';
import TermsOfService from './pages/TermsOfService';
import AcceptableUse from './pages/AcceptableUse';
import Support from './pages/Support';
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
  const navigate = useLocation(); // Changed from useNavigate to useLocation
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState('');
  const [showUnhideModal, setShowUnhideModal] = useState(false);
  const [hiddenCoins, setHiddenCoins] = useState([]);
  const [selectedHiddenCoins, setSelectedHiddenCoins] = useState([]);
  const [selectAllHidden, setSelectAllHidden] = useState(false);
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



  // Unhide Coins functionality
  const handleUnhideCoins = async () => {
    try {
      const response = await axios.get('/api/hidden-coins', { withCredentials: true });
      setHiddenCoins(response.data || []);
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
        <div className="nav-content">
          <Link to="/" className="nav-brand">
            Crypto Alert App
          </Link>

          {user && (
            <div className="nav-links">
              <Link to="/" className="nav-link">
                📊 Dashboard
              </Link>
              <Link to="/ai-analysis" className="nav-link">
                🤖 AI Analysis
              </Link>
              <Link to="/trading" className="nav-link">
                📈 Trading
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
                <TradingNew />
              </ProtectedRoute>
            } />
            <Route path="/ai-analysis" element={
              <ProtectedRoute isLightMode={isLightMode}>
                <AIDashboard />
              </ProtectedRoute>
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
          © 2026 Crypto Alert App. All rights reserved.
        </p>
      </footer>

      {/* OAuth Modal - REMOVED - This was causing duplicate modals */}
    </div>
  );
}
