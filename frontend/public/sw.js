const CACHE_NAME = 'marketflow-v3';
const API_CACHE = 'marketflow-api-v1';

const STATIC_ASSETS = [
  '/',
  '/dashboard',
  '/dashboard/kr',
  '/dashboard/us',
  '/dashboard/crypto',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png',
];

// API endpoints to cache for offline
const CACHEABLE_API = [
  '/api/us/market-briefing',
  '/api/kr/market-gate',
  '/api/crypto/dominance',
  '/api/kr/vcp-enhanced',
  '/api/us/vcp-enhanced',
  '/api/crypto/vcp-enhanced',
  '/api/kr/jongga-v2/latest',
  '/api/us/portfolio',
  '/api/us/decision-signal',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== CACHE_NAME && k !== API_CACHE)
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method !== 'GET') return;

  // API requests: network-first, cache fallback
  if (url.pathname.startsWith('/api/') && CACHEABLE_API.some(ep => url.pathname.startsWith(ep))) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(API_CACHE).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => caches.match(request).then((cached) => cached || new Response('{"error":"offline"}', {
          status: 503,
          headers: { 'Content-Type': 'application/json' },
        })))
    );
    return;
  }

  // Skip non-cacheable API
  if (url.pathname.startsWith('/api/')) return;

  // Static assets: stale-while-revalidate
  event.respondWith(
    caches.match(request).then((cached) => {
      const fetchPromise = fetch(request)
        .then((response) => {
          if (response.ok && (url.pathname.match(/\.(js|css|png|jpg|svg|woff2?)$/) || STATIC_ASSETS.includes(url.pathname))) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => cached || (request.mode === 'navigate' ? caches.match('/') : new Response('Offline', { status: 503 })));

      return cached || fetchPromise;
    })
  );
});
