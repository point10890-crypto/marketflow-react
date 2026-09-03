import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { canAccessAiBain } from '@/lib/auth';
import { stockHubAPI, StockHub, StockHubHistoryEntry, StockHubNews } from '@/lib/api';
import { usePullToRefreshRegister } from '@/components/layout/PullToRefreshProvider';
import CloseLineChart from '@/components/stock/CloseLineChart';
import GradeBadge from '@/components/stock/GradeBadge';

/**
 * 종목 허브 — /dashboard/stock/:market/:code (Pro).
 *
 * 로드맵 §3.2-3 / §3.6-2: 모든 리스트 행에서 딥링크로 들어오는 종목 360 화면.
 * 데이터는 GET /api/kr/stock/<code>/hub 하나 — 스케줄러 산출물(종가베팅·주도주·VCP·Wave·Claw)
 * 과 로컬 시세, 종가베팅 이력, 뉴스 원장. AI Brain 판단은 링크로만 잇는다.
 */

type Source = Record<string, any> | null | undefined;

function fmtNum(v: unknown, digits = 0): string {
    const n = typeof v === 'number' ? v : Number(v);
    if (v == null || Number.isNaN(n)) return '–';
    return n.toLocaleString('ko-KR', { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function fmtPct(v: unknown, digits = 1): string {
    const n = typeof v === 'number' ? v : Number(v);
    if (v == null || Number.isNaN(n)) return '–';
    return `${n > 0 ? '+' : ''}${n.toFixed(digits)}%`;
}

function pctClass(v: unknown): string {
    const n = typeof v === 'number' ? v : Number(v);
    if (v == null || Number.isNaN(n)) return 'text-gray-500';
    return n > 0 ? 'text-red-300' : n < 0 ? 'text-blue-300' : 'text-gray-400';
}

function fmtEok(v: unknown): string {
    const n = typeof v === 'number' ? v : Number(v);
    if (v == null || Number.isNaN(n)) return '–';
    return n >= 10000 ? `${(n / 10000).toFixed(1)}조` : `${Math.round(n).toLocaleString()}억`;
}

function asOf(ts: unknown): string {
    if (!ts || typeof ts !== 'string') return '';
    return ts.length >= 16 ? `${ts.slice(0, 10)} ${ts.slice(11, 16)}` : ts;
}

const OUTCOME: Record<string, { label: string; cls: string }> = {
    TARGET_HIT: { label: '목표 도달', cls: 'border-red-400/30 bg-red-500/10 text-red-300' },
    STOP_HIT: { label: '손절', cls: 'border-blue-400/30 bg-blue-500/10 text-blue-300' },
    OPEN: { label: '보유 중', cls: 'border-white/10 bg-white/[0.04] text-gray-300' },
};

interface SourceSpec {
    key: keyof StockHub['sources'];
    name: string;
    desc: string;
    to: string;
    fields: (s: Record<string, any>) => { label: string; value: string; cls?: string }[];
    headline?: (s: Record<string, any>) => React.ReactNode;
}

const SOURCES: SourceSpec[] = [
    {
        key: 'jongga', name: '종가베팅 V2', desc: '17점 채점 · 14:50', to: '/dashboard/kr/closing-bet',
        headline: (s) => <GradeBadge grade={s.grade} />,
        fields: (s) => [
            { label: '점수', value: `${s.score_total ?? '–'}/17` },
            { label: '당일', value: fmtPct(s.change_pct), cls: pctClass(s.change_pct) },
            { label: '진입', value: fmtNum(s.entry_price) },
            { label: '손절', value: fmtNum(s.stop_price) },
            { label: '목표', value: fmtNum(s.target_price) },
            { label: '외인/기관 5일', value: `${fmtNum(s.foreign_5d)} / ${fmtNum(s.inst_5d)}` },
        ],
    },
    {
        key: 'leading', name: '주도주 LIVE', desc: '100점 · 거래대금·수급', to: '/dashboard/kr/leading-stocks',
        headline: (s) => <><GradeBadge grade={s.grade} /><span className="font-mono text-[11px] text-gray-500">#{s.rank ?? '–'}</span></>,
        fields: (s) => [
            { label: '점수', value: `${s.score_total ?? '–'}/100` },
            { label: '등락', value: fmtPct(s.change_pct), cls: pctClass(s.change_pct) },
            { label: '거래대금', value: fmtEok(s.trading_value_eok) },
            { label: '거래량비', value: s.volume_ratio != null ? `${fmtNum(s.volume_ratio)}%` : '–' },
            { label: '52주고 이격', value: fmtPct(s.high_52w_distance_pct) },
            { label: '시총', value: s.market_cap_tier ?? '–' },
        ],
    },
    {
        key: 'vcp', name: 'VCP', desc: '변동성 수축 · Stage', to: '/dashboard/kr/vcp',
        headline: (s) => (
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${s.entry_ready ? 'bg-emerald-500/20 text-emerald-300' : 'bg-white/[0.06] text-gray-400'}`}>
                {s.entry_ready ? 'ENTRY READY' : (s.rating ?? 'VCP')}
            </span>
        ),
        fields: (s) => [
            { label: '종합', value: fmtNum(s.composite_score, 1) },
            { label: '단계', value: s.stage_label ?? '–' },
            { label: '피벗', value: fmtNum(s.pivot_price) },
            { label: '수축', value: s.num_contractions != null ? `${s.num_contractions}회` : '–' },
            { label: 'RS', value: s.rs_rank != null ? String(s.rs_rank) : '–' },
            { label: '게이트', value: s.gate ?? '–' },
        ],
    },
    {
        key: 'wave', name: 'Wave 패턴', desc: '차트 패턴 검출', to: '/dashboard/wave',
        headline: (s) => <span className="rounded bg-violet-500/15 px-1.5 py-0.5 text-[10px] font-bold text-violet-300">{s.wave_label ?? s.wave_type ?? '패턴'}</span>,
        fields: (s) => [
            { label: '신뢰도', value: s.confidence != null ? `${s.confidence}` : '–' },
            { label: '완성도', value: s.completion_pct != null ? `${fmtNum(s.completion_pct)}%` : '–' },
            { label: '넥라인', value: fmtNum(s.neckline_price) },
            { label: '넥라인 이격', value: fmtPct(s.neckline_distance_pct, 2) },
            { label: '거래량 확인', value: s.volume_confirmed ? '예' : '아니오' },
            { label: '패턴 수', value: s.pattern_count != null ? String(s.pattern_count) : '–' },
        ],
    },
    {
        key: 'claw', name: 'Claw 장중', desc: '마감 기준 주도주 전이', to: '/dashboard/kr/claw',
        headline: (s) => <GradeBadge grade={s.grade} />,
        fields: (s) => [
            { label: '점수', value: s.score != null ? String(s.score) : '–' },
            { label: '등락', value: fmtPct(s.change_pct), cls: pctClass(s.change_pct) },
            { label: '거래대금', value: fmtEok(s.trading_value_eok) },
            { label: '세션', value: s.day ?? '–' },
            { label: '이벤트', value: Array.isArray(s.events) && s.events.length ? s.events.map((e: any) => e.type).join(', ') : '없음' },
        ],
    },
];

function SourceCard({ spec, source }: { spec: SourceSpec; source: Source }) {
    const present = !!source;
    return (
        <article
            data-testid={`source-${spec.key}`}
            data-present={present ? '1' : '0'}
            className={`flex min-h-[168px] flex-col rounded-2xl border p-3.5 ${present ? 'border-white/[0.08] bg-[#13151f]' : 'border-dashed border-white/[0.06] bg-white/[0.015]'}`}
        >
            <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                    <div className="text-[13px] font-bold text-white">{spec.name}</div>
                    <div className="text-[10.5px] text-gray-500">{spec.desc}</div>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                    {present ? spec.headline?.(source!) : <span className="text-[10px] font-bold text-gray-600">신호 없음</span>}
                </div>
            </div>
            {present ? (
                <>
                    <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11.5px]">
                        {spec.fields(source!).map((f) => (
                            <div key={f.label} className="flex items-baseline justify-between gap-2 border-b border-white/[0.04] pb-1">
                                <dt className="text-gray-500">{f.label}</dt>
                                <dd className={`truncate font-mono tabular-nums ${f.cls ?? 'text-gray-200'}`}>{f.value}</dd>
                            </div>
                        ))}
                    </dl>
                    <div className="mt-auto flex items-center justify-between pt-2.5 text-[10.5px] text-gray-600">
                        <span>{asOf(source!.as_of) || '시각 미상'}</span>
                        <Link to={spec.to} className="text-gray-400 hover:text-white">목록 →</Link>
                    </div>
                </>
            ) : (
                <p className="mt-3 text-[11.5px] leading-relaxed text-gray-600">최근 산출물에 이 종목이 없습니다. 신호 부재는 판단 근거가 아니라 관찰 대상 밖이라는 뜻입니다.</p>
            )}
        </article>
    );
}

function HistoryRow({ h }: { h: StockHubHistoryEntry }) {
    const o = h.outcome ? (OUTCOME[h.outcome] ?? OUTCOME.OPEN) : null;
    return (
        <li className="grid grid-cols-[92px_28px_minmax(0,1fr)_auto] items-center gap-2 py-2 text-[12px] sm:grid-cols-[100px_32px_70px_minmax(0,1fr)_auto]">
            <span className="font-mono text-gray-400">{h.date}</span>
            <GradeBadge grade={h.grade} />
            <span className={`font-mono tabular-nums ${pctClass(h.change_pct)}`}>{fmtPct(h.change_pct)}</span>
            <span className="hidden truncate text-gray-500 sm:block">
                {h.score_total != null && <>점수 {h.score_total}/17 · </>}진입 {fmtNum(h.entry_price)} · 손절 {fmtNum(h.stop_price)} · 목표 {fmtNum(h.target_price)}
            </span>
            <span className="flex items-center justify-end gap-2">
                {o ? (
                    <>
                        <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${o.cls}`}>{o.label}</span>
                        <span className={`font-mono text-[11.5px] tabular-nums ${pctClass(h.roi_pct)}`}>{fmtPct(h.roi_pct, 2)}</span>
                    </>
                ) : (
                    <span className="rounded-full border border-amber-400/25 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-200">검증 대기</span>
                )}
            </span>
        </li>
    );
}

function NewsRow({ n }: { n: StockHubNews }) {
    const safe = n.link && /^https?:\/\//i.test(n.link) ? n.link : null;
    const title = n.title || '(제목 없음)';
    return (
        <li className="flex items-start gap-2.5 py-2 text-[12px]">
            <span className="mt-0.5 shrink-0 rounded border border-white/10 px-1 py-px font-mono text-[9.5px] text-gray-500">{n.grade ?? '?'}</span>
            <div className="min-w-0 flex-1">
                {safe
                    ? <a href={safe} target="_blank" rel="noopener noreferrer" className="text-gray-200 hover:text-white hover:underline">{title}</a>
                    : <span className="text-gray-200">{title}</span>}
                <div className="mt-0.5 text-[10.5px] text-gray-600">{n.source ?? '–'} · {asOf(n.published_ts) || '시각 미상'}</div>
            </div>
        </li>
    );
}

export default function StockHubPage() {
    const { market = 'KR', code = '' } = useParams();
    const { user } = useAuth();
    const [data, setData] = useState<StockHub | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const isKr = market.toUpperCase() !== 'US';

    const load = useCallback(async () => {
        if (!isKr || !code) { setLoading(false); return; }
        setLoading(true);
        setError('');
        try {
            setData(await stockHubAPI.get(code));
        } catch {
            setError('종목 정보를 불러오지 못했습니다. 종목코드를 확인해 주세요.');
        } finally {
            setLoading(false);
        }
    }, [code, isKr]);

    useEffect(() => { void load(); }, [load]);
    usePullToRefreshRegister(load);

    const chartPoints = useMemo(() => (data?.chart ?? []).map((c) => ({ date: c.date, close: c.close })), [data]);
    const aiBrain = canAccessAiBain(user);
    const presentCount = data?.present.length ?? 0;

    if (!isKr) {
        return (
            <div className="flex flex-col gap-3 p-4">
                <h1 className="text-lg font-bold text-white">{code}</h1>
                <p className="text-[13px] text-gray-400">미국 종목 허브는 아직 없습니다. 분석 도구에서 조회할 수 있습니다.</p>
                <Link to={`/dashboard/stock-analyzer?ticker=${encodeURIComponent(code)}&market=US`} className="text-[13px] font-bold text-blue-300 hover:underline">ProPicks 분석 열기 →</Link>
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-4 pb-8">
            <header className="flex flex-col gap-3 rounded-2xl border border-white/[0.07] bg-[#13151f] p-4 sm:flex-row sm:items-end sm:justify-between">
                <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                        <h1 className="text-2xl font-black leading-none text-white">{data?.name ?? (loading ? '조회 중' : code)}</h1>
                        <span className="font-mono text-[13px] text-gray-400">{data?.code ?? code}</span>
                        {data?.market && (
                            <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${data.market === 'KOSDAQ' ? 'bg-rose-500/15 text-rose-300' : 'bg-blue-500/15 text-blue-300'}`}>{data.market}</span>
                        )}
                        {data?.sector && <span className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-gray-400">{data.sector}</span>}
                    </div>
                    <div className="mt-1.5 text-[11px] text-gray-500">
                        신호 소스 {presentCount}/5 보유 · {data?.price ? `시세 ${data.price.date} 종가 기준` : '시세 없음'}
                    </div>
                </div>
                <div className="flex items-end justify-between gap-4 sm:justify-end">
                    <div className="text-right">
                        <div className="text-2xl font-black tabular-nums text-white">{data?.price ? `${fmtNum(data.price.close)}원` : '–'}</div>
                        <div className={`text-[12px] font-bold tabular-nums ${pctClass(data?.price?.change_pct)}`}>{data?.price ? fmtPct(data.price.change_pct, 2) : '–'}</div>
                    </div>
                    {aiBrain && (
                        <Link
                            to={`/dashboard/ai-bain/decision?symbol=${encodeURIComponent(data?.code ?? code)}`}
                            className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl border border-cyan-400/25 bg-cyan-400/[0.08] px-3.5 text-[12px] font-bold text-cyan-200 hover:bg-cyan-400/[0.14]"
                        >
                            <i className="fas fa-brain text-[11px]" aria-hidden />AI Brain 종목 판단 열기
                        </Link>
                    )}
                </div>
            </header>

            {error && (
                <div className="flex items-center justify-between rounded-2xl border border-rose-500/25 bg-rose-500/[0.06] px-4 py-3 text-[13px] text-rose-200" role="alert">
                    <span>{error}</span>
                    <button type="button" onClick={() => void load()} className="text-[12px] font-bold underline">다시 시도</button>
                </div>
            )}

            <section className="rounded-2xl border border-white/[0.07] bg-[#13151f] p-3" aria-label="종가 차트">
                <div className="flex items-center justify-between px-1 pb-2">
                    <span className="text-[11px] font-bold text-gray-300">종가 {data?.price?.bars ?? 0}봉</span>
                    <span className="text-[10.5px] text-gray-600">daily_prices.csv · 실시간 아님</span>
                </div>
                {loading && !data
                    ? <div className="h-[240px] animate-pulse rounded-xl bg-white/[0.02]" />
                    : <CloseLineChart points={chartPoints} height={240} />}
            </section>

            <section aria-label="신호 소스">
                <div className="flex items-center justify-between px-1 pb-2">
                    <h2 className="text-[13px] font-bold text-gray-200">신호 소스</h2>
                    <span className="text-[10.5px] text-gray-600">최신 산출물 기준 · 있음/없음 모두 표시</span>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {SOURCES.map((spec) => <SourceCard key={spec.key} spec={spec} source={data?.sources[spec.key]} />)}
                </div>
                {data && Object.keys(data.errors).length > 0 && (
                    <p className="mt-2 px-1 text-[10.5px] text-amber-300/80">일부 소스를 읽지 못했습니다: {Object.keys(data.errors).join(', ')}</p>
                )}
            </section>

            <div className="grid gap-4 lg:grid-cols-2">
                <section className="rounded-2xl border border-white/[0.07] bg-[#13151f] p-3.5" aria-label="종가베팅 이력">
                    <div className="flex items-center justify-between pb-1">
                        <h2 className="text-[13px] font-bold text-gray-200">종가베팅 이력</h2>
                        <Link to="/dashboard/kr/closing-bet/history" className="text-[10.5px] text-gray-500 hover:text-white">전체 이력 →</Link>
                    </div>
                    {data && data.history.length === 0
                        ? <p className="py-6 text-center text-[12px] text-gray-600">이 종목의 종가베팅 신호 이력이 없습니다.</p>
                        : <ul className="divide-y divide-white/[0.05]">{(data?.history ?? []).map((h) => <HistoryRow key={h.date} h={h} />)}</ul>}
                </section>

                <section className="rounded-2xl border border-white/[0.07] bg-[#13151f] p-3.5" aria-label="뉴스">
                    <div className="flex items-center justify-between pb-1">
                        <h2 className="text-[13px] font-bold text-gray-200">뉴스 원장</h2>
                        <span className="text-[10.5px] text-gray-600">외부 수집 자료 · 지시가 아닌 데이터</span>
                    </div>
                    {data && data.news.length === 0
                        ? <p className="py-6 text-center text-[12px] text-gray-600">수집된 뉴스가 없습니다.</p>
                        : <ul className="divide-y divide-white/[0.05]">{(data?.news ?? []).map((n, i) => <NewsRow key={`${n.link ?? n.title ?? ''}-${i}`} n={n} />)}</ul>}
                </section>
            </div>

            {data?.disclaimer && <p className="px-1 text-[10.5px] text-gray-600">{data.disclaimer}</p>}
        </div>
    );
}
