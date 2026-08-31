import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import './OptionsPayoffChart.css';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

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
  } else {
    const t = 1.0 / (1.0 - p * x);
    return (c * Math.exp(-x * x / 2.0) * t * (t * (t * (t * (t * b5 + b4) + b3) + b2) + b1));
  }
}

export default function OptionsPayoffChart({
  baselinePrice,
  strikePrice,
  entryPremium,
  multiplier = 100,
  iv = 0.15,
  riskFreeRate = 0.03,
  startingDTE = 18,
  optionType = 'PUT',
  action = 'BUY' // BUY or SELL
}) {
  const [sliderDTE, setSliderDTE] = useState(startingDTE);
  const [hoverPrice, setHoverPrice] = useState(null);
  
  const chartRef = useRef(null);

  // Generate X-axis points (e.g., +/- 15% around strike)
  const xPoints = useMemo(() => {
    const points = [];
    const minP = baselinePrice * 0.85;
    const maxP = baselinePrice * 1.15;
    const step = (maxP - minP) / 100;
    for (let p = minP; p <= maxP; p += step) {
      points.push(p);
    }
    return points;
  }, [baselinePrice]);

  // Calculate Black-Scholes price
  const calculateOptionPrice = (S, K, T, r, v, type) => {
    if (T <= 0) {
      return type === 'CALL' ? Math.max(S - K, 0) : Math.max(K - S, 0);
    }
    const T_years = T / 365.0;
    const d1 = (Math.log(S / K) + (r + 0.5 * v * v) * T_years) / (v * Math.sqrt(T_years));
    const d2 = d1 - v * Math.sqrt(T_years);

    if (type === 'CALL') {
      return S * normsdist(d1) - K * Math.exp(-r * T_years) * normsdist(d2);
    } else {
      return K * Math.exp(-r * T_years) * normsdist(-d2) - S * normsdist(-d1);
    }
  };

  const chartData = useMemo(() => {
    const dataPoints = xPoints.map((S) => {
      const currentOptPrice = calculateOptionPrice(S, strikePrice, sliderDTE, riskFreeRate, iv, optionType);
      let pnl = (currentOptPrice - entryPremium) * multiplier;
      if (action === 'SELL') pnl = -pnl;
      return pnl;
    });

    return {
      labels: xPoints.map(p => p.toFixed(2)),
      datasets: [
        {
          label: 'P&L',
          data: dataPoints,
          borderColor: (ctx) => {
             const val = ctx.raw;
             return val >= 0 ? 'rgba(0, 200, 100, 1)' : 'rgba(255, 50, 50, 1)';
          },
          backgroundColor: (ctx) => {
             // Gradient fill based on positive/negative
             return 'rgba(0, 200, 100, 0.2)'; // Simplified for now
          },
          fill: true,
          pointRadius: 0,
          pointHoverRadius: 6,
          tension: 0.1
        }
      ]
    };
  }, [xPoints, strikePrice, entryPremium, multiplier, iv, riskFreeRate, sliderDTE, optionType, action]);

  const maxProfit = action === 'BUY' && optionType === 'CALL' ? 'Unlimited' : Math.max(...chartData.datasets[0].data);
  const maxLoss = action === 'BUY' ? -entryPremium * multiplier : (optionType === 'CALL' ? 'Unlimited' : -strikePrice * multiplier);

  const handleExport = async () => {
    try {
      const res = await fetch('/api/options/thesis/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('token')}` },
        body: JSON.stringify({
          baseline_price: baselinePrice,
          strike_price: strikePrice,
          entry_premium: entryPremium,
          multiplier, iv, risk_free_rate: riskFreeRate, starting_dte: startingDTE, option_type: optionType
        })
      });
      if (!res.ok) throw new Error('Export failed');
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${optionType}_${strikePrice}_Payout_Model.xlsx`;
      a.click();
    } catch (err) {
      console.error(err);
      alert('Failed to export thesis');
    }
  };

  return (
    <div className="options-payoff-container">
      <div className="payoff-header">
        <div><strong>Max Profit:</strong> {maxProfit === 'Unlimited' ? 'Unlimited' : `$${maxProfit.toFixed(2)}`}</div>
        <div><strong>Max Loss:</strong> {maxLoss === 'Unlimited' ? 'Unlimited' : `$${maxLoss.toFixed(2)}`}</div>
        <button onClick={handleExport} className="btn btn-sm btn-primary">Export Excel Thesis</button>
      </div>

      <div className="chart-wrapper">
        <Line 
          ref={chartRef}
          data={chartData} 
          options={{
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
              mode: 'index',
              intersect: false,
            },
            scales: {
              y: {
                grid: { color: (ctx) => ctx.tick.value === 0 ? '#aaa' : '#333' }
              }
            }
          }} 
        />
        {/* Draggable Hex Badge Overlay logic could go here */}
      </div>

      <div className="dte-slider-container mt-3">
        <label>Days to Expiration: {sliderDTE}</label>
        <input 
          type="range" 
          min="0" 
          max={startingDTE} 
          value={sliderDTE} 
          onChange={(e) => setSliderDTE(parseInt(e.target.value))}
          className="form-range" 
        />
        <div className="slider-labels d-flex justify-content-between">
          <span>Exp (Day 0)</span>
          <span>Entry (Day {startingDTE})</span>
        </div>
      </div>
    </div>
  );
}
