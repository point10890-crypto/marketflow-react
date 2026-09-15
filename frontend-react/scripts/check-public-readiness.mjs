// Offline checks against the actual build; no ad requests or external APIs.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';
import { GUIDES, renderGuideNotes } from '../src/data/guides.mjs';
import { PUBLISHING_PAGES, AD_PRIVACY_HTML, DATA_SHARING_HTML } from '../src/data/publishing.mjs';
import { EXAMPLE_RESULTS, EXAMPLE_HIT_RATE, EXAMPLE_MEAN_NET } from '../src/data/verificationExample.mjs';

const dist = fileURLToPath(new URL('../dist/', import.meta.url));
const sitemap = readFileSync(`${dist}/sitemap.xml`, 'utf8');
const routes = ['/', '/about', '/privacy', '/terms', '/pricing', '/community', '/guide',
    ...GUIDES.map(g => `/guide/${g.slug}`), ...PUBLISHING_PAGES.map(p => p.path)];
const normalize = html => new JSDOM(html).window.document.body.textContent.replace(/\s+/g, ' ').trim();
for (const route of routes) {
    const html = readFileSync(`${dist}/${route === '/' ? '' : route.slice(1) + '/'}index.html`, 'utf8');
    const doc = new JSDOM(html).window.document;
    assert.equal(doc.querySelectorAll('h1').length, 1, `${route}: duplicate/missing main heading`);
    assert.equal(doc.querySelector('link[rel="canonical"]')?.href, `https://bit-man.net${route}`);
    assert.equal(doc.querySelector('meta[name="google-adsense-account"]')?.content, 'ca-pub-4268071335236139');
    assert.equal(doc.querySelector('script[src*="adsbygoogle"], .adsbygoogle'), null);
    assert.ok(sitemap.includes(`<loc>https://bit-man.net${route}</loc>`), `${route}: missing sitemap URL`);
    assert.ok(doc.querySelector('#seo-content a[href="/contact"]'));
    for (const el of doc.querySelectorAll('script[type="application/ld+json"]')) JSON.parse(el.textContent);
    const guide = GUIDES.find(g => route === `/guide/${g.slug}`);
    if (guide) {
        assert.ok(normalize(html).includes(normalize(guide.html)), `${route}: guide body mismatch`);
        assert.ok(normalize(html).includes(normalize(renderGuideNotes(guide))), `${route}: source notes mismatch`);
        assert.equal(doc.querySelector('meta[property="og:type"]')?.content, 'article');
    }
    const page = PUBLISHING_PAGES.find(p => p.path === route);
    if (page) assert.ok(normalize(html).includes(normalize(page.html)), `${route}: publishing page mismatch`);
    if (route === '/privacy') {
        for (const fragment of [AD_PRIVACY_HTML, DATA_SHARING_HTML]) assert.ok(normalize(html).includes(normalize(fragment)));
    }
}
assert.deepEqual(EXAMPLE_RESULTS.map(row => Number(row.netPct.toFixed(1))), [7.5, -4.5, 1.5, -0.5]);
assert.equal(EXAMPLE_HIT_RATE, 50);
assert.ok(Math.abs(EXAMPLE_MEAN_NET - 1) < 1e-10);
console.log(`Public readiness: ${routes.length} static pages, article parity, ownership, no ads, and example calculations passed.`);
