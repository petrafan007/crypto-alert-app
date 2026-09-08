import React from 'react';
import { summarizeAccuracy } from '../utils/sentimentAccuracy.mjs';
export default function SentimentAccuracyCards({ history, defaultMethod }) {
  const stats = summarizeAccuracy(history, defaultMethod);
  return <>
    <div className="accuracy-kpi-grid">
      {[['directional', 'Directional Win Rate'], ['bullish', 'Bullish Win Rate'], ['bearish', 'Bearish Win Rate'], ['hold', 'Hold Accuracy']].map(([key, label]) => {
        const value = stats[key];
        return <div key={key} className={`accuracy-kpi-card ${key}`}><div className="kpi-label">{label}</div><div className="kpi-value">{value.rate === null ? 'No results' : `${value.rate.toFixed(1)}%`}</div><div className="kpi-subtext">{value.correct} correct / {value.evaluated} decisive · {value.neutral} neutral</div></div>;
      })}
    </div>
    <p className="kpi-subtext">Fixed-horizon results for the selected assets and date range. Hold calls are scored separately; neutral outcomes are shown but excluded from win rates. {stats.tracking} awaiting evaluation · {stats.unscored} unscored.</p>
    {stats.directional.evaluated < 30 && <p role="status">{stats.directional.evaluated ? 'Limited directional sample; this rate is not evidence of reliable predictive performance.' : 'No evaluated directional calls. Successful Hold calls do not establish a bullish or bearish win rate.'}</p>}
  </>;
}
