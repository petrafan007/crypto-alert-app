import React, { useState, useEffect } from 'react';
import './CBBIWidget.css';

const CBBIWidget = () => {
  const [cbbiData, setCbbiData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchCBBIData = async () => {
    try {
      setLoading(true);
      const response = await fetch('/api/widgets/cbbi');
      if (!response.ok) {
        throw new Error('Failed to fetch CBBI data');
      }
      const data = await response.json();
      
      // Get the latest confidence score
      const confidenceData = data.confidence;
      if (confidenceData && typeof confidenceData === 'object') {
        // Get the most recent timestamp and value
        const timestamps = Object.keys(confidenceData).map(Number).sort((a, b) => b - a);
        const latestTimestamp = timestamps[0];
        const latestValue = confidenceData[latestTimestamp];
        
        setCbbiData({
          value: latestValue,
          timestamp: latestTimestamp,
          lastUpdate: new Date(latestTimestamp * 1000)
        });
      } else {
        throw new Error('Invalid CBBI data format');
      }
      
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCBBIData();
    
    // Update every 30 minutes for real-time updates
    const interval = setInterval(fetchCBBIData, 30 * 60 * 1000);
    
    return () => clearInterval(interval);
  }, []);

  const getColorByValue = (value) => {
    // CBBI ranges from 0-1, with higher values indicating higher confidence we're at peak
    if (value < 0.2) return '#4caf50'; // Low risk - Green
    if (value < 0.4) return '#8bc34a'; // Moderate-low risk - Light green
    if (value < 0.6) return '#ffc107'; // Moderate risk - Yellow
    if (value < 0.8) return '#ff9800'; // High risk - Orange
    return '#f44336'; // Very high risk - Red
  };

  const getRiskLevel = (value) => {
    if (value < 0.2) return 'Low Risk';
    if (value < 0.4) return 'Moderate-Low';
    if (value < 0.6) return 'Moderate';
    if (value < 0.8) return 'High Risk';
    return 'Very High Risk';
  };

  const getRiskIcon = (value) => {
    if (value < 0.2) return '🟢';
    if (value < 0.4) return '🟡';
    if (value < 0.6) return '🟠';
    if (value < 0.8) return '🔴';
    return '🚨';
  };

  if (loading) {
    return (
      <div className="cbbi-widget">
        <div className="widget-header">
          <h3>CBBI</h3>
          <small>Peak Confidence</small>
        </div>
        <div className="widget-content loading">
          <div className="loading-spinner"></div>
          <p>Loading...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="cbbi-widget">
        <div className="widget-header">
          <h3>CBBI</h3>
          <small>Peak Confidence</small>
        </div>
        <div className="widget-content error">
          <p>Failed to load data</p>
          <button onClick={fetchCBBIData} className="retry-btn">
            Retry
          </button>
        </div>
      </div>
    );
  }

  const value = cbbiData?.value || 0;
  const percentage = Math.round(value * 100);

  return (
    <div className="cbbi-widget">
      <div className="widget-header">
        <h3>CBBI</h3>
        <small>Peak Confidence</small>
      </div>
      <div className="widget-content">
        <div className="cbbi-main-display">
          <div 
            className="cbbi-value-circle"
            style={{ borderColor: getColorByValue(value) }}
          >
            <span className="cbbi-value" style={{ color: getColorByValue(value) }}>
              {percentage}%
            </span>
          </div>
          <div className="cbbi-risk-level">
            <span className="cbbi-icon">{getRiskIcon(value)}</span>
            <span className="cbbi-text">{getRiskLevel(value)}</span>
          </div>
        </div>
        
        <div className="cbbi-progress-bar">
          <div className="cbbi-progress-track">
            <div 
              className="cbbi-progress-fill"
              style={{ 
                width: `${percentage}%`,
                backgroundColor: getColorByValue(value)
              }}
            ></div>
          </div>
          <div className="cbbi-scale">
            <span>0%</span>
            <span>25%</span>
            <span>50%</span>
            <span>75%</span>
            <span>100%</span>
          </div>
        </div>
        
        <div className="cbbi-info">
          <p className="cbbi-description">
            Confidence we are at crypto market peak
          </p>
        </div>
        
        <div className="cbbi-footer">
          <small>Updated: {cbbiData?.lastUpdate?.toLocaleString()}</small>
        </div>
      </div>
    </div>
  );
};

export default CBBIWidget;
