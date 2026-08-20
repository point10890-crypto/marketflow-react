import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
    mirofishApi,
    type MiroFishAlphaDashboardStatus,
    type MiroFishAlphaMetric,
    type MiroFishAlphaService,
    type MiroFishAlphaServiceDashboardResponse,
    type MiroFishAlphaWarning,
} from '@/lib/mirofishApi';

const DATA_STATUS_LABEL: Record<MiroFishAlphaDashboardStatus, string> = {
    ready: '준비됨', stale: '오래됨', partial: '일부만', empty: '데이터 없음',
};

const DATA_STATUS_ICON: Record<MiroFishAlphaDashboardStatus, string> = {
    ready: '✓', stale: '◷', partial: '!', empty: '–',
};

const SCHEDULE_LABEL = { upcoming: '예정', due: '현재 구간', elapsed: '경과' } as const;
const SCHEDULE_ICON = { upcoming: '○', due: '●', elapsed: '✓' } as const;

const DATA_STATUS_CLASS: Record<MiroFishAlphaDashboardStatus, string> = {
    ready: 'border-[#6EE7B7]/25 bg-[#6EE7B7]/10 text-[#6EE7B7]',
    stale: 'border-[#FCD34D]/25 bg-[#FCD34D]/10 text-[#FCD34D]',
    partial: 'border-[#FCD34D]/25 bg-[#FCD34D]/10 text-[#FCD34D]',
    empty: 'border-[#FCD34D]/25 bg-[#FCD34D]/10 text-[#FCD34D]',
};

const METRIC_TONE_CLASS: Record<MiroFishAlphaMetric['tone'], string> = {
    positive: 'text-[#6EE7B7]', neutral: 'text-slate-100', warning: 'text-[#FCD34D]', negative: 'text-[#FDA4AF]',
};

function formatNumber(value: number | null, maximumFractionDigits = 2) {
    if (value === null) return '—';
    return new Intl.NumberFormat('ko-KR', { maximumFractionDigits }).format(value);
}

function formatPercent(value: number | null) {
    if (value === null) return '—';
    return `${value > 0 ? '+' : ''}${formatNumber(value)}%`;
}

function formatRate(value: number | null) {
    return value === null ? '—' : `${formatNumber(value)}%`;
}

function formatMetric(metric: MiroFishAlphaMetric) {
    if (metric.value === null) return '—';
    const value = typeof metric.value === 'number' ? formatNumber(metric.value) : metric.value;
    return `${value}${metric.unit ?? ''}`;
}

function compactTimestamp(value: string | null) {
    if (!value) return '기준 시각 없음';
    return value.replace('T', ' ').replace(/([+-]\d{2}:\d{2}|Z)$/, '').slice(0, 16);
}

function sourceLabel(source: string) {
    if (source === 'paper_30d') return '가상매매 30일';
    if (source === 'workflow_outcomes') return 'Forward outcomes';
    return source;
}

function warningKey(warning: MiroFishAlphaWarning) {
    return `${warning.section ?? ''}:${warning.code}:${warning.message}`;
}

function uniqueWarnings(warnings: MiroFishAlphaWarning[]) {
    return Array.from(new Map(warnings.map(warning => [warningKey(warning), warning])).values());
}

