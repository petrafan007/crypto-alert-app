// Run against a local Vite server; all API traffic is replaced with fixtures.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.ORDER_TABLE_TEST_ORIGIN || 'http://127.0.0.1:5178';
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const errors = [];
let userId = 1;
page.setDefaultTimeout(15000);
page.on('pageerror', (error) => errors.push(error.message));

const openOrders = [
  { id: '2', symbol: 'ETHUSD', side: 'SELL', order_type: 'LIMIT', quantity: 2, price: 2500, filled_quantity: 0, status: 'NEW', created_at: '2026-09-02T12:00:00Z' },
  { id: '1', symbol: 'BTCUSD', side: 'BUY', order_type: 'LIMIT', quantity: 1, price: 70000, filled_quantity: 0, status: 'NEW', created_at: '2026-09-01T12:00:00Z' },
];

await page.route('**/*', async (route) => {
  const url = new URL(route.request().url());
  if (url.pathname.startsWith('/api/')) {
    let data = { success: true };
    if (url.pathname === '/api/session') data = { user: { id: userId, username: `user${userId}`, is_admin: true } };
    else if (url.pathname === '/api/webull/accounts') data = { accounts: [], enabled_account_ids: [] };
    else if (url.pathname === '/api/trading/open-orders') data = { orders: openOrders };
    else if (url.pathname === '/api/trading/real-orders') data = { orders: openOrders, total: openOrders.length };
    else if (url.pathname === '/api/coin-data-live') data = { portfolio: [] };
    else if (url.pathname === '/api/ai/workflow-latest') data = {};
    return route.fulfill({ json: data });
  }
  if (route.request().resourceType() === 'document') return route.fulfill({ response: await route.fetch({ url: `${origin}/static/` }) });
  if (url.origin !== origin) return route.abort();
  return route.continue();
});

const table = () => page.locator('.configurable-order-table').first();
const headers = () => table().locator('thead th button').allTextContents();

try {
  await page.goto(`${origin}/orders?tab=open`);
  await page.getByRole('heading', { name: 'All Open Orders' }).waitFor();
  assert.equal(await table().locator('tbody tr').count(), 2);

  await table().locator('th').filter({ hasText: 'Symbol' }).getByRole('button').click();
  assert.match((await table().locator('tbody tr').first().innerText()), /BTCUSD/);
  await table().locator('th').filter({ hasText: 'Symbol' }).getByRole('button').click();
  assert.match((await table().locator('tbody tr').first().innerText()), /ETHUSD/);

  await table().getByRole('button', { name: 'Filter', exact: true }).click();
  const filterDialog = page.getByRole('dialog', { name: 'Order filters' });
  await filterDialog.getByRole('searchbox').fill('BTC');
  await filterDialog.getByRole('button', { name: 'Done', exact: true }).click();
  assert.equal(await table().locator('tbody tr').count(), 1);

  await table().getByRole('button', { name: 'Customize columns' }).click();
  const columnsDialog = page.getByRole('dialog', { name: 'Customize columns' });
  await columnsDialog.getByRole('checkbox', { name: 'Show Fee', exact: true }).uncheck();
  await columnsDialog.getByRole('button', { name: 'Move Symbol left', exact: true }).click();
  await columnsDialog.getByRole('button', { name: 'Done', exact: true }).click();
  assert.ok(!(await headers()).includes('Fee'));

  await page.reload();
  await page.getByRole('heading', { name: 'All Open Orders' }).waitFor();
  assert.equal(await table().locator('tbody tr').count(), 1);
  assert.ok(!(await headers()).includes('Fee'));
  assert.match((await table().locator('tbody tr').first().innerText()), /BTCUSD/);

  userId = 2;
  await page.reload();
  await page.getByRole('heading', { name: 'All Open Orders' }).waitFor();
  assert.equal(await table().locator('tbody tr').count(), 2);
  assert.ok((await headers()).includes('Fee'));
  assert.deepEqual(errors, []);
  console.log('Order table browser checks passed: sort, filter, column visibility/order, reload persistence, and user isolation.');
} catch (error) {
  console.error({ errors, text: (await page.locator('body').innerText()).slice(-2500) });
  throw error;
} finally {
  await browser.close();
}
