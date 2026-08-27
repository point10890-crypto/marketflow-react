import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { GUIDES, findGuide } from '@/data/guides.mjs';

/**
 * 인사이트 가이드 데이터 계약 — AdSense 심사용 핵심 콘텐츠 존이므로
 * 데이터 품질과 sitemap 동기화를 테스트로 잠근다.
 */
describe('insight guides content contract', () => {
    it('has substantial, well-formed articles with unique slugs', () => {
        expect(GUIDES.length).toBeGreaterThanOrEqual(5);
        const slugs = GUIDES.map((g) => g.slug);
        expect(new Set(slugs).size).toBe(slugs.length);

        for (const g of GUIDES) {
            expect(g.slug).toMatch(/^[a-z0-9-]+$/);
            expect(g.title.length).toBeGreaterThan(10);
            expect(g.description.length).toBeGreaterThan(30);
            expect(g.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
            expect(g.readMinutes).toBeGreaterThan(0);
            // 본문은 실질 콘텐츠여야 한다 (얇은 글은 심사에 오히려 해가 됨)
            expect(g.html.length).toBeGreaterThan(1500);
            expect(g.html).toContain('<h2>');
        }
    });

    it('keeps hype and solicitation language out of guide content', () => {
        const banned = /수익 보장|확실한 수익|무조건|매수 추천|매수하세요|100% |급등 예정/;
        for (const g of GUIDES) {
            expect(`${g.title} ${g.description} ${g.html}`).not.toMatch(banned);
        }
    });

    it('lists every guide URL in sitemap.xml', () => {
        const sitemap = readFileSync(resolve(__dirname, '../../public/sitemap.xml'), 'utf-8');
        expect(sitemap).toContain('https://bit-man.net/guide</loc>');
        for (const g of GUIDES) {
            expect(sitemap).toContain(`https://bit-man.net/guide/${g.slug}</loc>`);
        }
    });

    it('resolves slugs through findGuide', () => {
        expect(findGuide(GUIDES[0].slug)?.title).toBe(GUIDES[0].title);
        expect(findGuide('no-such-guide')).toBeNull();
    });
});
