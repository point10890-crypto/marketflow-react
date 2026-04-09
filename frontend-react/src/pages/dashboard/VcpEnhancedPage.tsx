

import { useEffect, useState, useCallback } from 'react';
import { fetchAPI } from '@/lib/api';
import { useAutoRefresh, useSmartRefresh } from '@/hooks/useAutoRefresh';
import { usePullToRefreshRegister } from '@/components/layout/PullToRefreshProvider';

interface VCPSignal {
    symbol: string;
    name: string;
    market?: string;
    price?: number;
    composite?: { composite_score: number; rating: string; rating_description?: string; entry_ready: boolean };
    trend_template?: { score: number; passed: boolean };
    vcp_pattern?: { score: number; valid_vcp: boolean; num_contractions?: number; pivot_price?: number };
    volume_pattern?: { score: number; dry_up_ratio?: number };
    pivot_proximity?: { score: number; distance_from_pivot_pct?: number; trade_status?: string };
    relative_strength?: { score: number; rs_rank_estimate?: number };
    stage?: { stage: number; stage_label?: string };
    market_gate?: string;
    gate_score?: number;
    position_modifier?: number;
    sector?: string;
}

interface VCPData {
    metadata: { market: string; generated_at?: string; gate?: string; gate_score?: number };
    summary: { total_screened?: number; stage2_passed?: number; vcp_found?: number; entry_ready?: number };
    signals: VCPSignal[];
}

type MarketTab = 'KR' | 'US' | 'CRYPTO';

const MARKET_CONFIG: Record<MarketTab, { endpoint: string; datesEndpoint: string; historyEndpoint: string; label: string; flag: string; color: string; accent: string }> = {
    KR: { endpoint: '/api/kr/vcp-enhanced', datesEndpoint: '/api/kr/vcp-enhanced/dates', historyEndpoint: '/api/kr/vcp-enhanced/history', label: '한국', flag: '🇰🇷', color: 'text-blue-400', accent: 'border-blue-500' },
    US: { endpoint: '/api/us/vcp-enhanced', datesEndpoint: '/api/us/vcp-enhanced/dates', historyEndpoint: '/api/us/vcp-enhanced/history', label: '미국', flag: '🇺🇸', color: 'text-emerald-400', accent: 'border-emerald-500' },
    CRYPTO: { endpoint: '/api/crypto/vcp-enhanced', datesEndpoint: '/api/crypto/vcp-enhanced/dates', historyEndpoint: '/api/crypto/vcp-enhanced/history', label: '크립토', flag: '₿', color: 'text-amber-400', accent: 'border-amber-500' },
};

/* ── 한글 매핑 ── */
const RATING_KR: Record<string, string> = {
    'Textbook VCP': '교과서적 VCP',
    'Strong VCP': '강력한 VCP',
    'Good VCP': '양호한 VCP',
    'Moderate': '보통',
};

const STAGE_KR: Record<string, string> = {
    'Stage 1 - Basing': '스테이지 1 - 바닥 다지기',
    'Stage 2 - Advancing': '스테이지 2 - 상승 추세',
    'Stage 3 - Topping': '스테이지 3 - 천장 형성',
    'Stage 4 - Declining': '스테이지 4 - 하락 추세',
};

const GATE_KR: Record<string, string> = {
    GREEN: '양호',
    YELLOW: '주의',
    RED: '위험',
};

function translateRating(rating?: string): string {
    if (!rating) return '';
    for (const [en, kr] of Object.entries(RATING_KR)) {
        if (rating.includes(en.split(' ')[0])) return kr;
    }
    return rating;
}

function translateStage(label?: string): string {
    if (!label) return '';
    return STAGE_KR[label] || label;
}

