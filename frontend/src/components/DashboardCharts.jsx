import React, { useMemo } from 'react';
import { Pie, Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  ArcElement,
  Tooltip,
  Legend,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  TimeScale,
} from 'chart.js';
import 'chartjs-adapter-date-fns';

ChartJS.register(
  ArcElement,
  Tooltip,
  Legend,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  TimeScale
);

export function PortfolioPie({ portfolio, isLightMode }) {
  // Only show coins with value > 0
  const data = useMemo(() => {
    const filtered = (portfolio || []).filter(c => c.current_value > 0);
    return {
      labels: filtered.map(c => c.symbol),
      datasets: [
        {
          data: filtered.map(c => c.current_value),
          backgroundColor: [
            '#ed64a6', // Pink for USDT
            '#68d391', // Light green for SOL
            '#f6e05e', // Orange for XRP
            '#63b3ed', // Light blue for LINK
            '#fc8181', // Red for DIMO
            '#4fd1c5', '#4299e1', '#f687b3', '#fbb6ce', '#b794f4', '#f56565', '#48bb78', '#ecc94b', '#ed8936', '#718096', '#e53e3e', '#38a169', '#d69e2e', '#805ad5', '#319795'
          ],
          borderWidth: 2,
          borderColor: '#232b31',
        },
      ],
    };
  }, [portfolio]);

  const options = useMemo(() => ({
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top',
        labels: {
          color: isLightMode ? '#333' : '#fff', // Dynamic color based on theme
          font: { size: 12 },
          usePointStyle: true,
          padding: 8,
        },
      },
      tooltip: {
        backgroundColor: isLightMode ? '#fff' : '#232b31',
        titleColor: isLightMode ? '#333' : '#4fd1c5',
        bodyColor: isLightMode ? '#333' : '#fff',
        borderColor: isLightMode ? '#ddd' : '#333',
        borderWidth: 1,
      },
    },
  }), [isLightMode]);

  return (
    <Pie data={data} options={options} />
  );
}

export function PortfolioTrend({ history, range, isLightMode }) {
  // history: [[timestamp, value], ...]
  const safeHistory = Array.isArray(history) ? history : [];
  
  // Get time scale configuration for each range
  const getTimeConfig = (rangeKey) => {
    const configs = {
      '4H': { unit: 'hour', stepSize: 1, displayFormat: 'HH:mm' },
      '12H': { unit: 'hour', stepSize: 2, displayFormat: 'HH:mm MMM dd' },
      '1D': { unit: 'hour', stepSize: 4, displayFormat: 'HH:mm' },
      '3D': { unit: 'hour', stepSize: 12, displayFormat: 'MMM dd HH:mm' },
      '7D': { unit: 'day', stepSize: 1, displayFormat: 'MMM dd' },
      '4W': { unit: 'week', stepSize: 1, displayFormat: 'MMM dd' },
      '3M': { unit: 'month', stepSize: 1, displayFormat: 'MMM yyyy' },
      '6M': { unit: 'month', stepSize: 1, displayFormat: 'MMM yyyy' },
      '1Y': { unit: 'month', stepSize: 1, displayFormat: 'MMM yyyy' }
    };
    return configs[rangeKey] || configs['1D'];
  };

  const timeConfig = getTimeConfig(range);

  const data = useMemo(() => ({
    labels: safeHistory.map(([t, _]) => new Date(t)),
    datasets: [
      {
        label: 'Portfolio Value',
        data: safeHistory.map(([_, v]) => v),
        fill: false, // Remove fill to avoid confusion
        borderColor: '#3182ce', // Blue line
        backgroundColor: '#3182ce',
        tension: 0.3,
        pointRadius: 4, // Make points more visible
        pointBackgroundColor: '#3182ce',
        pointBorderColor: '#fff',
        pointBorderWidth: 2,
        pointHoverRadius: 6,
        borderWidth: 2,
      },
    ],
  }), [safeHistory]);

  const options = useMemo(() => ({
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      intersect: false,
      mode: 'index',
    },
    plugins: {
      legend: {
        display: false,
      },
      tooltip: {
        mode: 'index',
        intersect: false,
        backgroundColor: '#232b31',
        titleColor: '#4fd1c5',
        bodyColor: '#fff',
        borderColor: '#333',
        borderWidth: 1,
        cornerRadius: 8,
        displayColors: false,
        callbacks: {
          title: function(context) {
            const date = new Date(context[0].parsed.x);
            return date.toLocaleString('en-US', {
              month: 'short',
              day: 'numeric',
              hour: range.includes('H') || range === '1D' || range === '3D' ? 'numeric' : undefined,
              minute: range.includes('H') || range === '1D' || range === '3D' ? '2-digit' : undefined,
              year: range.includes('M') || range === '1Y' ? 'numeric' : undefined
            });
          },
          label: function(context) {
            return `$${context.parsed.y.toFixed(2)}`;
          }
        }
      },
    },
    scales: {
      x: {
        type: 'time',
        time: {
          unit: timeConfig.unit,
          stepSize: timeConfig.stepSize,
          displayFormats: {
            hour: 'HH:mm',
            day: 'MMM dd',
            week: 'MMM dd',
            month: 'MMM yyyy'
          },
          tooltipFormat: 'MMM dd, yyyy HH:mm'
        },
        ticks: {
          source: 'data', // Use data points for ticks
          color: isLightMode ? '#666' : '#ccc',
          font: { size: 11 },
          maxTicksLimit: safeHistory.length, // Show all data points
          callback: function(value, index) {
            const date = new Date(value);
            // Format based on range
            if (range.includes('H') || range === '1D') {
              return date.toLocaleString('en-US', { hour: 'numeric', minute: '2-digit' });
            } else if (range === '3D') {
              return date.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric' });
            } else if (range === '7D' || range === '4W') {
              return date.toLocaleString('en-US', { month: 'short', day: 'numeric' });
            } else {
              return date.toLocaleString('en-US', { month: 'short', year: range === '1Y' ? 'numeric' : undefined });
            }
          }
        },
        grid: {
          color: isLightMode ? 'rgba(0, 0, 0, 0.1)' : 'rgba(255, 255, 255, 0.1)',
          drawBorder: false,
        },
        border: {
          color: isLightMode ? '#ddd' : '#333',
        },
      },
      y: {
        beginAtZero: false,
        ticks: {
          color: isLightMode ? '#666' : '#ccc',
          font: { size: 11 },
          callback: function(value) {
            return '$' + value.toFixed(0);
          }
        },
        grid: {
          color: isLightMode ? 'rgba(0, 0, 0, 0.1)' : 'rgba(255, 255, 255, 0.1)',
          drawBorder: false,
        },
        border: {
          color: isLightMode ? '#ddd' : '#333',
        },
      },
    },
  }), [range, safeHistory.length, timeConfig, isLightMode]);

  return <Line data={data} options={options} />;
}
