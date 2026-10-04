import '@/pages/dashboard/ai-design.css';
import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { fetchChartAnalogue, type ChartAnaloguePrediction, type ChartAnalogueStatus } from '@/lib/chartAnalogueApi';
import AiBrainServiceTabs from '@/components/aibain/AiBrainServiceTabs';
import ChartAnalogueChart, { formatAnaloguePrice, formatAnalogueReturn } from '@/components/aibain/ChartAnalogueChart';
import ChartAnalogueEvaluationPanel from '@/components/aibain/ChartAnalogueEvaluationPanel';
import ChartAnalogueSymbolSearch from '@/components/aibain/ChartAnalogueSymbolSearch';
import ChartAnalogueTop3Panel from '@/components/aibain/ChartAnalogueTop3Panel';
import ChartAnalogueKellyPanel from '@/components/aibain/ChartAnalogueKellyPanel';
import AlphaLabPanel from '@/components/aibain/AlphaLabPanel';

const stateLabels: Record<Exclude<ChartAnalogueStatus, 'ready'>, { title: string; detail: string }> = {
    missing_index: { title: '과거 사례 색인이 준비되지 않았습니다', detail: '가격 자료의 색인이 준비되면 유사 사례를 조회할 수 있습니다.' },
    stale_data: { title: '가격 데이터가 오래되었습니다', detail: '최근 거래일 자료가 갱신될 때까지 관측 분포를 표시하지 않습니다.' },
    insufficient_history: { title: '가격 이력이 부족합니다', detail: '분석에 필요한 일별 종가 이력이 충분하지 않습니다.' },
    insufficient_analogues: { title: '유사 사례 표본이 부족합니다', detail: '기간별 결과를 계산할 수 있는 중복이 제거된 과거 사례가 부족합니다.' },
    unavailable: { title: '현재 유사 사례 분석을 사용할 수 없습니다', detail: '자료를 확인할 수 없어 관측 분포를 표시하지 않습니다. 잠시 후 다시 조회해 주세요.' },
};
const timestamp = (value?: string) => value ? `${value.slice(0, 19).replace('T', ' ')} UTC` : '미확인';
const priceBasis = (value?: string) => value === 'provider_adjusted' ? '공급자 수정주가 · 확정 일봉'
    : value === 'unadjusted' ? '수정 전 가격' : value ?? '미확인';
const panelClass = 'ai-panel min-w-0 border border-[#30363f] p-4 sm:p-5';
const warningLabels: Record<string, string> = {
    raw_price_corporate_action_uncertainty: '수정 전 가격이므로 액면분할·배당 등 기업행사의 영향이 남아 있을 수 있습니다.',
    'Historical analogues are shadow evidence; forward efficacy has not been validated.': '유사 사례는 관측용 근거이며 향후 성과는 아직 검증되지 않았습니다.',
    'Up frequency is an empirical sample frequency, not a calibrated probability.': '상승 빈도는 과거 표본의 관측값이며 보정된 상승 확률이 아닙니다.',
    'Source closes are unadjusted; suspected corporate-action discontinuities are excluded.': '수정 전 종가를 사용하며 기업행사로 의심되는 급격한 가격 단절은 제외합니다.',
    'Source closes are provider-adjusted snapshots; historic adjustments may be revised later.': '공급자 수정주가를 사용합니다. 기업행사에 따라 과거 수정가격이 추후 변경될 수 있습니다.',
    'Samples can share market regimes and are not statistically independent.': '같은 시장 국면을 공유할 수 있어 통계적으로 독립된 표본이 아닙니다.',
    'Gross close-to-close returns exclude trading costs and slippage.': '종가 간 수익률에서 거래 비용과 슬리피지는 차감하지 않았습니다.',
};
const warningText = (warning: string) => warningLabels[warning] ?? warning;

