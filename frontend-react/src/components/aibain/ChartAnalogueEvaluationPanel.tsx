import { useEffect, useId, useState } from 'react';
import { fetchChartAnalogueEvaluation, type ChartAnalogueEvaluationRecord, type ChartAnalogueEvaluationReport } from '@/lib/chartAnalogueApi';

const formatReturn = (value: number | null, points = false) => value === null ? '—'
    : `${value > 0 ? '+' : ''}${value.toFixed(2)}${points ? '%p' : '%'}`;
const formatKst = (timestamp: string) => `${new Date(Date.parse(timestamp) + 9 * 60 * 60 * 1000).toISOString().slice(0, 16).replace('T', ' ')} KST`;

function recordState(record: ChartAnalogueEvaluationRecord) {
    if (record.reason === 'intraday_excluded'
        || ['intraday', 'intraday_excluded', 'excluded_intraday'].includes(record.status)) return '장중 관측 제외';
    if (['insufficient_baseline', 'missing_forecasts', 'invalid_forecasts', 'blocked'].includes(record.status)
        || record.horizons.some(row => row.status === 'blocked')) return '선정 종목·자료 부족';
    if (['duplicate_daily_cohort', 'daily_duplicate'].includes(record.status)) return '당일 반복 관측 제외';
    if (record.horizons.some(row => row.status === 'matured')) return '기간별 관측 완료';
    return '관측 중';
}

function SelectedPicks({ title, picks }: { title: string; picks: ChartAnalogueEvaluationRecord['baseline'] }) {
    return <div className="min-w-0"><p className="mb-1.5 text-[11px] text-gray-400">{title}</p>
        {picks.length === 0 ? <p className="text-xs text-gray-500">선정 자료 없음</p>
            : <ul className="flex flex-wrap gap-1.5">{picks.map((pick, index) => <li key={`${pick.symbol}-${index}`} className="rounded-md border border-[#30363f] bg-[#101318] px-2 py-1 text-xs text-gray-200">
                {pick.target || '종목명 미확인'} <span className="font-mono text-[11px] text-gray-400">{pick.symbol}</span>
            </li>)}</ul>}
    </div>;
}

