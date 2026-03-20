

import React, { useState, useEffect, useCallback } from 'react';
import { useAutoRefresh, useSmartRefresh } from '@/hooks/useAutoRefresh';
import { usePullToRefreshRegister } from '@/components/layout/PullToRefreshProvider';
import { API_BASE, API_HEADERS } from '@/lib/api';

// Interfaces (Based on backend models)
interface ScoreDetail {
    news: number;
    volume: number;
    chart: number;
    candle: number;
    consolidation: number;
    supply: number;
    disclosure: number;
    analyst: number;
    llm_reason: string;
    llm_source?: string;
    total: number;
}

interface AIPick {
    stock_code: string;
    stock_name: string;
    rank: number;
    confidence: 'HIGH' | 'MEDIUM' | 'LOW';
    reason: string;
    risk: string;
    expected_return: string;
    source?: string;           // "consensus" | "gemini_only" | "openai_only"
    gemini_rank?: number;
    openai_rank?: number;
}

interface AIPicks {
    picks: AIPick[];
    market_view?: string;
    top_themes?: string[];
    generated_at?: string;
    model?: string;
    models?: string[];
    consensus_count?: number;
    gemini_count?: number;
    openai_count?: number;
    consensus_method?: string;
}

interface ChecklistDetail {
    has_news: boolean;
    news_sources: string[];
    volume_sufficient: boolean;
    is_new_high: boolean;
    is_breakout: boolean;
    ma_aligned: boolean;
    good_candle: boolean;
    has_consolidation: boolean;
    supply_positive: boolean;
    has_disclosure?: boolean;
    disclosure_types?: string[];
    negative_news: boolean;
    upper_wick_long: boolean;
    volume_suspicious: boolean;
}

interface NewsItem {
    title: string;
    source: string;
    published_at: string;
    url: string;
}

interface Signal {
    stock_code: string;
    stock_name: string;
    market: string;
    sector?: string;
    signal_date?: string;
    grade: string; // 'S', 'A', 'B', 'C'
    score: ScoreDetail;
    checklist: ChecklistDetail;
    current_price: number;
    entry_price: number;
    stop_price: number;
    target_price: number;
    quantity?: number;
    position_size?: number;
    r_value?: number;
    r_multiplier?: number;
    change_pct: number;
    trading_value: number;
    volume_ratio?: number;
    foreign_5d: number;
    inst_5d: number;
    news_items?: NewsItem[];
    themes?: string[];
}

interface ScreenerResult {
    date: string;
    total_candidates: number;
    filtered_count: number;
    signals: Signal[];
    by_grade?: Record<string, number>;
    by_market?: Record<string, number>;
    processing_time_ms?: number;
    updated_at: string;
    claude_picks?: AIPicks;
}

// 3. Naver Chart Image Component (Bypass iframe restriction)
function NaverChartWidget({ symbol }: { symbol: string }) {
    // stable timestamp for the lifecycle of the component
    const [timestamp] = useState(() => Date.now());

    return (
        <div className="flex flex-col items-center justify-center p-8 bg-white h-full relative">
            <div className="w-full flex-1 flex items-center justify-center overflow-hidden">
                <img
                    src={`https://ssl.pstatic.net/imgfinance/chart/item/candle/day/${symbol}.png?sidcode=${timestamp}`}
                    alt="Chart"
                    className="max-w-full max-h-full object-contain"
                />
            </div>
            <a
                href={`https://m.stock.naver.com/domestic/stock/${symbol}/chart`}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-6 px-6 py-3 bg-[#03c75a] hover:bg-[#00b24e] text-white font-bold rounded-xl transition-all shadow-lg hover:shadow-xl flex items-center gap-2"
            >
                <span>View Interactive Chart (Naver)</span>
                <i className="fas fa-external-link-alt"></i>
            </a>
            <p className="mt-4 text-xs text-gray-400">
                * Static chart image provided by Naver Finance. Click the button for real-time interactive analysis.
            </p>
        </div>
    );
}

// 4. Chart Modal Component
function ChartModal({ symbol, name, onClose }: { symbol: string, name: string, onClose: () => void }) {
    useEffect(() => {
        const handleEsc = (e: KeyboardEvent) => {
            if (e.key === 'Escape') onClose();
        };
        window.addEventListener('keydown', handleEsc);
        return () => window.removeEventListener('keydown', handleEsc);
    }, [onClose]);

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 transition-opacity animate-in fade-in duration-200" onClick={onClose}>
            <div
                className="bg-[#1c1c1e] w-full max-w-4xl h-[90vh] md:h-[80vh] rounded-xl md:rounded-2xl border border-white/10 shadow-2xl flex flex-col overflow-hidden relative animate-in zoom-in-95 duration-200"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="flex items-center justify-between p-4 border-b border-white/5 bg-[#1c1c1e]">
                    <div className="flex items-center gap-3">
                        <h3 className="text-xl font-bold text-white">{name}</h3>
                        <span className="text-sm font-mono text-gray-400">{symbol}</span>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-2 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                    >
                        <i className="fas fa-times text-xl"></i>
                    </button>
                </div>

                {/* Content - White background for Chart Image */}
                <div className="flex-1 bg-white relative">
                    <NaverChartWidget symbol={symbol} />
                </div>
            </div>
        </div>
    );
}

