import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { fetchAuthAPI } from '@/lib/api';
import DetectionsCard from './DetectionsCard';
import PerformanceCard from './PerformanceCard';
import LearningCard from './LearningCard';

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
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const load = useCallback(async () => {
        setLoading(true);
        setError('');
        try {
            const data = await fetchAuthAPI<AiBainOverview>('/api/admin/mirofish/aibain/overview', token ?? undefined);
            setOverview(data);
        } catch {
            setError('데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.');
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => {
        load();
    }, [load]);

    return (
        <div className="min-h-screen bg-[#09090b] text-white p-4 sm:p-6 lg:p-8">
            <div className="max-w-5xl mx-auto space-y-6">
                <Header />

                {loading && <LoadingState />}

                {!loading && error && <ErrorState error={error} onRetry={load} />}

                {!loading && !error && overview && (
                    <>
                        <DetectionsCard data={overview.detections} />
                        <PerformanceCard data={overview.performance} />
                        <LearningCard data={overview.learning} />
                    </>
                )}
            </div>
        </div>
    );
}

function Header() {
    return (
        <div className="rounded-2xl border border-cyan-500/25 bg-gradient-to-br from-cyan-500/[0.06] via-[#13151f] to-[#1c1c1e] p-6 sm:p-8 relative overflow-hidden">
            <div className="absolute top-0 right-0 w-64 h-64 bg-gradient-to-bl from-cyan-500/10 to-transparent rounded-bl-full pointer-events-none" />
            <div className="relative flex items-start gap-4">
                <div className="grid h-14 w-14 sm:h-16 sm:w-16 shrink-0 place-items-center rounded-2xl bg-cyan-500/15 text-cyan-300 text-3xl">
                    <i className="fas fa-robot" />
                </div>
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <h1 className="text-2xl sm:text-3xl font-black tracking-tight">AI Brain 알파 스캐너</h1>
                        <span className="inline-flex items-center gap-1 rounded-full border border-cyan-400/30 bg-cyan-500/10 px-2 py-0.5 text-[10px] font-black text-cyan-300 uppercase tracking-wider">
                            <i className="fas fa-bolt text-[10px]" />
                            ALPHA SCAN
                        </span>
                    </div>
                    <p className="mt-2 text-sm sm:text-base text-gray-300 leading-relaxed">
                        오늘의 검출, 성과 검증, AI 학습 피드백을 한눈에 확인하세요.
                    </p>
                </div>
            </div>
        </div>
    );
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
