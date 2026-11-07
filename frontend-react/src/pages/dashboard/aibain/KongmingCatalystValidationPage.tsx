import '@/pages/dashboard/ai-design.css';
import { useCallback, useEffect, useRef, useState } from 'react';
import AiBrainServiceTabs from '@/components/aibain/AiBrainServiceTabs';
import { useAuth } from '@/contexts/AuthContext';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import { ApiError, fetchAPI } from '@/lib/api';
import { canAccessKongming } from '@/lib/auth';

const endpoint = '/api/admin/mirofish/kongming/catalyst-validation';
const legacyQuoteExpirySeconds = 60;
const panel = 'ai-panel min-w-0 space-y-3 border border-[#30363f] p-4 sm:p-5';
const evidence = 'min-w-0 space-y-2 break-words rounded-xl border border-[#425565] p-3 sm:p-4';
const detailsStyle = 'rounded-lg border border-[#30363f] p-3';
const styleLabels = [['scalp', '단타'], ['swing', '스윙'], ['close', '종가베팅']] as const;
type Style = typeof styleLabels[number][0];

interface SymbolRow { name?: string; symbol?: string }
interface Setup { label?: string; complete?: boolean; failed?: string[]; missing?: string[] }
interface SwingWatch {
    source_as_of?: string;
    population?: number;
    baseline_count?: number;
    common_watch_count?: number;
    baseline_rows?: (SymbolRow & { common_pass?: boolean; failed_common?: string[]; missing_common?: string[] })[];
    watch_rows?: (SymbolRow & { setups?: Record<string, Setup | null> })[];
    common_funnel?: { label?: string; count?: number }[];
}
interface StyleResult {
    state?: string;
    technical_pass?: boolean;
    qualified?: boolean;
    eligible?: boolean;
    currently_eligible?: boolean;
    blockers?: string[];
    quote?: {
        observed_at?: string | null;
        received_at?: string | null;
        plan?: { valid_until?: string | null } | null;
    } | null;
}
interface Claim {
    metric?: string;
    article_amount_krw?: string | number | null;
    official_amount_krw?: string | number | null;
    verified?: boolean;
}
interface FilingCheck {
    status?: string;
    url?: string;
    filing?: { report_nm?: string };
    claims?: Claim[];
}
interface CatalystRow extends SymbolRow {
    task_id?: string;
    article_title?: string;
    article_url?: string;
    article_published_at?: string;
    first_seen_at?: string;
    checked_at?: string;
    primary?: { status?: string; checks?: FilingCheck[] };
    styles?: Partial<Record<Style, StyleResult | null>>;
}
interface HistoryRow extends SymbolRow {
    id?: string;
    checked_at?: string;
    primary?: { status?: string };
    market_state?: string;
    buy_eligible?: boolean;
}
interface Dashboard {
    computed_at?: string;
    items?: CatalystRow[];
    swing_watch?: SwingWatch | null;
    history_count?: number;
    current_eligible_count?: number;
    quote_expiry_seconds?: number | null;
    operation?: {
        state?: string; error_type?: string; market_open?: boolean; task_count?: number; price_probed?: number;
        task_errors?: Record<string, number>; watch_error?: string;
    };
    live?: {
        last_run_at?: string | null; last_change_at?: string | null; age_seconds?: number | null;
        stalled?: boolean; worker_interval_seconds?: number;
    };
}

