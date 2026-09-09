// Actual Settings/telemetry components; all API traffic stays in local fixtures.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.AUDIT_TEST_ORIGIN || 'http://127.0.0.1:5178';
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(15000);
const errors = [];
page.on('pageerror', error => errors.push(error.message));
const policy = { engine_purpose: 'PAPER research only.', evidence_rules: 'The configured numeric target overrides legacy ranges. Do not invent missing measurements.', default_guidance: 'Explain measured target gaps and controlled experiments.', master_scope: 'Master scope fixture.', module_scope: 'Specialist scope fixture.' };
const goal = { mode: 'PAPER', target_annual_return_pct: 18.5, started_at: '2025-01-01T00:00:00Z', as_of: '2026-01-01T00:00:00Z', elapsed_days: 365,
  current_equity: 55000, target_equity: 59250, target_gap_usd: -4250, target_gap_pct: -7.17299578, total_return_pct: 10, annualized_return_pct: 10, cagr_gap_pct_points: -8.5,
  annualization_min_days: 30, capital_utilization_pct: 54.55, reserved_capital_usd: 29000,
  annualization_note: 'Thirty days is a display threshold, not validation.', target_note: 'Hypothetical target, not a forecast.',
  module_contributions: [{ module: 'equities', net_pnl: 5000, contribution_pct_points: 10 }], unattributed_pnl_usd: 0,
  observations: { observed_calendar_days: 2, expected_calendar_days: 366, missing_calendar_days: 364, snapshot_count: 2, gap_ranges: [{ start: '2025-01-02', end: '2025-12-31', days: 364 }] },
  rolling_returns: { '30': { return_pct: null, reason: 'Missing recorded boundary.' }, '90': { return_pct: null, reason: 'Missing recorded boundary.' }, '365': { return_pct: 10, target_return_pct: 18.5, actual_elapsed_days: 365, missing_calendar_days: 364 } },
  curve: [{ time: '2025-01-01T00:00:00Z', equity: 50000, target_equity: 50000 }, { time: '2026-01-01T00:00:00Z', equity: 55000, target_equity: 59250 }],
};
let settings = { success: true, audit_hours: 6, master_ai_prompt: 'My preserved custom mandate: 16.5–21%.', default_master_ai_prompt: 'Current canonical master mandate.', audit_prompt_policy: policy,
  ai_config: { audit_guidance: policy.default_guidance, ...Object.fromEntries(['primary', 'secondary', 'tertiary'].map(tier => [tier, { provider: 'gemini', model: 'gemini-fixture', reasoning_level: 'low', api_key: '', has_key: false }])) } };
let saves = 0;
await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname.startsWith('/api/')) {
    let data = { success: true, settings: {}, orders: [], accounts: [], config: {}, modules: {} };
    if (url.pathname === '/api/session') data = { user: { id: 1, username: 'fixture', is_admin: true } };
    if (url.pathname === '/api/notifications') data = [];
    if (url.pathname === '/api/webull/portfolio-algo/audits') data = { success: true, audits: [{ id: 42, status: 'SUCCESS', created_at: goal.as_of, content: 'Recorded audit fixture.', evidence: { goal_tracking: goal }, generation: 1 }] };
    if (url.pathname === '/api/webull/portfolio-algo/config') data = { success: true, config: { module_settings: { futures: { enabled: false } }, watchlists: {}, master_ai_config: settings.ai_config }, defaults: {}, audit_prompt_policy: policy };
    if (url.pathname === '/api/webull/portfolio-algo/status') data = { success: true, account: { total_equity: 55000 }, goal_tracking: goal, modules: {}, positions: [], performance: {} };
    if (url.pathname === '/api/webull/portfolio-algo/ai-config') {
      if (route.request().method() === 'POST') {
        const body = route.request().postDataJSON();
        settings = { ...settings, ai_config: body.ai_config, master_ai_prompt: body.master_ai_prompt };
        saves += 1;
      }
      data = settings;
    }
    return route.fulfill({ json: data });
  }
  if (route.request().resourceType() === 'document') return route.fulfill({ response: await route.fetch({ url: `${origin}/static/` }) });
  if (url.origin !== origin) return route.abort();
  return route.continue();
});
try {
  await page.goto(`${origin}/settings?tab=quant-strategy`);
  const telemetry = page.getByRole('region', { name: 'Paper execution and performance' });
  await telemetry.getByRole('heading', { name: /18.50% annual research goal/ }).waitFor();
  await telemetry.getByText('$59,250.00', { exact: true }).waitFor();
  await telemetry.getByText('-8.50 pp', { exact: true }).waitFor();
  await telemetry.getByText(/Observation coverage: 2 \/ 366 UTC days/).click();
  await telemetry.getByText('2025-01-02 through 2025-12-31: 364 missing snapshot day(s)', { exact: true }).waitFor();
  await page.getByRole('button', { name: '📊 View report', exact: true }).click();
  let dialog = page.getByRole('dialog');
  await dialog.getByText('REPORT COMPLETE', { exact: true }).waitFor();
  await dialog.getByText('-8.50 pp', { exact: true }).waitFor();
  await dialog.getByText(/does not imply healthy workers/).waitFor();
  await dialog.getByRole('button', { name: 'Close report', exact: true }).click();
  await page.getByRole('button', { name: '🤖 AI Configuration', exact: true }).click();
  dialog = page.getByRole('dialog');
  const guidance = dialog.getByLabel('Shared goal review & experiment guidance (master and all specialists)', { exact: true });
  assert.equal(await guidance.inputValue(), policy.default_guidance);
  assert.equal(await dialog.getByLabel('Master CIO / Auditor System Prompt', { exact: true }).inputValue(), settings.master_ai_prompt);
  await dialog.getByText('Shared system instructions applied to this master prompt', { exact: true }).click();
  await dialog.getByText(policy.evidence_rules, { exact: true }).waitFor();
  await guidance.fill('My custom measurable experiment guidance.');
  await dialog.getByRole('button', { name: '💾 Save AI Configuration', exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('[role="dialog"]'));
  assert.equal(saves, 1);
  assert.equal(settings.ai_config.audit_guidance, 'My custom measurable experiment guidance.');
  assert.equal(settings.master_ai_prompt, 'My preserved custom mandate: 16.5–21%.');
  await page.reload();
  await page.getByRole('button', { name: '🤖 AI Configuration', exact: true }).click();
  assert.equal(await page.getByLabel('Shared goal review & experiment guidance (master and all specialists)', { exact: true }).inputValue(), 'My custom measurable experiment guidance.');
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: 'Configure Equities & ETFs', exact: true }).click();
  await page.getByText('Shared system instructions applied to this specialist prompt', { exact: true }).click();
  await page.getByText('My custom measurable experiment guidance.', { exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log('Goal browser checks passed: observed gap, coverage, saved report, prompt visibility, editable guidance save/reload, specialist disclosure.');
} catch (error) {
  console.error({ errors, text: (await page.locator('body').innerText()).slice(-4000) });
  throw error;
} finally { await browser.close(); }
