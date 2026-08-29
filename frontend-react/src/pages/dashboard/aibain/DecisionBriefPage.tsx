/**
 * 종목 판단 — AI Brain 전용 페이지.
 *
 * GET /api/kr/decision/<symbol> 를 조회해 시스템이 보유한 독립 근거 7종을 한 종목
 * 기준으로 나란히 비교한다. 어디서 일치하고 어디서 갈리는지, 무엇을 모르는지,
 * 신뢰를 어디까지 둘 수 있는지를 보여주는 것이 이 화면의 전부다.
 * 매수/매도를 지시하지 않는다 — 상태는 watch | neutral | avoid_data_gap 뿐이다.
 */
import { FormEvent, useCallback, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { fetchAuthAPI } from '@/lib/api';
import AiBrainServiceTabs from '@/components/aibain/AiBrainServiceTabs';

const ENDPOINT = '/api/kr/decision';

type Stance = 'positive' | 'negative' | 'neutral' | 'absent' | string;

interface Signal {
    source: string;
    stance: Stance;
    grade: string;
    as_of: string | null;
    detail: Record<string, unknown>;
}

interface Agreement {
    positive: number;
    negative: number;
    neutral: number;
    absent: number;
    active: number;
    ratio: number | null;
    verdict: 'aligned' | 'conflicted' | 'mixed' | 'insufficient' | string;
    direction: string | null;
}

interface DecisionBrief {
    schema_version: string;
    generated_at: string;
    symbol: string;
    name: string | null;
    status: 'watch' | 'neutral' | 'avoid_data_gap' | string;
    signals: Signal[];
    agreement: Agreement;
    strong_evidence: number;
    data_gaps: string[];
    invalidators: { type: string; cond: string; mode: string }[];
    confidence_cap: number;
    cap_reasons: string[];
    regime: { phase: string | null; gate_status: string | null; conflict: boolean };
    errors: Record<string, string>;
    disclaimer?: string;
}

const SOURCE_LABEL: Record<string, { name: string; desc: string }> = {
    claw: { name: '주도주 전이', desc: '장중 등급·이탈 감시' },
    jongga: { name: '종가베팅 V2', desc: '17점 채점 시그널' },
    scanner: { name: '알파 스캐너', desc: '알파·리스크·RS' },
    detection: { name: 'CIO 판정', desc: '워크플로우 TOP3' },
    tradingagents: { name: '딥검증', desc: '불/베어 토론 → 리스크' },
    paper: { name: '가상 원장', desc: '보유·청산 상태' },
    observation: { name: '관측 실측', desc: '과거 검출 성과' },
};

const STANCE_STYLE: Record<string, { label: string; cls: string; dot: string }> = {
    positive: { label: '긍정', cls: 'text-red-300', dot: 'bg-red-400' },
    negative: { label: '부정', cls: 'text-blue-300', dot: 'bg-blue-400' },
    neutral: { label: '중립', cls: 'text-gray-300', dot: 'bg-gray-500' },
    absent: { label: '없음', cls: 'text-gray-600', dot: 'bg-gray-700' },
};

const VERDICT_STYLE: Record<string, { label: string; cls: string; hint: string }> = {
    aligned: { label: '의견 일치', cls: 'border-emerald-400/30 bg-emerald-500/10 text-emerald-300', hint: '근거들이 같은 방향을 가리킵니다' },
    conflicted: { label: '의견 충돌', cls: 'border-amber-400/35 bg-amber-500/10 text-amber-300', hint: '근거가 서로 반대입니다 — 판단을 미루는 편이 안전합니다' },
    mixed: { label: '중립 혼재', cls: 'border-gray-500/30 bg-white/[0.04] text-gray-300', hint: '뚜렷한 방향이 없습니다' },
    insufficient: { label: '근거 부족', cls: 'border-gray-600/30 bg-white/[0.03] text-gray-500', hint: '판단할 근거 자체가 없습니다' },
};

const STATUS_STYLE: Record<string, { label: string; cls: string }> = {
    watch: { label: '관찰 대상', cls: 'border-teal-400/40 bg-teal-500/12 text-teal-200' },
    neutral: { label: '중립', cls: 'border-gray-500/30 bg-white/[0.04] text-gray-300' },
    avoid_data_gap: { label: '근거 미달', cls: 'border-amber-400/35 bg-amber-500/10 text-amber-300' },
};

function fmtTime(ts: string | null): string {
    if (!ts) return '-';
    return ts.slice(0, 16).replace('T', ' ');
}

function isDecisionBrief(v: unknown): v is DecisionBrief {
    const o = v as Partial<DecisionBrief> | null;
    return !!o && typeof o === 'object' && Array.isArray(o.signals) && !!o.agreement;
}

export default function DecisionBriefPage() {
    const { token } = useAuth();
    const [input, setInput] = useState('');
    const [brief, setBrief] = useState<DecisionBrief | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const lookup = useCallback(async (raw: string) => {
        const symbol = raw.trim();
        if (!symbol) return;
        setLoading(true);
        setError('');
        try {
            const res = await fetchAuthAPI<unknown>(`${ENDPOINT}/${encodeURIComponent(symbol)}`,
                token ?? undefined, 30000);
            if (isDecisionBrief(res)) {
                setBrief(res);
            } else {
                setBrief(null);
                setError('판단 브리프 형식이 올바르지 않습니다.');
            }
        } catch {
            setBrief(null);
            setError('조회에 실패했습니다. 종목 코드를 확인하고 다시 시도해 주세요.');
        } finally {
            setLoading(false);
        }
    }, [token]);

    const onSubmit = (e: FormEvent) => {
        e.preventDefault();
        void lookup(input);
    };

    return (
        <div className="min-h-full bg-[#09090b] p-4 text-white sm:p-6 lg:p-8">
            <div className="mx-auto max-w-4xl space-y-5">
                <AiBrainServiceTabs active="decision" />

                <header>
                    <h1 className="text-2xl font-black tracking-tight sm:text-3xl">종목 판단</h1>
                    <p className="mt-2 max-w-2xl text-sm text-gray-400">
                        시스템이 가진 독립 근거 7종을 한 종목 기준으로 나란히 놓고, 어디서 일치하고
                        어디서 갈리는지 보여줍니다. 매수·매도를 지시하지 않습니다.
                    </p>
                </header>

                <form onSubmit={onSubmit} className="flex gap-2">
                    <input
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        placeholder="종목 코드 (예: 005930)"
                        inputMode="numeric"
                        aria-label="종목 코드"
                        className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 font-mono text-[15px] text-white placeholder:text-gray-600 focus:border-teal-400/50 focus:outline-none"
                    />
                    <button
                        type="submit"
                        disabled={loading || !input.trim()}
                        className="shrink-0 rounded-xl border border-teal-400/30 bg-teal-500/15 px-5 py-3 text-sm font-bold text-teal-200 transition hover:bg-teal-500/25 disabled:opacity-40"
                    >
                        {loading ? '조회 중' : '판단 조회'}
                    </button>
                </form>

                {error && (
                    <div className="rounded-xl border border-amber-400/30 bg-amber-500/[0.07] px-4 py-3 text-sm text-amber-200">
                        {error}
                    </div>
                )}

                {!brief && !error && !loading && (
                    <div className="rounded-2xl border border-white/[0.06] bg-[#13151f] p-8 text-center">
                        <i className="fas fa-scale-balanced mb-3 text-2xl text-gray-600" />
                        <p className="text-sm text-gray-500">종목 코드를 입력하면 근거 대조 결과를 보여줍니다.</p>
                    </div>
                )}

                {brief && <BriefBody brief={brief} />}
            </div>
        </div>
    );
}

function BriefBody({ brief }: { brief: DecisionBrief }) {
    const verdict = VERDICT_STYLE[brief.agreement.verdict] ?? VERDICT_STYLE.mixed;
    const status = STATUS_STYLE[brief.status] ?? STATUS_STYLE.neutral;
    const capPct = Math.round((brief.confidence_cap ?? 0) * 100);

    return (
        <div className="space-y-4">
            {/* 요약 */}
            <section className="rounded-2xl border border-white/[0.07] bg-[#13151f] p-5">
                <div className="flex flex-wrap items-center gap-3">
                    <h2 className="text-xl font-bold">
                        {brief.name || '종목'}
                        <span className="ml-2 font-mono text-sm text-gray-500">{brief.symbol}</span>
                    </h2>
                    <span className={`rounded-full border px-3 py-1 text-[11px] font-bold ${status.cls}`}>
                        {status.label}
                    </span>
                    <span className={`rounded-full border px-3 py-1 text-[11px] font-bold ${verdict.cls}`}>
                        {verdict.label}
                    </span>
                </div>
                <p className="mt-2 text-[13px] text-gray-400">{verdict.hint}</p>

                <div className="mt-4 grid gap-3 sm:grid-cols-3">
                    <Metric label="근거를 낸 소스" value={`${brief.agreement.active}개`}
                        sub={`강한 근거 ${brief.strong_evidence}개`} />
                    <Metric label="신뢰 상한" value={`${capPct}%`}
                        sub={brief.cap_reasons.length ? `${brief.cap_reasons.length}개 감산 사유` : '감산 없음'} />
                    <Metric label="시장 국면" value={brief.regime.phase || '알 수 없음'}
                        sub={brief.regime.conflict ? '레짐 축 충돌' : `게이트 ${brief.regime.gate_status || '-'}`} />
                </div>

                {brief.cap_reasons.length > 0 && (
                    <ul className="mt-3 space-y-1 border-t border-white/[0.06] pt-3">
                        {brief.cap_reasons.map((r, i) => (
                            <li key={i} className="text-[12px] text-gray-500">· {r}</li>
                        ))}
                    </ul>
                )}
            </section>

            {/* 근거 대조 */}
            <section className="rounded-2xl border border-white/[0.07] bg-[#13151f] p-5">
                <h3 className="mb-3 text-[11px] font-bold uppercase tracking-wider text-gray-500">근거 대조</h3>
                {brief.signals.length === 0 ? (
                    <p className="py-3 text-sm text-gray-500">이 종목에 대한 근거가 하나도 없습니다.</p>
                ) : (
                    <ul className="space-y-1.5">
                        {brief.signals.map((s) => {
                            const meta = SOURCE_LABEL[s.source] ?? { name: s.source, desc: '' };
                            const st = STANCE_STYLE[s.stance] ?? STANCE_STYLE.neutral;
                            return (
                                <li key={s.source} className="flex items-center gap-3 rounded-lg px-2 py-2 hover:bg-white/[0.03]">
                                    <span className={`h-2 w-2 shrink-0 rounded-full ${st.dot}`} />
                                    <span className="min-w-0 flex-1">
                                        <b className="font-bold text-white">{meta.name}</b>
                                        <span className="ml-2 text-[11px] text-gray-600">{meta.desc}</span>
                                    </span>
                                    <span className="shrink-0 rounded border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-gray-500">
                                        {s.grade}
                                    </span>
                                    <span className={`w-10 shrink-0 text-right text-[12px] font-bold ${st.cls}`}>{st.label}</span>
                                    <span className="hidden w-28 shrink-0 text-right font-mono text-[11px] text-gray-600 sm:inline">
                                        {fmtTime(s.as_of)}
                                    </span>
                                </li>
                            );
                        })}
                    </ul>
                )}

                {brief.data_gaps.length > 0 && (
                    <div className="mt-3 border-t border-white/[0.06] pt-3">
                        <span className="text-[11px] font-bold uppercase tracking-wider text-gray-500">모르는 것</span>
                        <div className="mt-1.5 flex flex-wrap gap-1.5">
                            {brief.data_gaps.map((g) => (
                                <span key={g} className="rounded bg-white/[0.05] px-2 py-0.5 font-mono text-[10.5px] text-gray-500">
                                    {(SOURCE_LABEL[g]?.name) ?? g}
                                </span>
                            ))}
                        </div>
                    </div>
                )}
            </section>

            {/* 무효화 조건 */}
            {brief.invalidators.length > 0 && (
                <section className="rounded-2xl border border-white/[0.07] bg-[#13151f] p-5">
                    <h3 className="mb-3 text-[11px] font-bold uppercase tracking-wider text-gray-500">
                        무효화 조건 <span className="ml-1 font-medium normal-case tracking-normal text-gray-600">— 관측 전용, 자동 청산 아님</span>
                    </h3>
                    <ul className="space-y-1.5">
                        {brief.invalidators.map((inv, i) => (
                            <li key={`${inv.type}-${i}`} className="flex items-center gap-2.5 text-[13px]">
                                <span className="rounded bg-amber-500/12 px-1.5 py-0.5 font-mono text-[10px] font-bold text-amber-300">
                                    {inv.type}
                                </span>
                                <span className="text-gray-300">{inv.cond}</span>
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            <p className="px-1 text-[11.5px] leading-relaxed text-gray-600">
                {brief.disclaimer || '정보 제공 목적이며 투자 권유가 아닙니다.'}
                <span className="ml-1">생성 {fmtTime(brief.generated_at)}</span>
            </p>
        </div>
    );
}

function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
    return (
        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3.5 py-3">
            <div className="text-[10.5px] font-bold uppercase tracking-wider text-gray-500">{label}</div>
            <div className="mt-1 text-lg font-bold text-white">{value}</div>
            {sub && <div className="mt-0.5 text-[11px] text-gray-500">{sub}</div>}
        </div>
    );
}