function ServiceWarnings({ title, warnings }: { title: string; warnings: MiroFishAlphaWarning[] }) {
    const unique = uniqueWarnings(warnings);
    const errors = unique.filter(warning => warning.severity === 'error');
    const cautions = unique.filter(warning => warning.severity === 'warning');
    const information = unique.filter(warning => warning.severity === 'info');
    if (unique.length === 0) return null;

    return (
        <div className="mt-2 space-y-1.5 text-xs font-bold">
            {errors.length > 0 && (
                <div role="alert" aria-label={`${title} 오류`} className="rounded-lg border border-[#FDA4AF]/20 bg-[#FDA4AF]/8 px-3 py-2 text-[#FDA4AF]">
                    {errors.map(warning => <div key={warningKey(warning)}>! {warning.message}</div>)}
                </div>
            )}
            {cautions.length > 0 && (
                <div role="alert" aria-label={`${title} 경고`} className="rounded-lg border border-[#FCD34D]/20 bg-[#FCD34D]/8 px-3 py-2 text-[#FCD34D]">
                    {cautions.map(warning => <div key={warningKey(warning)}>! {warning.message}</div>)}
                </div>
            )}
            {information.length > 0 && (
                <div role="status" aria-label={`${title} 안내`} className="rounded-lg border border-[#67E8F9]/15 bg-[#67E8F9]/8 px-3 py-2 text-[#67E8F9]">
                    {information.map(warning => <div key={warningKey(warning)}>ⓘ {warning.message}</div>)}
                </div>
            )}
        </div>
    );
}

