import sanitizeHtml from 'sanitize-html';
import { decodeHTML } from 'entities';
import { publicUrl } from '../src/lib/publicUrls.mjs';

export const API = 'https://marketflow-api.bit-man.net/api/public/community';
const API_ORIGIN = 'https://marketflow-api.bit-man.net';
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export class PublicContentError extends Error {
    constructor(status) { super(`Public content unavailable (${status})`); this.status = status; }
}

export async function publicJson(path, fetcher = fetch) {
    // Only anonymous public endpoints, never forward client cookies or tokens.
    const response = await fetcher(API + path, { signal: AbortSignal.timeout(8000), headers: { Accept: 'application/json' } });
    if (!response.ok) throw new PublicContentError(response.status === 404 ? 404 : 503);
    return response.json();
}

export function safeBody(content) {
    return sanitizeHtml(content || '', {
        allowedTags: ['p','br','h1','h2','h3','h4','ul','ol','li','strong','em','b','i','blockquote','pre','code','hr','table','thead','tbody','tr','th','td','a','img','section','div','span'],
        allowedAttributes: { a: ['href','title','rel'], img: ['src','alt','width','height'], th: ['colspan','rowspan'], td: ['colspan','rowspan'] },
        allowedSchemes: ['http','https','mailto'],
        allowedSchemesByTag: { img: ['https'] },
        allowProtocolRelative: false,
        transformTags: {
            a: (tagName, attrs) => ({ tagName, attribs: { ...attrs, rel: 'nofollow ugc noopener' } }),
            img: (tagName, attrs) => ({ tagName, attribs: { ...attrs, src: attrs.src?.startsWith('/api/community/uploads/') ? API_ORIGIN + attrs.src : attrs.src } }),
        },
    });
}

const NAV = '<nav><a href="/">홈</a> · <a href="/community/">커뮤니티</a> · <a href="/guide/">가이드</a> · <a href="/contact/">문의 · 정정</a></nav>';
const list = posts => `<ul>${posts.map(p => `<li><a href="/community/post/${Number(p.id)}/">${esc(p.title)}</a> · ${esc(p.created_at?.slice(0,10))}</li>`).join('')}</ul>`;

export async function communityModel(pathname, fetcher = fetch) {
    const path = pathname.replace(/\/+$/, '');
    const canonical = publicUrl(path);
    const match = path.match(/^\/community\/post\/([1-9]\d*)$/);
    if (match) {
        const { post } = await publicJson(`/posts/${match[1]}`, fetcher);
        if (!post || String(post.id) !== match[1] || !post.board) throw new PublicContentError(503);
        const content = safeBody(post.content);
        const description = decodeHTML(sanitizeHtml(content, { allowedTags: [], allowedAttributes: {} })).replace(/\s+/g,' ').trim().slice(0,160);
        return {
            canonical, title: `${post.title} | MarketFlow 커뮤니티`, description, type: 'article',
            body: `${NAV}<article><h1>${esc(post.title)}</h1><p>${esc(post.author_name)} · ${esc(post.created_at)}</p>${content}</article>`,
            jsonLd: { '@context':'https://schema.org', '@type':'Article', headline:post.title, mainEntityOfPage:canonical, datePublished:post.created_at, author:{'@type':'Person', name:post.author_name}, inLanguage:'ko' },
        };
    }
    const boardMatch = path.match(/^\/community\/([a-z0-9-]+)$/);
    if (path !== '/community' && !boardMatch) throw new PublicContentError(404);
    const { boards } = await publicJson('/boards', fetcher);
    if (!Array.isArray(boards)) throw new PublicContentError(503);
    const selected = boardMatch ? boards.filter(b => b.slug === boardMatch[1]) : boards;
    if (boardMatch && !selected.length) throw new PublicContentError(404);
    const sections = await Promise.all(selected.map(async b => {
        const page = await publicJson(`/boards/${encodeURIComponent(b.slug)}/posts?page=1`, fetcher);
        if (!Array.isArray(page.posts) || !Array.isArray(page.notices)) throw new PublicContentError(503);
        const posts = [...new Map([...page.notices, ...page.posts].map(p => [p.id, p])).values()];
        return `<section><h2><a href="/community/${esc(b.slug)}/">${esc(b.name)}</a></h2>${list(posts)}</section>`;
    }));
    const title = boardMatch ? `${selected[0].name} | MarketFlow 커뮤니티` : '커뮤니티 — AI 시장 분석과 이야기 | MarketFlow';
    return { canonical, title, description:'시장 분석 기록과 공지, 회원들의 이야기를 읽는 공개 커뮤니티입니다.', type:'website', body:`${NAV}<h1>${esc(title)}</h1>${sections.join('')}`, jsonLd:{'@context':'https://schema.org','@type':'CollectionPage',url:canonical,name:title} };
}

