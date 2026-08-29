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

export function PortfolioPie({ portfolio, isLightMode, totalValue: authoritativeTotalValue, onCoinClick }) {
  const neonPalette = [
    '#38bdf8', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6', '#14b8a6',
    '#ef4444', '#f97316', '#eab308', '#84cc16', '#06b6d4', '#6366f1', '#d946ef'
  ];

  // Only show coins with value > 0
  const filtered = useMemo(() => (portfolio || []).filter(c => c.current_value > 0), [portfolio]);

  // Prefer the same authoritative total shown in the "Total Portfolio Value" widget
  // (includes staking and sub-$1 dust) rather than re-summing just the rendered slices.
  const totalValue = useMemo(() => {
    if (authoritativeTotalValue !== null && authoritativeTotalValue !== undefined) {
      return Number(authoritativeTotalValue) || 0;
    }
    return filtered.reduce((sum, c) => sum + Number(c.current_value || 0), 0);
  }, [authoritativeTotalValue, filtered]);

  const formattedTotal = useMemo(() => (
    totalValue.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 })
  ), [totalValue]);

  const portfolioPnl = useMemo(() => {
    const basisTracked = (portfolio || []).filter(coin => (
      Number(coin?.amount) > 0 && Number(coin?.avg_entry) > 0 &&
      Number.isFinite(Number(coin?.current_price ?? coin?.price))
    ));
    const costBasis = basisTracked.reduce((sum, coin) => sum + Number(coin.amount) * Number(coin.avg_entry), 0);
    const currentValue = basisTracked.reduce((sum, coin) => sum + (
      Number(coin.current_value) || Number(coin.amount) * Number(coin.current_price ?? coin.price)
    ), 0);
    if (!(costBasis > 0)) return null;
    const value = currentValue - costBasis;
    return { value, percent: (value / costBasis) * 100 };
  }, [portfolio]);

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
    onClick: (_event, elements) => {
      const sliceIndex = elements?.[0]?.index;
      const symbol = filtered[sliceIndex]?.symbol;
      if (symbol && onCoinClick) onCoinClick(symbol);
    },
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
  }), [filtered, isLightMode, onCoinClick]);

  return (
    <div style={{ display: 'flex', alignItems: 'center', width: '100%', height: '100%', position: 'relative', overflow: 'hidden' }}>
      {/* Donut chart container: fills available space to the left of the legend */}
      <div style={{ position: 'relative', flex: 1, height: '100%', minWidth: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ position: 'relative', width: '100%', height: '100%', maxWidth: '260px', maxHeight: '260px' }}>
          <Doughnut data={data} options={options} />
          {/* Rendered as a plain DOM overlay (not a canvas plugin) so it always reflects the
              latest totalValue on every render, instead of going stale between chart.js redraws */}
          <div style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            pointerEvents: 'none',
            textAlign: 'center',
            padding: '0 14px'
          }}>
            <span style={{ fontSize: '16px', fontWeight: '700', color: isLightMode ? '#0f172a' : '#f8fafc' }}>
              {formattedTotal}
            </span>
            <span style={{ fontSize: '10px', fontWeight: '600', letterSpacing: '0.04em', color: isLightMode ? '#64748b' : '#94a3b8' }}>
              TOTAL VALUE
            </span>
            {portfolioPnl && (
              <span style={{ marginTop: '3px', fontSize: '10px', fontWeight: '700', color: portfolioPnl.value >= 0 ? '#22c55e' : '#ef4444', whiteSpace: 'nowrap' }}>
                {portfolioPnl.value >= 0 ? '+' : ''}{portfolioPnl.value.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 })} ({portfolioPnl.percent >= 0 ? '+' : ''}{portfolioPnl.percent.toFixed(2)}%)
              </span>
            )}
          </div>
        </div>
      </div>
      {/* Legend on the far right: never overlaps with donut */}
      <div
        className="custom-scrollbar"
        style={{
          width: 'auto',
          minWidth: '85px',
          maxWidth: '120px',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: '6px',
          overflowY: 'auto',
          padding: '4px 8px 4px 4px',
          flexShrink: 0
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
      '1H': { unit: 'minute', stepSize: 15 },
      '4H': { unit: 'hour', stepSize: 1, displayFormat: 'HH:mm' },
      '12H': { unit: 'hour', stepSize: 2, displayFormat: 'HH:mm MMM dd' },
      '24H': { unit: 'hour', stepSize: 4, displayFormat: 'HH:mm' },
      '2D': { unit: 'hour', stepSize: 8, displayFormat: 'MMM dd HH:mm' },
      '3D': { unit: 'hour', stepSize: 12, displayFormat: 'MMM dd HH:mm' },
      '4D': { unit: 'day', stepSize: 1, displayFormat: 'MMM dd' },
      '5D': { unit: 'day', stepSize: 1, displayFormat: 'MMM dd' },
      '6D': { unit: 'day', stepSize: 1, displayFormat: 'MMM dd' },
      '7D': { unit: 'day', stepSize: 1, displayFormat: 'MMM dd' },
      '14D': { unit: 'day', stepSize: 2, displayFormat: 'MMM dd' },
      '30D': { unit: 'week', stepSize: 1, displayFormat: 'MMM dd' },
      '60D': { unit: 'week', stepSize: 1, displayFormat: 'MMM dd' },
      '90D': { unit: 'month', stepSize: 1, displayFormat: 'MMM yyyy' },
      '1Y': { unit: 'month', stepSize: 1, displayFormat: 'MMM yyyy' },
      '2Y': { unit: 'month', stepSize: 2, displayFormat: 'MMM yyyy' },
      '3Y': { unit: 'month', stepSize: 3, displayFormat: 'MMM yyyy' },
      // Let Chart.js choose sensible tick spacing for an arbitrary all-time span.
      'ALL': { unit: false }
    };
    return configs[rangeKey] || configs['24H'];
  };

  const timeConfig = getTimeConfig(range);
  const historySpanMs = safeHistory.length > 1
    ? safeHistory[safeHistory.length - 1][0] - safeHistory[0][0]
    : 0;

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
              timeZone: 'America/New_York',
              month: 'short',
              day: 'numeric',
              hour: range.includes('H') || range === '3D' ? 'numeric' : undefined,
              minute: range.includes('H') || range === '3D' ? '2-digit' : undefined,
              year: range === 'ALL' || range.includes('M') || range === '1Y' ? 'numeric' : undefined
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
          unit: timeConfig.unit || undefined,
          stepSize: timeConfig.stepSize,
          displayFormats: {
            minute: 'HH:mm',
            hour: 'HH:mm',
            day: 'MMM dd',
            week: 'MMM dd',
            month: 'MMM yyyy'
          },
          tooltipFormat: 'MMM dd, yyyy HH:mm'
        },
        ticks: {
          source: range === 'ALL' ? 'auto' : 'data',
          color: isLightMode ? '#64748b' : '#94a3b8',
          font: { size: 11, family: 'Inter, sans-serif' },
          maxTicksLimit: range === 'ALL' ? 7 : Math.min(safeHistory.length, 7),
          callback: function(value, index) {
            const date = new Date(value);
            if (range === 'ALL') {
              if (historySpanMs <= 31 * 24 * 60 * 60 * 1000) {
                return date.toLocaleDateString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric' });
              }
              return date.toLocaleDateString('en-US', { timeZone: 'America/New_York', month: 'short', year: 'numeric' });
            } else if (range.includes('H')) {
              return date.toLocaleString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit' });
            } else if (range === '3D') {
              return date.toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric' });
            } else if (range === '7D' || range === '30D') {
              return date.toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric' });
            } else {
              return date.toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', year: range === '1Y' ? 'numeric' : undefined });
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
            return Number(value).toLocaleString('en-US', {
              style: 'currency',
              currency: 'USD',
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            });
          }
        },
        grid: {
          color: isLightMode ? 'rgba(0, 0, 0, 0.05)' : 'rgba(255, 255, 255, 0.05)',
          drawBorder: false,
        },
        border: { display: false },
      },
    },
  }), [range, safeHistory.length, timeConfig, isLightMode, historySpanMs]);

  return <Line data={data} options={options} />;
}
