import React, { useState } from 'react';
import axios from 'axios';
import TotpCodeInput from './TotpCodeInput';

export default function StakingPurchaseModal({ asset, balances, settings, userId, onClose, onComplete, savedReceipt }) {
  const quotes = (asset?.quoteAssets || []).filter(quote => balances[quote]?.balance > 1);
  const [quote, setQuote] = useState(quotes[0] || 'USDT');
  const [amount, setAmount] = useState('');
  const [stake, setStake] = useState(true);
  const [autoRestake, setAutoRestake] = useState(true);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(savedReceipt || null);
  const [intentId, setIntentId] = useState(savedReceipt?.id || null);
  const requires2FA = settings.require_2fa && settings.totp_enabled;
  const refreshReceipt = async () => {
    setBusy(true); setError('');
    try {
      const response = await axios.get(`/api/staking/purchases/${intentId}`);
      setResult(response.data);
      onComplete();
    } catch (err) { setError(err.response?.data?.error || 'Receipt unavailable. Check Binance history before placing another order.'); }
    finally { setBusy(false); }
  };
  const submit = async event => {
    event.preventDefault();
    if (busy || intentId) return;
    setBusy(true); setError('');
    let id;
    try {
      let token;
      if (requires2FA) token = (await axios.post('/api/trading/2fa/verify', { code })).data.token;
      if (requires2FA && !token) throw new Error('2FA verification failed.');
      id = crypto.randomUUID();
      setIntentId(id);
      sessionStorage.setItem(`stakingPurchase:${userId}`, id);
      const response = await axios.post('/api/staking/purchases', {
        id, asset: asset.stakingAsset, quoteAsset: quote, quoteAmount: amount, stake, autoRestake, twofa_token: token,
      });
      setResult(response.data);
      onComplete();
    } catch (err) {
      // A definite validation rejection has no exchange side effect. A timeout stays locked to its receipt.
      if (err.response?.status === 400 || err.response?.status === 403) {
        setIntentId(null);
        sessionStorage.removeItem(`stakingPurchase:${userId}`);
      }
      setError(err.response?.data?.error || err.message || 'Confirmation unavailable. Check the saved receipt before trading again.');
    } finally { setBusy(false); }
  };
  return <div className="modal-overlay"><div className="modal-content" role="dialog" aria-modal="true" aria-label="Purchase to stake" style={{ maxWidth: 540, padding: 24 }}>
    <h2>{result ? 'Purchase receipt' : `Trade ${asset?.stakingAsset}`}</h2>
    {error && <p role="alert">{error}</p>}
    {result ? <>
      <p>{result.message || `Status: ${result.status}. Check Binance history before submitting another request.`}</p>
      <p>Reference: {result.id}</p>
      {result.purchasedQuantity && <p>Purchased: {result.purchasedQuantity} {result.asset}</p>}
      {result.stakeQuantity && <p>Staking request: {result.stakeQuantity} {result.asset}</p>}
    </> : <form onSubmit={submit}>
      <label>Payment currency <select value={quote} onChange={event => setQuote(event.target.value)} disabled={busy || !!intentId}>
        {quotes.map(value => <option key={value} value={value}>Buy with {value}</option>)}
      </select></label>
      <p>Free balance: {(balances[quote]?.balance || 0).toFixed(2)} {quote}</p>
      <label>Spend <input aria-label="Purchase amount" type="number" min="1.01" step="0.01" required value={amount} onChange={event => setAmount(event.target.value)} disabled={busy || !!intentId} /></label>
      <label style={{ display: 'block', margin: '16px 0' }}><input type="checkbox" checked={stake} onChange={event => setStake(event.target.checked)} disabled={busy || !!intentId} /> Stake purchased coins immediately</label>
      {stake && <label style={{ display: 'block', margin: '16px 0' }}><input type="checkbox" checked={autoRestake} onChange={event => setAutoRestake(event.target.checked)} disabled={busy || !!intentId} /> Automatically restake rewards (APY assumes compounding)</label>}
      <p>Estimated {asset?.rateLabel || 'APY'}: {((asset?.apy || 0) * 100).toFixed(2)}%. Rates vary. Minimum stake: {asset?.minStakingLimit} {asset?.stakingAsset}. Unstaking period: {asset?.unstakingPeriod} hours.</p>
      <p>This places a real market purchase. Trading fees apply; leave 1% of your balance available. If staking fails, the purchased coins remain in your account. Bonding can delay rewards.</p>
      {requires2FA && <label>Authenticator code <TotpCodeInput aria-label="Authenticator code" value={code} onChange={event => setCode(event.target.value)} required disabled={busy || !!intentId} /></label>}
      <button className="btn-stake" type="submit" disabled={busy || !!intentId || !quotes.length}>{busy ? 'Processing…' : stake ? 'Confirm purchase and stake' : 'Confirm purchase'}</button>
    </form>}
    {intentId && <button type="button" onClick={refreshReceipt} disabled={busy}>Refresh receipt</button>}
    <button type="button" onClick={onClose} disabled={busy}>Close</button>
  </div></div>;
}
