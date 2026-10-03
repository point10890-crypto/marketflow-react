import { useEffect, useId, useRef, useState } from 'react';
import { fetchChartAnalogueKelly, startChartAnalogueKelly, type ChartAnalogueKellyCandidate,
    type ChartAnalogueKellyEnvelope, type ChartAnalogueKellyMetric, type ChartAnalogueKellyReport } from '@/lib/chartAnalogueKellyApi';

const panel = 'ai-panel min-w-0 border border-[#30363f] p-4 sm:p-5';
const pct = (v: number | null, fraction = false) => v === null ? '대기' : `${(fraction ? v * 100 : v).toFixed(1)}%`;
const signed = (v: number | null) => v === null ? '대기' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`;
const won = (v: number | null) => v === null ? '대기' : `${Math.round(v).toLocaleString('ko-KR')}원`;
const kst = (v?: string) => v ? `${new Date(Date.parse(v) + 9 * 3600000).toISOString().slice(0, 16).replace('T', ' ')} KST` : '미확인';
const states = { stable: '과거 안정성 통과', watch: '관찰 · 조건 미충족', insufficient: '자료·표본 부족' };
const reasonLabels: Record<string, string> = {
    train_samples_below_minimum: '훈련 표본이 최소 기준보다 적습니다.',
    validation_samples_below_minimum: '검증 표본이 최소 기준보다 적습니다.',
    insufficient_train_samples: '훈련 표본 부족', insufficient_validation_samples: '검증 표본 부족',
    insufficient_samples: '표본 부족', missing_prices: '가격 자료 부족', stale_prices: '가격 자료 갱신 대기',
    missing_index: '가격 색인 준비 대기', point_in_time_vintage_unverified: '최초 공시·가격 보정 시점 검증 대기',
    historical_stability_only: '과거 자료의 안정성 검토이며 실투자 승인을 뜻하지 않습니다.',
    train_nonpositive_expectancy: '훈련 순수익 기대값이 양수가 아닙니다.',
    validation_nonpositive_expectancy: '검증 순수익 기대값이 양수가 아닙니다.',
    forward_validation_pending: '새 결정 이후 실제 관측 결과 누적 대기',
    train_too_few_samples: '훈련 표본이 최소 30개보다 적습니다.', validation_too_few_samples: '검증 표본이 최소 30개보다 적습니다.',
    train_win_rate_below_60: '훈련 순수익 상승 빈도가 60%보다 낮습니다.', validation_win_rate_below_60: '검증 순수익 상승 빈도가 60%보다 낮습니다.',
    train_wilson_below_60: '훈련 Wilson 진단 하한이 60%보다 낮습니다.', validation_wilson_below_60: '검증 Wilson 진단 하한이 60%보다 낮습니다.',
    train_payoff_unavailable: '훈련 손익비를 산정할 수 없습니다.', validation_payoff_unavailable: '검증 손익비를 산정할 수 없습니다.', payoff_unavailable: '승리·손실 표본을 모두 확보해야 손익비를 산정할 수 있습니다.',
    train_payoff_below_one: '훈련 손익비가 1보다 작습니다.', validation_payoff_below_one: '검증 손익비가 1보다 작습니다.',
    train_nonpositive_net_expectancy: '훈련 평균 순수익이 양수가 아닙니다.', validation_nonpositive_net_expectancy: '검증 평균 순수익이 양수가 아닙니다.',
    nonpositive_watch_score: '하락 위험을 차감한 참고 점수가 양수가 아닙니다.', no_similar_cases: '검토 조건에 맞는 유사 사례가 없습니다.', symbol_missing: '종목 가격이 색인에 없습니다.',
    prospective_validation_required: '새 결정 이후 전향 성과 관측이 필요합니다.', historical_point_in_time_unverified: '최초 공시·가격 보정 시점이 검증되지 않았습니다.',
    snapshot_retrospective_stability_not_walk_forward: '현재 스냅샷의 회고 안정성 분석이며 당시 의사결정을 재현한 성과가 아닙니다.',
    current_universe_survivorship_bias: '현재 우량주 목록에 따른 생존 편향이 남아 있습니다.', shared_market_regime_dependence: '사례가 공유 시장 국면의 영향을 받을 수 있습니다.',
    assumed_33bps_roundtrip_cost_not_executed_fill: '왕복 비용·슬리피지 33bp는 연구 가정이며 체결 비용이 아닙니다.', supplier_adjusted_history_can_be_revised: '공급자 수정주가는 기업행사에 따라 추후 변경될 수 있습니다.',
    research_weights_are_not_approved_allocations: '연구 비중은 승인된 실투자 비중이 아닙니다.',
};
const reasonText = (v: string) => reasonLabels[v] ?? v;

function EvidenceChart({ row }: { row: ChartAnalogueKellyCandidate }) {
    const id = useId();
    const [selected, setSelected] = useState(0);
    const observed = row.chart.cases[selected] ?? row.chart.cases[0];
    if (row.chart.query.length === 0 || !observed) return <p className="flex min-h-[190px] items-center justify-center rounded-lg border border-[#30363f] text-xs text-gray-400">비교할 차트 사례 대기</p>;
    const all = [...row.chart.query, ...observed.input, ...observed.future];
    const low = Math.min(...all); const high = Math.max(...all); const pad = Math.max(3, (high - low) * .1);
    const y = (v: number) => 218 - (v - low + pad) / (high - low + pad * 2) * 190;
    const path = (values: number[], start: number, span: number) => values.map((value, i) => `${i ? 'L' : 'M'}${(start + i / (values.length - 1) * span).toFixed(1)},${y(value).toFixed(1)}`).join(' ');
    return <div className="mt-4">
        <svg role="img" aria-labelledby={`${id}-title ${id}-description`} viewBox="0 0 720 252" className="block h-auto w-full rounded-lg border border-[#30363f] bg-[#0f151c]">
            <title id={`${id}-title`}>{row.target} 현재 흐름과 과거 유사 사례의 관측 결과</title>
            <desc id={`${id}-description`}>현재 252관측일 흐름을 마지막 가격 100으로 환산했습니다. {observed.target}의 닮은 과거 구간과 그 다음 관측 종가부터 20관측일 결과를 겹쳐 봅니다. 음영은 이미 관측된 과거 결과이며 현재 종목의 예측 경로가 아닙니다.</desc>
            <rect x="510" y="18" width="185" height="203" fill="#172c34" />
            {[low, (low + high) / 2, high].map(value => <g key={value}><line x1="34" x2="695" y1={y(value)} y2={y(value)} stroke="#29343f" /><text x="6" y={y(value) + 4} fill="#8294a5" fontSize="10">{value.toFixed(0)}</text></g>)}
            <path d={path(observed.input, 35, 475)} fill="none" stroke="#a9b6c3" strokeWidth="1.5" strokeDasharray="5 4" />
            <path d={path(row.chart.query, 35, 475)} fill="none" stroke="#8bc9f3" strokeWidth="2.5" />
            <path d={`M510,${y(100)} L${path(observed.future, 520, 165).slice(1)}`} fill="none" stroke="#84ccc2" strokeWidth="2" />
            <line x1="510" x2="510" y1="18" y2="221" stroke="#64808e" strokeDasharray="3 4" />
            <text x="35" y="242" fill="#a8b6c3" fontSize="11">닮은 과거 252관측일 · 마지막 가격 = 100</text>
            <text x="518" y="242" fill="#a4c8c4" fontSize="11">과거 사례의 이후 20관측일</text>
        </svg>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-gray-400"><span className="text-[#8bc9f3]">실선: {row.target} 현재 흐름</span><span>점선: {observed.target} 과거 흐름</span><span className="text-[#84ccc2]">음영: 그 사례의 관측 완료 결과</span></div>
        {row.chart.cases.length > 1 && <div className="mt-3 flex flex-wrap gap-2" aria-label={`${row.target} 비교 사례 선택`}>{row.chart.cases.map((item, index) => <button type="button" key={`${item.symbol}-${item.anchor_date}`} onClick={() => setSelected(index)} aria-pressed={index === selected} className={`min-h-9 rounded border px-2 text-[11px] ${index === selected ? 'border-[#638f9d] bg-[#20333d] text-[#acd3ff]' : 'border-[#30363f] text-gray-400'}`}>{index + 1}. {item.target}</button>)}</div>}
        <p className="mt-2 text-[11px] leading-relaxed text-gray-400">{observed.target} {observed.symbol} · 유사도 {(observed.similarity * 100).toFixed(1)}%<br />사례 기준 {observed.anchor_date} → 다음 관측 종가 {observed.entry_date} → 종료 {observed.exit_date}<br />가격 {won(observed.entry_close)} → {won(observed.exit_close)} · 비용 후 {signed(observed.net_return_pct)}</p>
    </div>;
}

function MetricRow({ title, value }: { title: string; value: ChartAnalogueKellyMetric | null }) {
    return <tr className="border-t border-[#30363f]"><th scope="row" className="py-2.5 pr-2 text-left font-medium">{title}<span className="mt-1 block text-[10px] font-normal text-gray-500">{value ? `${value.period_start} ~ ${value.period_end}` : '표본 대기'}</span></th>
        <td className="px-2 py-2.5">{value ? `${value.sample_count}개 / ${value.distinct_symbols}종목` : '—'}</td><td className="px-2">{pct(value?.net_win_rate_pct ?? null)}</td><td className="px-2">{pct(value?.wilson_lower_pct ?? null)}</td>
        <td className="px-2">{value?.payoff_ratio === null || value?.payoff_ratio === undefined ? '미산정' : value.payoff_ratio.toFixed(2)}</td><td className="pl-2">{signed(value?.expectancy_pct ?? null)}</td></tr>;
}
function StockCard({ row, capital, onSelect }: { row: ChartAnalogueKellyCandidate; capital: number | null; onSelect?: (symbol: string) => void }) {
    const k = row.kelly;
    return <article aria-label={`차트·켈리 연구 후보 ${row.rank}위 ${row.target}`} className="min-w-0 rounded-xl border border-[#3b4d5c] bg-[#121a22] p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-[11px] font-semibold text-[#acd3ff]">연구 후보 #{row.rank} · {row.market}</p><h3 className="mt-1 text-xl font-semibold tracking-tight">{row.target}</h3><p className="mt-1 font-mono text-xs text-gray-400">{row.symbol} · 시총 순위 {row.universe_rank}</p></div><span className={`rounded-md border px-2.5 py-1 text-[11px] ${row.research_status === 'stable' ? 'border-[#497368] text-teal-200' : 'border-[#796b4e] text-amber-200'}`}>{states[row.research_status]}</span></div>
        <EvidenceChart row={row} />
        <div className="mt-4 overflow-x-auto" tabIndex={0}><table aria-label={`${row.target} 훈련과 검증 순수익 근거`} className="w-full min-w-[630px] text-right text-[11px] tabular-nums"><thead className="text-gray-400"><tr><th className="pb-2 text-left">시간순 분리</th><th className="pb-2">표본 / 사례 종목</th><th className="pb-2">순수익 상승 빈도</th><th className="pb-2">Wilson 하한*</th><th className="pb-2">손익비</th><th className="pb-2">평균 순수익</th></tr></thead><tbody><MetricRow title="훈련" value={row.train} /><MetricRow title="검증" value={row.validation} /></tbody></table></div>
        <p className="mt-2 text-[10px] leading-relaxed text-gray-500">* 공유 시장 국면·겹친 사례를 독립 표본으로 인증하지 않습니다. 하한은 설명용 진단이며 미래 승률을 보장하지 않습니다.</p>
        <div className="mt-4 grid grid-cols-2 gap-2 text-xs sm:grid-cols-5">{[
            ['순수익 Kelly', pct(k.empirical_fraction, true)], ['하프 × 0.5', pct(k.half_fraction, true)], ['종목 한도 20%', pct(k.half_fraction === null ? null : Math.min(.2, k.half_fraction), true)],
            ['변동성 가드', k.volatility_guard ? '× 0.5' : '× 1.0'], ['연구 비중', pct(k.research_weight, true)],
        ].map(([label, value], i) => <div key={label} className={`rounded-lg border p-3 ${i === 4 ? 'border-[#4d7c75] bg-[#1c302e]' : 'border-[#303f4b]'}`}><p className="text-[10px] text-gray-400">{label}</p><p className="mt-1 font-mono text-base tabular-nums">{value}</p></div>)}</div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-y border-[#30363f] py-3 text-xs"><span className="text-gray-400">시나리오 금액 <strong className="ml-2 font-mono text-base text-white">{won(capital === null ? null : capital * k.research_weight)}</strong></span><span className="text-amber-200">실투자 비중·금액: 미승인</span></div>
        <p className="mt-2 text-[11px] text-gray-500">전체 노출 조정 × {k.portfolio_scale.toFixed(3)} · 참고 점수 {row.score.toFixed(2)} · {row.reference_session ?? '가격 대기'} {row.current_close === null ? '' : won(row.current_close)}</p>
        {row.reasons.length > 0 && <ul className="mt-3 space-y-1 text-[11px] leading-relaxed text-gray-400">{row.reasons.map((reason, index) => <li key={`${reason}-${index}`}>{reasonText(reason)}</li>)}</ul>}
        {onSelect ? <button type="button" onClick={() => onSelect(row.symbol)} className="mt-4 flex min-h-11 w-full items-center justify-center rounded-lg border border-[#365372] text-xs font-semibold text-[#acd3ff] hover:bg-[#1b2c40]">상세 차트 · 사례 더 보기</button>
            : <a href={`/dashboard/ai-bain/chart-predict?code=${row.symbol}`} className="mt-4 flex min-h-11 items-center justify-center rounded-lg border border-[#365372] text-xs font-semibold text-[#acd3ff]">상세 차트 · 사례 더 보기</a>}
    </article>;
}

/** Same pure evidence view is used by the member dashboard and local report preview. No brokerage action exists here. */
export function ChartAnalogueKellyReportView({ report, onSelect, stale = false }: { report: ChartAnalogueKellyReport; onSelect?: (symbol: string) => void; stale?: boolean }) {
    const capitalId = useId();
    const [capitalInput, setCapitalInput] = useState('10000000');
    const amount = capitalInput.trim() ? Number(capitalInput) : NaN;
    const capital = Number.isFinite(amount) && amount >= 0 && amount <= 1e12 ? amount : null;
    const f = report.forward;
    return <div className="space-y-4">
        {stale && <p className="rounded-lg border border-amber-400/20 bg-amber-400/[0.04] p-3 text-xs text-amber-200">이전 결과입니다. 현재 가격 색인·우량주 기준과의 일치를 확인한 새 검사가 끝날 때까지 최신 분석으로 해석하지 마세요.</p>}
        <div className="grid grid-cols-2 gap-2 border-y border-[#30363f] py-4 text-xs sm:grid-cols-4">{[
            ['시총 상위 검사 범위', `${report.universe.ranked}종목`], ['재무 1차 통과 · 검사', `${report.universe.quality_passed} · ${report.universe.processed}종목`],
            ['과거 안정성 통과', `${report.universe.stable}종목`], ['실투자 승인', '보류 · 0%'],
        ].map(([label, value]) => <div key={label} className="border-l border-[#303f4b] pl-3"><p className="text-[10px] text-gray-400">{label}</p><p className="mt-1 text-base font-semibold tabular-nums">{value}</p></div>)}</div>
        <div className="rounded-lg border border-amber-400/25 bg-[#242119] p-3 text-xs leading-relaxed text-amber-100"><p className="font-semibold">최종 투자 승인 보류</p><p className="mt-1">아래는 차트 사례의 과거 결과와 켈리 연구 시나리오입니다. 순위는 매수 승인 순위가 아닙니다. 과거 자료 검증과 새 결정 이후 성과 관측이 완료되기 전에는 실제 투자 비중을 승인하지 않습니다.</p>
            {report.approval.reasons.length > 0 && <p className="mt-2 text-[11px] text-amber-200/80">{report.approval.reasons.map(reasonText).join(' · ')}</p>}</div>
        <div className="flex flex-wrap items-end justify-between gap-3 rounded-lg border border-[#303f4b] bg-[#141d26] p-3"><div><label htmlFor={capitalId} className="block text-xs font-semibold text-gray-300">시나리오 자산 금액</label><div className="mt-2 flex items-center gap-2"><input id={capitalId} type="number" min="0" max="1000000000000" step="1000000" value={capitalInput} onChange={e => setCapitalInput(e.target.value)} aria-invalid={capital === null} className="h-10 w-44 rounded-lg border border-[#435363] bg-[#0e151d] px-3 font-mono text-sm tabular-nums" /><span className="text-xs text-gray-400">원</span></div>{capital === null && <p className="mt-1 text-[11px] text-amber-200">0~1조원 범위의 금액을 입력해 주세요.</p>}</div><p className="text-xs tabular-nums text-gray-400">연구 노출 {pct(report.portfolio.research_exposure, true)} · 현금 {pct(report.portfolio.research_cash, true)}<span className="mt-1 block text-[10px]">화면에서만 계산하는 가정입니다. 주문·계좌 변경은 없습니다.</span></p></div>
        {report.candidates.length === 0 ? <p className="py-6 text-sm text-gray-400">표시할 연구 후보가 없습니다. 자료 상태와 검사 조건을 확인해 주세요.</p>
            : <div className="space-y-4">{[...report.candidates].sort((a, b) => a.rank - b.rank).map(row => <StockCard key={row.symbol} row={row} capital={capital} onSelect={onSelect} />)}</div>}
        {f && <aside className="rounded-lg border border-[#303f4b] p-3 text-xs leading-relaxed text-gray-400"><p className="font-medium text-gray-200">전향 관측 · {f.matured_trades === 0 ? '성과 관측 대기' : '결과 누적 중'}</p><p className="mt-1 tabular-nums">결정 {f.decision_days}일 · 관측 완료 {f.matured_trades}건 · 진행 {f.pending_trades}건{f.matured_trades > 0 ? ` · 순수익 상승 빈도 ${pct(f.net_win_rate_pct)} · 평균 순수익 ${signed(f.expectancy_pct)}` : ''}</p><p className="mt-1 text-[10px]">한국시간 날짜별 첫 결정만 고정합니다. 관측 건수는 독립 표본 인증이나 미래 성과 입증을 뜻하지 않습니다.</p></aside>}
        {report.leaderboard.length > 0 && <details className="border-t border-[#30363f] pt-3"><summary className="cursor-pointer text-xs font-semibold text-[#acd3ff]">검사한 우량주 {report.leaderboard.length}종목 · 전체 결과 보기</summary><div className="mt-3 overflow-x-auto" tabIndex={0}><table aria-label="우량주 차트 켈리 전체 검사" className="w-full min-w-[670px] text-right text-[11px] tabular-nums"><thead className="text-gray-400"><tr><th className="pb-2 text-left">종목 · 코드</th><th className="pb-2">상태</th><th className="pb-2">훈련 / 검증 표본</th><th className="pb-2">검증 상승 빈도</th><th className="pb-2">검증 평균 순수익</th><th className="pb-2">연구 비중</th></tr></thead><tbody>{report.leaderboard.map(row => <tr key={row.symbol} className="border-t border-[#30363f]"><th className="py-2.5 text-left font-normal">{onSelect ? <button type="button" onClick={() => onSelect(row.symbol)} className="text-[#acd3ff] underline-offset-4 hover:underline">{row.target}</button> : row.target}<span className="ml-2 font-mono text-gray-500">{row.symbol}</span></th><td>{states[row.research_status]}</td><td>{row.train?.sample_count ?? 0} / {row.validation?.sample_count ?? 0}</td><td>{pct(row.validation?.net_win_rate_pct ?? null)}</td><td>{signed(row.validation?.expectancy_pct ?? null)}</td><td>{pct(row.kelly.research_weight, true)}</td></tr>)}</tbody></table></div></details>}
        <details className="border-t border-[#30363f] pt-3 text-[11px] leading-relaxed text-gray-400"><summary className="cursor-pointer text-xs font-medium text-[#acd3ff]">계산 방법 · 출처 · 활용 순서</summary><div className="mt-3 space-y-2"><p>① 시총 상위 100개 중 재무 1차 통과 종목만 검사합니다. ② 닮은 252관측일 구간을 찾습니다. ③ 사례 기준일 다음 관측 종가로 진입하여 20관측일 뒤 종가와 비교하고, 왕복 비용·슬리피지 33bp(0.33%)를 차감합니다.</p><p>④ 훈련·검증 구간 사이에 전체 252관측일 입력 중복을 제거하며 각 구간 최소 30개 표본을 요구합니다. 과거 안정성 검토는 보정된 미래 승률 검증과 다릅니다. 표본이 부족한 종목도 관찰 후보로 보여주되 연구 비중은 0입니다.</p><p>⑤ 실제 순수익 표본으로 mean(log(1 + f × 순수익))를 최대화한 켈리 값을 구합니다. 하프 켈리, 종목 한도 20%, 변동성 가드와 전체 노출 60%·현금 40% 한도를 적용합니다. 승률 60%·손익비 1의 이항 켈리 20%를 모든 주식에 그대로 대입하지 않습니다.</p><p>종목명 → 검증 표본·순수익·하락 위험 → 과거 사례의 날짜 → 연구 비중 순서로 읽으세요. 사례 그래프의 음영은 과거에 관측된 결과입니다. 현재 종목의 예측 경로나 목표가·손절가가 아닙니다.</p><p>우량주 기준 {report.universe.as_of} · 가격 거래일 {report.source.latest_session ?? '미확인'} · 자료 {report.source.source_id ?? '미확인'} · 공급자 수정주가</p><p>가격 수집 {kst(report.source.captured_at)} · 색인 생성 {kst(report.source.built_at)} · 분석 기준 {kst(report.as_of)} · 보고서 생성 {kst(report.generated_at)}</p><p>현재 우량주 목록과 현재 공급자 수정주가를 사용한 회고 분석입니다. 최초 공시 시점 재현·생존 편향 제거·실전 성과 인증은 완료되지 않았습니다. 뉴스·수급·공시·유동성은 별도로 대조합니다.</p>{report.warnings.length > 0 && <p>{report.warnings.map(reasonText).join(' · ')}</p>}<a href="/guide/using-ai-signals#chart-analogue-kelly" className="inline-flex min-h-9 items-center text-[#acd3ff] underline underline-offset-4">차트·켈리 사용 매뉴얼</a></div></details>
    </div>;
}

export default function ChartAnalogueKellyPanel({ token, onSelect }: { token?: string; onSelect?: (symbol: string) => void }) {
    const heading = useId(); const sequence = useRef(0); const mounted = useRef(false);
    const [snapshot, setSnapshot] = useState<ChartAnalogueKellyEnvelope | null>(null);
    const [reading, setReading] = useState(true); const [posting, setPosting] = useState(false);
    const [error, setError] = useState(''); const [revision, setRevision] = useState(0);
    const accept = (value: ChartAnalogueKellyEnvelope) => setSnapshot(old => ({ ...value, report: value.report ?? (['running', 'error'].includes(value.state) ? old?.report ?? null : null) }));
    useEffect(() => {
        mounted.current = true; let active = true; const id = ++sequence.current;
        setSnapshot(null); setReading(true); setPosting(false); setError('');
        fetchChartAnalogueKelly(token).then(value => { if (active && id === sequence.current) accept(value); })
            .catch(() => { if (active && id === sequence.current) setError('차트·켈리 결과를 불러오지 못했습니다. 다시 조회해 주세요.'); })
            .finally(() => { if (active && id === sequence.current) setReading(false); });
        return () => { active = false; mounted.current = false; ++sequence.current; };
    }, [token, revision]);
    const state = snapshot?.state;
    useEffect(() => {
        if (state !== 'running') return;
        let active = true; let timer: ReturnType<typeof setTimeout>;
        const poll = async () => {
            const id = ++sequence.current;
            try {
                const value = await fetchChartAnalogueKelly(token);
                if (!active || id !== sequence.current) return;
                accept(value);
                if (value.state === 'running') timer = setTimeout(poll, 4000);
            } catch {
                if (!active || id !== sequence.current) return;
                setError('검사 진행 상태를 확인하지 못했습니다. 다시 조회해 주세요.');
            }
        };
        timer = setTimeout(poll, 4000);
        return () => { active = false; clearTimeout(timer); };
    }, [state, token, revision]);
    const start = async () => {
        if (reading || posting || state === 'running') return;
        const id = ++sequence.current; setPosting(true); setError('');
        try { const value = await startChartAnalogueKelly(token); if (mounted.current && id === sequence.current) accept(value); }
        catch { if (mounted.current && id === sequence.current) setError('차트·켈리 검사를 시작하지 못했습니다. 잠시 후 다시 시도해 주세요.'); }
        finally { if (mounted.current && id === sequence.current) setPosting(false); }
    };
    const problem = error || (state === 'error' ? '차트·켈리 검사를 완료하지 못했습니다. 이전 결과와 자료 상태를 확인해 주세요.' : '');
    return <section className={panel} aria-labelledby={heading}><div className="mb-4 flex flex-wrap items-start justify-between gap-3"><div><p className="text-[10px] font-semibold tracking-[.08em] text-gray-400">PATTERN EVIDENCE → KELLY RESEARCH</p><h2 id={heading} className="ai-section-title mt-1 text-lg">우량주 차트·켈리 연구 TOP3</h2><p className="mt-2 max-w-2xl text-xs leading-relaxed text-gray-400">실제 종목의 닮은 과거 사례, 시간순 순수익 검증과 켈리 비중을 연결합니다. 조건 미충족 후보와 실투자 승인 보류 상태도 함께 보여줍니다.</p></div><button type="button" onClick={start} disabled={reading || posting || state === 'running'} className="min-h-11 rounded-lg border border-[#365372] bg-[#1b2c40] px-4 text-xs font-semibold text-[#acd3ff] disabled:cursor-wait disabled:opacity-50">차트·켈리 검사</button></div>
        {reading && <p role="status" className="py-5 text-sm text-gray-400">저장된 차트·켈리 결과 확인 중…</p>}
        {(posting || state === 'running') && <p role="status" className="mb-4 rounded-lg border border-[#365372] bg-[#1b2c40] p-3 text-xs tabular-nums text-[#acd3ff]">{snapshot && snapshot.total > 0 ? `우량주 검사 중 · ${snapshot.processed} / ${snapshot.total}` : '검사 준비 중…'}</p>}
        {problem && <div role="alert" className="mb-4 rounded-lg border border-amber-400/20 p-3 text-xs text-amber-200"><p>{problem}</p><button type="button" onClick={() => setRevision(v => v + 1)} className="mt-2 min-h-9 rounded border border-[#5e5748] px-3">다시 조회</button></div>}
        {!reading && !snapshot?.report && !problem && state !== 'running' && !posting && <p className="py-5 text-sm text-gray-400">저장된 차트·켈리 결과가 없습니다. 검사 버튼으로 우량주 분석을 시작해 주세요.</p>}
        {snapshot?.report && <ChartAnalogueKellyReportView report={snapshot.report} onSelect={onSelect} stale={snapshot.freshness !== 'current'} />}
    </section>;
}