export default function ChartAnaloguePage() {
    const { token, user, loading: authLoading } = useAuth();
    const [params, setParams] = useSearchParams();
    const code = params.get('code') ?? '003690';
    const [data, setData] = useState<ChartAnaloguePrediction | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [inputError, setInputError] = useState('');
    const [revision, setRevision] = useState(0);

    useEffect(() => {
        let active = true;
        setData(null);
        setError('');
        setInputError('');
        if (!/^\d{6}$/.test(code)) {
            setLoading(false);
            setInputError('국내 종목 코드 6자리를 입력해 주세요.');
            return;
        }
        setLoading(true);
        fetchChartAnalogue(code, token ?? undefined)
            .then(result => { if (active) setData(result); })
            .catch(cause => {
                if (active) setError(cause instanceof Error && cause.message.includes('응답 형식')
                    ? cause.message : '유사 사례를 불러오지 못했습니다. 잠시 후 다시 조회해 주세요.');
            })
            .finally(() => { if (active) setLoading(false); });
        return () => { active = false; };
    }, [code, token, revision]);

    const selectSymbol = useCallback((next: string) => {
        setInputError('');
        if (code === next) setRevision(value => value + 1);
        else setParams(previous => { const updated = new URLSearchParams(previous); updated.set('code', next); return updated; });
    }, [code, setParams]);

    return (
        <div className="ai-design min-h-full min-w-0 bg-[#101318] p-4 text-white sm:p-6 lg:p-8">
            <div className="mx-auto max-w-5xl space-y-5">
                <AiBrainServiceTabs active="chart-predict" />
                <header className="ai-page-header">
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] font-medium text-gray-400">
                        <span>AI BRAIN · HISTORICAL ANALOGUES</span><span className="rounded border border-[#365372] bg-[#1b2c40] px-2 py-0.5 text-[#acd3ff]">관측 전용 · SHADOW</span>
                    </div>
                    <h1 className="ai-page-title">차트 유사 사례</h1>
                    <p className="mt-2 text-sm leading-relaxed text-gray-400">현재 가격 흐름과 닮은 과거 구간의 이후 결과를 비교합니다. 상승 빈도는 과거 표본의 관측값이며 보정된 상승 확률이 아닙니다.</p>
                </header>
                <AlphaLabPanel token={token ?? undefined} onSelectSymbol={selectSymbol}
                    isAdmin={!authLoading && user?.role === 'admin' && user.status === 'approved' && !!token} />
                <ChartAnalogueKellyPanel token={token ?? undefined} onSelect={selectSymbol} />
                <ChartAnalogueTop3Panel token={token ?? undefined} />
                <ChartAnalogueSymbolSearch symbol={code} token={token ?? undefined} onSelect={selectSymbol} />
                <details className={`${panelClass} text-sm text-gray-300`}>
                    <summary className="cursor-pointer font-semibold text-[#acd3ff] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#72b4fb]">사용법 · 수치 해석 가이드</summary>
                    <div className="mt-4 space-y-3 text-xs leading-relaxed sm:text-sm">
                        <p>최근 거래일과 표본 수를 확인한 뒤, 검토할 기간의 상승 빈도·중앙 수익률·하락 쪽 10백분위를 함께 보세요. 과거 유사 사례의 종목과 날짜, 현재 거래량·수급·공시도 대조합니다.</p>
                        <p>예를 들어, 과거 사례 20개 중 11개가 상승했다면 상승 빈도는 55%입니다. 유사도는 가격 흐름의 닮은 정도이며, 두 수치 모두 미래 상승 확률을 확정하지 않습니다.</p>
                        <p>점선과 음영은 과거 결과를 현재 기준 종가로 환산한 중앙값과 10~90백분위입니다. 환산 가격은 목표가, 음영 하단은 손절가로 자동 적용할 수 없습니다. 기간 종료 수익률은 보유 중 최대 낙폭을 나타내지 않습니다.</p>
                        <a href="/guide/using-ai-signals#chart-analogue" className="inline-flex min-h-11 items-center text-[#acd3ff] underline underline-offset-4">차트 유사 사례 사용 매뉴얼 전체 보기</a>
                    </div>
                </details>
                {inputError && <p id="analogue-input-error" role="alert" className="text-sm text-amber-300">{inputError}</p>}
                {loading && <div role="status" className={`${panelClass} flex min-h-[340px] items-center justify-center text-sm text-gray-400`}>과거 유사 사례 조회 중…</div>}
                {!loading && error && <div role="alert" className={`${panelClass} space-y-3`}><p className="text-sm text-amber-200">{error}</p><button onClick={() => setRevision(value => value + 1)} className="rounded-lg border border-[#3a424d] px-3 py-2 text-xs font-medium text-gray-200">다시 조회</button></div>}
                {!loading && data && <>
                    <section className={panelClass} aria-label="종목과 데이터 출처">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                            <div><h2 className="text-lg font-semibold">{data.target || data.symbol} <span className="ml-1 font-mono text-sm font-normal text-gray-400">{data.symbol} · KR</span></h2><p className="mt-1 text-xs text-gray-400">분석 {data.lookback_sessions}거래일 · 표본 {data.sample_count}개</p></div>
                            {data.history.length > 0 && <div className="text-right"><p className="font-mono text-lg tabular-nums">{formatAnaloguePrice(data.history[data.history.length - 1].close)}</p><p className="text-[11px] text-gray-400">마지막 관측 종가</p></div>}
                        </div>
                        <dl className="mt-4 grid gap-x-6 gap-y-2 border-t border-[#30363f] pt-3 text-xs sm:grid-cols-2">
                            <div><dt className="inline text-gray-400">가격 출처 </dt><dd className="inline break-all text-gray-200">{data.source?.name ?? '미확인'}{data.source?.source_id ? ` · ${data.source.source_id}` : ''}</dd></div>
                            <div><dt className="inline text-gray-400">최근 거래일 </dt><dd className="inline text-gray-200">{data.source?.latest_session ?? data.diagnostics?.latest_session ?? '미확인'}</dd></div>
                            <div><dt className="inline text-gray-400">종목 가격 수집 </dt><dd className="inline text-gray-200">{timestamp(data.source?.query_captured_at ?? data.source?.captured_at)}</dd></div>
                            <div><dt className="inline text-gray-400">색인 생성 </dt><dd className="inline text-gray-200">{timestamp(data.source?.built_at)}</dd></div>
                            <div><dt className="inline text-gray-400">분석 기준 </dt><dd className="inline text-gray-200">{timestamp(data.as_of)}</dd></div>
                            <div><dt className="inline text-gray-400">모델 </dt><dd className="inline break-all text-gray-200">{data.model_version}</dd></div>
                            <div><dt className="inline text-gray-400">가격 기준 </dt><dd className="inline text-gray-200">{priceBasis(data.source?.price_basis)}</dd></div>
                        </dl>
                        {data.source?.query_collection_status === 'cache_preserved' && <p className="mt-3 text-xs leading-relaxed text-amber-200/90">이번 가격 수집에 실패하여 이전 정상 스냅샷을 사용합니다. 최근 거래일과 종목 가격 수집 시각을 확인해 주세요.</p>}
                        {data.source?.price_basis === 'unadjusted' && <p className="mt-3 text-xs leading-relaxed text-amber-200/90">수정 전 가격 · 액면분할·배당 등 기업행사의 영향이 남아 있을 수 있습니다.</p>}
                    </section>
                    {data.status !== 'ready' ? <section className={`${panelClass} space-y-2`} aria-label="데이터 상태"><h2 className="text-base font-semibold text-amber-200">{stateLabels[data.status].title}</h2><p className="text-sm leading-relaxed text-gray-400">{stateLabels[data.status].detail}</p><button onClick={() => setRevision(value => value + 1)} className="mt-2 rounded-lg border border-[#3a424d] px-3 py-2 text-xs text-gray-200">다시 조회</button></section> : <>
                        <section className={panelClass} aria-labelledby="analogue-chart-heading"><h2 id="analogue-chart-heading" className="ai-section-title mb-4 text-sm">종가 흐름과 과거 사례 분포</h2><ChartAnalogueChart data={data} /></section>
                        <section className={panelClass}><h2 className="ai-section-title text-sm">기간별 관측 결과</h2><p className="mb-3 mt-1 text-xs leading-relaxed text-gray-400">5·20·40은 자료에 포함된 이후 관측 거래일 수입니다. 연속된 시장 거래일을 보장하지 않습니다. 수익률은 비용·슬리피지 차감 전 과거 결과입니다.</p>
                            <div className="overflow-x-auto" tabIndex={0}><table aria-label="유사 사례의 기간별 관측 결과" className="w-full min-w-[640px] text-right text-xs tabular-nums"><thead className="text-gray-400"><tr><th className="pb-2 text-left">기간</th><th className="pb-2">과거 상승 빈도</th><th className="pb-2">중앙 수익률</th><th className="pb-2">수익률 10~90백분위</th><th className="pb-2">환산 중앙 가격</th><th className="pb-2">환산 가격 범위</th></tr></thead><tbody>{data.horizons.map(row => <tr key={row.sessions} className="border-t border-[#30363f]"><th className="py-3 text-left font-medium">{row.sessions}거래일</th><td className="py-3">{row.up_frequency_pct.toFixed(1)}%</td><td className="py-3 text-teal-200">{formatAnalogueReturn(row.median_return_pct)}</td><td className="py-3">{formatAnalogueReturn(row.p10_return_pct)} ~ {formatAnalogueReturn(row.p90_return_pct)}</td><td className="py-3">{formatAnaloguePrice(row.median_price)}</td><td className="py-3">{formatAnaloguePrice(row.lower_price)} ~ {formatAnaloguePrice(row.upper_price)}</td></tr>)}</tbody></table></div>
                        </section>
                        <section className={panelClass}><h2 className="ai-section-title text-sm">과거 유사 사례</h2><p className="mb-3 mt-1 text-xs text-gray-400">실제 종목·구간·결과를 확인하세요. 유사도는 가격 패턴의 닮은 정도입니다.</p>
                            <div className="overflow-x-auto" tabIndex={0}><table aria-label="과거 유사 사례" className="w-full min-w-[680px] text-right text-xs tabular-nums"><thead className="text-gray-400"><tr><th className="pb-2 text-left">종목 / 유사 구간</th><th className="pb-2">유사도</th><th className="pb-2">5거래일</th><th className="pb-2">20거래일</th><th className="pb-2">40거래일</th><th className="pb-2">결과 관측 완료</th></tr></thead><tbody>{data.neighbors.map((row, index) => <tr key={`${row.symbol}-${row.end_date}-${index}`} className="border-t border-[#30363f]"><th className="py-3 text-left font-normal"><span className="font-medium">{row.target || row.symbol} <span className="font-mono text-gray-400">{row.symbol}</span></span><span className="mt-1 block text-[11px] text-gray-400">{row.start_date} ~ {row.end_date}</span></th><td className="py-3">{(row.similarity * 100).toFixed(1)}%</td>{[5, 20, 40].map(sessions => <td key={sessions} className="py-3">{formatAnalogueReturn(row.returns[String(sessions)])}</td>)}<td className="py-3">{row.outcome_end_date ?? '미확인'}</td></tr>)}</tbody></table></div>
                        </section>
                    </>}
                    {data.warnings.length > 0 && <aside className="rounded-xl border border-amber-400/20 bg-amber-400/[0.04] p-4 text-xs leading-relaxed text-amber-200/90" aria-label="데이터 주의사항"><p className="mb-2 font-semibold">데이터 주의사항</p><ul className="list-disc space-y-1 pl-4">{data.warnings.map((warning, index) => <li key={index}>{warningText(warning)}</li>)}</ul></aside>}
                </>}
                <ChartAnalogueEvaluationPanel token={token ?? undefined} />
                <footer className="border-t border-[#30363f] pt-4 text-xs leading-relaxed text-gray-400">자동 TOP3는 차트 사례 기반의 별도 검토 목록이며 기존 AI Brain 검출 순위를 변경하지 않습니다. 과거 유사 사례는 미래 수익이나 매매 성과를 보장하지 않으며, 다른 가격·수급·리스크 근거와 함께 확인해야 합니다.</footer>
            </div>
        </div>
    );
}
