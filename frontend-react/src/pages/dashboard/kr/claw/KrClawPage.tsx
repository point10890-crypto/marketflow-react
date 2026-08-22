/**
 * Claw LIVE — 전체 화면 (/dashboard/kr/claw).
 *
 * 12컬럼: 상태 스트립 3×4 → 주도주 7 : 이벤트 5 → 브리핑 8 : 시스템 4 (접힘).
 * 읽기전용. 장중 5s / 장외 60s 폴링(useAutoRefresh: 탭 비활성 시 중단).
 * 설계: docs/superpowers/specs/2026-08-22-claw-dashboard-design.md
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { fetchAuthAPI } from '@/lib/api';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import { CLAW_OVERVIEW_ENDPOINT, ClawOverview, LOOP_LABEL, REGIME_LABEL, eventChip, fmtAge, hhmm, isClawOverview } from '@/lib/claw';
import ClawLeadersCard from './ClawLeadersCard';
import ClawEventsCard from './ClawEventsCard';
import ClawBriefsCard from './ClawBriefsCard';

export default function KrClawPage() {
    const { token } = useAuth();
    const [data, setData] = useState<ClawOverview | null>(null);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(true);
    const [tick, setTick] = useState(0); // "n초 전" 1초 갱신용
    const fetchedAt = useRef<number>(Date.now());

    const load = useCallback(async () => {
        try {
            const res = await fetchAuthAPI<unknown>(CLAW_OVERVIEW_ENDPOINT, token ?? undefined);
            if (!isClawOverview(res)) throw new Error('bad shape');
            setData(res); setError(''); fetchedAt.current = Date.now();
        } catch {
            setError('Claw 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.');
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => { void load(); }, [load]);
    useAutoRefresh(load, data?.loop.market_open ? 5000 : 60000, true);
    useEffect(() => { const t = setInterval(() => setTick(v => v + 1), 1000); return () => clearInterval(t); }, []);

    return (
        <div className="min-h-screen bg-[#09090b] p-4 text-white sm:p-6 lg:p-8">
            <div className="mx-auto max-w-[1200px] space-y-4">
                <Header data={data} tick={tick} fetchedAt={fetchedAt.current} />
                {loading && <Skeleton />}
                {!loading && error && (
                    <div className="rounded-2xl border border-red-500/20 bg-red-500/5 p-6 text-center">
                        <p className="mb-4 text-sm text-red-300">{error}</p>
                        <button type="button" onClick={load} className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-medium text-gray-300 hover:bg-white/10">
                            <i className="fas fa-rotate-right" />다시 시도
                        </button>
                    </div>
                )}
                {!loading && !error && data && (
                    <>
                        <StatusStrip data={data} />
                        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
                            <ClawLeadersCard data={data} />
                            <ClawEventsCard data={data} />
                            <ClawBriefsCard data={data} />
                            <SystemCard data={data} />
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}

function Header({ data, tick, fetchedAt }: { data: ClawOverview | null; tick: number; fetchedAt: number }) {
    const state = data?.loop.state ?? null;
    const live = state === 'running';
    // 서버 age + 마지막 fetch 이후 경과초(tick 으로 1초마다 재계산) → 살아있음을 보여준다
    void tick;
    const age = data?.loop.heartbeat_age_s != null ? data.loop.heartbeat_age_s + Math.max(0, Math.round((Date.now() - fetchedAt) / 1000)) : null;
    return (
        <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2.5">
                <span className="relative grid h-2.5 w-2.5 place-items-center">
                    <span className={`absolute inline-flex h-2.5 w-2.5 rounded-full ${live ? 'bg-teal-400/60 animate-ping' : ''}`} />
                    <span className={`relative inline-flex h-2 w-2 rounded-full ${live ? 'bg-teal-400' : state === 'halt' ? 'bg-amber-400' : state === 'dead' ? 'bg-red-500' : 'bg-gray-600'}`} />
                </span>
                <h1 className="text-xl font-black tracking-tight sm:text-2xl">Claw LIVE</h1>
                {data && (
                    <span className="text-[11px] text-gray-500">
                        {data.loop.last_tick_ts ? `마지막 틱 ${data.loop.last_tick_ts.slice(5, 16).replace('T', ' ')}` : '아직 틱 없음'}
                        {data.loop.source && ` · ${data.loop.source} ${fmtAge(data.loop.source_age_s)} 전`}
                        {age != null && ` · 하트비트 ${fmtAge(age)} 전`}
                    </span>
                )}
            </div>
            <Link to="/dashboard/kr/leading-stocks" className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[12px] font-bold text-gray-300 hover:bg-white/[0.08] hover:text-white">
                <i className="fas fa-chart-line text-[11px]" />주도주LIVE 열기
            </Link>
        </div>
    );
}

function StatusStrip({ data }: { data: ClawOverview }) {
    const L = data.loop, R = data.regime;
    const loop = LOOP_LABEL[L.state] ?? LOOP_LABEL.idle;
    const reg = REGIME_LABEL[R.regime] ?? REGIME_LABEL.UNKNOWN;
    const halted = L.state === 'halt';
    const counts = Object.entries(data.events.counts);
    const tile = (warn: 'none' | 'warn' | 'bad' = 'none') =>
        `rounded-2xl border bg-[#13151f] px-4 py-3.5 min-h-[92px] flex flex-col gap-1.5 ${warn === 'bad' ? 'border-red-500/50' : warn === 'warn' || halted ? 'border-amber-400/45' : 'border-white/[0.06]'}`;
    const k = 'text-[11px] font-semibold uppercase tracking-wider text-gray-500';
    const v = 'flex flex-wrap items-baseline gap-2 text-[22px] font-extrabold leading-none tracking-tight';
    const d = 'flex flex-wrap items-center gap-1.5 text-[12px] text-gray-400';
    return (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <section className={tile(L.state === 'dead' ? 'bad' : halted ? 'warn' : 'none')}>
                <div className={k}>루프 · 시장</div>
                <div className={v}>
                    <span className={halted ? 'text-amber-300' : L.state === 'dead' ? 'text-red-400' : 'text-white'}>{loop.label}</span>
                    <small className="text-[12px] font-semibold text-gray-400">{L.state === 'running' ? `틱 ${hhmm(L.last_tick_ts)}` : loop.sub}</small>
                </div>
                <div className={d}>
                    {halted ? <><span className="rounded bg-amber-500/15 px-1.5 text-[11px] font-bold text-amber-300">HALT</span>{R.reasons[0]}</>
                        : L.state === 'dead' ? `하트비트 ${fmtAge(L.heartbeat_age_s)} 전 · 워치독 재기동 대기`
                        : `하트비트 ${fmtAge(L.heartbeat_age_s)} 전 · 소스 ${L.source ?? '-'}`}
                </div>
            </section>
            <section className={tile()}>
                <div className={k}>레짐</div>
                <div className={v}><span className={reg.cls}>{reg.label}</span>{R.gate_score != null ? <small className="text-[12px] font-semibold text-gray-400">gate {R.gate_status} {R.gate_score}</small> : <small className="text-[12px] text-gray-500">입력 없음</small>}</div>
                <div className={d}>{R.breadth_pct != null && `breadth 상승 ${R.breadth_pct}% · `}S/A {R.leader_count ?? 0}종목{!halted && R.reasons[0] ? ` · ${R.reasons[0]}` : ''}</div>
            </section>
            <section className={tile()}>
                <div className={k}>오늘 이벤트</div>
                <div className={v}><span className="text-white">{data.events.items.length}</span><small className="text-[12px] font-semibold text-gray-400">건</small></div>
                <div className={d}>{counts.length ? counts.map(([t, n]) => <span key={t} className={`rounded px-1.5 text-[11px] font-bold ${eventChip(t).cls}`}>{eventChip(t).label} {n}</span>) : '아직 없음'}</div>
            </section>
            <section className={tile()}>
                <div className={k}>발송</div>
                <div className={v}><span className="text-white">{data.system.briefs_delivered_today}</span><small className="text-[12px] font-semibold text-gray-400">/ {data.system.briefs_today} 브리핑</small></div>
                <div className={d}>{data.system.delivery.mode === 'direct-dm' ? '@bitman75 DM' : '개인봇'}{!data.system.delivery.enabled && <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-bold text-amber-300">dry-run</span>}</div>
            </section>
        </div>
    );
}

function SystemCard({ data }: { data: ClawOverview }) {
    const [open, setOpen] = useState(false);
    const s = data.system;
    const rows: [string, string][] = [
        ['하트비트', `${fmtAge(data.loop.heartbeat_age_s)} 전`], ['소스', `${data.loop.source ?? '-'} · ${fmtAge(data.loop.source_age_s)}`],
        ['오늘 스냅샷', s.snapshots_today.toLocaleString('ko-KR')], ['오늘 KIS 직접호출', String(s.kis_calls_today)],
        ['DB', `${(s.db_bytes / 1024).toFixed(0)} KB`], ['DROP 확정', `${s.drop_confirm_ticks} 틱`],
        ['발송 경로', `${s.delivery.mode} · ${s.delivery.token_key}`],
        ['킬스위치', Object.entries(s.kill_switches).map(([k, v]) => `${k.replace('CLAW_', '').replace('_ENABLED', '')} ${v ? 'on' : 'off'}`).join(' · ')],
    ];
    return (
        <section className="rounded-2xl border border-white/[0.06] bg-[#13151f] p-5 lg:col-span-4">
            <button type="button" onClick={() => setOpen(v => !v)} aria-expanded={open} className="flex w-full items-center justify-between text-[12px] font-bold text-gray-500 hover:text-gray-300">
                <span><i className="fas fa-microchip mr-2 text-[10px]" />시스템</span>
                <i className={`fas fa-chevron-${open ? 'up' : 'down'} text-[10px]`} />
            </button>
            {open && (
                <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12.5px]">
                    {rows.map(([a, b]) => <Fragment2 key={a} a={a} b={b} />)}
                    {Object.keys(data.errors).length > 0 && <Fragment2 a="오류" b={Object.entries(data.errors).map(([k, v]) => `${k}: ${v}`).join(' · ')} />}
                </dl>
            )}
        </section>
    );
}

function Fragment2({ a, b }: { a: string; b: string }) {
    return (<><dt className="text-gray-500">{a}</dt><dd className="m-0 text-right font-mono text-[12px] tabular-nums text-gray-300">{b}</dd></>);
}

function Skeleton() {
    return (
        <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">{[0, 1, 2, 3].map(i => <div key={i} className="h-[92px] animate-pulse rounded-2xl border border-white/[0.06] bg-[#13151f]" />)}</div>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
                <div className="h-72 animate-pulse rounded-2xl border border-white/[0.06] bg-[#13151f] lg:col-span-7" />
                <div className="h-72 animate-pulse rounded-2xl border border-white/[0.06] bg-[#13151f] lg:col-span-5" />
            </div>
        </div>
    );
}