export async function communitySitemapUrls(fetcher = fetch) {
    const { boards } = await publicJson('/boards', fetcher);
    if (!Array.isArray(boards) || boards.length > 15) throw new PublicContentError(503);
    const urls = new Set([publicUrl('/community')]);
    for (const board of boards) {
        urls.add(publicUrl(`/community/${board.slug}`));
    }
    let cursor = 0;
    for (let request = 0; request < 38; request++) {
        const data = await publicJson(`/sitemap?after_id=${cursor}&per_page=500`, fetcher);
        if (!Array.isArray(data.posts)) throw new PublicContentError(503);
        for (const post of data.posts) {
            if (!Number.isSafeInteger(post.id) || post.id <= cursor) throw new PublicContentError(503);
            urls.add(publicUrl(`/community/post/${post.id}`));
        }
        if (data.next_after_id === null) return [...urls];
        if (!Number.isSafeInteger(data.next_after_id) || data.next_after_id <= cursor) throw new PublicContentError(503);
        cursor = data.next_after_id;
    }
    throw new PublicContentError(503); // Never publish a silently truncated sitemap.
}

export function unavailable(status) {
    return new Response(`<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="robots" content="noindex"><title>${status === 404 ? '글을 찾을 수 없습니다' : '일시적으로 불러올 수 없습니다'} | MarketFlow</title><body>${NAV}<h1>${status === 404 ? '글을 찾을 수 없습니다' : '잠시 후 다시 시도해 주세요'}</h1></body></html>`, {
        status, headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','X-Robots-Tag':'noindex', ...(status === 503 ? {'Retry-After':'60'} : {})},
    });
}

export async function serveCommunity(context) {
    if (!['GET','HEAD'].includes(context.request.method)) return new Response('Method not allowed', {status:405,headers:{Allow:'GET, HEAD'}});
    const url = new URL(context.request.url);
    if (!url.pathname.endsWith('/')) { url.pathname += '/'; return Response.redirect(url.href, 308); }
    try {
        const model = await communityModel(url.pathname);
        // Use the static homepage only as the application shell. Replace ALL its content signals.
        const shell = await context.env.ASSETS.fetch(new Request(new URL('/', url)));
        if (!shell.ok) throw new PublicContentError(503);
        const head = `<title>${esc(model.title)}</title><meta name="description" content="${esc(model.description)}"><link rel="canonical" href="${model.canonical}"><meta property="og:title" content="${esc(model.title)}"><meta property="og:description" content="${esc(model.description)}"><meta property="og:url" content="${model.canonical}"><meta property="og:type" content="${model.type}"><meta name="twitter:title" content="${esc(model.title)}"><meta name="twitter:description" content="${esc(model.description)}"><script type="application/ld+json" data-seo="jsonld">${JSON.stringify(model.jsonLd).replace(/</g,'\\u003c')}</script><style>#seo-content img{max-width:100%;height:auto}#seo-content pre{white-space:pre-wrap}#seo-content table{display:block;overflow-x:auto}</style>`;
        const rewriter = new HTMLRewriter()
            .on('title, link[rel="canonical"], meta[name="description"], meta[name="robots"], meta[property="og:title"], meta[property="og:description"], meta[property="og:url"], meta[property="og:type"], meta[name="twitter:title"], meta[name="twitter:description"], script[type="application/ld+json"]', { element(e) { e.remove(); } })
            .on('head', { element(e) { e.append(head, {html:true}); } })
            .on('#seo-content', { element(e) { e.setInnerContent(model.body, {html:true}); } });
        const response = rewriter.transform(shell);
        const headers = new Headers(response.headers);
        for (const key of ['etag','last-modified','content-length']) headers.delete(key);
        headers.set('Cache-Control','no-store');
        headers.set('Link', `<${model.canonical}>; rel="canonical"`);
        return new Response(context.request.method === 'HEAD' ? null : response.body, {status:200,headers});
    } catch (error) { return unavailable(error instanceof PublicContentError ? error.status : 503); }
}
