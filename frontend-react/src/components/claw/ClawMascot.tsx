/**
 * Claw 마스코트 — MarketFlow 고유 캐릭터 (원본 SVG, 외부 브랜드 자산 미사용).
 *
 * 상태가 곧 표정이다:
 *  running : 집게가 상승 캔들을 집고 가볍게 움직임, 눈 깜빡임, 몸 바운스
 *  idle    : 느린 숨, 반쯤 감은 눈, "z z" 떠오름
 *  halt    : 앰버 톤, 집게를 들어 "멈춤", "!" 배지
 *  dead    : 회색, 움직임 없음, "?" 배지
 * prefers-reduced-motion 이면 모든 애니메이션을 끈다 (index.css).
 */
import type { ClawLoopState } from '@/lib/claw';

interface Props {
    state: ClawLoopState | null;
    size?: number;
    className?: string;
    title?: string;
}

const TONE: Record<string, { body1: string; body2: string; claw: string; eye: string; glow: string }> = {
    // 브랜드 레드 — 레퍼런스(빨간 크랩 + 붉은 아우라)와 같은 톤
    running: { body1: '#ff8a6b', body2: '#b91c1c', claw: '#ff5a3c', eye: '#1a0a08', glow: 'rgba(255,90,60,.45)' },
    idle: { body1: '#f0836a', body2: '#8f1d1d', claw: '#e0553c', eye: '#1a0a08', glow: 'rgba(255,90,60,.22)' },
    halt: { body1: '#fcd34d', body2: '#b45309', claw: '#fbbf24', eye: '#1a1200', glow: 'rgba(251,191,36,.35)' },
    dead: { body1: '#9ca3af', body2: '#4b5563', claw: '#6b7280', eye: '#111827', glow: 'rgba(156,163,175,.18)' },
};

export default function ClawMascot({ state, size = 72, className = '', title }: Props) {
    const s = state ?? 'idle';
    const t = TONE[s] ?? TONE.idle;
    const anim = s === 'running' ? 'claw-anim-run' : s === 'idle' ? 'claw-anim-idle' : s === 'halt' ? 'claw-anim-halt' : 'claw-anim-dead';
    const id = `clawg-${s}`;
    return (
        <svg
            width={size} height={size} viewBox="0 0 120 120" role="img" aria-label={title ?? 'Claw 마스코트'}
            className={`claw-mascot ${anim} ${className}`} data-state={s}
        >
            <defs>
                <radialGradient id={`${id}-glow`} cx="50%" cy="55%" r="50%">
                    <stop offset="0%" stopColor={t.glow} />
                    <stop offset="100%" stopColor="rgba(0,0,0,0)" />
                </radialGradient>
                <linearGradient id={`${id}-body`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={t.body1} />
                    <stop offset="100%" stopColor={t.body2} />
                </linearGradient>
            </defs>

            {/* 배경 글로우 */}
            <circle cx="60" cy="66" r="54" fill={`url(#${id}-glow)`} className="claw-glow" />

            <g className="claw-body" style={{ transformOrigin: '60px 70px' }}>
                {/* 다리 */}
                <g stroke={t.body2} strokeWidth="3" strokeLinecap="round" opacity=".9">
                    <path d="M38 84 L30 94" /><path d="M46 88 L42 99" /><path d="M54 90 L53 101" />
                    <path d="M82 84 L90 94" /><path d="M74 88 L78 99" /><path d="M66 90 L67 101" />
                </g>

                {/* 왼쪽 집게 */}
                <g className="claw-left" style={{ transformOrigin: '34px 68px' }}>
                    <path d="M34 68 L26 56 A13 13 0 1 0 26 80 Z" fill={t.claw} />
                    <circle cx="25" cy="68" r="4" fill={t.body2} opacity=".35" />
                </g>

                {/* 오른쪽 집게 + 상승 캔들 */}
                <g className="claw-right" style={{ transformOrigin: '86px 68px' }}>
                    <path d="M86 68 L94 56 A13 13 0 1 1 94 80 Z" fill={t.claw} />
                    <g className="claw-candles" transform="translate(92 50)">
                        <rect x="0" y="12" width="4" height="10" rx="1" fill="#6fa3ff" />
                        <rect x="6" y="7" width="4" height="15" rx="1" fill="#ff5c72" />
                        <rect x="12" y="1" width="4" height="21" rx="1" fill="#ff5c72" />
                        <path d="M2 10 L2 12 M8 4 L8 7 M14 -3 L14 1" stroke="#ffd1c9" strokeWidth="1.5" strokeLinecap="round" />
                    </g>
                </g>

                {/* 몸통 */}
                <ellipse cx="60" cy="68" rx="30" ry="22" fill={`url(#${id}-body)`} />
                <ellipse cx="60" cy="62" rx="22" ry="11" fill="rgba(255,255,255,.10)" />

                {/* 눈자루 + 눈 */}
                <g stroke={t.body2} strokeWidth="3" strokeLinecap="round">
                    <path d="M50 50 L46 36" /><path d="M70 50 L74 36" />
                </g>
                <g className="claw-eyes" style={{ transformOrigin: '60px 34px' }}>
                    <circle cx="46" cy="33" r="7" fill="#ffffff" />
                    <circle cx="74" cy="33" r="7" fill="#ffffff" />
                    <circle cx="47.5" cy="34" r="3" fill={t.eye} className="claw-pupil" />
                    <circle cx="75.5" cy="34" r="3" fill={t.eye} className="claw-pupil" />
                    {s === 'idle' && (<g fill={t.body2} opacity=".9"><path d="M39 31 A7 7 0 0 1 53 31 L53 33 L39 33 Z" /><path d="M67 31 A7 7 0 0 1 81 31 L81 33 L67 33 Z" /></g>)}
                    {s === 'dead' && (<g stroke={t.eye} strokeWidth="2" strokeLinecap="round"><path d="M43 30 L49 36 M49 30 L43 36" /><path d="M71 30 L77 36 M77 30 L71 36" /></g>)}
                </g>

                {/* 입 */}
                {s === 'halt' ? <path d="M52 76 Q60 72 68 76" stroke={t.eye} strokeWidth="2.5" strokeLinecap="round" fill="none" />
                    : s === 'dead' ? <path d="M53 76 L67 76" stroke={t.eye} strokeWidth="2.5" strokeLinecap="round" />
                    : <path d="M52 74 Q60 80 68 74" stroke={t.eye} strokeWidth="2.5" strokeLinecap="round" fill="none" />}
            </g>

            {/* 상태 배지 */}
            {s === 'halt' && (
                <g className="claw-badge">
                    <circle cx="98" cy="22" r="11" fill="#fbbf24" />
                    <text x="98" y="27" textAnchor="middle" fontSize="15" fontWeight="800" fill="#1a1200" fontFamily="system-ui, sans-serif">!</text>
                </g>
            )}
            {s === 'dead' && (
                <g>
                    <circle cx="98" cy="22" r="11" fill="#6b7280" />
                    <text x="98" y="27" textAnchor="middle" fontSize="14" fontWeight="800" fill="#f3f4f6" fontFamily="system-ui, sans-serif">?</text>
                </g>
            )}
            {s === 'idle' && (
                <g className="claw-zz" fill="#9ca3af" fontFamily="system-ui, sans-serif" fontWeight="800">
                    <text x="92" y="30" fontSize="11">z</text>
                    <text x="100" y="20" fontSize="14">z</text>
                </g>
            )}
        </svg>
    );
}