const primaryLabels: Record<string, string> = {
    waiting: '공식 대조 대기',
    verified_numeric_claims: '명시된 실적 금액 대조 통과',
    related_filing_found: '관련 공시 확인 · 주장 미확정',
    no_matching_filing: '관련 공시 미발견 · 확인 범위 한정',
    document_unavailable: '공시 원문 해석/제공 오류',
    official_source_failed: '공식 자료 수신 실패',
    issuer_name_conflict: '공식 발행사 명칭 불일치 · 연결 보류',
};
const styleStates: Record<string, string> = {
    market_closed: '진입 시간창 밖 · 다음 정규장 자동 재검증',
    awaiting_post_receipt_data: '기사 이후 분봉·호가 대기',
    technical_checked: '신규 기술 조건 검사',
    plan_or_quote_unverified: '가격 계획·호가 미확인',
    prior_daily_setups_checked: '전일 확정 셋업 검사',
    latest_completed_daily_source_missing: '최신 확정 일봉 대기',
};
function label(labels: Record<string, string>, value?: string) {
    if (typeof value !== 'string' || !value) return '미확인';
    const translated = labels[value];
    return typeof translated === 'string' ? translated : value;
}
const count = (value?: number | null, unit = '') => typeof value === 'number' && Number.isFinite(value) ? `${value}${unit}` : '미확인';
const amount = (value?: string | number | null) => typeof value === 'string'
    ? /^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(value) ? `${value}원` : '미확인'
    : count(value, '원');
const stamp = (value?: string | null) => value && Number.isFinite(Date.parse(value))
    ? new Date(value).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }) : '미확인';
const isAccessError = (error: unknown) => error instanceof ApiError && (error.status === 401 || error.status === 403);

function quoteTime(value?: string | null) {
    return typeof value === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? Date.parse(value) : NaN;
}

function currentEligibilityDeadline(style: StyleResult, expirySeconds: number | null, now: number) {
    if (style.currently_eligible !== true || typeof expirySeconds !== 'number'
        || !Number.isFinite(expirySeconds) || expirySeconds <= 0) return null;
    const { quote } = style;
    const observed = quoteTime(quote?.observed_at);
    const received = quoteTime(quote?.received_at);
    if (!Number.isFinite(observed) || !Number.isFinite(received) || Math.max(observed, received) > now) return null;

    const planDeadline = quote?.plan === null ? NaN
        : quote?.plan?.valid_until === undefined ? Infinity : quoteTime(quote.plan.valid_until);
    const deadline = Math.min(observed + expirySeconds * 1000, received + expirySeconds * 1000, planDeadline);
    return Number.isFinite(deadline) && deadline > now ? deadline : null;
}

function SourceLink({ url, text }: { url?: string; text?: string }) {
    let href: string | undefined;
    try {
        if (url) {
            const parsed = new URL(url);
            if (parsed.protocol === 'https:' && !parsed.port && !parsed.username && !parsed.password
                && ['www.businesspost.co.kr', 'dart.fss.or.kr'].includes(parsed.hostname)) href = parsed.href;
        }
    } catch { /* Preserve the label when the source URL is invalid. */ }
    return href
        ? <a className="text-sky-300 underline-offset-2 hover:underline" href={href} target="_blank" rel="noopener noreferrer">{text ?? '원문'}</a>
        : <span>{text ?? '미확인'}</span>;
}

function VerificationClock({ view, stale }: { view: Dashboard; stale: boolean }) {
    const { live, operation } = view;
    const run = stamp(live?.last_run_at);
    const age = live?.age_seconds;
    const elapsed = typeof age === 'number' && Number.isFinite(age) && age >= 0
        ? age < 60 ? `${age}초 전` : `${Math.round(age / 60)}분 전` : '미확인';
    if (stale || !live || (live.stalled !== true && (live.stalled !== false || run === '미확인'))) {
        return <p role="status" className="text-slate-400">자동검증 상태 확인할 수 없음 · 마지막 실행 {run} · 마지막 변경 {stamp(live?.last_change_at ?? view.computed_at)}</p>;
    }
    if (live.stalled || operation?.state === 'error' || operation?.state === 'busy') {
        return <p role="status" className="text-amber-300">자동검증 멈춤 · 마지막 실행 {run} ({elapsed}){operation?.error_type ? ` · ${operation.error_type}` : ''}</p>;
    }
    return (
        <p role="status" className="text-slate-300">
            자동검증 작동 중 · 마지막 실행 {run} ({elapsed}) · {operation?.market_open === true ? '장중' : operation?.market_open === false ? '장외' : '장 상태 미확인'}
            {' · 대상 '}{count(operation?.task_count, '건')}{' · 시세 조회 '}{count(operation?.price_probed, '종목')}
            {operation?.task_errors && Object.keys(operation.task_errors).length > 0 && ` · 일부 오류 ${Object.entries(operation.task_errors).map(([name, total]) => `${name} ${total}`).join(', ')}`}
            {operation?.watch_error && ` · 스윙 원장 오류 ${operation.watch_error}`} · 마지막 변경 {stamp(live.last_change_at)}
        </p>
    );
}

