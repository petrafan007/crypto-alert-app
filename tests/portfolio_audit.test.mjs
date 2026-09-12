import test from 'node:test';
import assert from 'node:assert/strict';
import {
  humanizeAuditSlug,
  cleanHumanText,
  buildExecutiveSummary,
  normalizePortfolioAudit,
} from '../frontend/src/utils/portfolioAudit.mjs';

test('humanizeAuditSlug maps known technical slugs to human phrases', () => {
  assert.equal(humanizeAuditSlug('warming_up'), 'Calibrating indicators & collecting history');
  assert.equal(humanizeAuditSlug('available_capacity'), 'Available buying power & capital headroom');
  assert.equal(humanizeAuditSlug('market_closed'), 'U.S. regular market closed (session inactive)');
  assert.equal(humanizeAuditSlug('circuit_paused'), 'Trading paused by portfolio risk circuit');
  assert.equal(humanizeAuditSlug('no_signal'), 'Market scanned; no qualifying trade setups');
  assert.equal(humanizeAuditSlug('data_limited'), 'Market quote feed temporarily delayed or incomplete');
  assert.equal(humanizeAuditSlug('custom_signal_name'), 'Custom Signal Name');
});

test('cleanHumanText strips raw slugs from prose', () => {
  const input = 'Module status: warming_up, capacity: `available_capacity`, state: market_closed.';
  const cleaned = cleanHumanText(input);
  assert.ok(!cleaned.includes('warming_up'));
  assert.ok(!cleaned.includes('available_capacity'));
  assert.ok(!cleaned.includes('market_closed'));
  assert.ok(cleaned.includes('Calibrating indicators & collecting history'));
  assert.ok(cleaned.includes('Available buying power & capital headroom'));
  assert.ok(cleaned.includes('U.S. regular market closed (session inactive)'));
});

test('buildExecutiveSummary derives healthy status and plain-English explanation', () => {
  const mockAudit = {
    id: 101,
    status: 'SUCCESS',
    headline: 'Macro strategy performing normally',
    content: 'All systems green.',
    evidence: {
      worker_status: 'RUNNING',
      enabled: true,
      modules: { crypto: { status: 'READY', enabled: true } },
      specialist_mandates: {
        equity_momentum: { title: 'Equity Momentum' },
        crypto_trend: { title: 'Crypto Trend' },
      },
      module_audits: {
        equity_momentum: { status: 'ready', summary: 'Scanned 15 tickers' },
        crypto_trend: { status: 'ready', summary: 'Scanned 8 pairs' },
      },
    },
  };

  const summary = buildExecutiveSummary(mockAudit);
  assert.equal(summary.healthStatus, 'healthy');
  assert.ok(summary.healthLabel.includes('Operating Properly'));
  assert.ok(summary.isOperatingProperly);
  assert.ok(summary.statusExplanation.includes('operating properly'));
  assert.equal(summary.modules.length, 2);
  assert.ok(summary.recommendations.length > 0);
});

test('buildExecutiveSummary derives degraded status on module error and gives repair recommendations', () => {
  const mockAudit = {
    id: 102,
    status: 'PARTIAL',
    content: 'Failed to evaluate crypto.',
    evidence: {
      worker_status: 'RUNNING',
      enabled: true,
      modules: { crypto: { status: 'READY', enabled: true } },
      specialist_mandates: {
        crypto_trend: { title: 'Crypto Trend' },
      },
      module_audit_errors: {
        crypto_trend: 'Binance API rate_limited',
      },
    },
  };

  const summary = buildExecutiveSummary(mockAudit);
  assert.equal(summary.healthStatus, 'degraded');
  assert.ok(!summary.isOperatingProperly);
  assert.ok(summary.statusExplanation.includes('requires inspection') || summary.statusExplanation.includes('require inspection'));
  assert.ok(summary.recommendations.some((rec) => rec.includes('Repair CRYPTO_TREND')));
});

test('health uses structured evidence, never narrative or report success alone', () => {
  const running = {worker_status: 'RUNNING', enabled: true, kill_switch: false, modules: {events: {status: 'NO_SIGNAL'}}};
  const cases = [
    [{status: 'FAILED', content: 'All systems healthy.'}, 'degraded'],
    [{status: 'UNAVAILABLE'}, 'degraded'],
    [{status: 'SUCCESS', content: 'All systems healthy.'}, 'idle'],
    [{status: 'PENDING', evidence: running}, 'pending'],
    [{status: 'SUCCESS', content: 'The risk circuit is not triggered.', evidence: running}, 'healthy'],
    [{status: 'SUCCESS', evidence: {...running, kill_switch: true}}, 'paused'],
    [{status: 'SUCCESS', evidence: {...running, worker_status: 'DEGRADED'}}, 'degraded'],
    [{status: 'SUCCESS', evidence: {...running, modules: {events: {status: 'DATA_LIMITED'}}}}, 'degraded'],
    [{status: 'SUCCESS', evidence: {...running, enabled: false, worker_status: 'STOPPED'}}, 'idle'],
    [{status: 'SUCCESS', evidence: {...running, modules: {crypto: {status: 'WARMING_UP'}}}}, 'healthy'],
    [{status: 'SUCCESS', evidence: {...running, modules: {equities: {status: 'MARKET_CLOSED'}}}}, 'healthy'],
    [{status: 'SUCCESS', evidence: {...running, modules: {events: {status: 'AWAITING_SCAN'}}}}, 'idle'],
  ];
  for (const [audit, expected] of cases) {
    const result = buildExecutiveSummary(audit);
    assert.equal(result.healthStatus, expected, JSON.stringify(audit));
    assert.equal(result.isOperatingProperly, expected === 'healthy');
    assert.ok(!result.headline.includes('Engine Healthy'));
  }
});
