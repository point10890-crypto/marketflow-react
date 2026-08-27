import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import './index.css';

declare const __BUILD_TIME__: string;

// 빌드 버전 로깅 (배포 확인용)
console.log(`[MarketFlow] Build: ${__BUILD_TIME__}`);

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

// 빌드 시 scripts/prerender-seo.mjs 가 크롤러용으로 심어 둔 정적 콘텐츠 스냅샷 제거.
// JS 가 실행되는 환경(사용자·렌더링 크롤러)에서는 React 앱이 같은 내용을 렌더한다.
document.getElementById('seo-content')?.remove();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>
);
