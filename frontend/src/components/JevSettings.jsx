import React, { useState } from 'react';
import axios from 'axios';
import JevTelemetry from './JevTelemetry';

export const JEV_DEFAULTS = {
  ai_gateway_key: '', jev_enabled: false, jev_transport: 'vercel', jev_model: 'typesafe-ai/jev',
  jev_endpoint: 'https://ai-gateway.vercel.sh/v1/evaluate', jev_timeout_seconds: 3,
  jev_confidence_threshold: 0.8, jev_conflict_threshold: 0.5, jev_sentiment_mode: 'off',
  jev_generative_fallback_enabled: true, jev_quant_shadow_enabled: false,
};

export default function JevSettings({ settings, onChange }) {
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [refresh, setRefresh] = useState(0);
  const value = key => settings[key] ?? JEV_DEFAULTS[key];
  const payload = () => Object.fromEntries(Object.keys(JEV_DEFAULTS).map(key => [key, value(key)]));
  const perform = async action => {
    setBusy(action); setMessage('');
    try {
      const { data } = await axios.post(action === 'save' ? '/api/settings' : '/api/jev/test-connection', payload());
      if (action === 'save') {
        onChange('ai_gateway_key', data.ai_gateway_key || '');
        setMessage('Jev settings saved. Sentiment also requires the main AI toggle to be enabled.');
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
    <h3>Jev Decision Engine (Experimental)</h3>
    <p>Evaluate news and quantitative setups with TypeSafe Jev through Vercel AI Gateway.</p>
    {toggle('jev_enabled', 'Enable Jev')}
    <div className="settings-form-group"><label htmlFor="jev-provider">Provider</label>
      <select id="jev-provider" value={value('jev_transport')} onChange={e => onChange('jev_transport', e.target.value)}><option value="vercel">Vercel AI Gateway</option></select>
    </div>
    <div className="settings-form-group"><label htmlFor="jev-model">Model</label>
      <input id="jev-model" value={value('jev_model')} onChange={e => onChange('jev_model', e.target.value)} list="jev-models" />
      <datalist id="jev-models"><option value="typesafe-ai/jev">Jev — TypeSafe AI</option></datalist>
    </div>
    <div className="settings-form-group"><label htmlFor="jev-key">Vercel AI Gateway API key</label>
      <input id="jev-key" type="password" autoComplete="new-password" value={value('ai_gateway_key')} onChange={e => onChange('ai_gateway_key', e.target.value)} placeholder="Enter your Vercel AI Gateway key" />
      <p className="settings-form-help">Encrypted when saved. The mask preserves your saved key; clear the field and save to remove it.</p>
    </div>
    <div className="settings-form-group"><label htmlFor="jev-sentiment">Sentiment mode</label>
      <select id="jev-sentiment" value={value('jev_sentiment_mode')} onChange={e => onChange('jev_sentiment_mode', e.target.value)}>
        <option value="off">Off</option><option value="shadow">Shadow — compare with current sentiment</option><option value="first">Jev-first — use accepted Jev sentiment</option>
      </select>
    </div>
    {toggle('jev_generative_fallback_enabled', 'Use generative fallback when Jev is uncertain or unavailable')}
    {toggle('jev_quant_shadow_enabled', 'Enable quant shadow observations')}
    <p>Paper gate: unavailable in v4.0.0. Quant shadow observations cannot change entries, exits, sizing, or risk controls.</p>
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
        <p className="settings-form-help">Custom endpoints require an operator-approved HTTPS address. Thresholds are experimental and need outcome calibration.</p>
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
