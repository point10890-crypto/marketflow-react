import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { registerSW } from 'virtual:pwa-register';
import App from './App';
import './index.css';

declare const __BUILD_TIME__: string;

// 빌드 버전 로깅 (배포 확인용)
console.log(`[MarketFlow] Build: ${__BUILD_TIME__}`);

// SW 업데이트 감지 시 즉시 적용 + 자동 새로고침
const updateSW = registerSW({
  onNeedRefresh() {
    // 새 버전 발견 → 즉시 활성화
    console.log('[PWA] New version detected, reloading...');
    updateSW(true); // skip waiting
    window.location.reload();
  },
  onOfflineReady() {
    console.log('[PWA] Offline ready');
  },
  onRegisteredSW(swUrl, registration) {
    // 60초마다 SW 업데이트 체크
    if (registration) {
      setInterval(() => {
        registration.update().catch(() => {});
      }, 60_000);
    }
  },
});

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
