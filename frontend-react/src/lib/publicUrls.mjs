export const PUBLIC_ORIGIN = 'https://bit-man.net';

export function publicUrl(path) {
    const url = new URL(path, PUBLIC_ORIGIN);
    return `${PUBLIC_ORIGIN}${url.pathname.replace(/\/+$/, '')}/`;
}

// Keep structured data consistent with the canonical without changing asset URLs.
export function normalizePublicLinks(value) {
    if (Array.isArray(value)) return value.map(normalizePublicLinks);
    if (value && typeof value === 'object') {
        return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, normalizePublicLinks(v)]));
    }
    if (typeof value === 'string' && value.startsWith(`${PUBLIC_ORIGIN}/`)) {
        const url = new URL(value);
        if (!/\.[^/]+$/.test(url.pathname)) return publicUrl(value) + url.hash;
    }
    return value;
}
