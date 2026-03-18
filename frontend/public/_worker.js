export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // API requests: proxy to Render backend with fallback to static JSON
    if (url.pathname.startsWith('/api/')) {
      const BACKEND = 'https://marketflow-api-fzez.onrender.com';

      try {
        const backendUrl = BACKEND + url.pathname + url.search;
        const response = await fetch(backendUrl, {
          method: request.method,
          headers: { 'Accept': 'application/json' },
          signal: AbortSignal.timeout(8000), // 8s timeout
        });

        if (response.ok) {
          // Clone and add CORS headers
          const newResponse = new Response(response.body, response);
          newResponse.headers.set('Access-Control-Allow-Origin', '*');
          newResponse.headers.set('Cache-Control', 'public, max-age=60');
          return newResponse;
        }
      } catch (e) {
        // Backend down or timeout — fall through to static
      }

      // Fallback: try static JSON file
      // /api/us/market-briefing → /api/data/us/market-briefing.json
      const dataPath = url.pathname.replace('/api/', '/api/data/') + '.json';
      const staticUrl = new URL(dataPath, url.origin);
      const staticResponse = await env.ASSETS.fetch(new Request(staticUrl));

      if (staticResponse.ok) {
        const newResponse = new Response(staticResponse.body, {
          status: 200,
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'public, max-age=300',
            'X-Data-Source': 'static-snapshot',
          },
        });
        return newResponse;
      }

      // Nothing available
      return new Response(JSON.stringify({ error: 'Service temporarily unavailable' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Non-API: serve static assets
    return env.ASSETS.fetch(request);
  },
};
