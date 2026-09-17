import { afterEach, expect, it } from 'vitest';
import { applySeo } from '@/lib/seo';

afterEach(() => { document.head.innerHTML = ''; });

it.each(['/guide', '/guide/', '/community/post/3', '/community/post/3/'])('uses the final slash URL before and after client navigation: %s', path => {
    applySeo({ title: '공개 콘텐츠', path });
    const expected = `https://bit-man.net${path.replace(/\/$/, '')}/`;
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe(expected);
    expect(document.querySelector('meta[property="og:url"]')?.getAttribute('content')).toBe(expected);
});

it('keeps a private route out of the canonical index', () => {
    applySeo({ title: '로그인', path: '/login', noindex: true });
    expect(document.querySelector('link[rel="canonical"]')).toBeNull();
});
