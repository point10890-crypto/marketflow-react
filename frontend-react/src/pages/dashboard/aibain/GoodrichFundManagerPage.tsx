import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { fetchAuthAPI, postAuthAPI } from '@/lib/api';
import AiBrainServiceTabs from '@/components/aibain/AiBrainServiceTabs';
import GoodrichTop3Charts from '@/components/aibain/GoodrichTop3Charts';

interface GoodrichPick {
    rank?: number;
    symbol: string;
    name: string;
    score?: number;
    entry_price?: number;
    current_price?: number;
    target_price?: number;
    stop_price?: number;
    status?: string;
    rationale?: string[];
    thesis?: string;
    risk?: string;
    observed_at?: string;
}

interface GoodrichSnapshot {
    mode?: string;
    status?: string;
    headline?: string;
    disclosure?: string;
    ai?: {
        provider?: string;
        model?: string;
        status?: string;
        market_summary?: string;
    };
    picks: GoodrichPick[];
    alerts?: Array<Record<string, unknown>>;
    integration?: {
        fetched_at?: string;
        universe?: string;
        universe_size?: number;
        candidate_count?: number;
        market_status?: string;
        ranking_owner?: string;
        ai_role?: string;
        ordering_enabled?: boolean;
    };
}

interface GoodrichHistoryItem {
    cycle_id: string;
    detected_at?: string;
    status?: string;
    picks: GoodrichPick[];
}

interface GoodrichHistory {
    items: GoodrichHistoryItem[];
    limit?: number;
    offset?: number;
}

interface GoodrichPerformance {
    window_days: number;
    generated_at?: string;
    total_picks: number;
    active_count: number;
    evaluated_count: number;
    target_hits: number;
    stop_hits: number;
    hit_rate_pct?: number | null;
    average_return_pct?: number | null;
}

const ENDPOINT = '/api/admin/mirofish/goodrich/fund-manager';

