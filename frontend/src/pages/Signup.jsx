import React, { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../components/AuthContext';
import './Onboarding.css';
import './Signup.css';

export default function Signup({ isLightMode, toggleTheme }) {
  const [form, setForm] = useState({ username: '', email: '', password: '', confirm: '', accepted: false });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { checkAuthStatus } = useAuth();
  const rules = useMemo(() => ({
    length: form.password.length >= 12,
    upper: /[A-Z]/.test(form.password), lower: /[a-z]/.test(form.password),
    number: /\d/.test(form.password), special: /[^A-Za-z0-9]/.test(form.password),
    match: Boolean(form.password) && form.password === form.confirm,
  }), [form.password, form.confirm]);
  const valid = Object.values(rules).every(Boolean) && form.username.trim().length >= 3 && /\S+@\S+\.\S+/.test(form.email) && form.accepted;
  const update = (field, value) => setForm(prev => ({ ...prev, [field]: value }));
  const submit = async event => {
    event.preventDefault(); setError('');
    if (!valid) { setError('Complete every required field and password requirement.'); return; }
    setLoading(true);
    try {
      const { data } = await axios.post('/register', { username: form.username.trim(), email: form.email.trim(), password: form.password, accepted_terms: form.accepted });
      await checkAuthStatus(); navigate(data.redirect || '/onboarding', { replace: true });
    } catch (err) { setError(err.response?.data?.error || 'Registration failed. Please try again.'); }
    finally { setLoading(false); }
  };
  return <div className="signup-page"><header className="ob-header"><svg className="ob-brand-icon" viewBox="0 0 32 32"><circle cx="16" cy="16" r="13" fill="none" stroke="currentColor" strokeWidth="2.4"/><path d="M8 21l5-5 4 3 7-8M20 11h4v4" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"/></svg><span><strong>Crypto &amp; Securities Dashboard</strong><small>CSDapp.online</small></span><button className="ob-theme" onClick={toggleTheme} type="button"><span>{isLightMode ? '☀' : '☾'}</span>{isLightMode ? 'Light' : 'Dark'}</button></header><main className="signup-main"><section className="signup-card"><div className="signup-heading"><small>Step 1 of 6</small><h1>Create your account</h1><p>Start with secure sign-in credentials. Setup progress will be saved after your account is created.</p></div>{error&&<div className="ob-notice error">{error}</div>}<form onSubmit={submit}><div className="ob-grid"><label className="ob-field"><span>Username</span><input value={form.username} onChange={e=>update('username',e.target.value)} autoComplete="username" required/><small>Between 3 and 80 characters.</small></label><label className="ob-field"><span>Email address</span><input type="email" value={form.email} onChange={e=>update('email',e.target.value)} autoComplete="email" required/><small>Used for recovery and security notices.</small></label><label className="ob-field"><span>Password</span><input type="password" value={form.password} onChange={e=>update('password',e.target.value)} autoComplete="new-password" required/></label><label className="ob-field"><span>Confirm password</span><input type="password" value={form.confirm} onChange={e=>update('confirm',e.target.value)} autoComplete="new-password" required/></label></div><div className="signup-rules">{[['length','At least 12 characters'],['upper','One uppercase letter'],['lower','One lowercase letter'],['number','One number'],['special','One special character'],['match','Passwords match']].map(([key,label])=><span className={rules[key]?'met':''} key={key}>{rules[key]?'✓':'○'} {label}</span>)}</div><label className="signup-accept"><input type="checkbox" checked={form.accepted} onChange={e=>update('accepted',e.target.checked)}/><span>I agree to the <Link to="/terms">Terms of Service</Link>, <Link to="/privacy">Privacy Policy</Link>, <Link to="/acceptable-use">Acceptable Use Policy</Link>, and trading-risk disclosures.</span></label><div className="signup-actions"><Link to="/login">Sign in instead</Link><button className="ob-button primary" disabled={loading||!valid}>{loading?'Creating Account…':'Create Account & Continue'}</button></div></form></section></main></div>;
}
