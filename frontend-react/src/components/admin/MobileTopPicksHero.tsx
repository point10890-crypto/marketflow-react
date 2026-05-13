/**
 * MobileTopPicksHero — 모바일 전용 (lg:hidden) 최상단 TOP 3 추천 미리보기.
 *
 * 목적: 모바일에서 페이지 진입 즉시 "오늘 뭐 추천했어?" 에 답한다.
 * 화면 상단에 컴팩트한 TOP 3 카드 + "자세히 ▼" 앵커.
 *
 * 데이터: GET /api/admin/mirofish/workflows/latest (60s 폴링)
 * 표시 조건: workflow.top3.length > 0 인 경우에만 (없으면 null 반환)
 *
 * 데스크탑(lg+)에서는 AlphaBoardPanel 내부의 TOP 3 섹션이 우선 표시.
 */
import { useEffect, useState } from 'react';
import { MiroFishWorkflow, mirofishApi } from '@/lib/mirofishApi';

const POLL_INTERVAL_MS = 60_000;
const ANCHOR_ID = 'alpha-board';

function verdictTone(action?: string): { tone: string; emoji: string } {
    const upper = (action || '').toUpperCase();
    if (upper === 'BUY') return { tone: 'border-emerald-300/30 bg-emerald-300/15 text-emerald-200', emoji: '▲' };
    if (upper === 'SELL') return { tone: 'border-rose-300/30 bg-rose-300/15 text-rose-200', emoji: '▼' };
    return { tone: 'border-amber-300/30 bg-amber-300/15 text-amber-200', emoji: '—' };
}

function outcomeChip(status?: string, hit?: boolean | null): { label: string; tone: string } {
    if (hit === true) return { label: '✅ HIT', tone: 'border-emerald-300/30 bg-emerald-300/10 text-emerald-200' };
    if (hit === false) return { label: '❌ MISS', tone: 'border-rose-300/30 bg-rose-300/10 text-rose-200' };
    if (status === 'pending' || status === 'partial') {
        return { label: '⏳ 진행중', tone: 'border-white/10 bg-white/5 text-neutral-400' };
    }
    return { label: '신규', tone: 'border-amber-400/30 bg-amber-400/10 text-amber-300' };
}

export default function MobileTopPicksHero() {
    const [workflow, setWorkflow] = useState<MiroFishWorkflow | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;
        async function load() {
            try {
                const wf = await mirofishApi.getLatestWorkflow();
                if (cancelled) return;
                setWorkflow(wf);
            } catch {
                // silent — 데스크탑에는 AlphaBoardPanel 이 자체 로딩 처리
            } finally {
                if (!cancelled) setLoading(false);
            }
        }
        load();
        const id = setInterval(load, POLL_INTERVAL_MS);
        return () => {
            cancelled = true;
            clearInterval(id);
        };
    }, []);

    const picks = workflow?.top3 || [];

    // 로딩중이거나 TOP 3 없으면 영역 자체 숨김 (스켈레톤 노이즈 방지)
    if (loading) {
        return (
            <section className="mt-6 rounded-xl border border-amber-400/20 bg-black/60 p-3 lg:hidden">
                <div className="h-4 w-32 animate-pulse rounded bg-white/5" />
                <div className="mt-3 space-y-2">
                    <div className="h-16 animate-pulse rounded-lg bg-white/[0.03]" />
                    <div className="h-16 animate-pulse rounded-lg bg-white/[0.03]" />
                </div>
            </section>
        );
    }

    if (picks.length === 0) {
        return null;
    }

    return (
        <section
            className="mt-6 rounded-xl border border-amber-500/15 bg-black/60 p-3 lg:hidden"
            aria-label="오늘의 TOP 추천 미리보기"
        >
            <header className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                    <div className="flex items-center gap-1.5 text-[10px] font-black uppercase tracking-[0.18em] text-amber-400">
                        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400" />
                        Today&apos;s Top Picks
                    </div>
                    <h2 className="mt-1 text-base font-black text-white">
                        🏆 오늘의 TOP {picks.length} 추천
                    </h2>
                </div>
                <a
                    href={`#${ANCHOR_ID}`}
                    className="shrink-0 rounded-md border border-white/10 bg-black/30 px-2.5 py-1.5 text-[10px] font-black uppercase tracking-wider text-neutral-300 transition-colors active:bg-amber-400/15 active:text-amber-400"
                    title="AlphaBoard 전체 분석 보기"
                >
                    자세히 ▼
                </a>
            </header>

            {workflow?.status && workflow.status !== 'completed' && (
                <div className="mt-2 rounded-md border border-amber-400/20 bg-amber-400/[0.05] px-2 py-1 text-[10px] font-bold leading-snug text-amber-300">
                    ⏳ 워크플로우 상태: {workflow.status} (진행중)
                </div>
            )}

            <div className="mt-3 space-y-2">
                {picks.slice(0, 3).map((item, index) => {
                    const candidate = item.candidate || {};
                    const name = item.target || candidate.display_name || candidate.name || item.symbol || '?';
                    const symbol = item.symbol || candidate.symbol || '';
                    const score = Math.round(Number(item.final_score || 0));
                    const verdict = verdictTone(item.verdict?.action);
                    const confidence = Math.round(Number(item.verdict?.confidence_pct || 0));
                    const outcome = outcomeChip(item.outcome?.status, item.outcome?.hit);
                    const forwardPct = item.outcome?.forward_return_pct;
                    const horizon = item.outcome?.primary_horizon_days;
                    return (
                        <div
                            key={`${symbol}-${item.run_id || index}-${index}`}
                            className="rounded-lg border border-white/10 bg-black/40 p-2.5 active:bg-white/[0.04]"
                        >
                            <div className="flex items-center gap-2">
                                {/* Rank 뱃지 */}
                                <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full border-2 border-amber-400/40 bg-amber-400/15 text-sm font-black text-amber-400">
                                    {index + 1}
                                </div>
                                {/* 종목명 + 코드 */}
                                <div className="min-w-0 flex-1">
                                    <div className="truncate text-sm font-black text-white">{name}</div>
                                    <div className="mt-0.5 flex items-center gap-1.5 text-[10px] font-bold text-neutral-400">
                                        <span className="font-mono tabular-nums">{symbol}</span>
                                        <span className="text-neutral-600">·</span>
                                        <span>score <span className="text-white tabular-nums">{score}</span></span>
                                    </div>
                                </div>
                                {/* Verdict 뱃지 */}
                                <span className={`shrink-0 rounded-full border px-2 py-1 text-[10px] font-black whitespace-nowrap ${verdict.tone}`}>
                                    {verdict.emoji} {item.verdict?.action || 'HOLD'} {confidence}%
                                </span>
                            </div>

                            {/* Outcome / forward return */}
                            <div className="mt-1.5 flex items-center justify-between gap-2 text-[10px] font-bold">
                                <span className={`inline-block rounded-full border px-1.5 py-0.5 ${outcome.tone}`}>
                                    {outcome.label}
                                </span>
                                {forwardPct !== null && forwardPct !== undefined ? (
                                    <span className={`font-mono tabular-nums ${forwardPct >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                                        T{horizon || '?'} {forwardPct >= 0 ? '+' : ''}{Number(forwardPct).toFixed(1)}%
                                    </span>
                                ) : (
                                    <span className="text-neutral-500">평가 대기중</span>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>

            <div className="mt-2 text-center text-[10px] font-bold text-neutral-500 leading-snug">
                컴팩트 미리보기 · 카톡 공유 + 상세 분석은 아래 AlphaBoard 참고
            </div>
        </section>
    );
}