function SwingWatchDetails({ watch }: { watch: SwingWatch | null | undefined }) {
    if (!watch) return <p>검증된 전체시장 일봉 원장 대기 · 완료 관찰 명단은 보존합니다.</p>;
    return (
        <section className="space-y-3" aria-label="스윙 검토 후보">
            <h3 className="ai-section-title text-base">스윙 검토 후보 · 공통 조건 통과 {count(watch.common_watch_count, '종목')}</h3>
            <p>기존 1차 수식 통과 {count(watch.baseline_count, '종목')} / 전체 {count(watch.population, '종목')} · 확정 일봉 {watch.source_as_of ?? '미확인'}</p>
            <p>관찰 단계입니다. 수축·돌파·눌림 완성 조건과 성과 기준은 그대로 유지합니다.</p>
            {watch.watch_rows?.length ? watch.watch_rows.map(row => (
                <article key={row.symbol} className={evidence}>
                    <h4 className="font-semibold">{row.name} <code>{row.symbol}</code> · 셋업 관찰</h4>
                    {Object.entries(row.setups ?? {}).map(([key, setup]) => (
                        <p key={key}>
                            {setup?.label ?? key}: {setup?.complete === true ? '기술 조건 완성 · 성과 별도' : setup?.complete === false ? '셋업 미완성' : '미확인'}
                            {!!setup?.failed?.length && <><br />미충족: {setup.failed.join(' / ')}</>}
                            {!!setup?.missing?.length && <><br />자료 부족: {setup.missing.join(' / ')}</>}
                        </p>
                    ))}
                    <p>매수 적격 아님 · 연구 관찰만으로 텔레그램 발송하지 않습니다.</p>
                </article>
            )) : <p>{watch.watch_rows ? '공통 조건 교집합 없음 · 아래 1차 명단과 조건별 수를 확인하세요.' : '공통 조건 명단 미확인'}</p>}
            <details className={detailsStyle}>
                <summary className="cursor-pointer font-medium">1차 수식 통과 전체 {count(watch.baseline_count, '종목')} 명단</summary>
                <ul className="mt-2 max-h-[480px] space-y-2 overflow-auto">
                    {watch.baseline_rows?.map(row => (
                        <li key={row.symbol} className="flex flex-wrap gap-x-2">
                            <strong>{row.name}</strong><code>{row.symbol}</code>
                            <span>{row.common_pass === true ? '공통 조건 통과' : row.common_pass === false
                                ? `공통 미충족 ${count(row.failed_common?.length)} / 자료 부족 ${count(row.missing_common?.length)}` : '공통 조건 미확인'}</span>
                        </li>
                    ))}
                </ul>
            </details>
            <details className={detailsStyle}>
                <summary className="cursor-pointer font-medium">기존 공통 조건별 누적 교집합</summary>
                {watch.common_funnel?.map((step, index) => <p key={index}>{step.label ?? '조건 미확인'} → {count(step.count, '종목')}</p>)}
                <p>문턱을 낮추거나 일부 조건만 통과한 종목을 완성 신호로 바꾸지 않습니다.</p>
            </details>
        </section>
    );
}