function ServiceDetails({ service }: { service: MiroFishAlphaService }) {
    switch (service.id) {
        case 'market_brief':
            return (
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                    {service.metrics.slice(0, 3).map(metric => (
                        <div key={metric.key} className="min-w-0 rounded-lg border border-white/8 bg-black/20 px-2.5 py-2">
                            <div className="truncate text-xs font-bold text-slate-500">{metric.label}</div>
                            <div className={`mt-1 font-mono text-sm font-black ${METRIC_TONE_CLASS[metric.tone]}`}>{formatMetric(metric)}</div>
                        </div>
                    ))}
                </div>
            );
        case 'score_leaders':
            return (
                <div className="space-y-1.5">
                    {service.items.slice(0, 5).map((item, index) => (
                        <div key={`${item.rank ?? index}-${item.symbol ?? 'unknown'}`} className="min-w-0 rounded-lg border border-white/8 bg-black/20 px-2.5 py-2">
                            <div className="flex min-w-0 items-start justify-between gap-3">
                                <div className="min-w-0">
                                    <div className="truncate text-xs font-black text-slate-100">{item.rank !== null ? `${item.rank}. ` : ''}{item.name ?? '—'}</div>
                                    <div className="truncate font-mono text-xs text-slate-500">{[item.symbol, item.market].filter(Boolean).join(' · ') || '—'}</div>
                                </div>
                                <div className="shrink-0 text-right font-mono">
                                    <div className="text-sm font-black text-[#67E8F9]">A {formatNumber(item.alpha_score, 1)}</div>
                                    <div className="text-xs text-slate-500">Risk {formatNumber(item.risk_score, 1)}</div>
                                </div>
                            </div>
                            <div className="mt-2 flex min-w-0 flex-wrap gap-1.5 font-mono text-xs text-slate-400">
                                {item.action && <span className="rounded border border-[#6EE7B7]/15 bg-[#6EE7B7]/8 px-1.5 py-0.5 text-[#6EE7B7]">{item.action}</span>}
                                {item.horizon && <span className="rounded border border-white/8 px-1.5 py-0.5">{item.horizon}</span>}
                                {item.price !== null && <span className="rounded border border-white/8 px-1.5 py-0.5">₩{formatNumber(item.price, 0)}</span>}
                            </div>
                        </div>
                    ))}
                </div>
            );
        case 'intraday_flow':
            return (
                <div className="space-y-1.5">
                    {service.items.slice(0, 5).map((item, index) => (
                        <div key={item.symbol ?? index} className="min-w-0 rounded-lg border border-white/8 bg-black/20 px-2.5 py-2">
                            <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-3">
                                <div className="min-w-0">
                                    <div className="truncate text-xs font-black text-slate-100">{item.name ?? '—'}</div>
                                    <div className="truncate font-mono text-xs text-slate-500">{item.symbol ?? '종목 코드 없음'} · 저장 종가 {formatNumber(item.last_close, 0)}</div>
                                </div>
                                <div className="text-right font-mono">
                                    {item.last_close_date && (
                                        <div className={`text-sm font-black ${item.unrealized_pct !== null && item.unrealized_pct < 0 ? 'text-[#FDA4AF]' : 'text-[#6EE7B7]'}`}>
                                            {formatPercent(item.unrealized_pct)}
                                        </div>
                                    )}
                                    <div className="text-xs text-slate-500">{item.last_close_date ?? '기준일 없음'}{item.held_trading_days !== null ? ` · ${formatNumber(item.held_trading_days, 0)}일` : ''}</div>
                                </div>
                            </div>
                            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 font-mono text-xs text-slate-500">
                                {item.target_price !== null && <span>목표 {formatNumber(item.target_price, 0)}</span>}
                                {item.stop_price !== null && <span className="text-[#FDA4AF]">손절 {formatNumber(item.stop_price, 0)}</span>}
                            </div>
                        </div>
                    ))}
                </div>
            );
        case 'trade_signals':
            return (
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                    {service.items.map(item => (
                        <div key={item.key} className="rounded-lg border border-white/8 bg-black/20 px-2.5 py-2">
                            <div className="text-xs font-bold text-slate-500">{item.label}</div>
                            <div className="mt-1 font-mono text-sm font-black text-slate-100">{item.count === null ? '—' : `${item.count}건`}</div>
                            <div className="mt-1 flex flex-wrap gap-1 font-mono text-xs text-slate-600">
                                {item.window_days !== null && <span>{item.window_days}일</span>}
                                {item.status && <span className="text-[#FCD34D]">{item.status}</span>}
                            </div>
                        </div>
                    ))}
                </div>
            );
        case 'performance_brief':
            return (
                <div className="space-y-1.5">
                    {service.items.map(item => {
                        const hasSamples = item.sample_count !== null && item.sample_count > 0;
                        return (
                            <div key={item.source} className="rounded-lg border border-white/8 bg-black/20 px-2.5 py-2">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                    <span className="text-xs font-black uppercase tracking-wider text-slate-400">{sourceLabel(item.source)}</span>
                                    {item.window_days !== null && <span className="font-mono text-xs text-slate-500">{item.window_days}일</span>}
                                    <span className={`font-mono text-xs font-black ${hasSamples ? 'text-[#6EE7B7]' : 'text-[#FCD34D]'}`}>
                                        {hasSamples ? `표본 ${item.sample_count}건` : '표본 없음'}
                                    </span>
                                </div>
                                <div className="mt-2 grid grid-cols-3 gap-2 font-mono text-xs">
                                    <span><span className="block text-xs text-slate-600">승률</span>{hasSamples ? formatRate(item.win_rate) : '—'}</span>
                                    <span><span className="block text-xs text-slate-600">평균</span>{hasSamples ? formatPercent(item.average_return_pct) : '—'}</span>
                                    <span><span className="block text-xs text-slate-600">누적</span>{hasSamples ? formatPercent(item.cumulative_return_pct) : '—'}</span>
                                </div>
                                {(item.hit_count !== null || item.miss_count !== null) && (
                                    <div className="mt-2 font-mono text-xs text-slate-500">Hit {formatNumber(item.hit_count, 0)} · Miss {formatNumber(item.miss_count, 0)}</div>
                                )}
                            </div>
                        );
                    })}
                </div>
            );
    }
}

