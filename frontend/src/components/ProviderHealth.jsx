import React, { useEffect, useState } from 'react';
import axios from 'axios';

export default function ProviderHealth() {
  const [blocks, setBlocks] = useState(null);
  const [error, setError] = useState('');
  const refresh = async () => {
    try {
      const { data } = await axios.get('/api/provider-health');
      setBlocks(data.blocks);
      setError('');
    } catch { setError('Provider status is unavailable.'); }
  };
  useEffect(() => { refresh(); }, []);
  return <div className="settings-page-section">
    <h3>Provider availability</h3>
    <p>Recent AI and search failures pause requests until the retry time. This does not test subscriptions or guarantee provider access.</p>
    <button type="button" onClick={refresh}>Refresh provider status</button>
    {error && <p role="alert">{error}</p>}
    {blocks?.length === 0 && <p>No provider cooldowns are currently recorded.</p>}
    {blocks?.map((row, index) => <p key={index}><strong>{row.service}</strong>: {row.reason}. Retry after {new Date(row.retry_at).toLocaleString()}.</p>)}
  </div>;
}
