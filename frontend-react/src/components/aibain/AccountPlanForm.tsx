import { useEffect, useId, useRef, useState } from 'react';
import { agentDeskHoldMessage, agentDeskInspectionFresh, agentDeskReasonLabel, requestAccountPlan, validAccountInput, type AccountInput, type AccountPlan, type AgentDesk } from '@/lib/agentDeskApi';
import { effectiveOpportunityEngine, type OpportunityEngine } from '@/lib/opportunityEngine';

const button = '!min-h-11 rounded-lg border border-[#365372] px-3 py-2 text-base font-semibold text-[#acd3ff] hover:bg-[#1b2c40] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb] disabled:cursor-not-allowed disabled:opacity-50 sm:text-sm';
const input = 'mt-1 !min-h-11 w-full min-w-0 rounded-lg border border-[#536579] bg-[#0d141c] px-3 py-2 text-base tabular-nums text-gray-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb]';
const money = (value: number) => `${Math.round(value).toLocaleString('ko-KR')}원`;
const clock = (value: string) => `${new Date(Date.parse(value) + 9 * 3600000).toISOString().slice(0, 16).replace('T', ' ')} KST`;
const explain = (codes: string[]) => Array.from(new Set(codes.map(agentDeskReasonLabel))).join(' · ');
type DraftPosition = { symbol: string; theme: string; market_value: string };
type Draft = { equity: string; available_cash: string; daily_pnl: string; weekly_pnl: string };
const initialDraft: Draft = { equity: '', available_cash: '', daily_pnl: '', weekly_pnl: '' };
const parsed = (value: string) => value.trim() === '' ? NaN : Number(value);

