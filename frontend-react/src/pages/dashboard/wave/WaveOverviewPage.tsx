import { useState, useCallback, useEffect } from 'react';
import { fetchAPI } from '@/lib/api';
import PatternChart, { ChartDataPoint, PatternOverlay, PatternPoint } from '@/components/wave/PatternChart';

/* ── Types ── */

interface ScreenerSignal {
    ticker: string;
    name: string;
    market: string;
    price: number;
    avg_volume: number;
    pattern_count: number;
    best_pattern: {
        pattern_class: string;
        wave_type: string;
        wave_label: string;
        neckline_price: number;
        confidence: number;
        completion_pct: number;
        neckline_distance_pct: number;
        bullish_bias: number;
        volume_confirmed: boolean;
        points: { date: string; price: number; type: string }[];
    };
}

interface ScreenerResult {
    date: string | null;
    updated_at: string | null;
    market: string;
    scan_count: number;
    signal_count: number;
    total_signal_count: number;
    processing_time_sec: number;
    signals: ScreenerSignal[];
}

interface WaveDetectResult {
    ticker: string;
    market: string;
    patterns: PatternOverlay[];
    chart_data: ChartDataPoint[];
    turning_points: PatternPoint[];
    pattern_count: number;
}

/* ── Filters ── */

type FilterMode = 'all' | 'W' | 'M';
type SortMode = 'confidence' | 'neckline' | 'completion';

const MARKET_TABS = [
    { key: 'KR', label: 'KR', placeholder: '종목코드 (예: 005930)' },
    { key: 'US', label: 'US', placeholder: 'Ticker (e.g. AAPL)' },
];

/* ── Component ── */

