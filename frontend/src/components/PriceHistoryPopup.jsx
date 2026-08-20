import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend
);

const PriceHistoryPopup = ({ symbol, isVisible, position, onClose, onMouseEnter, onChartClick }) => {
  const [priceData, setPriceData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastFetchedSymbol, setLastFetchedSymbol] = useState(null);
  const popupRef = useRef(null);

  useEffect(() => {
    // Only fetch if visible, symbol exists, and we haven't already fetched this symbol
    if (isVisible && symbol && symbol !== lastFetchedSymbol) {
      fetchPriceHistory();
    }
  }, [isVisible, symbol]);

  const fetchPriceHistory = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get(`/api/chart_history/${symbol}`);
      if (response.data.prices && response.data.prices.length > 0) {
        setPriceData(response.data.prices);
        setLastFetchedSymbol(symbol); // Mark this symbol as fetched
      } else {
        setError('No price data available');
      }
    } catch (err) {
      console.error('Error fetching price history:', err);
      setError('Failed to load price data');
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (timestamp) => {
    const date = new Date(timestamp);
    return date.toLocaleDateString('en-US', { 
      month: 'short', 
      day: 'numeric'
    });
  };

  const processedData = React.useMemo(() => {
    if (!priceData || priceData.length === 0) return null;
    
    const daysMap = {};
    priceData.forEach(point => {
      const d = new Date(point[0]);
      const dateStr = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      daysMap[dateStr] = point[1]; // Keep latest price for the day
    });

    const labels = [];
    const dataPoints = [];
    
    for (let i = 6; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      const dateStr = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      labels.push(dateStr);
      dataPoints.push(daysMap[dateStr] || null);
    }
    
    // Forward fill gaps
    let lastKnown = null;
    for (let i = 0; i < dataPoints.length; i++) {
      if (dataPoints[i] !== null) {
        lastKnown = dataPoints[i];
      } else if (lastKnown !== null) {
        dataPoints[i] = lastKnown;
      }
    }
    
    // Backfill if first days are null
    const firstKnown = dataPoints.find(val => val !== null) || 0;
    for (let i = 0; i < dataPoints.length; i++) {
      if (dataPoints[i] === null) dataPoints[i] = firstKnown;
    }
    
    return { labels, data: dataPoints };
  }, [priceData]);

  const chartData = processedData ? {
    labels: processedData.labels,
    datasets: [
      {
        label: `${symbol || 'Unknown'} Price`,
        data: processedData.data,
        borderColor: '#3182ce', // Blue line like portfolio trend
        backgroundColor: 'rgba(49, 130, 206, 0.3)', // Translucent blue area
        borderWidth: 2,
        fill: true,
        tension: 0.4, // Smoother line
        pointBackgroundColor: '#3182ce',
        pointBorderColor: '#fff',
        pointBorderWidth: 0,
        pointRadius: 0, // No dots at all as requested
        pointHoverRadius: 4, // Still allow hover interaction
      },
    ],
  } : null;

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: false,
      },
      tooltip: {
        backgroundColor: '#232b31',
        titleColor: '#4fd1c5',
        bodyColor: '#fff',
        borderColor: '#333',
        borderWidth: 1,
        cornerRadius: 8,
        displayColors: false,
        callbacks: {
          label: function(context) {
            return `$${context.parsed.y.toFixed(2)}`;
          }
        }
      },
    },
    scales: {
      x: {
        display: true,
        grid: {
          color: 'rgba(255, 255, 255, 0.1)',
          drawBorder: false,
        },
        ticks: {
          color: '#fff', // White X-axis labels
          font: {
            size: 10,
          },
        },
        border: {
          color: '#333',
        },
      },
      y: {
        display: true,
        grid: {
          color: 'rgba(255, 255, 255, 0.1)',
          drawBorder: false,
        },
        ticks: {
          color: '#fff', // White Y-axis labels
          font: {
            size: 10,
          },
          callback: function(value) {
            return `$${value.toFixed(2)}`;
          }
        },
        border: {
          color: '#333',
        },
      },
    },
    interaction: {
      intersect: false,
      mode: 'index',
    },
  };

  const handleChartClick = () => {
    if (onChartClick) {
      onChartClick(symbol);
    }
  };

  if (!isVisible) return null;

  return (
    <div
      ref={popupRef}
      style={{
        position: 'fixed',
        left: position.x,
        top: position.y,
        zIndex: 1000,
        backgroundColor: '#1a1a1a',
        border: '1px solid #333',
        borderRadius: '8px',
        padding: '16px',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
        minWidth: '300px',
        maxWidth: '400px',
        pointerEvents: 'auto',
      }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onClose}
    >
      <div style={{ 
        display: 'flex', 
        justifyContent: 'space-between', 
        alignItems: 'center', 
        marginBottom: '12px' 
      }}>
        <h3 style={{ 
          margin: 0, 
          color: '#fff', 
          fontSize: '16px',
          fontWeight: 'bold'
        }}>
          {symbol || 'Unknown'} - 7 Day Performance
        </h3>
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            color: '#888',
            cursor: 'pointer',
            fontSize: '18px',
            padding: '0',
            width: '20px',
            height: '20px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          ×
        </button>
      </div>

      {loading && (
        <div style={{ 
          height: '200px', 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center',
          color: '#888'
        }}>
          Loading...
        </div>
      )}

      {error && (
        <div style={{ 
          height: '200px', 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center',
          color: '#ff6b6b'
        }}>
          {error}
        </div>
      )}

      {chartData && !loading && !error && (
        <div 
          style={{ 
            height: '200px', 
            position: 'relative'
          }}
        >
          <Line data={chartData} options={chartOptions} />
        </div>
      )}
    </div>
  );
};

export default PriceHistoryPopup; 
