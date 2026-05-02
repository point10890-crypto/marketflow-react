import { useEffect, useMemo, useState } from 'react';
import { MiroFishAnalyst, MiroFishLayer, MiroFishLog, MiroFishNode, MiroFishRun, MiroFishStatus, mirofishApi } from '@/lib/mirofishApi';

const agentCounts = [3, 7, 10, 15];

const layerColors: Record<string, string> = {
    TARGET: 'bg-red-500',
    'CAUSAL HISTORY': 'bg-blue-500',
    'AI ANALYSTS': 'bg-violet-500',
    PREDICTIONS: 'bg-orange-400',
    VERDICT: 'bg-emerald-400',
};

const fallbackRun: MiroFishRun = {
    target: 'Samsung Electronics',
    display_name: 'Samsung Electronics',
    price: 216000,
    change_pct: 0,
    status: 'local_fallback',
    mode: 'full',
    brain: { score: 50, regime: 'neutral', crisis: 'Lv.2' },
    pipeline: { graph_links: 39, similar_events: 1, agent_count: 10 },
    layers: [
        { label: '대상', count: 1 },
        { label: '인과 메모리', count: 34 },
        { label: 'AI 애널리스트', count: 7 },
        { label: '예측', count: 7 },
        { label: '판정', count: 1 },
    ],
    logs: [
        { phase: 1, time: '06:52:26', text: '분석 시작', tone: 'text-blue-300' },
        { phase: 1, time: '06:52:27', text: '대상 락온: Samsung Electronics', tone: 'text-emerald-300' },
        { phase: 3, time: '07:09:32', text: 'GraphRAG 인과 시그널 39개 연결', tone: 'text-teal-400' },
        { phase: 3, time: '07:09:32', text: 'Brain 점수 50.0, 체제 중립', tone: 'text-teal-400' },
        { phase: 4, time: '07:09:42', text: '애널리스트 토론 완료: 강세 3 / 약세 0 / 중립 4', tone: 'text-violet-400' },
        { phase: 5, time: '07:09:58', text: '최종 판정 합성 완료: BUY', tone: 'text-emerald-400' },
    ],
    analysts: [
        { name: '김치', role: '반도체 애널리스트', verdict: 'NEUTRAL', confidence: 55, icon: 'fa-microscope' },
        { name: '모건', role: '매크로 전략가', verdict: 'NEUTRAL', confidence: 65, icon: 'fa-chart-line' },
        { name: '에미', role: 'AI 인프라 전문가', verdict: 'BULLISH', confidence: 60, icon: 'fa-globe-asia' },
        { name: '박', role: '지정학 리스크 애널리스트', verdict: 'NEUTRAL', confidence: 70, icon: 'fa-bolt' },
        { name: '송', role: '공급망 스페셜리스트', verdict: 'BULLISH', confidence: 68, icon: 'fa-building-columns' },
        { name: '로빈', role: '퀀트 애널리스트', verdict: 'BULLISH', confidence: 65, icon: 'fa-calculator' },
        { name: '강', role: '포트폴리오 매니저', verdict: 'NEUTRAL', confidence: 65, icon: 'fa-briefcase' },
    ],
    graph_nodes: [
        { label: 'hbm', x: 50, y: 39 },
        { label: 'robot_joint', x: 58, y: 37 },
        { label: 'image_sensor', x: 43, y: 38 },
        { label: 'sk_hynix', x: 39, y: 40 },
        { label: 'kospi', x: 70, y: 48 },
        { label: 'china_pmi', x: 65, y: 55 },
        { label: 'global_pmi', x: 68, y: 58 },
        { label: 'networking', x: 59, y: 51 },
        { label: 'ai_memory', x: 48, y: 55 },
        { label: 'dc_cooling', x: 35, y: 59 },
    ],
    prediction_nodes: [
        { label: '에미 강세', x: 40, y: 65, verdict: 'bull' },
        { label: '김 중립', x: 35, y: 70, verdict: 'neutral' },
        { label: '모건 중립', x: 43, y: 76, verdict: 'neutral' },
        { label: '박 중립', x: 56, y: 73, verdict: 'neutral' },
        { label: '송 강세', x: 70, y: 65, verdict: 'bull' },
        { label: '로빈 강세', x: 75, y: 66, verdict: 'bull' },
        { label: '강 중립', x: 81, y: 75, verdict: 'neutral' },
    ],
    verdict: {
        label: 'BUY',
        confidence: 64,
        bullish: 3,
        bearish: 0,
        neutral: 4,
        horizon: '1M',
        summary: '강세 3, 약세 0, 중립 4 — 매수 우위 합의.',
    },
};

