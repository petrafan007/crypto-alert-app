import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useAuth } from '../components/AuthContext';
import { Modal, Button } from 'react-bootstrap';
import { FaToggleOn, FaToggleOff, FaInfoCircle } from 'react-icons/fa';
import { useSearchParams } from 'react-router-dom';
import OnboardingModal from '../components/OnboardingModal';

const getDefaultModel = (provider, options) => {
  const models = options[provider] || [];
  if (models.length > 0) {
    // Prefer a non-experimental default if available
    const nonExp = models.find(m => !m.label.includes('(exp)'));
    return nonExp ? nonExp.value : models[0].value;
  }
  return '';
};

const sanitizeModel = (provider, model, options) => {
  const validList = options[provider] || [];
  const validValues = validList.map((item) => item.value);
  return validValues.includes(model) ? model : getDefaultModel(provider, options);
};

export default function Settings({ isLightMode }) {
  // Pull user so we can gate admin-only sections without runtime errors
  const { user, isLoggingOut } = useAuth();
  const [modelOptions, setModelOptions] = useState({
    openai: [],
    zai: [],
    perplexity: [],
    gemini: [],
  });
  const [settings, setSettings] = useState({
    api_key: '',
    api_secret: '',
    binance_testnet: true,
    openai_key: '',
    zai_key: '',
    perplexity_key: '',
    gemini_key: '',
    ai_provider: 'openai',
    ai_model: '',
    telegram_token: '',
    telegram_chat_id: '',
    news_api: '',
    credentials_encryption_key: '',
    // AI Settings
    ai_risk_tolerance: 'moderate',
    ai_confidence_threshold: 75,
    ai_notifications_enabled: true,
    ai_analysis_frequency: 'daily',
    sentiment_analysis_frequency_hours: 24,
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
      sentiment_prompt_post: ''
    },
    copilot_chat_pre: '',
    copilot_chat_post: ''
  });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState(''); // 'success' or 'error'
  const [testingBinance, setTestingBinance] = useState(false);
  const [testingTrading, setTestingTrading] = useState(false);
  const [testingOpenAI, setTestingOpenAI] = useState(false);
  const [testingZAI, setTestingZAI] = useState(false);
  const [testingBraveApi, setTestingBraveApi] = useState(false);
  const [testingBraveApiFallback, setTestingBraveApiFallback] = useState(false);
  const [braveApiTestResult, setBraveApiTestResult] = useState(null);
  const [braveApiFallbackTestResult, setBraveApiFallbackTestResult] = useState(null);
  const [testingFallback, setTestingFallback] = useState(false);
  const [fallbackTestResult, setFallbackTestResult] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const [encryptionStatus, setEncryptionStatus] = useState({ configured: false, persisted: false });
  const [encryptionKeyDirty, setEncryptionKeyDirty] = useState(false);
  const [forcingAnalysis, setForcingAnalysis] = useState(false);
  const [forceAnalysisResult, setForceAnalysisResult] = useState(null);
  const [upgrading, setUpgrading] = useState(false);

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
      let currentModelOptions = { openai: [], zai: [], perplexity: [], gemini: [] };
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

      setSettings((prev) => {
        const mergedSettings = {
          ...sanitizedSettingsResponse,
        };

        const provider = mergedSettings.ai_provider || prev.ai_provider || 'openai';
        let model = mergedSettings.ai_model;

        const sanitizedModel = sanitizeModel(provider, model, currentModelOptions);

        return {
          ...prev,
          ...mergedSettings,
          ai_provider: provider,
          ai_model: sanitizedModel
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
        }
      }

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

  // Test OpenAI Connection
  const testOpenAIConnection = async () => {
    setTestingOpenAI(true);
    setMessage('');
    setMessageType('');

    try {
      const response = await axios.get('/api/test-openai-connection', { withCredentials: true });

      if (response.data.success) {
        setMessage('✅ OpenAI API connection successful!');
        setMessageType('success');
      } else {
        setMessage(`❌ ${response.data.message || 'Failed to connect to OpenAI API'}`);
        setMessageType('error');
      }
    } catch (error) {
      console.error('Error testing OpenAI connection:', error);
      const errorMessage = error.response?.data?.message || error.message || 'Failed to connect to OpenAI API';
      setMessage(`❌ ${errorMessage}`);
      setMessageType('error');
    } finally {
      setTestingOpenAI(false);
    }
  };

  // Test Z.AI Connection
  const testZAIConnection = async () => {
    setTestingZAI(true);
    setMessage('');
    setMessageType('');

    try {
      const response = await axios.get('/api/test-zai-connection', { withCredentials: true });

      if (response.data.success) {
        setMessage('✅ Z.AI API connection successful!');
        setMessageType('success');
      } else {
        setMessage(`❌ ${response.data.message || 'Failed to connect to Z.AI API'}`);
        setMessageType('error');
      }
    } catch (error) {
      console.error('Error testing Z.AI connection:', error);
      const errorMessage = error.response?.data?.message || error.message || 'Failed to connect to Z.AI API';
      setMessage(`❌ ${errorMessage}`);
      setMessageType('error');
    } finally {
      setTestingZAI(false);
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

  // Test AI Fallback Connection
  const testFallbackConnection = async () => {
    setTestingFallback(true);
    setFallbackTestResult(null);

    const provider = settings.ai_provider_fallback;
    let apiKey = '';

    // Determine the key based on provider
    if (provider === 'openai') apiKey = settings.openai_key_fallback;
    else if (provider === 'zai') apiKey = settings.zai_key_fallback;
    else if (provider === 'perplexity') apiKey = settings.perplexity_key_fallback;
    else if (provider === 'gemini') apiKey = settings.gemini_key_fallback;

    try {
      const response = await axios.post('/api/test-ai-connection-generic', {
        provider: provider,
        api_key: apiKey,
        model: settings.ai_model_fallback
      }, { withCredentials: true });

      setFallbackTestResult({
        success: response.data.success,
        message: response.data.message || (response.data.success ? 'Fallback connection successful!' : 'Connection failed')
      });
    } catch (error) {
      console.error('Error testing fallback connection:', error);
      setFallbackTestResult({
        success: false,
        message: error.response?.data?.message || 'Failed to test fallback connection'
      });
    } finally {
      setTestingFallback(false);
    }
  };

  const handleForceAnalysis = async () => {
    setForcingAnalysis(true);
    setForceAnalysisResult(null);
    try {
      const response = await axios.post('/api/force-sentiment-analysis', {}, { withCredentials: true });
      if (response.data.success) {
        setForceAnalysisResult({ success: true, message: response.data.message });
      } else {
        setForceAnalysisResult({ success: false, message: response.data.error || 'Failed to start analysis' });
      }
    } catch (err) {
      console.error('Force analysis error:', err);
      setForceAnalysisResult({ success: false, message: err.response?.data?.error || 'Failed to connect to server' });
    } finally {
      setForcingAnalysis(false);
    }
  };

  const handleUpgrade = async () => {
    if (!window.confirm("Are you sure you want to pull the latest Version 1.03 Beta updates from GitHub and restart the app?")) return;
    setUpgrading(true);
    setMessage('Upgrade initiated. Please wait, the page will automatically refresh when complete...');
    setMessageType('success');
    try {
      const response = await axios.post('/api/system/upgrade', {}, { withCredentials: true });
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
      {/* Onboarding Modal */}
      <OnboardingModal
        show={showOnboardingModal}
        onClose={handleOnboardingClose}
        isLightMode={isLightMode}
      />
      {/* Header with Action Buttons */}
      <div className="settings-header">
        <h1>Settings & API Configuration</h1>

        {/* Top Right Action Buttons */}
        <div className="settings-action-buttons">
          <div className="settings-status">
            <div
              style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', userSelect: 'none' }}
              onClick={() => handleInputChange('ai_enabled', !settings.ai_enabled)}
            >
              <span className={`me-2 fw-bold ${settings.ai_enabled ? 'text-success' : 'text-muted'}`}>
                {settings.ai_enabled ? 'AI Integration Enabled' : 'AI Integration Disabled'}
              </span>
              {settings.ai_enabled ? (
                <FaToggleOn size={32} color="#4fd1c5" />
              ) : (
                <FaToggleOff size={32} color="#6c757d" />
              )}
            </div>
          </div>

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

          <button
            onClick={handleUpgrade}
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
        {/* Binance.US API Key and Secret (Unified) */}
        <div className="settings-page-section" style={{ flex: "0 0 100%" }}>
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

        {/* AI Integration - Side by side with 2FA */}
        <div className="settings-page-section" style={{ flex: "0 0 48%" }}>
          <h3>AI Integration</h3>

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
            </select>
            <div className="settings-form-help">
              Choose your AI provider for analysis and recommendations
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

          {/* OpenAI Configuration - Only show when OpenAI is selected */}
          {settings.ai_provider === 'openai' && (
            <div className="settings-form-group">
              <label>
                OpenAI API Key
              </label>
              <input
                type="password"
                value={settings.openai_key || ''}
                onChange={(e) => handleInputChange('openai_key', e.target.value)}
                placeholder="Enter OpenAI API Key"
              />
              <div className="settings-form-help">
                Used for AI-powered trading analysis and recommendations
              </div>

              {/* Test OpenAI Connection button */}
              <button
                onClick={testOpenAIConnection}
                disabled={testingOpenAI}
                className={`settings-button secondary ${testingOpenAI ? 'disabled' : ''}`}
                style={{ marginTop: '8px' }}
              >
                {testingOpenAI ? 'Testing...' : 'Test OpenAI Connection'}
              </button>
            </div>
          )}

          {/* Z.AI Configuration - Only show when Z.AI is selected */}
          {settings.ai_provider === 'zai' && (
            <div className="settings-form-group">
              <label>
                Z.AI API Key
              </label>
              <input
                type="password"
                value={settings.zai_key || ''}
                onChange={(e) => handleInputChange('zai_key', e.target.value)}
                placeholder="Enter Z.AI API Key"
              />
              <div className="settings-form-help">
                Used for AI-powered trading analysis and recommendations
              </div>

              {/* Test Z.AI Connection button */}
              <button
                onClick={testZAIConnection}
                disabled={testingZAI}
                className={`settings-button secondary ${testingZAI ? 'disabled' : ''}`}
                style={{ marginTop: '8px' }}
              >
                {testingZAI ? 'Testing...' : 'Test Z.AI Connection'}
              </button>
            </div>
          )}

          {/* Perplexity Configuration - Only show when Perplexity is selected */}
          {settings.ai_provider === 'perplexity' && (
            <div className="settings-form-group">
              <label>
                Perplexity API Key
              </label>
              <input
                type="password"
                value={settings.perplexity_key || ''}
                onChange={(e) => handleInputChange('perplexity_key', e.target.value)}
                placeholder="Enter Perplexity API Key"
              />
              <div className="settings-form-help">
                Used for AI-powered trading analysis and recommendations
              </div>
              <button
                onClick={async () => {
                  setMessage('');
                  setMessageType('');
                  try {
                    const resp = await axios.post('/api/test-perplexity-connection', {
                      model: settings.ai_model,
                      perplexity_key: settings.perplexity_key,
                    }, { withCredentials: true });
                    setMessage(resp.data.message || '✅ Perplexity connection successful');
                    setMessageType(resp.data.success ? 'success' : 'error');
                  } catch (err) {
                    setMessage(err.response?.data?.message || '❌ Failed to test Perplexity connection');
                    setMessageType('error');
                  }
                }}
                className="settings-button secondary"
                style={{ marginTop: '8px' }}
                disabled={!settings.perplexity_key}
              >
                Test AI Integration
              </button>
            </div>
          )}

          {/* Gemini Configuration - Only show when Gemini is selected */}
          {settings.ai_provider === 'gemini' && (
            <div className="settings-form-group">
              <label>
                Gemini API Key
              </label>
              <input
                type="password"
                value={settings.gemini_key || ''}
                onChange={(e) => handleInputChange('gemini_key', e.target.value)}
                placeholder="Enter Gemini API Key"
              />
              <div className="settings-form-help">
                Used for AI-powered trading analysis and recommendations
              </div>
              <button
                onClick={async () => {
                  setMessage('');
                  setMessageType('');
                  try {
                    const resp = await axios.post('/api/test-gemini-connection', {
                      model: settings.ai_model,
                      gemini_key: settings.gemini_key,
                    }, { withCredentials: true });
                    setMessage(resp.data.message || '✅ Gemini connection successful');
                    setMessageType(resp.data.success ? 'success' : 'error');
                  } catch (err) {
                    setMessage(err.response?.data?.message || '❌ Failed to test Gemini connection');
                    setMessageType('error');
                  }
                }}
                className="settings-button secondary"
                style={{ marginTop: '8px' }}
                disabled={!settings.gemini_key}
              >
                Test AI Integration
              </button>
            </div>
          )}
        </div>

        {/* AI Integration Fallback */}
        <div className="settings-page-section">
          <h3>🤖 AI Integration Fallback</h3>
          <div className="settings-form-help" style={{ marginBottom: '16px' }}>
            Configure a backup AI provider. If the primary provider fails (e.g., rate limits, downtime), the system will automatically retry using these credentials.
          </div>

          <div className="settings-form-group">
            <label>AI Provider Fallback</label>
            <select
              value={settings.ai_provider_fallback || ''}
              onChange={(e) => handleInputChange('ai_provider_fallback', e.target.value)}
            >
              <option value="">-- Select Fallback Provider --</option>
              <option value="openai">OpenAI</option>
              <option value="zai">Z.AI</option>
              <option value="perplexity">Perplexity</option>
              <option value="gemini">Gemini</option>
            </select>
          </div>

          {settings.ai_provider_fallback && (
            <div className="settings-form-group">
              <label>AI Model Fallback</label>
              <select
                value={settings.ai_model_fallback || ''}
                onChange={(e) => handleInputChange('ai_model_fallback', e.target.value)}
              >
                {(modelOptions[settings.ai_provider_fallback] || []).map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </div>
          )}

          {/* OpenAI Fallback */}
          {settings.ai_provider_fallback === 'openai' && (
            <div className="settings-form-group">
              <label>OpenAI API Key (Fallback)</label>
              <input
                type="password"
                value={settings.openai_key_fallback || ''}
                onChange={(e) => handleInputChange('openai_key_fallback', e.target.value)}
                placeholder="Enter Fallback OpenAI API Key"
              />
            </div>
          )}

          {/* Z.AI Fallback */}
          {settings.ai_provider_fallback === 'zai' && (
            <div className="settings-form-group">
              <label>Z.AI API Key (Fallback)</label>
              <input
                type="password"
                value={settings.zai_key_fallback || ''}
                onChange={(e) => handleInputChange('zai_key_fallback', e.target.value)}
                placeholder="Enter Fallback Z.AI API Key"
              />
            </div>
          )}

          {/* Perplexity Fallback */}
          {settings.ai_provider_fallback === 'perplexity' && (
            <div className="settings-form-group">
              <label>Perplexity API Key (Fallback)</label>
              <input
                type="password"
                value={settings.perplexity_key_fallback || ''}
                onChange={(e) => handleInputChange('perplexity_key_fallback', e.target.value)}
                placeholder="Enter Fallback Perplexity API Key"
              />
            </div>
          )}

          {/* Gemini Fallback */}
          {settings.ai_provider_fallback === 'gemini' && (
            <div className="settings-form-group">
              <label>Gemini API Key (Fallback)</label>
              <input
                type="password"
                value={settings.gemini_key_fallback || ''}
                onChange={(e) => handleInputChange('gemini_key_fallback', e.target.value)}
                placeholder="Enter Fallback Gemini API Key"
              />
            </div>
          )}

          {/* Test Button for Fallback */}
          <div className="settings-form-group" style={{ marginTop: '16px' }}>
            <button
              onClick={testFallbackConnection}
              disabled={!settings.ai_provider_fallback || testingFallback}
              className={`settings-button secondary ${(!settings.ai_provider_fallback || testingFallback) ? 'disabled' : ''}`}
            >
              {testingFallback ? 'Testing...' : 'Test AI Fallback Integration'}
            </button>
            {fallbackTestResult && (
              <div className={`settings-status ${fallbackTestResult.success ? 'success' : 'error'}`} style={{ marginTop: '8px' }}>
                {fallbackTestResult.message}
              </div>
            )}
          </div>
        </div>

        <div className="settings-page-section">
          <h3>⚡ Force Analysis</h3>
          <div className="settings-form-help">
            Manually trigger sentiment analysis for all your coins immediately. This is useful for testing AI integration or refreshing stale data.
          </div>
          <div className="settings-form-group">
            <button
              onClick={handleForceAnalysis}
              disabled={forcingAnalysis}
              className={`settings-button primary ${forcingAnalysis ? 'disabled' : ''}`}
              style={{ width: '100%', marginTop: '10px' }}
            >
              {forcingAnalysis ? 'Running Analysis...' : 'Run Sentiment Analysis Now'}
            </button>
            {forceAnalysisResult && (
              <div className={`settings-status ${forceAnalysisResult.success ? 'success' : 'error'}`} style={{ marginTop: '8px' }}>
                {forceAnalysisResult.message}
              </div>
            )}
          </div>
        </div>

        {/* Two-Factor Authentication Section - Side by side with AI Integration */}
        <div className="settings-page-section" style={{ flex: "0 0 48%" }}>
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

        {/* Credential Encryption - ONLY for Admin (id=1) */}
        {user && user.id === 1 && (
          <div className="settings-page-section" style={{ flex: "0 0 48%" }}>
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

            {/* Risk Assessment */}
            <div style={{ background: '#1a1f23', padding: 16, borderRadius: 8, border: '1px solid #444' }}>
              <h5 style={{ color: '#4fd1c5', marginBottom: 12, fontSize: '14px' }}>Risk Assessment</h5>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', marginBottom: 8, color: '#fff', fontSize: '12px' }}>
                    Pre-Search Prompt (Stage 1)
                  </label>
                  <textarea
                    value={settings.ai_prompts?.risk_assessment_pre || ''}
                    onChange={(e) => {
                      handleInputChange('ai_prompts', {
                        ...settings.ai_prompts,
                        risk_assessment_pre: e.target.value
                      });
                      autoResizeTextarea(e.target);
                    }}
                    onInput={(e) => autoResizeTextarea(e.target)}
                    placeholder="Prompt to generate search queries for risk assessment..."
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
                    value={settings.ai_prompts?.risk_assessment_post || ''}
                    onChange={(e) => {
                      handleInputChange('ai_prompts', {
                        ...settings.ai_prompts,
                        risk_assessment_post: e.target.value
                      });
                      autoResizeTextarea(e.target);
                    }}
                    onInput={(e) => autoResizeTextarea(e.target)}
                    placeholder="Prompt to synthesize search results into risk assessment..."
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

            {/* Sentiment Analysis */}
            <div style={{ background: '#1a1f23', padding: 16, borderRadius: 8, border: '1px solid #444' }}>
              <h5 style={{ color: '#4fd1c5', marginBottom: 12, fontSize: '14px' }}>Sentiment Analysis</h5>
              <p style={{ color: '#a0a6b8', fontSize: '12px', marginBottom: 16, lineHeight: '1.4' }}>
                Automated sentiment analysis runs every 30 minutes for all portfolio coins. Configure the prompts used for the 3-stage agentic workflow.
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

                  {/* Sentiment Update Frequency */}
                  <div style={{ marginTop: 12 }}>
                    <label style={{ display: 'block', marginBottom: 6, color: '#fff', fontSize: '12px' }}>
                      Sentiment Update Frequency (hours)
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


            {/* AI Copilot System Prompt */}
            <div style={{ background: '#1a1f23', padding: 16, borderRadius: 8, border: '1px solid #444', marginTop: 16 }}>
              <h5 style={{ color: '#4fd1c5', marginBottom: 12, fontSize: '14px' }}>AI Copilot System Prompt</h5>
              <p style={{ color: '#a0a6b8', fontSize: '12px', marginBottom: 16, lineHeight: '1.4' }}>
                Configure the behavior of the manual AI Copilot sidebar. Use the Pre-Search prompt to extract search queries, and the Post-Search prompt to guide the final answer.
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', marginBottom: 8, color: '#fff', fontSize: '12px' }}>
                    Pre-Search Prompt (Search Logic)
                  </label>
                  <textarea
                    value={settings.copilot_chat_pre || ''}
                    onChange={(e) => {
                      handleInputChange('copilot_chat_pre', e.target.value);
                      autoResizeTextarea(e.target);
                    }}
                    onInput={(e) => autoResizeTextarea(e.target)}
                    placeholder="e.g. Analyze the request and extract search terms..."
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
                    Post-Search Prompt (Answer Logic)
                  </label>
                  <textarea
                    value={settings.copilot_chat_post || ''}
                    onChange={(e) => {
                      handleInputChange('copilot_chat_post', e.target.value);
                      autoResizeTextarea(e.target);
                    }}
                    onInput={(e) => autoResizeTextarea(e.target)}
                    placeholder="e.g. You are a helpful assistant. Use the search results..."
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

      {/* Notifications */}
      <div className="settings-page-section">
        <h3>Notifications</h3>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div>
            <label style={{ display: 'block', marginBottom: 8, color: '#fff' }}>
              Telegram Bot Token
            </label>
            <input
              type="text"
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
              type="text"
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
            type="text"
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

