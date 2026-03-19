

import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useNavigate } from 'react-router-dom';
import { usAPI, krAPI, cryptoAPI } from '@/lib/api';
import { usePullToRefreshRegister } from '@/components/layout/PullToRefreshProvider';

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
    const [briefing, setBriefing] = useState<any>(initialData.briefing);
    const [krGate, setKrGate] = useState<any>(initialData.krGate);
    const [cryptoDom, setCryptoDom] = useState<any>(initialData.cryptoDom);
    const [vcpData, setVcpData] = useState<VCPSummary>({ kr: 0, us: 0, crypto: 0, topSignals: [] });

    const loadData = useCallback(async () => {
        try {
            const [b, kr, crypto, vcpKr, vcpUs, vcpCrypto] = await Promise.all([
                usAPI.getMarketBriefing().catch(() => null),
                krAPI.getMarketGate().catch(() => null),
                cryptoAPI.getDominance().catch(() => null),
                krAPI.getVCPEnhanced().catch(() => null),
                usAPI.getVCPEnhanced().catch(() => null),
                cryptoAPI.getVCPEnhanced().catch(() => null),
            ]);
            setBriefing(b);
            setKrGate(kr);
            setCryptoDom(crypto);

            // VCP summary
            const allSignals: Array<{ name: string; market: string; score: number }> = [];
            const addSignals = (data: any, market: string) => {
                if (data?.signals) {
                    data.signals.slice(0, 3).forEach((s: any) => {
                        const score = typeof s.composite === 'object'
                            ? (s.composite?.composite_score ?? 0)
                            : (s.composite ?? s.score ?? 0);
                        allSignals.push({ name: s.name || s.ticker || '?', market, score });
                    });
                }
            };
            addSignals(vcpKr, 'KR');
            addSignals(vcpUs, 'US');
            addSignals(vcpCrypto, 'CRYPTO');

            setVcpData({
                kr: vcpKr?.signals?.length ?? 0,
                us: vcpUs?.signals?.length ?? 0,
                crypto: vcpCrypto?.signals?.length ?? 0,
                topSignals: allSignals.sort((a, b) => b.score - a.score).slice(0, 5),
            });
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
                const allSignals: Array<{ name: string; market: string; score: number }> = [];
                const addSignals = (data: any, market: string) => {
                    if (data?.signals) {
                        data.signals.slice(0, 3).forEach((s: any) => {
                            const score = typeof s.composite === 'object'
                                ? (s.composite?.composite_score ?? 0)
                                : (s.composite ?? s.score ?? 0);
                            allSignals.push({ name: s.name || s.ticker || '?', market, score });
                        });
                    }
                };
                addSignals(vcpKr, 'KR');
                addSignals(vcpUs, 'US');
                addSignals(vcpCrypto, 'CRYPTO');
                setVcpData({
                    kr: vcpKr?.signals?.length ?? 0,
                    us: vcpUs?.signals?.length ?? 0,
                    crypto: vcpCrypto?.signals?.length ?? 0,
                    topSignals: allSignals.sort((a, b) => b.score - a.score).slice(0, 5),
                });
            });
        }
    }, [initialData, loadData]);

    usePullToRefreshRegister(loadData);

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

    // ── Render ────────────────────────────────────────────────────────────────

    return (
        <div className="flex flex-col gap-3 md:gap-4 pb-4">

            {/* ── Header with animated title ── */}
            <div className="flex items-end justify-between">
                <div>
                    <div className="flex items-center gap-2 mb-1.5">
                        <LiveDot />
                        <span className="text-[10px] font-semibold text-emerald-400 uppercase tracking-widest">Live Markets</span>
                        <span className="text-[10px] text-gray-600 ml-1">
                            {new Date().toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })}
                        </span>
                    </div>
                    <h2 className="text-2xl md:text-3xl font-extrabold tracking-tighter text-white leading-none">
                        Market{' '}
                        <span className="text-transparent bg-clip-text" style={{ backgroundImage: 'linear-gradient(135deg, #f59e0b 0%, #fbbf24 40%, #f97316 100%)' }}>
                            Overview
                        </span>
                    </h2>
                    <p className="text-[11px] text-gray-500 mt-0.5">AI-Powered Multi-Market Intelligence</p>
                </div>

                {/* Desktop quick links */}
                <div className="hidden md:flex items-center gap-1">
                    {[
                        { label: 'Briefing', to: '/dashboard/us' },
                        { label: 'VCP', to: '/dashboard/vcp-enhanced' },
                        { label: '종가베팅', to: '/dashboard/kr/closing-bet' },
                    ].map(link => (
                        <Link key={link.to} to={link.to}
                            className="px-3 py-1.5 text-[11px] font-medium text-gray-500 hover:text-white hover:bg-white/[0.06] rounded-lg transition-all border border-transparent hover:border-white/10">
                            {link.label}
                        </Link>
                    ))}
                </div>
            </div>

            {/* ── Compact Stats Row ── */}
            <div className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-[#13151f] overflow-x-auto scrollbar-none">
                <StatPill label="VIX" value={vixVal} sub={vixSub} color={vixColor} />
                <div className="w-px h-8 bg-white/[0.06]" />
                <StatPill label="F&G" value={fgScore != null ? String(fgScore) : '—'} sub={fgLabel} color={fgColor} />
                <div className="w-px h-8 bg-white/[0.06]" />
                <StatPill label="BTC" value={btcPrice} sub={btcSub} color="text-amber-400" />
                <div className="w-px h-8 bg-white/[0.06]" />
                <StatPill label="KR" value={gateScore} sub={gateLabel} color={gateColor} />
            </div>

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
                    metricLabel="Gate Score"
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
                    metricLabel="Top Pick"
                />
            </div>

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
                            <h3 className="text-base font-bold text-white">VCP Enhanced</h3>
                            <p className="text-[10px] text-gray-500">Volume Contraction Pattern · All Markets</p>
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

            {/* ── Bottom utility ── */}
            <div className="flex items-center justify-between pt-1">
                <div className="flex items-center gap-3">
                    <Link to="/dashboard/data-status" className="flex items-center gap-1.5 text-[11px] text-gray-600 hover:text-gray-400 transition-colors">
                        <i className="fas fa-database text-[9px]" /> Data Status
                    </Link>
                </div>
                <span className="text-[10px] text-gray-700 font-mono">v2.7.0</span>
            </div>
        </div>
    );
}