/* ── 컴포넌트 ── */
function ScoreBar({ score, label, color }: { score: number; label: string; color: string }) {
    return (
        <div className="flex items-center gap-2">
            <span className="text-[11px] sm:text-xs text-gray-400 w-10 sm:w-12 text-right shrink-0">{label}</span>
            <div className="flex-1 h-2 bg-white/5 rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(score, 100)}%` }} />
            </div>
            <span className="text-[11px] sm:text-xs font-semibold text-gray-300 w-7 shrink-0">{score}</span>
        </div>
    );
}

function getRatingColor(rating?: string): string {
    if (!rating) return 'text-gray-400';
    if (rating.includes('Textbook') || rating.includes('교과서')) return 'text-emerald-400';
    if (rating.includes('Strong') || rating.includes('강력')) return 'text-blue-400';
    if (rating.includes('Good') || rating.includes('양호')) return 'text-yellow-400';
    return 'text-gray-400';
}

function getScoreColor(score: number): string {
    if (score >= 80) return 'bg-emerald-500';
    if (score >= 70) return 'bg-blue-500';
    if (score >= 60) return 'bg-yellow-500';
    return 'bg-gray-500';
}

function getScoreBadgeBg(score: number): string {
    if (score >= 80) return 'bg-emerald-500/15 ring-1 ring-emerald-500/30';
    if (score >= 70) return 'bg-blue-500/15 ring-1 ring-blue-500/30';
    if (score >= 60) return 'bg-yellow-500/15 ring-1 ring-yellow-500/30';
    return 'bg-white/5 ring-1 ring-white/10';
}

