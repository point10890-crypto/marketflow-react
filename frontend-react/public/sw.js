// MarketFlow PWA-installable service worker (v4.2.0)
//
// 목적: PWA 설치 가능하게 만드는 최소한의 SW.
// Chrome / Edge / Samsung Internet 의 PWA install prompt 는 fetch 이벤트
// 핸들러가 등록된 SW + valid manifest 가 있어야 발동된다.
//
// 캐시 정책: 일부러 캐싱하지 않음.
//   - 과거 v3.1.0 이전 Workbox SW 가 stale 캐시로 "앱이 안 뜸" 불만 다발.
//   - 현재는 모든 fetch 를 네트워크로 직행 (pass-through).
//   - 캐시가 필요하면 향후 신중하게 cache-first 가 아닌 stale-while-revalidate
//     로 navigation 만 적용하는 방향으로 검토.

const SW_VERSION = 'v4.2.0';

self.addEventListener('install', (event) => {
    // 새 SW 즉시 활성화 — 대기 없이
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil((async () => {
        try {
            // 잔존 캐시 모두 제거 (이전 Workbox SW 흔적 정리)
            if (self.caches && caches.keys) {
                const keys = await caches.keys();
                await Promise.all(keys.map((k) => caches.delete(k)));
            }
        } catch (e) { /* ignore */ }
        // 열려 있는 탭 통제권 획득 (다음 fetch 부터 이 SW 가 처리)
        try { await self.clients.claim(); } catch (e) { /* ignore */ }
    })());
});

// PWA installable 요건: fetch 이벤트 핸들러 존재.
// 핸들러는 빈 함수면 안 되고 (Chrome 일부 버전에서 무시), respondWith 호출이
// 있어야 등록된 것으로 인정. 단순 pass-through 로 네트워크 직행.
self.addEventListener('fetch', (event) => {
    // POST / PUT 등 mutation 은 SW 가 건드리지 않음
    if (event.request.method !== 'GET') return;
    // navigation 요청만 네트워크-우선 (오프라인 시 기본 응답)
    if (event.request.mode === 'navigate') {
        event.respondWith(
            fetch(event.request).catch(() => new Response(
                '<!doctype html><meta charset=utf-8><title>오프라인</title>' +
                '<style>body{background:#09090b;color:#fff;font-family:sans-serif;' +
                'display:grid;place-items:center;min-height:100vh;margin:0}</style>' +
                '<div><h1>MarketFlow</h1><p>오프라인입니다. 네트워크 확인 후 다시 시도하세요.</p></div>',
                { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
            ))
        );
        return;
    }
    // 그 외 정적 자산 / API — 네트워크 직행
});

self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});
