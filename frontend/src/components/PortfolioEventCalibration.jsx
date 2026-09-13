import React from 'react';

const score = value => value == null ? 'Unavailable' : Number(value).toFixed(4);

function CalibrationBreakdown({ title, heading, data }) {
  if (!data) return null;
  return <details style={{ margin: '12px 0' }}>
    <summary>{title} · {data.total_groups ?? 0} groups</summary>
    {!data.rows?.length ? <p>No resolved forecasts in this sample.</p> : <>
      <p>Model Brier, market Brier and skill use the same matched contracts in each row. Calibration error uses all resolved contracts in the row.</p>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', textAlign: 'left', fontSize: 13 }}>
          <caption>{title}</caption>
          <thead><tr><th scope="col">{heading}</th><th scope="col">Resolved</th><th scope="col">Matched</th><th scope="col">Model Brier</th><th scope="col">Market Brier</th><th scope="col">Skill</th><th scope="col">Calibration error</th></tr></thead>
          <tbody>{data.rows.map(row => <tr key={row.key}>
            <th scope="row">{row.label}</th><td>{row.resolved_contracts}</td><td>{row.market_comparison_contracts}</td>
            <td>{score(row.paired_model_brier_score)}</td><td>{score(row.market_brier_score)}</td><td>{score(row.skill_score)}</td><td>{score(row.calibration_error)}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </>}
    {data.omitted_groups > 0 && <p role="alert">Showing {data.rows?.length ?? 0} of {data.total_groups} groups. {data.omitted_groups} groups containing {data.omitted_contracts} sampled contracts are omitted from this table; they remain in the overall scores.</p>}
  </details>;
}

export default function PortfolioEventCalibration({ calibration }) {
  if (!calibration) return null;
  return <section aria-label="Event probability calibration" style={{ margin: '18px 0' }}>
    <h4>Event probability calibration · observed settlements only</h4>
    <p>{calibration.status || 'Awaiting evidence'} · {calibration.resolved_contracts ?? 0} resolved contracts</p>
    <p>Model Brier score (resolved sample): {score(calibration.brier_score)} · Calibration error: {score(calibration.calibration_error)}</p>
    <p>Matched market comparison ({calibration.market_comparison_contracts ?? 0} contracts): model {score(calibration.paired_model_brier_score)} · market {score(calibration.market_brier_score)} · skill {score(calibration.skill_score)}</p>
    <p>Lower Brier scores are better. A positive skill score beats the supplied market probabilities on this sample; it does not establish profitability or future returns.</p>
    {calibration.breakdowns && <>
      <p>{calibration.breakdown_policy}</p>
      <CalibrationBreakdown title="By forecast model" heading="Provider / model / strategy version" data={calibration.breakdowns.model} />
      <CalibrationBreakdown title="By contract duration" heading="Archived duration" data={calibration.breakdowns.duration} />
      <CalibrationBreakdown title="By forecast month" heading="Month (UTC)" data={calibration.breakdowns.period} />
    </>}
    <details><summary>Calibration coverage, exclusions and buckets</summary>
      <p>{calibration.sample_policy}</p><p>{calibration.coverage_note}</p>
      {calibration.truncated && <p role="alert">Evidence is truncated at {calibration.contract_limit ?? calibration.row_limit} distinct resolved contracts; these results do not cover every resolved contract in this run.</p>}
      <table style={{ width: '100%', textAlign: 'left', fontSize: 13 }}><thead><tr><th>Probability bucket</th><th>Contracts</th><th>Mean forecast YES</th><th>Observed YES rate</th></tr></thead><tbody>
        {(calibration.buckets || []).map(bucket => <tr key={bucket.lower}><td>{Math.round(bucket.lower * 100)}–{Math.round(bucket.upper * 100)}%</td><td>{bucket.count}</td><td>{score(bucket.mean_probability)}</td><td>{score(bucket.observed_yes_rate)}</td></tr>)}
      </tbody></table>
      {Object.entries(calibration.exclusions || {}).map(([reason, count]) => <p key={reason}>{reason.replaceAll('_', ' ')}: {count}</p>)}
      <p>{calibration.interpretation}</p>
    </details>
  </section>;
}
