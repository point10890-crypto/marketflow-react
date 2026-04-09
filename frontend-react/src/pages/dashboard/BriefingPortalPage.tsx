import { useEffect, useState, useCallback, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { usAPI, krAPI, cryptoAPI, briefingAPI, type BriefingData, type BriefingMarketData, type DecisionSignalData, type AIBriefing } from '@/lib/api';
import { usePullToRefreshRegister } from '@/components/layout/PullToRefreshProvider';

// ── Helper ──────────────────────────────────────────────────────────────────

function fmt(n: number | undefined | null, dec = 2): string {
    if (n == null || isNaN(n)) return '—';
    return Number(n).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

function fmtK(n: number | undefined | null): string {
    if (n == null || isNaN(n)) return '—';
    const v = Number(n);
    if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
    if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
    return `$${v.toFixed(2)}`;
}

function chgColor(v: number | undefined | null): string {
    if (v == null) return 'text-gray-500';
    return v > 0 ? 'text-emerald-400' : v < 0 ? 'text-red-400' : 'text-gray-400';
}

function chgStr(v: number | undefined | null, suffix = '%'): string {
    if (v == null || isNaN(v!)) return '—';
    return `${v > 0 ? '+' : ''}${Number(v).toFixed(2)}${suffix}`;
}

// ── Ticker Strip ────────────────────────────────────────────────────────────

function TickerStrip({ items }: { items: { label: string; price: string; change: number | null }[] }) {
    return (
        <div className="flex items-center gap-4 overflow-x-auto scrollbar-none py-2 px-1 -mx-1">
            {items.map(t => (
                <div key={t.label} className="flex items-center gap-2 shrink-0">
                    <span className="text-[10px] font-bold text-gray-400">{t.label}</span>
                    <span className="text-[11px] font-bold text-white tabular-nums">{t.price}</span>
                    <span className={`text-[10px] font-semibold tabular-nums ${chgColor(t.change)}`}>
                        {chgStr(t.change)}
                    </span>
                </div>
            ))}
        </div>
    );
}

// ── Index Card ──────────────────────────────────────────────────────────────

function IndexCard({ name, ticker, data }: { name: string; ticker: string; data?: BriefingMarketData }) {
    if (!data) return null;
    const pct = data.change ?? 0;
    const color = pct >= 0 ? '#10b981' : '#ef4444';
    const barW = Math.min(Math.abs(pct) * 10, 100);
    return (
        <div className="flex flex-col gap-1.5 rounded-xl border border-white/[0.07] bg-[#13151f] p-3">
            <div className="flex items-center justify-between">
                <span className="text-[10px] font-semibold text-gray-500">{ticker}</span>
                {data.pct_from_high != null && (
                    <span className="text-[9px] text-gray-600">ATH {data.pct_from_high > 0 ? '+' : ''}{data.pct_from_high.toFixed(1)}%</span>
                )}
            </div>
            <span className="text-lg font-extrabold text-white tabular-nums leading-tight">{fmt(data.price)}</span>
            <div className="flex items-center gap-2">
                <div className="flex-1 h-1 rounded-full bg-white/[0.06] overflow-hidden">
                    <div className="h-full rounded-full transition-all" style={{ width: `${barW}%`, background: color }} />
                </div>
                <span className={`text-xs font-bold tabular-nums ${chgColor(pct)}`}>{chgStr(pct)}</span>
            </div>
            <span className="text-[10px] text-gray-500 font-medium">{name}</span>
        </div>
    );
}

// ── Indicator Tile ──────────────────────────────────────────────────────────

function IndicatorTile({ label, value, change, icon, color }: {
    label: string; value: string; change?: number | null; icon: string; color: string;
}) {
    return (
        <div className="flex flex-col items-center gap-1 rounded-xl border border-white/[0.07] bg-[#13151f] p-3 min-w-0">
            <i className={`fas ${icon} text-xs ${color}`} />
            <span className="text-[9px] font-semibold text-gray-500 uppercase tracking-wider">{label}</span>
            <span className="text-sm font-bold text-white tabular-nums">{value}</span>
            {change != null && (
                <span className={`text-[9px] font-semibold tabular-nums ${chgColor(change)}`}>{chgStr(change)}</span>
            )}
        </div>
    );
}

// ── Portal Link Card ────────────────────────────────────────────────────────

function PortalLink({ to, icon, label, desc, accent }: {
    to: string; icon: string; label: string; desc: string; accent: string;
}) {
    return (
        <Link to={to}
            className="group flex items-center gap-3 rounded-xl border border-white/[0.07] bg-[#13151f] p-3 hover:border-white/15 hover:bg-white/[0.03] transition-all active:scale-[0.98]"
        >
            <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                style={{ background: `${accent}15`, border: `1px solid ${accent}25` }}>
                <i className={`fas ${icon} text-sm`} style={{ color: accent }} />
            </div>
            <div className="flex flex-col min-w-0">
                <span className="text-xs font-bold text-white">{label}</span>
                <span className="text-[10px] text-gray-500 truncate">{desc}</span>
            </div>
            <i className="fas fa-chevron-right text-[9px] text-gray-700 ml-auto opacity-0 group-hover:opacity-100 transition-opacity" />
        </Link>
    );
}

// ── Smart Money Row ─────────────────────────────────────────────────────────

function SmartMoneyRow({ rank, ticker, name, score, recommendation, upside }: {
    rank: number; ticker: string; name: string; score: number; recommendation: string; upside: number;
}) {
    const recColor = recommendation?.includes('적극') || recommendation?.includes('Strong')
        ? 'text-emerald-400 bg-emerald-400/10'
        : recommendation?.includes('매수') || recommendation?.includes('Buy')
            ? 'text-blue-400 bg-blue-400/10'
            : 'text-gray-400 bg-gray-400/10';
    return (
        <div className="flex items-center gap-3 py-2.5 border-b border-white/[0.04] last:border-b-0">
            <span className="w-6 h-6 rounded-lg bg-amber-500/15 text-amber-400 text-[10px] font-black flex items-center justify-center shrink-0">
                {rank}
            </span>
            <div className="flex flex-col min-w-0 flex-1">
                <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-white">{ticker}</span>
                    <span className="text-[10px] text-gray-500 truncate">{name}</span>
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                    <div className="h-1 flex-1 max-w-[80px] rounded-full bg-white/[0.06] overflow-hidden">
                        <div className="h-full rounded-full bg-amber-400" style={{ width: `${Math.min(score, 100)}%` }} />
                    </div>
                    <span className="text-[9px] text-gray-500 tabular-nums">{score.toFixed(0)}</span>
                </div>
            </div>
            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full shrink-0 ${recColor}`}>
                {recommendation}
            </span>
            <span className={`text-xs font-bold tabular-nums shrink-0 ${upside > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {upside > 0 ? '+' : ''}{upside.toFixed(1)}%
            </span>
        </div>
    );
}

// ── Decision Signal Badge ───────────────────────────────────────────────────

function SignalPanel({ signal }: { signal: DecisionSignalData | null }) {
    if (!signal) return null;
    const actionColors: Record<string, string> = {
        STRONG_BUY: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
        BUY: 'bg-green-500/20 text-green-400 border-green-500/30',
        NEUTRAL: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
        CAUTIOUS: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
        DEFENSIVE: 'bg-red-500/20 text-red-400 border-red-500/30',
    };
    const style = actionColors[signal.action] ?? actionColors.NEUTRAL;
    const components = signal.components;
    return (
        <div className="rounded-xl border border-white/[0.07] bg-[#13151f] p-4">
            <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-bold text-white">Decision Signal</span>
                <span className={`text-[10px] font-black px-2 py-1 rounded-lg border ${style}`}>{signal.action}</span>
            </div>
            {/* Score bar */}
            <div className="flex items-center gap-3 mb-3">
                <div className="flex-1 h-2 rounded-full bg-white/[0.06] overflow-hidden">
                    <div className="h-full rounded-full transition-all"
                        style={{
                            width: `${signal.score}%`,
                            background: signal.score >= 60 ? '#10b981' : signal.score >= 40 ? '#f59e0b' : '#ef4444'
                        }}
                    />
                </div>
                <span className="text-sm font-extrabold text-white tabular-nums">{signal.score}</span>
            </div>
            {/* Components */}
            {components && (
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                    {Object.entries(components).map(([key, comp]) => (
                        <div key={key} className="flex flex-col items-center gap-0.5 px-2 py-1.5 rounded-lg bg-white/[0.03]">
                            <span className="text-[8px] font-semibold text-gray-600 uppercase">{key.replace('_', ' ')}</span>
                            <span className={`text-[10px] font-bold tabular-nums ${(comp as any).contribution > 0 ? 'text-emerald-400' : (comp as any).contribution < 0 ? 'text-red-400' : 'text-gray-400'}`}>
                                {(comp as any).contribution > 0 ? '+' : ''}{(comp as any).contribution}
                            </span>
                        </div>
                    ))}
                </div>
            )}
            {signal.timing && (
                <div className="mt-2 text-[10px] text-gray-500">
                    <i className="fas fa-clock mr-1" />Timing: <span className="text-gray-300 font-semibold">{signal.timing}</span>
                </div>
            )}
        </div>
    );
}

// ── Briefing Tab Bar ────────────────────────────────────────────────────────

type BriefingTab = 'portal' | 'morning' | 'closing';

function BriefingTabBar({ active, onChange, morningAvail, closingAvail }: {
    active: BriefingTab; onChange: (t: BriefingTab) => void;
    morningAvail: boolean; closingAvail: boolean;
}) {
    const tabs: { key: BriefingTab; label: string; icon: string; avail?: boolean }[] = [
        { key: 'portal', label: 'Portal', icon: 'fa-th-large' },
        { key: 'morning', label: '조간', icon: 'fa-sun', avail: morningAvail },
        { key: 'closing', label: '마감', icon: 'fa-moon', avail: closingAvail },
    ];
    return (
        <div className="flex items-center gap-1 p-1 rounded-xl bg-white/[0.04] border border-white/[0.07]">
            {tabs.map(t => (
                <button
                    key={t.key}
                    onClick={() => onChange(t.key)}
                    className={`flex-1 flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg text-[11px] font-bold transition-all ${
                        active === t.key
                            ? 'bg-amber-500/20 text-amber-400 shadow-sm'
                            : 'text-gray-500 hover:text-gray-300 hover:bg-white/[0.04]'
                    }`}
                >
                    <i className={`fas ${t.icon} text-[10px]`} />
                    {t.label}
                    {t.avail === false && t.key !== 'portal' && (
                        <span className="w-1.5 h-1.5 rounded-full bg-gray-600 shrink-0" />
                    )}
                    {t.avail === true && (
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0 animate-pulse" />
                    )}
                </button>
            ))}
        </div>
    );
}

// ── Simple Markdown Renderer ────────────────────────────────────────────────

// Parse inline **bold** and `code` into React nodes.
// Returns plain text + <strong>/<code> elements — no HTML strings, no XSS.
function inlineFmt(text: string): ReactNode[] {
    const parts: ReactNode[] = [];
    const pattern = /\*\*(.+?)\*\*|`(.+?)`/g;
    let lastIndex = 0;
    let key = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
        if (match.index > lastIndex) {
            parts.push(text.slice(lastIndex, match.index));
        }
        if (match[1] !== undefined) {
            parts.push(
                <strong key={key++} className="text-white font-bold">{match[1]}</strong>
            );
        } else if (match[2] !== undefined) {
            parts.push(
                <code key={key++} className="text-amber-300 bg-white/5 px-1 rounded text-[10px]">{match[2]}</code>
            );
        }
        lastIndex = match.index + match[0].length;
    }
    if (lastIndex < text.length) {
        parts.push(text.slice(lastIndex));
    }
    return parts;
}

function RenderMarkdown({ content }: { content: string }) {
    const lines = content.split('\n');
    const elements: JSX.Element[] = [];
    let listItems: string[] = [];

    const flushList = () => {
        if (listItems.length > 0) {
            elements.push(
                <ul key={`list-${elements.length}`} className="space-y-1 my-2">
                    {listItems.map((item, i) => (
                        <li key={`li-${i}-${item.slice(0, 16)}`} className="flex items-start gap-2 text-[11px] text-gray-300 leading-relaxed">
                            <span className="text-amber-400 mt-0.5 shrink-0">•</span>
                            <span>{inlineFmt(item)}</span>
                        </li>
                    ))}
                </ul>
            );
            listItems = [];
        }
    };

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) {
            flushList();
            continue;
        }
        if (line.startsWith('- ') || line.startsWith('* ')) {
            listItems.push(line.slice(2));
            continue;
        }
        if (line.startsWith('|') && line.endsWith('|')) {
            flushList();
            // Table: collect all consecutive | lines
            const tableLines: string[] = [line];
            while (i + 1 < lines.length && lines[i + 1].trim().startsWith('|')) {
                i++;
                tableLines.push(lines[i].trim());
            }
            const rows = tableLines
                .filter(l => !l.match(/^\|[\s-:|]+\|$/))  // skip separator
                .map(l => l.split('|').filter(c => c.trim()).map(c => c.trim()));
            if (rows.length > 0) {
                const [header, ...body] = rows;
                elements.push(
                    <div key={`table-${elements.length}`} className="overflow-x-auto my-2">
                        <table className="w-full text-[10px]">
                            <thead>
                                <tr>
                                    {header.map((h, j) => (
                                        <th key={`th-${j}-${h}`} className="text-left text-gray-500 font-semibold py-1 px-2 border-b border-white/10">{h}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {body.map((row, ri) => (
                                    <tr key={`tr-${ri}`}>
                                        {row.map((cell, ci) => (
                                            <td key={`td-${ri}-${ci}`} className="text-gray-300 py-1 px-2 border-b border-white/5">
                                                {inlineFmt(cell)}
                                            </td>
                                        ))}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                );
            }
            continue;
        }
        flushList();
        elements.push(
            <p key={`p-${elements.length}`} className="text-[11px] text-gray-300 leading-relaxed my-1">
                {inlineFmt(line)}
            </p>
        );
    }
    flushList();
    return <>{elements}</>;
}

// ── AI Briefing View ────────────────────────────────────────────────────────

function BriefingView({ briefing }: { briefing: AIBriefing }) {
    const sentimentStyle: Record<string, string> = {
        BULLISH: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
        NEUTRAL: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
        BEARISH: 'bg-red-500/20 text-red-400 border-red-500/30',
    };
    const style = sentimentStyle[briefing.market_sentiment] ?? sentimentStyle.NEUTRAL;

    return (
        <div className="flex flex-col gap-3">
            {/* Header */}
            <div className="rounded-xl border border-white/[0.07] bg-[#13151f] p-4">
                <div className="flex items-start justify-between gap-3 mb-3">
                    <h3 className="text-sm font-extrabold text-white leading-snug flex-1">{briefing.title}</h3>
                    <span className={`text-[9px] font-black px-2 py-1 rounded-lg border shrink-0 ${style}`}>
                        {briefing.market_sentiment}
                    </span>
                </div>
                <p className="text-[11px] text-gray-400 leading-relaxed">{briefing.summary}</p>
                {briefing.confidence > 0 && (
                    <div className="flex items-center gap-2 mt-2">
                        <div className="flex-1 h-1 rounded-full bg-white/[0.06] overflow-hidden max-w-[120px]">
                            <div className="h-full rounded-full bg-amber-400" style={{ width: `${briefing.confidence * 100}%` }} />
                        </div>
                        <span className="text-[9px] text-gray-500">confidence {(briefing.confidence * 100).toFixed(0)}%</span>
                    </div>
                )}
            </div>

            {/* Sections */}
            {briefing.sections?.map((section, i) => (
                <div key={i} className="rounded-xl border border-white/[0.07] bg-[#13151f] p-4">
                    <h4 className="text-xs font-bold text-white mb-2">{section.heading}</h4>
                    <RenderMarkdown content={section.content} />
                </div>
            ))}

            {/* Key Events */}
            {briefing.key_events?.length > 0 && (
                <div className="rounded-xl border border-white/[0.07] bg-[#13151f] p-4">
                    <h4 className="text-xs font-bold text-white mb-2">
                        <i className="fas fa-calendar-alt text-amber-400 mr-2" />Key Events
                    </h4>
                    <div className="flex flex-wrap gap-1.5">
                        {briefing.key_events.map((ev, i) => (
                            <span key={i} className="text-[10px] text-gray-300 bg-white/[0.05] rounded-lg px-2 py-1 border border-white/[0.07]">
                                {ev}
                            </span>
                        ))}
                    </div>
                </div>
            )}

            {/* Sources + Timestamp */}
            <div className="flex items-center justify-between text-[9px] text-gray-600 px-1">
                <div className="flex items-center gap-1">
                    <i className="fas fa-robot" />
                    <span>Gemini 2.5 Flash + Google Search</span>
                </div>
                <span>
                    {briefing.generated_at ? new Date(briefing.generated_at).toLocaleString('ko-KR', {
                        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                    }) : ''}
                </span>
            </div>
        </div>
    );
}

// ── Main Page ───────────────────────────────────────────────────────────────

export default function BriefingPortalPage() {
    const [searchParams, setSearchParams] = useSearchParams();
    const initialTab = (searchParams.get('tab') as BriefingTab) || 'portal';

    const [briefing, setBriefing] = useState<BriefingData | null>(null);
    const [krGate, setKrGate] = useState<any>(null);
    const [cryptoDom, setCryptoDom] = useState<any>(null);
    const [decision, setDecision] = useState<DecisionSignalData | null>(null);
    const [loading, setLoading] = useState(true);

    const [activeTab, setActiveTab] = useState<BriefingTab>(initialTab);
    const [morningBriefing, setMorningBriefing] = useState<AIBriefing | null>(null);
    const [closingBriefing, setClosingBriefing] = useState<AIBriefing | null>(null);
    const [briefingLoading, setBriefingLoading] = useState(false);

    const loadData = useCallback(async () => {
        try {
            const [b, kg, cd, ds] = await Promise.all([
                usAPI.getMarketBriefing().catch(() => null),
                krAPI.getMarketGate().catch(() => null),
                cryptoAPI.getDominance().catch(() => null),
                usAPI.getDecisionSignal().catch(() => null),
            ]);
            if (b) setBriefing(b);
            if (kg) setKrGate(kg);
            if (cd) setCryptoDom(cd);
            if (ds) setDecision(ds);
        } finally {
            setLoading(false);
        }
    }, []);

    // Load AI briefings when tab changes
    useEffect(() => {
        if (activeTab === 'morning' && !morningBriefing) {
            setBriefingLoading(true);
            briefingAPI.getMorning().then(d => setMorningBriefing(d)).catch(() => {}).finally(() => setBriefingLoading(false));
        }
        if (activeTab === 'closing' && !closingBriefing) {
            setBriefingLoading(true);
            briefingAPI.getClosing().then(d => setClosingBriefing(d)).catch(() => {}).finally(() => setBriefingLoading(false));
        }
    }, [activeTab, morningBriefing, closingBriefing]);

    // Also load availability on mount
    useEffect(() => {
        briefingAPI.getMorning().then(d => setMorningBriefing(d)).catch(() => {});
        briefingAPI.getClosing().then(d => setClosingBriefing(d)).catch(() => {});
    }, []);

    const handleTabChange = (tab: BriefingTab) => {
        setActiveTab(tab);
        if (tab === 'portal') {
            searchParams.delete('tab');
        } else {
            searchParams.set('tab', tab);
        }
        setSearchParams(searchParams, { replace: true });
    };

    useEffect(() => { loadData(); }, [loadData]);
    usePullToRefreshRegister(loadData);

    if (loading) {
        return (
            <div className="flex items-center justify-center h-full min-h-[400px]">
                <div className="flex flex-col items-center gap-3">
                    <div className="w-8 h-8 border-2 border-amber-500 border-t-transparent rounded-full animate-spin" />
                    <span className="text-white/50 text-sm">Loading Market Data...</span>
                </div>
            </div>
        );
    }

    // ── Derived data ────────────────────────────────────────────────────────

    const md = briefing?.market_data;
    const indices = md?.indices ?? {};
    const futures = md?.futures ?? {};
    const bonds = md?.bonds ?? {};
    const currencies = md?.currencies ?? {};
    const commodities = md?.commodities ?? {};
    const korIndices = md?.korean_indices ?? {};

    // Ticker strip items
    const tickerItems = [
        { label: 'S&P 500', price: fmt(indices['SPY']?.price), change: indices['SPY']?.change ?? null },
        { label: 'NASDAQ', price: fmt(indices['QQQ']?.price), change: indices['QQQ']?.change ?? null },
        { label: 'DOW', price: fmt(indices['DIA']?.price), change: indices['DIA']?.change ?? null },
        { label: 'KOSPI', price: fmt(korIndices['^KS11']?.price), change: korIndices['^KS11']?.change ?? null },
        { label: 'KOSDAQ', price: fmt(korIndices['^KQ11']?.price), change: korIndices['^KQ11']?.change ?? null },
        { label: 'BTC', price: fmtK(cryptoDom?.btc_price), change: cryptoDom?.btc_30d_change ?? null },
    ];

    // VIX
    const vix = briefing?.vix;
    const vixColor = vix?.value != null ? (vix.value > 25 ? 'text-red-400' : vix.value > 18 ? 'text-yellow-400' : 'text-emerald-400') : 'text-gray-400';

    // Fear & Greed
    const fg = briefing?.fear_greed;
    const fgColor = fg?.score != null ? (fg.score >= 60 ? '#10b981' : fg.score <= 40 ? '#ef4444' : '#f59e0b') : '#666';

    // Opportunity Score
    const krScore = krGate?.score ?? 0;
    const vixNum = vix?.value != null ? Number(vix.value) : 20;
    const fgNum = fg?.score ?? 50;
    const usScore = Math.max(0, Math.min(100, (100 - vixNum * 2.5) * 0.6 + fgNum * 0.4));
    const btcRsi = cryptoDom?.btc_rsi != null ? Number(cryptoDom.btc_rsi) : 50;
    const cryptoScore = Math.max(0, Math.min(100, btcRsi > 70 ? 40 : btcRsi < 30 ? 35 : btcRsi));
    const opScore = krScore * 0.40 + usScore * 0.35 + cryptoScore * 0.15 + 40 * 0.10;
    const opColor = opScore >= 70 ? '#10b981' : opScore >= 45 ? '#f59e0b' : '#ef4444';
    const opLabel = opScore >= 70 ? 'BULLISH' : opScore >= 45 ? 'NEUTRAL' : 'BEARISH';

    // Smart Money picks
    const picks = briefing?.smart_money?.top_picks?.picks ?? [];

    // Arc values
    const arc = Math.min(opScore / 100, 1);
    const r = 40, cx = 48, cy = 48, stroke = 7;
    const circumference = 2 * Math.PI * r;

    // Fear & Greed arc
    const fgArc = Math.min((fg?.score ?? 0) / 100, 1);

    return (
        <div className="flex flex-col gap-3 md:gap-4 pb-4">

            {/* ── Page Header ── */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-xl md:text-2xl font-extrabold tracking-tight text-white">
                        Market{' '}
                        <span className="text-transparent bg-clip-text" style={{ backgroundImage: 'linear-gradient(135deg, #f59e0b 0%, #fbbf24 40%, #f97316 100%)' }}>
                            Briefing
                        </span>
                    </h2>
                    <p className="text-[10px] text-gray-500 mt-0.5">Yahoo Finance-Style Market Portal</p>
                </div>
                <span className="text-[10px] text-gray-600">
                    {briefing?.timestamp ? new Date(briefing.timestamp).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''}
                </span>
            </div>

            {/* ── Tab Bar ── */}
            <BriefingTabBar
                active={activeTab}
                onChange={handleTabChange}
                morningAvail={!!morningBriefing}
                closingAvail={!!closingBriefing}
            />

            {/* ── AI Briefing Tab Content ── */}
            {activeTab === 'morning' && (
                briefingLoading ? (
                    <div className="flex items-center justify-center py-16">
                        <div className="flex flex-col items-center gap-3">
                            <div className="w-6 h-6 border-2 border-amber-500 border-t-transparent rounded-full animate-spin" />
                            <span className="text-xs text-gray-500">Loading briefing...</span>
                        </div>
                    </div>
                ) : morningBriefing ? (
                    <BriefingView briefing={morningBriefing} />
                ) : (
                    <div className="flex flex-col items-center justify-center py-16 gap-2">
                        <i className="fas fa-sun text-2xl text-gray-700" />
                        <span className="text-xs text-gray-500">조간 브리핑이 아직 생성되지 않았습니다</span>
                        <span className="text-[10px] text-gray-600">매일 09:05 KST에 자동 생성됩니다</span>
                    </div>
                )
            )}

            {activeTab === 'closing' && (
                briefingLoading ? (
                    <div className="flex items-center justify-center py-16">
                        <div className="flex flex-col items-center gap-3">
                            <div className="w-6 h-6 border-2 border-amber-500 border-t-transparent rounded-full animate-spin" />
                            <span className="text-xs text-gray-500">Loading briefing...</span>
                        </div>
                    </div>
                ) : closingBriefing ? (
                    <BriefingView briefing={closingBriefing} />
                ) : (
                    <div className="flex flex-col items-center justify-center py-16 gap-2">
                        <i className="fas fa-moon text-2xl text-gray-700" />
                        <span className="text-xs text-gray-500">마감 브리핑이 아직 생성되지 않았습니다</span>
                        <span className="text-[10px] text-gray-600">매일 16:05 KST에 자동 생성됩니다</span>
                    </div>
                )
            )}

            {/* ── Portal Tab Content ── */}
            {activeTab === 'portal' && (<>

            {/* ── 1. Ticker Strip ── */}
            <div className="rounded-xl border border-white/[0.07] bg-[#13151f] px-3">
                <TickerStrip items={tickerItems} />
            </div>

            {/* ── 2. Hero: Opportunity + VIX + F&G ── */}
            <div className="grid grid-cols-3 gap-3">
                {/* Opportunity Score */}
                <div className="flex flex-col items-center gap-1 rounded-xl border border-white/[0.07] bg-[#13151f] p-4">
                    <span className="text-[9px] font-semibold text-gray-500 uppercase tracking-widest">Opportunity</span>
                    <div className="relative" style={{ width: 96, height: 96 }}>
                        <svg width={96} height={96} viewBox="0 0 96 96">
                            <circle cx={cx} cy={cy} r={r} fill="none" stroke="#1e2130" strokeWidth={stroke} />
                            <circle cx={cx} cy={cy} r={r} fill="none" stroke={opColor} strokeWidth={stroke}
                                strokeDasharray={`${arc * circumference} ${circumference}`}
                                strokeLinecap="round"
                                transform={`rotate(-90 ${cx} ${cy})`}
                                style={{ transition: 'stroke-dasharray 0.6s ease' }}
                            />
                        </svg>
                        <div className="absolute inset-0 flex flex-col items-center justify-center">
                            <span className="text-2xl font-extrabold tabular-nums leading-none" style={{ color: opColor }}>{Math.round(opScore)}</span>
                            <span className="text-[8px] text-gray-600 font-semibold">/100</span>
                        </div>
                    </div>
                    <span className="text-[9px] font-black px-2 py-0.5 rounded-full" style={{ background: `${opColor}20`, color: opColor }}>{opLabel}</span>
                </div>

                {/* VIX */}
                <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-white/[0.07] bg-[#13151f] p-4">
                    <span className="text-[9px] font-semibold text-gray-500 uppercase tracking-widest">VIX</span>
                    <span className={`text-3xl font-extrabold tabular-nums ${vixColor}`}>{vix?.value != null ? Number(vix.value).toFixed(1) : '—'}</span>
                    <span className={`text-[10px] font-semibold tabular-nums ${chgColor(vix?.change)}`}>
                        {chgStr(vix?.change, '')}
                    </span>
                    <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full ${
                        vix?.level === 'Fear' ? 'bg-red-400/15 text-red-400'
                            : vix?.level === 'Greed' ? 'bg-emerald-400/15 text-emerald-400'
                                : 'bg-yellow-400/15 text-yellow-400'
                    }`}>{vix?.level ?? '—'}</span>
                </div>

                {/* Fear & Greed */}
                <div className="flex flex-col items-center gap-1 rounded-xl border border-white/[0.07] bg-[#13151f] p-4">
                    <span className="text-[9px] font-semibold text-gray-500 uppercase tracking-widest">Fear & Greed</span>
                    <div className="relative" style={{ width: 96, height: 96 }}>
                        <svg width={96} height={96} viewBox="0 0 96 96">
                            <circle cx={cx} cy={cy} r={r} fill="none" stroke="#1e2130" strokeWidth={stroke} />
                            <circle cx={cx} cy={cy} r={r} fill="none" stroke={fgColor} strokeWidth={stroke}
                                strokeDasharray={`${fgArc * circumference} ${circumference}`}
                                strokeLinecap="round"
                                transform={`rotate(-90 ${cx} ${cy})`}
                                style={{ transition: 'stroke-dasharray 0.6s ease' }}
                            />
                        </svg>
                        <div className="absolute inset-0 flex flex-col items-center justify-center">
                            <span className="text-2xl font-extrabold tabular-nums leading-none" style={{ color: fgColor }}>{fg?.score ?? '—'}</span>
                            <span className="text-[8px] text-gray-600 font-semibold">/100</span>
                        </div>
                    </div>
                    <span className="text-[9px] font-black px-2 py-0.5 rounded-full" style={{ background: `${fgColor}20`, color: fgColor }}>{fg?.level ?? '—'}</span>
                </div>
            </div>

            {/* ── 3. Indices Grid ── */}
            <div>
                <h3 className="text-sm font-bold text-white mb-2">
                    <i className="fas fa-chart-bar text-amber-400 mr-2" />Market Indices
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                    <IndexCard name="S&P 500" ticker="SPY" data={indices['SPY']} />
                    <IndexCard name="NASDAQ 100" ticker="QQQ" data={indices['QQQ']} />
                    <IndexCard name="Dow Jones" ticker="DIA" data={indices['DIA']} />
                    <IndexCard name="Russell 2000" ticker="IWM" data={indices['IWM']} />
                    <IndexCard name="KOSPI" ticker="^KS11" data={korIndices['^KS11']} />
                    <IndexCard name="KOSDAQ" ticker="^KQ11" data={korIndices['^KQ11']} />
                </div>
            </div>

            {/* ── 4. Quick Navigation Portal ── */}
            <div>
                <h3 className="text-sm font-bold text-white mb-2">
                    <i className="fas fa-th-large text-blue-400 mr-2" />Quick Access
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                    <PortalLink to="/dashboard/us" icon="fa-globe-americas" label="US Market" desc="포트폴리오 · 섹터" accent="#10b981" />
                    <PortalLink to="/dashboard/kr" icon="fa-chart-line" label="KR Market" desc="시장 게이트 · 수급" accent="#3b82f6" />
                    <PortalLink to="/dashboard/crypto" icon="fa-bitcoin-sign" label="Crypto" desc="BTC · 리스크" accent="#f59e0b" />
                    <PortalLink to="/dashboard/vcp-enhanced" icon="fa-bolt" label="VCP Enhanced" desc="변동성 축소 패턴" accent="#06b6d4" />
                    <PortalLink to="/dashboard/wave" icon="fa-wave-square" label="W Pattern" desc="AI 차트 패턴" accent="#ec4899" />
                    <PortalLink to="/dashboard/kr/closing-bet" icon="fa-chart-bar" label="종가베팅" desc="모멘텀 스크리너" accent="#8b5cf6" />
                    <PortalLink to="/dashboard/us/etf" icon="fa-exchange-alt" label="ETF Flows" desc="자금 흐름 추적" accent="#14b8a6" />
                    <PortalLink to="/dashboard/stock-analyzer" icon="fa-crosshairs" label="ProPicks" desc="Investing.com 분석" accent="#a855f7" />
                </div>
            </div>

            {/* ── 5. Key Indicators ── */}
            <div>
                <h3 className="text-sm font-bold text-white mb-2">
                    <i className="fas fa-tachometer-alt text-cyan-400 mr-2" />Key Indicators
                </h3>
                <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
                    <IndicatorTile label="VIX" value={vix?.value != null ? Number(vix.value).toFixed(1) : '—'} change={vix?.change} icon="fa-bolt" color={vixColor} />
                    <IndicatorTile label="10Y Yield" value={fmt(bonds['^TNX']?.price)} change={bonds['^TNX']?.change} icon="fa-landmark" color="text-blue-400" />
                    <IndicatorTile label="Gold" value={fmtK(commodities['GC=F']?.price)} change={commodities['GC=F']?.change} icon="fa-coins" color="text-yellow-400" />
                    <IndicatorTile label="Oil" value={fmtK(commodities['CL=F']?.price)} change={commodities['CL=F']?.change} icon="fa-gas-pump" color="text-orange-400" />
                    <IndicatorTile label="USD/KRW" value={fmt(currencies['USDKRW=X']?.price, 0)} change={currencies['USDKRW=X']?.change} icon="fa-won-sign" color="text-green-400" />
                    <IndicatorTile label="BTC" value={fmtK(cryptoDom?.btc_price)} change={cryptoDom?.btc_30d_change} icon="fa-bitcoin-sign" color="text-amber-400" />
                </div>
            </div>

            {/* ── 6. Futures ── */}
            {Object.keys(futures).length > 0 && (
                <div>
                    <h3 className="text-sm font-bold text-white mb-2">
                        <i className="fas fa-clock text-purple-400 mr-2" />Futures
                    </h3>
                    <div className="grid grid-cols-3 gap-2">
                        {Object.entries(futures).slice(0, 3).map(([key, data]) => (
                            <div key={key} className="flex flex-col items-center gap-1 rounded-xl border border-white/[0.07] bg-[#13151f] p-3">
                                <span className="text-[10px] font-semibold text-gray-500">{data.name || key}</span>
                                <span className="text-sm font-bold text-white tabular-nums">{fmt(data.price)}</span>
                                <span className={`text-[10px] font-semibold tabular-nums ${chgColor(data.change)}`}>{chgStr(data.change)}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* ── 7. Smart Money Picks ── */}
            {picks.length > 0 && (
                <div className="rounded-xl border border-white/[0.07] bg-[#13151f] p-4">
                    <div className="flex items-center justify-between mb-3">
                        <h3 className="text-sm font-bold text-white">
                            <i className="fas fa-trophy text-amber-400 mr-2" />Smart Money Top Picks
                        </h3>
                        <Link to="/dashboard/us" className="text-[10px] text-amber-400 hover:text-amber-300 font-semibold">
                            View All <i className="fas fa-chevron-right text-[8px] ml-0.5" />
                        </Link>
                    </div>
                    {picks.map((p, i) => (
                        <SmartMoneyRow
                            key={p.ticker}
                            rank={p.rank ?? i + 1}
                            ticker={p.ticker}
                            name={p.name}
                            score={p.final_score}
                            recommendation={p.ai_recommendation}
                            upside={p.target_upside}
                        />
                    ))}
                </div>
            )}

            {/* ── 8. Decision Signal ── */}
            <SignalPanel signal={decision} />

            </>)}

            {/* ── 9. Footer ── */}
            <div className="text-center py-2">
                <span className="text-[9px] text-gray-700">Data refreshed every 30 seconds · Powered by MarketFlow AI</span>
            </div>
        </div>
    );
}
