// Exercise the real Settings tab with local API fixtures; never contact providers.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.AUDIT_TEST_ORIGIN || 'http://127.0.0.1:5178';
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
page.setDefaultTimeout(15000);
const errors = [];
page.on('pageerror', error => errors.push(error.message));
let saves = 0, tests = 0;
let settings = { ai_enabled: false, ai_provider: 'openai', ai_model: 'fixture', ai_gateway_key: '',
  jev_enabled: false, jev_transport: 'vercel', jev_model: 'typesafe-ai/jev', jev_endpoint: 'https://ai-gateway.vercel.sh/v1/evaluate',
  jev_timeout_seconds: 3, jev_confidence_threshold: .8, jev_conflict_threshold: .5, jev_sentiment_mode: 'off',
  jev_generative_fallback_enabled: true, jev_quant_shadow_enabled: false };
await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname.startsWith('/api/')) {
    let data = { success: true, settings: {}, orders: [], accounts: [], config: {}, modules: {} };
    if (url.pathname === '/api/session') data = { user: { id: 1, username: 'fixture', is_admin: true } };
    if (url.pathname === '/api/notifications') data = [];
    if (url.pathname === '/api/ai/models') data = { openai: [{ value: 'fixture', label: 'Fixture' }], ollama: [] };
    if (url.pathname === '/api/settings') {
      if (route.request().method() === 'POST') {
        const body = route.request().postDataJSON();
        assert.equal(body.jev_transport, 'vercel');
        assert.equal(body.jev_sentiment_mode, 'shadow');
        assert.equal(body.jev_quant_shadow_enabled, true);
        assert.equal(body.ai_gateway_key, 'synthetic-browser-key');
        settings = { ...settings, ...body, ai_gateway_key: '********' };
        saves++;
      }
      data = settings;
    }
    if (url.pathname === '/api/jev/test-connection') {
      assert.equal(route.request().postDataJSON().ai_gateway_key, '********');
      data = { success: true, model: 'typesafe-ai/jev', latency_ms: 42, message: 'Jev evaluation connection succeeded.' };
      tests++;
    }
    if (url.pathname === '/api/jev/telemetry') data = { sample_count: 0, sample_limit: 2000, pending_count: 0, cost_reported_count: 0, recent: [], calibration: {} };
    return route.fulfill({ json: data });
  }
  if (route.request().resourceType() === 'document') return route.fulfill({ response: await route.fetch({ url: `${origin}/static/` }) });
  if (url.origin !== origin) return route.abort();
  return route.continue();
});
try {
  await page.goto(`${origin}/settings?tab=ai-providers`);
  await page.getByRole('heading', { name: 'Jev Decision Engine (Experimental)' }).waitFor();
  const enabled = page.getByLabel('Enable Jev', { exact: true });
  assert.equal(await enabled.isChecked(), false);
  assert.equal(await page.getByLabel('Sentiment mode').inputValue(), 'off');
  await enabled.check();
  const key = page.getByLabel('Vercel AI Gateway API key', { exact: true });
  assert.equal(await key.getAttribute('type'), 'password');
  await key.fill('synthetic-browser-key');
  await page.getByLabel('Sentiment mode').selectOption('shadow');
  await page.getByLabel('Enable quant shadow observations').check();
  await page.getByRole('button', { name: 'Save Jev Settings', exact: true }).click();
  await page.getByText(/Jev settings saved/).waitFor();
  assert.equal(await key.inputValue(), '********');
  await page.getByRole('button', { name: 'Test Jev Connection', exact: true }).click();
  await page.getByText(/Latency: 42 ms/).waitFor();
  await page.reload();
  await page.getByRole('heading', { name: 'Jev Decision Engine (Experimental)' }).waitFor();
  assert.equal(await key.inputValue(), '********');
  assert.equal(await page.getByLabel('Sentiment mode').inputValue(), 'shadow');
  assert.equal(await page.getByLabel('Enable quant shadow observations').isChecked(), true);
  await page.getByText(/Paper gate: unavailable in v4.0.0/).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await key.scrollIntoViewIfNeeded();
  const box = await key.boundingBox();
  assert.ok(box.width > 100 && box.x >= 0 && box.x + box.width <= 391, JSON.stringify(box));
  assert.equal(saves, 1);
  assert.equal(tests, 1);
  assert.deepEqual(errors, []);
  console.log('Jev browser checks passed: tab placement, defaults, masked key, save/reload, test connection, shadow controls, mobile layout.');
} catch (error) {
  console.error({ errors, text: (await page.locator('body').innerText()).slice(-3000) });
  throw error;
} finally { await browser.close(); }
