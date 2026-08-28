import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import axios from 'axios';
import { useAuth } from '../components/AuthContext';
import { FaToggleOn, FaToggleOff, FaInfoCircle } from 'react-icons/fa';
import { useSearchParams } from 'react-router-dom';
import OnboardingModal from '../components/OnboardingModal';

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

export default function Settings({ isLightMode }) {
  // Pull user so we can gate admin-only sections without runtime errors
  const { user, isLoggingOut } = useAuth();
  const [modelOptions, setModelOptions] = useState({
    openai: [],
    zai: [],
    perplexity: [],
    gemini: [],
    inception: [],
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
    copilot_chat_post: ''
  });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState(''); // 'success' or 'error'
  const [testingBinance, setTestingBinance] = useState(false);
  const [testingWebull, setTestingWebull] = useState(false);
  const [loadingWebullAccounts, setLoadingWebullAccounts] = useState(false);
  const [webullAccounts, setWebullAccounts] = useState([]);
  const [webullAccountsMessage, setWebullAccountsMessage] = useState('');
  const [accountAliases, setAccountAliases] = useState({});
  const [savingAliases, setSavingAliases] = useState(false);
  const [aliasMessage, setAliasMessage] = useState('');
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

  // 2FA State
  const [twoFactorEnabled, setTwoFactorEnabled] = useState(false);
  const [showQRCode, setShowQRCode] = useState(false);
  const [qrCodeData, setQRCodeData] = useState(null);
  const [verificationCode, setVerificationCode] = useState('');
  const [disableCode, setDisableCode] = useState('');
  const [twoFactorLoading, setTwoFactorLoading] = useState(false);
  const [twoFactorMessage, setTwoFactorMessage] = useState('');

  // Onboarding Modal State
  const [showOnboardingModal, setShowOnboardingModal] = useState(false);
  const [searchParams] = useSearchParams();

  // Delete Account State
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  useEffect(() => {
    // Show onboarding for new users (redirected from signup with ?new_user=true)
    if (searchParams.get('new_user') === 'true') {
      setShowOnboardingModal(true);
    }
  }, [searchParams]);

  // Auto-resize textarea function
  const autoResizeTextarea = (textarea) => {
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = textarea.scrollHeight + 'px';
    }
  };

  useEffect(() => {
    fetchSettings();
  }, []);

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
      let currentModelOptions = { openai: [], zai: [], perplexity: [], gemini: [], inception: [] };
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
          ai_reasoning_level_tertiary: mergedSettings.ai_reasoning_level_tertiary || prev.ai_reasoning_level_tertiary || 'medium'
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

  const handleInputChange = (field, value) => {
    console.log(`Updating ${field} to: ${value}`);
    setSettings((prev) => {
      if (field === 'ai_provider') {
        const sanitizedModel = sanitizeModel(value, prev.ai_model, modelOptions);
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
        const sanitizedModel = value ? sanitizeModel(value, prev.ai_model_secondary || prev.ai_model_fallback, modelOptions) : '';
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
        const sanitizedModel = value ? sanitizeModel(value, prev.ai_model_tertiary, modelOptions) : '';
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

  const fetchWebullAccounts = async () => {
    setLoadingWebullAccounts(true);
    setWebullAccountsMessage('');
    try {
      const response = await axios.get('/api/webull/accounts', { withCredentials: true });
      const result = response.data || {};
      const accList = Array.isArray(result.accounts) ? result.accounts : [];
      setWebullAccounts(accList);
      setWebullAccountsMessage(result.message || 'Webull accounts refreshed.');
      const initialAliases = { ...(result.aliases || {}) };
      accList.forEach((acc) => {
        if (acc.account_id && !initialAliases[acc.account_id]) {
          initialAliases[acc.account_id] = acc.custom_name || acc.account_name || '';
        }
      });
      setAccountAliases(initialAliases);
    } catch (error) {
      console.error('Error discovering Webull accounts:', error);
      setWebullAccounts([]);
      setWebullAccountsMessage(`Unable to discover accounts: ${error.response?.data?.message || 'Please verify the Webull connection.'}`);
    } finally {
      setLoadingWebullAccounts(false);
    }
  };

  const saveWebullAccountAliases = async () => {
    setSavingAliases(true);
    setAliasMessage('');
    try {
      const response = await axios.post('/api/webull/account-aliases', { aliases: accountAliases }, { withCredentials: true });
      if (response.data?.success) {
        setAliasMessage('✓ Account nicknames saved successfully.');
        await fetchWebullAccounts();
        setTimeout(() => setAliasMessage(''), 4000);
      } else {
        setAliasMessage(`❌ ${response.data?.message || 'Failed to save nicknames.'}`);
      }
    } catch (err) {
      setAliasMessage(`❌ ${err.response?.data?.message || 'Failed to save account nicknames.'}`);
    } finally {
      setSavingAliases(false);
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
        tier: 'tertiary'
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
    setShowUpgradeModal(true);
    fetchLatestVersion(includeBeta);
  };

  useEffect(() => {
    if (showUpgradeModal) {
      fetchLatestVersion(includeBeta);
    }
  }, [includeBeta, showUpgradeModal]);

  const confirmUpgrade = async () => {
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

  const handleOnboardingClose = async () => {
    setShowOnboardingModal(false);
    try {
      await axios.post('/api/mark-onboarding-complete', {}, { withCredentials: true });
    } catch (err) {
      console.error('Failed to mark onboarding complete:', err);
    }
  };

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
      {showUpgradeModal && createPortal(
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
      {/* Onboarding Modal */}
      <OnboardingModal
        show={showOnboardingModal}
        onClose={handleOnboardingClose}
        isLightMode={isLightMode}
      />
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

        {/* Webull OpenAPI is intentionally read-only until its account/position sync phase. */}
        <div className="settings-page-section">
          <h3>Webull OpenAPI Connection</h3>
          <p>
            Connect your personal Webull Trading API application. This step only verifies account access; it does <strong>not</strong> import positions, place orders, or enable trading yet.
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
                    onClick={fetchWebullAccounts}
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
                  <div style={{ marginTop: '12px', display: 'grid', gap: '10px' }}>
                    <p style={{ margin: '0 0 4px', fontSize: '13px', color: '#94a3b8' }}>
                      Set custom nicknames for your accounts (e.g. <em>Roth IRA</em>, <em>Rollover IRA</em>, <em>Cash</em>).
                    </p>
                    {webullAccounts.map((account, index) => (
                      <div
                        key={`${account.account_id || index}`}
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          gap: '12px',
                          alignItems: 'center',
                          padding: '10px 14px',
                          borderRadius: '6px',
                          background: 'rgba(15, 23, 42, 0.42)',
                          border: '1px solid rgba(255, 255, 255, 0.08)',
                          flexWrap: 'wrap'
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1, minWidth: '260px' }}>
                          <input
                            type="text"
                            value={accountAliases[account.account_id] !== undefined ? accountAliases[account.account_id] : (account.custom_name || account.account_name || '')}
                            onChange={(e) => {
                              const val = e.target.value;
                              setAccountAliases((prev) => ({ ...prev, [account.account_id]: val }));
                            }}
                            placeholder={account.account_sub_type ? `${account.account_type} (${account.account_sub_type})` : (account.account_type || 'Nickname')}
                            aria-label={`Custom nickname for account ${account.account_id_masked}`}
                            style={{
                              padding: '6px 12px',
                              borderRadius: '6px',
                              background: 'var(--input-bg, #0f172a)',
                              color: '#fff',
                              border: '1px solid rgba(255, 255, 255, 0.25)',
                              fontSize: '13px',
                              fontWeight: '600',
                              width: '220px'
                            }}
                          />
                          <span style={{ fontSize: '12px', color: '#94a3b8' }}>
                            ({account.account_type}{account.account_sub_type ? ` · ${account.account_sub_type}` : ''})
                          </span>
                        </div>
                        <span style={{ fontFamily: 'monospace', opacity: 0.85, fontSize: '13px', color: '#cbd5e1' }}>
                          {account.account_id_masked}
                        </span>
                      </div>
                    ))}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '4px' }}>
                      <button
                        type="button"
                        onClick={saveWebullAccountAliases}
                        disabled={savingAliases}
                        style={{
                          padding: '7px 16px',
                          backgroundColor: savingAliases ? '#6c757d' : '#10b981',
                          color: '#fff',
                          border: 'none',
                          borderRadius: '4px',
                          cursor: savingAliases ? 'not-allowed' : 'pointer',
                          fontSize: '13px',
                          fontWeight: 'bold',
                          transition: 'background 0.2s ease',
                        }}
                      >
                        {savingAliases ? 'Saving...' : '💾 Save Account Nicknames'}
                      </button>
                      {aliasMessage && (
                        <span style={{ fontSize: '13px', color: aliasMessage.startsWith('❌') ? '#ef4444' : '#10b981', fontWeight: 600 }}>
                          {aliasMessage}
                        </span>
                      )}
                    </div>
                  </div>
                )}
                <div style={{ marginTop: '14px', paddingTop: '12px', borderTop: '1px solid rgba(79, 209, 197, 0.20)' }}>
                  <strong>Portfolio Preview</strong>
                  <p className="settings-form-help" style={{ margin: '4px 0 10px' }}>
                    All connected Webull accounts are selected. This fetches a live, read-only preview of balances and open positions; it does not merge or save them into the dashboard yet.
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

        {/* Row 1, Right: Two-Factor Authentication Section */}
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

          {/* Gemini Reasoning Effort */}
          {settings.ai_provider === 'gemini' && (
            <div className="settings-form-group">
              <label>Reasoning</label>
              <select
                value={settings.ai_reasoning_level || 'medium'}
                onChange={(e) => handleInputChange('ai_reasoning_level', e.target.value)}
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
              <div className="settings-form-help">
                Configure reasoning effort for Gemini models (Low, Medium, or High)
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

          {/* Gemini Reasoning Effort for Secondary */}
          {(settings.ai_provider_secondary === 'gemini' || settings.ai_provider_fallback === 'gemini') && (
            <div className="settings-form-group">
              <label>Reasoning</label>
              <select
                value={settings.ai_reasoning_level_secondary || settings.ai_reasoning_level_fallback || 'medium'}
                onChange={(e) => handleInputChange('ai_reasoning_level_secondary', e.target.value)}
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
              <div className="settings-form-help">
                Configure reasoning effort for Gemini models (Low, Medium, or High)
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

          {/* Gemini Reasoning Effort for Tertiary */}
          {settings.ai_provider_tertiary === 'gemini' && (
            <div className="settings-form-group">
              <label>Reasoning</label>
              <select
                value={settings.ai_reasoning_level_tertiary || 'medium'}
                onChange={(e) => handleInputChange('ai_reasoning_level_tertiary', e.target.value)}
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
              <div className="settings-form-help">
                Configure reasoning effort for Gemini models (Low, Medium, or High)
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

        {/* Credential Encryption - ONLY for Admin (id=1) */}
        {user && user.id === 1 && (
          <div className="settings-page-section" style={{ gridColumn: '1 / -1' }}>
            <h3>Credential Encryption</h3>
            <p>
              Store a Fernet key to encrypt Binance, AI, and notification credentials at rest. Provide either a 32-character raw secret or a URL-safe base64 string.
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

      {/* Web Search Settings */}
      <div className="settings-page-section">
        <h3>🔍 Web Search</h3>

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
        </div>

        <div className="settings-form-help" style={{ marginTop: '12px', fontStyle: 'italic' }}>
          💡 Combined limit: 4,000 searches/month before falling back to DuckDuckGo
        </div>
      </div>

      {/* AI Settings */}
      <div data-section="ai-settings" className="settings-page-section">
        <h3>🤖 AI Trading Settings</h3>

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

        <div style={{ marginTop: 16 }}>
          <h4 style={{ color: '#fff', marginBottom: 12 }}>AI Agentic Workflow Prompts</h4>
          <p style={{ color: '#666', fontSize: '12px', marginBottom: 16 }}>
            Configure prompts for the 3-stage agentic workflow: Stage 1 (search query generation), Stage 2 (web search), Stage 3 (synthesis).
            Each analysis type has pre-search and post-search prompts that accept {'{symbol}'} and {'{datetime}'} variables.
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


            {/* Coin & News Analysis */}
            <div style={{ background: '#1a1f23', padding: 16, borderRadius: 8, border: '1px solid #444' }}>
              <h5 style={{ color: '#4fd1c5', marginBottom: 12, fontSize: '14px' }}>Coin & News Analysis</h5>
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
                    placeholder="Prompt to generate search queries for coin & news analysis..."
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
                    placeholder="Prompt to synthesize search results into coin & news analysis..."
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
                Automated sentiment analysis for all portfolio coins you currently own. Classifies into: <strong>Hold, Buy Immediately, Consider Buying, Sell Immediately, Consider Selling</strong>.
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
                Automated and on-the-spot sentiment analysis for watchlist coins you are monitoring. Classifies prospective entry into: <strong>Avoid, Watch, Consider Buying, Definitely Buy</strong>.
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
                Configure the persona and analytical behavior of the AI Copilot sidebar. The Copilot automatically receives your live portfolio, watchlist, pending orders, and active sidebar conversation feed.
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
                    placeholder="e.g. You are the AI Copilot for Crypto Alert App, an expert cryptocurrency portfolio strategist..."
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
      </div>

      <section className="settings-page-section sentiment-variable-settings" style={{ marginTop: '24px' }}>
        <h3>🎯 Sentiment Variable Settings</h3>
        <p>
          Grade each new recommendation at its fixed forecast horizon using the rule values saved with that prediction. Existing history remains visible as legacy next-check evaluation. Directional Wrong values and the Hold steady range may be 0.00%; the Hold Wrong Threshold must be greater than its steady range. Exact boundaries are decisive.
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

          <div style={{ marginTop: 16 }}>
            <label style={{ display: 'block', marginBottom: 8, color: '#fff' }}>
              News API Key
            </label>
            <input
              type="password"
              value={settings.news_api || ''}
              onChange={(e) => handleInputChange('news_api', e.target.value)}
              placeholder="Enter News API Key"
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
