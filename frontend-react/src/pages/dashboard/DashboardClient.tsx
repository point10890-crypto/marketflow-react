

import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useNavigate } from 'react-router-dom';
import { usAPI, krAPI, cryptoAPI, jonggaAPI, waveAPI, briefingAPI, commonAPI, communityAPI, type AIBriefing, type MarketIndexItem, type KRAIChartAnalysisResponse, type USAIChartAnalysisResponse, type CommunitySummary } from '@/lib/api';
import { usePullToRefreshRegister } from '@/components/layout/PullToRefreshProvider';
import { useAuth } from '@/contexts/AuthContext';
import { useSmartRefresh } from '@/hooks/useAutoRefresh';

// ── Types ──────────────────────────────────────────────────────────────────────

interface InitialData {
    briefing: any;
    krGate: any;
    cryptoDom: any;
}

interface VCPSummary {
    kr: number;
    us: number;
    crypto: number;
    topSignals: Array<{ name: string; market: string; score: number }>;
}

const SUMMARY_WATCH_FILES = [
    'briefing/latest.json',
    'market_briefing.json',
    'market_gate_cache.json',
    'crypto_dominance_cache.json',
    'jongga_v2_latest.json',
    'screener_leading_latest.json',
    'wave_screener_latest.json',
    'vcp_kr_latest.json',
    'vcp_us_latest.json',
    'vcp_crypto_latest.json',
];

function isPayloadFresh(data: any): boolean {
    const freshness = data?.metadata?.freshness ?? data?.freshness;
    return !freshness?.is_stale;
}

