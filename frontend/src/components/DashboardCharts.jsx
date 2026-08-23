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
  const neonPalette = [
    '#38bdf8', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6', '#14b8a6',
    '#ef4444', '#f97316', '#eab308', '#84cc16', '#06b6d4', '#6366f1', '#d946ef'
  ];

  // Only show coins with value > 0
  const filtered = useMemo(() => (portfolio || []).filter(c => c.current_value > 0), [portfolio]);

  const totalValue = useMemo(
    () => filtered.reduce((sum, c) => sum + Number(c.current_value || 0), 0),
    [filtered]
  );

  const formattedTotal = useMemo(() => (
    totalValue.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 0 })
  ), [totalValue]);

  const data = useMemo(() => ({
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
  }), [filtered, isLightMode]);

  const options = useMemo(() => ({
    responsive: true,
    maintainAspectRatio: false,
    cutout: '65%',
    plugins: {
      legend: {
        display: false,
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

  // Draws the total portfolio value in the doughnut's center hole
  const centerTextPlugin = useMemo(() => ({
    id: 'centerTextPlugin',
    afterDraw(chart) {
      const { ctx, chartArea } = chart;
      if (!chartArea) return;
      const centerX = (chartArea.left + chartArea.right) / 2;
      const centerY = (chartArea.top + chartArea.bottom) / 2;
      ctx.save();
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = isLightMode ? '#0f172a' : '#f8fafc';
      ctx.font = "700 16px 'Inter', sans-serif";
      ctx.fillText(formattedTotal, centerX, centerY - 8);
      ctx.fillStyle = isLightMode ? '#64748b' : '#94a3b8';
      ctx.font = "600 10px 'Inter', sans-serif";
      ctx.fillText('TOTAL VALUE', centerX, centerY + 10);
      ctx.restore();
    },
  }), [formattedTotal, isLightMode]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      {/* Ring stays centered in the full panel regardless of the legend's width */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, margin: 'auto', width: '75%', maxWidth: '260px' }}>
        <Doughnut data={data} options={options} plugins={[centerTextPlugin]} />
      </div>
      <div
        className="custom-scrollbar"
        style={{
          position: 'absolute',
          top: 0,
          right: 0,
          bottom: 0,
          width: '32%',
          minWidth: '90px',
          maxWidth: '140px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: '6px',
          overflowY: 'auto',
          padding: '4px 0'
        }}
      >
        {filtered.map((c, i) => (
          <div key={c.symbol} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px' }}>
            <span style={{ width: '9px', height: '9px', borderRadius: '50%', flexShrink: 0, background: neonPalette[i % neonPalette.length] }} />
            <span style={{ color: isLightMode ? '#475569' : '#e2e8f0', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {c.symbol}
            </span>
          </div>
        ))}
      </div>
    </div>
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
