import { useEffect, useMemo, useState } from 'react';
import {
    mirofishApi,
    type MiroFishAlphaCandidate,
    type MiroFishFearIndex,
    type MiroFishWorkflowAnalysisResult,
} from '@/lib/mirofishApi';

type Variant = 'default' | 'compact';

interface MiroFishFearIndexCardProps {
    className?: string;
    variant?: Variant;
    href?: string;
    candidates?: MiroFishAlphaCandidate[];
    candidatesLoading?: boolean;
    topResults?: MiroFishWorkflowAnalysisResult[];
    topResultsLoading?: boolean;
}

const actionLabels: Record<string, string> = {
    BUY: '매수',
    BUY_CANDIDATE: '매수 후보',
    WATCH: '관망',
    HOLD: '보유',
    SELL: '매도',
    SELL_CANDIDATE: '매도 후보',
    AVOID: '제외',
};

function actionLabel(action?: string) {
    const normalized = String(action || 'WATCH').toUpperCase();
    return actionLabels[normalized] || normalized.split('_').join(' ');
}

function actionTone(action?: string) {
    const normalized = String(action || '').toUpperCase();
    if (normalized.includes('BUY')) return 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100';
    if (normalized.includes('SELL') || normalized === 'AVOID') return 'border-rose-300/25 bg-rose-300/10 text-rose-100';
    return 'border-cyan-300/25 bg-cyan-300/10 text-cyan-100';
}

function formatPrice(value?: number | string) {
    if (value === undefined || value === null || value === '') return '--';
    const numeric = typeof value === 'number' ? value : Number(String(value).split(',').join(''));
    return Number.isFinite(numeric) ? Math.round(numeric).toLocaleString('ko-KR') : String(value);
}

function toneColor(tone?: string | null) {
    if (tone === 'danger') return 'text-rose-300';
    if (tone === 'warning') return 'text-amber-300';
    if (tone === 'calm') return 'text-emerald-300';
    if (tone === 'risk') return 'text-sky-300';
    return 'text-slate-200';
}

function toneBorder(tone?: string | null) {
    if (tone === 'danger') return 'border-rose-300/30 bg-rose-500/[0.07]';
    if (tone === 'warning') return 'border-amber-300/30 bg-amber-500/[0.07]';
    if (tone === 'calm') return 'border-emerald-300/25 bg-emerald-500/[0.06]';
    if (tone === 'risk') return 'border-sky-300/25 bg-sky-500/[0.06]';
    return 'border-cyan-300/20 bg-cyan-500/[0.05]';
}

