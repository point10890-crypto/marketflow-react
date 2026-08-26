import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { fetchAuthAPI } from '@/lib/api';
import DetectionsCard from './DetectionsCard';
import PerformanceCard from './PerformanceCard';
import PaperTradingCard, { PaperOverview } from './PaperTradingCard';
import ClawLiveCard from './ClawLiveCard';
import CloseLeadersCard from './CloseLeadersCard';
import AlphaCoreOpsCard from './AlphaCoreOpsCard';

interface AiBainOverview {
    generated_at: string;
    detections: {
        as_of: string | null;
        items: {
            symbol: string | null;
            name: string | null;
            action: string | null;
            alpha_score: number | null;
            risk_score: number | null;
            rs_rating: number | null;
            entry_date: string | null;
            tradingagents?: { verdict: string | null; confidence: number | null; strong_buy: boolean | null } | null;
        }[];
    };
    performance: {
        window_days: number;
        hit_rate_pct: number | null;
        avg_forward_return_pct: number | null;
        false_positive_pct: number | null;
        evaluated_count: number;
        verified: {
            symbol: string | null;
            name: string | null;
            entry_date: string | null;
            forward_return_pct: number | null;
            hit: boolean | null;
            status: string;
        }[];
    };
    learning: {
        regime_distribution: Record<string, number>;
        top_positive: { combo: string; n: number; hit_rate: number; expectancy_pct: number }[];
        top_negative: { combo: string; n: number; hit_rate: number; expectancy_pct: number }[];
        updated_at: string | null;
    };
}

export default function AiBainDashboard() {
    const { token } = useAuth();
    const [overview, setOverview] = useState<AiBainOverview | null>(null);
    const [paper, setPaper] = useState<PaperOverview | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showDetail, setShowDetail] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        setError('');
        try {
            // 두 뷰는 독립 — 한쪽 실패가 다른 쪽을 가리지 않게 개별 수집
            const [ov, pa] = await Promise.allSettled([
                fetchAuthAPI<AiBainOverview>('/api/admin/mirofish/aibain/overview', token ?? undefined),
                fetchAuthAPI<PaperOverview>('/api/admin/mirofish/paper/overview', token ?? undefined),
            ]);
            if (ov.status === 'fulfilled') setOverview(ov.value);
            if (pa.status === 'fulfilled') setPaper(pa.value);
            if (ov.status !== 'fulfilled' && pa.status !== 'fulfilled') {
                setError('데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.');
            }
        } catch {
            setError('데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.');
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => {
        load();
    }, [load]);

    const learningPattern = overview?.learning?.top_positive?.[0]?.combo ?? null;

    return (
        <div className="min-h-full bg-[#09090b] text-white p-4 sm:p-6 lg:p-8">
            <div className="max-w-3xl mx-auto space-y-5">
                <Header
                    hitRatePct={overview?.performance?.hit_rate_pct ?? null}
                    windowDays={overview?.performance?.window_days ?? 30}
                    asOf={overview?.detections?.as_of ?? null}
                    live={!loading && !error}
                />

                {/* AlphaClaw v1.1 — GET 전용 관측·페이퍼 운영면. 주문/승인 액션은 의도적으로 없다. */}
                <AlphaCoreOpsCard />

                {loading && <LoadingState />}

                {!loading && error && <ErrorState error={error} onRetry={load} />}

                {!loading && !error && (
                    <>
                        {/* 핵심: 가상 매매 시그널 (국면·보유·성과) — 사용자가 매일 보는 것 */}
                        {paper && <PaperTradingCard data={paper} />}

                        {/* Claw LIVE — 장중 주도주 전이 감시 (자체 폴링, 기존 엔드포인트와 독립) */}
                        <ClawLiveCard />

                        {/* 마감 주도주 — 마감 기준 세션 확정본 (마스터 플랜 P3) */}
                        <CloseLeadersCard />

                        {/* 검출 Top3 */}
                        {overview && <DetectionsCard data={overview.detections} />}

                        {/* 상세 분석(검증·학습)은 접힘 — 필요한 사람만 펼쳐본다 */}
                        {overview && (
                            <div>
                                <button
                                    type="button"
                                    onClick={() => setShowDetail(v => !v)}
                                    className="flex w-full items-center justify-between rounded-xl border border-white/[0.06] bg-white/[0.02] px-4 py-3 text-[12px] font-bold text-gray-500 transition-colors hover:text-gray-300"
                                >
                                    <span><i className="fas fa-flask mr-2 text-[10px]" />상세 분석 (검증 표본 · 학습 패턴)</span>
                                    <i className={`fas fa-chevron-${showDetail ? 'up' : 'down'} text-[10px]`} />
                                </button>
                                {showDetail && (
                                    <div className="mt-3">
                                        <PerformanceCard data={overview.performance} learningPattern={learningPattern} />
                                    </div>
                                )}
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}

function Header({
    hitRatePct,
    windowDays,
    asOf,
    live,
}: {
    hitRatePct: number | null;
    windowDays: number;
    asOf: string | null;
    live: boolean;
}) {
    return (
        <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2.5 min-w-0">
                <span className="relative grid place-items-center h-2.5 w-2.5">
                    <span className={`absolute inline-flex h-2.5 w-2.5 rounded-full ${live ? 'bg-cyan-400/60 animate-ping' : ''}`} />
                    <span className={`relative inline-flex h-2 w-2 rounded-full ${live ? 'bg-cyan-400' : 'bg-gray-600'}`} />
                </span>
                <h1 className="text-xl sm:text-2xl font-black tracking-tight">AI Brain</h1>
                {asOf && <span className="text-[11px] text-gray-500">{`마지막 검출 ${fmtDate(asOf)}`}</span>}
            </div>
            {hitRatePct != null && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-cyan-400/25 bg-cyan-500/10 px-3 py-1 text-xs font-bold text-cyan-300">
                    <i className="fas fa-bullseye text-[10px]" />
                    {`최근 ${windowDays}일 적중률 ${hitRatePct}%`}
                </span>
            )}
        </div>
    );
}

function fmtDate(iso: string): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 16).replace('T', ' ');
    return d.toLocaleString('ko-KR', {
        timeZone: 'Asia/Seoul',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    });
}

function LoadingState() {
    return (
        <div className="rounded-2xl border border-cyan-400/15 bg-[#13151f] p-10 flex items-center justify-center">
            <div className="text-center">
                <i className="fas fa-spinner fa-spin text-cyan-400 text-2xl mb-3" />
                <p className="text-sm text-gray-400">데이터를 불러오는 중...</p>
            </div>
        </div>
    );
}

function ErrorState({ error, onRetry }: { error: string; onRetry: () => void }) {
    return (
        <div className="rounded-2xl border border-red-500/20 bg-red-500/5 p-6 text-center">
            <p className="text-sm text-red-300 mb-4">{error}</p>
            <button
                type="button"
                onClick={onRetry}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-white/10 bg-white/5 text-gray-300 font-medium text-xs hover:bg-white/10 transition-all"
            >
                <i className="fas fa-rotate-right" />
                다시 시도
            </button>
        </div>
    );
}
