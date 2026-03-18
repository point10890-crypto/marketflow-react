'use client';

import { SessionProvider } from 'next-auth/react';

/**
 * SessionProvider를 항상 감싸는 래퍼.
 * Vercel에서도 /api/auth/[...nextauth] route handler가 세션 요청을 처리하므로
 * SessionProvider를 항상 활성화해야 useSession() 훅이 정상 동작합니다.
 * (SessionProvider 없이 useSession()을 호출하면 production에서 undefined를 반환하여
 *  destructuring TypeError로 전체 hydration이 실패합니다)
 */
export default function AuthProvider({ children }: { children: React.ReactNode }) {
    return <SessionProvider>{children}</SessionProvider>;
}
