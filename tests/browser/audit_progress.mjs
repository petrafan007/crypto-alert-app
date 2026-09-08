// Exercise the actual Settings modal; every API response is a fixture.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.AUDIT_TEST_ORIGIN || 'http://127.0.0.1:5178';
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(15000);
const errors = [];
page.on('pageerror', error => errors.push(error.message));
let audit = { id: 42, status: 'PENDING', timestamp: new Date(Date.now() - 120000).toISOString(), content: 'Audit in progress.',
  progress: { percent: 45, stage: 'module', current_module: 'options', modules: ['equities', 'crypto', 'options', 'events'], completed_modules: ['equities', 'crypto'], failed_modules: [], provider: 'ollama', tier: 'secondary', model: 'nemotron-3-ultra:cloud', event: 'retrying' },
  evidence: { provider_attempts: [{ stage: 'module', module: 'options', event: 'retrying', tier: 'secondary', model: 'nemotron-3-ultra:cloud', error: 'Ollama HTTP 500: temporary server error' }] } };
await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname.startsWith('/api/')) {
    let data = { success: true, settings: {}, orders: [], accounts: [], config: {}, modules: {} };
    if (url.pathname === '/api/session') data = { user: { id: 1, username: 'fixture', is_admin: true } };
    if (url.pathname === '/api/notifications') data = [];
    if (url.pathname === '/api/webull/portfolio-algo/audits') data = { success: true, audits: [audit] };
    if (url.pathname === '/api/webull/portfolio-algo/config') data = { success: true, config: { module_settings: { futures: { enabled: false } }, watchlists: {}, master_ai_config: {} }, defaults: {} };
    return route.fulfill({ json: data });
  }
  if (route.request().resourceType() === 'document') return route.fulfill({ response: await route.fetch({ url: `${origin}/static/` }) });
  if (url.origin !== origin) return route.abort();
  return route.continue();
});
const openReport = async () => {
  await page.getByRole('button', { name: '📊 View report', exact: true }).click();
  await page.getByRole('heading', { name: /Quantitative Portfolio AI Audit Report/ }).waitFor();
};
try {
  await page.goto(`${origin}/settings?tab=quant-strategy`);
  await openReport();
  const bar = page.getByRole('progressbar', { name: 'Approximate audit completion' });
  assert.equal(await bar.getAttribute('aria-valuenow'), '45');
  await page.getByText('2 / 4 enabled specialists finished', { exact: true }).waitFor();
  await page.getByText('Provider retries and fallback reasons (1)', { exact: true }).click();
  await page.getByRole('region', { name: 'AI audit progress' }).getByText(/Ollama HTTP 500: temporary server error/).waitFor();
  assert.ok(await page.getByRole('button', { name: /Analyzing worker/ }).isDisabled());
  await page.getByRole('button', { name: 'Close report', exact: true }).click();
  await page.reload();
  await openReport();
  assert.equal(await bar.getAttribute('aria-valuenow'), '45');
  audit = { ...audit, progress: { ...audit.progress, percent: 85, stage: 'master', current_module: null, completed_modules: audit.progress.modules, event: 'started' } };
  await page.waitForFunction(() => document.querySelector('[aria-label="Approximate audit completion"]')?.getAttribute('aria-valuenow') === '85');
  await page.getByText('Live audit #42: Master CIO synthesis', { exact: true }).waitFor();
  audit = { ...audit, status: 'SUCCESS', content: 'Completed master report.', progress: { ...audit.progress, percent: 100, stage: 'complete', elapsed_seconds: 180 } };
  await page.waitForFunction(() => document.querySelector('[aria-label="Approximate audit completion"]')?.getAttribute('aria-valuenow') === '100');
  await page.getByText('Completed master report.', { exact: true }).waitFor();
  assert.ok(await page.getByRole('button', { name: /Generate Fresh Report Now/ }).isEnabled());
  assert.deepEqual(errors, []);
  console.log('Audit modal browser checks passed: real percentage, enabled count, retry detail, reload, polling, and terminal completion.');
} catch (error) {
  console.error({ errors, text: (await page.locator('body').innerText()).slice(-3500) });
  throw error;
} finally { await browser.close(); }