function ServiceCard({ service }: { service: MiroFishAlphaService }) {
    const isDue = service.schedule.phase === 'due';
    const warnings = [...service.warnings];
    if (service.id === 'intraday_flow' && service.items.some(item => !item.last_close_date)) {
        warnings.push({ section: 'intraday_flow', code: 'last_close_date_missing', message: '저장 가격 기준일을 확인할 수 없습니다.', severity: 'warning' });
    }

    return (
        <article className={`relative min-w-0 rounded-xl border bg-[#151C28] p-3 pl-4 ${isDue ? 'border-[#67E8F9]/25' : 'border-white/8'}`}>
            <span
                aria-hidden="true"
                data-alpha-current-marker={isDue ? '' : undefined}
                className={`absolute -left-[19px] top-4 h-3 w-3 rounded-full border-2 border-[#10151F] ${isDue ? 'bg-[#67E8F9] shadow-[0_0_14px_rgba(103,232,249,0.7)] motion-safe:animate-pulse motion-reduce:animate-none' : service.data_status === 'ready' ? 'bg-[#6EE7B7]' : 'bg-[#FCD34D]'}`}
            />
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                    <div className="font-mono text-xs font-black tracking-wide text-[#67E8F9]">{service.schedule.label}</div>
                    <h3 className="mt-0.5 truncate text-sm font-black text-slate-50">{service.title}</h3>
                </div>
                <div className="flex flex-wrap justify-end gap-1">
                    <span aria-label={`일정 상태: ${SCHEDULE_LABEL[service.schedule.phase]}`} className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-black ${isDue ? 'border-[#67E8F9]/25 bg-[#67E8F9]/10 text-[#67E8F9]' : 'border-white/10 bg-white/5 text-slate-400'}`}>
                        <span aria-hidden="true">{SCHEDULE_ICON[service.schedule.phase]}</span>{SCHEDULE_LABEL[service.schedule.phase]}
                    </span>
                    <span aria-label={`데이터 상태: ${DATA_STATUS_LABEL[service.data_status]}`} className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-black ${DATA_STATUS_CLASS[service.data_status]}`}>
                        <span aria-hidden="true">{DATA_STATUS_ICON[service.data_status]}</span>{DATA_STATUS_LABEL[service.data_status]}
                    </span>
                </div>
            </div>
            <p className="mt-1 text-xs leading-5 text-slate-400">{service.description}</p>
            <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 font-mono text-xs text-slate-600">
                <span>{compactTimestamp(service.as_of)}</span>
                {service.provenance.sources.map((source, index) => (
                    <span key={`${source.source}-${source.run_id ?? index}`} className="inline-flex min-w-0 flex-wrap gap-x-1">
                        <span className={source.fallback || source.freshness !== 'fresh' ? 'text-[#FCD34D]' : 'text-slate-500'}>
                            {source.source} · {source.freshness}{source.fallback ? ' · fallback' : ''}
                        </span>
                        {(source.run_id || source.as_of) && (
                            <span className="break-all text-slate-600">{source.run_id ? `run ${source.run_id}` : 'run 없음'} · {compactTimestamp(source.as_of)}</span>
                        )}
                    </span>
                ))}
            </div>
            <p className="mt-2 text-xs font-bold text-slate-300">{service.summary}</p>
            <div className="mt-2"><ServiceDetails service={service} /></div>
            <ServiceWarnings title={service.title} warnings={warnings} />
        </article>
    );
}

function LoadingSkeleton() {
    return (
        <div aria-label="서비스 현황 로딩 중" className="space-y-2 pl-5">
            {Array.from({ length: 5 }, (_, index) => (
                <div key={index} className="h-28 rounded-xl border border-white/8 bg-[#151C28] animate-pulse motion-reduce:animate-none" />
            ))}
        </div>
    );
}

function RequestFailure({ message, onRetry }: { message: string; onRetry: () => void }) {
    return (
        <div className="rounded-xl border border-[#FDA4AF]/25 bg-[#FDA4AF]/8 p-4">
            <p role="alert" aria-label="서비스 조회 오류" className="text-xs font-bold text-[#FDA4AF]">{message}</p>
            <button
                type="button"
                onClick={onRetry}
                className="mt-3 min-h-11 rounded-lg border border-[#FDA4AF]/30 bg-[#FDA4AF]/10 px-4 text-xs font-black text-[#FDA4AF] outline-none transition hover:bg-[#FDA4AF]/15 focus-visible:ring-2 focus-visible:ring-[#67E8F9] focus-visible:ring-offset-2 focus-visible:ring-offset-[#10151F]"
            >
                다시 불러오기
            </button>
        </div>
    );
}

