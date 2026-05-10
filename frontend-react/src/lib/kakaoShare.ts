/**
 * Kakao SDK 공유 헬퍼.
 *
 * 사용:
 *   import { shareToKakao } from '@/lib/kakaoShare';
 *   await shareToKakao({ title, description, image_url, link_url });
 *
 * 우선순위:
 *   1) Kakao SDK initialized → Kakao.Share.sendDefault (네이티브 카드)
 *   2) navigator.share API → 모바일에서 카카오톡 포함 시스템 공유 시트
 *   3) fallback → 클립보드 복사
 *
 * Kakao SDK 자바스크립트 키: VITE_KAKAO_JS_KEY (Cloudflare Pages env).
 * 미설정이라도 navigator.share / clipboard fallback 으로 폴리시.
 */

declare global {
    interface Window {
        Kakao?: {
            isInitialized: () => boolean;
            init: (jsKey: string) => void;
            Share: {
                sendDefault: (options: KakaoFeedTemplate) => void;
            };
        };
    }
}

export interface KakaoShareInput {
    title: string;
    description: string;
    image_url: string;
    link_url: string;
}

interface KakaoFeedTemplate {
    objectType: 'feed';
    content: {
        title: string;
        description: string;
        imageUrl: string;
        link: { mobileWebUrl: string; webUrl: string };
    };
    buttons?: Array<{ title: string; link: { mobileWebUrl: string; webUrl: string } }>;
}

let initAttempted = false;

function ensureKakaoInit(): boolean {
    if (typeof window === 'undefined' || !window.Kakao) return false;
    if (window.Kakao.isInitialized()) return true;
    if (initAttempted) return false;
    initAttempted = true;
    const key = import.meta.env.VITE_KAKAO_JS_KEY as string | undefined;
    if (!key || key.length < 10) {
        console.warn('[kakaoShare] VITE_KAKAO_JS_KEY 미설정 — Kakao SDK 비활성, fallback 사용');
        return false;
    }
    try {
        window.Kakao.init(key);
        return window.Kakao.isInitialized();
    } catch (err) {
        console.warn('[kakaoShare] Kakao.init 실패:', err);
        return false;
    }
}

/**
 * 우선 Kakao SDK → 실패 시 navigator.share → 최종 클립보드.
 * @returns 'kakao' | 'web-share' | 'clipboard' | 'failed'
 */
export async function shareToKakao(input: KakaoShareInput): Promise<'kakao' | 'web-share' | 'clipboard' | 'failed'> {
    // 1) Kakao SDK
    if (ensureKakaoInit() && window.Kakao?.Share) {
        try {
            window.Kakao.Share.sendDefault({
                objectType: 'feed',
                content: {
                    title: input.title,
                    description: input.description,
                    imageUrl: input.image_url,
                    link: { mobileWebUrl: input.link_url, webUrl: input.link_url },
                },
                buttons: [
                    { title: '분석 보기', link: { mobileWebUrl: input.link_url, webUrl: input.link_url } },
                ],
            });
            return 'kakao';
        } catch (err) {
            console.warn('[kakaoShare] Kakao.Share.sendDefault 실패:', err);
        }
    }

    // 2) Web Share API (모바일에서 카카오톡 포함 시스템 시트)
    if (typeof navigator !== 'undefined' && typeof navigator.share === 'function') {
        try {
            await navigator.share({
                title: input.title,
                text: input.description,
                url: input.link_url,
            });
            return 'web-share';
        } catch (err) {
            // 사용자가 취소한 경우도 여기로 옴 — 무시
            if ((err as Error)?.name !== 'AbortError') {
                console.warn('[kakaoShare] navigator.share 실패:', err);
            }
        }
    }

    // 3) 클립보드 fallback
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
        try {
            await navigator.clipboard.writeText(`${input.title}\n${input.description}\n${input.link_url}`);
            return 'clipboard';
        } catch (err) {
            console.warn('[kakaoShare] clipboard 복사 실패:', err);
        }
    }

    return 'failed';
}
