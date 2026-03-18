import type { NextConfig } from "next";

// Local: BACKEND_URL → rewrites proxy to Flask (5001) / Spring Boot (8080)
// Cloud: Cloudflare Workers (_worker.js) → Render backend proxy
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:5001';

// Spring Boot backend (gradual migration)
const SPRING_BOOT_URL = process.env.SPRING_BOOT_URL || 'http://localhost:8080';

// API path prefixes that map to Flask endpoints
// NOTE: 'auth' is excluded — next-auth handles /api/auth/* via its own route handler
const API_PREFIXES = [
  'kr', 'us', 'crypto', 'econ', 'dividend',
  'admin', 'stripe',
  'system', 'stock', 'skills',
];

const nextConfig: NextConfig = {
  output: process.env.STATIC_EXPORT === '1' ? 'export' : undefined,
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
        ],
      },
    ];
  },
  async rewrites() {
      // ── Migrated endpoints → Spring Boot (8080) ──
      // These specific routes MUST come before the generic Flask catch-all
      const migratedRewrites = [
        // ── US Market (10 endpoints) ──
        { source: '/api/us/market-briefing', destination: `${SPRING_BOOT_URL}/api/us/market-briefing` },
        { source: '/api/us/portfolio', destination: `${SPRING_BOOT_URL}/api/us/portfolio` },
        { source: '/api/us/market-gate', destination: `${SPRING_BOOT_URL}/api/us/market-gate` },
        { source: '/api/us/decision-signal', destination: `${SPRING_BOOT_URL}/api/us/decision-signal` },
        { source: '/api/us/market-regime', destination: `${SPRING_BOOT_URL}/api/us/market-regime` },
        { source: '/api/us/index-prediction', destination: `${SPRING_BOOT_URL}/api/us/index-prediction` },
        { source: '/api/us/risk-alerts', destination: `${SPRING_BOOT_URL}/api/us/risk-alerts` },
        { source: '/api/us/sector-rotation', destination: `${SPRING_BOOT_URL}/api/us/sector-rotation` },
        { source: '/api/us/cumulative-performance', destination: `${SPRING_BOOT_URL}/api/us/cumulative-performance` },
        { source: '/api/us/super-performance', destination: `${SPRING_BOOT_URL}/api/us/super-performance` },
        // ── KR Market (7 endpoints) ──
        { source: '/api/kr/market-gate', destination: `${SPRING_BOOT_URL}/api/kr/market-gate` },
        { source: '/api/kr/signals', destination: `${SPRING_BOOT_URL}/api/kr/signals` },
        { source: '/api/kr/backtest-summary', destination: `${SPRING_BOOT_URL}/api/kr/backtest-summary` },
        { source: '/api/kr/ai-analysis', destination: `${SPRING_BOOT_URL}/api/kr/ai-analysis` },
        { source: '/api/kr/vcp-stats', destination: `${SPRING_BOOT_URL}/api/kr/vcp-stats` },
        { source: '/api/kr/vcp-history', destination: `${SPRING_BOOT_URL}/api/kr/vcp-history` },
        { source: '/api/kr/realtime-prices', destination: `${SPRING_BOOT_URL}/api/kr/realtime-prices` },
        // ── KR Closing Bet (5 endpoints) ──
        { source: '/api/kr/jongga-v2/latest', destination: `${SPRING_BOOT_URL}/api/kr/jongga-v2/latest` },
        { source: '/api/kr/jongga-v2/dates', destination: `${SPRING_BOOT_URL}/api/kr/jongga-v2/dates` },
        { source: '/api/kr/jongga-v2/history/:dateStr', destination: `${SPRING_BOOT_URL}/api/kr/jongga-v2/history/:dateStr` },
        { source: '/api/kr/jongga-v2/analyze', destination: `${SPRING_BOOT_URL}/api/kr/jongga-v2/analyze` },
        { source: '/api/kr/jongga-v2/run', destination: `${SPRING_BOOT_URL}/api/kr/jongga-v2/run` },
        // ── Crypto (9 endpoints) ──
        { source: '/api/crypto/dominance', destination: `${SPRING_BOOT_URL}/api/crypto/dominance` },
        { source: '/api/crypto/overview', destination: `${SPRING_BOOT_URL}/api/crypto/overview` },
        { source: '/api/crypto/market-gate', destination: `${SPRING_BOOT_URL}/api/crypto/market-gate` },
        { source: '/api/crypto/gate-history', destination: `${SPRING_BOOT_URL}/api/crypto/gate-history` },
        { source: '/api/crypto/briefing', destination: `${SPRING_BOOT_URL}/api/crypto/briefing` },
        { source: '/api/crypto/vcp-signals', destination: `${SPRING_BOOT_URL}/api/crypto/vcp-signals` },
        { source: '/api/crypto/run-scan', destination: `${SPRING_BOOT_URL}/api/crypto/run-scan` },
        { source: '/api/crypto/task-status', destination: `${SPRING_BOOT_URL}/api/crypto/task-status` },
        { source: '/api/crypto/signal-analysis', destination: `${SPRING_BOOT_URL}/api/crypto/signal-analysis` },
        // ── Stock Analyzer / ProPicks → Flask (5001) ──
        { source: '/api/stock-analyzer/search', destination: `${BACKEND_URL}/api/stock-analyzer/search` },
        { source: '/api/stock-analyzer/analyze', destination: `${BACKEND_URL}/api/stock-analyzer/analyze` },
        { source: '/api/stock-analyzer/export', destination: `${BACKEND_URL}/api/stock-analyzer/export` },
      ];

      // ── LOCAL: Remaining endpoints → Flask backend ──
      const flaskRewrites = API_PREFIXES.map(prefix => ({
        source: `/api/${prefix}/:path*`,
        destination: `${BACKEND_URL}/api/${prefix}/:path*`,
      }));

      const additionalRewrites = [
        { source: '/api/health', destination: `${BACKEND_URL}/api/health` },
        { source: '/api/realtime-prices', destination: `${BACKEND_URL}/api/realtime-prices` },
        { source: '/api/data-version', destination: `${BACKEND_URL}/api/data-version` },
        { source: '/api/portfolio-summary', destination: `${BACKEND_URL}/api/portfolio-summary` },
      ];

      return [...migratedRewrites, ...flaskRewrites, ...additionalRewrites];
  },
};

export default nextConfig;
