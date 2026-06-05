// Mobile overflow check using playwright directly (bypass MCP version mismatch)
import { chromium } from 'playwright';

const URL = 'https://bit-man.net/dashboard/ai-bain';
const TOKEN = '3:1781415971:ee1876e8b522be5d719e3b91c268028a';

(async () => {
    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 3,
        isMobile: true,
        hasTouch: true,
        userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
    });

    const page = await context.newPage();
    // Inject token before navigating to bit-man.net (set on root first to set domain)
    await page.goto('https://bit-man.net/login', { waitUntil: 'domcontentloaded' });
    await page.evaluate((tok) => localStorage.setItem('auth_token', tok), TOKEN);

    // Navigate to target page
    await page.goto(URL, { waitUntil: 'networkidle' });
    await page.waitForTimeout(3000);

    // Check overflow
    const result = await page.evaluate(() => {
        const docW = document.documentElement.scrollWidth;
        const viewW = document.documentElement.clientWidth;
        const bodyW = document.body.scrollWidth;
        // Find elements wider than viewport
        const wider = [];
        document.querySelectorAll('*').forEach(el => {
            const r = el.getBoundingClientRect();
            if (r.width > viewW + 5) {
                wider.push({
                    tag: el.tagName,
                    classes: (el.className?.toString() || '').substring(0, 80),
                    width: Math.round(r.width),
                    left: Math.round(r.left),
                    right: Math.round(r.right),
                });
            }
        });
        return { viewW, docW, bodyW, overflowPx: docW - viewW, widerCount: wider.length, widerSample: wider.slice(0, 8) };
    });

    console.log('=== Mobile (390px) overflow check ===');
    console.log(JSON.stringify(result, null, 2));

    // Take screenshot
    await page.screenshot({ path: 'C:/bitman_marketfloww/scripts/mobile_aibain.png', fullPage: false });
    console.log('Screenshot: scripts/mobile_aibain.png');

    await browser.close();
})();
