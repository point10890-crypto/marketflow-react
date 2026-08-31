/**
 * 종목 판단 — AI Brain 전용 페이지.
 *
 * GET /api/kr/decision/<symbol> 를 조회해 시스템이 보유한 독립 근거 7종을 한 종목
 * 기준으로 나란히 비교한다. 어디서 일치하고 어디서 갈리는지, 무엇을 모르는지,
 * 신뢰를 어디까지 둘 수 있는지를 보여주는 것이 이 화면의 전부다.
 * 매수/매도를 지시하지 않는다 — 상태는 watch | neutral | avoid_data_gap 뿐이다.
 */
import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { fetchAuthAPI, postAuthAPI } from '@/lib/api';
import AiBrainServiceTabs from '@/components/aibain/AiBrainServiceTabs';
import RagStatusCard from './RagStatusCard';

const ENDPOINT = '/api/kr/decision';

interface DeepAnalysis {
    symbol: string;
    name: string | null;
    status: string;
    analysts: {
        role: string; title: string; stance: string; score: number | null;
        summary: string; evidence: string[]; method: string;
        verification: { verified: number; unverified: number; contradicted: number } | null;
    }[];
    debate: { rounds: { round: number; bull: string; bear: string }[];
              manager: { stance?: string; thesis?: string; confidence?: number };
              method: string | null } | null;
    risk: Record<string, unknown> | null;
    verdict: { verdict?: string; confidence?: number } | null;
    verification: { verified: number; unverified: number; contradicted: number } | null;
    citations: { kind: string; text: string; grade: string; source: string | null; link: string | null }[];
    retrieval: { news_count?: number; graph_count?: number } | null;
    method: string | null;
    error: string | null;
    cached?: boolean;
    cached_at?: string;
}

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
    verification: { verified: number; unverified: number; contradicted: number } | null;
    news: {
        count: number;
        items: {
            title: string; link: string; source: string; grade: string;
            score: number; published_ts: string | null; corroboration: number;
        }[];
    };
    errors: Record<string, string>;
    disclaimer?: string;
    cached?: boolean;
    cached_at?: string;
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

/**
 * 심층 분석(TradingAgents)이 내는 참고 판정의 한글 라벨.
 * 이것은 **에이전트들이 토론 끝에 낸 분석 결론**이지, 시스템의 매매 지시가 아니다.
 * 브리프 자체의 status 어휘(watch|neutral|avoid_data_gap)는 그대로 유지된다.
 * 색은 국내 관행을 따른다 — 매수 계열 적색, 매도 계열 청색.
 */
const CALL_STYLE: Record<string, { label: string; cls: string; bar: string }> = {
    STRONG_BUY: { label: '적극매수', cls: 'border-red-400/45 bg-red-500/12 text-red-300', bar: 'bg-red-400' },
    BUY: { label: '매수', cls: 'border-red-400/30 bg-red-500/[0.07] text-red-300/90', bar: 'bg-red-400/70' },
    HOLD: { label: '중립', cls: 'border-gray-500/30 bg-white/[0.04] text-gray-300', bar: 'bg-gray-400' },
    NEUTRAL: { label: '중립', cls: 'border-gray-500/30 bg-white/[0.04] text-gray-300', bar: 'bg-gray-400' },
    SELL: { label: '매도', cls: 'border-blue-400/30 bg-blue-500/[0.07] text-blue-300/90', bar: 'bg-blue-400/70' },
    STRONG_SELL: { label: '적극매도', cls: 'border-blue-400/45 bg-blue-500/12 text-blue-300', bar: 'bg-blue-400' },
};

const CALL_FALLBACK = { label: '판정 없음', cls: 'border-gray-600/30 bg-white/[0.03] text-gray-500', bar: 'bg-gray-600' };

function callStyle(raw: string | null | undefined) {
    return CALL_STYLE[String(raw ?? '').toUpperCase()] ?? CALL_FALLBACK;
}

/**
 * 백엔드 감산 사유는 계약 문자열(영문)이다. 화면에서는 사람이 읽는 문장으로 바꾼다.
 * 매핑되지 않는 새 사유는 원문 그대로 흘려보낸다 — 숨기지 않는다.
 */
