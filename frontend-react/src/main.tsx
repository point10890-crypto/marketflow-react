import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import './index.css';

declare const __BUILD_TIME__: string;

// 빌드 버전 로깅 (배포 확인용)
console.log(`[MarketFlow] Build: ${__BUILD_TIME__}`);

// Service Worker 영구 비활성화 — stale 캐시로 인한 "앱 안 뜸" 문제 해소
// 기존에 등록된 SW와 모든 캐시를 매 로드마다 정리
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistrations().then((regs) => {
    regs.forEach((r) => r.unregister());
  }).catch(() => {});
}
if ('caches' in window) {
  caches.keys().then((names) => {
    names.forEach((name) => caches.delete(name));
  }).catch(() => {});
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>
);
