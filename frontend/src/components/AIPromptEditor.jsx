import React, { useEffect, useState } from 'react';
import axios from 'axios';

const DECISION_PROMPT_GROUPS = new Set(['sentiment', 'watchlist_sentiment', 'contract_probability']);

export default function AIPromptEditor({ groups, title, onChange }) {
  const [entries, setEntries] = useState({});
  const [dirty, setDirty] = useState({});
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let active = true;
    axios.get('/api/ai/prompt-catalog').then(({ data }) => {
      if (active) { setEntries(data.prompts); setLoaded(true); }
    }).catch(() => { if (active) setMessage('Could not load saved instructions. Reopen settings to retry.'); });
    return () => { active = false; };
  }, []);
  const change = (key, value) => {
    setEntries(previous => ({ ...previous, [key]: { ...previous[key], value } }));
    const changed = { ...dirty, [key]: value };
    setDirty(changed); setMessage('');
    onChange?.(changed);
  };
  const save = async () => {
    setBusy(true); setMessage('');
    try {
      const { data } = await axios.post('/api/ai/prompt-catalog', dirty);
      setEntries(data.prompts); setDirty({}); setMessage('Instructions saved. New evaluations use these settings.');
    } catch (error) { setMessage(error.response?.data?.error || 'Instructions could not be saved.'); }
    finally { setBusy(false); }
  };
  const usesDecisionEngine = groups.some(group => DECISION_PROMPT_GROUPS.has(group));
  const usesWorkflowAI = groups.some(group => !DECISION_PROMPT_GROUPS.has(group));
  const text = (id, label, value, update) => <label key={id} htmlFor={id} style={{ display: 'block', margin: '12px 0' }}>
    {label}
    <textarea id={id} value={value} rows={4} maxLength={24000} onChange={event => update(event.target.value)}
      style={{ display: 'block', width: '100%', boxSizing: 'border-box', padding: 10, marginTop: 6, background: '#232b31', color: '#fff', border: '1px solid #64748b', borderRadius: 6 }} />
  </label>;
  return <section aria-label={title} style={{ margin: '16px 0', padding: 14, border: '1px solid #64748b', borderRadius: 8 }}>
    <h4>{title}</h4>
    {usesDecisionEngine && <p>Sentiment and contract-probability instructions configure Decision Engine requests. The selected provider/model returns typed answers; workflow enablement and fallback settings still apply.</p>}
    {usesWorkflowAI && <p>These instructions accompany requests through the AI provider/model cascade configured for their workflow.</p>}
    {!loaded && !message && <p>Loading saved instructions…</p>}
    {Object.entries(entries).filter(([, entry]) => groups.includes(entry.group)).map(([key, entry]) => <details key={key} open={key.startsWith('decision.')}>
      <summary>{entry.label}</summary>
      {typeof entry.value === 'string' ? text(key, 'Instructions / query template', entry.value, value => change(key, value)) :
        Object.entries(entry.value).map(([name, question]) => <div key={name}>
          {text(`${key}-${name}`, `${name.replaceAll('_', ' ')} — ${question.type}`, question.instructions,
            instructions => change(key, { ...entry.value, [name]: { ...question, instructions } }))}
          {question.criteria && Object.entries(question.criteria).map(([label, description]) => text(`${key}-${name}-${label}`, `Answer ${label}`, description, value => {
            const criteria = Array.isArray(question.criteria) ? [...question.criteria] : { ...question.criteria };
            criteria[label] = value;
            change(key, { ...entry.value, [name]: { ...question, criteria } });
          }))}
        </div>)}
      <button type="button" onClick={() => change(key, structuredClone(entry.default))}>Reset these instructions to default</button>
    </details>)}
    {groups.includes('contract_probability') && <p>Contract questions must keep <code>{'{index}'}</code> and <code>{'{symbol}'}</code>. They identify the contract within the supplied batch.</p>}
    {onChange ? <p>Save these instructions with Save AI Configuration below.</p> :
      <button type="button" className="btn btn-primary" disabled={!loaded || busy || !Object.keys(dirty).length} onClick={save}>{busy ? 'Saving…' : 'Save instructions'}</button>}
    {message && <p role="status">{message}</p>}
  </section>;
}
