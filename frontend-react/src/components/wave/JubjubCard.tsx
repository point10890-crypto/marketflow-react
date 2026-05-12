/**
 * 🪣 줍줍이 카드 — W 패턴 + 저점 매수 시그널.
 *
 * 디자인: emerald + amber + glassmorphism + bento + sparkline
 * 2025-2026 트렌드 반영:
 *  - Glassmorphism (backdrop-blur + 반투명 border)
 *  - Bold tabular numerals for prices
 *  - Micro-interaction: hover scale + pulse on '매수 타이밍'
 *  - Progressive disclosure (모바일 첫화면 핵심 + 확장)
 *  - Sparkline mini W 패턴 시각화
 */
import { useState } from 'react';
import { JubjubCandidate, JubjubBadgeTone } from '@/lib/jubjubApi';

function formatNumber(n: number): string {
    return n.toLocaleString('ko-KR');
}

function formatPct(n: number | null): string {
    if (n === null || n === undefined) return '--';
    const sign = n >= 0 ? '+' : '';
    return `${sign}${n.toFixed(2)}%`;
}

function toneStyles(tone: JubjubBadgeTone): { border: string; bg: string; text: string } {
    switch (tone) {
        case 'amber':
            return {
                border: 'border-amber-300/40',
                bg: 'bg-amber-300/15',
                text: 'text-amber-200',
            };
        case 'rose':
            return {
                border: 'border-rose-300/40',
                bg: 'bg-rose-300/15',
                text: 'text-rose-200',
            };
        case 'emerald':
            return {
                border: 'border-emerald-300/30',
                bg: 'bg-emerald-300/10',
                text: 'text-emerald-200',
            };
        case 'slate':
        default:
            return {
                border: 'border-slate-300/20',
                bg: 'bg-slate-300/5',
                text: 'text-slate-300',
            };
    }
}

function Stars({ count }: { count: number }) {
    const stars = '⭐'.repeat(Math.max(0, Math.min(3, count)));
    if (!stars) return null;
    return <span className="text-amber-300 text-xs">{stars}</span>;
}

/** 매수→1차→2차 + 손절 막대 시각화 */
function TradePlanBar({ candidate }: { candidate: JubjubCandidate }) {
    const tp = candidate.trade_plan;
    const current = candidate.current_price;
    // 가격 범위: stop 보다 5% 아래 ~ target_2 보다 2% 위
    const minP = Math.min(tp.stop_price, current) * 0.95;
    const maxP = Math.max(tp.target_2, current) * 1.02;
    const range = maxP - minP;
    const pos = (p: number) => Math.max(0, Math.min(100, ((p - minP) / range) * 100));

    return (
        <div className="space-y-1.5">
            {/* 바 */}
            <div className="relative h-7">
                {/* 배경 그라데이션: 손절(rose) → 현재가 → 목표(emerald) */}
                <div className="absolute inset-0 rounded-full bg-gradient-to-r from-rose-500/20 via-slate-700/30 to-emerald-500/20" />
                {/* 손절 마커 */}
                <div
                    className="absolute top-0 h-7 w-0.5 bg-rose-400"
                    style={{ left: `${pos(tp.stop_price)}%` }}
                    title={`손절 ${formatNumber(tp.stop_price)}`}
                />
                {/* 현재가 마커 */}
                <div
                    className="absolute top-0 h-7 w-0.5 bg-cyan-300"
                    style={{ left: `${pos(current)}%` }}
                    title={`현재 ${formatNumber(current)}`}
                />
                {/* 매수가 마커 (강조) */}
                <div
                    className="absolute top-0 h-7 w-1 bg-amber-300 rounded-full ring-2 ring-amber-300/30"
                    style={{ left: `${pos(tp.entry_price)}%` }}
                    title={`매수 ${formatNumber(tp.entry_price)}`}
                />
                {/* 1차 목표 */}
                <div
                    className="absolute top-0 h-7 w-0.5 bg-emerald-400"
                    style={{ left: `${pos(tp.target_1)}%` }}
                    title={`1차 ${formatNumber(tp.target_1)}`}
                />
                {/* 2차 목표 */}
                <div
                    className="absolute top-0 h-7 w-0.5 bg-emerald-400"
                    style={{ left: `${pos(tp.target_2)}%` }}
                    title={`2차 ${formatNumber(tp.target_2)}`}
                />
            </div>
            {/* 범례 */}
            <div className="flex justify-between text-[9px] font-bold tabular-nums">
                <span className="text-rose-300">{formatNumber(tp.stop_price)}</span>
                <span className="text-amber-300">{formatNumber(tp.entry_price)}</span>
                <span className="text-emerald-300">{formatNumber(tp.target_2)}</span>
            </div>
        </div>
    );
}

