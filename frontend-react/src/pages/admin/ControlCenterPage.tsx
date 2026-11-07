import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import {
    type CcCheck, type CcHistory, type CcPage, type CcStatus,
    fetchControlCenterHistory, fetchControlCenterIncidents, fetchControlCenterRoutes, fetchControlCenterSummary,
} from '@/lib/controlCenterApi';

/**
 * 운영 관제 센터 — 앱 전체 운영 상태를 한 화면에서 본다.
 * 감시는 MiniPC 의 별도 실행기(python -m app.services.control_center run)가 하고,
 * 이 화면은 그 결과를 읽기만 한다. 재시작·재실행 같은 조치 버튼은 두지 않는다(잡 재실행은 관리자 > 잡 상태).
 */

const POLL_MS = 30_000;
const TIERS = [['fast', '빠른 점검'], ['standard', '일반 점검'], ['deep', '심층 점검']] as const;

export const STATUS_META: Record<CcStatus, { label: string; icon: string; cls: string; dot: string }> = {
    ok: { label: '정상', icon: 'fa-check-circle', cls: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20', dot: 'bg-emerald-400' },
    warn: { label: '주의', icon: 'fa-exclamation-triangle', cls: 'text-amber-300 bg-amber-500/10 border-amber-500/20', dot: 'bg-amber-400' },
    fail: { label: '장애', icon: 'fa-times-circle', cls: 'text-red-300 bg-red-500/10 border-red-500/25', dot: 'bg-red-500' },
    unknown: { label: '확인 불가', icon: 'fa-question-circle', cls: 'text-gray-300 bg-white/5 border-white/10', dot: 'bg-gray-400' },
    skipped: { label: '판정 안 함', icon: 'fa-minus-circle', cls: 'text-gray-400 bg-white/5 border-white/10', dot: 'bg-gray-600' },
};

const FAMILY_LABEL: Record<string, string> = {
    process: '프로세스·터널', endpoint: 'API 엔드포인트', page: '메뉴 화면', data: '데이터 신선도', job: '스케줄 작업',
    task: 'Windows 작업', provider: '외부 API', host: '호스트', security: '보안', monitor: '관제 실행기',
};
const FAMILY_ORDER = ['process', 'security', 'endpoint', 'data', 'job', 'task', 'provider', 'host', 'monitor'];
const PROBE_LABEL: Record<string, string> = {
    auth_gate: '인증 점검', public_safe: '공개 점검', public_reviewed: '공개 검토 완료 · 미호출', public_unreviewed: '검토 필요', excluded: '제외', none: '등록 정보만',
};

export function StatusBadge({ status, small = false }: { status: CcStatus; small?: boolean }) {
    const m = STATUS_META[status] ?? STATUS_META.unknown;
    return (
        <span className={`inline-flex shrink-0 items-center gap-1 self-start whitespace-nowrap rounded border ${small ? 'px-1.5 py-0 text-[11px]' : 'px-2 py-0.5 text-xs'} ${m.cls}`}>
            <i className={`fas ${m.icon}`} aria-hidden="true" />{m.label}
        </span>
    );
}

function useControlRequest<T>() {
    const current = useRef<AbortController | null>(null);
    const [data, setData] = useState<T | null>(null);
    const [error, setError] = useState('');
    const [pending, setPending] = useState(false);

    const abort = useCallback(() => {
        current.current?.abort();
        current.current = null;
    }, []);
    useEffect(() => abort, [abort]);

    const clear = () => {
        abort();
        setData(null);
        setError('');
        setPending(false);
    };

    const run = useCallback(async (request: (signal: AbortSignal) => Promise<T>) => {
        if (current.current) return;
        const controller = new AbortController();
        current.current = controller;
        setPending(true);
        try {
            const result = await request(controller.signal);
            if (!controller.signal.aborted) {
                setData(result);
                setError('');
            }
        } catch (e) {
            if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '조회에 실패했습니다.');
        } finally {
            if (current.current === controller) {
                current.current = null;
                setPending(false);
            }
        }
    }, []);
    return { data, error, pending, run, clear };
}

function since(iso: string | null | undefined): string {
    if (!iso) return '-';
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return '-';
    return ageLabel((Date.now() - t) / 1000);
}