export default function WaveOverviewPage() {
    // Screener state
    const [screener, setScreener] = useState<ScreenerResult | null>(null);
    const [screenerLoading, setScreenerLoading] = useState(true);
    const [filter, setFilter] = useState<FilterMode>('all');
    const [sortMode, setSortMode] = useState<SortMode>('confidence');

    // Detail state (when user clicks a signal or searches)
    const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
    const [detailResult, setDetailResult] = useState<WaveDetectResult | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [selectedIdx, setSelectedIdx] = useState(0);

    // Search state
    const [market, setMarket] = useState('KR');
    const [searchTicker, setSearchTicker] = useState('');
    const [searchError, setSearchError] = useState('');

    // Load screener on mount
    useEffect(() => {
        loadScreener();
    }, []);

    const loadScreener = async () => {
        setScreenerLoading(true);
        try {
            const data = await fetchAPI<ScreenerResult>('/api/wave/screener/latest');
            setScreener(data);
        } catch {
            // No data yet — acceptable
        } finally {
            setScreenerLoading(false);
        }
    };

    // Load detail chart for a ticker
    const loadDetail = useCallback(async (ticker: string, mkt: string = 'KR') => {
        setDetailLoading(true);
        setSearchError('');
        setSelectedTicker(ticker);
        setSelectedIdx(0);
        try {
            const data = await fetchAPI<WaveDetectResult>(
                `/api/wave/detect/${ticker}?market=${mkt}&lookback=200`
            );
            setDetailResult(data);
        } catch (e: any) {
            setSearchError(e.message || '패턴 감지 실패');
            setDetailResult(null);
        } finally {
            setDetailLoading(false);
        }
    }, []);

    const handleSearch = () => {
        if (!searchTicker.trim()) return;
        loadDetail(searchTicker.trim(), market);
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter') handleSearch();
    };

    const closeDetail = () => {
        setSelectedTicker(null);
        setDetailResult(null);
        setSearchError('');
    };

    // Filtered & sorted signals
    const filteredSignals = (screener?.signals || [])
        .filter(s => filter === 'all' || s.best_pattern.pattern_class === filter)
        .sort((a, b) => {
            if (sortMode === 'confidence') return b.best_pattern.confidence - a.best_pattern.confidence;
            if (sortMode === 'neckline') return Math.abs(a.best_pattern.neckline_distance_pct) - Math.abs(b.best_pattern.neckline_distance_pct);
            return b.best_pattern.completion_pct - a.best_pattern.completion_pct;
        });

    const pat = detailResult?.patterns?.[selectedIdx];

    return (
        <div className="space-y-5">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-cyan-500/20 flex items-center justify-center">
                        <i className="fas fa-wave-square text-cyan-400" />
                    </div>
                    <div>
                        <h1 className="text-xl font-black text-white">W Pattern</h1>
                        <p className="text-xs text-gray-500">AI 차트 패턴 자동 인식 · M&W 파동 분석</p>
                    </div>
                </div>
                {screener?.updated_at && (
                    <div className="text-[10px] text-gray-600">
                        Updated: {screener.updated_at}
                    </div>
                )}
            </div>

            {/* Search Bar */}
            <div className="bg-[#1c1c1e] rounded-2xl border border-white/5 p-3">
                <div className="flex items-center gap-2">
                    <div className="flex bg-black/40 rounded-lg p-0.5">
                        {MARKET_TABS.map(tab => (
                            <button
                                key={tab.key}
                                onClick={() => setMarket(tab.key)}
                                className={`px-2.5 py-1 text-xs font-bold rounded-md transition-all ${
                                    market === tab.key
                                        ? 'bg-cyan-500 text-black'
                                        : 'text-gray-500 hover:text-white'
                                }`}
                            >
                                {tab.label}
                            </button>
                        ))}
                    </div>
                    <input
                        type="text"
                        value={searchTicker}
                        onChange={e => setSearchTicker(e.target.value.toUpperCase())}
                        onKeyDown={handleKeyDown}
                        placeholder={MARKET_TABS.find(t => t.key === market)?.placeholder}
                        className="flex-1 bg-black/40 border border-white/10 rounded-lg px-3 py-1.5 text-white text-sm placeholder:text-gray-600 focus:outline-none focus:border-cyan-500/50"
                    />
                    <button
                        onClick={handleSearch}
                        disabled={detailLoading || !searchTicker.trim()}
                        className="px-3 py-1.5 bg-cyan-500 text-black font-bold text-xs rounded-lg hover:bg-cyan-400 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                    >
                        {detailLoading ? (
                            <span className="flex items-center gap-1.5">
                                <div className="w-3 h-3 border-2 border-black border-t-transparent rounded-full animate-spin" />
                                분석중
                            </span>
                        ) : '검색'}
                    </button>
                </div>
            </div>

            {/* Error */}
            {searchError && (
                <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-3 text-red-400 text-sm">
                    {searchError}
                </div>
            )}

            {/* Detail Chart (when a ticker is selected) */}
            {(selectedTicker && detailResult) && (
                <div className="bg-[#1c1c1e] rounded-2xl border border-cyan-500/20 p-4 space-y-3">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <span className="text-lg font-black text-white">{detailResult.ticker}</span>
                            <span className="text-xs text-gray-500">{detailResult.market}</span>
                            {pat && (
                                <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                                    pat.pattern_class === 'W'
                                        ? 'bg-cyan-500/20 text-cyan-400'
                                        : 'bg-pink-500/20 text-pink-400'
                                }`}>
                                    {pat.wave_label}
                                </span>
                            )}
                            {pat && (
                                <span className={`text-xs font-bold ${
                                    pat.confidence >= 70 ? 'text-green-400' :
                                    pat.confidence >= 50 ? 'text-yellow-400' : 'text-gray-400'
                                }`}>{pat.confidence}점</span>
                            )}
                        </div>
                        <button
                            onClick={closeDetail}
                            className="text-gray-500 hover:text-white text-xs px-2 py-1 rounded-lg hover:bg-white/10 transition-colors"
                        >
                            <i className="fas fa-times mr-1" />닫기
                        </button>
                    </div>
                    <PatternChart
                        chartData={detailResult.chart_data}
                        patterns={detailResult.patterns}
                        turningPoints={detailResult.turning_points}
                        selectedPatternIdx={selectedIdx}
                        height={350}
                    />
                    {/* Pattern selector pills */}
                    {detailResult.patterns.length > 1 && (
                        <div className="flex gap-2 flex-wrap">
                            {detailResult.patterns.map((p, i) => (
                                <button
                                    key={i}
                                    onClick={() => setSelectedIdx(i)}
                                    className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all ${
                                        selectedIdx === i
                                            ? 'bg-cyan-500 text-black'
                                            : 'bg-white/5 text-gray-400 hover:bg-white/10'
                                    }`}
                                >
                                    {p.wave_label} ({p.confidence}점)
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Screener Stats */}
            {screener && screener.date && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <StatCard label="스캔 종목" value={screener.scan_count.toLocaleString()} icon="fa-search" />
                    <StatCard label="패턴 감지" value={`${screener.total_signal_count}개`} icon="fa-wave-square" color="text-cyan-400" />
                    <StatCard
                        label="W (Bullish)"
                        value={`${(screener.signals || []).filter(s => s.best_pattern.pattern_class === 'W').length}개`}
                        icon="fa-arrow-up"
                        color="text-green-400"
                    />
                    <StatCard
                        label="M (Bearish)"
                        value={`${(screener.signals || []).filter(s => s.best_pattern.pattern_class === 'M').length}개`}
                        icon="fa-arrow-down"
                        color="text-red-400"
                    />
                </div>
            )}

            {/* Filters & Sort */}
            {screener && screener.signals.length > 0 && (
                <div className="flex items-center justify-between">
                    <div className="flex gap-1.5">
                        {(['all', 'W', 'M'] as FilterMode[]).map(f => (
                            <button
                                key={f}
                                onClick={() => setFilter(f)}
                                className={`px-3 py-1 text-xs font-bold rounded-lg transition-all ${
                                    filter === f
                                        ? f === 'W' ? 'bg-cyan-500/20 text-cyan-400'
                                        : f === 'M' ? 'bg-pink-500/20 text-pink-400'
                                        : 'bg-white/10 text-white'
                                        : 'text-gray-500 hover:text-white hover:bg-white/5'
                                }`}
                            >
                                {f === 'all' ? '전체' : f === 'W' ? 'W (Bullish)' : 'M (Bearish)'}
                            </button>
                        ))}
                    </div>
                    <div className="flex items-center gap-1.5 text-[10px] text-gray-500">
                        <span>정렬</span>
                        {([
                            ['confidence', '신뢰도'],
                            ['neckline', '넥라인 근접'],
                            ['completion', '완성도'],
                        ] as [SortMode, string][]).map(([key, label]) => (
                            <button
                                key={key}
                                onClick={() => setSortMode(key)}
                                className={`px-2 py-0.5 rounded text-[10px] transition-all ${
                                    sortMode === key
                                        ? 'bg-white/10 text-white font-bold'
                                        : 'text-gray-600 hover:text-gray-400'
                                }`}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {/* Screener Results */}
            {screenerLoading ? (
                <div className="bg-[#1c1c1e] rounded-2xl border border-white/5 p-12 text-center">
                    <div className="w-8 h-8 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
                    <p className="text-gray-500 text-sm">스크리너 데이터 로딩중...</p>
                </div>
            ) : filteredSignals.length > 0 ? (
                <div className="bg-[#1c1c1e] rounded-2xl border border-white/5 overflow-hidden">
                    <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
                        <h3 className="text-sm font-bold text-white">
                            감지된 패턴 <span className="text-cyan-400">{filteredSignals.length}개</span>
                        </h3>
                        <span className="text-[10px] text-gray-600">{screener?.date}</span>
                    </div>

                    {/* Desktop Table */}
                    <div className="hidden sm:block">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="text-gray-500 text-xs border-b border-white/5">
                                    <th className="text-left px-4 py-2 font-medium">종목</th>
                                    <th className="text-center px-2 py-2 font-medium">패턴</th>
                                    <th className="text-center px-2 py-2 font-medium">방향</th>
                                    <th className="text-center px-2 py-2 font-medium">신뢰도</th>
                                    <th className="text-center px-2 py-2 font-medium">완성도</th>
                                    <th className="text-right px-3 py-2 font-medium">현재가</th>
                                    <th className="text-right px-3 py-2 font-medium">넥라인</th>
                                    <th className="text-right px-3 py-2 font-medium">거리</th>
                                    <th className="text-center px-2 py-2 font-medium">거래량</th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredSignals.map((s, i) => {
                                    const bp = s.best_pattern;
                                    return (
                                        <tr
                                            key={`${s.ticker}-${i}`}
                                            onClick={() => loadDetail(s.ticker, s.market)}
                                            className={`border-b border-white/5 cursor-pointer transition-colors ${
                                                selectedTicker === s.ticker ? 'bg-cyan-500/10' : 'hover:bg-white/5'
                                            }`}
                                        >
                                            <td className="px-4 py-2.5">
                                                <div className="flex items-center gap-2">
                                                    <span className="text-white font-semibold text-xs">{s.name}</span>
                                                    <span className="text-gray-600 text-[10px]">{s.ticker}</span>
                                                </div>
                                            </td>
                                            <td className="text-center px-2 py-2.5">
                                                <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                                    bp.pattern_class === 'W'
                                                        ? 'bg-cyan-500/20 text-cyan-400'
                                                        : 'bg-pink-500/20 text-pink-400'
                                                }`}>{bp.wave_label}</span>
                                            </td>
                                            <td className="text-center px-2 py-2.5">
                                                <span className={`text-[10px] font-bold ${
                                                    bp.bullish_bias > 0 ? 'text-green-400' : 'text-red-400'
                                                }`}>
                                                    {bp.bullish_bias > 0 ? 'Bullish' : 'Bearish'}
                                                </span>
                                            </td>
                                            <td className="text-center px-2 py-2.5">
                                                <span className={`font-bold text-xs ${
                                                    bp.confidence >= 70 ? 'text-green-400' :
                                                    bp.confidence >= 50 ? 'text-yellow-400' : 'text-gray-400'
                                                }`}>{bp.confidence}</span>
                                            </td>
                                            <td className="text-center px-2 py-2.5">
                                                <div className="flex items-center justify-center gap-1">
                                                    <div className="w-10 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                                                        <div
                                                            className="h-full bg-cyan-500 rounded-full"
                                                            style={{ width: `${bp.completion_pct}%` }}
                                                        />
                                                    </div>
                                                    <span className="text-gray-400 text-[10px]">{bp.completion_pct}%</span>
                                                </div>
                                            </td>
                                            <td className="text-right px-3 py-2.5 text-white font-mono text-xs">
                                                {s.price.toLocaleString()}
                                            </td>
                                            <td className="text-right px-3 py-2.5 text-gray-400 font-mono text-xs">
                                                {bp.neckline_price.toLocaleString()}
                                            </td>
                                            <td className="text-right px-3 py-2.5">
                                                <span className={`font-mono text-xs ${
                                                    bp.neckline_distance_pct > 0 ? 'text-green-400' : 'text-red-400'
                                                }`}>
                                                    {bp.neckline_distance_pct > 0 ? '+' : ''}{bp.neckline_distance_pct.toFixed(1)}%
                                                </span>
                                            </td>
                                            <td className="text-center px-2 py-2.5">
                                                {bp.volume_confirmed ? (
                                                    <i className="fas fa-check-circle text-green-400 text-xs" />
                                                ) : (
                                                    <i className="fas fa-minus-circle text-gray-600 text-xs" />
                                                )}
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>

                    {/* Mobile Cards */}
                    <div className="sm:hidden divide-y divide-white/5">
                        {filteredSignals.map((s, i) => {
                            const bp = s.best_pattern;
                            return (
                                <div
                                    key={`${s.ticker}-${i}`}
                                    onClick={() => loadDetail(s.ticker, s.market)}
                                    className={`p-3.5 cursor-pointer transition-colors ${
                                        selectedTicker === s.ticker ? 'bg-cyan-500/10' : ''
                                    }`}
                                >
                                    <div className="flex items-center justify-between mb-1.5">
                                        <div className="flex items-center gap-2">
                                            <span className="text-white font-bold text-sm">{s.name}</span>
                                            <span className="text-gray-600 text-[10px]">{s.ticker}</span>
                                        </div>
                                        <span className={`text-sm font-black ${
                                            bp.confidence >= 70 ? 'text-green-400' :
                                            bp.confidence >= 50 ? 'text-yellow-400' : 'text-gray-400'
                                        }`}>{bp.confidence}점</span>
                                    </div>
                                    <div className="flex items-center gap-2 mb-1">
                                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                            bp.pattern_class === 'W'
                                                ? 'bg-cyan-500/20 text-cyan-400'
                                                : 'bg-pink-500/20 text-pink-400'
                                        }`}>{bp.wave_label}</span>
                                        <span className={`text-[10px] font-bold ${
                                            bp.bullish_bias > 0 ? 'text-green-400' : 'text-red-400'
                                        }`}>{bp.bullish_bias > 0 ? 'Bullish' : 'Bearish'}</span>
                                        {bp.volume_confirmed && (
                                            <span className="text-[9px] text-green-400">
                                                <i className="fas fa-check-circle mr-0.5" />Vol
                                            </span>
                                        )}
                                    </div>
                                    <div className="flex items-center gap-3 text-[10px] text-gray-500">
                                        <span>{s.price.toLocaleString()}원</span>
                                        <span>완성도 {bp.completion_pct}%</span>
                                        <span>넥라인 {bp.neckline_price.toLocaleString()}</span>
                                        <span className={bp.neckline_distance_pct > 0 ? 'text-green-400' : 'text-red-400'}>
                                            {bp.neckline_distance_pct > 0 ? '+' : ''}{bp.neckline_distance_pct.toFixed(1)}%
                                        </span>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            ) : !screenerLoading && (
                <div className="bg-[#1c1c1e] rounded-2xl border border-white/5 p-10 text-center">
                    <div className="w-14 h-14 mx-auto mb-3 rounded-2xl bg-cyan-500/10 flex items-center justify-center">
                        <i className="fas fa-wave-square text-cyan-400 text-xl" />
                    </div>
                    <h3 className="text-white font-bold mb-1.5">아직 스캔 데이터가 없습니다</h3>
                    <p className="text-gray-500 text-xs max-w-md mx-auto mb-4">
                        매일 16:30 KST에 자동 스캔됩니다. 위 검색창에서 개별 종목을 직접 분석할 수도 있습니다.
                    </p>
                    <div className="flex items-center justify-center gap-4 text-xs text-gray-600">
                        <span><i className="fas fa-chart-line mr-1" />32가지 패턴</span>
                        <span><i className="fas fa-bullseye mr-1" />넥라인 감지</span>
                        <span><i className="fas fa-chart-bar mr-1" />거래량 확인</span>
                    </div>
                </div>
            )}
        </div>
    );
}


/* ── Stat Card ── */

function StatCard({ label, value, icon, color = 'text-white' }: {
    label: string; value: string; icon: string; color?: string;
}) {
    return (
        <div className="bg-[#1c1c1e] rounded-xl border border-white/5 p-3">
            <div className="flex items-center gap-2 mb-1">
                <i className={`fas ${icon} text-[10px] text-gray-600`} />
                <span className="text-[10px] text-gray-500">{label}</span>
            </div>
            <div className={`text-lg font-black ${color}`}>{value}</div>
        </div>
    );
}