function ArticleEvidence({ row, activeStyles, eligibilityUnknown }: {
    row: CatalystRow;
    activeStyles: ReadonlySet<StyleResult>;
    eligibilityUnknown: boolean;
}) {
    const checks = row.primary?.checks;
    return (
        <article className={evidence}>
            <h4 className="font-semibold">{row.name ?? '종목 미확인'} <code>{row.symbol}</code></h4>
            <p><SourceLink url={row.article_url} text={row.article_title} /></p>
            <p>{label(primaryLabels, row.primary?.status)}</p>
            {styleLabels.map(([key, name]) => {
                const result = row.styles?.[key];
                const state = !eligibilityUnknown && result && activeStyles.has(result) ? '현재 매수 적격'
                    : result?.eligible === true ? eligibilityUnknown ? '이전 적격 확인 · 현재 상태 미확인' : '이전 적격 확인 만료'
                    : result?.technical_pass === true ? '기술 통과 · 성과/실행 보류' : label(styleStates, result?.state);
                return <p key={key}><strong>{name}</strong> · {state}</p>;
            })}
            <details className={detailsStyle}>
                <summary className="cursor-pointer font-medium">공식 근거·미충족·시각</summary>
                <div className="mt-2 space-y-2">
                    {checks?.length ? checks.map((check, index) => (
                        <div key={index}>
                            <p><SourceLink url={check.url} text={check.filing?.report_nm} /> · {label(primaryLabels, check.status)}</p>
                            {check.claims?.map((claim, claimIndex) => (
                                <p key={claimIndex}>{claim.metric ?? '항목 미확인'} · 기사 {amount(claim.article_amount_krw)} / 공식 {amount(claim.official_amount_krw)}
                                    {' · '}{claim.verified === true ? '해당 금액 대조 통과' : claim.verified === false ? '미확정/불일치' : '검증 상태 미확인'}</p>
                            ))}
                        </div>
                    )) : <p>{checks ? '공식 공시 목록 조회 범위에서 연결되는 원문 없음 · 허위라고 단정하지 않습니다.' : '공식 근거 확인 대기'}</p>}
                    <p>최초 수신 {stamp(row.first_seen_at)} · 확인 {stamp(row.checked_at)} KST</p>
                    {styleLabels.map(([key, name]) => {
                        const result = row.styles?.[key];
                        return (
                            <p key={key}>{name}: 기술 {result?.technical_pass === true ? '통과' : '미확인/미충족'} · 성과 {result?.qualified === true ? '기존 동일정책 검증 통과' : '검증 미완료'}
                                <br />차단 {result?.blockers ? result.blockers.join(', ') || '없음' : '미확인'}
                                <br />호가 관측 {stamp(result?.quote?.observed_at)} · 수신 {stamp(result?.quote?.received_at)}</p>
                        );
                    })}
                </div>
            </details>
        </article>
    );
}

function latestBySymbol(rows: CatalystRow[], activeStyles: ReadonlySet<StyleResult>) {
    const hasEligibility = (row: CatalystRow) => Object.values(row.styles ?? {}).some(style => style && activeStyles.has(style));
    const sorted = [...rows].sort((a, b) => Number(hasEligibility(b)) - Number(hasEligibility(a))
        || (b.article_published_at ?? '').localeCompare(a.article_published_at ?? ''));
    const seen = new Set<string>();
    return sorted.filter(row => {
        if (!row.symbol) return true;
        if (seen.has(row.symbol)) return false;
        seen.add(row.symbol);
        return true;
    });
}

