import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import axios from 'axios';
import { useAuth } from '../components/AuthContext';
import { FaToggleOn, FaToggleOff, FaInfoCircle } from 'react-icons/fa';
import { useSearchParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { formatEasternDateTime } from '../utils/dateTime';

const SENTIMENT_VARIABLES = [
  { label: 'Buy Immediately', code: 'BI', kind: 'directional', direction: 'up', correctKey: 'sentiment_buy_immediately_correct_pct', wrongKey: 'sentiment_buy_immediately_wrong_pct' },
  { label: 'Consider Buying', code: 'CB', kind: 'directional', direction: 'up', correctKey: 'sentiment_consider_buying_correct_pct', wrongKey: 'sentiment_consider_buying_wrong_pct' },
  { label: 'Hold', code: 'H', kind: 'hold', steadyKey: 'sentiment_hold_steady_pct', wrongKey: 'sentiment_hold_wrong_pct' },
  { label: 'Consider Selling', code: 'CS', kind: 'directional', direction: 'down', correctKey: 'sentiment_consider_selling_correct_pct', wrongKey: 'sentiment_consider_selling_wrong_pct' },
  { label: 'Sell Immediately', code: 'SI', kind: 'directional', direction: 'down', correctKey: 'sentiment_sell_immediately_correct_pct', wrongKey: 'sentiment_sell_immediately_wrong_pct' },
];

const sentimentThresholdError = (value, minimum = 0.01) => {
  const raw = String(value ?? '').trim();
  if (!raw) return 'A value is required.';
  if (!/^\d+(?:\.\d{1,2})?$/.test(raw)) return 'Enter a non-negative number with no more than two decimal places.';
  if (Number(raw) < minimum) return `Enter a value of at least ${minimum.toFixed(2)}%.`;
  return '';
};

const holdThresholdErrors = settings => {
  const steadyError = sentimentThresholdError(settings.sentiment_hold_steady_pct, 0);
  let wrongError = sentimentThresholdError(settings.sentiment_hold_wrong_pct, 0);
  if (!steadyError && !wrongError && Number(settings.sentiment_hold_wrong_pct) <= Number(settings.sentiment_hold_steady_pct)) {
    wrongError = 'Must be greater than the Hold Steady Range.';
  }
  return { steadyError, wrongError };
};

const formatThreshold = value => Number(value).toFixed(2);

const EVENT_STRATEGY_DURATIONS = [
  'FIFTEEN_MINUTES', 'HOURLY', 'DAILY', 'WEEKLY',
  'MONTHLY', 'ANNUAL', 'ONE_OFF', 'CUSTOM',
];

const getDefaultModel = (provider, options) => {
  if (!options || !provider) return '';
  const models = options[provider] || [];
  if (Array.isArray(models) && models.length > 0) {
    const nonExp = models.find(m => m && typeof m.label === 'string' && !m.label.includes('(exp)'));
    return nonExp ? (nonExp.value || nonExp) : (models[0]?.value || models[0] || '');
  }
  return '';
};

const sanitizeModel = (provider, model, options) => {
  if (!options || !provider) return model || '';
  const validList = options[provider] || [];
  if (!Array.isArray(validList) || validList.length === 0) return model || '';
  const validValues = validList.map((item) => (item && typeof item === 'object' ? item.value : item));
  return (model && validValues.includes(model)) ? model : getDefaultModel(provider, options);
};

const getHeadlineCalloutStyle = (status, isLight) => {
  const norm = String(status || '').toUpperCase();
  if (norm === 'ATTENTION_REQUIRED' || norm === 'WARN' || norm === 'WARNING') {
    return {
      bg: isLight ? '#fffbeb' : 'rgba(245, 158, 11, 0.1)',
      border: '1px solid rgba(245, 158, 11, 0.35)',
      color: isLight ? '#92400e' : '#fcd34d',
      icon: '⚠️'
    };
  }
  if (norm === 'DEGRADED') {
    return {
      bg: isLight ? '#fff7ed' : 'rgba(249, 115, 22, 0.1)',
      border: '1px solid rgba(249, 115, 22, 0.35)',
      color: isLight ? '#9a3412' : '#fdba74',
      icon: '⚡'
    };
  }
  if (norm === 'ERROR' || norm === 'CRITICAL') {
    return {
      bg: isLight ? '#fef2f2' : 'rgba(239, 68, 68, 0.1)',
      border: '1px solid rgba(239, 68, 68, 0.35)',
      color: isLight ? '#991b1b' : '#fca5a5',
      icon: '🚨'
    };
  }
  return {
    bg: isLight ? '#f0fdf4' : 'rgba(34, 197, 94, 0.08)',
    border: '1px solid rgba(34, 197, 94, 0.25)',
    color: isLight ? '#166534' : '#86efac',
    icon: '💡'
  };
};

const getAuditWindowHours = (report, fallbackHours) => {
  if (report?.period_start && report?.period_end) {
    try {
      const diffHours = Math.round((new Date(report.period_end) - new Date(report.period_start)) / 3600000);
      if (diffHours > 0) return `${diffHours} Hours`;
    } catch {
      // fallback
    }
  }
  return `${fallbackHours || 6} Hours`;
};

const formatReportMarkdown = (rawContent, summary) => {
  const content = String(rawContent || summary || 'No detailed content available.').trim();
  if (content.startsWith('{') && content.endsWith('}')) {
    try {
      const data = JSON.parse(content);
      if (data && typeof data === 'object') {
        if (data.content_markdown && typeof data.content_markdown === 'string' && !data.content_markdown.trim().startsWith('{')) {
          return data.content_markdown;
        }
        const statusVal = String(data.overall_status || data.status || 'HEALTHY').toUpperCase();
        const headline = data.headline || (data.issues?.length ? `Audit completed: ${data.issues.length} operational issue(s) analyzed.` : 'AI operational audit completed.');
        const lines = [
          '## Event Strategy Engine Operational AI Audit Report',
          '',
          `**Audit Status:** \`${statusVal}\`  `,
          `**Executive Verdict:** ${headline}  `,
          '',
          '---',
        ];
        if (Array.isArray(data.issues) && data.issues.length > 0) {
          lines.push('\n### 🚨 Detected Operational Issues & Bottlenecks\n');
          data.issues.forEach((iss) => {
            if (iss && typeof iss === 'object') {
              const itype = (iss.type || iss.name || 'Operational Notice').replace(/_/g, ' ');
              const countStr = iss.count !== undefined ? ` **(Count: ${iss.count})**` : '';
              const desc = iss.description || iss.details || iss.message || '';
              lines.push(`- **${itype}**${countStr}: ${desc}`);
            } else {
              lines.push(`- ${iss}`);
            }
          });
        }
        if (data.metrics_summary && typeof data.metrics_summary === 'object') {
          const ms = data.metrics_summary;
          lines.push('\n### 📊 Telemetry & Execution Summary\n');
          if (ms.heartbeat_age_seconds !== undefined) {
            lines.push(`- **Worker Heartbeat Age:** \`${Number(ms.heartbeat_age_seconds).toFixed(1)}s\``);
          }
          lines.push(`- **Scans Analyzed:** \`${ms.scans_count ?? 0}\` (${ms.scanned_contracts ?? 0} contracts evaluated)`);
          lines.push(`- **Decisions Recorded:** \`${ms.decisions_count ?? 0}\` (${ms.eligible_count ?? 0} qualified trades, \`${ms.no_trade_count ?? 0}\` held)`);
          lines.push(`- **Operational Logs:** \`${ms.total_logs ?? ((ms.error_count ?? 0) + (ms.warning_count ?? 0) + (ms.info_count ?? 0))}\` total (\`${ms.error_count ?? 0}\` errors, \`${ms.warning_count ?? 0}\` warnings, \`${ms.info_count ?? 0}\` info)`);
          if (ms.top_reason_codes && typeof ms.top_reason_codes === 'object') {
            const reasons = Object.entries(ms.top_reason_codes).map(([k, v]) => `\`${k.replace(/_/g, ' ')}\` (${v})`).join(', ');
            if (reasons) lines.push(`- **Top Decision Hold Reasons:** ${reasons}`);
          }
          if (ms.ai_evaluations && typeof ms.ai_evaluations === 'object') {
            const evals = Object.entries(ms.ai_evaluations).map(([k, v]) => `**${k}**: \`${v}\``).join(', ');
            if (evals) lines.push(`- **AI Model Predictions:** ${evals}`);
          }
        }
        if (Array.isArray(data.recommendations) && data.recommendations.length > 0) {
          lines.push('\n### 💡 Actionable Recommendations & Tuning\n');
          data.recommendations.forEach((rec, idx) => {
            if (rec && typeof rec === 'object') {
              const actionTitle = (rec.action || rec.title || `Recommendation ${idx + 1}`).replace(/_/g, ' ');
              const details = rec.details || rec.description || rec.text || '';
              lines.push(`${idx + 1}. **${actionTitle}**${details ? `: ${details}` : ''}`);
            } else {
              lines.push(`${idx + 1}. ${rec}`);
            }
          });
        }
        if (data.next_steps) {
          lines.push('\n### 🎯 Next Steps\n');
          if (Array.isArray(data.next_steps)) {
            data.next_steps.forEach((s) => lines.push(`- ${s}`));
          } else {
            lines.push(String(data.next_steps));
          }
        }
        return lines.join('\n');
      }
    } catch {
      // ignore
    }
  }
  return content;
};

export default function Settings({ isLightMode }) {
  // Pull user so we can gate admin-only sections without runtime errors
  const { user, isLoggingOut } = useAuth();
  const [modelOptions, setModelOptions] = useState({
    openai: [],
    zai: [],
    perplexity: [],
    gemini: [],
    inception: [],
    ollama: [],
  });
  const [settings, setSettings] = useState({
    api_key: '',
    api_secret: '',
    binance_testnet: true,
    webull_app_key: '',
    webull_app_secret: '',
    webull_environment: 'production',
    webull_configured: false,
    openai_key: '',
    zai_key: '',
    perplexity_key: '',
    gemini_key: '',
    inception_key: '',
    ai_provider: 'openai',
    ai_model: '',
    ai_reasoning_level: 'medium',

    // Secondary AI Integration
    ai_provider_fallback: '',
    ai_model_fallback: '',
    ai_reasoning_level_fallback: 'medium',
    ai_provider_secondary: '',
    ai_model_secondary: '',
    ai_reasoning_level_secondary: 'medium',
    openai_key_fallback: '',
    zai_key_fallback: '',
    perplexity_key_fallback: '',
    gemini_key_fallback: '',
    inception_key_fallback: '',

    // Tertiary AI Integration
    ai_provider_tertiary: '',
    ai_model_tertiary: '',
    ai_reasoning_level_tertiary: 'medium',
    openai_key_tertiary: '',
    zai_key_tertiary: '',
    perplexity_key_tertiary: '',
    gemini_key_tertiary: '',
    inception_key_tertiary: '',

    // Quartan AI Integration (fourth fallback)
    ai_provider_quartan: '',
    ai_model_quartan: '',
    ai_reasoning_level_quartan: 'medium',
    openai_key_quartan: '',
    zai_key_quartan: '',
    perplexity_key_quartan: '',
    gemini_key_quartan: '',
    inception_key_quartan: '',

    telegram_token: '',
    telegram_chat_id: '',
    news_api: '',
    credentials_encryption_key: '',
    // AI Settings
    ai_risk_tolerance: 'moderate',
    ai_confidence_threshold: 75,
    ai_outcome_neutral_threshold_pct: 5.0,
    sentiment_buy_immediately_correct_pct: '5.00',
    sentiment_buy_immediately_wrong_pct: '5.00',
    sentiment_consider_buying_correct_pct: '5.00',
    sentiment_consider_buying_wrong_pct: '5.00',
    sentiment_hold_steady_pct: '1.00',
    sentiment_hold_wrong_pct: '5.00',
    sentiment_consider_selling_correct_pct: '5.00',
    sentiment_consider_selling_wrong_pct: '5.00',
    sentiment_sell_immediately_correct_pct: '5.00',
    sentiment_sell_immediately_wrong_pct: '5.00',
    max_slippage_pct: 2.0,
    ai_notifications_enabled: true,
    ai_analysis_frequency: 'daily',
    sentiment_analysis_frequency_hours: 24,
    watchlist_sentiment_analysis_frequency_hours: 24,
    sentiment_history_lookback_hours: 12,
    watchlist_sentiment_history_lookback_hours: 12,
    sentiment_forecast_horizon_hours: 24,
    watchlist_sentiment_forecast_horizon_hours: 24,
    volatility_hours: 24,
    automated_trigger_confirmation_minutes: 15,
    toast_notifications_enabled: true,
    tax_cost_basis_method: 'fifo',
    ai_prompts: {
      market_analysis_pre: '',
      market_analysis_post: '',
      risk_assessment_pre: '',
      risk_assessment_post: '',
      portfolio_review_pre: '',
      portfolio_review_post: '',
      coin_analysis_pre: '',
      news_analysis_pre: '',
      news_analysis_post: '',
      coin_analysis_post: '',
      sentiment_prompt_pre: '',
      sentiment_prompt_post: '',
      watchlist_sentiment_prompt_pre: '',
      watchlist_sentiment_prompt_post: ''
    },
    copilot_chat_pre: '',
    copilot_chat_post: '',
    event_strategy_audit_hours: 6,
    event_strategy_audit_prompt: ''
  });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState(''); // 'success' or 'error'
  const [testingBinance, setTestingBinance] = useState(false);
  const [testingWebull, setTestingWebull] = useState(false);
  const [loadingWebullAccounts, setLoadingWebullAccounts] = useState(false);
  const [webullAccounts, setWebullAccounts] = useState([]);
  const [enabledAccountIds, setEnabledAccountIds] = useState([]);
  const [webullAccountsMessage, setWebullAccountsMessage] = useState('');
  const [loadingWebullPreview, setLoadingWebullPreview] = useState(false);
  const [webullPortfolioPreview, setWebullPortfolioPreview] = useState([]);
  const [webullPreviewMessage, setWebullPreviewMessage] = useState('');
  const [syncingWebullPortfolio, setSyncingWebullPortfolio] = useState(false);
  const [webullImportMessage, setWebullImportMessage] = useState('');
  const [testingTrading, setTestingTrading] = useState(false);
  const [testingPrimaryAi, setTestingPrimaryAi] = useState(false);
  const [primaryAiTestResult, setPrimaryAiTestResult] = useState(null);
  const [testingBraveApi, setTestingBraveApi] = useState(false);
  const [testingBraveApiFallback, setTestingBraveApiFallback] = useState(false);
  const [braveApiTestResult, setBraveApiTestResult] = useState(null);
  const [braveApiFallbackTestResult, setBraveApiFallbackTestResult] = useState(null);
  const [testingFallback, setTestingFallback] = useState(false);
  const [fallbackTestResult, setFallbackTestResult] = useState(null);
  const [testingTertiaryAi, setTestingTertiaryAi] = useState(false);
  const [tertiaryAiTestResult, setTertiaryAiTestResult] = useState(null);
  const [testingQuartanAi, setTestingQuartanAi] = useState(false);
  const [quartanAiTestResult, setQuartanAiTestResult] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [encryptionStatus, setEncryptionStatus] = useState({ configured: false, persisted: false });
  const [encryptionKeyDirty, setEncryptionKeyDirty] = useState(false);
  const [forcingAnalysis, setForcingAnalysis] = useState(false);
  const [forceAnalysisResult, setForceAnalysisResult] = useState(null);
  const [upgrading, setUpgrading] = useState(false);
  const [showUpgradeModal, setShowUpgradeModal] = useState(false);
  const [includeBeta, setIncludeBeta] = useState(true);
  const [availableVersion, setAvailableVersion] = useState(null);
  const [isFetchingVersion, setIsFetchingVersion] = useState(false);
  const [versionLookupError, setVersionLookupError] = useState('');

  // Event Contract Strategy Engine (paper / signal-only) state
  const [eventStrategyConfig, setEventStrategyConfig] = useState(null);
  const [eventStrategyHealth, setEventStrategyHealth] = useState(null);
  const [eventStrategyLogs, setEventStrategyLogs] = useState([]);
  const [eventStrategyBusy, setEventStrategyBusy] = useState(false);
  const [eventStrategyMessage, setEventStrategyMessage] = useState('');
  const [showEventStrategyLogs, setShowEventStrategyLogs] = useState(false);
  const [eventStrategyReport, setEventStrategyReport] = useState(null);
  const [eventStrategyReportHistory, setEventStrategyReportHistory] = useState([]);
  const [showEventStrategyReport, setShowEventStrategyReport] = useState(false);
  const [eventStrategyReportLoading, setEventStrategyReportLoading] = useState(false);
  const [eventStrategyReportGenerating, setEventStrategyReportGenerating] = useState(false);
  const [eventStrategyReportError, setEventStrategyReportError] = useState('');
  const [eventStrategyReportMessage, setEventStrategyReportMessage] = useState('');
  const [showEventStrategyAIModal, setShowEventStrategyAIModal] = useState(false);
  const [eventStrategyAIConfig, setEventStrategyAIConfig] = useState({
    audit_hours: 6,
    audit_prompt: '',
    ai_config: {
      primary: { provider: 'gemini', model: 'gemini-3.8-flash', reasoning_level: 'medium', api_key: '', has_key: false },
      secondary: { provider: 'ollama', model: 'gpt-oss:120b-cloud', reasoning_level: 'medium', api_key: '', has_key: false },
      tertiary: { provider: 'ollama', model: 'qwen2.5:14b', reasoning_level: 'medium', api_key: '', has_key: false },
    }
  });
  const [eventStrategyAILoading, setEventStrategyAILoading] = useState(false);
  const [eventStrategyAISaving, setEventStrategyAISaving] = useState(false);
  const [eventStrategyAITesting, setEventStrategyAITesting] = useState({ primary: false, secondary: false, tertiary: false });
  const [eventStrategyAITestResults, setEventStrategyAITestResults] = useState({ primary: null, secondary: null, tertiary: null });
  const [showEventStrategyApiKey, setShowEventStrategyApiKey] = useState({ primary: false, secondary: false, tertiary: false });
  // Keep the duration draft in a ref as well as React state. This makes a
  // checkbox change available to Save immediately, even when the user clicks
  // Save before React has committed the next render.
  const eventStrategyDurationsRef = useRef(null);

  // 2FA State
  const [twoFactorEnabled, setTwoFactorEnabled] = useState(false);
  const [showQRCode, setShowQRCode] = useState(false);
  const [qrCodeData, setQRCodeData] = useState(null);
  const [verificationCode, setVerificationCode] = useState('');
  const [disableCode, setDisableCode] = useState('');
  const [twoFactorLoading, setTwoFactorLoading] = useState(false);
  const [twoFactorMessage, setTwoFactorMessage] = useState('');

  const [searchParams, setSearchParams] = useSearchParams();

  const SETTINGS_TABS = [
    { id: 'apis', label: 'Exchange & Broker APIs', icon: '🔌' },
    { id: 'ai-providers', label: 'AI Providers & Models', icon: '🧠' },
    { id: 'ai-prompts', label: 'AI Workflow Prompts', icon: '📝' },
    { id: 'sentiment-strategy', label: 'Sentiment & Strategy', icon: '🎯' },
    { id: 'web-search', label: 'Web Search & News', icon: '🔍' },
    { id: 'security-2fa', label: 'Security & 2FA', icon: '🔐' },
    { id: 'system', label: 'Notifications & System', icon: '⚙️' },
    { id: 'event-strategy', label: 'Event Contract Strategy Engine', icon: '📊' },
  ];
  const isEventStrategyAdmin = Boolean(user?.is_admin || user?.id === 1);
  const isSystemAdmin = Boolean(user?.is_admin || user?.id === 1);
  const visibleSettingsTabs = isEventStrategyAdmin
    ? SETTINGS_TABS
    : SETTINGS_TABS.filter((tab) => tab.id !== 'event-strategy');

  const [activeTab, setActiveTab] = useState(() => {
    const tabParam = searchParams.get('tab');
    const validTabs = ['apis', 'ai-providers', 'ai-prompts', 'sentiment-strategy', 'web-search', 'security-2fa', 'system'];
    if (isEventStrategyAdmin) validTabs.push('event-strategy');
    if (tabParam && validTabs.includes(tabParam)) return tabParam;
    const sectionParam = searchParams.get('section');
    if (sectionParam === '2fa') return 'security-2fa';
    if (sectionParam === 'ai-settings' || sectionParam === 'ai-prompts') return 'ai-prompts';
    return 'apis';
  });

  const handleTabChange = (tabId) => {
    if (tabId === 'event-strategy' && !isEventStrategyAdmin) return;
    setActiveTab(tabId);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set('tab', tabId);
      return next;
    }, { replace: true });
  };

  // Delete Account State
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  useEffect(() => {
    const tabParam = searchParams.get('tab');
    const validTabs = ['apis', 'ai-providers', 'ai-prompts', 'sentiment-strategy', 'web-search', 'security-2fa', 'system'];
    if (isEventStrategyAdmin) validTabs.push('event-strategy');
    if (tabParam && validTabs.includes(tabParam)) {
      setActiveTab(tabParam);
    }
  }, [searchParams, isEventStrategyAdmin]);

  useEffect(() => {
    if (user && !isEventStrategyAdmin && activeTab === 'event-strategy') {
      setActiveTab('apis');
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set('tab', 'apis');
        return next;
      }, { replace: true });
    }
  }, [user, isEventStrategyAdmin, activeTab, setSearchParams]);

  // Auto-resize textarea function
  const autoResizeTextarea = (textarea) => {
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = textarea.scrollHeight + 'px';
    }
  };

  useEffect(() => {
    fetchSettings();
    fetchWebullAccounts(false);
  }, []);

  const loadEventStrategy = async () => {
    try {
      const response = await axios.get('/api/webull/event-algo/status', { withCredentials: true });
      if (response.data?.success) {
        const nextConfig = response.data.config || null;
        const nextDurations = Array.isArray(nextConfig?.durations) ? [...nextConfig.durations] : [];
        eventStrategyDurationsRef.current = nextConfig ? nextDurations : null;
        setEventStrategyConfig(nextConfig ? { ...nextConfig, durations: nextDurations } : null);
        setEventStrategyHealth(response.data.health || null);
      }
    } catch (error) {
      setEventStrategyMessage(error.response?.data?.message || 'Unable to load the Event Contract Strategy Engine.');
    }
  };

  useEffect(() => {
    if (activeTab === 'event-strategy' && isEventStrategyAdmin) loadEventStrategy();
  }, [activeTab, isEventStrategyAdmin]);

  const updateEventStrategySignal = (key, value) => {
    setEventStrategyConfig((prev) => ({
      ...prev,
      signal_config: { ...(prev?.signal_config || {}), [key]: value },
    }));
  };

  const updateEventStrategyDuration = (duration, checked) => {
    const current = Array.isArray(eventStrategyDurationsRef.current)
      ? eventStrategyDurationsRef.current
      : (Array.isArray(eventStrategyConfig?.durations) ? eventStrategyConfig.durations : []);
    const next = checked
      ? [...new Set([...current, duration])]
      : current.filter((item) => item !== duration);
    eventStrategyDurationsRef.current = next;
    setEventStrategyConfig((prev) => ({ ...prev, durations: next }));
  };

  const saveEventStrategy = async () => {
    if (!eventStrategyConfig) return;
    setEventStrategyBusy(true);
    setEventStrategyMessage('');
    try {
      const durations = eventStrategyDurationsRef.current ?? eventStrategyConfig.durations ?? [];
      const response = await axios.put('/api/webull/event-algo/config', {
        name: eventStrategyConfig.name,
        enabled: !!eventStrategyConfig.enabled,
        symbols: eventStrategyConfig.symbols,
        durations,
        risk_config: eventStrategyConfig.risk_config,
        signal_config: eventStrategyConfig.signal_config,
        kill_switch: !!eventStrategyConfig.kill_switch,
      }, { withCredentials: true });
      const savedConfig = response.data.config || {};
      const savedDurations = Array.isArray(savedConfig.durations) ? [...savedConfig.durations] : [];
      eventStrategyDurationsRef.current = savedDurations;
      setEventStrategyConfig({ ...savedConfig, durations: savedDurations });
      setEventStrategyMessage('Event Contract Strategy Engine settings saved.');
      await loadEventStrategy();
    } catch (error) {
      setEventStrategyMessage(error.response?.data?.message || 'Unable to save Event Contract Strategy Engine settings.');
    } finally {
      setEventStrategyBusy(false);
    }
  };

  const eventStrategyAction = async (action) => {
    setEventStrategyBusy(true);
    setEventStrategyMessage('');
    try {
      const response = await axios.post(`/api/webull/event-algo/${action}`, action === 'scan' ? { refresh: true } : {}, { withCredentials: true });
      if (response.data?.config) setEventStrategyConfig(response.data.config);
      setEventStrategyMessage(action === 'scan' ? 'Paper scan completed.' : `Engine ${action} request completed.`);
      await loadEventStrategy();
    } catch (error) {
      setEventStrategyMessage(error.response?.data?.message || `Unable to ${action} the engine.`);
    } finally {
      setEventStrategyBusy(false);
    }
  };

  const loadEventStrategyLogs = async () => {
    try {
      const response = await axios.get('/api/webull/event-algo/logs?limit=200', { withCredentials: true });
      setEventStrategyLogs(response.data?.logs || []);
      setShowEventStrategyLogs(true);
    } catch (error) {
      setEventStrategyMessage(error.response?.data?.message || 'Unable to load engine logs.');
    }
  };

  const loadEventStrategyReport = async (reportId = null) => {
    setEventStrategyReportLoading(true);
    setEventStrategyReportError('');
    setEventStrategyReportMessage('');
    try {
      const url = reportId ? `/api/webull/event-algo/report?id=${reportId}` : '/api/webull/event-algo/report';
      const response = await axios.get(url, { withCredentials: true });
      if (response.data?.success) {
        setEventStrategyReport(response.data.report || null);
        setEventStrategyReportHistory(response.data.history || []);
        setShowEventStrategyReport(true);
      } else {
        const errMsg = response.data?.message || 'Unable to load strategy engine report.';
        setEventStrategyReportError(errMsg);
        setEventStrategyMessage(errMsg);
      }
    } catch (error) {
      const errMsg = error.response?.data?.message || error.message || 'Unable to load strategy engine report.';
      setEventStrategyReportError(errMsg);
      setEventStrategyMessage(errMsg);
    } finally {
      setEventStrategyReportLoading(false);
    }
  };

  const generateEventStrategyReportNow = async () => {
    setEventStrategyReportGenerating(true);
    setEventStrategyReportError('');
    setEventStrategyReportMessage('');
    try {
      const response = await axios.post('/api/webull/event-algo/report/generate', { hours: 6 }, { withCredentials: true });
      if (response.data?.success) {
        setEventStrategyReport(response.data.report || null);
        setEventStrategyReportHistory(response.data.history || []);
        setEventStrategyReportMessage('AI audit report generated successfully.');
        setEventStrategyMessage('AI audit report generated successfully.');
      } else {
        const errMsg = response.data?.message || 'Unable to generate AI audit report.';
        setEventStrategyReportError(errMsg);
        setEventStrategyMessage(errMsg);
      }
    } catch (error) {
      const errMsg = error.response?.data?.message || error.message || 'Unable to generate AI audit report.';
      setEventStrategyReportError(errMsg);
      setEventStrategyMessage(errMsg);
    } finally {
      setEventStrategyReportGenerating(false);
    }
  };

  const DEFAULT_EVENT_AUDIT_PROMPT =
    'You are a principal quantitative trading auditor and AI reliability engineer. ' +
    'Your task is to analyze telemetry, execution logs, and decision traces from an autonomous ' +
    'paper-trading strategy worker operating on Webull Event Contracts over an observation window. ' +
    'Evaluate whether the worker is performing properly, whether the collected market data is useful and complete, ' +
    'whether any scans or quotes were missed, what errors or warnings occurred, and how decisions were formed. ' +
    'Cite specific timestamps, contract symbols, reason codes, and log messages as concrete evidence. ' +
    'Format your evaluation as a structured audit with executive verdict, detected operational issues, ' +
    'telemetry summary, actionable tuning recommendations, and next steps.';

  const loadEventStrategyAIConfig = async () => {
    setEventStrategyAILoading(true);
    try {
      const response = await axios.get('/api/webull/event-algo/ai-config', { withCredentials: true });
      if (response.data?.success) {
        setEventStrategyAIConfig({
          audit_hours: response.data.audit_hours ?? 6,
          audit_prompt: response.data.audit_prompt || '',
          ai_config: response.data.ai_config || {
            primary: { provider: 'gemini', model: 'gemini-3.8-flash', reasoning_level: 'medium', api_key: '', has_key: false },
            secondary: { provider: 'ollama', model: 'gpt-oss:120b-cloud', reasoning_level: 'medium', api_key: '', has_key: false },
            tertiary: { provider: 'ollama', model: 'qwen2.5:14b', reasoning_level: 'medium', api_key: '', has_key: false },
          },
        });
      }
    } catch (err) {
      console.error('Failed to load Event Strategy AI configuration:', err);
    } finally {
      setEventStrategyAILoading(false);
    }
  };

  const openEventStrategyAIModal = () => {
    setShowEventStrategyAIModal(true);
    setEventStrategyAITestResults({ primary: null, secondary: null, tertiary: null });
    loadEventStrategyAIConfig();
  };

  const saveEventStrategyAIConfig = async () => {
    setEventStrategyAISaving(true);
    try {
      const response = await axios.post('/api/webull/event-algo/ai-config', eventStrategyAIConfig, { withCredentials: true });
      if (response.data?.success) {
        setEventStrategyMessage('Event Strategy AI configuration saved successfully.');
        setSettings((prev) => ({
          ...prev,
          event_strategy_audit_hours: response.data.audit_hours,
          event_strategy_audit_prompt: response.data.audit_prompt,
        }));
        setEventStrategyAIConfig((prev) => ({
          ...prev,
          audit_hours: response.data.audit_hours,
          audit_prompt: response.data.audit_prompt,
          ai_config: response.data.ai_config,
        }));
        setShowEventStrategyAIModal(false);
      }
    } catch (err) {
      console.error('Failed to save Event Strategy AI config:', err);
      alert(err.response?.data?.message || 'Failed to save AI configuration.');
    } finally {
      setEventStrategyAISaving(false);
    }
  };

  const testEventStrategyAITier = async (tierKey) => {
    setEventStrategyAITesting((prev) => ({ ...prev, [tierKey]: true }));
    setEventStrategyAITestResults((prev) => ({ ...prev, [tierKey]: null }));
    const tierData = eventStrategyAIConfig?.ai_config?.[tierKey] || {};
    try {
      const res = await axios.post('/api/webull/event-algo/ai-test', {
        tier: tierKey,
        provider: tierData.provider,
        model: tierData.model,
        reasoning_level: tierData.reasoning_level,
        api_key: tierData.api_key,
      }, { withCredentials: true });
      setEventStrategyAITestResults((prev) => ({
        ...prev,
        [tierKey]: {
          success: Boolean(res.data?.success),
          message: res.data?.message || 'Connection successful!',
        }
      }));
    } catch (err) {
      setEventStrategyAITestResults((prev) => ({
        ...prev,
        [tierKey]: {
          success: false,
          message: err.response?.data?.message || err.message || 'Connection test failed',
        }
      }));
    } finally {
      setEventStrategyAITesting((prev) => ({ ...prev, [tierKey]: false }));
    }
  };

  const updateEventStrategyAITierField = (tierKey, field, value) => {
    setEventStrategyAIConfig((prev) => {
      const currentTier = prev?.ai_config?.[tierKey] || {};
      const updatedTier = { ...currentTier, [field]: value };
      if (field === 'provider') {
        const availableModels = modelOptions[value] || [];
        if (availableModels.length > 0) {
          updatedTier.model = availableModels[0].value;
        } else if (value === 'gemini') {
          updatedTier.model = 'gemini-3.8-flash';
        } else if (value === 'ollama') {
          updatedTier.model = tierKey === 'tertiary' ? 'qwen2.5:14b' : 'gpt-oss:120b-cloud';
        } else if (value === 'openai') {
          updatedTier.model = 'gpt-5.4-mini';
        }
      }
      return {
        ...prev,
        ai_config: {
          ...(prev?.ai_config || {}),
          [tierKey]: updatedTier,
        },
      };
    });
  };

  // Auto-resize all textareas when settings change
  useEffect(() => {
    const textareas = document.querySelectorAll('textarea');
    textareas.forEach(textarea => autoResizeTextarea(textarea));
  }, [settings.ai_prompts]);

  const fetchSettings = async () => {
    // Don't make API calls if we're logging out
    if (isLoggingOut || window.globalIsLoggingOut) {
      return;
    }

    setLoading(true);
    try {
      console.log('Fetching settings...');

      // Fetch AI models first
      let currentModelOptions = { openai: [], zai: [], perplexity: [], gemini: [], inception: [], ollama: [] };
      try {
        const modelsResponse = await axios.get('/api/ai/models', { withCredentials: true });
        if (modelsResponse.data) {
          currentModelOptions = modelsResponse.data;
          setModelOptions(currentModelOptions);
        }
      } catch (modelError) {
        console.error('Failed to fetch AI models:', modelError);
      }

      // Fetch regular settings
      const settingsResponse = await axios.get('/api/settings', { withCredentials: true });
      console.log('Fetched settings:', settingsResponse.data);
      const encryptionConfigured = Boolean(settingsResponse.data.credentials_encryption_key_configured);
      const encryptionPersisted = Boolean(settingsResponse.data.credentials_encryption_key_persisted);
      setEncryptionStatus({
        configured: encryptionConfigured,
        persisted: encryptionPersisted
      });
      setEncryptionKeyDirty(false);
      const sanitizedSettingsResponse = { ...settingsResponse.data };
      delete sanitizedSettingsResponse.credentials_encryption_key_configured;
      delete sanitizedSettingsResponse.credentials_encryption_key_persisted;
      sanitizedSettingsResponse.credentials_encryption_key = encryptionConfigured ? '********' : '';
      sanitizedSettingsResponse.webull_app_key = sanitizedSettingsResponse.webull_configured ? '********' : '';
      sanitizedSettingsResponse.webull_app_secret = sanitizedSettingsResponse.webull_configured ? '********' : '';

      setSettings((prev) => {
        const mergedSettings = {
          ...sanitizedSettingsResponse,
        };

        const provider = mergedSettings.ai_provider || prev.ai_provider || 'openai';
        let model = mergedSettings.ai_model;
        const sanitizedModel = sanitizeModel(provider, model, currentModelOptions);

        const secondaryProvider = mergedSettings.ai_provider_secondary || mergedSettings.ai_provider_fallback || prev.ai_provider_secondary || prev.ai_provider_fallback || '';
        let secondaryModel = mergedSettings.ai_model_secondary || mergedSettings.ai_model_fallback;
        const sanitizedSecondaryModel = secondaryProvider ? sanitizeModel(secondaryProvider, secondaryModel, currentModelOptions) : (secondaryModel || '');

        const tertiaryProvider = mergedSettings.ai_provider_tertiary || prev.ai_provider_tertiary || '';
        let tertiaryModel = mergedSettings.ai_model_tertiary;
        const sanitizedTertiaryModel = tertiaryProvider ? sanitizeModel(tertiaryProvider, tertiaryModel, currentModelOptions) : (tertiaryModel || '');

        const quartanProvider = mergedSettings.ai_provider_quartan || prev.ai_provider_quartan || '';
        let quartanModel = mergedSettings.ai_model_quartan;
        const sanitizedQuartanModel = quartanProvider ? sanitizeModel(quartanProvider, quartanModel, currentModelOptions) : (quartanModel || '');

        return {
          ...prev,
          ...mergedSettings,
          ai_provider: provider,
          ai_model: sanitizedModel,
          ai_provider_fallback: secondaryProvider,
          ai_model_fallback: sanitizedSecondaryModel,
          ai_reasoning_level_fallback: mergedSettings.ai_reasoning_level_secondary || mergedSettings.ai_reasoning_level_fallback || prev.ai_reasoning_level_fallback || 'medium',
          ai_provider_secondary: secondaryProvider,
          ai_model_secondary: sanitizedSecondaryModel,
          ai_reasoning_level_secondary: mergedSettings.ai_reasoning_level_secondary || mergedSettings.ai_reasoning_level_fallback || prev.ai_reasoning_level_fallback || 'medium',
          ai_provider_tertiary: tertiaryProvider,
          ai_model_tertiary: sanitizedTertiaryModel,
          ai_reasoning_level_tertiary: mergedSettings.ai_reasoning_level_tertiary || prev.ai_reasoning_level_tertiary || 'medium',
          ai_provider_quartan: quartanProvider,
          ai_model_quartan: sanitizedQuartanModel,
          ai_reasoning_level_quartan: mergedSettings.ai_reasoning_level_quartan || prev.ai_reasoning_level_quartan || 'medium'
        };
      });
    } catch (error) {
      console.error('Failed to fetch settings:', error);
      console.error('Error response:', error.response?.data);
      setMessage('Failed to load settings');
      setMessageType('error');
    } finally {
      setLoading(false);
    }
  };

  // Ollama is a local administrator-only provider. Refresh its model catalog
  // whenever it is selected so newly installed models appear without a full
  // page reload. The server enforces the same administrator restriction.
  useEffect(() => {
    if (!isEventStrategyAdmin) return undefined;
    const selectedProviders = [
      settings.ai_provider,
      settings.ai_provider_secondary || settings.ai_provider_fallback,
      settings.ai_provider_tertiary,
      settings.ai_provider_quartan,
    ];
    if (!selectedProviders.includes('ollama')) return undefined;

    let active = true;
    axios.get('/api/ai/models', { withCredentials: true })
      .then((response) => {
        if (!active || !response.data) return;
        const nextOptions = response.data;
        setModelOptions(nextOptions);
        const ollamaModels = Array.isArray(nextOptions.ollama) ? nextOptions.ollama : [];
        if (ollamaModels.length) {
          setSettings((prev) => {
            const next = { ...prev };
            const firstModel = ollamaModels[0]?.value || ollamaModels[0];
            if (prev.ai_provider === 'ollama' && !prev.ai_model) next.ai_model = firstModel;
            if ((prev.ai_provider_secondary || prev.ai_provider_fallback) === 'ollama' && !(prev.ai_model_secondary || prev.ai_model_fallback)) {
              next.ai_model_secondary = firstModel;
              next.ai_model_fallback = firstModel;
            }
            if (prev.ai_provider_tertiary === 'ollama' && !prev.ai_model_tertiary) next.ai_model_tertiary = firstModel;
            if (prev.ai_provider_quartan === 'ollama' && !prev.ai_model_quartan) next.ai_model_quartan = firstModel;
            return next;
          });
        }
      })
      .catch((error) => console.error('Failed to refresh Ollama models:', error));
    return () => { active = false; };
  }, [isEventStrategyAdmin, settings.ai_provider, settings.ai_provider_secondary, settings.ai_provider_fallback, settings.ai_provider_tertiary, settings.ai_provider_quartan]);

  const handleInputChange = (field, value) => {
    console.log(`Updating ${field} to: ${value}`);
    setSettings((prev) => {
      if (field === 'ai_provider') {
        const sanitizedModel = sanitizeModel(value, value === 'ollama' ? '' : prev.ai_model, modelOptions);
        return {
          ...prev,
          ai_provider: value,
          ai_model: sanitizedModel,
        };
      }

      if (field === 'ai_model') {
        const sanitizedModel = sanitizeModel(prev.ai_provider, value, modelOptions);
        return {
          ...prev,
          ai_model: sanitizedModel,
        };
      }

      if (field === 'ai_provider_fallback' || field === 'ai_provider_secondary') {
        const sanitizedModel = value ? sanitizeModel(value, value === 'ollama' ? '' : (prev.ai_model_secondary || prev.ai_model_fallback), modelOptions) : '';
        return {
          ...prev,
          ai_provider_fallback: value,
          ai_provider_secondary: value,
          ai_model_fallback: sanitizedModel,
          ai_model_secondary: sanitizedModel,
        };
      }

      if (field === 'ai_model_fallback' || field === 'ai_model_secondary') {
        const prov = prev.ai_provider_secondary || prev.ai_provider_fallback;
        const sanitizedModel = prov ? sanitizeModel(prov, value, modelOptions) : value;
        return {
          ...prev,
          ai_model_fallback: sanitizedModel,
          ai_model_secondary: sanitizedModel,
        };
      }

      if (field === 'ai_provider_tertiary') {
        const sanitizedModel = value ? sanitizeModel(value, value === 'ollama' ? '' : prev.ai_model_tertiary, modelOptions) : '';
        return {
          ...prev,
          ai_provider_tertiary: value,
          ai_model_tertiary: sanitizedModel,
        };
      }

      if (field === 'ai_model_tertiary') {
        const sanitizedModel = prev.ai_provider_tertiary ? sanitizeModel(prev.ai_provider_tertiary, value, modelOptions) : value;
        return {
          ...prev,
          ai_model_tertiary: sanitizedModel,
        };
      }

      if (field === 'ai_provider_quartan') {
        const sanitizedModel = value ? sanitizeModel(value, value === 'ollama' ? '' : prev.ai_model_quartan, modelOptions) : '';
        return {
          ...prev,
          ai_provider_quartan: value,
          ai_model_quartan: sanitizedModel,
        };
      }

      if (field === 'ai_model_quartan') {
        const sanitizedModel = prev.ai_provider_quartan ? sanitizeModel(prev.ai_provider_quartan, value, modelOptions) : value;
        return {
          ...prev,
          ai_model_quartan: sanitizedModel,
        };
      }

      if (field === 'credentials_encryption_key') {
        setEncryptionKeyDirty(true);
      }

      return {
        ...prev,
        [field]: value,
      };
    });
  };

  const handleSave = async () => {
    setSaving(true);
    setMessage('');

    try {
      // Validation Logic
      const errors = [];

      // Always Required
      if (!settings.api_key) errors.push("Binance.US API Key is required.");
      if (!settings.api_secret) errors.push("Binance.US API Secret is required.");

      // Conditionally Required if AI is Enabled
      if (settings.ai_enabled) {
        if (!settings.ai_provider) errors.push("AI Provider is required when AI is enabled.");
        if (!settings.ai_model) errors.push("AI Model is required when AI is enabled.");

        switch (settings.ai_provider) {
          case 'openai':
            if (!settings.openai_key) errors.push("OpenAI API Key is required.");
            break;
          case 'zai':
            if (!settings.zai_key) errors.push("Z.AI API Key is required.");
            break;
          case 'perplexity':
            if (!settings.perplexity_key) errors.push("Perplexity API Key is required.");
            break;
          case 'gemini':
            if (!settings.gemini_key) errors.push("Gemini API Key is required.");
            break;
          case 'inception':
            if (!settings.inception_key) errors.push("Inception Labs API Key is required.");
            break;
        }
      }

      // Quartan is optional, but once selected it must have a supported model
      // and a key for cloud providers. Ollama is local and requires no key.
      if (settings.ai_provider_quartan) {
        if (!settings.ai_model_quartan) errors.push("Quartan AI Model is required when a provider is selected.");
        if (settings.ai_provider_quartan !== 'ollama') {
          const quartanKey = settings[`${settings.ai_provider_quartan}_key_quartan`];
          if (!quartanKey) errors.push("Quartan AI API Key is required for the selected provider.");
        }
      }

      const volatilityHours = Number(settings.volatility_hours);
      if (!Number.isInteger(volatilityHours) || volatilityHours < 1) {
        errors.push("Volatility Hours must be a whole number of at least 1.");
      }
      const confirmationMinutes = Number(settings.automated_trigger_confirmation_minutes);
      if (!Number.isInteger(confirmationMinutes) || confirmationMinutes < 1 || confirmationMinutes > 1440) {
        errors.push("Automated Trigger Confirmation Window must be a whole number from 1 through 1440 minutes.");
      }

      [
        ['Portfolio history lookback', settings.sentiment_history_lookback_hours, 72],
        ['Watchlist history lookback', settings.watchlist_sentiment_history_lookback_hours, 72],
        ['Portfolio forecast horizon', settings.sentiment_forecast_horizon_hours, 168],
        ['Watchlist forecast horizon', settings.watchlist_sentiment_forecast_horizon_hours, 168],
      ].forEach(([label, rawValue, maximum]) => {
        const value = Number(rawValue);
        if (!Number.isInteger(value) || value < 1 || value > maximum) {
          errors.push(`${label} must be a whole number from 1 through ${maximum} hours.`);
        }
      });

      SENTIMENT_VARIABLES.forEach(variable => {
        if (variable.kind === 'hold') {
          const { steadyError, wrongError } = holdThresholdErrors(settings);
          if (steadyError) errors.push(`Hold Steady Range: ${steadyError}`);
          if (wrongError) errors.push(`Hold Wrong Threshold: ${wrongError}`);
          return;
        }
        const correctError = sentimentThresholdError(settings[variable.correctKey]);
        const wrongError = sentimentThresholdError(settings[variable.wrongKey], 0);
        if (correctError) errors.push(`${variable.label} Correct: ${correctError}`);
        if (wrongError) errors.push(`${variable.label} Wrong: ${wrongError}`);
      });

      if (errors.length > 0) {
        setMessage(errors.join(" "));
        setMessageType('error');
        setSaving(false);
        return;
      }

      console.log('Saving settings:', settings);

      // Save regular settings
      const payload = { ...settings };
      if (!encryptionKeyDirty || payload.credentials_encryption_key === '********') {
        delete payload.credentials_encryption_key;
      } else if (
        typeof payload.credentials_encryption_key === 'string' &&
        payload.credentials_encryption_key.trim() === ''
      ) {
        delete payload.credentials_encryption_key;
      }
      if (payload.webull_app_key === '********' || !payload.webull_app_key?.trim()) {
        delete payload.webull_app_key;
      }
      if (payload.webull_app_secret === '********' || !payload.webull_app_secret?.trim()) {
        delete payload.webull_app_secret;
      }

      const settingsResponse = await axios.post('/api/settings', payload, {
        withCredentials: true,
        headers: {
          'Content-Type': 'application/json'
        }
      });



      console.log('Save response:', settingsResponse.data);
      setEncryptionStatus({
        configured: Boolean(settingsResponse.data?.credentials_encryption_key_configured),
        persisted: Boolean(settingsResponse.data?.credentials_encryption_key_persisted)
      });
      setSettings((prev) => ({
        ...prev,
        credentials_encryption_key: Boolean(settingsResponse.data?.credentials_encryption_key_configured)
          ? '********'
          : ''
      }));
      setEncryptionKeyDirty(false);
      setMessageType('success');

      // Trigger portfolio sync after saving API keys
      if (settings.api_key && settings.api_secret) {
        console.log('Triggering portfolio sync after settings save...');
        try {
          await axios.post('/api/sync-portfolio', {}, { withCredentials: true });
        } catch (syncErr) {
          console.error('Initial portfolio sync failed:', syncErr);
        }
      }

      // Refresh settings to show any auto-filled fields (like prompts)
      await fetchSettings();

    } catch (error) {
      setMessage(error.response?.data?.message || 'Failed to save settings');
      setMessageType('error');
    } finally {
      setSaving(false);
    }
  };

  const testBinanceConnection = async () => {
    setTestingBinance(true);
    setMessage('');
    setMessageType('');

    try {
      const response = await axios.post('/api/test-binance-connection', {
        api_key: settings.api_key,
        api_secret: settings.api_secret
      }, { withCredentials: true });

      if (response.data.success) {
        setMessage('✅ Binance API connection successful!');
        setMessageType('success');

        // Update the last connected timestamp
        const now = new Date().toISOString();
        setSettings(prev => ({
          ...prev,
          binance_connected_at: now,
          binance_connected: true
        }));
      } else {
        setMessage(`❌ ${response.data.message || 'Failed to connect to Binance API'}`);
        setMessageType('error');
      }
    } catch (error) {
      console.error('Error testing Binance connection:', error);
      const errorMessage = error.response?.data?.message || error.message || 'Failed to connect to Binance API';
      setMessage(`❌ ${errorMessage}`);
      setMessageType('error');
    } finally {
      setTestingBinance(false);
    }
  };

  const testWebullConnection = async () => {
    setTestingWebull(true);
    setMessage('');
    setMessageType('');

    try {
      const response = await axios.post('/api/test-webull-connection', {
        webull_app_key: settings.webull_app_key,
        webull_app_secret: settings.webull_app_secret,
        webull_environment: settings.webull_environment,
      }, { withCredentials: true });

      if (response.data.success) {
        setMessage(`✅ ${response.data.message}`);
        setMessageType('success');
      } else {
        setMessage(`❌ ${response.data.message || 'Webull API connection failed.'}`);
        setMessageType('error');
      }
    } catch (error) {
      console.error('Error testing Webull connection:', error);
      setMessage(`❌ ${error.response?.data?.message || 'Failed to connect to the Webull API.'}`);
      setMessageType('error');
    } finally {
      setTestingWebull(false);
    }
  };

  const startWebullVerification = async () => {
    if (!settings.webull_configured) {
      setMessage('❌ Save your Webull App Key and App Secret before starting verification.');
      setMessageType('error');
      return;
    }

    setTestingWebull(true);
    setMessage('');
    setMessageType('');
    try {
      const response = await axios.post('/api/webull-token/initiate', {}, { withCredentials: true });
      const result = response.data || {};
      setSettings(prev => ({
        ...prev,
        webull_token_status: result.status || prev.webull_token_status,
        webull_token_expires_at: result.expires_at || prev.webull_token_expires_at,
      }));
      if (result.success) {
        await fetchWebullAccounts();
      }
      setMessage(`${result.success ? '✅' : '📱'} ${result.message || 'Webull verification started.'}`);
      setMessageType(result.success ? 'success' : (result.verification_required ? 'success' : 'error'));
    } catch (error) {
      console.error('Error starting Webull verification:', error);
      setMessage(`❌ ${error.response?.data?.message || 'Unable to start Webull verification.'}`);
      setMessageType('error');
    } finally {
      setTestingWebull(false);
    }
  };

  const checkWebullVerification = async () => {
    setTestingWebull(true);
    setMessage('');
    setMessageType('');
    try {
      const response = await axios.post('/api/webull-token/status', {}, { withCredentials: true });
      const result = response.data || {};
      setSettings(prev => ({
        ...prev,
        webull_token_status: result.status || prev.webull_token_status,
        webull_token_expires_at: result.expires_at || prev.webull_token_expires_at,
      }));
      if (result.success) {
        await fetchWebullAccounts();
      }
      setMessage(`${result.success ? '✅' : '📱'} ${result.message || 'Webull verification status checked.'}`);
      setMessageType(result.success ? 'success' : (result.verification_required ? 'success' : 'error'));
    } catch (error) {
      console.error('Error checking Webull verification:', error);
      setMessage(`❌ ${error.response?.data?.message || 'Unable to check Webull verification.'}`);
      setMessageType('error');
    } finally {
      setTestingWebull(false);
    }
  };

  const fetchWebullAccounts = async (forceRefresh = false) => {
    setLoadingWebullAccounts(true);
    setWebullAccountsMessage('');
    try {
      const url = forceRefresh ? '/api/webull/accounts?refresh=true' : '/api/webull/accounts';
      const response = await axios.get(url, { withCredentials: true });
      const result = response.data || {};
      const accList = Array.isArray(result.accounts) ? result.accounts : [];
      setWebullAccounts(accList);
      const activeIds = Array.isArray(result.enabled_account_ids) ? result.enabled_account_ids : accList.map((a) => a.account_id);
      setEnabledAccountIds(activeIds);
      if (forceRefresh) {
        setWebullAccountsMessage(result.message || 'Webull accounts refreshed.');
      }
    } catch (error) {
      console.error('Error discovering Webull accounts:', error);
      setWebullAccounts([]);
      setWebullAccountsMessage(`Unable to discover accounts: ${error.response?.data?.message || 'Please verify the Webull connection.'}`);
    } finally {
      setLoadingWebullAccounts(false);
    }
  };

  const toggleAccountEnabled = async (accountId) => {
    const nextEnabled = enabledAccountIds.includes(accountId)
      ? enabledAccountIds.filter((id) => id !== accountId)
      : [...enabledAccountIds, accountId];
    setEnabledAccountIds(nextEnabled);
    try {
      await axios.post('/api/webull/enabled-accounts', { enabled_account_ids: nextEnabled }, { withCredentials: true });
    } catch (err) {
      console.error('Failed to update enabled Webull accounts:', err);
    }
  };

  const loadWebullPortfolioPreview = async () => {
    setLoadingWebullPreview(true);
    setWebullPreviewMessage('');
    try {
      const response = await axios.get('/api/webull/portfolio-preview', { withCredentials: true });
      const result = response.data || {};
      setWebullPortfolioPreview(Array.isArray(result.accounts) ? result.accounts : []);
      setWebullPreviewMessage(result.message || 'Webull portfolio preview loaded.');
    } catch (error) {
      console.error('Error loading Webull portfolio preview:', error);
      setWebullPortfolioPreview([]);
      setWebullPreviewMessage(`Unable to load preview: ${error.response?.data?.message || 'Please try again.'}`);
    } finally {
      setLoadingWebullPreview(false);
    }
  };

  const syncWebullPortfolio = async () => {
    setSyncingWebullPortfolio(true);
    setWebullImportMessage('');
    try {
      const response = await axios.post('/api/webull/portfolio-sync', {}, { withCredentials: true });
      const result = response.data || {};
      setWebullImportMessage(result.message || 'Webull portfolio imported.');
    } catch (error) {
      console.error('Error importing Webull portfolio:', error);
      setWebullImportMessage(`Unable to import Webull portfolio: ${error.response?.data?.message || 'Please try again.'}`);
    } finally {
      setSyncingWebullPortfolio(false);
    }
  };

  // Handle Sync Coins button click
  const handleSyncCoins = async () => {
    setSyncing(true);
    setMessage('');
    setMessageType('');

    try {
      const response = await axios.post('/api/sync-coins', {}, { withCredentials: true });

      if (response.data.success) {
        setMessage('✅ Coins synced successfully! Portfolio and price history updated.');
        setMessageType('success');
      } else {
        setMessage(`❌ ${response.data.error || 'Failed to sync coins'}`);
        setMessageType('error');
      }
    } catch (error) {
      console.error('Error syncing coins:', error);
      const errorMessage = error.response?.data?.error || error.message || 'Failed to sync coins';
      setMessage(`❌ ${errorMessage}`);
      setMessageType('error');
    } finally {
      setSyncing(false);
    }
  };

  // Handle Save Settings button click
  const saveSettings = async () => {
    await handleSave();
  };

  // Test Primary AI Connection
  const testPrimaryAiConnection = async () => {
    setTestingPrimaryAi(true);
    setPrimaryAiTestResult(null);

    const provider = settings.ai_provider;
    let apiKey = '';

    if (provider === 'openai') apiKey = settings.openai_key;
    else if (provider === 'zai') apiKey = settings.zai_key;
    else if (provider === 'perplexity') apiKey = settings.perplexity_key;
    else if (provider === 'gemini') apiKey = settings.gemini_key;
    else if (provider === 'inception') apiKey = settings.inception_key;

    try {
      const response = await axios.post('/api/test-ai-connection-generic', {
        provider: provider,
        api_key: apiKey,
        model: settings.ai_model,
        tier: 'primary',
        reasoning_level: settings.ai_reasoning_level,
        is_fallback: false
      }, { withCredentials: true });

      setPrimaryAiTestResult({
        success: response.data.success,
        message: response.data.message || (response.data.success ? 'AI connection successful!' : 'Connection failed')
      });
    } catch (error) {
      console.error('Error testing primary AI connection:', error);
      setPrimaryAiTestResult({
        success: false,
        message: error.response?.data?.message || error.message || 'Failed to test AI connection'
      });
    } finally {
      setTestingPrimaryAi(false);
    }
  };

  // Test Brave Search API Key
  const testBraveSearchApiKey = async () => {
    setTestingBraveApi(true);
    setBraveApiTestResult(null);

    try {
      const response = await axios.post('/api/test-brave-search', {
        api_key: settings.brave_search_api_key
      }, { withCredentials: true });

      setBraveApiTestResult({
        success: response.data.success,
        message: response.data.message || (response.data.success ? 'API key is valid!' : 'API key test failed')
      });
    } catch (error) {
      console.error('Error testing Brave Search API:', error);
      setBraveApiTestResult({
        success: false,
        message: error.response?.data?.message || error.message || 'Failed to test API key'
      });
    } finally {
      setTestingBraveApi(false);
    }
  };

  const testBraveSearchApiFallback = async () => {
    setTestingBraveApiFallback(true);
    setBraveApiFallbackTestResult(null);

    try {
      const response = await axios.post('/api/test-brave-search', {
        api_key: settings.brave_search_api_key_fallback
      }, { withCredentials: true });

      setBraveApiFallbackTestResult({
        success: response.data.success,
        message: response.data.message || (response.data.success ? 'Fallback API key is valid!' : 'Fallback API key test failed')
      });
    } catch (error) {
      console.error('Error testing Fallback Brave Search API:', error);
      setBraveApiFallbackTestResult({
        success: false,
        message: error.response?.data?.message || error.message || 'Failed to test fallback API key'
      });
    } finally {
      setTestingBraveApiFallback(false);
    }
  };

  // Test AI Secondary (Fallback) Connection
  const testFallbackConnection = async () => {
    setTestingFallback(true);
    setFallbackTestResult(null);

    const provider = settings.ai_provider_secondary || settings.ai_provider_fallback;
    let apiKey = '';

    // Determine the key based on provider
    if (provider === 'openai') apiKey = settings.openai_key_fallback;
    else if (provider === 'zai') apiKey = settings.zai_key_fallback;
    else if (provider === 'perplexity') apiKey = settings.perplexity_key_fallback;
    else if (provider === 'gemini') apiKey = settings.gemini_key_fallback;
    else if (provider === 'inception') apiKey = settings.inception_key_fallback;

    try {
      const response = await axios.post('/api/test-ai-connection-generic', {
        provider: provider,
        api_key: apiKey,
        model: settings.ai_model_secondary || settings.ai_model_fallback,
        tier: 'secondary',
        reasoning_level: settings.ai_reasoning_level_secondary || settings.ai_reasoning_level_fallback,
        is_fallback: true
      }, { withCredentials: true });

      setFallbackTestResult({
        success: response.data.success,
        message: response.data.message || (response.data.success ? 'Secondary connection successful!' : 'Connection failed')
      });
    } catch (error) {
      console.error('Error testing secondary connection:', error);
      setFallbackTestResult({
        success: false,
        message: error.response?.data?.message || 'Failed to test secondary connection'
      });
    } finally {
      setTestingFallback(false);
    }
  };

  // Test AI Tertiary Connection
  const testTertiaryAiConnection = async () => {
    setTestingTertiaryAi(true);
    setTertiaryAiTestResult(null);

    const provider = settings.ai_provider_tertiary;
    let apiKey = '';

    // Determine the key based on provider
    if (provider === 'openai') apiKey = settings.openai_key_tertiary;
    else if (provider === 'zai') apiKey = settings.zai_key_tertiary;
    else if (provider === 'perplexity') apiKey = settings.perplexity_key_tertiary;
    else if (provider === 'gemini') apiKey = settings.gemini_key_tertiary;
    else if (provider === 'inception') apiKey = settings.inception_key_tertiary;

    try {
      const response = await axios.post('/api/test-ai-connection-generic', {
        provider: provider,
        api_key: apiKey,
        model: settings.ai_model_tertiary,
        tier: 'tertiary',
        reasoning_level: settings.ai_reasoning_level_tertiary
      }, { withCredentials: true });

      setTertiaryAiTestResult({
        success: response.data.success,
        message: response.data.message || (response.data.success ? 'Tertiary connection successful!' : 'Connection failed')
      });
    } catch (error) {
      console.error('Error testing tertiary connection:', error);
      setTertiaryAiTestResult({
        success: false,
        message: error.response?.data?.message || 'Failed to test tertiary connection'
      });
    } finally {
      setTestingTertiaryAi(false);
    }
  };

  // Test the fourth (quartan) AI fallback connection.
  const testQuartanAiConnection = async () => {
    setTestingQuartanAi(true);
    setQuartanAiTestResult(null);

    const provider = settings.ai_provider_quartan;
    let apiKey = '';
    if (provider === 'openai') apiKey = settings.openai_key_quartan;
    else if (provider === 'zai') apiKey = settings.zai_key_quartan;
    else if (provider === 'perplexity') apiKey = settings.perplexity_key_quartan;
    else if (provider === 'gemini') apiKey = settings.gemini_key_quartan;
    else if (provider === 'inception') apiKey = settings.inception_key_quartan;

    try {
      const response = await axios.post('/api/test-ai-connection-generic', {
        provider,
        api_key: apiKey,
        model: settings.ai_model_quartan,
        tier: 'quartan',
        reasoning_level: settings.ai_reasoning_level_quartan,
        is_fallback: true
      }, { withCredentials: true });

      setQuartanAiTestResult({
        success: response.data.success,
        message: response.data.message || (response.data.success ? 'Quartan connection successful!' : 'Connection failed')
      });
    } catch (error) {
      console.error('Error testing quartan connection:', error);
      setQuartanAiTestResult({
        success: false,
        message: error.response?.data?.message || error.message || 'Failed to test quartan connection'
      });
    } finally {
      setTestingQuartanAi(false);
    }
  };

  const handleForceAnalysis = async () => {
    setForcingAnalysis(true);
    setForceAnalysisResult(null);
    try {
      const response = await axios.post('/api/force-sentiment-analysis', {}, { withCredentials: true });
      if (response.data.success) {
        setForceAnalysisResult({ success: true, message: response.data.message });
        setMessage(response.data.message || 'Sentiment analysis started successfully');
        setMessageType('success');
      } else {
        const errMsg = response.data.error || 'Failed to start analysis';
        setForceAnalysisResult({ success: false, message: errMsg });
        setMessage(errMsg);
        setMessageType('error');
      }
    } catch (err) {
      console.error('Force analysis error:', err);
      const errMsg = err.response?.data?.error || 'Failed to connect to server';
      setForceAnalysisResult({ success: false, message: errMsg });
      setMessage(errMsg);
      setMessageType('error');
    } finally {
      setForcingAnalysis(false);
    }
  };

  const fetchLatestVersion = async (wantsBeta) => {
    setIsFetchingVersion(true);
    setAvailableVersion(null);
    setVersionLookupError('');
    try {
      const response = await axios.get('/api/system/latest-release', {
        params: {
          include_beta: wantsBeta,
          cache_bust: Date.now(),
        },
        headers: { 'Cache-Control': 'no-cache' },
        withCredentials: true,
      });
      if (!response.data?.tag_name) {
        throw new Error('GitHub did not return a release tag');
      }
      setAvailableVersion(response.data.tag_name);
    } catch (error) {
      console.error('Latest GitHub release lookup failed:', error);
      setVersionLookupError(error.response?.data?.error || 'Unable to retrieve the latest GitHub release. Please try again.');
    } finally {
      setIsFetchingVersion(false);
    }
  };

  const handleOpenUpgradeModal = () => {
    if (!isSystemAdmin) return;
    setShowUpgradeModal(true);
    fetchLatestVersion(includeBeta);
  };

  useEffect(() => {
    if (showUpgradeModal && isSystemAdmin) {
      fetchLatestVersion(includeBeta);
    }
  }, [includeBeta, showUpgradeModal, isSystemAdmin]);

  const confirmUpgrade = async () => {
    if (!isSystemAdmin) return;
    setShowUpgradeModal(false);
    setUpgrading(true);
    setMessage('Upgrade initiated. Please wait, the page will automatically refresh when complete...');
    setMessageType('success');
    try {
      const response = await axios.post('/api/system/upgrade', {
        include_beta: includeBeta,
      }, { withCredentials: true });
      if (response.data.success) {
        let serverWentDown = false;
        const pollInterval = setInterval(async () => {
          try {
            await axios.get('/login');
            if (serverWentDown) {
              clearInterval(pollInterval);
              window.location.reload();
            }
          } catch (e) {
            serverWentDown = true;
          }
        }, 2000);
      } else {
        setMessage('❌ ' + (response.data.error || 'Upgrade failed'));
        setMessageType('error');
        setUpgrading(false);
      }
    } catch (err) {
      console.error('Upgrade error:', err);
      setMessage('❌ ' + (err.response?.data?.error || 'Failed to trigger upgrade'));
      setMessageType('error');
      setUpgrading(false);
    }
  };

  // 2FA Functions
  const fetchTradingSettings = async () => {
    try {
      const response = await axios.get('/api/trading/settings', { withCredentials: true });
      if (response.data && response.data.settings) {
        setTwoFactorEnabled(response.data.settings.totp_enabled || false);
      }
    } catch (error) {
      console.error('Error fetching trading settings:', error);
    }
  };

  useEffect(() => {
    fetchTradingSettings();
  }, []);

  const handleEnable2FA = async () => {
    setTwoFactorLoading(true);
    setTwoFactorMessage('');
    try {
      const response = await axios.post('/api/trading/2fa/setup', {}, { withCredentials: true });
      if (response.data.success) {
        setQRCodeData(response.data);
        setShowQRCode(true);
        setTwoFactorMessage('Scan the QR code with your authenticator app (Bitwarden, Google Authenticator, etc.)');
      } else {
        setTwoFactorMessage(response.data.error || 'Failed to generate 2FA setup');
      }
    } catch (error) {
      console.error('Error setting up 2FA:', error);
      setTwoFactorMessage(error.response?.data?.error || 'Failed to generate 2FA setup');
    } finally {
      setTwoFactorLoading(false);
    }
  };

  const handleVerify2FA = async () => {
    if (!verificationCode || verificationCode.length !== 6) {
      setTwoFactorMessage('Please enter a 6-digit code');
      return;
    }

    setTwoFactorLoading(true);
    setTwoFactorMessage('');
    try {
      const response = await axios.post('/api/trading/2fa/verify-setup', {
        code: verificationCode
      }, { withCredentials: true });

      if (response.data.success) {
        setTwoFactorEnabled(true);
        setShowQRCode(false);
        setVerificationCode('');
        setQRCodeData(null);
        setTwoFactorMessage('✅ 2FA enabled successfully! You will now be asked for a code when placing orders.');
        setTimeout(() => setTwoFactorMessage(''), 5000);
        // Refresh settings to ensure database value is loaded
        await fetchTradingSettings();
      } else {
        setTwoFactorMessage('❌ ' + (response.data.error || 'Invalid verification code'));
      }
    } catch (error) {
      console.error('Error verifying 2FA:', error);
      setTwoFactorMessage('❌ ' + (error.response?.data?.error || 'Failed to verify code'));
    } finally {
      setTwoFactorLoading(false);
    }
  };

  const handleDisable2FA = async () => {
    if (!disableCode || disableCode.length !== 6) {
      setTwoFactorMessage('Please enter a 6-digit code to disable 2FA');
      return;
    }

    setTwoFactorLoading(true);
    setTwoFactorMessage('');
    try {
      const response = await axios.post('/api/trading/2fa/disable', {
        code: disableCode
      }, { withCredentials: true });

      if (response.data.success) {
        setTwoFactorEnabled(false);
        setDisableCode('');
        setTwoFactorMessage('✅ 2FA disabled successfully');
        setTimeout(() => setTwoFactorMessage(''), 5000);
        // Refresh settings to ensure database value is loaded
        await fetchTradingSettings();
      } else {
        setTwoFactorMessage('❌ ' + (response.data.error || 'Invalid code'));
      }
    } catch (error) {
      console.error('Error disabling 2FA:', error);
      setTwoFactorMessage('❌ ' + (error.response?.data?.error || 'Failed to disable 2FA'));
    } finally {
      setTwoFactorLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="settings-loading">
        Loading settings...
      </div>
    );
  }

  // Delete Account Handlers
  const handleExportTaxData = async () => {
    try {
      const response = await axios.get('/api/tax-report/export', {
        responseType: 'blob',
        withCredentials: true
      });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `crypto_tax_report_${new Date().toISOString().split('T')[0]}.csv`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to export tax data:', err);
      alert('Failed to export tax data. Please try again.');
    }
  };

  const handleDeleteAccount = async () => {
    setDeleteLoading(true);
    setDeleteError('');
    try {
      await axios.delete('/api/account/delete', { withCredentials: true });
      // Logout and redirect
      window.location.href = '/login?deleted=true';
    } catch (err) {
      console.error('Failed to delete account:', err);
      setDeleteError(err.response?.data?.error || 'Failed to delete account. Please try again.');
      setDeleteLoading(false);
    }
  };

  return (
    <div className="settings-page-container">
      {showUpgradeModal && isSystemAdmin && createPortal(
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.7)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 999999
        }}>
          <div style={{
            backgroundColor: isLightMode ? '#fff' : '#1a1a2e',
            borderRadius: '12px',
            maxWidth: '500px',
            width: '90%',
            padding: '0',
            border: `1px solid ${isLightMode ? '#e2e8f0' : '#4fd1c5'}`,
            boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)'
          }}>
            {/* Modal Header */}
            <div style={{
              padding: '20px 24px',
              borderBottom: `1px solid ${isLightMode ? '#e2e8f0' : '#2d3748'}`,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}>
              <h2 style={{ margin: 0, color: isLightMode ? '#2d3748' : '#fff', fontSize: '1.25rem', fontWeight: 'bold' }}>
                Confirm Application Upgrade
              </h2>
              <button 
                onClick={() => setShowUpgradeModal(false)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: isLightMode ? '#718096' : '#a0aec0',
                  fontSize: '1.5rem',
                  cursor: 'pointer',
                  lineHeight: 1
                }}
              >
                &times;
              </button>
            </div>

            {/* Modal Body */}
            <div style={{ padding: '24px' }}>
              {isFetchingVersion ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', color: isLightMode ? '#4a5568' : '#e2e8f0' }}>
                  <div className="spinner-border spinner-border-sm" role="status" style={{ width: '1.5rem', height: '1.5rem', border: '0.2em solid currentColor', borderRightColor: 'transparent', borderRadius: '50%', animation: 'spinner-border .75s linear infinite' }}></div>
                  <style>
                    {`@keyframes spinner-border { to { transform: rotate(360deg); } }`}
                  </style>
                  <span>Checking for latest version from GitHub...</span>
                </div>
              ) : versionLookupError ? (
                <p style={{ margin: 0, color: '#f56565', fontSize: '1rem', lineHeight: '1.6' }}>
                  {versionLookupError}
                </p>
              ) : (
                <p style={{ margin: 0, color: isLightMode ? '#4a5568' : '#e2e8f0', fontSize: '1rem', lineHeight: '1.6' }}>
                  Are you sure you want to pull the latest version {availableVersion ? (
                    <strong style={{ color: '#ecc94b' }}>({availableVersion})</strong>
                  ) : ''} from GitHub and restart the app?
                </p>
              )}
            </div>

            {/* Modal Footer */}
            <div style={{
              padding: '16px 24px',
              borderTop: `1px solid ${isLightMode ? '#e2e8f0' : '#2d3748'}`,
              display: 'flex',
              justifyContent: 'flex-end',
              gap: '12px'
            }}>
              <button
                onClick={() => setShowUpgradeModal(false)}
                style={{
                  padding: '10px 20px',
                  borderRadius: '6px',
                  border: `1px solid ${isLightMode ? '#e2e8f0' : '#4a5568'}`,
                  background: 'transparent',
                  color: isLightMode ? '#4a5568' : '#e2e8f0',
                  fontSize: '14px',
                  fontWeight: '600',
                  cursor: 'pointer'
                }}
              >
                Cancel
              </button>
              <button
                onClick={confirmUpgrade}
                disabled={isFetchingVersion || !availableVersion}
                style={{
                  padding: '10px 20px',
                  borderRadius: '6px',
                  border: 'none',
                  background: isFetchingVersion || !availableVersion ? '#4a5568' : '#ecc94b',
                  color: '#000',
                  fontSize: '14px',
                  fontWeight: 'bold',
                  cursor: isFetchingVersion || !availableVersion ? 'not-allowed' : 'pointer',
                  boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)'
                }}
              >
                Confirm Upgrade
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
      {/* Header with Action Buttons */}
      <div className="settings-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
        <h1 style={{ margin: 0 }}>Settings & API Configuration</h1>

        {/* Top Right Action Buttons */}
        <div className="settings-action-buttons" style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '12px', flexWrap: 'wrap', marginLeft: 'auto' }}>
          <button
            onClick={handleForceAnalysis}
            disabled={forcingAnalysis}
            style={{
              padding: '12px 24px',
              borderRadius: 6,
              border: '1px solid #4fd1c5',
              background: 'transparent',
              color: '#4fd1c5',
              fontSize: '16px',
              cursor: forcingAnalysis ? 'not-allowed' : 'pointer',
              transition: 'all 0.2s'
            }}
          >
            {forcingAnalysis ? 'Analyzing...' : 'Run Sentiment Analysis Now'}
          </button>

          <button
            onClick={handleSyncCoins}
            disabled={syncing}
            style={{
              padding: '12px 24px',
              borderRadius: 6,
              border: '1px solid #4fd1c5',
              background: 'transparent',
              color: '#4fd1c5',
              fontSize: '16px',
              cursor: syncing ? 'not-allowed' : 'pointer',
              transition: 'all 0.2s'
            }}
          >
            {syncing ? 'Syncing...' : 'Sync Coins'}
          </button>

          <button
            onClick={saveSettings}
            disabled={saving}
            style={{
              padding: '12px 24px',
              borderRadius: 6,
              border: 'none',
              background: saving ? '#666' : '#4fd1c5',
              color: '#fff',
              fontSize: '16px',
              fontWeight: 'bold',
              cursor: saving ? 'not-allowed' : 'pointer',
              transition: 'background 0.2s'
            }}
          >
            {saving ? 'Saving...' : 'Save Settings'}
          </button>

          <button
            onClick={() => window.open('/reset-password', '_blank')}
            style={{
              padding: '12px 24px',
              borderRadius: 6,
              border: '1px solid #f56565',
              background: 'transparent',
              color: '#f56565',
              fontSize: '16px',
              cursor: 'pointer',
              transition: 'all 0.2s'
            }}
          >
            Reset Password
          </button>

          {isSystemAdmin && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
              <button
                onClick={handleOpenUpgradeModal}
                disabled={upgrading}
                style={{
                  padding: '12px 24px',
                  borderRadius: 6,
                  border: '1px solid #ecc94b',
                  background: 'transparent',
                  color: '#ecc94b',
                  fontSize: '16px',
                  cursor: upgrading ? 'not-allowed' : 'pointer',
                  transition: 'all 0.2s'
                }}
              >
                {upgrading ? 'Upgrading...' : 'Upgrade App'}
              </button>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', color: isLightMode ? '#2d3748' : '#e2e8f0', userSelect: 'none', margin: 0 }}>
                <input
                  type="checkbox"
                  checked={includeBeta}
                  onChange={(e) => setIncludeBeta(e.target.checked)}
                  style={{ position: 'absolute', opacity: 0, pointerEvents: 'none' }}
                />
                {includeBeta ? <FaToggleOn size={30} color="#4fd1c5" /> : <FaToggleOff size={30} color="#6c757d" />}
                Include Beta Versions
              </label>
            </div>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <label
              style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', color: isLightMode ? '#2d3748' : '#e2e8f0', userSelect: 'none', margin: 0 }}
              title="Enable or disable all AI integrations"
            >
              <input
                type="checkbox"
                checked={!!settings.ai_enabled}
                onChange={(e) => handleInputChange('ai_enabled', e.target.checked)}
                style={{ position: 'absolute', opacity: 0, pointerEvents: 'none' }}
              />
              {settings.ai_enabled ? <FaToggleOn size={30} color="#4fd1c5" /> : <FaToggleOff size={30} color="#6c757d" />}
              AI Integrations Enabled
            </label>
          </div>
        </div>
        <div style={{ marginTop: '15px', color: '#a0aec0', fontSize: '14px', textAlign: 'center' }}>

        </div>
      </div>

      {/* Message Display */}
      {message && (
        <div className={`settings-message ${messageType}`}>
          {message}
        </div>
      )}

      {/* Settings Navigation Tabs */}
      <div className="settings-tabs-nav">
        {visibleSettingsTabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`settings-tab-btn ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => handleTabChange(tab.id)}
          >
            <span>{tab.icon}</span>
            <span>{tab.label}</span>
          </button>
        ))}
      </div>

      {activeTab === 'apis' && (
        <div className="settings-grid">
        {/* Row 1, Left: Binance.US API Key and Secret (Unified) */}
        <div className="settings-page-section">
          <h3>Binance.US API Key and Secret</h3>
          <p>
            Enter your Binance.US API Key and Secret. This single key is used for <strong>Portfolio Sync, Price Tracking, and Trading</strong>. Ensure the key has <strong>SPOT Trading</strong> permissions enabled.
          </p>

          <div className="settings-form-group">
            <label>
              API Key
            </label>
            <input
              type="password"
              value={settings.api_key || ''}
              onChange={(e) => handleInputChange('api_key', e.target.value)}
              placeholder="Enter Binance.US API Key"
            />
          </div>

          <div className="settings-form-group">
            <label>
              API Secret
            </label>
            <input
              type="password"
              value={settings.api_secret || ''}
              onChange={(e) => handleInputChange('api_secret', e.target.value)}
              placeholder="Enter Binance.US API Secret"
            />
            <p className="settings-form-help">
              Requires SPOT trading permissions for full functionality.
            </p>

            {/* Unified Test Connection button */}
            <button
              onClick={testBinanceConnection}
              disabled={testingBinance}
              style={{
                marginTop: '10px',
                padding: '8px 16px',
                backgroundColor: testingBinance ? '#6c757d' : '#f0b90b',
                color: 'black',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '14px',
                width: '100%',
                fontWeight: 'bold',
                transition: 'all 0.2s'
              }}
            >
              {testingBinance ? 'Testing Connection...' : 'Test API Connection'}
            </button>
          </div>
        </div>

        {/* Connection verification is read-only; imported selected accounts may then be used in the scoped Webull workspace. */}
        <div className="settings-page-section">
          <h3>Webull OpenAPI Connection</h3>
          <p>
            Connect your personal Webull Trading API application. Verification only confirms account access; choose and import account snapshots before using their scoped Webull trading workspace.
          </p>

          <div className="settings-form-group">
            <label>Environment</label>
            <select
              value={settings.webull_environment || 'production'}
              onChange={(e) => handleInputChange('webull_environment', e.target.value)}
            >
              <option value="production">Production — my live Webull account</option>
              <option value="sandbox">Sandbox — Webull test account</option>
            </select>
            <p className="settings-form-help">
              Choose the environment that issued your App Key and App Secret. Production credentials must not be tested against Sandbox.
            </p>
          </div>

          <div className="settings-form-group">
            <label>App Key</label>
            <input
              type="password"
              value={settings.webull_app_key || ''}
              onChange={(e) => handleInputChange('webull_app_key', e.target.value)}
              placeholder="Enter Webull App Key"
              autoComplete="off"
            />
          </div>

          <div className="settings-form-group">
            <label>App Secret</label>
            <input
              type="password"
              value={settings.webull_app_secret || ''}
              onChange={(e) => handleInputChange('webull_app_secret', e.target.value)}
              placeholder="Enter Webull App Secret"
              autoComplete="new-password"
            />
            <p className="settings-form-help">
              Both values are encrypted at rest and are never returned to the browser after saving. Save Settings first, then start the Webull verification flow.
            </p>
            {settings.webull_token_status === 'PENDING' && (
              <div className="settings-form-help" style={{ marginTop: '10px', padding: '12px', background: 'rgba(79, 209, 197, 0.10)', borderLeft: '3px solid #4fd1c5', borderRadius: '4px' }}>
                <strong>Verification awaiting approval.</strong><br />
                In Webull, go to <strong>Menu → Messages → OpenAPI Notifications</strong>, open the newest message, select <strong>Check Now</strong>, and confirm the SMS code. Then click <strong>Check Webull Verification</strong> below. Webull expires an unverified request after five minutes.
              </div>
            )}
            {settings.webull_token_status === 'NORMAL' && (
              <p className="settings-form-help" style={{ marginTop: '10px', color: '#38d39f' }}>
                ✓ Webull verification is active for {settings.webull_environment === 'production' ? 'Production' : 'Sandbox'}.
              </p>
            )}
            <button
              onClick={startWebullVerification}
              disabled={testingWebull || !settings.webull_configured}
              style={{
                marginTop: '10px',
                padding: '8px 16px',
                backgroundColor: testingWebull ? '#6c757d' : '#4fd1c5',
                color: '#0f172a',
                border: 'none',
                borderRadius: '4px',
                cursor: testingWebull ? 'not-allowed' : 'pointer',
                fontSize: '14px',
                width: '100%',
                fontWeight: 'bold',
                transition: 'all 0.2s'
              }}
            >
              {testingWebull
                ? 'Contacting Webull...'
                : settings.webull_token_status === 'NORMAL'
                  ? 'Test API Connection'
                  : 'Connect and Verify in Webull'}
            </button>
            {settings.webull_token_status === 'PENDING' && (
              <button
                onClick={checkWebullVerification}
                disabled={testingWebull}
                style={{
                  marginTop: '10px',
                  padding: '8px 16px',
                  backgroundColor: testingWebull ? '#6c757d' : '#2563eb',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: testingWebull ? 'not-allowed' : 'pointer',
                  fontSize: '14px',
                  width: '100%',
                  fontWeight: 'bold',
                  transition: 'all 0.2s'
                }}
              >
                {testingWebull ? 'Checking Verification...' : 'Check Webull Verification'}
              </button>
            )}
            {settings.webull_token_status === 'NORMAL' && (
              <div style={{ marginTop: '16px', padding: '14px', border: '1px solid rgba(79, 209, 197, 0.35)', borderRadius: '6px', background: 'rgba(79, 209, 197, 0.05)' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
                  <div>
                    <strong>Connected Webull Accounts</strong>
                    <p className="settings-form-help" style={{ margin: '4px 0 0' }}>
                      Discovery is read-only. Balances, positions, orders, and portfolio data have not been imported.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => fetchWebullAccounts(true)}
                    disabled={loadingWebullAccounts}
                    style={{ padding: '7px 12px', backgroundColor: loadingWebullAccounts ? '#6c757d' : '#2563eb', color: '#fff', border: 'none', borderRadius: '4px', cursor: loadingWebullAccounts ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 'bold' }}
                  >
                    {loadingWebullAccounts ? 'Discovering...' : 'Refresh Accounts'}
                  </button>
                </div>
                {webullAccountsMessage && (
                  <p className="settings-form-help" style={{ margin: '12px 0 0' }}>{webullAccountsMessage}</p>
                )}
                {webullAccounts.length > 0 && (
                  <div className="webull-connected-account-list">
                    <p style={{ margin: '0 0 6px', fontSize: '13px', color: '#94a3b8' }}>
                      Select which accounts to display in Webull Trading navigation:
                    </p>
                    {webullAccounts.map((account, index) => {
                      const isChecked = enabledAccountIds.includes(account.account_id);
                      return (
                        <div
                          key={`${account.account_id || account.account_id_masked || index}`}
                          className={`webull-connected-account ${isChecked ? 'is-enabled' : 'is-disabled'}`}
                        >
                          <label className="webull-connected-account-label">
                            <input
                              className="webull-connected-account-checkbox"
                              type="checkbox"
                              checked={isChecked}
                              onChange={() => toggleAccountEnabled(account.account_id)}
                            />
                            <strong className="webull-connected-account-name">
                              {account.account_label || account.account_name || account.account_type || 'Webull Account'}
                            </strong>
                            <span className="webull-connected-account-type">
                              {account.account_type || 'CASH'}
                            </span>
                          </label>
                          <span className="webull-connected-account-mask">
                            {account.account_id_masked}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
                <div style={{ marginTop: '14px', paddingTop: '12px', borderTop: '1px solid rgba(79, 209, 197, 0.20)' }}>
                  <strong>Portfolio Preview</strong>
                  <p className="settings-form-help" style={{ margin: '4px 0 10px' }}>
                    Your enabled Webull accounts are included. This fetches a live, read-only preview of balances and open positions; it does not merge or save them into the dashboard yet.
                  </p>
                  <button
                    type="button"
                    onClick={loadWebullPortfolioPreview}
                    disabled={loadingWebullPreview}
                    style={{ padding: '7px 12px', backgroundColor: loadingWebullPreview ? '#6c757d' : '#0f766e', color: '#fff', border: 'none', borderRadius: '4px', cursor: loadingWebullPreview ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 'bold' }}
                  >
                    {loadingWebullPreview ? 'Loading Preview...' : 'Load Read-Only Portfolio Preview'}
                  </button>
                  <button
                    type="button"
                    onClick={syncWebullPortfolio}
                    disabled={syncingWebullPortfolio}
                    style={{ marginLeft: '8px', padding: '7px 12px', backgroundColor: syncingWebullPortfolio ? '#6c757d' : '#2563eb', color: '#fff', border: 'none', borderRadius: '4px', cursor: syncingWebullPortfolio ? 'not-allowed' : 'pointer', fontSize: '13px', fontWeight: 'bold' }}
                  >
                    {syncingWebullPortfolio ? 'Importing...' : 'Import into Unified Portfolio'}
                  </button>
                  {webullPreviewMessage && <p className="settings-form-help" style={{ margin: '10px 0 0' }}>{webullPreviewMessage}</p>}
                  {webullImportMessage && <p className="settings-form-help" style={{ margin: '10px 0 0' }}>{webullImportMessage}</p>}
                  {webullPortfolioPreview.map((account, index) => (
                    <div key={`${account.account_type}-${account.account_id_masked}-${index}`} style={{ marginTop: '10px', padding: '10px', borderRadius: '4px', background: 'rgba(15, 23, 42, 0.45)' }}>
                      <strong>{account.account_type || 'Webull Account'} · {account.account_id_masked}</strong>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', marginTop: '8px', fontSize: '13px' }}>
                        <span>Net value: <strong>{account.balance?.total_net_liquidation_value ?? '—'} {account.balance?.total_asset_currency || ''}</strong></span>
                        <span>Cash: <strong>{account.balance?.total_cash_balance ?? '—'}</strong></span>
                        <span>Market value: <strong>{account.balance?.total_market_value ?? '—'}</strong></span>
                        <span>Open P&amp;L: <strong>{account.balance?.total_unrealized_profit_loss ?? '—'}</strong></span>
                      </div>
                      {account.positions?.length > 0 ? (
                        <div style={{ marginTop: '9px', display: 'grid', gap: '5px', fontSize: '13px' }}>
                          {account.positions.map((position, positionIndex) => (
                            <div key={`${position.symbol}-${position.instrument_type}-${positionIndex}`} style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', flexWrap: 'wrap' }}>
                              <span><strong>{position.symbol || 'Unknown'}</strong> · {position.instrument_type || 'Position'} · Qty {position.quantity ?? '—'}</span>
                              <span>Last {position.last_price ?? '—'} · Open P&amp;L {position.unrealized_profit_loss ?? '—'}</span>
                            </div>
                          ))}
                        </div>
                      ) : <p className="settings-form-help" style={{ margin: '9px 0 0' }}>No open positions returned for this account.</p>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Credential Encryption - ONLY for Admin (id=1) */}
          {user && user.id === 1 && (
            <div className="settings-page-section" style={{ gridColumn: '1 / -1' }}>
              <h3>Credential Encryption</h3>
              <p>
                Store a Fernet key to encrypt Binance, Webull, AI, and notification credentials at rest. Provide either a 32-character raw secret or a URL-safe base64 string.
              </p>
              <div className="settings-form-group">
                <label>Encryption Key</label>
                <input
                  type="password"
                  value={settings.credentials_encryption_key || ''}
                  onChange={(e) => handleInputChange('credentials_encryption_key', e.target.value)}
                  placeholder="Enter Fernet key and click Save Settings"
                />
                <p className="settings-form-help">
                  {encryptionStatus.configured ? (
                    encryptionStatus.persisted
                      ? 'Encryption is active and stored securely in the database.'
                      : 'Encryption is active via environment configuration.'
                  ) : (
                    'Encryption is not configured yet. Add a key to enable it.'
                  )}
                </p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Security & 2FA Tab */}
      {activeTab === 'security-2fa' && (
        <div className="settings-page-section">
          <h3>🔐 Two-Factor Authentication (2FA)</h3>

          <div className="settings-form-help" style={{ marginBottom: '20px', padding: '12px', background: 'rgba(102, 126, 234, 0.1)', borderLeft: '3px solid #667eea', borderRadius: '4px', fontSize: '13px' }}>
            <strong>What is App 2FA?</strong><br />
            This is <strong>separate</strong> from your Binance.US 2FA. It adds an extra security layer to this app, requiring a code from your authenticator app (Bitwarden, Google Authenticator, etc.) every time you place an order.
            <br /><br />
            <strong>Why enable it?</strong><br />
            Even with Binance 2FA, anyone with access to this app could place orders. App 2FA prevents unauthorized trading.
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px', padding: '16px', background: twoFactorEnabled ? 'rgba(76, 175, 80, 0.1)' : 'rgba(244, 67, 54, 0.1)', borderRadius: '8px' }}>
            <div style={{ fontSize: '48px' }}>
              {twoFactorEnabled ? '🔒' : '🔓'}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: '18px', fontWeight: 'bold', marginBottom: '4px' }}>
                Status: {twoFactorEnabled ? 'Enabled' : 'Disabled'}
              </div>
              <div style={{ fontSize: '14px', color: '#999' }}>
                {twoFactorEnabled
                  ? 'Your orders are protected with 2FA verification'
                  : 'Orders can be placed without additional verification'}
              </div>
            </div>
          </div>

          {twoFactorMessage && (
            <div style={{
              padding: '12px',
              marginBottom: '16px',
              borderRadius: '6px',
              background: twoFactorMessage.includes('✅') ? 'rgba(76, 175, 80, 0.2)' : 'rgba(244, 67, 54, 0.2)',
              color: twoFactorMessage.includes('✅') ? '#4CAF50' : '#f44336',
              border: `1px solid ${twoFactorMessage.includes('✅') ? '#4CAF50' : '#f44336'}`,
              fontSize: '13px'
            }}>
              {twoFactorMessage}
            </div>
          )}

          {!twoFactorEnabled && !showQRCode && (
            <button
              onClick={handleEnable2FA}
              disabled={twoFactorLoading}
              className="settings-button"
              style={{ marginBottom: '16px' }}
            >
              {twoFactorLoading ? '⏳ Generating...' : '🔐 Enable 2FA'}
            </button>
          )}

          {showQRCode && qrCodeData && (
            <div style={{ padding: '20px', background: 'rgba(255,255,255,0.05)', borderRadius: '8px', marginBottom: '20px' }}>
              <h4 style={{ marginTop: 0, marginBottom: '16px', fontSize: '16px' }}>Setup Your Authenticator</h4>

              <div style={{ marginBottom: '20px' }}>
                <p style={{ marginBottom: '12px', color: '#ccc', fontSize: '13px' }}>
                  <strong>Step 1:</strong> Scan this QR code with your authenticator app:
                </p>
                <div style={{ textAlign: 'center', padding: '20px', background: 'white', borderRadius: '8px', marginBottom: '16px' }}>
                  <img src={qrCodeData.qr_code} alt="2FA QR Code" style={{ maxWidth: '200px', width: '100%' }} />
                </div>
              </div>

              <div style={{ marginBottom: '20px' }}>
                <p style={{ marginBottom: '8px', color: '#ccc', fontSize: '13px' }}>
                  <strong>Step 2:</strong> Or manually enter this secret key:
                </p>
                <div style={{
                  padding: '12px',
                  background: 'rgba(0,0,0,0.3)',
                  borderRadius: '6px',
                  fontFamily: 'monospace',
                  fontSize: '14px',
                  wordBreak: 'break-all',
                  userSelect: 'all',
                  cursor: 'pointer'
                }}
                  onClick={() => {
                    navigator.clipboard.writeText(qrCodeData.secret);
                    setTwoFactorMessage('✅ Secret copied to clipboard!');
                    setTimeout(() => setTwoFactorMessage(''), 3000);
                  }}
                >
                  {qrCodeData.secret}
                  <span style={{ fontSize: '11px', color: '#999', display: 'block', marginTop: '4px' }}>
                    (Click to copy)
                  </span>
                </div>
              </div>

              <div style={{ marginBottom: '20px' }}>
                <p style={{ marginBottom: '8px', color: '#ccc', fontSize: '13px' }}>
                  <strong>Step 3:</strong> Enter the 6-digit code from your authenticator:
                </p>
                <input
                  type="text"
                  value={verificationCode}
                  onChange={(e) => {
                    const value = e.target.value.replace(/\D/g, '').slice(0, 6);
                    setVerificationCode(value);
                  }}
                  placeholder="000000"
                  maxLength="6"
                  style={{
                    width: '100%',
                    padding: '12px',
                    fontSize: '20px',
                    textAlign: 'center',
                    letterSpacing: '6px',
                    fontFamily: 'monospace',
                    borderRadius: '6px',
                    background: '#1a1f23',
                    border: '2px solid #667eea',
                    color: '#fff',
                    boxSizing: 'border-box'
                  }}
                />
              </div>

              <div style={{ display: 'flex', gap: '12px', flexDirection: 'column' }}>
                <button
                  onClick={handleVerify2FA}
                  disabled={twoFactorLoading || verificationCode.length !== 6}
                  className="settings-button"
                  style={{ width: '100%' }}
                >
                  {twoFactorLoading ? '⏳ Verifying...' : '✅ Verify & Enable 2FA'}
                </button>
                <button
                  onClick={() => {
                    setShowQRCode(false);
                    setQRCodeData(null);
                    setVerificationCode('');
                  }}
                  className="settings-button"
                  style={{ background: '#666', width: '100%' }}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {twoFactorEnabled && (
            <div style={{ padding: '20px', background: 'rgba(244, 67, 54, 0.1)', borderRadius: '8px', border: '1px solid rgba(244, 67, 54, 0.3)' }}>
              <h4 style={{ marginTop: 0, marginBottom: '16px', color: '#f44336', fontSize: '16px' }}>Disable 2FA</h4>

              <p style={{ marginBottom: '12px', color: '#ccc', fontSize: '13px' }}>
                Enter your current 6-digit code to disable 2FA:
              </p>

              <input
                type="text"
                value={disableCode}
                onChange={(e) => {
                  const value = e.target.value.replace(/\D/g, '').slice(0, 6);
                  setDisableCode(value);
                }}
                placeholder="000000"
                maxLength="6"
                style={{
                  width: '100%',
                  padding: '12px',
                  fontSize: '20px',
                  textAlign: 'center',
                  letterSpacing: '6px',
                  fontFamily: 'monospace',
                  borderRadius: '6px',
                  background: '#1a1f23',
                  border: '2px solid #f44336',
                  color: '#fff',
                  marginBottom: '12px',
                  boxSizing: 'border-box'
                }}
              />

              <button
                onClick={handleDisable2FA}
                disabled={twoFactorLoading || disableCode.length !== 6}
                className="settings-button"
                style={{ background: '#f44336', width: '100%' }}
              >
                {twoFactorLoading ? '⏳ Disabling...' : '🔓 Disable 2FA'}
              </button>
            </div>
          )}
        </div>
      )}

      {/* AI Providers & Models Tab */}
      {activeTab === 'ai-providers' && (
        <div className="settings-grid">
          {/* Row 2, Left: Primary AI Integration */}
          <div className="settings-page-section">
            <h3>Primary AI Integration</h3>

          <div className="settings-form-group">
            <label>AI Provider</label>
            <select
              value={settings.ai_provider || 'openai'}
              onChange={(e) => handleInputChange('ai_provider', e.target.value)}
            >
              <option value="openai">OpenAI</option>
              <option value="zai">Z.AI</option>
              <option value="perplexity">Perplexity</option>
              <option value="gemini">Gemini</option>
              <option value="inception">Inception Labs</option>
              {isEventStrategyAdmin && <option value="ollama">Ollama (local)</option>}
            </select>
            <div className="settings-form-help">
              Choose your primary AI provider for analysis and recommendations
            </div>
          </div>

          <div className="settings-form-group">
            <label>AI Model</label>
            <select
              value={settings.ai_model || ''}
              onChange={(e) => handleInputChange('ai_model', e.target.value)}
            >
              {(modelOptions[settings.ai_provider] || []).map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
            <div className="settings-form-help">
              Select an AI model supported by the chosen provider
            </div>
          </div>

          {/* Reasoning Effort */}
          {['gemini', 'openai'].includes(settings.ai_provider) && (
            <div className="settings-form-group">
              <label>Reasoning</label>
              <select
                value={settings.ai_reasoning_level || 'medium'}
                onChange={(e) => handleInputChange('ai_reasoning_level', e.target.value)}
              >
                <option value="light">Light</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="extra high">Extra High</option>
              </select>
              <div className="settings-form-help">
                Configure reasoning effort for supported models
              </div>
            </div>
          )}

          {/* OpenAI Configuration - Only show when OpenAI is selected */}
          {settings.ai_provider === 'openai' && (
            <div className="settings-form-group">
              <label>OpenAI API Key</label>
              <input
                type="password"
                value={settings.openai_key || ''}
                onChange={(e) => handleInputChange('openai_key', e.target.value)}
                placeholder="Enter OpenAI API Key"
              />
              <div className="settings-form-help">
                Used for AI-powered trading analysis and recommendations
              </div>
            </div>
          )}

          {/* Z.AI Configuration - Only show when Z.AI is selected */}
          {settings.ai_provider === 'zai' && (
            <div className="settings-form-group">
              <label>Z.AI API Key</label>
              <input
                type="password"
                value={settings.zai_key || ''}
                onChange={(e) => handleInputChange('zai_key', e.target.value)}
                placeholder="Enter Z.AI API Key"
              />
              <div className="settings-form-help">
                Used for AI-powered trading analysis and recommendations
              </div>
            </div>
          )}

          {/* Perplexity Configuration - Only show when Perplexity is selected */}
          {settings.ai_provider === 'perplexity' && (
            <div className="settings-form-group">
              <label>Perplexity API Key</label>
              <input
                type="password"
                value={settings.perplexity_key || ''}
                onChange={(e) => handleInputChange('perplexity_key', e.target.value)}
                placeholder="Enter Perplexity API Key"
              />
              <div className="settings-form-help">
                Used for AI-powered trading analysis and recommendations
              </div>
            </div>
          )}

          {/* Gemini Configuration - Only show when Gemini is selected */}
          {settings.ai_provider === 'gemini' && (
            <div className="settings-form-group">
              <label>Gemini API Key</label>
              <input
                type="password"
                value={settings.gemini_key || ''}
                onChange={(e) => handleInputChange('gemini_key', e.target.value)}
                placeholder="Enter Gemini API Key"
              />
              <div className="settings-form-help">
                Used for AI-powered trading analysis and recommendations
              </div>
            </div>
          )}

          {/* Inception Labs Configuration - Only show when Inception is selected */}
          {settings.ai_provider === 'inception' && (
            <div className="settings-form-group">
              <label>Inception Labs API Key</label>
              <input
                type="password"
                value={settings.inception_key || ''}
                onChange={(e) => handleInputChange('inception_key', e.target.value)}
                placeholder="Enter Inception Labs API Key"
              />
              <div className="settings-form-help">
                Used for AI-powered trading analysis and recommendations
              </div>
            </div>
          )}

          {settings.ai_provider === 'ollama' && isEventStrategyAdmin && (
            <div className="settings-form-help" style={{ marginTop: '8px' }}>
              Ollama runs on this server. No API key is required; models are loaded from the local Ollama service.
            </div>
          )}

          {/* Test Primary AI Integration button */}
          <div className="settings-form-group" style={{ marginTop: '8px' }}>
            <button
              onClick={testPrimaryAiConnection}
              disabled={!settings.ai_provider || testingPrimaryAi}
              style={{ marginTop: '10px', padding: '8px 16px', backgroundColor: (!settings.ai_provider || testingPrimaryAi) ? '#6c757d' : '#f0b90b', color: 'black', border: 'none', borderRadius: '4px', cursor: (!settings.ai_provider || testingPrimaryAi) ? 'not-allowed' : 'pointer', fontSize: '14px', width: '100%', fontWeight: 'bold', transition: 'all 0.2s' }}
            >
              {testingPrimaryAi ? 'Testing Connection...' : 'Test API Connection'}
            </button>
            {primaryAiTestResult && (
              <div className={`settings-status ${primaryAiTestResult.success ? 'success' : 'error'}`} style={{ marginTop: '8px' }}>
                {primaryAiTestResult.message}
              </div>
            )}
          </div>
        </div>

        {/* Row 2, Right: Secondary AI Integration */}
        <div className="settings-page-section">
          <h3>Secondary AI Integration</h3>

          <div className="settings-form-group">
            <label>AI Provider</label>
            <select
              value={settings.ai_provider_secondary || settings.ai_provider_fallback || ''}
              onChange={(e) => handleInputChange('ai_provider_secondary', e.target.value)}
            >
              <option value="">-- Select Secondary Provider --</option>
              <option value="openai">OpenAI</option>
              <option value="zai">Z.AI</option>
              <option value="perplexity">Perplexity</option>
              <option value="gemini">Gemini</option>
              <option value="inception">Inception Labs</option>
              {isEventStrategyAdmin && <option value="ollama">Ollama (local)</option>}
            </select>
            <div className="settings-form-help">
              Choose your secondary AI provider for automatic failover
            </div>
          </div>

          <div className="settings-form-group">
            <label>AI Model</label>
            <select
              value={settings.ai_model_secondary || settings.ai_model_fallback || ''}
              onChange={(e) => handleInputChange('ai_model_secondary', e.target.value)}
            >
              {(modelOptions[settings.ai_provider_secondary || settings.ai_provider_fallback] || []).map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
            <div className="settings-form-help">
              Select an AI model supported by the chosen secondary provider
            </div>
          </div>

          {/* Reasoning Effort for Secondary */}
          {['gemini', 'openai'].includes(settings.ai_provider_secondary || settings.ai_provider_fallback) && (
            <div className="settings-form-group">
              <label>Reasoning</label>
              <select
                value={settings.ai_reasoning_level_secondary || settings.ai_reasoning_level_fallback || 'medium'}
                onChange={(e) => handleInputChange('ai_reasoning_level_secondary', e.target.value)}
              >
                <option value="light">Light</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="extra high">Extra High</option>
              </select>
              <div className="settings-form-help">
                Configure reasoning effort for supported models
              </div>
            </div>
          )}

          {/* OpenAI Secondary Configuration */}
          {(settings.ai_provider_secondary === 'openai' || settings.ai_provider_fallback === 'openai') && (
            <div className="settings-form-group">
              <label>OpenAI API Key</label>
              <input
                type="password"
                value={settings.openai_key_fallback || ''}
                onChange={(e) => handleInputChange('openai_key_fallback', e.target.value)}
                placeholder="Enter OpenAI API Key"
              />
              <div className="settings-form-help">
                Used as secondary fallback for AI-powered trading analysis
              </div>
            </div>
          )}

          {/* Z.AI Secondary Configuration */}
          {(settings.ai_provider_secondary === 'zai' || settings.ai_provider_fallback === 'zai') && (
            <div className="settings-form-group">
              <label>Z.AI API Key</label>
              <input
                type="password"
                value={settings.zai_key_fallback || ''}
                onChange={(e) => handleInputChange('zai_key_fallback', e.target.value)}
                placeholder="Enter Z.AI API Key"
              />
              <div className="settings-form-help">
                Used as secondary fallback for AI-powered trading analysis
              </div>
            </div>
          )}

          {/* Perplexity Secondary Configuration */}
          {(settings.ai_provider_secondary === 'perplexity' || settings.ai_provider_fallback === 'perplexity') && (
            <div className="settings-form-group">
              <label>Perplexity API Key</label>
              <input
                type="password"
                value={settings.perplexity_key_fallback || ''}
                onChange={(e) => handleInputChange('perplexity_key_fallback', e.target.value)}
                placeholder="Enter Perplexity API Key"
              />
              <div className="settings-form-help">
                Used as secondary fallback for AI-powered trading analysis
              </div>
            </div>
          )}

          {/* Gemini Secondary Configuration */}
          {(settings.ai_provider_secondary === 'gemini' || settings.ai_provider_fallback === 'gemini') && (
            <div className="settings-form-group">
              <label>Gemini API Key</label>
              <input
                type="password"
                value={settings.gemini_key_fallback || ''}
                onChange={(e) => handleInputChange('gemini_key_fallback', e.target.value)}
                placeholder="Enter Gemini API Key"
              />
              <div className="settings-form-help">
                Used as secondary fallback for AI-powered trading analysis
              </div>
            </div>
          )}

          {/* Inception Labs Secondary Configuration */}
          {(settings.ai_provider_secondary === 'inception' || settings.ai_provider_fallback === 'inception') && (
            <div className="settings-form-group">
              <label>Inception Labs API Key</label>
              <input
                type="password"
                value={settings.inception_key_fallback || ''}
                onChange={(e) => handleInputChange('inception_key_fallback', e.target.value)}
                placeholder="Enter Inception Labs API Key"
              />
              <div className="settings-form-help">
                Used as secondary fallback for AI-powered trading analysis
              </div>
            </div>
          )}

          {(settings.ai_provider_secondary === 'ollama' || settings.ai_provider_fallback === 'ollama') && isEventStrategyAdmin && (
            <div className="settings-form-help" style={{ marginTop: '8px' }}>
              Ollama runs on this server. No API key is required; models are loaded from the local Ollama service.
            </div>
          )}

          {/* Test Secondary AI Connection button */}
          <div className="settings-form-group" style={{ marginTop: '8px' }}>
            <button
              onClick={testFallbackConnection}
              disabled={!(settings.ai_provider_secondary || settings.ai_provider_fallback) || testingFallback}
              style={{ marginTop: '10px', padding: '8px 16px', backgroundColor: (!(settings.ai_provider_secondary || settings.ai_provider_fallback) || testingFallback) ? '#6c757d' : '#f0b90b', color: 'black', border: 'none', borderRadius: '4px', cursor: (!(settings.ai_provider_secondary || settings.ai_provider_fallback) || testingFallback) ? 'not-allowed' : 'pointer', fontSize: '14px', width: '100%', fontWeight: 'bold', transition: 'all 0.2s' }}
            >
              {testingFallback ? 'Testing Connection...' : 'Test API Connection'}
            </button>
            {fallbackTestResult && (
              <div className={`settings-status ${fallbackTestResult.success ? 'success' : 'error'}`} style={{ marginTop: '8px' }}>
                {fallbackTestResult.message}
              </div>
            )}
          </div>
        </div>

        {/* Row 3: Tertiary AI Integration */}
        <div className="settings-page-section">
          <h3>Tertiary AI Integration</h3>

          <div className="settings-form-group">
            <label>AI Provider</label>
            <select
              value={settings.ai_provider_tertiary || ''}
              onChange={(e) => handleInputChange('ai_provider_tertiary', e.target.value)}
            >
              <option value="">-- Select Tertiary Provider --</option>
              <option value="openai">OpenAI</option>
              <option value="zai">Z.AI</option>
              <option value="perplexity">Perplexity</option>
              <option value="gemini">Gemini</option>
              <option value="inception">Inception Labs</option>
              {isEventStrategyAdmin && <option value="ollama">Ollama (local)</option>}
            </select>
            <div className="settings-form-help">
              Choose your tertiary AI provider for secondary failover
            </div>
          </div>

          <div className="settings-form-group">
            <label>AI Model</label>
            <select
              value={settings.ai_model_tertiary || ''}
              onChange={(e) => handleInputChange('ai_model_tertiary', e.target.value)}
            >
              {(modelOptions[settings.ai_provider_tertiary] || []).map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
            <div className="settings-form-help">
              Select an AI model supported by the chosen tertiary provider
            </div>
          </div>

          {/* Reasoning Effort for Tertiary */}
          {['gemini', 'openai'].includes(settings.ai_provider_tertiary) && (
            <div className="settings-form-group">
              <label>Reasoning</label>
              <select
                value={settings.ai_reasoning_level_tertiary || 'medium'}
                onChange={(e) => handleInputChange('ai_reasoning_level_tertiary', e.target.value)}
              >
                <option value="light">Light</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="extra high">Extra High</option>
              </select>
              <div className="settings-form-help">
                Configure reasoning effort for supported models
              </div>
            </div>
          )}

          {/* OpenAI Tertiary Configuration */}
          {settings.ai_provider_tertiary === 'openai' && (
            <div className="settings-form-group">
              <label>OpenAI API Key</label>
              <input
                type="password"
                value={settings.openai_key_tertiary || ''}
                onChange={(e) => handleInputChange('openai_key_tertiary', e.target.value)}
                placeholder="Enter OpenAI API Key"
              />
              <div className="settings-form-help">
                Used as tertiary fallback for AI-powered trading analysis
              </div>
            </div>
          )}

          {/* Z.AI Tertiary Configuration */}
          {settings.ai_provider_tertiary === 'zai' && (
            <div className="settings-form-group">
              <label>Z.AI API Key</label>
              <input
                type="password"
                value={settings.zai_key_tertiary || ''}
                onChange={(e) => handleInputChange('zai_key_tertiary', e.target.value)}
                placeholder="Enter Z.AI API Key"
              />
              <div className="settings-form-help">
                Used as tertiary fallback for AI-powered trading analysis
              </div>
            </div>
          )}

          {/* Perplexity Tertiary Configuration */}
          {settings.ai_provider_tertiary === 'perplexity' && (
            <div className="settings-form-group">
              <label>Perplexity API Key</label>
              <input
                type="password"
                value={settings.perplexity_key_tertiary || ''}
                onChange={(e) => handleInputChange('perplexity_key_tertiary', e.target.value)}
                placeholder="Enter Perplexity API Key"
              />
              <div className="settings-form-help">
                Used as tertiary fallback for AI-powered trading analysis
              </div>
            </div>
          )}

          {/* Gemini Tertiary Configuration */}
          {settings.ai_provider_tertiary === 'gemini' && (
            <div className="settings-form-group">
              <label>Gemini API Key</label>
              <input
                type="password"
                value={settings.gemini_key_tertiary || ''}
                onChange={(e) => handleInputChange('gemini_key_tertiary', e.target.value)}
                placeholder="Enter Gemini API Key"
              />
              <div className="settings-form-help">
                Used as tertiary fallback for AI-powered trading analysis
              </div>
            </div>
          )}

          {/* Inception Labs Tertiary Configuration */}
          {settings.ai_provider_tertiary === 'inception' && (
            <div className="settings-form-group">
              <label>Inception Labs API Key</label>
              <input
                type="password"
                value={settings.inception_key_tertiary || ''}
                onChange={(e) => handleInputChange('inception_key_tertiary', e.target.value)}
                placeholder="Enter Inception Labs API Key"
              />
              <div className="settings-form-help">
                Used as tertiary fallback for AI-powered trading analysis
              </div>
            </div>
          )}

          {settings.ai_provider_tertiary === 'ollama' && isEventStrategyAdmin && (
            <div className="settings-form-help" style={{ marginTop: '8px' }}>
              Ollama runs on this server. No API key is required; models are loaded from the local Ollama service.
            </div>
          )}

          {/* Test Tertiary AI Connection button */}
          <div className="settings-form-group" style={{ marginTop: '8px' }}>
            <button
              onClick={testTertiaryAiConnection}
              disabled={!settings.ai_provider_tertiary || testingTertiaryAi}
              style={{ marginTop: '10px', padding: '8px 16px', backgroundColor: (!settings.ai_provider_tertiary || testingTertiaryAi) ? '#6c757d' : '#f0b90b', color: 'black', border: 'none', borderRadius: '4px', cursor: (!settings.ai_provider_tertiary || testingTertiaryAi) ? 'not-allowed' : 'pointer', fontSize: '14px', width: '100%', fontWeight: 'bold', transition: 'all 0.2s' }}
            >
              {testingTertiaryAi ? 'Testing Connection...' : 'Test API Connection'}
            </button>
            {tertiaryAiTestResult && (
              <div className={`settings-status ${tertiaryAiTestResult.success ? 'success' : 'error'}`} style={{ marginTop: '8px' }}>
                {tertiaryAiTestResult.message}
              </div>
            )}
          </div>
        </div>

        {/* Row 4: Quartan AI Integration */}
        <div className="settings-page-section">
          <h3>Quartan AI Integration (Fourth Fallback)</h3>

          <div className="settings-form-group">
            <label>AI Provider</label>
            <select
              value={settings.ai_provider_quartan || ''}
              onChange={(e) => handleInputChange('ai_provider_quartan', e.target.value)}
            >
              <option value="">-- Select Quartan Provider --</option>
              <option value="openai">OpenAI</option>
              <option value="zai">Z.AI</option>
              <option value="perplexity">Perplexity</option>
              <option value="gemini">Gemini</option>
              <option value="inception">Inception Labs</option>
              {isEventStrategyAdmin && <option value="ollama">Ollama (local/cloud)</option>}
            </select>
            <div className="settings-form-help">
              Used as the final fallback after primary, secondary, and tertiary providers.
            </div>
          </div>

          <div className="settings-form-group">
            <label>AI Model</label>
            <select
              value={settings.ai_model_quartan || ''}
              onChange={(e) => handleInputChange('ai_model_quartan', e.target.value)}
              disabled={!settings.ai_provider_quartan}
            >
              <option value="">-- Select a model --</option>
              {(modelOptions[settings.ai_provider_quartan] || []).map((option) => (
                <option key={option.value || option} value={option.value || option}>{option.label || option.value || option}</option>
              ))}
            </select>
            <div className="settings-form-help">
              Select an AI model supported by the chosen quartan provider.
            </div>
          </div>

          {['gemini', 'openai'].includes(settings.ai_provider_quartan) && (
            <div className="settings-form-group">
              <label>Reasoning</label>
              <select
                value={settings.ai_reasoning_level_quartan || 'medium'}
                onChange={(e) => handleInputChange('ai_reasoning_level_quartan', e.target.value)}
              >
                <option value="light">Light</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="extra high">Extra High</option>
              </select>
              <div className="settings-form-help">Configure reasoning effort for supported models.</div>
            </div>
          )}

          {settings.ai_provider_quartan && settings.ai_provider_quartan !== 'ollama' && (
            <div className="settings-form-group">
              <label>{settings.ai_provider_quartan === 'zai' ? 'Z.AI' : settings.ai_provider_quartan[0].toUpperCase() + settings.ai_provider_quartan.slice(1)} API Key</label>
              <input
                type="password"
                value={settings[`${settings.ai_provider_quartan}_key_quartan`] || ''}
                onChange={(e) => handleInputChange(`${settings.ai_provider_quartan}_key_quartan`, e.target.value)}
                placeholder="Enter API Key"
              />
              <div className="settings-form-help">Used only when all earlier AI providers are unavailable.</div>
            </div>
          )}

          {settings.ai_provider_quartan === 'ollama' && isEventStrategyAdmin && (
            <div className="settings-form-help" style={{ marginTop: '8px' }}>
              Ollama runs through the Ollama service on this server. Local and signed-in cloud models are supported; no API key is required here.
            </div>
          )}

          <div className="settings-form-group" style={{ marginTop: '8px' }}>
            <button
              onClick={testQuartanAiConnection}
              disabled={!settings.ai_provider_quartan || !settings.ai_model_quartan || testingQuartanAi}
              style={{ marginTop: '10px', padding: '8px 16px', backgroundColor: (!settings.ai_provider_quartan || !settings.ai_model_quartan || testingQuartanAi) ? '#6c757d' : '#f0b90b', color: 'black', border: 'none', borderRadius: '4px', cursor: (!settings.ai_provider_quartan || !settings.ai_model_quartan || testingQuartanAi) ? 'not-allowed' : 'pointer', fontSize: '14px', width: '100%', fontWeight: 'bold', transition: 'all 0.2s' }}
            >
              {testingQuartanAi ? 'Testing Connection...' : 'Test API Connection'}
            </button>
            {quartanAiTestResult && (
              <div className={`settings-status ${quartanAiTestResult.success ? 'success' : 'error'}`} style={{ marginTop: '8px' }}>
                {quartanAiTestResult.message}
              </div>
            )}
          </div>
        </div>
        </div>
      )}

      {/* Web Search & News Tab */}
      {activeTab === 'web-search' && (
        <div className="settings-page-section">
          <h3>🔍 Web Search &amp; News Grounding</h3>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          {/* Primary Brave Search API Key */}
          <div className="settings-form-group">
            <label>
              Brave Search API Key
            </label>
            <input
              type="password"
              value={settings.brave_search_api_key || ''}
              onChange={(e) => handleInputChange('brave_search_api_key', e.target.value)}
              placeholder="Enter primary API key..."
            />
            <div className="settings-form-help">
              Primary search API (2,000 uses/month)
            </div>
            <button
              onClick={testBraveSearchApiKey}
              disabled={!settings.brave_search_api_key || testingBraveApi}
              className={`settings-button ${(!settings.brave_search_api_key || testingBraveApi) ? 'disabled' : ''}`}
              style={{ marginTop: '8px' }}
            >
              {testingBraveApi ? '⏳ Testing...' : '🧪 Test Brave Search API Key'}
            </button>
            {braveApiTestResult && (
              <div className={`settings-status ${braveApiTestResult.success ? 'success' : 'error'}`}>
                {braveApiTestResult.message}
              </div>
            )}
          </div>

          {/* Fallback Brave Search API Key */}
          <div className="settings-form-group">
            <label>
              Fallback Brave Search API Key
            </label>
            <input
              type="password"
              value={settings.brave_search_api_key_fallback || ''}
              onChange={(e) => handleInputChange('brave_search_api_key_fallback', e.target.value)}
              placeholder="Enter fallback API key..."
            />
            <div className="settings-form-help">
              Fallback search API (2,000 uses/month)
            </div>
            <button
              onClick={testBraveSearchApiFallback}
              disabled={!settings.brave_search_api_key_fallback || testingBraveApiFallback}
              className={`settings-button ${(!settings.brave_search_api_key_fallback || testingBraveApiFallback) ? 'disabled' : ''}`}
              style={{ marginTop: '8px' }}
            >
              {testingBraveApiFallback ? '⏳ Testing...' : '🧪 Test Brave Search API Key'}
            </button>
            {braveApiFallbackTestResult && (
              <div className={`settings-status ${braveApiFallbackTestResult.success ? 'success' : 'error'}`}>
                {braveApiFallbackTestResult.message}
              </div>
            )}
          </div>

          <div className="settings-form-group">
            <label>
              NewsAPI.org API Key
            </label>
            <input
              type="password"
              value={settings.news_api || ''}
              onChange={(e) => handleInputChange('news_api', e.target.value)}
              placeholder="Enter your NewsAPI.org API key..."
            />
            <div className="settings-form-help">
              Used only with NewsAPI.org&apos;s article search feed to ground market-news analysis. This is not an AI-provider key.
            </div>
          </div>
        </div>

        <div className="settings-form-help" style={{ marginTop: '12px', fontStyle: 'italic' }}>
          💡 Combined limit: 4,000 searches/month before falling back to DuckDuckGo
        </div>
        </div>
      )}

      {/* Sentiment & Strategy Tab - Part 1: Strategy Parameters */}
      {activeTab === 'sentiment-strategy' && (
        <div data-section="ai-settings" className="settings-page-section">
          <h3>🤖 AI Trading &amp; Strategy Parameters</h3>
          <p style={{ color: '#94a3b8', fontSize: '13px', marginBottom: 16 }}>
            Parameters governing automated portfolio scans, risk profiles, and execution confidence for all cryptocurrencies and traditional securities.
          </p>

        <div className="settings-grid">
          <div className="settings-form-group">
            <label>
              AI Notifications
            </label>
            <div className="settings-checkbox-group">
              <input
                type="checkbox"
                checked={settings.ai_notifications_enabled || false}
                onChange={(e) => handleInputChange('ai_notifications_enabled', e.target.checked)}
                className="settings-checkbox"
              />
              <span>
                Enable AI trading alerts
              </span>
            </div>
            <div className="settings-form-help">
              Receive alerts for high-confidence AI signals
            </div>
          </div>

          <div className="settings-form-group">
            <label>
              Analysis Frequency
            </label>
            <select
              value={settings.ai_analysis_frequency || 'daily'}
              onChange={(e) => handleInputChange('ai_analysis_frequency', e.target.value)}
            >
              <option value="hourly">Hourly</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
            </select>
            <div className="settings-form-help">
              How often AI analyzes your portfolio
            </div>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
          <div>
            <label style={{ display: 'block', marginBottom: 8, color: '#fff' }}>
              Risk Tolerance
            </label>
            <select
              value={settings.ai_risk_tolerance || 'moderate'}
              onChange={(e) => handleInputChange('ai_risk_tolerance', e.target.value)}
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: 6,
                background: '#1a1f23',
                color: '#fff',
                border: '1px solid #444',
                boxSizing: 'border-box'
              }}
            >
              <option value="conservative">Conservative</option>
              <option value="moderate">Moderate</option>
              <option value="aggressive">Aggressive</option>
            </select>
            <p style={{ color: '#666', fontSize: '12px', marginTop: 4 }}>
              Determines AI trading strategy risk level
            </p>
          </div>

          <div>
            <label style={{ display: 'block', marginBottom: 8, color: '#fff' }}>
              Confidence Threshold (%)
            </label>
            <input
              type="number"
              min="50"
              max="95"
              value={settings.ai_confidence_threshold || 75}
              onChange={(e) => handleInputChange('ai_confidence_threshold', parseInt(e.target.value))}
              style={{
                width: 'calc(100% - 24px)',
                padding: '8px 12px',
                borderRadius: 6,
                background: '#1a1f23',
                color: '#fff',
                border: '1px solid #444',
                boxSizing: 'border-box'
              }}
            />
            <p style={{ color: '#666', fontSize: '12px', marginTop: 4 }}>
              Minimum confidence for AI recommendations
            </p>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
          <div>
            <label style={{ display: 'block', marginBottom: 8, color: '#fff' }}>
              Cache Duration (Hours)
            </label>
            <input
              type="number"
              min="1"
              max="24"
              value={settings.ai_cache_duration_hours || 4}
              onChange={(e) => handleInputChange('ai_cache_duration_hours', parseInt(e.target.value))}
              style={{
                width: 'calc(100% - 24px)',
                padding: '8px 12px',
                borderRadius: 6,
                background: '#1a1f23',
                color: '#fff',
                border: '1px solid #444',
                boxSizing: 'border-box'
              }}
            />
            <p style={{ color: '#666', fontSize: '12px', marginTop: 4 }}>
              How long to cache AI analysis results
            </p>
          </div>

          <div>
            <label style={{ display: 'block', marginBottom: 8, color: '#fff' }}>
              Analysis Window Start
            </label>
            <input
              type="time"
              value={settings.ai_analysis_window_start || '08:00'}
              onChange={(e) => handleInputChange('ai_analysis_window_start', e.target.value)}
              style={{
                width: 'calc(100% - 24px)',
                padding: '8px 12px',
                borderRadius: 6,
                background: '#1a1f23',
                color: '#fff',
                border: '1px solid #444',
                boxSizing: 'border-box'
              }}
            />
            <p style={{ color: '#666', fontSize: '12px', marginTop: 4 }}>
              Start time for AI analysis window (ET)
            </p>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>

          {settings.ai_analysis_frequency === 'hourly' && (
            <div>
              <label style={{ display: 'block', marginBottom: 8, color: '#fff' }}>
                Analysis Window End
              </label>
              <input
                type="time"
                value={settings.ai_analysis_window_end || '24:00'}
                onChange={(e) => handleInputChange('ai_analysis_window_end', e.target.value)}
                style={{
                  width: 'calc(100% - 24px)',
                  padding: '8px 12px',
                  borderRadius: 6,
                  background: '#1a1f23',
                  color: '#fff',
                  border: '1px solid #444',
                  boxSizing: 'border-box'
                }}
              />
              <p style={{ color: '#666', fontSize: '12px', marginTop: 4 }}>
                End time for AI analysis window (ET)
              </p>
            </div>
          )}

          <div>
            <label style={{ display: 'block', marginBottom: 8, color: '#fff' }}>
              Max Tokens per Request
            </label>
            <input
              type="number"
              min="500"
              max="8000"
              value={settings.ai_max_tokens || 2000}
              onChange={(e) => handleInputChange('ai_max_tokens', parseInt(e.target.value))}
              style={{
                width: 'calc(100% - 24px)',
                padding: '8px 12px',
                borderRadius: 6,
                background: '#1a1f23',
                color: '#fff',
                border: '1px solid #444',
                boxSizing: 'border-box'
              }}
            />
            <p style={{ color: '#666', fontSize: '12px', marginTop: 4 }}>
              Maximum tokens for AI responses (500-8000)
            </p>
          </div>
        </div>
        </div>
      )}

      {/* AI Agentic Workflow Prompts Tab */}
      {activeTab === 'ai-prompts' && (
        <div data-section="ai-prompts" className="settings-page-section">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
            <h3 style={{ margin: 0, color: '#4fd1c5' }}>📝 AI Agentic Workflow Prompts</h3>
            <span style={{ fontSize: '12px', color: '#60a5fa', background: 'rgba(59, 130, 246, 0.12)', padding: '4px 10px', borderRadius: '4px', border: '1px solid rgba(59, 130, 246, 0.25)' }}>
              Crypto (Binance.US &amp; Webull) · Securities &amp; ETFs (Webull)
            </span>
          </div>
          <p style={{ color: '#94a3b8', fontSize: '13px', marginBottom: 20, lineHeight: 1.5 }}>
            Configure prompts for the 3-stage agentic workflow: <strong>Stage 1</strong> (search query generation), <strong>Stage 2</strong> (web search &amp; news grounding), and <strong>Stage 3</strong> (synthesis &amp; strategy evaluation). All prompt templates accept <code>{'{symbol}'}</code>, <code>{'{datetime}'}</code>, and <code>{'{amount}'}</code> variables, and apply universally to both cryptocurrency and traditional securities across Binance.US and Webull.
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 16 }}>
            {/* Market Analysis */}
            <div style={{ background: '#1a1f23', padding: 16, borderRadius: 8, border: '1px solid #444' }}>
              <h5 style={{ color: '#4fd1c5', marginBottom: 12, fontSize: '14px' }}>Market Analysis</h5>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', marginBottom: 8, color: '#fff', fontSize: '12px' }}>
                    Pre-Search Prompt (Stage 1)
                  </label>
                  <textarea
                    value={settings.ai_prompts?.market_analysis_pre || ''}
                    onChange={(e) => {
                      handleInputChange('ai_prompts', {
                        ...settings.ai_prompts,
                        market_analysis_pre: e.target.value
                      });
                      autoResizeTextarea(e.target);
                    }}
                    onInput={(e) => autoResizeTextarea(e.target)}
                    placeholder="Prompt to generate search queries for market analysis..."
                    style={{
                      width: 'calc(100% - 24px)',
                      padding: '8px 12px',
                      borderRadius: 6,
                      background: '#232b31',
                      color: '#fff',
                      border: '1px solid #555',
                      boxSizing: 'border-box',
                      resize: 'none',
                      fontSize: '12px',
                      minHeight: '80px',
                      overflow: 'hidden',
                      lineHeight: '1.5'
                    }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: 8, color: '#fff', fontSize: '12px' }}>
                    Post-Search Prompt (Stage 3)
                  </label>
                  <textarea
                    value={settings.ai_prompts?.market_analysis_post || ''}
                    onChange={(e) => {
                      handleInputChange('ai_prompts', {
                        ...settings.ai_prompts,
                        market_analysis_post: e.target.value
                      });
                      autoResizeTextarea(e.target);
                    }}
                    onInput={(e) => autoResizeTextarea(e.target)}
                    placeholder="Prompt to synthesize search results into market analysis..."
                    style={{
                      width: 'calc(100% - 24px)',
                      padding: '8px 12px',
                      borderRadius: 6,
                      background: '#232b31',
                      color: '#fff',
                      border: '1px solid #555',
                      boxSizing: 'border-box',
                      resize: 'none',
                      fontSize: '12px',
                      minHeight: '80px',
                      overflow: 'hidden',
                      lineHeight: '1.5'
                    }}
                  />
                </div>
              </div>
            </div>


            {/* Portfolio Review */}
            <div style={{ background: '#1a1f23', padding: 16, borderRadius: 8, border: '1px solid #444' }}>
              <h5 style={{ color: '#4fd1c5', marginBottom: 12, fontSize: '14px' }}>Portfolio Review</h5>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', marginBottom: 8, color: '#fff', fontSize: '12px' }}>
                    Pre-Search Prompt (Stage 1)
                  </label>
                  <textarea
                    value={settings.ai_prompts?.portfolio_review_pre || ''}
                    onChange={(e) => {
                      handleInputChange('ai_prompts', {
                        ...settings.ai_prompts,
                        portfolio_review_pre: e.target.value
                      });
                      autoResizeTextarea(e.target);
                    }}
                    onInput={(e) => autoResizeTextarea(e.target)}
                    placeholder="Prompt to generate search queries for portfolio review..."
                    style={{
                      width: 'calc(100% - 24px)',
                      padding: '8px 12px',
                      borderRadius: 6,
                      background: '#232b31',
                      color: '#fff',
                      border: '1px solid #555',
                      boxSizing: 'border-box',
                      resize: 'none',
                      fontSize: '12px',
                      minHeight: '80px',
                      overflow: 'hidden',
                      lineHeight: '1.5'
                    }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: 8, color: '#fff', fontSize: '12px' }}>
                    Post-Search Prompt (Stage 3)
                  </label>
                  <textarea
                    value={settings.ai_prompts?.portfolio_review_post || ''}
                    onChange={(e) => {
                      handleInputChange('ai_prompts', {
                        ...settings.ai_prompts,
                        portfolio_review_post: e.target.value
                      });
                      autoResizeTextarea(e.target);
                    }}
                    onInput={(e) => autoResizeTextarea(e.target)}
                    placeholder="Prompt to synthesize search results into portfolio review..."
                    style={{
                      width: 'calc(100% - 24px)',
                      padding: '8px 12px',
                      borderRadius: 6,
                      background: '#232b31',
                      color: '#fff',
                      border: '1px solid #555',
                      boxSizing: 'border-box',
                      resize: 'none',
                      fontSize: '12px',
                      minHeight: '80px',
                      overflow: 'hidden',
                      lineHeight: '1.5'
                    }}
                  />
                </div>
              </div>
            </div>


            {/* Asset & News Analysis (Crypto & Securities) */}
            <div style={{ background: '#1a1f23', padding: 16, borderRadius: 8, border: '1px solid #444' }}>
              <h5 style={{ color: '#4fd1c5', marginBottom: 12, fontSize: '14px' }}>Asset &amp; News Analysis (Crypto &amp; Securities)</h5>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', marginBottom: 8, color: '#fff', fontSize: '12px' }}>
                    Pre-Search Prompt (Stage 1)
                  </label>
                  <textarea
                    value={settings.ai_prompts?.coin_analysis_pre || ''}
                    onChange={(e) => {
                      handleInputChange('ai_prompts', {
                        ...settings.ai_prompts,
                        coin_analysis_pre: e.target.value
                      });
                      autoResizeTextarea(e.target);
                    }}
                    onInput={(e) => autoResizeTextarea(e.target)}
                    placeholder="Prompt to generate search queries for cryptocurrency or equity asset & news analysis..."
                    style={{
                      width: 'calc(100% - 24px)',
                      padding: '8px 12px',
                      borderRadius: 6,
                      background: '#232b31',
                      color: '#fff',
                      border: '1px solid #555',
                      boxSizing: 'border-box',
                      resize: 'none',
                      fontSize: '12px',
                      minHeight: '80px',
                      overflow: 'hidden',
                      lineHeight: '1.5'
                    }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: 8, color: '#fff', fontSize: '12px' }}>
                    Post-Search Prompt (Stage 3)
                  </label>
                  <textarea
                    value={settings.ai_prompts?.coin_analysis_post || ''}
                    onChange={(e) => {
                      handleInputChange('ai_prompts', {
                        ...settings.ai_prompts,
                        coin_analysis_post: e.target.value
                      });
                      autoResizeTextarea(e.target);
                    }}
                    onInput={(e) => autoResizeTextarea(e.target)}
                    placeholder="Prompt to synthesize search results into comprehensive asset & news analysis..."
                    style={{
                      width: 'calc(100% - 24px)',
                      padding: '8px 12px',
                      borderRadius: 6,
                      background: '#232b31',
                      color: '#fff',
                      border: '1px solid #555',
                      boxSizing: 'border-box',
                      resize: 'none',
                      fontSize: '12px',
                      minHeight: '80px',
                      overflow: 'hidden',
                      lineHeight: '1.5'
                    }}
                  />
                </div>
              </div>
            </div>

            {/* Portfolio Sentiment Analysis */}
            <div style={{ background: '#1a1f23', padding: 16, borderRadius: 8, border: '1px solid #444', marginTop: 16 }}>
              <h5 style={{ color: '#4fd1c5', marginBottom: 12, fontSize: '14px' }}>Portfolio Sentiment Analysis</h5>
              <p style={{ color: '#a0a6b8', fontSize: '12px', marginBottom: 16, lineHeight: '1.4' }}>
                Automated sentiment analysis for held assets (cryptocurrency &amp; traditional securities) across Binance.US and Webull. Classifies into: <strong>Hold, Buy Immediately, Consider Buying, Sell Immediately, Consider Selling</strong>.
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', marginBottom: 8, color: '#fff', fontSize: '12px' }}>
                    Pre-Search Prompt (Stage 1)
                  </label>
                  <textarea
                    value={settings.ai_prompts?.sentiment_prompt_pre || ''}
                    onChange={(e) => {
                      handleInputChange('ai_prompts', {
                        ...settings.ai_prompts,
                        sentiment_prompt_pre: e.target.value
                      });
                      autoResizeTextarea(e.target);
                    }}
                    style={{
                      width: 'calc(100% - 24px)',
                      padding: '8px 12px',
                      borderRadius: 6,
                      background: '#232b31',
                      color: '#fff',
                      border: '1px solid #555',
                      boxSizing: 'border-box',
                      resize: 'none',
                      fontSize: '12px',
                      minHeight: '80px',
                      overflow: 'hidden',
                      lineHeight: '1.5'
                    }}
                  />

                  {/* Portfolio Sentiment Update Frequency */}
                  <div style={{ marginTop: 12 }}>
                    <label style={{ display: 'block', marginBottom: 6, color: '#fff', fontSize: '12px' }}>
                      Portfolio Sentiment Update Frequency (hours)
                    </label>
                    <input
                      type="number"
                      min="1"
                      value={settings.sentiment_analysis_frequency_hours || 24}
                      onChange={(e) => handleInputChange('sentiment_analysis_frequency_hours', parseInt(e.target.value))}
                      style={{
                        width: '100%',
                        padding: '8px 12px',
                        borderRadius: 6,
                        background: '#232b31',
                        color: '#fff',
                        border: '1px solid #555',
                        boxSizing: 'border-box',
                        fontSize: '12px'
                      }}
                    />
                  </div>

                  <div style={{ marginTop: 12 }}>
                    <label style={{ display: 'block', marginBottom: 6, color: '#fff', fontSize: '12px' }}>
                      Forecast Evaluation Horizon (hours)
                    </label>
                    <input
                      type="number"
                      min="1"
                      max="168"
                      value={settings.sentiment_forecast_horizon_hours ?? 24}
                      onChange={(e) => handleInputChange('sentiment_forecast_horizon_hours', e.target.value)}
                      style={{ width: '100%', padding: '8px 12px', borderRadius: 6, background: '#232b31', color: '#fff', border: '1px solid #555', boxSizing: 'border-box', fontSize: '12px' }}
                    />
                    <span style={{ fontSize: '11px', color: '#94a3b8', marginTop: 4, display: 'block' }}>
                      Every prediction is graded at this fixed future horizon. Manual refreshes create separate forecasts and cannot close earlier ones.
                    </span>
                  </div>

                  {/* Portfolio Schedule Start Time */}
                  <div style={{ marginTop: 12 }}>
                    <label style={{ display: 'block', marginBottom: 6, color: '#fff', fontSize: '12px' }}>
                      Schedule Anchor Time (Start Time)
                    </label>
                    <input
                      type="time"
                      value={settings.portfolio_schedule_start_time || "08:00"}
                      onChange={(e) => handleInputChange('portfolio_schedule_start_time', e.target.value)}
                      style={{
                        width: '100%',
                        padding: '8px 12px',
                        borderRadius: 6,
                        background: '#232b31',
                        color: '#fff',
                        border: '1px solid #555',
                        boxSizing: 'border-box',
                        fontSize: '12px',
                        colorScheme: 'dark'
                      }}
                    />
                  </div>

                  {/* Sentiment Price & Volume Lookback Window */}
                  <div style={{ marginTop: 12 }}>
                    <label style={{ display: 'block', marginBottom: 6, color: '#fff', fontSize: '12px' }}>
                      Price & Volume History Lookback Window (hours)
                    </label>
                    <input
                      type="number"
                      min="1"
                      max="72"
                      value={settings.sentiment_history_lookback_hours || 12}
                      onChange={(e) => handleInputChange('sentiment_history_lookback_hours', parseInt(e.target.value) || 12)}
                      style={{
                        width: '100%',
                        padding: '8px 12px',
                        borderRadius: 6,
                        background: '#232b31',
                        color: '#fff',
                        border: '1px solid #555',
                        boxSizing: 'border-box',
                        fontSize: '12px'
                      }}
                    />
                    <span style={{ fontSize: '11px', color: '#94a3b8', marginTop: 4, display: 'block' }}>
                      Hours of hourly price & volume data fed to the AI model (Default: 12h, e.g. 6, 12, 24, 48).
                    </span>
                  </div>
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: 8, color: '#fff', fontSize: '12px' }}>
                    Post-Search Prompt (Stage 3)
                  </label>
                  <textarea
                    value={settings.ai_prompts?.sentiment_prompt_post || ''}
                    onChange={(e) => {
                      handleInputChange('ai_prompts', {
                        ...settings.ai_prompts,
                        sentiment_prompt_post: e.target.value
                      });
                      autoResizeTextarea(e.target);
                    }}
                    style={{
                      width: 'calc(100% - 24px)',
                      padding: '8px 12px',
                      borderRadius: 6,
                      background: '#232b31',
                      color: '#fff',
                      border: '1px solid #555',
                      boxSizing: 'border-box',
                      resize: 'none',
                      fontSize: '12px',
                      minHeight: '80px',
                      overflow: 'hidden',
                      lineHeight: '1.5'
                    }}
                  />
                </div>
              </div>
            </div>

            {/* Watchlist Sentiment Analysis */}
            <div style={{ background: '#1a1f23', padding: 16, borderRadius: 8, border: '1px solid #444', marginTop: 16 }}>
              <h5 style={{ color: '#4fd1c5', marginBottom: 12, fontSize: '14px' }}>Watchlist Sentiment Analysis</h5>
              <p style={{ color: '#a0a6b8', fontSize: '12px', marginBottom: 16, lineHeight: '1.4' }}>
                Automated and on-the-spot sentiment analysis for watchlist assets (cryptocurrency &amp; securities) monitored across Binance.US and Webull. Classifies prospective entry into: <strong>Avoid, Watch, Consider Buying, Definitely Buy</strong>.
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', marginBottom: 8, color: '#fff', fontSize: '12px' }}>
                    Pre-Search Prompt (Stage 1)
                  </label>
                  <textarea
                    value={settings.ai_prompts?.watchlist_sentiment_prompt_pre || ''}
                    onChange={(e) => {
                      handleInputChange('ai_prompts', {
                        ...settings.ai_prompts,
                        watchlist_sentiment_prompt_pre: e.target.value
                      });
                      autoResizeTextarea(e.target);
                    }}
                    style={{
                      width: 'calc(100% - 24px)',
                      padding: '8px 12px',
                      borderRadius: 6,
                      background: '#232b31',
                      color: '#fff',
                      border: '1px solid #555',
                      boxSizing: 'border-box',
                      resize: 'none',
                      fontSize: '12px',
                      minHeight: '80px',
                      overflow: 'hidden',
                      lineHeight: '1.5'
                    }}
                  />

                  {/* Watchlist Sentiment Update Frequency */}
                  <div style={{ marginTop: 12 }}>
                    <label style={{ display: 'block', marginBottom: 6, color: '#fff', fontSize: '12px' }}>
                      Watchlist Sentiment Update Frequency (hours)
                    </label>
                    <input
                      type="number"
                      min="1"
                      value={settings.watchlist_sentiment_analysis_frequency_hours || 24}
                      onChange={(e) => handleInputChange('watchlist_sentiment_analysis_frequency_hours', parseInt(e.target.value))}
                      style={{
                        width: '100%',
                        padding: '8px 12px',
                        borderRadius: 6,
                        background: '#232b31',
                        color: '#fff',
                        border: '1px solid #555',
                        boxSizing: 'border-box',
                        fontSize: '12px'
                      }}
                    />
                  </div>

                  <div style={{ marginTop: 12 }}>
                    <label style={{ display: 'block', marginBottom: 6, color: '#fff', fontSize: '12px' }}>
                      Forecast Evaluation Horizon (hours)
                    </label>
                    <input
                      type="number"
                      min="1"
                      max="168"
                      value={settings.watchlist_sentiment_forecast_horizon_hours ?? 24}
                      onChange={(e) => handleInputChange('watchlist_sentiment_forecast_horizon_hours', e.target.value)}
                      style={{ width: '100%', padding: '8px 12px', borderRadius: 6, background: '#232b31', color: '#fff', border: '1px solid #555', boxSizing: 'border-box', fontSize: '12px' }}
                    />
                    <span style={{ fontSize: '11px', color: '#94a3b8', marginTop: 4, display: 'block' }}>
                      Every prediction is graded at this fixed future horizon. Manual refreshes create separate forecasts and cannot close earlier ones.
                    </span>
                  </div>

                  {/* Watchlist Schedule Start Time */}
                  <div style={{ marginTop: 12 }}>
                    <label style={{ display: 'block', marginBottom: 6, color: '#fff', fontSize: '12px' }}>
                      Schedule Anchor Time (Start Time)
                    </label>
                    <input
                      type="time"
                      value={settings.watchlist_schedule_start_time || "08:00"}
                      onChange={(e) => handleInputChange('watchlist_schedule_start_time', e.target.value)}
                      style={{
                        width: '100%',
                        padding: '8px 12px',
                        borderRadius: 6,
                        background: '#232b31',
                        color: '#fff',
                        border: '1px solid #555',
                        boxSizing: 'border-box',
                        fontSize: '12px',
                        colorScheme: 'dark'
                      }}
                    />
                  </div>

                  {/* Watchlist Sentiment Price & Volume Lookback Window */}
                  <div style={{ marginTop: 12 }}>
                    <label style={{ display: 'block', marginBottom: 6, color: '#fff', fontSize: '12px' }}>
                      Price & Volume History Lookback Window (hours)
                    </label>
                    <input
                      type="number"
                      min="1"
                      max="72"
                      value={settings.watchlist_sentiment_history_lookback_hours || 12}
                      onChange={(e) => handleInputChange('watchlist_sentiment_history_lookback_hours', parseInt(e.target.value) || 12)}
                      style={{
                        width: '100%',
                        padding: '8px 12px',
                        borderRadius: 6,
                        background: '#232b31',
                        color: '#fff',
                        border: '1px solid #555',
                        boxSizing: 'border-box',
                        fontSize: '12px'
                      }}
                    />
                    <span style={{ fontSize: '11px', color: '#94a3b8', marginTop: 4, display: 'block' }}>
                      Hours of hourly price & volume data fed to the AI model for watchlist coins (Default: 12h, e.g. 6, 12, 24, 48).
                    </span>
                  </div>
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: 8, color: '#fff', fontSize: '12px' }}>
                    Post-Search Prompt (Stage 3)
                  </label>
                  <textarea
                    value={settings.ai_prompts?.watchlist_sentiment_prompt_post || ''}
                    onChange={(e) => {
                      handleInputChange('ai_prompts', {
                        ...settings.ai_prompts,
                        watchlist_sentiment_prompt_post: e.target.value
                      });
                      autoResizeTextarea(e.target);
                    }}
                    style={{
                      width: 'calc(100% - 24px)',
                      padding: '8px 12px',
                      borderRadius: 6,
                      background: '#232b31',
                      color: '#fff',
                      border: '1px solid #555',
                      boxSizing: 'border-box',
                      resize: 'none',
                      fontSize: '12px',
                      minHeight: '80px',
                      overflow: 'hidden',
                      lineHeight: '1.5'
                    }}
                  />
                </div>
              </div>
            </div>


            {/* AI Copilot System Prompt */}
            <div style={{ background: '#1a1f23', padding: 16, borderRadius: 8, border: '1px solid #444', marginTop: 16 }}>
              <h5 style={{ color: '#4fd1c5', marginBottom: 12, fontSize: '14px' }}>AI Copilot System Prompt</h5>
              <p style={{ color: '#a0a6b8', fontSize: '12px', marginBottom: 16, lineHeight: '1.4' }}>
                Configure the persona and analytical intelligence of the AI Copilot sidebar across both Binance.US (cryptocurrency) and Webull (cryptocurrency, equities, ETFs, options). The Copilot automatically receives your live portfolio, watchlist, pending orders, and active sidebar conversation feed.
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', marginBottom: 8, color: '#fff', fontSize: '12px' }}>
                    Search Intelligence Prompt (Pre-Search)
                  </label>
                  <textarea
                    value={settings.copilot_chat_pre || ''}
                    onChange={(e) => {
                      handleInputChange('copilot_chat_pre', e.target.value);
                      autoResizeTextarea(e.target);
                    }}
                    onInput={(e) => autoResizeTextarea(e.target)}
                    placeholder="e.g. You are the search intelligence module for the AI Copilot..."
                    style={{
                      width: 'calc(100% - 24px)',
                      padding: '8px 12px',
                      borderRadius: 6,
                      background: '#232b31',
                      color: '#fff',
                      border: '1px solid #555',
                      boxSizing: 'border-box',
                      resize: 'none',
                      fontSize: '12px',
                      minHeight: '80px',
                      overflow: 'hidden',
                      lineHeight: '1.5'
                    }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: 8, color: '#fff', fontSize: '12px' }}>
                    Copilot System Instructions (Post-Search Synthesis)
                  </label>
                  <textarea
                    value={settings.copilot_chat_post || ''}
                    onChange={(e) => {
                      handleInputChange('copilot_chat_post', e.target.value);
                      autoResizeTextarea(e.target);
                    }}
                    onInput={(e) => autoResizeTextarea(e.target)}
                    placeholder="e.g. You are the AI Copilot for Crypto & Securities Dashboard, an expert cryptocurrency portfolio strategist..."
                    style={{
                      width: 'calc(100% - 24px)',
                      padding: '8px 12px',
                      borderRadius: 6,
                      background: '#232b31',
                      color: '#fff',
                      border: '1px solid #555',
                      boxSizing: 'border-box',
                      resize: 'none',
                      fontSize: '12px',
                      minHeight: '80px',
                      overflow: 'hidden',
                      lineHeight: '1.5'
                    }}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Sentiment & Strategy Tab - Part 2: Sentiment Variable Settings */}
      {activeTab === 'sentiment-strategy' && (
        <section className="settings-page-section sentiment-variable-settings" style={{ marginTop: '24px' }}>
          <h3>🎯 Sentiment Variable Settings</h3>
          <p>
            Grade each new recommendation at its fixed forecast horizon using the rule values saved with that prediction. Applies universally to all cryptocurrency (Binance.US / Webull) and traditional securities (Webull). Directional Wrong values and the Hold steady range may be 0.00%; the Hold Wrong Threshold must be greater than its steady range. Exact boundaries are decisive.
          </p>
        <div className="sentiment-variable-grid">
          {SENTIMENT_VARIABLES.map(variable => {
            if (variable.kind === 'hold') {
              const steadyValue = settings[variable.steadyKey];
              const wrongValue = settings[variable.wrongKey];
              const { steadyError, wrongError } = holdThresholdErrors(settings);
              const valuesAreValid = !steadyError && !wrongError;
              const steady = valuesAreValid ? formatThreshold(steadyValue) : '';
              const wrong = valuesAreValid ? formatThreshold(wrongValue) : '';
              const correctText = Number(steadyValue) === 0
                ? 'Correct only when the price change is exactly 0.00%.'
                : `Correct from -${steady}% through +${steady}%.`;
              return <article className="sentiment-variable-row" key={variable.code}>
                <header>
                  <span className="sentiment-variable-code sentiment-variable-code-h">H</span>
                  <div>
                    <h4>Hold</h4>
                    <small>Expects price to remain steady</small>
                  </div>
                </header>
                <div className="sentiment-variable-inputs">
                  <label>
                    <span>Steady Range (±%)</span>
                    <input
                      type="number"
                      inputMode="decimal"
                      step="0.01"
                      min="0"
                      value={steadyValue ?? ''}
                      onChange={event => handleInputChange(variable.steadyKey, event.target.value)}
                      className={steadyError ? 'sentiment-threshold-invalid' : ''}
                      aria-invalid={Boolean(steadyError)}
                      aria-describedby={`${variable.steadyKey}-error`}
                    />
                    {steadyError && <small id={`${variable.steadyKey}-error`} className="sentiment-threshold-error">{steadyError}</small>}
                  </label>
                  <label>
                    <span>Wrong Threshold (±%)</span>
                    <input
                      type="number"
                      inputMode="decimal"
                      step="0.01"
                      min="0.01"
                      value={wrongValue ?? ''}
                      onChange={event => handleInputChange(variable.wrongKey, event.target.value)}
                      className={wrongError ? 'sentiment-threshold-invalid' : ''}
                      aria-invalid={Boolean(wrongError)}
                      aria-describedby={`${variable.wrongKey}-error`}
                    />
                    {wrongError && <small id={`${variable.wrongKey}-error`} className="sentiment-threshold-error">{wrongError}</small>}
                  </label>
                </div>
                {valuesAreValid && <p className="sentiment-neutral-help">
                  {correctText} Wrong at +{wrong}% or higher, or -{wrong}% or lower. Any move with a magnitude greater than {steady}% but less than {wrong}% is Neutral.
                </p>}
              </article>;
            }

            const correctValue = settings[variable.correctKey];
            const wrongValue = settings[variable.wrongKey];
            const correctError = sentimentThresholdError(correctValue);
            const wrongError = sentimentThresholdError(wrongValue, 0);
            const valuesAreValid = !correctError && !wrongError;
            const correct = valuesAreValid ? formatThreshold(correctValue) : '';
            const wrong = valuesAreValid ? formatThreshold(wrongValue) : '';
            const wrongBoundary = Number(wrongValue) === 0 ? '0.00' : `${variable.direction === 'up' ? '-' : '+'}${wrong}`;
            const neutralText = variable.direction === 'up'
              ? `Correct at +${correct}% or higher. Wrong at ${wrongBoundary}% or lower. Any move strictly between ${wrongBoundary}% and +${correct}% is Neutral.`
              : `Correct at -${correct}% or lower. Wrong at ${wrongBoundary}% or higher. Any move strictly between -${correct}% and ${wrongBoundary}% is Neutral.`;
            return <article className="sentiment-variable-row" key={variable.code}>
              <header>
                <span className={`sentiment-variable-code sentiment-variable-code-${variable.code.toLowerCase()}`}>{variable.code}</span>
                <div>
                  <h4>{variable.label}</h4>
                  <small>{variable.direction === 'up' ? 'Expects price to increase' : 'Expects price to decrease'}</small>
                </div>
              </header>
              <div className="sentiment-variable-inputs">
                <label>
                  <span>Correct (%)</span>
                  <input
                    type="number"
                    inputMode="decimal"
                    step="0.01"
                    min="0.01"
                    value={correctValue ?? ''}
                    onChange={event => handleInputChange(variable.correctKey, event.target.value)}
                    className={correctError ? 'sentiment-threshold-invalid' : ''}
                    aria-invalid={Boolean(correctError)}
                    aria-describedby={`${variable.correctKey}-error`}
                  />
                  {correctError && <small id={`${variable.correctKey}-error`} className="sentiment-threshold-error">{correctError}</small>}
                </label>
                <label>
                  <span>Wrong (%)</span>
                  <input
                    type="number"
                    inputMode="decimal"
                    step="0.01"
                    min="0"
                    value={wrongValue ?? ''}
                    onChange={event => handleInputChange(variable.wrongKey, event.target.value)}
                    className={wrongError ? 'sentiment-threshold-invalid' : ''}
                    aria-invalid={Boolean(wrongError)}
                    aria-describedby={`${variable.wrongKey}-error`}
                  />
                  {wrongError && <small id={`${variable.wrongKey}-error`} className="sentiment-threshold-error">{wrongError}</small>}
                </label>
              </div>
              {valuesAreValid && <p className="sentiment-neutral-help">{neutralText}</p>}
            </article>;
          })}
        </div>
      </section>
      )}

      {/* Event Contract Strategy Engine Tab */}
      {activeTab === 'event-strategy' && isEventStrategyAdmin && (
        <div className="settings-grid" style={{ marginTop: '24px' }}>
          <div className="settings-page-section" style={{ gridColumn: '1 / -1' }}>
            <h3>📊 Event Contract Strategy Engine</h3>
            <p style={{ color: isLightMode ? '#4a5568' : '#a0aec0' }}>
              Paper-only research and signal generation for Webull Event Contracts. Market snapshots continue on their own cadence; AI is called in bounded batches and never places an order.
            </p>
            {eventStrategyMessage && <div className="settings-message" style={{ marginBottom: 16 }}>{eventStrategyMessage}</div>}
            {!eventStrategyConfig ? (
              <p>Loading engine settings…</p>
            ) : (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12, marginBottom: 18 }}>
                  {[
                    ['worker_status', 'Worker', eventStrategyHealth?.worker_status || eventStrategyConfig.worker_status],
                    ['last_run', 'Last scan', eventStrategyHealth?.last_run ? formatEasternDateTime(eventStrategyHealth.last_run) : '—'],
                    ['heartbeat_at', 'Last heartbeat', eventStrategyHealth?.heartbeat_at ? formatEasternDateTime(eventStrategyHealth.heartbeat_at) : '—'],
                    ['next_expected_scan', 'Next expected scan', eventStrategyHealth?.next_expected_scan ? formatEasternDateTime(eventStrategyHealth.next_expected_scan) : '—'],
                    ['ai_batch_calls_last_hour', 'AI batches (last hour)', `${eventStrategyHealth?.ai_batch_calls_last_hour ?? 0} / ${eventStrategyHealth?.ai_batch_budget_per_hour ?? 12}`],
                    ['ai_evaluations', 'AI evaluation states', (() => {
                      const evals = eventStrategyHealth?.ai_evaluations;
                      if (!evals || typeof evals !== 'object' || Object.keys(evals).length === 0) {
                        return <span style={{ color: isLightMode ? '#718096' : '#94a3b8', fontStyle: 'italic', fontWeight: 400, fontSize: '0.85rem' }}>No evaluations yet</span>;
                      }
                      const badgeMap = {
                        SUCCESS: { bg: isLightMode ? '#dcfce7' : 'rgba(34, 197, 94, 0.18)', border: '#22c55e', text: isLightMode ? '#15803d' : '#4ade80', label: 'Success' },
                        SKIPPED: { bg: isLightMode ? '#fef3c7' : 'rgba(234, 179, 8, 0.18)', border: '#eab308', text: isLightMode ? '#b45309' : '#fde047', label: 'Skipped' },
                        INVALID: { bg: isLightMode ? '#fee2e2' : 'rgba(239, 68, 68, 0.18)', border: '#ef4444', text: isLightMode ? '#b91c1c' : '#f87171', label: 'Invalid' },
                        FAILED: { bg: isLightMode ? '#fee2e2' : 'rgba(239, 68, 68, 0.18)', border: '#ef4444', text: isLightMode ? '#b91c1c' : '#f87171', label: 'Failed' },
                        PENDING: { bg: isLightMode ? '#e0f2fe' : 'rgba(56, 189, 248, 0.18)', border: '#38bdf8', text: isLightMode ? '#0369a1' : '#7dd3fc', label: 'Pending' },
                      };
                      return (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                          {Object.entries(evals).map(([k, count]) => {
                            const conf = badgeMap[k.toUpperCase()] || {
                              bg: isLightMode ? '#f1f5f9' : 'rgba(148, 163, 184, 0.18)',
                              border: '#94a3b8',
                              text: isLightMode ? '#475569' : '#cbd5e1',
                              label: k.charAt(0) + k.slice(1).toLowerCase(),
                            };
                            return (
                              <span
                                key={k}
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 4,
                                  padding: '2px 8px',
                                  borderRadius: 6,
                                  fontSize: '0.8rem',
                                  fontWeight: 600,
                                  background: conf.bg,
                                  border: `1px solid ${conf.border}`,
                                  color: conf.text,
                                }}
                              >
                                <span>{conf.label}:</span>
                                <span>{count}</span>
                              </span>
                            );
                          })}
                        </div>
                      );
                    })()],
                  ].map(([cardKey, label, value]) => (
                    <div key={label} style={{ padding: '12px 14px', borderRadius: 8, background: isLightMode ? '#edf2f7' : 'rgba(255,255,255,0.05)', border: '1px solid rgba(148,163,184,0.2)' }}>
                      <div style={{ fontSize: 12, color: isLightMode ? '#718096' : '#94a3b8' }}>{label}</div>
                      <div style={{ marginTop: 4, fontWeight: 600, wordBreak: 'break-word' }}>
                        {cardKey === 'ai_evaluations' ? value : String(value || '—')}
                      </div>
                    </div>
                  ))}
                </div>

                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 18 }}>
                  <button type="button" className="settings-save-button" disabled={eventStrategyBusy} onClick={saveEventStrategy}>💾 Save settings</button>
                  <button type="button" className="settings-action-button" disabled={eventStrategyBusy || eventStrategyConfig.enabled} onClick={() => eventStrategyAction('start')}>▶ Start</button>
                  <button type="button" className="settings-action-button" disabled={eventStrategyBusy || !eventStrategyConfig.enabled} onClick={() => eventStrategyAction('stop')}>⏸ Stop</button>
                  <button type="button" className="settings-action-button" disabled={eventStrategyBusy} onClick={() => eventStrategyAction('scan')}>🔎 Scan now</button>
                  <button type="button" className="settings-action-button" disabled={eventStrategyBusy} onClick={loadEventStrategyLogs}>📜 View logs</button>
                  <button type="button" className="settings-action-button" disabled={eventStrategyBusy || eventStrategyReportLoading} onClick={() => loadEventStrategyReport()}>📊 View Report</button>
                  <button type="button" className="settings-action-button" disabled={eventStrategyBusy} onClick={openEventStrategyAIModal}>🤖 AI Configuration</button>
                  <button type="button" className="settings-danger-button" disabled={eventStrategyBusy || eventStrategyConfig.kill_switch} onClick={() => eventStrategyAction('kill-switch')}>⛔ Kill switch</button>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
                  <div>
                    <h4>Research scope</h4>
                    <label className="settings-form-group">Symbols (comma separated)
                      <input value={(eventStrategyConfig.symbols || []).join(', ')} onChange={(e) => setEventStrategyConfig((prev) => ({ ...prev, symbols: e.target.value.split(',').map((item) => item.trim().toUpperCase()).filter(Boolean) }))} />
                    </label>
                    <div className="settings-form-group">
                      <label>Durations</label>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                        {EVENT_STRATEGY_DURATIONS.map((duration) => (
                          <label key={duration} style={{ display: 'flex', gap: 5, alignItems: 'center', fontSize: 13 }}>
                            <input type="checkbox" checked={(eventStrategyConfig.durations || []).includes(duration)} onChange={(e) => updateEventStrategyDuration(duration, e.target.checked)} />
                            {duration.replace('_', ' ').toLowerCase()}
                          </label>
                        ))}
                      </div>
                    </div>
                  </div>
                  <div>
                    <h4>Collection and AI frequency</h4>
                    {[
                      ['snapshot_interval_seconds', 'Snapshot collection interval (seconds)'],
                      ['scan_interval_seconds', 'Worker scan interval (seconds)'],
                      ['ai_batch_interval_seconds', 'Minimum interval between AI batches (seconds)'],
                      ['ai_batch_size', 'Contracts per AI batch'],
                      ['max_ai_calls_per_hour', 'Maximum AI batches per hour'],
                      ['ai_cache_ttl_seconds', 'Prediction cache TTL (seconds)'],
                      ['ai_context_refresh_hours', 'Web/search context refresh (hours)'],
                      ['ai_retry_backoff_seconds', 'Initial AI retry backoff (seconds)'],
                    ].map(([key, label]) => (
                      <label key={key} className="settings-form-group" style={{ display: 'block' }}>{label}
                        <input type="number" min="1" value={eventStrategyConfig.signal_config?.[key] ?? ''} onChange={(e) => updateEventStrategySignal(key, e.target.value)} />
                      </label>
                    ))}
                  </div>
                  <div>
                    <h4>AI cooldown by contract duration</h4>
                    {['FIFTEEN_MINUTES', 'HOURLY', 'DAILY', 'WEEKLY', 'MONTHLY', 'ANNUAL', 'ONE_OFF', 'CUSTOM'].map((duration) => (
                      <label key={duration} className="settings-form-group" style={{ display: 'block' }}>{duration.replace('_', ' ').toLowerCase()} cooldown (seconds)
                        <input type="number" min="30" value={eventStrategyConfig.signal_config?.ai_cooldown_by_duration?.[duration] ?? ''} onChange={(e) => setEventStrategyConfig((prev) => ({ ...prev, signal_config: { ...(prev.signal_config || {}), ai_cooldown_by_duration: { ...(prev.signal_config?.ai_cooldown_by_duration || {}), [duration]: e.target.value } } }))} />
                      </label>
                    ))}
                  </div>
                </div>
                <p style={{ color: isLightMode ? '#718096' : '#94a3b8', fontSize: 13, marginTop: 16 }}>
                  A cached prediction is used only while it is fresh and tied to the same contract snapshot. Provider failures are retried with backoff, surfaced in logs/toasts, and remain no-trade decisions.
                </p>
              </>
            )}
          </div>
        </div>
      )}

      {showEventStrategyLogs && createPortal(
        <div role="dialog" aria-modal="true" style={{ position: 'fixed', inset: 0, zIndex: 10000, background: 'rgba(0,0,0,0.72)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div style={{ width: 'min(1000px, 96vw)', maxHeight: '86vh', overflow: 'hidden', borderRadius: 12, background: isLightMode ? '#fff' : '#111827', color: isLightMode ? '#1a202c' : '#e2e8f0', border: '1px solid #4fd1c5', display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 20px', borderBottom: '1px solid rgba(148,163,184,0.25)' }}>
              <h3 style={{ margin: 0 }}>Event Strategy Engine Logs</h3>
              <button type="button" onClick={() => setShowEventStrategyLogs(false)} aria-label="Close logs">✕</button>
            </div>
            <div style={{ overflow: 'auto', padding: 16 }}>
              {eventStrategyLogs.length === 0 ? <p>No engine log entries yet.</p> : eventStrategyLogs.map((entry) => (
                <div key={entry.id} style={{ padding: '10px 0', borderBottom: '1px solid rgba(148,163,184,0.18)' }}>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', fontSize: 12, color: isLightMode ? '#718096' : '#94a3b8' }}>
                    <span>{entry.created_at ? formatEasternDateTime(entry.created_at) : '—'}</span><span>{entry.level}</span><span>{entry.event_type}</span>{entry.symbol && <span>{entry.symbol}</span>}{entry.duration && <span>{entry.duration}</span>}
                  </div>
                  <div style={{ marginTop: 4 }}>{entry.message}</div>
                </div>
              ))}
            </div>
          </div>
        </div>,
        document.body,
      )}

      {showEventStrategyReport && createPortal(
        <div role="dialog" aria-modal="true" style={{ position: 'fixed', inset: 0, zIndex: 10000, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div style={{ width: 'min(1060px, 96vw)', maxHeight: '90vh', overflow: 'hidden', borderRadius: 14, background: isLightMode ? '#fff' : '#0f172a', color: isLightMode ? '#1a202c' : '#e2e8f0', border: '1px solid #38bdf8', display: 'flex', flexDirection: 'column', boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)' }}>
            {/* Modal Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 24px', borderBottom: '1px solid rgba(148,163,184,0.2)' }}>
              <div>
                <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 10, fontSize: '1.25rem' }}>
                  <span>📊 Event Strategy Engine AI Audit Report</span>
                  {eventStrategyReport?.status && (
                    <span style={{
                      fontSize: '0.75rem',
                      fontWeight: 700,
                      padding: '3px 10px',
                      borderRadius: 12,
                      background: eventStrategyReport.status === 'HEALTHY' ? 'rgba(34, 197, 94, 0.18)' : (eventStrategyReport.status === 'DEGRADED' || eventStrategyReport.status === 'ERROR' ? 'rgba(239, 68, 68, 0.18)' : 'rgba(234, 179, 8, 0.18)'),
                      border: `1px solid ${eventStrategyReport.status === 'HEALTHY' ? '#22c55e' : (eventStrategyReport.status === 'DEGRADED' || eventStrategyReport.status === 'ERROR' ? '#ef4444' : '#eab308')}`,
                      color: eventStrategyReport.status === 'HEALTHY' ? '#4ade80' : (eventStrategyReport.status === 'DEGRADED' || eventStrategyReport.status === 'ERROR' ? '#f87171' : '#fde047'),
                    }}>
                      {eventStrategyReport.status}
                    </span>
                  )}
                </h3>
                <div style={{ fontSize: '0.82rem', color: isLightMode ? '#64748b' : '#94a3b8', marginTop: 4 }}>
                  Autonomous 6-hour evaluation of worker performance, operational logs, quote data utility, and calibrated decisions.
                </div>
              </div>
              <button type="button" onClick={() => setShowEventStrategyReport(false)} aria-label="Close report" style={{ background: 'none', border: 'none', color: isLightMode ? '#64748b' : '#94a3b8', fontSize: 20, cursor: 'pointer', padding: 4 }}>✕</button>
            </div>

            {/* Sub-bar with Report Selector & Generate Now */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, padding: '12px 24px', background: isLightMode ? '#f8fafc' : 'rgba(255,255,255,0.02)', borderBottom: '1px solid rgba(148,163,184,0.15)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: '0.85rem', fontWeight: 600, color: isLightMode ? '#475569' : '#cbd5e1' }}>Report History:</span>
                {eventStrategyReportHistory.length > 0 ? (
                  <select
                    value={eventStrategyReport?.id || ''}
                    onChange={(e) => loadEventStrategyReport(e.target.value)}
                    style={{
                      padding: '5px 10px',
                      borderRadius: 6,
                      fontSize: '0.82rem',
                      background: isLightMode ? '#fff' : '#1e293b',
                      color: isLightMode ? '#1e293b' : '#f1f5f9',
                      border: '1px solid rgba(148,163,184,0.3)',
                    }}
                  >
                    {eventStrategyReportHistory.map((rep) => (
                      <option key={rep.id} value={rep.id}>
                        {formatEasternDateTime(rep.created_at)} ({rep.status || 'Report'})
                      </option>
                    ))}
                  </select>
                ) : (
                  <span style={{ fontSize: '0.82rem', color: isLightMode ? '#64748b' : '#94a3b8' }}>No saved reports yet</span>
                )}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <button
                  type="button"
                  className="settings-action-button"
                  disabled={eventStrategyReportGenerating}
                  onClick={generateEventStrategyReportNow}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.85rem', padding: '6px 14px', cursor: eventStrategyReportGenerating ? 'not-allowed' : 'pointer', opacity: eventStrategyReportGenerating ? 0.7 : 1 }}
                >
                  {eventStrategyReportGenerating ? '⚡ Analyzing worker & logs…' : '⚡ Generate Fresh Report Now'}
                </button>
              </div>
            </div>

            {/* Modal Alerts & Progress Banner */}
            {eventStrategyReportGenerating && (
              <div style={{
                margin: '12px 24px 0',
                padding: '12px 16px',
                borderRadius: 8,
                background: 'rgba(56, 189, 248, 0.12)',
                border: '1px solid #38bdf8',
                color: isLightMode ? '#0284c7' : '#38bdf8',
                fontSize: '0.88rem',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
              }}>
                <span style={{ fontSize: '1.1rem' }}>⚡</span>
                <span>Auditing strategy telemetry, market quotes, worker cadence, and error logs... Please wait.</span>
              </div>
            )}
            {eventStrategyReportError && (
              <div style={{
                margin: '12px 24px 0',
                padding: '10px 14px',
                borderRadius: 8,
                background: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid #ef4444',
                color: isLightMode ? '#dc2626' : '#f87171',
                fontSize: '0.88rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 8,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span>⚠️</span>
                  <span>{eventStrategyReportError}</span>
                </div>
                <button
                  type="button"
                  onClick={() => setEventStrategyReportError('')}
                  style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: '1rem', padding: '0 4px' }}
                >
                  ✕
                </button>
              </div>
            )}
            {eventStrategyReportMessage && (
              <div style={{
                margin: '12px 24px 0',
                padding: '10px 14px',
                borderRadius: 8,
                background: 'rgba(34, 197, 94, 0.15)',
                border: '1px solid #22c55e',
                color: isLightMode ? '#16a34a' : '#4ade80',
                fontSize: '0.88rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 8,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span>✓</span>
                  <span>{eventStrategyReportMessage}</span>
                </div>
                <button
                  type="button"
                  onClick={() => setEventStrategyReportMessage('')}
                  style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: '1rem', padding: '0 4px' }}
                >
                  ✕
                </button>
              </div>
            )}

            {/* Scrollable Report Body */}
            <div style={{ overflow: 'auto', padding: '20px 24px', flex: 1 }}>
              {eventStrategyReportLoading ? (
                <div style={{ padding: '40px 0', textAlign: 'center', color: isLightMode ? '#64748b' : '#94a3b8' }}>
                  Loading strategy engine report…
                </div>
              ) : !eventStrategyReport ? (
                <div style={{ padding: '40px 0', textAlign: 'center' }}>
                  <p style={{ fontSize: '1.05rem', color: isLightMode ? '#475569' : '#cbd5e1' }}>No audit report has been generated yet.</p>
                  <p style={{ fontSize: '0.88rem', color: isLightMode ? '#64748b' : '#94a3b8', maxWidth: 500, margin: '0 auto 20px' }}>
                    The report runs automatically every 6 hours while the engine is active. You can generate an immediate evaluation right now to inspect current worker operations and logs.
                  </p>
                  <button
                    type="button"
                    className="settings-save-button"
                    disabled={eventStrategyReportGenerating}
                    onClick={generateEventStrategyReportNow}
                    style={{ cursor: eventStrategyReportGenerating ? 'not-allowed' : 'pointer', opacity: eventStrategyReportGenerating ? 0.7 : 1 }}
                  >
                    {eventStrategyReportGenerating ? '⚡ Analyzing worker & logs…' : '⚡ Generate Initial Report Now'}
                  </button>
                </div>
              ) : (
                <div>
                  {/* Top metrics ribbon */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 12, marginBottom: 20 }}>
                    <div style={{ padding: '10px 14px', borderRadius: 8, background: isLightMode ? '#f1f5f9' : 'rgba(255,255,255,0.04)', border: '1px solid rgba(148,163,184,0.18)' }}>
                      <div style={{ fontSize: 11, color: isLightMode ? '#64748b' : '#94a3b8' }}>Report Created</div>
                      <div style={{ fontWeight: 600, fontSize: '0.88rem', marginTop: 3 }}>{formatEasternDateTime(eventStrategyReport.created_at)}</div>
                    </div>
                    <div style={{ padding: '10px 14px', borderRadius: 8, background: isLightMode ? '#f1f5f9' : 'rgba(255,255,255,0.04)', border: '1px solid rgba(148,163,184,0.18)' }}>
                      <div style={{ fontSize: 11, color: isLightMode ? '#64748b' : '#94a3b8' }}>Audit Window</div>
                      <div style={{ fontWeight: 600, fontSize: '0.88rem', marginTop: 3 }}>{getAuditWindowHours(eventStrategyReport, settings.event_strategy_audit_hours)}</div>
                    </div>
                    <div style={{ padding: '10px 14px', borderRadius: 8, background: isLightMode ? '#f1f5f9' : 'rgba(255,255,255,0.04)', border: '1px solid rgba(148,163,184,0.18)' }}>
                      <div style={{ fontSize: 11, color: isLightMode ? '#64748b' : '#94a3b8' }}>Scans Analyzed</div>
                      <div style={{ fontWeight: 600, fontSize: '0.88rem', marginTop: 3 }}>{eventStrategyReport.metrics?.scans_count ?? 0} scans ({eventStrategyReport.metrics?.scanned_contracts ?? 0} contracts)</div>
                    </div>
                    <div style={{ padding: '10px 14px', borderRadius: 8, background: isLightMode ? '#f1f5f9' : 'rgba(255,255,255,0.04)', border: '1px solid rgba(148,163,184,0.18)' }}>
                      <div style={{ fontSize: 11, color: isLightMode ? '#64748b' : '#94a3b8' }}>Decisions &amp; Holds</div>
                      <div style={{ fontWeight: 600, fontSize: '0.88rem', marginTop: 3 }}>{eventStrategyReport.metrics?.eligible_count ?? 0} qualified / {eventStrategyReport.metrics?.no_trade_count ?? 0} hold</div>
                    </div>
                    <div style={{ padding: '10px 14px', borderRadius: 8, background: isLightMode ? '#f1f5f9' : 'rgba(255,255,255,0.04)', border: '1px solid rgba(148,163,184,0.18)' }}>
                      <div style={{ fontSize: 11, color: isLightMode ? '#64748b' : '#94a3b8' }}>Auditor Model</div>
                      <div style={{ fontWeight: 600, fontSize: '0.88rem', marginTop: 3 }}>{eventStrategyReport.model || eventStrategyReport.provider || 'AI Evaluator'}</div>
                    </div>
                  </div>

                  {/* Headline Callout with dynamic alert coloring */}
                  {eventStrategyReport.headline && (() => {
                    const style = getHeadlineCalloutStyle(eventStrategyReport.status, isLightMode);
                    return (
                      <div style={{
                        padding: '12px 16px',
                        borderRadius: 8,
                        marginBottom: 20,
                        background: style.bg,
                        border: style.border,
                        fontWeight: 600,
                        fontSize: '0.95rem',
                        color: style.color,
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                      }}>
                        <span>{style.icon}</span>
                        <span>{eventStrategyReport.headline}</span>
                      </div>
                    );
                  })()}

                  {/* Markdown Report Content - defensively parsed so raw JSON never displays */}
                  <div className="event-strategy-report-markdown" style={{ lineHeight: 1.65, fontSize: '0.92rem' }}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {formatReportMarkdown(eventStrategyReport.content_markdown, eventStrategyReport.summary)}
                    </ReactMarkdown>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>,
        document.body,
      )}

      {/* Event Strategy AI Configuration Modal */}
      {showEventStrategyAIModal && createPortal(
        <div role="dialog" aria-modal="true" style={{ position: 'fixed', inset: 0, zIndex: 10000, background: 'rgba(0,0,0,0.78)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20, backdropFilter: 'blur(4px)' }}>
          <div style={{ width: 'min(1060px, 96vw)', maxHeight: '90vh', overflow: 'hidden', borderRadius: 14, background: isLightMode ? '#ffffff' : '#0f172a', color: isLightMode ? '#1a202c' : '#e2e8f0', border: '1px solid #38bdf8', display: 'flex', flexDirection: 'column', boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.7)' }}>
            {/* Modal Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 24px', borderBottom: '1px solid rgba(148,163,184,0.2)', background: isLightMode ? '#f8fafc' : 'rgba(255,255,255,0.02)' }}>
              <div>
                <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 10, fontSize: '1.25rem', color: isLightMode ? '#0f172a' : '#f8fafc' }}>
                  <span>🤖</span> Event Contract Strategy Engine AI Configuration
                </h3>
                <div style={{ fontSize: '0.82rem', color: isLightMode ? '#64748b' : '#94a3b8', marginTop: 4 }}>
                  Dedicated 3-tier AI integration cascade, isolated API credentials, and autonomous operational audit controls.
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowEventStrategyAIModal(false)}
                aria-label="Close AI configuration"
                style={{ background: 'none', border: 'none', color: isLightMode ? '#64748b' : '#94a3b8', fontSize: 22, cursor: 'pointer', padding: '4px 8px', borderRadius: 6 }}
              >
                ✕
              </button>
            </div>

            {/* Modal Body */}
            <div style={{ overflowY: 'auto', padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 22 }}>
              {eventStrategyAILoading ? (
                <div style={{ textAlign: 'center', padding: '40px 0', color: isLightMode ? '#64748b' : '#94a3b8' }}>
                  Loading AI configuration...
                </div>
              ) : (
                <>
                  {/* TOP SECTION: Autonomous Operational Audit Controls */}
                  <div style={{
                    padding: 18,
                    borderRadius: 10,
                    background: isLightMode ? '#f8fafc' : 'rgba(15, 23, 42, 0.65)',
                    border: '1px solid rgba(56, 189, 248, 0.25)',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontSize: '1.2rem' }}>📊</span>
                        <h4 style={{ margin: 0, fontSize: '1rem', color: isLightMode ? '#0f172a' : '#38bdf8' }}>
                          Autonomous Operational Audit Controls
                        </h4>
                      </div>
                      <span style={{
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        padding: '2px 8px',
                        borderRadius: 12,
                        background: 'rgba(56, 189, 248, 0.15)',
                        border: '1px solid #38bdf8',
                        color: '#38bdf8'
                      }}>
                        Autonomous Auditing
                      </span>
                    </div>
                    <p style={{ fontSize: '0.82rem', color: isLightMode ? '#475569' : '#94a3b8', margin: '0 0 16px 0', lineHeight: 1.45 }}>
                      Governs the autonomous evaluation cadence and system prompt used by the AI auditor to inspect worker cadence, quote data utility, decision calibration, error logs, and operational tuning recommendations.
                    </p>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16, alignItems: 'start' }}>
                      <div style={{ maxWidth: 280 }}>
                        <label style={{ display: 'block', marginBottom: 8, fontSize: '12px', fontWeight: 600, color: isLightMode ? '#334155' : '#e2e8f0' }}>
                          Audit Interval (Hours)
                        </label>
                        <input
                          type="number"
                          min="1"
                          max="72"
                          step="1"
                          value={eventStrategyAIConfig.audit_hours || 6}
                          onChange={(e) => setEventStrategyAIConfig((prev) => ({
                            ...prev,
                            audit_hours: parseInt(e.target.value) || 6,
                          }))}
                          style={{
                            width: '100%',
                            padding: '8px 12px',
                            borderRadius: 6,
                            background: isLightMode ? '#ffffff' : '#1e293b',
                            color: isLightMode ? '#0f172a' : '#ffffff',
                            border: '1px solid rgba(148,163,184,0.3)',
                            boxSizing: 'border-box',
                            fontSize: '13px'
                          }}
                        />
                        <span style={{ fontSize: '11px', color: isLightMode ? '#64748b' : '#94a3b8', marginTop: 6, display: 'block', lineHeight: 1.4 }}>
                          Cadence for autonomous evaluations (Default: 6 hours, e.g. 4, 6, 8, 12, 24).
                        </span>
                      </div>

                      <div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                          <label style={{ fontSize: '12px', fontWeight: 600, color: isLightMode ? '#334155' : '#e2e8f0' }}>
                            Auditor System Prompt
                          </label>
                          <button
                            type="button"
                            onClick={() => setEventStrategyAIConfig((prev) => ({
                              ...prev,
                              audit_prompt: DEFAULT_EVENT_AUDIT_PROMPT,
                            }))}
                            style={{
                              background: 'none',
                              border: 'none',
                              color: '#38bdf8',
                              fontSize: '11px',
                              cursor: 'pointer',
                              padding: 0,
                              textDecoration: 'underline'
                            }}
                          >
                            ↺ Reset to Default
                          </button>
                        </div>
                        <textarea
                          value={eventStrategyAIConfig.audit_prompt || ''}
                          onChange={(e) => {
                            setEventStrategyAIConfig((prev) => ({
                              ...prev,
                              audit_prompt: e.target.value,
                            }));
                            autoResizeTextarea(e.target);
                          }}
                          onInput={(e) => autoResizeTextarea(e.target)}
                          placeholder="e.g. You are a principal quantitative trading auditor and AI reliability engineer..."
                          style={{
                            width: '100%',
                            padding: '8px 12px',
                            borderRadius: 6,
                            background: isLightMode ? '#ffffff' : '#1e293b',
                            color: isLightMode ? '#0f172a' : '#ffffff',
                            border: '1px solid rgba(148,163,184,0.3)',
                            boxSizing: 'border-box',
                            resize: 'vertical',
                            fontSize: '12px',
                            minHeight: '84px',
                            lineHeight: 1.45
                          }}
                        />
                        <span style={{ fontSize: '11px', color: isLightMode ? '#64748b' : '#94a3b8', marginTop: 4, display: 'block' }}>
                          Guides the AI model's analytical persona, issue severity classification, telemetry inspection, and actionable tuning recommendations.
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* BOTTOM SECTION: Segregated 3-Tier AI Integration */}
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8, flexWrap: 'wrap', gap: 8 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontSize: '1.2rem' }}>🧠</span>
                        <h4 style={{ margin: 0, fontSize: '1rem', color: isLightMode ? '#0f172a' : '#f8fafc' }}>
                          Segregated 3-Tier AI Integration
                        </h4>
                      </div>
                      <span style={{
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        padding: '2px 8px',
                        borderRadius: 12,
                        background: 'rgba(34, 197, 94, 0.15)',
                        border: '1px solid #22c55e',
                        color: '#4ade80'
                      }}>
                        Dedicated Engine Cascade
                      </span>
                    </div>

                    <div style={{
                      padding: '10px 14px',
                      borderRadius: 8,
                      background: isLightMode ? '#eff6ff' : 'rgba(59, 130, 246, 0.1)',
                      border: '1px solid rgba(59, 130, 246, 0.25)',
                      fontSize: '0.8rem',
                      color: isLightMode ? '#1e40af' : '#93c5fd',
                      marginBottom: 16,
                      lineHeight: 1.45
                    }}>
                      🛡️ <strong>Complete Isolation:</strong> This 3-tier cascade and its dedicated API keys are used exclusively by the Event Contract Strategy Engine (market probability estimations, batched scanning, and autonomous audits). Global Copilot, Portfolio Review, and Watchlist Sentiment remain completely separate and unaffected.
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(310px, 1fr))', gap: 16 }}>
                      {/* Tier Renderer Helper */}
                      {[
                        { key: 'primary', label: 'Primary AI Integration', badge: 'Tier 1' },
                        { key: 'secondary', label: 'Secondary AI Integration', badge: 'Tier 2 (Failover)' },
                        { key: 'tertiary', label: 'Tertiary AI Integration', badge: 'Tier 3 (Failover)' },
                      ].map(({ key: tierKey, label: tierLabel, badge: tierBadge }) => {
                        const tier = eventStrategyAIConfig?.ai_config?.[tierKey] || {};
                        const provider = tier.provider || (tierKey === 'primary' ? 'gemini' : 'ollama');
                        const model = tier.model || '';
                        const reasoningLevel = tier.reasoning_level || 'medium';
                        const isOllama = provider === 'ollama';
                        const isTesting = Boolean(eventStrategyAITesting[tierKey]);
                        const testResult = eventStrategyAITestResults[tierKey];
                        const showKey = Boolean(showEventStrategyApiKey[tierKey]);

                        return (
                          <div
                            key={tierKey}
                            style={{
                              padding: 16,
                              borderRadius: 10,
                              background: isLightMode ? '#f8fafc' : 'rgba(15, 23, 42, 0.65)',
                              border: '1px solid rgba(148, 163, 184, 0.2)',
                              display: 'flex',
                              flexDirection: 'column',
                              gap: 12,
                            }}
                          >
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <h5 style={{ margin: 0, fontSize: '0.92rem', color: isLightMode ? '#1e293b' : '#f1f5f9', fontWeight: 600 }}>
                                {tierLabel}
                              </h5>
                              <span style={{
                                fontSize: '0.7rem',
                                fontWeight: 700,
                                padding: '1px 6px',
                                borderRadius: 10,
                                background: isLightMode ? '#e2e8f0' : 'rgba(255,255,255,0.08)',
                                color: isLightMode ? '#475569' : '#94a3b8',
                              }}>
                                {tierBadge}
                              </span>
                            </div>

                            {/* Provider Select */}
                            <div>
                              <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: isLightMode ? '#475569' : '#94a3b8', marginBottom: 4 }}>
                                AI Provider
                              </label>
                              <select
                                value={provider}
                                onChange={(e) => updateEventStrategyAITierField(tierKey, 'provider', e.target.value)}
                                style={{
                                  width: '100%',
                                  padding: '7px 10px',
                                  borderRadius: 6,
                                  background: isLightMode ? '#ffffff' : '#1e293b',
                                  color: isLightMode ? '#0f172a' : '#ffffff',
                                  border: '1px solid rgba(148,163,184,0.3)',
                                  fontSize: '12px'
                                }}
                              >
                                <option value="gemini">Gemini</option>
                                <option value="openai">OpenAI</option>
                                <option value="zai">Z.AI</option>
                                <option value="perplexity">Perplexity</option>
                                <option value="inception">Inception Labs</option>
                                {isEventStrategyAdmin && <option value="ollama">Ollama (local)</option>}
                              </select>
                            </div>

                            {/* Model Select */}
                            <div>
                              <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: isLightMode ? '#475569' : '#94a3b8', marginBottom: 4 }}>
                                Model
                              </label>
                              <select
                                value={model}
                                onChange={(e) => updateEventStrategyAITierField(tierKey, 'model', e.target.value)}
                                style={{
                                  width: '100%',
                                  padding: '7px 10px',
                                  borderRadius: 6,
                                  background: isLightMode ? '#ffffff' : '#1e293b',
                                  color: isLightMode ? '#0f172a' : '#ffffff',
                                  border: '1px solid rgba(148,163,184,0.3)',
                                  fontSize: '12px'
                                }}
                              >
                                {(modelOptions[provider] || []).length > 0 ? (
                                  (modelOptions[provider] || []).map((opt) => (
                                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                                  ))
                                ) : (
                                  <>
                                    {provider === 'gemini' && <option value="gemini-3.8-flash">Gemini 3.8 Flash</option>}
                                    {provider === 'gemini' && <option value="gemini-3.7-flash">Gemini 3.7 Flash</option>}
                                    {provider === 'ollama' && <option value="gpt-oss:120b-cloud">gpt-oss:120b-cloud</option>}
                                    {provider === 'ollama' && <option value="qwen2.5:14b">qwen2.5:14b</option>}
                                    {provider === 'openai' && <option value="gpt-5.4-mini">5.4 mini</option>}
                                    {provider === 'openai' && <option value="gpt-5.4">5.4</option>}
                                    {provider === 'zai' && <option value="glm-4.5-flash">GLM-4.5 Flash</option>}
                                    {provider === 'perplexity' && <option value="sonar">Sonar</option>}
                                    {provider === 'inception' && <option value="mercury-2">Mercury 2</option>}
                                  </>
                                )}
                              </select>
                            </div>

                            {/* Reasoning Level (Gemini & OpenAI) */}
                            {['gemini', 'openai'].includes(provider) && (
                              <div>
                                <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: isLightMode ? '#475569' : '#94a3b8', marginBottom: 4 }}>
                                  Reasoning Effort
                                </label>
                                <select
                                  value={reasoningLevel}
                                  onChange={(e) => updateEventStrategyAITierField(tierKey, 'reasoning_level', e.target.value)}
                                  style={{
                                    width: '100%',
                                    padding: '7px 10px',
                                    borderRadius: 6,
                                    background: isLightMode ? '#ffffff' : '#1e293b',
                                    color: isLightMode ? '#0f172a' : '#ffffff',
                                    border: '1px solid rgba(148,163,184,0.3)',
                                    fontSize: '12px'
                                  }}
                                >
                                  <option value="light">Light</option>
                                  <option value="medium">Medium</option>
                                  <option value="high">High</option>
                                  <option value="extra high">Extra High</option>
                                </select>
                              </div>
                            )}

                            {/* API Key Input */}
                            {!isOllama ? (
                              <div>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                                  <label style={{ fontSize: '11px', fontWeight: 600, color: isLightMode ? '#475569' : '#94a3b8' }}>
                                    Dedicated API Key
                                  </label>
                                  {tier.has_key && (
                                    <span style={{ fontSize: '10px', color: '#4ade80', fontWeight: 600 }}>
                                      ✓ Key Configured
                                    </span>
                                  )}
                                </div>
                                <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                                  <input
                                    type={showKey ? 'text' : 'password'}
                                    value={tier.api_key || ''}
                                    onChange={(e) => updateEventStrategyAITierField(tierKey, 'api_key', e.target.value)}
                                    placeholder={tier.has_key ? '•••••••••••• (Saved)' : `Enter dedicated ${provider.toUpperCase()} API key`}
                                    style={{
                                      width: '100%',
                                      padding: '7px 32px 7px 10px',
                                      borderRadius: 6,
                                      background: isLightMode ? '#ffffff' : '#1e293b',
                                      color: isLightMode ? '#0f172a' : '#ffffff',
                                      border: '1px solid rgba(148,163,184,0.3)',
                                      fontSize: '12px',
                                      boxSizing: 'border-box'
                                    }}
                                  />
                                  <button
                                    type="button"
                                    onClick={() => setShowEventStrategyApiKey((prev) => ({ ...prev, [tierKey]: !prev[tierKey] }))}
                                    style={{
                                      position: 'absolute',
                                      right: 8,
                                      background: 'none',
                                      border: 'none',
                                      color: isLightMode ? '#64748b' : '#94a3b8',
                                      cursor: 'pointer',
                                      padding: 0,
                                      fontSize: '14px'
                                    }}
                                  >
                                    {showKey ? '🙈' : '👁️'}
                                  </button>
                                </div>
                                <span style={{ fontSize: '10px', color: isLightMode ? '#64748b' : '#94a3b8', marginTop: 4, display: 'block' }}>
                                  Dedicated to this tier. Blank falls back to your global project key.
                                </span>
                              </div>
                            ) : (
                              <div style={{
                                padding: '8px 10px',
                                borderRadius: 6,
                                background: isLightMode ? '#f1f5f9' : 'rgba(255,255,255,0.04)',
                                border: '1px dashed rgba(148,163,184,0.25)',
                                fontSize: '11px',
                                color: isLightMode ? '#64748b' : '#94a3b8',
                                lineHeight: 1.4
                              }}>
                                🖥️ Ollama runs locally on this system. Models execute directly without requiring an API key.
                              </div>
                            )}

                            {/* Test API Connection button */}
                            <div style={{ marginTop: 'auto', paddingTop: 8 }}>
                              <button
                                type="button"
                                onClick={() => testEventStrategyAITier(tierKey)}
                                disabled={isTesting || !provider}
                                style={{
                                  width: '100%',
                                  padding: '6px 12px',
                                  fontSize: '11px',
                                  fontWeight: 600,
                                  borderRadius: 6,
                                  border: '1px solid rgba(56, 189, 248, 0.4)',
                                  background: isTesting ? 'rgba(56, 189, 248, 0.1)' : 'rgba(56, 189, 248, 0.15)',
                                  color: '#38bdf8',
                                  cursor: isTesting ? 'not-allowed' : 'pointer',
                                  transition: 'all 0.15s ease'
                                }}
                              >
                                {isTesting ? 'Testing Connection...' : '⚡ Test API Connection'}
                              </button>
                              {testResult && (
                                <div style={{
                                  marginTop: 6,
                                  padding: '5px 8px',
                                  borderRadius: 5,
                                  fontSize: '11px',
                                  lineHeight: 1.3,
                                  background: testResult.success ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                                  border: `1px solid ${testResult.success ? '#22c55e' : '#ef4444'}`,
                                  color: testResult.success ? '#4ade80' : '#f87171',
                                }}>
                                  {testResult.message}
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </>
              )}
            </div>

            {/* Modal Footer */}
            <div style={{
              display: 'flex',
              justifyContent: 'flex-end',
              alignItems: 'center',
              gap: 12,
              padding: '14px 24px',
              borderTop: '1px solid rgba(148,163,184,0.2)',
              background: isLightMode ? '#f8fafc' : 'rgba(255,255,255,0.02)'
            }}>
              <button
                type="button"
                onClick={() => setShowEventStrategyAIModal(false)}
                style={{
                  padding: '8px 16px',
                  borderRadius: 6,
                  border: '1px solid rgba(148,163,184,0.3)',
                  background: 'transparent',
                  color: isLightMode ? '#475569' : '#cbd5e1',
                  fontSize: '13px',
                  cursor: 'pointer'
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                className="settings-save-button"
                disabled={eventStrategyAISaving}
                onClick={saveEventStrategyAIConfig}
                style={{ padding: '8px 20px', fontSize: '13px', fontWeight: 600 }}
              >
                {eventStrategyAISaving ? 'Saving...' : '💾 Save AI Configuration'}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {/* Notifications & System Tab */}
      {activeTab === 'system' && (
        <>
          {/* Notifications & Tax Configuration - Side by Side */}
          <div className="settings-grid" style={{ marginTop: '24px' }}>
        {/* Notifications */}
        <div className="settings-page-section">
          <h3>🔔 Notifications & Alerts</h3>

          <div style={{ marginBottom: 20, padding: '16px', background: 'rgba(255, 255, 255, 0.03)', borderRadius: 8, border: '1px solid rgba(255, 255, 255, 0.08)' }}>
            <div className="settings-form-group" style={{ marginBottom: 0 }}>
              <label style={{ display: 'block', marginBottom: 8, color: '#fff', fontWeight: 600 }}>
                Browser Toast Notifications
              </label>
              <div className="settings-checkbox-group">
                <input
                  type="checkbox"
                  checked={settings.toast_notifications_enabled !== false}
                  onChange={(e) => {
                    handleInputChange('toast_notifications_enabled', e.target.checked);
                    localStorage.setItem('crypto_toast_notifications_enabled', e.target.checked ? 'true' : 'false');
                    window.dispatchEvent(new CustomEvent('app:toast-setting-changed', { detail: { enabled: e.target.checked } }));
                  }}
                  className="settings-checkbox"
                />
                <span style={{ fontWeight: 500 }}>
                  Enable instant toast popups in the bottom-right corner
                </span>
              </div>
              <div className="settings-form-help" style={{ marginTop: 6, color: '#94a3b8', fontSize: '0.82rem' }}>
                Shows modern popup notifications across all pages for completed/filled trades, canceled orders, AI sentiment alerts, and price threshold crossings.
              </div>
            </div>
          </div>

          <h4 style={{ color: '#e2e8f0', marginBottom: 12, fontSize: '0.95rem' }}>📱 Telegram Integration</h4>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <div>
              <label style={{ display: 'block', marginBottom: 8, color: '#fff' }}>
                Telegram Bot Token
              </label>
              <input
                type="password"
                value={settings.telegram_token || ''}
                onChange={(e) => handleInputChange('telegram_token', e.target.value)}
                placeholder="Enter Telegram Bot Token"
                style={{
                  width: 'calc(100% - 24px)',
                  padding: '8px 12px',
                  borderRadius: 6,
                  background: '#1a1f23',
                  color: '#fff',
                  border: '1px solid #444',
                  boxSizing: 'border-box'
                }}
              />
            </div>

            <div>
              <label style={{ display: 'block', marginBottom: 8, color: '#fff' }}>
                Telegram Chat ID
              </label>
              <input
                type="password"
                value={settings.telegram_chat_id || ''}
                onChange={(e) => handleInputChange('telegram_chat_id', e.target.value)}
                placeholder="Enter Telegram Chat ID"
                style={{
                  width: 'calc(100% - 24px)',
                  padding: '8px 12px',
                  borderRadius: 6,
                  background: '#1a1f23',
                  color: '#fff',
                  border: '1px solid #444',
                  boxSizing: 'border-box'
                }}
              />
            </div>
          </div>

        </div>

        {/* Tax Configuration */}
        <div className="settings-page-section">
          <h3>💰 Tax Configuration</h3>
          <p>Configure tax calculation methods for your portfolio report.</p>

          <div style={{ marginTop: 16 }}>
            <label style={{ display: 'block', marginBottom: 8, color: '#fff' }}>
              Cost Basis Method
            </label>
            <select
              value={settings.tax_cost_basis_method || 'fifo'}
              onChange={(e) => handleInputChange('tax_cost_basis_method', e.target.value)}
              style={{
                width: '100%',
                padding: '12px 12px',
                borderRadius: 6,
                background: '#1a1f23',
                color: '#fff',
                border: '1px solid #444',
                boxSizing: 'border-box',
                fontSize: '16px'
              }}
            >
              <option value="fifo">FIFO (First In, First Out)</option>
              <option value="lifo">LIFO (Last In, First Out)</option>
            </select>
            <p className="settings-form-help">
              Used to calculate realized/unrealized gains. FIFO is standard for most jurisdictions.
            </p>
          </div>
        </div>
      </div>

      {/* Portfolio Table Settings */}
      <div className="settings-page-section" style={{ marginTop: '24px' }}>
        <h3>Portfolio Table & Execution Safety Settings</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 16 }}>
          <div>
            <label style={{ display: 'block', marginBottom: 8, color: '#fff' }}>
              Volatility Hours
            </label>
            <input
              type="number"
              min="1"
              max="999"
              step="1"
              value={settings.volatility_hours ?? 24}
              onChange={(e) => handleInputChange('volatility_hours', e.target.value)}
              style={{
                width: '100%',
                padding: '12px',
                borderRadius: 6,
                background: '#1a1f23',
                color: '#fff',
                border: '1px solid #444',
                boxSizing: 'border-box',
                fontSize: '16px'
              }}
            />
            <p className="settings-form-help">
              Volatility drop/surge comparison lookback window in hours.
            </p>
          </div>

          <div>
            <label style={{ display: 'block', marginBottom: 8, color: '#fff' }}>
              Automated Trigger Confirmation Window (Minutes)
            </label>
            <input
              type="number"
              min="1"
              max="1440"
              step="1"
              value={settings.automated_trigger_confirmation_minutes ?? 15}
              onChange={(e) => handleInputChange('automated_trigger_confirmation_minutes', e.target.value)}
              style={{
                width: '100%',
                padding: '12px',
                borderRadius: 6,
                background: '#1a1f23',
                color: '#fff',
                border: '1px solid #444',
                boxSizing: 'border-box',
                fontSize: '16px'
              }}
            />
            <p className="settings-form-help">
              Default: 15 minutes. Auto-Buy and Auto-Sell must remain beyond their configured volatility threshold for this entire window before an order is placed. If the price recovers across the threshold, the timer resets.
            </p>
          </div>

          <div>
            <label style={{ display: 'block', marginBottom: 8, color: '#fff' }}>
              Max Allowed Slippage (%)
            </label>
            <input
              type="number"
              min="0.1"
              max="15.0"
              step="0.1"
              value={settings.max_slippage_pct ?? 2.0}
              onChange={(e) => handleInputChange('max_slippage_pct', parseFloat(e.target.value) || 2.0)}
              style={{
                width: '100%',
                padding: '12px',
                borderRadius: 6,
                background: '#1a1f23',
                color: '#fff',
                border: '1px solid #444',
                boxSizing: 'border-box',
                fontSize: '16px'
              }}
            />
            <p className="settings-form-help">
              Pre-flight order book depth simulation aborts Auto-Sell/Auto-Buy if estimated slippage exceeds this %; orders execute with IOC limit price floors to guarantee protection.
            </p>
          </div>
        </div>
      </div>

      {/* Delete Account Section */}
      <div className="settings-page-section" style={{ borderTop: '1px solid #f56565', marginTop: '32px', paddingTop: '24px' }}>
        <h3 style={{ color: '#f56565' }}>⚠️ Delete Account</h3>
        <p style={{ color: '#e0e0e0', marginBottom: '16px' }}>
          Permanently delete your account and all associated data. This action cannot be undone.
        </p>
        <button
          onClick={() => setShowDeleteModal(true)}
          style={{
            padding: '12px 24px',
            backgroundColor: '#dc3545',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            fontSize: '16px',
            fontWeight: 600,
            cursor: 'pointer'
          }}
        >
          Delete My Account
        </button>
      </div>
        </>
      )}

      {/* Delete Account Confirmation Modal */}
      {showDeleteModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.7)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999
        }}>
          <div style={{
            backgroundColor: '#1a1a2e',
            borderRadius: '12px',
            maxWidth: '500px',
            width: '90%',
            padding: '0',
            border: '1px solid #f56565'
          }}>
            {/* Modal Header */}
            <div style={{
              padding: '20px 24px',
              borderBottom: '1px solid #2d3748'
            }}>
              <h2 style={{ margin: 0, color: '#f56565', fontSize: '1.3rem' }}>
                ⚠️ Delete Account
              </h2>
            </div>

            {/* Modal Body */}
            <div style={{ padding: '24px' }}>
              <p style={{ color: '#e0e0e0', marginBottom: '16px', lineHeight: '1.6' }}>
                <strong>This will permanently delete your account and all associated data, including:</strong>
              </p>
              <ul style={{ color: '#e0e0e0', paddingLeft: '20px', marginBottom: '16px' }}>
                <li>Your profile and settings</li>
                <li>API credentials and 2FA configuration</li>
                <li>Trading history and order records</li>
                <li>Tax report data</li>
                <li>AI conversation history</li>
              </ul>
              <p style={{ color: '#f56565', fontWeight: 600, marginBottom: '16px' }}>
                This action CANNOT be undone!
              </p>

              {deleteError && (
                <div style={{
                  backgroundColor: '#5c1e1e',
                  color: '#f5a3a3',
                  padding: '12px',
                  borderRadius: '6px',
                  marginBottom: '16px'
                }}>
                  {deleteError}
                </div>
              )}

              <div style={{
                backgroundColor: '#1e3a5f',
                padding: '16px',
                borderRadius: '8px',
                marginBottom: '16px'
              }}>
                <p style={{ color: '#4da6ff', margin: 0, fontSize: '14px' }}>
                  💡 <strong>Tip:</strong> Before deleting, you may want to export your tax report data for your records.
                </p>
              </div>
            </div>

            {/* Modal Footer */}
            <div style={{
              padding: '16px 24px',
              borderTop: '1px solid #2d3748',
              display: 'flex',
              justifyContent: 'space-between',
              gap: '12px',
              flexWrap: 'wrap'
            }}>
              <button
                onClick={handleExportTaxData}
                style={{
                  padding: '10px 20px',
                  backgroundColor: '#4da6ff',
                  color: 'white',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontWeight: 500
                }}
              >
                📥 Export Tax Report
              </button>
              <div style={{ display: 'flex', gap: '12px' }}>
                <button
                  onClick={() => { setShowDeleteModal(false); setDeleteError(''); }}
                  style={{
                    padding: '10px 20px',
                    backgroundColor: 'transparent',
                    color: '#e0e0e0',
                    border: '1px solid #555',
                    borderRadius: '6px',
                    cursor: 'pointer'
                  }}
                >
                  No, Cancel
                </button>
                <button
                  onClick={handleDeleteAccount}
                  disabled={deleteLoading}
                  style={{
                    padding: '10px 20px',
                    backgroundColor: '#dc3545',
                    color: 'white',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: deleteLoading ? 'not-allowed' : 'pointer',
                    opacity: deleteLoading ? 0.7 : 1,
                    fontWeight: 600
                  }}
                >
                  {deleteLoading ? 'Deleting...' : 'Yes, Delete'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
