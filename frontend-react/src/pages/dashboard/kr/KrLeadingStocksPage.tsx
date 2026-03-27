import { useState, useCallback, useEffect } from 'react';
import { fetchAPI } from '@/lib/api';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import { usePullToRefreshRegister } from '@/components/layout/PullToRefreshProvider';

// ─── TypeScript 인터페이스 ───

interface ScoreDetail {
    total: number;
    total_enriched?: number | null;
    trading_value: number;
    momentum: number;
    smart_money: number;
    volume_surge: number;
    sector: number;
    new_high?: number;
    ai_news?: number | null;
    consecutive?: number | null;
}

interface High52wInfo {
    high_52w: number;
    low_52w: number;
    high_date: string;
    days_since: number | null;
    distance_pct: number;
}

interface Enrichment {
    ai_score: number;
    ai_reason: string;
    themes: string[];
    consecutive_days: number;
    market_cap_eok: number;
    market_cap_tier: string;
    enriched_at: string;
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
    high_52w?: High52wInfo;
    market_cap_eok?: number;
    enrichment?: Enrichment;
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

// ─── 스타일 상수 ───

const GRADE_STYLE: Record<string, { bg: string; border: string; text: string; glow: string; ring: string }> = {
    S: { bg: 'bg-rose-500/10', border: 'border-rose-500/30', text: 'text-rose-400', glow: 'shadow-rose-500/20', ring: 'ring-rose-500/30' },
    A: { bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400', glow: 'shadow-amber-500/20', ring: 'ring-amber-500/30' },
    B: { bg: 'bg-blue-500/10', border: 'border-blue-500/30', text: 'text-blue-400', glow: 'shadow-blue-500/20', ring: 'ring-blue-500/30' },
};

const THEME_COLORS = [
    'bg-violet-500/15 text-violet-300 border-violet-500/20',
    'bg-cyan-500/15 text-cyan-300 border-cyan-500/20',
    'bg-emerald-500/15 text-emerald-300 border-emerald-500/20',
    'bg-pink-500/15 text-pink-300 border-pink-500/20',
];

const CAP_STYLE: Record<string, string> = {
    '대형': 'bg-blue-500/15 text-blue-300 border-blue-500/20',
    '중형': 'bg-teal-500/15 text-teal-300 border-teal-500/20',
    '중소형': 'bg-amber-500/15 text-amber-300 border-amber-500/20',
    '소형': 'bg-orange-500/15 text-orange-300 border-orange-500/20',
};

// ─── 서브 컴포넌트 ───

function ScoreBar({ label, score, max, color }: { label: string; score: number; max: number; color: string }) {
    const pct = max > 0 ? (score / max) * 100 : 0;
    return (
        <div className="flex items-center gap-2 text-xs">
            <span className="w-7 text-gray-500 text-right text-[10px] font-medium">{label}</span>
            <div className="flex-1 h-1.5 bg-gray-700/50 rounded-full overflow-hidden">
                <div className={`h-full rounded-full transition-all duration-700 ${color}`}
                    style={{ width: `${pct}%` }} />
            </div>
            <span className="w-7 text-right font-mono text-[10px]">
                <span className="text-white font-bold">{score}</span>
                <span className="text-gray-600">/{max}</span>
            </span>
        </div>
    );
}

function AIBadge({ score }: { score: number }) {
    if (score <= 0) return null;
    const styles = [
        '', // 0
        'bg-gray-500/15 text-gray-400',     // 1 불분명
        'bg-emerald-500/15 text-emerald-400', // 2 긍정적
        'bg-rose-500/15 text-rose-400',       // 3 확실한 호재
    ];
    const labels = ['', '불분명', '긍정적', '강력호재'];
    return (
        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold border border-white/5 ${styles[score] || styles[1]}`}>
            <svg className="w-2.5 h-2.5" viewBox="0 0 16 16" fill="currentColor">
                <path d="M8 1a2.5 2.5 0 012.5 2.5c0 .87-.56 1.6-1.15 2.17L8 7l-1.35-1.33A2.97 2.97 0 015.5 3.5 2.5 2.5 0 018 1zm0 8.5l3.5 2-1-3.8 3-2.5h-3.8L8 1.5 6.3 5.2H2.5l3 2.5-1 3.8z"/>
            </svg>
            {labels[score]}
        </span>
    );
}

function StockCard({ stock }: { stock: LeadingStock }) {
    const gs = GRADE_STYLE[stock.grade] || GRADE_STYLE.B;
    const s = stock.score;
    const e = stock.enrichment;
    const capEok = stock.market_cap_eok || e?.market_cap_eok || 0;
    const capTier = e?.market_cap_tier || '';

    return (
        <div className={`group relative rounded-2xl border ${gs.border} bg-[#1c1c1e] overflow-hidden hover:border-opacity-60 transition-all duration-300 hover:shadow-lg ${gs.glow}`}>
            {/* Glow */}
            <div className={`absolute top-0 right-0 w-40 h-40 ${gs.bg} rounded-full blur-[50px] -translate-y-1/2 translate-x-1/2 opacity-15 group-hover:opacity-30 transition-opacity duration-500`} />

            <div className="relative z-10 p-4 flex flex-col gap-2.5">
                {/* Row 1: Grade + Change% */}
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-black border ${gs.bg} ${gs.border} ${gs.text}`}>
                            {stock.grade}
                        </span>
                        <span className="text-[10px] text-gray-600 font-mono">#{stock.rank}</span>
                        {/* 연속 주도주 뱃지 */}
                        {e && e.consecutive_days >= 2 && (
                            <span className="flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-orange-500/10 border border-orange-500/20 text-[9px] text-orange-400 font-bold">
                                <span className="text-[10px]">&#x1F525;</span>{e.consecutive_days}일연속
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-1.5">
                        <span className={`text-base font-black font-mono tabular-nums ${stock.change_pct >= 0 ? 'text-rose-400' : 'text-blue-400'}`}>
                            {stock.change_pct >= 0 ? '+' : ''}{stock.change_pct.toFixed(1)}%
                        </span>
                    </div>
                </div>

                {/* Row 2: Name + Price + Cap */}
                <div>
                    <div className="flex items-center gap-2">
                        <span className="text-base font-bold text-white leading-tight">{stock.name}</span>
                        {/* 시총 뱃지 */}
                        {capTier && capTier !== '미분류' && (
                            <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${CAP_STYLE[capTier] || 'bg-gray-500/10 text-gray-400'}`}>
                                {capTier}
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-3 mt-0.5">
                        <span className="text-sm font-mono text-gray-300">{stock.price.toLocaleString()}원</span>
                        <span className="text-[10px] text-gray-600">{stock.trading_value_eok.toLocaleString()}억</span>
                        {capEok > 0 && (
                            <span className="text-[10px] text-gray-600">시총 {capEok >= 10000 ? `${(capEok / 10000).toFixed(1)}조` : `${capEok.toLocaleString()}억`}</span>
                        )}
                    </div>
                </div>

                {/* Row 3: AI 분석 (있을 때만) */}
                {e && e.ai_reason && (
                    <div className="flex items-start gap-2 px-2.5 py-2 rounded-xl bg-gradient-to-r from-violet-500/5 to-indigo-500/5 border border-violet-500/10">
                        <span className="text-[10px] mt-0.5 shrink-0">&#x1F916;</span>
                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5 mb-0.5">
                                <span className="text-[10px] text-violet-400 font-bold">AI 분석</span>
                                <AIBadge score={e.ai_score} />
                            </div>
                            <p className="text-[11px] text-gray-300 leading-relaxed">{e.ai_reason}</p>
                        </div>
                    </div>
                )}

                {/* Row 4: 테마 칩 */}
                {e && e.themes && e.themes.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                        {e.themes.map((theme, i) => (
                            <span key={i} className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${THEME_COLORS[i % THEME_COLORS.length]}`}>
                                #{theme}
                            </span>
                        ))}
                    </div>
                )}

                {/* Row 5: Score (기본 + 보강) */}
                <div className="flex items-center gap-2">
                    <span className={`text-2xl font-mono font-black ${gs.text}`}>
                        {s.total_enriched != null ? s.total_enriched : s.total}
                    </span>
                    {s.total_enriched != null ? (
                        <div className="flex items-baseline gap-1">
                            <span className="text-gray-600 text-xs">= {s.total}</span>
                            <span className="text-violet-400 text-xs font-bold">+{s.total_enriched - s.total}</span>
                            <span className="text-[9px] text-violet-500/60">AI</span>
                        </div>
                    ) : (
                        <span className="text-gray-600 text-sm">/100</span>
                    )}
                </div>

                {/* Row 6: Score Bars — Layer 1 (실시간) */}
                <div className="space-y-1">
                    <ScoreBar label="거래" score={s.trading_value} max={30} color="bg-gradient-to-r from-emerald-500 to-green-400" />
                    <ScoreBar label="모멘" score={s.momentum} max={25} color="bg-gradient-to-r from-amber-500 to-yellow-400" />
                    <ScoreBar label="수급" score={s.smart_money} max={25} color="bg-gradient-to-r from-rose-500 to-pink-400" />
                    <ScoreBar label="급증" score={s.volume_surge} max={10} color="bg-gradient-to-r from-cyan-500 to-blue-400" />
                    <ScoreBar label="섹터" score={s.sector} max={10} color="bg-gradient-to-r from-violet-500 to-purple-400" />
                    {s.new_high != null && s.new_high > 0 && (
                        <ScoreBar label="신고" score={s.new_high} max={15} color="bg-gradient-to-r from-orange-500 to-red-500" />
                    )}
                </div>

                {/* Layer 2 보강 점수 (AI 분석 완료 시) */}
                {s.ai_news != null && (
                    <div className="space-y-1 pt-1 border-t border-white/5">
                        <div className="text-[9px] text-violet-400/70 font-bold flex items-center gap-1 mb-0.5">
                            <span>&#x1F916;</span> AI 보강
                        </div>
                        <ScoreBar label="뉴스" score={s.ai_news} max={10} color="bg-gradient-to-r from-violet-500 to-indigo-400" />
                        {s.consecutive != null && (
                            <ScoreBar label="연속" score={s.consecutive} max={8} color="bg-gradient-to-r from-orange-500 to-amber-400" />
                        )}
                    </div>
                )}

                {/* Row 7: 52주 신고가 뱃지 */}
                {stock.high_52w && s.new_high != null && s.new_high > 0 && (
                    <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-xl bg-orange-500/10 border border-orange-500/20">
                        <span className="text-[11px]">&#x1F451;</span>
                        <span className="text-[10px] text-orange-300 font-medium">
                            {stock.high_52w.distance_pct <= 0 ? '52주 신고가 갱신!' :
                             `52주 고가 ${stock.high_52w.distance_pct}% 이내`}
                        </span>
                        {stock.high_52w.days_since != null && (
                            <span className="text-[9px] text-orange-400/60 ml-auto">{stock.high_52w.days_since}일 전</span>
                        )}
                    </div>
                )}

                {/* Row 8: 투자자 흐름 */}
                {(stock.investor.foreign_net !== 0 || stock.investor.inst_net !== 0) && (
                    <div className="flex gap-2">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${stock.investor.foreign_net > 0 ? 'bg-rose-500/10 text-rose-400' : stock.investor.foreign_net < 0 ? 'bg-blue-500/10 text-blue-400' : 'bg-gray-500/10 text-gray-500'}`}>
                            외인 {stock.investor.foreign_net > 0 ? '+' : ''}{Math.abs(stock.investor.foreign_net) >= 10000 ? `${(stock.investor.foreign_net / 10000).toFixed(1)}만` : stock.investor.foreign_net.toLocaleString()}
                        </span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${stock.investor.inst_net > 0 ? 'bg-rose-500/10 text-rose-400' : stock.investor.inst_net < 0 ? 'bg-blue-500/10 text-blue-400' : 'bg-gray-500/10 text-gray-500'}`}>
                            기관 {stock.investor.inst_net > 0 ? '+' : ''}{Math.abs(stock.investor.inst_net) >= 10000 ? `${(stock.investor.inst_net / 10000).toFixed(1)}만` : stock.investor.inst_net.toLocaleString()}
                        </span>
                    </div>
                )}
            </div>
        </div>
    );
}

// ─── 메인 페이지 ───

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

    // 보강된 종목 수
    const enrichedCount = data?.results?.filter(r => r.enrichment?.ai_reason).length || 0;

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
                    <div>
                        <h2 className="text-2xl md:text-3xl font-extrabold text-white tracking-tight">
                            주도주<span className="text-transparent bg-clip-text bg-gradient-to-r from-red-400 to-orange-400">LIVE</span>
                        </h2>
                        <p className="text-[10px] text-gray-600 -mt-0.5">KIS OpenAPI + Gemini AI 실시간 분석</p>
                    </div>
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
                    <button onClick={loadData} className="w-8 h-8 rounded-lg bg-zinc-900 border border-white/10 flex items-center justify-center hover:border-white/20 hover:bg-white/5 transition-all active:scale-95">
                        <i className={`fas fa-sync-alt text-[11px] ${loading ? 'animate-spin text-amber-400' : 'text-zinc-500'}`} />
                    </button>
                </div>
            </div>

            {/* Stats Row */}
            {data && (
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                    {[
                        { label: '후보 종목', value: data.total_candidates, suffix: '개', icon: '&#x1F50D;' },
                        { label: 'S등급', value: data.by_grade?.S || 0, suffix: '개', color: 'text-rose-400', icon: '&#x1F525;' },
                        { label: 'A등급', value: data.by_grade?.A || 0, suffix: '개', color: 'text-amber-400', icon: '&#x1F7E1;' },
                        { label: 'B등급', value: data.by_grade?.B || 0, suffix: '개', color: 'text-blue-400', icon: '&#x1F535;' },
                        { label: 'AI분석', value: enrichedCount, suffix: '종목', color: 'text-violet-400', icon: '&#x1F916;' },
                    ].map((stat) => (
                        <div key={stat.label} className="p-3 rounded-xl bg-[#1c1c1e] border border-white/5">
                            <div className="flex items-center gap-1 mb-1">
                                <span className="text-[10px]" dangerouslySetInnerHTML={{ __html: stat.icon }} />
                                <span className="text-[10px] text-gray-500 uppercase tracking-wider font-bold">{stat.label}</span>
                            </div>
                            <div className={`text-xl font-mono font-bold ${stat.color || 'text-white'}`}>
                                {stat.value}<span className="text-gray-600 text-xs ml-0.5">{stat.suffix}</span>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Grade Filter */}
            <div className="flex gap-2 flex-wrap">
                {grades.map(g => {
                    const count = g === 'ALL' ? (data?.results?.length || 0) : (data?.by_grade?.[g] || 0);
                    const active = gradeFilter === g;
                    return (
                        <button key={g} onClick={() => setGradeFilter(g)}
                            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all active:scale-95 ${
                                active
                                    ? 'bg-white/10 text-white border border-white/20 shadow-sm'
                                    : 'bg-white/5 text-gray-500 border border-transparent hover:text-gray-300 hover:bg-white/[0.07]'
                            }`}>
                            {g === 'ALL' ? '전체' : g} ({count})
                        </button>
                    );
                })}
            </div>

            {/* Market Closed State */}
            {data && !isOpen && (
                <div className="flex flex-col items-center justify-center py-6 gap-2 bg-[#1c1c1e] rounded-2xl border border-white/5">
                    <div className="w-10 h-10 rounded-full bg-zinc-800/60 flex items-center justify-center">
                        <i className="fas fa-moon text-zinc-600 text-base" />
                    </div>
                    <span className="text-xs text-zinc-600 font-medium">장 마감 &#x2014; 마지막 스캔 결과</span>
                    {data.timestamp && (
                        <span className="text-[10px] text-zinc-700">{new Date(data.timestamp).toLocaleString('ko-KR')}</span>
                    )}
                </div>
            )}

            {/* Results Grid */}
            {loading && !data ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {[1, 2, 3, 4, 5, 6].map(i => (
                        <div key={i} className="h-72 rounded-2xl bg-white/5 animate-pulse" />
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
                        <span className="text-3xl opacity-30">&#x1F50D;</span>
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
                <div className="text-[10px] text-zinc-600 text-center py-2 space-x-2">
                    <span>KIS API</span>
                    <span>&#x00B7;</span>
                    <span>{data.api_calls}건 호출</span>
                    <span>&#x00B7;</span>
                    <span>{data.elapsed_ms}ms</span>
                    <span>&#x00B7;</span>
                    <span>후보 {data.total_candidates} &#x2192; 결과 {data.results?.length || 0}종목</span>
                    {enrichedCount > 0 && (
                        <>
                            <span>&#x00B7;</span>
                            <span className="text-violet-500">AI {enrichedCount}종목 분석</span>
                        </>
                    )}
                </div>
            )}
        </div>
    );
}