/** Global prospective comparison is loaded independently from the selected-symbol forecast. */
export default function ChartAnalogueEvaluationPanel({ token }: { token?: string }) {
    const headingId = useId();
    const [report, setReport] = useState<ChartAnalogueEvaluationReport | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [revision, setRevision] = useState(0);

    useEffect(() => {
        let active = true;
        setLoading(true);
        setError('');
        setReport(null);
        fetchChartAnalogueEvaluation(token)
            .then(result => { if (active) setReport(result); })
            .catch(() => { if (active) setError('비교 관측을 불러오지 못했습니다. 잠시 후 다시 조회해 주세요.'); })
            .finally(() => { if (active) setLoading(false); });
        return () => { active = false; };
    }, [token, revision]);

    const unavailable = report?.status === 'unavailable';
    const label = error || unavailable ? '자료 확인 불가' : !report ? '자료 확인 중' : report.counts.recorded === 0 ? '관측 대기'
        : report.horizons.some(row => row.paired_days > 0) ? '기간별 결과 누적 중' : '관측 중';
    return (
        <section aria-labelledby={headingId} className="ai-panel min-w-0 rounded-xl border border-[#30363f] p-4 sm:p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 id={headingId} className="ai-section-title text-sm">TOP3 비교 관측</h2>
                <span className="rounded border border-[#365372] bg-[#1b2c40] px-2 py-0.5 text-[11px] text-[#acd3ff]">{label}</span>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-gray-400">실제 최종 TOP3와 결정 시점에 고정한 비교 선정 TOP3의 이후 결과를 대조합니다. 비교 선정은 20관측일 중앙수익률 기준이며 기존 순위를 바꾸지 않습니다.</p>
            {loading && <p role="status" className="py-6 text-sm text-gray-400">TOP3 비교 관측 조회 중…</p>}
            {!loading && error && <div role="alert" className="mt-4 space-y-3"><p className="text-sm text-amber-200">{error}</p><button type="button" onClick={() => setRevision(value => value + 1)} className="rounded-lg border border-[#3a424d] px-3 py-2 text-xs text-gray-200">비교 관측 다시 조회</button></div>}
            {!loading && unavailable && <div className="mt-4 space-y-3"><p className="text-sm text-amber-200">비교 관측 자료를 확인할 수 없습니다</p><button type="button" onClick={() => setRevision(value => value + 1)} className="rounded-lg border border-[#3a424d] px-3 py-2 text-xs text-gray-200">비교 관측 다시 조회</button></div>}
            {!loading && report && !unavailable && <>
                <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 border-y border-[#30363f] py-3 text-xs tabular-nums text-gray-300">
                    <span>저장된 관측 {report.counts.recorded}건</span><span>유효 관측 {report.counts.eligible_days}일</span>
                    <span>진행 중 {report.counts.pending}건</span><span>자료 부족 {report.counts.blocked}건</span><span>장중 제외 {report.counts.intraday_excluded}건</span>
                </div>
                <p className="mb-3 mt-3 text-xs leading-relaxed text-gray-400">한국시간 하루 첫 유효 관측만 비교 표본에 포함합니다. 반복 실행은 날짜별 표본 수를 늘리지 않습니다.</p>
                <p className="mb-3 text-[11px] leading-relaxed text-gray-400">완료된 날짜별 비교 결과의 평균입니다. 각 TOP3는 세 종목에 동일 비중을 적용합니다.</p>
                <div className="overflow-x-auto" tabIndex={0}>
                    <table aria-label="TOP3 기간별 비교 관측" className="w-full min-w-[680px] text-right text-xs tabular-nums">
                        <thead className="text-gray-400"><tr><th className="pb-2 text-left">기간</th><th className="pb-2">비교 완료 일수</th><th className="pb-2">실제 TOP3 순수익률</th><th className="pb-2">비교 선정 순수익률</th><th className="pb-2">차이 (%p)</th><th className="pb-2">진행 / 보류 일수</th></tr></thead>
                        <tbody>{report.horizons.map(row => <tr key={row.sessions} className="border-t border-[#30363f]">
                            <th className="py-3 text-left font-medium">{row.sessions}관측일</th><td className="py-3">{row.paired_days}일</td>
                            {row.paired_days === 0 ? <td colSpan={3} className="py-3 text-center text-gray-500">{row.blocked_days > 0 && row.pending_days === 0 ? '자료 부족 · 결과 없음' : '관측 대기'}</td>
                                : <><td className="py-3">{formatReturn(row.baseline_net_return_pct)}</td><td className="py-3">{formatReturn(row.challenger_net_return_pct)}</td><td className="py-3 text-teal-200">{formatReturn(row.excess_return_pct, true)}</td></>}
                            <td className="py-3">{row.pending_days} / {row.blocked_days}</td>
                        </tr>)}</tbody>
                    </table>
                </div>
                {report.recent.length > 0 && <details className="mt-4 border-t border-[#30363f] pt-3" open>
                    <summary className="w-fit cursor-pointer text-xs font-medium text-[#acd3ff]">최근 결정과 고정한 종목</summary>
                    <ul aria-label="최근 TOP3 비교 관측" className="mt-3 space-y-3">{report.recent.map((record, index) => <li key={`${record.workflow_id}-${index}`} className="rounded-lg border border-[#30363f] p-3">
                        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-[11px]"><time dateTime={record.decision_at} className="tabular-nums text-gray-400">{formatKst(record.decision_at)}</time><span className="text-gray-300">{recordState(record)}</span></div>
                        <div className="grid gap-3 sm:grid-cols-2"><SelectedPicks title="실제 최종 TOP3" picks={record.baseline} /><SelectedPicks title="결정 시점의 비교 선정 TOP3" picks={record.challenger} /></div>
                        {record.horizons.length > 0 && <p className="mt-3 border-t border-[#30363f] pt-2 text-[11px] tabular-nums text-gray-400">{record.horizons.map(row => `${row.sessions}관측일: ${row.status === 'matured' ? `차이 ${formatReturn(row.excess_return_pct, true)}` : row.status === 'blocked' ? '자료 부족' : `${row.observed_sessions}관측일 진행`}`).join(' · ')}</p>}
                    </li>)}</ul>
                </details>}
                <p className="mt-4 text-[11px] text-gray-500">{report.evaluated_at ? `평가 시각 ${formatKst(report.evaluated_at)}` : '아직 평가 기록 없음'}</p>
            </>}
            <div className="mt-4 space-y-1.5 border-t border-[#30363f] pt-3 text-[11px] leading-relaxed text-gray-400">
                <p>연구용 왕복 비용 23bp(0.23%) · 슬리피지 10bp(0.10%) 가정입니다. 각 종목 묶음의 종가 간 수익률에서 총 0.33%를 차감합니다.</p>
                <p>종가 간 모의 비교이며 실제 체결 수익이 아닙니다. 시장 지수와의 비교는 제공하지 않습니다.</p>
                <p>가격 자료는 2026-10-01부터 수집했으며, 2026-10-01 이전 시점에 알고 있던 자료를 재현한 성과가 아닙니다. 전향 관측을 누적 중입니다.</p>
            </div>
        </section>
    );
}