export default function AccountPlanForm({ board, desk, now, blocked, token }: {
    board: OpportunityEngine; desk: AgentDesk; now: number; blocked: boolean; token?: string;
}) {
    const heading = useId();
    const [draft, setDraft] = useState<Draft>(initialDraft);
    const [holdingsMode, setHoldingsMode] = useState<'empty' | 'positions' | null>(null);
    const [positions, setPositions] = useState<DraftPosition[]>([]);
    const [confirmed, setConfirmed] = useState(false);
    const [pending, setPending] = useState(false);
    const [error, setError] = useState('');
    const [currentTime, setCurrentTime] = useState(now);
    const [result, setResult] = useState<{ plan: AccountPlan; context: string; edit: number } | null>(null);
    const edit = useRef(0), generation = useRef(0), mounted = useRef(true);
    const clockNow = Math.max(now, currentTime, Date.now());
    const effective = effectiveOpportunityEngine(board, clockNow, blocked);
    const context = JSON.stringify([token, board, desk, agentDeskInspectionFresh(desk, clockNow), effective.candidates.map(row => [row.opportunity_id, row.action, row.current_price, row.reference_weight]),
        desk.candidates.map(row => [row.opportunity_id, !!row.invalidation.valid_until && clockNow < Date.parse(row.invalidation.valid_until)])]);
    const latest = useRef({ context, blocked }); latest.current = { context, blocked };
    const account: AccountInput = {
        equity: parsed(draft.equity), available_cash: parsed(draft.available_cash), daily_pnl: parsed(draft.daily_pnl), weekly_pnl: parsed(draft.weekly_pnl),
        positions_confirmed: true, positions: holdingsMode === 'positions' ? positions.map(row => ({ ...row, symbol: row.symbol.trim(), theme: row.theme.trim(), market_value: parsed(row.market_value) })) : [],
    };
    const factsConfirmed = holdingsMode === 'empty' || holdingsMode === 'positions' && positions.length > 0 && confirmed;
    const canSubmit = !blocked && !pending && factsConfirmed && validAccountInput(account) && board.candidates.length > 0;
    const visible = result && result.context === context && result.edit === edit.current && !blocked
        && (result.plan.status !== 'ready' || !!result.plan.valid_until && clockNow < Date.parse(result.plan.valid_until)
            && result.plan.plans.every(p => p.status !== 'ready' || effective.candidates.some(row => row.opportunity_id === p.opportunity_id && row.action === 'entry_candidate')))
        && (result.plan.status !== 'ready' || agentDeskInspectionFresh(desk, clockNow) && desk.candidates.every(row => !!row.invalidation.valid_until && clockNow < Date.parse(row.invalidation.valid_until)))
        ? result.plan : null;
    useEffect(() => {
        generation.current++; setResult(null); setPending(false); setError('');
    }, [context, blocked]);
    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; generation.current++; };
    }, []);
    useEffect(() => {
        if (!result?.plan.valid_until) return;
        const expiry = Date.parse(result.plan.valid_until);
        if (expiry <= Date.now()) { setResult(null); return; }
        const timer = setTimeout(() => { generation.current++; setCurrentTime(Date.now()); setResult(null); }, Math.min(expiry - Date.now(), 2147483647));
        return () => clearTimeout(timer);
    }, [result]);
    const invalidate = () => { edit.current++; generation.current++; setResult(null); setError(''); setPending(false); };
    const submit = async (event: React.FormEvent) => {
        event.preventDefault(); if (!canSubmit) return;
        const current = ++generation.current; const submittedEdit = edit.current;
        setResult(null); setError(''); setPending(true);
        try {
            const plan = await requestAccountPlan(account, board, desk, token);
            if (mounted.current && current === generation.current && latest.current.context === context && !latest.current.blocked && submittedEdit === edit.current) {
                setResult({ plan, context, edit: submittedEdit }); setCurrentTime(Date.now());
            }
        } catch {
            if (mounted.current && current === generation.current && latest.current.context === context && !latest.current.blocked) {
                setResult(null); setError('계좌 한도 계산을 확인하지 못했습니다. 최신 저장 자료와 입력값을 확인해 주세요.');
            }
        } finally { if (mounted.current && current === generation.current) setPending(false); }
    };
    const changePosition = (index: number, field: keyof DraftPosition, value: string) => {
        invalidate(); setConfirmed(false); setPositions(old => old.map((row, i) => i === index ? { ...row, [field]: value } : row));
    };
    return <details className="min-w-0 border-t border-[#365372] pt-1">
        <summary className="min-h-11 cursor-pointer rounded py-3 text-base font-semibold text-[#acd3ff] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb]">계좌 한도 계산 · 연구 참고</summary>
        <div className="mt-2 min-w-0 space-y-4 text-base leading-relaxed sm:text-sm">
            <p className="text-gray-300">실제 계좌의 현금·손익·보유 종목을 입력하면 별도 한도를 계산합니다. 입력값은 이번 요청에만 사용하며 저장하지 않습니다.</p>
            <p className="text-gray-300">거래별 계획 위험 0.5% · 오늘 손실 1.5% / 주간 손실 4%에서 신규 진입 중단 · 현금 최소 40% · 종목 최대 5% · 동일 테마 최대 30% · 동시 보유 최대 3종목</p>
            <p className="text-amber-200">갭 하락·체결 차이로 실제 손실이 계획 손실보다 클 수 있습니다. 계산 완료는 CIO·전략 승인이나 주문 허용을 뜻하지 않습니다.</p>
            <form onSubmit={submit} aria-labelledby={heading} className="min-w-0 space-y-4" autoComplete="off">
                <h4 id={heading} className="font-semibold text-gray-100">계좌 정보 · 직접 확인한 값</h4>
                <div className="grid min-w-0 gap-3 sm:grid-cols-2">{([
                    ['equity', '총자산 (원)'], ['available_cash', '주문 가능 현금 (원)'], ['daily_pnl', '오늘 손익 (원)'], ['weekly_pnl', '이번 주 손익 (원)'],
                ] as Array<[keyof Draft, string]>).map(([field, label]) => <label key={field} className="min-w-0 text-gray-200">{label}
                    <input type="number" inputMode="decimal" step="any" required autoComplete="off" value={draft[field]} className={input}
                        min={field === 'equity' ? 1 : field === 'available_cash' ? 0 : undefined}
                        onChange={event => { invalidate(); setDraft(old => ({ ...old, [field]: event.target.value })); }} /></label>)}</div>
                <p className="text-gray-400">손익이 없으면 0을 직접 입력하세요. 손실은 음수로 입력합니다.</p>
                <fieldset className="min-w-0 space-y-2"><legend className="mb-1 font-semibold text-gray-100">현재 보유 종목 확인</legend>
                    <label className="flex min-h-11 cursor-pointer items-center gap-3 text-gray-200"><input type="checkbox" className="h-5 w-5 shrink-0 accent-[#72b4fb]" checked={holdingsMode === 'empty'}
                        onChange={event => { invalidate(); setHoldingsMode(event.target.checked ? 'empty' : null); setConfirmed(false); setPositions([]); }} />현재 보유 종목이 없습니다</label>
                    <label className="flex min-h-11 cursor-pointer items-center gap-3 text-gray-200"><input type="checkbox" className="h-5 w-5 shrink-0 accent-[#72b4fb]" checked={holdingsMode === 'positions'}
                        onChange={event => { invalidate(); setHoldingsMode(event.target.checked ? 'positions' : null); setConfirmed(false); }} />보유 종목을 입력합니다</label>
                    {holdingsMode === 'positions' && <div className="space-y-3">{positions.map((row, index) => <div key={index} className="min-w-0 space-y-3 rounded-lg border border-[#30363f] p-3">
                        <div className="grid min-w-0 gap-3 sm:grid-cols-3"><label className="min-w-0 text-gray-200">보유 {index + 1} 종목 코드<input className={input} inputMode="numeric" required maxLength={6} value={row.symbol} onChange={event => changePosition(index, 'symbol', event.target.value)} /></label>
                            <label className="min-w-0 text-gray-200">보유 {index + 1} 테마<input className={input} required maxLength={80} value={row.theme} onChange={event => changePosition(index, 'theme', event.target.value)} /></label>
                            <label className="min-w-0 text-gray-200">보유 {index + 1} 평가금액 (원)<input className={input} type="number" inputMode="decimal" min={1} step="any" required value={row.market_value} onChange={event => changePosition(index, 'market_value', event.target.value)} /></label></div>
                        <button type="button" className={button} aria-label={`보유 ${index + 1} 삭제`} onClick={() => { invalidate(); setConfirmed(false); setPositions(old => old.filter((_, i) => i !== index)); }}>보유 종목 삭제</button>
                    </div>)}<button type="button" className={button} disabled={positions.length >= 100} onClick={() => { invalidate(); setConfirmed(false); setPositions(old => [...old, { symbol: '', theme: '', market_value: '' }]); }}>보유 종목 추가</button>
                        <label className="flex min-h-11 cursor-pointer items-center gap-3 text-gray-200"><input type="checkbox" className="h-5 w-5 shrink-0 accent-[#72b4fb]" checked={confirmed} onChange={event => { invalidate(); setConfirmed(event.target.checked); }} />모든 보유 종목과 평가금액을 확인했습니다</label></div>}
                </fieldset>
                {blocked && <p role="status" className="text-amber-200">저장 자료를 확인 중이거나 갱신에 실패하여 계산 결과를 보류합니다.</p>}
                <button type="submit" className={`${button} w-full sm:w-auto`} disabled={!canSubmit}>{pending ? '계좌 한도 확인 중…' : '계좌 한도 계산'}</button>
            </form>
            {error && <p role="alert" className="break-words text-amber-200">{error}</p>}
            {visible && <section aria-label="계좌 한도 계산 결과" className="space-y-3 border-t border-[#30363f] pt-3">
                <h4 className="font-semibold text-gray-100">{visible.status === 'ready' ? '한도 계산 완료 · 연구 참고' : visible.status === 'halt' ? '신규 진입 중단' : '계좌 한도 계산 보류'}</h4>
                {visible.status !== 'ready' && <p className="break-words text-amber-200">{agentDeskHoldMessage(visible.reasons)}</p>}
                {visible.plans.map(plan => <div key={plan.opportunity_id} className="min-w-0 border-t border-[#30363f] pt-3">
                    <p className="break-words font-semibold text-gray-100">{plan.name} · {plan.symbol} · KR</p>
                    {plan.status === 'ready' && plan.quantity !== null && <><p aria-label={`${plan.name} 계좌 참고 수량`} className="mt-2 text-xl font-semibold tabular-nums text-[#acd3ff]">참고 수량 {plan.quantity.toLocaleString('ko-KR')}주</p>
                        <dl className="mt-2 space-y-1 tabular-nums">{[['참고 예산', money(plan.budget)], ['계획 손실', money(plan.planned_loss)], ['계좌 참고 비중', `${(plan.weight * 100).toFixed(2)}%`]].map(([label, value]) => <div key={label} className="flex flex-wrap justify-between gap-2"><dt className="text-gray-300">{label}</dt><dd className="font-mono text-gray-100">{value}</dd></div>)}</dl></>}
                    {plan.status !== 'ready' && plan.reasons.length > 0 && <p className="mt-2 break-words text-gray-300">{agentDeskHoldMessage(plan.reasons)}</p>}
                </div>)}
                {visible.valid_until && <p className="tabular-nums text-gray-300">계산 유효기한 {clock(visible.valid_until)} · 가격·계좌·출처 변경 시 다시 계산</p>}
                <p className="text-gray-400">실제 주문 실행 없음 · 기존 TOP3의 연구 참고 비중과 계좌 한도는 별도입니다.</p>
                {visible.reasons.length > 0 && <details><summary className="min-h-11 cursor-pointer rounded py-3 font-semibold text-[#acd3ff] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#72b4fb]">계산 보류·한도 근거 펼치기</summary><p className="break-words text-gray-300">{explain(visible.reasons)}</p></details>}
            </section>}
        </div>
    </details>;
}
