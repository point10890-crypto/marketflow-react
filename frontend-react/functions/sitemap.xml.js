import { communitySitemapUrls, esc } from '../edge/community.mjs';

export async function onRequest({request, env}) {
    if (!['GET','HEAD'].includes(request.method)) return new Response('Method not allowed',{status:405});
    try {
        const staticMap = await env.ASSETS.fetch(new Request(new URL('/sitemap.xml',request.url)));
        if (!staticMap.ok) throw new Error('Missing static sitemap');
        const xml = await staticMap.text();
        const known = new Set([...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map(m => m[1]));
        const urls = await communitySitemapUrls();
        const added = urls.filter(url => !known.has(url)).map(url => `<url><loc>${esc(url)}</loc></url>`).join('\n');
        return new Response(request.method === 'HEAD' ? null : xml.replace('</urlset>',added+'\n</urlset>'), {headers:{'Content-Type':'application/xml; charset=utf-8','Cache-Control':'public, max-age=300'}});
    } catch { return new Response('Sitemap temporarily unavailable',{status:503,headers:{'Cache-Control':'no-store','Retry-After':'60'}}); }
}
