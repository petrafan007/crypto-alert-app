// Run against a local Vite server; all API traffic is replaced with fixtures.
// PLAYWRIGHT_MODULE may point to an external playwright installation.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.POSITIONS_TEST_ORIGIN || 'http://127.0.0.1:5178';
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const errors = [];
page.setDefaultTimeout(15000);
page.on('pageerror', error => errors.push(error.message));
let userId = 1, failPositions = false, testEnabled = false;
const event = { id: 'event-1', symbol: 'KXBTC-TEST', instrument_type: 'EVENT', event_title: 'Will Bitcoin close above $70,000?', event_rules: 'Closing price must exceed $70,000.', event_outcome: 'NO', quantity: 50, cost_price: .33, last_price: 0, market_value: 0, unrealized_profit_loss: -16.5, collateral: 16.5, account_id: 'events-1234', account_name: 'Webull Events', source: 'webull', settlement: { cutoff_at: '2026-01-01T16:00:00Z', status: 'PENDING' } };
const equity = { id: 'equity-1', symbol: 'AAPL', instrument_type: 'EQUITY', quantity: 10, cost_price: 200, last_price: 210, market_value: 2100, unrealized_profit_loss: 100, account_id: 'cash-1234', source: 'webull' };
const crypto = { id: 'crypto-1', symbol: 'BTC', amount: 1, avg_entry: 60000, current_price: 70000, current_value: 70000, cost_basis: 60000 };
const paper = [{ ...event, id: 'paper-event', is_paper: true, source: 'webull_test' }];
const quant = [{ ...event, id: 'quant-event', is_paper: true, is_quant: true, source: 'webull_quant', purchased_outcome: 'NO' }];
await page.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (url.pathname.startsWith('/api/')) {
    let data = { success: true, orders: [], signals: [], settings: {}, accounts: [], summary: {}, analysis: null };
    if (url.pathname === '/api/session') data = { user: { id: userId, username: `user${userId}`, is_admin: userId === 1 } };
    if (url.pathname === '/api/coin-data-live') data = { portfolio: [event, equity, crypto], success: true };
    if (url.pathname === '/api/webull/test/status') data = { enabled: testEnabled };
    if (url.pathname === '/api/webull/test/toggle') testEnabled = route.request().postDataJSON().enabled;
    if (url.pathname === '/api/webull/test/positions') data = { success: true, positions: paper };
    if (url.pathname === '/api/webull/portfolio-algo/positions') {
      if (failPositions) return route.fulfill({ status: 503, json: { message: 'Positions temporarily unavailable' } });
      data = { success: true, positions: quant };
    }
    if (url.pathname === '/api/webull/accounts') data = { success: true, accounts: [{ account_id: 'cash-1234', account_name: 'Individual Cash', account_class: 'CASH', is_enabled: true }, { account_id: 'events-1234', account_name: 'Events', account_class: 'EVENT', is_enabled: true }] };
    if (url.pathname.includes('account-summary')) data = { success: true, summary: { total_cash_balance: 10000, total_equity: 10000 } };
    return route.fulfill({ json: data });
  }
  if (route.request().resourceType() === 'document') {
    const response = await route.fetch({ url: `${origin}/static/` });
    return route.fulfill({ response });
  }
  // No external APIs or third-party widgets are contacted during this test.
  if (url.origin !== origin) return route.abort();
  return route.continue();
});
const table = () => page.locator('.webull-positions');
const headers = () => table().locator('thead th button').allTextContents();
const asset = name => table().getByRole('group', { name: 'Position asset view' }).getByRole('button', { name: new RegExp(`^${name}`) }).click();
try {
  await page.goto(`${origin}/orders?tab=positions`);
  await table().getByText(/Real Trading — Positions/).waitFor();
  assert.equal(await table().locator('tbody .position-data-row').count(), 3);
  await asset('Event Contracts');
  assert.equal(await table().locator('tbody .position-data-row').count(), 1);
  assert.ok((await headers()).includes('Trading cutoff'));
  assert.equal(await table().locator('table').evaluate(el => getComputedStyle(el).tableLayout), 'fixed');
  assert.ok(await table().locator('.webull-positions-table-wrap').evaluate(el => el.scrollWidth > el.clientWidth));
  assert.equal(await table().locator('tbody .position-symbol').textContent(), 'KXBTC-TEST');
  assert.equal(await table().locator('.position-expand').count(), 0);
  assert.equal(await table().locator('.positions-drag-handle').count(), 0);
  await table().locator('th').filter({ hasText: 'Quantity' }).dragTo(table().locator('th').filter({ hasText: /^Mark$/ }).first());
  const reordered = await headers();
  assert.ok(reordered.indexOf('Quantity') > reordered.indexOf('Mark'));
  assert.match(reordered[0], /Symbol \/ ticker/); // Dragging did not change sorting.
  const symbolHeader = table().locator('th').filter({ hasText: /Symbol \/ ticker/ }).first();
  const initialWidth = (await symbolHeader.boundingBox()).width;
  const resizeHandle = symbolHeader.locator('.positions-column-resizer');
  const handleBox = await resizeHandle.boundingBox();
  await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(handleBox.x + handleBox.width / 2 + 55, handleBox.y + handleBox.height / 2);
  await page.mouse.up();
  assert.ok((await symbolHeader.boundingBox()).width >= initialWidth + 50);
  await table().getByRole('button', { name: 'Customize columns' }).click();
  const dialog = page.getByRole('dialog', { name: 'Customize columns' });
  await dialog.getByRole('button', { name: 'Move Quantity left', exact: true }).click();
  await dialog.getByRole('checkbox', { name: 'Show Time to cutoff', exact: true }).uncheck();
  await dialog.getByRole('button', { name: 'Done', exact: true }).click();
  assert.ok(!(await headers()).includes('Time to cutoff'));
  await asset('Equities & ETFs');
  assert.ok(!(await headers()).includes('Trading cutoff'));
  await page.reload();
  await table().getByText(/Real Trading — Positions/).waitFor();
  await asset('Event Contracts');
  assert.ok(!(await headers()).includes('Time to cutoff'));
  assert.ok((await table().locator('th').filter({ hasText: /Symbol \/ ticker/ }).first().boundingBox()).width >= initialWidth + 50);
  await page.getByRole('group', { name: 'Positions trading mode', exact: true }).getByRole('button', { name: 'Webull Test Mode', exact: true }).click();
  await table().getByText(/Test Mode — Paper Positions/).waitFor();
  assert.equal(await table().locator('tbody .position-data-row').count(), 1);
  await page.getByRole('group', { name: 'Positions trading mode', exact: true }).getByRole('button', { name: 'Quantitative Strategy', exact: true }).click();
  await table().getByText(/Quantitative Strategy — Paper Positions/).waitFor();
  failPositions = true;
  await page.getByRole('button', { name: 'Refresh positions', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'Positions temporarily unavailable' }).waitFor();
  assert.equal(await table().count(), 0);
  failPositions = false;
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await table().getByText(/Quantitative Strategy — Paper Positions/).waitFor();
  await page.getByRole('button', { name: /Open Orders/ }).click();
  await page.getByText('All Open Orders', { exact: true }).waitFor();
  assert.equal(await page.getByText('Loading combined orders…').count(), 0);

  await page.goto(`${origin}/trading/webull`);
  await table().getByText(/Real Trading — Positions/).waitFor();
  assert.equal(await table().getByRole('button', { name: /^Equities & ETFs/ }).getAttribute('aria-pressed'), 'true');
  assert.equal((await table().locator('tbody .position-symbol').first().textContent()).trim(), 'AAPL');
  assert.equal(await table().getByRole('button', { name: 'Load trade ticket', exact: true }).count(), 0);
  await page.getByRole('button', { name: /^Positions/ }).first().click();
  await table().getByText(/Real Trading — Positions/).waitFor();
  await asset('Event Contracts');
  assert.ok(!(await headers()).includes('Time to cutoff')); // Shared with /orders.
  await page.getByRole('button', { name: /🧪 Test Mode/ }).click();
  await table().getByText(/Test Mode — Paper Positions/).waitFor();
  await page.getByRole('button', { name: /Quantitative Strategy Mode$/ }).click();
  await table().getByText(/Quantitative Strategy — Paper Positions/).waitFor();
  await asset('Event Contracts');
  await table().getByRole('button', { name: 'Customize columns' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Reset to defaults' }).click();
  await page.keyboard.press('Escape');
  assert.ok((await headers()).includes('Time to cutoff'));
  if (process.env.POSITIONS_SCREENSHOT) await page.screenshot({ path: process.env.POSITIONS_SCREENSHOT });
  await page.setViewportSize({ width: 390, height: 844 });
  await table().getByRole('button', { name: 'Customize columns' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Move Quantity right' }).click();
  await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('dialog').count(), 0);

  userId = 2;
  await page.goto(`${origin}/orders?tab=positions`);
  await table().getByText(/Real Trading — Positions/).waitFor();
  assert.equal(await page.getByRole('button', { name: 'Quantitative Strategy', exact: true }).count(), 0);
  await asset('Event Contracts');
  assert.ok((await headers()).includes('Time to cutoff'));
  assert.deepEqual(errors, []);
  console.log('Positions browser checks passed: /orders and Webull real/test/quant, ticker-only rows, handle-free drag, resize persistence, filters, mobile, errors, user isolation.');
} catch (error) {
  if (process.env.POSITIONS_SCREENSHOT) await page.screenshot({ path: process.env.POSITIONS_SCREENSHOT });
  console.error('Browser page errors:', errors);
  throw error;
} finally {
  await browser.close();
}
