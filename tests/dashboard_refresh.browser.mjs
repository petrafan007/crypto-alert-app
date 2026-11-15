// Fixture-only integration test of the actual Dashboard and cancellation modal.
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
const scratch = await mkdtemp(path.join(tmpdir(), 'dashboard-refresh-'));
let browser, server;
try {
  await build({
    stdin: { resolveDir: path.join(root, 'frontend'), loader: 'jsx', contents: `
      import React from 'react'; import {createRoot} from 'react-dom/client';
      import {MemoryRouter} from 'react-router-dom'; import Dashboard from './src/pages/Dashboard.jsx';
      import './src/index.css'; import './src/theme.css';
      const root=createRoot(document.getElementById('root'));
      window.unmountDashboard=()=>root.unmount();
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
  for (const scenario of ['confirmed', 'pending', 'failed', 'empty', 'unavailable', 'zero-total', 'missing-total']) {
    const page = await browser.newPage({ viewport: { width: 1800, height: 1100 } });
    await page.addInitScript(() => {
      localStorage.setItem('dashboard_totalValue', '999999');
      localStorage.setItem('dashboard_accountTotals', JSON.stringify({ all: 999999, binance: 999999, webull: 999999 }));
    });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const order = { order_id: 'ladder_21', provider: 'webull', account_id: 'A', asset: 'NVDA', symbol: 'NVDA', side: 'BUY', quantity: 1, price: 100, quote_amount: 100, is_synthetic: true };
    const portfolio = [
      { id: 1, source: 'webull', is_external: true, account_id: 'A', webull_account_id: 'A', symbol: 'NVDA', instrument_type: 'EQUITY', amount: 2, current_price: 100, current_value: 200 },
      { id: 2, source: 'webull', is_external: true, account_id: 'A', webull_account_id: 'A', symbol: 'USD', instrument_type: 'CASH', amount: 1000, current_price: 1, current_value: 1000 },
    ];
    let orderReads = 0, cachedReads = 0, cancellations = 0, delayedRoute;
    let holdNext = false, empty = false, unavailable = false;
    const snapshot = { portfolio, account_totals: { all: 1200, binance: 0, webull: 1200 }, pending_orders: [order] };
    await page.route('**/api/**', async route => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname.endsWith('/cancel')) {
        cancellations++;
        assert.equal(pathname, '/api/trading/ladder-orders/21/cancel');
        assert.equal(route.request().postDataJSON().two_factor_code, '123456');
        return route.fulfill({ json: scenario === 'failed' ? { success: false, error: 'Fixture broker rejected cancellation' }
          : { success: true, ladder_order: { status: scenario === 'pending' ? 'CANCEL_PENDING' : 'CANCELLED' } } });
      }
      if (pathname === '/api/coin-data') { cachedReads++; return route.fulfill({ json: snapshot }); }
      if (pathname === '/api/coin-data-live') return route.fulfill({ json: snapshot });
      if (pathname === '/api/pending-orders') {
        orderReads++;
        if (holdNext) { holdNext = false; delayedRoute = route; return; }
        return route.fulfill(unavailable ? { status: 503, json: { error: 'offline' } } : { json: { pending_orders: empty ? [] : [order] } });
      }
      if (pathname === '/api/orders') return route.fulfill({ json: { orders: [] } });
      if (pathname === '/api/settings') return route.fulfill({ json: {} });
      if (pathname === '/api/trading-pairs') return route.fulfill({ json: { pairs: [] } });
      return route.fulfill({ json: [] });
    });
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.waitForFunction(() => document.querySelectorAll('tr.pending-order').length === 2);
    // Observe every rendered highlight after cancellation, including brief flashes.
    await page.evaluate(() => {
      window.highlightCounts = [];
      new MutationObserver(() => window.highlightCounts.push(document.querySelectorAll('tr.pending-order').length))
        .observe(document.getElementById('root'), { subtree: true, attributes: true, attributeFilter: ['class'], childList: true });
    });
    if (['zero-total', 'missing-total'].includes(scenario)) {
      snapshot.account_totals = scenario === 'zero-total' ? { all: 0, binance: 0, webull: 0 } : { all: null };
      await page.evaluate(() => window.dispatchEvent(new Event('app:refresh-dashboard')));
      if (scenario === 'zero-total') await page.getByText('Total Value: $0.00 USD', { exact: true }).waitFor();
      else {
        await page.getByText('Totals unavailable · showing last totals', { exact: true }).waitFor();
        await page.getByText('Total Value: $1,200.00 USD', { exact: true }).waitFor();
      }
      assert.equal(await page.getByText(/999,999/).count(), 0, 'old unscoped financial cache is ignored');
    } else if (['empty', 'unavailable'].includes(scenario)) {
      empty = scenario === 'empty'; unavailable = scenario === 'unavailable';
      const before = orderReads;
      await page.evaluate(() => window.dispatchEvent(new Event('app:refresh-dashboard')));
      await page.waitForFunction(() => !document.body.textContent.includes('Saved snapshot'));
      await new Promise(resolve => setTimeout(resolve, 250));
      assert.ok(orderReads > before);
      assert.equal(await page.locator('tr.pending-order').count(), empty ? 0 : 2);
    } else {
      holdNext = true;
      await page.evaluate(() => window.dispatchEvent(new Event('app:refresh-dashboard')));
      for (let tries = 0; !delayedRoute && tries < 100; tries++) await new Promise(resolve => setTimeout(resolve, 10));
      assert.ok(delayedRoute, 'held an old pending-order response');
      const row = page.locator('tbody tr').filter({ hasText: 'NVDA' }).first();
      const cancel = row.locator('button[title^="Cancel "]');
      if (await cancel.count()) await cancel.click();
      else {
        await row.locator('.actions-dropdown-btn').click();
        await page.getByRole('menuitem').filter({ hasText: 'Cancel' }).click();
      }
      await page.locator('.cancel-confirm-modal input').fill('123456');
      await page.getByRole('button', { name: 'Yes, Cancel Order', exact: true }).click();
      if (scenario === 'confirmed') {
        await page.waitForFunction(() => document.querySelectorAll('tr.pending-order').length === 0);
        await page.evaluate(() => { window.highlightCounts = []; });
      } else {
        await page.getByText(scenario === 'failed' ? 'Fixture broker rejected cancellation' : /Cancellation requested\./).waitFor();
      }
      await delayedRoute.fulfill({ json: { pending_orders: [order] } }).catch(() => {});
      await new Promise(resolve => setTimeout(resolve, 300));
      assert.equal(await page.locator('tr.pending-order').count(), scenario === 'confirmed' ? 0 : 2);
      if (scenario === 'confirmed') {
        assert.ok(orderReads >= 3, 'post-cancel read completed with stale cached order fixture');
        assert.ok((await page.evaluate(() => window.highlightCounts)).every(count => count === 0), 'no transient highlight resurrection');
      }
      assert.equal(cancellations, 1);
    }
    assert.ok(cachedReads <= 2, 'cached hydration is not repeated by refresh events (StrictMode may abort first mount)');
    await page.evaluate(() => window.unmountDashboard());
    assert.deepEqual(errors, []);
    await page.close();
    console.log(`Dashboard fixture scenario passed: ${scenario}`);
  }
} finally {
  await browser?.close();
  if (server) await new Promise(resolve => server.close(resolve));
  await rm(scratch, { recursive: true, force: true });
}
