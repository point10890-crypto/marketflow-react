import { useEffect, useMemo, useState } from 'react';

import { useAuth } from '@/contexts/AuthContext';
import {
    fetchAlphaCoreSnapshot,
    type AlphaCoreHypothesis,
    type AlphaCoreRiskDecision,
    type AlphaCoreSnapshot,
} from '@/lib/alphaCore';

interface Props {
    loadSnapshot?: (apiToken?: string) => Promise<AlphaCoreSnapshot>;
}

type UnknownRecord = Record<string, unknown>;

const EMPTY: AlphaCoreSnapshot = {
    status: null,
    portfolio: null,
    riskDecisions: null,
    hypotheses: null,
    ledger: null,
    unavailable: ['status', 'portfolio', 'riskDecisions', 'hypotheses', 'ledger'],
};

function record(value: unknown): UnknownRecord | null {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
        ? value as UnknownRecord
        : null;
}

function firstNumber(source: UnknownRecord | null, keys: string[]): number | null {
    for (const key of keys) {
        const value = source?.[key];
        if (typeof value === 'number' && Number.isFinite(value)) return value;
    }
    return null;
}

function firstString(source: UnknownRecord | null, keys: string[]): string | null {
    for (const key of keys) {
        const value = source?.[key];
        if (typeof value === 'string' && value.trim()) return value.trim();
    }
    return null;
}

function numericCount(value: unknown): number | null {
    if (typeof value === 'number' && Number.isFinite(value)) return Math.max(0, value);
    if (typeof value === 'boolean') return value ? 1 : 0;
    return null;
}

function formatMoney(value: number | null): string {
    if (value == null) return '-';
    return new Intl.NumberFormat('ko-KR', {
        style: 'currency',
        currency: 'KRW',
        notation: 'compact',
        maximumFractionDigits: 1,
    }).format(value);
}