const pipelineCards = [
    {
        title: 'GraphRAG',
        desc: '리서치 메모리에서 엔티티, 인과 관계, 시장 맥락을 자동 추출합니다.',
        icon: 'fa-project-diagram',
        color: 'text-cyan-300',
        metric: 'EKG + LLM',
    },
    {
        title: '에이전트 토론',
        desc: '강세/약세/매크로/퀀트/리스크 5인 페르소나가 토론한 뒤 합의를 도출합니다.',
        icon: 'fa-comments',
        color: 'text-violet-300',
        metric: '에이전트 10명',
    },
    {
        title: 'CIO 리포트',
        desc: 'ReACT 추론 트레이스, Brain 시그널, 에이전트 토론을 종합해 최종 판정을 내립니다.',
        icon: 'fa-brain',
        color: 'text-amber-300',
        metric: '3-레이어 그래프',
    },
];

const impactSteps = [
    { no: '01', ko: '대상 입력', en: 'TARGET', icon: 'fa-search' },
    { no: '02', ko: 'Brain 13D', en: 'BRAIN', icon: 'fa-brain' },
    { no: '03', ko: '그래프 추출', en: 'GRAPHRAG', icon: 'fa-link' },
    { no: '04', ko: '에이전트 토론', en: 'DEBATE', icon: 'fa-users' },
    { no: '05', ko: 'CIO 판정', en: 'VERDICT', icon: 'fa-gavel' },
];

const runSteps = ['입력', 'Brain 13D', 'GraphRAG', '에이전트', '리포트'];

function clampCount(value: unknown, fallback: number) {
    const numberValue = Number(value);
    return Number.isFinite(numberValue) ? numberValue : fallback;
}

function verdictTone(verdict?: string) {
    const upper = (verdict || '').toUpperCase();
    if (upper.includes('BULL') || upper === 'BUY') return 'border-emerald-400 bg-emerald-500/10 text-emerald-500';
    if (upper.includes('BEAR') || upper === 'SELL') return 'border-rose-400 bg-rose-500/10 text-rose-500';
    return 'border-amber-400 bg-amber-500/10 text-amber-500';
}

function visibleLayers(run: MiroFishRun, phase: number): MiroFishLayer[] {
    const base = run.layers?.length ? run.layers : fallbackRun.layers || [];
    return base.map((layer) => {
        const label = layer.label.toUpperCase();
        const count = phase < 3 && label !== 'TARGET'
            ? 0
            : phase < 4 && label === 'PREDICTIONS'
                ? 0
                : phase < 5 && label === 'VERDICT'
                    ? 0
                    : layer.count;
        return { ...layer, label, count, color: layer.color || layerColors[label] || 'bg-slate-400' };
    });
}

function visibleLogs(run: MiroFishRun, phase: number): MiroFishLog[] {
    const logs = run.logs?.length ? run.logs : fallbackRun.logs || [];
    return logs.filter((log) => (log.phase || 1) <= phase);
}

function analystPositions(analysts: MiroFishAnalyst[]): MiroFishNode[] {
    const xs = [31, 43, 55, 67, 76, 83, 89, 24, 50, 71];
    return analysts.map((analyst, index) => ({
        label: analyst.name,
        x: xs[index] ?? 50,
        y: index > 6 ? 82 : 75 + (index % 2),
    }));
}

function Stepper({ phase }: { phase: number }) {
    return (
        <section className="rounded-xl border border-white/30 bg-white/[0.86] p-5 text-slate-900 shadow-[0_22px_80px_rgba(124,58,237,0.18)]">
            <div className="relative grid gap-3 md:grid-cols-5">
                <div className="absolute left-[10%] right-[10%] top-12 hidden h-px bg-slate-300/70 md:block" />
                {impactSteps.map((step, index) => {
                    const active = index + 1 <= phase;
                    return (
                        <div key={step.no} className="relative flex flex-col items-center text-center">
                            <div className={`grid h-[72px] w-[72px] place-items-center rounded-2xl border text-sm font-black shadow-lg ${active ? 'border-blue-300 bg-gradient-to-br from-blue-500 to-violet-600 text-white ring-8 ring-blue-300/25' : 'border-slate-200 bg-white/90 text-slate-300'}`}>
                                {active ? <i className={`fas ${step.icon}`} /> : step.no}
                            </div>
                            <div className={`mt-3 text-xs font-black ${active ? 'text-slate-900' : 'text-slate-300'}`}>{step.ko}</div>
                            <div className={`mt-0.5 text-[10px] font-bold tracking-[0.18em] ${active ? 'text-blue-500' : 'text-slate-300'}`}>{step.en}</div>
                        </div>
                    );
                })}
            </div>
        </section>
    );
}

