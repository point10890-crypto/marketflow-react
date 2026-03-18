export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        status: 204,
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type, Accept',
          'Access-Control-Max-Age': '86400',
        },
      });
    }

    // API requests: proxy to Render backend with static fallback
    if (url.pathname.startsWith('/api/')) {
      const BACKEND = 'https://marketflow-api-fzez.onrender.com';

      // stock-analyzer는 POST + 실시간 → 긴 타임아웃, 폴백 없음
      const isInteractive = url.pathname.includes('stock-analyzer');
      const timeout = isInteractive ? 30000 : 60000;

      // 1) Try Render backend first (live data)
      try {
        const backendUrl = BACKEND + url.pathname + url.search;
        const fetchOptions = {
          method: request.method,
          headers: {
            'Accept': 'application/json',
          },
          signal: AbortSignal.timeout(timeout),
        };

        // Forward body and Content-Type for POST/PUT/PATCH
        if (['POST', 'PUT', 'PATCH'].includes(request.method)) {
          fetchOptions.body = await request.text();
          fetchOptions.headers['Content-Type'] = request.headers.get('Content-Type') || 'application/json';
        }

        const response = await fetch(backendUrl, fetchOptions);

        if (response.ok) {
          const newResponse = new Response(response.body, response);
          newResponse.headers.set('Access-Control-Allow-Origin', '*');
          newResponse.headers.set('X-Data-Source', 'render-live');
          if (request.method === 'GET') {
            newResponse.headers.set('Cache-Control', isInteractive ? 'no-cache' : 'public, max-age=60');
          }
          return newResponse;
        }
      } catch (e) {
        // Backend down or timeout — fall through to static
      }

      // 2) Fallback: static JSON snapshot (GET only, non-interactive)
      if (request.method === 'GET' && !isInteractive) {
        const dataPath = url.pathname.replace('/api/', '/api/data/') + '.json';
        const staticUrl = new URL(dataPath, url.origin);
        const staticResponse = await env.ASSETS.fetch(new Request(staticUrl));

        if (staticResponse.ok) {
          return new Response(staticResponse.body, {
            status: 200,
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*',
              'Cache-Control': 'public, max-age=300',
              'X-Data-Source': 'static-snapshot',
            },
          });
        }
      }

      // 3) Nothing available
      const errorMsg = isInteractive
        ? 'Backend is starting up. Please retry in 30 seconds.'
        : 'Service temporarily unavailable';
      return new Response(JSON.stringify({ error: errorMsg }), {
        status: 503,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      });
    }

    // Non-API: serve static assets
    return env.ASSETS.fetch(request);
  },
};
