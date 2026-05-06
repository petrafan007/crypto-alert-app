import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../components/AuthContext';

const Signup = () => {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const navigate = useNavigate();
    const { checkAuthStatus } = useAuth();

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');

        if (password !== confirmPassword) {
            setError("Passwords do not match");
            return;
        }

        if (password.length < 4) {
            setError("Password must be at least 4 characters");
            return;
        }

        setLoading(true);

        try {
            const response = await axios.post('/register', {
                username,
                password
            });

            console.log("Registration response:", response);

            if (response.data.success) {
                // Attempt to refresh auth state, but don't block success if it fails
                try {
                    if (typeof checkAuthStatus === 'function') {
                        await checkAuthStatus();
                    } else {
                        console.warn('checkAuthStatus is not a function in Signup.jsx');
                    }
                } catch (authErr) {
                    console.error('Failed to refresh auth status:', authErr);
                    // Continue anyway because registration was successful
                }

                // Redirect to settings with new_user flag
                navigate(response.data.redirect || '/settings');
            }
        } catch (err) {
            console.error("Registration error object:", err);
            const errMsg = err.response?.data?.error || err.message || "Registration failed. Please try again.";
            setError(errMsg);
        } finally {
            setLoading(false);
        }
    };

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
                Create Account
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
                        onChange={(e) => setUsername(e.target.value)}
                        required
                        placeholder="Choose a username"
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
                    />
                </div>

                <div style={{ marginBottom: 20 }}>
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
                        onChange={(e) => setPassword(e.target.value)}
                        required
                        placeholder="Create password"
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
                    />
                </div>

                <div style={{ marginBottom: 24 }}>
                    <label style={{
                        display: 'block',
                        marginBottom: 8,
                        color: '#fff',
                        fontWeight: 500
                    }}>
                        Confirm Password
                    </label>
                    <input
                        type="password"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        required
                        placeholder="Confirm password"
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
                    {loading ? 'Creating Account...' : 'Sign Up'}
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
                <span style={{ color: '#aaa' }}>Already have an account? </span>
                <Link to="/login" style={{ color: '#4fd1c5', textDecoration: 'none', fontWeight: 500 }}>Login here</Link>
            </div>
        </div>
    );
};

export default Signup;
