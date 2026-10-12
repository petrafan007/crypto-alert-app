import React, { useState } from 'react';
import axios from 'axios';
import JevTelemetry from './JevTelemetry';

const PROVIDERS = {
  vercel: {
    label: 'Vercel AI Gateway',
    keyField: 'ai_gateway_key',
    model: 'typesafe-ai/jev',
    endpoint: 'https://ai-gateway.vercel.sh/v1/evaluate',
  },
  openrouter: {
    label: 'OpenRouter',
    keyField: 'openrouter_api_key',
    model: 'typesafe/jev-1.13',
    endpoint: 'https://openrouter.ai/api/alpha/decisions',
  },
  subq: {
    label: 'SubQ',
    keyField: 'subq_api_key',
    model: 'subq-snap-preview',
    endpoint: 'https://api.subq.ai/v1/systemone',
  },
};

const ALTERNATE_PROVIDERS = { vercel: 'openrouter', openrouter: 'vercel' };

export const JEV_DEFAULTS = {
  ai_gateway_key: '', openrouter_api_key: '', subq_api_key: '', jev_enabled: false, jev_transport: 'vercel', jev_model: 'typesafe-ai/jev',
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
  const transport = value('jev_transport');
  const provider = PROVIDERS[transport] || PROVIDERS.vercel;
  const providerLabel = provider.label;
  const selectedModel = value('jev_model') || provider.model;
  const keyField = provider.keyField;
  const fallbackTransport = ALTERNATE_PROVIDERS[transport];
  const fallbackProvider = fallbackTransport ? PROVIDERS[fallbackTransport] : null;
  const configured = settings[`${keyField}_configured`] === true;
  const enteredKey = typeof value(keyField) === 'string' && Boolean(value(keyField).trim()) && value(keyField).trim() !== '********';
  const fallbackConfigured = Boolean(fallbackProvider && settings[`${fallbackProvider.keyField}_configured`] === true);

  const perform = async action => {
    const requestProvider = provider;
    const requestModel = selectedModel;
    const requestFallback = fallbackProvider;
    setBusy(action); setMessage('');
    try {
      const { data } = await axios.post(action === 'save' ? '/api/settings' : '/api/jev/test-connection', payload());
      if (action === 'save') {
        for (const field of ['ai_gateway_key', 'openrouter_api_key', 'subq_api_key']) {
          if (data[field] !== undefined) onChange(field, data[field] || '');
          if (data[`${field}_configured`] !== undefined) onChange(`${field}_configured`, data[`${field}_configured`]);
        }
        const keyIsConfigured = data[`${requestProvider.keyField}_configured`] === true;
        const fallbackIsConfigured = requestFallback && data[`${requestFallback.keyField}_configured`] === true;
        setMessage(keyIsConfigured
          ? `Decision Engine settings saved. ${requestProvider.label} · ${requestModel} is configured with an encrypted API key.`
          : fallbackIsConfigured
            ? `Decision Engine settings saved. The selected ${requestProvider.label} key is missing; ${requestFallback.label} credentials are available as a supported alternate.`
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
      : fallbackConfigured
        ? `Selected key missing; ${fallbackProvider.label} credentials are available as an alternate`
        : 'Missing API key — enter and save the selected provider’s key';
  const readinessColor = configured || enteredKey ? '#4ade80' : fallbackConfigured ? '#fbbf24' : '#f87171';
  const credentialStatus = field => settings[`${field}_configured`] === true ? '✓ Configured' : 'Not configured';

  return <div className="settings-page-section" style={{ gridColumn: '1 / -1' }}>
    <h3>Decision Engine</h3>
    <p>Choose the structured decision provider and model for supported evaluations. This selection is used whenever an enabled Decision Engine workflow runs: sentiment, crypto quantitative shadow observations, and Event probability forecasts. General AI features such as Copilot keep their separate provider settings.</p>
    <div aria-label="Decision provider status" style={{ margin: '8px 0 12px 0', padding: '10px 14px', background: 'rgba(255,255,255,0.04)', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.1)' }}>
      <div style={{ marginBottom: '4px' }}>
        <strong>Selected provider and model:</strong>{' '}{providerLabel} · <code>{selectedModel}</code>
      </div>
      <div style={{ marginBottom: '6px' }}>
        <strong>Credential readiness:</strong>{' '}
        <span style={{ color: readinessColor }}>{readinessText}</span>
      </div>
      <div style={{ fontSize: '12px', opacity: 0.8, display: 'flex', flexWrap: 'wrap', gap: '4px 16px' }}>
        <span>Vercel AI Gateway: {credentialStatus('ai_gateway_key')}</span>
        <span>OpenRouter: {credentialStatus('openrouter_api_key')}</span>
        <span>SubQ: {credentialStatus('subq_api_key')}</span>
      </div>
    </div>
    {toggle('jev_enabled', 'Enable Decision Engine')}
    <div className="settings-form-group"><label htmlFor="decision-provider">Decision provider</label>
      <select id="decision-provider" value={transport} onChange={e => {
        const nextProvider = PROVIDERS[e.target.value] || PROVIDERS.vercel;
        onChange('jev_transport', e.target.value);
        onChange('jev_endpoint', nextProvider.endpoint);
        onChange('jev_model', nextProvider.model);
      }}>
        <option value="vercel">Vercel AI Gateway</option>
        <option value="openrouter">OpenRouter</option>
        <option value="subq">SubQ — subq-snap-preview</option>
      </select>
    </div>
    <div className="settings-form-group"><label htmlFor="decision-model">Decision model</label>
      <input id="decision-model" value={selectedModel} readOnly={transport === 'subq'} onChange={e => onChange('jev_model', e.target.value)} list="decision-models" />
      <datalist id="decision-models"><option value={provider.model}>{provider.label} decision model</option></datalist>
      <p className="settings-form-help">This model is used for each enabled evaluation through the selected provider. SubQ supports only <code>subq-snap-preview</code>.</p>
    </div>
    {transport === 'subq' ? (
      <div className="settings-form-group"><label htmlFor="decision-subq-key">SubQ API key</label>
        <input id="decision-subq-key" type="password" autoComplete="new-password" value={value('subq_api_key')} onChange={e => onChange('subq_api_key', e.target.value)} placeholder="Enter your SubQ API key" />
        <p className="settings-form-help">Encrypted when saved. The mask preserves your saved key; clear the field and save to remove it.</p>
        <p className="settings-form-help">Decision state and instructions are sent to SubQ. Stored decisions follow SubQ’s data-retention policy.</p>
      </div>
    ) : transport === 'vercel' ? (
      <>
        <div className="settings-form-group"><label htmlFor="decision-vercel-key">Vercel AI Gateway API key</label>
          <input id="decision-vercel-key" type="password" autoComplete="new-password" value={value('ai_gateway_key')} onChange={e => {
            const val = e.target.value;
            if (val.startsWith('sk-or-')) onChange('openrouter_api_key', val);
            else onChange('ai_gateway_key', val);
          }} placeholder="Enter your Vercel AI Gateway key" />
          <p className="settings-form-help">Encrypted when saved. The mask preserves your saved key; clear the field and save to remove it.</p>
        </div>
        <details style={{ marginBottom: '12px' }}>
          <summary style={{ fontSize: '13px', cursor: 'pointer', opacity: 0.85 }}>Alternate: OpenRouter API key {settings.openrouter_api_key_configured === true ? '(✓ Configured)' : ''}</summary>
          <div className="settings-form-group" style={{ marginTop: '8px' }}>
            <label htmlFor="decision-openrouter-key-alt">OpenRouter API key</label>
            <input id="decision-openrouter-key-alt" type="password" autoComplete="new-password" value={value('openrouter_api_key')} onChange={e => onChange('openrouter_api_key', e.target.value)} placeholder="Enter your OpenRouter API key" />
          </div>
        </details>
      </>
    ) : (
      <>
        <div className="settings-form-group"><label htmlFor="decision-openrouter-key">OpenRouter API key</label>
          <input id="decision-openrouter-key" type="password" autoComplete="new-password" value={value('openrouter_api_key')} onChange={e => {
            const val = e.target.value;
            if (val.startsWith('vck_')) onChange('ai_gateway_key', val);
            else onChange('openrouter_api_key', val);
          }} placeholder="Enter your OpenRouter API key" />
          <p className="settings-form-help">Encrypted when saved. The mask preserves your saved key; clear the field and save to remove it.</p>
        </div>
        <details style={{ marginBottom: '12px' }}>
          <summary style={{ fontSize: '13px', cursor: 'pointer', opacity: 0.85 }}>Alternate: Vercel AI Gateway API key {settings.ai_gateway_key_configured === true ? '(✓ Configured)' : ''}</summary>
          <div className="settings-form-group" style={{ marginTop: '8px' }}>
            <label htmlFor="decision-vercel-key-alt">Vercel AI Gateway API key</label>
            <input id="decision-vercel-key-alt" type="password" autoComplete="new-password" value={value('ai_gateway_key')} onChange={e => onChange('ai_gateway_key', e.target.value)} placeholder="Enter your Vercel AI Gateway key" />
          </div>
        </details>
      </>
    )}
    <div className="settings-form-group"><label htmlFor="decision-sentiment">Sentiment mode</label>
      <select id="decision-sentiment" value={value('jev_sentiment_mode')} onChange={e => onChange('jev_sentiment_mode', e.target.value)}>
        <option value="off">Off</option><option value="first">Use selected decision model for sentiment evaluations</option>
      </select>
    </div>
    <p>Sentiment uses the selected provider/model when the Decision Engine and sentiment mode are enabled; scheduled sentiment also requires the main AI setting. Crypto quantitative shadow and Event probability evaluations use the same selection when their workflows invoke the engine.</p>
    {toggle('jev_quant_shadow_enabled', 'Enable crypto quantitative shadow evaluations')}
    <p>Shadow evaluations use the selected provider/model for research only and do not change trading decisions. Event forecasts use this same selection when enabled in the Quantitative Strategy Engine.</p>
    <details><summary>Evaluation thresholds and connection settings</summary>
      {[
        ['jev_confidence_threshold', 'Minimum direction probability / reported confidence', 0, 1, 0.01],
        ['jev_conflict_threshold', 'Maximum evidence-conflict probability', 0, 1, 0.01],
        ['jev_timeout_seconds', 'Evaluation timeout (seconds)', 0.25, 15, 0.25],
      ].map(([key, label, min, max, step]) => <div className="settings-form-group" key={key}>
        <label htmlFor={key}>{label}</label><input id={key} type="number" min={min} max={max} step={step} value={value(key)} onChange={e => onChange(key, e.target.value === '' ? '' : Number(e.target.value))} />
      </div>)}
      <div className="settings-form-group"><label htmlFor="decision-endpoint">Provider endpoint</label>
        <input id="decision-endpoint" type="url" value={value('jev_endpoint')} readOnly={transport === 'subq'} onChange={e => onChange('jev_endpoint', e.target.value)} />
        <p className="settings-form-help">SubQ always uses its official Decisions API endpoint. Other endpoints must be operator-approved HTTPS addresses. Confidence thresholds apply to evaluation acceptance.</p>
      </div>
    </details>
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', margin: '12px 0' }}>
      <button type="button" className="btn btn-primary" disabled={Boolean(busy)} onClick={() => perform('save')}>{busy === 'save' ? 'Saving…' : 'Save Settings'}</button>
      <button type="button" className="btn btn-outline-primary" disabled={Boolean(busy)} onClick={() => perform('test')}>{busy === 'test' ? 'Testing…' : 'Test Connection'}</button>
    </div>
    <p className="settings-form-help">Test Connection sends one small structured evaluation using the selected provider/model and the entered or saved credential. It does not change trading decisions.</p>
    {message && <p role="status">{message}</p>}
    <h4>Decision Engine activity</h4>
    <JevTelemetry refreshKey={refresh} />
  </div>;
}
