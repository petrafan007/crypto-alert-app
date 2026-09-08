const bullish = new Set(['buy immediately', 'definitely buy', 'strong buy', 'consider buying', 'buy']);
const bearish = new Set(['consider selling', 'watch', 'sell immediately', 'avoid', 'strong sell', 'do not buy', 'sell']);
export function summarizeAccuracy(history = [], defaultMethod = null) {
  const counts = { bullish: { correct: 0, wrong: 0, neutral: 0 }, bearish: { correct: 0, wrong: 0, neutral: 0 }, hold: { correct: 0, wrong: 0, neutral: 0 } };
  let tracking = 0, unscored = 0;
  for (const row of history) {
    if ((row.evaluation_method || defaultMethod) !== 'fixed_horizon') continue;
    const label = String(row.sentiment || '').trim().toLowerCase();
    const group = bullish.has(label) ? 'bullish' : bearish.has(label) ? 'bearish' : label === 'hold' ? 'hold' : null;
    const status = row.outcome_status;
    if (status === 'tracking') { tracking++; continue; }
    if (!group || !['correct', 'wrong', 'neutral'].includes(status)) { unscored++; continue; }
    counts[group][status]++;
  }
  const rate = bucket => { const n = bucket.correct + bucket.wrong; return { ...bucket, evaluated: n, rate: n ? bucket.correct * 100 / n : null }; };
  const directional = rate({ correct: counts.bullish.correct + counts.bearish.correct, wrong: counts.bullish.wrong + counts.bearish.wrong, neutral: counts.bullish.neutral + counts.bearish.neutral });
  return { directional, bullish: rate(counts.bullish), bearish: rate(counts.bearish), hold: rate(counts.hold), tracking, unscored };
}