// 5. Theme Cloud Widget Component
function ThemeCloudWidget({ signals }: { signals: Signal[] }) {
    // 1. 테마 빈도 집계
    const themeCounts: Record<string, number> = {};
    if (signals && signals.length > 0) {
        signals.forEach(s => {
            if (s.themes) {
                s.themes.forEach(t => {
                    themeCounts[t] = (themeCounts[t] || 0) + 1;
                });
            }
        });
    }

    const entries = Object.entries(themeCounts);

    // 2. 상위 15개 추출
    const sortedThemes = entries
        .sort((a, b) => b[1] - a[1]) // 빈도순 내림차순
        .slice(0, 15);

    // 3. 가중치 기반 크기 계산 (빈 배열 처리)
    const maxCount = sortedThemes.length > 0 ? sortedThemes[0][1] : 0;
    const minCount = sortedThemes.length > 0 ? sortedThemes[sortedThemes.length - 1][1] : 0;

    // Design Spec: 6 types of gradients
    const gradients = [
        'from-cyan-400 to-blue-500',       // Cyber Blue
        'from-purple-400 to-pink-500',     // Neon Purple
        'from-amber-400 to-orange-500',    // Sunset
        'from-emerald-400 to-teal-500',    // Aurora
        'from-rose-400 to-red-500',        // Passion
        'from-indigo-400 to-violet-500',   // Deep Space
    ];

    return (
        <div className="bg-[#1c1c1e] border border-white/5 rounded-2xl p-5 backdrop-blur-md relative overflow-hidden group w-full h-full min-h-[140px] flex flex-col justify-center">
            {/* Background Decor */}
            <div className="absolute top-0 right-0 w-32 h-32 bg-indigo-500/10 rounded-full blur-2xl -translate-y-1/2 translate-x-1/2 pointer-events-none"></div>

            <div className="text-[10px] uppercase tracking-wider text-rose-500 font-bold mb-3 flex items-center gap-2 relative z-10">
                <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse"></span> TRENDING THEMES
            </div>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 relative z-10">
                {entries.length === 0 ? (
                    <span className="text-sm text-gray-500 italic">No themes available</span>
                ) : (
                    sortedThemes.map(([theme, count], idx) => {
                        const weight = maxCount === minCount ? 0 : (count - minCount) / (maxCount - minCount);

                        // Compact Styles
                        let fontSize = 'text-xs opacity-60';
                        let fontWeight = 'font-normal';

                        if (weight > 0.8) { fontSize = 'text-base opacity-100'; fontWeight = 'font-bold'; }
                        else if (weight > 0.5) { fontSize = 'text-sm opacity-90'; fontWeight = 'font-bold'; }
                        else if (weight > 0.3) { fontSize = 'text-xs opacity-80'; fontWeight = 'font-semibold'; }

                        const gradientIndex = (theme.length + idx) % gradients.length;
                        const gradient = gradients[gradientIndex];

                        return (
                            <span
                                key={theme}
                                className={`${fontSize} ${fontWeight}
                                            cursor-pointer transition-all duration-300
                                            bg-clip-text text-transparent bg-gradient-to-r ${gradient}
                                            hover:scale-105 hover:brightness-125
                                            select-none`}
                                title={`${count} items`}
                            >
                                {theme}
                            </span>
                        );
                    })
                )}
            </div>
        </div>
    );
}

