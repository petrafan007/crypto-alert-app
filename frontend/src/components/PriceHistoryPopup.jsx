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

const PriceHistoryPopup = ({ symbol, isVisible, position, onClose, onChartClick }) => {
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

  const chartData = priceData ? {
    labels: priceData.map(point => formatDate(point[0])),
    datasets: [
      {
        label: `${symbol || 'Unknown'} Price`,
        data: priceData.map(point => point[1]),
        borderColor: '#3182ce', // Blue line like portfolio trend
        backgroundColor: 'rgba(49, 130, 206, 0.3)', // Translucent blue area
        borderWidth: 2,
        fill: true,
        tension: 0.3,
        pointBackgroundColor: '#3182ce', // Blue dots
        pointBorderColor: '#fff', // White border
        pointBorderWidth: 1,
        pointRadius: 2, // Smaller dots like portfolio trend
        pointHoverRadius: 4,
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
      onMouseEnter={() => {}} // Keep popup open when hovering over it
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
