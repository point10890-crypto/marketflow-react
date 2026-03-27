import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
  define: {
    __BUILD_TIME__: JSON.stringify(new Date().toISOString()),
  },
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'apple-touch-icon.png'],
      manifest: false, // use public/manifest.json
      workbox: {
        skipWaiting: true,
        clientsClaim: true,
        cleanupOutdatedCaches: true,
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/api\.bit-man\.net\/api\//,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-cache',
              expiration: { maxEntries: 50, maxAgeSeconds: 300 },
              networkTimeoutSeconds: 10,
            },
          },
          {
            urlPattern: /^https:\/\/cdnjs\.cloudflare\.com\//,
            handler: 'CacheFirst',
            options: {
              cacheName: 'cdn-cache',
              expiration: { maxEntries: 10, maxAgeSeconds: 86400 * 30 },
            },
          },
        ],
      },
    }),
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
    sourcemap: false,
    minify: 'terser',
    terserOptions: {
      compress: { drop_console: true, drop_debugger: true },
      mangle: { toplevel: true },
    },
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
          query: ['@tanstack/react-query'],
        },
        chunkFileNames: 'assets/[hash].js',
        entryFileNames: 'assets/[hash].js',
        assetFileNames: 'assets/[hash][extname]',
      },
    },
  },
});