export default function VCPEnhancedPage() {
    const [activeTab, setActiveTab] = useState<MarketTab>('KR');
    const [data, setData] = useState<Record<MarketTab, VCPData | null>>({ KR: null, US: null, CRYPTO: null });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [dates, setDates] = useState<Record<MarketTab, string[]>>({ KR: [], US: [], CRYPTO: [] });
    const [selectedDate, setSelectedDate] = useState<string>('latest');

    const loadDates = useCallback(async (market: MarketTab) => {
        try {
            const result = await fetchAPI<string[]>(MARKET_CONFIG[market].datesEndpoint);
            setDates(prev => ({ ...prev, [market]: result }));
        } catch { /* ignore */ }
    }, []);

    const loadData = useCallback(async (market: MarketTab, date: string = 'latest') => {
        setLoading(true);
        setError(null);
        try {
            const url = date === 'latest'
                ? MARKET_CONFIG[market].endpoint
                : `${MARKET_CONFIG[market].historyEndpoint}/${date}`;
            const result = await fetchAPI<VCPData>(url);
            setData(prev => ({ ...prev, [market]: result }));
        } catch (e: any) {
            setError(e.message || '데이터 로드 실패');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        setSelectedDate('latest');
        loadDates(activeTab);
        loadData(activeTab, 'latest');
    }, [activeTab, loadData, loadDates]);

    useEffect(() => {
        loadData(activeTab, selectedDate);
    }, [selectedDate, activeTab, loadData]);

    const silentRefresh = useCallback(async () => {
        if (selectedDate !== 'latest') return;
        await loadData(activeTab, 'latest');
    }, [loadData, activeTab, selectedDate]);
    useAutoRefresh(silentRefresh, 60000, selectedDate === 'latest');
    useSmartRefresh(silentRefresh, ['vcp_kr_latest.json', 'vcp_us_latest.json', 'vcp_crypto_latest.json'], 15000, selectedDate === 'latest');
    usePullToRefreshRegister(useCallback(async () => { await loadData(activeTab, selectedDate); }, [loadData, activeTab, selectedDate]));

    const current = data[activeTab];
    const rawSignals = current?.signals || [];
    const signals = rawSignals.filter((s, i, arr) => arr.findIndex(x => x.symbol === s.symbol) === i);
    const meta = current?.metadata;
    const summary = current?.summary;

    return (
        <div className="flex flex-col gap-4 md:gap-5 h-full min-h-0">
            {/* ── Header ── */}
            <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3 shrink-0">
                <div>
                    <div className="flex items-center gap-2 mb-1">
                        <i className="fas fa-bolt text-yellow-400" />
                        <span className="text-xs font-semibold text-yellow-400 uppercase tracking-widest">
                            VCP Enhanced
                        </span>
                    </div>
                    <h2 className="text-xl sm:text-2xl font-extrabold tracking-tight text-white">
                        Volatility Contraction{' '}
                        <span className="text-transparent bg-clip-text bg-gradient-to-r from-yellow-300 to-amber-500">
                            Pattern
                        </span>
                    </h2>
                    <p className="text-xs sm:text-sm text-gray-400 mt-1">
                        Minervini SEPA 기반 멀티마켓 통합 스크리닝
                    </p>
                </div>

                <div className="flex items-center gap-3">
                    {meta?.generated_at && (
                        <span className="text-xs text-gray-500">
                            업데이트: {new Date(meta.generated_at).toLocaleString('ko-KR')}
                        </span>
                    )}
                    <select
                        value={selectedDate}
                        onChange={e => setSelectedDate(e.target.value)}
                        className="text-xs sm:text-sm bg-[#13151f] border border-white/10 rounded-lg px-3 py-2 text-gray-300 focus:outline-none focus:border-yellow-500/50"
                    >
                        <option value="latest">최신 리포트</option>
                        {dates[activeTab].map(d => (
                            <option key={d} value={d}>{d}</option>
                        ))}
                    </select>
                </div>
            </div>

            {/* ── Market Tabs ── */}
            <div className="flex gap-1 shrink-0">
                {(Object.keys(MARKET_CONFIG) as MarketTab[]).map(market => (
                    <button
                        key={market}
                        onClick={() => setActiveTab(market)}
                        className={`px-4 py-2.5 text-sm font-semibold rounded-lg transition-all ${
                            activeTab === market
                                ? `text-white bg-white/10 border ${MARKET_CONFIG[market].accent}`
                                : 'text-gray-400 hover:text-white hover:bg-white/5 border border-transparent'
                        }`}
                    >
                        <span className={activeTab === market ? MARKET_CONFIG[market].color : ''}>
                            {MARKET_CONFIG[market].flag} {MARKET_CONFIG[market].label}
                        </span>
                        {data[market] && (
                            <span className="ml-2 text-xs text-gray-500">
                                {data[market]!.signals.length}
                            </span>
                        )}
                    </button>
                ))}
            </div>

            {/* ── Gate + Summary Bar ── */}
            {meta && (
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 rounded-xl bg-[#13151f] border border-white/[0.08] shrink-0">
                    {meta.gate && (
                        <div className="flex items-center gap-2">
                            <span className="text-xs text-gray-400">마켓 게이트</span>
                            <span className={`px-2.5 py-1 rounded-md text-xs font-bold ${
                                meta.gate === 'GREEN' ? 'bg-emerald-500/20 text-emerald-400' :
                                meta.gate === 'YELLOW' ? 'bg-yellow-500/20 text-yellow-400' :
                                'bg-red-500/20 text-red-400'
                            }`}>
                                {GATE_KR[meta.gate] || meta.gate}
                            </span>
                        </div>
                    )}
                    {meta.gate_score != null && (
                        <span className="text-xs text-gray-400">점수: <b className="text-white text-sm">{meta.gate_score}</b></span>
                    )}
                    <div className="hidden sm:block h-4 w-px bg-white/10" />
                    {summary?.total_screened != null && (
                        <span className="text-xs text-gray-400">스크리닝: <b className="text-gray-200">{summary.total_screened}</b></span>
                    )}
                    {summary?.vcp_found != null && (
                        <span className="text-xs text-gray-400">VCP 감지: <b className="text-yellow-400">{summary.vcp_found}</b></span>
                    )}
                    {summary?.entry_ready != null && (
                        <span className="text-xs text-gray-400">진입 가능: <b className="text-emerald-400">{summary.entry_ready}</b></span>
                    )}
                </div>
            )}

            {/* ── Signals Grid ── */}
            <div className="flex-1 overflow-y-auto min-h-0 space-y-2 md:space-y-3">
                {loading && (
                    <div className="flex items-center justify-center py-20">
                        <div className="w-6 h-6 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin" />
                    </div>
                )}

                {error && (
                    <div className="text-center py-12 text-red-400 text-sm">{error}</div>
                )}

                {!loading && !error && signals.length === 0 && (
                    <div className="text-center py-20 text-gray-400">
                        <i className="fas fa-search text-3xl mb-3 block opacity-40" />
                        <p className="text-sm">감지된 VCP 시그널이 없습니다</p>
                        <p className="text-xs text-gray-500 mt-1">{MARKET_CONFIG[activeTab].flag} {MARKET_CONFIG[activeTab].label} 마켓</p>
                    </div>
                )}

                {!loading && signals.map((signal, i) => (
                    <div
                        key={`${signal.symbol}-${i}`}
                        className="p-4 md:p-5 rounded-xl bg-[#13151f] border border-white/[0.08] hover:border-white/15 transition-colors"
                    >
                        {/* 상단: 종목명 + 점수 */}
                        <div className="flex items-start justify-between mb-3">
                            <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-base sm:text-lg font-bold text-white">{signal.name || signal.symbol}</span>
                                    <span className="text-xs sm:text-sm text-gray-400 font-mono">{signal.symbol}</span>
                                    {signal.composite?.entry_ready && (
                                        <span className="px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                                            진입 가능
                                        </span>
                                    )}
                                </div>
                                {signal.stage?.stage_label && (
                                    <span className="text-xs text-gray-500 mt-1 block">
                                        {translateStage(signal.stage.stage_label)}
                                    </span>
                                )}
                            </div>
                            <div className="flex items-center gap-3 shrink-0 ml-3">
                                {signal.price != null && (
                                    <span className="text-sm sm:text-base text-gray-200 font-mono font-semibold">
                                        {activeTab === 'KR'
                                            ? `${signal.price.toLocaleString()}원`
                                            : activeTab === 'CRYPTO'
                                                ? `$${signal.price.toLocaleString()}`
                                                : `$${signal.price.toFixed(2)}`}
                                    </span>
                                )}
                                {signal.composite?.composite_score != null && (
                                    <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg ${getScoreBadgeBg(signal.composite.composite_score)}`}>
                                        <div className={`w-2.5 h-2.5 rounded-full ${getScoreColor(signal.composite.composite_score)}`} />
                                        <span className="text-lg sm:text-xl font-bold text-white">{signal.composite.composite_score.toFixed(0)}</span>
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* 중단: 레이팅 */}
                        {signal.composite?.rating && (
                            <div className="mb-3">
                                <span className={`text-xs sm:text-sm font-semibold ${getRatingColor(signal.composite.rating)}`}>
                                    {translateRating(signal.composite.rating)}
                                </span>
                                {signal.composite?.rating_description && (
                                    <span className="text-xs text-gray-500 ml-2">{signal.composite.rating_description}</span>
                                )}
                            </div>
                        )}

                        {/* 하단: 5항목 스코어바 */}
                        <div className="grid grid-cols-1 sm:grid-cols-5 gap-2 sm:gap-3">
                            {signal.trend_template && (
                                <ScoreBar score={signal.trend_template.score} label="추세" color="bg-blue-500" />
                            )}
                            {signal.vcp_pattern && (
                                <ScoreBar score={signal.vcp_pattern.score} label="VCP" color="bg-yellow-500" />
                            )}
                            {signal.volume_pattern && (
                                <ScoreBar score={signal.volume_pattern.score} label="거래량" color="bg-purple-500" />
                            )}
                            {signal.pivot_proximity && (
                                <ScoreBar score={signal.pivot_proximity.score} label="피봇" color="bg-emerald-500" />
                            )}
                            {signal.relative_strength && (
                                <ScoreBar score={signal.relative_strength.score} label="상대강도" color="bg-orange-500" />
                            )}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
