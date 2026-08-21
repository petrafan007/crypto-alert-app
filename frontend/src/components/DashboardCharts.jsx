import React, { useMemo } from 'react';
import { Doughnut, Line } from 'react-chartjs-2';
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
  Filler,
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
  TimeScale,
  Filler
);

export function PortfolioPie({ portfolio, isLightMode }) {
  // Only show coins with value > 0
  const data = useMemo(() => {
    const filtered = (portfolio || []).filter(c => c.current_value > 0);
    const neonPalette = [
      '#38bdf8', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6', '#14b8a6',
      '#ef4444', '#f97316', '#eab308', '#84cc16', '#06b6d4', '#6366f1', '#d946ef'
    ];
    return {
      labels: filtered.map(c => c.symbol),
      datasets: [
        {
          data: filtered.map(c => c.current_value),
          backgroundColor: neonPalette,
          borderWidth: 3,
          borderColor: isLightMode ? '#ffffff' : '#0f172a',
          hoverOffset: 6,
        },
      ],
    };
  }, [portfolio, isLightMode]);

  const options = useMemo(() => ({
    responsive: true,
    maintainAspectRatio: false,
    cutout: '65%',
    plugins: {
      legend: {
        position: 'right',
        labels: {
          color: isLightMode ? '#475569' : '#e2e8f0',
          font: { size: 12, family: 'Inter, sans-serif' },
          usePointStyle: true,
          pointStyle: 'circle',
          padding: 16,
        },
      },
      tooltip: {
        backgroundColor: isLightMode ? 'rgba(255, 255, 255, 0.95)' : 'rgba(15, 23, 42, 0.95)',
        titleColor: isLightMode ? '#0f172a' : '#f8fafc',
        bodyColor: isLightMode ? '#334155' : '#e2e8f0',
        borderColor: isLightMode ? 'rgba(0, 0, 0, 0.1)' : 'rgba(255, 255, 255, 0.1)',
        borderWidth: 1,
        padding: 12,
        cornerRadius: 8,
        titleFont: { size: 13, weight: 'bold', family: 'Inter, sans-serif' },
        bodyFont: { size: 13, family: 'Inter, sans-serif' },
        boxPadding: 6,
      },
    },
  }), [isLightMode]);

  return <Doughnut data={data} options={options} />;
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
        fill: true,
        backgroundColor: (context) => {
          const chart = context.chart;
          const { ctx, chartArea } = chart;
          if (!chartArea) return null;
          const gradient = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
          if (isLightMode) {
            gradient.addColorStop(0, 'rgba(2, 132, 199, 0.3)');
            gradient.addColorStop(1, 'rgba(2, 132, 199, 0.0)');
          } else {
            gradient.addColorStop(0, 'rgba(56, 189, 248, 0.4)');
            gradient.addColorStop(1, 'rgba(56, 189, 248, 0.0)');
          }
          return gradient;
        },
        borderColor: isLightMode ? '#0284c7' : '#38bdf8',
        borderWidth: 3,
        tension: 0.4,
        pointRadius: 0,
        pointHoverRadius: 6,
        pointBackgroundColor: isLightMode ? '#0284c7' : '#38bdf8',
        pointBorderColor: '#ffffff',
        pointBorderWidth: 2,
      },
    ],
  }), [safeHistory, isLightMode]);

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
        backgroundColor: isLightMode ? 'rgba(255, 255, 255, 0.95)' : 'rgba(15, 23, 42, 0.95)',
        titleColor: isLightMode ? '#0f172a' : '#f8fafc',
        bodyColor: isLightMode ? '#0284c7' : '#38bdf8',
        borderColor: isLightMode ? 'rgba(0, 0, 0, 0.1)' : 'rgba(255, 255, 255, 0.1)',
        borderWidth: 1,
        padding: 12,
        cornerRadius: 8,
        titleFont: { size: 13, weight: 'bold', family: 'Inter, sans-serif' },
        bodyFont: { size: 14, weight: 'bold', family: 'Inter, sans-serif' },
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
            return `$${context.parsed.y.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
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
          source: 'data',
          color: isLightMode ? '#64748b' : '#94a3b8',
          font: { size: 11, family: 'Inter, sans-serif' },
          maxTicksLimit: safeHistory.length,
          callback: function(value, index) {
            const date = new Date(value);
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
          color: isLightMode ? 'rgba(0, 0, 0, 0.05)' : 'rgba(255, 255, 255, 0.05)',
          drawBorder: false,
        },
        border: { display: false },
      },
      y: {
        beginAtZero: false,
        ticks: {
          color: isLightMode ? '#64748b' : '#94a3b8',
          font: { size: 11, family: 'Inter, sans-serif' },
          callback: function(value) {
            return '$' + value.toLocaleString();
          }
        },
        grid: {
          color: isLightMode ? 'rgba(0, 0, 0, 0.05)' : 'rgba(255, 255, 255, 0.05)',
          drawBorder: false,
        },
        border: { display: false },
      },
    },
  }), [range, safeHistory.length, timeConfig, isLightMode]);

  return <Line data={data} options={options} />;
}