export default function JonggaV2Page() {
    const [data, setData] = useState<ScreenerResult | null>(null);
    const [loading, setLoading] = useState(true);
    const [dates, setDates] = useState<string[]>([]);
    const [selectedDate, setSelectedDate] = useState<string>('latest');
    const [isUserSelected, setIsUserSelected] = useState(false); // 사용자가 직접 날짜를 선택했는지

    // 차트 모달 상태
    const [chartModal, setChartModal] = useState<{ isOpen: boolean, symbol: string, name: string }>({
        isOpen: false, symbol: '', name: ''
    });

    // 1. Load Available Dates
    useEffect(() => {
        fetch(`${API_BASE}/api/kr/jongga-v2/dates`, { headers: API_HEADERS })
            .then((res) => res.json())
            .then((data) => {
                if (Array.isArray(data)) {
                    setDates(data);
                } else if (data?.dates && Array.isArray(data.dates)) {
                    setDates(data.dates);
                }
            })
            .catch((err) => console.error('Failed to fetch dates:', err));
    }, []);

    // 2. Load Data (Latest or Specific Date)
    const fetchData = useCallback(async (silent = false) => {
        if (!silent) setLoading(true);
        try {
            let url = `${API_BASE}/api/kr/jongga-v2/latest`;
            if (isUserSelected && selectedDate !== 'latest') {
                url = `${API_BASE}/api/kr/jongga-v2/history/${selectedDate}`;
            }

            const res = await fetch(url, { headers: API_HEADERS });
            const result = await res.json();

            // Fallback: latest에 시그널이 없으면 과거 날짜에서 시그널 탐색
            if (!isUserSelected && (!result?.signals || result.signals.length === 0) && dates.length > 0) {
                const latestDateStr = result?.date?.replace(/-/g, '') || '';
                for (const d of dates) {
                    if (d === latestDateStr) continue;
                    try {
                        const histRes = await fetch(`${API_BASE}/api/kr/jongga-v2/history/${d}`, { headers: API_HEADERS });
                        const histData = await histRes.json();
                        if (histData?.signals && histData.signals.length > 0) {
                            setData(histData);
                            setLoading(false);
                            return;
                        }
                    } catch { /* skip */ }
                }
            }
            setData(result);
        } catch (err) {
            console.error('Failed to fetch data:', err);
            if (!silent) setData(null);
        } finally {
            setLoading(false);
        }
    }, [selectedDate, dates, isUserSelected]);

    useEffect(() => {
        fetchData(false);
    }, [selectedDate, dates, fetchData]);

    // 사일런트 자동 갱신 (60초 fallback) - 사용자가 직접 날짜를 선택하지 않은 경우에만
    const silentRefresh = useCallback(async () => {
        if (isUserSelected) return;
        await fetchData(true);
    }, [fetchData, isUserSelected]);
    useAutoRefresh(silentRefresh, 60000, !isUserSelected);

    // 스마트 갱신 (15초 버전 체크) - 파일 변경 감지 시에만 refetch (로컬+모바일 동시 갱신)
    useSmartRefresh(silentRefresh, ['jongga_v2_latest.json'], 15000, !isUserSelected);
    usePullToRefreshRegister(useCallback(async () => { await fetchData(false); }, [fetchData]));

    if (loading) {
        return (
            <div className="flex h-96 items-center justify-center text-gray-500">
                <div className="relative w-16 h-16">
                    <div className="absolute top-0 left-0 w-full h-full border-4 border-blue-500/30 rounded-full animate-ping"></div>
                    <div className="absolute top-0 left-0 w-full h-full border-4 border-t-blue-500 rounded-full animate-spin"></div>
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-4 md:space-y-8 pb-12">
            {/* 1. Header Section (Robust Flex Layout) */}
            <div className="flex flex-col lg:flex-row items-end justify-between gap-4 md:gap-8 mb-4 md:mb-8">
                <div className="w-full lg:w-2/3">
                    <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-indigo-500/20 bg-indigo-500/5 text-xs text-indigo-400 font-medium mb-4">
                        <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-ping"></span>
                        AI Powered Strategy
                    </div>
                    <h2 className="text-2xl md:text-5xl font-bold tracking-tighter text-white leading-tight mb-2">
                        Closing <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-cyan-400">Bet V2</span>
                    </h2>
                    <p className="text-gray-400 text-sm md:text-lg">
                        Multi-AI Consensus (Gemini + GPT-4o) + DART Disclosure + Supply Trend
                    </p>
                </div>

                {/* Theme Cloud Widget (Right Side) - Always visible */}
                <div className="w-full lg:w-1/3 flex justify-end">
                    <ThemeCloudWidget signals={data?.signals || []} />
                </div>
            </div>

            {/* 2. Controls & Stats */}
            <div className="flex flex-col md:flex-row md:items-end justify-between gap-3 md:gap-6 pb-4 md:pb-6 border-b border-white/5">
                <div className="flex gap-6">
                    <StatBox label="Candidates" value={data?.total_candidates || 0} />
                    <StatBox label="Signals" value={data?.filtered_count || 0} highlight />
                    <DataStatusBox updatedAt={data?.updated_at} />
                </div>

                <div className="flex items-center gap-3">
                    <select
                        value={selectedDate}
                        onChange={(e) => {
                            const val = e.target.value;
                            setSelectedDate(val);
                            setIsUserSelected(val !== 'latest');
                        }}
                        className="bg-[#1c1c1e] border border-white/10 text-gray-300 rounded-xl px-4 py-2 text-sm focus:ring-2 focus:ring-indigo-500/50 outline-none transition-all hover:border-white/20"
                    >
                        <option value="latest">Latest Report</option>
                        {dates.map((d) => (
                            <option key={d} value={d}>
                                {d.length === 8 ? `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}` : d}
                            </option>
                        ))}
                    </select>
                    <button
                        onClick={() => setSelectedDate(selectedDate)}
                        className="p-2 bg-[#1c1c1e] border border-white/10 rounded-xl hover:bg-white/5 text-gray-400 hover:text-white transition-all"
                        title="Refresh"
                    >
                        <i className="fas fa-sync-alt"></i> ↻
                    </button>
                </div>
            </div>

            {/* 3. Multi-AI Consensus Top Picks */}
            {data?.claude_picks?.picks && data.claude_picks.picks.length > 0 && (
                <AIConsensusSection aiPicks={data.claude_picks} />
            )}

            {/* 4. Signal Grid */}
            <div className="grid grid-cols-1 gap-3 md:gap-6">
                {!data || !data.signals || data.signals.length === 0 ? (
                    <div className="bg-[#1c1c1e] rounded-2xl p-16 text-center border border-white/5 flex flex-col items-center">
                        <div className="w-16 h-16 bg-white/5 rounded-full flex items-center justify-center mb-4">
                            <span className="text-3xl opacity-30">💤</span>
                        </div>
                        <h3 className="text-xl font-bold text-gray-300">No Signals Found</h3>
                        <p className="text-gray-500 mt-2 max-w-md">
                            Today&apos;s market conditions did not meet the strict AI & Supply criteria.
                        </p>
                    </div>
                ) : (
                    data.signals.map((signal, idx) => (
                        <SignalCard
                            key={signal.stock_code}
                            signal={signal}
                            index={idx}
                            onOpenChart={() => setChartModal({ isOpen: true, symbol: signal.stock_code, name: signal.stock_name })}
                        />
                    ))
                )}
            </div>

            <div className="text-center text-xs text-gray-600 pt-8">
                Engine: v2.2.0 (Multi-AI Consensus + DART) • Updated: {data?.updated_at || '-'}
            </div>

            {/* Chart Modal */}
            {chartModal.isOpen && (
                <ChartModal
                    symbol={chartModal.symbol}
                    name={chartModal.name}
                    onClose={() => setChartModal({ ...chartModal, isOpen: false })}
                />
            )}
        </div>
    );
}

function DataStatusBox({ updatedAt }: { updatedAt?: string }) {
    const [updating, setUpdating] = useState(false);

    if (!updatedAt && !updating) return <StatBox label="Data Status" value={0} customValue="LOADING..." />;

    const updateDate = updatedAt ? new Date(updatedAt) : new Date();
    const today = new Date();
    const isToday = updatedAt ? (
        updateDate.getDate() === today.getDate() &&
        updateDate.getMonth() === today.getMonth() &&
        updateDate.getFullYear() === today.getFullYear()
    ) : false;

    const timeStr = updateDate.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });

    const handleUpdate = async () => {
        if (updating) return;
        if (!confirm('종가베팅 v2 분석 엔진을 전체 실행하시겠습니까? (수분 소요될 수 있음)')) return;

        setUpdating(true);
        try {
            const res = await fetch(`${API_BASE}/api/kr/jongga-v2/run`, { method: 'POST', headers: API_HEADERS });
            if (res.ok) {
                alert('전체 분석이 완료되었습니다!');
                window.location.reload();
            } else {
                alert('엔진 실행 실패. 서버 로그를 확인하세요.');
            }
        } catch (error) {
            console.error(error);
            alert('업데이트 요청 중 오류 발생');
        } finally {
            setUpdating(false);
        }
    }

    return (
        <div className="flex flex-col">
            <span className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-1 flex items-center gap-2">
                Data Status
                <button
                    onClick={handleUpdate}
                    disabled={updating}
                    className={`p-1 rounded bg-white/5 hover:bg-white/10 transition-all ${updating ? 'animate-spin text-indigo-400' : 'text-gray-500 hover:text-white'}`}
                    title="Run Engine V2 (Full Update)"
                >
                    <i className="fas fa-sync-alt text-[10px]"></i>
                </button>
            </span>
            <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${(isToday && !updating) ? 'bg-emerald-500 animate-pulse' : 'bg-gray-500'}`}></span>
                <span className={`text-xl font-mono font-bold ${(isToday && !updating) ? 'text-emerald-400' : 'text-gray-400'}`}>
                    {updating ? 'RUNNING...' : (isToday ? 'UPDATED' : 'OLD DATA')}
                </span>
            </div>
            <span className="text-[10px] text-gray-600 font-mono mt-0.5">{updating ? 'Please wait...' : timeStr}</span>
        </div>
    )
}

function StatBox({ label, value, highlight = false, customValue }: { label: string, value: number, highlight?: boolean, customValue?: string }) {
    return (
        <div className="flex flex-col">
            <span className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-1">{label}</span>
            <span className={`text-2xl font-mono font-bold ${highlight ? 'text-indigo-400' : 'text-white'}`}>
                {customValue || value}
            </span>
        </div>
    )
}

function SignalCard({ signal, index, onOpenChart }: { signal: Signal, index: number, onOpenChart: () => void }) {
    // 등급별 스타일
    const gradeStyles: Record<string, { bg: string, text: string, border: string, glow: string }> = {
        S: { bg: 'bg-indigo-500/10', text: 'text-indigo-400', border: 'border-indigo-500/30', glow: 'shadow-indigo-500/20' },
        A: { bg: 'bg-rose-500/10', text: 'text-rose-400', border: 'border-rose-500/30', glow: 'shadow-rose-500/20' },
        B: { bg: 'bg-blue-500/10', text: 'text-blue-400', border: 'border-blue-500/30', glow: 'shadow-blue-500/30' },
        C: { bg: 'bg-gray-500/10', text: 'text-gray-400', border: 'border-gray-500/30', glow: 'shadow-gray-500/20' },
    };

    const style = gradeStyles[signal.grade] || gradeStyles.B;

    // 날짜 포맷팅 헬퍼 (2025-01-15T12:00 -> 01.15)
    const formatDate = (isoString: string) => {
        if (!isoString) return '';
        const d = new Date(isoString);
        return `${(d.getMonth() + 1).toString().padStart(2, '0')}.${d.getDate().toString().padStart(2, '0')}`;
    };

    const handleCopyKakao = async () => {
        const price = signal.current_price || signal.entry_price || 0;

        const text = `🚀 [종가베팅 V2] ${signal.stock_name} (${signal.stock_code})
⭐️ ${signal.grade}급 시그널 / 점수 ${signal.score?.total || 0}점

📊 현재가: ${price.toLocaleString()}원 (${(signal.change_pct || 0) > 0 ? '+' : ''}${signal.change_pct || 0}%)
🎯 목표가: ${(signal.target_price || 0).toLocaleString()}원 (+5%)
🛡️ 손절가: ${(signal.stop_price || 0).toLocaleString()}원 (-3%)

💰 거래대금: ${((signal.trading_value || 0) / 100000000).toFixed(0)}억
🟢 외인: ${((signal.foreign_5d || 0) / 1000).toFixed(0)}K
🟠 기관: ${((signal.inst_5d || 0) / 1000).toFixed(0)}K

🤖 AI 분석
"${signal.score?.llm_reason || '분석 내용 없음'}"`;

        // 1. 네이티브 공유 (Mac, 모바일 등)
        if (navigator.share) {
            try {
                await navigator.share({
                    title: `[종가베팅] ${signal.stock_name}`,
                    text: text,
                });
                return; // 공유 성공 시 종료
            } catch (err) {
                // 사용자가 취소했거나 에러 발생 시 아래 복사 로직으로 진행
                console.log('Share canceled or failed:', err);
            }
        }

        // 2. 클립보드 복사 (Fallback)
        navigator.clipboard.writeText(text).then(() => {
            alert('📋 텍스트가 복사되었습니다!\n카카오톡에 붙여넣기(Ctrl+V) 하세요.');
        });
    };

    return (
        <div
            className={`relative rounded-2xl border ${style.border} bg-[#1c1c1e] overflow-hidden transition-all duration-300 hover:scale-[1.01] hover:border-opacity-50 group`}
            style={{ animationDelay: `${index * 0.1}s`, animationFillMode: 'both' }}
        >
            {/* Background Glow */}
            <div className={`absolute top-0 right-0 w-64 h-64 ${style.bg} rounded-full blur-[60px] -translate-y-1/2 translate-x-1/2 opacity-20 group-hover:opacity-30 transition-opacity`}></div>

            <div className="flex flex-col lg:flex-row relative z-10">

                {/* Left: Info & Grade */}
                <div className="p-4 md:p-6 lg:w-1/3 border-b lg:border-b-0 lg:border-r border-white/5 flex flex-col justify-between">
                    <div>
                        <div className="flex items-center justify-between mb-4">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${style.border} ${style.bg} ${style.text}`}>
                                {signal.grade} GRADE
                            </span>
                            <span className="text-xs text-gray-500 font-mono">#{index + 1}</span>
                        </div>

                        <div className="flex items-center justify-between">
                            <div>
                                <h3 className="text-2xl font-bold text-white leading-none mb-1">
                                    {signal.stock_name}
                                </h3>
                                <div className="text-sm text-gray-400 font-mono">{signal.stock_code}</div>
                            </div>
                            <div className={`text-4xl font-black ${style.text} opacity-20`}>{signal.grade}</div>
                        </div>

                        <div className="mt-6 flex flex-wrap gap-2">
                            {/* Tags */}
                            {signal.themes && signal.themes.length > 0 && signal.themes.map((theme, i) => (
                                <span
                                    key={i}
                                    className="px-2 py-1 rounded bg-violet-500/10 border border-violet-500/20 text-violet-400 text-[10px] font-bold"
                                >
                                    {theme}
                                </span>
                            ))}
                            {signal.checklist.is_new_high && (
                                <span className="px-2 py-1 rounded bg-rose-500/10 border border-rose-500/20 text-rose-400 text-[10px] font-bold">NEW HIGH</span>
                            )}
                            {signal.checklist.supply_positive && (
                                <span className="px-2 py-1 rounded bg-amber-500/10 border border-amber-500/20 text-amber-400 text-[10px] font-bold">INST BUY</span>
                            )}
                            {signal.checklist.has_news && (
                                <span className="px-2 py-1 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-[10px] font-bold">NEWS</span>
                            )}
                            {signal.checklist.has_disclosure && signal.checklist.disclosure_types && signal.checklist.disclosure_types.map((dtype, i) => (
                                <span key={`disc-${i}`} className="px-2 py-1 rounded bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 text-[10px] font-bold">
                                    📋 {dtype}
                                </span>
                            ))}
                        </div>

                        {/* 가격 정보 */}
                        <div className="mt-6 space-y-1">
                            <div className="flex justify-between items-center text-sm">
                                <span className="text-gray-400">Current</span>
                                <span className="font-mono font-bold text-white">
                                    {(signal.current_price || signal.entry_price || 0).toLocaleString()}
                                    <span className={`ml-1 text-xs ${(signal.change_pct || 0) > 0 ? 'text-rose-400' : 'text-blue-400'}`}>
                                        ({(signal.change_pct || 0) > 0 ? '+' : ''}{signal.change_pct || 0}%)
                                    </span>
                                </span>
                            </div>
                            <div className="flex justify-between items-center text-xs">
                                <span className="text-gray-500">Target</span>
                                <span className="font-mono text-rose-400">{(signal.target_price || 0).toLocaleString()}</span>
                            </div>
                            <div className="flex justify-between items-center text-xs">
                                <span className="text-gray-500">Stop</span>
                                <span className="font-mono text-blue-400">{(signal.stop_price || 0).toLocaleString()}</span>
                            </div>
                        </div>

                        {/* 거래대금 / 외인 / 기관 데이터 */}
                        <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs">
                            <div className="bg-black/20 rounded-lg px-2 py-1.5 border border-white/5">
                                <div className="text-gray-500 text-[10px] mb-0.5">거래대금</div>
                                <div className="text-white font-mono font-bold">
                                    {(signal.trading_value / 100_000_000).toFixed(0)}억
                                </div>
                            </div>
                            <div className="bg-black/20 rounded-lg px-2 py-1.5 border border-white/5">
                                <div className="text-gray-500 text-[10px] mb-0.5">외인 5일</div>
                                <div className={`font-mono font-bold ${signal.foreign_5d >= 0 ? 'text-rose-400' : 'text-blue-400'}`}>
                                    {signal.foreign_5d >= 0 ? '+' : ''}{(signal.foreign_5d / 1000).toFixed(0)}K
                                </div>
                            </div>
                            <div className="bg-black/20 rounded-lg px-2 py-1.5 border border-white/5">
                                <div className="text-gray-500 text-[10px] mb-0.5">기관 5일</div>
                                <div className={`font-mono font-bold ${signal.inst_5d >= 0 ? 'text-rose-400' : 'text-blue-400'}`}>
                                    {signal.inst_5d >= 0 ? '+' : ''}{(signal.inst_5d / 1000).toFixed(0)}K
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="mt-4 flex gap-2">
                        <button
                            onClick={onOpenChart}
                            className="flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-sm text-gray-300 transition-all hover:text-white w-fit group-hover:border-indigo-500/30"
                        >
                            <i className="fas fa-chart-line text-indigo-400"></i>
                            <span>View Chart</span>
                        </button>

                        <button
                            onClick={handleCopyKakao}
                            className="flex items-center gap-2 px-4 py-2 bg-[#FEE500] hover:bg-[#FDD835] text-black border border-[#FEE500] rounded-lg text-sm font-bold transition-all w-fit opacity-90 hover:opacity-100"
                        >
                            <i className="fas fa-comment"></i>
                            <span>Kakao</span>
                        </button>
                    </div>
                </div>

                {/* Middle: AI Analysis + News References */}
                <div className="p-4 md:p-6 lg:w-5/12 border-b lg:border-b-0 lg:border-r border-white/5 flex flex-col">
                    <div className="mb-3 flex items-center gap-2">
                        <span className={`w-1.5 h-1.5 rounded-full ${
                            signal.score.llm_source?.includes('claude') ? 'bg-gradient-to-r from-orange-400 to-amber-400' :
                            signal.score.llm_source?.includes('openai') ? 'bg-gradient-to-r from-emerald-400 to-green-400' :
                            'bg-gradient-to-r from-blue-400 to-indigo-400'
                        }`}></span>
                        <span className="text-xs font-bold text-gray-300">
                            {signal.score.llm_source?.includes('claude') ? 'Claude AI Analysis' :
                             signal.score.llm_source?.includes('openai') ? 'OpenAI Analysis' :
                             'Gemini 3.0 Analysis'}
                        </span>
                    </div>
                    {/* Analysis Text */}
                    <div className="bg-black/20 rounded-xl p-5 text-sm text-gray-300 leading-relaxed border border-white/5 mb-4">
                        {signal.score.llm_reason ? (
                            `"${signal.score.llm_reason}"`
                        ) : (
                            <span className="text-gray-600 italic">No analysis available.</span>
                        )}
                    </div>

                    {/* News References */}
                    {signal.news_items && signal.news_items.length > 0 && (
                        <div className="mt-auto">
                            <div className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-2 flex items-center gap-1">
                                <i className="fas fa-quote-left"></i> References
                            </div>
                            <div className="space-y-1.5">
                                {signal.news_items.slice(0, 3).map((news, i) => (
                                    <a
                                        key={i}
                                        href={news.url || '#'}
                                        target="_blank"
                                        rel="noreferrer"
                                        className="block text-xs text-gray-400 hover:text-indigo-400 hover:bg-white/5 p-1.5 rounded transition-colors truncate"
                                    >
                                        <span className="text-gray-500 font-mono mr-2">[{news.source || 'News'}]</span>
                                        <span className="mr-2">{news.title}</span>
                                        <span className="text-gray-600 text-[10px] ml-auto">({formatDate(news.published_at)})</span>
                                    </a>
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                {/* Right: Score Breakdown */}
                <div className="p-4 md:p-6 lg:w-1/4 bg-white/[0.02] flex flex-col justify-center">
                    <div className="text-center mb-3 md:mb-6">
                        <div className="inline-flex items-baseline gap-1">
                            <span className="text-3xl md:text-4xl font-mono font-bold text-white">{signal.score.total}</span>
                            <span className="text-sm text-gray-500">/ 17</span>
                        </div>
                        <div className="text-[10px] text-gray-500 mt-1 uppercase tracking-wider">Total Score</div>
                    </div>

                    {/* Mobile compact score grid */}
                    <div className="md:hidden">
                        <div className="grid grid-cols-4 gap-1">
                            {[
                                { label: 'News', score: signal.score.news, max: 3 },
                                { label: 'Supply', score: signal.score.supply, max: 2 },
                                { label: 'Chart', score: signal.score.chart, max: 2 },
                                { label: 'Volume', score: signal.score.volume, max: 3 },
                                { label: 'Candle', score: signal.score.candle, max: 1 },
                                { label: 'Consol', score: signal.score.consolidation, max: 1 },
                                { label: 'DART', score: signal.score.disclosure || 0, max: 2 },
                                { label: 'Analyst', score: signal.score.analyst || 0, max: 3 },
                            ].map((item) => (
                                <div key={item.label} className="text-center p-1.5 rounded-lg bg-white/[0.03] border border-white/5">
                                    <div className="text-[9px] text-gray-500 leading-none mb-1">{item.label}</div>
                                    <div className="text-xs font-mono font-bold">
                                        <span className={item.score >= item.max ? 'text-emerald-400' : item.score > 0 ? 'text-white' : 'text-gray-600'}>{item.score}</span>
                                        <span className="text-gray-600">/{item.max}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                    {/* Desktop score bars */}
                    <div className="hidden md:block space-y-2.5">
                        <ScoreBar label="News" score={signal.score.news} max={3} />
                        <ScoreBar label="Supply" score={signal.score.supply} max={2} />
                        <ScoreBar label="Chart" score={signal.score.chart} max={2} />
                        <ScoreBar label="Volume" score={signal.score.volume} max={3} />
                        <ScoreBar label="Candle" score={signal.score.candle} max={1} />
                        <ScoreBar label="Consol" score={signal.score.consolidation} max={1} />
                        <ScoreBar label="DART" score={signal.score.disclosure || 0} max={2} />
                        <ScoreBar label="Analyst" score={signal.score.analyst || 0} max={3} />
                    </div>
                </div>

            </div>
        </div>
    );
}

function AIConsensusSection({ aiPicks }: { aiPicks: AIPicks }) {
    const confidenceStyles: Record<string, { bg: string; text: string; border: string }> = {
        HIGH: { bg: 'bg-rose-500/10', text: 'text-rose-400', border: 'border-rose-500/20' },
        MEDIUM: { bg: 'bg-amber-500/10', text: 'text-amber-400', border: 'border-amber-500/20' },
        LOW: { bg: 'bg-gray-500/10', text: 'text-gray-400', border: 'border-gray-500/20' },
    };

    const sourceBadge = (source?: string) => {
        if (source === 'consensus') return { label: 'CONSENSUS', bg: 'bg-violet-500/15', text: 'text-violet-400', border: 'border-violet-500/25' };
        if (source === 'gemini_only') return { label: 'GEMINI', bg: 'bg-blue-500/15', text: 'text-blue-400', border: 'border-blue-500/25' };
        if (source === 'openai_only') return { label: 'GPT-4o', bg: 'bg-emerald-500/15', text: 'text-emerald-400', border: 'border-emerald-500/25' };
        return { label: 'AI', bg: 'bg-gray-500/15', text: 'text-gray-400', border: 'border-gray-500/25' };
    };

    return (
        <div className="bg-[#1c1c1e] rounded-2xl border border-violet-500/20 overflow-hidden relative">
            {/* Background glow */}
            <div className="absolute top-0 right-0 w-64 h-64 bg-violet-500/5 rounded-full blur-[80px] -translate-y-1/2 translate-x-1/2 pointer-events-none"></div>

            {/* Header */}
            <div className="p-5 pb-0 relative z-10">
                <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-violet-500/20 bg-violet-500/5 text-xs text-violet-400 font-medium">
                            <span className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse"></span>
                            Multi-AI Consensus Picks
                        </div>
                        {aiPicks.consensus_count !== undefined && (
                            <span className="text-[10px] text-violet-400 font-mono font-bold">
                                {aiPicks.consensus_count} consensus
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-2">
                        {aiPicks.models && aiPicks.models.map((m, i) => (
                            <span key={i} className="text-[10px] text-gray-600 font-mono bg-white/5 px-1.5 py-0.5 rounded">{m}</span>
                        ))}
                        {aiPicks.generated_at && (
                            <span className="text-[10px] text-gray-600 font-mono">
                                {new Date(aiPicks.generated_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}
                            </span>
                        )}
                    </div>
                </div>

                {/* Market View */}
                {aiPicks.market_view && (
                    <p className="text-sm text-gray-400 leading-relaxed mb-3">{aiPicks.market_view}</p>
                )}

                {/* Hot Themes */}
                {aiPicks.top_themes && aiPicks.top_themes.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mb-4">
                        {aiPicks.top_themes.map((theme, i) => (
                            <span key={i} className="px-2 py-0.5 rounded-full bg-violet-500/10 border border-violet-500/15 text-violet-400 text-[10px] font-bold">
                                {theme}
                            </span>
                        ))}
                    </div>
                )}
            </div>

            {/* Picks List */}
            <div className="px-5 pb-5 relative z-10">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {aiPicks.picks.map((pick) => {
                        const cs = confidenceStyles[pick.confidence] || confidenceStyles.LOW;
                        const sb = sourceBadge(pick.source);
                        return (
                            <div key={pick.stock_code} className={`bg-black/20 rounded-xl p-4 border ${pick.source === 'consensus' ? 'border-violet-500/20 hover:border-violet-500/40' : 'border-white/5 hover:border-white/10'} transition-all`}>
                                <div className="flex items-center justify-between mb-2">
                                    <div className="flex items-center gap-2">
                                        <span className="text-violet-400 font-mono text-xs font-bold">#{pick.rank}</span>
                                        <span className="text-white font-bold text-sm">{pick.stock_name}</span>
                                    </div>
                                    <div className="flex items-center gap-1">
                                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${sb.bg} ${sb.text} ${sb.border}`}>
                                            {sb.label}
                                        </span>
                                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${cs.bg} ${cs.text} ${cs.border}`}>
                                            {pick.confidence}
                                        </span>
                                    </div>
                                </div>
                                <p className="text-xs text-gray-400 leading-relaxed mb-2 line-clamp-3">{pick.reason}</p>
                                <div className="flex items-center justify-between text-[10px]">
                                    <span className="text-gray-500">Risk: <span className="text-amber-400">{pick.risk}</span></span>
                                    <span className="text-gray-500">Return: <span className="text-emerald-400">{pick.expected_return}</span></span>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}

function ScoreBar({ label, score, max }: { label: string, score: number, max: number }) {
    const pct = (score / max) * 100;
    return (
        <div className="flex items-center gap-3 text-xs">
            <span className="w-12 text-gray-400 text-right">{label}</span>
            <div className="flex-1 h-1.5 bg-gray-700/50 rounded-full overflow-hidden border border-white/5">
                <div
                    className={`h-full rounded-full transition-all duration-500 ${pct >= 100 ? 'bg-gradient-to-r from-emerald-500 to-green-400' : pct >= 50 ? 'bg-gradient-to-r from-yellow-500 to-orange-400' : 'bg-gray-600'}`}
                    style={{ width: `${pct}%` }}
                ></div>
            </div>
            <span className="w-8 text-right font-mono text-gray-300 transform scale-90">
                <span className="text-white font-bold">{score}</span>
                <span className="text-gray-600">/{max}</span>
            </span>
        </div>
    )
}