function TargetCard({ run }: { run: MiroFishRun }) {
    const change = Number(run.change_pct ?? 0);
    const price = run.price ?? '--';
    return (
        <section className="rounded-xl border border-white/30 bg-white/[0.88] p-6 text-slate-900 shadow-[0_22px_80px_rgba(14,165,233,0.12)]">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div>
                    <div className="flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.22em] text-slate-400">
                        분석 대상
                        <span className="h-2 w-2 rounded-full bg-violet-600" />
                        <span className="text-violet-600">실시간 스트리밍</span>
                        <i className="fas fa-signal text-violet-500" />
                    </div>
                    <h2 className="mt-2 break-words text-4xl font-black tracking-tight">{run.display_name || run.target}</h2>
                    <div className="mt-5 h-1.5 w-72 max-w-full rounded-full bg-gradient-to-r from-blue-500 via-violet-500 to-emerald-400" />
                </div>
                <div className="text-left md:text-right">
                    <div className="text-5xl font-black tracking-tight">{price}<span className="ml-2 text-lg font-bold text-slate-400">KRW</span></div>
                    <div className={`mt-2 inline-flex items-center gap-2 rounded-xl px-3 py-1.5 text-sm font-black ${change >= 0 ? 'bg-emerald-500/10 text-emerald-500' : 'bg-red-500/10 text-red-500'}`}>
                        <i className={`fas ${change >= 0 ? 'fa-caret-up' : 'fa-caret-down'}`} />
                        {change.toFixed(2)}%
                    </div>
                </div>
            </div>
        </section>
    );
}

