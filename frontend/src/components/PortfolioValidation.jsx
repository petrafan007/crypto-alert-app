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
    <h4>Historical research validation</h4>
    <p>Administrator-only, read-only replay of one equities or crypto symbol, or Event forecast/book sensitivity using your saved rules. Import actual historical observations; nothing is fetched, traded, or sent to AI. This is not a full-portfolio backtest or proof of the CAGR target.</p>
    <details>
      <summary>Historical input format and limitations</summary>
      <p>JSON schema version 1 requires <code>module</code> (equities or crypto), <code>symbol</code>, a description of <code>source</code>, <code>evaluation_start</code>, <code>split_at</code>, <code>bars</code>, and <code>quotes</code>. Timestamps should include a UTC offset. Quotes contain <code>time</code> and <code>price</code>. Bars contain their opening <code>time</code> plus <code>open/high/low/close</code>; volume is optional. Use daily NYSE-session bars for equities and hourly bars for crypto. Optional <code>available_at</code> records delayed publication, never before candle completion.</p>
      <p>Equities additionally require daily SPY <code>benchmark_bars</code>. Altcoins require BTC <code>dominance_observations</code> with <code>time/value</code>: a current observation within one hour and all seven preceding UTC dates. BTC itself does not require dominance data.</p>
      <p>Provide indicator warm-up before evaluation_start and at least two quote observations on each side of split_at. Quotes represent worker scan times; stops cannot react to unseen intrabar prices. Development and held-out periods start independent paper ledgers with identical saved parameters, allocation, and bankroll. The rest of the portfolio stays in cash. Chronological separation cannot certify that you have never inspected a holdout.</p>
      <p>Limit: 3,000 quotes and 12,000 observations per other series, ten years, 5 MiB total. Source accuracy, corporate-action adjustments, and survivorship must be checked by you. The spot replay does not validate options, futures, Event contracts, or combined multi-symbol execution.</p>
      <p>For Event research, use module <code>events</code>, source, split_at and 2–2,000 unique contract records. Each record supplies symbol, decision_at, cutoff_at, resolved_at, outcome, probability_yes, confidence and a matching market object with bids, asks, sizes and timestamp provenance. Optional independent_quote_at enables timestamp comparisons. Explicit timezone offsets are required. The experiment reports calibration and one-contract book/cost sensitivities; it does not simulate aggregate bankroll risk.</p>
      <button type="button" onClick={() => download({schema_version:1,module:'events',source:'REPLACE with exact provider and settlement provenance',split_at:'REPLACE with chronological split timestamp',records:[]}, 'event-validation-template.json')}>Download Event input template</button>
      <button type="button" onClick={() => download({ schema_version: 1, module: 'crypto', symbol: 'BTC', source: 'REPLACE with historical provider, quote provenance, and adjustment assumptions', evaluation_start: 'REPLACE with ISO-8601 time after warm-up', split_at: 'REPLACE with later chronological split time', bars: [], quotes: [], benchmark_bars: [], dominance_observations: [] }, 'portfolio-replay-input-template.json')}>Download empty input template</button>
    </details>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center', margin: '12px 0' }}>
      <label>Historical JSON <input type="file" accept=".json,application/json" disabled={running} onChange={load} /></label>
      <button type="button" disabled={!input || running} onClick={run}>{running ? 'Computing historical replay…' : 'Run read-only validation'}</button>
    </div>
    {input && <p>Selected: {filename} · {input.module}{input.symbol ? ` / ${input.symbol}` : ''} · {input.module === 'events' ? input.records?.length || 0 : input.quotes?.length || 0} observations. The server uses current saved settings; this file cannot change them.</p>}
    {error && <p role="alert">{error}</p>}
    {running && <p role="status">Evaluating chronological windows and explicit cost, entry-latency, and missed-fill scenarios. No model is loading.</p>}
    {result?.scope === 'event_forecast_book_sensitivity' && <div aria-label="Event validation results">
      <h4>Event forecast and reported-book sensitivity</h4>
      <p>Declared source: {result.source}. Source identity and outcomes are not independently certified.</p>
      {Object.entries(result.windows).map(([key, window]) => <div key={key}><h5>{key.replace('_', ' ')} · {window.contracts} contracts</h5>
        <p>Paired independent timestamps: {window.paired_independent_timestamps}. Missing pairs cannot validate retrieval-time freshness.</p>
        <p>Resolved forecasts: {window.calibration.resolved_contracts}. Brier score: {metric(window.calibration.brier_score)}. Matched market Brier score: {metric(window.calibration.market_brier_score)}. Relative skill: {metric(window.calibration.skill_score)}.</p>
        <p>Lower Brier scores are better. Skill and calibration are descriptive; small or correlated samples do not establish profitability.</p>
        <table><thead><tr><th>Scenario</th><th>Hypothetical fills</th><th>Net P&amp;L</th></tr></thead><tbody>
        {window.scenarios.map(row => <tr key={row.scenario}><td>{row.scenario}</td><td>{row.filled_contracts}</td><td>{row.net_pnl == null ? 'Unavailable' : money(row.net_pnl)}</td></tr>)}
        </tbody></table></div>)}
      {result.assumptions.map(text => <p key={text}>{text}</p>)}
      <button type="button" onClick={() => download(result, 'event-research-validation.json')}>Download evidence and results</button>
    </div>}
    {result && result.scope !== 'event_forecast_book_sensitivity' && <div aria-label="Historical replay results">
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
