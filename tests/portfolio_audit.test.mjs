import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizePortfolioAudit, selectPortfolioAudit, auditOutcomeMessage } from '../frontend/src/utils/portfolioAudit.mjs';

test('archive content and timestamp survive normalization and history selection', () => {
  const audits = [
    { id: 4, timestamp: '2026-09-06T15:13:09Z', status: 'FAILED', content: "AI audit failed: 'instrument_type'.", evidence: {} },
    { id: 2, timestamp: '2026-09-06T03:12:21Z', status: 'SUCCESS', content: '## Portfolio report\nExisting detailed assessment.', evidence: { open_positions_count: 0 } },
  ].map(normalizePortfolioAudit);
  const old = selectPortfolioAudit(audits, '2');
  assert.equal(old.id, 2);
  assert.equal(old.created_at, '2026-09-06T03:12:21Z');
  assert.match(old.content_markdown, /Existing detailed assessment/);
  assert.equal(selectPortfolioAudit(audits, null).id, 4);
  assert.equal(selectPortfolioAudit([], null), null);
  assert.match(auditOutcomeMessage(audits[0]), /instrument_type/);
  assert.doesNotMatch(auditOutcomeMessage(audits[0]), /completed/);
});

test('pending and incomplete reports never claim successful completion', () => {
  for (const status of ['PENDING', 'PARTIAL', 'FAILED', 'UNAVAILABLE']) {
    const audit = normalizePortfolioAudit({ id: 1, status, content: ' ' });
    assert.ok(audit.content_markdown.trim());
    assert.notEqual(auditOutcomeMessage(audit), 'Portfolio AI audit completed.');
  }
  assert.match(auditOutcomeMessage({ status: 'PENDING' }), /queued/);
  assert.match(auditOutcomeMessage({ status: 'PARTIAL' }), /limitations/);
});
