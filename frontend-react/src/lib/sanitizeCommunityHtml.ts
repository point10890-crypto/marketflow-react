import DOMPurify from 'dompurify';

const YOUTUBE_HOSTS = new Set([
    'youtube.com',
    'www.youtube.com',
    'youtube-nocookie.com',
    'www.youtube-nocookie.com',
]);

export function sanitizeCommunityHtml(content: string, apiBase = ''): string {
    const sanitized = DOMPurify.sanitize(content, {
        ADD_TAGS: ['img', 'video', 'source', 'iframe'],
        ADD_ATTR: [
            'target', 'rel', 'src', 'alt', 'href', 'controls', 'playsinline',
            'muted', 'loop', 'autoplay', 'width', 'height', 'allowfullscreen',
            'frameborder', 'allow', 'type',
        ],
        FORBID_ATTR: ['style'],
    });

    const template = document.createElement('template');
    template.innerHTML = sanitized;

    if (apiBase) {
        template.content.querySelectorAll<HTMLElement>('img[src], video[src], source[src]').forEach((node) => {
            const src = node.getAttribute('src');
            if (src?.startsWith('/api/')) node.setAttribute('src', `${apiBase}${src}`);
        });
    }

    template.content.querySelectorAll<HTMLAnchorElement>('a[target="_blank"]').forEach((anchor) => {
        anchor.setAttribute('rel', 'noopener noreferrer');
    });

    template.content.querySelectorAll<HTMLIFrameElement>('iframe').forEach((iframe) => {
        const src = iframe.getAttribute('src');
        let allowed = false;
        if (src) {
            try {
                const url = new URL(src, window.location.origin);
                allowed = url.protocol === 'https:'
                    && YOUTUBE_HOSTS.has(url.hostname.toLowerCase())
                    && url.pathname.startsWith('/embed/');
            } catch {
                allowed = false;
            }
        }
        if (!allowed) {
            iframe.remove();
            return;
        }
        iframe.setAttribute('loading', 'lazy');
        iframe.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
        iframe.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-presentation');
    });

    return template.innerHTML;
}
