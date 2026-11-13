import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import { fetchTechnicalProfiles, isTechnicalSymbol, queueTechnicalProfile, type TechnicalProfile, type TechnicalProfileView, type TechnicalZone } from '@/lib/kongmingTechnical';

const number = (value: number) => value.toLocaleString('ko-KR', { maximumFractionDigits: 2 });
const exact = (value: number) => value.toLocaleString('ko-KR', { maximumFractionDigits: 20 });
const money = (value: number | null) => value === null ? '미확인' : `${value.toLocaleString('ko-KR', { maximumFractionDigits: 0 })}원`;
function compact(value: number, unit: '주' | '원', estimate: boolean) {
    if (value > 0 && value < 1) return `1${unit} 미만`;
    const scale = [[1e12, '조'], [1e8, '억'], [1e4, '만']] as const;
    const matched = scale.find(([threshold]) => value >= threshold);
    if (matched) {
        const scaled = value / matched[0];
        return `약 ${scaled.toLocaleString('ko-KR', { maximumFractionDigits: scaled >= 1000 ? 0 : 1 })}${matched[1]}${unit}`;
    }
    return `${estimate || !Number.isInteger(value) ? '약 ' : ''}${value.toLocaleString('ko-KR', { maximumFractionDigits: 0 })}${unit}`;
}
function Amount({ value, unit, estimate = false }: { value: number | null; unit: '주' | '원'; estimate?: boolean }) {
    return value === null ? <>미확인</> : <span title={`${exact(value)}${unit}`}>{compact(value, unit, estimate)}</span>;
}
function PriceRange({ zone }: { zone: TechnicalZone }) {
    return <span title={`${exact(zone.low)}원${zone.high !== zone.low ? ` ~ ${exact(zone.high)}원` : ''}`}>약 {money(zone.low)}{zone.high !== zone.low && ` ~ ${money(zone.high)}`}</span>;
}
const clock = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
const statuses = { ready: '저장 결과', pending: '수집 대기', insufficient_history: '거래일 자료 부족', source_unavailable: '원천 자료 이용 불가', price_event_review: '가격 변동 사건 확인 필요', stale: '이전 저장 결과 · 갱신 필요' };
const button = 'min-h-11 rounded-lg border border-[#526a83] px-3 py-2 text-sm font-semibold text-sky-200 hover:bg-sky-400/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-300 disabled:opacity-50';
function Time({ value }: { value: string | null }) {
    return value ? <time dateTime={value}>{clock.format(Date.parse(value))}</time> : <>미확인</>;
}
function Level({ label, zone }: { label: string; zone: TechnicalZone | null }) {
    return <div aria-label={label} className="min-w-0 space-y-2 rounded-lg border border-slate-700 bg-[#101318] p-3">
        <h4 className="text-xs font-semibold text-sky-200">{label}</h4>
        {zone ? <><p className="font-semibold tabular-nums text-white"><PriceRange zone={zone} /></p>
            <p className="text-sm tabular-nums text-slate-200"><Amount value={zone.volume} unit="주" estimate /> · {number(zone.volume_pct)}%</p>
            <p className="text-xs tabular-nums text-slate-400">추정 거래대금 <Amount value={zone.traded_value} unit="원" estimate /></p></>
            : <p className="text-sm text-slate-400">해당 가격대 없음</p>}
    </div>;
}
export function TechnicalProfileCard({ row, compact: compactView = false }: { row: TechnicalProfile; compact?: boolean }) {
    const hasProfile = row.bins.length > 0;
    const zeroVolume = row.reason === 'zero_volume_window';
    const maxVolume = Math.max(...row.bins.map(bin => bin.volume), 0);
    const distribution = <div className="space-y-2"><h4 className="text-sm font-semibold text-slate-200">가격대별 추정 거래량</h4><p className="text-xs leading-5 text-slate-400">전체 거래량 대비 비중 · 기준 종가가 속한 구간 표시</p>
                <ul aria-label="가격대별 추정 거래량" className="space-y-2">{[...row.bins].reverse().map(bin => <li key={bin.index} className="min-w-0 text-xs tabular-nums">
                    <div className="mb-1 flex flex-wrap justify-between gap-x-2 gap-y-1"><span className={row.current_zone?.index === bin.index ? 'font-semibold text-sky-200' : 'text-slate-300'}><PriceRange zone={bin} />{row.current_zone?.index === bin.index && ' · 기준 종가 구간'}{row.poc?.index === bin.index && ' · POC'}</span><span className="text-slate-300"><Amount value={bin.volume} unit="주" estimate /> · {number(bin.volume_pct)}%</span></div>
                    <div aria-hidden="true" className="h-2 overflow-hidden rounded-sm bg-slate-800"><div className={`h-full ${row.current_zone?.index === bin.index ? 'bg-sky-300' : 'bg-slate-500'}`} style={{ width: `${maxVolume ? bin.volume / maxVolume * 100 : 0}%` }} /></div>
                    <span className="sr-only">추정 거래대금 <Amount value={bin.traded_value} unit="원" estimate /></span>
                </li>)}</ul></div>;
    return <article aria-label={`${row.name} 20일 매물대`} className="min-w-0 space-y-4 rounded-xl border border-[#425565] bg-[#10181f] p-3 [overflow-wrap:anywhere] sm:p-4">
        <header className="flex flex-wrap items-start justify-between gap-2"><div><h3 className="text-lg font-bold text-white">{row.name}</h3><p className="mt-1 text-xs text-slate-400">{row.symbol} · 국내 주식 · KRX</p></div>
            <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${row.status === 'ready' ? 'border-sky-300/25 text-sky-200' : 'border-amber-300/25 text-amber-200'}`}>{zeroVolume ? '기간 내 거래량 없음' : statuses[row.status]}</span></header>
        <p className="text-xs leading-5 text-slate-300">집계 {row.window_start ?? '미확인'} ~ {row.window_end ?? '미확인'} · {row.sessions_used} / {row.sessions_required} 거래일</p>
        {row.status === 'insufficient_history' && <p className="text-sm leading-6 text-amber-200">{zeroVolume ? '집계 기간에 거래량이 없어 매물대 후보를 표시하지 않습니다.' : '20거래일 자료가 부족해 매물대를 계산하지 않았습니다.'}</p>}
        {row.status === 'price_event_review' && <p className="text-sm leading-6 text-amber-200">분할·권리 등 가격 변동 사건을 확인하기 전까지 가격대를 표시하지 않습니다.</p>}
        {row.status === 'source_unavailable' && <p className="text-sm leading-6 text-amber-200">원천 자료를 확인할 수 없습니다. 다음 수집 후 저장 결과를 확인해 주세요.</p>}
        {row.status === 'pending' && <p className="text-sm leading-6 text-slate-300">자료 수집 대기 중입니다. 완료되면 저장 결과에 표시됩니다.</p>}
        {row.status === 'stale' && <p className="text-sm leading-6 text-amber-200">최신 수집을 완료하지 못해 이전에 저장된 자료를 표시합니다. 기준일을 확인해 주세요.</p>}
        <dl className="grid gap-3 sm:grid-cols-3"><div><dt className="text-xs text-slate-400">기준 종가</dt><dd className="mt-1 font-semibold tabular-nums text-white">{money(row.reference_price)}</dd><dd className="mt-1 text-xs text-slate-400">{row.as_of ?? '기준일 미확인'} · 완료된 거래일</dd></div>
            <div><dt className="text-xs text-slate-400">기간 총 거래량</dt><dd className="mt-1 font-semibold tabular-nums text-white"><Amount value={row.total_volume} unit="주" /></dd></div>
            <div><dt className="text-xs text-slate-400">기간 총 거래대금</dt><dd className="mt-1 font-semibold tabular-nums text-white"><Amount value={row.total_traded_value} unit="원" /></dd></div></dl>
        {hasProfile && <><div className="grid gap-2 lg:grid-cols-3"><Level label="최대 거래량 구간 · POC" zone={row.poc} /><Level label="지지 후보" zone={row.support} /><Level label="저항 후보" zone={row.resistance} /></div>
            {compactView ? <details data-profile-bins className="border-t border-slate-700"><summary className="flex min-h-11 cursor-pointer items-center text-sm font-semibold text-sky-200">가격대별 추정 거래량 펼치기</summary>{distribution}</details> : distribution}</>}
        <p className="text-xs leading-5 text-slate-400">일봉 OHLCV의 저가~고가 구간에 거래량·거래대금을 균등 배분한 추정치입니다. 실제 가격별 체결 내역과 다를 수 있습니다.</p>
        <details className="border-t border-slate-700 text-xs leading-5 text-slate-400"><summary className="flex min-h-11 cursor-pointer items-center font-semibold text-sky-200">자료 출처·수집 상태</summary>
            <div className="space-y-1 pb-2"><p>수집 <Time value={row.fetched_at} /> · 한국시간</p><p>시세 출처 {row.source ?? '미확인'}</p><p>거래일 출처 {row.calendar_source ?? '미확인'}</p><p>가격 기준 {row.price_basis === 'KIS_KRX_raw_J_D_1' ? 'KRX 비수정 일봉' : '미확인'}</p>
                {row.limitations.length > 0 && <ul className="list-disc space-y-1 pl-4">{row.limitations.map((line, index) => <li key={index}>{line}</li>)}</ul>}</div>
        </details>
    </article>;
}
function SavedTechnicalProfiles({ initialSymbol }: { initialSymbol?: string }) {
    const heading = useId(); const search = useId();
    const [view, setView] = useState<TechnicalProfileView | null>(null);
    const [selected, setSelected] = useState(initialSymbol ?? '');
    const [query, setQuery] = useState(initialSymbol ?? '');
    const [loading, setLoading] = useState(true); const [queuing, setQueuing] = useState(false);
    const [message, setMessage] = useState(''); const [error, setError] = useState<'access' | 'unavailable' | null>(null);
    const mounted = useRef(false); const pending = useRef(false); const queuePending = useRef(false); const denied = useRef(false);
    const queuedSymbol = useRef<string | null>(null);
    const refresh = useCallback(async () => {
        if (!mounted.current || pending.current || denied.current || document.visibilityState !== 'visible') return;
        pending.current = true; setLoading(true);
        try {
            const next = await fetchTechnicalProfiles();
            if (mounted.current && !denied.current) {
                setView(next); setError(null);
                if (queuedSymbol.current && next.items.some(item => item.symbol === queuedSymbol.current && item.status !== 'pending')) {
                    queuedSymbol.current = null; setMessage('');
                }
            }
        } catch (failure) {
            if (!mounted.current) return;
            const access = failure instanceof Error && 'status' in failure && [401, 403].includes(Number(failure.status));
            if (access) { denied.current = true; setView(null); setMessage(''); }
            setError(access ? 'access' : 'unavailable');
        } finally { pending.current = false; if (mounted.current) setLoading(false); }
    }, []);
    useEffect(() => { mounted.current = true; void refresh(); return () => { mounted.current = false; }; }, [refresh]);
    useAutoRefresh(refresh, 30000, error !== 'access');
    const rows = [...(view?.items ?? [])].sort((a, b) => (b.fetched_at ? Date.parse(b.fetched_at) : 0) - (a.fetched_at ? Date.parse(a.fetched_at) : 0));
    const normalized = query.trim().toLocaleLowerCase('ko-KR');
    const matches = rows.filter(row => `${row.name} ${row.symbol}`.toLocaleLowerCase('ko-KR').includes(normalized));
    const manual = query.trim().toUpperCase();
    const target = isTechnicalSymbol(manual) ? manual : rows.find(row => row.name === query.trim())?.symbol;
    const row = selected ? rows.find(item => item.symbol === selected) : rows[0];
    async function queue() {
        if (!target || queuePending.current || denied.current || !mounted.current) return;
        queuePending.current = true; setQueuing(true); setMessage(''); setSelected(target);
        try {
            const receipt = await queueTechnicalProfile(target);
            if (!mounted.current || denied.current) return;
            queuedSymbol.current = receipt.status === 'queued' ? target : null;
            setMessage(receipt.status === 'queued' ? `${target} 자료 수집 대기 중입니다. 완료되면 자동으로 표시됩니다.` : `${target} 저장된 최신 결과를 확인했습니다.`);
            await refresh();
        } catch (failure) {
            if (!mounted.current) return;
            const access = failure instanceof Error && 'status' in failure && [401, 403].includes(Number(failure.status));
            if (access) { denied.current = true; setView(null); setError('access'); }
            else setMessage('조회 요청을 접수하지 못했습니다. 잠시 후 다시 요청해 주세요.');
        } finally { queuePending.current = false; if (mounted.current) setQueuing(false); }
    }
    return <section id="technical-profiles" aria-labelledby={heading} aria-busy={loading || queuing} className="ai-panel min-w-0 scroll-mt-20 space-y-4 border border-[#365372] p-4 sm:p-5">
        <header className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h2 id={heading} className="ai-section-title text-xl">기술적 분석 에이전트 · 20일 매물대</h2><p className="mt-2 text-sm leading-6 text-slate-300">최근 완료된 20거래일의 거래량 분포로 지지·저항 가격대 후보를 확인합니다.</p></div>
            <button type="button" onClick={() => void refresh()} disabled={loading || error === 'access'} className={button}>매물대 저장 결과 새로고침</button></header>
        <form onSubmit={event => { event.preventDefault(); void queue(); }} className="space-y-2"><label htmlFor={search} className="block text-xs font-semibold text-slate-300">기술 분석 종목명 또는 코드</label><div className="flex flex-col gap-2 sm:flex-row">
            <input id={search} type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="저장된 종목명 또는 영문·숫자 6자리 코드" autoComplete="off" maxLength={80} disabled={error === 'access'} className="min-h-11 w-full min-w-0 rounded-lg border border-[#526a83] bg-[#101318] px-3 text-sm text-white placeholder:text-slate-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-300 disabled:opacity-50" />
            <button type="submit" disabled={!target || queuing || error === 'access'} className={`${button} shrink-0`}>{queuing ? '요청 중…' : '매물대 조회 요청'}</button></div>
            <p className="text-xs leading-5 text-slate-400">저장된 종목은 이름으로 선택할 수 있습니다. 새 종목은 6자리 코드로 수집을 요청하세요.</p>
        </form>
        {matches.length > 0 && error !== 'access' && <div className="space-y-2"><p className="text-xs text-slate-400">{normalized ? '일치하는 저장 종목' : '최근 수집 후보'}</p><div className="flex flex-wrap gap-2">{matches.slice(0, 8).map(item => <button key={item.symbol} type="button" aria-label={`${item.name} ${item.symbol} 선택`} aria-pressed={row?.symbol === item.symbol} onClick={() => { setSelected(item.symbol); setQuery(item.name); setMessage(''); }} className={`${button} text-xs aria-pressed:border-sky-300`}>{item.name} <span className="tabular-nums text-slate-400">{item.symbol}</span></button>)}</div></div>}
        {message && <p role="status" className="text-sm leading-6 text-sky-200">{message}</p>}
        {loading && !view && <p role="status" className="text-sm text-slate-300">저장된 매물대를 불러오는 중…</p>}
        {error && <p role="alert" className="text-sm leading-6 text-amber-200">{error === 'access' ? '기술적 분석 이용 권한을 확인해 주세요. 로그인 상태와 제갈공명 구독을 확인하세요.' : view ? '결과 갱신이 지연되어 이전에 저장된 자료를 표시합니다. 기준일을 확인해 주세요.' : '매물대 조회가 지연되고 있습니다. 잠시 후 저장 결과를 다시 조회해 주세요.'}</p>}
        {view && <><p className="text-xs text-slate-400">마지막 수집 실행 <Time value={view.last_run_at} /> · 한국시간</p>{row ? <TechnicalProfileCard row={row} /> : <p className="rounded-lg border border-slate-700 p-4 text-sm leading-6 text-slate-300">{selected ? `${selected} 저장 결과가 아직 없습니다. 수집 요청 후 완료를 기다려 주세요.` : '저장된 매물대가 없습니다. 종목 코드를 입력해 수집을 요청할 수 있습니다.'}</p>}</>}
        <p className="text-xs leading-5 text-slate-400">과거 체결량의 추정 분포이며 현재 보유 물량이나 호가 잔량을 뜻하지 않습니다. 지지·저항 후보가 실제 반등·돌파를 보장하지 않습니다.</p>
        <p className="text-xs leading-5 text-slate-400">30초마다 저장 결과만 조회합니다. 자동 조회로 추가 유료 AI 분석이나 주문을 실행하지 않습니다.</p>
    </section>;
}
export default function KongmingTechnicalPanel({ token, initialSymbol }: { token?: string; initialSymbol?: string }) {
    return token ? <SavedTechnicalProfiles key={`${token}:${initialSymbol ?? ''}`} initialSymbol={initialSymbol && isTechnicalSymbol(initialSymbol) ? initialSymbol : undefined} /> : null;
}
