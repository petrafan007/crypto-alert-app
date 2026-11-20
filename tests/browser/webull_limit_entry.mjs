// Serve the frontend with Vite. All API calls use fixtures, including order review.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.POSITIONS_TEST_ORIGIN || 'http://127.0.0.1:5178';
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true });
try {
  const page = await browser.newPage();
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const account = { account_id: 'fixture', account_name: 'Individual Cash', cash_balance: 500, is_enabled: true };
  let quote = 91.79;
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname.startsWith('/api/')) {
      const fixtures = {
        '/api/session': { user: { id: 1, username: 'fixture', is_admin: true } },
        '/api/webull/test/status': { enabled: false },
        '/api/webull/accounts': { accounts: [account], default_account_id: account.account_id },
        '/api/coin-data-live': { portfolio: [] },
        '/api/webull/market-snapshot': { snapshot: { symbol: 'ANT', price: quote, has_traded: true } },
      };
      return route.fulfill({ json: fixtures[url.pathname] || { success: true, orders: [], signals: [], settings: {} } });
    }
    if (route.request().resourceType() === 'document') {
      return route.fulfill({ response: await route.fetch({ url: origin + '/static/' }) });
    }
    return route.continue();
  });
  await page.clock.install();
  await page.goto(origin + '/trading/webull?symbol=ANT&side=BUY&mode=REAL&instrument_type=EQUITY');
  const limit = page.getByRole('button', { name: 'Limit', exact: true });
  await limit.click();
  const qty = page.getByLabel('Order quantity for ANT');
  const price = page.getByLabel('Limit price per share ($)', { exact: true });
  const budget = page.locator('#quoteQuantity');
  await page.waitForFunction(() => document.querySelector('#price')?.value === '91.79');
  await qty.fill('1');
  await budget.fill('87');
  await budget.blur();
  assert.match(await limit.getAttribute('class'), /\bactive\b/);
  assert.ok(await page.getByRole('button', { name: 'By Shares (QTY)' }).evaluate(el => el.classList.contains('active')));
  await qty.fill('4.43064');
  await page.getByRole('button', { name: 'Use 4 whole shares' }).click();
  assert.equal(await qty.inputValue(), '4');
  assert.equal(await limit.isEnabled(), true);
  await qty.fill('1');
  await price.fill('87');
  await price.blur();
  assert.equal(await qty.inputValue(), '1');
  assert.equal(await budget.inputValue(), '87.00');
  quote = 92.50;
  const refresh = page.waitForResponse(response => response.url().includes('/api/webull/market-snapshot'));
  await page.clock.fastForward(31000);
  await refresh;
  assert.equal(await price.inputValue(), '87');
  assert.equal(await qty.inputValue(), '1');
  await page.locator('.modern-submit-button').click();
  const review = page.locator('.order-detail-row');
  await review.filter({ hasText: /Price:\s*\$87/ }).waitFor();
  assert.match(await review.allTextContents().then(rows => rows.join('\n')), /Quantity:\s*1\b/);
  assert.match(await review.allTextContents().then(rows => rows.join('\n')), /Limit/i);
  quote = 92.125;
  account.balance = { total_cash_balance: 600, available_cash: 412.48 };
  await page.goto(origin + '/trading/webull?symbol=ANT&side=BUY&mode=REAL&instrument_type=EQUITY');
  await page.getByRole('button', { name: 'Ladder / Trailing Stop', exact: true }).click();
  await page.locator('select').filter({ has: page.locator('option[value="CORE"]') }).selectOption('CORE');
  await qty.fill('4');
  await page.getByRole('button', { name: /Aggressive/ }).click();
  const warning = page.locator('#ladder-cash-warning');
  await warning.waitFor();
  const message = await warning.textContent();
  for (const amount of ['$414.56', '$412.48', '$2.08']) assert.ok(message.includes(amount), message);
  const submit = page.locator('.modern-submit-button');
  assert.ok(await submit.isDisabled());
  await qty.fill('3');
  await warning.waitFor({ state: 'hidden' });
  assert.ok(await submit.isEnabled());
  console.log('ANT ladder blocked at $414.56 against $412.48, then enabled after resizing.');
  assert.deepEqual(errors, []);
  console.log('Webull Limit by Shares remained 1 share at $87 through review.');
} finally {
  await browser.close();
}
