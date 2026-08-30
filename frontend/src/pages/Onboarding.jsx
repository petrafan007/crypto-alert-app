import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../components/AuthContext';
import { BinanceLogo, WebullLogo } from '../components/CryptoIcon';
import { APP_VERSION } from '../version';
import './Onboarding.css';

const RAIL_STEPS = ['Account', 'Security', 'Exchanges', 'AI & data', 'Notifications', 'Review'];
const PAGE_STEP = {
  'security-choice': 1, 'security-setup': 1, exchanges: 2, binance: 2,
  webull: 2, 'webull-accounts': 2, 'ai-choice': 3, 'ai-primary': 3,
  'ai-secondary': 3, 'ai-tertiary': 3, 'search-news': 3, telegram: 4, review: 5,
};
const BACK_PAGE = {
  'security-choice': null, 'security-setup': 'security-choice', exchanges: 'security-choice',
  binance: 'exchanges', webull: 'exchanges', 'webull-accounts': 'webull',
  'ai-choice': 'exchanges', 'ai-primary': 'ai-choice', 'ai-secondary': 'ai-primary',
  'ai-tertiary': 'ai-secondary', 'search-news': 'ai-choice', telegram: 'search-news', review: 'telegram',
};

function BrandIcon() {
  return <svg className="ob-brand-icon" viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="13" fill="none" stroke="currentColor" strokeWidth="2.4"/><path d="M8 21l5-5 4 3 7-8M20 11h4v4" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/></svg>;
}

function ThemeButton({ isLightMode, toggleTheme }) {
  return <button className="ob-theme" onClick={toggleTheme} type="button" aria-label={`Switch to ${isLightMode ? 'dark' : 'light'} mode`}><span>{isLightMode ? '☀' : '☾'}</span>{isLightMode ? 'Light' : 'Dark'}</button>;
}
function Field({ label, hint, children, full = false }) {
  return <label className={`ob-field ${full ? 'full' : ''}`}><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}
function Notice({ type = 'info', children }) { return <div className={`ob-notice ${type}`}>{children}</div>; }
function Choice({ selected, onClick, icon, title, children }) {
  return <button type="button" className={`ob-choice ${selected ? 'selected' : ''}`} onClick={onClick}><span className="ob-radio"/><span className="ob-choice-icon">{icon}</span><strong>{title}</strong><small>{children}</small></button>;
}