export default function AlphaServiceDashboard() {
    const [dashboard, setDashboard] = useState<MiroFishAlphaServiceDashboardResponse | null>(null);
    const [error, setError] = useState<string | null>(null);
    const mountedRef = useRef(false);
    const inFlightRef = useRef(false);

    const load = useCallback(async () => {
        if (inFlightRef.current) return;
        inFlightRef.current = true;
        try {
            const next = await mirofishApi.getAlphaServiceDashboard();
            if (mountedRef.current) {
                setDashboard(next);
                setError(null);
            }
        } catch {
            if (mountedRef.current) setError('서비스 현황을 불러오지 못했습니다.');
        } finally {
            inFlightRef.current = false;
        }
    }, []);

    useEffect(() => {
        mountedRef.current = true;
        void load();
        const intervalId = window.setInterval(() => {
            if (document.visibilityState === 'visible') void load();
        }, 60_000);
        const onVisibility = () => {
            if (document.visibilityState === 'visible') void load();
        };
        document.addEventListener('visibilitychange', onVisibility);
        return () => {
            mountedRef.current = false;
            window.clearInterval(intervalId);
            document.removeEventListener('visibilitychange', onVisibility);
        };
    }, [load]);

    const globalWarnings = useMemo(() => {
        if (!dashboard) return [];
        const cardWarningKeys = new Set(dashboard.services.flatMap(service => service.warnings.map(warningKey)));
        return uniqueWarnings(dashboard.warnings.filter(warning => !cardWarningKeys.has(warningKey(warning))));
    }, [dashboard]);

    return (
        <section aria-labelledby="alpha-service-clock-title" className="relative min-w-0 overflow-hidden rounded-2xl border border-[#67E8F9]/15 bg-[#10151F] p-4">
            <header className="mb-4 flex min-w-0 flex-wrap items-start justify-between gap-3 border-b border-white/8 pb-3">
                <div className="min-w-0">
                    <div className="font-mono text-xs font-black uppercase tracking-[0.24em] text-[#67E8F9]/70">Daily Alpha Sequence</div>
                    <h2 id="alpha-service-clock-title" className="mt-1 text-base font-black tracking-tight text-white">Alpha Service Clock</h2>
                    <p className="mt-1 text-xs font-semibold text-slate-500">시장 정리 → 후보 → 장중 관찰 → 신호 → 성과</p>
                </div>
                {dashboard && (
                    <div className="shrink-0 text-right">
                        <div aria-label={`전체 데이터 상태: ${DATA_STATUS_LABEL[dashboard.status]}`} className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-black ${DATA_STATUS_CLASS[dashboard.status]}`}>
                            <span aria-hidden="true">{DATA_STATUS_ICON[dashboard.status]}</span>전체 상태 · {DATA_STATUS_LABEL[dashboard.status]}
                        </div>
                        <div className="mt-1 font-mono text-xs text-slate-600">{compactTimestamp(dashboard.generated_at)} KST</div>
                    </div>
                )}
            </header>

            {!dashboard && !error && <LoadingSkeleton />}
            {!dashboard && error && <RequestFailure message={error} onRetry={() => void load()} />}

            {dashboard && (
                <>
                    {error && <div className="mb-3"><RequestFailure message={error} onRetry={() => void load()} /></div>}
                    <ServiceWarnings title="전체 서비스" warnings={globalWarnings} />
                    <div className="relative space-y-2 pl-5">
                        <div aria-hidden="true" className="absolute bottom-5 left-[6px] top-5 w-px bg-gradient-to-b from-[#67E8F9]/50 via-white/15 to-[#FCD34D]/25" />
                        {dashboard.services.map(service => <ServiceCard key={service.id} service={service} />)}
                    </div>
                </>
            )}
        </section>
    );
}
