// All API requests are fixtures; never contacts an exchange or places a real order.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.POSITIONS_TEST_ORIGIN || 'http://127.0.0.1:5178';
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
page.setDefaultTimeout(15000);
const errors = [], requests = [], purchases = [];
page.on('pageerror', error => errors.push(error.message));
let receipt = null, testEnabled = true, delayBalances = true;
const holdings = [{ id: 'etf', symbol: 'ETH', amount: 9, current_price: 23.44, current_value: 210.96, avg_entry: 34.4681, source: 'webull', is_external: true, instrument_type: 'EQUITY', webull_account_type: 'Traditional IRA', account_id: 'live-cash', sentiment: 'Hold' }, { symbol: 'BTC', amount: 1, current_price: 70000, current_value: 70000, avg_entry: 60000, sentiment: 'Hold' }];
const assets = Array.from({ length: 5 }, (_, index) => ({ stakingAsset: `COIN${index}`, apy: (15-index)/100, minStakingLimit: 1, unstakingPeriod: 168, quoteAssets: ['USD', 'USDT'] }));
await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname.startsWith('/api/')) {
    requests.push(url.pathname + url.search);
    let data = { success: true, orders: [], signals: [], settings: {}, accounts: [], summary: {}, analysis: null };
    if (url.pathname === '/api/session') data = { user: { id: 1, username: 'fixture', is_admin: true } };
    if (['/api/coin-data', '/api/coin-data-live'].includes(url.pathname)) data = { portfolio: holdings };
    if (['/api/watchlist', '/api/watchlist-live'].includes(url.pathname)) data = [{ symbol: 'SOL', current_price: 100, sentiment: 'Hold' }];
    if (['/api/orders', '/api/trading-pairs', '/api/staking/stakeable-coins'].includes(url.pathname)) data = [];
    if (url.pathname === '/api/check-trade-permission') data = { has_api_key: true, has_permission: true };
    if (url.pathname === '/api/trading/settings') data = { settings: { require_2fa: false, totp_enabled: false, test_mode_enabled: false } };
    if (url.pathname === '/api/staking/discovery') data = { userId: 1, assets, recommendations: assets, balances: { USD: { balance: 50 }, USDT: { balance: 100 } } };
    if (url.pathname === '/api/staking/balance') {
      if (delayBalances) await new Promise(resolve => setTimeout(resolve, 4000));
      data = { balances: [], summary: {} };
    }
    if (['/api/staking/history', '/api/staking/rewards'].includes(url.pathname)) data = [];
    if (url.pathname === '/api/staking/purchases' && route.request().method() === 'POST') {
      const body = route.request().postDataJSON(); purchases.push(body);
      receipt = { ...body, status: 'bought_not_staked', purchasedQuantity: '9.9', message: 'Purchase filled; staking unavailable. Your coins remain available.' };
      data = receipt;
    }
    if (url.pathname.startsWith('/api/staking/purchases/')) data = receipt;
    if (url.pathname === '/api/webull/test/status') data = { enabled: testEnabled };
    if (url.pathname === '/api/webull/test/toggle') testEnabled = route.request().postDataJSON().enabled;
    if (url.pathname === '/api/webull/test/positions') data = { success: true, positions: [] };
    if (url.pathname === '/api/webull/accounts') data = { accounts: [{ account_id: 'live-cash', account_name: 'Individual Cash', is_enabled: true }], enabled_account_ids: ['live-cash'], default_account_id: 'live-cash' };
    if (url.pathname === '/api/webull/open-orders') {
      assert.equal(url.searchParams.get('account_id'), 'live-cash');
      data = { success: true, orders: [] };
    }
    return route.fulfill({ json: data });
  }
  if (route.request().resourceType() === 'document') return route.fulfill({ response: await route.fetch({ url: `${origin}/static/` }) });
  if (url.origin !== origin) return route.abort();
  return route.continue();
});
try {
  await page.goto(`${origin}/staking`);
  await page.getByRole('heading', { name: 'Recommended Coins to Stake' }).waitFor();
  await page.getByRole('button', { name: 'Trade', exact: true }).first().waitFor();
  assert.equal(await page.getByRole('button', { name: 'Trade', exact: true }).count(), 5);
  assert.ok(await page.getByRole('status').filter({ hasText: 'Refreshing staking balances' }).isVisible());
  assert.ok(!requests.some(url => url.startsWith('/api/coin-data')));
  delayBalances = false;
  await page.getByRole('button', { name: 'Trade', exact: true }).first().click();
  const modal = page.getByRole('dialog', { name: 'Purchase to stake' });
  await modal.getByRole('combobox').selectOption('USDT');
  await modal.getByRole('spinbutton', { name: 'Purchase amount' }).fill('20');
  await modal.getByRole('button', { name: 'Confirm purchase and stake' }).click();
  await modal.getByText('Purchase filled; staking unavailable. Your coins remain available.').waitFor();
  await modal.getByRole('button', { name: 'Refresh receipt' }).click();
  assert.equal(purchases.length, 1);
  assert.equal(purchases[0].quoteAsset, 'USDT');
  assert.equal(purchases[0].stake, true);
  await modal.getByRole('button', { name: 'Close', exact: true }).click();
  await page.reload();
  await page.getByRole('button', { name: 'View last purchase receipt' }).click();
  await modal.getByText('Purchase filled; staking unavailable. Your coins remain available.').waitFor();
  assert.equal(purchases.length, 1);

  await page.goto(`${origin}/`);
  const typeHeaders = page.locator('th.asset-type-header');
  await typeHeaders.first().waitFor();
  assert.equal(await typeHeaders.count(), 2);
  for (const header of await typeHeaders.all()) assert.equal(await header.evaluate(element => getComputedStyle(element).textAlign), 'center');
  await page.locator('td.asset-type-cell').getByText('Traditional IRA', { exact: true }).waitFor();
  assert.equal(await page.locator('.symbol-cell .webull-account-pill').count(), 0);
  await page.reload();
  await typeHeaders.first().waitFor();

  await page.goto(`${origin}/trading/webull`);
  await page.getByRole('button', { name: /Real Trading Mode/ }).click();
  await page.getByText('Switched to Webull Live Trading Mode.').waitFor();
  await page.waitForFunction(() => document.body.textContent.includes('Individual Cash'));
  assert.ok(!await page.getByText('Choose one of your enabled Webull accounts.', { exact: false }).count());
  assert.ok(requests.some(url => url.startsWith('/api/webull/open-orders?account_id=live-cash')));
  assert.deepEqual(errors, []);
  console.log('v2.94.0 browser checks passed: independent staking load, five recommendations, purchase receipt/replay, centered Type columns, account switching.');
} catch (error) {
  console.error({ errors, typeCells: await page.locator('td.asset-type-cell').allTextContents(), text: (await page.locator('body').innerText()).slice(-3500) });
  throw error;
} finally { await browser.close(); }
