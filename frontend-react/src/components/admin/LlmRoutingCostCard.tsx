import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
    type MiroFishLlmHealthStatus,
    type MiroFishLlmRoutingStatus,
    type MiroFishLlmUsageGroup,
    type MiroFishLlmUsageResponse,
    mirofishApi,
} from '@/lib/mirofishApi';


const integerFormatter = new Intl.NumberFormat('ko-KR');

function percent(value: number | null) {
    return value === null || !Number.isFinite(value) ? '미확인' : `${(value * 100).toFixed(1)}%`;
}

function tokenValue(value: number | null | undefined) {
    return value === null || value === undefined ? '사용량 미확인' : integerFormatter.format(value);
}

function costValue(value: string | null | undefined) {
    return value === null || value === undefined ? '비용 미확인' : `$${value}`;
}

function healthLabel(status: MiroFishLlmHealthStatus) {
    const labels: Record<MiroFishLlmHealthStatus, string> = {
        healthy: '정상',
        authentication: '인증 실패 · 백업 사용 중',
        billing: '결제 상태 확인 필요 · 백업 사용 중',
        insufficient_balance: '잔액 부족 · 백업 사용 중',
        rate_limit: '호출 제한 · 백업 사용 중',
        timeout: '응답 지연 · 백업 사용 중',
        connection: '연결 실패 · 백업 사용 중',
        server_error: '제공자 장애 · 백업 사용 중',
        model_unavailable: '모델 사용 불가 · 백업 사용 중',
        unavailable: '사용 불가 · 백업 사용 중',
        unknown: '상태 미확인',
    };
    return labels[status];
}

function spendSort(left: MiroFishLlmUsageGroup, right: MiroFishLlmUsageGroup) {
    const leftUnknown = left.estimated_cost_usd === null;
    const rightUnknown = right.estimated_cost_usd === null;
    if (leftUnknown !== rightUnknown) return leftUnknown ? 1 : -1;
    const leftCost = Number(left.known_estimated_cost_usd || 0);
    const rightCost = Number(right.known_estimated_cost_usd || 0);
    if (leftCost !== rightCost) return rightCost - leftCost;
    const leftUnknownUsage = left.total_tokens === null;
    const rightUnknownUsage = right.total_tokens === null;
    if (leftUnknownUsage !== rightUnknownUsage) return leftUnknownUsage ? 1 : -1;
    if (left.known_total_tokens !== right.known_total_tokens) {
        return right.known_total_tokens - left.known_total_tokens;
    }
    return String(left.endpoint || left.operation || '').localeCompare(
        String(right.endpoint || right.operation || ''),
    );
}

