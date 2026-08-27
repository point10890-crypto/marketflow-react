import { useEffect } from 'react';

/**
 * 공개 페이지 SEO 헤드 관리 — react-helmet 없이 document head 를 직접 갱신한다.
 *
 * SPA 는 모든 경로가 같은 index.html 을 반환하므로, 라우트별 canonical /
 * title / description / OG / JSON-LD 를 렌더 시점에 심어야 검색엔진과
 * AdSense 심사 크롤러가 각 URL 을 고유 문서로 인식한다.
 * 크롤러가 JS 를 실행하지 못하는 경우는 scripts/prerender-seo.mjs 가
 * 빌드 시 만들어 두는 정적 스냅샷이 커버한다.
 */

export const SITE_ORIGIN = 'https://bit-man.net';
export const SITE_NAME = 'MarketFlow';
export const DEFAULT_OG_IMAGE = `${SITE_ORIGIN}/icon-512.png`;

export interface SeoOptions {
    /** 문서 제목. "| MarketFlow" 는 자동으로 붙지 않으므로 완성형으로 전달. */
    title: string;
    description?: string;
    /** canonical 경로 (예: '/about'). 생략 시 현재 pathname 사용. */
    path?: string;
    /** 로그인·가입·결제 등 검색 결과에 노출할 이유가 없는 페이지는 true. */
    noindex?: boolean;
    ogType?: 'website' | 'article';
    ogImage?: string;
    /** schema.org JSON-LD 객체 (단일 또는 배열). */
    jsonLd?: object | object[];
}

function upsertMeta(attr: 'name' | 'property', key: string, content: string | null) {
    let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
    if (content === null) {
        el?.remove();
        return;
    }
    if (!el) {
        el = document.createElement('meta');
        el.setAttribute(attr, key);
        document.head.appendChild(el);
    }
    el.setAttribute('content', content);
}

function upsertCanonical(href: string | null) {
    let el = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
    if (href === null) {
        el?.remove();
        return;
    }
    if (!el) {
        el = document.createElement('link');
        el.setAttribute('rel', 'canonical');
        document.head.appendChild(el);
    }
    el.setAttribute('href', href);
}

function upsertJsonLd(data: object | object[] | null) {
    let el = document.head.querySelector<HTMLScriptElement>('script[data-seo="jsonld"]');
    if (!data) {
        el?.remove();
        return;
    }
    if (!el) {
        el = document.createElement('script');
        el.type = 'application/ld+json';
        el.dataset.seo = 'jsonld';
        document.head.appendChild(el);
    }
    el.textContent = JSON.stringify(data);
}

export function applySeo(opts: SeoOptions) {
    const path = opts.path ?? window.location.pathname;
    const url = `${SITE_ORIGIN}${path === '/' ? '/' : path.replace(/\/+$/, '')}`;

    document.title = opts.title;
    if (opts.description) upsertMeta('name', 'description', opts.description);
    upsertMeta('name', 'robots', opts.noindex ? 'noindex, nofollow' : null);

    // noindex 페이지는 canonical 을 두지 않는다 (모순 신호 방지).
    upsertCanonical(opts.noindex ? null : url);

    upsertMeta('property', 'og:title', opts.title);
    if (opts.description) upsertMeta('property', 'og:description', opts.description);
    upsertMeta('property', 'og:url', url);
    upsertMeta('property', 'og:type', opts.ogType ?? 'website');
    upsertMeta('property', 'og:image', opts.ogImage ?? DEFAULT_OG_IMAGE);
    upsertMeta('name', 'twitter:card', 'summary');
    upsertMeta('name', 'twitter:title', opts.title);
    if (opts.description) upsertMeta('name', 'twitter:description', opts.description);

    upsertJsonLd(opts.jsonLd ?? null);
}

/**
 * 라우트 진입 시 SEO 메타를 적용하는 훅.
 * 의존성은 title/path/noindex 직렬화 값 — 게시글처럼 데이터 로딩 후
 * 제목이 바뀌는 페이지는 로딩 완료 시점 값으로 다시 호출된다.
 */
export function useSeo(opts: SeoOptions) {
    const depKey = JSON.stringify([opts.title, opts.description, opts.path, opts.noindex, opts.ogType]);
    useEffect(() => {
        applySeo(opts);
        // 페이지 이탈 시 이 페이지 고유 신호는 제거한다. 다음 페이지의
        // useSeo (cleanup 후 실행) 가 자기 값을 다시 심는다.
        return () => {
            upsertMeta('name', 'robots', null);
            upsertCanonical(null);
            upsertJsonLd(null);
        };
    }, [depKey]);
}

/** HTML 문자열에서 텍스트만 추출해 메타 description 용으로 요약. */
export function summarizeHtml(html: string, maxLen = 160): string {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const text = (doc.body.textContent || '').replace(/\s+/g, ' ').trim();
    return text.length > maxLen ? `${text.slice(0, maxLen - 1)}…` : text;
}
