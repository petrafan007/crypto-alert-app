import React, { useState } from 'react';
import axios from 'axios';

const money = value => Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
const metric = (value, suffix = '') => value == null ? 'Insufficient history' : `${Number(value).toFixed(2)}${suffix}`;
const scenarioNames = {
  baseline: 'Saved rules / baseline costs',
  double_execution_costs: 'Double fees and slippage',
  one_observation_entry_delay: 'Entry delayed one quote',
  every_second_entry_unfilled: 'Every second entry unfilled',
};
function download(value, filename) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function PortfolioValidation({ endpoint = '/api/webull/portfolio-algo/validation' }) {
  const [input, setInput] = useState(null);
  const [filename, setFilename] = useState('');
  const [error, setError] = useState('');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const load = async event => {
    const file = event.target.files?.[0];
    setInput(null);
    setResult(null);
    setError('');
    setFilename(file?.name || '');
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      setError('Historical input is limited to 5 MiB. Reduce the date range or observation frequency.');
      return;
    }
    try {
      const parsed = JSON.parse(await file.text());
      if (!parsed || Array.isArray(parsed) || parsed.schema_version !== 1) throw new Error('Input must be an object with schema_version: 1.');
      setInput(parsed);
    } catch (err) {
      setError(`Cannot read historical JSON: ${err.message}`);
    }
  };
  const run = async () => {
    setRunning(true);
    setError('');
    setResult(null);
    try {
      const { data } = await axios.post(endpoint, input, { timeout: 120000 });
      if (!data.success || !data.validation) throw new Error(data.message || 'Replay did not return a result.');
      setResult(data.validation);
    } catch (err) {
      setError(err.response?.data?.message || err.message || 'Historical replay failed.');
    } finally {
      setRunning(false);
    }
  };
  return <section aria-label="Historical strategy validation" style={{ marginTop: 20 }}>
    <h4>Historical strategy validation</h4>
    <p>Administrator-only, read-only replay of one equities or crypto symbol using your saved strategy rules. Import actual historical observations; nothing is fetched, traded, or sent to AI. This is not a full-portfolio backtest or proof of the CAGR target.</p>
    <details>
      <summary>Historical input format and limitations</summary>
      <p>JSON schema version 1 requires <code>module</code> (equities or crypto), <code>symbol</code>, a description of <code>source</code>, <code>evaluation_start</code>, <code>split_at</code>, <code>bars</code>, and <code>quotes</code>. Timestamps should include a UTC offset. Quotes contain <code>time</code> and <code>price</code>. Bars contain their opening <code>time</code> plus <code>open/high/low/close</code>; volume is optional. Use daily NYSE-session bars for equities and hourly bars for crypto. Optional <code>available_at</code> records delayed publication, never before candle completion.</p>
      <p>Equities additionally require daily SPY <code>benchmark_bars</code>. Altcoins require BTC <code>dominance_observations</code> with <code>time/value</code>: a current observation within one hour and all seven preceding UTC dates. BTC itself does not require dominance data.</p>
      <p>Provide indicator warm-up before evaluation_start and at least two quote observations on each side of split_at. Quotes represent worker scan times; stops cannot react to unseen intrabar prices. Development and held-out periods start independent paper ledgers with identical saved parameters, allocation, and bankroll. The rest of the portfolio stays in cash. Chronological separation cannot certify that you have never inspected a holdout.</p>
      <p>Limit: 3,000 quotes and 12,000 observations per other series, ten years, 5 MiB total. Source accuracy, corporate-action adjustments, and survivorship must be checked by you. No options, futures, event-contract, or multi-symbol execution validation is implied.</p>
      <button type="button" onClick={() => download({ schema_version: 1, module: 'crypto', symbol: 'BTC', source: 'REPLACE with historical provider, quote provenance, and adjustment assumptions', evaluation_start: 'REPLACE with ISO-8601 time after warm-up', split_at: 'REPLACE with later chronological split time', bars: [], quotes: [], benchmark_bars: [], dominance_observations: [] }, 'portfolio-replay-input-template.json')}>Download empty input template</button>
    </details>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center', margin: '12px 0' }}>
      <label>Historical JSON <input type="file" accept=".json,application/json" disabled={running} onChange={load} /></label>
      <button type="button" disabled={!input || running} onClick={run}>{running ? 'Computing historical replay…' : 'Run read-only validation'}</button>
    </div>
    {input && <p>Selected: {filename} · {input.module} / {input.symbol} · {input.quotes?.length || 0} quote observations. The server uses current saved settings; this file cannot change them.</p>}
    {error && <p role="alert">{error}</p>}
    {running && <p role="status">Evaluating chronological windows and explicit cost, entry-latency, and missed-fill scenarios. No model is loading.</p>}
    {result && <div aria-label="Historical replay results">
      <h4>{result.module} / {result.symbol}: historical replay results</h4>
      <p>Declared source: {result.source} — not independently verified. Saved allocation: {metric(result.allocation_pct, '%')}; comparison target: {metric(result.target_cagr_pct, '% CAGR')}. The target gap below applies to an isolated-symbol replay with idle cash, not the combined strategy.</p>
      {Object.entries(result.windows || {}).map(([key, window]) => <div key={key}>
        <h5>{window.label}</h5>
        <p>{window.start} → {window.end} · {window.quote_observations} quote observations</p>
        <div className="quant-table-scroll"><table>
          <thead><tr><th>Scenario</th><th>Net period return</th><th>Annualized estimate</th><th>Target equity gap</th><th>Max drawdown</th><th>Entries / closed / open</th><th>Risk hold</th></tr></thead>
          <tbody>{window.scenarios.map(scenario => <tr key={scenario.scenario}>
            <td>{scenarioNames[scenario.scenario] || scenario.scenario}</td>
            <td>{metric(scenario.period_return_pct, '%')}</td>
            <td>{metric(scenario.annualized_return_pct, '%')}{scenario.annualized_return_pct != null && scenario.annualized_estimate_preliminary ? ' (preliminary)' : ''}</td>
            <td>{money(scenario.target_equity_gap)}</td><td>{metric(scenario.max_drawdown_pct, '%')}</td>
            <td>{scenario.entries} / {scenario.closed_trades} / {scenario.open_positions}</td><td>{scenario.circuit_paused ? 'New entries paused' : 'Not triggered'}</td>
          </tr>)}</tbody>
        </table></div>
        <details><summary>Signal, data-quality, and execution decisions</summary>
          {window.scenarios.map(scenario => <div key={scenario.scenario}><strong>{scenarioNames[scenario.scenario]}</strong>
            {Object.entries(scenario.decisions || {}).map(([reason, count]) => <p key={reason}>{reason.replaceAll('_', ' ')}: {count}</p>)}
          </div>)}
        </details>
      </div>)}
      <details><summary>Scope, assumptions, and unvalidated coverage</summary>
        {Object.entries(result.coverage || {}).map(([module, status]) => <p key={module}>{module}: {status.replaceAll('_', ' ')}</p>)}
        {result.assumptions.map((assumption, index) => <p key={index}>{assumption}</p>)}
        <p>Parameters used: <code>{JSON.stringify(result.saved_parameters)}</code></p>
      </details>
      <button type="button" onClick={() => download(result, `portfolio-replay-${result.module}-${result.symbol.replaceAll(/[^a-zA-Z0-9.-]/g, '_')}.json`)}>Download results, trades, and equity curves</button>
      <p>Results are not saved to the trading ledger or AI audit. Export them to preserve this experiment.</p>
    </div>}
  </section>;
}