function KnowledgeGraph({ phase, run }: { phase: number; run: MiroFishRun }) {
    const isGraphReady = phase >= 3;
    const isPredictionReady = phase >= 4;
    const isVerdictReady = phase >= 5;
    const layers = visibleLayers(run, phase);
    const graphNodes = run.graph_nodes?.length ? run.graph_nodes : fallbackRun.graph_nodes || [];
    const analysts = run.analysts?.length ? run.analysts : fallbackRun.analysts || [];
    const analystNodes = analystPositions(analysts);
    const predictionNodes = run.prediction_nodes?.length ? run.prediction_nodes : fallbackRun.prediction_nodes || [];
    const verdict = run.verdict || fallbackRun.verdict;

    return (
        <section className="relative min-h-[430px] overflow-hidden rounded-xl border border-white/25 bg-slate-50/90 p-5 text-slate-900">
            <div className="absolute left-5 top-5 z-20 w-48 rounded-xl bg-white/80 p-4 shadow-xl shadow-slate-300/30">
                <div className="mb-3 text-[11px] font-black uppercase tracking-[0.2em] text-slate-400">레이어</div>
                <div className="space-y-3">
                    {layers.map((layer) => (
                        <div key={layer.label} className="flex items-center gap-3 text-xs font-black">
                            <span className={`h-3 w-3 rounded-full ${layer.color} shadow`} />
                            <span className="flex-1">{layer.label}</span>
                            <span className="text-slate-500">{layer.count}</span>
                        </div>
                    ))}
                </div>
            </div>

            <div className="absolute left-1/2 top-6 z-20 -translate-x-1/2 rounded-xl bg-white/80 px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] text-slate-500 shadow">
                지식 그래프 <span className="ml-2 inline-block h-2 w-2 rounded-full bg-emerald-400" />
            </div>
            {isPredictionReady && (
                <div className="absolute right-40 top-6 z-20 hidden items-center gap-2 rounded-xl bg-white/80 px-4 py-2 text-[11px] font-black uppercase tracking-[0.12em] text-slate-500 shadow lg:flex">
                    <span className="h-2 w-2 rounded-full bg-emerald-400" />
                    <span>강세 <b className="text-emerald-500">{verdict?.bullish ?? 0}</b></span>
                    <span className="h-2 w-2 rounded-full bg-amber-400" />
                    <span>중립 <b className="text-amber-500">{verdict?.neutral ?? 0}</b></span>
                    <span className="h-2 w-2 rounded-full bg-rose-500" />
                    <span>약세 <b className="text-rose-500">{verdict?.bearish ?? 0}</b></span>
                </div>
            )}

            {isGraphReady ? (
                <>
                    <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
                        {graphNodes.map((node, index) => (
                            <line key={`${node.label}-${index}`} x1="30" y1="31" x2={node.x ?? 50} y2={node.y ?? 50} stroke="rgba(99,102,241,0.34)" strokeWidth="0.32" />
                        ))}
                        {isPredictionReady && predictionNodes.map((node, index) => {
                            const source = analystNodes[index] ?? analystNodes[0];
                            return <line key={`pred-${node.label}`} x1={source.x} y1={source.y} x2={node.x ?? 50} y2={node.y ?? 65} stroke="rgba(245,158,11,0.36)" strokeWidth="0.36" />;
                        })}
                        {isVerdictReady && predictionNodes.map((node) => (
                            <line key={`verdict-${node.label}`} x1={node.x ?? 50} y1={node.y ?? 65} x2="58" y2="92" stroke="rgba(16,185,129,0.36)" strokeWidth="0.38" />
                        ))}
                    </svg>

                    <div className="absolute left-[30%] top-[31%] z-10 -translate-x-1/2 -translate-y-1/2 text-center">
                        <div className="grid h-16 w-16 place-items-center rounded-full border-2 border-red-400 bg-red-500/15 text-red-500 shadow-[0_0_0_8px_rgba(248,113,113,0.13)]">
                            <i className="fas fa-warning" />
                        </div>
                        <div className="-mt-1 max-w-[140px] truncate rounded border border-red-300 bg-white px-2 py-0.5 text-[10px] font-black">{run.display_name || run.target}</div>
                    </div>

                    {graphNodes.map((node) => (
                        <div key={node.label} className="absolute z-10 -translate-x-1/2 -translate-y-1/2 text-center" style={{ left: `${node.x ?? 50}%`, top: `${node.y ?? 50}%` }}>
                            <div className="mx-auto h-5 w-5 rounded-full border-2 border-indigo-400 bg-indigo-300/35" />
                            <div className="-mt-0.5 max-w-[78px] truncate rounded border border-indigo-200 bg-white px-1.5 py-0.5 text-[9px] font-bold text-slate-500">{node.label}</div>
                        </div>
                    ))}

                    {analystNodes.map((node) => (
                        <div key={node.label} className="absolute z-10 -translate-x-1/2 -translate-y-1/2 text-center" style={{ left: `${node.x}%`, top: `${node.y}%` }}>
                            <div className="mx-auto h-8 w-8 rounded-full border-2 border-violet-400 bg-violet-300/35" />
                            <div className="-mt-0.5 max-w-[84px] truncate rounded border border-violet-200 bg-white px-2 py-0.5 text-[9px] font-bold text-slate-500">{node.label}</div>
                        </div>
                    ))}

                    {isPredictionReady && predictionNodes.map((node) => (
                        <div key={node.label} className="absolute z-20 -translate-x-1/2 -translate-y-1/2 text-center" style={{ left: `${node.x ?? 50}%`, top: `${node.y ?? 65}%` }}>
                            <div className={`mx-auto h-7 w-7 rounded-full border-2 ${node.verdict === 'bull' ? 'border-emerald-400 bg-emerald-300/40' : node.verdict === 'bear' ? 'border-rose-400 bg-rose-300/40' : 'border-amber-400 bg-amber-300/40'}`} />
                            <div className="max-w-[96px] truncate rounded border border-orange-200 bg-white px-2 py-0.5 text-[9px] font-bold text-slate-500">{node.label}</div>
                        </div>
                    ))}

                    {isVerdictReady && (
                        <div className="absolute left-[58%] top-[92%] z-30 -translate-x-1/2 -translate-y-1/2 text-center">
                            <div className="mx-auto h-20 w-20 rounded-full border-4 border-emerald-400 bg-emerald-300/45 shadow-[0_0_0_10px_rgba(16,185,129,0.12),0_0_42px_rgba(16,185,129,0.38)]" />
                            <div className="-mt-1 rounded border border-emerald-300 bg-white px-3 py-1 text-sm font-black text-emerald-600">{verdict?.label || 'BUY'}</div>
                        </div>
                    )}
                </>
            ) : (
                <>
                    <div className="absolute inset-x-12 bottom-8 h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent" />
                    <div className="absolute bottom-5 right-5 text-xs font-bold text-slate-300">Waiting for graph nodes</div>
                </>
            )}
        </section>
    );
}

