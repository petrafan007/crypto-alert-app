import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import './ConvertDustModal.css';

const TO_ASSET_OPTIONS = ['BNB', 'BTC', 'ETH', 'USDT'];

export default function ConvertDustModal({ isVisible, onClose, require2fa, onSuccess }) {
  const [toAsset, setToAsset] = useState('BNB');
  const [assets, setAssets] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [withinRestrictedTime, setWithinRestrictedTime] = useState(false);
  const [loadingAssets, setLoadingAssets] = useState(false);
  const [converting, setConverting] = useState(false);
  const [twoFaCode, setTwoFaCode] = useState('');
  const [error, setError] = useState('');

  /* ── fetch eligible assets whenever toAsset changes or modal opens ── */
  const fetchAssets = useCallback(async () => {
    if (!isVisible) return;
    setLoadingAssets(true);
    setError('');
    setAssets([]);
    setSelected(new Set());
    try {
      const res = await axios.get(`/api/dust/assets?toAsset=${toAsset}`, {
        withCredentials: true,
      });
      if (res.data.success) {
        const data = res.data.data;
        const list = data.convertibleAssets || [];
        setAssets(list);
        setWithinRestrictedTime(data.withinRestrictedTime === true);
        // Pre-select all by default
        setSelected(new Set(list.map((a) => a.fromAsset)));
      } else {
        setError(res.data.error || 'Failed to load convertible assets.');
      }
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Error loading assets.');
    } finally {
      setLoadingAssets(false);
    }
  }, [isVisible, toAsset]);

  useEffect(() => {
    fetchAssets();
  }, [fetchAssets]);

  /* ── reset 2FA code on re-open ── */
  useEffect(() => {
    if (isVisible) {
      setTwoFaCode('');
      setError('');
    }
  }, [isVisible]);

  /* ── helpers ── */
  const toggleAsset = (fromAsset) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(fromAsset) ? next.delete(fromAsset) : next.add(fromAsset);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === assets.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(assets.map((a) => a.fromAsset)));
    }
  };

  /* ── totals for selected rows ── */
  const selectedAssets = assets.filter((a) => selected.has(a.fromAsset));
  const totalReceived = selectedAssets.reduce(
    (sum, a) => sum + parseFloat(a.receivedAsset || 0),
    0
  );
  const totalFee = selectedAssets.reduce(
    (sum, a) => sum + parseFloat(a.conversionFee || 0),
    0
  );
  const totalUsd = selectedAssets.reduce(
    (sum, a) => sum + parseFloat(a.usdValueConvertedAsset || 0),
    0
  );

  /* ── submit ── */
  const handleConvert = async () => {
    if (selected.size === 0) {
      setError('Please select at least one asset to convert.');
      return;
    }
    if (require2fa && twoFaCode.length !== 6) {
      setError('Please enter your 6-digit 2FA code.');
      return;
    }

    setConverting(true);
    setError('');

    try {
      let twofaToken = null;

      // 1. Verify 2FA if required
      if (require2fa) {
        const verifyRes = await axios.post(
          '/api/trading/2fa/verify',
          { code: twoFaCode },
          { withCredentials: true }
        );
        if (!verifyRes.data.success) {
          throw new Error(verifyRes.data.error || '2FA verification failed');
        }
        twofaToken = verifyRes.data.token;
      }

      // 2. Execute dust conversion
      const payload = {
        fromAssets: Array.from(selected),
        toAsset,
        ...(twofaToken ? { twofa_token: twofaToken } : {}),
      };

      const res = await axios.post('/api/dust/convert', payload, {
        withCredentials: true,
      });

      if (res.data.success) {
        onSuccess && onSuccess(res.data.data, toAsset);
        onClose();
      } else {
        setError(res.data.error || 'Conversion failed. Please try again.');
      }
    } catch (err) {
      setError(err.response?.data?.error || err.message || 'Conversion failed.');
    } finally {
      setConverting(false);
    }
  };

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget && !converting) onClose();
  };

  const canConvert =
    !withinRestrictedTime && selected.size > 0 && !converting && !loadingAssets;

  if (!isVisible) return null;

  return (
    <div className="dust-modal-backdrop" onClick={handleBackdropClick}>
      <div className="dust-modal" role="dialog" aria-modal="true" aria-label="Convert Small Balances">
        {/* ── Header ── */}
        <div className="dust-modal-header">
          <h3>🪙 Convert Small Balances</h3>
          {!converting && (
            <button className="dust-modal-close" onClick={onClose} aria-label="Close">
              ×
            </button>
          )}
        </div>

        {/* ── Body ── */}
        <div className="dust-modal-body">

          {/* Section 1 — Target asset */}
          <div>
            <div className="dust-section-label">Convert into</div>
            <div className="dust-target-group">
              {TO_ASSET_OPTIONS.map((opt) => (
                <button
                  key={opt}
                  className={`dust-target-btn${toAsset === opt ? ' active' : ''}`}
                  onClick={() => setToAsset(opt)}
                  disabled={converting}
                  id={`dust-target-${opt}`}
                >
                  {opt}
                </button>
              ))}
            </div>
          </div>

          {/* Section 2 — Eligible assets table */}
          <div>
            <div className="dust-section-label">
              Eligible balances
              {assets.length > 0 && (
                <span style={{ marginLeft: 8, fontSize: '0.75rem', fontWeight: 400 }}>
                  ({selected.size}/{assets.length} selected)
                </span>
              )}
            </div>

            {withinRestrictedTime && (
              <div className="dust-restricted-banner">
                ⚠️ Conversion temporarily unavailable — Binance.US enforces a cooldown
                between dust conversions. Please try again later.
              </div>
            )}

            {loadingAssets ? (
              <div className="dust-loading">Loading eligible balances…</div>
            ) : assets.length === 0 && !error ? (
              <div className="dust-empty">
                No eligible balances found for conversion to {toAsset}.
              </div>
            ) : assets.length > 0 ? (
              <>
                <div className="dust-table-wrap">
                <table className="dust-assets-table">
                  <thead>
                    <tr>
                      <th>
                        <input
                          type="checkbox"
                          className="dust-check"
                          checked={selected.size === assets.length && assets.length > 0}
                          onChange={toggleAll}
                          disabled={converting || withinRestrictedTime}
                          aria-label="Select all"
                        />
                      </th>
                      <th>Asset</th>
                      <th>Balance</th>
                      <th>≈ USD Value</th>
                      <th>Fee</th>
                      <th>You Receive</th>
                    </tr>
                  </thead>
                  <tbody>
                    {assets.map((asset) => (
                      <tr key={asset.fromAsset}>
                        <td>
                          <input
                            type="checkbox"
                            className="dust-check"
                            checked={selected.has(asset.fromAsset)}
                            onChange={() => toggleAsset(asset.fromAsset)}
                            disabled={converting || withinRestrictedTime}
                            id={`dust-check-${asset.fromAsset}`}
                          />
                        </td>
                        <td>
                          <span className="dust-asset-symbol">{asset.fromAsset}</span>
                        </td>
                        <td>{parseFloat(asset.availableBalance || 0).toFixed(6)}</td>
                        <td>${parseFloat(asset.usdValueConvertedAsset || 0).toFixed(4)}</td>
                        <td>
                          <span className="dust-fee-text">
                            {parseFloat(asset.conversionFee || 0).toFixed(8)} {toAsset}
                          </span>
                        </td>
                        <td>
                          <span className="dust-received-text">
                            {parseFloat(asset.receivedAsset || 0).toFixed(8)} {toAsset}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>

                {selectedAssets.length > 0 && (
                  <div className="dust-totals-row">
                    <span>
                      Total ≈ <strong>${totalUsd.toFixed(4)}</strong> USD &nbsp;|&nbsp;
                      Fee: <strong>{totalFee.toFixed(8)} {toAsset}</strong>
                    </span>
                    <span>
                      You receive: <strong>{totalReceived.toFixed(8)} {toAsset}</strong>
                    </span>
                  </div>
                )}
              </>
            ) : null}
          </div>

          {/* Section 3 — 2FA (only if required) */}
          {require2fa && (
            <div className="dust-2fa-section">
              <label className="dust-2fa-label" htmlFor="dustTwoFaCode">
                🔐 Two-Factor Authentication
              </label>
              <input
                id="dustTwoFaCode"
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                maxLength="6"
                value={twoFaCode}
                onChange={(e) => {
                  setTwoFaCode(e.target.value.replace(/\D/g, '').slice(0, 6));
                  setError('');
                }}
                placeholder="000000"
                className="dust-2fa-input"
                disabled={converting}
                autoComplete="off"
              />
              <p className="dust-2fa-help">
                Enter the code from your authenticator app (e.g. Google Authenticator, Bitwarden)
              </p>
            </div>
          )}

          {/* Error */}
          {error && <div className="dust-error">❌ {error}</div>}
        </div>

        {/* ── Footer ── */}
        <div className="dust-modal-footer">
          <button
            className="dust-btn dust-btn-cancel"
            onClick={onClose}
            disabled={converting}
            id="dust-cancel-btn"
          >
            Cancel
          </button>
          <button
            className="dust-btn dust-btn-convert"
            onClick={handleConvert}
            disabled={!canConvert || (require2fa && twoFaCode.length !== 6)}
            id="dust-convert-btn"
            title={
              withinRestrictedTime
                ? 'Conversion temporarily unavailable — please try again later'
                : ''
            }
          >
            {converting ? '⏳ Converting…' : `Convert to ${toAsset}`}
          </button>
        </div>
      </div>
    </div>
  );
}