function capReasonText(raw: string): string {
    const gap = /^data gap:\s*(\S+)/.exec(raw);
    if (gap) return `${SOURCE_LABEL[gap[1]]?.name ?? gap[1]} 근거 없음`;

    if (raw.startsWith('strong evidence')) return '강한 근거(S·A 등급) 부족';
    if (raw === 'sources conflicted') return '근거들이 서로 반대 방향';
    if (raw === 'regime sources conflict') return '시장 국면 판정이 축마다 다름';

    const num = /^unverified numbers:\s*(\d+)/.exec(raw);
    if (num) return `AI 서술 수치 ${num[1]}건이 원천과 대조되지 않음`;

    const phase = /^negative phase ceiling \((.+)\)$/.exec(raw);
    if (phase) return `하락 국면(${phase[1]}) — 신뢰 상한 강제 제한`;

    return raw;
}

/** 화면 맨 위에 한 줄로 두는 결론 — 무엇을 알고 무엇을 모르는지. */
function conclusionLine(b: DecisionBrief): string {
    const a = b.agreement;
    if (b.status === 'avoid_data_gap') {
        return `강한 근거가 ${b.strong_evidence}개뿐입니다 — 판단할 재료가 모자랍니다.`;
    }
    if (a.verdict === 'conflicted') {
        return `근거 ${a.active}개가 긍정 ${a.positive} · 부정 ${a.negative}으로 갈립니다 — 결론을 미루는 편이 안전합니다.`;
    }
    if (b.status === 'watch') {
        return `근거 ${a.positive}개가 같은 방향(긍정)을 가리킵니다 — 관찰 대상입니다.`;
    }
    return `뚜렷한 방향이 없습니다 — 근거 ${a.active}개 중 긍정 ${a.positive} · 부정 ${a.negative}.`;
}

interface Candidate {
    symbol: string;
    name: string | null;
    confidence: number;
    reason: string;
}

