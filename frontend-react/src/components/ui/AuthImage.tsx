import { useEffect, useState } from 'react';
import { authHeaders } from '@/lib/api';

// 인증 헤더를 포함해 이미지를 blob으로 받아 ObjectURL로 렌더링.
// <img> 태그는 Authorization 헤더를 실을 수 없기 때문에 pro-gate 엔드포인트에 직접 src로 붙이면 403이 발생.
export function AuthImage({ src, alt, className }: { src: string; alt: string; className?: string }) {
    const [objectUrl, setObjectUrl] = useState<string | null>(null);
    const [failed, setFailed] = useState(false);

    useEffect(() => {
        let cancelled = false;
        let createdUrl: string | null = null;
        setFailed(false);
        setObjectUrl(null);
        (async () => {
            try {
                const res = await fetch(src, { headers: authHeaders() });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const blob = await res.blob();
                if (cancelled) return;
                createdUrl = URL.createObjectURL(blob);
                setObjectUrl(createdUrl);
            } catch {
                if (!cancelled) setFailed(true);
            }
        })();
        return () => {
            cancelled = true;
            if (createdUrl) URL.revokeObjectURL(createdUrl);
        };
    }, [src]);

    if (failed) return null;
    if (!objectUrl) {
        return <div className={`${className ?? ''} aspect-[16/9] bg-white/[0.03] animate-pulse`} />;
    }
    return <img src={objectUrl} alt={alt} className={className} loading="lazy" />;
}
