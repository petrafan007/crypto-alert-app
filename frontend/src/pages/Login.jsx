import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../components/AuthContext';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [twoFactorCode, setTwoFactorCode] = useState('');
  const [requires2FA, setRequires2FA] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();
  const { login } = useAuth();

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');

    if (requires2FA && twoFactorCode.length !== 6) {
      setError('Please enter your 6-digit authentication code.');
      return;
    }

    setLoading(true);

    try {
      const result = await login(username, password, twoFactorCode);
      if (result.success) {
        navigate('/');
      } else if (result.requires_2fa) {
        setRequires2FA(true);
        if (result.error) {
          setError(result.error);
        }
      } else {
        setError(result.error || 'Login failed. Please check your credentials.');
      }
    } catch (err) {
      setError('An unexpected error occurred. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      padding: '40px 24px',
      maxWidth: 400,
      margin: '40px auto',
      background: '#232b31',
      borderRadius: 12,
      boxShadow: '0 8px 32px rgba(0,0,0,0.3)'
    }}>
      <h2 style={{
        textAlign: 'center',
        marginBottom: 32,
        color: '#fff',
        fontSize: '2rem',
        fontWeight: 600
      }}>
        Login to Crypto &amp; Securities Dashboard
      </h2>

      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: 20 }}>
          <label style={{
            display: 'block',
            marginBottom: 8,
            color: '#fff',
            fontWeight: 500
          }}>
            Username
          </label>
          <input
            type="text"
            value={username}
            onChange={e => setUsername(e.target.value)}
            required
            disabled={requires2FA}
            style={{
              width: '100%',
              padding: '12px 16px',
              borderRadius: 8,
              border: '1px solid #444',
              background: requires2FA ? '#14181b' : '#1a1f23',
              color: '#fff',
              fontSize: '16px',
              boxSizing: 'border-box'
            }}
            placeholder="Enter your username"
          />
        </div>

        <div style={{ marginBottom: requires2FA ? 20 : 24 }}>
          <label style={{
            display: 'block',
            marginBottom: 8,
            color: '#fff',
            fontWeight: 500
          }}>
            Password
          </label>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            disabled={requires2FA}
            style={{
              width: '100%',
              padding: '12px 16px',
              borderRadius: 8,
              border: '1px solid #444',
              background: requires2FA ? '#14181b' : '#1a1f23',
              color: '#fff',
              fontSize: '16px',
              boxSizing: 'border-box'
            }}
            placeholder="Enter your password"
          />
        </div>

        {requires2FA && (
          <div style={{ marginBottom: 24, animation: 'fadeIn 0.2s ease-in' }}>
            <label style={{
              display: 'block',
              marginBottom: 8,
              color: '#38bdf8',
              fontWeight: 600
            }}>
              🔐 6-digit Two-Factor Code
            </label>
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              maxLength="6"
              value={twoFactorCode}
              onChange={e => setTwoFactorCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              required
              autoFocus
              style={{
                width: '100%',
                padding: '12px 16px',
                borderRadius: 8,
                border: '1px solid #38bdf8',
                background: '#1a1f23',
                color: '#fff',
                fontSize: '20px',
                letterSpacing: '4px',
                textAlign: 'center',
                boxSizing: 'border-box',
                boxShadow: '0 0 10px rgba(56, 189, 248, 0.25)'
              }}
              placeholder="000000"
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
              <span style={{ color: '#94a3b8', fontSize: '12px' }}>Enter code from authenticator app</span>
              <button
                type="button"
                onClick={() => { setRequires2FA(false); setTwoFactorCode(''); setError(''); }}
                style={{ background: 'none', border: 'none', color: '#94a3b8', fontSize: '12px', cursor: 'pointer', textDecoration: 'underline' }}
              >
                Back
              </button>
            </div>
          </div>
        )}

        <button
          type="submit"
          disabled={loading || (requires2FA && twoFactorCode.length !== 6)}
          style={{
            width: '100%',
            padding: '14px 16px',
            borderRadius: 8,
            border: 'none',
            background: loading ? '#666' : (requires2FA ? '#0284c7' : '#4fd1c5'),
            color: '#fff',
            fontSize: '16px',
            fontWeight: 600,
            cursor: loading ? 'not-allowed' : 'pointer',
            transition: 'background 0.2s'
          }}
        >
          {loading ? 'Verifying...' : (requires2FA ? 'Verify & Login' : 'Login')}
        </button>

        {error && (
          <div style={{
            color: '#f56565',
            marginTop: 16,
            padding: '12px 16px',
            background: 'rgba(245, 101, 101, 0.1)',
            borderRadius: 8,
            border: '1px solid rgba(245, 101, 101, 0.3)',
            textAlign: 'center'
          }}>
            {error}
          </div>
        )}
      </form>

      <div style={{ marginTop: 24, textAlign: 'center' }}>
        <span style={{ color: '#aaa' }}>New user? </span>
        <Link to="/signup" style={{ color: '#4fd1c5', textDecoration: 'none', fontWeight: 500 }}>Create New Account</Link>
      </div>
    </div>
  );
}
