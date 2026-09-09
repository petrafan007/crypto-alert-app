import React from 'react';

const score = value => value == null ? 'Unavailable' : Number(value).toFixed(4);

export default function PortfolioEventCalibration({ calibration }) {
  if (!calibration) return null;
  return <section aria-label="Event probability calibration" style={{ margin: '18px 0' }}>
    <h4>Event probability calibration · observed settlements only</h4>
    <p>{calibration.status || 'Awaiting evidence'} · {calibration.resolved_contracts ?? 0} resolved contracts</p>
    <p>Model Brier score (all resolved): {score(calibration.brier_score)} · Calibration error: {score(calibration.calibration_error)}</p>
    <p>Matched market comparison ({calibration.market_comparison_contracts ?? 0} contracts): model {score(calibration.paired_model_brier_score)} · market {score(calibration.market_brier_score)} · skill {score(calibration.skill_score)}</p>
    <p>Lower Brier scores are better. A positive skill score beats the supplied market probabilities on this sample; it does not establish profitability or future returns.</p>
    <details><summary>Calibration coverage, exclusions and buckets</summary>
      <p>{calibration.sample_policy}</p><p>{calibration.coverage_note}</p>
      {calibration.truncated && <p role="alert">Evidence is truncated at {calibration.row_limit} forecast rows; these results do not cover every forecast in this run.</p>}
      <table style={{ width: '100%', textAlign: 'left', fontSize: 13 }}><thead><tr><th>Probability bucket</th><th>Contracts</th><th>Mean forecast YES</th><th>Observed YES rate</th></tr></thead><tbody>
        {(calibration.buckets || []).map(bucket => <tr key={bucket.lower}><td>{Math.round(bucket.lower * 100)}–{Math.round(bucket.upper * 100)}%</td><td>{bucket.count}</td><td>{score(bucket.mean_probability)}</td><td>{score(bucket.observed_yes_rate)}</td></tr>)}
      </tbody></table>
      {Object.entries(calibration.exclusions || {}).map(([reason, count]) => <p key={reason}>{reason.replaceAll('_', ' ')}: {count}</p>)}
      <p>{calibration.interpretation}</p>
    </details>
  </section>;
}