function ageLabel(seconds: number): string {
    const m = Math.max(0, Math.floor(seconds / 60));
    if (m === 0) return '방금';
    if (m < 60) return `${m}분 전`;
    if (m < 2880) return `${Math.round(m / 60)}시간 전`;
    return `${Math.round(m / 1440)}일 전`;
}

function PageCard({ page }: { page: CcPage }) {
    const [open, setOpen] = useState(false);
    return (
        <li className="min-w-0 rounded-lg border border-white/10 bg-white/[0.02]">
            <button type="button" onClick={() => setOpen(v => !v)} aria-expanded={open}
                className="flex min-h-11 w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left hover:bg-white/5">
                <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${STATUS_META[page.status]?.dot ?? 'bg-gray-400'}`} aria-hidden="true" />
                <span className="min-w-0 flex-1">
                    <span className="block break-words text-sm text-gray-100">{page.label}{page.critical && <span className="ml-1 text-[11px] text-red-300">핵심</span>}</span>
                    <span className="block break-all font-mono text-[11px] text-gray-400">{page.path}</span>
                </span>
                <StatusBadge status={page.status} small />
            </button>
            {open && (
                <ul className="px-3 pb-3 space-y-1 text-xs">
                    {page.parts.length === 0 && <li className="text-gray-400">표시할 연결 점검이 없습니다.</li>}
                    {page.parts.map(p => (
                        <li key={p.kind + p.target} className="flex gap-2">
                            <StatusBadge status={p.status} small />
                            <span className="min-w-0 break-words text-gray-300"><span className="font-mono text-gray-400">{p.target}</span> — {p.detail}</span>
                        </li>
                    ))}
                </ul>
            )}
        </li>
    );
}

function HistoryStrip({ history }: { history: CcHistory }) {
    const rows = [...history.history].reverse().slice(-96);
    if (!rows.length) return <p className="mt-2 text-xs text-gray-400">최근 24시간 관측 이력이 없습니다.</p>;
    const newest = rows[rows.length - 1];
    return (
        <div className="mt-2">
            <div className="flex gap-px" aria-label={`최근 ${rows.length}회 관측`}>
                {rows.map((h, i) => (
                    <span key={i} title={`${h.observed_at} ${STATUS_META[h.status]?.label ?? h.status} ${h.detail}`}
                        className={`h-4 min-w-0 flex-1 rounded-sm ${STATUS_META[h.status]?.dot ?? 'bg-gray-500'}`} />
                ))}
            </div>
            <p className="mt-1 break-words text-xs text-gray-400">최근 관측 {since(newest.observed_at)} · {STATUS_META[newest.status].label} · {newest.detail}</p>
            <details className="mt-1 text-xs text-gray-400">
                <summary className="cursor-pointer py-2">관측 시각과 내용</summary>
                <ul className="max-h-56 space-y-1 overflow-y-auto break-words">
                    {[...rows].reverse().map((row, i) => (
                        <li key={i}><time dateTime={row.observed_at}>{row.observed_at}</time> · {STATUS_META[row.status].label} · {row.detail}</li>
                    ))}
                </ul>
            </details>
        </div>
    );
}

function CheckRow({ c, token }: { c: CcCheck; token?: string }) {
    const [open, setOpen] = useState(false);
    const { data, error, pending, run, clear } = useControlRequest<CcHistory>();
    const load = () => run(signal => fetchControlCenterHistory(c.check_id, token, signal));
    const toggle = () => {
        setOpen(!open);
        if (open) clear();
        else void load();
    };
    return (
        <li className="border-t border-white/5 py-2">
            <button type="button" onClick={toggle} aria-expanded={open} className="flex min-h-11 w-full flex-wrap items-start gap-2 text-left">
                <StatusBadge status={c.status} small />
                {c.severity === 'critical' && <span className="text-[10px] rounded bg-red-500/20 px-1 text-red-200">치명</span>}
                <span className="min-w-0 break-all font-mono text-xs text-gray-400">{c.check_id}</span>
                <span className="min-w-0 basis-full break-words text-sm text-gray-200">{c.detail}</span>
                <span className="text-xs text-gray-400">{FAMILY_LABEL[c.family] ?? c.family} · 최근 관측 {since(c.last_observed_at)}{c.latency_ms != null ? ` · ${c.latency_ms}ms` : ''}</span>
            </button>
            {open && pending && <p role="status" className="mt-2 text-xs text-gray-400">관측 이력을 불러오는 중…</p>}
            {open && error && <p role="alert" className="mt-2 break-words text-xs text-amber-300">{error} <button type="button" className="min-h-11 underline" onClick={load}>다시 시도</button></p>}
            {open && data && <HistoryStrip history={data} />}
        </li>
    );
}

function RoutesPanel({ token }: { token?: string }) {
    const { data, error, pending, run } = useControlRequest<Awaited<ReturnType<typeof fetchControlCenterRoutes>>>();
    const [q, setQ] = useState('');
    const load = () => run(signal => fetchControlCenterRoutes(token, signal));
    const rows = useMemo(() => (data?.routes ?? []).filter(r => r.rule.includes(q.trim())), [data, q]);
    if (!data) {
        return (
            <div>
                <button type="button" onClick={load} disabled={pending} className="min-h-11 rounded bg-white/5 px-3 text-xs text-gray-300 hover:bg-white/10">
                    <i className="fas fa-list mr-1" aria-hidden="true" />{pending ? '경로 목록을 불러오는 중…' : '등록 경로와 점검 설정 보기'}
                </button>
                {error && <p role="alert" className="mt-2 break-words text-xs text-amber-300">{error}</p>}
            </div>
        );
    }
    const t = data.totals;
    return (
        <div className="space-y-3">
            <p className="text-sm text-gray-300">
                등록 경로 {t.routes} · 인증 점검 설정 {t.auth_gate} · 심층 점검 설정 {t.deep}
                · 공개 점검 설정 {t.public_safe} · 검토 필요 공개 {t.public_unreviewed} · 제외 {t.excluded}
            </p>
            <p className="text-xs text-gray-400">경로 목록은 등록 정보입니다. 실제 점검 결과는 위 상태와 관측 이력에서 확인할 수 있습니다.</p>
            <label className="block text-xs text-gray-400">경로 검색
                <input value={q} onChange={e => setQ(e.target.value)} className="mt-1 block w-full rounded bg-black/30 border border-white/10 px-2 py-1 text-sm text-gray-100" />
            </label>
            <p className="text-xs text-gray-400" role="status">검색 결과 {rows.length}건{rows.length > 500 ? ' · 처음 500건 표시' : ''}</p>
            <div className="max-h-96 overflow-y-auto">
                <table role="table" className="block !w-full table-fixed text-xs sm:table" aria-label="엔드포인트 감시 범위">
                    <colgroup className="hidden sm:table-column-group"><col className="w-1/2" /><col className="w-1/6" /><col className="w-1/6" /><col className="w-1/6" /></colgroup>
                    <thead className="hidden text-left text-gray-400 sm:table-header-group"><tr><th className="py-1">경로</th><th>메서드</th><th>인증</th><th>점검 설정</th></tr></thead>
                    <tbody role="rowgroup" className="block sm:table-row-group">
                        {rows.slice(0, 500).map(r => (
                            <tr role="row" key={r.rule + r.methods.join()} className="grid grid-cols-3 gap-x-2 border-t border-white/5 py-2 sm:table-row">
                                <td role="cell" className="col-span-3 min-w-0 !whitespace-normal break-all font-mono text-gray-200 sm:py-2">{r.rule}</td>
                                <td role="cell" className="min-w-0 !whitespace-normal break-all !px-1 text-gray-400"><span className="block sm:hidden">메서드</span>{r.methods.join(', ')}</td>
                                <td role="cell" className="min-w-0 !whitespace-normal break-all !px-1 text-gray-400"><span className="block sm:hidden">인증</span>{r.auth}</td>
                                <td role="cell" className="min-w-0 !whitespace-normal break-all !px-1 text-gray-400"><span className="block sm:hidden">점검 설정</span>{PROBE_LABEL[r.probe_mode] ?? r.probe_mode}{r.deep ? ' + 데이터' : ''}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

export default function ControlCenterPage() {
    const { token } = useAuth();
    return <ControlCenterView key={token} apiToken={token ?? undefined} />;
}

function ControlCenterView({ apiToken }: { apiToken?: string }) {
    const { data: snap, error, pending, run } = useControlRequest<Awaited<ReturnType<typeof fetchControlCenterSummary>>>();
    const recent = useControlRequest<Awaited<ReturnType<typeof fetchControlCenterIncidents>>>();
    const load = useCallback(() => run(signal => fetchControlCenterSummary(apiToken, signal)), [apiToken, run]);

    useEffect(() => {
        void load();
        const refreshVisible = () => { if (document.visibilityState === 'visible') void load(); };
        const timer = setInterval(refreshVisible, POLL_MS);
        document.addEventListener('visibilitychange', refreshVisible);
        return () => {
            clearInterval(timer);
            document.removeEventListener('visibilitychange', refreshVisible);
        };
    }, [load]);

    const pages = useMemo(() => {
        const order: Record<string, number> = { fail: 0, warn: 1, unknown: 2, skipped: 3, ok: 4 };
        return [...(snap?.pages ?? [])].sort((a, b) => (order[a.status] - order[b.status]) || Number(b.critical) - Number(a.critical));
    }, [snap]);

    const c = snap?.counts ?? {};
    return (
        <div className="min-w-0 space-y-4 px-1 py-3 sm:px-4 sm:py-5">
            <header className="flex flex-wrap items-center justify-between gap-3">
                <div>
                    <h1 className="text-xl font-bold text-white"><i className="fas fa-satellite-dish text-cyan-400 mr-2" />운영 관제 센터</h1>
                    <p className="mt-1 text-sm text-gray-400">서비스, 데이터, 예약 작업의 최근 점검 결과입니다.</p>
                    {snap?.generated_at && <p className="mt-1 text-xs text-gray-400">마지막 결과 생성 {since(snap.generated_at)}</p>}
                </div>
                <div className="flex items-center gap-2">
                    <button type="button" onClick={load} disabled={pending} className="min-h-11 rounded bg-white/5 px-3 text-xs text-gray-300 hover:bg-white/10 hover:text-white" aria-label="관제 새로고침">
                        <i className="fas fa-sync-alt mr-1" aria-hidden="true" />{pending ? '새로고침 중…' : '새로고침'}
                    </button>
                </div>
            </header>

            {!snap && !error && <p role="status" className="text-sm text-gray-400">관제 상태를 불러오는 중…</p>}
            {error && <p role="alert" className="break-words rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
                관제 요약 조회 실패 · {error}{snap && ' 마지막으로 받은 결과를 표시합니다.'}
            </p>}

            {snap && snap.monitor.status !== 'ok' && (
                <div role="alert" className="break-words rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
                    <i className="fas fa-exclamation-circle mr-1" aria-hidden="true" />관제 실행기 이상: {snap.monitor.detail} · 일부 결과가 오래됐거나 아직 수집되지 않았습니다.
                </div>
            )}

            {snap && (
                <>
                    <section aria-label="요약" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                        {[
                            ['전체', <StatusBadge key="o" status={snap.overall} />],
                            ['장애', c.fail == null ? '—' : `${c.fail}건${c.critical_fail == null ? '' : ` (치명 ${c.critical_fail})`}`],
                            ['주의', c.warn == null ? '—' : `${c.warn}건`],
                            ['열린 사건', c.open_incidents == null ? '—' : `${c.open_incidents}건`],
                        ].map(([label, value]) => (
                            <div key={String(label)} className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                                <div className="text-xs text-gray-400">{label}</div>
                                <div className="mt-1 text-base font-semibold text-gray-100 tabular-nums">{value}</div>
                            </div>
                        ))}
                    </section>

                    <section aria-labelledby="cc-monitor" className="rounded-lg border border-white/10 p-3">
                        <h2 id="cc-monitor" className="text-sm font-semibold text-white">관제 실행기</h2>
                        <ul className="mt-2 grid gap-2 sm:grid-cols-3">
                            {TIERS.map(([tier, label]) => {
                                const state = snap.monitor.tiers?.[tier];
                                return <li key={tier} className="min-w-0 rounded border border-white/10 p-2.5">
                                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-gray-200">
                                        {label}<StatusBadge status={state?.status ?? 'unknown'} small />
                                    </div>
                                    <p className="mt-1 break-words text-xs text-gray-400">
                                        {state?.detail ?? '실행 정보 없음'}{typeof state?.age_seconds === 'number' && ` · ${ageLabel(state.age_seconds)}`}
                                    </p>
                                </li>;
                            })}
                        </ul>
                        <p className="mt-2 text-xs text-gray-400">
                            확인 불가 {c.unknown ?? '—'} · 판정 안 함 {c.skipped ?? '—'}
                        </p>
                    </section>

                    <section aria-label="분야별 상태" className="flex flex-wrap gap-2">
                        {FAMILY_ORDER.filter(f => snap.families[f]).map(f => (
                            <span key={f} className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs ${STATUS_META[snap.families[f].status]?.cls ?? ''}`}>
                                {FAMILY_LABEL[f]} · {STATUS_META[snap.families[f].status]?.label}
                                <span className="text-gray-400 tabular-nums">{(snap.families[f].counts.fail ?? 0) + (snap.families[f].counts.warn ?? 0)}/{Object.values(snap.families[f].counts).reduce((a, b) => a + b, 0)}</span>
                            </span>
                        ))}
                    </section>

                    <section aria-labelledby="cc-failing" className="rounded-xl border border-white/10 p-3">
                        <h2 id="cc-failing" className="text-sm font-semibold text-white">장애 {snap.failing.length} · 주의 {snap.warning.length}</h2>
                        <p className="text-[11px] text-gray-500 mb-1">항목을 누르면 최근 24시간 관측 이력이 열립니다.</p>
                        {snap.failing.length + snap.warning.length === 0
                            ? <p className="py-2 text-sm text-gray-400">표시할 장애·주의 관측이 없습니다.</p>
                            : <ul>{[...snap.failing, ...snap.warning].map(x => <CheckRow key={x.check_id} c={x} token={apiToken} />)}</ul>}
                    </section>

                    <section aria-labelledby="cc-incidents" className="rounded-xl border border-white/10 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-x-2">
                            <h2 id="cc-incidents" className="text-sm font-semibold text-white">열린 사건 {snap.open_incidents.length}</h2>
                            <button type="button" className="min-h-11 text-xs text-gray-300 hover:text-white"
                                aria-expanded={recent.pending || recent.data !== null}
                                onClick={() => {
                                    if (recent.pending || recent.data) recent.clear();
                                    else void recent.run(signal => fetchControlCenterIncidents('recent', apiToken, signal));
                                }}>
                                {recent.pending || recent.data ? '최근 이력 닫기' : '최근 이력 보기'}
                            </button>
                        </div>
                        {recent.pending && <p role="status" className="text-xs text-gray-400">최근 사건을 불러오는 중…</p>}
                        {recent.error && <p role="alert" className="break-words text-xs text-amber-300">{recent.error}</p>}
                        {recent.data && <p className="text-xs text-gray-400">최근 사건 {recent.data.length}건</p>}
                        <ul className="mt-2 space-y-1 text-sm">
                            {(recent.data ?? snap.open_incidents).map(i => (
                                <li key={i.id} className="flex flex-wrap gap-2 border-t border-white/5 pt-1">
                                    <StatusBadge status={i.resolved_at ? 'ok' : 'fail'} small />
                                    <span className="min-w-0 break-all font-mono text-xs text-gray-400">{i.check_id}</span>
                                    <span className="min-w-0 basis-full break-words text-gray-300">{i.last_detail}</span>
                                    <span className="text-[11px] text-gray-500">발생 {since(i.opened_at)}{i.resolved_at ? ` · 복구 ${since(i.resolved_at)}` : ''} · {i.occurrences}회{i.flapping ? ' · 깜빡임' : ''}</span>
                                </li>
                            ))}
                            {(recent.data ?? snap.open_incidents).length === 0 && <li className="text-sm text-gray-400">표시할 사건이 없습니다.</li>}
                        </ul>
                    </section>

                    <section aria-labelledby="cc-pages" className="rounded-xl border border-white/10 p-3">
                        <h2 id="cc-pages" className="mb-3 text-sm font-semibold text-white">메뉴 화면 상태</h2>
                        {pages.length ? <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{pages.map(p => <PageCard key={p.path} page={p} />)}</ul>
                            : <p className="text-sm text-gray-400">수집된 화면 상태가 없습니다.</p>}
                    </section>

                    <section aria-labelledby="cc-routes" className="rounded-xl border border-white/10 p-3">
                        <h2 id="cc-routes" className="text-sm font-semibold text-white mb-2">엔드포인트 감시 범위</h2>
                        <p className="mb-2 text-xs text-gray-400">
                            {snap.gate_coverage
                                ? `최근 인증 응답 관측 ${snap.gate_coverage.observed}/${snap.gate_coverage.candidates}개 · 미관측 ${snap.gate_coverage.skipped}개`
                                : '최근 인증 응답 관측 정보 없음'}
                        </p>
                        <RoutesPanel token={apiToken} />
                    </section>

                </>
            )}
        </div>
    );
}
