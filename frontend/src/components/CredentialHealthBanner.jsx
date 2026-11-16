import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';

// Shows any broker whose API credentials were rejected repeatedly and whose
// background sync the server has paused, with a way to retry immediately.
export default function CredentialHealthBanner() {
  const [providers, setProviders] = useState({});
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    if (document.hidden) return;
    try {
      const { data } = await axios.get('/api/credential-health', { withCredentials: true });
      setProviders(data?.providers || {});
    } catch {
      // Not signed in or offline: show nothing rather than a misleading banner.
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 60000);
    return () => clearInterval(timer);
  }, [load]);

  const resume = async (provider) => {
    setBusy(provider);
    try {
      await axios.post(`/api/credential-health/${provider}/resume`, {}, { withCredentials: true });
      await load();
    } finally {
      setBusy('');
    }
  };

  const paused = Object.entries(providers).filter(([, info]) => info.paused);
  if (!paused.length) return null;
  return (
    <div role="alert" style={{ margin: '12px 16px 0', padding: '12px 16px', borderRadius: 8, border: '1px solid #f56565', background: 'rgba(245, 101, 101, 0.12)', color: 'var(--text-primary, #fed7d7)' }}>
      {paused.map(([provider, info]) => (
        <div key={provider} style={{ display: 'flex', gap: 12, alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <span>
            <strong>{info.label} sync is paused.</strong> Its API credentials were rejected {info.consecutive_failures} times in a row
            {info.last_error ? ` (${info.last_error})` : ''}. Fix the keys in <Link to="/settings">Settings</Link>; syncing resumes when they work.
          </span>
          <button className="btn btn-secondary" disabled={busy === provider} onClick={() => resume(provider)}>
            {busy === provider ? 'Retrying…' : 'Retry now'}
          </button>
        </div>
      ))}
    </div>
  );
}
