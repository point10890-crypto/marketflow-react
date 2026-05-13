import { useState, useCallback, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useSearchParams } from 'react-router-dom';
import { fetchAPI, API_BASE, authHeaders, ApiError } from '@/lib/api';
import PatternChart, { ChartDataPoint, PatternOverlay, PatternPoint } from '@/components/wave/PatternChart';
import { useIsMobile } from '@/hooks/useIsMobile';
import { getJubjubCandidates, JubjubResponse, JubjubCandidate } from '@/lib/jubjubApi';
import JubjubCard from '@/components/wave/JubjubCard';
import JubjubBanner, { JubjubBadgeFilter } from '@/components/wave/JubjubBanner';

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
    name: string;
    patterns: PatternOverlay[];
    chart_data: ChartDataPoint[];
    turning_points: PatternPoint[];
    pattern_count: number;
}

/* ── Filters ── */

type FilterMode = 'all' | 'W' | 'M' | 'jubjub';
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
    const [screenerError, setScreenerError] = useState<'auth' | 'server' | null>(null);
    const [filter, setFilter] = useState<FilterMode>('all');
    const [sortMode, setSortMode] = useState<SortMode>('confidence');
    // 🪣 Jubjub state
    const [jubjub, setJubjub] = useState<JubjubResponse | null>(null);
    const [jubjubLoading, setJubjubLoading] = useState(false);
    const [jubjubMinScore, setJubjubMinScore] = useState<number>(60);
    const [jubjubBadgeFilter, setJubjubBadgeFilter] = useState<JubjubBadgeFilter>('all');
    const jubjubGridRef = useRef<HTMLDivElement | null>(null);

    const handleBadgeFilterChange = useCallback((next: JubjubBadgeFilter) => {
        setJubjubBadgeFilter((prev) => {
            // 같은 탭 재클릭 시 토글로 전체 해제
            return prev === next && next !== 'all' ? 'all' : next;
        });
        // 다음 paint 후 스크롤 — 모바일 우선
        requestAnimationFrame(() => {
            jubjubGridRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    }, []);

    // Detail state (when user clicks a signal or searches)
    const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
    const [detailResult, setDetailResult] = useState<WaveDetectResult | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [selectedIdx, setSelectedIdx] = useState(0);

    // Search state
    const [market, setMarket] = useState('KR');
    const [searchTicker, setSearchTicker] = useState('');
    const [searchError, setSearchError] = useState('');

    // URL query params (from dashboard click)
    const [searchParams, setSearchParams] = useSearchParams();

    // Load screener on mount
    useEffect(() => {
        loadScreener();
    }, []);

    const loadScreener = async () => {
        setScreenerLoading(true);
        setScreenerError(null);
        try {
            const data = await fetchAPI<ScreenerResult>('/api/wave/screener/latest');
            setScreener(data);
        } catch (err) {
            if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
                setScreenerError('auth');
            } else {
                setScreenerError('server');
            }
        } finally {
            setScreenerLoading(false);
        }
    };

    // 🪣 Jubjub: 점수 변경 시 자동 재로드
    useEffect(() => {
        if (filter !== 'jubjub') return;
        let cancelled = false;
        async function loadJubjub() {
            setJubjubLoading(true);
            try {
                const data = await getJubjubCandidates({ min_score: jubjubMinScore, limit: 50 });
                if (!cancelled) setJubjub(data);
            } catch {
                // ignore
            } finally {
                if (!cancelled) setJubjubLoading(false);
            }
        }
        loadJubjub();
        return () => {
            cancelled = true;
        };
    }, [filter, jubjubMinScore]);

    // Load detail chart for a ticker
    const loadDetail = useCallback(async (ticker: string, mkt: string = 'KR') => {
        setDetailLoading(true);
        setSearchError('');
        setSelectedTicker(ticker);
        setSelectedIdx(0);
        try {
            // Wave detect는 16초+ 걸릴 수 있어 별도 타임아웃 (30초)
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 30000);
            const url = `${API_BASE}/api/wave/detect/${ticker}?market=${mkt}&lookback=200`;
            const res = await fetch(url, { signal: controller.signal, headers: authHeaders() });
            clearTimeout(timeoutId);
            if (!res.ok) throw new Error(`API Error: ${res.status}`);
            const data: WaveDetectResult = await res.json();
            setDetailResult(data);
        } catch (e: any) {
            setSearchError(e.message || '패턴 감지 실패');
            setDetailResult(null);
        } finally {
            setDetailLoading(false);
        }
    }, []);

    // Auto-load ticker from query params (?ticker=005930&market=KR)
    useEffect(() => {
        const qTicker = searchParams.get('ticker');
        const qMarket = searchParams.get('market') || 'KR';
        if (qTicker) {
            setMarket(qMarket);
            setSearchTicker(qTicker);
            loadDetail(qTicker, qMarket);
            setSearchParams({}, { replace: true });
        }
    }, [searchParams, loadDetail, setSearchParams]);

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

    // Filtered & sorted signals (jubjub 모드는 별도 처리 — 여기서는 W/M/all 만)
    const filteredSignals = (screener?.signals || [])
        .filter(s => filter === 'all' || filter === 'jubjub' || s.best_pattern.pattern_class === filter)
        .sort((a, b) => {
            if (sortMode === 'confidence') return b.best_pattern.confidence - a.best_pattern.confidence;
            if (sortMode === 'neckline') return Math.abs(a.best_pattern.neckline_distance_pct) - Math.abs(b.best_pattern.neckline_distance_pct);
            return b.best_pattern.completion_pct - a.best_pattern.completion_pct;
        });

    const pat = detailResult?.patterns?.[selectedIdx];

    return (
        <div
            className="space-y-5 h-full overflow-y-auto p-3 md:p-6 pb-36 md:pb-6"
            style={{ touchAction: 'pan-y', overscrollBehavior: 'contain', WebkitOverflowScrolling: 'touch' }}
        >
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-amber-500/12 flex items-center justify-center">
                        <i className="fas fa-wave-square text-amber-300" />
                    </div>
                    <div>
                        <h1 className="text-2xl font-black text-white">W Pattern</h1>
                        <p className="text-sm text-gray-400">AI 차트 패턴 자동 인식 · M&W 파동 분석</p>
                    </div>
                </div>
                {screener?.updated_at && (
                    <div className="text-xs text-gray-500">
                        Updated: {screener.updated_at}
                    </div>
                )}
            </div>

            {/* Search Bar */}
            <div className="bg-black/60 rounded-2xl border border-white/5 p-3">
                <div className="flex items-center gap-2">
                    <div className="flex bg-black/40 rounded-lg p-0.5">
                        {MARKET_TABS.map(tab => (
                            <button
                                key={tab.key}
                                onClick={() => setMarket(tab.key)}
                                className={`px-2.5 py-1 text-xs font-bold rounded-md transition-all ${
                                    market === tab.key
                                        ? 'bg-amber-400 text-black'
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
                        onChange={e => {
                            const v = e.target.value;
                            // 영문만 대문자 변환, 한글은 그대로
                            setSearchTicker(/^[a-zA-Z0-9]*$/.test(v) ? v.toUpperCase() : v);
                        }}
                        onKeyDown={handleKeyDown}
                        placeholder={MARKET_TABS.find(t => t.key === market)?.placeholder}
                        className="flex-1 bg-black/40 border border-white/10 rounded-lg px-3 py-1.5 text-white text-sm placeholder:text-gray-600 focus:outline-none focus:border-amber-400/40"
                    />
                    <button
                        onClick={handleSearch}
                        disabled={detailLoading || !searchTicker.trim()}
                        className="px-3 py-1.5 bg-amber-400 text-black font-bold text-xs rounded-lg hover:bg-amber-300 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
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
                <div className="bg-rose-500/8 border border-rose-500/15 rounded-xl p-3 text-rose-300 text-sm">
                    {searchError}
                </div>
            )}

            {/* Detail Chart Modal (when a ticker is selected) */}
            {(selectedTicker && detailResult) && (
                <ChartDetailModal
                    detailResult={detailResult}
                    pat={pat}
                    selectedIdx={selectedIdx}
                    setSelectedIdx={setSelectedIdx}
                    screenerSignal={screener?.signals?.find(s => s.ticker === detailResult.ticker) ?? null}
                    onClose={closeDetail}
                />
            )}

            {/* Screener Stats */}
            {screener && screener.date && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <StatCard label="스캔 종목" value={screener.scan_count.toLocaleString()} icon="fa-search" />
                    <StatCard label="패턴 감지" value={`${screener.total_signal_count}개`} icon="fa-wave-square" color="text-amber-300" />
                    <StatCard
                        label="W (Bullish)"
                        value={`${(screener.signals || []).filter(s => s.best_pattern.pattern_class === 'W').length}개`}
                        icon="fa-arrow-up"
                        color="text-emerald-300"
                    />
                    <StatCard
                        label="M (Bearish)"
                        value={`${(screener.signals || []).filter(s => s.best_pattern.pattern_class === 'M').length}개`}
                        icon="fa-arrow-down"
                        color="text-rose-300"
                    />
                </div>
            )}

            {/* Filters & Sort */}
            {screener && screener.signals.length > 0 && (
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-2">
                        {/* 일반 패턴 탭 (전체/W/M) */}
                        {(['all', 'W', 'M'] as FilterMode[]).map(f => (
                            <button
                                key={f}
                                onClick={() => setFilter(f)}
                                className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${
                                    filter === f
                                        ? f === 'W' ? 'bg-amber-500/12 text-amber-300'
                                        : f === 'M' ? 'bg-rose-500/10 text-rose-300'
                                        : 'bg-white/10 text-white'
                                        : 'text-gray-500 hover:text-white hover:bg-white/5'
                                }`}
                            >
                                {f === 'all' ? '전체' : f === 'W' ? 'W (Bullish)' : 'M (Bearish)'}
                            </button>
                        ))}

                        {/* 🪣 줍줍이 — Quant Terminal CTA */}
                        <button
                            onClick={() => setFilter('jubjub')}
                            className={`group relative overflow-hidden rounded-lg px-4 py-2 sm:px-5 sm:py-2.5 text-sm sm:text-[15px] font-black transition-colors ${
                                filter === 'jubjub'
                                    ? 'bg-amber-400 text-black ring-1 ring-amber-300/50'
                                    : 'bg-amber-400/10 text-amber-300 ring-1 ring-amber-400/25 hover:bg-amber-400/15 hover:ring-amber-400/40'
                            }`}
                        >
                            <span className="relative flex items-center gap-2">
                                <span className="text-lg sm:text-xl leading-none">🪣</span>
                                <span className="leading-none tracking-tight">줍줍이</span>
                                <span className={`hidden sm:inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-black tracking-wider ${
                                    filter === 'jubjub'
                                        ? 'bg-black/25 text-black'
                                        : 'bg-amber-400/15 text-amber-200'
                                }`}>
                                    HOT
                                </span>
                            </span>
                        </button>
                    </div>
                    <div className="flex items-center gap-1.5 text-xs text-gray-400">
                        <span>정렬</span>
                        {([
                            ['confidence', '신뢰도'],
                            ['neckline', '넥라인 근접'],
                            ['completion', '완성도'],
                        ] as [SortMode, string][]).map(([key, label]) => (
                            <button
                                key={key}
                                onClick={() => setSortMode(key)}
                                className={`px-2.5 py-1 rounded text-xs transition-all ${
                                    sortMode === key
                                        ? 'bg-white/10 text-white font-bold'
                                        : 'text-gray-500 hover:text-gray-300'
                                }`}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {/* 🪣 Jubjub Mode — W 패턴 + 저점 매수 시그널 */}
            {filter === 'jubjub' && (
                <>
                    <JubjubBanner
                        data={jubjub}
                        minScore={jubjubMinScore}
                        onMinScoreChange={setJubjubMinScore}
                        badgeFilter={jubjubBadgeFilter}
                        onBadgeFilterChange={handleBadgeFilterChange}
                        loading={jubjubLoading}
                    />
                    {jubjubLoading && !jubjub ? (
                        <div className="bg-black/60 rounded-2xl border border-amber-500/15 p-12 text-center">
                            <div className="w-8 h-8 border-2 border-amber-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
                            <p className="text-gray-500 text-sm">🪣 줍줍 후보 검출 중...</p>
                        </div>
                    ) : !jubjub?.candidates?.length ? (
                        <div className="bg-black/60 rounded-2xl border border-amber-500/15 p-12 text-center">
                            <div className="text-4xl mb-3">🪣</div>
                            <p className="text-gray-400 text-sm">
                                현재 줍줍 후보가 없습니다 (최소 점수 ≥ {jubjubMinScore}).
                            </p>
                            <p className="text-gray-600 text-xs mt-1">
                                점수 기준을 낮추거나 다음 스캔까지 기다려 보세요.
                            </p>
                        </div>
                    ) : (() => {
                        const visibleCandidates = jubjubBadgeFilter === 'all'
                            ? jubjub.candidates
                            : jubjub.candidates.filter((c) => c.jubjub_badge === jubjubBadgeFilter);
                        return (
                        <div ref={jubjubGridRef} className="scroll-mt-4">
                          {jubjubBadgeFilter !== 'all' && (
                            <div className="mb-3 flex items-center justify-between rounded-lg border border-amber-400/25 bg-amber-400/[0.06] px-3 py-2">
                              <div className="text-[11px] font-bold text-amber-200">
                                <span className="opacity-70">필터: </span>
                                <span className="font-black">
                                  {jubjubBadgeFilter === 'imminent' ? '🎯 진입 임박'
                                    : jubjubBadgeFilter === 'buy_now' ? '🔥 매수 타이밍'
                                    : jubjubBadgeFilter === 'breakout' ? '🚀 막 돌파'
                                    : jubjubBadgeFilter === 'late' ? '⏰ 늦은 진입'
                                    : jubjubBadgeFilter === 'watching' ? '👀 관찰 중'
                                    : jubjubBadgeFilter}
                                </span>
                                <span className="ml-2 text-neutral-400">· {visibleCandidates.length}개</span>
                              </div>
                              <button
                                type="button"
                                onClick={() => setJubjubBadgeFilter('all')}
                                className="text-[10px] font-black uppercase tracking-wider text-amber-300 hover:text-amber-200"
                              >
                                전체 보기 ×
                              </button>
                            </div>
                          )}
                          {visibleCandidates.length === 0 ? (
                            <div className="bg-black/60 rounded-2xl border border-amber-500/15 p-10 text-center">
                              <div className="text-3xl mb-2">🪣</div>
                              <p className="text-gray-400 text-sm">선택한 카테고리에 해당하는 종목이 없습니다.</p>
                            </div>
                          ) : (
                          <div className="grid grid-cols-1 gap-3 sm:gap-4 lg:grid-cols-2 2xl:grid-cols-3">
                            {visibleCandidates.map((c: JubjubCandidate) => (
                                <JubjubCard
                                    key={c.ticker}
                                    candidate={c}
                                    onChart={(cand) => {
                                        // 차트 보기 = 기존 detail 로드
                                        loadDetail(cand.ticker, cand.market || 'KR');
                                    }}
                                    onShare={(cand) => {
                                        const text = `🪣 줍줍 신호 — ${cand.name} (${cand.ticker})\n점수: ${Math.round(cand.jubjub_score)}/100 ${cand.jubjub_badge_label_ko}\n매수가: ${cand.trade_plan.entry_price.toLocaleString()}원\n1차 목표: ${cand.trade_plan.target_1.toLocaleString()}원\n손절가: ${cand.trade_plan.stop_price.toLocaleString()}원\nR/R: 1차 ${cand.trade_plan.rr_1}x`;
                                        if (navigator.share) {
                                            navigator.share({ title: `🪣 ${cand.name} 줍줍 신호`, text });
                                        } else {
                                            navigator.clipboard.writeText(text);
                                            alert('복사됨 — 카톡 채팅에 붙여넣기 하세요.');
                                        }
                                    }}
                                />
                            ))}
                          </div>
                          )}
                        </div>
                        );
                    })()}
                </>
            )}

            {/* Screener Results (기존 W/M 모드 — jubjub 모드 시 숨김) */}
            {filter !== 'jubjub' && (screenerLoading ? (
                <div className="bg-black/60 rounded-2xl border border-white/5 p-12 text-center">
                    <div className="w-8 h-8 border-2 border-amber-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
                    <p className="text-gray-500 text-sm">스크리너 데이터 로딩중...</p>
                </div>
            ) : filteredSignals.length > 0 ? (
                <div className="bg-black/60 rounded-2xl border border-white/5 overflow-hidden">
                    <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
                        <h3 className="text-base font-bold text-white">
                            감지된 패턴 <span className="text-amber-300">{filteredSignals.length}개</span>
                        </h3>
                        <span className="text-xs text-gray-500">{screener?.date}</span>
                    </div>

                    {/* Desktop Table */}
                    <div className="hidden sm:block">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="text-gray-400 text-sm border-b border-white/5">
                                    <th className="text-left px-4 py-2.5 font-medium">종목</th>
                                    <th className="text-center px-2 py-2.5 font-medium">패턴</th>
                                    <th className="text-center px-2 py-2.5 font-medium">방향</th>
                                    <th className="text-center px-2 py-2.5 font-medium">신뢰도</th>
                                    <th className="text-center px-2 py-2.5 font-medium">완성도</th>
                                    <th className="text-right px-3 py-2.5 font-medium">현재가</th>
                                    <th className="text-right px-3 py-2.5 font-medium">넥라인</th>
                                    <th className="text-right px-3 py-2.5 font-medium">거리</th>
                                    <th className="text-center px-2 py-2.5 font-medium">거래량</th>
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
                                                selectedTicker === s.ticker ? 'bg-amber-500/8' : 'hover:bg-white/5'
                                            }`}
                                        >
                                            <td className="px-4 py-3">
                                                <div className="flex items-center gap-2">
                                                    <span className="text-white font-bold text-sm">{s.name}</span>
                                                    <span className="text-gray-500 text-xs">{s.ticker}</span>
                                                </div>
                                            </td>
                                            <td className="text-center px-2 py-3">
                                                <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                                                    bp.pattern_class === 'W'
                                                        ? 'bg-amber-500/12 text-amber-300'
                                                        : 'bg-rose-500/10 text-rose-300'
                                                }`}>{bp.wave_label}</span>
                                            </td>
                                            <td className="text-center px-2 py-3">
                                                <span className={`text-xs font-bold ${
                                                    bp.bullish_bias > 0 ? 'text-emerald-300' : 'text-rose-300'
                                                }`}>
                                                    {bp.bullish_bias > 0 ? 'Bullish' : 'Bearish'}
                                                </span>
                                            </td>
                                            <td className="text-center px-2 py-3">
                                                <span className={`font-bold text-sm ${
                                                    bp.confidence >= 70 ? 'text-emerald-300' :
                                                    bp.confidence >= 50 ? 'text-amber-300' : 'text-gray-400'
                                                }`}>{bp.confidence}</span>
                                            </td>
                                            <td className="text-center px-2 py-3">
                                                <div className="flex items-center justify-center gap-1.5">
                                                    <div className="w-12 h-2 bg-gray-700 rounded-full overflow-hidden">
                                                        <div
                                                            className="h-full bg-amber-400/70 rounded-full"
                                                            style={{ width: `${bp.completion_pct}%` }}
                                                        />
                                                    </div>
                                                    <span className="text-gray-300 text-xs">{bp.completion_pct}%</span>
                                                </div>
                                            </td>
                                            <td className="text-right px-3 py-3 text-white font-mono text-sm font-bold">
                                                {s.price.toLocaleString()}
                                            </td>
                                            <td className="text-right px-3 py-3 text-gray-300 font-mono text-sm">
                                                {bp.neckline_price.toLocaleString()}
                                            </td>
                                            <td className="text-right px-3 py-3">
                                                <span className={`font-mono text-sm font-bold ${
                                                    bp.neckline_distance_pct > 0 ? 'text-emerald-300' : 'text-rose-300'
                                                }`}>
                                                    {bp.neckline_distance_pct > 0 ? '+' : ''}{bp.neckline_distance_pct.toFixed(1)}%
                                                </span>
                                            </td>
                                            <td className="text-center px-2 py-3">
                                                {bp.volume_confirmed ? (
                                                    <i className="fas fa-check-circle text-emerald-300 text-sm" />
                                                ) : (
                                                    <i className="fas fa-minus-circle text-gray-600 text-sm" />
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
                                        selectedTicker === s.ticker ? 'bg-amber-500/8' : ''
                                    }`}
                                >
                                    <div className="flex items-center justify-between mb-1.5">
                                        <div className="flex items-center gap-2">
                                            <span className="text-white font-bold text-sm">{s.name}</span>
                                            <span className="text-gray-600 text-[10px]">{s.ticker}</span>
                                            <span className="text-gray-500 text-[10px]">{s.market}</span>
                                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                                bp.pattern_class === 'W'
                                                    ? 'bg-amber-500/12 text-amber-300'
                                                    : 'bg-rose-500/10 text-rose-300'
                                            }`}>{bp.wave_label}</span>
                                            <span className={`text-xs font-black ${
                                                bp.confidence >= 70 ? 'text-emerald-300' :
                                                bp.confidence >= 50 ? 'text-amber-300' : 'text-gray-400'
                                            }`}>{bp.confidence}점</span>
                                        </div>
                                        <span className="text-white font-mono font-bold text-sm">{s.price.toLocaleString()}원</span>
                                    </div>
                                    <div className="flex items-center gap-2 mb-1">
                                        <span className={`text-[10px] font-bold ${
                                            bp.bullish_bias > 0 ? 'text-emerald-300' : 'text-rose-300'
                                        }`}>{bp.bullish_bias > 0 ? 'Bullish' : 'Bearish'}</span>
                                        {bp.volume_confirmed && (
                                            <span className="text-[9px] text-emerald-300">
                                                <i className="fas fa-check-circle mr-0.5" />Vol
                                            </span>
                                        )}
                                    </div>
                                    <div className="flex items-center gap-3 text-[10px] text-gray-500">
                                        <span>완성도 {bp.completion_pct}%</span>
                                        <span>넥라인 {bp.neckline_price.toLocaleString()}</span>
                                        <span className={bp.neckline_distance_pct > 0 ? 'text-emerald-300' : 'text-rose-300'}>
                                            {bp.neckline_distance_pct > 0 ? '+' : ''}{bp.neckline_distance_pct.toFixed(1)}%
                                        </span>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            ) : screenerError === 'auth' ? (
                <div className="bg-black/60 rounded-2xl border border-amber-500/20 p-10 text-center">
                    <div className="w-14 h-14 mx-auto mb-3 rounded-2xl bg-amber-500/12 flex items-center justify-center">
                        <i className="fas fa-lock text-amber-300 text-xl" />
                    </div>
                    <h3 className="text-white font-bold mb-1.5">로그인이 필요합니다</h3>
                    <p className="text-neutral-400 text-xs max-w-md mx-auto mb-4">
                        W Pattern 스크리너는 Pro / Ultra Pro 회원 전용 기능입니다. 로그인 후 다시 시도해 주세요.
                    </p>
                    <div className="flex items-center justify-center gap-2">
                        <a
                            href="/login"
                            className="inline-flex items-center gap-1.5 rounded-lg bg-amber-400 px-4 py-2 text-xs font-black text-black hover:bg-amber-300 transition-colors"
                        >
                            <i className="fas fa-sign-in-alt" /> 로그인
                        </a>
                        <button
                            type="button"
                            onClick={loadScreener}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-xs font-bold text-neutral-300 hover:bg-white/10 transition-colors"
                        >
                            <i className="fas fa-rotate-right" /> 재시도
                        </button>
                    </div>
                </div>
            ) : screenerError === 'server' ? (
                <div className="bg-black/60 rounded-2xl border border-rose-500/20 p-10 text-center">
                    <div className="w-14 h-14 mx-auto mb-3 rounded-2xl bg-rose-500/10 flex items-center justify-center">
                        <i className="fas fa-circle-exclamation text-rose-300 text-xl" />
                    </div>
                    <h3 className="text-white font-bold mb-1.5">서버 연결 실패</h3>
                    <p className="text-neutral-400 text-xs max-w-md mx-auto mb-4">
                        스크리너 API 호출 중 오류가 발생했습니다. 잠시 후 다시 시도하거나 관리자에게 문의해 주세요.
                    </p>
                    <button
                        type="button"
                        onClick={loadScreener}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-amber-400 px-4 py-2 text-xs font-black text-black hover:bg-amber-300 transition-colors"
                    >
                        <i className="fas fa-rotate-right" /> 재시도
                    </button>
                </div>
            ) : !screenerLoading && (
                <div className="bg-black/60 rounded-2xl border border-white/5 p-10 text-center">
                    <div className="w-14 h-14 mx-auto mb-3 rounded-2xl bg-amber-500/8 flex items-center justify-center">
                        <i className="fas fa-wave-square text-amber-300 text-xl" />
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
            ))}
        </div>
    );
}


