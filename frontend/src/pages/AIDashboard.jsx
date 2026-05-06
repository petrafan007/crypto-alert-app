import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useAuth } from '../components/AuthContext';
import AIAnalysisModal from '../components/AIAnalysisModal';
import ApiKeyRequiredModal from '../components/ApiKeyRequiredModal';
import './AIDashboard.css';

const formatEasternTime = (isoString) => {
  if (!isoString) return 'Not available';

  try {
    const date = new Date(isoString);
    // Format as Eastern time with AM/PM
    return date.toLocaleString('en-US', {
      timeZone: 'America/New_York',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZoneName: 'short'
    });
  } catch (error) {
    console.error('Error formatting timestamp:', error);
    return 'Invalid date';
  }
};

const escapeHtml = (str) =>
  str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

const formatInlineMarkdown = (text) => {
  let formatted = escapeHtml(text);
  formatted = formatted.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  formatted = formatted.replace(/\*(.+?)\*/g, '<em>$1</em>');
  formatted = formatted.replace(/`(.+?)`/g, '<code>$1</code>');
  formatted = formatted.replace(/\[(.+?)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  formatted = formatted.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
  return formatted;
};

const renderMarkdown = (markdown) => {
  if (!markdown) return '';
  const lines = markdown.split(/\r?\n/);
  const html = [];
  let inUl = false;
  let inOl = false;
  let inBlockquote = false;

  const closeLists = () => {
    if (inUl) {
      html.push('</ul>');
      inUl = false;
    }
    if (inOl) {
      html.push('</ol>');
      inOl = false;
    }
  };

  const closeBlockquote = () => {
    if (inBlockquote) {
      html.push('</blockquote>');
      inBlockquote = false;
    }
  };

  lines.forEach((line) => {
    const trimmed = line.trim();

    if (!trimmed) {
      closeLists();
      closeBlockquote();
      return;
    }

    const headingMatch = trimmed.match(/^(#{1,4})\s+(.*)$/);
    if (headingMatch) {
      closeLists();
      closeBlockquote();
      const level = Math.min(headingMatch[1].length, 4);
      html.push(`<h${level}>${formatInlineMarkdown(headingMatch[2].trim())}</h${level}>`);
      return;
    }

    const blockquoteMatch = trimmed.match(/^>\s+(.*)$/);
    if (blockquoteMatch) {
      closeLists();
      if (!inBlockquote) {
        html.push('<blockquote>');
        inBlockquote = true;
      }
      html.push(`<p>${formatInlineMarkdown(blockquoteMatch[1])}</p>`);
      return;
    }

    const olMatch = trimmed.match(/^(\d+)\.\s+(.*)$/);
    if (olMatch) {
      if (!inOl) {
        closeLists();
        closeBlockquote();
        html.push('<ol>');
        inOl = true;
      }
      html.push(`<li>${formatInlineMarkdown(olMatch[2])}</li>`);
      return;
    }

    const ulMatch = trimmed.match(/^[-*]\s+(.*)$/);
    if (ulMatch) {
      if (!inUl) {
        closeLists();
        closeBlockquote();
        html.push('<ul>');
        inUl = true;
      }
      html.push(`<li>${formatInlineMarkdown(ulMatch[1])}</li>`);
      return;
    }

    closeLists();
    closeBlockquote();
    html.push(`<p>${formatInlineMarkdown(trimmed)}</p>`);
  });

  closeLists();
  closeBlockquote();
  return html.join('');
};

export default function AIDashboard({ isLightMode }) {
  const { user, loading: authLoading, isLoggingOut } = useAuth();

  const [aiAnalysis, setAiAnalysis] = useState(null);
  const [marketSentiment, setMarketSentiment] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showAnalysisModal, setShowAnalysisModal] = useState(false);
  const [selectedSymbol, setSelectedSymbol] = useState(null);
  const [aiEnabled, setAiEnabled] = useState(true);
  const [analysisResults, setAnalysisResults] = useState([]);

  // New state for 3-stage agentic workflows
  const [marketAnalysisData, setMarketAnalysisData] = useState(null);
  const [riskAssessmentData, setRiskAssessmentData] = useState(null);
  const [portfolioReviewData, setPortfolioReviewData] = useState(null);
  // Prompt viewing state
  const [marketPrompt, setMarketPrompt] = useState(null);
  const [riskPrompt, setRiskPrompt] = useState(null);
  const [portfolioPrompt, setPortfolioPrompt] = useState(null);
  const [showMarketPrompt, setShowMarketPrompt] = useState(false);
  const [showRiskPrompt, setShowRiskPrompt] = useState(false);
  const [showPortfolioPrompt, setShowPortfolioPrompt] = useState(false);
  const [workflowLoading, setWorkflowLoading] = useState({
    marketAnalysis: false,
    riskAssessment: false,
    portfolioReview: false
  });

  // API Key check state
  const [showApiKeyModal, setShowApiKeyModal] = useState(false);

  console.log('AIDashboard component rendered:', { user, authLoading });

  useEffect(() => {
    console.log('AIDashboard useEffect:', { authLoading, user });
    const init = async () => {
      if (!authLoading && user) {
        // Check if user has API key first
        try {
          const permResponse = await axios.get('/api/check-trade-permission', { withCredentials: true });
          if (!permResponse.data.has_api_key) {
            setShowApiKeyModal(true);
            setLoading(false);
            return;
          }
        } catch (err) {
          console.error('Failed to check API key status:', err);
        }

        console.log('User authenticated, checking AI status and loading latest results...');
        const enabled = await checkAiStatus();
        setLoading(false);
        if (enabled) {
          await loadLatestResults();
        }
      } else {
        console.log('Not checking AI status:', { authLoading, user });
      }
    };
    init();
  }, [authLoading, user]);

  const checkAiStatus = async () => {
    try {
      // Don't make API calls if we're logging out
      if (isLoggingOut || window.globalIsLoggingOut) {
        return false;
      }

      const response = await axios.get('/api/ai/settings', { withCredentials: true });
      const enabled = response.data.ai_enabled === true || response.data.ai_enabled === 'true';
      setAiEnabled(enabled);
      return enabled;
    } catch (error) {
      console.error('Error checking AI status:', error);
      // Default to enabled if check fails
      setAiEnabled(true);
      return true;
    }
  };

  const loadLatestResults = async () => {
    // Rehydrate sections from latest saved ai_conversations entries
    try {
      if (isLoggingOut || window.globalIsLoggingOut) return;

      const loadOne = async (type, setter, stateKeyName) => {
        try {
          const res = await axios.get(`/api/ai/workflow-latest`, {
            params: { type },
            withCredentials: true,
          });
          if (res.status === 200 && res.data && res.data.body) {
            const createdAt = res.data.created_at || res.data.time || new Date().toISOString();
            setter({
              stage1: { status: 'completed', description: 'Loaded latest saved result' },
              stage2: { status: 'skipped', description: 'Loaded from history' },
              stage3: { status: 'completed', description: 'Loaded from history' },
              analysis: {
                content: res.data.body,
                generated_at: createdAt,
              },
              cache_info: null,
            });
            console.log(`Rehydrated ${stateKeyName} from latest saved result`);
          }
        } catch (e) {
          // 404 means no prior saved result; ignore silently
          if (!(e?.response && e.response.status === 404)) {
            console.warn(`Failed to rehydrate ${stateKeyName}:`, e?.response?.data || e.message);
          }
        }
      };

      await Promise.all([
        loadOne('market_analysis', setMarketAnalysisData, 'marketAnalysis'),
        loadOne('risk_assessment', setRiskAssessmentData, 'riskAssessment'),
        loadOne('portfolio_review', setPortfolioReviewData, 'portfolioReview'),
      ]);
    } catch (err) {
      console.error('Error loading latest results:', err);
    }
  };

  // Fetch the latest saved Stage 3 prompt (sender='user') for a section
  const fetchWorkflowPrompt = async (type) => {
    try {
      const urlMap = {
        market_analysis: '/api/ai/market-analysis-workflow-prompt',
        risk_assessment: '/api/ai/risk-assessment-workflow-prompt',
        portfolio_review: '/api/ai/portfolio-review-workflow-prompt',
      };
      const url = urlMap[type];
      if (!url) return '(No endpoint)';
      const res = await axios.get(url, { params: { source: 'prompts' }, withCredentials: true });
      return res?.data?.body || '(Empty prompt)';
    } catch (e) {
      if (e?.response && e.response.status === 404) {
        return '(No saved prompt yet)';
      }
      console.error('Failed to fetch prompt:', e);
      return '(Failed to load prompt)';
    }
  };

  const onViewMarketPrompt = async () => {
    const body = await fetchWorkflowPrompt('market_analysis');
    setMarketPrompt(body);
    setShowMarketPrompt(true);
  };
  const onViewRiskPrompt = async () => {
    const body = await fetchWorkflowPrompt('risk_assessment');
    setRiskPrompt(body);
    setShowRiskPrompt(true);
  };
  const onViewPortfolioPrompt = async () => {
    const body = await fetchWorkflowPrompt('portfolio_review');
    setPortfolioPrompt(body);
    setShowPortfolioPrompt(true);
  };

  const fetchWorkflowData = async (workflowType, manual = true) => {
    // Don't make API calls if we're logging out
    if (isLoggingOut || window.globalIsLoggingOut) {
      return;
    }

    // Map workflow types to state and endpoints
    const workflowConfig = {
      'market-analysis': {
        stateKey: 'marketAnalysis',
        endpoint: '/api/ai/market-analysis-workflow',
        setter: setMarketAnalysisData
      },
      'risk-assessment': {
        stateKey: 'riskAssessment',
        endpoint: '/api/ai/risk-assessment-workflow',
        setter: setRiskAssessmentData
      },
      'portfolio-review': {
        stateKey: 'portfolioReview',
        endpoint: '/api/ai/portfolio-review-workflow',
        setter: setPortfolioReviewData
      }
    };

    const config = workflowConfig[workflowType];
    if (!config) {
      console.error(`Unknown workflow type: ${workflowType}`);
      return;
    }

    // Set loading state
    setWorkflowLoading(prev => ({ ...prev, [config.stateKey]: true }));

    try {
      const url = manual ? `${config.endpoint}?manual=true` : config.endpoint;
      const response = await axios.get(url, { withCredentials: true });

      if (response.data.success) {
        // Check if this is an async response (analysis started but not complete)
        if (response.data.status === 'analysis_started') {
          console.log(`${workflowType} analysis started in background - will poll for results`);

          // Set initial loading state with proper message
          config.setter({
            stage1: { status: 'in-progress', description: 'Analysis started in background...' },
            stage2: { status: 'pending', description: 'Web search in progress...' },
            stage3: { status: 'pending', description: 'AI analysis will be generated...' },
            analysis: null,
            cache_info: null,
            status: 'in-progress'
          });

          // Poll for results every 10 seconds for up to 3 minutes (portfolio analysis can take time)
          let pollCount = 0;
          const maxPolls = 18; // 180 seconds total (3 minutes)

          const pollForResults = async () => {
            try {
              pollCount++;
              console.log(`Polling for ${workflowType} results (attempt ${pollCount}/${maxPolls})`);

              // Use the results endpoint to check for completed analysis
              const resultsEndpoint = config.endpoint.replace('-workflow', '-results');
              const pollResponse = await axios.get(resultsEndpoint, { withCredentials: true });

              if (pollResponse.data.success && pollResponse.data.analysis) {
                console.log(`${workflowType} analysis completed!`);
                config.setter(pollResponse.data);
                setWorkflowLoading(prev => ({ ...prev, [config.stateKey]: false }));
                return;
              }

              if (pollCount < maxPolls) {
                setTimeout(pollForResults, 10000); // Poll again in 10 seconds
              } else {
                console.log(`${workflowType} polling timeout after 3 minutes - analysis may still be running`);
                config.setter(prev => ({
                  ...prev,
                  stage1: { status: 'timeout', description: 'Analysis timeout after 3 minutes - please try refreshing manually or check logs' }
                }));
                setWorkflowLoading(prev => ({ ...prev, [config.stateKey]: false }));
              }
            } catch (pollError) {
              console.error(`Error polling for ${workflowType} results:`, pollError);
              if (pollCount < maxPolls) {
                setTimeout(pollForResults, 10000); // Continue polling despite errors
              } else {
                console.log(`${workflowType} polling failed after ${maxPolls} attempts`);
                setWorkflowLoading(prev => ({ ...prev, [config.stateKey]: false }));
              }
            }
          };

          // Start polling after a 5-second delay to give backend time to start
          setTimeout(pollForResults, 5000);

        } else {
          // Synchronous response - set data immediately
          config.setter(response.data);
          setWorkflowLoading(prev => ({ ...prev, [config.stateKey]: false }));
          console.log(`${workflowType} workflow completed successfully`);
        }
      } else {
        console.error(`${workflowType} workflow failed:`, response.data.message);
        alert(`${workflowType} analysis failed: ${response.data.message}`);
        setWorkflowLoading(prev => ({ ...prev, [config.stateKey]: false }));
      }
    } catch (error) {
      console.error(`Error fetching ${workflowType} workflow:`, error);
      alert(`Failed to execute ${workflowType} analysis. Please try again.`);
      setWorkflowLoading(prev => ({ ...prev, [config.stateKey]: false }));
    }
  };

  const fetchAIData = async () => {
    // This function is deprecated - new workflow data is fetched via fetchWorkflowData
    // Keeping for backward compatibility with existing analysis results
    console.log('fetchAIData called - deprecated, using workflow endpoints instead');
  };

  const getConfidenceColor = (confidence) => {
    if (confidence >= 80) return '#48bb78'; // Green
    if (confidence >= 60) return '#ed8936'; // Orange
    return '#f56565'; // Red
  };

  const getSentimentColor = (sentiment) => {
    if (sentiment >= 60) return '#48bb78'; // Bullish
    if (sentiment <= 40) return '#f56565'; // Bearish
    return '#ed8936'; // Neutral
  };

  if (loading) {
    return (
      <div className="ai-dashboard">
        <div className="ai-loading">
          <div className="ai-loading-spinner"></div>
          <p>Loading AI Analysis...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="ai-dashboard">
        <div className="ai-error">
          <h2>AI Analysis Error</h2>
          <p>{error}</p>
          <button onClick={fetchAIData} className="btn">Retry</button>
        </div>
      </div>
    );
  }

  if (!aiEnabled) {
    return (
      <div className="ai-dashboard">
        <div className="ai-error">
          <div className="modal-backdrop" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div className="modal" style={{ display: 'block', position: 'relative', width: 'auto', maxWidth: '500px', backgroundColor: '#2d3748', border: '1px solid #4a5568' }}>
              <div className="modal-header">
                <h3>⚠️ AI Integration Required</h3>
              </div>
              <div className="modal-body">
                <p>You need to add your AI integration information in settings to use the AI Analysis features.</p>
              </div>
              <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                <button
                  className="btn btn-primary"
                  onClick={() => window.location.href = '/'}
                >
                  Return to Dashboard
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="ai-dashboard">
      {/* API Key Required Modal */}
      <ApiKeyRequiredModal
        show={showApiKeyModal}
        onClose={() => setShowApiKeyModal(false)}
        isLightMode={isLightMode}
      />
      {/* Header */}
      <div className="ai-header">
        <h1>🤖 AI Trading Dashboard</h1>
      </div>

      {/* Market Analysis - 3-Stage Agentic Workflow */}
      <div className="ai-section">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2>📊 Market Analysis</h2>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={() => fetchWorkflowData('market-analysis')}
              disabled={workflowLoading.marketAnalysis}
              className="btn btn-secondary"
              style={{ fontSize: '14px' }}
            >
              {workflowLoading.marketAnalysis ? '⏳ Analyzing...' : '🔍 Refresh Market Analysis'}
            </button>
            <button
              onClick={onViewMarketPrompt}
              className="btn"
              style={{ fontSize: '14px' }}
            >
              View Prompt
            </button>
          </div>
        </div>
        {showMarketPrompt && (
          <div className="modal-backdrop">
            <div className="modal">
              <div className="modal-header">
                <h3>📝 Market Analysis Prompt</h3>
              </div>
              <div className="modal-body" style={{ maxHeight: '60vh', overflowY: 'auto' }}>
                <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.6' }}>
                  {marketPrompt || '(No saved prompt yet)'}
                </pre>
              </div>
              <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                <button className="btn btn-secondary" onClick={() => setShowMarketPrompt(false)}>Close</button>
              </div>
            </div>
          </div>
        )}

        {marketAnalysisData ? (
          <div className="workflow-result">
            {/* Workflow Stages */}
            <div className="workflow-stages" style={{ display: 'none' }}>
              <div className={`workflow-stage ${marketAnalysisData.stage1?.status || 'pending'}`}>
                <div className="stage-header">
                  <span className="stage-number">1</span>
                  <span className="stage-title">Data Gathering</span>
                  <span className={`stage-status ${marketAnalysisData.stage1?.status || 'pending'}`}>
                    {marketAnalysisData.stage1?.status === 'completed' ? '✅' :
                      marketAnalysisData.stage1?.status === 'failed' ? '❌' : '⏳'}
                  </span>
                </div>
                <p className="stage-description">
                  {marketAnalysisData.stage1?.description || 'Generating market data search queries...'}
                </p>
              </div>

              <div className={`workflow-stage ${marketAnalysisData.stage2?.status || 'pending'}`}>
                <div className="stage-header">
                  <span className="stage-number">2</span>
                  <span className="stage-title">Web Search</span>
                  <span className={`stage-status ${marketAnalysisData.stage2?.status || 'pending'}`}>
                    {marketAnalysisData.stage2?.status === 'completed' ? '✅' :
                      marketAnalysisData.stage2?.status === 'failed' ? '❌' : '⏳'}
                  </span>
                </div>
                <p className="stage-description">
                  {marketAnalysisData.stage2?.description || 'Executing real-time market searches...'}
                </p>
              </div>

              <div className={`workflow-stage ${marketAnalysisData.stage3?.status || 'pending'}`}>
                <div className="stage-header">
                  <span className="stage-number">3</span>
                  <span className="stage-title">Analysis</span>
                  <span className={`stage-status ${marketAnalysisData.stage3?.status || 'pending'}`}>
                    {marketAnalysisData.stage3?.status === 'completed' ? '✅' :
                      marketAnalysisData.stage3?.status === 'failed' ? '❌' : '⏳'}
                  </span>
                </div>
                <p className="stage-description">
                  {marketAnalysisData.stage3?.description || 'Synthesizing comprehensive market analysis...'}
                </p>
              </div>
            </div>

            {/* Analysis Results */}
            {marketAnalysisData.analysis?.content && (
              <div className="workflow-content">
                <h3>📈 Market Analysis Results</h3>
                <div className="analysis-content">
                  <div
                    style={{
                      whiteSpace: 'pre-wrap',
                      fontFamily: 'inherit',
                      fontSize: '14px',
                      lineHeight: '1.6'
                    }}
                    dangerouslySetInnerHTML={{
                      __html: renderMarkdown(marketAnalysisData.analysis.content)
                    }}
                  />
                </div>
                <div className="analysis-meta">
                  <p className="analysis-footer">
                    <strong>Generated:</strong> {formatEasternTime(marketAnalysisData.analysis.generated_at)}
                  </p>
                  {marketAnalysisData.cache_info?.expires_at && (
                    <span className="meta-item">
                      <strong>Cache Expires:</strong> {new Date(marketAnalysisData.cache_info.expires_at).toLocaleString()}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="workflow-placeholder">
            <div className="placeholder-content">
              <h3>🤖 Market Analysis</h3>
              <p>Click "Refresh Market Analysis" to execute the agentic workflow:</p>
              <p style={{ fontSize: '12px', opacity: 0.7, marginTop: '16px' }}>
                Analysis runs automatically during your configured analysis window.
                Use manual refresh for off-hours analysis.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Risk Assessment - 3-Stage Agentic Workflow */}
      <div className="ai-section">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2>⚠️ Risk Assessment</h2>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={() => fetchWorkflowData('risk-assessment')}
              disabled={workflowLoading.riskAssessment}
              className="btn btn-secondary"
              style={{ fontSize: '14px' }}
            >
              {workflowLoading.riskAssessment ? '⏳ Assessing...' : '🔍 Refresh Risk Assessment'}
            </button>
            <button
              onClick={onViewRiskPrompt}
              className="btn"
              style={{ fontSize: '14px' }}
            >
              View Prompt
            </button>
          </div>
        </div>
        {showRiskPrompt && (
          <div className="modal-backdrop">
            <div className="modal">
              <div className="modal-header">
                <h3>📝 Risk Assessment Prompt</h3>
              </div>
              <div className="modal-body" style={{ maxHeight: '60vh', overflowY: 'auto' }}>
                <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.6' }}>
                  {riskPrompt || '(No saved prompt yet)'}
                </pre>
              </div>
              <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                <button className="btn btn-secondary" onClick={() => setShowRiskPrompt(false)}>Close</button>
              </div>
            </div>
          </div>
        )}

        {riskAssessmentData ? (
          <div className="workflow-result">
            {/* Workflow Stages */}
            <div className="workflow-stages" style={{ display: 'none' }}>
              <div className={`workflow-stage ${riskAssessmentData.stage1?.status || 'pending'}`}>
                <div className="stage-header">
                  <span className="stage-number">1</span>
                  <span className="stage-title">Risk Data Gathering</span>
                  <span className={`stage-status ${riskAssessmentData.stage1?.status || 'pending'}`}>
                    {riskAssessmentData.stage1?.status === 'completed' ? '✅' :
                      riskAssessmentData.stage1?.status === 'failed' ? '❌' : '⏳'}
                  </span>
                </div>
                <p className="stage-description">
                  {riskAssessmentData.stage1?.description || 'Generating risk-focused search queries...'}
                </p>
              </div>

              <div className={`workflow-stage ${riskAssessmentData.stage2?.status || 'pending'}`}>
                <div className="stage-header">
                  <span className="stage-number">2</span>
                  <span className="stage-title">Risk Intelligence</span>
                  <span className={`stage-status ${riskAssessmentData.stage2?.status || 'pending'}`}>
                    {riskAssessmentData.stage2?.status === 'completed' ? '✅' :
                      riskAssessmentData.stage2?.status === 'failed' ? '❌' : '⏳'}
                  </span>
                </div>
                <p className="stage-description">
                  {riskAssessmentData.stage2?.description || 'Retrieving current risk indicators...'}
                </p>
              </div>

              <div className={`workflow-stage ${riskAssessmentData.stage3?.status || 'pending'}`}>
                <div className="stage-header">
                  <span className="stage-number">3</span>
                  <span className="stage-title">Risk Analysis</span>
                  <span className={`stage-status ${riskAssessmentData.stage3?.status || 'pending'}`}>
                    {riskAssessmentData.stage3?.status === 'completed' ? '✅' :
                      riskAssessmentData.stage3?.status === 'failed' ? '❌' : '⏳'}
                  </span>
                </div>
                <p className="stage-description">
                  {riskAssessmentData.stage3?.description || 'Synthesizing risk assessment with recommendations...'}
                </p>
              </div>
            </div>

            {/* Risk Assessment Results */}
            {riskAssessmentData.analysis?.content && (
              <div className="workflow-content">
                <h3>⚡ Risk Assessment Results</h3>
                <div className="analysis-content">
                  <div
                    style={{
                      whiteSpace: 'pre-wrap',
                      fontFamily: 'inherit',
                      fontSize: '14px',
                      lineHeight: '1.6'
                    }}
                    dangerouslySetInnerHTML={{
                      __html: renderMarkdown(riskAssessmentData.analysis.content)
                    }}
                  />
                </div>
                <div className="analysis-meta">
                  <span className="meta-item">
                    <strong>Generated:</strong> {formatEasternTime(riskAssessmentData.analysis.generated_at)}
                  </span>
                  {riskAssessmentData.cache_info?.expires_at && (
                    <span className="meta-item">
                      <strong>Cache Expires:</strong> {new Date(riskAssessmentData.cache_info.expires_at).toLocaleString()}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="workflow-placeholder">
            <div className="placeholder-content">
              <h3>🤖 Risk Assessment</h3>
              <p>Click "Refresh Risk Assessment" to execute the agentic workflow:</p>
              <p style={{ fontSize: '12px', opacity: 0.7, marginTop: '16px' }}>
                Risk assessment runs automatically during your configured analysis window.
                Use manual refresh for immediate risk evaluation.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Analysis Results Section */}
      {analysisResults.length > 0 && (
        <div className="ai-section">
          <h2>📊 Analysis Results</h2>
          <div className="analysis-results-table">
            <table className="ai-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Time</th>
                  <th>Symbol</th>
                  <th>Price Change</th>
                  <th>Volatility</th>
                  <th>Analysis Results</th>
                </tr>
              </thead>
              <tbody>
                {analysisResults.map((result, index) => (
                  <tr key={index}>
                    <td>{result.date}</td>
                    <td>{result.time}</td>
                    <td style={{ fontWeight: 'bold' }}>{result.symbol}</td>
                    <td style={{ color: result.price_change >= 0 ? '#00c851' : '#ff4444' }}>
                      {result.price_change >= 0 ? '+' : ''}{result.price_change?.toFixed(2)}%
                    </td>
                    <td>{result.volatility?.toFixed(3)}</td>
                    <td style={{
                      maxWidth: '400px',
                      fontSize: '14px',
                      lineHeight: '1.4',
                      wordWrap: 'break-word',
                      whiteSpace: 'pre-wrap',
                      overflowWrap: 'break-word'
                    }}>
                      {result.analysis}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Portfolio Review - 3-Stage Agentic Workflow */}
      <div className="ai-section">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2>💼 Portfolio Review</h2>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={() => fetchWorkflowData('portfolio-review')}
              disabled={workflowLoading.portfolioReview}
              className="btn btn-secondary"
              style={{ fontSize: '14px' }}
            >
              {workflowLoading.portfolioReview ? '⏳ Reviewing...' : '🔍 Refresh Portfolio Review'}
            </button>
            <button
              onClick={onViewPortfolioPrompt}
              className="btn"
              style={{ fontSize: '14px' }}
            >
              View Prompt
            </button>
          </div>
        </div>
        {showPortfolioPrompt && (
          <div className="modal-backdrop">
            <div className="modal">
              <div className="modal-header">
                <h3>📝 Portfolio Review Prompt</h3>
              </div>
              <div className="modal-body" style={{ maxHeight: '60vh', overflowY: 'auto' }}>
                <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.6' }}>
                  {portfolioPrompt || '(No saved prompt yet)'}
                </pre>
              </div>
              <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                <button className="btn btn-secondary" onClick={() => setShowPortfolioPrompt(false)}>Close</button>
              </div>
            </div>
          </div>
        )}

        {portfolioReviewData ? (
          <div className="workflow-result">
            {/* Workflow Stages */}
            <div className="workflow-stages" style={{ display: 'none' }}>
              <div className={`workflow-stage ${portfolioReviewData.stage1?.status || 'pending'}`}>
                <div className="stage-header">
                  <span className="stage-number">1</span>
                  <span className="stage-title">Portfolio Data Gathering</span>
                  <span className={`stage-status ${portfolioReviewData.stage1?.status || 'pending'}`}>
                    {portfolioReviewData.stage1?.status === 'completed' ? '✅' :
                      portfolioReviewData.stage1?.status === 'failed' ? '❌' : '⏳'}
                  </span>
                </div>
                <p className="stage-description">
                  {portfolioReviewData.stage1?.description || 'Generating portfolio optimization search queries...'}
                </p>
              </div>

              <div className={`workflow-stage ${portfolioReviewData.stage2?.status || 'pending'}`}>
                <div className="stage-header">
                  <span className="stage-number">2</span>
                  <span className="stage-title">Market Research</span>
                  <span className={`stage-status ${portfolioReviewData.stage2?.status || 'pending'}`}>
                    {portfolioReviewData.stage2?.status === 'completed' ? '✅' :
                      portfolioReviewData.stage2?.status === 'failed' ? '❌' : '⏳'}
                  </span>
                </div>
                <p className="stage-description">
                  {portfolioReviewData.stage2?.description || 'Retrieving market data and portfolio strategies...'}
                </p>
              </div>

              <div className={`workflow-stage ${portfolioReviewData.stage3?.status || 'pending'}`}>
                <div className="stage-header">
                  <span className="stage-number">3</span>
                  <span className="stage-title">Portfolio Analysis</span>
                  <span className={`stage-status ${portfolioReviewData.stage3?.status || 'pending'}`}>
                    {portfolioReviewData.stage3?.status === 'completed' ? '✅' :
                      portfolioReviewData.stage3?.status === 'failed' ? '❌' : '⏳'}
                  </span>
                </div>
                <p className="stage-description">
                  {portfolioReviewData.stage3?.description || 'Generating comprehensive portfolio review...'}
                </p>
              </div>
            </div>

            {/* Portfolio Review Results */}
            {portfolioReviewData.analysis?.content && (
              <div className="workflow-content">
                <h3>📊 Portfolio Review Results</h3>
                <div className="analysis-content">
                  <div
                    style={{
                      whiteSpace: 'pre-wrap',
                      fontFamily: 'inherit',
                      fontSize: '14px',
                      lineHeight: '1.6'
                    }}
                    dangerouslySetInnerHTML={{
                      __html: renderMarkdown(portfolioReviewData.analysis.content)
                    }}
                  />
                </div>
                <div className="analysis-meta">
                  <span className="meta-item">
                    <strong>Generated:</strong> {formatEasternTime(portfolioReviewData.analysis.generated_at)}
                  </span>
                  {portfolioReviewData.cache_info?.expires_at && (
                    <span className="meta-item">
                      <strong>Cache Expires:</strong> {new Date(portfolioReviewData.cache_info.expires_at).toLocaleString()}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="workflow-placeholder">
            <div className="placeholder-content">
              <h3>🤖 Portfolio Review</h3>
              <p>Click "Refresh Portfolio Review" to execute the agentic workflow:</p>
              <p style={{ fontSize: '12px', opacity: 0.7, marginTop: '16px' }}>
                Portfolio review runs automatically during your configured analysis window.
                Use manual refresh for immediate portfolio optimization insights.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* AI Analysis Modal */}
      <AIAnalysisModal
        symbol={selectedSymbol}
        isVisible={showAnalysisModal}
        onClose={() => {
          setShowAnalysisModal(false);
          setSelectedSymbol(null);
        }}
      />
    </div>
  );
} 