function FeedPanel({ phase, run }: { phase: number; run: MiroFishRun }) {
    const logs = visibleLogs(run, phase);
    return (
        <section className="min-h-[430px] rounded-xl border border-white/25 bg-white/[0.78] p-5 text-slate-900">
            <div className="mb-5 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span className="h-3 w-3 rounded-full bg-red-400" />
                    <span className="h-3 w-3 rounded-full bg-yellow-400" />
                    <span className="h-3 w-3 rounded-full bg-emerald-400" />
                    <span className="ml-2 text-[11px] font-black uppercase tracking-[0.2em] text-slate-300">Feed</span>
                </div>
                <span className="text-xs font-black text-slate-300">{logs.length}</span>
            </div>
            <div className="space-y-4 font-mono text-xs">
                {logs.map((log, index) => (
                    <div key={`${log.time || index}-${log.text}`} className="flex gap-3">
                        <span className="shrink-0 text-slate-300">{log.time || 'live'}</span>
                        <span className={`font-bold ${log.tone || 'text-blue-300'}`}>{log.text}</span>
                    </div>
                ))}
                {phase < 5 && <div className="h-5 w-1.5 animate-pulse rounded bg-blue-500" />}
            </div>
        </section>
    );
}

function SignalSummaryCard({ run }: { run: MiroFishRun }) {
    const score = clampCount(run.brain?.score, 50);
    return (
        <section className="max-w-3xl rounded-xl border border-white/30 bg-white/90 p-4 text-slate-900 shadow-[0_18px_70px_rgba(124,58,237,0.16)]">
            <div className="flex items-center gap-5">
                <div className="grid h-24 w-24 shrink-0 place-items-center rounded-full border-4 border-blue-200 bg-blue-50 text-center shadow-inner">
                    <div>
                        <div className="text-2xl font-black text-blue-600">{score}</div>
                        <div className="text-[10px] font-bold text-slate-400">/100</div>
                    </div>
                </div>
                <div className="min-w-0 flex-1">
                    <div className="text-lg font-black text-blue-700">Brain 시그널 요약</div>
                    <div className="mt-3 grid grid-cols-2 gap-4 text-xs font-bold text-slate-400 sm:grid-cols-4">
                        <span>체제</span>
                        <span className="text-slate-700">{run.brain?.regime || 'neutral'}</span>
                        <span>위기 단계</span>
                        <span className="text-slate-700">{run.brain?.crisis || 'Lv.2'}</span>
                    </div>
                    <div className="mt-5 h-2 rounded-full bg-slate-100">
                        <div className="h-full rounded-full bg-gradient-to-r from-blue-400 via-violet-400 to-emerald-300" style={{ width: `${Math.min(100, Math.max(0, score))}%` }} />
                    </div>
                </div>
            </div>
        </section>
    );
}

