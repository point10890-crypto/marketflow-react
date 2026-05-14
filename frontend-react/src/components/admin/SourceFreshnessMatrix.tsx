import { MiroFishWorkflowGraphRAG, MiroFishWorkflowSourceFreshness } from '@/lib/mirofishApi';

interface SourceFreshnessMatrixProps {
    sourceFreshness?: MiroFishWorkflowSourceFreshness;
    graphrag?: MiroFishWorkflowGraphRAG;
    className?: string;
}

type FreshnessTier = 'fresh' | 'partial' | 'stale' | 'unavailable';

const FRESHNESS_LABEL: Record<FreshnessTier, string> = {
    fresh: 'FRESH',
    partial: 'CACHED',
    stale: 'STALE',
    unavailable: 'N/A',
};

const FRESHNESS_TONE: Record<FreshnessTier, string> = {
    fresh: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200',
    partial: 'border-amber-400/30 bg-amber-400/10 text-amber-200',
    stale: 'border-rose-400/25 bg-rose-400/10 text-rose-200',
    unavailable: 'border-neutral-400/20 bg-neutral-400/[0.06] text-neutral-400',
};

function normalizeFreshness(value: string | undefined | null): FreshnessTier {
    const v = String(value || '').toLowerCase().trim();
    if (v === 'fresh' || v === 'live') return 'fresh';
    if (v === 'partial' || v === 'cached') return 'partial';
    if (v === 'stale' || v === 'missing') return 'stale';
    return 'unavailable';
}

function overallStatusTone(status: string): string {
    const v = String(status || '').toLowerCase();
    if (v === 'fresh') return 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200';
    if (v === 'partial') return 'border-amber-400/30 bg-amber-400/10 text-amber-200';
    if (v === 'stale') return 'border-rose-400/25 bg-rose-400/10 text-rose-200';
    return 'border-neutral-400/20 bg-neutral-400/10 text-neutral-300';
}

interface SourceRow {
    id: string;
    label: string;
    tier: FreshnessTier;
}

function buildRows(freshness?: MiroFishWorkflowSourceFreshness, graphrag?: MiroFishWorkflowGraphRAG): SourceRow[] {
    const sources = freshness?.sources || {};
    const coverage = graphrag?.source_coverage || {};
    return [
        { id: 'scanner', label: 'Scanner', tier: normalizeFreshness(sources.scanner_freshness || coverage.scanner) },
        { id: 'kis', label: 'KIS', tier: normalizeFreshness(sources.kis_freshness || coverage.kis) },
        { id: 'tradingview', label: 'TradingView', tier: normalizeFreshness(sources.tradingview_freshness || coverage.tradingview) },
        { id: 'dart', label: 'DART', tier: normalizeFreshness(sources.dart_freshness || coverage.dart) },
        { id: 'news', label: 'News', tier: normalizeFreshness(sources.news_freshness || coverage.news) },
        { id: 'deepseek', label: 'DeepSeek', tier: normalizeFreshness(sources.deepseek_freshness || coverage.deepseek) },
    ];
}

export default function SourceFreshnessMatrix({ sourceFreshness, graphrag, className }: SourceFreshnessMatrixProps) {
    const hasData = Boolean(sourceFreshness || graphrag);
    if (!hasData) return null;

    const rows = buildRows(sourceFreshness, graphrag);
    const status = sourceFreshness?.status || '--';
    const ageHours = sourceFreshness?.data_age_hours;
    const entityCount = graphrag?.entity_count ?? 0;
    const edgeCount = graphrag?.edge_count ?? 0;

    return (
        <section className={`rounded-xl border border-amber-500/15 bg-black/60 p-3 sm:p-4 ${className || ''}`}>
            <header className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                    <div className="flex items-center gap-1.5 text-[10px] font-black uppercase tracking-[0.18em] text-amber-300/70 sm:text-[11px] sm:tracking-[0.22em]">
                        <i className="fas fa-signal text-amber-400" />
                        <span className="truncate">Source Freshness</span>
                    </div>
                    <h3 className="mt-1 text-sm font-black text-white sm:text-base">Evidence coverage matrix</h3>
                </div>
                <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-black tracking-wider ${overallStatusTone(status)}`}>
                    {String(status).toUpperCase()}
                </span>
            </header>

            <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-2 md:grid-cols-3">
                {rows.map((row) => (
                    <div key={row.id} className={`rounded-md border px-2 py-1.5 ${FRESHNESS_TONE[row.tier]}`}>
                        <div className="text-[9px] font-black uppercase tracking-[0.14em] text-current/70">
                            {row.label}
                        </div>
                        <div className="mt-0.5 text-[11px] font-black tracking-wide">
                            {FRESHNESS_LABEL[row.tier]}
                        </div>
                    </div>
                ))}
            </div>

            <div className="mt-3 grid grid-cols-3 gap-2 rounded-lg border border-white/10 bg-black/30 p-2.5 text-[10px] font-bold">
                <div>
                    <div className="text-neutral-500 uppercase tracking-wider">Entities</div>
                    <div className="mt-0.5 text-sm font-black text-white tabular-nums">{entityCount}</div>
                </div>
                <div>
                    <div className="text-neutral-500 uppercase tracking-wider">Edges</div>
                    <div className="mt-0.5 text-sm font-black text-white tabular-nums">{edgeCount}</div>
                </div>
                <div>
                    <div className="text-neutral-500 uppercase tracking-wider">Age</div>
                    <div className="mt-0.5 text-sm font-black text-white tabular-nums">
                        {ageHours === undefined || ageHours === null ? '--' : `${ageHours.toFixed(1)}h`}
                    </div>
                </div>
            </div>
        </section>
    );
}
