// Render each main page against stub API data and fail on any crash (for
// example React error #300 from a hook called after an early return).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.AUDIT_TEST_ORIGIN || 'http://127.0.0.1:5178';
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
// Flask serves the single-page app's index.html at every page path; assets
// come from the preview server under /static/.
const indexHtml = readFileSync(process.env.DIST_INDEX || fileURLToPath(new URL('../../frontend/dist/index.html', import.meta.url)), 'utf8');
const failures = [];
const stub = (path) => {
  if (path === '/api/session' || path === '/api/check-auth' || path === '/api/user') return { authenticated: true, user: { id: 1, username: 'fixture', is_admin: true } };
  if (path === '/api/notifications') return [];
  if (path === '/api/settings') return { ai_enabled: false, ai_provider: 'openai', ai_model: 'fixture', webull_configured: false, tax_cost_basis_method: 'fifo' };
  if (path === '/api/tax-report') return { transactions: [], summary: { total_gain_loss: 0, needs_review_count: 0, manual_invested_amount: 0 }, current_holdings: {}, fifo_lots: {} };
  if (path === '/api/credential-health') return { success: true, providers: {} };
  return { success: true, settings: {}, orders: [], accounts: [], config: {}, modules: {}, items: [], data: [] };
};
for (const path of ['/settings', '/tax-report-binance', '/tax-report-webull', '/help', '/orders']) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/api/')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(stub(url.pathname)) });
    }
    if (!url.pathname.startsWith('/static/')) {
      return route.fulfill({ status: 200, contentType: 'text/html', body: indexHtml });
    }
    return route.continue();
  });
  await page.goto(origin + path, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  const bodyText = await page.locator('body').innerText();
  assert.ok(!/did you mean to visit/.test(bodyText), `${path} did not load the app`);
  const crashed = await page.getByText('View Loading Error').count();
  const hookCrash = errors.filter((message) => /Minified React error|Rendered (fewer|more) hooks/.test(message));
  if (crashed || hookCrash.length) failures.push(`${path}: ${crashed ? 'error boundary shown; ' : ''}${hookCrash.join(' | ')}`);
  await page.close();
}
await browser.close();
assert.deepEqual(failures, []);
console.log('page smoke test passed');