export default function Onboarding({ isLightMode, toggleTheme }) {
  const navigate = useNavigate();
  const { logout, checkAuthStatus } = useAuth();
  const [status, setStatus] = useState(null);
  const [page, setPage] = useState('security-choice');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [skip2faModal, setSkip2faModal] = useState(false);
  const [qr, setQr] = useState(null);
  const [totpCode, setTotpCode] = useState('');
  const [exchangeChoice, setExchangeChoice] = useState('');
  const [binance, setBinance] = useState({ api_key: '', api_secret: '' });
  const [webull, setWebull] = useState({ webull_app_key: '', webull_app_secret: '' });
  const [webullStage, setWebullStage] = useState('credentials');
  const [accounts, setAccounts] = useState([]);
  const [enabledAccounts, setEnabledAccounts] = useState([]);
  const [importAccounts, setImportAccounts] = useState([]);
  const [models, setModels] = useState({});
  const [ai, setAi] = useState({
    primary: { provider: 'openai', model: '', reasoning: 'medium', apiKey: '' },
    secondary: { provider: '', model: '', reasoning: 'medium', apiKey: '' },
    tertiary: { provider: '', model: '', reasoning: 'medium', apiKey: '' },
  });
  const [search, setSearch] = useState({ brave: '', fallback: '', news: '' });
  const [telegram, setTelegram] = useState({ token: '', chatId: '' });

  const refreshStatus = async () => {
    const { data } = await axios.get('/api/onboarding/status', { withCredentials: true });
    setStatus(data);
    setPage(data.page || 'security-choice');
    setExchangeChoice(data.exchange_choice || '');
    setAccounts(data.webull_accounts || []);
    setEnabledAccounts(data.webull_enabled_account_ids || []);
    setImportAccounts(data.webull_enabled_account_ids || []);
    setAi(prev => {
      const next = { ...prev };
      for (const tier of ['primary', 'secondary', 'tertiary']) {
        const saved = data.ai_tiers?.[tier] || {};
        next[tier] = { ...next[tier], provider: saved.provider || next[tier].provider, model: saved.model || next[tier].model };
      }
      return next;
    });
    return data;
  };

  useEffect(() => {
    Promise.all([refreshStatus(), axios.get('/api/ai/models', { withCredentials: true })])
      .then(([, modelResponse]) => setModels(modelResponse.data || {}))
      .catch(err => setMessage({ type: 'error', text: err.response?.data?.error || 'Unable to load onboarding.' }));
  }, []);

  const step = PAGE_STEP[page] ?? 1;
  const modelOptions = useMemo(() => models[ai[page.replace('ai-', '')]?.provider] || [], [models, ai, page]);

  const saveProgress = async (payload) => {
    const { data } = await axios.post('/api/onboarding/progress', payload, { withCredentials: true });
    if (payload.page) setPage(payload.page);
    return data;
  };
  const go = async (nextPage, extra = {}) => {
    setMessage(null); setBusy(true);
    try { await saveProgress({ ...extra, page: nextPage }); setPage(nextPage); }
    catch (err) { setMessage({ type: 'error', text: err.response?.data?.error || 'Unable to save your progress.' }); }
    finally { setBusy(false); }
  };
  const back = () => { const target = BACK_PAGE[page]; if (target) go(target); };

  const start2fa = async () => {
    setBusy(true); setMessage(null);
    try { const { data } = await axios.post('/api/trading/2fa/setup', {}, { withCredentials: true }); setQr(data); await go('security-setup', { two_factor_deferred: false }); }
    catch (err) { setMessage({ type: 'error', text: err.response?.data?.error || 'Unable to start 2FA setup.' }); setBusy(false); }
  };
  const verify2fa = async () => {
    setBusy(true); setMessage(null);
    try { await axios.post('/api/trading/2fa/verify-setup', { code: totpCode }, { withCredentials: true }); await refreshStatus(); await go('exchanges', { two_factor_deferred: false }); }
    catch (err) { setMessage({ type: 'error', text: err.response?.data?.error || 'That code could not be verified.' }); }
    finally { setBusy(false); }
  };
  const defer2fa = async () => { setSkip2faModal(false); await go('exchanges', { two_factor_deferred: true }); };

  const continueExchangeChoice = async () => {
    if (!exchangeChoice) { setMessage({ type: 'error', text: 'Select Binance.US, Webull, or both.' }); return; }
    await go(exchangeChoice === 'webull' ? 'webull' : 'binance', { exchange_choice: exchangeChoice });
  };
  const testBinance = async () => {
    if (!binance.api_key || !binance.api_secret) { setMessage({ type: 'error', text: 'Enter both Binance.US credentials.' }); return; }
    setBusy(true); setMessage(null);
    try {
      const { data } = await axios.post('/api/test-binance-connection', { ...binance, save_on_success: true }, { withCredentials: true });
      setBinance({ api_key: '', api_secret: '' }); setMessage({ type: 'success', text: data.message }); await refreshStatus();
    } catch (err) { const d = err.response?.data || {}; setMessage({ type: 'error', text: [d.message, d.details, d.suggestion].filter(Boolean).join(' ') || 'Binance.US connection failed.' }); }
    finally { setBusy(false); }
  };
  const afterBinance = () => go(exchangeChoice === 'both' ? 'webull' : 'ai-choice');

  const connectWebull = async () => {
    if (!status?.webull_configured && (!webull.webull_app_key || !webull.webull_app_secret)) { setMessage({ type: 'error', text: 'Enter the Webull App Key and App Secret.' }); return; }
    setBusy(true); setMessage(null);
    try {
      if (webull.webull_app_key && webull.webull_app_secret) {
        await axios.post('/api/settings', { ...webull, webull_environment: 'production' }, { withCredentials: true });
        setWebull({ webull_app_key: '', webull_app_secret: '' });
      }
      const { data } = await axios.post('/api/webull-token/initiate', {}, { withCredentials: true });
      if (data.status === 'NORMAL') await loadWebullAccounts();
      else { setWebullStage('pending'); setMessage({ type: 'info', text: data.message }); }
    } catch (err) { setMessage({ type: 'error', text: err.response?.data?.message || 'Unable to connect Webull.' }); }
    finally { setBusy(false); }
  };
  const checkWebull = async () => {
    setBusy(true); setMessage(null);
    try { const { data } = await axios.post('/api/webull-token/status', {}, { withCredentials: true }); if (data.status === 'NORMAL') await loadWebullAccounts(); else setMessage({ type: 'info', text: data.message }); }
    catch (err) { setMessage({ type: 'error', text: err.response?.data?.message || 'Verification is not complete yet.' }); }
    finally { setBusy(false); }
  };
  const loadWebullAccounts = async () => {
    const { data } = await axios.get('/api/webull/accounts?refresh=true', { withCredentials: true });
    const ids = data.enabled_account_ids?.length ? data.enabled_account_ids : (data.accounts || []).map(a => String(a.account_id));
    setAccounts(data.accounts || []); setEnabledAccounts(ids); setImportAccounts(ids); setWebullStage('accounts'); await go('webull-accounts');
  };
  const saveWebullAccounts = async () => {
    if (!enabledAccounts.length) { setMessage({ type: 'error', text: 'Select at least one Webull account.' }); return; }
    setBusy(true); setMessage(null);
    try {
      await axios.post('/api/webull/enabled-accounts', { enabled_account_ids: enabledAccounts }, { withCredentials: true });
      if (importAccounts.length) await axios.post('/api/webull/portfolio-sync', { account_ids: importAccounts }, { withCredentials: true });
      await refreshStatus(); await go('ai-choice');
    } catch (err) { setMessage({ type: 'error', text: err.response?.data?.message || 'Unable to save Webull account selections.' }); }
    finally { setBusy(false); }
  };
  const skipWebull = () => {
    if (!status?.binance_verified) { setMessage({ type: 'error', text: 'Connect Webull or go back and successfully connect Binance.US.' }); return; }
    go('ai-choice');
  };

  const setAiTier = (tier, field, value) => setAi(prev => ({ ...prev, [tier]: { ...prev[tier], [field]: value, ...(field === 'provider' ? { model: '' } : {}) } }));
  const testAndSaveAi = async (tier) => {
    const entry = ai[tier];
    if (!entry.provider || !entry.model || !entry.apiKey) { setMessage({ type: 'error', text: 'Choose a provider and model, then enter its API key.' }); return; }
    setBusy(true); setMessage(null);
    try {
      const { data } = await axios.post('/api/test-ai-connection-generic', { provider: entry.provider, model: entry.model, api_key: entry.apiKey, tier }, { withCredentials: true });
      const suffix = tier === 'primary' ? '' : tier === 'secondary' ? '_fallback' : '_tertiary';
      const payload = { ai_enabled: true, [`ai_provider${tier === 'primary' ? '' : `_${tier}`}`]: entry.provider, [`ai_model${tier === 'primary' ? '' : `_${tier}`}`]: entry.model, [`ai_reasoning_level${tier === 'primary' ? '' : `_${tier}`}`]: entry.reasoning, [`${entry.provider}_key${suffix}`]: entry.apiKey };
      await axios.post('/api/settings', payload, { withCredentials: true });
      setAiTier(tier, 'apiKey', ''); setMessage({ type: 'success', text: data.message }); await refreshStatus();
    } catch (err) { setMessage({ type: 'error', text: err.response?.data?.message || 'The AI connection test failed.' }); }
    finally { setBusy(false); }
  };
  const afterAiTier = (tier) => go(tier === 'primary' ? 'ai-secondary' : tier === 'secondary' ? 'ai-tertiary' : 'search-news');

  const saveSearch = async () => {
    setBusy(true); setMessage(null);
    try {
      if (search.brave) {
        const { data } = await axios.post('/api/test-brave-search', { api_key: search.brave }, { withCredentials: true });
        if (!data.success) throw new Error(data.message);
      }
      await axios.post('/api/settings', { brave_search_api_key: search.brave, brave_search_api_key_fallback: search.fallback, news_api: search.news }, { withCredentials: true });
      setSearch({ brave: '', fallback: '', news: '' }); await go('telegram', { search_skipped: false });
    } catch (err) { setMessage({ type: 'error', text: err.response?.data?.message || err.message || 'Unable to save search and news services.' }); }
    finally { setBusy(false); }
  };
  const testTelegram = async () => {
    setBusy(true); setMessage(null);
    try { const { data } = await axios.post('/api/onboarding/telegram-test', { telegram_token: telegram.token, telegram_chat_id: telegram.chatId }, { withCredentials: true }); setTelegram({ token: '', chatId: '' }); setMessage({ type: 'success', text: data.message }); await refreshStatus(); }
    catch (err) { setMessage({ type: 'error', text: err.response?.data?.message || 'Telegram could not deliver the test message.' }); }
    finally { setBusy(false); }
  };
  const finish = async () => {
    setBusy(true); setMessage(null);
    try { await axios.post('/api/onboarding/finish', {}, { withCredentials: true }); await checkAuthStatus(true); navigate('/', { replace: true }); }
    catch (err) { setMessage({ type: 'error', text: err.response?.data?.error || 'Complete the required exchange connection first.' }); }
    finally { setBusy(false); }
  };

  if (!status) return <div className="ob-loading">Loading secure onboarding…</div>;

  const renderAiTier = tier => {
    const entry = ai[tier]; const saved = status.ai_tiers?.[tier]; const options = models[entry.provider] || [];
    return <><Notice>Configure the {tier} provider. {tier !== 'primary' && 'This fallback is optional.'}</Notice><div className="ob-grid"><Field label="Provider"><select value={entry.provider} onChange={e => setAiTier(tier, 'provider', e.target.value)}><option value="">No {tier} provider</option>{['openai','zai','perplexity','gemini','inception'].map(p => <option key={p} value={p}>{p === 'zai' ? 'Z.AI' : p[0].toUpperCase()+p.slice(1)}</option>)}</select></Field><Field label="Model"><select value={entry.model} onChange={e => setAiTier(tier, 'model', e.target.value)}><option value="">Choose a model</option>{options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select></Field><Field label="Reasoning"><select value={entry.reasoning} onChange={e => setAiTier(tier, 'reasoning', e.target.value)}>{['light', 'medium', 'high', 'extra high'].map(x => <option key={x}>{x}</option>)}</select></Field><Field label="API Key" hint={saved?.configured ? 'A verified key is already saved. Enter a new key only to replace it.' : ''}><input type="password" value={entry.apiKey} onChange={e => setAiTier(tier, 'apiKey', e.target.value)} placeholder={saved?.configured ? 'Verified key saved' : 'Enter API key'} /></Field></div><div className="ob-actions-inline"><button className="ob-button secondary" onClick={() => testAndSaveAi(tier)} disabled={busy}>{busy ? 'Testing…' : 'Test API Connection'}</button>{saved?.configured && <span className="ob-success-text">✓ Connection verified</span>}</div></>;
  };

  let title = ''; let subtitle = ''; let body = null; let primary = null; let primaryLabel = ''; let auxiliary = null;
  if (page === 'security-choice') { title='Protect your account'; subtitle='Add an authenticator now, or continue with live trading locked until 2FA is configured.'; body=<><Notice>Two-factor authentication protects account access and live trading actions. Webull paper trading does not require it.</Notice><div className="ob-choices two"><Choice icon="🛡" title="Set up 2FA now" onClick={start2fa}>Recommended. Use Bitwarden, Google Authenticator, Authy, or another TOTP app.</Choice><Choice icon="◷" title="Not right now" onClick={() => setSkip2faModal(true)}>Continue onboarding. Live order placement and cancellation remain unavailable.</Choice></div></>; }
  if (page === 'security-setup') { title='Set up two-factor authentication'; subtitle='Scan the code, save the setup key, then enter the current six-digit code.'; body=<div className="ob-grid"><div className="ob-panel qr">{qr?.qr_code ? <img src={qr.qr_code} alt="Authenticator QR code"/> : <button className="ob-button secondary" onClick={start2fa}>Generate QR code</button>}<div><strong>Manual setup key</strong><code>{qr?.secret || 'Generate a new setup code'}</code></div></div><div className="ob-panel"><Field label="6-digit verification code"><input inputMode="numeric" maxLength="6" value={totpCode} onChange={e => setTotpCode(e.target.value.replace(/\D/g,''))} placeholder="000000" /></Field></div></div>; primary=verify2fa; primaryLabel='Verify & Continue'; }
  if (page === 'exchanges') { title='Choose at least one exchange'; subtitle='Connect Binance.US, Webull, or both before entering the Dashboard.'; body=<><Notice type="warning"><strong>Required:</strong> At least one exchange must pass its connection test.</Notice><div className="ob-choices three"><Choice selected={exchangeChoice==='binance'} onClick={() => setExchangeChoice('binance')} icon={<BinanceLogo size={36}/>} title="Binance.US">Connect spot balances, portfolios, orders, and market data.</Choice><Choice selected={exchangeChoice==='webull'} onClick={() => setExchangeChoice('webull')} icon={<WebullLogo size={36}/>} title="Webull">Connect Production OpenAPI, then select detected live or paper accounts.</Choice><Choice selected={exchangeChoice==='both'} onClick={() => setExchangeChoice('both')} icon={<span className="ob-both"><BinanceLogo size={32}/><WebullLogo size={32}/></span>} title="Both exchanges">Set up Binance.US first, followed by Webull after.</Choice></div></>; primary=continueExchangeChoice; primaryLabel=exchangeChoice==='webull'?'Continue to Webull':'Continue to Binance.US'; }
  if (page === 'binance') { title='Connect Binance.US'; subtitle='Enter a Binance.US API key with Reading and Spot Trading enabled.'; body=<><div className="ob-grid"><Field label="API Key"><input type="password" value={binance.api_key} onChange={e=>setBinance({...binance,api_key:e.target.value})} placeholder={status.binance_configured?'Verified credentials saved':'Enter Binance.US API key'} /></Field><Field label="API Secret"><input type="password" value={binance.api_secret} onChange={e=>setBinance({...binance,api_secret:e.target.value})} placeholder={status.binance_configured?'Verified credentials saved':'Enter Binance.US API secret'} /></Field></div><div className="ob-panel"><strong>Required permissions</strong><ul><li>Enable Reading</li><li>Enable Spot Trading</li><li>Keep Withdrawals disabled</li><li>Use IP restrictions where practical</li></ul></div>{status.binance_verified && <Notice type="success">✓ Binance.US is connected and satisfies the exchange requirement.</Notice>}</>; auxiliary=<button className="ob-button secondary" onClick={testBinance} disabled={busy}>{busy?'Testing…':'Test API Connection'}</button>; primary=status.binance_verified?afterBinance:null; primaryLabel=exchangeChoice==='both'?'Continue to Webull':'Continue'; }
  if (page === 'webull') { title='Connect Webull'; subtitle='Production OpenAPI is used by default. Paper accounts are selected after account discovery.'; body=<><Notice><strong>Connection environment: Production</strong> — the internal Sandbox environment is not available here.</Notice><div className="ob-grid"><Field label="Webull App Key"><input type="password" value={webull.webull_app_key} onChange={e=>setWebull({...webull,webull_app_key:e.target.value})} placeholder={status.webull_configured?'Saved credentials available':'Enter App Key'} /></Field><Field label="Webull App Secret"><input type="password" value={webull.webull_app_secret} onChange={e=>setWebull({...webull,webull_app_secret:e.target.value})} placeholder={status.webull_configured?'Saved credentials available':'Enter App Secret'} /></Field></div>{webullStage==='pending' && <Notice type="warning">Approve the OpenAPI request in Webull, then return and check verification.</Notice>}{status.binance_verified && <Notice type="success">✓ Binance.US is already connected, so Webull may be skipped.</Notice>}</>; auxiliary=<>{status.binance_verified&&<button className="ob-button secondary" onClick={skipWebull}>Skip Webull</button>}<button className="ob-button secondary" onClick={webullStage==='pending'?checkWebull:connectWebull} disabled={busy}>{busy?'Checking…':webullStage==='pending'?'Check Webull Verification':'Connect & Find Accounts'}</button></>; }
  if (page === 'webull-accounts') { title='Choose Webull accounts'; subtitle='Select the accounts CSDapp.online may use and which portfolios to import.'; body=<>{accounts.map(a=>{const id=String(a.account_id);return <div className="ob-account" key={id}><input type="checkbox" checked={enabledAccounts.includes(id)} onChange={e=>{if(e.target.checked){setEnabledAccounts([...enabledAccounts,id]);}else{setEnabledAccounts(enabledAccounts.filter(x=>x!==id));setImportAccounts(importAccounts.filter(x=>x!==id));}}}/><span><strong>{a.account_label||a.account_name||'Webull Account'}</strong><small>{a.account_id_masked}</small></span><span className={`ob-badge ${(a.account_type||'').toLowerCase().includes('paper')?'paper':''}`}>{a.account_type||a.account_class||'ACCOUNT'}</span><label><input type="checkbox" checked={importAccounts.includes(id)} disabled={!enabledAccounts.includes(id)} onChange={e=>setImportAccounts(e.target.checked?[...importAccounts,id]:importAccounts.filter(x=>x!==id))}/> Import portfolio</label></div>})}<Notice type="warning">Selecting an account does not place trades. Live trading remains locked until 2FA is enabled.</Notice></>; primary=saveWebullAccounts; primaryLabel='Save Accounts & Continue'; }
  if (page === 'ai-choice') { title='Set up AI integrations?'; subtitle='AI is optional. Configure providers now or return from Settings later.'; body=<><div className="ob-choices two"><Choice icon="✦" title="Configure AI now" onClick={()=>go('ai-primary',{ai_skipped:false})}>Add a primary provider and optional secondary and tertiary fallbacks.</Choice><Choice icon="→" title="Skip AI setup" onClick={()=>go('search-news',{ai_skipped:true})}>Trading and portfolio features remain available.</Choice></div><div className="ob-panel"><strong>Your starting defaults</strong><p>Standard workflow prompts, sentiment strategy, execution-safety values, and FIFO cost basis are ready to use and can be changed in Settings.</p></div></>; }
  if (page.startsWith('ai-') && page!=='ai-choice') { const tier=page.replace('ai-',''); title=`Configure ${tier} AI`; subtitle=tier==='primary'?'Choose the first provider used for analysis.':'Add an optional fallback provider.'; body=renderAiTier(tier); auxiliary=tier!=='primary'?<button className="ob-button secondary" onClick={()=>afterAiTier(tier)}>Skip {tier}</button>:null; primary=status.ai_tiers?.[tier]?.configured?()=>afterAiTier(tier):null; primaryLabel=tier==='tertiary'?'Continue to Search & News':'Continue'; }
  if (page === 'search-news') { title='Connect search and news grounding'; subtitle='Optional services can give AI workflows current web and market-news context.'; body=<div className="ob-grid"><Field label="Brave Search API Key"><input type="password" value={search.brave} onChange={e=>setSearch({...search,brave:e.target.value})} placeholder={status.search_configured?'Saved key available':'Optional'} /></Field><Field label="Fallback Brave Search Key"><input type="password" value={search.fallback} onChange={e=>setSearch({...search,fallback:e.target.value})} placeholder="Optional" /></Field><Field label="NewsAPI.org API Key" full><input type="password" value={search.news} onChange={e=>setSearch({...search,news:e.target.value})} placeholder="Optional" /></Field></div>; auxiliary=<button className="ob-button secondary" onClick={()=>go('telegram',{search_skipped:true})}>Skip</button>; primary=saveSearch; primaryLabel='Test, Save & Continue'; }
  if (page === 'telegram') { title='Set up Telegram notifications?'; subtitle='Telegram is optional. Send a test message before saving.'; body=<><div className="ob-grid"><Field label="Telegram Bot Token"><input type="password" value={telegram.token} onChange={e=>setTelegram({...telegram,token:e.target.value})} placeholder={status.telegram_configured?'Saved token available':'Enter bot token'} /></Field><Field label="Telegram Chat ID"><input value={telegram.chatId} onChange={e=>setTelegram({...telegram,chatId:e.target.value})} placeholder="Enter chat ID" /></Field></div>{status.telegram_configured&&<Notice type="success">✓ Telegram has delivered a test message.</Notice>}</>; auxiliary=<button className="ob-button secondary" onClick={()=>go('review',{telegram_skipped:true})}>Skip</button>; primary=status.telegram_configured?()=>go('review'):testTelegram; primaryLabel=status.telegram_configured?'Continue to Review':'Send Test Message'; }
  if (page === 'review') { title='Review your setup'; subtitle='Open any section to make changes before entering the Dashboard.'; const rows=[['Account & security',status.two_factor_enabled?'2FA enabled':'2FA deferred','security-choice'],['Required exchange gate',[status.binance_verified&&'Binance.US',status.webull_verified&&'Webull'].filter(Boolean).join(' • '),'exchanges'],['AI providers',status.ai_skipped?'Skipped':'Configured providers can be changed','ai-choice'],['Search & news',status.search_configured?'Configured':'Skipped or not configured','search-news'],['Telegram',status.telegram_configured?'Test message delivered':'Skipped','telegram']]; body=<><div className="ob-review">{rows.map(([name,detail,target])=><button key={name} onClick={()=>go(target)}><span><strong>{name}</strong><small>{detail}</small></span><span>Edit ›</span></button>)}</div><Notice type="success"><strong>Ready for Dashboard.</strong> At least one exchange is connected and every required setup item is complete.</Notice></>; primary=finish; primaryLabel='Finish & Open Dashboard'; }

  return <div className="ob-page"><header className="ob-header"><BrandIcon/><span><strong>Crypto &amp; Securities Dashboard</strong><small>CSDapp.online</small></span><ThemeButton isLightMode={isLightMode} toggleTheme={toggleTheme}/></header><main className="ob-shell"><aside className="ob-rail"><h2>Welcome to Crypto &amp; Securities Dashboard</h2><p>Let’s configure your secure trading workspace.</p>{RAIL_STEPS.map((name,index)=><div key={name} className={`ob-step ${index<step?'done':''} ${index===step?'active':''}`}><span>{index<step?'✓':index+1}</span>{name}</div>)}<div className="ob-resume"><strong>Safe to leave</strong><small>Progress is saved after each completed step. Signing back in resumes at the first incomplete requirement.</small></div></aside><div style={{display:'flex',flexDirection:'column',gap:'20px'}}><section className="ob-card"><div className="ob-progress"><i style={{width:`${((step+1)/6)*100}%`}}/></div><div className="ob-card-head"><small>Step {step+1} of 6</small><h1>{title}</h1><p>{subtitle}</p></div><div className="ob-card-body">{message&&<Notice type={message.type}>{message.text}</Notice>}{body}</div><footer className="ob-footer"><button className="ob-button link" onClick={logout}>Exit setup</button>{BACK_PAGE[page]&&<button className="ob-button secondary" onClick={back} disabled={busy}>Back</button>}<span/>{auxiliary}{primary&&<button className="ob-button primary" onClick={primary} disabled={busy}>{busy?'Working…':primaryLabel}</button>}</footer></section><footer style={{textAlign:'center',color:'var(--text-tertiary, #888)',fontSize:'13px',paddingBottom:'24px'}}>Crypto &amp; Securities Dashboard version {APP_VERSION}. © 2026 Cavallaro Services, LLC. All rights reserved.</footer></div></main>{skip2faModal&&<div className="ob-modal-backdrop"><div className="ob-modal"><small>Security reminder</small><h2>Live trading will remain disabled</h2><p>You may complete onboarding without two-factor authentication, but you cannot place or cancel live trades until 2FA is configured and verified. This requirement helps protect your connected accounts and assets.</p><Notice type="warning">Paper trading remains available if you connect an eligible Webull paper account.</Notice><div><button className="ob-button secondary" onClick={()=>{setSkip2faModal(false);start2fa();}}>Set Up 2FA</button><button className="ob-button primary" onClick={defer2fa}>I Understand — Continue</button></div></div></div>}</div>;
}
