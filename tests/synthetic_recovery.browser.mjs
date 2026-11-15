// Browser regression with mocked HTTP only; never loads account data or submits live orders.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
const root = path.resolve(import.meta.dirname, '..');
const require = createRequire(path.join(root, 'frontend/package.json'));
const { build } = require('esbuild');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const scratch = await mkdtemp(path.join(os.tmpdir(), 'synthetic-recovery-browser-'));
let server, browser, route_url_of_last_recover='';
try {
  await build({ stdin: { resolveDir: path.join(root, 'frontend'), loader: 'jsx', contents: `
    import React from 'react'; import {createRoot} from 'react-dom/client';
    import Table from './src/components/SyntheticOrdersTable.jsx';
    import Host from './src/components/SyntheticRecoveryHost.jsx';
    import Toasts from './src/components/ToastNotifications.jsx';
    import './src/theme.css'; import './src/theme-variables.css'; import './src/light-theme.css';
    const theme = new URLSearchParams(location.search).get('theme') || 'dark'; document.body.className=theme+'-mode';
    createRoot(document.getElementById('root')).render(<><h1>Order History</h1><Table historyMode defaultBroker="webull" showBrokerFilter={false}/><Host userId={1}/><Toasts isLightMode={theme==='light'}/></>);
  ` }, bundle: true, outfile: path.join(scratch, 'app.js') });
  server = http.createServer(async (req,res) => {
    if (req.url.startsWith('/app.')) {
      const css = req.url.startsWith('/app.css'); res.setHeader('Content-Type', css ? 'text/css' : 'text/javascript');
      res.end(await readFile(path.join(scratch, css ? 'app.css' : 'app.js')));
    } else res.end('<html><head><link rel="stylesheet" href="/app.css"></head><body><div id="root"></div><script src="/app.js"></script></body></html>');
  });
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  browser = await chromium.launch({ headless:true, executablePath:process.env.CHROMIUM_PATH||undefined, args:['--no-sandbox'] });
  for (const theme of ['dark','light']) {
    const page = await browser.newPage({ viewport:{width:theme==='dark'?1400:390,height:900} });
    const errors=[]; page.on('pageerror', e=>errors.push(e.message));
    let payload, reject=false, holdLadders=false, heldLadders=[], trailing=[];
    let order={id:21,broker:'webull',account_id:'IRA_ACCOUNT',symbol:'NVDA',instrument_type:'EQUITY',side:'BUY',test_mode:false,
      status:'FAILED',status_label:'Partially filled — remainder cancelled',recovery_available:true,filled_quantity:4,remaining_quantity:6,
      total_quantity:10,pending_quantity:0,created_at:'2026-11-14T20:00:00',upside_mode:'SINGLE',upside_target_price:165,
      downside_mode:'SINGLE',downside_target_price:160,trading_session:'ALL',last_price:162,monitoring_error:'Limit order timed out; final cancellation confirmed.',executions:[]};
    await page.route('**/api/**', route=> {
      const url=route.request().url();
      if(url.includes('/recover')) {
        payload=route.request().postDataJSON(); route_url_of_last_recover=url;
        if(reject) return route.fulfill({status:403,json:{success:false,error:'Enter a valid authenticator code.'}});
        order={...order,recovery_available:false,recovery_action:payload.action,replacement_id:22};
        return route.fulfill({json:{success:true,replacement_id:22}});
      }
      if(url.includes('ladder-orders')) {
        if(holdLadders) { heldLadders.push(route); return; }
        return route.fulfill({json:{success:true,ladder_orders:[order]}});
      }
      if(url.includes('trailing-orders')) return route.fulfill({json:{success:true,trailing_orders:trailing}});
      if(url.includes('/notifications')) return route.fulfill({json:[]});
      return route.fulfill({json:{browser_notifications_enabled:true}});
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/?theme=${theme}`);
    await page.getByRole('button',{name:'Partially filled — remainder cancelled',exact:true}).click();
    const dialog=page.getByRole('dialog'); await dialog.waitFor();
    assert.match(await dialog.innerText(), /Unfilled remainder: 6/);
    await dialog.getByRole('button',{name:'B. Use Regular Hours'}).click();
    await dialog.locator('input[name="totp"]').fill('123456');
    reject=true;
    await dialog.getByRole('button',{name:'Confirm and submit',exact:true}).click();
    await dialog.getByRole('alert').filter({hasText:'valid authenticator'}).waitFor();
    assert.equal(payload.action,'REGULAR');
    await dialog.getByRole('button',{name:'Back',exact:true}).click();
    await dialog.getByRole('button',{name:'A. Replace / Retry'}).click();
    await dialog.getByLabel('Order type',{exact:true}).selectOption('OCO');
    await dialog.getByLabel('Trading session',{exact:true}).selectOption('ALL');
    assert.equal(await dialog.locator('fieldset').count(),2);
    reject=false;
    await dialog.getByRole('button',{name:'Confirm and submit',exact:true}).click();
    await dialog.waitFor({state:'hidden'});
    assert.equal(payload.action,'REPLACE'); assert.equal(payload.strategy_type,'OCO'); assert.equal(payload.trading_session,'ALL');
    assert.equal(payload.legs[0].price,160); assert.equal(payload.legs[1].stop_price,165);
    // A new failure should raise a clickable warning even when only history is open.
    order={...order,id:23,recovery_available:true,recovery_action:null,status_label:'Failed — no shares filled',filled_quantity:0,remaining_quantity:10};
    const toast=page.locator('.toast-card.type-warning');
    await toast.waitFor({timeout:12000}); await toast.click();
    await dialog.waitFor();
    assert.match(await dialog.innerText(),/A\. Replace \/ Retry/);
    await dialog.getByRole('button',{name:'C. Keep Cancelled'}).click();
    await dialog.waitFor({state:'hidden'}); assert.equal(payload.action,'KEEP_CANCELLED');
    // Open one strategy, then another before the first lookup answers. The
    // late first answer must not replace the strategy now on screen.
    trailing=[{id:41,broker:'webull',account_id:'IRA_ACCOUNT',symbol:'TSLA',instrument_type:'EQUITY',side:'SELL',test_mode:false,status:'FAILED',
      status_label:'Failed — no shares filled',recovery_available:true,filled_quantity:0,remaining_quantity:3,trail_value:2,trading_session:'CORE',monitoring_error:'Rejected.'}];
    holdLadders=true;
    await page.evaluate(first=>window.dispatchEvent(new CustomEvent('app:synthetic-recovery',{detail:first})),{...order,parentKind:'LADDER'});
    for(let tries=0;!heldLadders.length&&tries<100;tries++) await new Promise(resolve=>setTimeout(resolve,10));
    assert.ok(heldLadders.length,'held the first strategy lookup');
    await page.evaluate(second=>window.dispatchEvent(new CustomEvent('app:synthetic-recovery',{detail:second})),{...trailing[0],parentKind:'TRAILING'});
    await dialog.getByText('Unfilled remainder: 3').waitFor();
    holdLadders=false;
    for(const route of heldLadders) await route.fulfill({json:{success:true,ladder_orders:[order]}}).catch(()=>{});
    await new Promise(resolve=>setTimeout(resolve,300));
    assert.match(await dialog.innerText(),/TSLA · SELL/);
    assert.doesNotMatch(await dialog.innerText(),/NVDA/);
    await dialog.getByRole('button',{name:'C. Keep Cancelled'}).click();
    await dialog.waitFor({state:'hidden'});
    assert.match(route_url_of_last_recover,/synthetic-orders\/TRAILING\/41\/recover/);
    assert.deepEqual(errors,[]);
    await page.close();
  }
  console.log('Synthetic recovery browser checks passed: history, partial fills, all three choices, 2FA failure, clickable toast, light/dark and mobile.');
} finally {
  await browser?.close(); if(server) await new Promise(resolve=>server.close(resolve)); await rm(scratch,{recursive:true,force:true});
}
