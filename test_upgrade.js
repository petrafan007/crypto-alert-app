const puppeteer = require('puppeteer');

(async () => {
  console.log("Launching browser...");
  const browser = await puppeteer.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage();
  
  page.on('console', msg => console.log('BROWSER:', msg.text()));
  page.on('requestfailed', request => {
    console.log('REQUEST FAILED:', request.url(), request.failure().errorText);
  });
  page.on('response', response => {
    if (response.status() >= 400) {
      console.log('FAILED RESPONSE:', response.url(), response.status());
    }
  });
  page.on('dialog', async dialog => {
    console.log('Dialog detected:', dialog.message());
    await dialog.accept();
  });

  try {
    console.log("Navigating to login...");
    await page.goto('http://127.0.0.1:5016/login', { waitUntil: 'networkidle0' });
    
    console.log("Entering credentials...");
    await page.type('input[type="text"]', 'jcavallarojr');
    await page.type('input[type="password"]', 'Virg1nia!');
    await page.click('button[type="submit"]');
    
    console.log("Waiting for navigation to dashboard...");
    await page.waitForNavigation({ waitUntil: 'networkidle0' });
    
    console.log("Navigating to settings...");
    await page.goto('http://127.0.0.1:5016/settings', { waitUntil: 'networkidle0' });
    
    console.log("Looking for upgrade button...");
    // The button text is "Upgrade App"
    const upgradeButton = await page.evaluateHandle(() => {
      const buttons = Array.from(document.querySelectorAll('button'));
      return buttons.find(b => b.textContent.includes('Upgrade App'));
    });
    
    if (upgradeButton) {
      console.log("Clicking upgrade button...");
      await upgradeButton.click();
      
      console.log("Waiting for modal to appear...");
      await page.waitForFunction(() => {
        const texts = Array.from(document.querySelectorAll('*')).map(el => el.textContent);
        return texts.some(t => t && t.includes('Confirm Application Upgrade'));
      });

      console.log("Looking for Confirm Upgrade button...");
      await page.waitForFunction(() => {
        const buttons = Array.from(document.querySelectorAll('button'));
        const btn = buttons.find(b => b.textContent.includes('Confirm Upgrade'));
        return btn && !btn.disabled;
      });

      const confirmButton = await page.evaluateHandle(() => {
        const buttons = Array.from(document.querySelectorAll('button'));
        return buttons.find(b => b.textContent.includes('Confirm Upgrade') && !b.disabled);
      });

      if (confirmButton && confirmButton.asElement()) {
        console.log("Clicking Confirm Upgrade button...");
        await confirmButton.click();
        
        console.log("Waiting for page reload (timeout 120s)...");
        await page.waitForNavigation({ timeout: 120000, waitUntil: 'networkidle0' });
      
      console.log("Page reloaded. Verifying content...");
      const bodyText = await page.evaluate(() => document.body.innerText);
      if (bodyText.includes("Crypto Alert App")) {
        console.log("SUCCESS: Upgrade completed, page refreshed, and branding is correct.");
      } else {
        console.log("ERROR: Branding not found. Page might not have refreshed properly.");
      }
      } else {
        console.log("ERROR: Confirm Upgrade button not found on Settings page modal.");
      }
    } else {
      console.log("ERROR: Upgrade button not found on Settings page.");
    }
  } catch (err) {
    console.error("Test failed:", err);
  } finally {
    await browser.close();
  }
})();