export default function LlmRoutingCostCard() {
    const [status, setStatus] = useState<MiroFishLlmRoutingStatus | null>(null);
    const [usage, setUsage] = useState<MiroFishLlmUsageResponse | null>(null);
    const [statusError, setStatusError] = useState(false);
    const [usageError, setUsageError] = useState(false);
    const [loading, setLoading] = useState(true);
    const mountedRef = useRef(false);
    const requestRef = useRef(0);

    const refresh = useCallback(async () => {
        const request = ++requestRef.current;
        setLoading(true);
        const [statusResult, usageResult] = await Promise.allSettled([
            mirofishApi.getLlmRoutingStatus(),
            mirofishApi.getLlmUsage({ days: 1, limit: 20 }),
        ]);
        if (!mountedRef.current || request !== requestRef.current) return;

        if (statusResult.status === 'fulfilled') {
            setStatus(statusResult.value);
            setStatusError(false);
        } else {
            setStatusError(true);
        }
        if (usageResult.status === 'fulfilled') {
            setUsage(usageResult.value);
            setUsageError(false);
        } else {
            setUsageError(true);
        }
        setLoading(false);
    }, []);

    useEffect(() => {
        mountedRef.current = true;
        void refresh();
        return () => {
            mountedRef.current = false;
        };
    }, [refresh]);

    const endpointRows = useMemo(
        () => [...(usage?.top_cost_endpoints || [])].sort(spendSort).slice(0, 5),
        [usage],
    );
    const operationRows = useMemo(
        () => [...(usage?.top_operations || [])].sort(spendSort).slice(0, 4),
        [usage],
    );
    const budget = status?.budget;
    const budgetPercent = budget?.usage_percent;
    const boundedBudgetPercent = budgetPercent === null || budgetPercent === undefined
        ? null
        : Math.max(0, Math.min(100, budgetPercent));

    return (
        <section
            aria-label="LLM 라우팅 비용"
            className="rounded-xl border border-cyan-300/15 bg-black/[.03] p-3 text-slate-200"
        >
            <div className="flex items-start justify-between gap-3">
                <div>
                    <h2 className="text-sm font-black text-slate-100">LLM 라우팅 비용</h2>
                    <p className="mt-0.5 text-[11px] text-slate-500">UTC 오늘 · 실제 라우팅 원장</p>
                </div>
                <div className="flex items-center gap-2">
                    {status && (
                        <span className="rounded-md border border-white/10 px-1.5 py-1 text-[10px] text-slate-400">
                            health {status.freshness.status}
                        </span>
                    )}
                    <button
                        type="button"
                        aria-label="LLM 라우팅 비용 새로고침"
                        onClick={() => void refresh()}
                        disabled={loading}
                        className="rounded-md border border-cyan-300/20 px-2 py-1 text-[11px] font-bold text-cyan-200 hover:bg-cyan-300/10 disabled:cursor-wait disabled:opacity-50"
                    >
                        {loading ? '조회 중' : '새로고침'}
                    </button>
                </div>
            </div>

            {(statusError || usageError) && (
                <div role="status" className="mt-2 rounded-md border border-amber-300/15 bg-amber-300/[.05] px-2 py-1.5 text-[11px] text-amber-100">
                    {statusError && <div>{status ? '상태 조회 실패 · 마지막 정상 데이터' : '상태 조회 실패'}</div>}
                    {usageError && <div>{usage ? '사용량 조회 실패 · 마지막 정상 데이터' : '사용량 조회 실패'}</div>}
                </div>
            )}

            <div className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-white/10 bg-white/10">
                <div className="bg-slate-950/80 p-2.5">
                    <div className="text-[10px] text-slate-500">총 토큰</div>
                    <div className="mt-1 text-lg font-black tabular-nums text-slate-100">
                        {usage ? tokenValue(usage.totals.total_tokens) : '—'}
                    </div>
                    {usage && (
                        <div className="mt-1 text-[10px] leading-4 text-slate-500">
                            입력 {tokenValue(usage.totals.input_tokens)} · 출력 {tokenValue(usage.totals.output_tokens)}<br />
                            캐시 {tokenValue(usage.totals.cached_input_tokens)} · 추론 {tokenValue(usage.totals.reasoning_tokens)}
                        </div>
                    )}
                </div>
                <div className="bg-slate-950/80 p-2.5">
                    <div className="text-[10px] text-slate-500">확인된 비용</div>
                    <div className="mt-1 text-lg font-black tabular-nums text-emerald-200">
                        {usage ? costValue(usage.totals.estimated_cost_usd) : '—'}
                    </div>
                    {usage && (
                        <div className="mt-1 text-[10px] leading-4 text-slate-500">
                            <span className="sr-only">OpenAI 비중 </span>
                            <span>호출 {percent(usage.openai_shares.attempts)}</span><br />
                            <span>토큰 {percent(usage.openai_shares.tokens)}</span><br />
                            <span>비용 {percent(usage.openai_shares.cost)}</span>
                        </div>
                    )}
                </div>
            </div>

            {usage && (
                <div className="mt-2 grid gap-1 text-[11px] text-slate-300 sm:grid-cols-2">
                    <div className="rounded-md border border-white/8 bg-white/[.025] px-2 py-1.5">
                        Fallback {usage.fallback_count}회 · {percent(usage.fallback_attempt_share)}
                    </div>
                    <div className="rounded-md border border-white/8 bg-white/[.025] px-2 py-1.5">
                        {usage.hold_review.available && usage.hold_review.count !== null
                            ? `HOLD_REVIEW ${usage.hold_review.count}회`
                            : 'HOLD_REVIEW 미집계'}
                    </div>
                </div>
            )}

            <div className="mt-3">
                {budget?.daily_cap_usd_configured && boundedBudgetPercent !== null ? (
                    <>
                        <div className="flex justify-between gap-2 text-[10px] text-slate-400">
                            <span>OpenAI 일일 비용</span>
                            <span className="tabular-nums">{costValue(budget.used_usd)} / {costValue(budget.daily_cap_usd)}</span>
                        </div>
                        <div
                            role="progressbar"
                            aria-label="OpenAI 일일 비용 예산 사용률"
                            aria-valuemin={0}
                            aria-valuemax={100}
                            aria-valuenow={boundedBudgetPercent}
                            className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-800"
                        >
                            <div
                                className="h-full rounded-full bg-cyan-300"
                                style={{ width: `${boundedBudgetPercent}%` }}
                            />
                        </div>
                    </>
                ) : budget?.daily_cap_usd_configured ? (
                    <div className="text-[10px] text-amber-200">
                        {budget.status === 'invalid_configuration' ? '예산 설정 확인 필요' : '예산 사용량 미확인'}
                    </div>
                ) : (
                    <div className="text-[10px] text-slate-500">일일 비용 상한 미설정</div>
                )}
            </div>

            {status && (
                <div className="mt-3 space-y-1 border-t border-white/8 pt-2">
                    {status.providers.map((provider) => (
                        <div key={`${provider.provider}:${provider.operation}`} className="flex items-start justify-between gap-2 text-[10px]">
                            <span className="min-w-0 truncate text-slate-400">{provider.provider} · {provider.model}</span>
                            <span className={provider.status === 'healthy' ? 'text-emerald-200' : 'text-amber-200'}>
                                {healthLabel(provider.status)}
                            </span>
                        </div>
                    ))}
                    <div className="flex flex-wrap gap-1 pt-1">
                        {status.breakers.map((breaker) => (
                            <span
                                key={`${breaker.provider}:${breaker.modality}:${breaker.model_tier}`}
                                aria-label={`${breaker.provider} ${breaker.modality} breaker ${breaker.state}`}
                                className="rounded border border-white/10 px-1.5 py-0.5 text-[10px] text-slate-400"
                            >
                                breaker {breaker.state}
                            </span>
                        ))}
                    </div>
                </div>
            )}

            <div className="mt-3 grid gap-3 xl:grid-cols-2">
                <table aria-label="LLM 엔드포인트별 비용" className="w-full table-fixed text-left text-[10px]">
                    <thead className="text-slate-500">
                        <tr>
                            <th className="w-[48%] pb-1 font-medium">엔드포인트</th>
                            <th className="w-[27%] pb-1 font-medium">토큰</th>
                            <th className="pb-1 text-right font-medium">비용</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-white/[.06]">
                        {endpointRows.map((row) => (
                            <tr key={row.endpoint}>
                                <td className="truncate py-1.5 pr-2 text-slate-300" title={row.endpoint}>{row.endpoint}</td>
                                <td className="py-1.5 tabular-nums text-slate-400">{tokenValue(row.total_tokens)}</td>
                                <td className="py-1.5 text-right tabular-nums text-slate-300">{costValue(row.estimated_cost_usd)}</td>
                            </tr>
                        ))}
                        {!endpointRows.length && (
                            <tr><td colSpan={3} className="py-2 text-slate-500">기록 없음</td></tr>
                        )}
                    </tbody>
                </table>

                <table aria-label="LLM 작업별 비용" className="w-full table-fixed text-left text-[10px]">
                    <thead className="text-slate-500">
                        <tr>
                            <th className="w-[48%] pb-1 font-medium">작업</th>
                            <th className="w-[27%] pb-1 font-medium">토큰</th>
                            <th className="pb-1 text-right font-medium">비용</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-white/[.06]">
                        {operationRows.map((row) => (
                            <tr key={row.operation}>
                                <td className="truncate py-1.5 pr-2 text-slate-300">{row.operation}</td>
                                <td className="py-1.5 tabular-nums text-slate-400">{tokenValue(row.total_tokens)}</td>
                                <td className="py-1.5 text-right tabular-nums text-slate-300">{costValue(row.estimated_cost_usd)}</td>
                            </tr>
                        ))}
                        {!operationRows.length && (
                            <tr><td colSpan={3} className="py-2 text-slate-500">기록 없음</td></tr>
                        )}
                    </tbody>
                </table>
            </div>
        </section>
    );
}