function CatalystPanel({ canRead }: { canRead: boolean }) {
    const [result, setResult] = useState<{ view: Dashboard; history: HistoryRow[] } | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<'access' | 'unavailable' | null>(null);
    const [eligibilityClock, setEligibilityClock] = useState(() => Date.now());
    const [needsVisibleRefresh, setNeedsVisibleRefresh] = useState(() => document.visibilityState !== 'visible');
    const mounted = useRef(false);
    const pending = useRef(false);
    const denied = useRef(false);
    const refresh = useCallback(async () => {
        if (!canRead || pending.current || denied.current) return;
        pending.current = true;
        setBusy(true);
        const guardAccess = (failure: unknown): never => {
            if (isAccessError(failure) && mounted.current) {
                denied.current = true;
                setResult(null);
                setError('access');
            }
            throw failure;
        };
        try {
            const [dashboardReply, historyReply] = await Promise.allSettled([
                fetchAPI<Dashboard>(endpoint, 8000).catch(guardAccess),
                fetchAPI<{ items?: HistoryRow[] }>(`${endpoint}-history`, 8000).catch(guardAccess),
            ]);
            if (denied.current) return;
            if (dashboardReply.status === 'rejected') throw dashboardReply.reason;
            if (historyReply.status === 'rejected') throw historyReply.reason;
            const view = dashboardReply.value;
            const history = historyReply.value;
            if (!view || typeof view !== 'object' || Array.isArray(view) || (view.items != null && !Array.isArray(view.items))
                || !Array.isArray(history?.items)) throw new Error('Invalid validation response');
            if (mounted.current) {
                setResult({ view, history: history.items });
                setError(null);
                setEligibilityClock(Date.now());
                setNeedsVisibleRefresh(document.visibilityState !== 'visible');
            }
        } catch {
            if (mounted.current && !denied.current) setError('unavailable');
        } finally {
            pending.current = false;
            if (mounted.current) setBusy(false);
        }
    }, [canRead]);
    useEffect(() => {
        mounted.current = true;
        void refresh();
        return () => { mounted.current = false; };
    }, [refresh]);
    useEffect(() => {
        const markRefreshNeeded = () => setNeedsVisibleRefresh(true);
        document.addEventListener('visibilitychange', markRefreshNeeded);
        return () => document.removeEventListener('visibilitychange', markRefreshNeeded);
    }, []);
    useAutoRefresh(refresh, 15000, canRead && error !== 'access');

    const accessDenied = !canRead || error === 'access';
    const view = accessDenied ? undefined : result?.view;
    const watch = view?.swing_watch;
    const stale = error === 'unavailable';
    const eligibilityUnknown = stale || needsVisibleRefresh;
    const activeStyles = new Set<StyleResult>();
    let activeRowCount = 0;
    let nextExpiry = Infinity;
    // Only shorten a source-approved decision. The server owns all strategy and session gates.
    if (view?.items) {
        const expirySeconds = view.quote_expiry_seconds === undefined ? legacyQuoteExpirySeconds : view.quote_expiry_seconds;
        for (const row of view.items) {
            let rowActive = false;
            for (const style of Object.values(row.styles ?? {})) {
                const deadline = style ? currentEligibilityDeadline(style, expirySeconds, eligibilityClock) : null;
                if (!style || deadline === null) continue;
                activeStyles.add(style);
                rowActive = true;
                nextExpiry = Math.min(nextExpiry, deadline);
            }
            if (rowActive) activeRowCount += 1;
        }
    }
    useEffect(() => {
        // Keep the displayed evidence selection while eligibility is unconfirmed.
        if (eligibilityUnknown || !Number.isFinite(nextExpiry)) return;
        const timer = window.setTimeout(() => setEligibilityClock(Date.now()), Math.max(0, nextExpiry - Date.now()));
        return () => window.clearTimeout(timer);
    }, [eligibilityUnknown, nextExpiry]);
    const currentEligibleCount = !eligibilityUnknown && typeof view?.current_eligible_count === 'number'
        ? Math.min(view.current_eligible_count, activeRowCount) : undefined;
    const rows = view?.items ? latestBySymbol(view.items, activeStyles) : undefined;
    const history = result?.history ?? [];
    return (
        <>
            <section id="catalyst-headline" className={panel} aria-label="스윙 참고 관찰">
                <h2 className="ai-section-title text-lg">새 스윙 검토 후보 · {count(watch?.common_watch_count, '종목')}</h2>
                <p>{watch?.watch_rows?.length ? watch.watch_rows.map(row => (
                    <strong key={row.symbol} className="mr-3 inline-block">{row.name} <code>{row.symbol}</code></strong>
                )) : watch?.watch_rows ? '공통 조건 관찰 대상 없음' : '검증된 원장 확인 대기'}</p>
                <p>셋업 관찰 단계 · 매수 적격 아님 · 자료 {watch?.source_as_of ?? '확인 중'}</p>
                <a className="text-sky-300 hover:underline" href="#catalyst-validation">1차 명단·미충족 사유·공식/시세 검증 히스토리 확인</a>
            </section>
            <section id="catalyst-validation" className={`${panel} scroll-mt-4`} aria-label="새 종목과 재료 검증 대시보드">
                <header className="flex flex-wrap items-center justify-between gap-2">
                    <h2 className="ai-section-title text-lg">새 종목·재료 검증 대시보드</h2>
                    {!accessDenied && <button type="button" disabled={busy} onClick={() => void refresh()}
                        className="rounded-lg border border-[#526a83] px-3 py-2 font-medium text-sky-200 hover:bg-sky-400/10 disabled:opacity-50">저장 상태 갱신</button>}
                </header>
                {accessDenied && <p role="alert" className="text-amber-300">제갈공명 검증 자료의 접근 권한을 확인해 주세요.</p>}
                {!accessDenied && stale && <p role="alert" className="text-amber-300">검증 대시보드 조회 실패{view ? ' · 이전 결과 보존' : ' · 보존 자료를 확인할 수 없습니다.'}</p>}
                {!accessDenied && !view && !stale && <p role="status">제갈공명 저장 결과를 불러오는 중입니다.</p>}
                {view && <>
                    <VerificationClock view={view} stale={stale} />
                    <p>공식 공시 대조 → 기사 수신 이후 가격·호가 → 기존 단타·스윙·종가 조건 → 성과·60초 실행 적격 → 적격만 텔레그램</p>
                    {['error', 'source_error', 'partial'].includes(view.operation?.state ?? '') && <p className="text-amber-300">일부 검증 실패 · 완료 자료와 원문은 보존 · 마지막 상태 확인 필요</p>}
                    <SwingWatchDetails watch={watch} />
                    <h3 className="ai-section-title text-base">기사 재료 검증 {count(rows?.length, '종목')} · 현재 매수 적격 {count(currentEligibleCount, '건')}</h3>
                    <p>관련 공시가 있다는 사실과 기사 내용이 맞다는 판정은 다릅니다. 금액 대조가 통과해도 기사 전체·증감률·인과·전망의 검증은 아닙니다.</p>
                    <div className="grid min-w-0 grid-cols-1 gap-3 lg:grid-cols-2">
                        {rows?.map((row, index) => <ArticleEvidence key={row.task_id ?? row.symbol ?? index} row={row}
                            activeStyles={activeStyles} eligibilityUnknown={eligibilityUnknown} />)}
                    </div>
                    <details className={detailsStyle}>
                        <summary className="cursor-pointer font-medium">재료 검증 히스토리 · {count(view.history_count, '건')} (최근 {history.length}건 조회)</summary>
                        <div className="mt-2 max-h-[480px] space-y-2 overflow-auto">
                            {history.map((row, index) => (
                                <p key={row.id ?? index}>{stamp(row.checked_at)} · <strong>{row.name}</strong> <code>{row.symbol}</code>
                                    <br />{label(primaryLabels, row.primary?.status)} · {row.market_state ?? '시장 상태 미확인'} · 당시 적격 {row.buy_eligible === true ? '있음' : row.buy_eligible === false ? '없음' : '미확인'}</p>
                            ))}
                        </div>
                    </details>
                    <p className="text-slate-400">출처 제갈공명 · 저장 결과 {stamp(view.computed_at)} KST · 화면 15초 조회{view.live?.worker_interval_seconds != null && ` · 서버 ${view.live.worker_interval_seconds}초마다 자동 검증`} · 실제 주문 없음</p>
                </>}
            </section>
        </>
    );
}

export default function KongmingCatalystValidationPage() {
    const { token, user } = useAuth();
    const canRead = Boolean(token && canAccessKongming(user));
    return (
        <div className="ai-design min-h-full bg-[#101318] p-3 text-sm text-slate-100 sm:p-6">
            <div className="mx-auto max-w-5xl space-y-4">
                <AiBrainServiceTabs active="kongming" />
                <CatalystPanel key={`${user?.id ?? ''}:${token ?? ''}:${canRead}`} canRead={canRead} />
            </div>
        </div>
    );
}
