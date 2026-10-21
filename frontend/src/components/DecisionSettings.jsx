import React, { useState } from 'react';
import axios from 'axios';
import DecisionTelemetry from './DecisionTelemetry';

const PROVIDERS = {
  subq: {
    label: 'SubQ',
    keyField: 'subq_api_key',
    model: 'subq-snap-preview',
    endpoint: 'https://api.subq.ai/v1/systemone',
  },
  inception: {
    label: 'Inception Mercury Decide',
    keyField: 'inception_decisions_key',
    model: 'mercury-decide',
    endpoint: 'https://api.inceptionlabs.ai/v1/decisions',
  },
};

export const DECISION_DEFAULTS = {
  subq_api_key: '', inception_decisions_key: '',
  decision_enabled: false, decision_transport: 'subq', decision_model: 'subq-snap-preview',
  decision_endpoint: 'https://api.subq.ai/v1/systemone', decision_timeout_seconds: 3,
  decision_confidence_threshold: 0.8, decision_conflict_threshold: 0.5,
  decision_sentiment_mode: 'first', decision_quant_enabled: false,
};

export default function DecisionSettings({ settings, onChange }) {
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [refresh, setRefresh] = useState(0);
  const value = key => settings[key] ?? DECISION_DEFAULTS[key];
  const payload = () => Object.fromEntries(Object.keys(DECISION_DEFAULTS).map(key => [key, value(key)]));
  const transport = value('decision_transport');
  const provider = PROVIDERS[transport] || PROVIDERS.subq;
  const providerLabel = provider.label;
  const selectedModel = value('decision_model') || provider.model;
  const keyField = provider.keyField;
  const configured = settings[`${keyField}_configured`] === true;
  const enteredKey = typeof value(keyField) === 'string' && Boolean(value(keyField).trim()) && value(keyField).trim() !== '********';

  const perform = async action => {
    const requestProvider = provider;
    const requestModel = selectedModel;
    setBusy(action); setMessage('');
    try {
      const { data } = await axios.post(action === 'save' ? '/api/settings' : '/api/decision/test-connection', payload());
      if (action === 'save') {
        for (const field of ['subq_api_key', 'inception_decisions_key']) {
          if (data[field] !== undefined) onChange(field, data[field] || '');
          if (data[`${field}_configured`] !== undefined) onChange(`${field}_configured`, data[`${field}_configured`]);
        }
        const keyIsConfigured = data[`${requestProvider.keyField}_configured`] === true;
        setMessage(keyIsConfigured
          ? `Decision Engine settings saved. ${requestProvider.label} · ${requestModel} is configured with an encrypted API key.`
          : `Decision Engine settings saved for ${requestProvider.label} · ${requestModel}, but no usable key is stored for the selected provider.`);
      } else {
        const actualProvider = data.provider ? ` Provider: ${data.provider}.` : '';
        setMessage(`${data.message || 'Connection test succeeded.'}${actualProvider} Model: ${data.model || requestModel}. Latency: ${data.latency_ms} ms.`);
      }
      setRefresh(n => n + 1);
    } catch (err) {
      setMessage(err.response?.data?.message || err.response?.data?.error || 'Decision Engine settings request failed.');
    } finally { setBusy(''); }
  };

  const toggle = (key, label) => <div className="settings-form-group"><label>
    <input type="checkbox" checked={Boolean(value(key))} onChange={e => onChange(key, e.target.checked)} /> {label}
  </label></div>;
  const readinessText = configured
    ? '✓ API key configured'
    : enteredKey
      ? 'API key entered — save settings to confirm'
      : 'Missing API key — enter and save the selected provider’s key';
  const readinessColor = configured || enteredKey ? '#4ade80' : '#f87171';
  const credentialStatus = field => settings[`${field}_configured`] === true ? '✓ Configured' : 'Not configured';

  return <div className="settings-page-section" style={{ gridColumn: '1 / -1' }}>
    <h3>Decision Engine</h3>
    <p>Choose the structured decision provider and model for supported evaluations. This selection is used whenever an enabled Decision Engine workflow runs: sentiment, crypto quantitative entry decisions, and Event probability forecasts. General AI features such as Copilot keep their separate provider settings.</p>
    <div aria-label="Decision provider status" style={{ margin: '8px 0 12px 0', padding: '10px 14px', background: 'rgba(255,255,255,0.04)', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.1)' }}>
      <div style={{ marginBottom: '4px' }}>
        <strong>Selected provider and model:</strong>{' '}{providerLabel} · <code>{selectedModel}</code>
      </div>
      <div style={{ marginBottom: '6px' }}>
        <strong>Credential readiness:</strong>{' '}
        <span style={{ color: readinessColor }}>{readinessText}</span>
      </div>
      <div style={{ fontSize: '12px', opacity: .8, display: 'flex', flexWrap: 'wrap', gap: '4px 16px' }}>
        <span>SubQ: {credentialStatus('subq_api_key')}</span>
        <span>Inception Mercury Decide: {credentialStatus('inception_decisions_key')}</span>
      </div>
    </div>
    {toggle('decision_enabled', 'Enable Decision Engine')}
    <div className="settings-form-group"><label htmlFor="decision-provider">Decision provider</label>
      <select id="decision-provider" value={transport} onChange={e => {
        const nextProvider = PROVIDERS[e.target.value] || PROVIDERS.subq;
        onChange('decision_transport', e.target.value);
        onChange('decision_endpoint', nextProvider.endpoint);
        onChange('decision_model', nextProvider.model);
      }}>
        <option value="subq">SubQ — subq-snap-preview</option>
        <option value="inception">Inception Mercury Decide — mercury-decide</option>
      </select>
    </div>
    <div className="settings-form-group"><label htmlFor="decision-model">Decision model</label>
      <input id="decision-model" value={selectedModel} readOnly onChange={e => onChange('decision_model', e.target.value)} list="decision-models" />
      <datalist id="decision-models"><option value={provider.model}>{provider.label} decision model</option></datalist>
      <p className="settings-form-help">Each provider supports exactly one decision model, so the model is pinned to the selected provider.</p>
    </div>
    <div className="settings-form-group"><label htmlFor="decision-subq-key">{providerLabel} API key</label>
      <input id="decision-subq-key" type="password" autoComplete="new-password" value={value(keyField)} onChange={e => onChange(keyField, e.target.value)} placeholder={`Enter your ${providerLabel} API key`} />
      <p className="settings-form-help">Encrypted when saved. The mask preserves your saved key; clear the field and save to remove it.</p>
      <p className="settings-form-help">Decision state and instructions are sent to {provider.label}. Stored decisions follow {provider.label}’s data-retention policy.</p>
    </div>
    <div className="settings-form-group"><label htmlFor="decision-sentiment">Sentiment mode</label>
      <select id="decision-sentiment" value={value('decision_sentiment_mode')} onChange={e => onChange('decision_sentiment_mode', e.target.value)}>
        <option value="off">Off</option><option value="first">Use selected decision model for sentiment evaluations</option>
      </select>
    </div>
    <p>Sentiment uses the selected provider/model when the Decision Engine and sentiment mode are enabled; scheduled sentiment also requires the main AI setting. Crypto quantitative entry decisions and Event probability forecasts use the same selection when their workflows invoke the engine.</p>
    {toggle('decision_quant_enabled', 'Enable crypto quantitative entry decisions')}
    <p>When enabled, a qualified crypto entry is confirmed by the Decision Engine before it is opened. A rejection blocks the entry and is recorded with its reason; an abstention never blocks a deterministic entry. Event forecasts use this same selection when enabled in the Quantitative Strategy Engine.</p>
    <details><summary>Evaluation thresholds and connection settings</summary>
      {[
        ['decision_confidence_threshold', 'Minimum direction probability / reported confidence', 0, 1, 0.01],
        ['decision_conflict_threshold', 'Maximum evidence-conflict probability', 0, 1, 0.01],
        ['decision_timeout_seconds', 'Evaluation timeout (seconds)', 0.25, 15, 0.25],
      ].map(([key, label, min, max, step]) => <div className="settings-form-group" key={key}>
        <label htmlFor={key}>{label}</label><input id={key} type="number" min={min} max={max} step={step} value={value(key)} onChange={e => onChange(key, e.target.value === '' ? '' : Number(e.target.value))} />
      </div>)}
      <div className="settings-form-group"><label htmlFor="decision-endpoint">Provider endpoint</label>
        <input id="decision-endpoint" type="url" value={value('decision_endpoint')} readOnly onChange={e => onChange('decision_endpoint', e.target.value)} />
        <p className="settings-form-help">Each provider always uses its official Decisions API endpoint. Confidence thresholds apply to evaluation acceptance.</p>
      </div>
    </details>
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', margin: '12px 0' }}>
      <button type="button" className="btn btn-primary" disabled={Boolean(busy)} onClick={() => perform('save')}>{busy === 'save' ? 'Saving…' : 'Save Settings'}</button>
      <button type="button" className="btn btn-outline-primary" disabled={Boolean(busy)} onClick={() => perform('test')}>{busy === 'test' ? 'Testing…' : 'Test Connection'}</button>
    </div>
    <p className="settings-form-help">Test Connection sends one small structured evaluation using the selected provider/model and the entered or saved credential. It does not change trading decisions.</p>
    {message && <p role="status">{message}</p>}
    <h4>Decision Engine activity</h4>
    <DecisionTelemetry refreshKey={refresh} />
  </div>;
}
