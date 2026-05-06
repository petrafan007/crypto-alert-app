import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../components/AuthContext';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();
  const { login } = useAuth();

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const result = await login(username, password);
      if (result.success) {
        navigate('/');
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
        Login to Crypto Dashboard
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
            style={{
              width: '100%',
              padding: '12px 16px',
              borderRadius: 8,
              border: '1px solid #444',
              background: '#1a1f23',
              color: '#fff',
              fontSize: '16px',
              boxSizing: 'border-box'
            }}
            placeholder="Enter your username"
          />
        </div>

        <div style={{ marginBottom: 24 }}>
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
            style={{
              width: '100%',
              padding: '12px 16px',
              borderRadius: 8,
              border: '1px solid #444',
              background: '#1a1f23',
              color: '#fff',
              fontSize: '16px',
              boxSizing: 'border-box'
            }}
            placeholder="Enter your password"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          style={{
            width: '100%',
            padding: '14px 16px',
            borderRadius: 8,
            border: 'none',
            background: loading ? '#666' : '#4fd1c5',
            color: '#fff',
            fontSize: '16px',
            fontWeight: 600,
            cursor: loading ? 'not-allowed' : 'pointer',
            transition: 'background 0.2s'
          }}
        >
          {loading ? 'Logging in...' : 'Login'}
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