function formatTime(value?: string | null) {
    if (!value) return '--';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '--';
    return date.toLocaleString('ko-KR', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
}

function topResultIdentity(result: MiroFishWorkflowAnalysisResult) {
    const candidate = result.candidate || {};
    const symbol = String(result.verdict?.symbol || result.symbol || candidate.symbol || '').trim();
    return {
        symbol,
        market: String(result.verdict?.market || result.market || candidate.market || 'KR').trim(),
        name: String(result.verdict?.target_display || result.target || candidate.display_name || candidate.name || symbol || 'Unknown').trim(),
    };
}

export default function MiroFishFearIndexCard({
    className = '',
    variant = 'default',
    href = '/dashboard/ai-bain',
    candidates,
    candidatesLoading = false,
    topResults = [],
    topResultsLoading = false,
}: MiroFishFearIndexCardProps) {
    const [data, setData] = useState<MiroFishFearIndex | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [fetchedCandidates, setFetchedCandidates] = useState<MiroFishAlphaCandidate[]>([]);
    const hasProvidedCandidates = (candidates?.length ?? 0) > 0;
    const [scannerLoading, setScannerLoading] = useState(!hasProvidedCandidates);

    useEffect(() => {
        let active = true;
        setLoading(true);
        setError('');
        mirofishApi.getFearIndex()
            .then((snapshot) => {
                if (!active) return;
                setData(snapshot);
                if ((snapshot.scanner_top_candidates?.length ?? 0) > 0) {
                    setFetchedCandidates(snapshot.scanner_top_candidates || []);
                }
            })
            .catch((err) => {
                if (!active) return;
                const message = err instanceof Error ? err.message : String(err);
                setError(message.includes('401') || message.includes('403') ? 'AI Brain 또는 관리자 권한 필요' : '공포지수 연결 대기');
            })
            .finally(() => {
                if (active) setLoading(false);
            });
        return () => {
            active = false;
        };
    }, []);

    useEffect(() => {
        if (hasProvidedCandidates) {
            setScannerLoading(false);
            return;
        }

        let active = true;
        setScannerLoading(true);
        mirofishApi.getLatestScannerCandidates(5)
            .then((payload) => {
                if (active) setFetchedCandidates(payload.candidates || []);
            })
            .catch(() => {
                if (active) setFetchedCandidates([]);
            })
            .finally(() => {
                if (active) setScannerLoading(false);
            });

        return () => {
            active = false;
        };
    }, [hasProvidedCandidates]);

    const score = typeof data?.score === 'number' ? Math.round(data.score) : null;
    const level = data?.level_label || data?.level || (loading ? '불러오는 중' : '확인 필요');
    const summary = data?.summary || error || 'VIX, Fear & Greed, 환율, 지수 압력을 묶어 Top3 신뢰도 보정에 사용합니다.';
    const driver = data?.dashboard?.primary_driver || data?.dashboard?.primary_detail || 'market stress';
    const coverage = typeof data?.coverage_pct === 'number' ? `${data.coverage_pct.toFixed(0)}%` : '--';
    const componentCount = useMemo(() => data?.components?.filter((item) => item.status === 'ok').length ?? 0, [data]);
    const topCandidates = useMemo(
        () => [...(hasProvidedCandidates ? (candidates ?? []) : fetchedCandidates)].sort((left, right) => left.rank - right.rank).slice(0, 5),
        [candidates, fetchedCandidates, hasProvidedCandidates],
    );
    const isCandidatesLoading = candidatesLoading || scannerLoading;
    const displayedTopResults = topResults.slice(0, 3);
    const compact = variant === 'compact';

    return (
        <a
            href={href}
            aria-label="AI Brain 세션으로 이동"
            data-testid="mirofish-fear-index-card"
            className={`group block relative overflow-hidden rounded-2xl border ${toneBorder(data?.tone)} p-4 ${compact ? 'sm:p-4' : 'sm:p-5'} ${className} cursor-pointer transition hover:-translate-y-0.5 hover:border-cyan-200/45 hover:shadow-[0_18px_70px_rgba(34,211,238,0.14)] focus:outline-none focus:ring-2 focus:ring-cyan-300/45`}
        >
            <div className="absolute -right-10 -top-10 h-28 w-28 rounded-full bg-cyan-300/10 blur-3xl" />
            <div className="relative flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-black/25 text-cyan-200">
                            <i className="fas fa-heart-pulse text-sm" />
                        </span>
                        <div>
                            <div className="text-[10px] font-black uppercase tracking-[0.22em] text-cyan-200/75">
                                MiroFish Risk Context
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                                <h3 className="text-base font-black text-white sm:text-lg">MiroFish 공포지수</h3>
                                <span className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-2 py-0.5 text-[10px] font-black text-cyan-100 opacity-80 transition group-hover:opacity-100">
                                    AI Brain 열기
                                </span>
                            </div>
                        </div>
                    </div>
                    <p className="mt-3 max-w-3xl text-xs font-semibold leading-5 text-slate-300 sm:text-sm">
                        {summary}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2 text-[11px] font-black">
                        <span className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-slate-300">
                            coverage {coverage}
                        </span>
                        <span className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-slate-300">
                            sources {componentCount || '--'}
                        </span>
                        <span className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-slate-300">
                            {formatTime(data?.generated_at)}
                        </span>
                    </div>
                </div>
                <div className="flex shrink-0 items-center gap-3 sm:min-w-[230px] sm:justify-end">
                    <div className="text-right">
                        <div className="text-[10px] font-black uppercase tracking-[0.18em] text-slate-500">Fear Score</div>
                        <div className={`mt-1 text-4xl font-black tabular-nums ${toneColor(data?.tone)}`}>
                            {loading ? '--' : score ?? '--'}
                        </div>
                        <div className="mt-1 text-xs font-black text-slate-400">{level}</div>
                    </div>
                    <div className="h-20 w-2 overflow-hidden rounded-full bg-white/10">
                        <div
                            className="w-full rounded-full bg-gradient-to-t from-emerald-300 via-amber-300 to-rose-400 transition-all"
                            style={{ height: `${Math.max(8, Math.min(100, score ?? 0))}%`, marginTop: `${100 - Math.max(8, Math.min(100, score ?? 0))}%` }}
                        />
                    </div>
                </div>
            </div>
            <div className="relative mt-4 flex items-center justify-between rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-[11px] font-bold text-slate-400">
                <span>Top3 confidence cap input</span>
                <span className="flex min-w-0 items-center gap-2 pl-3 text-right text-cyan-100">
                    <span className="truncate">{driver}</span>
                    <i className="fas fa-arrow-right text-[10px] opacity-60 transition group-hover:translate-x-0.5 group-hover:opacity-100" />
                </span>
            </div>
            <div className="relative mt-3 overflow-hidden rounded-xl border border-white/10 bg-black/20" data-testid="fear-index-top-candidates">
                <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
                    <span className="text-[10px] font-black uppercase tracking-[0.18em] text-slate-500">Alpha Scanner Top 5</span>
                    <span className="text-[10px] font-black text-cyan-100/80">최신 검출 종목</span>
                </div>
                {topCandidates.length > 0 ? (
                    <ol className="divide-y divide-white/[0.07]">
                        {topCandidates.map((candidate, index) => (
                            <li key={`${candidate.symbol}-${candidate.rank}`} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2.5 px-3 py-2.5 transition group-hover:bg-white/[0.015] sm:gap-3">
                                <span className="w-5 text-center font-mono text-[11px] font-black text-emerald-200">#{index + 1}</span>
                                <span className="min-w-0">
                                    <span className="block truncate text-xs font-black text-white sm:text-[13px]">
                                        {candidate.display_name || candidate.name || candidate.symbol}
                                    </span>
                                    <span className="mt-0.5 block truncate font-mono text-[9px] font-bold text-slate-500 sm:text-[10px]">
                                        {candidate.symbol} · {candidate.market || 'KR'} · A {Math.round(candidate.alpha_score)} / R {Math.round(candidate.risk_score)}
                                    </span>
                                </span>
                                <span className="flex min-w-[76px] flex-col items-end gap-1">
                                    <span className={`rounded-full border px-2 py-0.5 text-[9px] font-black ${actionTone(candidate.action)}`}>
                                        {actionLabel(candidate.action)}
                                    </span>
                                    <span className="font-mono text-[10px] font-black tabular-nums text-slate-300">
                                        {candidate.price === undefined || candidate.price === null || candidate.price === '' ? '--' : `${formatPrice(candidate.price)}원`}
                                    </span>
                                </span>
                            </li>
                        ))}
                    </ol>
                ) : (
                    <div className="px-3 py-5 text-center text-[11px] font-bold text-slate-500">
                        {isCandidatesLoading ? '최신 검출 종목을 불러오는 중입니다.' : '표시할 최신 검출 종목이 없습니다.'}
                    </div>
                )}
            </div>
            <div className="relative mt-3 overflow-hidden rounded-xl border border-amber-300/15 bg-amber-300/[0.035]" data-testid="fear-index-top-results">
                <div className="flex items-center justify-between border-b border-amber-300/10 px-3 py-2">
                    <span className="text-[10px] font-black uppercase tracking-[0.18em] text-amber-200/70">MCP Verified Top 3</span>
                    <span className="text-[10px] font-black text-amber-100/75">최종 분석 결과</span>
                </div>
                {displayedTopResults.length > 0 ? (
                    <div className="grid gap-2 p-2 sm:grid-cols-3">
                        {displayedTopResults.map((result, index) => {
                            const identity = topResultIdentity(result);
                            const action = String(result.verdict?.action || 'HOLD').toUpperCase();
                            const confidence = Math.round(Number(result.verdict?.confidence_pct || 0));
                            const scoreValue = Math.round(Number(result.final_score || 0));
                            const referenceDate = String(result.verdict?.reference_date || '').slice(0, 10);
                            const outcomeStatus = String(result.outcome_status || result.outcome?.status || 'pending').toUpperCase();
                            return (
                                <article key={`${identity.symbol}-${result.run_id || index}`} className="min-w-0 rounded-lg border border-white/10 bg-[#24231f]/85 p-2.5 shadow-[0_8px_24px_rgba(0,0,0,0.16)]">
                                    <div className="text-[9px] font-black uppercase tracking-[0.14em] text-orange-300">Top {index + 1}</div>
                                    <div className="mt-1 truncate text-[12px] font-black text-white" title={identity.name}>
                                        {identity.name}
                                    </div>
                                    <div className="mt-1 truncate font-mono text-[9px] font-bold text-slate-500">
                                        {identity.symbol || '--'} · {identity.market} · score {scoreValue}
                                    </div>
                                    {referenceDate && (
                                        <div className="mt-0.5 font-mono text-[9px] font-bold text-slate-600">ref {referenceDate}</div>
                                    )}
                                    <div className="mt-2 flex flex-wrap items-center gap-1">
                                        <span className={`rounded-full border px-2 py-0.5 text-[9px] font-black ${actionTone(action)}`}>
                                            {action} {confidence}%
                                        </span>
                                        <span className="rounded border border-amber-300/15 bg-amber-300/[0.06] px-1.5 py-0.5 font-mono text-[8px] font-black text-amber-200/80">
                                            L {result.graphrag?.links ?? 0}
                                        </span>
                                        <span className="rounded border border-amber-300/15 bg-amber-300/[0.06] px-1.5 py-0.5 font-mono text-[8px] font-black text-amber-200/80">
                                            E {result.graphrag?.entities ?? 0}
                                        </span>
                                        <span className="rounded border border-amber-300/15 bg-amber-300/[0.06] px-1.5 py-0.5 font-mono text-[8px] font-black text-amber-200/80">
                                            R {result.graphrag?.relations ?? 0}
                                        </span>
                                    </div>
                                    <div className="mt-2 inline-flex rounded-full border border-amber-300/25 bg-amber-300/[0.05] px-2 py-0.5 text-[8px] font-black text-amber-100/80">
                                        {outcomeStatus}
                                    </div>
                                    {referenceDate && (
                                        <div className="mt-2 truncate text-[8px] font-black uppercase tracking-[0.08em] text-slate-600">
                                            Replay-safe after {referenceDate}
                                        </div>
                                    )}
                                </article>
                            );
                        })}
                    </div>
                ) : (
                    <div className="px-3 py-5 text-center text-[11px] font-bold text-slate-500">
                        {topResultsLoading ? '최종 Top 3 분석 결과를 불러오는 중입니다.' : '표시할 최종 Top 3 결과가 없습니다.'}
                    </div>
                )}
            </div>
        </a>
    );
}
