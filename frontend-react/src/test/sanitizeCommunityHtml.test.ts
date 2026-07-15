import { describe, expect, it } from 'vitest';
import { sanitizeCommunityHtml } from '@/lib/sanitizeCommunityHtml';

describe('sanitizeCommunityHtml', () => {
    it('removes executable markup, inline style, and unsafe embeds', () => {
        const html = sanitizeCommunityHtml(`
            <script>alert(1)</script>
            <p style="position:fixed" onclick="alert(1)">safe</p>
            <iframe src="https://evil.example/embed/1"></iframe>
        `);
        expect(html).toContain('<p>safe</p>');
        expect(html).not.toContain('script');
        expect(html).not.toContain('style=');
        expect(html).not.toContain('onclick');
        expect(html).not.toContain('iframe');
    });

    it('allows hardened YouTube embeds and rewrites API media URLs', () => {
        const html = sanitizeCommunityHtml(`
            <iframe src="https://www.youtube-nocookie.com/embed/abc"></iframe>
            <img src="/api/community/uploads/example.png">
            <a href="https://example.com" target="_blank">external</a>
        `, 'https://marketflow-api.bit-man.net');

        expect(html).toContain('https://www.youtube-nocookie.com/embed/abc');
        expect(html).toContain('sandbox="allow-scripts allow-same-origin allow-presentation"');
        expect(html).toContain('src="https://marketflow-api.bit-man.net/api/community/uploads/example.png"');
        expect(html).toContain('rel="noopener noreferrer"');
    });
});
