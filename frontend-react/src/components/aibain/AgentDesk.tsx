import { agentDeskHoldMessage, agentDeskInspectionFresh, agentDeskReasonLabel, agentRoleLabels, type AgentDesk as AgentDeskContract } from '@/lib/agentDeskApi';
import { effectiveOpportunityEngine, type OpportunityEngine } from '@/lib/opportunityEngine';
import AccountPlanForm from './AccountPlanForm';

const states = { 'No-trade': '신규 진입 보류', Watch: '관찰', 'Conditional plan': '조건부 연구 계획', 'Exit review': '청산 조건 검토' };
const roleState = { passed: '통과', held: '보류', unavailable: '자료 없음' };
const explain = (codes: string[]) => Array.from(new Set(codes.map(agentDeskReasonLabel))).join(' · ');

export default function AgentDesk({ desk, board, now, blocked, token }: {
    desk?: AgentDeskContract; board: OpportunityEngine; now: number; blocked: boolean; token?: string;
}) {
    if (!desk) return <p className="mb-4 text-base leading-relaxed text-gray-400 sm:text-sm">이 저장 결과에는 계좌·출처 검사 계약이 없습니다. 연구 참고 가격을 표시하며 계좌 수량은 제공하지 않습니다.</p>;
    const effective = effectiveOpportunityEngine(board, now, blocked);
    const inspectionFresh = !blocked && agentDeskInspectionFresh(desk, now);
    const rolesFresh = inspectionFresh && desk.candidates.every(row => !!row.invalidation.valid_until && now < Date.parse(row.invalidation.valid_until));
    const receipt = desk.contract;
    const marketFresh = (check: NonNullable<AgentDeskContract['contract']>['market_checks'][number]) =>
        inspectionFresh && check.status === 'passed' && !!check.valid_until && now < Date.parse(check.valid_until);
    const contractBlocked = !!receipt && (receipt.evidence_status !== 'ready' || !receipt.market_checks.some(marketFresh));
    return <section aria-label="계좌·출처 검사" className="mb-5 min-w-0 space-y-3 text-base leading-relaxed sm:text-sm">
        <h3 className="text-lg font-semibold text-gray-100">계좌·출처 검사</h3>
        <p className="text-gray-300">미래 확률 검증 대기. TOP3 연구 참고 제안의 출처와 계좌 한도를 추가로 확인합니다.</p>
        {receipt && <div aria-label="저장 근거 계약" className="min-w-0 space-y-1 border-t border-[#30363f] pt-2">
            <p className="break-words text-gray-300">서버 정책 {receipt.policy_version} · 식별자 <span className="font-mono tabular-nums">{receipt.policy_hash.slice(0, 12)}</span></p>
            <p className={receipt.evidence_status === 'ready' ? 'text-gray-300' : 'text-amber-200'}>{({ ready: '근거 묶음 저장됨', missing: '근거 묶음 없음', held: '근거 묶음 확인 보류' })[receipt.evidence_status]}</p>
        </div>}
        {desk.candidates.length > 0 && <ul className="divide-y divide-[#30363f] border-y border-[#30363f]">{desk.candidates.map(row => {
            const sourceFresh = inspectionFresh && !!row.invalidation.valid_until && now < Date.parse(row.invalidation.valid_until);
            const market = receipt?.market_checks.find(check => check.opportunity_id === row.opportunity_id);
            const currentMarket = !!market && marketFresh(market);
            const unavailable = !sourceFresh || effective.candidates.find(r => r.opportunity_id === row.opportunity_id)?.action !== 'entry_candidate'
                || !!receipt && (receipt.evidence_status !== 'ready' || !currentMarket);
            return <li key={row.opportunity_id} className="min-w-0 py-3">
                <p className="break-words font-semibold text-gray-100">{row.name} · {row.symbol} · KR</p>
                <p className="mt-1 text-gray-300">{unavailable && row.state === 'Conditional plan' ? '관찰 · 최신 자료 확인 대기' : states[row.state]} · 출처 감사 {sourceFresh ? roleState[row.audit.status] : '갱신 대기'} · 독립 계통 {row.audit.independent_sources}개</p>
                {!sourceFresh && <p className="mt-1 text-amber-200">출처 검사와 현재 가격을 새로 확인한 뒤 계좌 한도를 계산하세요.</p>}
                {receipt && <p className={`mt-1 break-words ${currentMarket ? 'text-gray-300' : 'text-amber-200'}`}>현재 시장 가드 {market?.status === 'held' ? '보류' : currentMarket ? '통과' : '갱신 대기'}{market?.reasons.length ? ` · ${explain(market.reasons)}` : ''}</p>}
                {row.audit.reasons.length > 0 && <p className="mt-1 break-words text-amber-200">{agentDeskHoldMessage(row.audit.reasons)}</p>}
                <details className="mt-2"><summary className="min-h-11 cursor-pointer rounded py-3 font-semibold text-[#acd3ff] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb]">{row.name} 출처·확률 제한</summary>
                    {row.audit.reasons.length > 0 && <p className="break-words text-gray-300">{explain(row.audit.reasons)}</p>}
                    {row.missing.length > 0 && <p className="mt-2 break-words text-gray-300">부족 자료: {explain(row.missing)}</p>}
                    <p className="mt-2 break-words text-gray-300">{row.probability.reason}</p><p className="mt-2 break-words text-gray-300">{row.invalidation.detail}</p></details>
            </li>;
        })}</ul>}
        <details className="border-t border-[#30363f] pt-1"><summary className="min-h-11 cursor-pointer rounded py-3 font-semibold text-[#acd3ff] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb]">12개 역할 · 자료 검사 펼치기</summary>
            <div className="space-y-3"><p className="text-gray-300">역할별 저장 근거를 확인하는 12개 작업입니다. 12번의 모델 호출이나 완료된 합의를 뜻하지 않습니다.</p>
                <ul className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-3">{desk.roles.map(role => <li key={role.id} className="min-w-0 border-t border-[#30363f] pt-2">
                    <p className="font-semibold text-gray-200">{agentRoleLabels[role.id]} · {!rolesFresh && role.status === 'passed' ? '갱신 대기' : roleState[role.status]}</p><p className="mt-1 break-words text-gray-300">{role.detail}</p>
                </li>)}</ul>
                {desk.promotion.reasons.length > 0 && <p className="break-words text-gray-300">M0 제한: {explain(desk.promotion.reasons)}</p>}
            </div>
        </details>
        <AccountPlanForm key={token ?? 'current-auth'} board={board} desk={desk} now={now} blocked={blocked || contractBlocked} token={token} />
    </section>;
}
