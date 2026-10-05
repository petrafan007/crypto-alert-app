import React, { useState } from 'react';
import axios from 'axios';
import JevTelemetry from './JevTelemetry';

export const JEV_DEFAULTS = {
  ai_gateway_key: '', openrouter_api_key: '', jev_enabled: false, jev_transport: 'vercel', jev_model: 'typesafe-ai/jev',
  jev_endpoint: 'https://ai-gateway.vercel.sh/v1/evaluate', jev_timeout_seconds: 3,
  jev_confidence_threshold: 0.8, jev_conflict_threshold: 0.5, jev_sentiment_mode: 'first',
  jev_generative_fallback_enabled: false, jev_quant_shadow_enabled: false,
};

export default function JevSettings({ settings, onChange }) {
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [refresh, setRefresh] = useState(0);
  const value = key => settings[key] ?? JEV_DEFAULTS[key];
  const payload = () => ({ ...Object.fromEntries(Object.keys(JEV_DEFAULTS).map(key => [key, value(key)])), jev_generative_fallback_enabled: false });
  const perform = async action => {
    setBusy(action); setMessage('');
    try {
      const { data } = await axios.post(action === 'save' ? '/api/settings' : '/api/jev/test-connection', payload());
      if (action === 'save') {
        if (data.ai_gateway_key !== undefined) onChange('ai_gateway_key', data.ai_gateway_key || '');
        if (data.openrouter_api_key !== undefined) onChange('openrouter_api_key', data.openrouter_api_key || '');
        if (data.ai_gateway_key_configured !== undefined) onChange('ai_gateway_key_configured', data.ai_gateway_key_configured);
        if (data.openrouter_api_key_configured !== undefined) onChange('openrouter_api_key_configured', data.openrouter_api_key_configured);
        const field = value('jev_transport') === 'openrouter' ? 'openrouter_api_key' : 'ai_gateway_key';
        setMessage(data[`${field}_configured`] === true
          ? 'Jev settings saved. The server confirmed an encrypted API key is stored. Sentiment also requires the main AI toggle to be enabled.'
          : 'Jev settings saved, but no usable key is stored for this provider. Enter the API key and save it.');
      } else setMessage(`${data.message} Model: ${data.model}. Latency: ${data.latency_ms} ms.`);
      setRefresh(n => n + 1);
    } catch (err) {
      setMessage(err.response?.data?.message || err.response?.data?.error || 'Jev settings request failed.');
    } finally { setBusy(''); }
  };
  const toggle = (key, label) => <div className="settings-form-group"><label>
    <input type="checkbox" checked={Boolean(value(key))} onChange={e => onChange(key, e.target.checked)} /> {label}
  </label></div>;
  return <div className="settings-page-section" style={{ gridColumn: '1 / -1' }}>
    <h3>Jev Decision Engine</h3>
    <p>Evaluate news and quantitative setups with TypeSafe Jev through Vercel AI Gateway or OpenRouter.</p>
    <div style={{ margin: '8px 0 12px 0', padding: '10px 14px', background: 'rgba(255,255,255,0.04)', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.1)' }}>
      <div style={{ marginBottom: '4px' }}>
        <strong>Active Provider ({value('jev_transport') === 'openrouter' ? 'OpenRouter' : 'Vercel AI Gateway'}):</strong>{' '}
        <span style={{ color: settings[value('jev_transport') === 'openrouter' ? 'openrouter_api_key_configured' : 'ai_gateway_key_configured'] === true ? '#4ade80' : (settings[value('jev_transport') === 'openrouter' ? 'ai_gateway_key_configured' : 'openrouter_api_key_configured'] === true ? '#fbbf24' : '#f87171') }}>
          {settings[value('jev_transport') === 'openrouter' ? 'openrouter_api_key_configured' : 'ai_gateway_key_configured'] === true
            ? '✓ Configured'
            : (settings[value('jev_transport') === 'openrouter' ? 'ai_gateway_key_configured' : 'openrouter_api_key_configured'] === true
                ? `Ready via fallback (${value('jev_transport') === 'openrouter' ? 'Vercel AI Gateway' : 'OpenRouter'} key saved)`
                : 'Missing — enter and save the key below')}
        </span>
      </div>
      <div style={{ fontSize: '12px', opacity: 0.8, display: 'flex', gap: '16px' }}>
        <span>Vercel AI Gateway: {settings.ai_gateway_key_configured === true ? '✓ Configured' : 'Not configured'}</span>
        <span>OpenRouter: {settings.openrouter_api_key_configured === true ? '✓ Configured' : 'Not configured'}</span>
      </div>
    </div>
    {toggle('jev_enabled', 'Enable Jev')}
    <div className="settings-form-group"><label htmlFor="jev-provider">Provider</label>
      <select id="jev-provider" value={value('jev_transport')} onChange={e => {
        const transport = e.target.value;
        onChange('jev_transport', transport);
        onChange('jev_endpoint', transport === 'openrouter' ? 'https://openrouter.ai/api/alpha/decisions' : JEV_DEFAULTS.jev_endpoint);
        onChange('jev_model', transport === 'openrouter' ? 'typesafe/jev-1.13' : JEV_DEFAULTS.jev_model);
      }}>
        <option value="vercel">Vercel AI Gateway</option>
        <option value="openrouter">OpenRouter</option>
      </select>
    </div>
    <div className="settings-form-group"><label htmlFor="jev-model">Model</label>
      <input id="jev-model" value={value('jev_model')} onChange={e => onChange('jev_model', e.target.value)} list="jev-models" />
      <datalist id="jev-models"><option value={value('jev_transport') === 'openrouter' ? 'typesafe/jev-1.13' : 'typesafe-ai/jev'}>Jev — TypeSafe AI</option></datalist>
    </div>
    {value('jev_transport') === 'vercel' ? (
      <>
        <div className="settings-form-group"><label htmlFor="jev-key">Vercel AI Gateway API key</label>
          <input id="jev-key" type="password" autoComplete="new-password" value={value('ai_gateway_key')} onChange={e => {
            const val = e.target.value;
            if (val.startsWith('sk-or-')) {
              onChange('openrouter_api_key', val);
            } else {
              onChange('ai_gateway_key', val);
            }
          }} placeholder="Enter your Vercel AI Gateway key" />
          <p className="settings-form-help">Encrypted when saved. The mask preserves your saved key; clear the field and save to remove it.</p>
        </div>
        <details style={{ marginBottom: '12px' }}>
          <summary style={{ fontSize: '13px', cursor: 'pointer', opacity: 0.85 }}>Alternate: OpenRouter API key {settings.openrouter_api_key_configured === true ? '(✓ Configured)' : ''}</summary>
          <div className="settings-form-group" style={{ marginTop: '8px' }}>
            <label htmlFor="jev-or-key-alt">OpenRouter API key</label>
            <input id="jev-or-key-alt" type="password" autoComplete="new-password" value={value('openrouter_api_key')} onChange={e => onChange('openrouter_api_key', e.target.value)} placeholder="Enter your OpenRouter API key" />
          </div>
        </details>
      </>
    ) : (
      <>
        <div className="settings-form-group"><label htmlFor="jev-or-key">OpenRouter API key</label>
          <input id="jev-or-key" type="password" autoComplete="new-password" value={value('openrouter_api_key')} onChange={e => {
            const val = e.target.value;
            if (val.startsWith('vck_')) {
              onChange('ai_gateway_key', val);
            } else {
              onChange('openrouter_api_key', val);
            }
          }} placeholder="Enter your OpenRouter API key" />
          <p className="settings-form-help">Encrypted when saved. The mask preserves your saved key; clear the field and save to remove it.</p>
        </div>
        <details style={{ marginBottom: '12px' }}>
          <summary style={{ fontSize: '13px', cursor: 'pointer', opacity: 0.85 }}>Alternate: Vercel AI Gateway API key {settings.ai_gateway_key_configured === true ? '(✓ Configured)' : ''}</summary>
          <div className="settings-form-group" style={{ marginTop: '8px' }}>
            <label htmlFor="jev-key-alt">Vercel AI Gateway API key</label>
            <input id="jev-key-alt" type="password" autoComplete="new-password" value={value('ai_gateway_key')} onChange={e => onChange('ai_gateway_key', e.target.value)} placeholder="Enter your Vercel AI Gateway key" />
          </div>
        </details>
      </>
    )}
    <div className="settings-form-group"><label htmlFor="jev-sentiment">Sentiment mode</label>
      <select id="jev-sentiment" value={value('jev_sentiment_mode')} onChange={e => onChange('jev_sentiment_mode', e.target.value)}>
        <option value="off">Off</option><option value="first">Jev — sentiment evaluations</option>
      </select>
    </div>
    <p>Sentiment and Event probability evaluations use Jev. Unavailable or uncertain results never fall back to generative models.</p>
    {toggle('jev_quant_shadow_enabled', 'Enable quant shadow observations')}
    <p>Crypto shadow observations do not change trading decisions. Event predictions can use Jev through the Quantitative Strategy Engine AI settings.</p>
    <details><summary>Evaluation thresholds and connection settings</summary>
      {[
        ['jev_confidence_threshold', 'Minimum direction probability / reported confidence', 0, 1, 0.01],
        ['jev_conflict_threshold', 'Maximum evidence-conflict probability', 0, 1, 0.01],
        ['jev_timeout_seconds', 'Evaluation timeout (seconds)', 0.25, 15, 0.25],
      ].map(([key, label, min, max, step]) => <div className="settings-form-group" key={key}>
        <label htmlFor={key}>{label}</label><input id={key} type="number" min={min} max={max} step={step} value={value(key)} onChange={e => onChange(key, e.target.value === '' ? '' : Number(e.target.value))} />
      </div>)}
      <div className="settings-form-group"><label htmlFor="jev-endpoint">Evaluation endpoint</label>
        <input id="jev-endpoint" type="url" value={value('jev_endpoint')} onChange={e => onChange('jev_endpoint', e.target.value)} />
        <p className="settings-form-help">Custom endpoints require an operator-approved HTTPS address. Confidence thresholds apply to evaluation acceptance.</p>
      </div>
    </details>
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', margin: '12px 0' }}>
      <button type="button" className="btn btn-primary" disabled={Boolean(busy)} onClick={() => perform('save')}>{busy === 'save' ? 'Saving…' : 'Save Jev Settings'}</button>
      <button type="button" className="btn btn-outline-primary" disabled={Boolean(busy)} onClick={() => perform('test')}>{busy === 'test' ? 'Testing…' : 'Test Jev Connection'}</button>
    </div>
    <p className="settings-form-help">Test Connection sends one small evaluation using the entered or saved key.</p>
    {message && <p role="status">{message}</p>}
    <JevTelemetry refreshKey={refresh} />
  </div>;
}
