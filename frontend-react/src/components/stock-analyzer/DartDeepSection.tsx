import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE, authHeaders } from '@/lib/api';

// ── Types ──────────────────────────────────────────────────────────────────

type StepStatus = 'pending' | 'running' | 'done' | 'error';

interface StepInfo {
    key: string;
    label: string;
    status: StepStatus;
    error: string | null;
}

interface ValuationDetail {
    grade?: 'S' | 'A' | 'B' | 'C' | 'D';
    strengths?: string[];
    risks?: string[];
    one_liner?: string;
}

interface YearlyMetric {
    year: number;
    revenue_eok?: number;
    op_profit_eok?: number;
    net_income_eok?: number;
    roe_pct?: number;
    op_margin_pct?: number;
    debt_ratio_pct?: number;
}

interface Summary10yr {
    revenue_cagr_pct?: number;
    op_profit_cagr_pct?: number;
    best_year?: number;
    worst_year?: number;
    avg_roe_pct?: number;
}

interface Metrics {
    yearly?: YearlyMetric[];
    summary_10yr?: Summary10yr;
    valuation?: ValuationDetail;
}

interface DcfBlock {
    text?: string;
    executed_code?: string;
    code_output?: string;
}

interface NewsBlock {
    text?: string;
    citations?: Array<{ title: string; uri: string }>;
}

interface ReportBlock {
    url?: string;
    summary?: string;
}

interface Financials {
    stock_code: string;
    corp_code?: string;
    years: number[];
    data: Record<string, Record<string, number>>;
    source?: string;
}

interface DartDeepResult {
    stock_code: string;
    stock_name: string;
    generated_at: string;
    financials?: Financials;
    metrics?: Metrics | null;
    dcf?: DcfBlock | null;
    news?: NewsBlock | null;
    report?: ReportBlock | null;
}

interface JobStatus {
    job_id: string;
    stock_code: string;
    stock_name: string;
    status: 'running' | 'done' | 'error' | 'cached';
    started_at: string;
    steps: StepInfo[];
    error: string | null;
    result: DartDeepResult | null;
}

// ── Helpers ────────────────────────────────────────────────────────────────

const GRADE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
    S: { bg: 'bg-gradient-to-br from-yellow-300 via-amber-500 to-yellow-600', text: 'text-black', label: '최상위' },
    A: { bg: 'bg-emerald-500', text: 'text-black', label: '우수' },
    B: { bg: 'bg-blue-500', text: 'text-white', label: '양호' },
    C: { bg: 'bg-yellow-500', text: 'text-black', label: '보통' },
    D: { bg: 'bg-red-500', text: 'text-white', label: '주의' },
};

function formatEok(n?: number): string {
    if (n == null || !Number.isFinite(n)) return '--';
    if (Math.abs(n) >= 10_000) return `${(n / 10_000).toFixed(1)}조`;
    return `${n.toLocaleString('ko-KR')}억`;
}

function formatPct(n?: number, digits = 1): string {
    if (n == null || !Number.isFinite(n)) return '--';
    return `${n.toFixed(digits)}%`;
}

// ── Main component ─────────────────────────────────────────────────────────

interface Props {
    stockCode: string;
    stockName: string;
}

