import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { execFileSync } from 'node:child_process';
import { fileURLToPath, URL } from 'node:url';

// VitePWA 영구 제거 — SW가 stale 캐시 서빙해서 "앱 안 뜸" 사용자 불만 발생.
// 오프라인 모드 포기 (어차피 거의 작동 안 함). Cloudflare CDN edge 캐시로 충분.

const buildId = (() => {
  const deploymentSha = process.env.CF_PAGES_COMMIT_SHA || process.env.GITHUB_SHA;
  if (deploymentSha) return deploymentSha.slice(0, 12);
  try {
    return execFileSync('git', ['rev-parse', '--short=12', 'HEAD'], {
      cwd: fileURLToPath(new URL('.', import.meta.url)),
      encoding: 'utf8',
    }).trim();
  } catch {
    return new Date().toISOString().replace(/\D/g, '').slice(0, 12);
  }
})();

export default defineConfig({
  define: {
    __BUILD_TIME__: JSON.stringify(new Date().toISOString()),
  },
  plugins: [
    react(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: Number(process.env.PORT) || 4000,
    proxy: (() => {
      // 워크트리별 Flask 포트 지원: VITE_FLASK_PORT 또는 FLASK_PORT 환경변수
      const flaskPort = process.env.VITE_FLASK_PORT || process.env.FLASK_PORT || '5001';
      const flask = `http://localhost:${flaskPort}`;
      return {
        '/api/kr/screener': { target: flask, changeOrigin: true },
        '/api/kr/jongga-v2/analyze': { target: flask, changeOrigin: true },
        '/api/kr/jongga-v2/run': { target: flask, changeOrigin: true },
        '/api/kr/realtime-prices': { target: flask, changeOrigin: true },
        '/api/kr/financial-health': { target: flask, changeOrigin: true },
        '/api/kr/stock-chart': { target: flask, changeOrigin: true },
        '/api/us/stock-chart': { target: flask, changeOrigin: true },
        '/api/us/smart-money': { target: flask, changeOrigin: true },
        '/api/us/ai-summary': { target: flask, changeOrigin: true },
        '/api/crypto/chart': { target: flask, changeOrigin: true },
        '/api/crypto/run-': { target: flask, changeOrigin: true },
        '/api/crypto/signal-analysis': { target: flask, changeOrigin: true },
        '/api/crypto/vcp-signals': { target: flask, changeOrigin: true },
        '/api/stock-analyzer': { target: flask, changeOrigin: true },
        '/api/econ': { target: flask, changeOrigin: true },
        '/api/auth': { target: flask, changeOrigin: true },
        '/api/admin': { target: flask, changeOrigin: true },
        '/api/stripe': { target: flask, changeOrigin: true },
        '/api': { target: flask, changeOrigin: true },
      };
    })(),
  },
  build: {
    outDir: 'dist',
    // Vite 8 defaults to Safari/iOS 16.4. Keep the initial bundle parseable on
    // older iPhones that are still common among mobile users.
    target: ['es2018', 'safari13'],
    cssTarget: 'safari13',
    sourcemap: false,
    minify: 'terser',
    terserOptions: {
      compress: { drop_console: true, drop_debugger: true },
      mangle: { toplevel: true },
    },
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/node_modules/@tanstack/react-query/')) return 'query';
          if (
            id.includes('/node_modules/react/')
            || id.includes('/node_modules/react-dom/')
            || id.includes('/node_modules/react-router/')
            || id.includes('/node_modules/react-router-dom/')
          ) {
            return 'vendor';
          }
          return undefined;
        },
        // Terser can change emitted bytes after Rollup calculates [hash]. Add the
        // source revision so Cloudflare never reuses a stale immutable asset.
        chunkFileNames: `assets/[hash]-${buildId}.js`,
        entryFileNames: `assets/[hash]-${buildId}.js`,
        assetFileNames: `assets/[hash]-${buildId}[extname]`,
      },
    },
  },
});