/* ── Stat Card ── */

function StatCard({ label, value, icon, color = 'text-white' }: {
    label: string; value: string; icon: string; color?: string;
}) {
    return (
        <div className="bg-black/60 rounded-xl border border-white/5 p-3">
            <div className="flex items-center gap-2 mb-1">
                <i className={`fas ${icon} text-xs text-gray-500`} />
                <span className="text-xs text-gray-400">{label}</span>
            </div>
            <div className={`text-xl font-black ${color}`}>{value}</div>
        </div>
    );
}


/* ── Chart Detail Modal ── */

function ChartDetailModal({
    detailResult,
    pat,
    selectedIdx,
    setSelectedIdx,
    screenerSignal,
    onClose,
}: {
    detailResult: WaveDetectResult;
    pat: PatternOverlay | undefined;
    selectedIdx: number;
    setSelectedIdx: (i: number) => void;
    screenerSignal: ScreenerSignal | null;
    onClose: () => void;
}) {
    const isMobile = useIsMobile();
    const [vh, setVh] = useState<number>(typeof window !== 'undefined' ? window.innerHeight : 900);
    useEffect(() => {
        const onResize = () => setVh(window.innerHeight);
        window.addEventListener('resize', onResize);
        return () => window.removeEventListener('resize', onResize);
    }, []);
    // Header(~70) + body padding(~32) + pattern buttons(~40) + safety(~80) = ~220px
    // 모바일은 헤더 + 패턴 버튼 + 안전여백 더 크게(~280)
    const chartHeight = isMobile
        ? Math.max(380, vh - 280)
        : Math.max(520, vh - 220);

    // Lock body scroll while modal is open
    useEffect(() => {
        const prev = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            document.body.style.overflow = prev;
        };
    }, []);

    // Close on Escape
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') onClose();
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [onClose]);

    return createPortal(
        <div
            className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm p-3 sm:p-6"
            onClick={onClose}
        >
            <div
                className="bg-black/60 rounded-2xl border border-amber-500/15 w-full max-w-[95vw] max-h-[95vh] flex flex-col overflow-hidden shadow-2xl"
                onClick={e => e.stopPropagation()}
            >
                {/* Header */}
                <div className="flex items-center justify-between gap-2 p-4 border-b border-white/5 shrink-0">
                    <div className="flex items-center gap-1.5 flex-wrap min-w-0">
                        <span className="text-base font-black text-white truncate">{detailResult.name || detailResult.ticker}</span>
                        <span className="text-[10px] text-gray-400">{detailResult.ticker}</span>
                        <span className="text-[10px] text-gray-500">{detailResult.market}</span>
                        {pat && (
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                pat.pattern_class === 'W'
                                    ? 'bg-amber-500/12 text-amber-300'
                                    : 'bg-rose-500/10 text-rose-300'
                            }`}>{pat.wave_label}</span>
                        )}
                        {pat && (
                            <span className={`text-xs font-bold ${
                                pat.confidence >= 70 ? 'text-emerald-300' :
                                pat.confidence >= 50 ? 'text-amber-300' : 'text-gray-400'
                            }`}>{pat.confidence}점</span>
                        )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                        {screenerSignal && (
                            <span className="text-amber-300 font-mono font-bold text-base sm:text-lg">
                                {screenerSignal.price.toLocaleString()}<span className="text-xs sm:text-sm">원</span>
                            </span>
                        )}
                        <button
                            onClick={onClose}
                            aria-label="Close"
                            className="text-gray-400 hover:text-white w-8 h-8 flex items-center justify-center rounded-lg hover:bg-white/10 transition-colors"
                        >
                            <i className="fas fa-times" />
                        </button>
                    </div>
                </div>

                {/* Body (scrollable) */}
                <div
                    className="overflow-y-auto p-4 space-y-3"
                    style={{ touchAction: 'pan-y', overscrollBehavior: 'contain', WebkitOverflowScrolling: 'touch' }}
                >
                    <PatternChart
                        chartData={detailResult.chart_data}
                        patterns={detailResult.patterns}
                        turningPoints={detailResult.turning_points}
                        selectedPatternIdx={selectedIdx}
                        height={chartHeight}
                    />
                    {detailResult.patterns.length > 1 && (
                        <div className="flex gap-2 flex-wrap">
                            {detailResult.patterns.map((p, i) => (
                                <button
                                    key={i}
                                    onClick={() => setSelectedIdx(i)}
                                    className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all ${
                                        selectedIdx === i
                                            ? 'bg-amber-400 text-black'
                                            : 'bg-white/5 text-gray-400 hover:bg-white/10'
                                    }`}
                                >
                                    {p.wave_label} ({p.confidence}점)
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>,
        document.body
    );
}
