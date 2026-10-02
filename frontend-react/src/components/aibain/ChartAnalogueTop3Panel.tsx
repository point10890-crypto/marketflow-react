import { useEffect, useId, useRef, useState } from 'react';
import { fetchChartAnalogueTop3, startChartAnalogueTop3, type ChartAnalogueTop3Envelope } from '@/lib/chartAnalogueApi';
import { formatAnaloguePrice, formatAnalogueReturn } from './ChartAnalogueChart';

const failureLabels: Record<string, string> = {
    missing_index: '가격 색인이 준비되지 않아 자동 TOP3를 검출할 수 없습니다.',
    invalid_index: '가격 색인 자료를 확인할 수 없어 검출을 보류했습니다.',
    stale_data: '가격 자료가 오래되어 자동 TOP3 검출을 보류했습니다.',
    failed: '자동 TOP3 검출을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.',
};
const timestamp = (value: string) => `${new Date(value).toISOString().slice(0, 19).replace('T', ' ')} UTC`;

export default function ChartAnalogueTop3Panel({ token }: { token?: string }) {
    const headingId = useId();
    const [snapshot, setSnapshot] = useState<ChartAnalogueTop3Envelope | null>(null);
    const [reading, setReading] = useState(true);
    const [posting, setPosting] = useState(false);
    const [requestError, setRequestError] = useState('');
    const requestId = useRef(0);
    const mounted = useRef(false);

    function accept(result: ChartAnalogueTop3Envelope) {
        setSnapshot(previous => ({ ...result, report: result.report
            ?? (['running', 'error'].includes(result.state) ? previous?.report ?? null : null) }));
    }

    useEffect(() => {
        mounted.current = true;
        let active = true;
        const id = ++requestId.current;
        setReading(true);
        setPosting(false);
        setSnapshot(null);
        setRequestError('');
        fetchChartAnalogueTop3(token)
            .then(result => { if (active && id === requestId.current) accept(result); })
            .catch(() => { if (active && id === requestId.current) setRequestError('자동 TOP3 상태를 불러오지 못했습니다. 검출 버튼으로 다시 시도해 주세요.'); })
            .finally(() => { if (active && id === requestId.current) setReading(false); });
        return () => { active = false; mounted.current = false; ++requestId.current; };
    }, [token]);

    const state = snapshot?.state;
    useEffect(() => {
        if (state !== 'running') return;
        let active = true;
        let timer: ReturnType<typeof setTimeout>;
        const poll = async () => {
            const id = ++requestId.current;
            try {
                const result = await fetchChartAnalogueTop3(token);
                if (!active || id !== requestId.current) return;
                accept(result);
                if (result.state === 'running') timer = setTimeout(poll, 4000);
            } catch {
                if (!active || id !== requestId.current) return;
                setRequestError('자동 TOP3 진행 상태를 불러오지 못했습니다. 검출 버튼으로 다시 시도해 주세요.');
                setSnapshot(previous => previous ? { ...previous, state: 'error' } : previous);
            }
        };
        timer = setTimeout(poll, 4000);
        return () => { active = false; clearTimeout(timer); };
    }, [state, token]);

    async function start() {
        if (reading || posting || state === 'running') return;
        const id = ++requestId.current;
        setPosting(true);
        setRequestError('');
        try {
            const result = await startChartAnalogueTop3(token);
            if (mounted.current && id === requestId.current) accept(result);
        } catch {
            if (mounted.current && id === requestId.current) setRequestError('자동 TOP3 검출을 시작하지 못했습니다. 잠시 후 다시 시도해 주세요.');
        } finally {
            if (mounted.current && id === requestId.current) setPosting(false);
        }
    }

    const report = snapshot?.report;
    const running = state === 'running';
    const previous = !!report && snapshot?.freshness !== 'current';
    const problem = requestError || (state === 'error'
        ? failureLabels[snapshot?.error ?? ''] ?? failureLabels[report?.status ?? 'failed'] ?? failureLabels.failed
        : report && !['ready', 'insufficient_candidates'].includes(report.status) ? failureLabels[report.status] : '');
    return <section aria-labelledby={headingId} className="ai-panel min-w-0 border border-[#30363f] p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h2 id={headingId} className="ai-section-title text-base">차트 자동 TOP3</h2><p className="mt-1 text-xs leading-relaxed text-gray-400">색인에 포함된 전 종목에서 20관측일 분포와 하락 위험 기준을 통과한 연구 후보입니다.</p></div>
            <button type="button" onClick={start} disabled={reading || posting || running} className="min-h-11 shrink-0 rounded-lg border border-[#365372] bg-[#1b2c40] px-4 text-sm font-semibold text-[#acd3ff] hover:bg-[#243c56] disabled:cursor-wait disabled:opacity-60">자동 TOP3 검출</button>
        </div>
        {reading && <p role="status" className="py-5 text-sm text-gray-400">저장된 TOP3 확인 중…</p>}
        {(posting || running) && <p role="status" className="mt-4 rounded-lg border border-[#365372] bg-[#1b2c40] px-3 py-2 text-xs tabular-nums text-[#acd3ff]">{running && snapshot && snapshot.total > 0 ? `전체 종목 검출 중 · ${snapshot.processed} / ${snapshot.total}` : '검출 작업을 준비 중입니다…'}</p>}
        {problem && <p role="alert" className="mt-4 rounded-lg border border-amber-400/20 bg-amber-400/[0.04] px-3 py-2 text-xs leading-relaxed text-amber-200">{problem}</p>}
        {previous && <p className="mt-4 rounded-lg border border-amber-400/20 bg-amber-400/[0.04] px-3 py-2 text-xs leading-relaxed text-amber-200">저장된 결과가 최신 가격 색인과 다릅니다. 아래는 이전 결과이며 새 검출이 끝날 때까지 최신 결과로 해석하지 마세요.</p>}
        {!reading && !report && !problem && !running && !posting && <p className="py-5 text-sm text-gray-400">저장된 자동 TOP3 결과가 없습니다</p>}
        {report && <>
            <div className="mb-4 mt-4 flex flex-wrap gap-x-4 gap-y-1 text-[11px] tabular-nums text-gray-400"><span>생성 {timestamp(report.generated_at)}</span><span>분석 기준 {timestamp(report.as_of)}</span><span>전체 색인 {report.universe.indexed.toLocaleString('ko-KR')}종목 · 검사 {report.universe.processed.toLocaleString('ko-KR')}종목 · 통과 {report.universe.eligible}종목</span></div>
            {report.source?.name && <p className="mb-4 break-all text-[11px] text-gray-400">자료 {report.source.name}{report.source.source_id ? ` · ${report.source.source_id}` : ''}{report.source.price_basis === 'provider_adjusted' ? ' · 공급자 수정주가 · 확정 일봉' : ''}</p>}
            {report.status === 'insufficient_candidates' && <p className="mb-4 text-xs text-amber-200">기준을 충족한 후보가 {report.candidates.length}개뿐입니다. 부족한 자리를 다른 종목으로 채우지 않습니다.</p>}
            <div className="grid min-w-0 gap-3 lg:grid-cols-3">{[...report.candidates].sort((a, b) => a.rank - b.rank).map(candidate => <article key={candidate.symbol} aria-label={`자동 TOP3 ${candidate.rank}위 ${candidate.target}`} className="min-w-0 rounded-xl border border-[#3a424d] bg-[#101318] p-4">
                <div className="flex items-start justify-between gap-2"><div><span className="text-[11px] font-semibold text-[#acd3ff]">#{candidate.rank} · KR</span><h3 className="mt-1 break-words text-base font-semibold">{candidate.target}</h3><p className="font-mono text-xs text-gray-400">{candidate.symbol}</p></div><div className="text-right"><p className="text-[10px] text-gray-400">연구 점수</p><p className="font-mono text-lg tabular-nums text-teal-200">{candidate.score.toFixed(2)}</p></div></div>
                <dl className="mt-4 grid grid-cols-2 gap-x-3 gap-y-3 text-xs tabular-nums">
                    <div><dt className="text-[10px] text-gray-400">20관측일 중앙 수익률</dt><dd className="mt-1 font-medium">{formatAnalogueReturn(candidate.horizon.median_return_pct)}</dd></div>
                    <div><dt className="text-[10px] text-gray-400">과거 상승 빈도</dt><dd className="mt-1 font-medium">{candidate.horizon.up_frequency_pct.toFixed(1)}%</dd></div>
                    <div><dt className="text-[10px] text-gray-400">하락 쪽 10백분위</dt><dd className="mt-1 font-medium">{formatAnalogueReturn(candidate.horizon.p10_return_pct)}</dd></div>
                    <div><dt className="text-[10px] text-gray-400">상승 쪽 90백분위</dt><dd className="mt-1 font-medium">{formatAnalogueReturn(candidate.horizon.p90_return_pct)}</dd></div>
                </dl>
                <p className="mt-4 border-t border-[#30363f] pt-3 text-[11px] leading-relaxed text-gray-400">표본 {candidate.sample_count}개 · {candidate.distinct_symbols}종목<br />유사도 중앙값 {(candidate.median_similarity * 100).toFixed(1)}% · 위험 감점 후 점수 양수</p>
                <p className="mt-2 text-[11px] tabular-nums text-gray-400">{candidate.latest_session} 종가 {formatAnaloguePrice(candidate.close)}</p>
                <p className="mt-1 text-[11px] tabular-nums text-gray-400">자료 수집 {timestamp(candidate.query_captured_at)}</p>
                <a href={`/dashboard/ai-bain/chart-predict?code=${candidate.symbol}`} className="mt-3 flex min-h-11 items-center justify-center rounded-lg border border-[#365372] text-xs font-semibold text-[#acd3ff] hover:bg-[#1b2c40]">상세 차트 · 근거 보기</a>
            </article>)}</div>
        </>}
        <details className="mt-4 border-t border-[#30363f] pt-3 text-[11px] leading-relaxed text-gray-400"><summary className="w-fit cursor-pointer text-xs font-medium text-[#acd3ff]">선정 기준 · 해석</summary><div className="mt-3 space-y-2"><p>신선한 공급자 수정주가의 확정 일봉만 사용합니다. 표본 20개 이상, 과거 사례 5종목 이상, 상승 빈도 60% 이상, 10백분위 -12% 이상, 유사도 중앙값 80% 이상을 요구합니다.</p><p>연구 점수 = 20관측일 중앙 수익률 − 왕복 비용·슬리피지 0.33% − 하락 쪽 10백분위 손실의 절반입니다. 점수가 양수인 종목만 남깁니다. 상승 빈도와 유사도는 보정된 예측 확률이 아닙니다.</p><p>일별 작업이 저장한 결과를 불러옵니다. 버튼은 같은 색인의 완료 결과를 재사용하고, 새 색인에서는 검출을 시작합니다. 매매 지시가 아니며 현재 수급·공시·리스크를 함께 확인해야 합니다. 기존 알파 스캐너와 CIO 순위는 바꾸지 않습니다.</p></div></details>
    </section>;
}