export default function GoodrichFundManagerPage() {
    const { token } = useAuth();
    const [data, setData] = useState<GoodrichSnapshot | null>(null);
    const [history, setHistory] = useState<GoodrichHistory | null>(null);
    const [performance, setPerformance] = useState<GoodrichPerformance | null>(null);
    const [loading, setLoading] = useState(true);
    const [researching, setResearching] = useState(false);
    const [error, setError] = useState('');

    const load = useCallback(async () => {
        setLoading(true);
        setError('');
        try {
            const [snapshot, historyResult, performanceResult] = await Promise.all([
                fetchAuthAPI<GoodrichSnapshot>(ENDPOINT, token ?? undefined, 20000),
                fetchAuthAPI<GoodrichHistory>(`${ENDPOINT}/history?limit=10&offset=0`, token ?? undefined, 20000),
                fetchAuthAPI<GoodrichPerformance>(`${ENDPOINT}/performance?window_days=30`, token ?? undefined, 20000),
            ]);
            setData(snapshot);
            setHistory(historyResult);
            setPerformance(performanceResult);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Goodrich 데이터를 불러오지 못했습니다.');
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => { void load(); }, [load]);

    const runResearch = async () => {
        if (researching) return;
        setResearching(true);
        setError('');
        try {
            setData(await postAuthAPI<GoodrichSnapshot>(`${ENDPOINT}/research`, {}, token ?? undefined, 100000));
        } catch (err) {
            setError(err instanceof Error ? err.message : '시장 재분석을 완료하지 못했습니다.');
        } finally {
            setResearching(false);
        }
    };

    return (
        <div className="min-h-screen bg-[#09090b] p-4 text-white sm:p-6 lg:p-8">
            <div className="mx-auto max-w-6xl space-y-5">
                <AiBrainServiceTabs active="goodrich" />
                <nav className="grid grid-cols-2 gap-3" aria-label="Goodrich 분석 엔드포인트">
                    <a
                        href="#goodrich-history"
                        className="flex min-h-20 items-center gap-3 rounded-2xl border border-cyan-400/25 bg-cyan-400/[0.08] px-4 py-3 transition hover:border-cyan-300/50 hover:bg-cyan-400/[0.12] sm:min-h-24 sm:px-6"
                    >
                        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-cyan-300/10 text-cyan-300">
                            <i className="fas fa-clock-rotate-left" />
                        </span>
                        <span>
                            <strong className="block text-base font-black sm:text-xl">검출 이력</strong>
                            <small className="mt-1 block text-[10px] text-cyan-100/60 sm:text-xs">TOP 3 선정 주기와 종목 변화</small>
                        </span>
                    </a>
                    <a
                        href="#goodrich-performance"
                        className="flex min-h-20 items-center gap-3 rounded-2xl border border-amber-400/25 bg-amber-400/[0.08] px-4 py-3 transition hover:border-amber-300/50 hover:bg-amber-400/[0.12] sm:min-h-24 sm:px-6"
                    >
                        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-amber-300/10 text-amber-300">
                            <i className="fas fa-chart-line" />
                        </span>
                        <span>
                            <strong className="block text-base font-black sm:text-xl">성과 검증</strong>
                            <small className="mt-1 block text-[10px] text-amber-100/60 sm:text-xs">목표가·손절가 달성 기록</small>
                        </span>
                    </a>
                </nav>
                <header className="rounded-2xl border border-emerald-400/20 bg-gradient-to-br from-emerald-500/[0.08] via-[#12171a] to-[#111318] p-5 sm:p-7">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                        <div>
                            <Link to="/dashboard/ai-bain" className="text-xs font-bold text-cyan-300 hover:text-cyan-200">
                                <i className="fas fa-arrow-left mr-2" />AI Brain
                            </Link>
                            <div className="mt-4 flex items-center gap-3">
                                <span className="grid h-12 w-12 place-items-center rounded-2xl bg-emerald-400/10 text-emerald-300">
                                    <i className="fas fa-ranking-star text-xl" />
                                </span>
                                <div>
                                    <h1 className="text-2xl font-black tracking-tight sm:text-3xl">Goodrich AI 펀드매니저</h1>
                                    <p className="mt-1 text-sm text-slate-400">KIS 실데이터 · 결정론적 TOP 3 · OpenAI 검증 설명</p>
                                </div>
                            </div>
                        </div>
                        <button
                            type="button"
                            onClick={runResearch}
                            disabled={researching || loading}
                            className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-emerald-400 px-4 text-sm font-black text-slate-950 transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                            <i className={`fas ${researching ? 'fa-spinner fa-spin' : 'fa-rotate'}`} />
                            {researching ? 'KIS·AI 분석 중' : '시장 다시 분석'}
                        </button>
                    </div>
                    <div className="mt-5 grid gap-2 text-xs sm:grid-cols-3">
                        <Meta label="검출 범위" value={`KIS 주도주 ${data?.integration?.universe_size ?? 0}종목`} />
                        <Meta label="순위 결정" value="시장 검출 + 정량 규칙" />
                        <Meta label="주문 기능" value="비활성 · 정보 제공 전용" />
                    </div>
                </header>

                {error && (
                    <div className="rounded-2xl border border-red-500/25 bg-red-500/[0.06] p-4 text-sm text-red-200">
                        <i className="fas fa-triangle-exclamation mr-2" />{error}
                        <button type="button" onClick={load} className="ml-3 font-black underline">다시 불러오기</button>
                    </div>
                )}

                {loading && (
                    <div className="grid min-h-64 place-items-center rounded-2xl border border-white/[0.07] bg-[#13151b] text-slate-400">
                        <span><i className="fas fa-spinner fa-spin mr-2 text-emerald-300" />현재 TOP 3를 확인하는 중입니다</span>
                    </div>
                )}

                {!loading && data && (
                    <>
                        <section className="rounded-2xl border border-white/[0.07] bg-[#13151b] p-5">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                                <div>
                                    <div className="text-[10px] font-black uppercase tracking-[0.2em] text-emerald-300">Market brief</div>
                                    <h2 className="mt-1 text-lg font-black">{data.headline || '오늘의 TOP 3'}</h2>
                                </div>
                                <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[11px] text-slate-400">
                                    {formatTime(data.integration?.fetched_at)}
                                </span>
                            </div>
                            <p className="mt-4 text-sm leading-6 text-slate-300">
                                {data.ai?.market_summary || '시장 요약이 아직 생성되지 않았습니다.'}
                            </p>
                        </section>

                        <section className="grid gap-4 lg:grid-cols-3">
                            {data.picks.map((pick, index) => <PickCard key={pick.symbol} pick={pick} fallbackRank={index + 1} />)}
                        </section>

                        <GoodrichTop3Charts picks={data.picks} />

                        <section id="goodrich-performance" className="scroll-mt-24 rounded-2xl border border-amber-400/20 bg-amber-400/[0.04] p-5 sm:p-6">
                            <div className="flex flex-wrap items-end justify-between gap-2">
                                <div>
                                    <div className="text-[10px] font-black uppercase tracking-[0.2em] text-amber-300">Performance endpoint</div>
                                    <h2 className="mt-1 text-xl font-black">성과 검증</h2>
                                </div>
                                <span className="text-xs text-slate-500">최근 {performance?.window_days ?? 30}일</span>
                            </div>
                            <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
                                <Metric label="누적 후보" value={performance?.total_picks ?? 0} />
                                <Metric label="모니터링" value={performance?.active_count ?? 0} />
                                <Metric label="평가 완료" value={performance?.evaluated_count ?? 0} />
                                <Metric label="목표 달성" value={performance?.target_hits ?? 0} tone="text-emerald-300" />
                                <Metric label="손절 도달" value={performance?.stop_hits ?? 0} tone="text-rose-300" />
                                <Metric
                                    label="적중률"
                                    value={performance?.hit_rate_pct == null ? '누적 중' : `${performance.hit_rate_pct}%`}
                                    tone="text-amber-200"
                                />
                            </div>
                            <p className="mt-4 text-xs text-slate-500">
                                30분 모니터링 시점의 KIS 현재가가 목표가 또는 손절가에 도달한 경우만 평가 완료로 기록합니다.
                            </p>
                        </section>

                        <section id="goodrich-history" className="scroll-mt-24 rounded-2xl border border-cyan-400/20 bg-cyan-400/[0.04] p-5 sm:p-6">
                            <div className="flex flex-wrap items-end justify-between gap-2">
                                <div>
                                    <div className="text-[10px] font-black uppercase tracking-[0.2em] text-cyan-300">Detection history endpoint</div>
                                    <h2 className="mt-1 text-xl font-black">검출 이력</h2>
                                </div>
                                <span className="text-xs text-slate-500">최근 {history?.items?.length ?? 0}회</span>
                            </div>
                            <div className="mt-5 space-y-3">
                                {(history?.items ?? []).map((item) => (
                                    <article key={item.cycle_id} className="rounded-xl border border-white/[0.07] bg-black/20 p-4">
                                        <div className="flex flex-wrap items-center justify-between gap-2">
                                            <time className="text-xs font-bold text-cyan-100">{formatTime(item.detected_at)}</time>
                                            <span className="font-mono text-[10px] text-slate-600">{item.cycle_id.slice(0, 8)}</span>
                                        </div>
                                        <div className="mt-3 grid gap-2 sm:grid-cols-3">
                                            {item.picks.map((pick) => (
                                                <div key={`${item.cycle_id}-${pick.symbol}`} className="rounded-lg bg-white/[0.035] px-3 py-2">
                                                    <div className="text-xs font-black text-white">TOP {pick.rank} · {pick.name}</div>
                                                    <div className="mt-1 text-[10px] text-slate-500">{pick.symbol} · {pick.status ?? 'monitoring'}</div>
                                                </div>
                                            ))}
                                        </div>
                                    </article>
                                ))}
                                {(history?.items?.length ?? 0) === 0 && (
                                    <div className="rounded-xl border border-dashed border-white/10 p-6 text-center text-sm text-slate-500">
                                        아직 저장된 검출 이력이 없습니다.
                                    </div>
                                )}
                            </div>
                        </section>

                        <footer className="rounded-2xl border border-amber-400/15 bg-amber-400/[0.04] p-4 text-xs leading-5 text-slate-400">
                            <strong className="text-amber-200">범위와 책임:</strong> KIS 거래대금·등락률·거래량 급증 순위에서 실제 시장 주도주 후보를 검출한 뒤 TOP 3를 선정합니다.
                            현재가·목표가·손절가는 KIS 데이터와 결정론적 규칙으로 계산하며 OpenAI는 종목이나 가격을 만들지 않고 검증된 수치의 근거와 위험만 설명합니다.
                            {data.disclosure && <span className="ml-1">{data.disclosure}</span>}
                        </footer>
                    </>
                )}
            </div>
        </div>
    );
}

function Meta({ label, value }: { label: string; value: string }) {
    return <div className="rounded-xl border border-white/[0.07] bg-black/20 px-3 py-2"><span className="text-slate-500">{label}</span><span className="ml-2 font-bold text-slate-200">{value}</span></div>;
}

function Metric({ label, value, tone = 'text-white' }: { label: string; value: string | number; tone?: string }) {
    return (
        <div className="rounded-xl border border-white/[0.06] bg-black/20 p-3">
            <div className="text-[10px] text-slate-500">{label}</div>
            <div className={`mt-1 text-lg font-black ${tone}`}>{value}</div>
        </div>
    );
}

function PickCard({ pick, fallbackRank }: { pick: GoodrichPick; fallbackRank: number }) {
    const current = pick.current_price ?? pick.entry_price;
    return (
        <article className="rounded-2xl border border-white/[0.08] bg-[#13151b] p-5">
            <div className="flex items-start justify-between gap-3">
                <div>
                    <span className="text-xs font-black text-emerald-300">TOP {pick.rank ?? fallbackRank}</span>
                    <h3 className="mt-1 text-xl font-black">{pick.name}</h3>
                    <p className="text-xs text-slate-500">{pick.symbol}</p>
                </div>
                {pick.score != null && <span className="rounded-xl bg-emerald-400/10 px-3 py-2 text-sm font-black text-emerald-200">{pick.score.toFixed(1)}</span>}
            </div>
            <div className="mt-5 grid grid-cols-2 gap-2">
                <Price label="현재가" value={current} />
                <Price label="진입 기준" value={pick.entry_price} />
                <Price label="목표가" value={pick.target_price} tone="text-emerald-300" />
                <Price label="손절가" value={pick.stop_price} tone="text-rose-300" />
            </div>
            <div className="mt-4 border-t border-white/[0.06] pt-4 text-xs leading-5 text-slate-400">
                <p><strong className="text-slate-200">강점</strong> {pick.thesis || pick.rationale?.join(' · ') || '검증 설명 대기'}</p>
                <p className="mt-2"><strong className="text-slate-200">위험</strong> {pick.risk || '핵심 위험 설명 대기'}</p>
            </div>
            <div className="mt-4 flex items-center justify-between text-[10px] text-slate-600">
                <span>{pick.status || 'monitoring'}</span>
                <span>{formatTime(pick.observed_at)}</span>
            </div>
        </article>
    );
}

function Price({ label, value, tone = 'text-white' }: { label: string; value?: number; tone?: string }) {
    return <div className="rounded-xl bg-black/20 p-3"><div className="text-[10px] text-slate-500">{label}</div><div className={`mt-1 text-sm font-black ${tone}`}>{value == null ? '—' : `${value.toLocaleString('ko-KR')}원`}</div></div>;
}

function formatTime(value?: string) {
    if (!value) return '시각 미확인';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false });
}
