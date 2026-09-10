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
