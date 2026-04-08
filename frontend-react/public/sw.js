// MarketFlow kill-switch service worker (v3.1.0+)
// 과거에 배포된 Workbox SW가 페이지/API 를 stale 캐시하는 문제를 영구히
// 제거하기 위한 빈 SW. 기존 유저 브라우저가 업데이트 체크 시 이 파일로
// 교체되면, activate 단계에서 모든 캐시를 삭제하고 본인 등록을 해제한 뒤
// 열려 있는 탭을 한 번 강제 새로고침해서 깨끗한 상태로 진입시킨다.

self.addEventListener('install', (event) => {
  // 대기열 건너뛰고 즉시 activate
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    try {
      // 1) 모든 캐시 스토리지 제거 (pages-cache / api-cache / workbox-precache 등)
      if (self.caches && caches.keys) {
        const keys = await caches.keys();
        await Promise.all(keys.map((k) => caches.delete(k)));
      }
    } catch (e) { /* ignore */ }

    try {
      // 2) 열려 있는 모든 탭을 통제 (claim) — 다음 navigate 시 네트워크로 빠짐
      await self.clients.claim();
    } catch (e) { /* ignore */ }

    try {
      // 3) 본인 등록 해제
      await self.registration.unregister();
    } catch (e) { /* ignore */ }

    try {
      // 4) 통제 중이던 모든 탭 강제 새로고침 — 최신 번들을 바로 로드
      const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const client of clients) {
        try { client.navigate(client.url); } catch (e) { /* ignore */ }
      }
    } catch (e) { /* ignore */ }
  })());
});

// fetch 핸들러는 구현하지 않음 — 브라우저가 네트워크로 직행
