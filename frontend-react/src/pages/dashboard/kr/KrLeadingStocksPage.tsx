import { useState, useCallback, useEffect } from 'react';
import { fetchAPI } from '@/lib/api';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import { usePullToRefreshRegister } from '@/components/layout/PullToRefreshProvider';

interface ScoreDetail {
    total: number;
    trading_value: number;
    momentum: number;
    smart_money: number;
    volume_surge: number;
    sector: number;
}

interface LeadingStock {
    rank: number;
    grade: string;
    code: string;
    name: string;
    price: number;
    change_pct: number;
    trading_value: number;
    trading_value_eok: number;
    volume: number;
    score: ScoreDetail;
    investor: { foreign_net: number; inst_net: number };
    volume_ratio: number;
    sector_rising_count: number;
}

interface ScreenerResult {
    timestamp: string;
    market_status: string;
    time_weight: number;
    total_candidates: number;
    results: LeadingStock[];
    by_grade: Record<string, number>;
    elapsed_ms: number;
    api_calls: number;
}

const GRADE_STYLE: Record<string, { bg: string; border: string; text: string; glow: string }> = {
    S: { bg: 'bg-rose-500/10', border: 'border-rose-500/30', text: 'text-rose-400', glow: 'shadow-rose-500/20' },
    A: { bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400', glow: 'shadow-amber-500/20' },
    B: { bg: 'bg-blue-500/10', border: 'border-blue-500/30', text: 'text-blue-400', glow: 'shadow-blue-500/20' },
};

function ScoreBar({ label, score, max, color }: { label: string; score: number; max: number; color: string }) {
    const pct = max > 0 ? (score / max) * 100 : 0;
    return (
        <div className="flex items-center gap-2 text-xs">
            <span className="w-8 text-gray-500 text-right text-[10px]">{label}</span>
            <div className="flex-1 h-1.5 bg-gray-700/50 rounded-full overflow-hidden">
                <div className={`h-full rounded-full transition-all duration-500 ${color}`}
                    style={{ width: `${pct}%` }} />
            </div>
            <span className="w-6 text-right font-mono text-[10px]">
                <span className="text-white font-bold">{score}</span>
                <span className="text-gray-600">/{max}</span>
            </span>
        </div>
    );
}

function StockCard({ stock }: { stock: LeadingStock }) {
    const gs = GRADE_STYLE[stock.grade] || GRADE_STYLE.B;
    const s = stock.score;

    return (
        <div className={`group relative rounded-2xl border ${gs.border} bg-[#1c1c1e] p-4 overflow-hidden hover:border-opacity-60 transition-all`}>
            {/* Glow */}
            <div className={`absolute top-0 right-0 w-40 h-40 ${gs.bg} rounded-full blur-[50px] -translate-y-1/2 translate-x-1/2 opacity-15 group-hover:opacity-25 transition-opacity`} />

            <div className="relative z-10 flex flex-col gap-3">
                {/* Header */}
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${gs.bg} ${gs.border} ${gs.text}`}>
                            {stock.grade}
                        </span>
                        <span className="text-[10px] text-gray-600 font-mono">#{stock.rank}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                        <span className={`text-sm font-bold font-mono tabular-nums ${stock.change_pct >= 0 ? 'text-rose-400' : 'text-blue-400'}`}>
                            {stock.change_pct >= 0 ? '+' : ''}{stock.change_pct.toFixed(1)}%
                        </span>
                    </div>
                </div>

                {/* Name + Price */}
                <div>
                    <div className="text-base font-bold text-white">{stock.name}</div>
                    <div className="flex items-center gap-3 mt-1">
                        <span className="text-sm font-mono text-gray-300">{stock.price.toLocaleString()}원</span>
                        <span className="text-[10px] text-gray-600">{stock.trading_value_eok.toLocaleString()}억</span>
                    </div>
                </div>

                {/* Score */}
                <div className="flex items-center gap-2 mb-1">
                    <span className={`text-2xl font-mono font-black ${gs.text}`}>{s.total}</span>
                    <span className="text-gray-600 text-sm">/100</span>
                </div>

                {/* Score Bars */}
                <div className="space-y-1.5">
                    <ScoreBar label="거래" score={s.trading_value} max={30} color="bg-gradient-to-r from-emerald-500 to-green-400" />
                    <ScoreBar label="모멘" score={s.momentum} max={25} color="bg-gradient-to-r from-amber-500 to-yellow-400" />
                    <ScoreBar label="수급" score={s.smart_money} max={25} color="bg-gradient-to-r from-rose-500 to-pink-400" />
                    <ScoreBar label="급증" score={s.volume_surge} max={10} color="bg-gradient-to-r from-cyan-500 to-blue-400" />
                    <ScoreBar label="섹터" score={s.sector} max={10} color="bg-gradient-to-r from-violet-500 to-purple-400" />
                </div>

                {/* Investor Flow */}
                {(stock.investor.foreign_net !== 0 || stock.investor.inst_net !== 0) && (
                    <div className="flex gap-2 mt-1">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${stock.investor.foreign_net > 0 ? 'bg-rose-500/10 text-rose-400' : 'bg-blue-500/10 text-blue-400'}`}>
                            외인 {stock.investor.foreign_net > 0 ? '+' : ''}{(stock.investor.foreign_net / 1000).toFixed(0)}K
                        </span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${stock.investor.inst_net > 0 ? 'bg-rose-500/10 text-rose-400' : 'bg-blue-500/10 text-blue-400'}`}>
                            기관 {stock.investor.inst_net > 0 ? '+' : ''}{(stock.investor.inst_net / 1000).toFixed(0)}K
                        </span>
                    </div>
                )}
            </div>
        </div>
    );
}

export default function KrLeadingStocksPage() {
    const [data, setData] = useState<ScreenerResult | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [gradeFilter, setGradeFilter] = useState<string>('ALL');
    const [dates, setDates] = useState<string[]>([]);
    const [selectedDate, setSelectedDate] = useState<string>('latest');

    const loadDates = useCallback(async () => {
        try {
            const res = await fetchAPI<{ dates: string[] }>('/api/kr/screener/leading/history?dates=true');
            if (res?.dates) setDates(res.dates);
        } catch { /* ignore */ }
    }, []);

    const loadData = useCallback(async () => {
        try {
            setError('');
            let result: ScreenerResult | null = null;
            if (selectedDate === 'latest') {
                result = await fetchAPI<ScreenerResult>('/api/kr/screener/leading');
            } else {
                result = await fetchAPI<ScreenerResult>(`/api/kr/screener/leading/history?date=${selectedDate}`);
            }
            if (result) setData(result);
        } catch (e: any) {
            setError(e.message || '데이터 로딩 실패');
        } finally {
            setLoading(false);
        }
    }, [selectedDate]);

    useEffect(() => { loadDates(); }, [loadDates]);
    useEffect(() => { setLoading(true); loadData(); }, [loadData]);
    const isOpen = data?.market_status === 'open' && selectedDate === 'latest';
    useAutoRefresh(loadData, isOpen ? 5000 : 60000, selectedDate === 'latest');
    usePullToRefreshRegister(loadData);

    const filtered = data?.results?.filter(r =>
        gradeFilter === 'ALL' || r.grade === gradeFilter
    ) || [];

    const grades = ['ALL', 'S', 'A', 'B'];

    return (
        <div className="flex flex-col gap-3 md:gap-4 animate-fade-in font-sans text-zinc-200">
            {/* Header */}
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div className="flex items-center gap-3">
                    <div className="relative flex items-center justify-center w-8 h-8">
                        <span className="absolute w-3 h-3 rounded-full bg-red-500 animate-ping opacity-75" />
                        <span className="relative w-3 h-3 rounded-full bg-red-500" />
                    </div>
                    <h2 className="text-2xl md:text-3xl font-extrabold text-white tracking-tight">
                        주도주<span className="text-transparent bg-clip-text bg-gradient-to-r from-red-400 to-orange-400">LIVE</span>
                    </h2>
                </div>
                <div className="flex items-center gap-2">
                    {dates.length > 0 && (
                        <select
                            value={selectedDate}
                            onChange={(e) => setSelectedDate(e.target.value)}
                            className="bg-zinc-900 border border-white/10 rounded-lg text-[11px] text-gray-300 px-2 py-1.5 focus:outline-none focus:border-white/20"
                        >
                            <option value="latest">Latest</option>
                            {dates.map(d => (
                                <option key={d} value={d}>{`${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6)}`}</option>
                            ))}
                        </select>
                    )}
                    {data && selectedDate === 'latest' && (
                        <span className="text-[10px] text-zinc-500 font-mono hidden sm:block">
                            {new Date(data.timestamp).toLocaleTimeString('ko-KR')}
                        </span>
                    )}
                    <button onClick={loadData} className="w-8 h-8 rounded-lg bg-zinc-900 border border-white/10 flex items-center justify-center hover:border-white/20 hover:bg-white/5 transition-all">
                        <i className={`fas fa-sync-alt text-[11px] ${loading ? 'animate-spin text-amber-400' : 'text-zinc-500'}`} />
                    </button>
                </div>
            </div>

            {/* Stats Row */}
            {data && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    {[
                        { label: '후보 종목', value: data.total_candidates, suffix: '개' },
                        { label: 'S등급', value: data.by_grade?.S || 0, suffix: '개', color: 'text-rose-400' },
                        { label: 'A등급', value: data.by_grade?.A || 0, suffix: '개', color: 'text-amber-400' },
                        { label: 'B등급', value: data.by_grade?.B || 0, suffix: '개', color: 'text-blue-400' },
                    ].map((stat) => (
                        <div key={stat.label} className="p-3 rounded-xl bg-[#1c1c1e] border border-white/5">
                            <div className="text-[10px] text-gray-500 uppercase tracking-wider font-bold mb-1">{stat.label}</div>
                            <div className={`text-xl font-mono font-bold ${stat.color || 'text-white'}`}>
                                {stat.value}<span className="text-gray-600 text-xs ml-0.5">{stat.suffix}</span>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Grade Filter */}
            <div className="flex gap-2">
                {grades.map(g => {
                    const count = g === 'ALL' ? (data?.results?.length || 0) : (data?.by_grade?.[g] || 0);
                    const active = gradeFilter === g;
                    return (
                        <button key={g} onClick={() => setGradeFilter(g)}
                            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${active ? 'bg-white/10 text-white border border-white/20' : 'bg-white/5 text-gray-500 border border-transparent hover:text-gray-300'}`}>
                            {g === 'ALL' ? '전체' : g} ({count})
                        </button>
                    );
                })}
            </div>

            {/* Market Closed State */}
            {data && !isOpen && (
                <div className="flex flex-col items-center justify-center py-8 gap-2 bg-[#1c1c1e] rounded-2xl border border-white/5">
                    <div className="w-10 h-10 rounded-full bg-zinc-800/60 flex items-center justify-center">
                        <i className="fas fa-moon text-zinc-600 text-base" />
                    </div>
                    <span className="text-xs text-zinc-600 font-medium">장 마감 — 마지막 스캔 결과</span>
                    {data.timestamp && (
                        <span className="text-[10px] text-zinc-700">{new Date(data.timestamp).toLocaleString('ko-KR')}</span>
                    )}
                </div>
            )}

            {/* Results Grid */}
            {loading && !data ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {[1, 2, 3, 4, 5, 6].map(i => (
                        <div key={i} className="h-64 rounded-2xl bg-white/5 animate-pulse" />
                    ))}
                </div>
            ) : error ? (
                <div className="bg-[#1c1c1e] rounded-2xl p-12 text-center border border-red-500/20">
                    <i className="fas fa-exclamation-triangle text-red-400 text-2xl mb-3 block" />
                    <p className="text-red-400 text-sm">{error}</p>
                    <button onClick={loadData} className="mt-3 px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-sm text-gray-400 transition-all">
                        재시도
                    </button>
                </div>
            ) : filtered.length === 0 ? (
                <div className="bg-[#1c1c1e] rounded-2xl p-16 text-center border border-white/5 flex flex-col items-center">
                    <div className="w-16 h-16 bg-white/5 rounded-full flex items-center justify-center mb-4">
                        <span className="text-3xl opacity-30">🔍</span>
                    </div>
                    <h3 className="text-xl font-bold text-gray-300">시그널 없음</h3>
                    <p className="text-gray-500 mt-2 max-w-md text-sm">현재 조건에 맞는 주도주가 없습니다. 장중에 다시 확인하세요.</p>
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {filtered.map(stock => (
                        <StockCard key={stock.code} stock={stock} />
                    ))}
                </div>
            )}

            {/* Footer Info */}
            {data && (
                <div className="text-[10px] text-zinc-600 text-center py-2">
                    KIS API · {data.api_calls}건 호출 · {data.elapsed_ms}ms · 후보 {data.total_candidates}종목 → 결과 {data.results?.length || 0}종목
                </div>
            )}
        </div>
    );
}
