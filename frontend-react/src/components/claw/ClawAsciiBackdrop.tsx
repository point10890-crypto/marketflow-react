/**
 * ASCII 집게 텍스처 — 캔버스로 절차 생성하는 원본 배경 (외부 이미지·브랜드 자산 없음).
 *
 * 희미한 점 격자 위에, 두 개의 집게(부분 링 + 벌어진 입)를 거리장(distance field)으로 그리고
 * 밀도에 따라 ' .:-=+x#@' 문자를 찍는다. 장중(live)엔 문자가 느리게 일렁이고,
 * prefers-reduced-motion 이거나 탭이 숨겨지면 정지한다.
 */
import { useEffect, useRef } from 'react';

const RAMP = ' .:-=+x#@';

interface Props { live?: boolean; tone?: 'teal' | 'amber' | 'gray'; className?: string; }

const TONES = { teal: [45, 212, 191], amber: [251, 191, 36], gray: [156, 163, 175] } as const;

export default function ClawAsciiBackdrop({ live = false, tone = 'teal', className = '' }: Props) {
    const ref = useRef<HTMLCanvasElement | null>(null);

    useEffect(() => {
        const canvas = ref.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;
        const [cr, cg, cb] = TONES[tone];
        const reduced = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
        let raf = 0, last = 0, phase = 0, W = 0, H = 0, dpr = 1;

        const resize = () => {
            const parent = canvas.parentElement;
            if (!parent) return;
            W = parent.clientWidth; H = parent.clientHeight;
            dpr = Math.min(2, window.devicePixelRatio || 1);
            canvas.width = Math.floor(W * dpr); canvas.height = Math.floor(H * dpr);
            canvas.style.width = `${W}px`; canvas.style.height = `${H}px`;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            draw();
        };

        // 집게 한 개의 강도: 중심 c, 반지름 R, 벌어진 입 각도(opening) 쪽은 비운다
        const clawField = (x: number, y: number, cx: number, cy: number, R: number, openTo: number): number => {
            const dx = x - cx, dy = y - cy;
            const d = Math.hypot(dx, dy);
            const ring = Math.exp(-((d - R) ** 2) / (2 * (R * 0.16) ** 2));        // 링 띠
            const ang = Math.atan2(dy, dx);
            let diff = Math.abs(ang - openTo); if (diff > Math.PI) diff = 2 * Math.PI - diff;
            const mouth = diff < 0.55 ? 0 : Math.min(1, (diff - 0.55) / 0.35);            // 입 벌림
            const inner = d < R * 0.55 ? Math.exp(-((d - R * 0.35) ** 2) / (2 * (R * 0.12) ** 2)) * 0.45 : 0; // 안쪽 마디
            return Math.max(ring * mouth, inner * mouth);
        };

        const draw = () => {
            if (!W || !H) return;
            ctx.clearRect(0, 0, W, H);
            const cw = 13, ch = 16;
            ctx.font = '11px "JetBrains Mono", "SF Mono", Consolas, monospace';
            ctx.textBaseline = 'middle';
            const R = Math.min(H * 0.42, W * 0.22);
            const cyL = H * 0.52, cyR = H * 0.52;
            const cxL = W * 0.22, cxR = W * 0.78;
            for (let y = ch / 2; y < H; y += ch) {
                for (let x = cw / 2; x < W; x += cw) {
                    const vL = clawField(x, y, cxL, cyL, R, 0);            // 오른쪽(중앙)으로 벌어짐
                    const vR = clawField(x, y, cxR, cyR, R, Math.PI);      // 왼쪽(중앙)으로 벌어짐
                    let v = Math.max(vL, vR);
                    // 살아있는 느낌: 위상에 따라 미세 일렁임
                    if (live) v *= 0.85 + 0.15 * Math.sin(phase + x * 0.05 + y * 0.03);
                    // 중앙(마스코트·헤드라인 영역)은 비운다
                    const cx = Math.abs(x - W / 2) / (W * 0.18), cy = (y - H * 0.5) / (H * 0.5);
                    const center = Math.exp(-(cx * cx + cy * cy) * 1.6);
                    v *= 1 - center;
                    if (v < 0.06) {
                        if (((x / cw) | 0) % 2 === ((y / ch) | 0) % 2) {
                            ctx.fillStyle = `rgba(${cr},${cg},${cb},0.07)`;
                            ctx.fillText('·', x - 2, y);
                        }
                        continue;
                    }
                    const idx = Math.min(RAMP.length - 1, Math.floor(v * (RAMP.length - 1)));
                    const alpha = 0.12 + v * 0.55;
                    ctx.fillStyle = `rgba(${cr},${cg},${cb},${alpha.toFixed(3)})`;
                    ctx.fillText(RAMP[idx], x - 3, y);
                }
            }
        };

        const loop = (t: number) => {
            if (t - last > 125) { phase += 0.12; last = t; draw(); }
            raf = requestAnimationFrame(loop);
        };
        const onVis = () => {
            cancelAnimationFrame(raf);
            if (live && !reduced && document.visibilityState === 'visible') raf = requestAnimationFrame(loop);
        };

        const ro = new ResizeObserver(resize);
        ro.observe(canvas.parentElement as Element);
        resize();
        onVis();
        document.addEventListener('visibilitychange', onVis);
        return () => { cancelAnimationFrame(raf); ro.disconnect(); document.removeEventListener('visibilitychange', onVis); };
    }, [live, tone]);

    return <canvas ref={ref} aria-hidden="true" className={`pointer-events-none absolute inset-0 ${className}`} />;
}
