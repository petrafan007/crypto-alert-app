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
    import React, {useState} from 'react'; import {createRoot} from 'react-dom/client';
    import Table from './src/components/SyntheticOrdersTable.jsx';
    import Config, {defaultLadderState} from './src/components/LadderOrderConfig.jsx';
    import TwoFactorModal from './src/components/TwoFactorModal.jsx';
    import PaperDepositModal from './src/components/PaperDepositModal.jsx';
    import AppDialogHost from './src/components/AppDialog.jsx';
    import {buildSyntheticReview,buildSyntheticPayload} from './src/utils/syntheticOrders.mjs';
    import './src/theme.css'; import './src/light-theme.css'; import './src/theme-variables.css';
    import './src/index.css'; import './src/pages/Trading.css'; import './src/pages/Trading.theme.css';
    const fees={takerRate:.0002, rates:{SELL:{taker:.0002},BUY:{taker:.0002}},bnb:{enabled:false},quantityStep:'.00001',source:'Verified test fixture',as_of:'2026-09-22T12:00:00Z'};
    const params=new URLSearchParams(location.search); document.body.className=params.get('theme')+'-mode'; document.documentElement.dataset.theme=params.get('theme');
    function App(){const [config,setConfig]=useState(defaultLadderState);const [side,setSide]=useState('SELL'); const [modal,setModal]=useState('');
      return <main style={{padding:16, background:'var(--card-bg)', color:'var(--text-primary)'}}>
        <h1>Synthetic orders</h1><Table defaultBroker={params.get('broker') || 'all'} />
        <section aria-label="Strategy editor"><button onClick={()=>setSide(side==='BUY'?'SELL':'BUY')}>Switch side</button>
          <Config fees={fees} side={side} currentPrice={100} totalQuantity="10" ladderConfig={config} onChange={setConfig}/>
          <button onClick={()=>{window.reviewPayload=buildSyntheticPayload(config)}}>Review payload</button>
          <button onClick={()=>setModal('2fa')}>Open confirmation</button>
          <button onClick={()=>setModal('paper')}>Open deposit</button>
          <button onClick={()=>setConfig({...config,upsideMode:'TRAILING',upsideActivationPrice:'200',upsideTrailValue:'2'})}>Set activation scenario</button>
          <TwoFactorModal isVisible={modal==='2fa'} onClose={()=>setModal('')} onVerify={()=>{}} orderDetails={{side,quantity:10,symbol:'BTCUSD',type:'LADDER',syntheticReview:buildSyntheticReview(config,{side,quantity:10,currentPrice:100,baseAsset:'BTC',fees})}}/>
          <PaperDepositModal visible={modal==='paper'} broker="Binance.US" balances={{USD:1200,USDT:2500}} currencies={['USD','USDT']} onClose={()=>setModal('')} onDeposit={(amount,currency)=>{window.deposit={amount,currency};setModal('')}} onReset={()=>{window.reset=true;setModal('')}}/>
        </section><AppDialogHost/></main>}
    createRoot(document.getElementById('root')).render(<App/>);` }, bundle: true, outfile: path.join(scratch, 'app.js'), loader: { '.woff2': 'dataurl', '.woff': 'dataurl', '.ttf': 'dataurl', '.svg': 'dataurl', '.png': 'dataurl' } });
  server = http.createServer(async (req, res) => {
    if (req.url.startsWith('/app.')) {
      const isCss = req.url.startsWith('/app.css'); res.setHeader('Content-Type', isCss ? 'text/css' : 'text/javascript');
      res.end(await readFile(path.join(scratch, isCss ? 'app.css' : 'app.js')));
    } else { res.setHeader('Content-Type', 'text/html'); res.end('<html><head><link rel="stylesheet" href="/app.css"></head><body><div id="root"></div><script src="/app.js"></script></body></html>'); }
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', args: ['--no-sandbox'] });
  for (const theme of ['dark','light']) {
    for (const broker of ['all','binance','webull']) {
      const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
      const runtimeErrors=[]; page.on('pageerror', error=>runtimeErrors.push(error.message));
      let nativeDialogs=0; page.on('dialog', async dialog=>{nativeDialogs++;await dialog.dismiss();});
      let failTrailing=false, loads=0, cancellationPayload=null;
      const base={id:1, broker:broker==='all'?'binance':broker, account_id:broker==='webull'?'ACCOUNT_A':null, symbol:'BTCUSD', side:'SELL', instrument_type:'CRYPTO', test_mode:false, created_at:'2026-09-22T12:00:00', status:'ACTIVE', total_quantity:1.23456789, filled_quantity:0, remaining_quantity:1.23456789, executions:[], upside_mode:'LADDER',downside_mode:'NONE',rungs:[{id:1,rung_number:1,rung_type:'TAKE_PROFIT',target_price:0.00000012,quantity:1.23456789,percentage_of_total:100,estimated_usd:.00001,status:'PENDING'}]};
      base.downside_mode='LADDER';
      base.rungs=Array.from({length:7},(_,i)=>({...base.rungs[0],id:i+1,rung_number:i+1,rung_type:i<4?'TAKE_PROFIT':'STOP_LOSS',percentage_of_total:24.940047961631,target_price:i===0?.00000012:90515.26,estimated_usd:282.4076112,error_message:'Example-long-error-'+ 'x'.repeat(90)}));
      await page.route('**/api/trading/**', async route=> {
        const isTrailing=route.request().url().includes('trailing-orders');loads++;
        if(route.request().method()==='POST'&&route.request().url().includes('/cancel')){
          cancellationPayload=route.request().postDataJSON();
          return route.fulfill({json:{success:true,ladder_order:{...base,status:'CANCELLED'}}});
        }
        if(isTrailing&&failTrailing) return route.fulfill({status:503,json:{success:false}});
        return route.fulfill({json:isTrailing ? {success:true,trailing_orders:[{...base,trail_type:'AMOUNT',trail_value:5,status:'FILLED',quantity:1.23456789,is_activated:true,highest_price:105,current_stop_price:100,rungs:undefined}]} : {success:true,ladder_orders:[base]}});
      });
      await page.goto(`http://127.0.0.1:${server.address().port}/?theme=${theme}&broker=${broker}`);
      await page.getByRole('button',{name:'Details',exact:true}).first().waitFor();
      assert.equal(await page.getByLabel('Status',{exact:true}).inputValue(),'ACTIVE');
      assert.equal(await page.getByRole('button',{name:'Details',exact:true}).count(),1);
      await page.getByLabel('Strategy',{exact:true}).selectOption('BRACKET');
      assert.equal(await page.getByRole('button',{name:'Details',exact:true}).count(),1);
      await page.getByRole('button',{name:'Details',exact:true}).click();
      assert.ok((await page.locator('.synthetic-detail').innerText()).includes('0.00 USD'));
      assert.ok((await page.locator('.synthetic-detail').innerText()).includes('(24.94%)'));
      for(const width of [2048,1440,768,390]){
        await page.setViewportSize({width,height:1000});
        const cards=await page.locator('.synthetic-step').evaluateAll(nodes=>nodes.map(el=>({width:el.clientWidth,scroll:el.scrollWidth,children:[...el.children].map(c=>({width:c.clientWidth,scroll:c.scrollWidth,wrap:getComputedStyle(c).whiteSpace}))})));
        assert.equal(cards.length,7);
        for(const card of cards){assert.ok(card.scroll<=card.width+1,JSON.stringify(card));for(const c of card.children){assert.equal(c.wrap,'normal');assert.ok(c.scroll<=c.width+1,JSON.stringify(c));}}
      }
      await page.setViewportSize({width:1440,height:1000});
      await page.getByLabel('Strategy',{exact:true}).selectOption('ALL');
      await page.getByLabel('Status',{exact:true}).selectOption('COMPLETED');
      assert.equal(await page.getByRole('button',{name:'Details',exact:true}).count(),1);
      assert.ok((await page.locator('.synthetic-orders').innerText()).includes('Trail 5.00 USD'));
      const styles=await page.locator('.synthetic-orders tbody strong').first().evaluate(el=>{
        let ancestor=el,bg='';while(ancestor){bg=getComputedStyle(ancestor).backgroundColor;if(!bg.includes('rgba')&&bg!=='transparent')break;ancestor=ancestor.parentElement;}
        return {text:getComputedStyle(el).color,bg,muted:getComputedStyle(el.parentElement.querySelector('small')).color};
      });
      assert.notEqual(styles.text,styles.bg);
      if(theme==='light') assert.notEqual(styles.text,'rgb(255, 255, 255)');
      const luminance = color => color.match(/[\d.]+/g).slice(0,3).map(v=>{const c=Number(v)/255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
      const contrast = (a,b) => (Math.max(luminance(a),luminance(b))+.05)/(Math.min(luminance(a),luminance(b))+.05);
      assert.ok(contrast(styles.text,styles.bg)>=4.5,JSON.stringify(styles));
      assert.ok(contrast(styles.muted,styles.bg)>=4.5,JSON.stringify(styles));
      await page.getByRole('button',{name:'Review payload'}).click();
      assert.equal((await page.evaluate(()=>window.reviewPayload)).downside_mode,'LADDER');
      assert.equal((await page.evaluate(()=>window.reviewPayload)).custom_rungs.length,3);
      await page.getByRole('button',{name:'Switch side'}).click();
      await page.getByRole('button',{name:'Review payload'}).click();
      assert.ok((await page.evaluate(()=>window.reviewPayload)).upside_target_price<100);
      assert.ok((await page.evaluate(()=>window.reviewPayload)).downside_target_price>100);
      await page.getByRole('checkbox').uncheck();
      await page.getByRole('button',{name:'Review payload'}).click();
      assert.equal((await page.evaluate(()=>window.reviewPayload)).downside_mode,'NONE');
      await page.getByRole('button',{name:'Switch side'}).click();
      await page.getByRole('checkbox').check();
      await page.getByRole('button',{name:'Open confirmation'}).click();
      let explanation=await page.locator('.order-explanation').innerText();
      assert.ok(explanation.includes('Upside strategy')); assert.ok(explanation.includes('Downside strategy'));
      assert.equal(await page.locator('.order-explanation .synthetic-review-step').count(),6);
      assert.ok(explanation.includes('Net proceeds')); assert.ok(explanation.includes('Cumulative gross'));
      await page.getByRole('button',{name:'Close',exact:true}).click();
      await page.getByRole('button',{name:'Set activation scenario'}).click();
      await page.getByRole('button',{name:'Open confirmation'}).click();
      explanation=await page.locator('.order-explanation').innerText();
      assert.ok(explanation.includes('200.00 USD')); assert.ok(explanation.includes('196.00 USD')); assert.ok(explanation.includes('1,959.61 USD'));
      await page.setViewportSize({width:390,height:844});
      const modalBox=await page.locator('.two-factor-modal').boundingBox();assert.ok(modalBox.width<=390);
      assert.ok(await page.locator('.two-factor-modal').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
      await page.getByRole('button',{name:'Close',exact:true}).click();
      await page.setViewportSize({width:1440,height:1000});
      await page.getByRole('button',{name:'Open deposit'}).click();
      assert.ok((await page.getByRole('dialog').innerText()).includes('1,200.00 USD'));
      await page.getByLabel('Paper currency').selectOption('USDT');
      assert.ok((await page.getByRole('dialog').innerText()).includes('2,500.00 USDT'));
      await page.getByRole('button',{name:'+5,000.00 USDT',exact:true}).click();
      await page.getByRole('button',{name:'Confirm Deposit'}).click();
      assert.deepEqual(await page.evaluate(()=>window.deposit),{amount:5000,currency:'USDT'});
      await page.getByRole('button',{name:'Open deposit'}).click();
      await page.getByLabel('Or Custom Deposit Amount (USD):').fill('12.345');
      assert.ok(await page.getByRole('button',{name:'Confirm Deposit'}).isDisabled());
      await page.getByLabel('Or Custom Deposit Amount (USD):').fill('123.45');
      await page.getByRole('button',{name:'Confirm Deposit'}).click();
      assert.deepEqual(await page.evaluate(()=>window.deposit),{amount:123.45,currency:'USD'});
      await page.getByRole('button',{name:'Open deposit'}).click();
      await page.getByRole('button',{name:'Reset Account'}).click();
      await page.locator('.app-dialog').getByRole('button',{name:'Keep Account'}).click();
      assert.equal(await page.evaluate(()=>window.reset),undefined);
      await page.getByRole('button',{name:'Reset Account'}).click();
      await page.locator('.app-dialog').getByRole('button',{name:'Reset Account'}).click();
      assert.equal(await page.evaluate(()=>window.reset),true);
      // A failed automatic refresh must retain the last known trailing row and surface an error.
      failTrailing=true; const before=loads; await page.getByRole('alert').waitFor({timeout:8000});
      assert.ok(loads>before); assert.equal(await page.getByRole('button',{name:'Details',exact:true}).count(),1);
      await page.setViewportSize({width:390,height:844});
      const dimensions = await page.locator('.synthetic-scroll').evaluate(el=>({scroll:el.scrollWidth,client:el.clientWidth,viewport:innerWidth,table:el.querySelector('table').offsetWidth}));
      assert.ok(dimensions.scroll>dimensions.client, JSON.stringify(dimensions));
      failTrailing=false;
      await page.getByLabel('Status',{exact:true}).selectOption('ACTIVE');
      await page.getByRole('button',{name:'Cancel',exact:true}).click();
      assert.ok((await page.locator('.two-factor-modal').innerText()).includes('filled quantities cannot be reversed'));
      await page.getByLabel('Two-factor authentication code').fill('123456');
      await page.locator('.two-factor-modal').getByRole('button',{name:'Confirm',exact:true}).click();
      assert.equal(cancellationPayload.two_factor_code,'123456');
      assert.equal(nativeDialogs,0);
      assert.deepEqual(runtimeErrors,[]);
      await page.close();
    }
  }
  console.log('Passed six broker/theme browser scenarios: filters, precision, editor payload, refresh errors, responsive tables.');
} finally {
  await browser?.close(); if(server?.listening) await new Promise(resolve=>server.close(resolve)); await rm(scratch,{recursive:true,force:true});
}
