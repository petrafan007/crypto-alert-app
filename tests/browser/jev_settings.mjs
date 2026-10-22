// Exercise the real Decision Engine settings tab with local API fixtures; never contact providers.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.AUDIT_TEST_ORIGIN || 'http://127.0.0.1:5178';
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
page.setDefaultTimeout(15000);
const errors = [];
page.on('pageerror', error => errors.push(error.message));
let saves = 0, tests = 0;
let settings = {
  ai_enabled: false, ai_provider: 'openai', ai_model: 'fixture', ai_gateway_key: '',
  ai_gateway_key_configured: false, openrouter_api_key: '', openrouter_api_key_configured: false,
  subq_api_key: '', subq_api_key_configured: false,
  jev_enabled: false, jev_transport: 'vercel', jev_model: 'typesafe-ai/jev', jev_endpoint: 'https://ai-gateway.vercel.sh/v1/evaluate',
  jev_timeout_seconds: 3, jev_confidence_threshold: .8, jev_conflict_threshold: .5, jev_sentiment_mode: 'off',
  jev_generative_fallback_enabled: true, jev_quant_shadow_enabled: false,
};
const keyFields = ['ai_gateway_key', 'openrouter_api_key', 'subq_api_key'];
const providerLabels = { vercel: 'Vercel AI Gateway', openrouter: 'OpenRouter', subq: 'SubQ' };
const providerKeys = { vercel: 'ai_gateway_key', openrouter: 'openrouter_api_key', subq: 'subq_api_key' };
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
        assert.equal(body.jev_sentiment_mode, 'first');
        assert.equal(body.jev_quant_shadow_enabled, true);
        assert.equal(body.jev_generative_fallback_enabled, false);
        const selectedKey = providerKeys[body.jev_transport];
        assert.ok(body[selectedKey] === 'synthetic-browser-key' || body[selectedKey] === '********');
        const updated = { ...settings, ...body };
        for (const field of keyFields) {
          const incoming = body[field];
          const configured = incoming === '********'
            ? settings[`${field}_configured`] === true
            : Boolean(incoming);
          updated[field] = configured ? '********' : '';
          updated[`${field}_configured`] = configured;
        }
        settings = updated;
        saves++;
      }
      data = { ...settings };
    }
    if (url.pathname === '/api/jev/test-connection') {
      const body = route.request().postDataJSON();
      const selectedKey = providerKeys[body.jev_transport];
      assert.equal(body[selectedKey], '********');
      data = {
        success: true, model: body.jev_model, provider: providerLabels[body.jev_transport],
        latency_ms: 42, message: 'Decision Engine connection succeeded.',
      };
      tests++;
    }
    if (url.pathname === '/api/jev/telemetry') data = {
      sample_count: 0, sample_limit: 2000, pending_count: 0, cost_reported_count: 0,
      recent: [], calibration: {},
    };
    return route.fulfill({ json: data });
  }
  if (route.request().resourceType() === 'document') return route.fulfill({ response: await route.fetch({ url: `${origin}/static/` }) });
  if (url.origin !== origin) return route.abort();
  return route.continue();
});
try {
  await page.goto(`${origin}/settings?tab=ai-providers`);
  await page.getByRole('heading', { name: 'Decision Engine' }).waitFor();
  const enabled = page.getByLabel('Enable Decision Engine', { exact: true });
  assert.equal(await enabled.isChecked(), false);
  assert.equal(await page.getByLabel('Sentiment mode').inputValue(), 'off');
  await enabled.check();
  await page.getByLabel('Sentiment mode').selectOption('first');
  await page.getByLabel('Enable crypto quantitative shadow evaluations').check();

  const provider = page.getByLabel('Decision provider');
  const model = page.getByLabel('Decision model');
  assert.equal(await provider.inputValue(), 'vercel');
  assert.equal(await model.inputValue(), 'typesafe-ai/jev');
  const vercelKey = page.getByLabel('Vercel AI Gateway API key', { exact: true });
  assert.equal(await vercelKey.getAttribute('type'), 'password');
  await vercelKey.fill('synthetic-browser-key');
  await page.getByRole('button', { name: 'Save Settings', exact: true }).click();
  await page.getByText(/Decision Engine settings saved\. Vercel AI Gateway/).waitFor();
  assert.equal(await vercelKey.inputValue(), '********');
  await page.getByRole('button', { name: 'Test Connection', exact: true }).click();
  await page.getByText(/Decision Engine connection succeeded.*Provider: Vercel AI Gateway.*Latency: 42 ms/).waitFor();

  await page.reload();
  await page.getByRole('heading', { name: 'Decision Engine' }).waitFor();
  assert.equal(await vercelKey.inputValue(), '********');
  assert.equal(await page.getByLabel('Sentiment mode').inputValue(), 'first');
  assert.equal(await page.getByLabel('Enable crypto quantitative shadow evaluations').isChecked(), true);
  assert.equal(await page.getByText('Jev Decision Engine', { exact: true }).count(), 0);

  await provider.selectOption('subq');
  assert.equal(await model.inputValue(), 'subq-snap-1.1');
  assert.equal(await model.getAttribute('readonly'), '');
  const subqKey = page.getByLabel('SubQ API key', { exact: true });
  assert.equal(await subqKey.getAttribute('type'), 'password');
  await subqKey.fill('synthetic-subq-key');
  await page.getByRole('button', { name: 'Save Settings', exact: true }).click();
  await page.getByText(/Decision Engine settings saved\. SubQ/).waitFor();
  assert.equal(await subqKey.inputValue(), '********');
  await page.getByRole('button', { name: 'Test Connection', exact: true }).click();
  await page.getByText(/Decision Engine connection succeeded.*Provider: SubQ.*Model: subq-snap-1.1.*Latency: 42 ms/).waitFor();
  await page.reload();
  await page.getByRole('heading', { name: 'Decision Engine' }).waitFor();
  assert.equal(await provider.inputValue(), 'subq');
  assert.equal(await model.inputValue(), 'subq-snap-1.1');
  assert.equal(await subqKey.inputValue(), '********');

  await page.setViewportSize({ width: 390, height: 844 });
  await subqKey.scrollIntoViewIfNeeded();
  const box = await subqKey.boundingBox();
  assert.ok(box.width > 100 && box.x >= 0 && box.x + box.width <= 391, JSON.stringify(box));
  assert.equal(saves, 2);
  assert.equal(tests, 2);
  assert.deepEqual(errors, []);
  console.log('Decision Engine browser checks passed: provider/model-aware labels, masked credentials, save/reload, both test connections, and mobile layout.');
} catch (error) {
  console.error({ errors, text: (await page.locator('body').innerText()).slice(-3000) });
  throw error;
} finally { await browser.close(); }
