/** guides.mjs 타입 선언 — React(TS)와 프리렌더 스크립트(node)가 같은 모듈을 공유한다. */

export interface Guide {
    slug: string;
    title: string;
    description: string;
    category: string;
    /** YYYY-MM-DD */
    date: string;
    readMinutes: number;
    /** 신뢰된 저장소 내장 HTML (h2/h3/p/ul/ol/strong/table 만 사용) */
    html: string;
}

export declare const GUIDES: Guide[];
export declare function findGuide(slug: string): Guide | null;
