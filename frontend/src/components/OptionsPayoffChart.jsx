import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  Chart as ChartJS,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import FileDownloadOutlinedIcon from '@mui/icons-material/FileDownloadOutlined';
import VisibilityOutlinedIcon from '@mui/icons-material/VisibilityOutlined';
import OptionsThesisModal from './OptionsThesisModal';
import './OptionsPayoffChart.css';

ChartJS.register(LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

const ZOOM_RANGES = [5, 10, 15, 25, 50, 75, 100];

// Normal distribution CDF approximation for JS (Black-Scholes)
function normsdist(x) {
  const b1 = 0.319381530;
  const b2 = -0.356563782;
  const b3 = 1.781477937;
  const b4 = -1.821255978;
  const b5 = 1.330274429;
  const p = 0.2316419;
  const c = 0.39894228;

  if (x >= 0.0) {
    const t = 1.0 / (1.0 + p * x);
    return (1.0 - c * Math.exp(-x * x / 2.0) * t * (t * (t * (t * (t * b5 + b4) + b3) + b2) + b1));
  }

  const t = 1.0 / (1.0 - p * x);
  return (c * Math.exp(-x * x / 2.0) * t * (t * (t * (t * (t * b5 + b4) + b3) + b2) + b1));
}

function safePrice(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function filenameFromDisposition(headerValue) {
  if (!headerValue) return '';
  const utf8Match = headerValue.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match) return decodeURIComponent(utf8Match[1].replace(/["']/g, ''));
  const plainMatch = headerValue.match(/filename="?([^";]+)"?/i);
  return plainMatch ? plainMatch[1].trim() : '';
}

export default function OptionsPayoffChart({
  underlyingSymbol = 'SPY',
  baselinePrice,
  strikePrice,
  entryPremium,
  multiplier = 100,
  quantity = 1,
  iv = 0.15,
  riskFreeRate = 0.03,
  expirationDate = '',
  startingDTE = 18,
  optionType = 'PUT',
  action = 'BUY',
  onStrikeSelect,
  isLightMode = false,
}) {
  const [daysElapsed, setDaysElapsed] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [simulatedPrice, setSimulatedPrice] = useState(strikePrice);
  const [rangePercent, setRangePercent] = useState(10);
  const [isThesisOpen, setIsThesisOpen] = useState(false);
  const [thesis, setThesis] = useState(null);
  const [thesisLoading, setThesisLoading] = useState(false);
  const [thesisError, setThesisError] = useState('');
  const chartRef = useRef(null);
  const simulatedPriceRef = useRef(strikePrice);

  const selectedStrike = safePrice(strikePrice, safePrice(baselinePrice, 1));
  const baseline = safePrice(baselinePrice, selectedStrike);
  const chartCenterPrice = baseline;
  const safeQuantity = Math.max(0, Number(quantity) || 0);
  const currentDTE = Math.max(0, startingDTE - daysElapsed);

  useEffect(() => {
    simulatedPriceRef.current = strikePrice;
    setSimulatedPrice(strikePrice);
  }, [strikePrice]);

  useEffect(() => {
    setDaysElapsed(0);
  }, [startingDTE, strikePrice]);

  useEffect(() => {
    setRangePercent(10);
  }, [strikePrice]);

  // Use exact one-cent price points around the current underlying price. Integer
  // cents prevent floating-point drift and duplicate axis labels.
  const xPoints = useMemo(() => {
    const range = chartCenterPrice * (rangePercent / 100);
    const minCents = Math.max(1, Math.round((chartCenterPrice - range) * 100));
    const maxCents = Math.max(minCents + 1, Math.round((chartCenterPrice + range) * 100));
    return Array.from({ length: maxCents - minCents + 1 }, (_, index) => (minCents + index) / 100);
  }, [chartCenterPrice, rangePercent]);

  const calculateOptionPrice = (S, K, T, r, v, type) => {
    if (T <= 0) {
      return type === 'CALL' ? Math.max(S - K, 0) : Math.max(K - S, 0);
    }
    const TYears = T / 365.0;
    const safeVolatility = Math.max(Number(v) || 0, 0.000000001);
    const d1 = (Math.log(S / K) + (r + 0.5 * safeVolatility * safeVolatility) * TYears)
      / (safeVolatility * Math.sqrt(TYears));
    const d2 = d1 - safeVolatility * Math.sqrt(TYears);

    if (type === 'CALL') {
      return S * normsdist(d1) - K * Math.exp(-r * TYears) * normsdist(d2);
    }
    return K * Math.exp(-r * TYears) * normsdist(-d2) - S * normsdist(-d1);
  };

  const chartData = useMemo(() => ({
    datasets: [
      {
        label: 'P&L',
        data: xPoints.map((underlyingPrice) => {
          const currentOptPrice = calculateOptionPrice(
            underlyingPrice,
            selectedStrike,
            currentDTE,
            riskFreeRate,
            iv,
            optionType,
          );
          let pnl = (currentOptPrice - entryPremium) * multiplier * safeQuantity;
          if (action === 'SELL') pnl = -pnl;
          return { x: underlyingPrice, y: pnl };
        }),
        parsing: false,
        fill: {
          target: 'origin',
          above: 'rgba(16, 185, 129, 0.2)',
          below: 'rgba(239, 68, 68, 0.2)',
        },
        segment: {
          borderColor: (context) => context.p0.parsed.y >= 0
            ? 'rgba(16, 185, 129, 1)'
            : 'rgba(239, 68, 68, 1)',
        },
        pointRadius: 0,
        pointHoverRadius: 6,
        tension: 0.1,
      },
    ],
  }), [xPoints, selectedStrike, entryPremium, multiplier, safeQuantity, iv, riskFreeRate, currentDTE, optionType, action]);

  let maxProfit = 0;
  let maxLoss = 0;
  if (action === 'BUY') {
    if (optionType === 'CALL') {
      maxProfit = 'Unlimited';
      maxLoss = -entryPremium * multiplier * safeQuantity;
    } else {
      maxProfit = (selectedStrike - entryPremium) * multiplier * safeQuantity;
      maxLoss = -entryPremium * multiplier * safeQuantity;
    }
  } else if (optionType === 'CALL') {
    maxProfit = entryPremium * multiplier * safeQuantity;
    maxLoss = 'Unlimited';
  } else {
    maxProfit = entryPremium * multiplier * safeQuantity;
    maxLoss = -(selectedStrike - entryPremium) * multiplier * safeQuantity;
  }

  const minP = xPoints[0];
  const maxP = xPoints[xPoints.length - 1];
  let hexLeftPercent = ((simulatedPrice - minP) / (maxP - minP)) * 100;
  hexLeftPercent = Math.max(5, Math.min(95, hexLeftPercent));

  const handlePointerMove = (event) => {
    if (!isDragging) return;
    const chart = chartRef.current;
    if (!chart) return;
    const rect = chart.canvas.getBoundingClientRect();
    const priceAtPointer = chart.scales.x.getValueForPixel(event.clientX - rect.left);
    if (Number.isFinite(priceAtPointer)) {
      const nextPrice = Math.max(minP, Math.min(maxP, Math.round(priceAtPointer * 100) / 100));
      simulatedPriceRef.current = nextPrice;
      setSimulatedPrice(nextPrice);
    }
  };

  const handleHexPointerDown = (event) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setIsDragging(true);
  };

  const handlePointerUp = () => {
    if (isDragging) onStrikeSelect?.(simulatedPriceRef.current);
    setIsDragging(false);
  };

  const changeZoom = (direction) => {
    const currentIndex = ZOOM_RANGES.indexOf(rangePercent);
    const nextIndex = Math.max(0, Math.min(ZOOM_RANGES.length - 1, currentIndex + direction));
    setRangePercent(ZOOM_RANGES[nextIndex]);
  };

  const buildThesisPayload = () => ({
    underlying_symbol: underlyingSymbol,
    baseline_price: baseline,
    strike_price: strikePrice,
    entry_premium: entryPremium,
    multiplier,
    iv,
    risk_free_rate: riskFreeRate,
    expiration_date: expirationDate,
    starting_dte: startingDTE,
    option_type: optionType,
    quantity: safeQuantity,
  });

  const handleExport = async () => {
    try {
      const response = await fetch('/api/options/thesis/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('token')}` },
        body: JSON.stringify(buildThesisPayload()),
      });
      if (!response.ok) throw new Error('Export failed');
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      const safeSymbol = String(underlyingSymbol || 'OPTION').toUpperCase().replace(/[^A-Z0-9.-]/g, '');
      const strikeToken = Number(strikePrice).toFixed(8).replace(/\.?0+$/, '');
      anchor.href = url;
      anchor.download = filenameFromDisposition(response.headers.get('Content-Disposition'))
        || `${optionType}_${strikeToken}_${safeSymbol}_Payout_Model.xlsx`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error(error);
      alert('Failed to export thesis');
    }
  };

  const handleViewThesis = async () => {
    setIsThesisOpen(true);
    setThesisLoading(true);
    setThesisError('');
    try {
      const response = await fetch('/api/options/thesis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('token')}` },
        body: JSON.stringify(buildThesisPayload()),
      });
      const payload = await response.json();
      if (!response.ok || !payload.success) throw new Error(payload.error || 'Unable to build thesis');
      setThesis(payload.thesis);
    } catch (error) {
      console.error(error);
      setThesisError('Unable to load the thesis. Please try again.');
    } finally {
      setThesisLoading(false);
    }
  };

  return (
    <div className="options-payoff-container">
      <div className="payoff-header">
        <div><strong>Max Profit:</strong> {maxProfit === 'Unlimited' ? 'Unlimited' : `$${maxProfit.toFixed(2)}`}</div>
        <div><strong>Max Loss:</strong> {maxLoss === 'Unlimited' ? 'Unlimited' : `$${maxLoss.toFixed(2)}`}</div>
        <div className="payoff-header-actions">
          <div className="payoff-zoom-controls" aria-label="Payoff chart zoom controls">
            <button type="button" onClick={() => changeZoom(-1)} disabled={rangePercent === ZOOM_RANGES[0]} title="Zoom in">+</button>
            <span>±{rangePercent}%</span>
            <button type="button" onClick={() => changeZoom(1)} disabled={rangePercent === ZOOM_RANGES[ZOOM_RANGES.length - 1]} title="Zoom out">−</button>
          </div>
          <button type="button" onClick={handleExport} className="btn btn-sm btn-primary payoff-thesis-action">
            <FileDownloadOutlinedIcon fontSize="small" />
            Export Thesis to Excel
          </button>
          <button type="button" onClick={handleViewThesis} className="btn btn-sm btn-secondary payoff-thesis-action">
            <VisibilityOutlinedIcon fontSize="small" />
            View Thesis
          </button>
        </div>
      </div>

      <div
        className="chart-wrapper"
        style={{ position: 'relative', cursor: isDragging ? 'grabbing' : 'default' }}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
      >
        <Line
          ref={chartRef}
          data={chartData}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            normalized: true,
            interaction: { mode: 'nearest', intersect: false },
            scales: {
              x: {
                type: 'linear',
                min: minP,
                max: maxP,
                border: { color: isLightMode ? '#cbd5e1' : '#475569' },
                grid: { color: isLightMode ? 'rgba(100, 116, 139, 0.18)' : 'rgba(148, 163, 184, 0.14)' },
                ticks: {
                  color: isLightMode ? '#475569' : '#cbd5e1',
                  autoSkip: true,
                  maxTicksLimit: 12,
                  precision: 2,
                  callback: (value) => `$${Number(value).toFixed(2)}`,
                },
              },
              y: {
                border: { color: isLightMode ? '#cbd5e1' : '#475569' },
                grid: { color: (context) => context.tick.value === 0 ? (isLightMode ? '#64748b' : '#94a3b8') : (isLightMode ? 'rgba(100, 116, 139, 0.18)' : 'rgba(148, 163, 184, 0.14)') },
                ticks: { color: isLightMode ? '#475569' : '#cbd5e1' },
              },
            },
            plugins: {
              legend: { labels: { color: isLightMode ? '#334155' : '#e2e8f0' } },
              tooltip: {
                callbacks: {
                  title: (items) => items.length ? `Underlying: $${Number(items[0].parsed.x).toFixed(2)}` : '',
                },
              },
            },
            animation: false,
          }}
        />

        <div style={{
          position: 'absolute',
          top: '35%',
          left: `${hexLeftPercent}%`,
          transform: 'translate(-50%, -50%)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          width: '70px',
          height: '80px',
          backgroundColor: '#0f766e',
          clipPath: 'polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)',
          color: 'white',
          fontSize: '11px',
          fontWeight: 'bold',
          border: '2px solid #2dd4bf',
          boxShadow: '0 4px 6px rgba(0,0,0,0.3)',
          zIndex: 10,
          cursor: isDragging ? 'grabbing' : 'grab',
          touchAction: 'none',
        }} onPointerDown={handleHexPointerDown}>
          <div>{action === 'BUY' ? 'Buy' : 'Sell'} {safeQuantity.toLocaleString()}</div>
          <div style={{ margin: '4px 0' }}>${Number(simulatedPrice).toFixed(2)}</div>
          <div style={{
            backgroundColor: '#14b8a6',
            borderRadius: '10px',
            padding: '2px 8px',
            fontSize: '10px',
          }}>
            {optionType.charAt(0).toUpperCase() + optionType.slice(1).toLowerCase()}
          </div>
        </div>
      </div>

      <div className="dte-slider-container mt-3">
        <label>Days to Expiration: {currentDTE} ({startingDTE} Day Contract)</label>
        <input
          type="range"
          min="0"
          max={startingDTE}
          value={daysElapsed}
          onChange={(event) => setDaysElapsed(parseInt(event.target.value, 10))}
          className="form-range"
        />
        <div className="slider-labels d-flex justify-content-between">
          <span>Entry ({startingDTE} DTE)</span>
          <span>Exp (0 DTE)</span>
        </div>
      </div>
      <OptionsThesisModal
        isOpen={isThesisOpen}
        onClose={() => setIsThesisOpen(false)}
        thesis={thesis}
        loading={thesisLoading}
        error={thesisError}
        onRetry={handleViewThesis}
      />
    </div>
  );
}