function FinalVerdictPanel({ run }: { run: MiroFishRun }) {
    const verdict = run.verdict || fallbackRun.verdict;
    return (
        <section className="relative overflow-hidden rounded-xl border border-emerald-200/20 bg-emerald-700 p-8 text-white shadow-[0_26px_90px_rgba(16,185,129,0.22)] md:p-12">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_36%,rgba(255,255,255,0.22),rgba(255,255,255,0)_24%),linear-gradient(135deg,rgba(6,95,70,0.9),rgba(5,150,105,0.95))]" />
            <div className="relative mx-auto flex min-h-[430px] max-w-5xl flex-col items-center justify-center text-center">
                <div className="mb-6 flex items-center gap-4 text-[11px] font-black uppercase tracking-[0.45em] text-emerald-100/50">
                    <span>최종 판정</span>
                    <span className="h-px w-12 bg-emerald-100/30" />
                </div>
                <h2 className="text-[76px] font-black leading-none tracking-tight text-white md:text-[152px]">{verdict?.label || 'BUY'}</h2>
                <p className="mt-7 text-base font-bold text-emerald-50/65 md:text-lg">{verdict?.summary || 'MiroFish 토론 완료.'}</p>
                <div className="mt-10 grid h-36 w-36 place-items-center rounded-full border-[7px] border-white/90 bg-white/5 shadow-[0_0_60px_rgba(255,255,255,0.16)]">
                    <div>
                        <div className="text-[11px] font-black uppercase tracking-[0.28em] text-emerald-50/45">확신도</div>
                        <div className="text-4xl font-black text-white">{verdict?.confidence ?? 64}%</div>
                    </div>
                </div>
                <div className="mt-10 grid w-full max-w-3xl grid-cols-2 gap-3 md:grid-cols-4">
                    {[
                        { label: '강세', value: verdict?.bullish ?? 0, color: 'text-emerald-100' },
                        { label: '약세', value: verdict?.bearish ?? 0, color: 'text-rose-200' },
                        { label: '중립', value: verdict?.neutral ?? 0, color: 'text-white' },
                        { label: '시계열', value: verdict?.horizon || '1M', color: 'text-white' },
                    ].map((stat) => (
                        <div key={stat.label} className="rounded-xl border border-white/15 bg-white/10 px-5 py-4 backdrop-blur">
                            <div className="text-[10px] font-black uppercase tracking-[0.25em] text-emerald-50/35">{stat.label}</div>
                            <div className={`mt-2 text-3xl font-black ${stat.color}`}>{stat.value}</div>
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
}

function ImpactPanel({ phase, run }: { phase: number; run: MiroFishRun }) {
    const analysts = run.analysts?.length ? run.analysts : fallbackRun.analysts || [];
    const verdict = run.verdict || fallbackRun.verdict;
    return (
        <div className="space-y-4">
            <Stepper phase={phase} />
            <TargetCard run={run} />
            {phase >= 5 && <SignalSummaryCard run={run} />}
            <div className="grid gap-4 lg:grid-cols-[1fr_0.64fr]">
                <KnowledgeGraph phase={phase} run={run} />
                <FeedPanel phase={phase} run={run} />
            </div>
            {phase >= 4 && (
                <section className="space-y-3">
                    <div className="flex items-center justify-between px-1">
                        <h2 className="text-sm font-black uppercase tracking-[0.18em] text-white/35">애널리스트 ({analysts.length})</h2>
                        <div className="text-xs font-black uppercase tracking-[0.16em]">
                            <span className="text-emerald-400">강세 {verdict?.bullish ?? 0}</span>
                            <span className="mx-3 text-white/25">|</span>
                            <span className="text-red-400">약세 {verdict?.bearish ?? 0}</span>
                        </div>
                    </div>
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                        {analysts.map((card) => (
                            <div key={card.name} className={`rounded-xl border border-white/20 bg-white/90 p-4 text-slate-900 shadow-xl shadow-black/10 border-t-4 ${verdictTone(card.verdict).split(' ')[0]}`}>
                                <div className="flex items-center gap-3">
                                    <div className="grid h-12 w-12 place-items-center rounded-full bg-slate-100 ring-1 ring-slate-200">
                                        <i className={`fas ${card.icon || 'fa-user-tie'} text-slate-500`} />
                                    </div>
                                    <div className="min-w-0">
                                        <div className="font-black text-slate-900">{card.name}</div>
                                        <div className="truncate text-xs font-bold text-slate-400">{card.role || 'MiroFish analyst'}</div>
                                    </div>
                                </div>
                                <div className={`mt-4 inline-flex rounded-full px-2.5 py-1 text-[10px] font-black ${verdictTone(card.verdict).replace('border-emerald-400 ', '').replace('border-rose-400 ', '').replace('border-amber-400 ', '')}`}>
                                    {card.verdict || 'NEUTRAL'} {card.confidence ? `${card.confidence}%` : ''}
                                </div>
                            </div>
                        ))}
                    </div>
                </section>
            )}
            {phase >= 5 && <FinalVerdictPanel run={run} />}
        </div>
    );
}

export default function AdminEndpointsPage() {
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [phase, setPhase] = useState(1);
    const [target, setTarget] = useState('삼성전자');
    const [agentCount, setAgentCount] = useState(10);
    const [run, setRun] = useState<MiroFishRun>(fallbackRun);
    const [status, setStatus] = useState<MiroFishStatus | null>(null);
    const [apiState, setApiState] = useState<'checking' | 'ready' | 'fallback' | 'running'>('checking');
    const [errorText, setErrorText] = useState<string | null>(null);

    useEffect(() => {
        let alive = true;
        mirofishApi.getStatus()
            .then((data) => {
                if (!alive) return;
                setStatus(data);
                setApiState('ready');
                setRun((current) => ({ ...current, brain: data.brain || current.brain, pipeline: data.pipeline || current.pipeline }));
            })
            .catch(() => {
                if (!alive) return;
                setApiState('fallback');
                setStatus({ ready: false, source: 'api unavailable', brain: fallbackRun.brain, pipeline: fallbackRun.pipeline });
            });
        return () => {
            alive = false;
        };
    }, []);

    useEffect(() => {
        if (!isAnalyzing) return;
        setPhase(1);
        const graphTimer = window.setTimeout(() => setPhase(3), 900);
        const predictionTimer = window.setTimeout(() => setPhase(4), 1900);
        const verdictTimer = window.setTimeout(() => setPhase(5), 3000);
        return () => {
            window.clearTimeout(graphTimer);
            window.clearTimeout(predictionTimer);
            window.clearTimeout(verdictTimer);
        };
    }, [isAnalyzing, run.id]);

    const brainSignals = useMemo(() => {
        const brain = status?.brain || run.brain || fallbackRun.brain;
        return [
            { label: 'BRAIN', value: String(brain?.score ?? 50), tone: 'text-violet-300' },
            { label: 'REGIME', value: brain?.regime || 'neutral', tone: 'text-slate-200' },
            { label: 'CRISIS', value: brain?.crisis || 'Lv.2', tone: 'text-amber-300' },
        ];
    }, [run.brain, status]);

    async function handleStart() {
        const nextTarget = target.trim() || fallbackRun.target;
        setErrorText(null);
        setIsAnalyzing(true);
        setApiState('running');
        setRun({ target: nextTarget, display_name: nextTarget, status: 'running' });
        try {
            const data = await mirofishApi.startRun({ target: nextTarget, agent_count: agentCount, mode: 'full' });
            setRun({ ...data, target: data.target || nextTarget, display_name: data.display_name || data.target || nextTarget });
            setApiState('ready');
        } catch (error) {
            setIsAnalyzing(false);
            setRun((current) => ({ ...current, status: 'api_error' }));
            setApiState('fallback');
            setErrorText(error instanceof Error ? error.message : 'MiroFish API unavailable. Live data was not loaded.');
        }
    }

    return (
        <div className="space-y-5">
            <section className="relative overflow-hidden rounded-xl border border-white/[0.07] bg-[#111113]">
                <div className="absolute inset-0 bg-[linear-gradient(120deg,rgba(20,184,166,0.22),rgba(124,58,237,0.24)_46%,rgba(245,158,11,0.16))]" />
                <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(9,9,11,0.10),rgba(9,9,11,0.74))]" />

                <div className="relative px-5 py-7 md:px-8 md:py-10">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-xs font-bold text-white/80 backdrop-blur">
                            <i className="fas fa-lock text-red-300" />
                            관리자 전용 리서치 콘솔
                        </div>
                        <div className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-bold ${apiState === 'fallback' ? 'border-amber-300/20 bg-amber-300/10 text-amber-200' : 'border-cyan-300/20 bg-cyan-300/10 text-cyan-200'}`}>
                            <i className="fas fa-satellite-dish" />
                            {apiState === 'checking' ? 'MiroFish 점검 중' : apiState === 'running' ? '분석 실행 중' : apiState === 'fallback' ? '폴백 모드' : 'MiroFish 준비됨'}
                        </div>
                    </div>

                    <div className="mt-8 max-w-4xl">
                        <h1 className="text-[40px] font-black leading-[0.98] tracking-tight text-white md:text-[72px]">
                            MiroFish Market Brain
                            <span className="block bg-gradient-to-r from-cyan-200 via-violet-300 to-amber-200 bg-clip-text text-transparent">
                                GraphRAG Analysis
                            </span>
                        </h1>
                        <p className="mt-5 max-w-2xl text-base font-semibold leading-7 text-slate-300 md:text-lg">
                            Brain 시그널 · 인과 메모리 · 5인 에이전트 토론 · CIO 판정을 관리자 MiroFish API 로 연결합니다.
                        </p>
                    </div>

                    <div className="mt-6 flex flex-wrap gap-2">
                        {brainSignals.map((signal) => (
                            <span key={signal.label} className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/80 px-4 py-2 text-xs font-black text-slate-500 shadow-lg shadow-black/10">
                                <span className="tracking-[0.18em]">{signal.label}</span>
                                <span className={`${signal.tone} text-sm`}>{signal.value}</span>
                            </span>
                        ))}
                    </div>

                    <div className="mt-8 max-w-4xl rounded-xl border border-cyan-300/40 bg-white/90 p-2 shadow-[0_18px_70px_rgba(34,211,238,0.22)]">
                        <div className="flex flex-col gap-2 sm:flex-row">
                            <label className="flex min-h-12 flex-1 items-center gap-3 px-3 text-slate-500">
                                <i className="fas fa-search text-lg" />
                                <input
                                    className="w-full bg-transparent text-base font-bold text-slate-900 outline-none placeholder:text-slate-400"
                                    placeholder="삼성전자, NVDA, BTC, FOMC 등 분석 대상 입력"
                                    value={target}
                                    onChange={(event) => setTarget(event.target.value)}
                                />
                            </label>
                            <button
                                type="button"
                                onClick={handleStart}
                                disabled={apiState === 'running'}
                                className="min-h-12 rounded-lg bg-gradient-to-r from-blue-600 to-violet-600 px-6 text-sm font-black text-white shadow-lg shadow-violet-600/25 transition hover:brightness-110 disabled:cursor-wait disabled:opacity-75"
                            >
                                {apiState === 'running' ? '분석 중' : '분석 시작'}
                            </button>
                        </div>
                    </div>

                    {errorText && <div className="mt-3 max-w-4xl rounded-lg border border-amber-300/20 bg-amber-300/10 px-4 py-2 text-xs font-bold text-amber-100">{errorText}</div>}

                    <div className="mt-5 flex flex-wrap items-center gap-3">
                        <div className="flex items-center gap-2 rounded-xl border border-white/15 bg-white/75 px-4 py-2 text-xs font-bold text-slate-500 backdrop-blur">
                            <span>에이전트</span>
                            <button type="button" onClick={() => setAgentCount((value) => Math.max(1, value - 1))} className="grid h-8 w-8 place-items-center rounded-lg border border-slate-200 bg-white text-slate-700">-</button>
                            <span className="text-xl font-black text-violet-600">{agentCount}</span>
                            <button type="button" onClick={() => setAgentCount((value) => Math.min(15, value + 1))} className="grid h-8 w-8 place-items-center rounded-lg border border-slate-200 bg-white text-slate-700">+</button>
                        </div>
                        <div className="flex items-center gap-1 rounded-xl border border-white/15 bg-white/45 p-1 backdrop-blur">
                            {agentCounts.map((count) => (
                                <button key={count} type="button" onClick={() => setAgentCount(count)} className={`h-8 min-w-8 rounded-lg px-2 text-xs font-black ${count === agentCount ? 'bg-violet-600 text-white shadow-lg shadow-violet-500/30' : 'text-slate-500 hover:bg-white/60'}`}>
                                    {count}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            </section>

            {isAnalyzing && <ImpactPanel phase={phase} run={run} />}

            <div className="grid gap-3 lg:grid-cols-3">
                {pipelineCards.map((card) => (
                    <section key={card.title} className="rounded-xl border border-white/[0.07] bg-[#141416] p-5">
                        <div className="flex items-start justify-between gap-3">
                            <span className="grid h-10 w-10 place-items-center rounded-lg bg-white/[0.06]">
                                <i className={`fas ${card.icon} ${card.color}`} />
                            </span>
                            <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11px] font-bold text-gray-400">{card.metric}</span>
                        </div>
                        <h2 className="mt-4 text-lg font-black text-white">{card.title}</h2>
                        <p className="mt-2 text-sm leading-6 text-gray-500">{card.desc}</p>
                    </section>
                ))}
            </div>

            <section className="rounded-xl border border-white/[0.07] bg-[#141416] p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                        <h2 className="text-lg font-black text-white">파이프라인 상태</h2>
                        <p className="mt-1 text-sm text-gray-500">
                            {status?.pipeline?.status || '/api/admin/mirofish/status 에서 상태를 가져옵니다. 응답 없을 때는 개발용 로컬 폴백을 사용합니다.'}
                        </p>
                    </div>
                    <span className={`rounded-full border px-3 py-1.5 text-xs font-black ${apiState === 'fallback' ? 'border-amber-500/20 bg-amber-500/10 text-amber-300' : 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300'}`}>
                        {apiState === 'fallback' ? '로컬 폴백' : 'API 연결'}
                    </span>
                </div>

                <div className="mt-5 grid gap-2 md:grid-cols-5">
                    {runSteps.map((step, index) => {
                        const ready = !isAnalyzing || index + 1 <= phase;
                        return (
                            <div key={step} className="rounded-lg border border-white/[0.06] bg-black/20 p-3">
                                <div className="flex items-center justify-between">
                                    <span className="text-[11px] font-black uppercase tracking-[0.14em] text-gray-600">단계 {index + 1}</span>
                                    <span className={`h-2 w-2 rounded-full ${ready ? 'bg-emerald-400' : 'bg-amber-400/70'}`} />
                                </div>
                                <div className="mt-3 text-sm font-bold text-white">{step}</div>
                                <div className="mt-1 text-xs text-gray-500">{ready ? '준비됨' : '대기 중'}</div>
                            </div>
                        );
                    })}
                </div>
            </section>
        </div>
    );
}
