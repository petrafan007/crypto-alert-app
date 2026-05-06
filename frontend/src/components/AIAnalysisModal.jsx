import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { getTradeUrl } from '../utils/exchangeUtils';
import './AIAnalysisModal.css';

export default function AIAnalysisModal({ symbol, isVisible, onClose }) {
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (isVisible && symbol) {
      fetchDetailedAnalysis();
    }
  }, [isVisible, symbol]);

  const fetchDetailedAnalysis = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get(`/api/ai/market-analysis/${symbol}`);
      setAnalysis(response.data);
    } catch (err) {
      console.error('Error fetching detailed analysis:', err);
      setError('Failed to load detailed analysis');
    } finally {
      setLoading(false);
    }
  };

  const getConfidenceColor = (confidence) => {
    if (confidence >= 80) return '#48bb78';
    if (confidence >= 60) return '#ed8936';
    return '#f56565';
  };

  const getSentimentColor = (sentiment) => {
    if (sentiment >= 60) return '#48bb78';
    if (sentiment <= 40) return '#f56565';
    return '#ed8936';
  };

  if (!isVisible) return null;

  return (
    <div className="ai-analysis-modal-overlay">
      <div className="ai-analysis-modal">
        <div className="ai-analysis-header">
          <h2>🤖 AI Analysis: {symbol}</h2>
          <button onClick={onClose} className="close-btn">×</button>
        </div>
        {loading && (
          <div className="ai-analysis-loading">
            <div className="spinner" />
            <p>Loading AI Analysis...</p>
          </div>
        )}
        {error && (
          <div className="ai-analysis-error">
            <h3>Analysis Error</h3>
            <p>{error}</p>
            <button onClick={fetchDetailedAnalysis} className="btn">Retry</button>
          </div>
        )}
        {analysis && !loading && !error && (
          <div>
            <div className="section-block">
              <h3>📊 Analysis Summary</h3>
              <div className="summary-grid">
                <div className="summary-card">
                  <h4>Overall Signal</h4>
                  <div className="metric" style={{ color: getConfidenceColor(analysis.overall_confidence) }}>{analysis.signal}</div>
                  <div className="muted">Confidence: {analysis.overall_confidence}%</div>
                </div>
                <div className="summary-card">
                  <h4>Market Sentiment</h4>
                  <div className="metric" style={{ color: getSentimentColor(analysis.sentiment_score) }}>{analysis.sentiment_score}%</div>
                  <div className="muted">{analysis.sentiment_score >= 60 ? 'Bullish' : analysis.sentiment_score <= 40 ? 'Bearish' : 'Neutral'}</div>
                </div>
                <div className="summary-card">
                  <h4>Risk Level</h4>
                  <div className="metric" style={{ color: getConfidenceColor(100 - analysis.risk_level) }}>{analysis.risk_level}%</div>
                  <div className="muted">{analysis.risk_level >= 70 ? 'High' : analysis.risk_level >= 40 ? 'Medium' : 'Low'}</div>
                </div>
              </div>
              {analysis.data_source && (
                <div className="muted tiny" style={{ marginTop: 8 }}>
                  Data source: {analysis.data_source} • Points: {analysis.series_window?.points || '—'}
                </div>
              )}
            </div>
            <div className="section-block">
              <h3>📈 Technical Analysis</h3>
              <div className="panel">
                <div className="tech-grid">
                  {analysis.technical_indicators && Object.entries(analysis.technical_indicators).map(([indicator, value]) => (
                    <div key={indicator} className="tech-item">
                      <div className="muted tiny">{indicator.replace(/_/g, ' ').toUpperCase()}</div>
                      <div className="value-strong">{value ?? '—'}</div>
                    </div>
                  ))}
                </div>
                {analysis.price_metrics && (
                  <div className="patterns" style={{ marginTop: 8 }}>
                    <h4>Price Metrics</h4>
                    <ul>
                      <li>1D: {analysis.price_metrics.pct_1d ?? '—'}%</li>
                      <li>3D: {analysis.price_metrics.pct_3d ?? '—'}%</li>
                      <li>7D: {analysis.price_metrics.pct_7d ?? '—'}%</li>
                    </ul>
                  </div>
                )}
                {analysis.patterns && analysis.patterns.length > 0 && (
                  <div className="patterns">
                    <h4>Identified Patterns</h4>
                    <ul>{analysis.patterns.map((p,i) => <li key={i}>{p}</li>)}</ul>
                  </div>
                )}
              </div>
            </div>
            <div className="section-block">
              <h3>🎯 Price Targets</h3>
              <div className="targets-grid">
                <div className="target-card">
                  <h4 className="accent-green">Entry Price</h4>
                  <div className="target-value">${analysis.entry_price}</div>
                  <div className="muted tiny">Recommended entry point</div>
                </div>
                <div className="target-card">
                  <h4 className="accent-red">Stop Loss</h4>
                  <div className="target-value">${analysis.stop_loss}</div>
                  <div className="muted tiny">Risk management level</div>
                </div>
                <div className="target-card">
                  <h4 className="accent-green">Take Profit</h4>
                  <div className="target-value">${analysis.take_profit}</div>
                  <div className="muted tiny">Profit target</div>
                </div>
              </div>
            </div>
            <div className="section-block">
              <h3>🧠 AI Reasoning</h3>
              <div className="panel"><div className="body-text">{analysis.reasoning}</div></div>
            </div>
            {analysis.recommendation && (
              <div className="section-block">
                <h3>✅ Recommendation</h3>
                <div className="panel">
                  <div className="body-text">
                    Signal: <strong>{analysis.recommendation.signal}</strong> • Confidence: <strong>{analysis.recommendation.confidence}%</strong><br/>
                    Technical score: {analysis.recommendation.technical_score} (risk penalty: {analysis.recommendation.risk_penalty})
                  </div>
                </div>
              </div>
            )}
            {analysis.risk_factors && analysis.risk_factors.length > 0 && (
              <div className="section-block">
                <h3>⚠️ Risk Factors</h3>
                <div className="panel"><ul className="risk-list">{analysis.risk_factors.map((f,i)=><li key={i}>{f}</li>)}</ul></div>
              </div>
            )}
            <div className="actions">
              <button className="btn btn-primary" onClick={() => { window.open(getTradeUrl(symbol), '_blank'); onClose(); }}>Open in Exchange</button>
              <button className="btn btn-secondary" onClick={onClose}>Close</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}