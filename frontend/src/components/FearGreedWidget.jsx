import React, { useState, useEffect } from 'react';
import './FearGreedWidget.css';

const FearGreedWidget = () => {
  const [fearGreedData, setFearGreedData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchFearGreedData = async () => {
    try {
      setLoading(true);
      const response = await fetch('/api/widgets/fear-greed');
      if (!response.ok) {
        throw new Error('Failed to fetch Fear & Greed data');
      }
      const data = await response.json();
      setFearGreedData(data.data[0]);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFearGreedData();
    
    // Update every hour
    const interval = setInterval(fetchFearGreedData, 60 * 60 * 1000);
    
    return () => clearInterval(interval);
  }, []);

  const getColorByValue = (value) => {
    if (value <= 20) return '#d32f2f'; // Extreme Fear - Red
    if (value <= 40) return '#f57c00'; // Fear - Orange
    if (value <= 60) return '#fbc02d'; // Neutral - Yellow
    if (value <= 80) return '#689f38'; // Greed - Light Green
    return '#388e3c'; // Extreme Greed - Green
  };

  const getClassificationIcon = (classification) => {
    switch (classification?.toLowerCase()) {
      case 'extreme fear':
        return '😨';
      case 'fear':
        return '😰';
      case 'neutral':
        return '😐';
      case 'greed':
        return '😄';
      case 'extreme greed':
        return '🤑';
      default:
        return '📊';
    }
  };

  if (loading) {
    return (
      <div className="fear-greed-widget">
        <div className="widget-header">
          <h3>Fear & Greed Index</h3>
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
      <div className="fear-greed-widget">
        <div className="widget-header">
          <h3>Fear & Greed Index</h3>
        </div>
        <div className="widget-content error">
          <p>Failed to load data</p>
          <button onClick={fetchFearGreedData} className="retry-btn">
            Retry
          </button>
        </div>
      </div>
    );
  }

  const value = parseInt(fearGreedData?.value || 0);
  const classification = fearGreedData?.value_classification || 'Unknown';

  return (
    <div className="fear-greed-widget">
      <div className="widget-header">
        <h3>Fear & Greed Index</h3>
      </div>
      <div className="widget-content">
        <div className="fg-main-display">
          <div 
            className="fg-value-circle"
            style={{ borderColor: getColorByValue(value) }}
          >
            <span className="fg-value" style={{ color: getColorByValue(value) }}>
              {value}
            </span>
          </div>
          <div className="fg-classification">
            <span className="fg-icon">{getClassificationIcon(classification)}</span>
            <span className="fg-text">{classification}</span>
          </div>
        </div>
        <div className="fg-progress-bar">
          <div className="fg-progress-track">
            <div 
              className="fg-progress-fill"
              style={{ 
                width: `${value}%`,
                backgroundColor: getColorByValue(value)
              }}
            ></div>
          </div>
          <div className="fg-scale">
            <span>0</span>
            <span>25</span>
            <span>50</span>
            <span>75</span>
            <span>100</span>
          </div>
        </div>
        <div className="fg-footer">
          <small>Updated: {new Date(fearGreedData?.timestamp * 1000).toLocaleString()}</small>
        </div>
      </div>
    </div>
  );
};

export default FearGreedWidget;
