/**
 * Kakao SDK 공유 헬퍼 — Feed + List 템플릿 + 3-tier fallback.
 *
 * 사용:
 *   import { shareToKakao } from '@/lib/kakaoShare';
 *   await shareToKakao({ title, description, image_url, link_url, list_contents?, kakao_buttons? });
 *
 * 우선순위:
 *   1) Kakao SDK initialized → list_contents 있으면 list template, 없으면 feed
 *   2) navigator.share API → 모바일 시스템 시트 (카톡 포함)
 *   3) clipboard 복사 → 알림
 *
 * VITE_KAKAO_JS_KEY 미설정이라도 fallback 작동.
 */

declare global {
    interface Window {
        Kakao?: {
            isInitialized: () => boolean;
            init: (jsKey: string) => void;
            Share: {
                sendDefault: (options: KakaoTemplate) => void;
            };
        };
    }
}

export interface KakaoShareItem {
    title: string;
    description: string;
    image_url: string;
    link_url: string;
}

export interface KakaoButton {
    title: string;
    link_url: string;
}

export interface KakaoShareInput {
    title: string;
    description: string;
    image_url: string;
    link_url: string;
    list_contents?: KakaoShareItem[];
    kakao_buttons?: KakaoButton[];
}

interface KakaoLink {
    mobileWebUrl: string;
    webUrl: string;
}

interface KakaoFeedTemplate {
    objectType: 'feed';
    content: { title: string; description: string; imageUrl: string; link: KakaoLink };
    buttons?: Array<{ title: string; link: KakaoLink }>;
}

interface KakaoListTemplate {
    objectType: 'list';
    headerTitle: string;
    headerLink: KakaoLink;
    contents: Array<{ title: string; description: string; imageUrl: string; link: KakaoLink }>;
    buttons?: Array<{ title: string; link: KakaoLink }>;
}

type KakaoTemplate = KakaoFeedTemplate | KakaoListTemplate;

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

function asLink(url: string): KakaoLink {
    return { mobileWebUrl: url, webUrl: url };
}

function buildButtons(input: KakaoShareInput) {
    const buttons = input.kakao_buttons && input.kakao_buttons.length > 0
        ? input.kakao_buttons
        : [{ title: '분석 보기', link_url: input.link_url }];
    // Kakao SDK 는 최대 2개 button 허용
    return buttons.slice(0, 2).map((b) => ({ title: b.title, link: asLink(b.link_url) }));
}

/**
 * Kakao SDK → navigator.share → clipboard 순서.
 * @returns 'kakao-list' | 'kakao-feed' | 'web-share' | 'clipboard' | 'failed'
 */
export async function shareToKakao(
    input: KakaoShareInput,
): Promise<'kakao-list' | 'kakao-feed' | 'web-share' | 'clipboard' | 'failed'> {
    // 1) Kakao SDK
    if (ensureKakaoInit() && window.Kakao?.Share) {
        try {
            // List template 우선 (TOP 3 등 다중 카드)
            if (input.list_contents && input.list_contents.length > 0) {
                window.Kakao.Share.sendDefault({
                    objectType: 'list',
                    headerTitle: input.title,
                    headerLink: asLink(input.link_url),
                    contents: input.list_contents.slice(0, 5).map((c) => ({
                        title: c.title,
                        description: c.description,
                        imageUrl: c.image_url,
                        link: asLink(c.link_url),
                    })),
                    buttons: buildButtons(input),
                });
                return 'kakao-list';
            }
            // Feed template (단일/요약)
            window.Kakao.Share.sendDefault({
                objectType: 'feed',
                content: {
                    title: input.title,
                    description: input.description,
                    imageUrl: input.image_url,
                    link: asLink(input.link_url),
                },
                buttons: buildButtons(input),
            });
            return 'kakao-feed';
        } catch (err) {
            console.warn('[kakaoShare] Kakao.Share.sendDefault 실패:', err);
        }
    }

    // 2) Web Share API (모바일에서 카카오톡 포함 시스템 시트)
    if (typeof navigator !== 'undefined' && typeof navigator.share === 'function') {
        try {
            // 풍부한 텍스트 — list 가 있으면 모두 합쳐서 공유
            const richText = input.list_contents && input.list_contents.length > 0
                ? input.list_contents.map((c) => `${c.title}\n${c.description}`).join('\n\n')
                : input.description;
            await navigator.share({
                title: input.title,
                text: richText,
                url: input.link_url,
            });
            return 'web-share';
        } catch (err) {
            if ((err as Error)?.name !== 'AbortError') {
                console.warn('[kakaoShare] navigator.share 실패:', err);
            }
        }
    }

    // 3) clipboard fallback — 풍부한 텍스트
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
        try {
            const fullText = [
                input.title,
                '',
                input.description,
                ...((input.list_contents || []).map((c) => `\n• ${c.title}\n  ${c.description}`)),
                '',
                input.link_url,
            ].join('\n');
            await navigator.clipboard.writeText(fullText);
            return 'clipboard';
        } catch (err) {
            console.warn('[kakaoShare] clipboard 복사 실패:', err);
        }
    }

    return 'failed';
}