function dedupSignals(signals: any[] = []) {
    const seen = new Set();
    return signals.filter((s: any) => {
        const key = s.symbol || s.name || s.ticker;
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}

function vcpSignalScore(signal: any): number {
    const composite = signal?.composite;
    if (typeof composite === 'object') {
        return Number(composite?.composite_score ?? 0);
    }
    return Number(composite ?? signal?.score ?? 0);
}

function buildVcpSummary(vcpKr: any, vcpUs: any, vcpCrypto: any): VCPSummary {
    const marketPayloads: Array<[string, any]> = [
        ['KR', vcpKr],
        ['US', vcpUs],
        ['CRYPTO', vcpCrypto],
    ];
    const counts: Record<string, number> = { KR: 0, US: 0, CRYPTO: 0 };
    const allSignals: Array<{ name: string; market: string; score: number }> = [];

    marketPayloads.forEach(([market, data]) => {
        if (!isPayloadFresh(data)) return;
        const unique = dedupSignals(Array.isArray(data?.signals) ? data.signals : []);
        counts[market] = unique.length;
        unique.slice(0, 3).forEach((s: any) => {
            allSignals.push({
                name: s.name || s.ticker || s.symbol || '?',
                market,
                score: vcpSignalScore(s),
            });
        });
    });

    return {
        kr: counts.KR,
        us: counts.US,
        crypto: counts.CRYPTO,
        topSignals: allSignals.sort((a, b) => b.score - a.score).slice(0, 5),
    };
}

// ── Compact Stat Pill ─────────────────────────────────────────────────────────

function StatPill({ label, value, sub, color }: { label: string; value: string; sub?: string; color: string }) {
    return (
        <div className="flex flex-col items-center min-w-[72px] px-2 py-2">
            <span className="text-[9px] font-semibold text-gray-500 uppercase tracking-widest">{label}</span>
            <span className={`text-base font-bold tabular-nums leading-tight ${color}`}>{value}</span>
            {sub && <span className="text-[9px] text-gray-500 font-medium">{sub}</span>}
        </div>
    );
}

// ── Market Card (Mobile-Optimized) ────────────────────────────────────────────

interface CompactCardProps {
    to: string;
    icon: string;
    label: string;
    sublabel: string;
    accent: string;
    status: string;
    statusColor: string;
    metric: string;
    metricLabel: string;
    metricSuffix?: string;
    badge?: string;
}

function CompactCard({ to, icon, label, sublabel, accent, status, statusColor, metric, metricLabel, metricSuffix, badge }: CompactCardProps) {
    return (
        <Link
            to={to}
            className="group relative flex flex-col rounded-2xl border border-white/[0.07] bg-[#13151f] p-4 overflow-hidden transition-all duration-200 active:scale-[0.98] hover:border-white/15 hover:shadow-lg"
        >
            {/* Gradient accent */}
            <div
                className="absolute -top-8 -right-8 w-28 h-28 rounded-full blur-3xl opacity-[0.07] group-hover:opacity-[0.12] transition-opacity"
                style={{ background: accent }}
            />

            {/* Top: icon + status */}
            <div className="relative flex items-center justify-between mb-3">
                <div
                    className="w-10 h-10 rounded-xl flex items-center justify-center"
                    style={{ background: `${accent}18`, border: `1px solid ${accent}25` }}
                >
                    <i className={`${icon} text-lg`} style={{ color: accent }} />
                </div>
                <div className="flex flex-col items-end gap-1">
                    <span className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider ${statusColor}`}
                        style={{ background: `${accent}12` }}
                    >
                        <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: accent }} />
                        {status}
                    </span>
                    {badge && <span className="text-[9px] text-gray-600">{badge}</span>}
                </div>
            </div>

            {/* Title */}
            <h3 className="text-lg font-bold text-white mb-0.5 leading-tight">{label}</h3>
            <p className="text-[10px] text-gray-500 mb-3">{sublabel}</p>

            {/* Bottom metric */}
            <div className="flex items-center justify-between pt-3 border-t border-white/[0.06]">
                <span className="text-[10px] text-gray-600 uppercase tracking-wider font-medium">{metricLabel}</span>
                <span className="text-sm font-bold tabular-nums" style={{ color: accent }}>
                    {metric}
                    {metricSuffix && <span className="text-[10px] text-gray-500 ml-0.5">{metricSuffix}</span>}
                </span>
            </div>

            {/* Arrow */}
            <div className="absolute bottom-4 right-4 opacity-0 group-hover:opacity-60 transition-opacity">
                <i className="fas fa-chevron-right text-[10px] text-gray-500" />
            </div>
        </Link>
    );
}

// ── VCP Signal Mini Card ──────────────────────────────────────────────────────

function VCPMiniRow({ name, market, score, accent }: { name: string; market: string; score: number; accent: string }) {
    const displayScore = typeof score === 'number' && !isNaN(score) ? score.toFixed(1) : '—';
    return (
        <div className="flex items-center justify-between py-1.5">
            <div className="flex items-center gap-2">
                <span className="text-[9px] font-bold px-1.5 py-0.5 rounded" style={{ background: `${accent}20`, color: accent }}>{market}</span>
                <span className="text-xs font-semibold text-white truncate max-w-[120px]">{name}</span>
            </div>
            <span className="text-xs font-bold tabular-nums" style={{ color: accent }}>{displayScore}</span>
        </div>
    );
}

// ── Opportunity Score Card ────────────────────────────────────────────────────

function OpportunityScoreCard({ score, krScore, usScore, cryptoScore }: {
    score: number; krScore: number; usScore: number; cryptoScore: number;
}) {
    const getLevel = (s: number) => {
        if (s >= 80) return { label: '적극매수', color: '#10b981' };
        if (s >= 60) return { label: '매수', color: '#22c55e' };
        if (s >= 40) return { label: '관망', color: '#f59e0b' };
        if (s >= 20) return { label: '매도', color: '#f97316' };
        return { label: '적극매도', color: '#ef4444' };
    };
    const current = getLevel(score);
    const color = current.color;
    const arc = Math.min(score / 100, 1);
    const markets: [string, number][] = [['KR', krScore], ['US', usScore], ['Crypto', cryptoScore]];
    return (
        <div className="flex flex-col gap-3 rounded-2xl border border-white/[0.07] bg-[#13151f] p-4 sm:p-5">
            {/* Top: gauge + title */}
            <div className="flex items-center gap-4">
                <div className="flex flex-col items-center gap-1.5 shrink-0">
                    <div className="relative" style={{ width: 80, height: 80 }}>
                        <svg width={80} height={80} viewBox="0 0 80 80">
                            <circle cx={40} cy={40} r={30} fill="none" stroke="#1e2130" strokeWidth={6} />
                            <circle cx={40} cy={40} r={30} fill="none" stroke={color} strokeWidth={6}
                                strokeDasharray={`${arc * 2 * Math.PI * 30} ${2 * Math.PI * 30}`}
                                strokeLinecap="round" transform="rotate(-90 40 40)"
                                style={{ transition: 'stroke-dasharray 0.6s ease' }} />
                        </svg>
                        <div className="absolute inset-0 flex flex-col items-center justify-center">
                            <span className="text-xl font-extrabold tabular-nums leading-none" style={{ color }}>{Math.round(score)}</span>
                            <span className="text-[8px] text-gray-600 font-semibold">/100</span>
                        </div>
                    </div>
                    <span className="text-[10px] font-bold px-2.5 py-0.5 rounded-full" style={{ background: `${color}20`, color }}>{current.label}</span>
                </div>
                <div className="flex flex-col gap-1 flex-1 min-w-0">
                    <span className="text-sm font-bold text-white">Opportunity Score</span>
                    <p className="text-[11px] text-gray-500">3개 시장 종합 진입 기회 지수</p>
                    <div className="flex items-center gap-3 mt-0.5">
                        {markets.map(([m, s]) => (
                            <span key={m} className="text-[11px] font-semibold" style={{ color: getLevel(s).color }}>
                                {m} {Math.round(s)}
                            </span>
                        ))}
                    </div>
                </div>
            </div>
            {/* Bottom: 시장별 강도 바 */}
            <div className="flex flex-col gap-1.5">
                {markets.map(([m, s]) => {
                    const lv = getLevel(s);
                    return (
                        <div key={m} className="flex items-center gap-2">
                            <span className="text-[10px] text-gray-500 w-10 text-right font-medium">{m}</span>
                            <div className="relative flex-1 h-2.5 rounded-full overflow-hidden" style={{ background: 'linear-gradient(to right, #ef4444, #f97316, #f59e0b, #22c55e, #10b981)' }}>
                                <div className="absolute top-0 h-full w-1 bg-white rounded-full shadow-[0_0_4px_rgba(255,255,255,0.9)]"
                                    style={{ left: `${Math.min(Math.max(s, 2), 98)}%`, transform: 'translateX(-50%)', transition: 'left 0.6s ease' }} />
                            </div>
                            <span className="text-[10px] font-bold w-12" style={{ color: lv.color }}>{lv.label}</span>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

// ── Top Signal Card ────────────────────────────────────────────────────────────

function TopSignalCard({ summary, leadingData }: { summary: any; leadingData: any }) {
    const top = summary?.top_signal;
    const byGrade = summary?.by_grade ?? {};
    const sCount = byGrade.S ?? 0;
    const aCount = byGrade.A ?? 0;
    const gradeColor = top?.grade === 'S' ? '#f59e0b' : top?.grade === 'A' ? '#60a5fa' : '#6b7280';

    const leadTop = leadingData?.results?.[0];
    const leadSCount = leadingData?.by_grade?.S ?? 0;
    const leadACount = leadingData?.by_grade?.A ?? 0;
    const leadGradeColor = leadTop?.grade === 'S' ? '#f97316' : leadTop?.grade === 'A' ? '#f59e0b' : '#3b82f6';

    return (
        <div className="flex flex-col gap-2 rounded-2xl border border-white/[0.07] bg-[#13151f] p-4">
            {/* 종가베팅 */}
            <Link to="/dashboard/kr/closing-bet" className="group flex flex-col gap-2 active:scale-[0.98] transition-transform">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded-lg flex items-center justify-center bg-violet-500/10 border border-violet-500/20">
                            <i className="fas fa-chart-bar text-xs text-violet-400" />
                        </div>
                        <span className="text-xs font-bold text-white">오늘 종가베팅</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                        {sCount > 0 && <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-yellow-500/20 text-yellow-400">S×{sCount}</span>}
                        {aCount > 0 && <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400">A×{aCount}</span>}
                        <i className="fas fa-chevron-right text-[9px] text-gray-600 group-hover:text-gray-400" />
                    </div>
                </div>
                {top ? (
                    <div className="flex items-center justify-between bg-white/[0.03] rounded-xl px-3 py-2">
                        <div className="flex items-center gap-2">
                            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded" style={{ background: `${gradeColor}20`, color: gradeColor }}>{top.grade}</span>
                            <span className="text-xs font-semibold text-white truncate">{top.stock_name}</span>
                        </div>
                        <span className={`text-xs font-bold tabular-nums ${top.change_pct > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {top.change_pct > 0 ? '+' : ''}{Number(top.change_pct).toFixed(1)}%
                        </span>
                    </div>
                ) : (
                    <p className="text-[10px] text-gray-600 px-1">아직 시그널 없음</p>
                )}
            </Link>

            {/* 구분선 + 주도주LIVE */}
            {leadTop && (
                <>
                    <div className="border-t border-white/5" />
                    <Link to="/dashboard/kr/leading-stocks"
                        className="group flex flex-col gap-2 active:scale-[0.98] transition-transform"
                        style={{ animation: 'breathe 3s ease-in-out infinite' }}
                    >
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                <div className="w-7 h-7 rounded-lg flex items-center justify-center bg-orange-500/10 border border-orange-500/20">
                                    <i className="fas fa-fire text-xs text-orange-400" />
                                </div>
                                <span className="text-xs font-bold text-white">주도주LIVE</span>
                                <span className="w-1.5 h-1.5 rounded-full bg-orange-400 animate-pulse" />
                            </div>
                            <div className="flex items-center gap-1.5">
                                {leadSCount > 0 && <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-400">S×{leadSCount}</span>}
                                {leadACount > 0 && <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400">A×{leadACount}</span>}
                                <i className="fas fa-chevron-right text-[9px] text-gray-600 group-hover:text-gray-400" />
                            </div>
                        </div>
                        <div className="flex items-center justify-between bg-white/[0.03] rounded-xl px-3 py-2">
                            <div className="flex items-center gap-2">
                                <span className="text-[10px] font-bold px-1.5 py-0.5 rounded" style={{ background: `${leadGradeColor}20`, color: leadGradeColor }}>{leadTop.grade}</span>
                                <span className="text-xs font-semibold text-white truncate">{leadTop.name}</span>
                            </div>
                            <div className="flex items-center gap-2">
                                <span className="text-[9px] text-gray-500 font-mono">{leadTop.score?.total}/100</span>
                                <span className={`text-xs font-bold tabular-nums ${leadTop.change_pct > 0 ? 'text-rose-400' : 'text-blue-400'}`}>
                                    {leadTop.change_pct > 0 ? '+' : ''}{Number(leadTop.change_pct).toFixed(1)}%
                                </span>
                            </div>
                        </div>
                        <style>{`
                            @keyframes breathe {
                                0%, 100% { transform: scale(1); }
                                50% { transform: scale(1.03); }
                            }
                        `}</style>
                    </Link>
                </>
            )}
        </div>
    );
}

// ── Leading Stock Card (주도주 대표종목) ─────────────────────────────────────

function LeadingStockCard({ data }: { data: any }) {
    if (!data?.results?.length) return null;
    const top = data.results[0];
    const sCount = data.by_grade?.S ?? 0;
    const aCount = data.by_grade?.A ?? 0;
    const gradeColor = top.grade === 'S' ? '#f97316' : top.grade === 'A' ? '#f59e0b' : '#3b82f6';
    return (
        <Link to="/dashboard/kr/leading-stocks"
            className="group flex flex-col gap-2 rounded-2xl border border-white/[0.07] bg-[#13151f] p-4 transition-all active:scale-[0.98] hover:border-white/15">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <div className="w-7 h-7 rounded-lg flex items-center justify-center bg-orange-500/10 border border-orange-500/20">
                        <i className="fas fa-fire text-xs text-orange-400" />
                    </div>
                    <span className="text-xs font-bold text-white">주도주LIVE</span>
                    <span className="w-1.5 h-1.5 rounded-full bg-orange-400 animate-pulse" />
                </div>
                <div className="flex items-center gap-1.5">
                    {sCount > 0 && <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-400">S×{sCount}</span>}
                    {aCount > 0 && <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400">A×{aCount}</span>}
                    <i className="fas fa-chevron-right text-[9px] text-gray-600 group-hover:text-gray-400" />
                </div>
            </div>
            <div className="flex items-center justify-between bg-white/[0.03] rounded-xl px-3 py-2">
                <div className="flex items-center gap-2">
                    <span className="text-[10px] font-bold px-1.5 py-0.5 rounded" style={{ background: `${gradeColor}20`, color: gradeColor }}>{top.grade}</span>
                    <span className="text-xs font-semibold text-white truncate">{top.name}</span>
                </div>
                <div className="flex items-center gap-2">
                    <span className="text-[9px] text-gray-500 font-mono">{top.score?.total}/100</span>
                    <span className={`text-xs font-bold tabular-nums ${top.change_pct > 0 ? 'text-rose-400' : 'text-blue-400'}`}>
                        {top.change_pct > 0 ? '+' : ''}{Number(top.change_pct).toFixed(1)}%
                    </span>
                </div>
            </div>
        </Link>
    );
}

// ── Live Dot ──────────────────────────────────────────────────────────────────

function LiveDot() {
    return (
        <span className="relative flex items-center">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping absolute opacity-75" />
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 relative" />
        </span>
    );
}

// ── Main Client Component ──────────────────────────────────────────────────────

export default function DashboardClient({ initialData }: { initialData: InitialData }) {
    const navigate = useNavigate();
    const { user } = useAuth();
    const [briefing, setBriefing] = useState<any>(initialData.briefing);
    const [krGate, setKrGate] = useState<any>(initialData.krGate);
    const [cryptoDom, setCryptoDom] = useState<any>(initialData.cryptoDom);
    const [vcpData, setVcpData] = useState<VCPSummary>({ kr: 0, us: 0, crypto: 0, topSignals: [] });
    const [todaySummary, setTodaySummary] = useState<any>(null);
    const [leadingData, setLeadingData] = useState<any>(null);
    const [waveData, setWaveData] = useState<any>(null);
    const [aiBriefing, setAiBriefing] = useState<AIBriefing | null>(null);
    const [marketIndices, setMarketIndices] = useState<MarketIndexItem[]>([]);
    const [aiChart, setAiChart] = useState<KRAIChartAnalysisResponse | null>(null);
    const [usAiChart, setUsAiChart] = useState<USAIChartAnalysisResponse | null>(null);
    const [communitySummary, setCommunitySummary] = useState<CommunitySummary | null>(null);

    const loadData = useCallback(async () => {
        try {
            const [b, kr, crypto, vcpKr, vcpUs, vcpCrypto, jongga, leading, wave, aiBrf, indices, aiChartRes, usAiChartRes, communitySum] = await Promise.all([
                usAPI.getMarketBriefing().catch(() => null),
                krAPI.getMarketGate().catch(() => null),
                cryptoAPI.getDominance().catch(() => null),
                krAPI.getVCPEnhanced().catch(() => null),
                usAPI.getVCPEnhanced().catch(() => null),
                cryptoAPI.getVCPEnhanced().catch(() => null),
                jonggaAPI.getTodaySummary().catch(() => null),
                krAPI.getLeadingStocks().catch(() => null),
                waveAPI.getDashboard().catch(() => null),
                briefingAPI.getLatest().catch(() => null),
                commonAPI.getMarketIndices().catch(() => null),
                krAPI.getAIChartAnalysis().catch(() => null),
                usAPI.getAIChartAnalysis().catch(() => null),
                communityAPI.getSummary().catch(() => null),
            ]);
            setBriefing(b);
            setKrGate(kr);
            setCryptoDom(crypto);
            setTodaySummary(jongga);
            setLeadingData(leading);
            setWaveData(wave);
            setAiBriefing(aiBrf);
            if (indices?.indices) setMarketIndices(indices.indices);
            if (aiChartRes) setAiChart(aiChartRes);
            if (usAiChartRes) setUsAiChart(usAiChartRes);
            if (communitySum) setCommunitySummary(communitySum);

            setVcpData(buildVcpSummary(vcpKr, vcpUs, vcpCrypto));
        } catch { /* ignore */ }
    }, []);

    useEffect(() => {
        if (!initialData.briefing && !initialData.krGate && !initialData.cryptoDom) {
            loadData();
        } else {
            // Load VCP data even if initial data exists
            Promise.all([
                krAPI.getVCPEnhanced().catch(() => null),
                usAPI.getVCPEnhanced().catch(() => null),
                cryptoAPI.getVCPEnhanced().catch(() => null),
            ]).then(([vcpKr, vcpUs, vcpCrypto]) => {
                setVcpData(buildVcpSummary(vcpKr, vcpUs, vcpCrypto));
            });
        }
    }, [initialData, loadData]);

    usePullToRefreshRegister(loadData);
    useSmartRefresh(loadData, SUMMARY_WATCH_FILES, 15000, true);

    // ── Derived values ─────────────────────────────────────────────────────────

    const vixVal = briefing?.vix?.value != null ? Number(briefing.vix.value).toFixed(2) : '—';
    const vixColor = briefing?.vix?.value > 25 ? 'text-red-400' : briefing?.vix?.value > 18 ? 'text-yellow-400' : 'text-emerald-400';
    const vixSub = briefing?.vix?.change != null ? `${Number(briefing.vix.change) > 0 ? '+' : ''}${Number(briefing.vix.change).toFixed(2)}` : undefined;

    const fgScore = briefing?.fear_greed?.score ?? null;
    const fgLabel = fgScore != null ? (fgScore >= 60 ? 'Greed' : fgScore <= 40 ? 'Fear' : 'Neutral') : '—';
    const fgColor = fgScore != null ? (fgScore >= 60 ? 'text-emerald-400' : fgScore <= 40 ? 'text-red-400' : 'text-yellow-400') : 'text-gray-400';

    const btcPrice = cryptoDom?.btc_price != null
        ? `$${Number(cryptoDom.btc_price).toLocaleString('en-US', { maximumFractionDigits: 0 })}`
        : '—';
    const btcSub = cryptoDom?.btc_30d_change != null ? `${Number(cryptoDom.btc_30d_change) > 0 ? '+' : ''}${Number(cryptoDom.btc_30d_change).toFixed(1)}%` : undefined;

    const gateScore = krGate?.score != null ? String(krGate.score) : '—';
    const gateLabel = krGate?.label ?? '—';
    const gateColor = krGate?.score != null
        ? (krGate.score >= 70 ? 'text-emerald-400' : krGate.score >= 45 ? 'text-yellow-400' : 'text-red-400')
        : 'text-gray-400';

    const krSignalLabel = krGate?.label ?? 'Live';
    const usGateLabel = briefing?.vix?.level ?? 'Live';
    const usVixOk = briefing?.vix?.value != null && Number(briefing.vix.value) < 20;
    const btcSentiment = cryptoDom?.sentiment ?? 'Tracking';

    const totalVCP = vcpData.kr + vcpData.us + vcpData.crypto;

    // ── Opportunity Score ───────────────────────────────────────────────────────
    const krScore = krGate?.score ?? 0;
    // US score: derived from VIX (lower = better) + F&G
    const vixNum = briefing?.vix?.value != null ? Number(briefing.vix.value) : 20;
    const fgNum = fgScore ?? 50;
    const usScore = Math.max(0, Math.min(100, (100 - vixNum * 2.5) * 0.6 + (fgNum) * 0.4));
    // Crypto score: derived from BTC RSI + sentiment
    const btcRsi = cryptoDom?.btc_rsi != null ? Number(cryptoDom.btc_rsi) : 50;
    const cryptoScore = Math.max(0, Math.min(100, btcRsi > 70 ? 40 : btcRsi < 30 ? 35 : btcRsi));
    // Signal bonus: top jongga grade
    const topGrade = todaySummary?.top_signal?.grade;
    const signalBonus = topGrade === 'S' ? 100 : topGrade === 'A' ? 70 : 40;
    const opportunityScore = krScore * 0.40 + usScore * 0.35 + cryptoScore * 0.15 + signalBonus * 0.10;

    // ── Render ────────────────────────────────────────────────────────────────

    return (
        <div className="flex flex-col gap-3 md:gap-4 pb-4">

            {/* ── Header + Scrolling Market Ticker ── */}
            <div className="flex items-center gap-2">
                <LiveDot />
                <h2 className="text-lg md:text-xl font-extrabold tracking-tight text-white leading-none shrink-0">
                    Market{' '}
                    <span className="text-transparent bg-clip-text" style={{ backgroundImage: 'linear-gradient(135deg, #f59e0b 0%, #fbbf24 40%, #f97316 100%)' }}>
                        Overview
                    </span>
                </h2>
                {/* Scrolling ticker */}
                {marketIndices.length > 0 && (
                    <div className="flex-1 overflow-hidden relative min-w-0 ml-2">
                        <div className="absolute left-0 top-0 bottom-0 w-4 z-10 bg-gradient-to-r from-[#0d0f17] to-transparent" />
                        <div className="absolute right-0 top-0 bottom-0 w-4 z-10 bg-gradient-to-l from-[#0d0f17] to-transparent" />
                        <div className="flex gap-3 animate-[tickerScroll_60s_linear_infinite] w-max">
                            {[...marketIndices, ...marketIndices].map((idx, i) => (
                                <span key={`${idx.name}-${i}`} className="flex items-center gap-1 text-[10px] whitespace-nowrap shrink-0">
                                    <span className="text-gray-500 font-medium">{idx.name}</span>
                                    <span className="text-white font-bold tabular-nums">{idx.price}</span>
                                    <span className={`font-bold tabular-nums ${idx.change_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                        {idx.change_pct >= 0 ? '▲' : '▼'} {idx.change_pct >= 0 ? '+' : ''}{idx.change_pct.toFixed(2)}%
                                    </span>
                                </span>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            {/* ── AI Brain 업그레이드 배너 (활성 Pro/Premium 회원, admin/AI Brain 활성자 제외) ── */}
            {(() => {
                const tier = user?.tier ?? null;
                const role = user?.role ?? 'user';
                const isAdmin = role === 'admin';
                const isActivePaid = (tier === 'pro' || tier === 'premium') && user?.status === 'approved' && !user?.is_pro_expired;
                const alreadyAibainActive = !!user?.is_aibain_active;
                if (isAdmin || !isActivePaid || alreadyAibainActive) return null;
                const tierLabel = tier === 'pro' ? 'Pro' : 'Ultra Pro';
                return (
                    <Link
                        to="/dashboard/ai-bain"
                        className="group block rounded-2xl border border-cyan-500/30 bg-gradient-to-r from-cyan-500/[0.08] via-[#13151f] to-[#1c1c1e] p-3.5 sm:p-4 overflow-hidden transition-all duration-200 active:scale-[0.99] hover:border-cyan-500/50 relative"
                    >
                        <div className="absolute -top-6 -right-6 w-28 h-28 rounded-full blur-3xl opacity-[0.10] group-hover:opacity-[0.16] transition-opacity bg-gradient-to-br from-cyan-400 to-sky-500" />
                        <div className="relative flex items-center gap-3">
                            <div className="w-10 h-10 sm:w-11 sm:h-11 rounded-xl bg-cyan-500/15 border border-cyan-500/30 flex items-center justify-center shrink-0">
                                <i className="fas fa-robot text-cyan-300 text-lg" />
                            </div>
                            <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-1.5 flex-wrap">
                                    <span className="text-white font-bold text-sm">AI Brain 알파 스캐너 추가</span>
                                    <span className="text-[8px] font-bold tracking-wider px-1.5 py-0.5 rounded-full bg-cyan-500/15 text-cyan-300 border border-cyan-500/25 animate-pulse" style={{ animationDuration: '2s' }}>
                                        NEW
                                    </span>
                                </div>
                                <p className="text-[11px] sm:text-xs text-gray-400 mt-0.5 leading-tight">
                                    <span className="text-cyan-300/90">{tierLabel} 구독 유지 + AI Brain</span> · MCP TOP 3 / 신규 5종 시그널 · <span className="text-cyan-200 font-semibold">+40,000원/30일</span>
                                </p>
                            </div>
                            <div className="shrink-0 flex items-center gap-2">
                                <span className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-cyan-500/15 text-cyan-200 font-bold text-xs border border-cyan-400/30">
                                    <i className="fas fa-paper-plane text-[10px]" />
                                    업그레이드 신청
                                </span>
                                <i className="fas fa-chevron-right text-[11px] text-cyan-400/70 group-hover:text-cyan-300 transition-colors" />
                            </div>
                        </div>
                    </Link>
                );
            })()}

            {/* ── AI Briefing Highlight Widget ── */}
            <Link to={`/dashboard/briefing?tab=${aiBriefing?.type || 'morning'}`}
                className="group block rounded-2xl border border-amber-500/20 bg-gradient-to-br from-[#1a1520] via-[#161320] to-[#13151f] overflow-hidden hover:border-amber-500/40 transition-all duration-300 active:scale-[0.995] relative"
            >
                {/* Glow effect */}
                <div className="absolute -top-8 -right-8 w-32 h-32 rounded-full blur-3xl opacity-[0.08] group-hover:opacity-[0.15] transition-opacity duration-500 bg-gradient-to-br from-amber-400 to-orange-500" />
                <div className="absolute -bottom-6 -left-6 w-24 h-24 rounded-full blur-3xl opacity-[0.05] group-hover:opacity-[0.1] transition-opacity duration-500 bg-gradient-to-tr from-amber-500 to-yellow-400" />

                {/* Top bar: type badge + sentiment + time */}
                <div className="flex items-center justify-between px-4 pt-3 pb-1 relative z-10">
                    <div className="flex items-center gap-2">
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/15 text-amber-400 border border-amber-500/20">
                            <i className={`fas ${aiBriefing?.type === 'closing' ? 'fa-moon' : 'fa-sun'} text-[8px]`} />
                            {aiBriefing?.type === 'closing' ? '마감 브리핑' : '조간 브리핑'}
                        </span>
                        {aiBriefing?.market_sentiment && (
                            <span className={`px-1.5 py-0.5 rounded text-[9px] font-extrabold ${
                                aiBriefing.market_sentiment === 'BULLISH' ? 'bg-emerald-500/15 text-emerald-400' :
                                aiBriefing.market_sentiment === 'BEARISH' ? 'bg-red-500/15 text-red-400' :
                                'bg-gray-500/15 text-gray-400'
                            }`}>
                                {aiBriefing.market_sentiment}
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-2">
                        {aiBriefing?.generated_at && (
                            <span className="text-[9px] text-gray-600">
                                {new Date(aiBriefing.generated_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}
                            </span>
                        )}
                        <i className="fas fa-chevron-right text-[10px] text-gray-600 group-hover:text-amber-400 transition-colors" />
                    </div>
                </div>

                {/* Title */}
                <div className="px-4 pb-2 relative z-10">
                    <h3 className="text-[13px] sm:text-sm font-bold text-white leading-snug line-clamp-2 group-hover:text-amber-50 transition-colors">
                        {aiBriefing?.title || 'AI 브리핑을 불러오는 중...'}
                    </h3>
                </div>

                {/* Summary */}
                {aiBriefing?.summary && (
                    <div className="px-4 pb-2 relative z-10">
                        <p className="text-[11px] text-gray-400 leading-relaxed line-clamp-2">
                            {aiBriefing.summary}
                        </p>
                    </div>
                )}

                {/* Key events tags + market indicators */}
                <div className="px-4 pb-3 flex items-center justify-between gap-2 relative z-10">
                    <div className="flex items-center gap-1.5 overflow-hidden flex-1 min-w-0">
                        {(aiBriefing?.key_events || []).slice(0, 3).map((evt, i) => (
                            <span key={i} className="inline-block px-1.5 py-0.5 rounded bg-white/[0.04] text-[9px] text-gray-500 truncate max-w-[120px] shrink-0">
                                {evt}
                            </span>
                        ))}
                    </div>
                    {/* Mini market indicators */}
                    <div className="flex items-center gap-2 shrink-0">
                        <span className={`text-[10px] font-bold tabular-nums ${vixColor}`}>{vixVal !== '—' ? `VIX ${vixVal}` : ''}</span>
                        <span className={`text-[10px] font-bold tabular-nums ${fgColor}`}>{fgScore != null ? `F&G ${fgScore}` : ''}</span>
                    </div>
                </div>
            </Link>

            {/* ── Opportunity Score + Top Signal ── */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <OpportunityScoreCard
                    score={opportunityScore}
                    krScore={krScore}
                    usScore={usScore}
                    cryptoScore={cryptoScore}
                />
                {todaySummary && <TopSignalCard summary={todaySummary} leadingData={leadingData} />}
            </div>

            {/* ── Wave Pattern Section ── */}
            {waveData && (waveData.summary?.active > 0 || waveData.active_signals?.length > 0) && (
                <div
                    className="group relative rounded-2xl border border-white/[0.07] bg-[#13151f] p-4 overflow-hidden transition-all duration-200 hover:border-pink-500/20"
                >
                    {/* Animated gradient blobs */}
                    <div className="absolute -top-10 -right-10 w-36 h-36 rounded-full blur-3xl opacity-[0.08] group-hover:opacity-[0.15] transition-opacity duration-700 bg-gradient-to-br from-pink-500 to-rose-600 animate-pulse" />
                    <div className="absolute -bottom-12 -left-12 w-28 h-28 rounded-full blur-3xl opacity-[0.05] group-hover:opacity-[0.1] transition-opacity duration-700 bg-gradient-to-tr from-fuchsia-500 to-pink-400"
                        style={{ animation: 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite 1.5s' }}
                    />

                    {/* Animated wave SVG background */}
                    <div className="absolute inset-0 opacity-[0.03] group-hover:opacity-[0.06] transition-opacity duration-500 overflow-hidden pointer-events-none">
                        <svg viewBox="0 0 400 80" className="absolute bottom-0 left-0 w-full h-16" preserveAspectRatio="none">
                            <path d="M0,40 C50,20 100,60 150,40 C200,20 250,60 300,40 C350,20 400,50 400,40 L400,80 L0,80 Z"
                                fill="url(#waveGrad)" className="animate-[waveShift_4s_ease-in-out_infinite]" />
                            <path d="M0,50 C60,30 120,65 180,45 C240,25 300,60 400,45 L400,80 L0,80 Z"
                                fill="url(#waveGrad2)" className="animate-[waveShift_5s_ease-in-out_infinite_reverse]" />
                            <defs>
                                <linearGradient id="waveGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                                    <stop offset="0%" stopColor="#ec4899" />
                                    <stop offset="100%" stopColor="#f43f5e" />
                                </linearGradient>
                                <linearGradient id="waveGrad2" x1="0%" y1="0%" x2="100%" y2="0%">
                                    <stop offset="0%" stopColor="#a855f7" />
                                    <stop offset="100%" stopColor="#ec4899" />
                                </linearGradient>
                            </defs>
                        </svg>
                    </div>

                    {/* Header — 클릭 시 Wave Overview 페이지 이동 */}
                    <Link to="/dashboard/wave" className="relative flex items-center justify-between mb-3 active:scale-[0.98] transition-transform">
                        <div className="flex items-center gap-2.5">
                            <div className="relative w-10 h-10 rounded-xl flex items-center justify-center bg-pink-500/10 border border-pink-500/20 group-hover:bg-pink-500/20 transition-colors duration-300">
                                <div className="absolute inset-0 rounded-xl border border-pink-400/30 animate-ping opacity-0 group-hover:opacity-30" style={{ animationDuration: '2s' }} />
                                <i className="fas fa-wave-square text-lg text-pink-400 group-hover:scale-110 transition-transform duration-300" />
                            </div>
                            <div>
                                <div className="flex items-center gap-2">
                                    <h3 className="text-base font-bold text-white">W 패턴</h3>
                                    <span className="relative flex items-center">
                                        <span className="w-1.5 h-1.5 rounded-full bg-pink-400 animate-ping absolute opacity-75" />
                                        <span className="w-1.5 h-1.5 rounded-full bg-pink-400 relative" />
                                    </span>
                                </div>
                                <p className="text-[10px] text-gray-500">M&W 차트 패턴 AI 탐지</p>
                            </div>
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-pink-500/10 text-pink-400 tabular-nums group-hover:bg-pink-500/20 transition-colors duration-300">
                                {waveData.summary?.active ?? 0}
                            </span>
                            <i className="fas fa-chevron-right text-[10px] text-gray-600 group-hover:text-pink-400 group-hover:translate-x-0.5 transition-all duration-300" />
                        </div>
                    </Link>

                    {/* Stats breakdown with stagger animation */}
                    <div className="relative flex items-center gap-4 mb-3">
                        {[
                            { label: '활성', value: waveData.summary?.active ?? 0, color: 'pink', dot: 'bg-pink-400', text: 'text-pink-400' },
                            { label: '승리', value: waveData.summary?.wins ?? 0, color: 'emerald', dot: 'bg-emerald-400', text: 'text-emerald-400' },
                            { label: '패배', value: waveData.summary?.losses ?? 0, color: 'red', dot: 'bg-red-400', text: 'text-red-400' },
                        ].map((stat, i) => (
                            <span key={stat.label} className="flex items-center gap-1.5 text-[10px] font-semibold"
                                style={{ animation: `fadeInUp 0.4s ease-out ${i * 0.1}s both` }}>
                                <span className={`w-2 h-2 rounded-full ${stat.dot}`} />
                                <span className="text-gray-400">{stat.label}</span>
                                <span className={`${stat.text} tabular-nums`}>{stat.value}</span>
                            </span>
                        ))}
                        {waveData.summary?.win_rate > 0 && (
                            <span className="text-[10px] font-bold text-amber-400 ml-auto animate-pulse" style={{ animationDuration: '2.5s' }}>
                                승률 {waveData.summary.win_rate}%
                            </span>
                        )}
                    </div>

                    {/* Top active signals — 종목 클릭 시 차트 페이지 이동 */}
                    {waveData.active_signals?.length > 0 && (
                        <div className="relative border-t border-white/[0.06] pt-2">
                            {waveData.active_signals
                                .filter((sig: any, idx: number, arr: any[]) =>
                                    arr.findIndex((s: any) => s.ticker === sig.ticker && s.pattern_class === sig.pattern_class) === idx
                                )
                                .slice(0, 5).map((sig: any, i: number) => {
                                const isW = sig.pattern_class === 'W';
                                const accent = isW ? '#ec4899' : '#f43f5e';
                                return (
                                    <div key={i}
                                        className="flex items-center justify-between py-1.5 hover:bg-white/[0.04] rounded-lg px-1 -mx-1 transition-colors duration-200 cursor-pointer active:scale-[0.98]"
                                        style={{ animation: `fadeInUp 0.3s ease-out ${0.3 + i * 0.08}s both` }}
                                        onClick={() => navigate(`/dashboard/wave?ticker=${sig.ticker}&market=KR`)}
                                    >
                                        <div className="flex items-center gap-2">
                                            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded" style={{ background: `${accent}20`, color: accent }}>
                                                {sig.pattern_class}
                                            </span>
                                            <span className="text-xs font-semibold text-white truncate max-w-[120px]">{sig.name || sig.ticker}</span>
                                            <span className="text-[9px] text-gray-600 hidden sm:inline">{sig.wave_label}</span>
                                        </div>
                                        <div className="flex items-center gap-1.5">
                                            <div className="w-12 h-1 rounded-full bg-white/[0.06] overflow-hidden hidden sm:block">
                                                <div className="h-full rounded-full transition-all duration-700"
                                                    style={{
                                                        width: `${sig.confidence}%`,
                                                        background: `linear-gradient(90deg, ${accent}80, ${accent})`,
                                                        animation: `growWidth 0.8s ease-out ${0.5 + i * 0.1}s both`,
                                                    }}
                                                />
                                            </div>
                                            <span className="text-xs font-bold tabular-nums" style={{ color: accent }}>{sig.confidence}</span>
                                            <i className="fas fa-chart-line text-[9px] text-gray-700 hover:text-pink-400 transition-colors" />
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}

                    {/* Inline keyframes */}
                    <style>{`
                        @keyframes fadeInUp {
                            from { opacity: 0; transform: translateY(8px); }
                            to { opacity: 1; transform: translateY(0); }
                        }
                        @keyframes waveShift {
                            0%, 100% { transform: translateX(0); }
                            50% { transform: translateX(-20px); }
                        }
                        @keyframes growWidth {
                            from { width: 0%; }
                        }
                    `}</style>
                </div>
            )}

            {/* ── VCP Enhanced Section ── */}
            <Link
                to="/dashboard/vcp-enhanced"
                className="group relative rounded-2xl border border-white/[0.07] bg-[#13151f] p-4 overflow-hidden transition-all duration-200 active:scale-[0.98] hover:border-cyan-500/20"
            >
                <div className="absolute -top-8 -right-8 w-32 h-32 rounded-full blur-3xl opacity-[0.06] group-hover:opacity-[0.1] transition-opacity bg-gradient-to-br from-cyan-400 to-teal-500" />

                {/* Header */}
                <div className="relative flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2.5">
                        <div className="w-10 h-10 rounded-xl flex items-center justify-center bg-cyan-500/10 border border-cyan-500/20">
                            <i className="fas fa-bolt text-lg text-cyan-400" />
                        </div>
                        <div>
                            <h3 className="text-base font-bold text-white">VCP 강화</h3>
                            <p className="text-[10px] text-gray-500">거래량 수축 패턴 · 전 시장</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-cyan-500/10 text-cyan-400 tabular-nums">
                            {totalVCP}
                        </span>
                        <i className="fas fa-chevron-right text-[10px] text-gray-600 group-hover:text-cyan-400 transition-colors" />
                    </div>
                </div>

                {/* Market breakdown */}
                <div className="relative flex items-center gap-3 mb-3">
                    <span className="flex items-center gap-1.5 text-[10px] font-semibold">
                        <span className="w-2 h-2 rounded-full bg-blue-400" />
                        <span className="text-gray-400">KR</span>
                        <span className="text-blue-400 tabular-nums">{vcpData.kr}</span>
                    </span>
                    <span className="flex items-center gap-1.5 text-[10px] font-semibold">
                        <span className="w-2 h-2 rounded-full bg-emerald-400" />
                        <span className="text-gray-400">US</span>
                        <span className="text-emerald-400 tabular-nums">{vcpData.us}</span>
                    </span>
                    <span className="flex items-center gap-1.5 text-[10px] font-semibold">
                        <span className="w-2 h-2 rounded-full bg-amber-400" />
                        <span className="text-gray-400">Crypto</span>
                        <span className="text-amber-400 tabular-nums">{vcpData.crypto}</span>
                    </span>
                </div>

                {/* Top signals */}
                {vcpData.topSignals.length > 0 && (
                    <div className="relative border-t border-white/[0.06] pt-2">
                        {vcpData.topSignals.map((sig, i) => {
                            const c = sig.market === 'KR' ? '#3b82f6' : sig.market === 'US' ? '#10b981' : '#f59e0b';
                            return <VCPMiniRow key={i} name={sig.name} market={sig.market} score={sig.score} accent={c} />;
                        })}
                    </div>
                )}
            </Link>

            {/* ── AI Chart Analysis Section ── */}
            {aiChart && aiChart.signals.length > 0 && (
                <Link
                    to="/dashboard/kr/ai-chart"
                    className="group relative rounded-2xl border border-white/[0.07] bg-[#13151f] p-4 overflow-hidden transition-all duration-200 active:scale-[0.98] hover:border-violet-500/20"
                >
                    <div className="absolute -top-8 -right-8 w-32 h-32 rounded-full blur-3xl opacity-[0.06] group-hover:opacity-[0.1] transition-opacity bg-gradient-to-br from-violet-400 to-purple-500" />

                    {/* Header */}
                    <div className="relative flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2.5">
                            <div className="w-10 h-10 rounded-xl flex items-center justify-center bg-violet-500/10 border border-violet-500/20">
                                <i className="fas fa-robot text-lg text-violet-400" />
                            </div>
                            <div>
                                <h3 className="text-base font-bold text-white">AI 차트 분석</h3>
                                <p className="text-[10px] text-gray-500">Gemini Vision · KR 100 종목 기술적 분석</p>
                            </div>
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-violet-500/10 text-violet-400 tabular-nums">
                                {aiChart.summary.total}
                            </span>
                            <i className="fas fa-chevron-right text-[10px] text-gray-600 group-hover:text-violet-400 transition-colors" />
                        </div>
                    </div>

                    {/* Signal breakdown */}
                    <div className="relative flex items-center gap-3 mb-3">
                        <span className="flex items-center gap-1.5 text-[10px] font-semibold">
                            <span className="w-2 h-2 rounded-full bg-emerald-400" />
                            <span className="text-gray-400">매수</span>
                            <span className="text-emerald-400 tabular-nums">{aiChart.summary.by_signal?.BUY ?? 0}</span>
                        </span>
                        <span className="flex items-center gap-1.5 text-[10px] font-semibold">
                            <span className="w-2 h-2 rounded-full bg-yellow-400" />
                            <span className="text-gray-400">관망</span>
                            <span className="text-yellow-400 tabular-nums">{aiChart.summary.by_signal?.HOLD ?? 0}</span>
                        </span>
                        <span className="flex items-center gap-1.5 text-[10px] font-semibold">
                            <span className="w-2 h-2 rounded-full bg-red-400" />
                            <span className="text-gray-400">매도</span>
                            <span className="text-red-400 tabular-nums">{aiChart.summary.by_signal?.SELL ?? 0}</span>
                        </span>
                        <span className="ml-auto text-[9px] text-gray-600">평균 신뢰도 {aiChart.summary.avg_confidence}%</span>
                    </div>

                    {/* Top BUY signals */}
                    {(() => {
                        const buys = aiChart.signals
                            .filter(s => s.signal === 'BUY')
                            .sort((a, b) => b.confidence - a.confidence)
                            .slice(0, 5);
                        if (buys.length === 0) return null;
                        return (
                            <div className="relative border-t border-white/[0.06] pt-2">
                                {buys.map((s, i) => (
                                    <div key={i} className="flex items-center justify-between py-1.5">
                                        <div className="flex items-center gap-2">
                                            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400">매수</span>
                                            <span className="text-xs font-semibold text-white truncate max-w-[120px]">{s.stock_name}</span>
                                            <span className="text-[9px] text-gray-600">{s.ma_status}</span>
                                        </div>
                                        <span className="text-xs font-bold tabular-nums text-emerald-400">{s.confidence}</span>
                                    </div>
                                ))}
                            </div>
                        );
                    })()}
                </Link>
            )}

            {/* ── US AI Chart Analysis Section ── */}
            {usAiChart && usAiChart.signals.length > 0 && (
                <Link
                    to="/dashboard/us/ai-chart"
                    className="group relative rounded-2xl border border-white/[0.07] bg-[#13151f] p-4 overflow-hidden transition-all duration-200 active:scale-[0.98] hover:border-green-500/20"
                >
                    <div className="absolute -top-8 -right-8 w-32 h-32 rounded-full blur-3xl opacity-[0.06] group-hover:opacity-[0.1] transition-opacity bg-gradient-to-br from-green-400 to-emerald-500" />

                    <div className="relative flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2.5">
                            <div className="w-10 h-10 rounded-xl flex items-center justify-center bg-green-500/10 border border-green-500/20">
                                <i className="fas fa-robot text-lg text-green-400" />
                            </div>
                            <div>
                                <h3 className="text-base font-bold text-white">US AI 차트</h3>
                                <p className="text-[10px] text-gray-500">Gemini Vision · S&P 500 Top 100</p>
                            </div>
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-green-500/10 text-green-400 tabular-nums">
                                {usAiChart.summary.total}
                            </span>
                            <i className="fas fa-chevron-right text-[10px] text-gray-600 group-hover:text-green-400 transition-colors" />
                        </div>
                    </div>

                    <div className="relative flex items-center gap-3 mb-3">
                        <span className="flex items-center gap-1.5 text-[10px] font-semibold">
                            <span className="w-2 h-2 rounded-full bg-emerald-400" />
                            <span className="text-gray-400">매수</span>
                            <span className="text-emerald-400 tabular-nums">{usAiChart.summary.by_signal?.BUY ?? 0}</span>
                        </span>
                        <span className="flex items-center gap-1.5 text-[10px] font-semibold">
                            <span className="w-2 h-2 rounded-full bg-yellow-400" />
                            <span className="text-gray-400">관망</span>
                            <span className="text-yellow-400 tabular-nums">{usAiChart.summary.by_signal?.HOLD ?? 0}</span>
                        </span>
                        <span className="flex items-center gap-1.5 text-[10px] font-semibold">
                            <span className="w-2 h-2 rounded-full bg-red-400" />
                            <span className="text-gray-400">매도</span>
                            <span className="text-red-400 tabular-nums">{usAiChart.summary.by_signal?.SELL ?? 0}</span>
                        </span>
                        <span className="ml-auto text-[9px] text-gray-600">평균 신뢰도 {usAiChart.summary.avg_confidence}%</span>
                    </div>

                    {(() => {
                        const buys = usAiChart.signals
                            .filter(s => s.signal === 'BUY')
                            .sort((a, b) => b.confidence - a.confidence)
                            .slice(0, 5);
                        if (buys.length === 0) return null;
                        return (
                            <div className="relative border-t border-white/[0.06] pt-2">
                                {buys.map((s, i) => (
                                    <div key={i} className="flex items-center justify-between py-1.5">
                                        <div className="flex items-center gap-2">
                                            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400">매수</span>
                                            <span className="text-xs font-semibold text-white truncate max-w-[120px]">{s.name}</span>
                                            <span className="text-[9px] text-gray-600">{s.ticker}</span>
                                        </div>
                                        <span className="text-xs font-bold tabular-nums text-emerald-400">{s.confidence}</span>
                                    </div>
                                ))}
                            </div>
                        );
                    })()}
                </Link>
            )}

            {/* ── AI Brain 알파 스캐너 Section (Pro + AI Brain 구독자 진입점) ── */}
            {(() => {
                const tier = user?.tier ?? null;
                const role = user?.role ?? 'user';
                const isAdmin = role === 'admin';
                const hasProAccess = isAdmin || tier === 'pro' || tier === 'premium';
                return (
                    <Link
                        to="/dashboard/ai-bain"
                        className="group relative rounded-2xl border border-cyan-500/20 bg-[#13151f] p-4 overflow-hidden transition-all duration-200 active:scale-[0.98] hover:border-cyan-500/40"
                    >
                        <div className="absolute -top-8 -right-8 w-32 h-32 rounded-full blur-3xl opacity-[0.08] group-hover:opacity-[0.14] transition-opacity bg-gradient-to-br from-cyan-400 to-sky-500" />

                        <div className="relative flex items-center justify-between mb-3">
                            <div className="flex items-center gap-2.5">
                                <div className="w-10 h-10 rounded-xl flex items-center justify-center bg-cyan-500/10 border border-cyan-500/25">
                                    <i className="fas fa-robot text-lg text-cyan-400" />
                                </div>
                                <div>
                                    <div className="flex items-center gap-1.5">
                                        <h3 className="text-base font-bold text-white">AI Brain 알파 스캐너</h3>
                                        <span className="text-[8px] font-bold tracking-wider px-1.5 py-0.5 rounded-full bg-cyan-500/15 text-cyan-400 border border-cyan-500/25 animate-pulse" style={{ animationDuration: '2s' }}>
                                            NEW
                                        </span>
                                    </div>
                                    <p className="text-[10px] text-gray-500">MCP TOP 3 · 신규 5종 · 실시간 시그널</p>
                                </div>
                            </div>
                            <div className="flex items-center gap-2">
                                {hasProAccess ? (
                                    <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-cyan-500/10 text-cyan-300 tabular-nums">
                                        이용 가능
                                    </span>
                                ) : (
                                    <span className="px-2.5 py-1 rounded-full text-[10px] font-bold bg-amber-500/10 text-amber-300 border border-amber-500/20">
                                        구독 필요
                                    </span>
                                )}
                                <i className="fas fa-chevron-right text-[10px] text-gray-600 group-hover:text-cyan-400 transition-colors" />
                            </div>
                        </div>

                        <div className="relative flex items-center gap-3 mb-3 flex-wrap">
                            <span className="flex items-center gap-1.5 text-[10px] font-semibold">
                                <span className="w-2 h-2 rounded-full bg-cyan-400" />
                                <span className="text-gray-400">알파 스캐너</span>
                            </span>
                            <span className="flex items-center gap-1.5 text-[10px] font-semibold">
                                <span className="w-2 h-2 rounded-full bg-sky-400" />
                                <span className="text-gray-400">MCP 워크플로우</span>
                            </span>
                            <span className="flex items-center gap-1.5 text-[10px] font-semibold">
                                <span className="w-2 h-2 rounded-full bg-blue-400" />
                                <span className="text-gray-400">그래프RAG 분석</span>
                            </span>
                            <span className="ml-auto text-[9px] text-gray-600">90,000원/30일</span>
                        </div>

                        <div className="relative border-t border-white/[0.06] pt-2.5">
                            <div className="flex items-center justify-between gap-3">
                                <p className="text-xs text-gray-300 leading-relaxed">
                                    {hasProAccess
                                        ? '실시간 알파 스캐너 결과와 MCP TOP 3 이벤트를 한 곳에서 확인.'
                                        : 'Pro + AI Brain 구독으로 실시간 시그널 서비스를 받아보세요.'}
                                </p>
                                <span className={`shrink-0 text-[11px] font-bold ${hasProAccess ? 'text-cyan-300' : 'text-amber-300'}`}>
                                    {hasProAccess ? '전체 보기 →' : '구독 신청 →'}
                                </span>
                            </div>
                        </div>
                    </Link>
                );
            })()}

            {/* ── Market Cards Grid ── */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <CompactCard
                    to="/dashboard/kr"
                    icon="fas fa-chart-line"
                    label="KR Market"
                    sublabel="KOSPI · KOSDAQ · 종가베팅 V2 · 기관 수급"
                    accent="#3b82f6"
                    status={krSignalLabel}
                    statusColor={gateColor}
                    metric={gateScore}
                    metricLabel="게이트 점수"
                    metricSuffix="/ 100"
                />
                <CompactCard
                    to="/dashboard/us"
                    icon="fas fa-globe-americas"
                    label="US Market"
                    sublabel="SPY · Nasdaq · Smart Money · Sector Rotation"
                    accent="#10b981"
                    status={usGateLabel || 'Live'}
                    statusColor={usVixOk ? 'text-emerald-400' : 'text-yellow-400'}
                    metric={vixVal}
                    metricLabel="VIX"
                    badge={fgScore != null ? `F&G ${fgScore}` : undefined}
                />
                <CompactCard
                    to="/dashboard/crypto"
                    icon="fab fa-bitcoin"
                    label="Crypto"
                    sublabel="BTC · ETH · On-chain · VCP Signals"
                    accent="#f59e0b"
                    status={btcSentiment}
                    statusColor="text-amber-400"
                    metric={btcPrice}
                    metricLabel="BTC Price"
                    badge={cryptoDom?.btc_rsi != null ? `RSI ${Number(cryptoDom.btc_rsi).toFixed(0)}` : undefined}
                />
                <CompactCard
                    to="/dashboard/stock-analyzer"
                    icon="fas fa-crosshairs"
                    label="ProPicks"
                    sublabel="Investing.com · AI Analysis · Stock Screener"
                    accent="#a855f7"
                    status="AI Powered"
                    statusColor="text-purple-400"
                    metric={briefing?.smart_money?.top_picks?.picks?.[0]?.ticker ?? '—'}
                    metricLabel="최고 추천"
                />
                <CompactCard
                    to="/dashboard/stock-analyzer?panel=dart-deep#dart-deep"
                    icon="fas fa-file-invoice-dollar"
                    label="DART 심층분석"
                    sublabel="10년 재무제표 · Gemini DCF · 6단계 파이프라인"
                    accent="#06b6d4"
                    status="Gemini 2.5"
                    statusColor="text-cyan-400"
                    metric="10Y"
                    metricLabel="재무분석"
                />
                <CompactCard
                    to="/dashboard/community"
                    icon="fas fa-comments"
                    label="커뮤니티"
                    sublabel="게시판 · 수식마켓 · 토론"
                    accent="#06b6d4"
                    status={communitySummary?.today_posts ? `+${communitySummary.today_posts} today` : 'Active'}
                    statusColor="text-cyan-400"
                    metric={communitySummary ? String(communitySummary.total_posts) : '—'}
                    metricLabel="Posts"
                    badge={communitySummary?.pending_purchases ? `${communitySummary.pending_purchases} pending` : undefined}
                />
            </div>

            {/* ── Bottom utility ── */}
            <div className="flex items-center justify-between pt-1">
                <div className="flex items-center gap-3">
                    <span className="text-[11px] text-gray-700">MarketFlow</span>
                </div>
                <span className="text-[10px] text-gray-700 font-mono">v2.7.0</span>
            </div>
        </div>
    );
}