/** W 패턴 mini SVG (sparkline) */
function MiniWChart({ candidate }: { candidate: JubjubCandidate }) {
    // 간단한 W 패턴 시각화 (실제 OHLCV 없이 추정)
    // 신뢰도 따라 패턴 강도 표현
    const conf = candidate.confidence;
    const stroke = conf >= 80 ? '#10B981' : conf >= 70 ? '#34D399' : '#6EE7B7';
    return (
        <svg viewBox="0 0 100 30" className="w-full h-7 opacity-80" aria-hidden>
            <defs>
                <linearGradient id={`wg-${candidate.ticker}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={stroke} stopOpacity="0.3" />
                    <stop offset="100%" stopColor={stroke} stopOpacity="0" />
                </linearGradient>
            </defs>
            {/* W shape: 시작 ↓ 첫 저점 ↑ 중봉 ↓ 두 번째 저점 ↑ 끝 (넥라인) */}
            <path
                d="M 5 8 L 22 24 L 40 14 L 58 22 L 75 6 L 95 4"
                fill="none"
                stroke={stroke}
                strokeWidth="1.5"
                strokeLinejoin="round"
                strokeLinecap="round"
            />
            {/* 넥라인 (수평 점선) */}
            <line x1="5" y1="8" x2="95" y2="8" stroke={stroke} strokeWidth="0.5" strokeDasharray="2 2" opacity="0.5" />
            {/* 매수 진입 포인트 */}
            <circle cx="95" cy="4" r="2" fill="#FCD34D" />
        </svg>
    );
}

interface JubjubCardProps {
    candidate: JubjubCandidate;
    onShare?: (c: JubjubCandidate) => void;
    onChart?: (c: JubjubCandidate) => void;
}

export default function JubjubCard({ candidate, onShare, onChart }: JubjubCardProps) {
    const [expanded, setExpanded] = useState(false);
    const tone = toneStyles(candidate.jubjub_badge_tone);
    const isBuyNow = candidate.jubjub_badge === 'buy_now';
    const isElite = candidate.jubjub_stars === 3;

    return (
        <article
            className={`group relative overflow-hidden rounded-2xl border bg-slate-950/60 p-3 backdrop-blur-md transition-all hover:scale-[1.01] sm:p-4 ${
                isElite ? 'border-amber-300/40 shadow-[0_8px_40px_rgba(252,211,77,0.10)]' :
                isBuyNow ? 'border-rose-300/40 shadow-[0_8px_40px_rgba(244,114,182,0.10)]' :
                'border-emerald-300/15 shadow-[0_8px_40px_rgba(16,185,129,0.06)]'
            }`}
        >
            {/* glassmorphism background tint */}
            <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-emerald-500/[0.03] to-transparent" aria-hidden />

            <div className="relative">
                {/* 헤더 — 점수 + 종목 + 뱃지 */}
                <header className="flex items-start justify-between gap-2">
                    <div className="flex items-baseline gap-2 min-w-0">
                        <span className="text-2xl sm:text-3xl font-black text-amber-300 tabular-nums leading-none">
                            {Math.round(candidate.jubjub_score)}
                        </span>
                        <span className="text-[10px] font-bold text-amber-300/60 leading-none">/100</span>
                        <Stars count={candidate.jubjub_stars} />
                    </div>
                    <span
                        className={`shrink-0 inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-black whitespace-nowrap ${tone.border} ${tone.bg} ${tone.text} ${
                            isBuyNow ? 'animate-pulse' : ''
                        }`}
                    >
                        {candidate.jubjub_badge_label_ko}
                    </span>
                </header>

                {/* 종목명 */}
                <div className="mt-2 flex items-baseline justify-between gap-2">
                    <div className="min-w-0">
                        <h3 className="truncate text-base font-black text-white sm:text-lg">
                            {candidate.name}
                        </h3>
                        <p className="mt-0.5 text-[10px] font-bold text-slate-500 tabular-nums">
                            🪣 {candidate.ticker} · {candidate.wave_label || '역헤드앤숄더'} · 신뢰 {Math.round(candidate.confidence)}
                        </p>
                    </div>
                    <div className="shrink-0 text-right">
                        <div className="text-sm font-black text-cyan-200 tabular-nums sm:text-base">
                            {formatNumber(candidate.current_price)}
                        </div>
                        <div className="text-[10px] font-bold text-slate-500">현재가</div>
                    </div>
                </div>

                {/* W 미니 차트 */}
                <div className="mt-2">
                    <MiniWChart candidate={candidate} />
                </div>

                {/* 매매 계획 — 컴팩트 표 */}
                <div className="mt-3 rounded-xl border border-white/5 bg-black/30 p-2.5">
                    <div className="text-[9px] font-black uppercase tracking-wider text-slate-500 mb-1.5">
                        매매 계획
                    </div>
                    <div className="grid grid-cols-4 gap-1.5 text-center text-[10px] font-bold">
                        <div>
                            <div className="text-rose-300/70">손절</div>
                            <div className="mt-0.5 font-mono tabular-nums text-rose-200">
                                {formatNumber(candidate.trade_plan.stop_price)}
                            </div>
                            <div className="mt-0.5 text-rose-300/60 tabular-nums">
                                {formatPct(candidate.trade_plan.stop_pct)}
                            </div>
                        </div>
                        <div className="rounded bg-amber-300/[0.06] -mx-0.5 px-0.5">
                            <div className="text-amber-300">매수</div>
                            <div className="mt-0.5 font-mono tabular-nums text-amber-200 font-black">
                                {formatNumber(candidate.trade_plan.entry_price)}
                            </div>
                            <div className="mt-0.5 text-amber-300/70 tabular-nums">
                                {formatPct(candidate.trade_plan.entry_pct)}
                            </div>
                        </div>
                        <div>
                            <div className="text-emerald-300/80">1차</div>
                            <div className="mt-0.5 font-mono tabular-nums text-emerald-200">
                                {formatNumber(candidate.trade_plan.target_1)}
                            </div>
                            <div className="mt-0.5 text-emerald-300/60 tabular-nums">
                                {formatPct(candidate.trade_plan.target_1_pct)}
                            </div>
                        </div>
                        <div>
                            <div className="text-emerald-300/80">2차</div>
                            <div className="mt-0.5 font-mono tabular-nums text-emerald-200">
                                {formatNumber(candidate.trade_plan.target_2)}
                            </div>
                            <div className="mt-0.5 text-emerald-300/60 tabular-nums">
                                {formatPct(candidate.trade_plan.target_2_pct)}
                            </div>
                        </div>
                    </div>
                    {/* R/R */}
                    <div className="mt-2 flex items-center justify-between text-[9px] font-bold">
                        <span className="text-slate-500">R/R</span>
                        <span className="tabular-nums">
                            <span className={`${(candidate.trade_plan.rr_1 || 0) >= 1.5 ? 'text-emerald-300' : 'text-amber-300'}`}>
                                1차 {candidate.trade_plan.rr_1 ?? '--'}x
                            </span>
                            <span className="mx-1 text-slate-600">·</span>
                            <span className={`${(candidate.trade_plan.rr_2 || 0) >= 2 ? 'text-emerald-300' : 'text-amber-300'}`}>
                                2차 {candidate.trade_plan.rr_2 ?? '--'}x
                            </span>
                        </span>
                    </div>
                </div>

                {/* 매매 가격 막대 시각화 */}
                <div className="mt-3">
                    <TradePlanBar candidate={candidate} />
                </div>

                {/* 확인 사항 + 액션 */}
                <div className="mt-3 flex items-center justify-between gap-2">
                    <div className="flex flex-wrap gap-1.5 text-[9px] font-bold">
                        {candidate.volume_confirmed && (
                            <span className="rounded-full bg-emerald-300/10 px-1.5 py-0.5 text-emerald-300">✓ 거래량</span>
                        )}
                        <span className="rounded-full bg-cyan-300/10 px-1.5 py-0.5 text-cyan-300 tabular-nums">
                            넥라인 {formatPct(candidate.neckline_distance_pct)}
                        </span>
                        <span className="rounded-full bg-violet-300/10 px-1.5 py-0.5 text-violet-300 tabular-nums">
                            완성 {Math.round(candidate.completion_pct)}%
                        </span>
                    </div>
                    <div className="flex gap-1 shrink-0">
                        {onChart && (
                            <button
                                type="button"
                                onClick={() => onChart(candidate)}
                                className="grid h-7 w-7 place-items-center rounded-lg border border-white/10 bg-black/30 text-cyan-300 transition-colors hover:border-cyan-300/40 hover:bg-cyan-300/[0.08] active:bg-cyan-300/[0.12]"
                                title="차트"
                            >
                                📊
                            </button>
                        )}
                        {onShare && (
                            <button
                                type="button"
                                onClick={() => onShare(candidate)}
                                className="grid h-7 w-7 place-items-center rounded-lg border border-white/10 bg-black/30 text-amber-300 transition-colors hover:border-amber-300/40 hover:bg-amber-300/[0.08] active:bg-amber-300/[0.12]"
                                title="카톡 공유"
                            >
                                📤
                            </button>
                        )}
                        <button
                            type="button"
                            onClick={() => setExpanded((v) => !v)}
                            className="grid h-7 w-7 place-items-center rounded-lg border border-white/10 bg-black/30 text-slate-300 transition-colors hover:border-slate-300/40"
                            title={expanded ? '접기' : '점수 분해'}
                        >
                            {expanded ? '▲' : '▼'}
                        </button>
                    </div>
                </div>

                {/* 확장: 점수 분해 */}
                {expanded && (
                    <div className="mt-3 rounded-xl border border-white/5 bg-black/40 p-2.5 space-y-1 text-[10px] font-bold">
                        <div className="text-slate-500 font-black uppercase tracking-wider mb-1">점수 분해</div>
                        {[
                            ['신뢰도 (40%)', candidate.score_breakdown.confidence, 40],
                            ['완성도 (20%)', candidate.score_breakdown.completion, 20],
                            ['넥라인 근접 (20%)', candidate.score_breakdown.proximity, 20],
                            ['거래량 (10%)', candidate.score_breakdown.volume, 10],
                            ['Bullish bias (10%)', candidate.score_breakdown.bias, 10],
                        ].map(([label, value, max]) => {
                            const pct = ((value as number) / (max as number)) * 100;
                            return (
                                <div key={label as string} className="flex items-center gap-2">
                                    <span className="w-28 shrink-0 text-slate-400 truncate">{label}</span>
                                    <div className="flex-1 overflow-hidden rounded-full bg-white/5">
                                        <div
                                            className="h-1.5 rounded-full bg-gradient-to-r from-emerald-400 to-amber-300"
                                            style={{ width: `${Math.max(2, Math.min(100, pct))}%` }}
                                        />
                                    </div>
                                    <span className="w-12 shrink-0 text-right tabular-nums text-white">
                                        {(value as number).toFixed(1)}
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </article>
    );
}
