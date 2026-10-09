// 선정 종목별 최초 가격 판단과 뉴스 발행·실제 수집의 시간 관계를 표시한다.
import { validateCatalystContext, type CatalystStage, type CatalystTiming } from '@/lib/catalystContext';
import type { OpportunityEngine } from '@/lib/opportunityEngine';

const clock = (value: string) => `${new Date(Date.parse(value) + 9 * 3600000).toISOString().slice(0, 19).replace('T', ' ')} KST`;
const timings: Record<CatalystTiming, string> = {
    captured_before_first: '사전 수집', published_before_captured_after: '사전 공개·사후 수집', reported_after_first: '선정 후 보도',
};
const stages: Record<CatalystStage, string> = {
    valuation_opinion: '저평가 의견', site_inspection: '부지 점검', infrastructure: '기반시설', investment: '투자', contract: '계약·수주', earnings: '실적', other: '기타',
};
const polarities = { supportive: '우호', adverse: '위험', mixed: '혼재', unknown: '판단 보류' };
const disclosureClass = 'min-h-11 cursor-pointer rounded py-3 font-semibold text-[#acd3ff] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb]';

export default function CatalystContext({ context, board, now = Date.now() }: { context?: unknown; board: OpportunityEngine; now?: number }) {
    const value = validateCatalystContext(context, board, now);
    if (!value) return null;
    return <section aria-label="가격 신호와 뉴스 동행" className="mb-5 min-w-0 space-y-3 border-t border-[#30363f] pt-4 text-base leading-relaxed sm:text-sm">
        <div><h3 className="font-semibold text-gray-100">가격 신호와 뉴스 동행</h3>
            <p className="mt-1 text-gray-300">원래 선정은 가격 기준; 뉴스는 별도 대조</p>
            <p className="mt-1 break-words text-gray-400">가격 검출 전후에 어떤 보도가 공개·수집되었는지 확인합니다. 사전 수집도 당시 선정에 사용됐다는 뜻은 아니며, 뉴스 선행 예측과 수익 연관성은 검증 중입니다.</p></div>
        <div className="grid min-w-0 gap-3 lg:grid-cols-3">{value.rows.map(row => <article key={row.symbol} aria-label={`${row.name} ${row.symbol} 뉴스 시각 대조`} className="min-w-0 rounded-lg border border-[#303f4b] bg-[#121a22] p-3 sm:p-4">
            <h4 className="break-words font-semibold text-gray-100">{row.name} <span className="font-mono text-gray-400">{row.symbol}</span></h4>
            <p className="mt-1 break-words tabular-nums text-gray-300">최초 판단 <time dateTime={row.first_detected_at} title={row.first_detected_at}>{clock(row.first_detected_at)}</time></p>
            {row.events.length ? <ul className="mt-3 divide-y divide-[#30363f]">{Array.from(new Set(row.events.map(event => event.event_group))).map(groupId => {
                const events = row.events.filter(event => event.event_group === groupId);
                return <li key={groupId} className="min-w-0 py-3 first:pt-0">
                    {events.length > 1 && <><p className="mb-2 break-words text-gray-300">같은 주제·날짜의 보도 묶음 · {events.length}건</p><p className="mb-2 break-words text-gray-400">묶음은 주제·날짜 대조용입니다. 실제 동일 사건·전재 여부는 미확인입니다.</p></>}
                    <ul aria-label={events.length > 1 ? '같은 주제·날짜의 보도 묶음' : undefined} className="divide-y divide-[#30363f]">{events.map(event => <li key={event.event_id} className="min-w-0 space-y-2 py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-2"><span className={`max-w-full rounded border px-2 py-1 font-semibold ${event.timing === 'captured_before_first' ? 'border-[#365372] text-[#acd3ff]' : 'border-[#4b4d44] text-gray-200'}`}>{timings[event.timing]}</span><span className="text-gray-400">{stages[event.stage]} · {polarities[event.polarity]}</span></div>
                <a href={event.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 max-w-full items-center break-words py-2 font-semibold text-[#acd3ff] underline decoration-[#365372] underline-offset-4 [overflow-wrap:anywhere] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb]">{event.title}<span className="sr-only"> · 원문 열기</span></a>
                <p className="break-words text-gray-400">{event.source} · B등급 · 일반 뉴스</p>
                <dl className="space-y-1 break-words tabular-nums text-gray-400"><div><dt className="inline">발행 </dt><dd className="inline"><time dateTime={event.published_at} title={event.published_at}>{clock(event.published_at)}</time></dd></div><div><dt className="inline">실제 수집 </dt><dd className="inline"><time dateTime={event.collected_at} title={event.collected_at}>{clock(event.collected_at)}</time></dd></div></dl>
                    </li>)}</ul>
                </li>;
            })}</ul> : <p className="mt-3 text-gray-400">연결할 수 있는 일반 뉴스 자료가 없습니다.</p>}
        </article>)}</div>
        <p className="break-words text-gray-400">일반 뉴스는 보조 맥락입니다. 반복 보도를 독립 호재로 집계하거나 투자 확정·성공으로 해석하지 않습니다.</p>
        <details className="min-w-0 border-t border-[#30363f]"><summary className={disclosureClass}>72시간 전향 관측 · 검증 상태</summary><div className="space-y-2 pb-3 text-gray-400">
            <p className="break-words tabular-nums">관측 등록 {value.validation.enrolled_decisions}건 · 관측 누적 중 · 시작 {clock(value.validation.started_at)}</p>
            <p>가격 신호 뒤 72시간의 사건을 비선정 대조 종목과 비교합니다. 관측 성과가 아직 없어 수익·확률·사건 발생률은 미산출이며, 우연한 동행을 배제하지 못했습니다.</p>
            <p className="break-words tabular-nums">뉴스 대조 갱신 {clock(value.captured_at)}</p>
        </div></details>
    </section>;
}
