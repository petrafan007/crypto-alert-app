// Real prompt editors and engine modal, using local API fixtures only.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.AUDIT_TEST_ORIGIN || 'http://127.0.0.1:5178';
const definitions = JSON.parse(await readFile(new URL('../../config/ai_prompt_catalog.json', import.meta.url), 'utf8'));
let prompts = Object.fromEntries(Object.entries(definitions).map(([key, entry]) => [key, { ...entry, default: structuredClone(entry.value) }]));
let aiConfig = { event_evaluator: 'jev', audit_guidance: 'Saved audit guidance', ...Object.fromEntries(['primary', 'secondary', 'tertiary', 'quaternary'].map(tier => [tier, { provider: '', model: '', reasoning_level: 'medium', api_key: '' }])) };
let sentimentSaves = 0, engineSaves = 0;
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
page.on('console', event => { if (event.type() === 'error') console.error(event.text()); });
page.setDefaultTimeout(15000);
await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname.startsWith('/api/')) {
    let data = { success: true, settings: {}, orders: [], accounts: [], config: {}, modules: {}, datasets:[], runs:[], jobs:[] };
    if (url.pathname === '/api/session') data = { user: { id: 1, username: 'fixture', is_admin: true } };
    if (url.pathname === '/api/notifications') data = [];
    if (url.pathname === '/api/jev/telemetry') data = { sample_count:0, sample_limit:2000, pending_count:0, cost_reported_count:0, recent:[], calibration:{} };
    if (url.pathname === '/api/webull/portfolio-algo/research-data') data = { collection: { settings:{}, sources:[], lanes:[], stored_bytes:0, recent:[] } };
    if (url.pathname === '/api/settings') data = { ai_enabled: true, jev_enabled: true, jev_sentiment_mode: 'first', ai_provider: 'gemini', ai_prompts: {} };
    if (url.pathname === '/api/ai/prompt-catalog') {
      if (route.request().method() === 'POST') {
        const changes = route.request().postDataJSON();
        assert.equal(changes['jev.watchlist_sentiment'].direction.instructions, 'Saved watchlist evaluation instruction');
        for (const [key, value] of Object.entries(changes)) prompts[key].value = value;
        sentimentSaves++;
      }
      data = { success: true, prompts };
    }
    if (url.pathname === '/api/webull/portfolio-algo/config') data = { success: true, config: { module_settings: {}, watchlists: {}, master_ai_config: aiConfig }, defaults: {} };
    if (url.pathname === '/api/webull/portfolio-algo/status') data = { success: true, account: {total_equity:50000}, modules: {}, positions: [], performance: {} };
    if (url.pathname === '/api/webull/portfolio-algo/ai-config') {
      if (route.request().method() === 'POST') {
        const body = route.request().postDataJSON();
        assert.equal(body.ai_config.event_evaluator, 'jev');
        assert.ok(body.prompt_overrides['jev.contract_probability'].outcome.instructions.includes('saved contract instruction'));
        for (const [key, value] of Object.entries(body.prompt_overrides)) prompts[key].value = value;
        aiConfig = body.ai_config; engineSaves++;
      }
      data = { success: true, master_ai_prompt: 'Saved master mandate', default_master_ai_prompt: 'Default mandate', ai_config: aiConfig, audit_prompt_policy: {} };
    }
    return route.fulfill({ json: data });
  }
  if (route.request().resourceType() === 'document') return route.fulfill({ response: await route.fetch({ url: `${origin}/static/` }) });
  if (url.origin !== origin) return route.abort();
  return route.continue();
});
try {
  await page.goto(`${origin}/settings?tab=ai-prompts`);
  const watchlist = page.getByRole('region', { name: 'Jev watchlist sentiment analysis instructions' });
  await watchlist.locator('[id="jev.watchlist_sentiment-direction"]').fill('Saved watchlist evaluation instruction');
  await watchlist.getByRole('button', { name: 'Save instructions', exact: true }).click();
  await watchlist.getByText('Instructions saved. New evaluations use these settings.').waitFor();
  await page.reload();
  assert.equal(await watchlist.locator('[id="jev.watchlist_sentiment-direction"]').inputValue(), 'Saved watchlist evaluation instruction');
  assert.equal(await page.locator('textarea').filter({ hasText: 'CRITICAL: You MUST respond' }).count(), 0);
  await page.goto(`${origin}/settings?tab=quant-strategy`);
  await page.getByRole('button', { name: '🤖 AI Configuration', exact: true }).click();
  const modal = page.getByRole('dialog');
  const outcome = modal.locator('[id="jev.contract_probability-outcome"]');
  await outcome.fill('Evaluate contracts[{index}] ({symbol}) using the saved contract instruction.');
  assert.equal(await modal.locator('#event-evaluator').count(), 0);
  await modal.getByRole('button', { name: '💾 Save AI Configuration', exact: true }).click();
  await page.getByRole('button', { name: '🤖 AI Configuration', exact: true }).click();
  await outcome.waitFor();
  assert.ok((await outcome.inputValue()).includes('saved contract instruction'));
  assert.equal(sentimentSaves, 1); assert.equal(engineSaves, 1); assert.deepEqual(errors, []);
  console.log('Jev prompt browser checks passed: watchlist save/reload, typed answer descriptions, contract modal save/reopen, Jev-only predictions.');
} catch (error) {
  console.error({ errors, body: (await page.locator('body').innerText()).slice(-1800) });
  throw error;
} finally { await browser.close(); }
