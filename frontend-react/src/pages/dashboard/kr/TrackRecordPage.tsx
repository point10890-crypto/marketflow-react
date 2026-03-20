
import { useEffect, useState, useCallback } from 'react';
import { usePullToRefreshRegister } from '@/components/layout/PullToRefreshProvider';
import { jonggaAPI } from '@/lib/api';

// Backend response shape
interface DayEntry {
    date: string;
    total_signals: number;
    by_grade: { S?: number; A?: number; B?: number; C?: number };
    top_signal: {
        stock_name: string;
        stock_code: string;
        grade: string;
        change_pct: number;
        score: number;
    } | null;
}

interface PerfData {
    days_count: number;
    total_signals: number;
    grade_totals: { S?: number; A?: number; B?: number; C?: number };
    history: DayEntry[];
}

// ── Grade Badge ────────────────────────────────────────────────────────────────

const GRADE_STYLE: Record<string, string> = {
    S: 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30',
    A: 'bg-blue-500/20 text-blue-400 border border-blue-500/30',
    B: 'bg-gray-500/20 text-gray-400 border border-gray-500/30',
    C: 'bg-red-500/20 text-red-400 border border-red-500/30',
};

function GradeBadge({ grade }: { grade: string }) {
    return (
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${GRADE_STYLE[grade] ?? GRADE_STYLE['C']}`}>
            {grade}
        </span>
    );
}

// ── Summary Stat Card ─────────────────────────────────────────────────────────

function StatCard({ label, value, sub, accent }: { label: string; value: string | number; sub?: string; accent: string }) {
    return (
        <div className="flex flex-col gap-1 bg-[#13151f] border border-white/[0.07] rounded-2xl p-4">
            <span className="text-[10px] text-gray-500 uppercase tracking-widest font-semibold">{label}</span>
            <span className="text-2xl font-bold tabular-nums" style={{ color: accent }}>{value}</span>
            {sub && <span className="text-[10px] text-gray-600">{sub}</span>}
        </div>
    );
}

// ── Change Pct Display ────────────────────────────────────────────────────────

function ChangePct({ v }: { v: number }) {
    const color = v > 0 ? 'text-emerald-400' : v < 0 ? 'text-red-400' : 'text-gray-500';
    return <span className={`text-xs font-bold tabular-nums ${color}`}>{v > 0 ? '+' : ''}{v.toFixed(1)}%</span>;
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function TrackRecordPage() {
    const [data, setData] = useState<PerfData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const loadData = useCallback(async () => {
        try {
            setLoading(true);
            setError(null);
            const result = await jonggaAPI.getPerformance() as any;
            setData(result);
        } catch (e) {
            setError('데이터 로드 실패');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { loadData(); }, [loadData]);
    usePullToRefreshRegister(loadData);

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="w-8 h-8 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    if (error || !data) {
        return (
            <div className="flex flex-col items-center justify-center h-64 gap-3">
                <i className="fas fa-exclamation-triangle text-2xl text-red-400" />
                <span className="text-gray-400 text-sm">{error ?? '데이터 없음'}</span>
                <button onClick={loadData} className="text-xs text-blue-400 underline">다시 시도</button>
            </div>
        );
    }

    const gt = data.grade_totals ?? {};
    const totalSA = (gt.S ?? 0) + (gt.A ?? 0);
    const saRate = data.total_signals > 0 ? ((totalSA / data.total_signals) * 100).toFixed(0) : '0';

    // Sort history newest first
    const history = [...(data.history ?? [])].sort((a, b) => b.date.localeCompare(a.date));

    return (
        <div className="flex flex-col gap-5 pb-8">
            {/* Header */}
            <div className="flex flex-col gap-1 pt-1">
                <div className="flex items-center gap-2">
                    <i className="fas fa-trophy text-yellow-400" />
                    <h1 className="text-xl font-bold text-white">Track Record</h1>
                </div>
                <p className="text-[11px] text-gray-500">종가베팅 V2 · 누적 성과 기록</p>
            </div>

            {/* Summary Stats */}
            <div className="grid grid-cols-2 gap-3">
                <StatCard label="운영 일수" value={data.days_count} sub="총 분석일" accent="#a78bfa" />
                <StatCard label="총 시그널" value={data.total_signals} sub="전체 누적" accent="#60a5fa" />
                <StatCard label="S+A급 비율" value={`${saRate}%`} sub={`${totalSA}개 핵심 시그널`} accent="#fbbf24" />
                <StatCard label="S급 시그널" value={gt.S ?? 0} sub={`A급 ${gt.A ?? 0}개`} accent="#f59e0b" />
            </div>

            {/* Grade Distribution Bar */}
            <div className="bg-[#13151f] border border-white/[0.07] rounded-2xl p-4">
                <span className="text-[10px] text-gray-500 uppercase tracking-widest font-semibold block mb-3">등급 분포</span>
                <div className="flex gap-3 mb-3">
                    {(['S', 'A', 'B', 'C'] as const).map(g => {
                        const cnt = gt[g] ?? 0;
                        const pct = data.total_signals > 0 ? (cnt / data.total_signals) * 100 : 0;
                        return (
                            <div key={g} className="flex flex-col items-center gap-1 flex-1">
                                <GradeBadge grade={g} />
                                <span className="text-sm font-bold text-white tabular-nums">{cnt}</span>
                                <span className="text-[9px] text-gray-600">{pct.toFixed(0)}%</span>
                            </div>
                        );
                    })}
                </div>
                {/* Visual bar */}
                <div className="flex h-1.5 rounded-full overflow-hidden gap-0.5">
                    {(['S', 'A', 'B', 'C'] as const).map(g => {
                        const cnt = gt[g] ?? 0;
                        const pct = data.total_signals > 0 ? (cnt / data.total_signals) * 100 : 0;
                        const colors: Record<string, string> = { S: '#f59e0b', A: '#60a5fa', B: '#6b7280', C: '#ef4444' };
                        return pct > 0 ? (
                            <div key={g} className="rounded-full" style={{ width: `${pct}%`, background: colors[g] }} />
                        ) : null;
                    })}
                </div>
            </div>

            {/* Daily History */}
            <div className="bg-[#13151f] border border-white/[0.07] rounded-2xl overflow-hidden">
                <div className="px-4 py-3 border-b border-white/[0.06] flex items-center justify-between">
                    <span className="text-[11px] font-semibold text-gray-300">일별 기록</span>
                    <span className="text-[10px] text-gray-600">{history.length}일</span>
                </div>
                <div className="divide-y divide-white/[0.04]">
                    {history.map((day) => {
                        const bg = day.by_grade ?? {};
                        const sCount = bg.S ?? 0;
                        const aCount = bg.A ?? 0;
                        return (
                            <div key={day.date} className="px-4 py-3 flex flex-col gap-2">
                                {/* Top row: date + grade counts */}
                                <div className="flex items-center justify-between">
                                    <span className="text-xs font-semibold text-white">{day.date}</span>
                                    <div className="flex items-center gap-1.5">
                                        {sCount > 0 && (
                                            <span className="flex items-center gap-0.5 text-[10px] font-bold text-yellow-400">
                                                <GradeBadge grade="S" /> ×{sCount}
                                            </span>
                                        )}
                                        {aCount > 0 && (
                                            <span className="flex items-center gap-0.5 text-[10px] font-bold text-blue-400">
                                                <GradeBadge grade="A" /> ×{aCount}
                                            </span>
                                        )}
                                        <span className="text-[10px] text-gray-600 ml-1">총 {day.total_signals}개</span>
                                    </div>
                                </div>
                                {/* Top signal */}
                                {day.top_signal && (
                                    <div className="flex items-center justify-between bg-white/[0.03] rounded-lg px-3 py-2">
                                        <div className="flex items-center gap-2">
                                            <GradeBadge grade={day.top_signal.grade} />
                                            <span className="text-xs font-semibold text-white">{day.top_signal.stock_name}</span>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <ChangePct v={day.top_signal.change_pct} />
                                            <span className="text-[10px] text-gray-600">{day.top_signal.score}점</span>
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
