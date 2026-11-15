// Fixture-only integration test of row order, row identity and watchlist
// add/remove in the actual Dashboard. No request leaves the browser.
// PLAYWRIGHT_MODULE_PATH may point to an existing Playwright installation.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import http from 'node:http';
const root = path.resolve(import.meta.dirname, '..');
const require = createRequire(path.join(root, 'frontend/package.json'));
const { build } = require('esbuild');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const scratch = await mkdtemp(path.join(tmpdir(), 'dashboard-tables-'));
let browser, server;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
try {
  await build({
    stdin: { resolveDir: path.join(root, 'frontend'), loader: 'jsx', contents: `
      import React from 'react'; import {createRoot} from 'react-dom/client';
      import {MemoryRouter} from 'react-router-dom'; import Dashboard from './src/pages/Dashboard.jsx';
      import './src/index.css'; import './src/theme.css';
      const root=createRoot(document.getElementById('root'));
      window.unmountDashboard=()=>root.unmount();
      window.toasts=[]; window.addEventListener('app:new-toast', event => window.toasts.push(event.detail.message));
      root.render(<React.StrictMode><MemoryRouter><Dashboard isLightMode={false}/></MemoryRouter></React.StrictMode>);
    ` },
    bundle: true, outfile: path.join(scratch, 'app.js'),
    loader: { '.woff2': 'dataurl', '.woff': 'dataurl', '.ttf': 'dataurl', '.svg': 'dataurl', '.png': 'dataurl' },
    plugins: [{ name: 'dashboard-fixtures', setup(build) {
      build.onResolve({ filter: /\/AuthContext(?:\.jsx)?$/ }, () => ({ path: 'auth', namespace: 'fixture' }));
      build.onResolve({ filter: /\/DashboardWidgetGrid(?:\.jsx)?$/ }, () => ({ path: 'widgets', namespace: 'fixture' }));
      build.onLoad({ filter: /.*/, namespace: 'fixture' }, args => ({ contents: args.path === 'auth'
        ? 'export const useAuth=()=>({user:{id:1},isLoggingOut:false});'
        : 'export default function Widgets(){return null;}' }));
    } }],
  });
  server = http.createServer(async (req, res) => {
    if (req.url.startsWith('/app.')) {
      const css = req.url.startsWith('/app.css');
      res.setHeader('Content-Type', css ? 'text/css' : 'text/javascript');
      res.end(await readFile(path.join(scratch, css ? 'app.css' : 'app.js')));
    } else {
      res.setHeader('Content-Type', 'text/html');
      res.end('<html><head><link rel="stylesheet" href="/app.css"></head><body><div id="root"></div><script src="/app.js"></script></body></html>');
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox'] });
  const url = `http://127.0.0.1:${server.address().port}`;

  const watch = (id, symbol, extra = {}) => ({ id, symbol, asset_type: 'crypto', current_price: 10, sentiment: 'Hold', change_24h: 1, alert_enabled: false, favorite: false, ...extra });
  const webullRow = (id, symbol, account, extra = {}) => ({ id, source: 'webull', is_external: true, account_id: account, webull_account_id: account,
    symbol, instrument_type: 'EQUITY', amount: 2, current_price: 100, current_value: 200, ...extra });

  // Each scenario gets a fresh page and its own mutable fixture state.
  async function open(fixture, init) {
    const context = await browser.newContext({ viewport: { width: 1900, height: 1200 } });
    const page = await context.newPage();
    if (init) await page.addInitScript(init);
    // The symbol is the one unlabelled span; icons and badges carry a class or title.
    await page.addInitScript(() => { window.symbolOf = cell => cell?.querySelector('.coin-symbol-container > span:not([title]):not([class])')?.textContent.trim(); });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/**', async route => {
      const pathname = new URL(route.request().url()).pathname;
      const custom = await fixture.handle?.(pathname, route);
      if (custom) return;
      if (pathname === '/api/coin-data' || pathname === '/api/coin-data-live') {
        return route.fulfill({ json: { portfolio: fixture.portfolio(), account_totals: { all: 1, binance: 1, webull: 1 }, pending_orders: fixture.orders } });
      }
      if (pathname === '/api/pending-orders') return route.fulfill({ json: { pending_orders: fixture.orders } });
      if (pathname === '/api/watchlist-live' || pathname === '/api/watchlist') return route.fulfill({ json: fixture.watchlist() });
      if (pathname === '/api/orders') return route.fulfill({ json: { orders: [] } });
      if (pathname === '/api/settings') return route.fulfill({ json: {} });
      if (pathname === '/api/trading-pairs') return route.fulfill({ json: { pairs: [] } });
      return route.fulfill({ json: [] });
    });
    await page.goto(url);
    const refresh = async () => {
      await page.evaluate(() => window.dispatchEvent(new Event('app:refresh-dashboard')));
      await pause(250);
    };
    const symbolsIn = table => page.locator(`.${table}-table tbody tr td.symbol-cell`).evaluateAll(cells => cells.map(cell => window.symbolOf(cell)));
    const close = async () => {
      await page.evaluate(() => window.unmountDashboard());
      assert.deepEqual(errors, []);
      await context.close();
    };
    return { page, refresh, symbolsIn, close };
  }

  // 1. BTC and ETH keep their places whatever order the server returns (F21, F22).
  {
    let reads = 0;
    const fixture = { orders: [], portfolio: () => [], watchlist: () => (reads++ % 2 ? [watch(2, 'ETH'), watch(1, 'BTC')] : [watch(1, 'BTC'), watch(2, 'ETH')]) };
    const { page, refresh, symbolsIn, close } = await open(fixture);
    await page.locator('.watchlist-table tbody tr td.symbol-cell').first().waitFor();
    await page.evaluate(() => {
      window.orders = [];
      new MutationObserver(() => window.orders.push([...document.querySelectorAll('.watchlist-table tbody td.symbol-cell')].map(cell => window.symbolOf(cell)).join(',')))
        .observe(document.querySelector('.watchlist-table tbody'), { subtree: true, childList: true, characterData: true });
    });
    for (let i = 0; i < 6; i++) await refresh();
    assert.ok(reads >= 6, 'the server order really alternated');
    assert.deepEqual(await symbolsIn('watchlist'), ['BTC', 'ETH']);
    assert.ok((await page.evaluate(() => window.orders)).every(order => order === 'BTC,ETH'), 'no transient swap under the default order');
    assert.equal(await page.locator('[data-sort-table="watchlist"]').textContent(), 'Order: A–Z by symbol');
    // Equal values under a chosen sort: still fixed, in both directions.
    const sentiment = page.locator('.watchlist-table thead th').filter({ hasText: 'Sentiment' });
    for (const direction of ['▲', '▼']) {
      await sentiment.click();
      await page.locator('[data-sort-table="watchlist"]').filter({ hasText: `Sentiment ${direction}` }).waitFor();
      await page.evaluate(() => { window.orders = []; });
      for (let i = 0; i < 4; i++) await refresh();
      assert.deepEqual(await symbolsIn('watchlist'), ['BTC', 'ETH'], `tied sentiment ${direction}`);
      assert.ok((await page.evaluate(() => window.orders)).every(order => order === 'BTC,ETH'));
    }
    await close();
    console.log('Dashboard tables scenario passed: stable-order');
  }

  // 2. Sorting one table never changes the other; each preference is saved separately (F23, F24).
  {
    const fixture = { orders: [],
      portfolio: () => [{ id: 1, symbol: 'AAA', amount: 1, current_price: 1, current_value: 1 }, { id: 2, symbol: 'BBB', amount: 9, current_price: 5, current_value: 45 }],
      watchlist: () => [watch(1, 'AAA', { current_price: 1 }), watch(2, 'BBB', { current_price: 9 })] };
    const legacy = () => { if (!sessionStorage.getItem('seeded')) { sessionStorage.setItem('seeded', '1'); localStorage.setItem('dashboardSortConfig', JSON.stringify({ key: 'current_price', direction: 'desc' })); } };
    const { page, symbolsIn, close } = await open(fixture, legacy);
    await page.locator('.portfolio-table tbody tr td.symbol-cell').nth(1).waitFor();
    await page.locator('.watchlist-table tbody tr td.symbol-cell').nth(1).waitFor();
    assert.deepEqual(await symbolsIn('portfolio'), ['BBB', 'AAA'], 'the retired shared setting seeds the portfolio only');
    assert.deepEqual(await symbolsIn('watchlist'), ['AAA', 'BBB'], 'the watchlist starts from the stable default');
    await page.locator('.portfolio-table thead th').filter({ hasText: 'Amount' }).click();
    await page.locator('[data-sort-table="portfolio"]').filter({ hasText: 'Amount ▲' }).waitFor();
    assert.deepEqual(await symbolsIn('portfolio'), ['AAA', 'BBB']);
    assert.equal(await page.locator('[data-sort-table="watchlist"]').textContent(), 'Order: A–Z by symbol');
    await page.locator('.watchlist-table thead th').filter({ hasText: 'Current Price' }).click();
    await page.locator('.watchlist-table thead th').filter({ hasText: 'Current Price' }).click();
    await page.locator('[data-sort-table="watchlist"]').filter({ hasText: 'Current Price ▼' }).waitFor();
    assert.deepEqual(await symbolsIn('watchlist'), ['BBB', 'AAA']);
    assert.deepEqual(await symbolsIn('portfolio'), ['AAA', 'BBB'], 'sorting the watchlist left the portfolio alone');
    await page.reload();
    await page.locator('[data-sort-table="portfolio"]').filter({ hasText: 'Amount ▲' }).waitFor();
    await page.locator('[data-sort-table="watchlist"]').filter({ hasText: 'Current Price ▼' }).waitFor();
    await page.locator('.watchlist-table tbody tr td.symbol-cell').nth(1).waitFor();
    assert.deepEqual(await symbolsIn('watchlist'), ['BBB', 'AAA']);
    await page.locator('[data-sort-table="watchlist"] button').click();
    assert.equal(await page.locator('[data-sort-table="watchlist"]').textContent(), 'Order: A–Z by symbol');
    assert.deepEqual(await symbolsIn('watchlist'), ['AAA', 'BBB']);
    await close();
    console.log('Dashboard tables scenario passed: independent-sorts');
  }

  // 3. Same ticker at two providers / two accounts: an order highlights only its own row (F10, F11).
  {
    const fixture = { portfolio: () => [
      { id: 5, symbol: 'ETH', amount: 1, current_price: 100, current_value: 100 },
      webullRow('webull-5', 'ETH', 'A'), webullRow('webull-6', 'NVDA', 'A'), webullRow('webull-7', 'NVDA', 'B'),
    ], watchlist: () => [], orders: [
      { order_id: '900', provider: 'webull', account_id: 'A', asset: 'NVDA', symbol: 'NVDA', side: 'SELL', quantity: 1, price: 150 },
      { order_id: 901, provider: 'binance', asset: 'ETH', symbol: 'ETHUSDT', side: 'SELL', quantity: 1, price: 150 },
    ] };
    const { page, close } = await open(fixture);
    await page.waitForFunction(() => document.querySelectorAll('.portfolio-table tr.pending-order').length >= 2);
    await pause(400);
    const highlighted = await page.locator('.portfolio-table tbody tr').evaluateAll(rows => rows.map(row => `${window.symbolOf(row.querySelector('td.symbol-cell'))}:${row.classList.contains('pending-order')}`));
    assert.deepEqual(highlighted, ['ETH:true', 'ETH:false', 'NVDA:true', 'NVDA:false'], 'Binance ETH and account A NVDA only');
    await close();
    console.log('Dashboard tables scenario passed: exact-row-highlights');
  }

  // 4. A failed removal is reported and rolled back; a successful removal survives an older list (F26).
  {
    let list = [watch(1, 'BTC'), watch(2, 'ETH'), watch(3, 'SOL')];
    let failRemoval = true, held = null, holdNext = false, removals = [];
    const fixture = { orders: [], portfolio: () => [], watchlist: () => list,
      async handle(pathname, route) {
        if (pathname === '/api/watchlist/remove') {
          const body = route.request().postDataJSON();
          removals.push(body.symbol);
          if (failRemoval) { await route.fulfill({ status: 500, json: { error: 'offline' } }); return true; }
          list = list.filter(row => row.symbol !== body.symbol);
          await route.fulfill({ json: { success: true } });
          return true;
        }
        if (pathname === '/api/watchlist-live' && holdNext) { holdNext = false; held = { route, snapshot: list }; return true; }
        return false;
      } };
    const { page, refresh, symbolsIn, close } = await open(fixture);
    await page.locator('.watchlist-table tbody tr td.symbol-cell').nth(2).waitFor();
    const remove = symbol => page.locator('.watchlist-table tbody tr').filter({ hasText: symbol }).locator('button[title="Delete from watchlist"]').click();
    await remove('ETH');
    await page.waitForFunction(() => window.toasts.some(message => message.includes('Could not remove ETH')));
    assert.deepEqual(await symbolsIn('watchlist'), ['BTC', 'ETH', 'SOL'], 'the row is back in its place');

    failRemoval = false; holdNext = true;
    await page.evaluate(() => window.dispatchEvent(new Event('app:refresh-dashboard')));
    for (let tries = 0; !held && tries < 100; tries++) await pause(10);
    assert.ok(held, 'held a watchlist response that still contains SOL');
    await remove('SOL');
    await page.waitForFunction(() => document.querySelectorAll('.watchlist-table tbody td.symbol-cell').length === 2);
    await page.evaluate(() => {
      window.sawSol = false;
      new MutationObserver(() => { if (document.querySelector('.watchlist-table tbody').textContent.includes('SOL')) window.sawSol = true; })
        .observe(document.querySelector('.watchlist-table tbody'), { subtree: true, childList: true, characterData: true });
    });
    await held.route.fulfill({ json: held.snapshot }).catch(() => {});
    for (let i = 0; i < 3; i++) await refresh();
    assert.deepEqual(await symbolsIn('watchlist'), ['BTC', 'ETH']);
    assert.equal(await page.evaluate(() => window.sawSol), false, 'the removed row never flashed back');
    assert.deepEqual(removals, ['ETH', 'SOL']);
    await close();
    console.log('Dashboard tables scenario passed: watchlist-removal');
  }

  // 5. A setting saved while a refresh is in flight is not reverted by that refresh (F27).
  {
    let alertEnabled = false, held = null, holdNext = false;
    const fixture = { orders: [], portfolio: () => [], watchlist: () => [watch(1, 'BTC', { alert_enabled: alertEnabled })],
      async handle(pathname, route) {
        if (pathname === '/api/set-watch-alert') { alertEnabled = route.request().postDataJSON().alert_enabled; await route.fulfill({ json: { success: true } }); return true; }
        if (pathname === '/api/watchlist-live' && holdNext) { holdNext = false; held = { route, snapshot: [watch(1, 'BTC', { alert_enabled: false })] }; return true; }
        return false;
      } };
    const { page, refresh, close } = await open(fixture);
    const bell = page.locator('.watchlist-table tbody tr').filter({ hasText: 'BTC' }).locator('[title="Alerts enabled"], [title="Alerts disabled"]').first();
    await bell.waitFor();
    assert.equal(await bell.getAttribute('title'), 'Alerts disabled');
    holdNext = true;
    await page.evaluate(() => window.dispatchEvent(new Event('app:refresh-dashboard')));
    for (let tries = 0; !held && tries < 100; tries++) await pause(10);
    assert.ok(held, 'held a refresh that began before the save');
    await bell.click();
    await page.locator('.watchlist-table tbody tr [title="Alerts enabled"]').first().waitFor();
    await page.evaluate(() => {
      window.reverted = false;
      new MutationObserver(() => { if (document.querySelector('.watchlist-table tbody [title="Alerts disabled"]')) window.reverted = true; })
        .observe(document.querySelector('.watchlist-table tbody'), { subtree: true, childList: true, attributes: true, attributeFilter: ['title'] });
    });
    await held.route.fulfill({ json: held.snapshot }).catch(() => {});
    for (let i = 0; i < 3; i++) await refresh();
    assert.equal(await page.locator('.watchlist-table tbody tr [title="Alerts enabled"]').count() > 0, true);
    assert.equal(await page.evaluate(() => window.reverted), false, 'the saved alert never flipped back');
    await close();
    console.log('Dashboard tables scenario passed: saved-edit-survives-refresh');
  }
} finally {
  await browser?.close();
  if (server) await new Promise(resolve => server.close(resolve));
  await rm(scratch, { recursive: true, force: true });
}
