import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
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
            urlPattern: /^https:\/\/.*\.ngrok-free\.(dev|app)\/api\//,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-cache',
              expiration: { maxEntries: 50, maxAgeSeconds: 300 },
              networkTimeoutSeconds: 10,
            },
          },
          {
            urlPattern: /\/data\/.*\.json$/,
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'static-data',
              expiration: { maxEntries: 30, maxAgeSeconds: 3600 },
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
    proxy: {
      // KIS 주도주 스크리너 → Flask
      '/api/kr/screener': { target: 'http://localhost:5001', changeOrigin: true },
      // LIVE_COMPUTE → Flask:5001 (yfinance, DART, LLM, subprocess)
      '/api/kr/jongga-v2/analyze': { target: 'http://localhost:5001', changeOrigin: true },
      '/api/kr/jongga-v2/run': { target: 'http://localhost:5001', changeOrigin: true },
      '/api/kr/realtime-prices': { target: 'http://localhost:5001', changeOrigin: true },
      '/api/kr/financial-health': { target: 'http://localhost:5001', changeOrigin: true },
      '/api/kr/stock-chart': { target: 'http://localhost:5001', changeOrigin: true },
      '/api/us/stock-chart': { target: 'http://localhost:5001', changeOrigin: true },
      '/api/us/smart-money': { target: 'http://localhost:5001', changeOrigin: true },
      '/api/us/ai-summary': { target: 'http://localhost:5001', changeOrigin: true },
      '/api/crypto/chart': { target: 'http://localhost:5001', changeOrigin: true },
      '/api/crypto/run-': { target: 'http://localhost:5001', changeOrigin: true },
      '/api/crypto/signal-analysis': { target: 'http://localhost:5001', changeOrigin: true },
      '/api/crypto/vcp-signals': { target: 'http://localhost:5001', changeOrigin: true },
      '/api/stock-analyzer': { target: 'http://localhost:5001', changeOrigin: true },
      '/api/econ': { target: 'http://localhost:5001', changeOrigin: true },
      '/api/auth': { target: 'http://localhost:5001', changeOrigin: true },
      '/api/admin': { target: 'http://localhost:5001', changeOrigin: true },
      '/api/stripe': { target: 'http://localhost:5001', changeOrigin: true },
      // 나머지 전부 → Spring Boot:8080
      '/api': { target: 'http://localhost:8080', changeOrigin: true },
    },
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