export default function DartDeepSection({ stockCode, stockName }: Props) {
    const [expanded, setExpanded] = useState(false);
    const [loading, setLoading] = useState(false);
    const [job, setJob] = useState<JobStatus | null>(null);
    const [error, setError] = useState<string | null>(null);
    const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

    // Cleanup on unmount
    useEffect(() => {
        return () => {
            if (pollTimer.current) clearInterval(pollTimer.current);
        };
    }, []);

    // Reset when stock changes
    useEffect(() => {
        setExpanded(false);
        setJob(null);
        setError(null);
        setLoading(false);
        if (pollTimer.current) {
            clearInterval(pollTimer.current);
            pollTimer.current = null;
        }
    }, [stockCode]);

    const startPolling = useCallback((jobId: string) => {
        if (pollTimer.current) clearInterval(pollTimer.current);
        pollTimer.current = setInterval(async () => {
            try {
                const res = await fetch(`${API_BASE}/api/stock-analyzer/dart-deep/status/${jobId}`, {
                    headers: authHeaders(),
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data: JobStatus = await res.json();
                setJob(data);
                if (data.status === 'done' || data.status === 'error') {
                    if (pollTimer.current) {
                        clearInterval(pollTimer.current);
                        pollTimer.current = null;
                    }
                    setLoading(false);
                    if (data.status === 'error') setError(data.error || '분석 실패');
                }
            } catch (e) {
                setError((e as Error).message);
                if (pollTimer.current) clearInterval(pollTimer.current);
                setLoading(false);
            }
        }, 700);
    }, []);

    const startAnalyze = useCallback(async () => {
        setLoading(true);
        setError(null);
        setJob(null);
        try {
            const res = await fetch(`${API_BASE}/api/stock-analyzer/dart-deep/analyze`, {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ stock_code: stockCode, stock_name: stockName }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

            if (data.status === 'cached' && data.result) {
                // 캐시 히트: 즉시 완료 상태 생성
                setJob({
                    job_id: data.job_id,
                    stock_code: stockCode,
                    stock_name: stockName,
                    status: 'done',
                    started_at: '',
                    steps: [],
                    error: null,
                    result: data.result as DartDeepResult,
                });
                setLoading(false);
            } else if (data.job_id) {
                startPolling(data.job_id);
            } else {
                throw new Error('잘못된 응답');
            }
        } catch (e) {
            setError((e as Error).message);
            setLoading(false);
        }
    }, [stockCode, stockName, startPolling]);

    // Auto-expand + start analysis when arrived via ?panel=dart-deep or #dart-deep
    // Note: native hash navigation handles scrolling (respects scroll-mt-24); no manual scrollIntoView
    useEffect(() => {
        if (typeof window === 'undefined') return;
        const params = new URLSearchParams(window.location.search);
        const wantsDart = params.get('panel') === 'dart-deep' || window.location.hash === '#dart-deep';
        if (wantsDart) {
            setExpanded(true);
            startAnalyze();
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [stockCode]);

    const handleToggle = useCallback(() => {
        if (!expanded) {
            setExpanded(true);
            if (!job && !loading) startAnalyze();
        } else {
            setExpanded(false);
        }
    }, [expanded, job, loading, startAnalyze]);

    const result = job?.result;
    const isDone = job?.status === 'done' && result;

    return (
        <div id="dart-deep" className="rounded-2xl bg-[#1c1c1e] border border-white/10 overflow-hidden scroll-mt-24">
            {/* Section header — clickable */}
            <button
                onClick={handleToggle}
                className="w-full px-4 md:px-6 py-4 flex items-center gap-3 text-left hover:bg-white/[0.02] transition-colors"
            >
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center shrink-0">
                    <i className="fas fa-brain text-white text-base" />
                </div>
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="text-base md:text-lg font-bold text-white">10년 재무제표 심층분석</h3>
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 font-bold">AI</span>
                    </div>
                    <p className="text-[11px] text-gray-500 mt-0.5">
                        DART 10년 × Gemini 6단계 · DCF 적정가치 · 뉴스 교차검증
                    </p>
                </div>
                <i className={`fas fa-chevron-down text-xs text-gray-500 transition-transform ${expanded ? 'rotate-180' : ''}`} />
            </button>

            {/* Body */}
            {expanded && (
                <div className="border-t border-white/[0.06] px-4 md:px-6 py-5 space-y-4">
                    {/* Loading with step checklist */}
                    {loading && job && job.steps.length > 0 && (
                        <StepChecklist steps={job.steps} />
                    )}
                    {loading && (!job || job.steps.length === 0) && (
                        <div className="flex items-center justify-center py-8 text-gray-500 text-sm">
                            <div className="w-5 h-5 border-2 border-purple-500/40 border-t-purple-500 rounded-full animate-spin mr-3" />
                            분석 시작 중…
                        </div>
                    )}

                    {/* Error */}
                    {error && !loading && (
                        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                            <i className="fas fa-exclamation-triangle mr-2" />
                            {error}
                            <button
                                onClick={startAnalyze}
                                className="ml-3 text-xs underline hover:text-red-300"
                            >
                                다시 시도
                            </button>
                        </div>
                    )}

                    {/* Results */}
                    {isDone && result && <DartDeepResultView result={result} />}
                </div>
            )}
        </div>
    );
}

// ── Sub-components ─────────────────────────────────────────────────────────

function StepChecklist({ steps }: { steps: StepInfo[] }) {
    const doneCount = steps.filter(s => s.status === 'done').length;
    const pct = Math.round((doneCount / steps.length) * 100);

    return (
        <div className="space-y-3">
            <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400 font-semibold">AI 분석 진행 중…</span>
                <span className="text-xs text-purple-300 font-bold tabular-nums">{pct}%</span>
            </div>
            <div className="h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
                <div
                    className="h-full bg-gradient-to-r from-purple-500 to-indigo-500 transition-all duration-500"
                    style={{ width: `${pct}%` }}
                />
            </div>
            <div className="space-y-1.5 pt-1">
                {steps.map(step => {
                    const icon =
                        step.status === 'done' ? 'fa-check text-emerald-400' :
                        step.status === 'running' ? 'fa-spinner fa-spin text-purple-400' :
                        step.status === 'error' ? 'fa-times text-red-400' :
                        'fa-circle text-gray-700';
                    return (
                        <div key={step.key} className="flex items-center gap-2.5 text-xs">
                            <i className={`fas ${icon} w-3 text-center`} />
                            <span className={step.status === 'done' ? 'text-gray-300' : step.status === 'running' ? 'text-white font-medium' : 'text-gray-600'}>
                                {step.label}
                            </span>
                            {step.error && (
                                <span className="text-[10px] text-red-400 truncate">· {step.error}</span>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

function DartDeepResultView({ result }: { result: DartDeepResult }) {
    const { metrics, dcf, news, report, financials } = result;
    const grade = metrics?.valuation?.grade;
    const gradeStyle = grade ? GRADE_STYLES[grade] : null;

    return (
        <div className="space-y-5">
            {/* Valuation hero card */}
            {metrics?.valuation && (
                <div className="p-4 md:p-5 rounded-2xl bg-[#13151f] border border-white/[0.07]">
                    <div className="flex items-center gap-3 mb-3">
                        {gradeStyle && (
                            <div className={`w-14 h-14 rounded-2xl ${gradeStyle.bg} flex items-center justify-center shrink-0`}>
                                <span className={`text-3xl font-black ${gradeStyle.text}`}>{grade}</span>
                            </div>
                        )}
                        <div className="min-w-0 flex-1">
                            <div className="text-[10px] text-gray-500 uppercase tracking-widest font-semibold">AI 투자등급</div>
                            <div className="text-base font-bold text-white mt-0.5">
                                {gradeStyle?.label || '--'}
                            </div>
                        </div>
                    </div>
                    {metrics.valuation.one_liner && (
                        <p className="text-sm text-gray-300 leading-relaxed">{metrics.valuation.one_liner}</p>
                    )}
                </div>
            )}

            {/* 강점 / 리스크 */}
            {metrics?.valuation && (metrics.valuation.strengths?.length || metrics.valuation.risks?.length) && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {metrics.valuation.strengths && metrics.valuation.strengths.length > 0 && (
                        <div className="p-4 rounded-2xl bg-emerald-500/5 border border-emerald-500/20">
                            <div className="flex items-center gap-2 mb-2">
                                <i className="fas fa-arrow-up text-emerald-400 text-xs" />
                                <span className="text-xs font-bold text-emerald-400 tracking-wide">강점</span>
                            </div>
                            <ul className="space-y-1.5">
                                {metrics.valuation.strengths.map((s, i) => (
                                    <li key={i} className="text-xs text-gray-300 flex gap-2">
                                        <span className="text-emerald-500 shrink-0">•</span>
                                        <span>{s}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                    {metrics.valuation.risks && metrics.valuation.risks.length > 0 && (
                        <div className="p-4 rounded-2xl bg-red-500/5 border border-red-500/20">
                            <div className="flex items-center gap-2 mb-2">
                                <i className="fas fa-arrow-down text-red-400 text-xs" />
                                <span className="text-xs font-bold text-red-400 tracking-wide">리스크</span>
                            </div>
                            <ul className="space-y-1.5">
                                {metrics.valuation.risks.map((r, i) => (
                                    <li key={i} className="text-xs text-gray-300 flex gap-2">
                                        <span className="text-red-500 shrink-0">•</span>
                                        <span>{r}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                </div>
            )}

            {/* 10yr summary */}
            {metrics?.summary_10yr && (
                <div className="p-4 rounded-2xl bg-[#13151f] border border-white/[0.07]">
                    <div className="text-[10px] text-gray-500 uppercase tracking-widest font-semibold mb-3">10년 요약</div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <StatTile label="매출 CAGR" value={formatPct(metrics.summary_10yr.revenue_cagr_pct)} accent="text-blue-400" />
                        <StatTile label="영업이익 CAGR" value={formatPct(metrics.summary_10yr.op_profit_cagr_pct)} accent="text-emerald-400" />
                        <StatTile label="평균 ROE" value={formatPct(metrics.summary_10yr.avg_roe_pct)} accent="text-purple-400" />
                        <StatTile label="최고/최악" value={`${metrics.summary_10yr.best_year ?? '-'}/${metrics.summary_10yr.worst_year ?? '-'}`} accent="text-gray-300" />
                    </div>
                </div>
            )}

            {/* Yearly table */}
            {metrics?.yearly && metrics.yearly.length > 0 && (
                <div className="rounded-2xl bg-[#13151f] border border-white/[0.07] overflow-hidden">
                    <div className="px-4 pt-4 pb-2 text-[10px] text-gray-500 uppercase tracking-widest font-semibold">
                        연도별 실적 · 단위: 억원
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                            <thead>
                                <tr className="text-[10px] text-gray-600 uppercase">
                                    <th className="text-left px-4 py-2 font-semibold">연도</th>
                                    <th className="text-right px-4 py-2 font-semibold">매출</th>
                                    <th className="text-right px-4 py-2 font-semibold">영업이익</th>
                                    <th className="text-right px-4 py-2 font-semibold">순이익</th>
                                    <th className="text-right px-4 py-2 font-semibold">ROE</th>
                                    <th className="text-right px-4 py-2 font-semibold">영익률</th>
                                </tr>
                            </thead>
                            <tbody>
                                {metrics.yearly.map(y => (
                                    <tr key={y.year} className="border-t border-white/[0.04]">
                                        <td className="px-4 py-2 text-gray-300 font-mono">{y.year}</td>
                                        <td className="px-4 py-2 text-right text-white tabular-nums">{formatEok(y.revenue_eok)}</td>
                                        <td className="px-4 py-2 text-right text-white tabular-nums">{formatEok(y.op_profit_eok)}</td>
                                        <td className="px-4 py-2 text-right text-white tabular-nums">{formatEok(y.net_income_eok)}</td>
                                        <td className="px-4 py-2 text-right text-purple-300 tabular-nums">{formatPct(y.roe_pct)}</td>
                                        <td className="px-4 py-2 text-right text-emerald-300 tabular-nums">{formatPct(y.op_margin_pct)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* DCF */}
            {dcf && (dcf.text || dcf.code_output) && (
                <div className="rounded-2xl bg-[#13151f] border border-white/[0.07] overflow-hidden">
                    <div className="px-4 pt-4 pb-2 flex items-center gap-2">
                        <i className="fas fa-calculator text-indigo-400 text-xs" />
                        <span className="text-[10px] text-gray-500 uppercase tracking-widest font-semibold">DCF 적정가치</span>
                    </div>
                    {dcf.text && (
                        <p className="px-4 pb-3 text-sm text-gray-300 whitespace-pre-wrap leading-relaxed">{dcf.text}</p>
                    )}
                    {dcf.code_output && (
                        <pre className="mx-4 mb-3 p-3 rounded-lg bg-black/40 border border-white/5 text-[10px] text-emerald-300 font-mono overflow-x-auto whitespace-pre">{dcf.code_output}</pre>
                    )}
                    {dcf.executed_code && (
                        <details className="mx-4 mb-4">
                            <summary className="text-[10px] text-gray-600 cursor-pointer hover:text-gray-400">실행된 파이썬 코드 보기</summary>
                            <pre className="mt-2 p-3 rounded-lg bg-black/40 border border-white/5 text-[10px] text-gray-400 font-mono overflow-x-auto whitespace-pre">{dcf.executed_code}</pre>
                        </details>
                    )}
                </div>
            )}

            {/* News cross-check */}
            {news && news.text && (
                <div className="p-4 rounded-2xl bg-[#13151f] border border-white/[0.07]">
                    <div className="flex items-center gap-2 mb-3">
                        <i className="fas fa-newspaper text-amber-400 text-xs" />
                        <span className="text-[10px] text-gray-500 uppercase tracking-widest font-semibold">뉴스 교차검증</span>
                    </div>
                    <div className="text-sm text-gray-300 whitespace-pre-wrap leading-relaxed">{news.text}</div>
                    {news.citations && news.citations.length > 0 && (
                        <div className="mt-3 pt-3 border-t border-white/[0.05]">
                            <div className="text-[10px] text-gray-600 mb-1.5">출처</div>
                            <div className="flex flex-wrap gap-1.5">
                                {news.citations.slice(0, 8).map((c, i) => (
                                    <a
                                        key={i}
                                        href={c.uri}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="text-[10px] px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-blue-300 truncate max-w-[200px]"
                                        title={c.title}
                                    >
                                        {c.title || new URL(c.uri).hostname}
                                    </a>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Report */}
            {report && report.summary && report.summary.length > 20 && (
                <div className="p-4 rounded-2xl bg-[#13151f] border border-white/[0.07]">
                    <div className="flex items-center gap-2 mb-3">
                        <i className="fas fa-file-lines text-cyan-400 text-xs" />
                        <span className="text-[10px] text-gray-500 uppercase tracking-widest font-semibold">사업보고서 요약</span>
                    </div>
                    <p className="text-sm text-gray-300 whitespace-pre-wrap leading-relaxed">{report.summary}</p>
                </div>
            )}

            {/* Footer — data provenance */}
            <div className="flex items-center justify-between text-[10px] text-gray-600 pt-2 border-t border-white/[0.04]">
                <span>
                    <i className="fas fa-database mr-1" />
                    DART {financials?.years?.length ?? 0}년치 · {financials?.source || '연결/개별'}
                </span>
                <span>
                    생성: {new Date(result.generated_at).toLocaleString('ko-KR')}
                </span>
            </div>
        </div>
    );
}

function StatTile({ label, value, accent }: { label: string; value: string; accent: string }) {
    return (
        <div>
            <div className="text-[9px] text-gray-600 uppercase tracking-wider mb-0.5">{label}</div>
            <div className={`text-base font-bold tabular-nums ${accent}`}>{value}</div>
        </div>
    );
}
