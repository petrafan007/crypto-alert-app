import React, { useState, useEffect } from 'react';
import axios from 'axios';

export default function AIAnalysis({ portfolioData, marketData }) {
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [recommendations, setRecommendations] = useState([]);

  useEffect(() => {
    if (portfolioData && marketData) {
      generateAnalysis();
    }
  }, [portfolioData, marketData]);

  const generateAnalysis = async () => {
    setLoading(true);
    try {
      // This is a simplified analysis - in a real implementation,
      // you would integrate with an AI service like OpenAI, Google AI, or a custom ML model
      
      const analysis = {
        riskAssessment: calculateRiskAssessment(portfolioData),
        tradingSignals: generateTradingSignals(marketData),
        portfolioOptimization: generatePortfolioRecommendations(portfolioData),
        marketSentiment: analyzeMarketSentiment(marketData)
      };

      setAnalysis(analysis);
      setRecommendations(analysis.tradingSignals);
    } catch (error) {
      console.error('AI Analysis error:', error);
    } finally {
      setLoading(false);
    }
  };

  const calculateRiskAssessment = (portfolio) => {
    if (!portfolio || !portfolio.holdings) return 'Medium';
    
    const holdings = portfolio.holdings;
    const totalValue = portfolio.total_value || 0;
    
    if (totalValue === 0) return 'Low';
    
    // Calculate concentration risk
    const largestHolding = Math.max(...holdings.map(h => h.percentage || 0));
    const diversificationScore = portfolio.diversification_score || 0;
    
    if (largestHolding > 50 || diversificationScore < 30) return 'High';
    if (largestHolding > 30 || diversificationScore < 60) return 'Medium';
    return 'Low';
  };

  const generateTradingSignals = (marketData) => {
    if (!marketData) return [];
    
    const signals = [];
    const { price, change_24h, volume_24h } = marketData;
    
    // Simple technical analysis signals
    if (change_24h > 5) {
      signals.push({
        type: 'SELL',
        confidence: 'High',
        reason: 'Strong upward momentum - consider taking profits',
        symbol: marketData.symbol
      });
    } else if (change_24h < -5) {
      signals.push({
        type: 'BUY',
        confidence: 'Medium',
        reason: 'Significant price drop - potential buying opportunity',
        symbol: marketData.symbol
      });
    }
    
    // Volume analysis
    if (volume_24h && volume_24h > 1000000) {
      signals.push({
        type: 'HOLD',
        confidence: 'Medium',
        reason: 'High trading volume indicates strong market interest',
        symbol: marketData.symbol
      });
    }
    
    return signals;
  };

  const generatePortfolioRecommendations = (portfolio) => {
    if (!portfolio || !portfolio.holdings) return [];
    
    const recommendations = [];
    const holdings = portfolio.holdings;
    
    // Diversification recommendations
    if (holdings.length < 3) {
      recommendations.push({
        type: 'DIVERSIFY',
        priority: 'High',
        message: 'Consider adding more assets to reduce concentration risk'
      });
    }
    
    // Rebalancing recommendations
    const largestHolding = holdings.reduce((max, h) => 
      (h.percentage || 0) > max ? (h.percentage || 0) : max, 0
    );
    
    if (largestHolding > 40) {
      recommendations.push({
        type: 'REBALANCE',
        priority: 'Medium',
        message: 'Consider rebalancing to reduce exposure to your largest holding'
      });
    }
    
    return recommendations;
  };

  const analyzeMarketSentiment = (marketData) => {
    if (!marketData) return 'Neutral';
    
    const { change_24h, volume_24h } = marketData;
    
    if (change_24h > 3) return 'Bullish';
    if (change_24h < -3) return 'Bearish';
    return 'Neutral';
  };

  if (loading) {
    return (
      <div style={{ 
        background: '#232b31', 
        padding: 20, 
        borderRadius: 12, 
        border: '1px solid #333',
        color: '#fff'
      }}>
        <h3 style={{ color: '#4fd1c5', marginBottom: 16 }}>AI Analysis</h3>
        <div style={{ textAlign: 'center', padding: '20px' }}>
          Analyzing portfolio and market data...
        </div>
      </div>
    );
  }

  if (!analysis) {
    return null;
  }

  return (
    <div style={{ 
      background: '#232b31', 
      padding: 20, 
      borderRadius: 12, 
      border: '1px solid #333',
      color: '#fff'
    }}>
      <h3 style={{ color: '#4fd1c5', marginBottom: 16 }}>AI Analysis & Recommendations</h3>
      
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: 16, marginBottom: 20 }}>
        <div style={{ background: '#1a1f23', padding: 16, borderRadius: 8 }}>
          <div style={{ color: '#666', fontSize: '14px' }}>Risk Assessment</div>
          <div style={{ 
            fontSize: '18px', 
            fontWeight: 'bold',
            color: analysis.riskAssessment === 'High' ? '#f56565' : 
                   analysis.riskAssessment === 'Medium' ? '#ed8936' : '#48bb78'
          }}>
            {analysis.riskAssessment}
          </div>
        </div>
        
        <div style={{ background: '#1a1f23', padding: 16, borderRadius: 8 }}>
          <div style={{ color: '#666', fontSize: '14px' }}>Market Sentiment</div>
          <div style={{ 
            fontSize: '18px', 
            fontWeight: 'bold',
            color: analysis.marketSentiment === 'Bullish' ? '#48bb78' : 
                   analysis.marketSentiment === 'Bearish' ? '#f56565' : '#ed8936'
          }}>
            {analysis.marketSentiment}
          </div>
        </div>
        
        <div style={{ background: '#1a1f23', padding: 16, borderRadius: 8 }}>
          <div style={{ color: '#666', fontSize: '14px' }}>Trading Signals</div>
          <div style={{ fontSize: '18px', fontWeight: 'bold' }}>
            {recommendations.length}
          </div>
        </div>
      </div>

      {/* Trading Signals */}
      {recommendations.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <h4 style={{ color: '#4fd1c5', marginBottom: 12 }}>Trading Signals</h4>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {recommendations.map((signal, index) => (
              <div key={index} style={{ 
                background: '#1a1f23', 
                padding: 12, 
                borderRadius: 6,
                border: '1px solid #333'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <span style={{ 
                      color: signal.type === 'BUY' ? '#48bb78' : 
                             signal.type === 'SELL' ? '#f56565' : '#ed8936',
                      fontWeight: 'bold',
                      marginRight: 8
                    }}>
                      {signal.type}
                    </span>
                    <span style={{ color: '#fff' }}>{signal.symbol}</span>
                  </div>
                  <span style={{ 
                    color: signal.confidence === 'High' ? '#48bb78' : '#ed8936',
                    fontSize: '12px'
                  }}>
                    {signal.confidence} Confidence
                  </span>
                </div>
                <div style={{ color: '#ccc', fontSize: '14px', marginTop: 4 }}>
                  {signal.reason}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Portfolio Recommendations */}
      {analysis.portfolioOptimization && analysis.portfolioOptimization.length > 0 && (
        <div>
          <h4 style={{ color: '#4fd1c5', marginBottom: 12 }}>Portfolio Recommendations</h4>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {analysis.portfolioOptimization.map((rec, index) => (
              <div key={index} style={{ 
                background: '#1a1f23', 
                padding: 12, 
                borderRadius: 6,
                border: '1px solid #333'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ 
                    color: rec.priority === 'High' ? '#f56565' : '#ed8936',
                    fontWeight: 'bold'
                  }}>
                    {rec.type}
                  </span>
                  <span style={{ 
                    color: rec.priority === 'High' ? '#f56565' : '#ed8936',
                    fontSize: '12px'
                  }}>
                    {rec.priority} Priority
                  </span>
                </div>
                <div style={{ color: '#ccc', fontSize: '14px', marginTop: 4 }}>
                  {rec.message}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ 
        marginTop: 16, 
        padding: 12, 
        background: 'rgba(79, 209, 197, 0.1)', 
        borderRadius: 6,
        border: '1px solid rgba(79, 209, 197, 0.3)',
        fontSize: '12px',
        color: '#4fd1c5'
      }}>
        <strong>Disclaimer:</strong> This analysis is for informational purposes only and should not be considered as financial advice. Always do your own research and consider consulting with a financial advisor before making investment decisions.
      </div>
    </div>
  );
} 