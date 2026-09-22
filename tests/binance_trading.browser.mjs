// Run with PLAYWRIGHT_MODULE_PATH pointing to an installed Playwright package.
// All HTTP calls use fixtures; this harness never loads account data or places orders.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import http from 'node:http';
const root = path.resolve(import.meta.dirname, '..');
const require = createRequire(path.join(root, 'frontend/package.json'));
const { build } = require('esbuild');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || process.argv[2] || 'playwright');
const scratch = await mkdtemp(path.join(tmpdir(), 'synthetic-browser-'));
let browser, server;
try {
  await build({ stdin: { resolveDir: path.join(root, 'frontend'), loader: 'jsx', contents: `
    import React from 'react'; import {createRoot} from 'react-dom/client';
    import Trading from './src/pages/Trading.jsx'; import {AuthProvider} from './src/components/AuthContext.jsx'; import {BrowserRouter} from 'react-router-dom';
    import './src/theme.css'; import './src/light-theme.css'; import './src/theme-variables.css'; import './src/index.css'; import './src/pages/Trading.theme.css';
    const theme=new URLSearchParams(location.search).get('theme');document.body.className=theme+'-mode';document.documentElement.dataset.theme=theme;
    createRoot(document.getElementById('root')).render(<BrowserRouter><AuthProvider><Trading isLightMode={theme==='light'} /></AuthProvider></BrowserRouter>);
` }, bundle: true, outfile: path.join(scratch, 'app.js'), loader: { '.woff2': 'dataurl', '.woff': 'dataurl', '.ttf': 'dataurl', '.svg': 'dataurl', '.png': 'dataurl' } });
  server = http.createServer(async (req, res) => {
    if (req.url.startsWith('/app.')) {
      const isCss = req.url.startsWith('/app.css'); res.setHeader('Content-Type', isCss ? 'text/css' : 'text/javascript');
      res.end(await readFile(path.join(scratch, isCss ? 'app.css' : 'app.js')));
    } else { res.setHeader('Content-Type', 'text/html'); res.end('<html><head><link rel="stylesheet" href="/app.css"></head><body><div id="root"></div><script src="/app.js"></script></body></html>'); }
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox'] });
  for (const theme of ['dark','light']) {
    const page = await browser.newPage({ viewport:{width:1440,height:1100} });
    const errors=[];page.on('pageerror',e=>errors.push(e.message));let paper=false, cash=1200, deposits=[];
    await page.route('**/*', async route=>{
      const url=new URL(route.request().url());
      if(url.hostname!=='127.0.0.1') return route.abort();
      if(!url.pathname.startsWith('/api/')) return route.continue();
      let data={success:true,orders:[],trailing_orders:[],ladder_orders:[],holdings:[],coins:[],pairs:[],has_api_key:true,has_permission:true};
      if(url.pathname==='/api/session')data={user:{id:1,username:'fixture'}};
      if(url.pathname==='/api/trading/settings'){
        if(route.request().method()==='POST') paper=route.request().postDataJSON().test_mode_enabled??paper;
        data={success:true,settings:{test_mode_enabled:paper,max_order_size_usd:5000,require_2fa:true}};
      }
      if(url.pathname.includes('/price/'))data={success:true,prices:{base:86515.98,base_asset:'BTC',quote:1,quote_asset:'USDT'}};
      if(url.pathname.includes('/balances/'))data={success:true,balances:{base:.01251477,base_asset:'BTC',quote:cash,quote_asset:'USDT'}};
      if(url.pathname.includes('/fees/'))data={success:true,fees:{symbol:'BTCUSDT',paper,takerRate:.0002,rates:{SELL:{taker:.0002},BUY:{taker:.0002}},quantityStep:'.00001',bnb:{enabled:false},source:'Account fee fixture',as_of:'2026-09-22T12:00:00Z'}};
      if(url.pathname.includes('/order-types'))data={success:true,order_types:[{value:'MARKET',label:'Market'},{value:'LADDER',label:'Ladder / Trailing Stop'}]};
      if(url.pathname==='/api/trading/paper-account')data={success:true,balances:{USD:0,USDT:cash}};
      if(url.pathname==='/api/trading/paper-account/deposit'){const body=route.request().postDataJSON();deposits.push(body);cash+=body.amount;data={success:true,balances:{USD:0,USDT:cash},message:'Deposit saved'};}
      return route.fulfill({json:data});
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/trading?theme=${theme}`);
    const dust=page.getByRole('button',{name:'Convert Dust'}), limit=page.getByRole('button',{name:/Order Limit:.*5,000/});
    await limit.waitFor();const dustBox=await dust.boundingBox(),limitBox=await limit.boundingBox();
    assert.ok(Math.abs(dustBox.y-limitBox.y)<1);assert.ok(Math.abs(dustBox.height-limitBox.height)<1);
    await limit.click();assert.ok(await page.getByText('Maximum Order Size', {exact:false}).count());
    await page.getByRole('button',{name:'Cancel',exact:true}).last().click();
    await page.locator('.binance-header-controls .toggle-switch').click();
    await page.getByRole('button',{name:'OK',exact:true}).click();
    await page.getByRole('button',{name:'Deposit Fake Money'}).click();
    await page.getByRole('dialog').waitFor();
    assert.ok((await page.getByRole('dialog').innerText()).includes('1,200.00 USDT'));
    await page.getByRole('button',{name:'+1,000.00 USDT',exact:true}).click();
    await page.getByRole('button',{name:'Confirm Deposit'}).click();
    await page.waitForFunction(()=>!document.querySelector('.paper-deposit-modal'));
    assert.deepEqual(deposits,[{amount:1000,currency:'USDT',reset:false,confirm_reset:false}]);
    await page.getByRole('button',{name:'OK',exact:true}).click();
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.locator('.binance-header-controls').evaluate(e=>e.getBoundingClientRect().right<=innerWidth));
    assert.deepEqual(errors,[]);
    await page.close();
  }
  console.log('Passed full Binance page checks in both themes: aligned header, order-limit dialog, test mode, funding endpoint and mobile header.');

} finally {
  await browser?.close(); if(server?.listening) await new Promise(resolve=>server.close(resolve)); await rm(scratch,{recursive:true,force:true});
}
