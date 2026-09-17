import { test } from 'node:test';
import assert from 'node:assert/strict';
import { API, communityModel, communitySitemapUrls, publicJson, safeBody, serveCommunity } from './community.mjs';

const post = {id:3,title:'공개 글 <안내>',content:'<p>실제 본문</p>',created_at:'2026-09-15T09:00:00',author_name:'운영자',board:{slug:'notice',name:'공지'}};
const fixture = routes => async (url, options) => {
    assert.equal(options.headers.Authorization, undefined);
    assert.equal(options.headers.Cookie, undefined);
    assert.ok(String(url).startsWith(API+'/'));
    const data = routes[String(url).slice(API.length)];
    return new Response(JSON.stringify(data ?? {error:'not found'}), {status:data ? 200 : 404});
};

test('article initial HTML model has its own URL, body and safe title', async () => {
    const model = await communityModel('/community/post/3/',fixture({'/posts/3':{post}}));
    assert.equal(model.canonical,'https://bit-man.net/community/post/3/');
    assert.equal(model.jsonLd.mainEntityOfPage,model.canonical);
    assert.ok(model.body.includes('실제 본문'));
    assert.ok(model.body.includes('공개 글 &lt;안내&gt;'));
});

test('public API denial remains not found; no member API fallback', async () => {
    await assert.rejects(communityModel('/community/post/3/',fixture({})),e=>e.status===404);
});

test('description is decoded text and will be HTML-escaped exactly once', async () => {
    const model=await communityModel('/community/post/3/',fixture({'/posts/3':{post:{...post,content:'<p>AT&amp;T &lt; 3 &gt; 2</p>'}}}));
    assert.equal(model.description,'AT&T < 3 > 2');
});

test('unknown or private board is excluded', async () => {
    await assert.rejects(communityModel('/community/pro-lounge/',fixture({'/boards':{boards:[{slug:'notice',name:'공지'}]}})),e=>e.status===404);
});

test('upstream outage is retryable rather than missing or homepage HTML', async () => {
    await assert.rejects(publicJson('/posts/3',async()=>new Response('',{status:500})),e=>e.status===503);
});

test('unsafe article markup is removed while content and API images survive', () => {
    const body=safeBody('<script>alert(1)</script><iframe src="https://evil.test"></iframe><img src="/api/community/uploads/a.png" onerror="alert(1)"><a href="javascript:alert(1)">출처</a><p>본문</p>');
    assert.ok(!/script|iframe|onerror|javascript:/i.test(body));
    assert.ok(body.includes('https://marketflow-api.bit-man.net/api/community/uploads/a.png'));
    assert.ok(body.includes('<p>본문</p>'));
});

test('board HTML contains crawlable article links without duplicate pinned entries', async () => {
    const model=await communityModel('/community/notice/',fixture({
        '/boards':{boards:[{slug:'notice',name:'공지'}]},
        '/boards/notice/posts?page=1':{posts:[post],notices:[post]},
    }));
    assert.equal((model.body.match(/href="\/community\/post\/3\/"/g)||[]).length,1);
    assert.equal(model.canonical,'https://bit-man.net/community/notice/');
});

test('sitemap includes pinned posts, all pages and final canonical addresses', async () => {
    const urls=await communitySitemapUrls(fixture({
        '/boards':{boards:[{slug:'notice',name:'공지'}]},
        '/sitemap?after_id=0&per_page=500':{posts:[{id:3},{id:7}],next_after_id:7},
        '/sitemap?after_id=7&per_page=500':{posts:[{id:8}],next_after_id:null},
    }));
    assert.deepEqual(new Set(urls),new Set(['/community/','/community/notice/','/community/post/3/','/community/post/7/','/community/post/8/'].map(p=>'https://bit-man.net'+p)));
});

test('sitemap fails instead of silently publishing partial pagination', async () => {
    await assert.rejects(communitySitemapUrls(fixture({
        '/boards':{boards:[{slug:'notice'}]},
        '/sitemap?after_id=0&per_page=500':{posts:[{id:3}],next_after_id:3},
    })));
});

test('redirect canonicalizes slash before accessing any backend', async () => {
    const response=await serveCommunity({request:new Request('https://bit-man.net/community/post/3?utm_source=test')});
    assert.equal(response.status,308);
    assert.equal(response.headers.get('Location'),'https://bit-man.net/community/post/3/?utm_source=test');
});

test('write requests never reach public content renderer', async () => {
    const response=await serveCommunity({request:new Request('https://bit-man.net/community/post/3/',{method:'POST'})});
    assert.equal(response.status,405);
});