/** 왜 이 후보가 걸렸는지 — 사용자가 고르는 데 필요한 정보다. */
const REASON_LABEL: Record<string, string> = {
    ticker_direct: '종목코드', yahoo_ticker: '티커', corp_code_reverse: '고유번호',
    exact_alias: '별칭', exact_name: '종목명',
    chosung_exact: '초성', chosung_prefix: '초성 일부',
    prefix_name: '이름 앞부분', fuzzy: '유사',
    universe_substring: '이름 포함', graphrag: '지식그래프',
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
    const [deep, setDeep] = useState<DeepAnalysis | null>(null);
    const [deepLoading, setDeepLoading] = useState(false);
    const [deepPhase, setDeepPhase] = useState('');
    const [suggestions, setSuggestions] = useState<Candidate[]>([]);
    const suppress = useRef(false);   // 후보를 골라 넣은 직후엔 다시 조회하지 않는다

    const lookup = useCallback(async (raw: string, force = false) => {
        const symbol = raw.trim();
        if (!symbol) return;
        setLoading(true);
        setError('');
        try {
            const path = `${ENDPOINT}/${encodeURIComponent(symbol)}${force ? '?force=1' : ''}`;
            // 캐시 미적중 조회는 프로덕션 실측 6~45초로 흔들린다(백그라운드 워커 경합).
            // 30초로는 첫 조회가 그대로 실패했다. 엣지 프록시 한계(100초) 아래로 잡는다.
            const res = await fetchAuthAPI<unknown>(path, token ?? undefined, 90000);
            if (isDecisionBrief(res)) {
                setBrief(res);
                setDeep(null);
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

    // 심층분석은 job+poll — 동기 대기는 Cloudflare 엣지 ~100초 한계에 걸린다.
    // 구백엔드(동기 응답)와의 호환: 응답에 analysts 가 있으면 그대로 결과다.
    const runDeep = useCallback(async (symbol: string, force = false) => {
        setDeepLoading(true);
        setDeepPhase('분석 요청 중…');
        try {
            const res = await postAuthAPI<DeepAnalysis & { state?: string }>(
                `${ENDPOINT}/${encodeURIComponent(symbol)}/analyze`,
                force ? { force: true } : {}, token ?? undefined, 30000);
            if (res && Array.isArray((res as DeepAnalysis).analysts)) {
                setDeep(res as DeepAnalysis);                       // 캐시 적중 또는 구백엔드
                return;
            }
            if (!res || res.state !== 'running') {
                setError('심층 분석 응답 형식이 올바르지 않습니다.');
                return;
            }
            const startedAt = Date.now();
            for (;;) {
                const st = await fetchAuthAPI<{ state: string; payload?: DeepAnalysis; error?: string | null }>(
                    `${ENDPOINT}/${encodeURIComponent(symbol)}/analyze/status`, token ?? undefined, 15000);
                if (st.state === 'done' && st.payload) { setDeep(st.payload); return; }
                if (st.state === 'error') {
                    setError(`심층 분석에 실패했습니다: ${st.error ?? '알 수 없는 오류'}`);
                    return;
                }
                if (st.state === 'none') {
                    setError('분석이 중단되었습니다(서버 재시작). 다시 실행해 주세요.');
                    return;
                }
                if (Date.now() - startedAt > 8 * 60 * 1000) {
                    setError('심층 분석이 예상보다 오래 걸립니다. 잠시 후 다시 확인해 주세요.');
                    return;
                }
                setDeepPhase(`AI 토론 진행 중… ${Math.round((Date.now() - startedAt) / 1000)}초`);
                await new Promise(r => setTimeout(r, 3000));
            }
        } catch (e) {
            setDeep(null);
            const msg = e instanceof Error ? e.message : '';
            if (msg.includes('quota_exceeded')) setError('심층 분석 일일 한도를 모두 사용했습니다. 내일 다시 이용해 주세요.');
            else if (msg.includes('busy')) setError('동시에 실행 중인 분석이 많습니다. 잠시 후 다시 시도해 주세요.');
            else setError('심층 분석에 실패했습니다. 잠시 후 다시 시도해 주세요.');
        } finally {
            setDeepLoading(false);
            setDeepPhase('');
        }
    }, [token]);

    // 종목명·별칭·초성 후보 조회. 기존 GraphRAG 리졸버가 해석한다.
    useEffect(() => {
        const q = input.trim();
        if (suppress.current) { suppress.current = false; return; }
        if (q.length < 2) { setSuggestions([]); return; }

        let alive = true;
        const timer = setTimeout(() => {
            void (async () => {
                try {
                    const res = await fetchAuthAPI<{ candidates?: Candidate[] }>(
                        `${ENDPOINT}/search?q=${encodeURIComponent(q)}`, token ?? undefined, 8000);
                    if (alive) setSuggestions(Array.isArray(res?.candidates) ? res.candidates : []);
                } catch {
                    if (alive) setSuggestions([]);   // 검색 실패가 직접 입력을 막지 않는다
                }
            })();
        }, 180);
        return () => { alive = false; clearTimeout(timer); };
    }, [input, token]);

    const pick = useCallback((c: Candidate) => {
        suppress.current = true;
        setInput(c.symbol);
        setSuggestions([]);
        void lookup(c.symbol);
    }, [lookup]);

    const onSubmit = (e: FormEvent) => {
        e.preventDefault();
        setSuggestions([]);
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

                <form onSubmit={onSubmit} className="relative flex gap-2">
                    <div className="relative min-w-0 flex-1">
                        <input
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            placeholder="종목명 · 코드 · 초성 (예: 삼성전자, 005930, ㅅㅅㅈㅈ)"
                            aria-label="종목 코드"
                            aria-autocomplete="list"
                            autoComplete="off"
                            className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 text-[15px] text-white placeholder:text-gray-600 focus:border-teal-400/50 focus:outline-none"
                        />
                        {suggestions.length > 0 && (
                            <ul role="listbox" aria-label="종목 후보"
                                className="absolute left-0 right-0 top-full z-20 mt-1.5 max-h-72 overflow-y-auto rounded-xl border border-white/10 bg-[#171a24] py-1 shadow-2xl">
                                {suggestions.map((c) => (
                                    <li key={c.symbol} role="option" aria-selected={false} tabIndex={0}
                                        onClick={() => pick(c)}
                                        onKeyDown={(e) => { if (e.key === 'Enter') pick(c); }}
                                        className="flex cursor-pointer items-center gap-2.5 px-3.5 py-2.5 hover:bg-white/[0.06]">
                                        <span className="min-w-0 flex-1 truncate text-[14px] font-semibold text-white">
                                            {c.name || c.symbol}
                                        </span>
                                        <span className="shrink-0 font-mono text-[12px] text-gray-500">{c.symbol}</span>
                                        <span className="shrink-0 rounded bg-white/[0.06] px-1.5 py-0.5 text-[10.5px] text-gray-400">
                                            {REASON_LABEL[c.reason] ?? c.reason}
                                        </span>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
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

                {loading && (
                    <div className="flex items-center gap-2.5 rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 text-[13px] text-gray-400">
                        <i className="fas fa-circle-notch fa-spin text-[12px] text-teal-300" />
                        근거 7종을 모으는 중입니다 — 처음 조회하는 종목은 1분 가까이 걸릴 수 있습니다.
                        같은 날 다시 보면 즉시 뜹니다.
                    </div>
                )}

                {!brief && !error && !loading && (
                    <div className="rounded-2xl border border-white/[0.06] bg-[#13151f] p-8 text-center">
                        <i className="fas fa-scale-balanced mb-3 text-2xl text-gray-600" />
                        <p className="text-sm text-gray-500">
                            종목 코드 또는 종목명을 입력하면 근거 대조 결과를 보여줍니다.
                        </p>
                    </div>
                )}

                {/* 검색 전에도 검색 계층이 무엇을 알고 있는지 보여준다 */}
                <RagStatusCard />

                {brief && <BriefBody brief={brief} onRefresh={() => void lookup(brief.symbol, true)}
                    refreshing={loading} />}

                {brief && (
                    <div className="rounded-2xl border border-teal-400/20 bg-[#13151f] p-5">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                            <div className="min-w-0">
                                <h3 className="text-sm font-bold text-white">심층 분석</h3>
                                <p className="mt-1 text-[12.5px] text-gray-500">
                                    검출 이력이 없어도 4명의 애널리스트가 각자 분석하고 강세·약세가
                                    토론한 뒤 리스크까지 판정합니다. 검색된 뉴스·그래프 근거가 함께 투입됩니다.
                                </p>
                            </div>
                            <button
                                type="button"
                                onClick={() => void runDeep(brief.symbol)}
                                disabled={deepLoading}
                                className="shrink-0 rounded-xl border border-teal-400/35 bg-teal-500/15 px-4 py-2.5 text-[13px] font-bold text-teal-200 transition hover:bg-teal-500/25 disabled:opacity-40"
                            >
                                {deepLoading ? (deepPhase || '분석 중…') : '심층 분석 실행'}
                            </button>
                        </div>
                        {deep && <DeepBody deep={deep}
                            onRerun={() => void runDeep(brief.symbol, true)}
                            rerunning={deepLoading} />}
                    </div>
                )}
            </div>
        </div>
    );
}

function BriefBody({ brief, onRefresh, refreshing }: {
    brief: DecisionBrief; onRefresh: () => void; refreshing: boolean;
}) {
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
                {brief.cached && (
                    <CacheNote testId="cache-badge" at={brief.cached_at} label="오늘 조회한 결과"
                        action="다시 조회" onAct={onRefresh} busy={refreshing} />
                )}

                <p data-testid="conclusion" className="mt-2.5 text-[15px] font-semibold leading-relaxed text-gray-100">
                    {conclusionLine(brief)}
                </p>
                <p className="mt-1 text-[12.5px] text-gray-500">{verdict.hint}</p>

                <StanceBar a={brief.agreement} />

                <div className="mt-4 grid gap-3 sm:grid-cols-3">
                    <Metric label="근거를 낸 소스" value={`${brief.agreement.active}개`}
                        sub={`강한 근거 ${brief.strong_evidence}개`} />
                    <Metric label="신뢰 상한" value={`${capPct}%`}
                        sub={brief.cap_reasons.length ? `${brief.cap_reasons.length}개 감산 사유` : '감산 없음'}
                        bar={capPct} />
                    <Metric label="시장 국면" value={brief.regime.phase || '알 수 없음'}
                        sub={brief.regime.conflict ? '레짐 축 충돌' : `게이트 ${brief.regime.gate_status || '-'}`} />
                </div>

                {brief.verification && <VerificationBadge v={brief.verification} />}

                {brief.cap_reasons.length > 0 && (
                    <div className="mt-3 border-t border-white/[0.06] pt-3">
                        <div className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-gray-500">
                            신뢰를 깎은 이유
                        </div>
                        <ul className="flex flex-wrap gap-1.5">
                            {brief.cap_reasons.map((r, i) => (
                                <li key={i}
                                    className="rounded-lg border border-amber-400/20 bg-amber-500/[0.06] px-2 py-1 text-[12px] text-amber-200/85">
                                    {capReasonText(r)}
                                </li>
                            ))}
                        </ul>
                    </div>
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

            {/* 뉴스 맥락 — 방향 판정이 아니라 맥락 */}
            {brief.news && brief.news.count > 0 && (
                <section className="rounded-2xl border border-white/[0.07] bg-[#13151f] p-5">
                    <h3 className="mb-3 text-[11px] font-bold uppercase tracking-wider text-gray-500">
                        뉴스 맥락 <span className="ml-1 font-medium normal-case tracking-normal text-gray-600">— 방향 판정 아님, 근거 보강용</span>
                    </h3>
                    <ul className="space-y-1.5">
                        {brief.news.items.map((n, i) => (
                            <li key={`${n.link}-${i}`} className="flex items-start gap-2.5 text-[13px]">
                                <span className="mt-0.5 shrink-0 rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] text-gray-500">
                                    {n.grade}
                                </span>
                                <span className="min-w-0 flex-1">
                                    {n.link ? (
                                        <a href={n.link} target="_blank" rel="noopener noreferrer"
                                            className="text-gray-200 underline-offset-2 hover:text-teal-300 hover:underline">
                                            {n.title}
                                        </a>
                                    ) : (
                                        <span className="text-gray-200">{n.title}</span>
                                    )}
                                    <span className="ml-2 text-[11px] text-gray-600">
                                        {n.source}{n.corroboration > 1 && ` · ${n.corroboration}개 매체`}
                                    </span>
                                </span>
                                <span className="shrink-0 font-mono text-[11px] tabular-nums text-gray-600">
                                    {fmtTime(n.published_ts)}
                                </span>
                            </li>
                        ))}
                    </ul>
                </section>
            )}

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

function DeepBody({ deep, onRerun, rerunning }: {
    deep: DeepAnalysis; onRerun: () => void; rerunning: boolean;
}) {
    if (deep.error) {
        return (
            <div className="mt-4 rounded-xl border border-amber-400/30 bg-amber-500/[0.07] px-4 py-3 text-sm text-amber-200">
                분석을 완료하지 못했습니다: {deep.error}
            </div>
        );
    }
    const stanceCls: Record<string, string> = {
        bullish: 'text-red-300', bearish: 'text-blue-300', neutral: 'text-gray-300',
    };
    const call = callStyle(deep.verdict?.verdict);
    const conf = deep.verdict?.confidence;
    return (
        <div className="mt-5 space-y-4 border-t border-white/[0.06] pt-4">
            {/* 참고 판정 — 토론 결과의 결론. 매매 지시가 아님을 같은 블록에 명시한다. */}
            <div data-testid="deep-call" className={`rounded-2xl border p-4 ${call.cls}`}>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                    <span className="text-[10.5px] font-bold uppercase tracking-wider opacity-70">
                        에이전트 종합 판정
                    </span>
                    <span className="text-2xl font-black tracking-tight">{call.label}</span>
                    {conf != null && (
                        <span className="flex min-w-[140px] flex-1 items-center gap-2">
                            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-black/25">
                                <span className={`block h-full rounded-full ${call.bar}`}
                                    style={{ width: `${Math.max(2, Math.min(100, conf))}%` }} />
                            </span>
                            <b className="font-mono text-[12px] tabular-nums">확신 {conf}</b>
                        </span>
                    )}
                </div>
                <p className="mt-2 text-[11.5px] opacity-70">
                    4인 분석 → 강세·약세 토론 → 리스크 검토를 거친 참고 판정입니다.
                    {deep.method && ` (${deep.method})`} 매매 지시가 아닙니다.
                </p>
                {deep.cached && (
                    <CacheNote at={deep.cached_at} label="오늘 분석한 결과"
                        action="다시 분석" onAct={onRerun} busy={rerunning} />
                )}
            </div>

            {/* 애널리스트 4인 */}
            {deep.analysts.length > 0 && (
                <div>
                    <h4 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">애널리스트 분석</h4>
                    <div className="grid gap-2 sm:grid-cols-2">
                        {deep.analysts.map((a) => (
                            <div key={a.role} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3.5">
                                <div className="flex items-center justify-between gap-2">
                                    <b className="text-[13px] font-bold text-white">{a.title || a.role}</b>
                                    <span className={`text-[11.5px] font-bold ${stanceCls[a.stance] ?? 'text-gray-400'}`}>
                                        {a.stance}{a.score != null && ` ${a.score > 0 ? '+' : ''}${a.score}`}
                                    </span>
                                </div>
                                <p className="mt-1.5 text-[12.5px] leading-relaxed text-gray-300">{a.summary}</p>
                                {a.evidence.length > 0 && (
                                    <ul className="mt-1.5 space-y-0.5">
                                        {a.evidence.slice(0, 3).map((e, i) => (
                                            <li key={i} className="text-[11.5px] text-gray-500">· {e}</li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* 강세 vs 약세 토론 */}
            {deep.debate && deep.debate.rounds.length > 0 && (
                <div>
                    <h4 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">강세 · 약세 토론</h4>
                    <div className="space-y-2">
                        {deep.debate.rounds.map((r) => (
                            <div key={r.round} className="grid gap-2 sm:grid-cols-2">
                                <div className="rounded-xl border border-red-400/20 bg-red-500/[0.05] p-3">
                                    <div className="mb-1 text-[10.5px] font-bold text-red-300">R{r.round} 강세</div>
                                    <p className="text-[12.5px] leading-relaxed text-gray-300">{r.bull}</p>
                                </div>
                                <div className="rounded-xl border border-blue-400/20 bg-blue-500/[0.05] p-3">
                                    <div className="mb-1 text-[10.5px] font-bold text-blue-300">R{r.round} 약세</div>
                                    <p className="text-[12.5px] leading-relaxed text-gray-300">{r.bear}</p>
                                </div>
                            </div>
                        ))}
                    </div>
                    {deep.debate.manager?.thesis && (
                        <div className="mt-2 rounded-xl border border-white/[0.08] bg-white/[0.03] p-3.5">
                            <div className="mb-1 flex items-center gap-2 text-[10.5px] font-bold uppercase tracking-wider text-gray-500">
                                <span>토론 종합</span>
                                {deep.debate.manager.stance && (
                                    <span className={stanceCls[deep.debate.manager.stance] ?? 'text-gray-300'}>
                                        {deep.debate.manager.stance}
                                    </span>
                                )}
                                {deep.debate.manager.confidence != null && (
                                    <span className="text-gray-500">확신 {deep.debate.manager.confidence}</span>
                                )}
                            </div>
                            <p className="text-[12.5px] leading-relaxed text-gray-200">{deep.debate.manager.thesis}</p>
                        </div>
                    )}
                </div>
            )}

            {deep.verification && <VerificationBadge v={deep.verification} />}

            {/* 검색된 근거 (변형 RAG) */}
            {deep.citations.length > 0 && (
                <div>
                    <h4 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">
                        투입된 검색 근거
                        <span className="ml-1 font-medium normal-case tracking-normal text-gray-600">
                            — 뉴스 {deep.retrieval?.news_count ?? 0} · 그래프 {deep.retrieval?.graph_count ?? 0}
                        </span>
                    </h4>
                    <ul className="space-y-1">
                        {deep.citations.slice(0, 8).map((c, i) => (
                            <li key={i} className="flex items-start gap-2 text-[12.5px]">
                                <span className="mt-0.5 shrink-0 rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] text-gray-500">
                                    {c.grade}
                                </span>
                                {c.link ? (
                                    <a href={c.link} target="_blank" rel="noopener noreferrer"
                                        className="text-gray-300 underline-offset-2 hover:text-teal-300 hover:underline">{c.text}</a>
                                ) : (
                                    <span className="text-gray-400">{c.text}</span>
                                )}
                            </li>
                        ))}
                    </ul>
                </div>
            )}

        </div>
    );
}


function VerificationBadge({ v }: { v: { verified: number; unverified: number; contradicted: number } }) {
    const total = v.verified + v.unverified + v.contradicted;
    if (total === 0) return null;
    const clean = v.contradicted === 0 && v.unverified === 0;
    const cls = v.contradicted > 0
        ? 'border-amber-400/35 bg-amber-500/[0.07] text-amber-200'
        : clean
            ? 'border-teal-400/30 bg-teal-500/[0.07] text-teal-200'
            : 'border-white/[0.08] bg-white/[0.03] text-gray-300';
    return (
        <div className={`mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border px-3.5 py-2.5 text-[12px] ${cls}`}>
            <span className="font-bold">기계적 검증</span>
            <span>원천 대조 <b>{v.verified}</b></span>
            <span>미검증 <b>{v.unverified}</b></span>
            <span>불일치 <b>{v.contradicted}</b></span>
            <span className="text-[11px] opacity-70">
                {clean ? 'AI 서술의 수치가 모두 수집 데이터와 일치' : 'AI 서술 수치 중 원천과 맞지 않는 항목이 있어 신뢰 상한을 낮춤'}
            </span>
        </div>
    );
}


function Metric({ label, value, sub, bar }: {
    label: string; value: string; sub?: string; bar?: number;
}) {
    return (
        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3.5 py-3">
            <div className="text-[10.5px] font-bold uppercase tracking-wider text-gray-500">{label}</div>
            <div className="mt-1 text-lg font-bold text-white">{value}</div>
            {bar != null && (
                <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                    <div className={`h-full rounded-full ${bar >= 50 ? 'bg-teal-400/70' : 'bg-amber-400/70'}`}
                        style={{ width: `${Math.max(2, Math.min(100, bar))}%` }} />
                </div>
            )}
            {sub && <div className="mt-0.5 text-[11px] text-gray-500">{sub}</div>}
        </div>
    );
}


/**
 * 캐시본을 보고 있다는 사실을 숨기지 않는다 — 언제 계산된 것인지 밝히고
 * 항상 다시 돌릴 길을 함께 준다.
 */
function CacheNote({ at, label, action, onAct, busy, testId }: {
    at?: string; label: string; action: string;
    onAct: () => void; busy: boolean; testId?: string;
}) {
    const time = at ? at.slice(11, 16) : '';
    return (
        <div data-testid={testId}
            className="mt-2.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-1.5 text-[11.5px] text-gray-400">
            <i className="fas fa-clock-rotate-left text-[10px] opacity-60" />
            <span>{label}{time && ` · ${time}`}</span>
            <button type="button" onClick={onAct} disabled={busy}
                className="rounded-md border border-white/15 px-2 py-0.5 text-[11px] font-bold text-gray-300 transition hover:bg-white/[0.06] disabled:opacity-40">
                {busy ? '실행 중' : action}
            </button>
        </div>
    );
}


/** 찬반 분포를 한눈에 — 숫자 나열보다 폭이 빠르다. */
function StanceBar({ a }: { a: Agreement }) {
    const seg = [
        { n: a.positive, cls: 'bg-red-400/80', label: '긍정' },
        { n: a.negative, cls: 'bg-blue-400/80', label: '부정' },
        { n: a.neutral, cls: 'bg-gray-400/60', label: '중립' },
        { n: a.absent, cls: 'bg-white/[0.07]', label: '없음' },
    ];
    const total = seg.reduce((s, x) => s + (x.n || 0), 0);
    if (total === 0) return null;
    const aria = seg.filter((s) => s.n > 0).map((s) => `${s.label} ${s.n}`).join(', ');
    return (
        <div className="mt-3.5">
            <div data-testid="stance-bar" role="img" aria-label={aria}
                className="flex h-2.5 overflow-hidden rounded-full bg-white/[0.04]">
                {seg.map((s) => s.n > 0 && (
                    <span key={s.label} className={s.cls} style={{ width: `${(s.n / total) * 100}%` }} />
                ))}
            </div>
            <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-gray-500">
                {seg.filter((s) => s.n > 0).map((s) => (
                    <span key={s.label} className="flex items-center gap-1.5">
                        <span className={`h-2 w-2 rounded-full ${s.cls}`} />
                        {s.label} <b className="font-mono text-gray-400">{s.n}</b>
                    </span>
                ))}
            </div>
        </div>
    );
}