function formatPct(value: number | null, signed = false): string {
    if (value == null) return '-';
    return `${signed && value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

function formatTime(value: string | null): string {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value.slice(0, 16).replace('T', ' ');
    return date.toLocaleString('ko-KR', {
        timeZone: 'Asia/Seoul',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    });
}

function reasonList(value: unknown): string[] {
    if (Array.isArray(value)) {
        return value.flatMap(item => {
            if (typeof item === 'string' && item.trim()) return [item.trim()];
            const itemRecord = record(item);
            const text = firstString(itemRecord, ['message', 'reason', 'code']);
            return text ? [text] : [];
        });
    }
    if (typeof value === 'string' && value.trim()) return [value.trim()];
    return [];
}

function riskItems(snapshot: AlphaCoreSnapshot): AlphaCoreRiskDecision[] {
    const raw = snapshot.riskDecisions;
    const items = raw?.items ?? raw?.decisions ?? [];
    return Array.isArray(items) ? items.filter(item => record(item)) : [];
}

function hypothesisItems(snapshot: AlphaCoreSnapshot): AlphaCoreHypothesis[] {
    const raw = snapshot.hypotheses;
    const items = raw?.items ?? raw?.hypotheses ?? [];
    return Array.isArray(items) ? items.filter(item => record(item)) : [];
}

function health(snapshot: AlphaCoreSnapshot): { label: string; cls: string; detail: string } {
    const status = record(snapshot.status);
    const statusText = firstString(status, ['status', 'state']);
    const quality = record(snapshot.status?.quality);
    const qualityText = firstString(quality, ['status', 'state'])
        ?? (typeof snapshot.status?.quality === 'string' ? snapshot.status.quality : null);
    const normalized = qualityText?.toLowerCase();
    if (!snapshot.status) return { label: '연결 확인 필요', cls: 'bg-gray-500/15 text-gray-300', detail: 'status API 응답 없음' };
    if (snapshot.status.available === false || statusText === 'not_initialized') {
        return { label: '초기화 대기', cls: 'bg-gray-500/15 text-gray-300', detail: '읽기 원장이 아직 초기화되지 않음' };
    }
    const counts = record(snapshot.status?.counts);
    const eventCount = firstNumber(counts, ['events', 'event_count']);
    const lastEventAt = firstString(status, ['last_event_at']);
    if (eventCount === 0 && !lastEventAt) {
        return { label: '관측 대기', cls: 'bg-violet-500/15 text-violet-300', detail: '원장 이벤트 없음' };
    }
    if (snapshot.status.ok === false || normalized === 'unavailable' || normalized === 'failed' || statusText === 'error') {
        return { label: '운영 보류', cls: 'bg-red-500/15 text-red-300', detail: qualityText || statusText || '코어 상태 이상' };
    }
    if (snapshot.unavailable.length > 0 || normalized === 'degraded' || normalized === 'unknown' || quality?.ok === false || quality?.stale === true) {
        return {
            label: '일부 지연',
            cls: 'bg-amber-500/15 text-amber-300',
            detail: snapshot.unavailable.length > 0
                ? `${snapshot.unavailable.length}개 섹션 확인 필요`
                : qualityText || '데이터 품질 확인 필요',
        };
    }
    return { label: '관측 정상', cls: 'bg-teal-500/15 text-teal-300', detail: qualityText || '데이터 품질 통과' };
}

function modeTone(mode: string): string {
    if (mode === 'PAPER') return 'border-blue-400/30 bg-blue-500/10 text-blue-300';
    if (mode === 'SHADOW') return 'border-violet-400/30 bg-violet-500/10 text-violet-300';
    return 'border-gray-500/30 bg-gray-500/10 text-gray-300';
}

export default function AlphaCoreOpsCard({ loadSnapshot = fetchAlphaCoreSnapshot }: Props) {
    const { token } = useAuth();
    const [snapshot, setSnapshot] = useState<AlphaCoreSnapshot>(EMPTY);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let active = true;
        let inFlight = false;
        let firstLoad = true;
        const refresh = () => {
            if (inFlight) return;
            inFlight = true;
            if (firstLoad) setLoading(true);
            loadSnapshot(token ?? undefined)
                .then(next => { if (active) setSnapshot(next); })
                .catch(() => { if (active && firstLoad) setSnapshot(EMPTY); })
                .finally(() => {
                    inFlight = false;
                    firstLoad = false;
                    if (active) setLoading(false);
                });
        };
        refresh();
        const refreshTimer = window.setInterval(refresh, 60_000);
        return () => {
            active = false;
            window.clearInterval(refreshTimer);
        };
    }, [loadSnapshot, token]);

    const view = useMemo(() => {
        const status = record(snapshot.status);
        const database = record(snapshot.status?.database);
        const portfolioEnvelope = record(snapshot.portfolio);
        const portfolio = record(snapshot.portfolio?.portfolio) ?? portfolioEnvelope;
        const ledger = record(snapshot.ledger);
        const ledgerSummary = record(snapshot.ledger?.summary) ?? record(snapshot.ledger?.counts) ?? ledger;
        const reconciliation = record(snapshot.ledger?.reconciliation);
        const risks = riskItems(snapshot);
        const hypotheses = hypothesisItems(snapshot);
        const rejected = risks.filter(item => {
            const decision = String(item.decision ?? item.state ?? '').toUpperCase();
            return decision.includes('REJECT') || decision.includes('BLOCK') || decision.includes('DENY');
        });
        const rejectReasons = Array.from(new Set(
            rejected.flatMap(item => reasonList(item.reason_codes ?? item.reject_reasons ?? item.reasons)),
        )).slice(0, 3);
        const statusRisk = record(snapshot.status?.risk_state);
        const riskState = firstString(statusRisk, ['state', 'status', 'level'])
            ?? (typeof snapshot.status?.risk_state === 'string' ? snapshot.status.risk_state : null)
            ?? firstString(record(risks[0]), ['decision', 'state'])
            ?? '관측 중';
        const pending = firstNumber(ledgerSummary, ['pending', 'pending_count', 'pending_intents', 'pending_order_intents'])
            ?? numericCount(snapshot.ledger?.pending)
            ?? numericCount(snapshot.ledger?.pending_count)
            ?? 0;
        const reconcile = firstNumber(reconciliation, ['unreconciled_count', 'pending', 'required', 'unmatched', 'unreconciled'])
            ?? firstNumber(ledgerSummary, ['reconcile_required', 'reconciliation_pending', 'unreconciled'])
            ?? numericCount(snapshot.ledger?.reconcile_required)
            ?? 0;

        return {
            mode: (firstString(status, ['mode', 'operating_mode']) ?? '확인 불가').toUpperCase(),
            dataAsOf: firstString(status, ['last_event_at'])
                ?? firstString(portfolioEnvelope, ['as_of']),
            responseAt: firstString(status, ['generated_at'])
                ?? firstString(portfolioEnvelope, ['generated_at']),
            cash: firstNumber(portfolio, ['cash_krw', 'cash', 'available_cash_krw']),
            nav: firstNumber(portfolio, ['nav_krw', 'nav', 'equity_krw', 'total_equity']),
            gross: firstNumber(portfolio, ['gross_exposure_krw', 'gross_exposure']),
            net: firstNumber(portfolio, ['net_exposure_krw', 'net_exposure']),
            drawdown: firstNumber(portfolio, ['drawdown_pct', 'dd_pct', 'drawdown']),
            riskState,
            rejectReasons,
            pending,
            reconcile,
            hypotheses: hypotheses.slice(0, 3),
            hypothesisStatus: firstString(record(snapshot.hypotheses), ['status']),
            databaseLabel: !snapshot.status
                ? 'DB 확인 불가'
                : (database?.initialized === false || database?.available === false ? 'DB WAIT' : 'DB READY'),
            health: health(snapshot),
        };
    }, [snapshot]);

    if (loading) {
        return <section aria-label="Alpha Core 운영 현황 불러오는 중" className="h-[190px] animate-pulse rounded-2xl border border-white/[0.06] bg-[#13151f]" />;
    }

    return (
        <section aria-label="Alpha Core 읽기 전용 운영 현황" className="overflow-hidden rounded-2xl border border-cyan-400/15 bg-[#13151f]">
            <div className="flex flex-wrap items-center gap-2 border-b border-white/[0.06] px-4 py-3.5 sm:px-5">
                <span className="grid h-8 w-8 place-items-center rounded-lg bg-cyan-500/10 text-cyan-300">
                    <i className="fas fa-shield-halved text-[13px]" />
                </span>
                <div className="min-w-0">
                    <h2 className="text-[14px] font-black text-white">AlphaClaw Core</h2>
                    <p className="text-[11px] text-gray-500">읽기 전용 운영 원장 · 주문 기능 없음</p>
                </div>
                <span className={`rounded-full border px-2 py-1 font-mono text-[11px] font-black ${modeTone(view.mode)}`}>{view.mode}</span>
                <span className={`rounded-full px-2 py-1 text-[11px] font-extrabold ${view.health.cls}`}>{view.health.label}</span>
                <span className="ml-auto text-[11px] text-gray-500" title={`API 응답 ${formatTime(view.responseAt)}`}>
                    {view.dataAsOf ? `원장 ${formatTime(view.dataAsOf)}` : '원장 이벤트 없음'}
                </span>
            </div>

            <div className="grid grid-cols-2 gap-px bg-white/[0.05] sm:grid-cols-5">
                <Metric label="현금" value={formatMoney(view.cash)} />
                <Metric label="NAV" value={formatMoney(view.nav)} />
                <Metric label="Gross" value={formatMoney(view.gross)} />
                <Metric label="Net" value={formatMoney(view.net)} />
                <Metric label="Drawdown" value={formatPct(view.drawdown)} warn={(view.drawdown ?? 0) < -3} spanMobile />
            </div>

            <div className="grid gap-3 p-4 sm:grid-cols-3 sm:p-5">
                <div className="min-w-0 rounded-xl border border-white/[0.06] bg-black/15 p-3">
                    <div className="flex items-center justify-between gap-2">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Risk Kernel</span>
                        <span className="truncate font-mono text-[11px] font-bold text-amber-300">{view.riskState}</span>
                    </div>
                    {view.rejectReasons.length > 0 ? (
                        <ul className="mt-2 space-y-1.5">
                            {view.rejectReasons.map(reason => (
                                <li key={reason} className="flex min-w-0 items-start gap-1.5 text-[11px] leading-4 text-gray-300">
                                    <i className="fas fa-ban mt-0.5 text-[9px] text-rose-400" />
                                    <span className="break-words">{reason}</span>
                                </li>
                            ))}
                        </ul>
                    ) : <p className="mt-2 text-[11px] text-gray-500">최근 거절 사유 없음</p>}
                </div>

                <div className="rounded-xl border border-white/[0.06] bg-black/15 p-3">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Paper Ledger</div>
                    <div className="mt-2 grid grid-cols-2 gap-2">
                        <LedgerMetric label="대기" value={view.pending} tone="text-blue-300" />
                        <LedgerMetric label="대사 필요" value={view.reconcile} tone={view.reconcile ? 'text-rose-300' : 'text-teal-300'} />
                    </div>
                    <p className="mt-2 text-[10px] text-gray-500">브로커 주문 경로와 분리된 내부 페이퍼 원장</p>
                </div>

                <div className="min-w-0 rounded-xl border border-white/[0.06] bg-black/15 p-3">
                    <div className="flex items-center justify-between gap-2">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Hypotheses</span>
                        <span className="font-mono text-[10px] text-gray-500">{view.hypotheses.length} shown</span>
                    </div>
                    {view.hypotheses.length > 0 ? (
                        <ul className="mt-2 space-y-1.5">
                            {view.hypotheses.map((item, index) => {
                                const itemRecord = record(item);
                                const id = firstString(itemRecord, ['hypothesis_id', 'id']) ?? String(index + 1);
                                const title = firstString(itemRecord, ['title', 'name', 'thesis']) ?? `가설 ${id}`;
                                const state = firstString(itemRecord, ['status', 'state']) ?? '관측';
                                return (
                                    <li key={id} className="flex min-w-0 items-center gap-2 text-[11px]">
                                        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-cyan-400" />
                                        <span className="min-w-0 flex-1 truncate text-gray-200" title={title}>{title}</span>
                                        <span className="shrink-0 rounded bg-white/[0.06] px-1.5 py-0.5 text-[9px] text-gray-400">{state}</span>
                                    </li>
                                );
                            })}
                        </ul>
                    ) : <p className="mt-2 text-[11px] text-gray-500">{view.hypothesisStatus === 'not_implemented' ? '가설 원장 준비 중' : '등록된 검증 가설 없음'}</p>}
                </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-1 border-t border-white/[0.05] px-4 py-2 text-[11px] text-gray-500 sm:px-5">
                <span>{view.databaseLabel} · Data Quality {view.health.detail}</span>
                <span>GET-only · 자동 승인/주문 없음</span>
            </div>
        </section>
    );
}

function Metric({ label, value, warn = false, spanMobile = false }: { label: string; value: string; warn?: boolean; spanMobile?: boolean }) {
    return (
        <div className={`bg-[#10121a] px-3 py-3 sm:px-4 ${spanMobile ? 'col-span-2 sm:col-span-1' : ''}`}>
            <div className="text-[10px] font-bold uppercase tracking-wider text-gray-500">{label}</div>
            <div className={`mt-1 truncate font-mono text-[14px] font-black tabular-nums ${warn ? 'text-rose-300' : 'text-gray-100'}`}>{value}</div>
        </div>
    );
}

function LedgerMetric({ label, value, tone }: { label: string; value: number; tone: string }) {
    return (
        <div className="rounded-lg bg-white/[0.025] px-2 py-2 text-center">
            <div className={`font-mono text-lg font-black tabular-nums ${tone}`}>{value.toLocaleString('ko-KR')}</div>
            <div className="text-[10px] text-gray-500">{label}</div>
        </div>
    );
}
